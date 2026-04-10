/**
 * Ticker Admin Panel - Data Loader
 * Extracted data loading methods from ticker-admin-panel.js.
 *
 * All methods accept `panel` as the first argument and set properties on it.
 */
window.Ticker = window.Ticker || {};

const EXCLUDED_PANELS = new Set(['ticker', 'ticker-admin', 'config', 'developer-tools']);

window.Ticker.AdminDataLoader = {
  /**
   * Load all data in parallel, then refresh tab badges.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadAll(panel) {
    await Promise.all([
      this.loadCategories(panel),
      this.loadUsers(panel),
      this.loadRecipients(panel),
      this.loadSubscriptions(panel),
      this.loadQueue(panel),
      this.loadLogs(panel),
      this.loadLogStats(panel),
      this.loadZones(panel),
      this.loadEntities(panel),
      this.loadActionSets(panel),
      this.loadDashboards(panel),
    ]);
    if (!panel._lovelaceViews) panel._lovelaceViews = {};
    await this.loadLovelaceViews(panel);
    panel._renderTabs();
  },

  /**
   * Load categories from the WebSocket API.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadCategories(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/categories' });
      panel._categories = result.categories || [];
    } catch (err) {
      console.error('[Ticker] Failed to load categories:', err);
    }
  },

  /**
   * Load users from the WebSocket API.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadUsers(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/users' });
      panel._users = result.users || [];
    } catch (err) {
      console.error('[Ticker] Failed to load users:', err);
    }
  },

  /**
   * Load recipients from the WebSocket API.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadRecipients(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/get_recipients' });
      panel._recipients = result.recipients || [];
    } catch (err) {
      console.error('[Ticker] Failed to load recipients:', err);
    }
  },

  /**
   * Load available notify services, optionally filtered by recipient.
   * @param {HTMLElement} panel - The admin panel instance
   * @param {string} [recipientId] - Optional recipient ID to filter by
   */
  async loadAvailableNotifyServices(panel, recipientId) {
    try {
      const wsMsg = { type: 'ticker/get_available_notify_services' };
      if (recipientId) wsMsg.recipient_id = recipientId;
      const result = await panel._hass.callWS(wsMsg);
      panel._availableNotifyServices = result.services || [];
    } catch (err) {
      console.error('[Ticker] Failed to load available notify services:', err);
    }
  },

  /**
   * Load TTS options (media players and TTS services).
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadTtsOptions(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/get_tts_options' });
      panel._ttsOptions = {
        media_players: result.media_players || [],
        tts_services: result.tts_services || [],
      };
    } catch (err) {
      console.error('[Ticker] Failed to load TTS options:', err);
      panel._ttsOptions = { media_players: [], tts_services: [] };
    }
  },

  /**
   * Load subscriptions and index by person_id.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadSubscriptions(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/subscriptions' });
      panel._subscriptions = {};
      for (const sub of result.subscriptions || []) {
        if (!panel._subscriptions[sub.person_id]) {
          panel._subscriptions[sub.person_id] = {};
        }
        panel._subscriptions[sub.person_id][sub.category_id] = sub;
      }
    } catch (err) {
      console.error('[Ticker] Failed to load subscriptions:', err);
    }
  },

  /**
   * Load the notification queue.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadQueue(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/queue' });
      panel._queue = result.queue || [];
    } catch (err) {
      console.error('[Ticker] Failed to load queue:', err);
    }
  },

  /**
   * Load notification logs.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadLogs(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/logs', limit: 500 });
      panel._logs = result.logs || [];
    } catch (err) {
      console.error('[Ticker] Failed to load logs:', err);
    }
  },

  /**
   * Load log statistics.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadLogStats(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/logs/stats' });
      panel._logStats = result.stats || {};
    } catch (err) {
      console.error('[Ticker] Failed to load log stats:', err);
    }
  },

  /**
   * Load zones from the WebSocket API.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadZones(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/zones' });
      panel._zones = result.zones || [];
    } catch (err) {
      console.error('[Ticker] Failed to load zones:', err);
      panel._zones = [];
    }
  },

  /**
   * Load action sets from the WebSocket API (F-5b).
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadActionSets(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'ticker/action_sets/list' });
      panel._actionSets = result.action_sets || [];
    } catch (err) {
      console.error('[Ticker] Failed to load action sets:', err);
      panel._actionSets = [];
    }
  },

  /**
   * Load Lovelace dashboards for navigation picker (F-22).
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadDashboards(panel) {
    try {
      const result = await panel._hass.callWS({ type: 'lovelace/dashboards/list' });
      panel._lovelaceDashboards = result || [];
    } catch (err) {
      console.error('[Ticker] Failed to load dashboards:', err);
      panel._lovelaceDashboards = [];
    }
  },

  /**
   * Load entities from hass.states (synchronous, no WS call).
   * @param {HTMLElement} panel - The admin panel instance
   */
  loadEntities(panel) {
    try {
      const states = panel._hass.states;
      const all = Object.keys(states);
      panel._entities = all.map(id => ({
        entity_id: id,
        name: states[id].attributes.friendly_name || id,
      })).sort((a, b) => a.name.localeCompare(b.name));
      panel._scripts = panel._entities.filter(e => e.entity_id.startsWith('script.'));

      // Build sidebar panels list from hass.panels (F-22b)
      const panels = panel._hass.panels || {};
      panel._hasPanels = Object.values(panels)
        .filter(p => p.title && !EXCLUDED_PANELS.has(p.url_path))
        .sort((a, b) => (a.title || '').localeCompare(b.title || ''))
        .map(p => ({ url_path: p.url_path, title: p.title, icon: p.icon || '' }));
    } catch (err) {
      console.error('[Ticker] Failed to load entities:', err);
      panel._entities = [];
      panel._scripts = [];
      panel._hasPanels = [];
    }
  },

  /**
   * Load Lovelace views for each dashboard (F-22b).
   * Must be called after loadDashboards so panel._lovelaceDashboards is available.
   * @param {HTMLElement} panel - The admin panel instance
   */
  async loadLovelaceViews(panel) {
    if (!panel._hass || !panel._hass.callWS) return;

    panel._lovelaceViews = {};

    // Fetch default dashboard views
    try {
      const config = await panel._hass.callWS({ type: 'lovelace/config' });
      if (config && config.views) {
        panel._lovelaceViews[''] = config.views
          .filter(v => v.title)
          .map((v, i) => ({ title: v.title, path: v.path || String(i) }));
      }
    } catch (_) { /* silent — yaml-mode or unconfigured dashboard has no lovelace config */ }

    // Fetch views for each user-created dashboard (in parallel)
    const dashboards = panel._lovelaceDashboards || [];
    await Promise.allSettled(dashboards.map(async (db) => {
      try {
        const config = await panel._hass.callWS({
          type: 'lovelace/config',
          url_path: db.url_path,
        });
        if (config && config.views) {
          panel._lovelaceViews[db.url_path] = config.views
            .filter(v => v.title)
            .map((v, i) => ({ title: v.title, path: v.path || String(i) }));
        }
      } catch (_) { /* silent — yaml-mode or unconfigured dashboard has no lovelace config */ }
    }));
  },
};
