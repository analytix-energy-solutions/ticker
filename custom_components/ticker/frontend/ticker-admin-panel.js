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

    // UI state
    this._expandedUsers = new Set();
    this._editingCategory = null;
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
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._init();
    }
  }

  async _init() {
    await this._loadDependencies();
    this._createStructure();
    this._wireHandlers();
    await this._loadData();
    this._renderTabContent();
  }

  /**
   * Dynamically load tab modules and shared utilities.
   */
  async _loadDependencies() {
    if (this._dependenciesLoaded) return;

    const base = '/ticker_frontend';
    const scripts = [
      `${base}/ticker-utils.js`,
      `${base}/ticker-styles.js`,
      `${base}/admin/categories-tab.js`,
      `${base}/admin/users-tab.js`,
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

  /**
   * Expose panel reference for onclick handlers in tab modules.
   */
  _wireHandlers() {
    window.Ticker = window.Ticker || {};
    window.Ticker._adminPanel = this;
  }

  /**
   * Create the persistent DOM structure.
   */
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

  /**
   * Render tab buttons.
   */
  _renderTabs() {
    const queueCount = this._queue.length;
    const logCount = this._logs.length;

    const tabs = [
      { id: 'categories', label: 'Categories' },
      { id: 'users', label: 'Users' },
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

  /**
   * Switch to a different tab.
   * @param {string} tabId - Tab identifier
   */
  _switchTab(tabId) {
    this._activeTab = tabId;
    this._renderTabs();
    this._renderTabContent();
  }

  /**
   * Render the active tab content.
   */
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
  }

  /**
   * Get current state for tab modules.
   * @returns {Object} - State object
   */
  _getState() {
    return {
      categories: this._categories,
      users: this._users,
      subscriptions: this._subscriptions,
      queue: this._queue,
      logs: this._logs,
      logStats: this._logStats,
      expandedUsers: this._expandedUsers,
      editingCategory: this._editingCategory,
      addingCategory: this._addingCategory,
      migrateFindings: this._migrateFindings,
      migrateCurrentIndex: this._migrateCurrentIndex,
      migrateScanning: this._migrateScanning,
      migrateConverting: this._migrateConverting,
      migrateDeleting: this._migrateDeleting,
    };
  }

  // ─── Data Loading ────────────────────────────────────────────────────────

  async _loadData() {
    await Promise.all([
      this._loadCategories(),
      this._loadUsers(),
      this._loadSubscriptions(),
      this._loadQueue(),
      this._loadLogs(),
      this._loadLogStats(),
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
      const result = await this._hass.callWS({ type: 'ticker/logs', limit: 100 });
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

  // ─── Messages ────────────────────────────────────────────────────────────

  _showError(message) {
    const el = this._els.message;
    if (el) {
      el.textContent = message;
      el.className = 'message error-message';
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 10000);
    }
  }

  _showSuccess(message) {
    const el = this._els.message;
    if (el) {
      el.textContent = message;
      el.className = 'message success-message';
      el.style.display = 'block';
      setTimeout(() => { el.style.display = 'none'; }, 3000);
    }
  }
}

customElements.define('ticker-admin-panel', TickerAdminPanel);
