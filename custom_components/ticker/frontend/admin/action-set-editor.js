/**
 * Ticker Admin Panel - Action Set Editor
 * Inline editor for category notification actions (F-5).
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.ActionSetEditor = {
  /**
   * Render the action set editor for a category.
   * @param {string} categoryId - Category ID
   * @param {Object|null} actionSet - Current action_set or null
   * @param {Array} scripts - Available script entities
   * @returns {string} - HTML string
   */
  render(categoryId, actionSet, scripts) {
    const { esc, escAttr } = window.Ticker.utils;
    const actions = (actionSet && actionSet.actions) || [];
    const escId = escAttr(categoryId);

    const snoozeDurations = [
      { value: 15, label: '15 min' },
      { value: 30, label: '30 min' },
      { value: 60, label: '1 hour' },
      { value: 120, label: '2 hours' },
      { value: 240, label: '4 hours' },
    ];

    const actionSlots = actions.map((action, i) => {
      const escTitle = escAttr(action.title || '');
      const type = action.type || 'dismiss';

      let typeField = '';
      if (type === 'script') {
        const opts = scripts.map(s =>
          `<option value="${escAttr(s.entity_id)}" ${s.entity_id === action.script_entity ? 'selected' : ''}>${esc(s.name || s.entity_id)}</option>`
        ).join('');
        typeField = `
          <select id="action-script-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121);min-width:180px">
            <option value="">Select script...</option>
            ${opts}
          </select>
        `;
      } else if (type === 'snooze') {
        const dOpts = snoozeDurations.map(d =>
          `<option value="${d.value}" ${d.value === action.snooze_minutes ? 'selected' : ''}>${esc(d.label)}</option>`
        ).join('');
        typeField = `
          <select id="action-snooze-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
            ${dOpts}
          </select>
        `;
      }

      return `
        <div class="action-slot" style="display:flex;gap:8px;align-items:center;padding:8px;background:rgba(6,182,212,0.08);border-left:3px solid var(--ticker-500,#06b6d4);border-radius:4px;margin-bottom:6px">
          <input type="text" id="action-title-${escId}-${i}" value="${escTitle}" placeholder="Button label" style="flex:1;min-width:100px;padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
          <select id="action-type-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)"
            onchange="window.Ticker.ActionSetEditor.handlers.typeChanged(window.Ticker._adminPanel, '${escId}', ${i}, this.value)">
            <option value="script" ${type === 'script' ? 'selected' : ''}>Script</option>
            <option value="snooze" ${type === 'snooze' ? 'selected' : ''}>Snooze</option>
            <option value="dismiss" ${type === 'dismiss' ? 'selected' : ''}>Dismiss</option>
          </select>
          ${typeField}
          <button onclick="window.Ticker.ActionSetEditor.handlers.removeAction(window.Ticker._adminPanel, '${escId}', ${i})"
            style="border:none;background:none;color:var(--error-color,#b71c1c);cursor:pointer;font-size:16px;padding:4px" title="Remove">&times;</button>
        </div>
      `;
    }).join('');

    const canAdd = actions.length < 3;
    const addBtn = canAdd ? `
      <button onclick="window.Ticker.ActionSetEditor.handlers.addAction(window.Ticker._adminPanel, '${escId}')"
        style="display:flex;align-items:center;gap:6px;padding:8px 12px;border:1px dashed var(--ticker-500,#06b6d4);border-radius:4px;background:transparent;color:var(--ticker-500,#06b6d4);cursor:pointer;font-size:13px;width:100%;justify-content:center">
        + Add action button
      </button>
    ` : '';

    const saveBtn = actions.length > 0 ? `
      <button class="btn btn-primary" style="margin-top:8px"
        onclick="window.Ticker.ActionSetEditor.handlers.save(window.Ticker._adminPanel, '${escId}')">Save Actions</button>
    ` : '';

    const clearBtn = actionSet ? `
      <button class="btn btn-secondary" style="margin-top:8px;margin-left:6px"
        onclick="window.Ticker.ActionSetEditor.handlers.clear(window.Ticker._adminPanel, '${escId}')">Clear Actions</button>
    ` : '';

    return `
      <div>
        <div class="form-group">
          <label style="font-weight:500;margin-bottom:8px;display:block">Action buttons</label>
          <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-bottom:8px">
            Buttons shown on notifications. Max 3.
          </div>
          ${actionSlots}
          ${addBtn}
          <div style="display:flex;gap:0">${saveBtn}${clearBtn}</div>
        </div>
      </div>
    `;
  },

  /** Read current DOM input values back into cat.action_set.actions. */
  _syncFromDom(panel, categoryId) {
    const cat = panel._categories.find(c => c.id === categoryId);
    if (!cat || !cat.action_set || !cat.action_set.actions) return;
    const root = panel.shadowRoot;
    cat.action_set.actions.forEach((a, i) => {
      const titleEl = root.getElementById(`action-title-${categoryId}-${i}`);
      if (titleEl) a.title = titleEl.value.trim();
      const typeEl = root.getElementById(`action-type-${categoryId}-${i}`);
      if (typeEl) a.type = typeEl.value;
      if (a.type === 'script') {
        const scriptEl = root.getElementById(`action-script-${categoryId}-${i}`);
        if (scriptEl) a.script_entity = scriptEl.value;
      }
      if (a.type === 'snooze') {
        const snoozeEl = root.getElementById(`action-snooze-${categoryId}-${i}`);
        if (snoozeEl) a.snooze_minutes = parseInt(snoozeEl.value || '30', 10);
      }
    });
  },

  handlers: {
    addAction(panel, categoryId) {
      const cat = panel._categories.find(c => c.id === categoryId);
      if (!cat) return;
      if (!cat.action_set) cat.action_set = { actions: [] };
      if (!cat.action_set.actions) cat.action_set.actions = [];
      if (cat.action_set.actions.length >= 3) return;

      window.Ticker.ActionSetEditor._syncFromDom(panel, categoryId);
      cat.action_set.actions.push({
        title: '',
        type: 'dismiss',
        index: cat.action_set.actions.length,
      });
      panel._renderTabContentPreserveScroll();
    },

    removeAction(panel, categoryId, index) {
      const cat = panel._categories.find(c => c.id === categoryId);
      if (!cat || !cat.action_set) return;
      window.Ticker.ActionSetEditor._syncFromDom(panel, categoryId);
      cat.action_set.actions.splice(index, 1);
      cat.action_set.actions.forEach((a, i) => { a.index = i; });
      panel._renderTabContentPreserveScroll();
    },

    typeChanged(panel, categoryId, index, newType) {
      const cat = panel._categories.find(c => c.id === categoryId);
      if (!cat || !cat.action_set) return;
      window.Ticker.ActionSetEditor._syncFromDom(panel, categoryId);
      const action = cat.action_set.actions[index];
      if (!action) return;
      action.type = newType;
      delete action.script_entity;
      delete action.snooze_minutes;
      if (newType === 'snooze') action.snooze_minutes = 30;
      panel._renderTabContentPreserveScroll();
    },

    async save(panel, categoryId) {
      const cat = panel._categories.find(c => c.id === categoryId);
      if (!cat || !cat.action_set) return;

      window.Ticker.ActionSetEditor._syncFromDom(panel, categoryId);
      const actions = cat.action_set.actions;

      // Client-side validation
      for (const a of actions) {
        if (!a.title) { panel._showError('Action title required'); return; }
        if (a.type === 'script' && !a.script_entity) { panel._showError('Select a script'); return; }
      }

      try {
        await panel._hass.callWS({
          type: 'ticker/category/set_action_set',
          category_id: categoryId,
          action_set: { actions },
        });
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Actions saved');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async clear(panel, categoryId) {
      if (!confirm('Remove all action buttons from this category?')) return;
      try {
        await panel._hass.callWS({
          type: 'ticker/category/set_action_set',
          category_id: categoryId,
          action_set: null,
        });
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Actions cleared');
      } catch (err) {
        panel._showError(err.message);
      }
    },
  },
};
