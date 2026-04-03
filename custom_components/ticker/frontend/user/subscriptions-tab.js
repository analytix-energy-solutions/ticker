/**
 * Ticker User Panel - Subscriptions Tab
 * Handles subscription management and rendering.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.UserSubscriptionsTab = {
  /**
   * Render the subscriptions tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, escAttr } = window.Ticker.utils;
    const {
      currentPerson,
      categories,
      subscriptions,
      devices,
      zones,
      expandedCategories,
      devicePrefMode,
      devicePrefDevices,
      devicePrefDirty,
    } = state;

    if (!currentPerson) {
      return '<div class="card"><div class="empty-state">No person entity found.</div></div>';
    }

    const person = currentPerson;
    const escName = esc(person.name);
    const initial = esc((person.name || '?')[0].toUpperCase());

    const disabledNotice = !person.enabled
      ? '<div class="warning-banner">Your notifications are currently disabled by an administrator.</div>'
      : '';

    // Filter out admin-disabled categories
    const visibleCategories = categories.filter(cat => {
      const sub = subscriptions[cat.id];
      if (!sub) return true;
      return !(sub.mode === 'never' && sub.set_by === 'admin');
    });

    const sortedCategories = [...visibleCategories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    let subscriptionsList = '';
    if (sortedCategories.length === 0) {
      subscriptionsList = '<div class="empty-state"><p>No notification categories available.</p></div>';
    } else {
      subscriptionsList = `<div class="subscriptions-list">${sortedCategories.map(cat =>
        this._renderSubscriptionItem(cat, person, state)
      ).join('')}</div>`;
    }

    // Device display
    const deviceDisplay = devices.length > 0
      ? `<div style="font-size: 13px; color: var(--text-secondary); margin-bottom: 4px;">Your devices:</div>
         <div class="notify-services">${devices.map(svc =>
           `<span class="notify-service-tag">${esc(svc.name)}</span>`
         ).join('')}</div>`
      : `<p style="color: var(--text-secondary); font-size: 14px; margin: 0;">
           <span class="badge badge-warning">No notify services</span> No notification services linked.
         </p>`;

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
        ${this._renderDevicePreference(person, state)}
      </div>
      <div class="card">
        <h2 class="card-title">My Subscriptions</h2>
        <p class="card-description">Choose how you want to receive notifications for each category.</p>
        ${subscriptionsList}
      </div>
    `;
  },

  /**
   * Render device preference section.
   */
  _renderDevicePreference(person, state) {
    const { esc, escAttr } = window.Ticker.utils;
    const { devices, devicePrefMode, devicePrefDevices, devicePrefDirty } = state;

    if (devices.length < 2) {
      return '';
    }

    const isAllMode = devicePrefMode === 'all';
    const isSelectedMode = devicePrefMode === 'selected';
    const disabled = !person.enabled;

    const deviceCheckboxes = devices.map(device => {
      const escService = escAttr(device.service);
      const escName = esc(device.name);
      const isChecked = devicePrefDevices.includes(device.service);
      const checkboxDisabled = disabled || isAllMode;

      return `
        <label class="device-checkbox ${checkboxDisabled ? 'disabled' : ''}">
          <input type="checkbox"
            ${isChecked ? 'checked' : ''}
            ${checkboxDisabled ? 'disabled' : ''}
            onchange="window.Ticker.UserSubscriptionsTab.handlers.handleDevicePrefDeviceToggle(window.Ticker._userPanel, '${escService}')">
          ${escName}
        </label>
      `;
    }).join('');

    const showValidationWarning = isSelectedMode && devicePrefDevices.length === 0;
    const validationWarning = showValidationWarning
      ? '<div class="warning-banner">Select at least one device to save</div>'
      : '';

    const showActions = devicePrefDirty;
    const actions = showActions ? `
      <div class="device-actions">
        <button class="btn btn-primary btn-small" onclick="window.Ticker.UserSubscriptionsTab.handlers.saveDevicePreference(window.Ticker._userPanel)" ${disabled ? 'disabled' : ''}>Save</button>
        <button class="btn btn-secondary btn-small" onclick="window.Ticker.UserSubscriptionsTab.handlers.cancelDevicePreference(window.Ticker._userPanel)">Cancel</button>
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
              onchange="window.Ticker.UserSubscriptionsTab.handlers.handleDevicePrefModeChange(window.Ticker._userPanel, 'all')">
            Send to all devices
          </label>
          <label class="radio-option">
            <input type="radio" name="device-pref-mode" value="selected"
              ${isSelectedMode ? 'checked' : ''}
              ${disabled ? 'disabled' : ''}
              onchange="window.Ticker.UserSubscriptionsTab.handlers.handleDevicePrefModeChange(window.Ticker._userPanel, 'selected')">
            Selected devices only
          </label>
        </div>
        ${isSelectedMode ? `<div class="device-list">${deviceCheckboxes}</div>` : ''}
        ${validationWarning}
        ${actions}
      </div>
    `;
  },

  /**
   * Render a single subscription item.
   */
  _renderSubscriptionItem(cat, person, state) {
    const { esc, escAttr } = window.Ticker.utils;
    const { subscriptions, devices, expandedCategories, zones, entities } = state;

    const escCatId = escAttr(cat.id);
    const escCatName = esc(cat.name || cat.id);
    // Fall back to category defaults if no explicit subscription
    const sub = subscriptions[cat.id] || this._getCategoryDefault(cat);
    const currentMode = sub.mode || 'always';
    const isConditional = currentMode === 'conditional';
    const isAlways = currentMode === 'always';
    const showExpand = isConditional || (isAlways && devices.length >= 2);
    const isExpanded = expandedCategories.has(cat.id);

    let expandableContent = '';

    if (isExpanded) {
      // Conditions UI for conditional mode
      let conditionsContent = '';
      if (isConditional) {
        const conditions = sub.conditions || {};
        const deliverWhenMet = conditions.deliver_when_met || false;
        const queueUntilMet = conditions.queue_until_met || false;
        const hasNoEffectiveDelivery = !deliverWhenMet && !queueUntilMet;

        conditionsContent = `
          <div class="conditions-section">
            <div class="section-title">Conditions</div>
            <ticker-conditions-ui
              id="conditions-ui-${escCatId}"
              ${!person.enabled ? 'disabled' : ''}
            ></ticker-conditions-ui>
            ${hasNoEffectiveDelivery ? `
              <div class="warning-banner">
                No delivery actions configured. Enable "Deliver when met" or "Queue until met".
              </div>
            ` : ''}
          </div>
        `;
      }

      // Device override section
      let deviceOverrideContent = '';
      if ((isAlways || isConditional) && devices.length >= 2) {
        deviceOverrideContent = this._renderDeviceOverride(cat, person, state);
      }

      expandableContent = `
        <div class="conditional-content">
          ${conditionsContent}
          ${deviceOverrideContent}
        </div>
      `;
    }

    const headerClick = showExpand
      ? `onclick="window.Ticker.UserSubscriptionsTab.handlers.toggleCategoryExpand(window.Ticker._userPanel, '${escCatId}')"`
      : '';

    return `
      <div class="subscription-item" data-category-id="${escCatId}">
        <div class="subscription-header ${isExpanded ? 'expanded' : ''}" ${headerClick}>
          <div class="subscription-label">
            ${showExpand ? `<span class="chevron ${isExpanded ? 'expanded' : ''}">▶</span>` : ''}
            ${escCatName}
          </div>
          <div class="subscription-controls">
            <select class="subscription-select"
              onchange="window.Ticker.UserSubscriptionsTab.handlers.handleModeChange(window.Ticker._userPanel, '${escCatId}', this.value); event.stopPropagation();"
              onclick="event.stopPropagation();"
              ${!person.enabled ? 'disabled' : ''}>
              <option value="always" ${currentMode === 'always' ? 'selected' : ''}>Always</option>
              <option value="never" ${currentMode === 'never' ? 'selected' : ''}>Never</option>
              <option value="conditional" ${currentMode === 'conditional' ? 'selected' : ''}>Conditional</option>
            </select>
          </div>
        </div>
        ${expandableContent}
      </div>
    `;
  },

  /**
   * Render device override section for a category.
   */
  _renderDeviceOverride(cat, person, state) {
    const { esc, escAttr } = window.Ticker.utils;
    const { subscriptions, devices, devicePrefMode, devicePrefDevices } = state;

    const escCatId = escAttr(cat.id);
    const sub = subscriptions[cat.id] || {};
    const deviceOverride = sub.device_override || { enabled: false, devices: [] };
    const overrideEnabled = deviceOverride.enabled;
    const overrideDevices = deviceOverride.devices || [];

    const deviceCheckboxes = devices.map(device => {
      const escService = escAttr(device.service);
      const escDeviceName = esc(device.name);
      const isChecked = overrideDevices.includes(device.service);
      const checkboxDisabled = !person.enabled || !overrideEnabled;

      return `
        <label class="device-checkbox ${checkboxDisabled ? 'disabled' : ''}">
          <input type="checkbox"
            ${isChecked ? 'checked' : ''}
            ${checkboxDisabled ? 'disabled' : ''}
            onchange="window.Ticker.UserSubscriptionsTab.handlers.toggleDeviceOverrideDevice(window.Ticker._userPanel, '${escCatId}', '${escService}')">
          ${escDeviceName}
        </label>
      `;
    }).join('');

    return `
      <div class="device-override-section">
        <label class="device-override-toggle">
          <input type="checkbox"
            ${overrideEnabled ? 'checked' : ''}
            ${!person.enabled ? 'disabled' : ''}
            onchange="window.Ticker.UserSubscriptionsTab.handlers.toggleDeviceOverride(window.Ticker._userPanel, '${escCatId}')">
          Also send to additional devices
        </label>
        ${overrideEnabled ? `
          <div class="device-override-help">Select extra devices for this category:</div>
          <div class="device-override-list">${deviceCheckboxes}</div>
        ` : ''}
      </div>
    `;
  },

  /**
   * Build a default subscription from category defaults.
   * Used when user has no explicit subscription yet.
   */
  _getCategoryDefault(cat) {
    if (cat.default_mode) {
      const sub = { mode: cat.default_mode };
      if (cat.default_mode === 'conditional' && cat.default_conditions) {
        sub.conditions = cat.default_conditions;
      }
      return sub;
    }
    return { mode: 'always' };
  },

  /**
   * Get condition_tree from conditions (with legacy conversion).
   * Returns a tree node (group) for the conditions UI.
   * Legacy zones/rules formats are auto-wrapped in a root AND group.
   */
  _getConditionTree(conditions) {
    // New format: condition_tree already present
    if (conditions.condition_tree) {
      return conditions.condition_tree;
    }

    // Flat rules[] format: wrap in root AND group
    if (conditions.rules && conditions.rules.length > 0) {
      return { type: 'group', operator: 'AND', children: conditions.rules };
    }

    // Convert legacy zones format
    const zones = conditions.zones || {};
    if (Object.keys(zones).length > 0) {
      const children = Object.entries(zones).map(([zoneId]) => ({
        type: 'zone',
        zone_id: zoneId,
      }));
      return { type: 'group', operator: 'AND', children };
    }

    return { type: 'group', operator: 'AND', children: [] };
  },

  /**
   * Set up conditions UI components after render.
   * Called from ticker-panel.js _afterRender() to wire up
   * ticker-conditions-ui elements with data and event listeners.
   * @param {TickerPanel} panel - The panel instance
   */
  setupConditionsUI(panel) {
    for (const cat of panel._categories) {
      const sub = panel._subscriptions[cat.id] || this._getCategoryDefault(cat);
      const isConditional = sub.mode === 'conditional';
      const isExpanded = panel._expandedCategories.has(cat.id);
      if (!isConditional || !isExpanded) continue;
      const conditionsUI = panel.shadowRoot.getElementById(`conditions-ui-${cat.id}`);
      if (!conditionsUI) continue;
      const conditions = sub.conditions || {};
      const tree = this._getConditionTree(conditions);
      conditionsUI.tree = tree;
      conditionsUI.deliverWhenMet = conditions.deliver_when_met || false;
      conditionsUI.queueUntilMet = conditions.queue_until_met || false;
      conditionsUI.zones = panel._zones;
      conditionsUI.entities = panel._entities;
      conditionsUI.removeEventListener('rules-changed', conditionsUI._rulesHandler);
      conditionsUI._rulesHandler = (e) => {
        this.handlers.handleRulesChanged(panel, cat.id, e.detail);
      };
      conditionsUI.addEventListener('rules-changed', conditionsUI._rulesHandler);
    }
  },

  // handlers object is loaded from user/subscriptions-handlers.js
};
