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
    const { esc, escAttr, formatTimeShort, getCategoryName } = window.Ticker.utils;
    const { history, categories } = state;
    const rawHistory = history || [];

    // Keep the "no history" empty state only when there is literally zero raw data.
    if (rawHistory.length === 0) {
      return '<div class="card"><div class="empty-state"><p>No notification history yet.</p></div></div>';
    }

    const clearBtn = `<button class="btn btn-danger btn-small" onclick="window.Ticker.UserHistoryTab.handlers.clearHistory(window.Ticker._userPanel)">Clear History</button>`;

    // F-26: read filter state
    const searchRaw = (state.historySearch || '').trim();
    const searchLower = searchRaw.toLowerCase();
    const filterCategory = state.historyCategory || '';
    const filterDateFrom = state.historyDateFrom || '';
    const filterDateTo = state.historyDateTo || '';

    // F-26: filter chain — date → category → text
    // Dates are compared on the entry's local date (YYYY-MM-DD) to match the
    // <input type="date"> value format.
    const toLocalDateKey = (ts) => {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return '';
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    };

    const filtered = rawHistory.filter((entry) => {
      // 1. Date range
      if (filterDateFrom || filterDateTo) {
        const key = toLocalDateKey(entry.timestamp);
        if (!key) return false;
        if (filterDateFrom && key < filterDateFrom) return false;
        if (filterDateTo && key > filterDateTo) return false;
      }
      // 2. Category
      if (filterCategory && entry.category_id !== filterCategory) return false;
      // 3. Text search (title + message + image_url)
      if (searchLower) {
        const hay = (
          (entry.title || '') + ' ' +
          (entry.message || '') + ' ' +
          (entry.image_url || '')
        ).toLowerCase();
        if (!hay.includes(searchLower)) return false;
      }
      return true;
    });

    // F-26: build filter bar (always shown when rawHistory has rows)
    // Unique categories present in raw history (preserve discovery order).
    const seenCatIds = new Set();
    const catOptions = [];
    for (const entry of rawHistory) {
      const cid = entry.category_id;
      if (!cid || seenCatIds.has(cid)) continue;
      seenCatIds.add(cid);
      catOptions.push({
        id: cid,
        name: getCategoryName(categories, cid),
      });
    }
    catOptions.sort((a, b) => a.name.localeCompare(b.name));

    const categoryOptionsHtml = [
      `<option value="">All categories</option>`,
      ...catOptions.map(c =>
        `<option value="${escAttr(c.id)}"${c.id === filterCategory ? ' selected' : ''}>${esc(c.name)}</option>`
      ),
    ].join('');

    const filterBar = `
      <div class="history-filter-bar" role="search">
        <label class="visually-hidden" for="ticker-history-search">Search history</label>
        <input
          id="ticker-history-search"
          type="search"
          placeholder="Search title, message, image URL..."
          value="${escAttr(searchRaw)}"
          oninput="window.Ticker._userPanel._setHistoryFilter('historySearch', this.value)"
        >
        <label class="visually-hidden" for="ticker-history-category">Filter by category</label>
        <select
          id="ticker-history-category"
          onchange="window.Ticker._userPanel._setHistoryFilter('historyCategory', this.value)"
        >${categoryOptionsHtml}</select>
        <label class="visually-hidden" for="ticker-history-date-from">From date</label>
        <input
          id="ticker-history-date-from"
          type="date"
          value="${escAttr(filterDateFrom)}"
          onchange="window.Ticker._userPanel._setHistoryFilter('historyDateFrom', this.value)"
        >
        <label class="visually-hidden" for="ticker-history-date-to">To date</label>
        <input
          id="ticker-history-date-to"
          type="date"
          value="${escAttr(filterDateTo)}"
          onchange="window.Ticker._userPanel._setHistoryFilter('historyDateTo', this.value)"
        >
      </div>
    `;

    // If filters eliminated every row, render filter bar + inline empty message.
    if (filtered.length === 0) {
      return `
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">Notification History</h2>
            ${clearBtn}
          </div>
          <p class="card-description">Notifications sent to your devices in the last 7 days.</p>
          ${filterBar}
          <div class="history-filter-empty">No matches. Clear filters to see all.</div>
        </div>
      `;
    }

    // Group entries by notification_id, then by date (operates on filtered list)
    const notifications = [];
    const groupedById = {};

    for (const entry of filtered) {
      const nid = entry.notification_id;
      const isExpired = entry.outcome === 'expired';
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
            action_taken: null,
            expired: isExpired,
          };
          notifications.push(groupedById[nid]);
        }
        // F-25: any non-expired row in the group means the user did receive
        // the notification — clear the expired flag in that case.
        if (!isExpired) {
          groupedById[nid].expired = false;
        }
        if (entry.notify_service) {
          groupedById[nid].devices.push(entry.notify_service);
        }
        if (entry.action_taken && !groupedById[nid].action_taken) {
          groupedById[nid].action_taken = entry.action_taken;
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
          expired: isExpired,
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

        const actionHtml = notif.action_taken
          ? `<div style="font-size:12px;color:var(--secondary-text-color,#727272);margin-top:4px">&#10003; You tapped: ${esc(notif.action_taken.title || '')}</div>`
          : '';

        const nidAttr = notif.notification_id
          ? window.Ticker.utils.escAttr(notif.notification_id)
          : '';
        const deleteBtn = notif.notification_id
          ? `<button class="btn btn-danger btn-small" title="Delete notification" onclick="window.Ticker.UserHistoryTab.handlers.deleteGroup(window.Ticker._userPanel, '${nidAttr}')">&times;</button>`
          : '';

        const expiredClass = notif.expired ? ' expired' : '';
        const expiredBadge = notif.expired
          ? '<span class="badge badge-muted">expired</span>'
          : '';

        return `
          <div class="history-item${expiredClass}">
            <div class="history-item-header">
              <span class="history-item-title">${escTitle}</span>
              <span class="history-item-time">${time}</span>
              ${deleteBtn}
            </div>
            <div class="history-item-message">${escMessage}</div>
            ${imageHtml}
            ${actionHtml}
            <div class="history-item-meta">
              <span class="notify-service-tag">${escCatName}</span>
              ${deviceTags}
              ${expiredBadge}
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
        <div class="card-header">
          <h2 class="card-title">Notification History</h2>
          ${clearBtn}
        </div>
        <p class="card-description">Notifications sent to your devices in the last 7 days.</p>
        ${filterBar}
        <div class="history-list">
          ${sections}
        </div>
      </div>
    `;
  },

  /**
   * Handler methods (F-32).
   */
  handlers: {
    async clearHistory(panel) {
      if (!panel || !panel._currentPerson) return;
      if (!confirm('Clear all notification history?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/logs/clear_for_person',
          person_id: panel._currentPerson.person_id,
        });
        await panel._loadHistory();
        panel._renderTabContent();
        panel._showSuccess('History cleared');
      } catch (err) {
        panel._showError(err.message || 'Failed to clear history');
      }
    },

    async deleteGroup(panel, notificationId) {
      if (!panel || !panel._currentPerson || !notificationId) return;
      if (!confirm('Delete this notification from history?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/logs/remove_group',
          notification_id: notificationId,
          person_id: panel._currentPerson.person_id,
        });
        await panel._loadHistory();
        panel._renderTabContent();
      } catch (err) {
        panel._showError(err.message || 'Failed to delete notification');
      }
    },
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
