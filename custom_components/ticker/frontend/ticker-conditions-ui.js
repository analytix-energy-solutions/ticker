/**
 * Ticker Conditions UI Component
 * Reusable component for editing F-2 Advanced Conditions
 *
 * Supports zone, time, and entity state conditions with AND logic.
 *
 * Brand: See branding/README.md
 * Colors: --ticker-500: #06b6d4, --ticker-400: #22d3ee, --ticker-700: #0e7490
 */

// Use shared utilities if available, fallback to local implementation
const _tickerUtils = (window.Ticker && window.Ticker.utils) || {
  esc: s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'),
  escAttr: s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;'),
};

class TickerConditionsUI extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._rules = [];
    this._zones = [];
    this._entities = [];
    this._disabled = false;
    this._expandedRules = new Set();
    this._deliverWhenMet = false;
    this._queueUntilMet = false;
    this._dispatchTimer = null;
  }

  static get observedAttributes() {
    return ['disabled'];
  }

  attributeChangedCallback(name, oldValue, newValue) {
    if (name === 'disabled') {
      this._disabled = newValue !== null;
      this._render();
    }
  }

  set rules(value) {
    this._rules = value || [];
    this._render();
  }

  get rules() {
    return this._rules;
  }

  set zones(value) {
    this._zones = value || [];
    this._render();
  }

  set entities(value) {
    this._entities = value || [];
    this._render();
  }

  set deliverWhenMet(value) {
    this._deliverWhenMet = !!value;
    this._render();
  }

  set queueUntilMet(value) {
    this._queueUntilMet = !!value;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _esc(str) {
    return _tickerUtils.esc(str);
  }

  _escAttr(str) {
    return _tickerUtils.escAttr(str);
  }

  _toggleRuleExpand(index) {
    if (this._expandedRules.has(index)) {
      this._expandedRules.delete(index);
    } else {
      this._expandedRules.add(index);
    }
    this._render();
  }

  _addRule(type) {
    const newRule = { type };

    if (type === 'zone') {
      // Default to first available zone
      newRule.zone_id = this._zones.length > 0 ? this._zones[0].zone_id : 'zone.home';
    } else if (type === 'time') {
      newRule.after = '08:00';
      newRule.before = '22:00';
      newRule.days = [1, 2, 3, 4, 5, 6, 7]; // All days
    } else if (type === 'state') {
      newRule.entity_id = '';
      newRule.state = '';
    }

    // Set default ruleset-level flags if this is the first rule
    if (this._rules.length === 0) {
      this._deliverWhenMet = true;
      this._queueUntilMet = true;
    }

    this._rules = [...this._rules, newRule];
    this._expandedRules.add(this._rules.length - 1);
    this._dispatchRulesChanged(true); // Immediate for discrete actions
    this._render();
  }

  _removeRule(index) {
    this._rules = this._rules.filter((_, i) => i !== index);
    this._expandedRules.delete(index);
    // Adjust expanded indices
    const newExpanded = new Set();
    for (const i of this._expandedRules) {
      if (i > index) {
        newExpanded.add(i - 1);
      } else if (i < index) {
        newExpanded.add(i);
      }
    }
    this._expandedRules = newExpanded;
    this._dispatchRulesChanged(true); // Immediate for discrete actions
    this._render();
  }

  _updateRule(index, field, value) {
    const rule = { ...this._rules[index] };
    rule[field] = value;
    this._rules = this._rules.map((r, i) => i === index ? rule : r);
    this._dispatchRulesChanged();
    this._render();
  }

  _toggleDay(index, day) {
    const rule = { ...this._rules[index] };
    const days = [...(rule.days || [])];
    const dayIndex = days.indexOf(day);
    if (dayIndex >= 0) {
      days.splice(dayIndex, 1);
    } else {
      days.push(day);
      days.sort((a, b) => a - b);
    }
    rule.days = days;
    this._rules = this._rules.map((r, i) => i === index ? rule : r);
    this._dispatchRulesChanged();
    this._render();
  }

  _toggleDeliverWhenMet() {
    this._deliverWhenMet = !this._deliverWhenMet;
    this._dispatchRulesChanged(true); // Immediate for toggle
    this._render();
  }

  _toggleQueueUntilMet() {
    this._queueUntilMet = !this._queueUntilMet;
    this._dispatchRulesChanged(true); // Immediate for toggle
    this._render();
  }

  /**
   * Dispatch rules-changed event with debouncing to prevent
   * excessive WebSocket calls and parent re-renders.
   * @param {boolean} immediate - If true, dispatch immediately without delay
   */
  _dispatchRulesChanged(immediate = false) {
    // Clear any pending dispatch
    if (this._dispatchTimer) {
      clearTimeout(this._dispatchTimer);
      this._dispatchTimer = null;
    }

    const dispatch = () => {
      this._dispatchTimer = null;
      this.dispatchEvent(new CustomEvent('rules-changed', {
        detail: {
          rules: this._rules,
          deliver_when_met: this._deliverWhenMet,
          queue_until_met: this._queueUntilMet,
        },
        bubbles: true,
        composed: true,
      }));
    };

    if (immediate) {
      dispatch();
    } else {
      // Debounce by 400ms to allow for multiple rapid changes
      this._dispatchTimer = setTimeout(dispatch, 400);
    }
  }

  _getZoneName(zoneId) {
    const zone = this._zones.find(z => z.zone_id === zoneId);
    return zone ? zone.name : zoneId.replace('zone.', '');
  }

  /**
   * Get suggested states based on entity domain.
   * @param {string} entityId - Entity ID
   * @returns {string[]} - Array of suggested states
   */
  _getStateSuggestions(entityId) {
    if (!entityId) return ['on', 'off'];

    const domain = entityId.split('.')[0];
    const domainStates = {
      'binary_sensor': ['on', 'off'],
      'switch': ['on', 'off'],
      'light': ['on', 'off'],
      'fan': ['on', 'off'],
      'input_boolean': ['on', 'off'],
      'lock': ['locked', 'unlocked'],
      'cover': ['open', 'closed', 'opening', 'closing'],
      'alarm_control_panel': ['armed_away', 'armed_home', 'armed_night', 'disarmed', 'triggered'],
      'climate': ['off', 'heat', 'cool', 'heat_cool', 'auto', 'dry', 'fan_only'],
      'media_player': ['off', 'on', 'playing', 'paused', 'idle', 'standby'],
      'vacuum': ['cleaning', 'docked', 'idle', 'paused', 'returning'],
      'person': ['home', 'not_home', 'away'],
      'device_tracker': ['home', 'not_home', 'away'],
      'sun': ['above_horizon', 'below_horizon'],
      'weather': ['sunny', 'cloudy', 'partlycloudy', 'rainy', 'snowy', 'fog'],
    };

    return domainStates[domain] || ['on', 'off'];
  }

  _getRuleTypeName(type) {
    const names = { zone: 'Zone', time: 'Time', state: 'Entity State' };
    return names[type] || type;
  }

  _getRuleSummary(rule) {
    if (rule.type === 'zone') {
      return `In ${this._getZoneName(rule.zone_id)}`;
    } else if (rule.type === 'time') {
      const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const days = (rule.days || []).map(d => dayNames[d - 1]).join(', ');
      return `${rule.after} - ${rule.before}${days ? ` (${days})` : ''}`;
    } else if (rule.type === 'state') {
      return rule.entity_id ? `${rule.entity_id} = ${rule.state}` : 'Not configured';
    }
    return 'Unknown';
  }

  _render() {
    const styles = `
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
          color: #ef4444;
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

    let content = '';

    if (this._rules.length === 0) {
      content = `
        <div class="empty-state">
          No conditions configured. Add a condition to control when notifications are delivered.
        </div>
      `;
    } else {
      const rulesHtml = this._rules.map((rule, index) => {
        const isExpanded = this._expandedRules.has(index);
        const isLast = index === this._rules.length - 1;

        let ruleContent = '';
        if (isExpanded) {
          ruleContent = this._renderRuleContent(rule, index);
        }

        return `
          <div class="rule-item ${isExpanded ? 'expanded' : ''}">
            <div class="rule-header" onclick="this.getRootNode().host._toggleRuleExpand(${index})">
              <div class="rule-header-left">
                <span class="chevron ${isExpanded ? 'expanded' : ''}">▶</span>
                <span class="rule-type-badge">${this._esc(this._getRuleTypeName(rule.type))}</span>
                <span class="rule-summary">${this._esc(this._getRuleSummary(rule))}</span>
              </div>
              <button class="rule-delete" onclick="event.stopPropagation(); this.getRootNode().host._removeRule(${index})" ${this._disabled ? 'disabled' : ''} title="Remove rule">×</button>
            </div>
            ${ruleContent}
          </div>
          ${!isLast ? '<div class="and-indicator"><span class="and-badge">AND</span></div>' : ''}
        `;
      }).join('');

      content = `<div class="rules-container">${rulesHtml}</div>`;
    }

    // Add rule buttons
    const addButtons = `
      <div class="add-rule-section">
        <button class="add-rule-btn" onclick="this.getRootNode().host._addRule('zone')" ${this._disabled ? 'disabled' : ''}>
          + Zone
        </button>
        <button class="add-rule-btn" onclick="this.getRootNode().host._addRule('time')" ${this._disabled ? 'disabled' : ''}>
          + Time
        </button>
        <button class="add-rule-btn" onclick="this.getRootNode().host._addRule('state')" ${this._disabled ? 'disabled' : ''}>
          + Entity State
        </button>
      </div>
      ${this._rules.length > 1 ? '<div class="info-text">All conditions must be met (AND logic).</div>' : ''}
    `;

    // Ruleset-level action toggles (shown when there are rules)
    const actionsSection = this._rules.length > 0 ? `
      <div class="ruleset-actions">
        <label class="action-toggle">
          <input type="checkbox" ${this._deliverWhenMet ? 'checked' : ''} onchange="this.getRootNode().host._toggleDeliverWhenMet()" ${this._disabled ? 'disabled' : ''}>
          Deliver when all conditions met
        </label>
        <label class="action-toggle">
          <input type="checkbox" ${this._queueUntilMet ? 'checked' : ''} onchange="this.getRootNode().host._toggleQueueUntilMet()" ${this._disabled ? 'disabled' : ''}>
          Queue until all conditions met
        </label>
      </div>
    ` : '';

    this.shadowRoot.innerHTML = `${styles}${content}${addButtons}${actionsSection}`;
  }

  _renderRuleContent(rule, index) {
    const disabledAttr = this._disabled ? 'disabled' : '';

    if (rule.type === 'zone') {
      const zoneOptions = this._zones.map(z =>
        `<option value="${this._escAttr(z.zone_id)}" ${z.zone_id === rule.zone_id ? 'selected' : ''}>${this._esc(z.name)}</option>`
      ).join('');

      return `
        <div class="rule-content">
          <div class="form-group">
            <label class="form-label">Zone</label>
            <select class="form-select" onchange="this.getRootNode().host._updateRule(${index}, 'zone_id', this.value)" ${disabledAttr}>
              ${zoneOptions}
            </select>
          </div>
        </div>
      `;
    } else if (rule.type === 'time') {
      const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const days = rule.days || [];
      const dayButtons = dayNames.map((name, i) => {
        const day = i + 1;
        const selected = days.includes(day);
        return `<button class="day-btn ${selected ? 'selected' : ''}" onclick="this.getRootNode().host._toggleDay(${index}, ${day})" ${disabledAttr}>${name}</button>`;
      }).join('');

      return `
        <div class="rule-content">
          <div class="form-group">
            <label class="form-label">Time Window</label>
            <div class="time-inputs">
              <input type="time" class="time-input" value="${this._escAttr(rule.after || '08:00')}" onchange="this.getRootNode().host._updateRule(${index}, 'after', this.value)" ${disabledAttr}>
              <span class="time-separator">to</span>
              <input type="time" class="time-input" value="${this._escAttr(rule.before || '22:00')}" onchange="this.getRootNode().host._updateRule(${index}, 'before', this.value)" ${disabledAttr}>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Days</label>
            <div class="days-selector">${dayButtons}</div>
          </div>
        </div>
      `;
    } else if (rule.type === 'state') {
      // Build entity options for datalist
      const entityOptions = this._entities.map(e =>
        `<option value="${this._escAttr(e.entity_id)}">${this._esc(e.name || e.entity_id)}</option>`
      ).join('');

      // Get state suggestions based on entity domain
      const stateSuggestions = this._getStateSuggestions(rule.entity_id);
      const stateOptions = stateSuggestions.map(s =>
        `<option value="${this._escAttr(s)}">${this._esc(s)}</option>`
      ).join('');

      return `
        <div class="rule-content">
          <div class="form-row">
            <div class="form-group" style="flex:2">
              <label class="form-label">Entity</label>
              <input type="text" class="form-input" list="entity-list-${index}"
                placeholder="Start typing to search..."
                value="${this._escAttr(rule.entity_id || '')}"
                oninput="this.getRootNode().host._updateRule(${index}, 'entity_id', this.value)"
                ${disabledAttr}>
              <datalist id="entity-list-${index}">${entityOptions}</datalist>
            </div>
            <div class="form-group" style="flex:1">
              <label class="form-label">State</label>
              <input type="text" class="form-input" list="state-list-${index}"
                placeholder="${stateSuggestions.length > 0 ? stateSuggestions[0] : 'on, off, etc.'}"
                value="${this._escAttr(rule.state || '')}"
                oninput="this.getRootNode().host._updateRule(${index}, 'state', this.value)"
                ${disabledAttr}>
              <datalist id="state-list-${index}">${stateOptions}</datalist>
            </div>
          </div>
        </div>
      `;
    }

    return '';
  }
}

// Register the component
customElements.define("ticker-conditions-ui", TickerConditionsUI);
