/**
 * Ticker Admin Panel - Logs Tab
 * Displays notification logs with statistics.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminLogsTab = {
  /**
   * Render the logs tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, escAttr, formatTime, getCategoryName } = window.Ticker.utils;
    const {
      logs, logStats, users, categories, statusFilter,
      logsSearch, logsCategory, logsPerson, logsDateFrom, logsDateTo,
    } = state;

    const byOutcome = logStats.by_outcome || {};

    // F-26 (admin): build the filter chain. F-24 status filter composes with
    // F-26 text/category/person/date filters via AND logic. Counters below
    // always show UNFILTERED totals from logStats so users see what clicking
    // would restore.
    const searchRaw = (logsSearch || '').trim();
    const searchLower = searchRaw.toLowerCase();
    const catFilter = (logsCategory || '').trim();
    const personFilter = (logsPerson || '').trim();
    const dateFromKey = (logsDateFrom || '').trim();
    const dateToKey = (logsDateTo || '').trim();

    function toLocalDateKey(iso) {
      if (!iso) return '';
      const d = new Date(iso);
      if (isNaN(d.getTime())) return '';
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${dd}`;
    }

    const filteredLogs = logs.filter(log => {
      if (statusFilter && log.outcome !== statusFilter) return false;
      if (catFilter && log.category_id !== catFilter) return false;
      if (personFilter && log.person_id !== personFilter) return false;
      if (dateFromKey || dateToKey) {
        const k = toLocalDateKey(log.timestamp);
        if (!k) return false;
        if (dateFromKey && k < dateFromKey) return false;
        if (dateToKey && k > dateToKey) return false;
      }
      if (searchLower) {
        const hay = [
          log.title || '',
          log.message || '',
          (log.data && log.data.image) || '',
          log.notify_service || '',
          log.reason || '',
        ].join(' ').toLowerCase();
        if (!hay.includes(searchLower)) return false;
      }
      return true;
    });

    // F-24: Build stat-card classes with active marker
    const totalActive = !statusFilter ? ' active' : '';
    const sentActive = statusFilter === 'sent' ? ' active' : '';
    const queuedActive = statusFilter === 'queued' ? ' active' : '';
    const skippedActive = statusFilter === 'skipped' ? ' active' : '';
    const failedActive = statusFilter === 'failed' ? ' active' : '';
    const snoozedActive = statusFilter === 'snoozed' ? ' active' : '';
    const expiredActive = statusFilter === 'expired' ? ' active' : '';

    const statsGrid = `
      <div class="stats-grid">
        <div class="stat-card${totalActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, null)">
          <div class="stat-value">${logStats.total || 0}</div>
          <div class="stat-label">Total</div>
        </div>
        <div class="stat-card stat-sent${sentActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'sent')">
          <div class="stat-value">${byOutcome.sent || 0}</div>
          <div class="stat-label">Sent</div>
        </div>
        <div class="stat-card stat-queued${queuedActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'queued')">
          <div class="stat-value">${byOutcome.queued || 0}</div>
          <div class="stat-label">Queued</div>
        </div>
        <div class="stat-card stat-skipped${skippedActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'skipped')">
          <div class="stat-value">${byOutcome.skipped || 0}</div>
          <div class="stat-label">Skipped</div>
        </div>
        <div class="stat-card stat-failed${failedActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'failed')">
          <div class="stat-value">${byOutcome.failed || 0}</div>
          <div class="stat-label">Failed</div>
        </div>
        ${byOutcome.snoozed ? `
        <div class="stat-card stat-skipped${snoozedActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'snoozed')">
          <div class="stat-value">${byOutcome.snoozed}</div>
          <div class="stat-label">Snoozed</div>
        </div>
        ` : ''}
        ${byOutcome.expired ? `
        <div class="stat-card stat-expired${expiredActive}" onclick="window.Ticker.AdminLogsTab.handlers.setFilter(window.Ticker._adminPanel, 'expired')">
          <div class="stat-value">${byOutcome.expired}</div>
          <div class="stat-label">Expired</div>
        </div>
        ` : ''}
      </div>
    `;

    // F-26 (admin): category + person dropdown options, built from the
    // distinct ids present in the currently loaded log list so users only
    // see options that could actually match a row.
    const catIds = [...new Set(logs.map(l => l.category_id).filter(Boolean))];
    catIds.sort((a, b) => {
      const an = getCategoryName(categories, a).toLowerCase();
      const bn = getCategoryName(categories, b).toLowerCase();
      return an.localeCompare(bn);
    });
    const categoryOptionsHtml = [
      `<option value="">All categories</option>`,
      ...catIds.map(cid => {
        const selected = catFilter === cid ? ' selected' : '';
        return `<option value="${escAttr(cid)}"${selected}>${esc(getCategoryName(categories, cid))}</option>`;
      }),
    ].join('');

    const personIds = [...new Set(logs.map(l => l.person_id).filter(Boolean))];
    personIds.sort((a, b) => {
      const an = this._getPersonName(users, a).toLowerCase();
      const bn = this._getPersonName(users, b).toLowerCase();
      return an.localeCompare(bn);
    });
    const personOptionsHtml = [
      `<option value="">All users</option>`,
      ...personIds.map(pid => {
        const selected = personFilter === pid ? ' selected' : '';
        return `<option value="${escAttr(pid)}"${selected}>${esc(this._getPersonName(users, pid))}</option>`;
      }),
    ].join('');

    const filterBar = `
      <div class="history-filter-bar" role="search">
        <label class="visually-hidden" for="ticker-logs-search">Search logs</label>
        <input
          id="ticker-logs-search"
          type="search"
          placeholder="Search title, message, service, reason..."
          value="${escAttr(searchRaw)}"
          oninput="window.Ticker._adminPanel._setLogsFilter('logsSearch', this.value)"
        >
        <label class="visually-hidden" for="ticker-logs-category">Filter by category</label>
        <select
          id="ticker-logs-category"
          onchange="window.Ticker._adminPanel._setLogsFilter('logsCategory', this.value)"
        >${categoryOptionsHtml}</select>
        <label class="visually-hidden" for="ticker-logs-person">Filter by user</label>
        <select
          id="ticker-logs-person"
          onchange="window.Ticker._adminPanel._setLogsFilter('logsPerson', this.value)"
        >${personOptionsHtml}</select>
        <label class="visually-hidden" for="ticker-logs-date-from">From date</label>
        <input
          id="ticker-logs-date-from"
          type="date"
          value="${escAttr(dateFromKey)}"
          onchange="window.Ticker._adminPanel._setLogsFilter('logsDateFrom', this.value)"
        >
        <label class="visually-hidden" for="ticker-logs-date-to">To date</label>
        <input
          id="ticker-logs-date-to"
          type="date"
          value="${escAttr(dateToKey)}"
          onchange="window.Ticker._adminPanel._setLogsFilter('logsDateTo', this.value)"
        >
      </div>
    `;

    if (!logs.length) {
      return `
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">Logs</h2>
          </div>
          ${statsGrid}
          <div class="empty-state">No logs.</div>
        </div>
      `;
    }

    const rows = filteredLogs.map(log => {
      const escTitle = esc(log.title);
      const escMessage = esc(log.message);
      const escPname = esc(this._getPersonName(users, log.person_id));
      const escCname = esc(getCategoryName(categories, log.category_id));
      const escService = log.notify_service ? esc(log.notify_service) : '';
      const escReason = log.reason ? esc(log.reason) : '';
      const badge = this._getOutcomeBadge(log.outcome);
      const logIdAttr = window.Ticker.utils.escAttr(log.log_id || '');
      const deleteBtn = log.log_id
        ? `<button class="btn btn-danger btn-small" title="Delete entry" onclick="window.Ticker.AdminLogsTab.handlers.deleteEntry(window.Ticker._adminPanel, '${logIdAttr}')">&times;</button>`
        : '';

      return `
        <div class="log-item">
          <div class="log-item-main">
            <div class="log-item-header">
              ${badge}
              <span class="log-item-title">${escTitle}</span>
              <span class="log-item-time">${formatTime(log.timestamp)}</span>
              ${deleteBtn}
            </div>
            <div class="log-item-message">${escMessage}</div>
            <div class="log-item-meta">
              <span>To: ${escPname}</span>
              <span>·</span>
              <span>Cat: ${escCname}</span>
              ${escService ? `<span>·</span><span>Via: ${escService}</span>` : ''}
              ${escReason ? `<span>·</span><span class="log-reason">${escReason}</span>` : ''}
              ${log.action_taken ? `<span>·</span><span style="background:var(--ticker-500-alpha-10);color:var(--ticker-700,#0e7490);padding:2px 8px;border-radius:10px;font-size:11px">${esc(this._getPersonName(users, log.person_id))} · ${esc(log.action_taken.title || '')}</span>` : ''}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // F-26 (admin): when filters reduce the list to zero, keep the filter
    // bar visible and explain why.
    const anyFilterActive = !!(statusFilter || searchRaw || catFilter || personFilter || dateFromKey || dateToKey);
    const rowsOrEmpty = filteredLogs.length
      ? rows
      : anyFilterActive
        ? `<div class="empty-state history-filter-empty">No matches. Clear filters to see all.</div>`
        : `<div class="empty-state">No logs.</div>`;

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Logs</h2>
          <button class="btn btn-danger btn-small" onclick="window.Ticker.AdminLogsTab.handlers.clearLogs(window.Ticker._adminPanel)">Clear</button>
        </div>
        <p class="card-description">Notification log — last 7 days, up to 500 entries.</p>
        ${statsGrid}
        ${filterBar}
        ${rowsOrEmpty}
      </div>
    `;
  },

  /**
   * Get person name by ID.
   * @param {Array} users - Users array
   * @param {string} personId - Person ID
   * @returns {string} - Person name or ID
   */
  _getPersonName(users, personId) {
    const user = users.find(x => x.person_id === personId);
    return user ? user.name : personId;
  },

  /**
   * Get badge HTML for outcome.
   * @param {string} outcome - Log outcome
   * @returns {string} - Badge HTML
   */
  _getOutcomeBadge(outcome) {
    const { esc } = window.Ticker.utils;

    switch (outcome) {
      case 'sent':
        return '<span class="badge badge-success">Sent</span>';
      case 'queued':
        return '<span class="badge">Queued</span>';
      case 'skipped':
        return '<span class="badge badge-warning">Skipped</span>';
      case 'snoozed':
        return '<span class="badge badge-warning">Snoozed</span>';
      case 'failed':
        return '<span class="badge badge-danger">Failed</span>';
      case 'expired':
        return '<span class="badge badge-muted">Expired</span>';
      default:
        return `<span class="badge">${esc(outcome)}</span>`;
    }
  },

  /**
   * Handler methods.
   */
  handlers: {
    async clearLogs(panel) {
      if (!confirm('Clear logs?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/logs/clear',
        });
        await Promise.all([panel._loadLogs(), panel._loadLogStats()]);
        // BUG-040: Preserve scroll position during same-tab update
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Cleared');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    /**
     * F-24: Set log status filter (client-side only — no reload).
     * @param {Object} panel - Admin panel instance
     * @param {string|null} status - Outcome to filter by, or null for all
     */
    setFilter(panel, status) {
      if (!panel) return;
      panel._statusFilter = status;
      panel._renderTabContentPreserveScroll();
    },

    /**
     * F-32: Delete a single log entry by log_id.
     * @param {Object} panel - Admin panel instance
     * @param {string} logId - The log entry's UUID
     */
    async deleteEntry(panel, logId) {
      if (!logId) return;
      if (!confirm('Delete this log entry?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/logs/remove',
          log_id: logId,
        });
        await Promise.all([panel._loadLogs(), panel._loadLogStats()]);
        panel._renderTabContentPreserveScroll();
        panel._showSuccess('Entry deleted');
      } catch (err) {
        panel._showError(err.message || 'Failed to delete entry');
      }
    },
  },
};
