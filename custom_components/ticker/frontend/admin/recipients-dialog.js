/**
 * Ticker Admin Panel - Recipients Dialog
 * Create/edit dialog for device recipients with Push/TTS type support.
 * Extracted from recipients-tab.js to stay under the 500-line limit.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminRecipientsDialog = {
  /**
   * Render the create/edit dialog overlay.
   * @param {Object} panel - Admin panel instance
   * @param {Object|null} existing - Existing recipient for edit, null for create
   * @returns {string} - HTML string
   */
  render(panel, existing) {
    const { esc, escAttr } = window.Ticker.utils;
    const isEdit = !!existing;
    const title = isEdit ? `Edit: ${esc(existing.name)}` : 'Add New Device';

    const name = existing ? existing.name : '';
    const icon = existing ? (existing.icon || 'mdi:bell-ring') : 'mdi:bell-ring';
    const deviceType = existing ? (existing.device_type || 'push') : 'push';
    const format = existing ? (existing.delivery_format || 'rich') : 'rich';
    const selectedServices = existing ? (existing.notify_services || []) : [];
    const mediaPlayerEntityId = existing ? (existing.media_player_entity_id || '') : '';
    const ttsService = existing ? (existing.tts_service || '') : '';

    const nameSection = this._renderNameSection(isEdit, existing, escAttr, name);
    const iconSection = this._renderIconField(escAttr, icon);
    const deviceTypeSection = this._renderDeviceTypeSelector(deviceType);
    const pushFields = this._renderPushFields(panel, selectedServices, format, deviceType);
    const resumeAfterTts = existing ? (existing.resume_after_tts || false) : false;
    const bufferDelay = existing ? (existing.tts_buffer_delay ?? 0) : 0;
    const ttsFields = this._renderTtsFields(panel, escAttr, mediaPlayerEntityId, ttsService, deviceType, resumeAfterTts, bufferDelay);

    return `
      <div id="recipient-dialog-overlay" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100;display:flex;align-items:center;justify-content:center" onclick="if(event.target===this)window.Ticker.AdminRecipientsTab.handlers.closeDialog(window.Ticker._adminPanel)">
        <div style="background:var(--bg-card);border-radius:8px;padding:24px;width:90%;max-width:480px;max-height:80vh;overflow-y:auto;box-shadow:0 8px 32px rgba(0,0,0,0.2)">
          <h3 style="margin:0 0 0;font-size:16px;color:var(--text-primary)">${title}</h3>
          <style>
            .dlg-tab{background:none;border:none;padding:8px 16px;font-size:13px;color:var(--text-secondary);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
            .dlg-tab.active{color:var(--ticker-500);border-bottom-color:var(--ticker-500);font-weight:600}
          </style>
          <div id="dlg-tabs" style="display:flex;gap:0;border-bottom:1px solid var(--divider);margin-bottom:16px">
            <button id="dlg-tab-settings" class="dlg-tab active" onclick="window.Ticker.AdminRecipientsDialog.switchTab('settings')">Settings</button>
            <button id="dlg-tab-conditions" class="dlg-tab" onclick="window.Ticker.AdminRecipientsDialog.switchTab('conditions')">Conditions</button>
          </div>
          <div id="dlg-error" style="display:none;padding:8px 12px;margin-bottom:12px;background:var(--ticker-error-bg, #fef2f2);border:1px solid var(--ticker-error-border, #fecaca);color:var(--ticker-danger-hover, #dc2626);border-radius:4px;font-size:13px"></div>
          <div id="dlg-panel-settings">
            ${nameSection}
            ${iconSection}
            ${deviceTypeSection}
            <div id="dlg-push-fields" style="display:${deviceType === 'push' ? 'block' : 'none'}">
              ${pushFields}
            </div>
            <div id="dlg-tts-fields" style="display:${deviceType === 'tts' ? 'block' : 'none'}">
              ${ttsFields}
            </div>
          </div>
          <div id="dlg-panel-conditions" style="display:none">
            <p style="margin:0 0 12px;font-size:13px;color:var(--text-secondary)">
              When conditions are configured, this device only receives notifications
              while all conditions are met. If not met, the notification is logged as skipped.
            </p>
            <ticker-conditions-ui id="dlg-device-conditions" hide-zone hide-queue></ticker-conditions-ui>
          </div>
          <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px">
            <button class="btn btn-secondary" onclick="window.Ticker.AdminRecipientsTab.handlers.closeDialog(window.Ticker._adminPanel)">Cancel</button>
            <button class="btn btn-primary" onclick="window.Ticker.AdminRecipientsTab.handlers.saveDialog(window.Ticker._adminPanel, ${isEdit ? 'true' : 'false'})">${isEdit ? 'Save' : 'Create'}</button>
          </div>
        </div>
      </div>
    `;
  },

  /**
   * Render name input and slug preview (BUG-051: auto-derive ID).
   * On create: name input + read-only slug preview. No manual ID input.
   * On edit: read-only ID + editable name.
   */
  _renderNameSection(isEdit, existing, escAttr, name) {
    if (isEdit) {
      return `
        <div class="form-group" style="margin-bottom:12px">
          <label>ID (slug)</label>
          <input class="form-input" id="dlg-recipient-id" value="${escAttr(existing.recipient_id)}" readonly style="opacity:0.6">
        </div>
        <div class="form-group" style="margin-bottom:12px">
          <label>Name</label>
          <input class="form-input" id="dlg-recipient-name" value="${escAttr(name)}" placeholder="e.g. Living Room TV">
        </div>
      `;
    }
    // Create mode: hide manual ID, show auto-slug preview
    return `
      <div class="form-group" style="margin-bottom:12px">
        <label>Name</label>
        <input class="form-input" id="dlg-recipient-name" value="" placeholder="e.g. Living Room TV" oninput="window.Ticker.AdminRecipientsDialog.updateSlugPreview(window.Ticker._adminPanel)">
      </div>
      <div class="form-group" style="margin-bottom:12px">
        <label style="font-size:12px;color:var(--text-secondary)">ID (auto-generated)</label>
        <div id="dlg-slug-preview" style="font-family:monospace;font-size:13px;color:var(--text-secondary);padding:6px 8px;background:var(--bg-primary);border:1px solid var(--divider);border-radius:4px;min-height:20px"></div>
      </div>
    `;
  },

  /** Render icon MDI input field. */
  _renderIconField(escAttr, icon) {
    return `
      <div class="form-group" style="margin-bottom:12px">
        <label>Icon (MDI)</label>
        <input class="form-input" id="dlg-recipient-icon" value="${escAttr(icon)}" placeholder="mdi:television">
      </div>
    `;
  },

  /** Render device type radio selector (Push / TTS). */
  _renderDeviceTypeSelector(deviceType) {
    const ns = 'window.Ticker.AdminRecipientsDialog';
    return `
      <div class="form-group" style="margin-bottom:12px">
        <label>Device Type</label>
        <div style="display:flex;gap:16px;margin-top:4px">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
            <input type="radio" name="dlg-device-type" value="push" ${deviceType === 'push' ? 'checked' : ''} onchange="${ns}.onDeviceTypeChange(window.Ticker._adminPanel)"> Push
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
            <input type="radio" name="dlg-device-type" value="tts" ${deviceType === 'tts' ? 'checked' : ''} onchange="${ns}.onDeviceTypeChange(window.Ticker._adminPanel)"> TTS
          </label>
        </div>
      </div>
    `;
  },

  /** Render Push-specific fields: notify services multi-select + delivery format. */
  _renderPushFields(panel, selectedServices, format, deviceType) {
    const { esc, escAttr } = window.Ticker.utils;
    const availableServices = panel._availableNotifyServices || [];
    const ns = 'window.Ticker.AdminRecipientsTab.handlers';

    const serviceOptions = availableServices.map(s => {
      const isSelected = selectedServices.some(sel => sel.service === s.service);
      return `<label style="display:flex;align-items:center;gap:8px;padding:4px 0;cursor:pointer">
        <input type="checkbox" value="${escAttr(s.service)}" data-name="${escAttr(s.name)}" data-format="${escAttr(s.detected_format)}" ${isSelected ? 'checked' : ''} onchange="${ns}.onServiceSelectionChange(window.Ticker._adminPanel)">
        <span style="font-size:13px">${esc(s.name)}</span>
        <span class="badge badge-outline" style="font-size:10px;padding:1px 6px">${esc(s.detected_format)}</span>
      </label>`;
    }).join('');

    // Push devices only get Rich / Plain formats
    const pushFormats = [
      { value: 'rich', label: 'Rich' },
      { value: 'plain', label: 'Plain' },
    ];
    const formatOptions = pushFormats.map(f =>
      `<option value="${f.value}" ${f.value === format ? 'selected' : ''}>${f.label}</option>`
    ).join('');

    return `
      <div class="form-group" style="margin-bottom:12px">
        <label>Notify Services</label>
        <div id="dlg-service-list" style="max-height:160px;overflow-y:auto;border:1px solid var(--divider);border-radius:4px;padding:8px">
          ${serviceOptions || '<span style="color:var(--text-secondary);font-size:13px">No notify services available</span>'}
        </div>
        <div id="dlg-format-notice" style="display:none;margin-top:6px;font-size:12px;color:var(--ticker-warning-dark)"></div>
      </div>
      <div class="form-group" style="margin-bottom:12px">
        <label>Delivery Format</label>
        <select class="form-select" id="dlg-recipient-format">
          ${formatOptions}
        </select>
      </div>
    `;
  },

  /** Render TTS-specific fields: media player entity + TTS service + resume toggle. */
  _renderTtsFields(panel, escAttr, mediaPlayerEntityId, ttsService, deviceType, resumeAfterTts, bufferDelay) {
    const { esc } = window.Ticker.utils;
    const ttsOptions = panel._ttsOptions || { media_players: [], tts_services: [] };
    const ns = 'window.Ticker.AdminRecipientsDialog';

    // Build media player dropdown options
    const mpOptions = ttsOptions.media_players.map(mp => {
      const selected = mp.entity_id === mediaPlayerEntityId ? 'selected' : '';
      return `<option value="${escAttr(mp.entity_id)}" ${selected}>${esc(mp.friendly_name)} (${esc(mp.entity_id)})</option>`;
    }).join('');

    // Build TTS service dropdown options
    const ttsOpts = ttsOptions.tts_services.map(svc => {
      const selected = svc.service_id === ttsService ? 'selected' : '';
      return `<option value="${escAttr(svc.service_id)}" ${selected}>${esc(svc.name)} (${esc(svc.service_id)})</option>`;
    }).join('');

    const noMpMsg = ttsOptions.media_players.length === 0
      ? '<span style="font-size:11px;color:var(--ticker-warning-dark);margin-top:2px;display:block">No media_player entities found in Home Assistant</span>'
      : '';
    const noTtsMsg = ttsOptions.tts_services.length === 0
      ? '<span style="font-size:11px;color:var(--ticker-warning-dark);margin-top:2px;display:block">No TTS services found in Home Assistant</span>'
      : '';

    // Announce support indicator for initially selected media player
    const announceHtml = this._getAnnounceIndicator(ttsOptions, mediaPlayerEntityId);

    return `
      <div class="form-group" style="margin-bottom:12px">
        <label>Media Player Entity</label>
        <select class="form-select" id="dlg-media-player" onchange="${ns}.onMediaPlayerChange(window.Ticker._adminPanel)">
          <option value="">-- Select media player --</option>
          ${mpOptions}
        </select>
        ${noMpMsg}
        <span style="font-size:11px;color:var(--text-secondary);margin-top:2px;display:block">The media player device to use for TTS output</span>
        <div id="dlg-announce-indicator" style="margin-top:4px">${announceHtml}</div>
      </div>
      <div class="form-group" style="margin-bottom:12px">
        <label>TTS Service</label>
        <select class="form-select" id="dlg-tts-service">
          <option value="">-- Select TTS service --</option>
          ${ttsOpts}
        </select>
        ${noTtsMsg}
        <span style="font-size:11px;color:var(--text-secondary);margin-top:2px;display:block">The text-to-speech service to use</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:8px">
        <label class="toggle">
          <input type="checkbox" id="dlg-resume-tts" ${resumeAfterTts ? 'checked' : ''}>
          <span class="toggle-slider"></span>
        </label>
        <span style="font-size:13px;color:var(--text-primary)">Resume playback after announcement</span>
      </div>
      <div style="margin-top:12px;margin-bottom:12px">
        <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--text-secondary)">TTS Buffer Delay (seconds)</label>
        <input type="number" id="dlg-tts-buffer-delay" min="0" max="10" step="0.5" value="${bufferDelay}" style="width:80px;padding:6px 8px;border-radius:4px;border:1px solid var(--divider);background:var(--bg-card);color:var(--text-primary)">
        <p style="margin:4px 0 0;font-size:11px;color:var(--text-secondary)">Chromecast / Cast devices may need a delay before TTS playback to avoid silent output. Set 2-3s for Chromecast. Leave at 0 for devices that work without delay.</p>
      </div>
    `;
  },

  /**
   * Build announce support indicator HTML for a given media player entity.
   * @param {Object} ttsOptions - TTS options with media_players array
   * @param {string} entityId - Selected media player entity ID
   * @returns {string} - HTML string
   */
  _getAnnounceIndicator(ttsOptions, entityId) {
    if (!entityId) return '';
    const mp = (ttsOptions.media_players || []).find(m => m.entity_id === entityId);
    if (!mp) return '';
    if (mp.supports_announce) {
      return `<span style="font-size:11px;color:var(--ticker-success)">&#10003; Supports announce mode (auto-resume)</span>`;
    }
    return `<span style="font-size:11px;color:var(--text-secondary)">&ndash; No announce support</span>`;
  },

  /** Update announce indicator when media player selection changes. */
  onMediaPlayerChange(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;
    const select = container.querySelector('#dlg-media-player');
    const indicator = container.querySelector('#dlg-announce-indicator');
    if (!select || !indicator) return;
    const ttsOptions = panel._ttsOptions || { media_players: [], tts_services: [] };
    indicator.innerHTML = this._getAnnounceIndicator(ttsOptions, select.value);
  },

  /**
   * Check whether any push-specific fields have user-entered values.
   * Checks checkboxes (spec-required) and also guards the delivery format
   * selection to prevent silent data loss when switching device types.
   */
  _hasPushValues(container) {
    const checkedServices = container.querySelectorAll('#dlg-service-list input[type="checkbox"]:checked');
    if (checkedServices.length > 0) return true;
    const format = container.querySelector('#dlg-recipient-format');
    if (format && format.value !== 'rich') return true;
    return false;
  },

  /**
   * Check whether any TTS-specific fields have user-entered values.
   * Checks the spec-required media player and TTS service dropdowns,
   * plus the resume_after_tts toggle.
   */
  _hasTtsValues(container) {
    const mp = container.querySelector('#dlg-media-player');
    if (mp && mp.value) return true;
    const tts = container.querySelector('#dlg-tts-service');
    if (tts && tts.value) return true;
    const resume = container.querySelector('#dlg-resume-tts');
    if (resume && resume.checked) return true;
    if (parseFloat(container.querySelector('#dlg-tts-buffer-delay')?.value) > 0) return true;
    return false;
  },

  /** Reset all push fields to their defaults. */
  _clearPushFields(container) {
    const checks = container.querySelectorAll('#dlg-service-list input[type="checkbox"]:checked');
    checks.forEach(cb => { cb.checked = false; });
    const format = container.querySelector('#dlg-recipient-format');
    if (format) format.value = 'rich';
    const notice = container.querySelector('#dlg-format-notice');
    if (notice) { notice.style.display = 'none'; notice.textContent = ''; }
  },

  /** Reset all TTS fields to their defaults. */
  _clearTtsFields(container) {
    const mp = container.querySelector('#dlg-media-player');
    if (mp) mp.value = '';
    const tts = container.querySelector('#dlg-tts-service');
    if (tts) tts.value = '';
    const resume = container.querySelector('#dlg-resume-tts');
    if (resume) resume.checked = false;
    const indicator = container.querySelector('#dlg-announce-indicator');
    if (indicator) indicator.innerHTML = '';
    const bufferEl = container.querySelector('#dlg-tts-buffer-delay');
    if (bufferEl) bufferEl.value = '0';
  },

  /**
   * Handle device type radio change: show/hide field groups.
   * If the previous type had user-entered values, prompt for confirmation
   * before switching and clearing those values.
   */
  onDeviceTypeChange(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;
    const selected = container.querySelector('input[name="dlg-device-type"]:checked');
    if (!selected) return;
    const newType = selected.value;

    const pushFields = container.querySelector('#dlg-push-fields');
    const ttsFields = container.querySelector('#dlg-tts-fields');
    if (!pushFields || !ttsFields) return;

    // Detect previous type from which container is currently visible
    const prevType = pushFields.style.display !== 'none' ? 'push' : 'tts';
    if (newType === prevType) return;

    // Check if the outgoing type has values worth preserving
    const hasValues = prevType === 'push'
      ? this._hasPushValues(container)
      : this._hasTtsValues(container);

    if (hasValues) {
      const label = prevType === 'push' ? 'Push' : 'TTS';
      const ok = confirm(`Switching will clear your ${label} field values. Continue?`);
      if (!ok) {
        // Revert the radio back to the previous type
        const prevRadio = container.querySelector(
          `input[name="dlg-device-type"][value="${prevType}"]`
        );
        if (prevRadio) prevRadio.checked = true;
        return;
      }
      // Clear the outgoing fields
      if (prevType === 'push') this._clearPushFields(container);
      else this._clearTtsFields(container);
    }

    pushFields.style.display = newType === 'push' ? 'block' : 'none';
    ttsFields.style.display = newType === 'tts' ? 'block' : 'none';
  },

  /**
   * Show an error message inside the dialog overlay (BUG-062).
   * @param {Object} panel - Admin panel instance
   * @param {string} message - Error message to display
   */
  showDialogError(panel, message) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;
    const el = container.querySelector('#dlg-error');
    if (el) { el.textContent = message; el.style.display = 'block'; }
  },

  /**
   * Clear the dialog error message (BUG-062).
   * @param {Object} panel - Admin panel instance
   */
  clearDialogError(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;
    const el = container.querySelector('#dlg-error');
    if (el) { el.style.display = 'none'; el.textContent = ''; }
  },

  /**
   * Switch between Settings and Conditions tabs in the dialog.
   * @param {string} name - Tab name: 'settings' or 'conditions'
   */
  switchTab(name) {
    const root = window.Ticker._adminPanel.shadowRoot;
    const container = root.getElementById('ticker-dialog-container');
    if (!container) return;
    ['settings', 'conditions'].forEach(t => {
      const tab = container.querySelector(`#dlg-tab-${t}`);
      const panel = container.querySelector(`#dlg-panel-${t}`);
      const active = t === name;
      if (tab) tab.classList.toggle('active', active);
      if (panel) panel.style.display = active ? 'block' : 'none';
    });
  },

  /** Update slug preview from name input (BUG-051). */
  updateSlugPreview(panel) {
    const container = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!container) return;
    const nameInput = container.querySelector('#dlg-recipient-name');
    const preview = container.querySelector('#dlg-slug-preview');
    if (!nameInput || !preview) return;
    const slug = window.Ticker.utils.generateCategoryId(nameInput.value);
    preview.textContent = slug || '(type a name above)';
  },
};
