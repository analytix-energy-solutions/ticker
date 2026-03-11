/**
 * Ticker User Panel - Queue Tab
 * Handles queued notifications display and management.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.UserQueueTab = {
  /**
   * Render the queue tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { esc, escAttr, formatTime, getCategoryName } = window.Ticker.utils;
    const { queue, categories } = state;

    if (queue.length === 0) {
      return '<div class="card"><div class="empty-state"><p>No queued notifications.</p></div></div>';
    }

    const queueItems = queue.map(entry => {
      const escQueueId = escAttr(entry.queue_id);
      const escTitle = esc(entry.title);
      const escMessage = esc(entry.message);
      const escCatName = esc(getCategoryName(categories, entry.category_id));

      return `
        <div class="queue-item">
          <div class="queue-item-header">
            <span class="queue-item-title">${escTitle}</span>
            <button class="btn btn-danger btn-small"
              onclick="window.Ticker.UserQueueTab.handlers.removeEntry(window.Ticker._userPanel, '${escQueueId}')">×</button>
          </div>
          <div class="queue-item-message">${escMessage}</div>
          <div class="queue-item-meta">
            <span>Category: ${escCatName}</span>
            <span>Queued: ${formatTime(entry.created_at)}</span>
            <span>Expires: ${formatTime(entry.expires_at)}</span>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="card">
        <div class="card-header">
          <h2 class="card-title">Queued Notifications</h2>
          <button class="btn btn-danger btn-small"
            onclick="window.Ticker.UserQueueTab.handlers.clearQueue(window.Ticker._userPanel)">Clear All</button>
        </div>
        <p class="card-description">These notifications will be delivered when all conditions are met.</p>
        <div class="queue-list">
          ${queueItems}
        </div>
      </div>
    `;
  },

  /**
   * Handler methods.
   */
  handlers: {
    async clearQueue(panel) {
      if (!panel._currentPerson) return;
      if (!confirm('Clear all queued notifications?')) return;

      try {
        await panel._hass.callWS({
          type: 'ticker/queue/clear',
          person_id: panel._currentPerson.person_id,
        });
        await panel._loadQueue();
        panel._renderTabContent();
        panel._showSuccess('Queue cleared');
      } catch (err) {
        panel._showError(err.message || 'Failed to clear queue');
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
        panel._showError(err.message || 'Failed to remove entry');
      }
    },
  },
};
