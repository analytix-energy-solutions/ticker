/**
 * Ticker Admin Panel - Automations Tab (F-3)
 * Scan and edit ticker.notify calls in automations and scripts.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminAutomationsTab = {
  /**
   * Render the automations tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { automationsFindings, automationsScanning } = state;

    if (automationsScanning) {
      return this._renderScanningState();
    }

    if (!automationsFindings.length && !state._automationsScanned) {
      return this._renderInitialState();
    }

    if (!automationsFindings.length) {
      return this._renderNoFindingsState();
    }

    return this._renderFilterBar(state) + this._renderFindingsList(state);
  },

  /**
   * Render the initial state (before scanning).
   * @returns {string} - HTML string
   */
  _renderInitialState() {
    return `
      <div class="card">
        <h2 class="card-title">Automations Manager</h2>
        <div class="empty-state">
          <ha-icon icon="mdi:robot" style="--mdc-icon-size:48px;color:var(--ticker-500);margin-bottom:16px;display:block"></ha-icon>
          <p>Scan your automations and scripts to find all ticker.notify service calls.</p>
          <button class="btn btn-primary" onclick="window.Ticker.AdminAutomationsTab.handlers.scan(window.Ticker._adminPanel)">
            <ha-icon icon="mdi:magnify" style="--mdc-icon-size:18px;margin-right:6px"></ha-icon>Scan Automations
          </button>
        </div>
      </div>
    `;
  },

  /**
   * Render the scanning state.
   * @returns {string} - HTML string
   */
  _renderScanningState() {
    return `
      <div class="card">
        <h2 class="card-title">Automations Manager</h2>
        <div class="empty-state">
          <span class="spinner"></span>
          <span>Scanning automations and scripts...</span>
        </div>
      </div>
    `;
  },

  /**
   * Render the no findings state.
   * @returns {string} - HTML string
   */
  _renderNoFindingsState() {
    return `
      <div class="card">
        <h2 class="card-title">Automations Manager</h2>
        <div class="empty-state">
          <p>No ticker.notify calls found in your automations or scripts.</p>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminAutomationsTab.handlers.scan(window.Ticker._adminPanel)" style="margin-top:16px">Scan Again</button>
        </div>
      </div>
    `;
  },

  /**
   * Render the filter bar.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  _renderFilterBar(state) {
    const { esc, escAttr } = window.Ticker.utils;
    const { automationsFilter, categories } = state;
    const filtered = this._applyFilters(state.automationsFindings, automationsFilter, state.categories);

    const sortedCats = [...categories].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
    const catOptions = '<option value="">All categories</option>' +
      sortedCats.map(c => `<option value="${escAttr(c.id)}" ${automationsFilter.category === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('');

    const sourceOptions = `
      <option value="">All sources</option>
      <option value="automation" ${automationsFilter.sourceType === 'automation' ? 'selected' : ''}>Automations</option>
      <option value="script" ${automationsFilter.sourceType === 'script' ? 'selected' : ''}>Scripts</option>
    `;

    return `
      <div class="card" style="margin-bottom:16px">
        <div class="card-header">
          <h2 class="card-title">Automations Manager</h2>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminAutomationsTab.handlers.scan(window.Ticker._adminPanel)">
            <ha-icon icon="mdi:refresh" style="--mdc-icon-size:16px;margin-right:4px"></ha-icon>Rescan
          </button>
        </div>
        <div class="form-row" style="margin-bottom:8px">
          <div class="form-group">
            <label>Category</label>
            <select class="form-select" onchange="window.Ticker.AdminAutomationsTab.handlers.updateFilter(window.Ticker._adminPanel, 'category', this.value)">
              ${catOptions}
            </select>
          </div>
          <div class="form-group">
            <label>Source type</label>
            <select class="form-select" onchange="window.Ticker.AdminAutomationsTab.handlers.updateFilter(window.Ticker._adminPanel, 'sourceType', this.value)">
              ${sourceOptions}
            </select>
          </div>
        </div>
        <div style="font-size:13px;color:var(--text-secondary)">${filtered.length} of ${state.automationsFindings.length} findings</div>
      </div>
    `;
  },

  /**
   * Render the findings list.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  _renderFindingsList(state) {
    const filtered = this._applyFilters(state.automationsFindings, state.automationsFilter, state.categories);

    if (!filtered.length) {
      return '<div class="card"><div class="empty-state"><p>No findings match the current filters.</p></div></div>';
    }

    return '<div class="list">' +
      filtered.map((finding, index) => {
        const originalIndex = state.automationsFindings.indexOf(finding);
        if (state.automationsExpanded === originalIndex) {
          return this._renderExpandedForm(state, finding, originalIndex);
        }
        return this._renderFindingItem(state, finding, originalIndex);
      }).join('') +
      '</div>';
  },

  /**
   * Render a collapsed finding item.
   * @param {Object} state - Panel state
   * @param {Object} finding - The finding object
   * @param {number} index - Original index in findings array
   * @returns {string} - HTML string
   */
  _renderFindingItem(state, finding, index) {
    const { esc, escAttr } = window.Ticker.utils;
    const sd = finding.service_data || {};
    const catId = sd.category || '';
    const cat = state.categories.find(c => c.id === catId || c.name === catId);
    const categoryBadge = cat
      ? `<span class="badge" style="background:${escAttr(cat.color || 'var(--ticker-500)')}">${esc(cat.name)}</span>`
      : catId
        ? `<span class="badge badge-gray">${esc(catId)}</span>`
        : '';
    const icon = finding.source_type === 'automation' ? 'mdi:robot' : 'mdi:file-document-outline';

    return `
      <div class="list-item" style="cursor:pointer" onclick="window.Ticker.AdminAutomationsTab.handlers.expand(window.Ticker._adminPanel, ${index})">
        <div class="list-item-header">
          <div class="list-item-content">
            <div class="list-item-title">
              <ha-icon icon="${icon}" style="--mdc-icon-size:20px;margin-right:4px;flex-shrink:0"></ha-icon>
              ${esc(finding.source_name)}
            </div>
            <div class="list-item-subtitle">
              <span class="badge" style="font-size:10px">${esc(finding.source_type)}</span>
              ${categoryBadge}
              <span style="color:var(--text-secondary);font-size:12px">Action #${finding.action_index + 1}</span>
            </div>
          </div>
          <ha-icon icon="mdi:chevron-right" class="chevron" style="--mdc-icon-size:20px"></ha-icon>
        </div>
      </div>
    `;
  },

  /**
   * Render the expanded form for a finding.
   * @param {Object} state - Panel state
   * @param {Object} finding - The finding object
   * @param {number} index - Original index in findings array
   * @returns {string} - HTML string
   */
  _renderExpandedForm(state, finding, index) {
    const { esc, escAttr } = window.Ticker.utils;
    const sd = finding.service_data || {};
    const catId = sd.category || '';
    const icon = finding.source_type === 'automation' ? 'mdi:robot' : 'mdi:file-document-outline';

    // Build category options — match by id OR name (automations may use either)
    const sortedCats = [...state.categories].sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
    const matchCat = (c) => catId === c.id || catId === c.name;
    const hasMatch = catId && sortedCats.some(matchCat);
    const placeholder = hasMatch ? '' : '<option value="" disabled selected>Select a category...</option>';
    const catOptions = placeholder + sortedCats.map(c =>
      `<option value="${escAttr(c.id)}" ${matchCat(c) ? 'selected' : ''}>${esc(c.name)}</option>`
    ).join('');

    const isYaml = finding.source_file && !finding.source_file.includes('.storage');
    const yamlWarning = isYaml ? `
      <div class="warning-banner">
        <ha-icon icon="mdi:alert" style="--mdc-icon-size:18px;flex-shrink:0"></ha-icon>
        This automation lives in a YAML file. Ticker will create a backup before saving.
      </div>
    ` : '';

    return `
      <div class="list-item" style="border-left:3px solid var(--ticker-500)">
        <div class="list-item-header expanded" onclick="window.Ticker.AdminAutomationsTab.handlers.collapse(window.Ticker._adminPanel)">
          <div class="list-item-content">
            <div class="list-item-title">
              <ha-icon icon="${icon}" style="--mdc-icon-size:20px;margin-right:4px;flex-shrink:0"></ha-icon>
              ${esc(finding.source_name)}
            </div>
          </div>
          <ha-icon icon="mdi:chevron-down" class="chevron expanded" style="--mdc-icon-size:20px"></ha-icon>
        </div>
        <div class="list-item-accordion" style="padding:16px;box-sizing:border-box;overflow:hidden">
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px">
            <strong>Source:</strong> ${esc(finding.source_type)} &middot; ${esc(finding.source_file || 'unknown')}
            &middot; Action path: ${esc(finding.action_path)}
          </div>
          ${yamlWarning}
          <div class="form-group" style="margin-bottom:12px">
            <label>Category</label>
            <select id="auto-edit-category" class="form-select" style="width:100%;box-sizing:border-box">
              ${catOptions}
            </select>
          </div>
          <div class="form-group" style="margin-bottom:12px">
            <label>Title</label>
            <input type="text" id="auto-edit-title" class="migrate-input" value="${escAttr(sd.title || '')}">
          </div>
          <div class="form-group" style="margin-bottom:12px">
            <label>Message</label>
            <input type="text" id="auto-edit-message" class="migrate-input" value="${escAttr(sd.message || '')}">
          </div>
          <div class="form-group" style="margin-bottom:12px">
            <label>Image URL</label>
            <input type="text" id="auto-edit-image" class="migrate-input" value="${escAttr((sd.data && sd.data.image) || '')}" placeholder="Optional image URL">
          </div>
          ${window.Ticker.NavigationPicker.render(sd.navigate_to || '', 'auto-' + index, { panels: state.hasPanels || [], dashboards: state.lovelaceDashboards || [], views: state.lovelaceViews || {} })}
          <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
            <div class="form-group" style="flex:1;min-width:120px">
              <label>Actions</label>
              <select id="auto-edit-actions" class="form-select" style="width:100%;box-sizing:border-box">
                ${this._buildActionsOptions(sd, state)}
              </select>
            </div>
            <div class="form-group" style="flex:1;min-width:120px">
              <label>Critical</label>
              <select id="auto-edit-critical" class="form-select" style="width:100%;box-sizing:border-box">
                <option value="" ${sd.critical == null ? 'selected' : ''}>Default (category)</option>
                <option value="true" ${sd.critical === true ? 'selected' : ''}>Yes</option>
                <option value="false" ${sd.critical === false ? 'selected' : ''}>No</option>
              </select>
            </div>
            <div class="form-group" style="flex:1;min-width:120px">
              <label>Expiration (hours)</label>
              <input type="number" id="auto-edit-expiration" class="migrate-input" min="1" max="48" value="${sd.expiration || ''}" placeholder="Default: 48">
            </div>
          </div>
          <div class="migrate-actions">
            <button class="btn btn-primary" onclick="window.Ticker.AdminAutomationsTab.handlers.save(window.Ticker._adminPanel, ${index})">
              <ha-icon icon="mdi:content-save" style="--mdc-icon-size:16px;margin-right:4px"></ha-icon>Save
            </button>
            <button class="btn btn-secondary" onclick="window.Ticker.AdminAutomationsTab.handlers.collapse(window.Ticker._adminPanel)">Cancel</button>
          </div>
        </div>
      </div>
    `;
  },

  /**
   * Build HTML options for the Actions dropdown, including library action sets.
   * @param {Object} sd - Service data from the finding
   * @param {Object} state - Panel state
   * @returns {string} - HTML options string
   */
  _buildActionsOptions(sd, state) {
    const { esc, escAttr } = window.Ticker.utils;
    const opts = [
      '<option value=""' + (!sd.actions ? ' selected' : '') + '>Default (inherit)</option>',
      '<option value="category_default"' + (sd.actions === 'category_default' ? ' selected' : '') + '>Category default</option>',
      '<option value="none"' + (sd.actions === 'none' ? ' selected' : '') + '>None</option>',
    ];
    for (const as of (state.actionSets || [])) {
      const sel = sd.actions === as.id ? ' selected' : '';
      opts.push('<option value="' + escAttr(as.id) + '"' + sel + '>' + esc(as.name) + '</option>');
    }
    return opts.join('');
  },

  /**
   * Apply client-side filters to findings.
   * @param {Array} findings - All findings
   * @param {Object} filter - Filter state { category, sourceType }
   * @returns {Array} - Filtered findings
   */
  _applyFilters(findings, filter, categories) {
    return findings.filter(f => {
      if (filter.category) {
        const sd = f.service_data || {};
        const val = sd.category || '';
        // Match by id or resolve name→id via categories list
        const cat = categories && categories.find(c => c.id === filter.category);
        const match = val === filter.category || (cat && val === cat.name);
        if (!match) return false;
      }
      if (filter.sourceType) {
        if (f.source_type !== filter.sourceType) return false;
      }
      return true;
    });
  },

  /**
   * Handler methods for automations tab interactions.
   */
  handlers: {
    /**
     * Scan for ticker.notify calls.
     * @param {HTMLElement} panel - Admin panel element
     */
    async scan(panel) {
      panel._automationsScanning = true;
      panel._automationsFindings = [];
      panel._automationsExpanded = null;
      panel._automationsScanned = true;
      panel._renderTabContent();

      const startTime = Date.now();
      let findings = [];
      let error = null;

      try {
        const result = await panel._hass.callWS({ type: 'ticker/automations/scan' });
        findings = result.findings || [];
      } catch (err) {
        error = err.message || String(err);
      }

      // Ensure scanning shows for at least 1.5 seconds
      const elapsed = Date.now() - startTime;
      if (elapsed < 1500) {
        await new Promise(resolve => setTimeout(resolve, 1500 - elapsed));
      }

      panel._automationsScanning = false;
      panel._automationsFindings = findings;
      panel._renderTabContent();

      if (error) {
        panel._showError(error);
      } else if (findings.length === 0) {
        panel._showSuccess('No ticker.notify calls found.');
      } else {
        panel._showSuccess(`Found ${findings.length} ticker.notify call${findings.length === 1 ? '' : 's'}.`);
      }
    },

    /**
     * Expand a finding for editing.
     * @param {HTMLElement} panel - Admin panel element
     * @param {number} findingIndex - Index in findings array
     */
    expand(panel, findingIndex) {
      panel._automationsExpanded = findingIndex;
      panel._renderTabContent();
    },

    /**
     * Collapse the expanded finding.
     * @param {HTMLElement} panel - Admin panel element
     */
    collapse(panel) {
      panel._automationsExpanded = null;
      panel._renderTabContent();
    },

    /**
     * Save changes to a finding.
     * @param {HTMLElement} panel - Admin panel element
     * @param {number} findingIndex - Index in findings array
     */
    async save(panel, findingIndex) {
      const finding = panel._automationsFindings[findingIndex];
      if (!finding) return;

      const root = panel.shadowRoot;
      const category = root.getElementById('auto-edit-category')?.value || '';
      const title = root.getElementById('auto-edit-title')?.value || '';
      const message = root.getElementById('auto-edit-message')?.value || '';
      const image = root.getElementById('auto-edit-image')?.value?.trim() || '';
      const actionsVal = root.getElementById('auto-edit-actions')?.value || '';
      const criticalVal = root.getElementById('auto-edit-critical')?.value || '';
      const expirationVal = root.getElementById('auto-edit-expiration')?.value || '';
      const navigateTo = window.Ticker.NavigationPicker.read(root, 'auto-' + findingIndex);

      if (!category) {
        panel._showError('Please select a category.');
        return;
      }

      const data = {};
      if (image) data.image = image;
      if (actionsVal) data.actions = actionsVal;
      if (criticalVal === 'true') data.critical = true;
      else if (criticalVal === 'false') data.critical = false;
      const expNum = parseInt(expirationVal, 10);
      if (expNum > 0 && expNum <= 48) data.expiration = expNum;

      try {
        await panel._hass.callWS({
          type: 'ticker/automations/update',
          finding: finding,
          category: category,
          title: title,
          message: message,
          ...(Object.keys(data).length ? { data } : {}),
          navigate_to: navigateTo || null,
        });

        // Update local finding with new values
        const sd = finding.service_data || {};
        sd.category = category;
        sd.title = title;
        sd.message = message;
        if (image) { sd.data = sd.data || {}; sd.data.image = image; }
        else if (sd.data) { delete sd.data.image; }
        if (actionsVal) sd.actions = actionsVal;
        else delete sd.actions;
        if (criticalVal === 'true') sd.critical = true;
        else if (criticalVal === 'false') sd.critical = false;
        else delete sd.critical;
        if (expNum > 0) sd.expiration = expNum;
        else delete sd.expiration;
        if (navigateTo) sd.navigate_to = navigateTo;
        else delete sd.navigate_to;
        finding.service_data = sd;

        panel._automationsExpanded = null;
        panel._renderTabContent();
        panel._showSuccess('Saved successfully.');
      } catch (err) {
        panel._showError(err.message || 'Failed to save.');
      }
    },

    /**
     * Update a filter field and re-render.
     * @param {HTMLElement} panel - Admin panel element
     * @param {string} field - Filter field name
     * @param {string} value - New filter value
     */
    updateFilter(panel, field, value) {
      panel._automationsFilter[field] = value;
      panel._automationsExpanded = null;
      panel._renderTabContent();
    },
  },
};
