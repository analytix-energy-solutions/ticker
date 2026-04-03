/**
 * Ticker Navigation Picker - Shared component for navigate_to selection (F-22)
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.NavigationPicker = {
  /**
   * Render a navigate_to picker as HTML string.
   * @param {string} currentValue - current navigate_to value or ''
   * @param {string} idSuffix - unique suffix for element IDs
   * @param {Object|Array} data - { panels, dashboards, views } or legacy dashboards array
   * @returns {string} HTML string
   */
  render(currentValue, idSuffix, data) {
    // Backward compat: array treated as dashboards-only
    if (Array.isArray(data)) data = { dashboards: data, panels: [], views: {} };
    const panels = data.panels || [];
    const dashboards = data.dashboards || [];
    const views = data.views || {};

    const { esc, escAttr } = window.Ticker.utils;
    const val = currentValue || '';
    const allValues = [];
    const groups = [];

    // --- Ticker group (hardcoded) ---
    const tickerItems = [
      { value: '/ticker#history', label: 'Notification History' },
      { value: '/ticker-admin', label: 'Ticker Admin' },
    ];
    const tickerOpts = tickerItems.map(i => {
      allValues.push(i.value);
      const sel = val === i.value ? ' selected' : '';
      return `<option value="${escAttr(i.value)}"${sel}>${esc(i.label)}</option>`;
    }).join('');
    groups.push(`<optgroup label="Ticker">${tickerOpts}</optgroup>`);

    // --- Dashboards group (from dashboards + views) ---
    const dashOpts = [];
    // Default dashboard
    const defPath = '/lovelace';
    allValues.push(defPath);
    const defSel = val === defPath ? ' selected' : '';
    dashOpts.push(`<option value="${escAttr(defPath)}"${defSel}>${esc('Overview (Default)')}</option>`);
    // Default dashboard views
    const defViews = views[''] || [];
    for (const v of defViews) {
      const vPath = `/lovelace/${v.path}`;
      allValues.push(vPath);
      const vSel = val === vPath ? ' selected' : '';
      dashOpts.push(`<option value="${escAttr(vPath)}"${vSel}>&nbsp;&nbsp;\u21b3 ${esc(v.title || v.path)}</option>`);
    }
    // User dashboards
    for (const d of dashboards) {
      const dPath = `/${d.url_path}`;
      allValues.push(dPath);
      const dSel = val === dPath ? ' selected' : '';
      dashOpts.push(`<option value="${escAttr(dPath)}"${dSel}>${esc(d.title || d.url_path)}</option>`);
      // Dashboard views
      const dViews = views[d.url_path] || [];
      for (const v of dViews) {
        const vPath = `/${d.url_path}/${v.path}`;
        allValues.push(vPath);
        const vSel = val === vPath ? ' selected' : '';
        dashOpts.push(`<option value="${escAttr(vPath)}"${vSel}>&nbsp;&nbsp;\u21b3 ${esc(v.title || v.path)}</option>`);
      }
    }
    if (dashOpts.length) {
      groups.push(`<optgroup label="Dashboards">${dashOpts.join('')}</optgroup>`);
    }

    // --- Sidebar group (from panels, skip lovelace-prefixed) ---
    const sidebarOpts = [];
    for (const p of panels) {
      if (p.url_path && p.url_path.startsWith('lovelace')) continue;
      const pPath = `/${p.url_path}`;
      allValues.push(pPath);
      const pSel = val === pPath ? ' selected' : '';
      sidebarOpts.push(`<option value="${escAttr(pPath)}"${pSel}>${esc(p.title || p.url_path)}</option>`);
    }
    if (sidebarOpts.length) {
      groups.push(`<optgroup label="Sidebar">${sidebarOpts.join('')}</optgroup>`);
    }

    // --- Settings group (hardcoded) ---
    const settingsItems = [
      { value: '/config', label: 'Settings' },
      { value: '/config/devices', label: 'Devices' },
      { value: '/config/integrations', label: 'Integrations' },
      { value: '/config/automation/dashboard', label: 'Automations' },
      { value: '/config/script', label: 'Scripts' },
      { value: '/config/scene', label: 'Scenes' },
      { value: '/config/helpers', label: 'Helpers' },
      { value: '/config/areas', label: 'Areas' },
    ];
    const settingsOpts = settingsItems.map(i => {
      allValues.push(i.value);
      const sel = val === i.value ? ' selected' : '';
      return `<option value="${escAttr(i.value)}"${sel}>${esc(i.label)}</option>`;
    }).join('');
    groups.push(`<optgroup label="Settings">${settingsOpts}</optgroup>`);

    // --- Custom ---
    const isCustom = val && !allValues.includes(val);
    const noneSelected = !val ? ' selected' : '';
    const customSelected = isCustom ? ' selected' : '';
    const customDisplay = isCustom ? '' : 'display:none;';

    return `
      <div class="form-group" style="margin-top:12px">
        <label>Tap action navigation</label>
        <select id="nav-preset-${escAttr(idSuffix)}" class="form-select" style="width:100%;box-sizing:border-box"
          onchange="window.Ticker.NavigationPicker._onChange(this)">
          <option value=""${noneSelected}>None (default behavior)</option>
          ${groups.join('')}
          <option value="__custom__"${customSelected}>Custom path...</option>
        </select>
        <input type="text" id="nav-custom-${escAttr(idSuffix)}" class="form-input"
          style="margin-top:4px;width:100%;box-sizing:border-box;${customDisplay}"
          placeholder="/lovelace/my-dashboard" value="${escAttr(isCustom ? val : '')}">
        <div style="font-size:12px;color:var(--text-secondary);margin-top:2px">
          Where to navigate when user taps the notification
        </div>
      </div>
    `;
  },

  /**
   * Handle select change: show/hide custom input.
   * @param {HTMLSelectElement} el - The select element
   */
  _onChange(el) {
    const customInput = el.parentElement.querySelector('input[id^="nav-custom-"]');
    if (!customInput) return;
    customInput.style.display = el.value === '__custom__' ? '' : 'none';
  },

  /**
   * Read the current value from the picker.
   * @param {ShadowRoot|Element} root
   * @param {string} idSuffix
   * @returns {string|null} path string or null (clear)
   */
  read(root, idSuffix) {
    const preset = root.getElementById(`nav-preset-${idSuffix}`)?.value || '';
    if (!preset) return '';
    if (preset === '__custom__') {
      return root.getElementById(`nav-custom-${idSuffix}`)?.value?.trim() || null;
    }
    return preset;
  },
};
