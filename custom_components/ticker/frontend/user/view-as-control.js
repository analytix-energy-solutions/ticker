/**
 * Ticker User Panel - View-as-User Control (F-38)
 *
 * Admin-only chrome that lets an HA admin operate the user panel on behalf of
 * another household member. Backend authority is unchanged; this is purely an
 * impersonation surface in the existing user UI.
 *
 * State lives on the panel instance:
 *   panel._isAdmin               - cached at _initialize() from hass.user.is_admin
 *   panel._availableUsers        - full roster (loaded via ticker/users) for admins
 *   panel._impersonatedPersonId  - person_id when impersonating, null otherwise
 *
 * Brand: See branding/README.md. All colors via CSS variables.
 *
 * Spec: docs/SPEC_F-38_v1.7.0.md §6.1, §6.6, §6.7
 */
window.Ticker = window.Ticker || {};

window.Ticker.ViewAsControl = {
  /**
   * Render the "Viewing as" dropdown HTML. Returns '' for non-admins so the
   * DOM node is not present at all (acceptance criterion).
   * @param {TickerPanel} panel
   * @returns {string} HTML or empty string.
   */
  renderDropdown(panel) {
    if (!panel._isAdmin) return '';
    const esc = window.Ticker.utils.esc;
    const escAttr = window.Ticker.utils.escAttr;

    const currentValue = panel._impersonatedPersonId || '';
    // FIX-002: read admin's own person_id from the cached panel-level field
    // (set once at _initialize). Deriving from _currentPerson breaks during
    // impersonation because _currentPerson then holds the impersonated person.
    const adminOwnPersonId = panel._adminOwnPersonId || null;

    const options = [];
    // Placeholder when admin has no linked self (so "Myself" can't be shown).
    if (!currentValue && !adminOwnPersonId) {
      options.push('<option value="" disabled selected>— Viewing as —</option>');
    }
    // "Myself" entry — render whenever the admin has a linked person, regardless
    // of impersonation state, so the admin can always return to self-view.
    if (adminOwnPersonId) {
      const isSelected = !currentValue;
      options.push(
        `<option value=""${isSelected ? ' selected' : ''}>Myself</option>`
      );
    } else if (!currentValue) {
      // Admin has no linked person and is not impersonating — show explicit
      // "no self view" entry so the dropdown is visibly in an actionable state.
      options.push('<option value="" selected>Myself (not linked)</option>');
    }

    for (const u of panel._availableUsers || []) {
      const pid = u.person_id;
      if (!pid) continue;
      if (pid === adminOwnPersonId) continue;
      const isSelected = currentValue === pid;
      options.push(
        `<option value="${escAttr(pid)}"${isSelected ? ' selected' : ''}>${esc(u.name || pid)}</option>`
      );
    }

    return `<select class="view-as-dropdown" id="view-as-select" aria-label="Viewing as">${options.join('')}</select>`;
  },

  /**
   * Render the persistent banner shown when impersonating. Returns '' when
   * not impersonating (banner slot collapses to empty).
   * @param {TickerPanel} panel
   * @returns {string} HTML or empty string.
   */
  renderBanner(panel) {
    if (!panel._impersonatedPersonId) return '';
    const esc = window.Ticker.utils.esc;
    const match = (panel._availableUsers || []).find(
      u => u.person_id === panel._impersonatedPersonId
    );
    const name = match ? (match.name || panel._impersonatedPersonId) : panel._impersonatedPersonId;
    return `
      <div class="view-as-banner" role="status" aria-live="polite">
        <span>Viewing as: <strong>${esc(name)}</strong></span>
        <button type="button" class="view-as-stop-btn">Stop viewing</button>
      </div>
    `;
  },

  /**
   * Switch impersonation target. Resets transient view state but keeps the
   * active tab so the admin lands on the same surface for the new identity.
   * Triggers a full data refresh.
   * @param {TickerPanel} panel
   * @param {string|null} personId - target person_id, or falsy for self.
   */
  async setImpersonatedPerson(panel, personId) {
    panel._impersonatedPersonId = personId || null;
    // Reset transient view state per spec §6.7.
    panel._expandedCategories.clear();
    panel._devicePrefDirty = false;
    panel._historySearch = '';
    panel._historyCategory = '';
    panel._historyDateFrom = '';
    panel._historyDateTo = '';
    // _activeTab intentionally unchanged.
    await panel._loadData();
  },

  /**
   * Exit impersonation; restore admin self-view.
   * @param {TickerPanel} panel
   */
  async stopViewing(panel) {
    await this.setImpersonatedPerson(panel, null);
  },

  /**
   * Load the impersonated person's merged record via ticker/get_person
   * (admin-only). Used by ticker-panel.js's _loadCurrentPerson when
   * _impersonatedPersonId is set.
   * @param {TickerPanel} panel
   */
  async loadImpersonatedPerson(panel) {
    try {
      const result = await panel._hass.callWS({
        type: 'ticker/get_person',
        person_id: panel._impersonatedPersonId,
      });
      panel._currentPerson = result ? result.person : null;
    } catch (err) {
      console.error('[Ticker] Failed to load impersonated person:', err);
      panel._currentPerson = null;
    }
  },

  /**
   * Wire up dropdown and banner event handlers. Idempotent: safe to call on
   * every render because we re-query the shadow root each time and the
   * innerHTML replacement clears prior listeners.
   * @param {TickerPanel} panel
   */
  attachEventListeners(panel) {
    if (!panel.shadowRoot) return;
    const dropdown = panel.shadowRoot.querySelector('.view-as-dropdown');
    if (dropdown) {
      dropdown.addEventListener('change', async (e) => {
        await window.Ticker.ViewAsControl.setImpersonatedPerson(panel, e.target.value);
      });
    }
    const stopBtn = panel.shadowRoot.querySelector('.view-as-stop-btn');
    if (stopBtn) {
      stopBtn.addEventListener('click', async () => {
        await window.Ticker.ViewAsControl.stopViewing(panel);
      });
    }
  },
};
