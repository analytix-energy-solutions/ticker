/**
 * Ticker Admin Panel - Users Tab
 * Handles user management and subscription toggles.
 *
 * Brand: See branding/README.md
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminUsersTab = {
  /**
   * Render the users tab content.
   * @param {Object} state - Panel state
   * @returns {string} - HTML string
   */
  render(state) {
    const { users } = state;

    if (!users.length) {
      return `
        <div class="card">
          <h2 class="card-title">Users & Subscriptions</h2>
          <div class="empty-state">No users.</div>
        </div>
      `;
    }

    const items = users.map(u => this._renderUserItem(state, u)).join('');

    return `
      <div class="card">
        <h2 class="card-title">Users & Subscriptions</h2>
        <p class="card-description">Click user to manage subscriptions.</p>
        <div class="list">
          ${items}
        </div>
      </div>
    `;
  },

  /**
   * Render a single user item.
   * @param {Object} state - Panel state
   * @param {Object} u - User object
   * @returns {string} - HTML string
   */
  _renderUserItem(state, u) {
    const { esc, escAttr } = window.Ticker.utils;
    const { expandedUsers } = state;

    const escPid = escAttr(u.person_id);
    const escName = esc(u.name);
    const expanded = u.enabled && expandedUsers.has(u.person_id);
    const canExpand = u.enabled;

    const expandIcon = canExpand ? `
      <svg class="expand-icon ${expanded ? 'open' : ''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="6,9 12,15 18,9"></polyline>
      </svg>
    ` : '';

    const notifyServices = u.notify_services.length
      ? `<div class="notify-services">${u.notify_services.map(s => `<span class="notify-service-tag">${esc(s.name || s.service || s)}</span>`).join('')}</div>`
      : '<span class="badge badge-warning">No services</span>';

    const headerStyle = canExpand ? '' : 'cursor:default';

    const header = `
      <div class="list-item-header" onclick="window.Ticker.AdminUsersTab.handlers.toggleExpanded(window.Ticker._adminPanel, '${escPid}')" style="${headerStyle}">
        <div class="list-item-content">
          <span class="list-item-title">
            ${escName}
            ${!u.enabled ? '<span class="badge badge-gray">Disabled</span>' : ''}
          </span>
          ${notifyServices}
        </div>
        <div class="list-item-actions">
          <button class="btn btn-secondary btn-small" onclick="event.stopPropagation();window.Ticker.AdminUsersTab.handlers.sendTest(window.Ticker._adminPanel, '${escPid}')" ${!u.enabled ? 'disabled' : ''}>Test</button>
          <label class="toggle" onclick="event.stopPropagation()">
            <input type="checkbox" ${u.enabled ? 'checked' : ''} onchange="window.Ticker.AdminUsersTab.handlers.toggleEnabled(window.Ticker._adminPanel, '${escPid}', ${u.enabled})">
            <span class="toggle-slider"></span>
          </label>
          ${expandIcon}
        </div>
      </div>
    `;

    const accordion = expanded ? this._renderUserSubscriptions(state, u) : '';

    return `<div class="list-item ${u.enabled ? '' : 'disabled'}">${header}${accordion}</div>`;
  },

  /**
   * Render user subscription toggles.
   * @param {Object} state - Panel state
   * @param {Object} u - User object
   * @returns {string} - HTML string
   */
  _renderUserSubscriptions(state, u) {
    const { esc, escAttr } = window.Ticker.utils;
    const { categories, subscriptions } = state;

    const escPid = escAttr(u.person_id);

    const sorted = [...categories].sort((a, b) => {
      if (a.is_default) return -1;
      if (b.is_default) return 1;
      return (a.name || a.id).localeCompare(b.name || b.id);
    });

    if (!sorted.length) {
      return `
        <div class="accordion-content">
          <p class="card-description" style="margin:12px 0 0">No categories.</p>
        </div>
      `;
    }

    const rows = sorted.map(c => {
      const escCid = escAttr(c.id);
      const escCname = esc(c.name || c.id);
      const escColor = escAttr(c.color || '');
      const sub = this._isSubscribed(subscriptions, u.person_id, c.id);
      const colorDot = c.color ? `<span class="color-indicator" style="background:${escColor}"></span>` : '';

      return `
        <div class="subscription-row">
          <span class="subscription-label">${colorDot}${escCname}</span>
          <label class="toggle">
            <input type="checkbox" ${sub ? 'checked' : ''} onchange="window.Ticker.AdminUsersTab.handlers.toggleSubscription(window.Ticker._adminPanel, '${escPid}', '${escCid}', ${sub})">
            <span class="toggle-slider"></span>
          </label>
        </div>
      `;
    }).join('');

    return `
      <div class="accordion-content">
        <div class="subscription-header">Include in notifications</div>
        <div class="subscriptions-list">
          ${rows}
        </div>
      </div>
    `;
  },

  /**
   * Check if user is subscribed to category.
   * @param {Object} subscriptions - Subscriptions map
   * @param {string} personId - Person ID
   * @param {string} categoryId - Category ID
   * @returns {boolean}
   */
  _isSubscribed(subscriptions, personId, categoryId) {
    const s = subscriptions[personId];
    return s && s[categoryId] ? s[categoryId].mode !== 'never' : true;
  },

  /**
   * Handler methods.
   */
  handlers: {
    toggleExpanded(panel, personId) {
      const user = panel._users.find(x => x.person_id === personId);
      if (user && !user.enabled) return;

      if (panel._expandedUsers.has(personId)) {
        panel._expandedUsers.delete(personId);
      } else {
        panel._expandedUsers.add(personId);
      }
      // BUG-040: Preserve scroll position during same-tab update
      panel._renderTabContentPreserveScroll();
    },

    async toggleEnabled(panel, personId, currentEnabled) {
      try {
        await panel._hass.callWS({
          type: 'ticker/user/set_enabled',
          person_id: personId,
          enabled: !currentEnabled,
        });
        if (currentEnabled) {
          panel._expandedUsers.delete(personId);
        }
        await panel._loadUsers();
        // BUG-040: Preserve scroll position during same-tab update
        panel._renderTabContentPreserveScroll();
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async toggleSubscription(panel, personId, categoryId, currentSubscribed) {
      try {
        await panel._hass.callWS({
          type: 'ticker/subscription/set',
          person_id: personId,
          category_id: categoryId,
          mode: currentSubscribed ? 'never' : 'always',
        });
        await panel._loadSubscriptions();
        // BUG-040: Preserve scroll position during same-tab update
        panel._renderTabContentPreserveScroll();
      } catch (err) {
        panel._showError(err.message);
      }
    },

    async sendTest(panel, personId) {
      try {
        const result = await panel._hass.callWS({
          type: 'ticker/test_notification',
          person_id: personId,
        });
        const ok = result.results.filter(x => x.success).length;
        const fail = result.results.filter(x => !x.success).length;

        if (!fail) {
          panel._showSuccess(`Test sent via ${ok} service(s)`);
        } else if (ok) {
          panel._showSuccess(`${ok} ok, ${fail} failed`);
        } else {
          panel._showError('All failed');
        }
      } catch (err) {
        panel._showError(err.message);
      }
    },
  },
};
