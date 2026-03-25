/**
 * Ticker Admin Panel - Recipients Tab (UI label: "Devices")
 * Handles non-user recipient management and subscription mode selectors.
 * Handlers are in recipients-handlers.js (extracted to stay under 500 lines).
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminRecipientsTab = window.Ticker.AdminRecipientsTab || {};

Object.assign(window.Ticker.AdminRecipientsTab, {
  /**
   * Render the recipients (devices) tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { recipients } = state;

    if (!recipients || !recipients.length) {
      return `
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">Devices</h2>
            <button class="btn btn-primary btn-small" onclick="window.Ticker.AdminRecipientsTab.handlers.openCreateDialog(window.Ticker._adminPanel)">+ Add New</button>
          </div>
          <div class="empty-state">No devices configured. Click "+ Add New" to create one.</div>
        </div>
      `;
    }

    const items = recipients.map(r => this._renderRecipientItem(state, r)).join('');

    return `
      <div class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">Devices</h2>
            <p class="card-description" style="margin-bottom:0">Click device to manage subscriptions.</p>
          </div>
          <button class="btn btn-primary btn-small" onclick="window.Ticker.AdminRecipientsTab.handlers.openCreateDialog(window.Ticker._adminPanel)">+ Add New</button>
        </div>
        <div class="list">
          ${items}
        </div>
      </div>
    `;
  },

  /**
   * Render a single recipient item.
   * @param {Object} state - Panel state
   * @param {Object} r - Recipient object
   * @returns {string} - HTML string
   */
  _renderRecipientItem(state, r) {
    const { esc, escAttr } = window.Ticker.utils;
    const { expandedRecipients } = state;

    const escRid = escAttr(r.recipient_id);
    const escName = esc(r.name);
    const expanded = r.enabled && expandedRecipients.has(r.recipient_id);
    const canExpand = r.enabled;

    const expandIcon = canExpand ? `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    ` : '';

    const deviceType = r.device_type || 'push';
    let serviceInfo;
    if (deviceType === 'tts') {
      const mp = r.media_player_entity_id || 'none';
      serviceInfo = `<span class="notify-service-tag">${esc(mp)}</span>`;
    } else {
      serviceInfo = r.notify_services && r.notify_services.length
        ? `<div class="notify-services">${r.notify_services.map(s => `<span class="notify-service-tag">${esc(s.name || s.service || s)}</span>`).join('')}</div>`
        : '<span class="badge badge-warning">No services</span>';
    }

    const typeBadge = this._renderTypeBadge(r);
    const headerStyle = canExpand ? '' : 'cursor:default';

    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminRecipientsTab.handlers.toggleExpanded(window.Ticker._adminPanel, '${escRid}')" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            <ha-icon icon="${escAttr(r.icon || 'mdi:bell-ring')}" style="--mdc-icon-size:20px;margin-right:4px"></ha-icon>
            ${escName}
            ${!r.enabled ? '<span class="badge badge-gray">Disabled</span>' : ''}
          </span>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
            ${serviceInfo}
            ${typeBadge}
          </div>
        </div>
        <div class="list-item-actions">
          <button class="btn btn-secondary btn-small" onclick="event.stopPropagation();window.Ticker.AdminRecipientsTab.handlers.openEditDialog(window.Ticker._adminPanel, '${escRid}')" title="Edit properties" ${!r.enabled ? 'disabled' : ''}>
            <ha-icon icon="mdi:pencil" style="--mdc-icon-size:14px"></ha-icon>
          </button>
          <button class="btn btn-secondary btn-small" onclick="event.stopPropagation();window.Ticker.AdminRecipientsTab.handlers.sendTest(window.Ticker._adminPanel, '${escRid}')" ${!r.enabled ? 'disabled' : ''}>Test</button>
          <label class="toggle" onclick="event.stopPropagation()">
            <input type="checkbox" ${r.enabled ? 'checked' : ''} onchange="window.Ticker.AdminRecipientsTab.handlers.toggleEnabled(window.Ticker._adminPanel, '${escRid}', ${r.enabled})">
            <span class="toggle-slider"></span>
          </label>
          ${expandIcon}
        </div>
      </div>
    `;

    const accordion = expanded ? this._renderRecipientSubscriptions(state, r) : '';

    return `<div class="list-item ${r.enabled ? '' : 'disabled'}">${header}${accordion}</div>`;
  },

  /**
   * Render device type and format badge pills.
   * @param {Object} r - Recipient object
   * @returns {string} - HTML string
   */
  _renderTypeBadge(r) {
    const { esc } = window.Ticker.utils;
    const deviceType = r.device_type || 'push';
    if (deviceType === 'tts') {
      let badges = `<span class="badge badge-outline" style="font-size:10px;padding:1px 6px">TTS</span>`;
      const panel = window.Ticker._adminPanel;
      if (panel && panel._ttsOptions && r.media_player_entity_id) {
        const mp = (panel._ttsOptions.media_players || []).find(
          m => m.entity_id === r.media_player_entity_id
        );
        if (mp && mp.supports_announce) {
          badges += ` <span class="badge badge-outline" style="font-size:10px;padding:1px 6px;border-color:var(--ticker-success);color:var(--ticker-success)">Announce</span>`;
        }
      }
      return badges;
    }
    const formatLabels = { rich: 'Rich', plain: 'Plain' };
    const fmt = formatLabels[r.delivery_format] || esc(r.delivery_format || 'Rich');
    return `<span class="badge badge-outline" style="font-size:10px;padding:1px 6px">Push (${fmt})</span>`;
  },

  /**
   * Render recipient subscription rows with 3-way mode selector.
   * @param {Object} state - Panel state
   * @param {Object} r - Recipient object
   * @returns {string} - HTML string
   */
  _renderRecipientSubscriptions(state, r) {
    const { esc, escAttr } = window.Ticker.utils;
    const { categories } = state;

    const escRid = escAttr(r.recipient_id);

    const sorted = [...categories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    if (!sorted.length) {
      return `
        <div class="accordion-content">
          <p class="card-description" style="margin:12px 0 0">No categories.</p>
        </div>
      `;
    }

    const subs = r.subscriptions || {};

    const rows = sorted.map(c => {
      const escCid = escAttr(c.id);
      const escCname = esc(c.name || c.id);
      const escColor = escAttr(c.color || '');
      const sub = subs[c.id] || { mode: 'always' };
      const mode = typeof sub === 'string' ? sub : (sub.mode || 'always');
      const colorDot = c.color ? `<span class="color-indicator" style="background:${escColor}"></span>` : '';

      // Conditions UI placeholder for conditional mode
      const conditionsHtml = mode === 'conditional' ? `
        <div style="padding:4px 0 8px 24px">
          <ticker-conditions-ui
            id="rcpt-conditions-${escRid}-${escCid}"
            hide-zone
          ></ticker-conditions-ui>
        </div>
      ` : '';

      return `
        <div class="subscription-row" style="flex-wrap:wrap">
          <span class="subscription-label">${colorDot}${escCname}</span>
          <select class="subscription-select" style="min-width:120px"
            onchange="window.Ticker.AdminRecipientsTab.handlers.handleModeChange(window.Ticker._adminPanel, '${escRid}', '${escCid}', this.value)"
            onclick="event.stopPropagation()">
            <option value="always" ${mode === 'always' ? 'selected' : ''}>Always</option>
            <option value="never" ${mode === 'never' ? 'selected' : ''}>Never</option>
            <option value="conditional" ${mode === 'conditional' ? 'selected' : ''}>Conditional</option>
          </select>
          ${conditionsHtml}
        </div>
      `;
    }).join('');

    const deleteBtn = `
      <div class="button-row" style="justify-content:flex-end">
        <button class="btn btn-danger btn-small" onclick="window.Ticker.AdminRecipientsTab.handlers.confirmDelete(window.Ticker._adminPanel, '${escRid}')">Delete Device</button>
      </div>
    `;

    return `
      <div class="accordion-content">
        <div class="subscription-header">Subscriptions</div>
        <div class="subscriptions-list">
          ${rows}
        </div>
        ${deleteBtn}
      </div>
    `;
  },

  /**
   * Set up conditions UI components for recipient subscriptions.
   * Called from ticker-admin-panel.js after rendering the devices tab.
   * @param {Object} panel - Admin panel instance
   */
  setupRecipientConditionsUI(panel) {
    if (!panel._recipients) return;

    for (const r of panel._recipients) {
      if (!r.enabled || !panel._expandedRecipients.has(r.recipient_id)) continue;
      const subs = r.subscriptions || {};

      for (const [catId, sub] of Object.entries(subs)) {
        const subObj = typeof sub === 'string' ? { mode: sub } : sub;
        if (subObj.mode !== 'conditional') continue;

        const uiId = `rcpt-conditions-${r.recipient_id}-${catId}`;
        const conditionsUI = panel.shadowRoot.getElementById(uiId);
        if (!conditionsUI) continue;

        const conditions = subObj.conditions || {};
        const rules = conditions.rules || [];

        conditionsUI.rules = rules;
        conditionsUI.deliverWhenMet = conditions.deliver_when_met || false;
        conditionsUI.queueUntilMet = conditions.queue_until_met || false;
        conditionsUI.zones = panel._zones;
        conditionsUI.entities = panel._entities;

        // Wire change listener
        conditionsUI.removeEventListener('rules-changed', conditionsUI._rcptHandler);
        const rid = r.recipient_id;
        const cid = catId;
        conditionsUI._rcptHandler = (e) => {
          window.Ticker.AdminRecipientsTab.handlers.handleRecipientRulesChanged(
            panel, rid, cid, e.detail,
          );
        };
        conditionsUI.addEventListener('rules-changed', conditionsUI._rcptHandler);
      }
    }
  },

  /**
   * Render dialog -- delegates to AdminRecipientsDialog module.
   * @param {Object} panel - Admin panel instance
   * @param {Object|null} existing - Existing recipient for edit, null for create
   * @returns {string} - HTML string
   */
  _renderDialog(panel, existing) {
    return window.Ticker.AdminRecipientsDialog.render(panel, existing);
  },

  // handlers object is loaded from admin/recipients-handlers.js
});
