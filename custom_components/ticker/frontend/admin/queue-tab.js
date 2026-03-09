/**
 * Ticker Admin Panel - Queue Tab
 * Displays and manages queued notifications grouped by person.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminQueueTab = {
  /**
   * Render the queue tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, escAttr, formatTime, getCategoryName } = window.Ticker.utils;
    const { queue, users, categories } = state;

    if (!queue.length) {
      return `
        <div class="card">
          <div class="empty-state">No queued notifications.</div>
        </div>
      `;
    }

    // Group by person
    const byPerson = {};
    for (const entry of queue) {
      if (!byPerson[entry.person_id]) {
        byPerson[entry.person_id] = [];
      }
      byPerson[entry.person_id].push(entry);
    }

    const sections = Object.entries(byPerson).map(([personId, entries]) => {
      const escPid = escAttr(personId);
      const escPname = esc(this._getPersonName(users, personId));

      const rows = entries.map(entry => {
        const escQid = escAttr(entry.queue_id);
        const escTitle = esc(entry.title);
        const escMessage = esc(entry.message);
        const escCname = esc(getCategoryName(categories, entry.category_id));

        return `
          <div class="queue-item">
            <div class="queue-item-content">
              <div class="queue-item-title">${escTitle}</div>
              <div class="queue-item-message">${escMessage}</div>
              <div class="queue-item-meta">
                Cat: ${escCname} · Q: ${formatTime(entry.created_at)} · Exp: ${formatTime(entry.expires_at)}
              </div>
            </div>
            <button class="btn btn-danger btn-small" onclick="window.Ticker.AdminQueueTab.handlers.removeEntry(window.Ticker._adminPanel, '${escQid}')">×</button>
          </div>
        `;
      }).join('');

      return `
        <div class="card">
          <div class="card-header">
            <h2 class="card-title">${escPname} <span class="badge">${entries.length}</span></h2>
            <button class="btn btn-danger btn-small" onclick="window.Ticker.AdminQueueTab.handlers.clearForPerson(window.Ticker._adminPanel, '${escPid}')">Clear</button>
          </div>
          ${rows}
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <h2 class="card-title">Queue</h2>
        <p class="card-description">Waiting for conditions to be met.</p>
      </div>
      ${sections}
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
   * Handler methods.
   */
  handlers: {
    async clearForPerson(panel, personId) {
      if (!confirm('Clear queue?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/queue/clear',
          person_id: personId,
        });
        await panel._loadQueue();
        panel._renderTabContent();
        panel._showSuccess('Cleared');
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async removeEntry(panel, queueId) {
      try {
        await panel._hass.callWS({
          type: 'ticker/queue/remove',
          queue_id: queueId,
        });
        await panel._loadQueue();
        panel._renderTabContent();
      } catch (err) {
        panel._showError(err.message);
      }
    },
  },
};
