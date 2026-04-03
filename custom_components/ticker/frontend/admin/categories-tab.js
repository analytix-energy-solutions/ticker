/**
 * Ticker Admin Panel - Categories Tab
 * Handles category management with inner sub-tabs per category.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminCategoriesTab = {
  render(state) {
    const { categories, users, subscriptions, editingCategory, addingCategory } = state;

    const sorted = [...categories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    const items = sorted.map(c => this._renderCategoryItem(state, c)).join('');
    const addItem = this._renderNewCategoryItem(state);

    return `
      <div class="card">
        <h2 class="card-title">Categories</h2>
        <p class="card-description">Click category to edit settings.</p>
        <div class="list">${items}${addItem}</div>
      </div>
    `;
  },

  _renderCategoryItem(state, c) {
    const { esc, escAttr } = window.Ticker.utils;
    const { users, subscriptions, editingCategory, editingCategorySubTab } = state;

    const escId = escAttr(c.id);
    const escName = esc(c.name || c.id);
    const escIcon = escAttr(c.icon || 'mdi:bell');
    const escColor = escAttr(c.color || window.Ticker.styles.brandPrimary);
    const expanded = editingCategory === c.id;

    const subCount = users.filter(u => u.enabled && this._isSubscribed(subscriptions, u.person_id, c.id)).length;
    const subText = `${subCount} subscriber${subCount !== 1 ? 's' : ''}`;
    const colorDot = c.color ? `<span class="color-indicator" style="background:${escColor}"></span>` : '';

    const expandIcon = `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    `;

    const headerStyle = `border-left:3px solid ${expanded ? 'var(--ticker-500)' : 'transparent'};background:${expanded ? 'var(--ticker-500-alpha-8)' : 'transparent'}`;

    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminCategoriesTab.handlers.startEdit(window.Ticker._adminPanel, '${escId}')" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            ${colorDot}
            <ha-icon icon="${escIcon}" style="--mdc-icon-size:18px"></ha-icon>
            ${escName}
            ${c.is_default ? '<span class="badge badge-outline">Default</span>' : ''}
            ${this._hasSmartConfig(c) ? '<span class="badge" style="background:var(--ticker-info)">Smart</span>' : ''}
          </span>
          <span class="list-item-subtitle">${subText}</span>
        </div>
        <div class="list-item-actions">${expandIcon}</div>
      </div>
    `;

    if (!expanded) {
      return `<div class="list-item">${header}</div>`;
    }

    const subTab = editingCategorySubTab || 'general';
    const tabBar = this._renderSubTabs(escId, subTab);
    let content = '';

    if (subTab === 'general') {
      content = this._renderGeneralTab(c, escId, escIcon, escColor);
    } else if (subTab === 'mode') {
      content = this._renderModeTab(c, escId);
    } else if (subTab === 'actions') {
      content = this._renderActionsTab(c, state);
    } else if (subTab === 'smart') {
      content = this._renderSmartTab(c, escId);
    }

    const accordion = `
      <div class="accordion-content" style="padding-top:0">
        ${tabBar}
        ${content}
        <div class="button-row">
          ${subTab === 'general' ? `<button class="btn btn-primary" onclick="window.Ticker.AdminCategoriesTab.handlers.save(window.Ticker._adminPanel, '${escId}')">Save</button>` : ''}
          <button class="btn btn-secondary" onclick="window.Ticker.AdminCategoriesTab.handlers.cancelEdit(window.Ticker._adminPanel)">Cancel</button>
          ${!c.is_default ? `<button class="btn btn-danger" onclick="window.Ticker.AdminCategoriesTab.handlers.delete(window.Ticker._adminPanel, '${escId}')">Delete</button>` : ''}
        </div>
      </div>
    `;

    return `<div class="list-item">${header}${accordion}</div>`;
  },

  _renderSubTabs(escId, activeTab) {
    const tabs = [
      { id: 'general', label: 'General' },
      { id: 'mode', label: 'Default Mode' },
      { id: 'actions', label: 'Actions' },
      { id: 'smart', label: 'Smart' },
    ];

    const btns = tabs.map(t => {
      const active = t.id === activeTab;
      const style = active
        ? 'color:var(--ticker-500);border-bottom:2px solid var(--ticker-500);font-weight:500'
        : 'color:var(--secondary-text-color,#727272);border-bottom:2px solid transparent';
      return `<button onclick="window.Ticker.AdminCategoriesTab.handlers.switchSubTab(window.Ticker._adminPanel, '${t.id}')"
        style="background:none;border:none;padding:8px 16px;cursor:pointer;font-size:13px;${style}">${t.label}</button>`;
    }).join('');

    return `<div style="display:flex;border-bottom:1px solid var(--divider,#e0e0e0);margin-bottom:12px">${btns}</div>`;
  },

  _renderGeneralTab(c, escId, escIcon, escColor) {
    const { escAttr } = window.Ticker.utils;
    const criticalChecked = c.critical ? 'checked' : '';
    return `
      <div class="form-row" style="padding-top:8px">
        <div class="form-group">
          <label>Name</label>
          <input type="text" id="edit-name-${escId}" value="${escAttr(c.name || '')}" style="min-width:180px">
        </div>
        <div class="form-group">
          <label>Icon</label>
          <input type="text" id="edit-icon-${escId}" value="${escIcon}" style="width:100px">
        </div>
        <div class="form-group">
          <label>Color</label>
          <input type="color" id="edit-color-${escId}" value="${escColor}">
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:12px">
        <label class="toggle" style="margin:0">
          <input type="checkbox" id="edit-critical-${escId}" ${criticalChecked}>
          <span class="toggle-slider"></span>
        </label>
        <div>
          <span style="font-size:13px;font-weight:500;color:var(--primary-text-color,#212121)">Critical notifications</span>
          <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:2px">
            Bypass Do Not Disturb and silent mode on recipients' devices
          </div>
        </div>
      </div>
      ${window.Ticker.NavigationPicker.render(c.navigate_to || '', 'cat-edit', { panels: window.Ticker._adminPanel._hasPanels || [], dashboards: window.Ticker._adminPanel._lovelaceDashboards || [], views: window.Ticker._adminPanel._lovelaceViews || {} })}
    `;
  },

  _renderModeTab(c, escId) {
    const panel = window.Ticker._adminPanel;
    const defaultMode = panel._pendingDefaultMode || c.default_mode || 'always';
    const hasConditions = defaultMode === 'conditional';

    return `
      <div style="padding-top:8px">
        <div class="form-group">
          <label>Default subscription mode</label>
          <select id="edit-default-mode-${escId}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)"
            onchange="window.Ticker.AdminCategoriesTab.handlers.defaultModeChanged(window.Ticker._adminPanel, '${escId}', this.value)">
            <option value="always" ${defaultMode === 'always' ? 'selected' : ''}>Always</option>
            <option value="never" ${defaultMode === 'never' ? 'selected' : ''}>Never</option>
            <option value="conditional" ${defaultMode === 'conditional' ? 'selected' : ''}>Conditional</option>
          </select>
          <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:4px">
            Pre-populates for new users. Users can change this afterwards.
          </div>
        </div>
        ${hasConditions ? `
          <div class="form-group" style="margin-top:8px">
            <label>Default conditions</label>
            <ticker-conditions-ui id="cat-conditions-ui-${escId}"></ticker-conditions-ui>
          </div>
        ` : ''}
        <div class="button-row" style="margin-top:12px">
          <button class="btn btn-primary" onclick="window.Ticker.AdminCategoriesTab.handlers.save(window.Ticker._adminPanel, '${escId}')">Save</button>
        </div>
      </div>
    `;
  },

  _renderActionsTab(c, state) {
    const { esc, escAttr } = window.Ticker.utils;
    const ns = 'window.Ticker.AdminCategoriesTab';
    const opts = (state.actionSets || []).map(as =>
      `<option value="${escAttr(as.id)}" ${c.action_set_id === as.id ? 'selected' : ''}>${esc(as.name)} (${as.actions.length} actions)</option>`
    ).join('');
    return `<div style="padding-top:8px"><div class="form-group" style="margin-bottom:12px">
      <label>Default Action Set</label>
      <select id="cat-action-set-${escAttr(c.id)}" class="form-select" style="width:100%;box-sizing:border-box"
        onchange="${ns}.handlers.saveActionSetId(window.Ticker._adminPanel,'${escAttr(c.id)}',this.value)">
        <option value="">None (no action buttons)</option>${opts}</select>
      <p style="margin:4px 0 0;font-size:12px;color:var(--secondary-text-color)">
        Select an action set from the library. Manage action sets in the Action Sets tab.</p>
    </div></div>`;
  },

  _hasSmartConfig(c) {
    const s = c.smart_notification;
    return s && (s.group || (s.tag_mode && s.tag_mode !== 'none') || s.sticky || s.persistent);
  },

  _renderSmartTab(c, escId) {
    const s = c.smart_notification || {};
    const group = !!s.group;
    const tagMode = s.tag_mode || 'none';
    const sticky = !!s.sticky;
    const persistent = !!s.persistent;
    const stickyForced = persistent;
    const stickyChecked = sticky || persistent;
    const ns = 'window.Ticker.AdminCategoriesTab';

    return `
      <div style="padding-top:8px">
        <div style="font-size:14px;font-weight:600;color:var(--primary-text-color,#212121);margin-bottom:12px">Smart Delivery</div>

        <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--divider,#e0e0e0)">
          <label class="toggle" style="margin:0">
            <input type="checkbox" id="smart-group-${escId}" ${group ? 'checked' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <div>
            <span style="font-size:13px;font-weight:500;color:var(--primary-text-color,#212121)">Group notifications</span>
            <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:2px">
              Group all notifications from this category together in the notification shade.
            </div>
          </div>
        </div>

        <div style="padding:10px 0;border-bottom:1px solid var(--divider,#e0e0e0)">
          <div class="form-group">
            <label>Notification replacement</label>
            <select id="smart-tag-mode-${escId}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)">
              <option value="none" ${tagMode === 'none' ? 'selected' : ''}>None</option>
              <option value="category" ${tagMode === 'category' ? 'selected' : ''}>Per category</option>
              <option value="title" ${tagMode === 'title' ? 'selected' : ''}>Per title</option>
            </select>
          </div>
        </div>

        <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--divider,#e0e0e0)">
          <label class="toggle" style="margin:0${stickyForced ? ';opacity:0.5;pointer-events:none' : ''}">
            <input type="checkbox" id="smart-sticky-${escId}" ${stickyChecked ? 'checked' : ''} ${stickyForced ? 'disabled' : ''}>
            <span class="toggle-slider"></span>
          </label>
          <div>
            <span style="font-size:13px;font-weight:500;color:var(--primary-text-color,#212121)">Sticky (keep visible)</span>
            <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:2px">
              Cannot be swiped away on device.${stickyForced ? ' Forced on by Persistent.' : ''}
            </div>
          </div>
        </div>

        <div style="display:flex;align-items:center;gap:10px;padding:10px 0">
          <label class="toggle" style="margin:0">
            <input type="checkbox" id="smart-persistent-${escId}" ${persistent ? 'checked' : ''}
              onchange="${ns}.handlers.persistentChanged(window.Ticker._adminPanel, '${escId}')">
            <span class="toggle-slider"></span>
          </label>
          <div>
            <span style="font-size:13px;font-weight:500;color:var(--primary-text-color,#212121)">Persistent</span>
            <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:2px">
              Cannot be dismissed. Requires <code>ticker.clear_notification</code> to remove.
            </div>
          </div>
        </div>
        ${persistent ? `
          <div class="warning-banner">
            <ha-icon icon="mdi:alert" style="--mdc-icon-size:16px;color:var(--ticker-warning-dark)"></ha-icon>
            Persistent notifications cannot be dismissed by the user. Use with caution.
          </div>
        ` : ''}

        <div class="button-row" style="margin-top:16px">
          <button class="btn btn-primary" onclick="${ns}.handlers.saveSmart(window.Ticker._adminPanel, '${escId}')">Save</button>
        </div>
      </div>
    `;
  },

  _renderNewCategoryItem(state) {
    const expanded = state.addingCategory;
    const expandIcon = `<svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6,9 12,15 18,9"></polyline></svg>`;
    const headerStyle = `border-left:3px solid ${expanded ? 'var(--ticker-500)' : 'transparent'};background:${expanded ? 'var(--ticker-500-alpha-8)' : 'transparent'}`;
    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminCategoriesTab.handlers.toggleAdd(window.Ticker._adminPanel)" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            <ha-icon icon="mdi:plus-circle-outline" style="--mdc-icon-size:18px;color:var(--ticker-500)"></ha-icon>
            <span style="color:var(--ticker-500)">Add new category</span>
          </span>
        </div>
        <div class="list-item-actions">${expandIcon}</div>
      </div>`;
    if (!expanded) return `<div class="list-item">${header}</div>`;
    const selStyle = 'padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)';
    const accordion = `
      <div class="accordion-content">
        <div class="form-row" style="padding-top:12px">
          <div class="form-group"><label>Name</label><input type="text" id="new-category-name" placeholder="e.g. Security" style="min-width:180px"></div>
          <div class="form-group"><label>Icon</label><input type="text" id="new-category-icon" placeholder="mdi:bell" style="width:100px"></div>
          <div class="form-group"><label>Color</label><input type="color" id="new-category-color" value="${window.Ticker.styles.brandPrimary}"></div>
          <div class="form-group"><label>Default Mode</label>
            <select id="new-category-default-mode" style="${selStyle}">
              <option value="always" selected>Always</option><option value="never">Never</option><option value="conditional">Conditional</option>
            </select></div>
        </div>
        <div class="button-row">
          <button class="btn btn-primary" onclick="window.Ticker.AdminCategoriesTab.handlers.create(window.Ticker._adminPanel)">Create Category</button>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminCategoriesTab.handlers.cancelEdit(window.Ticker._adminPanel)">Cancel</button>
        </div>
      </div>`;
    return `<div class="list-item">${header}${accordion}</div>`;
  },

  _isSubscribed(subscriptions, personId, categoryId) {
    const s = subscriptions[personId];
    return s && s[categoryId] ? s[categoryId].mode !== 'never' : true;
  },

  handlers: {
    toggleAdd(panel) {
      panel._addingCategory = !panel._addingCategory;
      panel._editingCategory = null;
      panel._renderTabContentPreserveScroll();
    },

    startEdit(panel, categoryId) {
      if (panel._editingCategory === categoryId) {
        panel._editingCategory = null;
      } else {
        panel._editingCategory = categoryId;
        panel._editingCategorySubTab = 'general';
      }
      panel._addingCategory = false;
      panel._pendingDefaultMode = null;
      panel._pendingDefaultConditions = null;
      panel._renderTabContentPreserveScroll();
    },

    switchSubTab(panel, subTab) {
      panel._editingCategorySubTab = subTab;
      panel._renderTabContentPreserveScroll();
    },

    cancelEdit(panel) {
      panel._editingCategory = null;
      panel._addingCategory = false;
      panel._pendingDefaultConditions = null;
      panel._pendingDefaultMode = null;
      panel._renderTabContentPreserveScroll();
    },

    defaultModeChanged(panel, categoryId, mode) {
      // Store pending mode on the panel, NOT on the category object.
      // This prevents stale in-memory mutation if the user cancels the edit.
      panel._pendingDefaultMode = mode;
      if (mode === 'conditional') {
        const cat = panel._categories.find(c => c.id === categoryId);
        if (cat && !cat.default_conditions && !panel._pendingDefaultConditions) {
          panel._pendingDefaultConditions = {
            deliver_when_met: true,
            queue_until_met: true,
            condition_tree: { type: 'group', operator: 'AND', children: [{ type: 'zone', zone_id: 'zone.home' }] },
          };
        }
      } else {
        panel._pendingDefaultConditions = null;
      }
      panel._renderTabContentPreserveScroll();
    },

    async create(panel) {
      const { generateCategoryId } = window.Ticker.utils;
      const name = panel.shadowRoot.getElementById('new-category-name')?.value?.trim();
      const icon = panel.shadowRoot.getElementById('new-category-icon')?.value?.trim() || 'mdi:bell';
      const color = panel.shadowRoot.getElementById('new-category-color')?.value || null;
      const defaultMode = panel.shadowRoot.getElementById('new-category-default-mode')?.value || 'always';

      if (!name) { panel._showError('Enter a category name'); return; }
      const id = generateCategoryId(name);
      if (!id) { panel._showError('Invalid name'); return; }

      try {
        const params = { type: 'ticker/category/create', category_id: id, name, icon, color };
        if (defaultMode !== 'always') { params.default_mode = defaultMode; }
        await panel._hass.callWS(params);
        panel._addingCategory = false;
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Category created');
      } catch (err) { panel._showError(err.message); }
    },

    async save(panel, categoryId) {
      const cat = panel._categories.find(c => c.id === categoryId);
      if (!cat) return;

      // Fall back to existing category values when inputs are on a different sub-tab
      const nameEl = panel.shadowRoot.getElementById(`edit-name-${categoryId}`);
      const name = nameEl ? nameEl.value.trim() : cat.name;
      const iconEl = panel.shadowRoot.getElementById(`edit-icon-${categoryId}`);
      const icon = iconEl ? iconEl.value.trim() : cat.icon;
      const colorEl = panel.shadowRoot.getElementById(`edit-color-${categoryId}`);
      const color = colorEl ? colorEl.value : (cat.color || null);
      const defaultModeEl = panel.shadowRoot.getElementById(`edit-default-mode-${categoryId}`);
      const defaultMode = defaultModeEl?.value || (cat.default_mode || 'always');
      const criticalEl = panel.shadowRoot.getElementById(`edit-critical-${categoryId}`);

      if (!name) { panel._showError('Name required'); return; }

      try {
        const params = { type: 'ticker/category/update', category_id: categoryId, name, icon, color };
        if (criticalEl) { params.critical = criticalEl.checked; }
        // Only read navigate_to when the picker is in the DOM (General sub-tab).
        // Omitting it lets the backend's sparse update preserve the existing value.
        const navPresetEl = panel.shadowRoot.getElementById('nav-preset-cat-edit');
        if (navPresetEl) {
          params.navigate_to = window.Ticker.NavigationPicker.read(panel.shadowRoot, 'cat-edit');
        }

        if (defaultMode === 'conditional') {
          params.default_mode = 'conditional';
          params.default_conditions = panel._pendingDefaultConditions || null;
        } else if (defaultMode === 'never') {
          params.default_mode = 'never';
        } else {
          params.default_mode = null;
        }

        await panel._hass.callWS(params);
        panel._pendingDefaultConditions = null;
        panel._pendingDefaultMode = null;
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Updated');
      } catch (err) { panel._showError(err.message); }
    },

    persistentChanged(panel, categoryId) {
      panel._renderTabContentPreserveScroll();
    },

    async saveSmart(panel, categoryId) {
      const root = panel.shadowRoot;
      const group = root.getElementById(`smart-group-${categoryId}`)?.checked || false;
      const tagMode = root.getElementById(`smart-tag-mode-${categoryId}`)?.value || 'none';
      const persistent = root.getElementById(`smart-persistent-${categoryId}`)?.checked || false;
      const stickyEl = root.getElementById(`smart-sticky-${categoryId}`);
      const sticky = persistent || (stickyEl?.checked || false);

      try {
        await panel._hass.callWS({
          type: 'ticker/category/update',
          category_id: categoryId,
          smart_notification: { group, tag_mode: tagMode, sticky, persistent },
        });
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Smart delivery updated');
      } catch (err) { panel._showError(err.message); }
    },

    async saveActionSetId(panel, categoryId, actionSetId) {
      try {
        await panel._hass.callWS({
          type: 'ticker/category/update',
          category_id: categoryId,
          action_set_id: actionSetId || '',  // empty string clears
        });
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Action set updated');
      } catch (e) {
        panel._showError(e.message || 'Failed to update action set');
      }
    },

    async delete(panel, categoryId) {
      if (!confirm('Delete category?')) return;
      try {
        await panel._hass.callWS({ type: 'ticker/category/delete', category_id: categoryId });
        await panel._loadCategories();
        panel._renderTabContentPreserveScroll();
      } catch (err) { panel._showError(err.message); }
    },
  },
};
