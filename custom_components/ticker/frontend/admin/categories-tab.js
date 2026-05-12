/** Ticker Admin Panel - Categories Tab. Brand: see branding/README.md */
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
      <div class="form-group" style="margin-top:12px">
        <label>Android Channel</label>
        <input type="text" id="edit-android-channel-${escId}" value="${escAttr(c.android_channel || '')}" placeholder="e.g. security_alerts" style="min-width:180px">
        <div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:2px">
          Android notification channel for per-category sound and DND routing
        </div>
      </div>
      ${this._renderCategoryVolumeBlock(c, escId)}
      ${this._renderCategoryChimeBlock(c, escId)}
      ${window.Ticker.NavigationPicker.render(c.navigate_to || '', 'cat-edit', { panels: window.Ticker._adminPanel._hasPanels || [], dashboards: window.Ticker._adminPanel._lovelaceDashboards || [], views: window.Ticker._adminPanel._lovelaceViews || {} })}
    `;
  },

  /**
   * F-35.2: Per-category volume override block. Shares the slider
   * markup with the recipient dialog via AdminVolumeOverride.render.
   */
  _renderCategoryVolumeBlock(c, escId) {
    const raw = c.volume_override;
    const volume = (typeof raw === 'number' && raw >= 0 && raw <= 1) ? raw : null;
    const helper = 'Overrides the device default for this category. Leave Default to inherit.';
    return window.Ticker.AdminVolumeOverride.render(
      `cat-${escId}`, volume, helper,
    );
  },

  /**
   * F-35: Render the per-category Pre-TTS Chime override picker. The
   * category has no inherent media_player, so the Test Chime button is
   * paired with a target dropdown populated from TTS recipients.
   *
   * F-35.1: Bundled-chime preset chips render above the URL field. The
   * chip list is loaded once per panel session into ``panel._bundledChimes``.
   */
  _renderCategoryChimeBlock(c, escId) {
    const { esc, escAttr } = window.Ticker.utils;
    const ns = 'window.Ticker.AdminCategoriesTab.handlers';
    const chimeId = c.chime_media_content_id || '';
    const recipients = (window.Ticker._adminPanel?._recipients || [])
      .filter(r => r.device_type === 'tts' && r.media_player_entity_id);
    const targetOptions = recipients.map(r => `
      <option value="${escAttr(r.media_player_entity_id)}">${esc(r.name || r.recipient_id)} (${esc(r.media_player_entity_id)})</option>
    `).join('');
    const noTarget = recipients.length === 0;
    const haveChime = !!(chimeId && chimeId.trim());
    const testDisabled = noTarget || !haveChime;
    const helper = noTarget
      ? 'No TTS device configured — add one to enable testing.'
      : 'Plays before TTS, overrides the device default. Empty = use device default. Some TTS engines (e.g. Amazon Alexa) play their own tone.';
    const presets = this._renderCategoryChimePresets(escId, chimeId);
    return `
      <div style="margin-top:12px;padding:8px;border:1px solid var(--divider);border-radius:4px">
        <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--primary-text-color,#212121);font-weight:600">Pre-TTS Chime (override)</label>
        ${presets}
        <input type="hidden" id="cat-chime-id-${escId}" value="${escAttr(chimeId)}">
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:6px">
          <input class="form-input" id="cat-chime-display-${escId}" value="${escAttr(chimeId)}" placeholder="media-source://media_source/local/chimes/alarm.mp3" style="flex:1" oninput="${ns}.onCategoryChimeInput(window.Ticker._adminPanel, '${escId}')">
          <button type="button" class="btn btn-secondary" style="padding:4px 10px;font-size:12px" onclick="${ns}.clearCategoryChime(window.Ticker._adminPanel, '${escId}')">Clear</button>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <select id="cat-chime-test-target-${escId}" class="form-select" style="font-size:12px;padding:4px 6px" ${noTarget ? 'disabled' : ''} onchange="${ns}.onCategoryChimeInput(window.Ticker._adminPanel, '${escId}')">
            ${noTarget ? '<option value="">No TTS device</option>' : targetOptions}
          </select>
          <button type="button" id="cat-chime-test-${escId}" class="btn btn-secondary" style="padding:4px 10px;font-size:12px" onclick="${ns}.testChimeFromCategory(window.Ticker._adminPanel, '${escId}')" ${testDisabled ? 'disabled' : ''}>Test Chime</button>
          <span style="font-size:11px;color:var(--secondary-text-color,#727272);flex-basis:100%">${helper}</span>
        </div>
      </div>
    `;
  },

  /** F-35.1: Render bundled-chime chips for the per-category override picker. */
  _renderCategoryChimePresets(escId, currentChime) {
    const { escAttr } = window.Ticker.utils;
    const list = (window.Ticker._adminPanel?._bundledChimes) || [];
    if (!list.length) {
      return `<div id="cat-chime-presets-${escId}" class="ticker-chime-presets" style="display:none"></div>`;
    }
    const ns = 'window.Ticker.AdminCategoriesTab.handlers';
    const chips = list.map(c => {
      const active = currentChime && currentChime === c.url ? ' active' : '';
      return `<button type="button" class="ticker-chime-chip${active}" data-chime-url="${escAttr(c.url)}" onclick="${ns}.pickBundledCategoryChime(window.Ticker._adminPanel, '${escId}', '${escAttr(c.url)}')">${escAttr(c.label)}</button>`;
    }).join('');
    return `<div id="cat-chime-presets-${escId}" class="ticker-chime-presets">${chips}</div>`;
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
    const pending = window.Ticker._adminPanel._pendingSmart?.[c.id];
    const s = Object.assign({}, c.smart_notification || {}, pending || {});
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

  // Handlers extracted to categories-handlers.js (BUG-055-style split).
};
