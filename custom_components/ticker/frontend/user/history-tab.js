/**
 * Ticker User Panel - History Tab
 * Displays notification history with grouping by notification_id.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.UserHistoryTab = {
  /**
   * Render the history tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, formatTimeShort, getCategoryName } = window.Ticker.utils;
    const { history, categories } = state;

    if (history.length === 0) {
      return '<div class="card"><div class="empty-state"><p>No notification history yet.</p></div></div>';
    }

    // Group entries by notification_id, then by date
    const notifications = [];
    const groupedById = {};

    for (const entry of history) {
      const nid = entry.notification_id;
      if (nid) {
        if (!groupedById[nid]) {
          groupedById[nid] = {
            notification_id: nid,
            title: entry.title,
            message: entry.message,
            category_id: entry.category_id,
            timestamp: entry.timestamp,
            image_url: entry.image_url || null,
            devices: [],
          };
          notifications.push(groupedById[nid]);
        }
        if (entry.notify_service) {
          groupedById[nid].devices.push(entry.notify_service);
        }
      } else {
        // Legacy entry without notification_id
        notifications.push({
          title: entry.title,
          message: entry.message,
          category_id: entry.category_id,
          timestamp: entry.timestamp,
          image_url: entry.image_url || null,
          devices: entry.notify_service ? [entry.notify_service] : [],
        });
      }
    }

    // Group by date
    const grouped = {};
    for (const notif of notifications) {
      const date = new Date(notif.timestamp);
      const dateKey = date.toLocaleDateString(undefined, {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      });
      if (!grouped[dateKey]) grouped[dateKey] = [];
      grouped[dateKey].push(notif);
    }

    const sections = Object.entries(grouped).map(([dateLabel, entries]) => {
      const items = entries.map(notif => {
        const escTitle = esc(notif.title);
        const escMessage = esc(notif.message);
        const escCatName = esc(getCategoryName(categories, notif.category_id));
        const time = formatTimeShort(notif.timestamp);
        const deviceTags = notif.devices.length > 0
          ? notif.devices.map(d => `<span class="notify-service-tag">${esc(d)}</span>`).join('')
          : '';

        let imageHtml = '';
        if (notif.image_url) {
          if (notif.image_url.startsWith('media-source://')) {
            imageHtml = '<div class="history-item-image"><ha-icon icon="mdi:image"></ha-icon></div>';
          } else {
            imageHtml = `<div class="history-item-image"><img src="${esc(notif.image_url)}" alt="Notification image" loading="lazy" onerror="this.parentElement.style.display='none'" /></div>`;
          }
        }

        return `
          <div class="history-item">
            <div class="history-item-header">
              <span class="history-item-title">${escTitle}</span>
              <span class="history-item-time">${time}</span>
            </div>
            <div class="history-item-message">${escMessage}</div>
            ${imageHtml}
            <div class="history-item-meta">
              <span class="notify-service-tag">${escCatName}</span>
              ${deviceTags}
            </div>
          </div>
        `;
      }).join('');

      return `
        <div class="history-date-group">
          <div class="history-date-label">${esc(dateLabel)}</div>
          ${items}
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <h2 class="card-title">Notification History</h2>
        <p class="card-description">Notifications sent to your devices in the last 7 days.</p>
        <div class="history-list">
          ${sections}
        </div>
      </div>
    `;
  },

  /**
   * Get grouped history count.
   * @param {Array} history - History entries
   * @returns {number} - Count of unique notifications
   */
  getGroupedCount(history) {
    const seen = new Set();
    let count = 0;
    for (const entry of history) {
      const nid = entry.notification_id;
      if (nid) {
        if (!seen.has(nid)) {
          seen.add(nid);
          count++;
        }
      } else {
        count++;
      }
    }
    return count;
  },
};
