/**
 * Ticker Shared Styles
 * Brand: See branding/README.md
 * Colors: --ticker-500: #06b6d4, --ticker-400: #22d3ee, --ticker-700: #0e7490
 */
window.Ticker = window.Ticker || {};

window.Ticker.styles = {
  /** CSS custom properties - include in every panel's :host */
  variables: `
    :host {
      --ticker-500: #06b6d4;
      --ticker-400: #22d3ee;
      --ticker-700: #0e7490;
      --text-primary: var(--primary-text-color, #212121);
      --text-secondary: var(--secondary-text-color, #727272);
      --bg-card: var(--card-background-color, #fff);
      --bg-primary: var(--primary-background-color, #fafafa);
      --divider: var(--divider-color, #e0e0e0);
    }
  `,

  /** Base layout, typography */
  base: `
    .container {
      font-family: system-ui, -apple-system, sans-serif;
      padding: 16px;
      max-width: 800px;
      margin: 0 auto;
    }
    .container-wide {
      font-family: system-ui, -apple-system, sans-serif;
      padding: 16px;
      max-width: 1200px;
      margin: 0 auto;
    }
  `,

  /** Header with logo */
  header: `
    .header {
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
    }
    .header h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
      color: var(--text-primary);
    }
    .header-logo {
      width: 40px;
      height: 40px;
    }
  `,

  /** Tabs navigation */
  tabs: `
    .tabs {
      display: flex;
      gap: 0;
      border-bottom: 1px solid var(--divider);
      margin-bottom: 24px;
      flex-wrap: wrap;
    }
    .tab {
      padding: 12px 24px;
      border: none;
      background: none;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      color: var(--text-secondary);
      border-bottom: 2px solid transparent;
      transition: all 0.2s ease;
    }
    .tab:hover {
      color: var(--ticker-500);
    }
    .tab.active {
      color: var(--ticker-500);
      border-bottom-color: var(--ticker-500);
    }
    .tab .badge-count {
      background: var(--ticker-500);
      color: white;
      padding: 2px 6px;
      border-radius: 10px;
      font-size: 11px;
      margin-left: 6px;
    }
  `,

  /** Cards */
  cards: `
    .card {
      background: var(--bg-card);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
      margin-bottom: 16px;
    }
    .card-title {
      font-size: 16px;
      font-weight: 600;
      margin: 0 0 16px 0;
      color: var(--text-primary);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }
    .card-header .card-title {
      margin: 0;
    }
    .card-description {
      color: var(--text-secondary);
      font-size: 14px;
      margin-bottom: 16px;
      line-height: 1.5;
    }
  `,

  /** Buttons */
  buttons: `
    .btn {
      padding: 8px 16px;
      border: none;
      border-radius: 4px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
    }
    .btn-primary {
      background: var(--ticker-500);
      color: white;
    }
    .btn-primary:hover {
      background: var(--ticker-700);
    }
    .btn-secondary {
      background: var(--bg-primary);
      color: var(--text-primary);
      border: 1px solid var(--divider);
    }
    .btn-secondary:hover {
      background: var(--divider);
    }
    .btn-danger {
      background: #ef4444;
      color: white;
    }
    .btn-danger:hover {
      background: #dc2626;
    }
    .btn-small {
      padding: 4px 8px;
      font-size: 12px;
    }
    .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
  `,

  /** Badges */
  badges: `
    .badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      font-weight: 500;
      background: var(--ticker-500);
      color: white;
    }
    .badge-success {
      background: #22c55e;
    }
    .badge-warning {
      background: #f59e0b;
    }
    .badge-danger {
      background: #ef4444;
    }
    .badge-disabled {
      background: #9ca3af;
    }
    .badge-outline {
      background: transparent;
      border: 1px solid var(--ticker-500);
      color: var(--ticker-500);
    }
  `,

  /** Messages (toast notifications) */
  messages: `
    .message {
      display: none;
      padding: 12px 16px;
      border-radius: 4px;
      margin-bottom: 16px;
    }
    .error-message {
      background: #fef2f2;
      border: 1px solid #fecaca;
      color: #dc2626;
    }
    .success-message {
      background: #f0fdf4;
      border: 1px solid #bbf7d0;
      color: #16a34a;
    }
  `,

  /** Loading and empty states */
  states: `
    .loading {
      text-align: center;
      padding: 40px;
      color: var(--text-secondary);
    }
    .loading-spinner {
      width: 32px;
      height: 32px;
      border: 3px solid var(--divider);
      border-top-color: var(--ticker-500);
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin: 0 auto 16px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    .empty-state {
      text-align: center;
      padding: 40px;
      color: var(--text-secondary);
    }
    .error-state {
      text-align: center;
      padding: 40px;
      color: #dc2626;
    }
  `,

  /** Toggle switches */
  toggles: `
    .toggle {
      position: relative;
      width: 44px;
      height: 24px;
      cursor: pointer;
      flex-shrink: 0;
    }
    .toggle input {
      opacity: 0;
      width: 0;
      height: 0;
    }
    .toggle-slider {
      position: absolute;
      inset: 0;
      background: #ccc;
      border-radius: 24px;
      transition: 0.3s;
    }
    .toggle-slider:before {
      position: absolute;
      content: "";
      height: 18px;
      width: 18px;
      left: 3px;
      bottom: 3px;
      background: #fff;
      border-radius: 50%;
      transition: 0.3s;
    }
    .toggle input:checked + .toggle-slider {
      background: var(--ticker-500);
    }
    .toggle input:checked + .toggle-slider:before {
      transform: translateX(20px);
    }
  `,

  /** Notify service tags */
  notifyServices: `
    .notify-services {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .notify-service-tag {
      padding: 2px 6px;
      background: rgba(6, 182, 212, 0.1);
      border-radius: 3px;
      font-size: 11px;
      color: var(--ticker-700);
    }
  `,

  /** Queue items */
  queueItems: `
    .queue-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .queue-item {
      padding: 12px 16px;
      background: var(--bg-primary);
      border-radius: 4px;
    }
    .queue-item-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 4px;
    }
    .queue-item-title {
      font-weight: 500;
      color: var(--text-primary);
    }
    .queue-item-message {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }
    .queue-item-meta {
      font-size: 11px;
      color: var(--text-secondary);
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }
  `,

  /** Warning banner (from branding/README.md) */
  warningBanner: `
    .warning-banner {
      background: #fef3c7;
      border: 1px solid #fcd34d;
      border-radius: 4px;
      padding: 10px 12px;
      margin-top: 8px;
      color: #92400e;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
  `,

  /** Forms */
  forms: `
    .form-row {
      display: flex;
      gap: 12px;
      align-items: flex-end;
      flex-wrap: wrap;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .form-group label {
      font-size: 12px;
      font-weight: 500;
      color: var(--text-secondary);
    }
    .form-input,
    .form-select {
      padding: 8px 12px;
      border: 1px solid var(--divider);
      border-radius: 4px;
      font-size: 14px;
      background: var(--bg-card);
      color: var(--text-primary);
    }
    .form-input:focus,
    .form-select:focus {
      outline: none;
      border-color: var(--ticker-500);
    }
  `,

  /** Expandable list items */
  listItems: `
    .list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .list-item {
      background: var(--bg-primary);
      border-radius: 4px;
      overflow: hidden;
    }
    .list-item.disabled {
      opacity: 0.6;
    }
    .list-item-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      cursor: pointer;
    }
    .list-item-header:hover {
      background: rgba(6, 182, 212, 0.05);
    }
    .list-item-header.expanded {
      border-left: 3px solid var(--ticker-500);
      background: rgba(6, 182, 212, 0.08);
    }
    .list-item-content {
      display: flex;
      flex-direction: column;
      gap: 2px;
      flex: 1;
    }
    .list-item-title {
      font-weight: 500;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .list-item-actions {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .list-item-accordion {
      padding: 0 16px 16px;
      border-top: 1px solid var(--divider);
      background: var(--bg-card);
    }
    .chevron {
      transition: transform 0.2s ease;
      color: var(--text-secondary);
    }
    .chevron.expanded {
      transform: rotate(90deg);
    }
    .expand-icon {
      width: 20px;
      height: 20px;
      color: var(--text-secondary);
      transition: transform 0.2s;
      flex-shrink: 0;
    }
    .expand-icon.open {
      transform: rotate(180deg);
    }
  `,

  /** Section titles */
  sections: `
    .section-title {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
  `,

  /** Category color indicator */
  colorIndicator: `
    .color-indicator {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 6px;
    }
  `,

  /** Accordion content */
  accordion: `
    .accordion-content {
      padding: 0 16px 16px;
      border-top: 1px solid var(--divider);
      background: var(--bg-card);
    }
    .button-row {
      display: flex;
      gap: 8px;
      margin-top: 16px;
    }
  `,

  /** List item subtitles */
  listItemExtras: `
    .list-item-subtitle {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 2px;
    }
    .badge-gray {
      background: #9ca3af;
    }
  `,

  /** Subscriptions (admin users tab) */
  subscriptions: `
    .subscription-header {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
      margin-top: 12px;
      margin-bottom: 4px;
    }
    .subscriptions-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 12px;
    }
    .subscription-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 12px;
      background: var(--bg-primary);
      border-radius: 4px;
    }
    .subscription-label {
      font-size: 14px;
      color: var(--text-primary);
    }
  `,

  /** Stats grid (admin logs tab) */
  statsGrid: `
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .stat-card {
      background: var(--bg-primary);
      border-radius: 6px;
      padding: 12px;
      text-align: center;
    }
    .stat-value {
      font-size: 24px;
      font-weight: 600;
      color: var(--ticker-500);
    }
    .stat-label {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 2px;
    }
    .stat-card.stat-sent .stat-value { color: #22c55e; }
    .stat-card.stat-queued .stat-value { color: #3b82f6; }
    .stat-card.stat-skipped .stat-value { color: #f59e0b; }
    .stat-card.stat-failed .stat-value { color: #ef4444; }
  `,

  /** Log items (admin logs tab) */
  logItems: `
    .log-item {
      padding: 10px 14px;
      background: var(--bg-primary);
      border-radius: 4px;
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .log-item-main {
      flex: 1;
    }
    .log-item-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }
    .log-item-title {
      font-weight: 500;
      color: var(--text-primary);
    }
    .log-item-message {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }
    .log-item-meta {
      font-size: 11px;
      color: var(--text-secondary);
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .log-reason {
      font-style: italic;
    }
    .log-item-time {
      font-size: 11px;
      color: var(--text-secondary);
      white-space: nowrap;
    }
  `,

  /** Queue items for admin panel (extended) */
  adminQueueItems: `
    .queue-item {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 10px 12px;
      background: var(--bg-primary);
      border-radius: 4px;
      margin-bottom: 8px;
    }
    .queue-item-content {
      flex: 1;
    }
    .queue-item-title {
      font-weight: 500;
      color: var(--text-primary);
    }
    .queue-item-message {
      font-size: 13px;
      color: var(--text-secondary);
      margin: 4px 0;
    }
    .queue-item-meta {
      font-size: 11px;
      color: var(--text-secondary);
    }
  `,

  /** Migrate wizard (admin migrate tab) */
  migrate: `
    .migrate-progress {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 12px;
    }
    .migrate-finding {
      background: var(--bg-primary);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
    }
    .migrate-finding.current {
      border: 2px solid var(--ticker-500);
    }
    .migrate-finding.adjacent {
      opacity: 0.7;
    }
    .finding-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--ticker-500);
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .finding-label.adjacent {
      color: var(--text-secondary);
    }
    .migrate-finding-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .migrate-finding-source {
      font-weight: 600;
      color: var(--text-primary);
    }
    .migrate-finding-type {
      font-size: 12px;
      color: var(--text-secondary);
    }
    .migrate-finding-data {
      background: var(--bg-card);
      border-radius: 4px;
      padding: 12px;
      margin-bottom: 12px;
    }
    .migrate-data-row {
      display: flex;
      margin-bottom: 6px;
      font-size: 13px;
    }
    .migrate-data-row:last-child {
      margin-bottom: 0;
    }
    .migrate-data-label {
      color: var(--text-secondary);
      width: 100px;
      flex-shrink: 0;
    }
    .migrate-data-value {
      color: var(--text-primary);
      word-break: break-word;
    }
    .migrate-data-value.mono {
      font-size: 11px;
      font-family: monospace;
    }
    .migrate-data-value.extra {
      font-size: 12px;
      white-space: pre-wrap;
    }
    .migrate-input {
      width: 100%;
      padding: 6px 10px;
      border: 1px solid var(--divider);
      border-radius: 4px;
      font-size: 13px;
      background: var(--bg-card);
      color: var(--text-primary);
    }
    .migrate-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 16px;
    }
    .duplicate-warning {
      background: #fef3c7;
      border: 1px solid #f59e0b;
      border-radius: 6px;
      padding: 12px 16px;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .duplicate-warning-content {
      flex: 1;
    }
    .duplicate-warning-title {
      font-weight: 600;
      color: #92400e;
    }
    .duplicate-warning-text {
      font-size: 13px;
      color: #a16207;
    }
    .duplicate-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }
    @media (max-width: 600px) {
      .duplicate-grid {
        grid-template-columns: 1fr;
      }
    }
  `,

  /** Spinner */
  spinner: `
    .spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid var(--divider);
      border-top-color: var(--ticker-500);
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin-right: 8px;
    }
  `,

  /** History tab styles */
  history: `
    .history-list {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .history-date-group {
      margin-bottom: 8px;
    }
    .history-date-label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .history-item {
      padding: 12px 16px;
      background: var(--bg-primary);
      border-radius: 4px;
      margin-bottom: 8px;
    }
    .history-item:last-child {
      margin-bottom: 0;
    }
    .history-item-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 4px;
    }
    .history-item-title {
      font-weight: 500;
      color: var(--text-primary);
    }
    .history-item-time {
      font-size: 12px;
      color: var(--text-secondary);
    }
    .history-item-message {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }
    .history-item-meta {
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }
  `,

  /** Ticker logo SVG as HTML string */
  logoSvg: `<svg class="header-logo" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="50" cy="50" r="12" fill="#06b6d4"/>
    <circle cx="50" cy="50" r="25" stroke="#06b6d4" stroke-width="4" fill="none"/>
    <circle cx="50" cy="50" r="40" stroke="#06b6d4" stroke-width="3" fill="none" opacity="0.6"/>
  </svg>`,

  /**
   * Get all common styles concatenated.
   * @returns {string} - All common CSS rules
   */
  getCommonStyles() {
    return [
      this.variables,
      this.base,
      this.header,
      this.tabs,
      this.cards,
      this.buttons,
      this.badges,
      this.messages,
      this.states,
      this.toggles,
      this.notifyServices,
      this.queueItems,
      this.warningBanner,
      this.forms,
      this.listItems,
      this.sections,
      this.colorIndicator,
      this.accordion,
      this.listItemExtras,
      this.subscriptions,
      this.statsGrid,
      this.logItems,
      this.adminQueueItems,
      this.migrate,
      this.spinner,
      this.history,
    ].join('\n');
  },
};
