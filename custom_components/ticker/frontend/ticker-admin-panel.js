/**
 * Ticker Admin Panel - Orchestrator
 * Smart notifications for Home Assistant
 *
 * This file coordinates tab modules, loads data, and handles shared state.
 * Tab rendering is delegated to individual modules in the admin/ directory.
 *
 * Brand: See branding/README.md
 */

class TickerAdminPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });

    // State
    this._hass = null;
    this._initialized = false;
    this._activeTab = 'categories';

    // Data
    this._categories = [];
    this._users = [];
    this._subscriptions = {};
    this._queue = [];
    this._logs = [];
    this._logStats = {};
    this._zones = [];
    this._entities = [];
    this._scripts = [];
    this._recipients = [];
    this._availableNotifyServices = [];
    this._ttsOptions = { media_players: [], tts_services: [] };

    // UI state
    this._expandedUsers = new Set();
    this._expandedRecipients = new Set();
    this._editingCategory = null;
    this._editingCategorySubTab = 'general';
    this._addingCategory = false;

    // Migration state
    this._migrateFindings = [];
    this._migrateCurrentIndex = 0;
    this._migrateScanning = false;
    this._migrateConverting = false;
    this._migrateDeleting = false;

    // DOM cache
    this._els = {};
    this._dependenciesLoaded = false;

    // BUG-040: Scroll preservation
    this._scrollPositions = {};
    this._pendingScrollRestore = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized && this.isConnected) {
      this._initialized = true;
      this._init();
    }
  }

  connectedCallback() {
    // Initialize if hass was set before we were connected
    if (!this._initialized && this._hass) {
      this._initialized = true;
      this._init();
    }

    // FIX-029F: If visibility/resume fired while disconnected, recover now.
    if (this._needsRecovery) {
      this._needsRecovery = false;
      console.log('[Ticker Admin] connectedCallback: executing deferred visibility recovery');
      this._forceRepaint();
      this._loadData().then(() => this._renderTabContent());
    }
  }

  disconnectedCallback() {
    // Clean up visibility/resume listeners
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
    this._initialized = false;
  }

  async _init() {
    await this._loadDependencies();
    this._createStructure();
    this._wireHandlers();
    this._setupRecoveryHandlers();
    await this._loadData();
    this._renderTabContent();
  }

  /**
   * FIX-029F: Set up recovery handlers (delegated to ticker-recovery.js).
   */
  _setupRecoveryHandlers() {
    window.Ticker.Recovery.setupRecoveryHandlers(this);
  }

  /**
   * FIX-029F: Force repaint (delegated to ticker-recovery.js).
   */
  _forceRepaint() {
    window.Ticker.Recovery.forceRepaint(this);
  }

  async _loadDependencies() {
    if (this._dependenciesLoaded) return;

    const base = '/ticker_frontend';
    const scripts = [
      `${base}/ticker-utils.js`,
      `${base}/ticker-styles.js`,
      `${base}/ticker-styles-extended.js`,
      `${base}/ticker-recovery.js`,
      `${base}/ticker-conditions-styles.js`,
      `${base}/ticker-conditions-ui.js`,
      `${base}/admin/categories-tab.js`,
      `${base}/admin/action-set-editor.js`,
      `${base}/admin/users-tab.js`,
      `${base}/admin/recipients-tab.js`,
      `${base}/admin/recipients-handlers.js`,
      `${base}/admin/recipients-dialog.js`,
      `${base}/admin/queue-tab.js`,
      `${base}/admin/logs-tab.js`,
      `${base}/admin/migrate-tab.js`,
    ];

    for (const src of scripts) {
      if (!document.querySelector(`script[src="${src}"]`)) {
        await new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = src;
          script.onload = resolve;
          script.onerror = reject;
          document.head.appendChild(script);
        });
      }
    }

    this._dependenciesLoaded = true;
  }

  _wireHandlers() {
    window.Ticker = window.Ticker || {};
    window.Ticker._adminPanel = this;
  }

  _createStructure() {
    const styles = window.Ticker.styles;
    const css = `<style>${styles.getCommonStyles()}</style>`;

    const logo = styles.logoSvg;

    this.shadowRoot.innerHTML = `
      ${css}
      <div class="container-wide">
        <div class="header">
          ${logo}
          <h1>Ticker Admin</h1>
        </div>
        <div class="tabs" id="tabs"></div>
        <div id="message" class="message"></div>
        <div id="tab-content"></div>
      </div>
    `;

    this._els = {
      tabs: this.shadowRoot.getElementById('tabs'),
      message: this.shadowRoot.getElementById('message'),
      content: this.shadowRoot.getElementById('tab-content'),
    };

    this._renderTabs();
  }

  _renderTabs() {
    const queueCount = this._queue.length;
    const logCount = this._logs.length;

    const tabs = [
      { id: 'categories', label: 'Categories' },
      { id: 'users', label: 'Users' },
      { id: 'devices', label: 'Devices' },
      { id: 'queue', label: 'Queue', count: queueCount },
      { id: 'logs', label: 'Logs', count: logCount },
      { id: 'migrate', label: 'Migrate' },
    ];

    this._els.tabs.innerHTML = tabs.map(tab => {
      const isActive = this._activeTab === tab.id;
      const badge = tab.count ? `<span class="badge-count">${tab.count}</span>` : '';
      return `
        <button class="tab ${isActive ? 'active' : ''}" data-tab="${tab.id}">
          ${tab.label}${badge}
        </button>
      `;
    }).join('');

    // Attach click handlers
    this._els.tabs.querySelectorAll('.tab').forEach(btn => {
      btn.onclick = () => this._switchTab(btn.dataset.tab);
    });
  }

  _switchTab(tabId) {
    // BUG-040: Save scroll position of current tab before switching
    if (this._els && this._els.content) {
      this._scrollPositions[this._activeTab] = this._els.content.scrollTop;
    }
    this._activeTab = tabId;
    // Schedule scroll restoration after render
    this._pendingScrollRestore = this._scrollPositions[tabId] || 0;
    this._renderTabs();
    this._renderTabContent();
  }

  _renderTabContentPreserveScroll() {
    const scrollTop = this._els?.content?.scrollTop || 0;
    this._pendingScrollRestore = scrollTop;
    this._renderTabContent();
  }

  _renderTabContent() {
    const state = this._getState();
    let html = '';

    switch (this._activeTab) {
      case 'categories':
        html = window.Ticker.AdminCategoriesTab.render(state);
        break;
      case 'users':
        html = window.Ticker.AdminUsersTab.render(state);
        break;
      case 'devices':
        html = window.Ticker.AdminRecipientsTab.render(state);
        break;
      case 'queue':
        html = window.Ticker.AdminQueueTab.render(state);
        break;
      case 'logs':
        html = window.Ticker.AdminLogsTab.render(state);
        break;
      case 'migrate':
        html = window.Ticker.AdminMigrateTab.render(state);
        break;
    }

    this._els.content.innerHTML = html;

    // BUG-040: Restore scroll position if pending
    if (this._pendingScrollRestore !== null && this._els.content) {
      this._els.content.scrollTop = this._pendingScrollRestore;
      this._pendingScrollRestore = null;
    }

    // Post-render: set up conditions UI components
    if (this._activeTab === 'categories') {
      this._setupCategoryConditionsUI();
    } else if (this._activeTab === 'devices') {
      window.Ticker.AdminRecipientsTab.setupRecipientConditionsUI(this);
    }
  }

  _setupCategoryConditionsUI() {
    const editId = this._editingCategory;
    if (!editId) return;

    const cat = this._categories.find(c => c.id === editId);
    if (!cat) return;

    const conditionsUI = this.shadowRoot.getElementById(`cat-conditions-ui-${editId}`);
    if (!conditionsUI) return;

    const conditions = cat.default_conditions || {};
    const rules = conditions.rules || [];

    conditionsUI.rules = rules;
    conditionsUI.deliverWhenMet = conditions.deliver_when_met || false;
    conditionsUI.queueUntilMet = conditions.queue_until_met || false;
    conditionsUI.zones = this._zones;
    conditionsUI.entities = this._entities;

    // Listen for changes
    conditionsUI.removeEventListener('rules-changed', conditionsUI._rulesHandler);
    conditionsUI._rulesHandler = (e) => {
      // Store temporarily on the panel for the save handler to pick up
      this._pendingDefaultConditions = {
        deliver_when_met: e.detail.deliver_when_met,
        queue_until_met: e.detail.queue_until_met,
        rules: e.detail.rules,
      };
    };
    conditionsUI.addEventListener('rules-changed', conditionsUI._rulesHandler);
  }

  _getState() {
    return {
      categories: this._categories,
      users: this._users,
      subscriptions: this._subscriptions,
      queue: this._queue,
      logs: this._logs,
      logStats: this._logStats,
      zones: this._zones,
      entities: this._entities,
      expandedUsers: this._expandedUsers,
      expandedRecipients: this._expandedRecipients,
      recipients: this._recipients,
      availableNotifyServices: this._availableNotifyServices,
      editingCategory: this._editingCategory,
      editingCategorySubTab: this._editingCategorySubTab,
      addingCategory: this._addingCategory,
      migrateFindings: this._migrateFindings,
      migrateCurrentIndex: this._migrateCurrentIndex,
      migrateScanning: this._migrateScanning,
      migrateConverting: this._migrateConverting,
      migrateDeleting: this._migrateDeleting,
      scripts: this._scripts,
    };
  }

  // ─── Data Loading ────────────────────────────────────────────────────────

  async _loadData() {
    await Promise.all([
      this._loadCategories(),
      this._loadUsers(),
      this._loadRecipients(),
      this._loadSubscriptions(),
      this._loadQueue(),
      this._loadLogs(),
      this._loadLogStats(),
      this._loadZones(),
      this._loadEntities(),
    ]);
    this._renderTabs();
  }

  async _loadCategories() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/categories' });
      this._categories = result.categories || [];
    } catch (err) {
      console.error('[Ticker] Failed to load categories:', err);
    }
  }

  async _loadUsers() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/users' });
      this._users = result.users || [];
    } catch (err) {
      console.error('[Ticker] Failed to load users:', err);
    }
  }

  async _loadRecipients() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/get_recipients' });
      this._recipients = result.recipients || [];
    } catch (err) {
      console.error('[Ticker] Failed to load recipients:', err);
    }
  }

  async _loadAvailableNotifyServices(recipientId) {
    try {
      const wsMsg = { type: 'ticker/get_available_notify_services' };
      if (recipientId) wsMsg.recipient_id = recipientId;
      const result = await this._hass.callWS(wsMsg);
      this._availableNotifyServices = result.services || [];
    } catch (err) {
      console.error('[Ticker] Failed to load available notify services:', err);
    }
  }

  async _loadTtsOptions() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/get_tts_options' });
      this._ttsOptions = {
        media_players: result.media_players || [],
        tts_services: result.tts_services || [],
      };
    } catch (err) {
      console.error('[Ticker] Failed to load TTS options:', err);
      this._ttsOptions = { media_players: [], tts_services: [] };
    }
  }

  async _loadSubscriptions() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/subscriptions' });
      this._subscriptions = {};
      for (const sub of result.subscriptions || []) {
        if (!this._subscriptions[sub.person_id]) {
          this._subscriptions[sub.person_id] = {};
        }
        this._subscriptions[sub.person_id][sub.category_id] = sub;
      }
    } catch (err) {
      console.error('[Ticker] Failed to load subscriptions:', err);
    }
  }

  async _loadQueue() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/queue' });
      this._queue = result.queue || [];
    } catch (err) {
      console.error('[Ticker] Failed to load queue:', err);
    }
  }

  async _loadLogs() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/logs', limit: 500 });
      this._logs = result.logs || [];
    } catch (err) {
      console.error('[Ticker] Failed to load logs:', err);
    }
  }

  async _loadLogStats() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/logs/stats' });
      this._logStats = result.stats || {};
    } catch (err) {
      console.error('[Ticker] Failed to load log stats:', err);
    }
  }

  async _loadZones() {
    try {
      const result = await this._hass.callWS({ type: 'ticker/zones' });
      this._zones = result.zones || [];
    } catch (err) {
      console.error('[Ticker] Failed to load zones:', err);
      this._zones = [];
    }
  }

  _loadEntities() {
    try {
      const states = this._hass.states;
      const all = Object.keys(states);
      this._entities = all.map(id => ({
        entity_id: id,
        name: states[id].attributes.friendly_name || id,
      })).sort((a, b) => a.name.localeCompare(b.name));
      this._scripts = this._entities.filter(e => e.entity_id.startsWith('script.'));
    } catch (err) {
      console.error('[Ticker] Failed to load entities:', err);
      this._entities = [];
      this._scripts = [];
    }
  }

  // ─── Messages ────────────────────────────────────────────────────────────

  _showMessage(message, isError) {
    const el = this._els.message;
    if (!el) return;
    el.textContent = message;
    el.className = `message ${isError ? 'error' : 'success'}-message`;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, isError ? 10000 : 3000);
  }
  _showError(message) { this._showMessage(message, true); }
  _showSuccess(message) { this._showMessage(message, false); }
}

customElements.define('ticker-admin-panel', TickerAdminPanel);
