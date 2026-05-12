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
    this._lovelaceDashboards = [];
    this._hasPanels = [];
    this._lovelaceViews = {};

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

    // Automations manager state (F-3)
    this._automationsFindings = [];
    this._automationsScanning = false;
    this._automationsFilter = { category: '', sourceType: '' };
    this._automationsExpanded = null;
    this._automationsScanned = false;

    // Action sets library state (F-5b)
    this._actionSets = [];
    this._editingActionSetId = null;

    // F-24: Logs tab status filter (null = show all)
    this._statusFilter = null;

    // F-26 (admin): Logs tab filter bar state
    this._logsSearch = '';
    this._logsCategory = '';
    this._logsPerson = '';
    this._logsDateFrom = '';
    this._logsDateTo = '';

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
    // F-24: Reset logs status filter when panel closes
    this._statusFilter = null;
    // F-26 (admin): Reset logs filter bar state on panel close
    this._logsSearch = '';
    this._logsCategory = '';
    this._logsPerson = '';
    this._logsDateFrom = '';
    this._logsDateTo = '';
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
      `${base}/ticker-conditions-tree.js`,
      `${base}/ticker-conditions-ui.js`,
      `${base}/admin/admin-data-loader.js`,
      `${base}/admin/navigation-picker.js`,
      `${base}/admin/categories-tab.js`,
      `${base}/admin/categories-handlers.js`,
      `${base}/admin/users-tab.js`,
      `${base}/admin/recipients-tab.js`,
      `${base}/admin/recipients-handlers.js`,
      `${base}/admin/recipients-volume.js`,
      `${base}/admin/recipients-dialog.js`,
      `${base}/admin/queue-tab.js`,
      `${base}/admin/logs-tab.js`,
      `${base}/admin/migrate-tab.js`,
      `${base}/admin/automations-tab.js`,
      `${base}/admin/automations-tab-multicategory.js`,
      `${base}/admin/action-sets-tab.js`,
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
      { id: 'action-sets', label: 'Action Sets' },
      { id: 'automations', label: 'Automations' },
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
      case 'action-sets':
        html = window.Ticker.AdminActionSetsTab.render(state);
        break;
      case 'automations':
        html = window.Ticker.AdminAutomationsTab.render(state);
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

    if (conditions.condition_tree) {
      conditionsUI.tree = conditions.condition_tree;
    } else {
      conditionsUI.rules = conditions.rules || [];
    }
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
        condition_tree: e.detail.condition_tree,
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
      actionSets: this._actionSets,
      editingActionSetId: this._editingActionSetId,
      automationsFindings: this._automationsFindings,
      automationsScanning: this._automationsScanning,
      automationsFilter: this._automationsFilter,
      automationsExpanded: this._automationsExpanded,
      _automationsScanned: this._automationsScanned,
      lovelaceDashboards: this._lovelaceDashboards,
      hasPanels: this._hasPanels || [],
      lovelaceViews: this._lovelaceViews || {},
      statusFilter: this._statusFilter,
      logsSearch: this._logsSearch,
      logsCategory: this._logsCategory,
      logsPerson: this._logsPerson,
      logsDateFrom: this._logsDateFrom,
      logsDateTo: this._logsDateTo,
    };
  }

  /**
   * F-26 (admin): Update a Logs tab filter field and re-render. Preserves
   * focus on the search input across keystrokes by capturing the active
   * element's id and selection range, then restoring them after the
   * shadow-DOM re-render replaces the input.
   * @param {string} field - One of logsSearch, logsCategory, logsPerson, logsDateFrom, logsDateTo
   * @param {string} value - New value
   */
  _setLogsFilter(field, value) {
    const allowed = ['logsSearch', 'logsCategory', 'logsPerson', 'logsDateFrom', 'logsDateTo'];
    if (!allowed.includes(field)) return;
    this['_' + field] = value || '';

    const active = this.shadowRoot?.activeElement;
    let focusInfo = null;
    if (active && active.id && active.id.startsWith('ticker-logs-')) {
      focusInfo = { id: active.id };
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

  // ─── Data Loading (delegated to AdminDataLoader) ─────────────────────────

  async _loadData() { return window.Ticker.AdminDataLoader.loadAll(this); }
  async _loadCategories() { return window.Ticker.AdminDataLoader.loadCategories(this); }
  async _loadUsers() { return window.Ticker.AdminDataLoader.loadUsers(this); }
  async _loadRecipients() { return window.Ticker.AdminDataLoader.loadRecipients(this); }
  async _loadAvailableNotifyServices(id) { return window.Ticker.AdminDataLoader.loadAvailableNotifyServices(this, id); }
  async _loadTtsOptions() { return window.Ticker.AdminDataLoader.loadTtsOptions(this); }
  async _loadSubscriptions() { return window.Ticker.AdminDataLoader.loadSubscriptions(this); }
  async _loadQueue() { return window.Ticker.AdminDataLoader.loadQueue(this); }
  async _loadLogs() { return window.Ticker.AdminDataLoader.loadLogs(this); }
  async _loadLogStats() { return window.Ticker.AdminDataLoader.loadLogStats(this); }
  async _loadZones() { return window.Ticker.AdminDataLoader.loadZones(this); }
  _loadEntities() { return window.Ticker.AdminDataLoader.loadEntities(this); }
  async _loadActionSets() { return window.Ticker.AdminDataLoader.loadActionSets(this); }
  async _loadDashboards() { return window.Ticker.AdminDataLoader.loadDashboards(this); }

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
