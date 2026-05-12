/**
 * Ticker Admin Panel - Categories Handlers
 * Event handlers for category management, extracted from
 * categories-tab.js to keep both files under the 500-line limit
 * (mirrors the recipients-tab.js / recipients-handlers.js split).
 *
 * All handlers receive a panel reference as their first argument and
 * are invoked via onclick strings rendered by categories-tab.js.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};
window.Ticker.AdminCategoriesTab = window.Ticker.AdminCategoriesTab || {};

window.Ticker.AdminCategoriesTab.handlers = {
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
      // F-35.1: lazy-load bundled chimes so the preset chips render on
      // first open. Re-render once the list arrives.
      this._loadBundledChimes(panel);
    }
    panel._addingCategory = false;
    panel._pendingDefaultMode = null;
    panel._pendingDefaultConditions = null;
    panel._renderTabContentPreserveScroll();
  },

  /**
   * F-35.1: Fetch bundled chimes once and trigger a re-render so the
   * chip row appears in already-open category accordions. Errors and
   * empty lists both result in no chip row (helper hides it).
   */
  async _loadBundledChimes(panel) {
    if (Array.isArray(panel._bundledChimes)) return;
    try {
      const result = await panel._hass.callWS({ type: 'ticker/get_bundled_chimes' });
      panel._bundledChimes = (result && result.chimes) || [];
    } catch (_err) {
      panel._bundledChimes = [];
    }
    if (panel._editingCategory) {
      panel._renderTabContentPreserveScroll();
    }
  },

  /**
   * F-35.1: Apply a bundled chime URL to the category override fields and
   * refresh the active chip. URL is written verbatim into the hidden
   * field so the production playback path is unchanged.
   */
  pickBundledCategoryChime(panel, categoryId, url) {
    const root = panel.shadowRoot;
    const display = root.getElementById(`cat-chime-display-${categoryId}`);
    const hidden = root.getElementById(`cat-chime-id-${categoryId}`);
    const test = root.getElementById(`cat-chime-test-${categoryId}`);
    const targetSel = root.getElementById(`cat-chime-test-target-${categoryId}`);
    if (display) display.value = url;
    if (hidden) hidden.value = url;
    if (test) {
      const haveTarget = !!(targetSel && targetSel.value);
      test.disabled = !(haveTarget && url);
    }
    this._refreshCategoryChimeChipActive(root, categoryId, url);
  },

  /** F-35.1: Toggle .active on the chip whose URL matches. */
  _refreshCategoryChimeChipActive(root, categoryId, url) {
    const wrap = root.getElementById(`cat-chime-presets-${categoryId}`);
    if (!wrap) return;
    wrap.querySelectorAll('.ticker-chime-chip').forEach(chip => {
      chip.classList.toggle('active', chip.dataset.chimeUrl === url);
    });
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

    const root = panel.shadowRoot;
    const nameEl = root.getElementById(`edit-name-${categoryId}`);
    const name = nameEl ? nameEl.value.trim() : cat.name;
    const iconEl = root.getElementById(`edit-icon-${categoryId}`);
    const icon = iconEl ? iconEl.value.trim() : cat.icon;
    const colorEl = root.getElementById(`edit-color-${categoryId}`);
    const color = colorEl ? colorEl.value : (cat.color || null);
    const defaultModeEl = root.getElementById(`edit-default-mode-${categoryId}`);
    const defaultMode = defaultModeEl?.value || (cat.default_mode || 'always');
    const criticalEl = root.getElementById(`edit-critical-${categoryId}`);
    const androidChannelEl = root.getElementById(`edit-android-channel-${categoryId}`);

    if (!name) { panel._showError('Name required'); return; }

    try {
      const params = { type: 'ticker/category/update', category_id: categoryId, name, icon, color };
      if (criticalEl) { params.critical = criticalEl.checked; }
      if (androidChannelEl) { params.android_channel = androidChannelEl.value.trim() || ''; }
      const navPresetEl = root.getElementById('nav-preset-cat-edit');
      if (navPresetEl) {
        params.navigate_to = window.Ticker.NavigationPicker.read(root, 'cat-edit');
      }

      // F-35: Pre-TTS chime override (sparse). Always send the field on
      // edit so empty value clears any prior override.
      const chimeEl = root.getElementById(`cat-chime-id-${categoryId}`);
      if (chimeEl) {
        params.chime_media_content_id = (chimeEl.value || '').trim();
      }

      // F-35.2: volume override — read slider; null = "Default" (inherit).
      // Always send the field on edit so cleared sliders flush prior overrides.
      const volume = window.Ticker.AdminVolumeOverride.read(`cat-${categoryId}`);
      params.volume_override = volume;  // null clears, float sets

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
    const r = panel.shadowRoot, g = id => r.getElementById(`smart-${id}-${categoryId}`);
    panel._pendingSmart = panel._pendingSmart || {};
    panel._pendingSmart[categoryId] = {
      group: g('group')?.checked || false, tag_mode: g('tag-mode')?.value || 'none',
      sticky: g('sticky')?.checked || false, persistent: g('persistent')?.checked || false,
    };
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
      if (panel._pendingSmart) delete panel._pendingSmart[categoryId];
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

  /**
   * F-35: Sync a category-dialog chime input with its hidden value field
   * and refresh the Test Chime button enabled state. Hidden field id is
   * cat-chime-id-${categoryId}; visible field is cat-chime-display-${categoryId}.
   */
  onCategoryChimeInput(panel, categoryId) {
    const root = panel.shadowRoot;
    const display = root.getElementById(`cat-chime-display-${categoryId}`);
    const hidden = root.getElementById(`cat-chime-id-${categoryId}`);
    const test = root.getElementById(`cat-chime-test-${categoryId}`);
    const targetSel = root.getElementById(`cat-chime-test-target-${categoryId}`);
    if (!display || !hidden) return;
    hidden.value = display.value || '';
    if (test) {
      const haveTarget = !!(targetSel && targetSel.value);
      const haveChime = !!(hidden.value && hidden.value.trim());
      test.disabled = !(haveTarget && haveChime);
    }
    // F-35.1: keep the bundled-chime active chip in sync with manual edits.
    this._refreshCategoryChimeChipActive(root, categoryId, hidden.value);
  },

  /** F-35: Clear the chime fields on the category dialog. */
  clearCategoryChime(panel, categoryId) {
    const root = panel.shadowRoot;
    const display = root.getElementById(`cat-chime-display-${categoryId}`);
    const hidden = root.getElementById(`cat-chime-id-${categoryId}`);
    const test = root.getElementById(`cat-chime-test-${categoryId}`);
    if (display) display.value = '';
    if (hidden) hidden.value = '';
    if (test) test.disabled = true;
    // F-35.1: clear active chip when the field is wiped.
    this._refreshCategoryChimeChipActive(root, categoryId, '');
  },

  /**
   * F-35: Test the category-override chime via ticker/test_chime. The
   * target media_player is read from a dropdown populated with TTS
   * recipients (panel._recipients filtered to device_type === 'tts').
   */
  async testChimeFromCategory(panel, categoryId) {
    const root = panel.shadowRoot;
    const target = root.getElementById(`cat-chime-test-target-${categoryId}`)?.value;
    const chimeId = (root.getElementById(`cat-chime-id-${categoryId}`)?.value || '').trim();
    if (!target || !chimeId) {
      panel._showError('Select a media player and enter a chime');
      return;
    }
    // F-35.2: include the dialog's current volume override so the test
    // preview matches the saved-state behavior (server snapshots/restores).
    const wsMsg = {
      type: 'ticker/test_chime',
      media_player_entity_id: target,
      chime_media_content_id: chimeId,
    };
    const volume = window.Ticker.AdminVolumeOverride.read(`cat-${categoryId}`);
    if (volume !== null) wsMsg.volume_override = volume;
    try {
      await panel._hass.callWS(wsMsg);
      panel._showSuccess('Chime sent');
    } catch (err) {
      panel._showError(err.message || 'Test chime failed');
    }
  },
};
