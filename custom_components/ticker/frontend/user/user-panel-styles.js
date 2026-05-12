/**
 * Ticker User Panel - Panel-specific Styles
 * Extracted from ticker-panel.js to keep orchestrator under 500 lines.
 *
 * Brand: See branding/README.md
 * Colors via CSS variables from ticker-styles.js
 */
window.Ticker = window.Ticker || {};

window.Ticker.userPanelStyles = `
  /* User profile */
  .user-info {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: var(--bg-primary);
    border-radius: 4px;
    margin-bottom: 16px;
  }
  .user-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--ticker-500);
    display: flex;
    align-items: center;
    justify-content: center;
    color: white;
    font-weight: 600;
    font-size: 16px;
  }
  .user-details { flex: 1; }
  .user-name { font-weight: 500; color: var(--text-primary); }

  /* Subscriptions list */
  .subscriptions-list { display: flex; flex-direction: column; gap: 8px; }
  .subscription-item { background: var(--bg-primary); border-radius: 4px; overflow: hidden; }
  .subscription-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    cursor: pointer;
  }
  .subscription-header.expanded {
    border-left: 3px solid var(--ticker-500);
    background: var(--ticker-500-alpha-8);
  }
  .subscription-label {
    font-size: 14px;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .subscription-controls { display: flex; align-items: center; gap: 8px; }
  .subscription-select {
    padding: 6px 10px;
    border: 1px solid var(--divider);
    border-radius: 4px;
    font-size: 13px;
    background: var(--bg-card);
    color: var(--text-primary);
    min-width: 120px;
    cursor: pointer;
  }
  .subscription-select:focus { outline: none; border-color: var(--ticker-500); }
  .conditional-content {
    padding: 0 16px 16px 16px;
    border-left: 3px solid var(--ticker-500);
    background: var(--ticker-500-alpha-4);
  }
  .conditions-section { margin-top: 8px; padding-top: 8px; }

  /* Device preferences */
  .device-section {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid var(--divider);
  }
  .device-section-title {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 12px;
  }
  .radio-group { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
  .radio-option {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--text-primary);
    cursor: pointer;
  }
  .radio-option input[type="radio"] {
    width: 16px;
    height: 16px;
    accent-color: var(--ticker-500);
    cursor: pointer;
  }
  .device-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-left: 24px;
    margin-bottom: 12px;
  }
  .device-checkbox {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-primary);
    cursor: pointer;
  }
  .device-checkbox input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--ticker-500);
    cursor: pointer;
  }
  .device-checkbox.disabled { color: var(--text-secondary); cursor: not-allowed; }
  .device-actions { display: flex; gap: 8px; margin-top: 8px; }
  .device-override-section {
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--divider);
  }
  .device-override-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-primary);
    cursor: pointer;
    margin-bottom: 8px;
  }
  .device-override-toggle input[type="checkbox"] {
    width: 16px;
    height: 16px;
    accent-color: var(--ticker-500);
    cursor: pointer;
  }
  .device-override-list { display: flex; flex-direction: column; gap: 6px; padding-left: 24px; }
  .device-override-help {
    font-size: 12px;
    color: var(--text-secondary);
    margin-bottom: 8px;
    padding-left: 24px;
  }

  /* History styles */
  .history-list { display: flex; flex-direction: column; gap: 16px; }
  .history-date-group { display: flex; flex-direction: column; gap: 8px; }
  .history-date-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--divider);
  }
  .history-item { padding: 12px 16px; background: var(--bg-primary); border-radius: 4px; }
  .history-item-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 4px;
  }
  .history-item-title { font-weight: 500; color: var(--text-primary); }
  .history-item-time {
    font-size: 12px;
    color: var(--text-secondary);
    white-space: nowrap;
    margin-left: 12px;
  }
  .history-item-message {
    font-size: 14px;
    color: var(--text-primary);
    line-height: 1.5;
    margin-bottom: 8px;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .history-item-image { margin: 8px 0; max-width: 100%; }
  .history-item-image img {
    max-width: 280px;
    max-height: 200px;
    border-radius: 4px;
    object-fit: cover;
    cursor: pointer;
    transition: opacity 150ms ease;
  }
  .history-item-image img:hover { opacity: 0.85; }
  .history-item-image ha-icon {
    color: var(--text-secondary);
    --mdc-icon-size: 24px;
  }
  .history-item-meta { display: flex; gap: 8px; flex-wrap: wrap; }

  /* No person state */
  .no-person-state { text-align: center; padding: 40px; }
  .no-person-state h3 { color: var(--text-primary); margin: 0 0 8px 0; }
  .no-person-state p { color: var(--text-secondary); margin: 0; }

  /* BUG-107: Terminal-card escape button focus ring (keyboard / screen reader) */
  .terminal-card-btn:focus-visible {
    outline: 2px solid var(--ticker-400);
    outline-offset: 2px;
  }
`;
