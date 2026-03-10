/**
 * Ticker Admin Panel - Categories Tab
 * Handles category management.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminCategoriesTab = {
  /**
   * Render the categories tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, escAttr } = window.Ticker.utils;
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
        <div class="list">
          ${items}
          ${addItem}
        </div>
      </div>
    `;
  },

  /**
   * Render a single category item.
   * @param {Object} state - Panel state
   * @param {Object} c - Category object
   * @returns {string} - HTML string
   */
  _renderCategoryItem(state, c) {
    const { esc, escAttr } = window.Ticker.utils;
    const { categories, users, subscriptions, editingCategory } = state;

    const escId = escAttr(c.id);
    const escName = esc(c.name || c.id);
    const escIcon = escAttr(c.icon || 'mdi:bell');
    const escColor = escAttr(c.color || '#06b6d4');
    const expanded = editingCategory === c.id;

    // Calculate subscriber count
    const subCount = users.filter(u => this._isSubscribed(subscriptions, u.person_id, c.id)).length;
    const subText = `${subCount} subscriber${subCount !== 1 ? 's' : ''}`;

    const colorDot = c.color ? `<span class="color-indicator" style="background:${escColor}"></span>` : '';

    const expandIcon = `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    `;

    const headerStyle = `border-left:3px solid ${expanded ? 'var(--ticker-500)' : 'transparent'};background:${expanded ? 'rgba(6,182,212,0.08)' : 'transparent'}`;

    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminCategoriesTab.handlers.startEdit(window.Ticker._adminPanel, '${escId}')" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            ${colorDot}
            <ha-icon icon="${escIcon}" style="--mdc-icon-size:18px"></ha-icon>
            ${escName}
            ${c.is_default ? '<span class="badge badge-outline">Default</span>' : ''}
          </span>
          <span class="list-item-subtitle">${subText}</span>
        </div>
        <div class="list-item-actions">
          ${expandIcon}
        </div>
      </div>
    `;

    if (!expanded) {
      return `<div class="list-item">${header}</div>`;
    }

    const defaultMode = c.default_mode || 'always';
    const hasDefaultConditions = defaultMode === 'conditional';

    const accordion = `
      <div class="accordion-content">
        <div class="form-row" style="padding-top:12px">
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
        <div style="padding-top:12px;border-top:1px solid var(--divider,#e0e0e0);margin-top:12px">
          <div class="form-group">
            <label>Default subscription mode</label>
            <select id="edit-default-mode-${escId}" style="padding:6px 10px;border:1px solid var(--divider,#e0e0e0);border-radius:4px;font-size:13px;background:var(--card-background-color,#fff);color:var(--primary-text-color,#212121)"
              onchange="window.Ticker.AdminCategoriesTab.handlers.defaultModeChanged(window.Ticker._adminPanel, '${escId}', this.value)">
              <option value="always" ${defaultMode === 'always' ? 'selected' : ''}>Always</option>
              <option value="conditional" ${defaultMode === 'conditional' ? 'selected' : ''}>Conditional</option>
            </select>
            <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:4px">
              Pre-populates for new users. Users can change this afterwards.
            </div>
          </div>
          ${hasDefaultConditions ? `
            <div class="form-group" style="margin-top:8px">
              <label>Default conditions</label>
              <ticker-conditions-ui id="cat-conditions-ui-${escId}"></ticker-conditions-ui>
            </div>
          ` : ''}
        </div>
        <div class="button-row">
          <button class="btn btn-primary" onclick="window.Ticker.AdminCategoriesTab.handlers.save(window.Ticker._adminPanel, '${escId}')">Save</button>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminCategoriesTab.handlers.cancelEdit(window.Ticker._adminPanel)">Cancel</button>
          ${!c.is_default ? `<button class="btn btn-danger" onclick="window.Ticker.AdminCategoriesTab.handlers.delete(window.Ticker._adminPanel, '${escId}')">Delete</button>` : ''}
        </div>
      </div>
    `;

    return `<div class="list-item">${header}${accordion}</div>`;
  },

  /**
   * Render the add new category item.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  _renderNewCategoryItem(state) {
    const expanded = state.addingCategory;

    const expandIcon = `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    `;

    const headerStyle = `border-left:3px solid ${expanded ? 'var(--ticker-500)' : 'transparent'};background:${expanded ? 'rgba(6,182,212,0.08)' : 'transparent'}`;

    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminCategoriesTab.handlers.toggleAdd(window.Ticker._adminPanel)" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            <ha-icon icon="mdi:plus-circle-outline" style="--mdc-icon-size:18px;color:var(--ticker-500)"></ha-icon>
            <span style="color:var(--ticker-500)">Add new category</span>
          </span>
        </div>
        <div class="list-item-actions">
          ${expandIcon}
        </div>
      </div>
    `;

    if (!expanded) {
      return `<div class="list-item">${header}</div>`;
    }

    const accordion = `
      <div class="accordion-content">
        <div class="form-row" style="padding-top:12px">
          <div class="form-group">
            <label>Name</label>
            <input type="text" id="new-category-name" placeholder="e.g. Security" style="min-width:180px">
          </div>
          <div class="form-group">
            <label>Icon</label>
            <input type="text" id="new-category-icon" placeholder="mdi:bell" style="width:100px">
          </div>
          <div class="form-group">
            <label>Color</label>
            <input type="color" id="new-category-color" value="#06b6d4">
          </div>
        </div>
        <div class="button-row">
          <button class="btn btn-primary" onclick="window.Ticker.AdminCategoriesTab.handlers.create(window.Ticker._adminPanel)">Create Category</button>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminCategoriesTab.handlers.cancelEdit(window.Ticker._adminPanel)">Cancel</button>
        </div>
      </div>
    `;

    return `<div class="list-item">${header}${accordion}</div>`;
  },

  /**
   * Check if user is subscribed to category.
   * @param {Object} subscriptions - Subscriptions map
   * @param {string} personId - Person ID
   * @param {string} categoryId - Category ID
   * @returns {boolean}
   */
  _isSubscribed(subscriptions, personId, categoryId) {
    const s = subscriptions[personId];
    return s && s[categoryId] ? s[categoryId].mode !== 'never' : true;
  },

  /**
   * Handler methods.
   */
  handlers: {
    toggleAdd(panel) {
      panel._addingCategory = !panel._addingCategory;
      panel._editingCategory = null;
      panel._renderTabContent();
    },

    startEdit(panel, categoryId) {
      panel._editingCategory = panel._editingCategory === categoryId ? null : categoryId;
      panel._addingCategory = false;
      panel._renderTabContent();
    },

    cancelEdit(panel) {
      panel._editingCategory = null;
      panel._addingCategory = false;
      panel._pendingDefaultConditions = null;
      panel._renderTabContent();
    },

    defaultModeChanged(panel, categoryId, mode) {
      // Update the category object temporarily for re-render
      const cat = panel._categories.find(c => c.id === categoryId);
      if (cat) {
        cat.default_mode = mode;
        if (mode === 'conditional' && !cat.default_conditions) {
          // Set initial default conditions
          cat.default_conditions = {
            deliver_when_met: true,
            queue_until_met: true,
            rules: [{ type: 'zone', zone_id: 'zone.home' }],
          };
          panel._pendingDefaultConditions = cat.default_conditions;
        } else if (mode === 'always') {
          panel._pendingDefaultConditions = null;
        }
      }
      panel._renderTabContent();
    },

    async create(panel) {
      const { generateCategoryId } = window.Ticker.utils;
      const name = panel.shadowRoot.getElementById('new-category-name')?.value?.trim();
      const icon = panel.shadowRoot.getElementById('new-category-icon')?.value?.trim() || 'mdi:bell';
      const color = panel.shadowRoot.getElementById('new-category-color')?.value || null;

      if (!name) {
        panel._showError('Enter a category name');
        return;
      }

      const id = generateCategoryId(name);
      if (!id) {
        panel._showError('Invalid name');
        return;
      }

      try {
        await panel._hass.callWS({
          type: 'ticker/category/create',
          category_id: id,
          name: name,
          icon: icon,
          color: color,
        });
        panel._addingCategory = false;
        await panel._loadCategories();
        panel._renderTabContent();
        panel._showSuccess('Category created');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async save(panel, categoryId) {
      const name = panel.shadowRoot.getElementById(`edit-name-${categoryId}`)?.value?.trim();
      const icon = panel.shadowRoot.getElementById(`edit-icon-${categoryId}`)?.value?.trim();
      const color = panel.shadowRoot.getElementById(`edit-color-${categoryId}`)?.value || null;
      const defaultModeEl = panel.shadowRoot.getElementById(`edit-default-mode-${categoryId}`);
      const defaultMode = defaultModeEl?.value || 'always';

      if (!name) {
        panel._showError('Name required');
        return;
      }

      try {
        const params = {
          type: 'ticker/category/update',
          category_id: categoryId,
          name: name,
          icon: icon,
          color: color,
        };

        if (defaultMode === 'conditional') {
          params.default_mode = 'conditional';
          params.default_conditions = panel._pendingDefaultConditions || null;
        } else {
          // Clear defaults by sending null
          params.default_mode = null;
        }

        await panel._hass.callWS(params);
        panel._editingCategory = null;
        panel._pendingDefaultConditions = null;
        await panel._loadCategories();
        panel._renderTabContent();
        panel._showSuccess('Updated');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async delete(panel, categoryId) {
      if (!confirm('Delete category?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/category/delete',
          category_id: categoryId,
        });
        await panel._loadCategories();
        panel._renderTabContent();
      } catch (err) {
        panel._showError(err.message);
      }
    },
  },
};
