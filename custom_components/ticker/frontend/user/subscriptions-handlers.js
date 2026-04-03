/**
 * Ticker User Panel - Subscriptions Handlers
 * Event handlers for subscription management, extracted from subscriptions-tab.js
 * to keep files under 500 lines.
 *
 * All handlers receive a panel reference as their first argument,
 * called via onclick strings in the rendered HTML.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};
window.Ticker.UserSubscriptionsTab = window.Ticker.UserSubscriptionsTab || {};

window.Ticker.UserSubscriptionsTab.handlers = {
  async handleModeChange(panel, categoryId, newMode) {
    const sub = panel._subscriptions[categoryId] || {};
    const existingOverride = sub.device_override || { enabled: false, devices: [] };
    if (newMode === 'conditional') {
      const conditions = {
        deliver_when_met: true,
        queue_until_met: true,
        condition_tree: {
          type: 'group',
          operator: 'AND',
          children: [{ type: 'zone', zone_id: 'zone.home' }],
        },
      };
      panel._expandedCategories.add(categoryId);
      await this.setSubscription(panel, categoryId, newMode, conditions, existingOverride);
    } else {
      panel._expandedCategories.delete(categoryId);
      const override = newMode === 'never' ? null : existingOverride;
      await this.setSubscription(panel, categoryId, newMode, null, override);
    }
  },

  async setSubscription(panel, categoryId, mode, conditions, deviceOverride) {
    if (!panel._currentPerson) return;
    try {
      const params = {
        type: 'ticker/subscription/set',
        person_id: panel._currentPerson.person_id,
        category_id: categoryId,
        mode: mode,
      };
      if (mode === 'conditional' && conditions) {
        params.conditions = conditions;
      }
      if (deviceOverride !== null) {
        params.device_override = deviceOverride;
      }
      await panel._hass.callWS(params);
      await panel._loadSubscriptions();
      panel._renderTabContentPreserveScroll();
      panel._showSuccess('Subscription updated');
    } catch (err) {
      panel._showError(err.message || 'Failed to update subscription');
    }
  },

  async handleRulesChanged(panel, categoryId, detail) {
    const { condition_tree, deliver_when_met, queue_until_met } = detail;
    const sub = panel._subscriptions[categoryId] || {};
    const deviceOverride = sub.device_override || { enabled: false, devices: [] };
    // No children in tree means no conditions: revert to always
    const leaves = window.Ticker.conditionsTree.collectLeaves(condition_tree);
    if (leaves.length === 0) {
      await this.setSubscription(panel, categoryId, 'always', null, deviceOverride);
      return;
    }
    const conditions = {
      deliver_when_met: deliver_when_met,
      queue_until_met: queue_until_met,
      condition_tree: condition_tree,
    };
    await this._saveTreeWithoutRerender(panel, categoryId, conditions, deviceOverride);
  },

  /**
   * Save condition tree without triggering a full re-render.
   * This preserves the conditions UI expanded state.
   * Incomplete leaves (e.g. state rules missing entity_id/state)
   * are pruned from the backend payload but kept in local state.
   */
  async _saveTreeWithoutRerender(panel, categoryId, conditions, deviceOverride) {
    if (!panel._currentPerson) return;
    // Always update local state with full tree (including incomplete leaves)
    if (!panel._subscriptions[categoryId]) {
      panel._subscriptions[categoryId] = {};
    }
    panel._subscriptions[categoryId].mode = 'conditional';
    panel._subscriptions[categoryId].conditions = conditions;
    if (deviceOverride !== null) {
      panel._subscriptions[categoryId].device_override = deviceOverride;
    }
    // Prune incomplete leaves for backend validation
    const tree = conditions.condition_tree;
    const pruned = window.Ticker.conditionsTree.pruneTree(tree);
    const validLeaves = window.Ticker.conditionsTree.collectLeaves(pruned);
    if (validLeaves.length === 0) return;
    try {
      const saveConditions = {
        deliver_when_met: conditions.deliver_when_met,
        queue_until_met: conditions.queue_until_met,
        condition_tree: pruned,
      };
      const params = {
        type: 'ticker/subscription/set',
        person_id: panel._currentPerson.person_id,
        category_id: categoryId,
        mode: 'conditional',
        conditions: saveConditions,
      };
      if (deviceOverride !== null) {
        params.device_override = deviceOverride;
      }
      await panel._hass.callWS(params);
      panel._showSuccess('Saved');
    } catch (err) {
      panel._showError(err.message || 'Failed to save');
    }
  },

  toggleCategoryExpand(panel, categoryId) {
    const shadowRoot = panel.shadowRoot;
    const item = shadowRoot.querySelector(`[data-category-id="${categoryId}"]`)
      || shadowRoot.querySelector(`.subscription-item:has([onclick*="${categoryId}"])`);
    if (panel._expandedCategories.has(categoryId)) {
      panel._expandedCategories.delete(categoryId);
      if (item) {
        const content = item.querySelector('.conditional-content');
        const header = item.querySelector('.subscription-header');
        if (content) content.remove();
        if (header) header.classList.remove('expanded');
        const chevron = header?.querySelector('.chevron');
        if (chevron) chevron.classList.remove('expanded');
      } else {
        panel._renderTabContentPreserveScroll();
      }
    } else {
      panel._expandedCategories.add(categoryId);
      panel._renderTabContentPreserveScroll();
    }
  },

  async toggleDeviceOverride(panel, categoryId) {
    const sub = panel._subscriptions[categoryId] || {};
    const currentOverride = sub.device_override || { enabled: false, devices: [] };
    const mode = sub.mode || 'always';
    const conditions = mode === 'conditional' ? sub.conditions : null;
    const newOverride = {
      enabled: !currentOverride.enabled,
      devices: currentOverride.devices || [],
    };
    await this.setSubscription(panel, categoryId, mode, conditions, newOverride);
  },

  async toggleDeviceOverrideDevice(panel, categoryId, serviceId) {
    const sub = panel._subscriptions[categoryId] || {};
    const currentOverride = sub.device_override || { enabled: false, devices: [] };
    const mode = sub.mode || 'always';
    const conditions = mode === 'conditional' ? sub.conditions : null;
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
    await this.setSubscription(panel, categoryId, mode, conditions, newOverride);
  },

  handleDevicePrefModeChange(panel, mode) {
    panel._devicePrefMode = mode;
    if (mode === 'all') {
      panel._devicePrefDevices = [];
    }
    panel._devicePrefDirty = true;
    // BUG-040: Targeted DOM update for device list visibility
    const shadowRoot = panel.shadowRoot;
    const deviceList = shadowRoot.querySelector('.device-section .device-list');
    const actionsContainer = shadowRoot.querySelector('.device-section .device-actions');
    if (mode === 'all' && deviceList) {
      deviceList.style.display = 'none';
    } else if (mode === 'selected' && deviceList) {
      deviceList.style.display = 'flex';
    } else {
      panel._renderTabContentPreserveScroll();
      return;
    }
    const radios = shadowRoot.querySelectorAll('.device-section input[type="radio"]');
    radios.forEach(radio => {
      radio.checked = radio.value === mode;
    });
    if (!actionsContainer && panel._devicePrefDirty) {
      panel._renderTabContentPreserveScroll();
    }
  },

  handleDevicePrefDeviceToggle(panel, serviceId) {
    const idx = panel._devicePrefDevices.indexOf(serviceId);
    if (idx >= 0) {
      panel._devicePrefDevices.splice(idx, 1);
    } else {
      panel._devicePrefDevices.push(serviceId);
    }
    panel._devicePrefDirty = true;
    // BUG-040: Checkbox state is already updated by browser, just show actions if needed
    const shadowRoot = panel.shadowRoot;
    const actionsContainer = shadowRoot.querySelector('.device-section .device-actions');
    if (!actionsContainer) {
      panel._renderTabContentPreserveScroll();
    }
  },

  async saveDevicePreference(panel) {
    if (!panel._currentPerson) return;
    if (panel._devicePrefMode === 'selected' && panel._devicePrefDevices.length === 0) {
      panel._showError('Please select at least one device');
      return;
    }
    try {
      await panel._hass.callWS({
        type: 'ticker/device_preference/set',
        mode: panel._devicePrefMode,
        devices: panel._devicePrefMode === 'selected' ? panel._devicePrefDevices : [],
      });
      await panel._loadCurrentPerson();
      panel._initDevicePrefState();
      panel._renderTabContentPreserveScroll();
      panel._showSuccess('Device preference saved');
    } catch (err) {
      panel._showError(err.message || 'Failed to save device preference');
    }
  },

  cancelDevicePreference(panel) {
    panel._initDevicePrefState();
    panel._renderTabContentPreserveScroll();
  },
};
