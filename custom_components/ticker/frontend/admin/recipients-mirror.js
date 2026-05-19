/**
 * Ticker Admin Panel - Recipients Mirror Renderer
 *
 * F-39 chunk 3: When a device (recipient) is linked to a person via
 * `user_link`, the device's category subscriptions are mirrored from the
 * linked user's per-category modes. This module renders a READ-ONLY view
 * of that mirrored snapshot — one row per category with a mode pill and
 * a short condition summary — so admins can see what the device will
 * deliver without leaving the Devices tab.
 *
 * Device-local conditions (the upstream F-21 gate) are unchanged and
 * remain editable in the recipient create/edit dialog.
 *
 * Brand: See branding/README.md — all colors via CSS variables and brand
 * tokens from ticker-styles.js. No inline hex.
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminRecipientsMirror = {
  /**
   * Render the mirrored, read-only subscription view for a linked
   * recipient. Returns the inner HTML for the accordion content body
   * (caller wraps in .accordion-content if needed — but in our case
   * the recipient-tab caller composes its own accordion shell, so we
   * return the full accordion-content block here).
   *
   * @param {Object} state - Admin panel state (provides `categories`)
   * @param {Object} recipient - Recipient object with `user_link`,
   *   `linked_user_name`, `linked_user_subscriptions`.
   * @returns {string} HTML string
   */
  render(state, recipient) {
    const { esc, escAttr } = window.Ticker.utils;
    const { categories } = state;

    const escRid = escAttr(recipient.recipient_id);
    const linkedName = recipient.linked_user_name
      || recipient.user_link
      || 'linked user';
    const escLinkedName = esc(linkedName);

    const mirrored = recipient.linked_user_subscriptions || {};

    const sorted = [...(categories || [])].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    const notice = `
      <div class="mirror-notice"
        style="padding:8px 12px;margin:0 0 8px 0;background:var(--bg-card);
               border:1px solid var(--divider);
               border-left:3px solid var(--ticker-500);border-radius:6px;
               color:var(--text-secondary);font-size:12px;line-height:1.4">
        <ha-icon icon="mdi:link-variant"
          style="--mdc-icon-size:14px;vertical-align:-2px;margin-right:4px"></ha-icon>
        Mirroring <strong>${escLinkedName}</strong> — edit in user panel
      </div>
    `;

    let rows;
    if (!sorted.length) {
      rows = `<p class="card-description" style="margin:12px 0 0">No categories.</p>`;
    } else {
      rows = sorted.map(c => this._renderRow(c, mirrored)).join('');
    }

    const deleteBtn = `
      <div class="button-row" style="justify-content:flex-end">
        <button class="btn btn-danger btn-small"
          onclick="window.Ticker.AdminRecipientsTab.handlers.confirmDelete(window.Ticker._adminPanel, '${escRid}')">
          Delete Device
        </button>
      </div>
    `;

    return `
      <div class="accordion-content">
        ${notice}
        <div class="subscription-header">Mirrored Subscriptions</div>
        <div class="subscriptions-list">
          ${rows}
        </div>
        ${deleteBtn}
      </div>
    `;
  },

  /**
   * Render one read-only category row: color dot + name, mode pill,
   * short condition summary when mode=conditional.
   *
   * @param {Object} category
   * @param {Object} mirrored - linked_user_subscriptions map
   * @returns {string} HTML string
   */
  _renderRow(category, mirrored) {
    const { esc, escAttr } = window.Ticker.utils;

    const escCname = esc(category.name || category.id);
    const escColor = escAttr(category.color || '');
    const colorDot = category.color
      ? `<span class="color-indicator" style="background:${escColor}"></span>`
      : '';

    const sub = mirrored[category.id] || { mode: 'always' };
    const mode = typeof sub === 'string' ? sub : (sub.mode || 'always');
    const modePill = this._renderModePill(mode);

    let summary = '';
    if (mode === 'conditional') {
      summary = this._renderConditionSummary(sub.conditions || {});
    }

    return `
      <div class="subscription-row" style="flex-wrap:wrap">
        <span class="subscription-label">${colorDot}${escCname}</span>
        ${modePill}
        ${summary}
      </div>
    `;
  },

  /**
   * Render the mode pill. Uses brand-token outline badges; no new colors.
   *
   * @param {string} mode - 'always' | 'never' | 'conditional'
   * @returns {string} HTML string
   */
  _renderModePill(mode) {
    const label = mode === 'always' ? 'Always'
      : mode === 'never' ? 'Never'
      : mode === 'conditional' ? 'Conditional'
      : mode;
    return `<span class="badge badge-outline"
      style="font-size:11px;padding:2px 8px">${label}</span>`;
  },

  /**
   * Best-effort short summary for a conditional block. Counts the leaf
   * conditions in the tree so admins get a quick "how many rules" cue
   * without re-implementing the conditions UI rendering.
   *
   * @param {Object} conditions
   * @returns {string} HTML string
   */
  _renderConditionSummary(conditions) {
    let leafCount = 0;
    const tree = conditions.condition_tree;
    if (tree && window.Ticker.conditionsTree
        && typeof window.Ticker.conditionsTree.collectLeaves === 'function') {
      const leaves = window.Ticker.conditionsTree.collectLeaves(tree);
      leafCount = Array.isArray(leaves) ? leaves.length : 0;
    } else if (Array.isArray(conditions.rules)) {
      leafCount = conditions.rules.length;
    }

    const text = leafCount > 0
      ? `${leafCount} rule${leafCount === 1 ? '' : 's'}`
      : 'no rules';
    return `<span style="color:var(--text-secondary);font-size:12px;
      margin-left:6px">${text}</span>`;
  },
};
