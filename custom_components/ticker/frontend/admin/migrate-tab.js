/**
 * Ticker Admin Panel - Migrate Tab
 * Handles migration wizard for converting notify calls to Ticker.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminMigrateTab = {
  /**
   * Render the migrate tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { migrateFindings, migrateCurrentIndex, migrateScanning, migrateConverting, migrateDeleting, categories } = state;

    // Initial state - no scan yet
    if (!migrateFindings.length && !migrateScanning) {
      return this._renderInitialState();
    }

    // Scanning in progress
    if (migrateScanning) {
      return this._renderScanningState();
    }

    // No findings after scan
    if (!migrateFindings.length) {
      return this._renderNoFindingsState();
    }

    // Show current finding
    const finding = migrateFindings[migrateCurrentIndex];
    const duplicate = this._getDuplicateFinding(migrateFindings, finding);
    const isProcessing = migrateConverting || migrateDeleting;

    if (duplicate) {
      return this._renderDuplicateView(state, finding, duplicate, isProcessing);
    }

    return this._renderFindingView(state, finding, isProcessing);
  },

  /**
   * Render the initial state (before scanning).
   * @returns {string} - HTML string
   */
  _renderInitialState() {
    return `
      <div class="card">
        <h2 class="card-title">Migration Wizard</h2>
        <p class="card-description">Scan automations and scripts for notification calls and convert them to Ticker.</p>
        <p class="card-description"><b>Scans:</b> Automations, Scripts<br><b>Services:</b> notify.*, persistent_notification.*</p>
        <button class="btn btn-primary" onclick="window.Ticker.AdminMigrateTab.handlers.scan(window.Ticker._adminPanel)">
          <ha-icon icon="mdi:magnify" style="--mdc-icon-size:18px;margin-right:6px"></ha-icon>Scan
        </button>
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
        <h2 class="card-title">Migration Wizard</h2>
        <div class="empty-state">
          <span class="spinner"></span>
          <span>Scanning...</span>
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
        <h2 class="card-title">Migration Wizard</h2>
        <div class="empty-state">
          <p>No notifications found.</p>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminMigrateTab.handlers.scan(window.Ticker._adminPanel)" style="margin-top:16px">Scan Again</button>
        </div>
      </div>
    `;
  },

  /**
   * Render the duplicate finding view.
   * @param {Object} state - Panel state
   * @param {Object} finding - Current finding
   * @param {Object} duplicate - Duplicate finding
   * @param {boolean} isProcessing - Whether processing
   * @returns {string} - HTML string
   */
  _renderDuplicateView(state, finding, duplicate, isProcessing) {
    const { esc, escAttr } = window.Ticker.utils;
    const { migrateFindings, migrateCurrentIndex } = state;

    const sd = finding.service_data || {};
    const dupSd = duplicate.service_data || {};

    const progress = `<div class="migrate-progress">${migrateCurrentIndex + 1} of ${migrateFindings.length}</div>`;

    return `
      <div class="card">
        <h2 class="card-title">Migration Wizard</h2>
        ${progress}
        <div class="duplicate-warning">
          <ha-icon icon="mdi:content-duplicate" style="--mdc-icon-size:20px;color:var(--ticker-warning-dark,#d97706)"></ha-icon>
          <div class="duplicate-warning-content">
            <div class="duplicate-warning-title">Duplicate Detected</div>
            <div class="duplicate-warning-text">This notification is identical to an adjacent one. You can delete this duplicate or keep both.</div>
          </div>
        </div>
        <div class="duplicate-grid">
          <div class="migrate-finding current">
            <div class="finding-label">Current (This One)</div>
            <div class="migrate-finding-header">
              <div>
                <div class="migrate-finding-source">${esc(finding.source_name)}</div>
                <div class="migrate-finding-type">Index: ${esc(finding.action_path)}</div>
              </div>
              <span class="badge">${esc(finding.service)}</span>
            </div>
            <div class="migrate-finding-data">
              <div class="migrate-data-row">
                <div class="migrate-data-label">Title</div>
                <div class="migrate-data-value">${esc(sd.title || '(none)')}</div>
              </div>
              <div class="migrate-data-row">
                <div class="migrate-data-label">Message</div>
                <div class="migrate-data-value">${esc(sd.message || '(none)')}</div>
              </div>
              <div class="migrate-data-row">
                <div class="migrate-data-label">Target</div>
                <div class="migrate-data-value mono">${esc(JSON.stringify(finding.target || {}))}</div>
              </div>
            </div>
          </div>
          <div class="migrate-finding adjacent">
            <div class="finding-label adjacent">Adjacent Duplicate</div>
            <div class="migrate-finding-header">
              <div>
                <div class="migrate-finding-source">${esc(duplicate.source_name)}</div>
                <div class="migrate-finding-type">Index: ${esc(duplicate.action_path)}</div>
              </div>
              <span class="badge">${esc(duplicate.service)}</span>
            </div>
            <div class="migrate-finding-data">
              <div class="migrate-data-row">
                <div class="migrate-data-label">Title</div>
                <div class="migrate-data-value">${esc(dupSd.title || '(none)')}</div>
              </div>
              <div class="migrate-data-row">
                <div class="migrate-data-label">Message</div>
                <div class="migrate-data-value">${esc(dupSd.message || '(none)')}</div>
              </div>
              <div class="migrate-data-row">
                <div class="migrate-data-label">Target</div>
                <div class="migrate-data-value mono">${esc(JSON.stringify(duplicate.target || {}))}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="migrate-actions">
          ${isProcessing ? '<span class="spinner"></span>' : ''}
          <button class="btn btn-danger" onclick="window.Ticker.AdminMigrateTab.handlers.deleteDuplicate(window.Ticker._adminPanel)" ${isProcessing ? 'disabled' : ''}>Delete This Duplicate</button>
          <button class="btn btn-secondary" onclick="window.Ticker.AdminMigrateTab.handlers.skip(window.Ticker._adminPanel)" ${isProcessing ? 'disabled' : ''}>Keep Both</button>
        </div>
      </div>
    `;
  },

  /**
   * Render the normal finding view.
   * @param {Object} state - Panel state
   * @param {Object} finding - Current finding
   * @param {boolean} isProcessing - Whether processing
   * @returns {string} - HTML string
   */
  _renderFindingView(state, finding, isProcessing) {
    const { esc, escAttr, generateCategoryId } = window.Ticker.utils;
    const { migrateFindings, migrateCurrentIndex, categories } = state;

    const sd = finding.service_data || {};
    const progress = `<div class="migrate-progress">${migrateCurrentIndex + 1} of ${migrateFindings.length}</div>`;

    // Build category options
    const sortedCats = [...categories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });
    const catOptions = sortedCats.map(c => `<option value="${escAttr(c.id)}">${esc(c.name)}</option>`).join('') + '<option value="__new__">+ New category...</option>';

    // Extra data (beyond title/message)
    const extraData = Object.entries(sd).filter(([k]) => k !== 'title' && k !== 'message');
    const extraDataHtml = extraData.length ? `
      <div class="migrate-data-row">
        <div class="migrate-data-label">Extra data</div>
        <div class="migrate-data-value mono extra">${extraData.map(([k, v]) => `${esc(k)}: ${esc(typeof v === 'object' ? JSON.stringify(v) : v)}`).join('\n')}</div>
      </div>
    ` : '';

    return `
      <div class="card">
        <h2 class="card-title">Migration Wizard</h2>
        ${progress}
        <div class="migrate-finding">
          <div class="migrate-finding-header">
            <div>
              <div class="migrate-finding-source">${esc(finding.source_name)}</div>
              <div class="migrate-finding-type">${esc(finding.source_type)} · from ${esc(finding.source_file || 'unknown')}</div>
            </div>
            <span class="badge">${esc(finding.service)}</span>
          </div>
          <div class="migrate-finding-data">
            <div class="migrate-data-row">
              <div class="migrate-data-label">Title</div>
              <div class="migrate-data-value">
                <input type="text" id="migrate-title" value="${escAttr(sd.title || '')}" class="migrate-input">
              </div>
            </div>
            <div class="migrate-data-row">
              <div class="migrate-data-label">Message</div>
              <div class="migrate-data-value">
                <input type="text" id="migrate-message" value="${escAttr(sd.message || '')}" class="migrate-input">
              </div>
            </div>
            ${extraDataHtml}
          </div>
          <div class="form-row" style="margin-bottom:12px">
            <div class="form-group">
              <label>Category</label>
              <select id="migrate-category" style="min-width:180px" onchange="const n=this.getRootNode().getElementById('migrate-new-cat-row');n.style.display=this.value==='__new__'?'flex':'none'">
                ${catOptions}
              </select>
            </div>
            <div class="form-group" id="migrate-new-cat-row" style="display:none">
              <label>New name</label>
              <input type="text" id="migrate-new-category" placeholder="Category name">
            </div>
          </div>
          <div class="migrate-actions">
            ${isProcessing ? '<span class="spinner"></span>' : ''}
            <button class="btn btn-primary" onclick="window.Ticker.AdminMigrateTab.handlers.convert(window.Ticker._adminPanel, true)" ${isProcessing ? 'disabled' : ''}>Apply Directly</button>
            <button class="btn btn-secondary" onclick="window.Ticker.AdminMigrateTab.handlers.convert(window.Ticker._adminPanel, false)" ${isProcessing ? 'disabled' : ''}>Copy YAML</button>
            <button class="btn btn-secondary" onclick="window.Ticker.AdminMigrateTab.handlers.skip(window.Ticker._adminPanel)" ${isProcessing ? 'disabled' : ''}>Skip</button>
          </div>
        </div>
      </div>
    `;
  },

  /**
   * Get duplicate finding if exists.
   * @param {Array} findings - All findings
   * @param {Object} finding - Current finding
   * @returns {Object|null} - Duplicate finding or null
   */
  _getDuplicateFinding(findings, finding) {
    if (!finding || !finding.has_duplicate || !finding.duplicate_finding_id) {
      return null;
    }
    return findings.find(x => x.finding_id === finding.duplicate_finding_id) || null;
  },

  /**
   * Handler methods.
   */
  handlers: {
    async scan(panel) {
      console.log('[Ticker] Starting migration scan...');
      panel._migrateScanning = true;
      panel._migrateFindings = [];
      panel._migrateCurrentIndex = 0;
      panel._renderTabContent();

      const startTime = Date.now();
      let findings = [];
      let error = null;

      try {
        console.log('[Ticker] Calling ticker/migrate/scan...');
        const result = await panel._hass.callWS({ type: 'ticker/migrate/scan' });
        console.log('[Ticker] Scan response:', result);
        findings = result.findings || [];
      } catch (err) {
        console.error('[Ticker] Scan error:', err);
        error = err.message || String(err);
      }

      // Ensure scanning shows for at least 2 seconds
      const elapsed = Date.now() - startTime;
      console.log('[Ticker] Elapsed:', elapsed, 'ms, waiting for 2s minimum');
      if (elapsed < 2000) {
        await new Promise(resolve => setTimeout(resolve, 2000 - elapsed));
      }

      panel._migrateScanning = false;
      panel._migrateFindings = findings;
      console.log('[Ticker] Rendering with', findings.length, 'findings');
      panel._renderTabContent();

      // Show message AFTER render so the element exists
      console.log('[Ticker] Showing message, error:', error);
      if (error) {
        panel._showError(error);
      } else if (findings.length === 0) {
        panel._showSuccess('Scan complete - no notification calls found in your automations or scripts.');
      } else {
        panel._showSuccess(`Found ${findings.length} notification call${findings.length === 1 ? '' : 's'} to review.`);
      }
    },

    skip(panel) {
      if (panel._migrateCurrentIndex < panel._migrateFindings.length - 1) {
        panel._migrateCurrentIndex++;
      } else {
        panel._migrateFindings = [];
        panel._migrateCurrentIndex = 0;
        panel._showSuccess('Done!');
      }
      panel._renderTabContent();
    },

    async convert(panel, applyDirectly) {
      const { generateCategoryId } = window.Ticker.utils;
      const finding = panel._migrateFindings[panel._migrateCurrentIndex];
      if (!finding) return;

      const categorySelect = panel.shadowRoot.getElementById('migrate-category');
      const newCategoryInput = panel.shadowRoot.getElementById('migrate-new-category');
      const titleInput = panel.shadowRoot.getElementById('migrate-title');
      const messageInput = panel.shadowRoot.getElementById('migrate-message');

      let categoryId = categorySelect?.value;
      let categoryName = '';
      const title = titleInput?.value || '';
      const message = messageInput?.value || '';

      // Warn for YAML-based files
      const isYamlFile = finding.source_file && !finding.source_file.includes('.storage');
      if (applyDirectly && isYamlFile) {
        const fileName = finding.source_file.split('/').pop();
        const confirmed = confirm(
          'YAML FILE MODIFICATION\n\n' +
          'File: ' + finding.source_file + '\n\n' +
          'IMPORTANT: This operation uses standard YAML processing which does NOT preserve:\n' +
          '  - Comments (inline and block)\n' +
          '  - Custom formatting and indentation\n' +
          '  - Quote styles\n' +
          '  - Blank lines\n\n' +
          'A backup will be created BEFORE any changes:\n' +
          '  config/ticker_migration_backups/' + fileName + '.[timestamp]\n\n' +
          'If you have important comments in your YAML, consider using "Copy YAML" instead and applying changes manually.\n\n' +
          'Continue with auto-apply?'
        );
        if (!confirmed) return;
      }

      // Handle new category creation
      if (categoryId === '__new__') {
        const newName = newCategoryInput?.value?.trim();
        if (!newName) {
          panel._showError('Enter category name');
          return;
        }
        categoryId = generateCategoryId(newName);
        categoryName = newName;
        try {
          await panel._hass.callWS({
            type: 'ticker/category/create',
            category_id: categoryId,
            name: newName,
            icon: 'mdi:bell',
          });
          await panel._loadCategories();
        } catch (err) {
          panel._showError(err.message);
          return;
        }
      } else {
        const cat = panel._categories.find(x => x.id === categoryId);
        categoryName = cat ? cat.name : categoryId;
      }

      panel._migrateConverting = true;
      panel._renderTabContent();

      try {
        const result = await panel._hass.callWS({
          type: 'ticker/migrate/convert',
          finding: finding,
          category_id: categoryId,
          category_name: categoryName,
          apply_directly: applyDirectly,
          title: title,
          message: message,
        });

        if (result.success) {
          if (applyDirectly && result.applied) {
            panel._showSuccess(isYamlFile ? 'Applied! Backup created.' : 'Applied!');
          } else {
            navigator.clipboard.writeText(result.yaml).then(() => {
              panel._showSuccess('YAML copied!');
            }).catch(() => {
              alert(result.yaml);
            });
          }
          this.skip(panel);
        } else {
          panel._showError(result.error || 'Failed');
        }
      } catch (err) {
        panel._showError(err.message);
      }

      panel._migrateConverting = false;
      panel._renderTabContent();
    },

    async deleteDuplicate(panel) {
      const finding = panel._migrateFindings[panel._migrateCurrentIndex];
      if (!finding) return;

      panel._migrateDeleting = true;
      panel._renderTabContent();

      try {
        const result = await panel._hass.callWS({
          type: 'ticker/migrate/delete',
          finding: finding,
        });

        if (result.success && result.deleted) {
          panel._showSuccess('Duplicate deleted');

          // Remove this finding and update duplicate pair
          const dupId = finding.duplicate_finding_id;
          panel._migrateFindings = panel._migrateFindings.filter(x => x.finding_id !== finding.finding_id);

          // Clear duplicate flag from paired finding
          const pairedFinding = panel._migrateFindings.find(x => x.finding_id === dupId);
          if (pairedFinding) {
            pairedFinding.has_duplicate = false;
            pairedFinding.duplicate_finding_id = null;
            pairedFinding.is_first_in_duplicate_pair = false;
          }

          // Adjust current index if needed
          if (panel._migrateCurrentIndex >= panel._migrateFindings.length) {
            panel._migrateCurrentIndex = Math.max(0, panel._migrateFindings.length - 1);
          }
          if (panel._migrateFindings.length === 0) {
            panel._migrateCurrentIndex = 0;
            panel._showSuccess('Done!');
          }
        } else {
          panel._showError(result.error || 'Failed to delete');
        }
      } catch (err) {
        panel._showError(err.message);
      }

      panel._migrateDeleting = false;
      panel._renderTabContent();
    },
  },
};
