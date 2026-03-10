/**
 * Ticker User Panel
 * Smart notifications for Home Assistant
 *
 * This is a thin orchestrator that delegates to tab modules:
 * - user/subscriptions-tab.js
 * - user/queue-tab.js
 * - user/history-tab.js
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
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._initialize();
    }
  }

  async _initialize() {
    await this._loadDependencies();
    this._createStructure();
    this._wireHandlers();
    await this._loadData();
  }

  async _loadDependencies() {
    if (this._dependenciesLoaded) return;

    const base = '/ticker_frontend';
    const scripts = [
      `${base}/ticker-utils.js`,
      `${base}/ticker-styles.js`,
      `${base}/ticker-conditions-ui.js`,
      `${base}/user/subscriptions-tab.js`,
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
    // Expose panel reference for tab handler onclick strings
    window.Ticker = window.Ticker || {};
    window.Ticker._userPanel = this;
  }

  _createStructure() {
    const { variables, base, header, tabs, cards, buttons, badges, messages,
            states, toggles, notifyServices, queueItems, warningBanner,
            forms, listItems, sections, colorIndicator, logoSvg } = window.Ticker.styles;

    // Panel-specific styles
    const panelStyles = `
      /* User profile */
      .user-info {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        background: var(--bg-primary);
        border-radius: 4px;
        margin-bottom: 16px;
      }
      .user-avatar {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--ticker-500);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 600;
        font-size: 16px;
      }
      .user-details { flex: 1; }
      .user-name { font-weight: 500; color: var(--text-primary); }

      /* Subscriptions list */
      .subscriptions-list { display: flex; flex-direction: column; gap: 8px; }
      .subscription-item { background: var(--bg-primary); border-radius: 4px; overflow: hidden; }
      .subscription-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        cursor: pointer;
      }
      .subscription-header.expanded {
        border-left: 3px solid var(--ticker-500);
        background: rgba(6, 182, 212, 0.08);
      }
      .subscription-label {
        font-size: 14px;
        color: var(--text-primary);
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .subscription-controls { display: flex; align-items: center; gap: 8px; }
      .subscription-select {
        padding: 6px 10px;
        border: 1px solid var(--divider);
        border-radius: 4px;
        font-size: 13px;
        background: var(--bg-card);
        color: var(--text-primary);
        min-width: 120px;
        cursor: pointer;
      }
      .subscription-select:focus { outline: none; border-color: var(--ticker-500); }
      .conditional-content {
        padding: 0 16px 16px 16px;
        border-left: 3px solid var(--ticker-500);
        background: rgba(6, 182, 212, 0.04);
      }
      .conditions-section { margin-top: 8px; padding-top: 8px; }

      /* Device preferences */
      .device-section {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--divider);
      }
      .device-section-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: 12px;
      }
      .radio-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
      .radio-option {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        color: var(--text-primary);
        cursor: pointer;
      }
      .radio-option input[type="radio"] {
        width: 16px;
        height: 16px;
        accent-color: var(--ticker-500);
        cursor: pointer;
      }
      .device-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
        padding-left: 24px;
        margin-bottom: 12px;
      }
      .device-checkbox {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--text-primary);
        cursor: pointer;
      }
      .device-checkbox input[type="checkbox"] {
        width: 16px;
        height: 16px;
        accent-color: var(--ticker-500);
        cursor: pointer;
      }
      .device-checkbox.disabled { color: var(--text-secondary); cursor: not-allowed; }
      .device-actions { display: flex; gap: 8px; margin-top: 8px; }
      .device-override-section {
        margin-top: 12px;
        padding-top: 12px;
        border-top: 1px solid var(--divider);
      }
      .device-override-toggle {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--text-primary);
        cursor: pointer;
        margin-bottom: 8px;
      }
      .device-override-toggle input[type="checkbox"] {
        width: 16px;
        height: 16px;
        accent-color: var(--ticker-500);
        cursor: pointer;
      }
      .device-override-list { display: flex; flex-direction: column; gap: 6px; padding-left: 24px; }
      .device-override-help {
        font-size: 12px;
        color: var(--text-secondary);
        margin-bottom: 8px;
        padding-left: 24px;
      }

      /* History styles */
      .history-list { display: flex; flex-direction: column; gap: 16px; }
      .history-date-group { display: flex; flex-direction: column; gap: 8px; }
      .history-date-label {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding-bottom: 4px;
        border-bottom: 1px solid var(--divider);
      }
      .history-item { padding: 12px 16px; background: var(--bg-primary); border-radius: 4px; }
      .history-item-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 4px;
      }
      .history-item-title { font-weight: 500; color: var(--text-primary); }
      .history-item-time {
        font-size: 12px;
        color: var(--text-secondary);
        white-space: nowrap;
        margin-left: 12px;
      }
      .history-item-message {
        font-size: 14px;
        color: var(--text-primary);
        line-height: 1.5;
        margin-bottom: 8px;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .history-item-meta { display: flex; gap: 8px; flex-wrap: wrap; }

      /* No person state */
      .no-person-state { text-align: center; padding: 40px; }
      .no-person-state h3 { color: var(--text-primary); margin: 0 0 8px 0; }
      .no-person-state p { color: var(--text-secondary); margin: 0; }
    `;

    const allStyles = [variables, base, header, tabs, cards, buttons, badges, messages,
      states, toggles, notifyServices, queueItems, warningBanner, forms, listItems,
      sections, colorIndicator, panelStyles].join('\n');

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
    };
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

    // Post-render setup
    this._afterRender();
  }

  _afterRender() {
    // Set up conditions UI components
    this._setupConditionsUI();
  }

  _setupConditionsUI() {
    for (const cat of this._categories) {
      const sub = this._subscriptions[cat.id]
        || window.Ticker.UserSubscriptionsTab._getCategoryDefault(cat);
      const isConditional = sub.mode === 'conditional';
      const isExpanded = this._expandedCategories.has(cat.id);

      if (isConditional && isExpanded) {
        const conditionsUI = this.shadowRoot.getElementById(`conditions-ui-${cat.id}`);
        if (conditionsUI) {
          const conditions = sub.conditions || {};
          const rules = window.Ticker.UserSubscriptionsTab._getSubscriptionRules(conditions);

          // Set data properties
          conditionsUI.rules = rules;
          conditionsUI.deliverWhenMet = conditions.deliver_when_met || false;
          conditionsUI.queueUntilMet = conditions.queue_until_met || false;
          conditionsUI.zones = this._zones;
          conditionsUI.entities = this._entities;

          // Listen for rules-changed event
          conditionsUI.removeEventListener('rules-changed', conditionsUI._rulesHandler);
          conditionsUI._rulesHandler = (e) => {
            window.Ticker.UserSubscriptionsTab.handlers.handleRulesChanged(
              this,
              cat.id,
              e.detail
            );
          };
          conditionsUI.addEventListener('rules-changed', conditionsUI._rulesHandler);
        }
      }
    }
  }

  _switchTab(tab) {
    this._activeTab = tab;
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
