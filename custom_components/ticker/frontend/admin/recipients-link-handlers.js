/**
 * Ticker Admin Panel - Recipients User-Link Handlers
 *
 * F-39 chunk 3: split out from recipients-handlers.js to keep that file
 * under the 500-line cap. Extends window.Ticker.AdminRecipientsTab.handlers
 * with the two handlers driven by the link-mode dropdown and user picker
 * in the devices-tab foldout.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};
window.Ticker.AdminRecipientsTab = window.Ticker.AdminRecipientsTab || {};
window.Ticker.AdminRecipientsTab.handlers =
  window.Ticker.AdminRecipientsTab.handlers || {};

Object.assign(window.Ticker.AdminRecipientsTab.handlers, {
  /**
   * Switch a recipient between Standalone and Linked-to-user.
   *
   * - Standalone: clears any pending-link state and fires the WS unlink.
   * - Linked: when already linked, just re-renders (no-op). When not
   *   yet linked, records the recipient in the panel-level
   *   `_pendingLinkRecipients` Set so the user picker renders without
   *   mutating recipient data. The actual link WS call fires when the
   *   admin picks a user (see `handleUserPickerChange`).
   *
   * @param {Object} panel - Admin panel instance
   * @param {string} recipientId
   * @param {string} newMode - 'standalone' | 'linked'
   */
  async handleLinkModeChange(panel, recipientId, newMode) {
    if (newMode === 'standalone') {
      // Clear any pending-link state for this recipient first.
      if (panel._pendingLinkRecipients) {
        panel._pendingLinkRecipients.delete(recipientId);
      }
      try {
        await panel._hass.callWS({
          type: 'ticker/set_recipient_user_link',
          recipient_id: recipientId,
          person_id: null,
        });
        await panel._loadRecipients();
        panel._renderTabContentPreserveScroll();
      } catch (err) {
        panel._showError(err.message || 'Failed to unlink device');
        // Reload to revert optimistic dropdown state.
        await panel._loadRecipients();
        panel._renderTabContentPreserveScroll();
      }
      return;
    }
    // newMode === 'linked'
    const r = panel._recipients.find(x => x.recipient_id === recipientId);
    if (r && r.user_link) {
      // Already linked — nothing to do, just re-render defensively.
      panel._renderTabContentPreserveScroll();
      return;
    }
    // Track the recipient in the panel-level pending-link Set so the
    // user picker renders. Recipient data is NOT mutated — the backend
    // is only touched when a user is selected (handleUserPickerChange).
    panel._pendingLinkRecipients = panel._pendingLinkRecipients || new Set();
    panel._pendingLinkRecipients.add(recipientId);
    panel._renderTabContentPreserveScroll();
  },

  /**
   * User picker change — set or clear the user_link.
   * Empty value reverts to Standalone (sends person_id=null).
   *
   * @param {Object} panel - Admin panel instance
   * @param {string} recipientId
   * @param {string} personId - person entity ID, or '' to clear
   */
  async handleUserPickerChange(panel, recipientId, personId) {
    const payload = {
      type: 'ticker/set_recipient_user_link',
      recipient_id: recipientId,
      person_id: personId ? personId : null,
    };
    try {
      await panel._hass.callWS(payload);
      // Backend now owns the link state; drop the pending marker so
      // subsequent renders read isLinked from r.user_link.
      if (panel._pendingLinkRecipients) {
        panel._pendingLinkRecipients.delete(recipientId);
      }
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    } catch (err) {
      panel._showError(err.message || 'Failed to set user link');
      await panel._loadRecipients();
      panel._renderTabContentPreserveScroll();
    }
  },
});
