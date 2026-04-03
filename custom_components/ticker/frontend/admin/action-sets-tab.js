/**
 * Ticker Admin Panel - Action Sets Tab (F-5b)
 * Library of reusable action set definitions.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminActionSetsTab = {
  render(state) {
    const { actionSets } = state;
    if (!actionSets || actionSets.length === 0) {
      if (state.editingActionSetId === '__new__') {
        return `
          <div class="card">
            <h2 class="card-title">Action Sets</h2>
            <p class="card-description">Reusable action button sets that can be assigned to categories.</p>
            ${this._renderNewForm()}
          </div>
        `;
      }
      return this._renderEmpty();
    }
    return this._renderList(state);
  },

  _renderEmpty() {
    const ns = 'window.Ticker.AdminActionSetsTab';
    return `
      <div class="card">
        <h2 class="card-title">Action Sets</h2>
        <p class="card-description">Reusable action button sets that can be assigned to categories.</p>
        <div style="text-align:center;padding:32px 16px">
          <ha-icon icon="mdi:gesture-tap-button" style="--mdc-icon-size:48px;color:var(--secondary-text-color,#727272);opacity:0.5"></ha-icon>
          <p style="color:var(--secondary-text-color,#727272);margin:12px 0 16px">No action sets yet. Create one to get started.</p>
          <button class="btn btn-primary" onclick="${ns}.handlers.create(window.Ticker._adminPanel)">Create Action Set</button>
        </div>
      </div>
    `;
  },

  _renderList(state) {
    const ns = 'window.Ticker.AdminActionSetsTab';
    const sorted = [...state.actionSets].sort((a, b) =>
      (a.name || a.id).localeCompare(b.name || b.id)
    );
    const items = sorted.map((as, i) => this._renderItem(state, as, i)).join('');
    const isCreating = state.editingActionSetId === '__new__';

    const newFormOrAddBtn = isCreating ? this._renderNewForm() : `
      <div class="list-item">
        <div class="list-item-header" onclick="${ns}.handlers.create(window.Ticker._adminPanel)"
          style="border-left:3px solid transparent;background:transparent">
          <div class="list-item-content">
            <span class="list-item-title">
              <ha-icon icon="mdi:plus-circle-outline" style="--mdc-icon-size:18px;color:var(--ticker-500)"></ha-icon>
              <span style="color:var(--ticker-500)">Add new action set</span>
            </span>
          </div>
        </div>
      </div>
    `;

    return `
      <div class="card">
        <h2 class="card-title">Action Sets</h2>
        <p class="card-description">Reusable action button sets that can be assigned to categories.</p>
        <div class="list">
          ${isCreating ? newFormOrAddBtn : ''}
          ${items}
          ${isCreating ? '' : newFormOrAddBtn}
        </div>
      </div>
    `;
  },

  _renderNewForm() {
    const ns = 'window.Ticker.AdminActionSetsTab';
    return `
      <div class="list-item" style="border-left:3px solid var(--ticker-500);background:var(--ticker-500-alpha-8)">
        <div style="padding:12px 16px">
          <label style="font-weight:500;display:block;margin-bottom:6px">New action set</label>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input type="text" id="as-new-name" placeholder="Action set name"
              style="flex:1;min-width:180px;padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
            <button class="btn btn-primary" onclick="${ns}.handlers.confirmCreate(window.Ticker._adminPanel)">Create</button>
            <button class="btn btn-secondary" onclick="${ns}.handlers.cancelCreate(window.Ticker._adminPanel)">Cancel</button>
          </div>
        </div>
      </div>
    `;
  },

  _renderItem(state, actionSet, index) {
    const { esc, escAttr } = window.Ticker.utils;
    const ns = 'window.Ticker.AdminActionSetsTab';
    const escId = escAttr(actionSet.id);
    const escName = esc(actionSet.name || actionSet.id);
    const actionCount = (actionSet.actions || []).length;
    const expanded = state.editingActionSetId === actionSet.id;

    // Find which categories use this action set
    const usingCategories = (state.categories || [])
      .filter(c => c.action_set_id === actionSet.id)
      .map(c => c.name || c.id);
    const usedByText = usingCategories.length > 0
      ? `Used by: ${usingCategories.map(n => esc(n)).join(', ')}`
      : 'Not assigned';

    const expandIcon = `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    `;

    const headerStyle = `border-left:3px solid ${expanded ? 'var(--ticker-500)' : 'transparent'};background:${expanded ? 'var(--ticker-500-alpha-8)' : 'transparent'}`;

    const header = `
      <div class="list-item-header" onclick="${ns}.handlers.${expanded ? 'collapse' : 'expand'}(window.Ticker._adminPanel, '${escId}')" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            <ha-icon icon="mdi:gesture-tap-button" style="--mdc-icon-size:18px"></ha-icon>
            ${escName}
          </span>
          <span class="list-item-subtitle">${actionCount} action${actionCount !== 1 ? 's' : ''} &middot; ${usedByText}</span>
        </div>
        <div class="list-item-actions">${expandIcon}</div>
      </div>
    `;

    if (!expanded) {
      return `<div class="list-item">${header}</div>`;
    }

    const accordion = `
      <div class="accordion-content" style="padding-top:0">
        ${this._renderExpandedEditor(state, actionSet)}
      </div>
    `;

    return `<div class="list-item">${header}${accordion}</div>`;
  },

  _renderExpandedEditor(state, actionSet) {
    const { esc, escAttr } = window.Ticker.utils;
    const ns = 'window.Ticker.AdminActionSetsTab';
    const escId = escAttr(actionSet.id);
    const escName = escAttr(actionSet.name || '');
    const escDesc = escAttr(actionSet.description || '');
    const scripts = state.scripts || [];

    const actionsHtml = this._renderActionsEditor(actionSet, scripts);

    return `
      <div style="padding:12px 0">
        <div class="form-row" style="align-items:flex-start">
          <div class="form-group">
            <label>ID</label>
            <span style="font-size:13px;color:var(--secondary-text-color,#727272);font-family:monospace">${esc(actionSet.id)}</span>
          </div>
          <div class="form-group">
            <label>Name</label>
            <input type="text" id="as-name-${escId}" value="${escName}" style="min-width:180px">
          </div>
          <div class="form-group">
            <label>Description</label>
            <input type="text" id="as-desc-${escId}" value="${escDesc}" placeholder="Optional description" style="min-width:200px">
          </div>
        </div>
        <div style="margin-top:12px">
          <label style="font-weight:500;margin-bottom:8px;display:block">Action buttons</label>
          <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-bottom:8px">
            Buttons shown on notifications. Max 3.
          </div>
          <div id="as-actions-${escId}">
            ${actionsHtml}
          </div>
        </div>
        <div class="button-row" style="margin-top:12px">
          <button class="btn btn-primary" onclick="${ns}.handlers.save(window.Ticker._adminPanel, '${escId}')">Save</button>
          <button class="btn btn-secondary" onclick="${ns}.handlers.collapse(window.Ticker._adminPanel)">Cancel</button>
          <button class="btn btn-danger" onclick="${ns}.handlers.remove(window.Ticker._adminPanel, '${escId}')">Delete</button>
        </div>
      </div>
    `;
  },

  /**
   * Render the actions editor inline for an action set.
   * Adapts the same UI pattern as ActionSetEditor but scoped to library entries.
   */
  _renderActionsEditor(actionSet, scripts) {
    const { esc, escAttr } = window.Ticker.utils;
    const ns = 'window.Ticker.AdminActionSetsTab';
    const escId = escAttr(actionSet.id);
    const actions = actionSet.actions || [];

    const snoozeDurations = [
      { value: 15, label: '15 min' },
      { value: 30, label: '30 min' },
      { value: 60, label: '1 hour' },
      { value: 120, label: '2 hours' },
      { value: 240, label: '4 hours' },
    ];

    const slots = actions.map((action, i) => {
      const escTitle = escAttr(action.title || '');
      const type = action.type || 'dismiss';

      let typeField = '';
      if (type === 'script') {
        const opts = scripts.map(s =>
          `<option value="${escAttr(s.entity_id)}" ${s.entity_id === action.script_entity ? 'selected' : ''}>${esc(s.name || s.entity_id)}</option>`
        ).join('');
        typeField = `
          <select id="as-action-script-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121);min-width:180px">
            <option value="">Select script...</option>
            ${opts}
          </select>
        `;
      } else if (type === 'snooze') {
        const dOpts = snoozeDurations.map(d =>
          `<option value="${d.value}" ${d.value === action.snooze_minutes ? 'selected' : ''}>${esc(d.label)}</option>`
        ).join('');
        typeField = `
          <select id="as-action-snooze-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
            ${dOpts}
          </select>
        `;
      }

      return `
        <div class="action-slot" style="display:flex;gap:8px;align-items:center;padding:8px;background:var(--ticker-500-alpha-8);border-left:3px solid var(--ticker-500,#06b6d4);border-radius:4px;margin-bottom:6px">
          <input type="text" id="as-action-title-${escId}-${i}" value="${escTitle}" placeholder="Button label" style="flex:1;min-width:100px;padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
          <select id="as-action-type-${escId}-${i}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)"
            onchange="${ns}.handlers.actionTypeChanged(window.Ticker._adminPanel, '${escId}', ${i}, this.value)">
            <option value="script" ${type === 'script' ? 'selected' : ''}>Script</option>
            <option value="snooze" ${type === 'snooze' ? 'selected' : ''}>Snooze</option>
            <option value="dismiss" ${type === 'dismiss' ? 'selected' : ''}>Dismiss</option>
          </select>
          ${typeField}
          <button onclick="${ns}.handlers.removeAction(window.Ticker._adminPanel, '${escId}', ${i})"
            style="border:none;background:none;color:var(--error-color,#b71c1c);cursor:pointer;font-size:16px;padding:4px" title="Remove">&times;</button>
        </div>
      `;
    }).join('');

    const canAdd = actions.length < 3;
    const addBtn = canAdd ? `
      <button onclick="${ns}.handlers.addAction(window.Ticker._adminPanel, '${escId}')"
        style="display:flex;align-items:center;gap:6px;padding:8px 12px;border:1px dashed var(--ticker-500,#06b6d4);border-radius:4px;background:transparent;color:var(--ticker-500,#06b6d4);cursor:pointer;font-size:13px;width:100%;justify-content:center">
        + Add action button
      </button>
    ` : '';

    return `${slots}${addBtn}`;
  },

  /** Sync action input values from DOM back into the in-memory action set. */
  _syncActionsFromDom(panel, actionSetId) {
    const as = panel._actionSets.find(a => a.id === actionSetId);
    if (!as || !as.actions) return;
    const root = panel.shadowRoot;
    as.actions.forEach((a, i) => {
      const titleEl = root.getElementById(`as-action-title-${actionSetId}-${i}`);
      if (titleEl) a.title = titleEl.value.trim();
      const typeEl = root.getElementById(`as-action-type-${actionSetId}-${i}`);
      if (typeEl) a.type = typeEl.value;
      if (a.type === 'script') {
        const scriptEl = root.getElementById(`as-action-script-${actionSetId}-${i}`);
        if (scriptEl) a.script_entity = scriptEl.value;
      }
      if (a.type === 'snooze') {
        const snoozeEl = root.getElementById(`as-action-snooze-${actionSetId}-${i}`);
        if (snoozeEl) a.snooze_minutes = parseInt(snoozeEl.value || '30', 10);
      }
    });
  },

  handlers: {
    expand(panel, id) {
      panel._editingActionSetId = id;
      panel._renderTabContentPreserveScroll();
    },

    collapse(panel) {
      panel._editingActionSetId = null;
      panel._renderTabContentPreserveScroll();
    },

    create(panel) {
      panel._editingActionSetId = '__new__';
      panel._renderTabContent();
    },

    async confirmCreate(panel) {
      const root = panel.shadowRoot;
      const nameEl = root.getElementById('as-new-name');
      const name = nameEl ? nameEl.value.trim() : '';
      if (!name) { panel._showError('Name is required'); return; }

      const slug = window.Ticker.utils.generateCategoryId(name);
      if (!slug) { panel._showError('Invalid name for ID generation'); return; }

      try {
        await panel._hass.callWS({
          type: 'ticker/action_set/create',
          action_set_id: slug,
          name,
          actions: [],
          description: '',
        });
        await window.Ticker.AdminDataLoader.loadActionSets(panel);
        panel._editingActionSetId = slug;
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Action set created');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    cancelCreate(panel) {
      panel._editingActionSetId = null;
      panel._renderTabContentPreserveScroll();
    },

    async save(panel, id) {
      const tab = window.Ticker.AdminActionSetsTab;
      tab._syncActionsFromDom(panel, id);

      const root = panel.shadowRoot;
      const nameEl = root.getElementById(`as-name-${id}`);
      const descEl = root.getElementById(`as-desc-${id}`);
      const name = nameEl ? nameEl.value.trim() : '';
      const description = descEl ? descEl.value.trim() : '';

      if (!name) { panel._showError('Name is required'); return; }

      const as = panel._actionSets.find(a => a.id === id);
      const actions = as ? (as.actions || []) : [];

      // Validate actions
      for (const a of actions) {
        if (!a.title) { panel._showError('All actions need a title'); return; }
        if (a.type === 'script' && !a.script_entity) { panel._showError('Select a script for each script action'); return; }
      }

      try {
        await panel._hass.callWS({
          type: 'ticker/action_set/update',
          action_set_id: id,
          name,
          description,
          actions,
        });
        await window.Ticker.AdminDataLoader.loadActionSets(panel);
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Action set saved');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async remove(panel, id) {
      if (!confirm('Delete this action set?')) return;
      try {
        await panel._hass.callWS({
          type: 'ticker/action_set/delete',
          action_set_id: id,
        });
        panel._editingActionSetId = null;
        await window.Ticker.AdminDataLoader.loadActionSets(panel);
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Action set deleted');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    addAction(panel, actionSetId) {
      const as = panel._actionSets.find(a => a.id === actionSetId);
      if (!as) return;
      if (!as.actions) as.actions = [];
      if (as.actions.length >= 3) return;

      window.Ticker.AdminActionSetsTab._syncActionsFromDom(panel, actionSetId);
      as.actions.push({ title: '', type: 'dismiss', index: as.actions.length });
      panel._renderTabContentPreserveScroll();
    },

    removeAction(panel, actionSetId, index) {
      const as = panel._actionSets.find(a => a.id === actionSetId);
      if (!as || !as.actions) return;
      window.Ticker.AdminActionSetsTab._syncActionsFromDom(panel, actionSetId);
      as.actions.splice(index, 1);
      as.actions.forEach((a, i) => { a.index = i; });
      panel._renderTabContentPreserveScroll();
    },

    actionTypeChanged(panel, actionSetId, index, newType) {
      const as = panel._actionSets.find(a => a.id === actionSetId);
      if (!as || !as.actions) return;
      window.Ticker.AdminActionSetsTab._syncActionsFromDom(panel, actionSetId);
      const action = as.actions[index];
      if (!action) return;
      action.type = newType;
      delete action.script_entity;
      delete action.snooze_minutes;
      if (newType === 'snooze') action.snooze_minutes = 30;
      panel._renderTabContentPreserveScroll();
    },
  },
};
