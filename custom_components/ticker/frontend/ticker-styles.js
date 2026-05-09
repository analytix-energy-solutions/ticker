/**
 * Ticker Shared Styles — brand colors and CSS variables (see branding/README.md)
 */
window.Ticker = window.Ticker || {};

window.Ticker.styles = {
  /** Brand primary color for use in JS (non-CSS) contexts */
  brandPrimary: '#06b6d4',

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
      --ticker-success: #22c55e;
      --ticker-warning: #f59e0b;
      --ticker-warning-dark: #d97706;
      --ticker-danger: #ef4444;
      --ticker-danger-hover: #dc2626;
      --ticker-disabled: #9ca3af;
      --ticker-info: #3b82f6;
      --ticker-warning-bg: #fef3c7;
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
      background: var(--ticker-danger);
      color: white;
    }
    .btn-danger:hover {
      background: var(--ticker-danger-hover);
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
      background: var(--ticker-success);
    }
    .badge-warning {
      background: var(--ticker-warning);
    }
    .badge-danger {
      background: var(--ticker-danger);
    }
    .badge-disabled {
      background: var(--ticker-disabled);
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
      background: var(--ticker-error-bg, #fef2f2);
      border: 1px solid var(--ticker-error-border, #fecaca);
      color: var(--ticker-danger-hover);
    }
    .success-message {
      background: var(--ticker-success-bg, #f0fdf4);
      border: 1px solid var(--ticker-success-border, #bbf7d0);
      color: var(--ticker-success-text, #16a34a);
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
      color: var(--ticker-danger-hover);
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
      background: var(--ticker-toggle-off, #ccc);
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
      background: var(--ticker-toggle-knob, #fff);
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
      background: var(--ticker-500-alpha-10, rgba(6,182,212,0.1));
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
      background: var(--ticker-warning-bg);
      border: 1px solid var(--ticker-warning-border, #fcd34d);
      border-radius: 4px;
      padding: 10px 12px;
      margin-top: 8px;
      color: var(--ticker-warning-text, #92400e);
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
    .form-input, .form-select {
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
    .list-item-header:hover { background: var(--ticker-500-alpha-5, rgba(6,182,212,0.05)); }
    .list-item-header.expanded {
      border-left: 3px solid var(--ticker-500);
      background: var(--ticker-500-alpha-8, rgba(6,182,212,0.08));
    }
    .list-item-content {
      display: flex;
      flex-direction: column;
      gap: 2px;
      flex: 1;
      min-width: 0;
    }
    .list-item-title {
      font-weight: 500;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 8px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .list-item-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
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
    .chevron.expanded { transform: rotate(90deg); }
    .expand-icon {
      width: 20px;
      height: 20px;
      color: var(--text-secondary);
      transition: transform 0.2s;
      flex-shrink: 0;
    }
    .expand-icon.open { transform: rotate(180deg); }
  `,

  /** F-35.2: volume override slider (recipients + categories dialogs) */
  volumeOverride: `.ticker-volume-override{margin-top:12px;padding:8px;border:1px solid var(--divider);border-radius:4px}.ticker-volume-override-label{display:block;margin-bottom:4px;font-size:13px;color:var(--text-primary);font-weight:600}.ticker-volume-override-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.ticker-volume-slider{flex:1;min-width:140px;accent-color:var(--ticker-500)}.ticker-volume-slider:disabled{opacity:0.4}.ticker-volume-value{min-width:48px;font-size:12px;color:var(--text-secondary);font-variant-numeric:tabular-nums}.ticker-volume-value.is-default{font-style:italic}.ticker-volume-help{display:block;margin-top:4px;font-size:11px;color:var(--text-secondary)}`,

  /** F-35.1: bundled chime preset chips (recipients + categories dialogs) */
  chimePresets: `
    .ticker-chime-presets { display:flex; flex-wrap:wrap; gap:6px; margin:4px 0 8px; }
    .ticker-chime-chip { padding:4px 10px; font-size:12px; border-radius:14px; border:1px solid var(--divider); background:var(--bg-card); color:var(--text-secondary); cursor:pointer; transition:background 0.1s, color 0.1s, border-color 0.1s; }
    .ticker-chime-chip:hover { border-color:var(--ticker-500); color:var(--text-primary); }
    .ticker-chime-chip.active { border-color:var(--ticker-500); background:var(--ticker-500-alpha-8, rgba(6,182,212,0.08)); color:var(--ticker-500); font-weight:600; }
  `,

  /** Ticker logo SVG as HTML string */
  logoSvg: `<svg class="header-logo" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="50" cy="50" r="12" style="fill:var(--ticker-500)"/>
    <circle cx="50" cy="50" r="25" style="stroke:var(--ticker-500)" stroke-width="4" fill="none"/>
    <circle cx="50" cy="50" r="40" style="stroke:var(--ticker-500)" stroke-width="3" fill="none" opacity="0.6"/>
  </svg>`,

  /** Get all common styles concatenated. */
  getCommonStyles() {
    return [
      this.variables, this.base, this.header, this.tabs, this.cards,
      this.buttons, this.badges, this.messages, this.states, this.toggles,
      this.notifyServices, this.queueItems, this.warningBanner, this.forms,
      this.listItems, this.chimePresets, this.volumeOverride,
    ].join('\n');
  },
};
