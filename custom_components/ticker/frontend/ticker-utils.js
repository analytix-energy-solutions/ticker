/**
 * Ticker Shared Utilities
 * Used by all Ticker frontend panels and components.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.utils = {
  /**
   * Escape HTML special characters to prevent XSS.
   * @param {string|null|undefined} str - The string to escape
   * @returns {string} - The escaped string
   */
  esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  },

  /**
   * Escape for HTML attribute values.
   * @param {string|null|undefined} str - The string to escape
   * @returns {string} - The escaped string safe for attributes
   */
  escAttr(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  },

  /**
   * Format ISO timestamp to locale string.
   * @param {string} isoString - ISO date string
   * @returns {string} - Formatted locale string
   */
  formatTime(isoString) {
    return new Date(isoString).toLocaleString();
  },

  /**
   * Format ISO timestamp to time only (HH:MM).
   * @param {string} isoString - ISO date string
   * @returns {string} - Formatted time string
   */
  formatTimeShort(isoString) {
    return new Date(isoString).toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit',
    });
  },

  /**
   * Get zone friendly name from zone list.
   * @param {Array} zones - Array of zone objects with zone_id and name
   * @param {string} zoneId - Zone entity ID
   * @returns {string} - Friendly name or cleaned ID
   */
  getZoneName(zones, zoneId) {
    const zone = zones.find(z => z.zone_id === zoneId);
    return zone ? zone.name : zoneId.replace('zone.', '');
  },

  /**
   * Get device friendly name from device list.
   * @param {Array} devices - Array of device objects with service and name
   * @param {string} serviceId - Service ID
   * @returns {string} - Friendly name or service ID
   */
  getDeviceName(devices, serviceId) {
    const device = devices.find(d => d.service === serviceId);
    return device ? device.name : serviceId;
  },

  /**
   * Get category name from category list.
   * @param {Array} categories - Array of category objects with id and name
   * @param {string} catId - Category ID
   * @returns {string} - Category name or ID
   */
  getCategoryName(categories, catId) {
    const cat = categories.find(c => c.id === catId);
    return cat ? cat.name : catId;
  },

  /**
   * Render a single queue item card (shared by admin and user panels).
   * @param {Object} entry - Queue entry object
   * @param {Object} options - Rendering options
   * @param {Array} options.categories - Category list for name lookup
   * @param {string} [options.removeHandler] - Handler function name for remove button
   * @returns {string} - HTML string
   */
  renderQueueItem(entry, options) {
    const { esc, escAttr, formatTime, getCategoryName } = window.Ticker.utils;
    const escQueueId = escAttr(entry.queue_id);
    const escTitle = esc(entry.title);
    const escMessage = esc(entry.message);
    const escCatName = esc(getCategoryName(options.categories, entry.category_id));
    const removeHandler = options.removeHandler
      ? `onclick="${escAttr(options.removeHandler)}('${escQueueId}')"`
      : '';
    return `
      <div class="queue-item">
        <div class="queue-item-header">
          <span class="queue-item-title">${escTitle}</span>
          ${removeHandler ? `<button class="btn btn-danger btn-small" ${removeHandler}>×</button>` : ''}
        </div>
        <div class="queue-item-message">${escMessage}</div>
        <div class="queue-item-meta">
          <span>Category: ${escCatName}</span>
          <span>Queued: ${formatTime(entry.created_at)}</span>
          <span>Expires: ${formatTime(entry.expires_at)}</span>
        </div>
      </div>
    `;
  },

  /**
   * Generate a category ID from a name.
   * @param {string} name - Category name
   * @returns {string} - Slugified category ID
   */
  generateCategoryId(name) {
    return name
      .toLowerCase()
      .trim()
      .replace(/[àáâãäå]/g, 'a')
      .replace(/[èéêë]/g, 'e')
      .replace(/[ìíîï]/g, 'i')
      .replace(/[òóôõö]/g, 'o')
      .replace(/[ùúûü]/g, 'u')
      .replace(/[ñ]/g, 'n')
      .replace(/[ç]/g, 'c')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .replace(/_+/g, '_');
  },
};

/**
 * Sidebar toggle for the panel_custom panels (BUG-111 / GitHub #51, @danswett).
 *
 * HA renders no toolbar for custom panels, so on mobile portrait there is no
 * hamburger to open the sidebar drawer. Both the user and admin panels share
 * this concern; it lives here (loaded by both) so the near-full panel and
 * style files stay under the 500-line limit. Colors use brand tokens and the
 * SVG uses currentColor per branding/README.md. The button is hidden by
 * default and revealed via .visible only when HA reports the panel as narrow.
 */
window.Ticker.SidebarToggle = {
  /** Raw inline hamburger SVG (currentColor). */
  ICON: '<svg viewBox="0 0 24 24"><path d="M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z"></path></svg>',

  /** Scoped CSS injected into each panel's shadow root <style> block. */
  STYLE: `
    .menu-button {
      display: none;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      flex: 0 0 auto;
      width: 40px;
      height: 40px;
      margin-left: -8px;
      padding: 8px;
      border: none;
      background: none;
      color: var(--text-primary);
      border-radius: 50%;
      cursor: pointer;
      -webkit-tap-highlight-color: transparent;
    }
    .menu-button.visible { display: inline-flex; }
    .menu-button:hover { background: var(--ticker-500-alpha-8, rgba(6, 182, 212, 0.08)); }
    .menu-button:focus-visible { outline: 2px solid var(--ticker-500); outline-offset: 2px; }
    .menu-button svg { display: block; width: 24px; height: 24px; fill: currentColor; }
  `,

  /**
   * Header hamburger button markup. Prepend as the first header child.
   * @returns {string} - HTML string for the menu button
   */
  buttonHtml() {
    return `<button class="menu-button" type="button" title="Menu"`
      + ` aria-label="Open sidebar menu"`
      + ` onclick="window.Ticker.SidebarToggle.toggleMenu(this)">${this.ICON}</button>`;
  },

  /**
   * Reflect HA's narrow state onto the button. Null-safe: narrow may be set
   * before the shadow DOM is built, so callers also re-invoke after render.
   * @param {HTMLElement} panel - The panel custom element
   * @param {boolean} narrow - HA-reported narrow flag
   */
  applyNarrow(panel, narrow) {
    const btn = panel.shadowRoot && panel.shadowRoot.querySelector('.menu-button');
    if (btn) btn.classList.toggle('visible', !!narrow);
  },

  /**
   * Dispatch HA's global sidebar-toggle event from the in-shadow button.
   * composed:true lets it cross the shadow boundary up to <home-assistant-main>.
   * @param {HTMLElement} btn - The clicked button (event dispatch source)
   */
  toggleMenu(btn) {
    btn.dispatchEvent(
      new CustomEvent('hass-toggle-menu', { bubbles: true, composed: true }),
    );
  },
};
