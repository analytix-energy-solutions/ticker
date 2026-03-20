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
    const { logs, logStats, users, categories } = state;

    const byOutcome = logStats.by_outcome || {};

    const statsGrid = `
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">${logStats.total || 0}</div>
          <div class="stat-label">Total</div>
        </div>
        <div class="stat-card stat-sent">
          <div class="stat-value">${byOutcome.sent || 0}</div>
          <div class="stat-label">Sent</div>
        </div>
        <div class="stat-card stat-queued">
          <div class="stat-value">${byOutcome.queued || 0}</div>
          <div class="stat-label">Queued</div>
        </div>
        <div class="stat-card stat-skipped">
          <div class="stat-value">${byOutcome.skipped || 0}</div>
          <div class="stat-label">Skipped</div>
        </div>
        <div class="stat-card stat-failed">
          <div class="stat-value">${byOutcome.failed || 0}</div>
          <div class="stat-label">Failed</div>
        </div>
        ${byOutcome.snoozed ? `
        <div class="stat-card stat-skipped">
          <div class="stat-value">${byOutcome.snoozed}</div>
          <div class="stat-label">Snoozed</div>
        </div>
        ` : ''}
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

    const rows = logs.map(log => {
      const escTitle = esc(log.title);
      const escMessage = esc(log.message);
      const escPname = esc(this._getPersonName(users, log.person_id));
      const escCname = esc(getCategoryName(categories, log.category_id));
      const escService = log.notify_service ? esc(log.notify_service) : '';
      const escReason = log.reason ? esc(log.reason) : '';
      const badge = this._getOutcomeBadge(log.outcome);

      return `
        <div class="log-item">
          <div class="log-item-main">
            <div class="log-item-header">
              ${badge}
              <span class="log-item-title">${escTitle}</span>
            </div>
            <div class="log-item-message">${escMessage}</div>
            <div class="log-item-meta">
              <span>To: ${escPname}</span>
              <span>·</span>
              <span>Cat: ${escCname}</span>
              ${escService ? `<span>·</span><span>Via: ${escService}</span>` : ''}
              ${escReason ? `<span>·</span><span class="log-reason">${escReason}</span>` : ''}
              ${log.action_taken ? `<span>·</span><span style="background:rgba(6,182,212,0.1);color:#0e7490;padding:2px 8px;border-radius:10px;font-size:11px">${esc(this._getPersonName(users, log.person_id))} · ${esc(log.action_taken.title || '')}</span>` : ''}
            </div>
          </div>
          <div class="log-item-time">${formatTime(log.timestamp)}</div>
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Logs</h2>
          <button class="btn btn-danger btn-small" onclick="window.Ticker.AdminLogsTab.handlers.clearLogs(window.Ticker._adminPanel)">Clear</button>
        </div>
        <p class="card-description">7 days, max 500.</p>
        ${statsGrid}
        ${rows}
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
  },
};
