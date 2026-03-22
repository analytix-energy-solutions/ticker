/**
 * Ticker Conditions UI Styles
 * Extracted from ticker-conditions-ui.js to keep files under 500 lines.
 *
 * Brand: See branding/README.md
 * Colors: --ticker-500: #06b6d4, --ticker-400: #22d3ee, --ticker-700: #0e7490
 */
window.Ticker = window.Ticker || {};

window.Ticker.conditionsStyles = `
  <style>
    :host {
      display: block;
      --ticker-500: #06b6d4;
      --ticker-400: #22d3ee;
      --ticker-700: #0e7490;
      --text-primary: var(--primary-text-color, #212121);
      --text-secondary: var(--secondary-text-color, #727272);
      --bg-card: var(--card-background-color, #fff);
      --bg-primary: var(--primary-background-color, #fafafa);
      --divider: var(--divider-color, #e0e0e0);
    }

    .rules-container {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .rule-item {
      background: rgba(6, 182, 212, 0.08);
      border-radius: 4px;
      overflow: hidden;
    }

    .rule-item.expanded {
      border-left: 3px solid var(--ticker-500);
    }

    .rule-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px 12px;
      cursor: pointer;
    }

    .rule-header-left {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .chevron {
      color: var(--text-secondary);
      transition: transform 0.2s ease;
      font-size: 12px;
    }

    .chevron.expanded {
      transform: rotate(90deg);
    }

    .rule-type-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;
      background: rgba(6, 182, 212, 0.2);
      color: var(--ticker-700);
    }

    .rule-summary {
      font-size: 13px;
      color: var(--text-primary);
    }

    .rule-delete {
      background: none;
      border: none;
      color: var(--text-secondary);
      cursor: pointer;
      padding: 4px 8px;
      font-size: 16px;
      line-height: 1;
      border-radius: 4px;
      transition: all 0.2s ease;
    }

    .rule-delete:hover {
      color: var(--ticker-danger,#ef4444);
      background: rgba(239, 68, 68, 0.1);
    }

    .rule-content {
      padding: 0 12px 12px 12px;
    }

    .form-group {
      margin-bottom: 12px;
    }

    .form-label {
      display: block;
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    .form-select, .form-input {
      width: 100%;
      padding: 8px 10px;
      border: 1px solid var(--divider);
      border-radius: 4px;
      font-size: 13px;
      background: var(--bg-card);
      color: var(--text-primary);
      box-sizing: border-box;
    }

    .form-select:focus, .form-input:focus {
      outline: none;
      border-color: var(--ticker-500);
    }

    .form-row {
      display: flex;
      gap: 12px;
      align-items: flex-end;
    }

    .form-row .form-group {
      flex: 1;
    }

    .time-inputs {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .time-input {
      width: 80px;
      padding: 8px 10px;
      border: 1px solid var(--divider);
      border-radius: 4px;
      font-size: 13px;
      background: var(--bg-card);
      color: var(--text-primary);
    }

    .time-separator {
      color: var(--text-secondary);
      font-size: 13px;
    }

    .days-selector {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }

    .day-btn {
      width: 36px;
      height: 28px;
      border: 1px solid var(--divider);
      border-radius: 4px;
      background: var(--bg-card);
      color: var(--text-primary);
      font-size: 11px;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .day-btn.selected {
      background: var(--ticker-500);
      border-color: var(--ticker-500);
      color: white;
    }

    .day-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .actions-section {
      display: flex;
      gap: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--divider);
    }

    .ruleset-actions {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding: 12px;
      background: rgba(6, 182, 212, 0.08);
      border-radius: 4px;
      border: 1px solid rgba(6, 182, 212, 0.2);
    }

    .action-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: var(--text-primary);
      cursor: pointer;
    }

    .action-toggle input[type="checkbox"] {
      width: 16px;
      height: 16px;
      accent-color: var(--ticker-500);
      cursor: pointer;
    }

    .add-rule-section {
      display: flex;
      gap: 8px;
      margin-top: 8px;
    }

    .add-rule-btn {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 12px;
      border: 1px dashed var(--ticker-500);
      border-radius: 4px;
      background: transparent;
      color: var(--ticker-500);
      cursor: pointer;
      font-size: 12px;
      transition: background 0.2s ease;
    }

    .add-rule-btn:hover:not(:disabled) {
      background: rgba(6, 182, 212, 0.08);
    }

    .add-rule-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    .and-indicator {
      display: flex;
      justify-content: center;
      padding: 4px 0;
    }

    .and-badge {
      background: var(--bg-primary);
      padding: 2px 12px;
      border-radius: 12px;
      border: 1px solid var(--divider);
      font-size: 11px;
      font-weight: 500;
      color: var(--text-secondary);
    }

    .empty-state {
      text-align: center;
      padding: 20px;
      color: var(--text-secondary);
      font-size: 13px;
    }

    .info-text {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 8px;
      padding: 8px;
      background: var(--bg-primary);
      border-radius: 4px;
    }
  </style>
`;
