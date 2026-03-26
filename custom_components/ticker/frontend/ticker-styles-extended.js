/**
 * Ticker Extended Styles
 * Admin-specific and feature-specific style blocks extracted from ticker-styles.js
 * to keep the base file under 500 lines.
 *
 * Loaded after ticker-styles.js. Adds properties to window.Ticker.styles and
 * monkey-patches getCommonStyles() to include them.
 */
(function () {
  const s = window.Ticker.styles;

  /** Section titles */
  s.sections = `
    .section-title {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-secondary);
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
  `;

  /** Category color indicator */
  s.colorIndicator = `
    .color-indicator {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 6px;
    }
  `;

  /** Accordion content */
  s.accordion = `
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
  `;

  /** List item subtitles */
  s.listItemExtras = `
    .list-item-subtitle {
      font-size: 12px;
      color: var(--text-secondary);
      margin-top: 2px;
    }
    .badge-gray {
      background: var(--ticker-disabled);
    }
  `;

  /** Subscriptions (admin users tab) */
  s.subscriptions = `
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
    .subscription-select:focus {
      outline: none;
      border-color: var(--ticker-500);
    }
  `;

  /** Stats grid (admin logs tab) */
  s.statsGrid = `
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
    .stat-card.stat-sent .stat-value { color: var(--ticker-success); }
    .stat-card.stat-queued .stat-value { color: var(--ticker-info); }
    .stat-card.stat-skipped .stat-value { color: var(--ticker-warning); }
    .stat-card.stat-failed .stat-value { color: var(--ticker-danger); }
  `;

  /** Log items (admin logs tab) */
  s.logItems = `
    .log-item {
      padding: 10px 14px;
      background: var(--bg-primary);
      border-radius: 4px;
      margin-bottom: 6px;
    }
    .log-item-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 4px;
    }
    .log-item-title {
      font-weight: 500;
      color: var(--text-primary);
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
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
      flex-shrink: 0;
      margin-left: auto;
    }
  `;

  /** Queue items for admin panel (extended) */
  s.adminQueueItems = `
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
  `;

  /** Migrate wizard (admin migrate tab) */
  s.migrate = `
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
      background: var(--ticker-warning-bg);
      border: 1px solid var(--ticker-warning);
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
      color: var(--ticker-warning-text, #92400e);
    }
    .duplicate-warning-text {
      font-size: 13px;
      color: var(--ticker-warning-text-alt, #a16207);
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
  `;

  /** Spinner */
  s.spinner = `
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
  `;

  /** Notify service tag overflow (extends base .notify-service-tag from ticker-styles.js) */
  s.notifyServiceOverflow = `
    .notify-service-tag {
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      display: inline-block;
    }
  `;

  /** History tab styles */
  s.history = `
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
  `;

  /** Brand alpha tokens */
  s.brandAlpha = `
    :host {
      --ticker-500-alpha-4: rgba(6,182,212,0.04);
      --ticker-500-alpha-5: rgba(6,182,212,0.05);
      --ticker-500-alpha-8: rgba(6,182,212,0.08);
      --ticker-500-alpha-10: rgba(6,182,212,0.1);
      --ticker-500-alpha-20: rgba(6,182,212,0.2);
      --ticker-error-bg: #fef2f2;
      --ticker-error-border: #fecaca;
      --ticker-success-bg: #f0fdf4;
      --ticker-success-border: #bbf7d0;
      --ticker-success-text: #16a34a;
      --ticker-toggle-off: #ccc;
      --ticker-toggle-knob: #fff;
      --ticker-warning-border: #fcd34d;
      --ticker-warning-text: #92400e;
      --ticker-warning-text-alt: #a16207;
    }
  `;

  // Monkey-patch getCommonStyles to include extended blocks
  const _baseGetCommonStyles = s.getCommonStyles.bind(s);
  s.getCommonStyles = function () {
    return _baseGetCommonStyles() + '\n' + [
      this.brandAlpha,
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
      this.notifyServiceOverflow,
      this.history,
    ].join('\n');
  };
})();
