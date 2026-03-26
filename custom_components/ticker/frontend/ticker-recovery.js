/**
 * Ticker Recovery Utilities
 * Extracted from ticker-admin-panel.js to stay under 500-line limit.
 *
 * Provides recovery handlers for tab focus loss, WS reconnection,
 * and browser visibility changes (FIX-029F).
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.Recovery = {
  /**
   * Set up recovery handlers for tab focus loss / WS reconnect.
   * Must be called with the panel element as context.
   * @param {HTMLElement} panel - The panel element (admin or user)
   */
  setupRecoveryHandlers(panel) {
    // 1. HA WebSocket reconnection
    if (panel._connectionReadyHandler && panel._hass?.connection) {
      panel._hass.connection.removeEventListener('ready', panel._connectionReadyHandler);
    }
    panel._connectionReadyHandler = () => {
      if (!panel.isConnected) return;
      console.log('[Ticker] Connection ready - refreshing data');
      panel._loadData().then(() => panel._renderTabContent());
    };
    panel._hass.connection.addEventListener('ready', panel._connectionReadyHandler);

    // 2. Browser visibility change
    if (!panel._visibilityHandler) {
      panel._lastHiddenAt = null;
      panel._visibilityHandler = () => {
        if (document.hidden) {
          panel._lastHiddenAt = Date.now();
          return;
        }
        if (!panel.isConnected) {
          panel._needsRecovery = true;
          return;
        }
        const hiddenMs = panel._lastHiddenAt ? Date.now() - panel._lastHiddenAt : 0;
        panel._lastHiddenAt = null;
        if (hiddenMs > 30000) {
          console.log(`[Ticker] Visible after ${Math.round(hiddenMs / 1000)}s - repaint + refresh`);
          window.Ticker.Recovery.forceRepaint(panel);
          panel._loadData().then(() => panel._renderTabContent());
        } else {
          window.Ticker.Recovery.forceRepaint(panel);
        }
      };
      document.addEventListener('visibilitychange', panel._visibilityHandler);
    }

    // 3. Chrome Page Lifecycle resume
    if (!panel._resumeHandler) {
      panel._resumeHandler = () => {
        if (!panel.isConnected) {
          panel._needsRecovery = true;
          return;
        }
        console.log('[Ticker] Resume from freeze - repaint + refresh');
        window.Ticker.Recovery.forceRepaint(panel);
        panel._loadData().then(() => panel._renderTabContent());
      };
      document.addEventListener('resume', panel._resumeHandler);
    }
  },

  /**
   * Force shadow host compositor layer re-creation.
   * @param {HTMLElement} panel - The panel element
   */
  forceRepaint(panel) {
    panel.style.display = 'none';
    void panel.offsetHeight;
    panel.style.display = '';
    void panel.offsetHeight;
  },
};
