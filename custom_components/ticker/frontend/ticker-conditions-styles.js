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
      --ticker-500-alpha-8: rgba(6,182,212,0.08);
      --ticker-500-alpha-20: rgba(6,182,212,0.2);
      --ticker-500-alpha-40: rgba(6,182,212,0.4);
      /* F-33 NOT operator — amber palette from branding/README.md Warning Banners */
      --ticker-negate-color: #92400e;             /* amber-800: NOT pill fill, group dashed border */
      --ticker-negate-bg: rgba(146,64,14,0.06);   /* amber-800 @ 6%: negated group header tint */
      --ticker-negate-color-hover: #7c2d12;       /* amber-900: NOT pill hover fill when active */
      --text-primary: var(--primary-text-color, #212121);
      --text-secondary: var(--secondary-text-color, #727272);
      --bg-card: var(--card-background-color, #fff);
      --bg-primary: var(--primary-background-color, #fafafa);
      --divider: var(--divider-color, #e0e0e0);
    }

    .rules-container {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .rule-item {
      background: var(--ticker-500-alpha-8);
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
      background: var(--ticker-500-alpha-20);
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

    .ruleset-actions {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
      margin-top: 16px;
      padding: 12px;
      background: var(--ticker-500-alpha-8);
      border-radius: 4px;
      border: 1px solid var(--ticker-500-alpha-20);
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
      background: var(--ticker-500-alpha-8);
    }

    .add-rule-btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }

    /* Operator row between conditions (AND/OR pill + group button) */
    .operator-row {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 6px;
      padding: 2px 0;
    }

    .operator-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 10px;
      border-radius: 12px;
      border: 1px solid var(--divider);
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      background: var(--bg-primary);
      color: var(--text-secondary);
      user-select: none;
      transition: background 0.15s, color 0.15s, border-color 0.15s;
    }

    .operator-pill.or {
      background: var(--ticker-500-alpha-20);
      color: var(--ticker-700);
      border-color: var(--ticker-500-alpha-40);
    }

    .operator-pill:hover {
      background: var(--ticker-500-alpha-8);
      border-color: var(--ticker-500);
    }

    .group-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      cursor: pointer;
      border-radius: 4px;
      font-size: 10px;
      transition: color 0.15s, background 0.15s;
    }

    .group-btn:hover {
      color: var(--ticker-500);
      background: var(--ticker-500-alpha-8);
    }

    .group-btn[disabled] {
      opacity: 0.3;
      cursor: not-allowed;
    }

    /* Group card (sub-group container) */
    .group-card {
      border-left: 3px solid var(--ticker-500);
      border-radius: 4px;
      background: var(--bg-primary);
      overflow: hidden;
    }

    .group-header {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      background: var(--ticker-500-alpha-8);
      cursor: default;
    }

    .group-label {
      font-size: 11px;
      font-weight: 500;
      color: var(--text-secondary);
    }

    .group-body {
      padding: 8px 8px 8px 12px;
    }

    /* F-33 NOT operator — group negation: dashed amber border + amber-tinted header */
    .group-card.negated {
      border-left: 3px dashed var(--ticker-negate-color);
    }

    .group-card.negated .group-header {
      background: var(--ticker-negate-bg);
    }

    /* F-33 NOT operator — inline NOT pill (shared by leaf and group nodes) */
    .negate-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 1px 6px;
      border-radius: 10px;
      border: 1px solid var(--text-secondary);
      background: transparent;
      color: var(--text-secondary);
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.3px;
      cursor: pointer;
      opacity: 0.5;
      user-select: none;
      transition: background 0.15s, color 0.15s, opacity 0.15s, border-color 0.15s;
    }

    .negate-pill:hover {
      opacity: 0.9;
      border-color: var(--ticker-negate-color);
      color: var(--ticker-negate-color);
    }

    .negate-pill:focus-visible {
      outline: 2px solid var(--ticker-negate-color);
      outline-offset: 2px;
      opacity: 1;
    }

    .negate-pill.active {
      background: var(--ticker-negate-color);
      border-color: var(--ticker-negate-color);
      color: #ffffff;
      opacity: 1;
    }

    .negate-pill.active:hover {
      background: var(--ticker-negate-color-hover);
      border-color: var(--ticker-negate-color-hover);
    }

    .negate-pill[disabled] {
      cursor: not-allowed;
      opacity: 0.35;
    }

    /* Reinforce a negated leaf with amber summary text */
    .rule-item.negated .rule-summary {
      color: var(--ticker-negate-color);
      font-weight: 500;
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
