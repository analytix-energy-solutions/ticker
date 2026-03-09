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
