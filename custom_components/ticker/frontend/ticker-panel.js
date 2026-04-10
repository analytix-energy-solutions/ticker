/**
 * Ticker User Panel
 * Smart notifications for Home Assistant
 *
 * This is a thin orchestrator that delegates to tab modules:
 * - user/subscriptions-tab.js
 * - user/queue-tab.js
 * - user/history-tab.js
 *
 * Styles: user/user-panel-styles.js
 * Recovery: user/recovery-handlers.js
 *
 * Brand: See branding/README.md
 * Colors: --ticker-500: #06b6d4, --ticker-400: #22d3ee, --ticker-700: #0e7490
 */

class TickerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._currentPerson = null;
    this._categories = [];
    this._subscriptions = {};
    this._zones = [];
    this._queue = [];
    this._devices = [];
    this._entities = [];
    this._activeTab = window.location.hash === '#history' ? 'history' : 'subscriptions';
    this._loading = true;
    this._error = null;
    this._history = [];
    this._expandedCategories = new Set();
    this._devicePrefMode = 'all';
    this._devicePrefDevices = [];
    this._devicePrefDirty = false;
    this._dependenciesLoaded = false;
    this._els = null;
    // BUG-040: Scroll/focus preservation
    this._scrollPositions = {};
    this._pendingScrollRestore = null;
    // F-26: Notification History Search filters (client-side only)
    this._historySearch = '';
    this._historyCategory = '';
    this._historyDateFrom = '';
    this._historyDateTo = '';
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized && this.isConnected) {
      this._initialized = true;
      this._initialize();
    }
  }

  connectedCallback() {
    if (!this._initialized && this._hass) {
      this._initialized = true;
      this._initialize();
    }
    // FIX-029F: If visibility/resume fired while disconnected, recover now.
    if (this._needsRecovery) {
      this._needsRecovery = false;
      console.log('[Ticker] connectedCallback: executing deferred visibility recovery');
      window.Ticker.UserRecoveryHandlers.forceRepaint(this);
      this._loadData();
    }
  }

  disconnectedCallback() {
    if (this._visibilityHandler) {
      document.removeEventListener('visibilitychange', this._visibilityHandler);
      this._visibilityHandler = null;
    }
    if (this._resumeHandler) {
      document.removeEventListener('resume', this._resumeHandler);
      this._resumeHandler = null;
    }
    if (this._connectionReadyHandler && this._hass?.connection) {
      this._hass.connection.removeEventListener('ready', this._connectionReadyHandler);
      this._connectionReadyHandler = null;
    }
    // F-26: reset history search filters on disconnect
    this._historySearch = '';
    this._historyCategory = '';
    this._historyDateFrom = '';
    this._historyDateTo = '';
    this._initialized = false;
  }

  async _initialize() {
    await this._loadDependencies();
    this._createStructure();
    this._wireHandlers();
    window.Ticker.UserRecoveryHandlers.setup(this);
    await this._loadData();
  }

  async _loadDependencies() {
    if (this._dependenciesLoaded) return;
    const base = '/ticker_frontend';
    const scripts = [
      `${base}/ticker-utils.js`,
      `${base}/ticker-styles.js`,
      `${base}/ticker-styles-extended.js`,
      `${base}/ticker-conditions-styles.js`,
      `${base}/ticker-conditions-tree.js`,
      `${base}/ticker-conditions-ui.js`,
      `${base}/user/user-panel-styles.js`,
      `${base}/user/recovery-handlers.js`,
      `${base}/user/subscriptions-tab.js`,
      `${base}/user/subscriptions-handlers.js`,
      `${base}/user/queue-tab.js`,
      `${base}/user/history-tab.js`,
    ];
    for (const src of scripts) {
      if (document.querySelector(`script[src="${src}"]`)) continue;
      await new Promise((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src;
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    this._dependenciesLoaded = true;
  }

  _wireHandlers() {
    window.Ticker = window.Ticker || {};
    window.Ticker._userPanel = this;
  }

  _createStructure() {
    const { variables, base, header, tabs, cards, buttons, badges, messages,
            states, toggles, notifyServices, queueItems, warningBanner,
            forms, listItems, sections, colorIndicator, logoSvg,
            historyFilterBar } = window.Ticker.styles;
    const panelStyles = window.Ticker.userPanelStyles;

    const allStyles = [variables, base, header, tabs, cards, buttons, badges, messages,
      states, toggles, notifyServices, queueItems, warningBanner, forms, listItems,
      sections, colorIndicator, historyFilterBar, panelStyles].join('\n');

    this.shadowRoot.innerHTML = `
      <style>${allStyles}</style>
      <div class="container">
        <div class="header">${logoSvg}<h1>Ticker</h1></div>
        <div id="message-area" class="message"></div>
        <div id="loading-area"></div>
        <div id="tabs-bar"></div>
        <div id="tab-content"></div>
      </div>
    `;

    this._els = {
      messageArea: this.shadowRoot.getElementById('message-area'),
      loadingArea: this.shadowRoot.getElementById('loading-area'),
      tabsBar: this.shadowRoot.getElementById('tabs-bar'),
      tabContent: this.shadowRoot.getElementById('tab-content'),
    };
  }

  async _loadData() {
    this._loading = true;
    this._error = null;
    this._renderTabContent();
    try {
      await Promise.all([
        this._loadCurrentPerson(),
        this._loadCategories(),
        this._loadZones(),
        this._loadDevices(),
        this._loadEntities(),
      ]);
      if (this._currentPerson) {
        await Promise.all([
          this._loadSubscriptions(),
          this._loadQueue(),
          this._loadHistory(),
        ]);
        this._initDevicePrefState();
      }
    } catch (err) {
      console.error('Failed to load data:', err);
      this._error = err.message || 'Failed to load data';
    }
    this._loading = false;
    this._renderTabContent();
  }

  async _loadCurrentPerson() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/current_person' });
      this._currentPerson = result.person;
    } catch (err) {
      console.error('Failed to load current person:', err);
      this._currentPerson = null;
    }
  }

  async _loadCategories() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/categories' });
      this._categories = result.categories || [];
    } catch (err) {
      console.error('Failed to load categories:', err);
      this._categories = [];
    }
  }

  async _loadZones() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/zones' });
      this._zones = result.zones || [];
    } catch (err) {
      console.error('Failed to load zones:', err);
      this._zones = [];
    }
  }

  async _loadDevices() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/devices' });
      this._devices = result.devices || [];
    } catch (err) {
      console.error('Failed to load devices:', err);
      this._devices = [];
    }
  }

  _loadEntities() {
    try {
      const states = this._hass.states;
      this._entities = Object.keys(states).map(entityId => ({
        entity_id: entityId,
        name: states[entityId].attributes.friendly_name || entityId,
      })).sort((a, b) => a.name.localeCompare(b.name));
    } catch (err) {
      console.error('Failed to load entities:', err);
      this._entities = [];
    }
  }

  async _loadSubscriptions() {
    if (!this._currentPerson) return;
    try {
      const result = await this._hass.callWS({
        type: 'ticker/subscriptions',
        person_id: this._currentPerson.person_id,
      });
      this._subscriptions = {};
      for (const sub of result.subscriptions || []) {
        this._subscriptions[sub.category_id] = sub;
      }
    } catch (err) {
      console.error('Failed to load subscriptions:', err);
      this._subscriptions = {};
    }
  }

  async _loadQueue() {
    if (!this._currentPerson) return;
    try {
      const result = await this._hass.callWS({
        type: 'ticker/queue',
        person_id: this._currentPerson.person_id,
      });
      this._queue = result.queue || [];
    } catch (err) {
      console.error('Failed to load queue:', err);
      this._queue = [];
    }
  }

  async _loadHistory() {
    if (!this._currentPerson) return;
    try {
      const result = await this._hass.callWS({
        type: 'ticker/logs',
        person_id: this._currentPerson.person_id,
        outcome: 'sent',
        limit: 500,
      });
      this._history = result.logs || [];
    } catch (err) {
      console.error('Failed to load history:', err);
      this._history = [];
    }
  }

  _initDevicePrefState() {
    if (!this._currentPerson) return;
    const pref = this._currentPerson.device_preference || { mode: 'all', devices: [] };
    this._devicePrefMode = pref.mode || 'all';
    this._devicePrefDevices = [...(pref.devices || [])];
    this._devicePrefDirty = false;
  }

  _getState() {
    return {
      currentPerson: this._currentPerson,
      categories: this._categories,
      subscriptions: this._subscriptions,
      devices: this._devices,
      zones: this._zones,
      entities: this._entities,
      queue: this._queue,
      history: this._history,
      expandedCategories: this._expandedCategories,
      devicePrefMode: this._devicePrefMode,
      devicePrefDevices: this._devicePrefDevices,
      devicePrefDirty: this._devicePrefDirty,
      // F-26: history search filter state
      historySearch: this._historySearch,
      historyCategory: this._historyCategory,
      historyDateFrom: this._historyDateFrom,
      historyDateTo: this._historyDateTo,
    };
  }

  /**
   * F-26: Update a history filter field and re-render the history tab
   * without losing scroll position. Captures the currently focused input
   * (id + selection range) before re-render and restores it afterwards
   * so the search box keeps focus across keystrokes.
   * @param {string} field - One of historySearch, historyCategory, historyDateFrom, historyDateTo
   * @param {string} value - New value
   */
  _setHistoryFilter(field, value) {
    const allowed = ['historySearch', 'historyCategory', 'historyDateFrom', 'historyDateTo'];
    if (!allowed.includes(field)) return;
    const key = '_' + field;
    this[key] = value || '';

    // Save focus state from the shadow root's active element.
    const active = this.shadowRoot?.activeElement;
    let focusInfo = null;
    if (active && active.id && active.id.startsWith('ticker-history-')) {
      focusInfo = { id: active.id };
      // Only text-like inputs expose selection range
      if (active.tagName === 'INPUT' && (active.type === 'search' || active.type === 'text')) {
        focusInfo.selStart = active.selectionStart;
        focusInfo.selEnd = active.selectionEnd;
      }
    }

    this._renderTabContentPreserveScroll();

    if (focusInfo) {
      const restored = this.shadowRoot?.getElementById(focusInfo.id);
      if (restored) {
        restored.focus();
        if (focusInfo.selStart != null && typeof restored.setSelectionRange === 'function') {
          try {
            restored.setSelectionRange(focusInfo.selStart, focusInfo.selEnd);
          } catch {
            // setSelectionRange throws on some input types — safe to ignore
          }
        }
      }
    }
  }

  _renderTabContent() {
    if (!this._els) return;
    if (this._loading) {
      this._els.loadingArea.innerHTML = `
        <div class="card">
          <div class="loading">
            <div class="loading-spinner"></div>
            <p>Loading...</p>
          </div>
        </div>
      `;
      this._els.tabsBar.innerHTML = '';
      this._els.tabContent.innerHTML = '';
      return;
    }
    this._els.loadingArea.innerHTML = '';
    if (this._error) {
      this._els.tabContent.innerHTML = `
        <div class="card">
          <div class="error-state">
            <p>Error: ${window.Ticker.utils.esc(this._error)}</p>
          </div>
        </div>
      `;
      return;
    }
    if (!this._currentPerson) {
      this._els.tabContent.innerHTML = `
        <div class="card">
          <div class="no-person-state">
            <h3>No Person Entity Found</h3>
            <p>Your Home Assistant user account is not linked to a person entity.<br>
            Ask an administrator to link your account in Settings → People.</p>
          </div>
        </div>
      `;
      return;
    }
    // Render tabs bar
    const queueCount = this._queue.length;
    const historyCount = window.Ticker.UserHistoryTab.getGroupedCount(this._history);
    this._els.tabsBar.innerHTML = `
      <div class="tabs">
        <button class="tab ${this._activeTab === 'subscriptions' ? 'active' : ''}"
          onclick="window.Ticker._userPanel._switchTab('subscriptions')">Subscriptions</button>
        <button class="tab ${this._activeTab === 'queue' ? 'active' : ''}"
          onclick="window.Ticker._userPanel._switchTab('queue')">Queue${queueCount > 0 ? `<span class="badge-count">${queueCount}</span>` : ''}</button>
        <button class="tab ${this._activeTab === 'history' ? 'active' : ''}"
          onclick="window.Ticker._userPanel._switchTab('history')">History${historyCount > 0 ? `<span class="badge-count">${historyCount}</span>` : ''}</button>
      </div>
    `;
    // Render active tab content
    const state = this._getState();
    if (this._activeTab === 'subscriptions') {
      this._els.tabContent.innerHTML = window.Ticker.UserSubscriptionsTab.render(state);
    } else if (this._activeTab === 'queue') {
      this._els.tabContent.innerHTML = window.Ticker.UserQueueTab.render(state);
    } else {
      this._els.tabContent.innerHTML = window.Ticker.UserHistoryTab.render(state);
    }
    this._afterRender();
  }

  _afterRender() {
    // BUG-040: Restore scroll position if pending
    if (this._pendingScrollRestore !== null && this._els && this._els.tabContent) {
      this._els.tabContent.scrollTop = this._pendingScrollRestore;
      this._pendingScrollRestore = null;
    }
    // Set up conditions UI components (delegated to subscriptions tab)
    window.Ticker.UserSubscriptionsTab.setupConditionsUI(this);
  }

  _switchTab(tab) {
    // BUG-040: Save scroll position of current tab before switching
    if (this._els && this._els.tabContent) {
      this._scrollPositions[this._activeTab] = this._els.tabContent.scrollTop;
    }
    // F-26: reset history filters when switching away from history tab
    if (this._activeTab === 'history' && tab !== 'history') {
      this._historySearch = '';
      this._historyCategory = '';
      this._historyDateFrom = '';
      this._historyDateTo = '';
    }
    this._activeTab = tab;
    this._pendingScrollRestore = this._scrollPositions[tab] || 0;
    this._renderTabContent();
  }

  /**
   * BUG-040: Re-render tab content while preserving scroll position.
   * Use this for same-tab updates like category expansion.
   */
  _renderTabContentPreserveScroll() {
    const scrollTop = this._els?.tabContent?.scrollTop || 0;
    this._pendingScrollRestore = scrollTop;
    this._renderTabContent();
  }

  _showError(message) {
    if (this._els && this._els.messageArea) {
      this._els.messageArea.textContent = message;
      this._els.messageArea.className = 'message error-message';
      this._els.messageArea.style.display = 'block';
      setTimeout(() => {
        this._els.messageArea.style.display = 'none';
      }, 10000);
    }
  }

  _showSuccess(message) {
    if (this._els && this._els.messageArea) {
      this._els.messageArea.textContent = message;
      this._els.messageArea.className = 'message success-message';
      this._els.messageArea.style.display = 'block';
      setTimeout(() => {
        this._els.messageArea.style.display = 'none';
      }, 3000);
    }
  }
}

customElements.define('ticker-panel', TickerPanel);
