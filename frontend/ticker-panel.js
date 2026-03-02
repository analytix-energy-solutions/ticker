/**
 * Ticker User Panel
 * Smart notifications for Home Assistant
 * 
 * Brand: See branding/README.md
 * Colors: --ticker-500: #06b6d4, --ticker-400: #22d3ee, --ticker-700: #0e7490
 */

class TickerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._currentPerson = null;
    this._categories = [];
    this._subscriptions = {};
    this._zones = [];
    this._queue = [];
    this._devices = [];
    this._activeTab = window.location.hash === "#history" ? "history" : "subscriptions";
    this._loading = true;
    this._error = null;
    this._history = [];
    this._expandedCategories = new Set();
    // Device preference editing state
    this._devicePrefMode = "all";
    this._devicePrefDevices = [];
    this._devicePrefDirty = false;
  }

  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  }

  _escAttr(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
    }
  }

  async _initialize() {
    this._initialized = true;
    this._render();
    await this._loadData();
  }

  async _loadData() {
    this._loading = true;
    this._error = null;
    this._render();

    try {
      await Promise.all([
        this._loadCurrentPerson(),
        this._loadCategories(),
        this._loadZones(),
        this._loadDevices(),
      ]);
      
      if (this._currentPerson) {
        await Promise.all([
          this._loadSubscriptions(),
          this._loadQueue(),
          this._loadHistory(),
        ]);
        // Initialize device preference state from loaded person
        this._initDevicePrefState();
      }
    } catch (err) {
      console.error("Failed to load data:", err);
      this._error = err.message || "Failed to load data";
    }

    this._loading = false;
    this._render();
  }

  async _loadCurrentPerson() {
    try {
      const result = await this._hass.callWS({ type: "ticker/current_person" });
      this._currentPerson = result.person;
    } catch (err) {
      console.error("Failed to load current person:", err);
      this._currentPerson = null;
    }
  }

  async _loadCategories() {
    try {
      const result = await this._hass.callWS({ type: "ticker/categories" });
      this._categories = result.categories || [];
    } catch (err) {
      console.error("Failed to load categories:", err);
      this._categories = [];
    }
  }

  async _loadZones() {
    try {
      const result = await this._hass.callWS({ type: "ticker/zones" });
      this._zones = result.zones || [];
    } catch (err) {
      console.error("Failed to load zones:", err);
      this._zones = [];
    }
  }

  async _loadDevices() {
    try {
      const result = await this._hass.callWS({ type: "ticker/devices" });
      this._devices = result.devices || [];
    } catch (err) {
      console.error("Failed to load devices:", err);
      this._devices = [];
    }
  }

  async _loadSubscriptions() {
    if (!this._currentPerson) return;
    
    try {
      const result = await this._hass.callWS({ 
        type: "ticker/subscriptions",
        person_id: this._currentPerson.person_id,
      });
      this._subscriptions = {};
      for (const sub of result.subscriptions || []) {
        this._subscriptions[sub.category_id] = sub;
      }
    } catch (err) {
      console.error("Failed to load subscriptions:", err);
      this._subscriptions = {};
    }
  }

  async _loadQueue() {
    if (!this._currentPerson) return;
    
    try {
      const result = await this._hass.callWS({ 
        type: "ticker/queue",
        person_id: this._currentPerson.person_id,
      });
      this._queue = result.queue || [];
    } catch (err) {
      console.error("Failed to load queue:", err);
      this._queue = [];
    }
  }

  async _loadHistory() {
    if (!this._currentPerson) return;
    
    try {
      const result = await this._hass.callWS({
        type: "ticker/logs",
        person_id: this._currentPerson.person_id,
        outcome: "sent",
        limit: 500,
      });
      this._history = result.logs || [];
    } catch (err) {
      console.error("Failed to load history:", err);
      this._history = [];
    }
  }

  _initDevicePrefState() {
    if (!this._currentPerson) return;
    const pref = this._currentPerson.device_preference || { mode: "all", devices: [] };
    this._devicePrefMode = pref.mode || "all";
    this._devicePrefDevices = [...(pref.devices || [])];
    this._devicePrefDirty = false;
  }

  _getSubscription(categoryId) {
    return this._subscriptions[categoryId] || { mode: "always" };
  }

  _getSubscriptionMode(categoryId) {
    const sub = this._getSubscription(categoryId);
    return sub.mode || "always";
  }

  _getSubscriptionConditions(categoryId) {
    const sub = this._getSubscription(categoryId);
    return sub.conditions || {};
  }

  _getConfiguredZones(categoryId) {
    const conditions = this._getSubscriptionConditions(categoryId);
    return conditions.zones || {};
  }

  _getDeviceOverride(categoryId) {
    const sub = this._getSubscription(categoryId);
    return sub.device_override || { enabled: false, devices: [] };
  }

  _isAdminDisabled(categoryId) {
    // Check if this category has been disabled by an admin
    const sub = this._subscriptions[categoryId];
    if (!sub) return false;
    return sub.mode === "never" && sub.set_by === "admin";
  }

  _getDeviceName(serviceId) {
    const device = this._devices.find(d => d.service === serviceId);
    return device ? device.name : serviceId;
  }

  // Device preference handlers
  _handleDevicePrefModeChange(mode) {
    this._devicePrefMode = mode;
    if (mode === "all") {
      this._devicePrefDevices = [];
    }
    this._devicePrefDirty = true;
    this._render();
  }

  _handleDevicePrefDeviceToggle(serviceId) {
    const idx = this._devicePrefDevices.indexOf(serviceId);
    if (idx >= 0) {
      this._devicePrefDevices.splice(idx, 1);
    } else {
      this._devicePrefDevices.push(serviceId);
    }
    this._devicePrefDirty = true;
    this._render();
  }

  async _saveDevicePreference() {
    if (!this._currentPerson) return;

    // Validate: selected mode requires at least one device
    if (this._devicePrefMode === "selected" && this._devicePrefDevices.length === 0) {
      this._showError("Please select at least one device");
      return;
    }

    try {
      await this._hass.callWS({
        type: "ticker/device_preference/set",
        mode: this._devicePrefMode,
        devices: this._devicePrefMode === "selected" ? this._devicePrefDevices : [],
      });
      
      // Reload person to get updated preference
      await this._loadCurrentPerson();
      this._initDevicePrefState();
      this._render();
      this._showSuccess("Device preference saved");
    } catch (err) {
      this._showError(err.message || "Failed to save device preference");
    }
  }

  _cancelDevicePreference() {
    this._initDevicePrefState();
    this._render();
  }

  async _setSubscription(categoryId, mode, conditions = null, deviceOverride = null) {
    if (!this._currentPerson) return;

    try {
      const params = {
        type: "ticker/subscription/set",
        person_id: this._currentPerson.person_id,
        category_id: categoryId,
        mode: mode,
      };
      
      if (mode === "conditional" && conditions) {
        params.conditions = conditions;
      }

      if (deviceOverride !== null) {
        params.device_override = deviceOverride;
      }

      await this._hass.callWS(params);
      await this._loadSubscriptions();
      this._render();
      this._showSuccess("Subscription updated");
    } catch (err) {
      this._showError(err.message || "Failed to update subscription");
    }
  }

  async _handleModeChange(categoryId, newMode) {
    // Preserve existing device override when changing modes
    const existingOverride = this._getDeviceOverride(categoryId);
    
    if (newMode === "conditional") {
      // Switch to conditional with default Home zone
      const conditions = {
        zones: {
          "zone.home": {
            deliver_while_here: true,
            queue_until_arrival: true,
          }
        }
      };
      this._expandedCategories.add(categoryId);
      await this._setSubscription(categoryId, newMode, conditions, existingOverride);
    } else {
      this._expandedCategories.delete(categoryId);
      // Device override not applicable for "never" mode
      const override = newMode === "never" ? null : existingOverride;
      await this._setSubscription(categoryId, newMode, null, override);
    }
  }

  async _toggleZoneOption(categoryId, zoneId, option) {
    const conditions = this._getSubscriptionConditions(categoryId);
    const zones = { ...conditions.zones } || {};
    
    if (!zones[zoneId]) {
      zones[zoneId] = { deliver_while_here: false, queue_until_arrival: false };
    }
    
    zones[zoneId][option] = !zones[zoneId][option];
    
    const deviceOverride = this._getDeviceOverride(categoryId);
    await this._setSubscription(categoryId, "conditional", { zones }, deviceOverride);
  }

  async _addZone(categoryId, zoneId) {
    const conditions = this._getSubscriptionConditions(categoryId);
    const zones = { ...conditions.zones } || {};
    
    if (!zones[zoneId]) {
      zones[zoneId] = { deliver_while_here: true, queue_until_arrival: true };
    }
    
    const deviceOverride = this._getDeviceOverride(categoryId);
    await this._setSubscription(categoryId, "conditional", { zones }, deviceOverride);
  }

  async _removeZone(categoryId, zoneId) {
    const conditions = this._getSubscriptionConditions(categoryId);
    const zones = { ...conditions.zones } || {};
    
    delete zones[zoneId];
    
    const deviceOverride = this._getDeviceOverride(categoryId);
    
    // If no zones left, switch to always mode
    if (Object.keys(zones).length === 0) {
      await this._setSubscription(categoryId, "always", null, deviceOverride);
    } else {
      await this._setSubscription(categoryId, "conditional", { zones }, deviceOverride);
    }
  }

  async _toggleDeviceOverride(categoryId) {
    const currentOverride = this._getDeviceOverride(categoryId);
    const mode = this._getSubscriptionMode(categoryId);
    const conditions = mode === "conditional" ? this._getSubscriptionConditions(categoryId) : null;
    
    const newOverride = {
      enabled: !currentOverride.enabled,
      devices: currentOverride.devices || [],
    };
    
    await this._setSubscription(categoryId, mode, conditions, newOverride);
  }

  async _toggleDeviceOverrideDevice(categoryId, serviceId) {
    const currentOverride = this._getDeviceOverride(categoryId);
    const mode = this._getSubscriptionMode(categoryId);
    const conditions = mode === "conditional" ? this._getSubscriptionConditions(categoryId) : null;
    
    const devices = [...(currentOverride.devices || [])];
    const idx = devices.indexOf(serviceId);
    if (idx >= 0) {
      devices.splice(idx, 1);
    } else {
      devices.push(serviceId);
    }
    
    const newOverride = {
      enabled: currentOverride.enabled,
      devices: devices,
    };
    
    await this._setSubscription(categoryId, mode, conditions, newOverride);
  }

  _toggleCategoryExpand(categoryId) {
    if (this._expandedCategories.has(categoryId)) {
      this._expandedCategories.delete(categoryId);
    } else {
      this._expandedCategories.add(categoryId);
    }
    this._render();
  }

  async _clearQueue() {
    if (!this._currentPerson) return;
    if (!confirm("Clear all queued notifications?")) return;

    try {
      await this._hass.callWS({
        type: "ticker/queue/clear",
        person_id: this._currentPerson.person_id,
      });
      await this._loadQueue();
      this._render();
      this._showSuccess("Queue cleared");
    } catch (err) {
      this._showError(err.message || "Failed to clear queue");
    }
  }

  async _removeQueueEntry(queueId) {
    try {
      await this._hass.callWS({
        type: "ticker/queue/remove",
        queue_id: queueId,
      });
      await this._loadQueue();
      this._render();
    } catch (err) {
      this._showError(err.message || "Failed to remove entry");
    }
  }

  _switchTab(tab) {
    this._activeTab = tab;
    this._render();
  }

  _showError(message) {
    const el = this.shadowRoot.getElementById("message-area");
    if (el) {
      el.textContent = message;
      el.className = "message error-message";
      el.style.display = "block";
      setTimeout(() => { el.style.display = "none"; }, 10000);
    }
  }

  _showSuccess(message) {
    const el = this.shadowRoot.getElementById("message-area");
    if (el) {
      el.textContent = message;
      el.className = "message success-message";
      el.style.display = "block";
      setTimeout(() => { el.style.display = "none"; }, 3000);
    }
  }

  _formatTime(isoString) {
    const date = new Date(isoString);
    return date.toLocaleString();
  }

  _getZoneName(zoneId) {
    const zone = this._zones.find(z => z.zone_id === zoneId);
    return zone ? zone.name : zoneId.replace("zone.", "");
  }

  _render() {
    const styles = `
      <style>
        :host {
          --ticker-500: #06b6d4;
          --ticker-400: #22d3ee;
          --ticker-700: #0e7490;
          --text-primary: var(--primary-text-color, #212121);
          --text-secondary: var(--secondary-text-color, #727272);
          --bg-card: var(--card-background-color, #fff);
          --bg-primary: var(--primary-background-color, #fafafa);
          --divider: var(--divider-color, #e0e0e0);
        }
        .container { font-family: system-ui, -apple-system, sans-serif; padding: 16px; max-width: 800px; margin: 0 auto; }
        .header { display: flex; align-items: center; gap: 16px; margin-bottom: 24px; }
        .header h1 { margin: 0; font-size: 24px; font-weight: 600; color: var(--text-primary); }
        .header-logo { width: 40px; height: 40px; }
        .tabs { display: flex; gap: 0; border-bottom: 1px solid var(--divider); margin-bottom: 24px; }
        .tab { padding: 12px 24px; border: none; background: none; cursor: pointer; font-size: 14px; font-weight: 500; color: var(--text-secondary); border-bottom: 2px solid transparent; transition: all 0.2s ease; }
        .tab:hover { color: var(--ticker-500); }
        .tab.active { color: var(--ticker-500); border-bottom-color: var(--ticker-500); }
        .tab .badge-count { background: var(--ticker-500); color: white; padding: 2px 6px; border-radius: 10px; font-size: 11px; margin-left: 6px; }
        .card { background: var(--bg-card); border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 16px; }
        .card-title { font-size: 16px; font-weight: 600; margin: 0 0 16px 0; color: var(--text-primary); }
        .card-description { color: var(--text-secondary); font-size: 14px; margin-bottom: 16px; line-height: 1.5; }
        .user-info { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: var(--bg-primary); border-radius: 4px; margin-bottom: 16px; }
        .user-avatar { width: 40px; height: 40px; border-radius: 50%; background: var(--ticker-500); display: flex; align-items: center; justify-content: center; color: white; font-weight: 600; font-size: 16px; }
        .user-details { flex: 1; }
        .user-name { font-weight: 500; color: var(--text-primary); }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500; background: var(--ticker-500); color: white; }
        .badge-warning { background: #f59e0b; }
        .badge-disabled { background: #9ca3af; }
        .error-message { display: none; padding: 12px 16px; background: #fef2f2; border: 1px solid #fecaca; border-radius: 4px; color: #dc2626; margin-bottom: 16px; }
        .success-message { display: none; padding: 12px 16px; background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 4px; color: #16a34a; margin-bottom: 16px; }
        .loading { text-align: center; padding: 40px; color: var(--text-secondary); }
        .loading-spinner { width: 32px; height: 32px; border: 3px solid var(--divider); border-top-color: var(--ticker-500); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 16px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        .empty-state { text-align: center; padding: 40px; color: var(--text-secondary); }
        .error-state { text-align: center; padding: 40px; color: #dc2626; }
        .no-person-state { text-align: center; padding: 40px; }
        .no-person-state h3 { color: var(--text-primary); margin: 0 0 8px 0; }
        .no-person-state p { color: var(--text-secondary); margin: 0; }
        .subscriptions-list { display: flex; flex-direction: column; gap: 8px; }
        .subscription-item { background: var(--bg-primary); border-radius: 4px; overflow: hidden; }
        .subscription-header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; cursor: pointer; }
        .subscription-header.expanded { border-left: 3px solid var(--ticker-500); background: rgba(6, 182, 212, 0.08); }
        .subscription-label { font-size: 14px; color: var(--text-primary); display: flex; align-items: center; gap: 8px; }
        .subscription-controls { display: flex; align-items: center; gap: 8px; }
        .subscription-select { padding: 6px 10px; border: 1px solid var(--divider); border-radius: 4px; font-size: 13px; background: var(--bg-card); color: var(--text-primary); min-width: 120px; cursor: pointer; }
        .subscription-select:focus { outline: none; border-color: var(--ticker-500); }
        .chevron { transition: transform 0.2s ease; color: var(--text-secondary); }
        .chevron.expanded { transform: rotate(90deg); }
        .conditional-content { padding: 0 16px 16px 16px; border-left: 3px solid var(--ticker-500); background: rgba(6, 182, 212, 0.04); }
        .section-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .zones-section { margin-top: 8px; }
        .zones-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
        .zone-item { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--bg-card); border-radius: 4px; margin-bottom: 8px; }
        .zone-name { font-size: 13px; color: var(--text-primary); font-weight: 500; }
        .zone-options { display: flex; gap: 16px; align-items: center; }
        .zone-option { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-secondary); }
        .zone-option input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--ticker-500); cursor: pointer; }
        .zone-delete { background: none; border: none; color: var(--text-secondary); cursor: pointer; padding: 4px; font-size: 16px; line-height: 1; }
        .zone-delete:hover { color: #ef4444; }
        .add-zone-btn { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border: 1px dashed var(--ticker-500); border-radius: 4px; background: transparent; color: var(--ticker-500); cursor: pointer; font-size: 13px; transition: background 0.2s ease; }
        .add-zone-btn:hover { background: rgba(6, 182, 212, 0.08); }
        .add-zone-select { padding: 6px 10px; border: 1px solid var(--divider); border-radius: 4px; font-size: 13px; background: var(--bg-card); color: var(--text-primary); margin-left: 8px; }
        .warning-banner { background: #fef3c7; border: 1px solid #fcd34d; border-radius: 4px; padding: 10px 12px; margin-top: 8px; color: #92400e; font-size: 12px; display: flex; align-items: center; gap: 8px; }
        .notify-services { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; }
        .notify-service-tag { padding: 2px 6px; background: rgba(6, 182, 212, 0.1); border-radius: 3px; font-size: 11px; color: var(--ticker-700); }
        .disabled-notice { background: #fef3c7; border: 1px solid #fcd34d; border-radius: 4px; padding: 12px 16px; margin-bottom: 16px; color: #92400e; font-size: 14px; }
        .queue-list { display: flex; flex-direction: column; gap: 8px; }
        .queue-item { padding: 12px 16px; background: var(--bg-primary); border-radius: 4px; }
        .queue-item-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
        .queue-item-title { font-weight: 500; color: var(--text-primary); }
        .queue-item-message { font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; }
        .queue-item-meta { font-size: 11px; color: var(--text-secondary); display: flex; gap: 12px; flex-wrap: wrap; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s ease; }
        .btn-primary { background: var(--ticker-500); color: white; }
        .btn-primary:hover { background: var(--ticker-700); }
        .btn-secondary { background: var(--bg-primary); color: var(--text-primary); border: 1px solid var(--divider); }
        .btn-secondary:hover { background: var(--divider); }
        .btn-danger { background: #ef4444; color: white; }
        .btn-danger:hover { background: #dc2626; }
        .btn-small { padding: 4px 8px; font-size: 11px; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .card-header .card-title { margin: 0; }
        
        /* Device preference styles */
        .device-section { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--divider); }
        .device-section-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px; }
        .radio-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
        .radio-option { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--text-primary); cursor: pointer; }
        .radio-option input[type="radio"] { width: 16px; height: 16px; accent-color: var(--ticker-500); cursor: pointer; }
        .device-list { display: flex; flex-direction: column; gap: 6px; padding-left: 24px; margin-bottom: 12px; }
        .device-checkbox { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-primary); cursor: pointer; }
        .device-checkbox input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--ticker-500); cursor: pointer; }
        .device-checkbox.disabled { color: var(--text-secondary); cursor: not-allowed; }
        .device-actions { display: flex; gap: 8px; margin-top: 8px; }
        
        /* Device override in subscription */
        .device-override-section { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--divider); }
        .device-override-toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-primary); cursor: pointer; margin-bottom: 8px; }
        .device-override-toggle input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--ticker-500); cursor: pointer; }
        .device-override-list { display: flex; flex-direction: column; gap: 6px; padding-left: 24px; }
        .device-override-help { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; padding-left: 24px; }
        
        /* History styles */
        .history-list { display: flex; flex-direction: column; gap: 16px; }
        .history-date-group { display: flex; flex-direction: column; gap: 8px; }
        .history-date-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.5px; padding-bottom: 4px; border-bottom: 1px solid var(--divider); }
        .history-item { padding: 12px 16px; background: var(--bg-primary); border-radius: 4px; }
        .history-item-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 4px; }
        .history-item-title { font-weight: 500; color: var(--text-primary); }
        .history-item-time { font-size: 12px; color: var(--text-secondary); white-space: nowrap; margin-left: 12px; }
        .history-item-message { font-size: 14px; color: var(--text-primary); line-height: 1.5; margin-bottom: 8px; white-space: pre-wrap; word-break: break-word; }
        .history-item-meta { display: flex; gap: 8px; flex-wrap: wrap; }
      </style>
    `;

    const header = `
      <div class="header">
        <svg class="header-logo" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="50" cy="50" r="12" fill="#06b6d4"/>
          <circle cx="50" cy="50" r="25" stroke="#06b6d4" stroke-width="4" fill="none"/>
          <circle cx="50" cy="50" r="40" stroke="#06b6d4" stroke-width="3" fill="none" opacity="0.6"/>
        </svg>
        <h1>Ticker</h1>
      </div>
    `;

    let content = "";

    if (this._loading) {
      content = `<div class="card"><div class="loading"><div class="loading-spinner"></div><p>Loading...</p></div></div>`;
    } else if (this._error) {
      content = `<div class="card"><div class="error-state"><p>Error: ${this._esc(this._error)}</p></div></div>`;
    } else if (!this._currentPerson) {
      content = `<div class="card"><div class="no-person-state"><h3>No Person Entity Found</h3><p>Your Home Assistant user account is not linked to a person entity.<br>Ask an administrator to link your account in Settings → People.</p></div></div>`;
    } else {
      const queueCount = this._queue.length;
      const historyCount = this._history.length;
      const tabs = `
        <div class="tabs">
          <button class="tab ${this._activeTab === 'subscriptions' ? 'active' : ''}" onclick="this.getRootNode().host._switchTab('subscriptions')">Subscriptions</button>
          <button class="tab ${this._activeTab === 'queue' ? 'active' : ''}" onclick="this.getRootNode().host._switchTab('queue')">Queue${queueCount > 0 ? `<span class="badge-count">${queueCount}</span>` : ''}</button>
          <button class="tab ${this._activeTab === 'history' ? 'active' : ''}" onclick="this.getRootNode().host._switchTab('history')">History${historyCount > 0 ? `<span class="badge-count">${historyCount}</span>` : ''}</button>
        </div>
      `;
      
      if (this._activeTab === "subscriptions") {
        content = tabs + this._renderSubscriptions();
      } else if (this._activeTab === "queue") {
        content = tabs + this._renderQueue();
      } else {
        content = tabs + this._renderHistory();
      }
    }

    this.shadowRoot.innerHTML = `${styles}<div class="container">${header}<div id="message-area" class="message"></div>${content}</div>`;
  }

  _renderSubscriptions() {
    const person = this._currentPerson;
    const escName = this._esc(person.name);
    const initial = this._esc((person.name || "?")[0].toUpperCase());

    const disabledNotice = !person.enabled ? `<div class="disabled-notice">Your notifications are currently disabled by an administrator.</div>` : '';

    // Filter out categories that have been disabled by an admin
    const visibleCategories = this._categories.filter(cat => !this._isAdminDisabled(cat.id));

    const sortedCategories = [...visibleCategories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    let subscriptionsList = '';
    
    if (sortedCategories.length === 0) {
      subscriptionsList = `<div class="empty-state"><p>No notification categories are available for you.</p></div>`;
    } else {
      subscriptionsList = `<div class="subscriptions-list">${sortedCategories.map(cat => this._renderSubscriptionItem(cat, person)).join("")}</div>`;
    }

    // Render device display (notify_services is now array of objects)
    const deviceDisplay = this._devices.length > 0 
      ? `<div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Your devices:</div>
         <div class="notify-services">${this._devices.map(svc => `<span class="notify-service-tag">${this._esc(svc.name)}</span>`).join("")}</div>`
      : `<p style="color: var(--text-secondary); font-size: 14px; margin: 0;"><span class="badge badge-warning">No notify services</span> No notification services linked.</p>`;

    return `
      ${disabledNotice}
      <div class="card">
        <h2 class="card-title">Your Profile</h2>
        <div class="user-info">
          <div class="user-avatar">${initial}</div>
          <div class="user-details"><div class="user-name">${escName}</div></div>
          ${!person.enabled ? '<span class="badge badge-disabled">Disabled</span>' : ''}
        </div>
        ${deviceDisplay}
        ${this._renderDevicePreference(person)}
      </div>
      <div class="card">
        <h2 class="card-title">My Subscriptions</h2>
        <p class="card-description">Choose how you want to receive notifications for each category.</p>
        ${subscriptionsList}
      </div>
    `;
  }

  _renderDevicePreference(person) {
    if (this._devices.length < 2) {
      // No point showing device preference with 0 or 1 device
      return '';
    }

    const isAllMode = this._devicePrefMode === "all";
    const isSelectedMode = this._devicePrefMode === "selected";
    const disabled = !person.enabled;

    const deviceCheckboxes = this._devices.map(device => {
      const escService = this._escAttr(device.service);
      const escName = this._esc(device.name);
      const isChecked = this._devicePrefDevices.includes(device.service);
      const checkboxDisabled = disabled || isAllMode;
      
      return `
        <label class="device-checkbox ${checkboxDisabled ? 'disabled' : ''}">
          <input type="checkbox" 
            ${isChecked ? 'checked' : ''} 
            ${checkboxDisabled ? 'disabled' : ''}
            onchange="this.getRootNode().host._handleDevicePrefDeviceToggle('${escService}')">
          ${escName}
        </label>
      `;
    }).join('');

    const showValidationWarning = isSelectedMode && this._devicePrefDevices.length === 0;
    const validationWarning = showValidationWarning 
      ? `<div class="warning-banner">⚠ Select at least one device to save</div>` 
      : '';

    const showActions = this._devicePrefDirty;
    const actions = showActions ? `
      <div class="device-actions">
        <button class="btn btn-primary btn-small" onclick="this.getRootNode().host._saveDevicePreference()" ${disabled ? 'disabled' : ''}>Save</button>
        <button class="btn btn-secondary btn-small" onclick="this.getRootNode().host._cancelDevicePreference()">Cancel</button>
      </div>
    ` : '';

    return `
      <div class="device-section">
        <div class="device-section-title">My Devices</div>
        <div class="radio-group">
          <label class="radio-option">
            <input type="radio" name="device-pref-mode" value="all" 
              ${isAllMode ? 'checked' : ''} 
              ${disabled ? 'disabled' : ''}
              onchange="this.getRootNode().host._handleDevicePrefModeChange('all')">
            Send to all devices
          </label>
          <label class="radio-option">
            <input type="radio" name="device-pref-mode" value="selected" 
              ${isSelectedMode ? 'checked' : ''} 
              ${disabled ? 'disabled' : ''}
              onchange="this.getRootNode().host._handleDevicePrefModeChange('selected')">
            Selected devices only
          </label>
        </div>
        ${isSelectedMode ? `<div class="device-list">${deviceCheckboxes}</div>` : ''}
        ${validationWarning}
        ${actions}
      </div>
    `;
  }

  _renderSubscriptionItem(cat, person) {
    const escCatId = this._escAttr(cat.id);
    const escCatName = this._esc(cat.name || cat.id);
    const currentMode = this._getSubscriptionMode(cat.id);
    const isConditional = currentMode === "conditional";
    const isAlways = currentMode === "always";
    const showExpand = isConditional || (isAlways && this._devices.length >= 2);
    const isExpanded = this._expandedCategories.has(cat.id);
    
    const configuredZones = this._getConfiguredZones(cat.id);
    const configuredZoneIds = Object.keys(configuredZones);
    const availableZonesToAdd = this._zones.filter(z => !configuredZoneIds.includes(z.zone_id));

    let expandableContent = '';
    
    if (isExpanded) {
      let zonesContent = '';
      if (isConditional) {
        const zoneItems = configuredZoneIds.map(zoneId => {
          const zoneConfig = configuredZones[zoneId];
          const escZoneId = this._escAttr(zoneId);
          const zoneName = this._esc(this._getZoneName(zoneId));
          
          return `
            <div class="zone-item">
              <span class="zone-name">${zoneName}</span>
              <div class="zone-options">
                <label class="zone-option">
                  <input type="checkbox" 
                    ${zoneConfig.deliver_while_here ? 'checked' : ''} 
                    onchange="this.getRootNode().host._toggleZoneOption('${escCatId}', '${escZoneId}', 'deliver_while_here')"
                    ${!person.enabled ? 'disabled' : ''}>
                  Deliver while here
                </label>
                <label class="zone-option">
                  <input type="checkbox" 
                    ${zoneConfig.queue_until_arrival ? 'checked' : ''} 
                    onchange="this.getRootNode().host._toggleZoneOption('${escCatId}', '${escZoneId}', 'queue_until_arrival')"
                    ${!person.enabled ? 'disabled' : ''}>
                  Queue until I arrive
                </label>
                <button class="zone-delete" onclick="this.getRootNode().host._removeZone('${escCatId}', '${escZoneId}')" title="Remove zone" ${!person.enabled ? 'disabled' : ''}>×</button>
              </div>
            </div>
          `;
        }).join('');

        const addZoneOptions = availableZonesToAdd.map(z => 
          `<option value="${this._escAttr(z.zone_id)}">${this._esc(z.name)}</option>`
        ).join('');

        const hasNoEffectiveDelivery = configuredZoneIds.length === 0 || 
          configuredZoneIds.every(zId => !configuredZones[zId].deliver_while_here && !configuredZones[zId].queue_until_arrival);

        zonesContent = `
          <div class="zones-section">
            <div class="zones-title">Zones</div>
            ${zoneItems}
            ${availableZonesToAdd.length > 0 ? `
              <div style="display: flex; align-items: center;">
                <button class="add-zone-btn" onclick="this.nextElementSibling.style.display='inline-block'; this.style.display='none';" ${!person.enabled ? 'disabled' : ''}>
                  + Add zone
                </button>
                <select class="add-zone-select" style="display: none;" onchange="if(this.value) { this.getRootNode().host._addZone('${escCatId}', this.value); this.previousElementSibling.style.display='flex'; this.style.display='none'; this.value=''; }">
                  <option value="">Select zone...</option>
                  ${addZoneOptions}
                </select>
              </div>
            ` : ''}
            ${hasNoEffectiveDelivery ? `
              <div class="warning-banner">
                ⚠ No delivery rules configured. Add a zone or enable options to receive notifications.
              </div>
            ` : ''}
          </div>
        `;
      }

      // Device override section (only for always/conditional, and only if 2+ devices)
      let deviceOverrideContent = '';
      if ((isAlways || isConditional) && this._devices.length >= 2) {
        const deviceOverride = this._getDeviceOverride(cat.id);
        const overrideEnabled = deviceOverride.enabled;
        const overrideDevices = deviceOverride.devices || [];
        
        // Get devices that are NOT in the global default selection
        // These are the devices user can add as override
        let availableOverrideDevices = [];
        if (this._devicePrefMode === "all") {
          // In "all" mode, all devices are already included, so override would add duplicates
          // But we still show the option in case user switches to "selected" later
          availableOverrideDevices = this._devices;
        } else {
          // In "selected" mode, show devices NOT in the global selection
          availableOverrideDevices = this._devices.filter(d => !this._devicePrefDevices.includes(d.service));
        }

        if (availableOverrideDevices.length > 0 || overrideDevices.length > 0) {
          const deviceCheckboxes = this._devices.map(device => {
            const escService = this._escAttr(device.service);
            const escDeviceName = this._esc(device.name);
            const isChecked = overrideDevices.includes(device.service);
            const checkboxDisabled = !person.enabled || !overrideEnabled;
            
            return `
              <label class="device-checkbox ${checkboxDisabled ? 'disabled' : ''}">
                <input type="checkbox" 
                  ${isChecked ? 'checked' : ''} 
                  ${checkboxDisabled ? 'disabled' : ''}
                  onchange="this.getRootNode().host._toggleDeviceOverrideDevice('${escCatId}', '${escService}')">
                ${escDeviceName}
              </label>
            `;
          }).join('');

          deviceOverrideContent = `
            <div class="device-override-section">
              <label class="device-override-toggle">
                <input type="checkbox" 
                  ${overrideEnabled ? 'checked' : ''} 
                  ${!person.enabled ? 'disabled' : ''}
                  onchange="this.getRootNode().host._toggleDeviceOverride('${escCatId}')">
                Also send to additional devices
              </label>
              ${overrideEnabled ? `
                <div class="device-override-help">Select extra devices for this category (additive to your default):</div>
                <div class="device-override-list">${deviceCheckboxes}</div>
              ` : ''}
            </div>
          `;
        }
      }

      expandableContent = `
        <div class="conditional-content">
          ${zonesContent}
          ${deviceOverrideContent}
        </div>
      `;
    }

    const headerClickable = showExpand;
    const headerClick = headerClickable 
      ? `onclick="this.getRootNode().host._toggleCategoryExpand('${escCatId}')"` 
      : '';

    return `
      <div class="subscription-item">
        <div class="subscription-header ${isExpanded ? 'expanded' : ''}" ${headerClick}>
          <div class="subscription-label">
            ${showExpand ? `<span class="chevron ${isExpanded ? 'expanded' : ''}">▶</span>` : ''}
            ${escCatName}
          </div>
          <div class="subscription-controls">
            <select class="subscription-select" onchange="this.getRootNode().host._handleModeChange('${escCatId}', this.value); event.stopPropagation();" onclick="event.stopPropagation();" ${!person.enabled ? 'disabled' : ''}>
              <option value="always" ${currentMode === 'always' ? 'selected' : ''}>Always</option>
              <option value="never" ${currentMode === 'never' ? 'selected' : ''}>Never</option>
              <option value="conditional" ${currentMode === 'conditional' ? 'selected' : ''}>Conditional</option>
            </select>
          </div>
        </div>
        ${expandableContent}
      </div>
    `;
  }

  _renderQueue() {
    if (this._queue.length === 0) {
      return `<div class="card"><div class="empty-state"><p>No queued notifications.</p></div></div>`;
    }

    const getCategoryName = (catId) => {
      const cat = this._categories.find(c => c.id === catId);
      return cat ? cat.name : catId;
    };

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Queued Notifications</h2>
          <button class="btn btn-danger btn-small" onclick="this.getRootNode().host._clearQueue()">Clear All</button>
        </div>
        <p class="card-description">These notifications will be delivered when you arrive at the specified zone.</p>
        <div class="queue-list">
          ${this._queue.map(entry => {
            const escQueueId = this._escAttr(entry.queue_id);
            const escTitle = this._esc(entry.title);
            const escMessage = this._esc(entry.message);
            const escCatName = this._esc(getCategoryName(entry.category_id));
            return `
            <div class="queue-item">
              <div class="queue-item-header">
                <span class="queue-item-title">${escTitle}</span>
                <button class="btn btn-danger btn-small" onclick="this.getRootNode().host._removeQueueEntry('${escQueueId}')">×</button>
              </div>
              <div class="queue-item-message">${escMessage}</div>
              <div class="queue-item-meta">
                <span>Category: ${escCatName}</span>
                <span>Queued: ${this._formatTime(entry.created_at)}</span>
                <span>Expires: ${this._formatTime(entry.expires_at)}</span>
              </div>
            </div>
          `;}).join("")}
        </div>
      </div>
    `;
  }
  _renderHistory() {
    if (this._history.length === 0) {
      return `<div class="card"><div class="empty-state"><p>No notification history yet.</p></div></div>`;
    }

    const getCategoryName = (catId) => {
      const cat = this._categories.find(c => c.id === catId);
      return cat ? cat.name : catId;
    };

    // Group by date
    const grouped = {};
    for (const entry of this._history) {
      const date = new Date(entry.timestamp);
      const dateKey = date.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
      if (!grouped[dateKey]) grouped[dateKey] = [];
      grouped[dateKey].push(entry);
    }

    const sections = Object.entries(grouped).map(([dateLabel, entries]) => {
      const items = entries.map(entry => {
        const escTitle = this._esc(entry.title);
        const escMessage = this._esc(entry.message);
        const escCatName = this._esc(getCategoryName(entry.category_id));
        const time = new Date(entry.timestamp).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        return `
          <div class="history-item">
            <div class="history-item-header">
              <span class="history-item-title">${escTitle}</span>
              <span class="history-item-time">${time}</span>
            </div>
            <div class="history-item-message">${escMessage}</div>
            <div class="history-item-meta">
              <span class="notify-service-tag">${escCatName}</span>
            </div>
          </div>
        `;
      }).join('');

      return `
        <div class="history-date-group">
          <div class="history-date-label">${this._esc(dateLabel)}</div>
          ${items}
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <h2 class="card-title">Notification History</h2>
        <p class="card-description">Notifications sent to your devices in the last 7 days.</p>
        <div class="history-list">
          ${sections}
        </div>
      </div>
    `;
  }
}

customElements.define("ticker-panel", TickerPanel);
