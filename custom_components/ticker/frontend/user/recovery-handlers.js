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

  /**
   * F-26 + BUG-040: Update a history filter field and re-render the history
   * tab without losing scroll position. Captures the currently focused input
   * (id + selection range) before re-render and restores it afterwards so
   * the search box keeps focus across keystrokes. Extracted from
   * ticker-panel.js for F-38 to keep that file under the 500-line cap.
   * @param {TickerPanel} panel - The panel instance.
   * @param {string} field - One of historySearch, historyCategory, historyDateFrom, historyDateTo.
   * @param {string} value - New value.
   */
  /**
   * FIX-002 (F-38): Show a transient message in the panel's #message-area.
   * Extracted from ticker-panel.js's _showError/_showSuccess to keep that
   * file under the 500-line cap. Success messages auto-hide after 3s,
   * errors after 10s — matches the original behavior exactly.
   * @param {TickerPanel} panel - The panel instance.
   * @param {string} text - Message text (already user-facing).
   * @param {'error'|'success'} kind - Message kind.
   */
  setMessage(panel, text, kind) {
    if (!panel._els || !panel._els.messageArea) return;
    const area = panel._els.messageArea;
    area.textContent = text;
    area.className = `message ${kind}-message`;
    area.style.display = 'block';
    const timeout = kind === 'error' ? 10000 : 3000;
    setTimeout(() => { area.style.display = 'none'; }, timeout);
  },

  setHistoryFilter(panel, field, value) {
    const allowed = ['historySearch', 'historyCategory', 'historyDateFrom', 'historyDateTo'];
    if (!allowed.includes(field)) return;
    const key = '_' + field;
    panel[key] = value || '';

    // Save focus state from the shadow root's active element.
    const active = panel.shadowRoot?.activeElement;
    let focusInfo = null;
    if (active && active.id && active.id.startsWith('ticker-history-')) {
      focusInfo = { id: active.id };
      // Only text-like inputs expose selection range
      if (active.tagName === 'INPUT' && (active.type === 'search' || active.type === 'text')) {
        focusInfo.selStart = active.selectionStart;
        focusInfo.selEnd = active.selectionEnd;
      }
    }

    panel._renderTabContentPreserveScroll();

    if (focusInfo) {
      const restored = panel.shadowRoot?.getElementById(focusInfo.id);
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
  },
};
