/**
 * Ticker Admin Panel - Automations Tab: F-27 Multi-Category Read-Only View
 *
 * Extracted from automations-tab.js to keep the parent module under the
 * 500-line limit. Renders a read-only expanded form for findings whose
 * ticker.notify `category` field is a list. Editing multi-category entries
 * via the single-select dropdown would force a lossy collapse, so users are
 * directed to edit the source YAML instead.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminAutomationsMultiCategory = {
  /**
   * Render the read-only multi-category expanded view.
   * @param {Object} parent - The AdminAutomationsTab module (for helpers)
   * @param {Object} state - Panel state
   * @param {Object} finding - The finding object (category is a list)
   * @param {number} index - Original index in findings array
   * @param {string} icon - MDI icon name for the source type
   * @returns {string} - HTML string
   */
  render(parent, state, finding, index, icon) {
    const { esc, escAttr } = window.Ticker.utils;
    const sd = finding.service_data || {};
    const cats = Array.isArray(sd.category) ? sd.category : [];
    const badges = cats.map(cid => parent._renderCategoryBadge(state, cid)).join(' ');
    const rows = Math.min(Math.max(cats.length, 2), 6);

    return `
      <div class="list-item" style="border-left:3px solid var(--ticker-500)">
        <div class="list-item-header expanded" onclick="window.Ticker.AdminAutomationsTab.handlers.collapse(window.Ticker._adminPanel)">
          <div class="list-item-content"><div class="list-item-title">
            <ha-icon icon="${icon}" style="--mdc-icon-size:20px;margin-right:4px;flex-shrink:0"></ha-icon>
            ${esc(finding.source_name)}
          </div></div>
          <ha-icon icon="mdi:chevron-down" class="chevron expanded" style="--mdc-icon-size:20px"></ha-icon>
        </div>
        <div class="list-item-accordion" style="padding:16px;box-sizing:border-box;overflow:hidden">
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px">
            <strong>Source:</strong> ${esc(finding.source_type)} &middot; ${esc(finding.source_file || 'unknown')} &middot; Action path: ${esc(finding.action_path)}
          </div>
          <div class="warning-banner">
            <ha-icon icon="mdi:alert" style="--mdc-icon-size:18px;flex-shrink:0"></ha-icon>
            Multi-category notification (F-27): targets ${cats.length} categories. The inline editor cannot safely edit multi-category entries &mdash; please edit the source YAML directly.
          </div>
          <div class="form-group" style="margin-bottom:12px">
            <label>Categories</label>
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">${badges}</div>
            <textarea class="migrate-input" readonly rows="${rows}" style="width:100%;box-sizing:border-box;font-family:monospace;font-size:12px">${esc(cats.join('\n'))}</textarea>
          </div>
          <div class="form-group" style="margin-bottom:12px"><label>Title</label>
            <input type="text" class="migrate-input" value="${escAttr(sd.title || '')}" readonly></div>
          <div class="form-group" style="margin-bottom:12px"><label>Message</label>
            <input type="text" class="migrate-input" value="${escAttr(sd.message || '')}" readonly></div>
          <div class="migrate-actions">
            <button class="btn btn-secondary" onclick="window.Ticker.AdminAutomationsTab.handlers.collapse(window.Ticker._adminPanel)">Close</button>
          </div>
        </div>
      </div>
    `;
  },
};
