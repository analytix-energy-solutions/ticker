/**
 * Ticker Admin Panel - Recipients Handlers
 * Event handlers for device (recipient) management, extracted from
 * recipients-tab.js to keep files under 500 lines.
 *
 * All handlers receive a panel reference as their first argument,
 * called via onclick strings in the rendered HTML.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};
window.Ticker.AdminRecipientsTab = window.Ticker.AdminRecipientsTab || {};

window.Ticker.AdminRecipientsTab.handlers = {
  toggleExpanded(panel, recipientId) {
    const r = panel._recipients.find(x => x.recipient_id === recipientId);
    if (r && !r.enabled) return;

    if (panel._expandedRecipients.has(recipientId)) {
      panel._expandedRecipients.delete(recipientId);
    } else {
      panel._expandedRecipients.add(recipientId);
    }
    panel._renderTabContentPreserveScroll();
  },

  async toggleEnabled(panel, recipientId, currentEnabled) {
    try {
      await panel._hass.callWS({
        type: 'ticker/update_recipient',
        recipient_id: recipientId,
        enabled: !currentEnabled,
      });
      if (currentEnabled) {
        panel._expandedRecipients.delete(recipientId);
      }
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    } catch (err) {
      panel._showError(err.message);
    }
  },

  /**
   * Set recipient subscription mode. Supports always/never/conditional.
   * When switching to conditional, creates default time rule and expands.
   * When switching away from conditional, clears conditions.
   */
  async setRecipientSubscription(panel, recipientId, categoryId, mode, conditions) {
    try {
      const params = {
        type: 'ticker/set_recipient_subscription',
        recipient_id: recipientId,
        category_id: categoryId,
        mode: mode,
      };
      if (mode === 'conditional' && conditions) {
        params.conditions = conditions;
      }
      await panel._hass.callWS(params);
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    } catch (err) {
      panel._showError(err.message);
    }
  },

  /**
   * Handle mode dropdown change for a recipient/category subscription.
   */
  async handleModeChange(panel, recipientId, categoryId, newMode) {
    if (newMode === 'conditional') {
      // Default to a time rule (zone is hidden for recipients)
      const conditions = {
        deliver_when_met: true,
        queue_until_met: true,
        rules: [{
          type: 'time',
          after: '08:00',
          before: '22:00',
          days: [1, 2, 3, 4, 5, 6, 7],
        }],
      };
      await this.setRecipientSubscription(panel, recipientId, categoryId, newMode, conditions);
    } else {
      await this.setRecipientSubscription(panel, recipientId, categoryId, newMode, null);
    }
  },

  /**
   * Handle rules-changed event from the conditions UI for a recipient subscription.
   */
  async handleRecipientRulesChanged(panel, recipientId, categoryId, detail) {
    const { rules, deliver_when_met, queue_until_met } = detail;

    if (!rules || rules.length === 0) {
      // No rules left: fall back to always
      await this.setRecipientSubscription(panel, recipientId, categoryId, 'always', null);
      return;
    }

    // Filter incomplete rules for backend
    const validRules = rules.filter(rule => {
      if (rule.type === 'state') return rule.entity_id && rule.state;
      if (rule.type === 'zone') return !!rule.zone_id;
      if (rule.type === 'time') return rule.after && rule.before;
      return true;
    });

    // Update local state immediately
    const r = panel._recipients.find(x => x.recipient_id === recipientId);
    if (r && r.subscriptions && r.subscriptions[categoryId]) {
      r.subscriptions[categoryId] = {
        mode: 'conditional',
        conditions: { deliver_when_met, queue_until_met, rules },
      };
    }

    // Skip backend if no complete rules
    if (validRules.length === 0) return;

    try {
      await panel._hass.callWS({
        type: 'ticker/set_recipient_subscription',
        recipient_id: recipientId,
        category_id: categoryId,
        mode: 'conditional',
        conditions: {
          deliver_when_met,
          queue_until_met,
          rules: validRules,
        },
      });
    } catch (err) {
      panel._showError(err.message || 'Failed to save conditions');
    }
  },

  async sendTest(panel, recipientId) {
    try {
      const result = await panel._hass.callWS({
        type: 'ticker/test_recipient',
        recipient_id: recipientId,
      });
      const testResults = result?.results || [];
      const ok = testResults.filter(x => x.success).length;
      const fail = testResults.filter(x => !x.success).length;

      if (!fail) {
        panel._showSuccess(`Test sent via ${ok} service(s)`);
      } else if (ok) {
        panel._showSuccess(`${ok} ok, ${fail} failed`);
      } else {
        panel._showError('All test notifications failed');
      }
    } catch (err) {
      panel._showError(err.message);
    }
  },

  async openCreateDialog(panel) {
    await Promise.all([
      panel._loadAvailableNotifyServices(),
      panel._loadTtsOptions(),
    ]);
    const overlay = window.Ticker.AdminRecipientsTab._renderDialog(panel, null);
    const container = document.createElement('div');
    container.id = 'ticker-dialog-container';
    container.innerHTML = overlay;
    panel.shadowRoot.appendChild(container);

    // Initialize conditions UI with empty state
    const conditionsEl = container.querySelector('#dlg-device-conditions');
    if (conditionsEl) {
      conditionsEl.zones = [];
      conditionsEl.entities = panel._hass
        ? Object.keys(panel._hass.states).map(id => ({ entity_id: id }))
        : [];
    }
  },

  async openEditDialog(panel, recipientId) {
    const r = panel._recipients.find(x => x.recipient_id === recipientId);
    if (!r) return;
    await Promise.all([
      panel._loadAvailableNotifyServices(recipientId),
      panel._loadTtsOptions(),
    ]);
    const overlay = window.Ticker.AdminRecipientsTab._renderDialog(panel, r);
    const container = document.createElement('div');
    container.id = 'ticker-dialog-container';
    container.innerHTML = overlay;
    panel.shadowRoot.appendChild(container);

    // Initialize conditions UI with existing device conditions
    const conditionsEl = container.querySelector('#dlg-device-conditions');
    if (conditionsEl) {
      if (r.conditions) {
        conditionsEl.deliverWhenMet = r.conditions.deliver_when_met ?? true;
        conditionsEl.queueUntilMet = false;
        conditionsEl.rules = r.conditions.rules || [];
      }
      conditionsEl.zones = [];
      conditionsEl.entities = panel._hass
        ? Object.keys(panel._hass.states).map(id => ({ entity_id: id }))
        : [];
    }
  },

  closeDialog(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (container) container.remove();
  },

  onServiceSelectionChange(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;

    const checkboxes = container.querySelectorAll('#dlg-service-list input[type="checkbox"]:checked');
    const formats = new Set();
    checkboxes.forEach(cb => formats.add(cb.dataset.format));

    const notice = container.querySelector('#dlg-format-notice');
    if (formats.size > 1 && notice) {
      notice.style.display = 'block';
      notice.textContent = 'Multiple formats detected - please confirm the delivery format below.';
    } else if (notice) {
      notice.style.display = 'none';
    }

    // Auto-set format from first checked service (only push-valid formats)
    const validFormats = ['rich', 'plain'];
    if (formats.size === 1 && validFormats.includes([...formats][0])) {
      const formatSelect = container.querySelector('#dlg-recipient-format');
      if (formatSelect) {
        formatSelect.value = [...formats][0];
      }
    }
  },

  async saveDialog(panel, isEdit) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;

    // BUG-062: Clear any previous dialog error before re-validating
    window.Ticker.AdminRecipientsDialog.clearDialogError(panel);

    const name = container.querySelector('#dlg-recipient-name')?.value?.trim();
    const icon = container.querySelector('#dlg-recipient-icon')?.value?.trim() || 'mdi:bell-ring';
    const deviceTypeRadio = container.querySelector('input[name="dlg-device-type"]:checked');
    const deviceType = deviceTypeRadio ? deviceTypeRadio.value : 'push';

    // BUG-051: Auto-derive ID from name on create; use stored ID on edit
    let recipientId;
    if (isEdit) {
      recipientId = container.querySelector('#dlg-recipient-id')?.value?.trim();
    } else {
      recipientId = name ? window.Ticker.utils.generateCategoryId(name) : '';
    }

    if (!recipientId || !name) {
      window.Ticker.AdminRecipientsDialog.showDialogError(panel, 'Name is required');
      return;
    }

    // Build WS payload based on device type
    const wsMsg = {
      type: isEdit ? 'ticker/update_recipient' : 'ticker/create_recipient',
      recipient_id: recipientId,
      name: name,
      icon: icon,
      device_type: deviceType,
    };

    if (deviceType === 'push') {
      const checkboxes = container.querySelectorAll('#dlg-service-list input[type="checkbox"]:checked');
      const notifyServices = [];
      checkboxes.forEach(cb => {
        notifyServices.push({ service: cb.value, name: cb.dataset.name || cb.value });
      });
      if (!notifyServices.length) {
        window.Ticker.AdminRecipientsDialog.showDialogError(panel, 'At least one notify service is required for Push devices');
        return;
      }
      wsMsg.notify_services = notifyServices;
      wsMsg.delivery_format = container.querySelector('#dlg-recipient-format')?.value || 'rich';
    } else {
      // TTS device
      const mediaPlayer = container.querySelector('#dlg-media-player')?.value?.trim();
      if (!mediaPlayer) {
        window.Ticker.AdminRecipientsDialog.showDialogError(panel, 'Media Player Entity ID is required for TTS devices');
        return;
      }
      wsMsg.media_player_entity_id = mediaPlayer;
      wsMsg.tts_service = container.querySelector('#dlg-tts-service')?.value?.trim() || 'tts.google_translate_say';
      wsMsg.resume_after_tts = !!container.querySelector('#dlg-resume-tts')?.checked;
      wsMsg.tts_buffer_delay = parseFloat(container.querySelector('#dlg-tts-buffer-delay')?.value) || 0;
    }

    // Read device-level conditions from the conditions UI component
    const conditionsEl = container.querySelector('#dlg-device-conditions');
    if (conditionsEl) {
      const rules = conditionsEl.rules || [];
      const deliverWhenMet = conditionsEl.deliverWhenMet ?? true;
      if (rules.length > 0) {
        const validRules = rules.filter(r => {
          if (r.type === 'state') return r.entity_id && r.state;
          if (r.type === 'time') return r.after && r.before;
          return false;
        });
        if (validRules.length > 0) {
          wsMsg.conditions = {
            deliver_when_met: deliverWhenMet,
            rules: validRules,
          };
        } else {
          wsMsg.conditions = null;
        }
      } else {
        wsMsg.conditions = null;
      }
    }

    try {
      await panel._hass.callWS(wsMsg);
      panel._showSuccess(isEdit ? 'Device updated' : 'Device created');
      this.closeDialog(panel);
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    } catch (err) {
      window.Ticker.AdminRecipientsDialog.showDialogError(panel, err.message);
    }
  },

  async confirmDelete(panel, recipientId) {
    const r = panel._recipients.find(x => x.recipient_id === recipientId);
    const recipientName = r ? r.name : recipientId;
    if (!confirm(`Delete device "${recipientName}"? This will also remove all its subscriptions.`)) {
      return;
    }

    try {
      await panel._hass.callWS({
        type: 'ticker/delete_recipient',
        recipient_id: recipientId,
      });
      panel._expandedRecipients.delete(recipientId);
      panel._showSuccess('Device deleted');
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    } catch (err) {
      panel._showError(err.message);
    }
  },
};
