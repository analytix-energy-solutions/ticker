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
    this._hideZone = false;
    this._hideQueue = false;
    this._expandedRules = new Set();
    this._deliverWhenMet = false;
    this._queueUntilMet = false;
    this._dispatchTimer = null;
  }

  static get observedAttributes() {
    return ['disabled', 'hide-zone', 'hide-queue'];
  }

  attributeChangedCallback(name, _oldValue, newValue) {
    const flag = newValue !== null;
    if (name === 'disabled') this._disabled = flag;
    else if (name === 'hide-zone') this._hideZone = flag;
    else if (name === 'hide-queue') this._hideQueue = flag;
    this._render();
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

  set deliverWhenMet(value) { this._deliverWhenMet = !!value; this._render(); }
  get deliverWhenMet() { return this._deliverWhenMet; }

  set queueUntilMet(value) { this._queueUntilMet = !!value; this._render(); }
  get queueUntilMet() { return this._queueUntilMet; }

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
      this._queueUntilMet = !this._hideQueue;
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

  _updateRule(index, field, value, skipRender = false) {
    const rule = { ...this._rules[index] };
    rule[field] = value;
    this._rules = this._rules.map((r, i) => i === index ? rule : r);
    this._dispatchRulesChanged();
    if (!skipRender) {
      this._render();
    }
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

  /**
   * Handle entity input: update rule data, filter datalist in-place.
   * Filters entities client-side and only populates the datalist
   * with the top 20 matches for performance.
   * Also updates the state select when the entity domain changes.
   */
  _onEntityInput(index, value) {
    // Track domain before update for state select refresh
    const oldDomain = (this._rules[index].entity_id || '').split('.')[0];

    // Update rule data without re-render
    this._updateRule(index, 'entity_id', value, true);

    // Filter entities and update datalist directly
    const datalist = this.shadowRoot.getElementById(`entity-list-${index}`);
    if (datalist) {
      if (!value || value.length < 2) {
        datalist.innerHTML = '';
      } else {
        const query = value.toLowerCase();
        const matches = [];
        for (let i = 0; i < this._entities.length && matches.length < 20; i++) {
          const e = this._entities[i];
          if (e.entity_id.toLowerCase().includes(query) ||
              (e.name && e.name.toLowerCase().includes(query))) {
            matches.push(e);
          }
        }
        datalist.innerHTML = matches.map(e =>
          `<option value="${this._escAttr(e.entity_id)}">${this._esc(e.name || e.entity_id)}</option>`
        ).join('');
      }
    }

    // Refresh state select if domain changed
    const newDomain = (value || '').split('.')[0];
    if (newDomain !== oldDomain) {
      const stateSelect = this.shadowRoot.getElementById(`state-select-${index}`);
      if (stateSelect) {
        const suggestions = this._getStateSuggestions(value);
        const currentState = this._rules[index].state || '';
        const hasCurrentInList = !currentState || suggestions.includes(currentState);
        let html = '<option value="">Select state...</option>';
        if (currentState && !hasCurrentInList) {
          html += `<option value="${this._escAttr(currentState)}" selected>${this._esc(currentState)}</option>`;
        }
        html += suggestions.map(s =>
          `<option value="${this._escAttr(s)}" ${s === currentState ? 'selected' : ''}>${this._esc(s)}</option>`
        ).join('');
        stateSelect.innerHTML = html;
      }
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
    // Styles loaded from ticker-conditions-styles.js via window.Ticker.conditionsStyles
    const styles = window.Ticker.conditionsStyles || '';

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

    // Add rule buttons (zone hidden when hide-zone attribute is set)
    const zoneBtn = this._hideZone ? '' : `
        <button class="add-rule-btn" onclick="this.getRootNode().host._addRule('zone')" ${this._disabled ? 'disabled' : ''}>
          + Zone
        </button>`;
    const addButtons = `
      <div class="add-rule-section">
        ${zoneBtn}
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
    const queueToggle = this._hideQueue ? '' : `
        <label class="action-toggle">
          <input type="checkbox" ${this._queueUntilMet ? 'checked' : ''} onchange="this.getRootNode().host._toggleQueueUntilMet()" ${this._disabled ? 'disabled' : ''}>
          Queue until all conditions met
        </label>`;
    const actionsSection = this._rules.length > 0 ? `
      <div class="ruleset-actions">
        <label class="action-toggle">
          <input type="checkbox" ${this._deliverWhenMet ? 'checked' : ''} onchange="this.getRootNode().host._toggleDeliverWhenMet()" ${this._disabled ? 'disabled' : ''}>
          Deliver when all conditions met
        </label>${queueToggle}
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
      // Get state suggestions based on entity domain
      const stateSuggestions = this._getStateSuggestions(rule.entity_id);
      const currentState = rule.state || '';
      const stateSelectOptions = stateSuggestions.map(s =>
        `<option value="${this._escAttr(s)}" ${s === currentState ? 'selected' : ''}>${this._esc(s)}</option>`
      ).join('');
      // Include current value as option if not in suggestions (custom state)
      const hasCurrentInList = !currentState || stateSuggestions.includes(currentState);
      const customOption = !hasCurrentInList
        ? `<option value="${this._escAttr(currentState)}" selected>${this._esc(currentState)}</option>`
        : '';

      // Entity datalist starts empty — populated on input via _onEntityInput
      return `
        <div class="rule-content">
          <div class="form-row">
            <div class="form-group" style="flex:2">
              <label class="form-label">Entity</label>
              <input type="text" class="form-input" list="entity-list-${index}"
                id="entity-input-${index}"
                placeholder="Start typing to search..."
                value="${this._escAttr(rule.entity_id || '')}"
                oninput="this.getRootNode().host._onEntityInput(${index}, this.value)"
                ${disabledAttr}>
              <datalist id="entity-list-${index}"></datalist>
            </div>
            <div class="form-group" style="flex:1">
              <label class="form-label">State</label>
              <select class="form-select" id="state-select-${index}"
                onchange="this.getRootNode().host._updateRule(${index}, 'state', this.value)"
                ${disabledAttr}>
                <option value=""${!currentState ? ' selected' : ''}>Select state...</option>
                ${customOption}
                ${stateSelectOptions}
              </select>
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
