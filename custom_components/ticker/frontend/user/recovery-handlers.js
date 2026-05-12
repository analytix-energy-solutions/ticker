/**
 * Ticker User Panel - Recovery Handlers
 * FIX-029F: Visibility/resume/reconnect recovery logic.
 * Extracted from ticker-panel.js to keep orchestrator under 500 lines.
 *
 * Provides setupRecoveryHandlers() and forceRepaint() as static helpers
 * that operate on a panel instance.
 */
window.Ticker = window.Ticker || {};

window.Ticker.UserRecoveryHandlers = {
  /**
   * FIX-029F: Set up recovery handlers for tab focus loss / WS reconnect.
   * Three independent mechanisms:
   * 1. connection 'ready' -- HA WebSocket reconnect -> reload data
   * 2. visibilitychange -- browser tab becomes visible -> force repaint + reload if stale
   * 3. resume (Page Lifecycle API) -- Chrome unfreeze -> force repaint + reload
   * @param {TickerPanel} panel - The panel instance
   */
  setup(panel) {
    // 1. HA WebSocket reconnection
    if (panel._connectionReadyHandler && panel._hass?.connection) {
      panel._hass.connection.removeEventListener('ready', panel._connectionReadyHandler);
    }
    panel._connectionReadyHandler = () => {
      if (!panel.isConnected) return;
      console.log('[Ticker] Connection ready -- refreshing data');
      panel._loadData();
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
          console.log(`[Ticker] Visible after ${Math.round(hiddenMs / 1000)}s -- repaint + refresh`);
          window.Ticker.UserRecoveryHandlers.forceRepaint(panel);
          panel._loadData();
        } else {
          window.Ticker.UserRecoveryHandlers.forceRepaint(panel);
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
        console.log('[Ticker] Resume from freeze -- repaint + refresh');
        window.Ticker.UserRecoveryHandlers.forceRepaint(panel);
        panel._loadData();
      };
      document.addEventListener('resume', panel._resumeHandler);
    }
  },

  /**
   * FIX-029F: Force shadow host compositor layer re-creation.
   * Toggle display on the HOST element to force Chromium to re-rasterize
   * the shadow root paint layer after a tab freeze/discard cycle.
   * @param {TickerPanel} panel - The panel instance
   */
  forceRepaint(panel) {
    panel.style.display = 'none';
    void panel.offsetHeight;
    panel.style.display = '';
    void panel.offsetHeight;
  },

  /**
   * BUG-107: Render a terminal-state card (no-person / error) with a
   * "Return to Dashboard" escape button. Caller is responsible for
   * focusing `.terminal-card-btn` after the DOM is in place.
   * @param {string} title - Card heading (escaped).
   * @param {string} message - Card body text (escaped).
   * @param {string} stateClass - Existing CSS class: 'no-person-state' or 'error-state'.
   * @returns {string} innerHTML for the card.
   */
  renderTerminalCard(title, message, stateClass) {
    const esc = window.Ticker.utils.esc;
    return `
      <div class="card">
        <div class="${stateClass}">
          <h3>${esc(title)}</h3>
          <p>${esc(message)}</p>
          <div style="margin-top: 16px;">
            <button class="btn btn-primary terminal-card-btn"
              onclick="window.Ticker._userPanel._returnToDashboard()">Return to Dashboard</button>
          </div>
        </div>
      </div>
    `;
  },

  /**
   * BUG-107: Escape the user panel via `history.replaceState` so the iOS
   * Companion App cached route no longer points at `/ticker`. Fires the
   * HA `location-changed` event so `ha-router` resolves the new path.
   * `replaceState` (not `pushState`) is required per SPEC_BUG-107 §4.1.
   */
  returnToDashboard() {
    window.history.replaceState(null, '', '/');
    window.dispatchEvent(new CustomEvent('location-changed', {
      detail: { replace: true },
      bubbles: true,
      composed: true,
    }));
  },
};
