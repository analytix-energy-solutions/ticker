/**
 * Ticker Admin Panel - Volume Override slider (F-35.2)
 *
 * Shared render + input handlers for the per-recipient and per-category
 * volume slider. Lives in its own module so the recipient dialog and
 * categories tab stay under the 500-line limit. The render output is
 * pure markup (no HA component dependency); handlers operate on DOM
 * ids built from the supplied ``idPrefix`` ("dlg" for recipient,
 * "cat-${catId}" for category).
 *
 * Brand: see branding/README.md — uses --ticker-500 via accent-color.
 */
window.Ticker = window.Ticker || {};

window.Ticker.AdminVolumeOverride = {
  /**
   * Render the volume-override block. ``volume`` is a float in [0,1]
   * or null/undefined for "default = inherit". ``helperText`` lets the
   * caller customize the description (recipient vs. category).
   */
  render(idPrefix, volume, helperText) {
    const isSet = (typeof volume === 'number' && volume >= 0 && volume <= 1);
    const pct = isSet ? Math.round(volume * 100) : 60;
    const dataCleared = isSet ? 'false' : 'true';
    const valueLabel = isSet ? `${pct}%` : 'Default';
    const valueClass = isSet ? '' : 'is-default';
    const buttonLabel = isSet ? 'Default' : 'Set';
    const ns = 'window.Ticker.AdminVolumeOverride';
    const help = helperText || 'Sets media_player volume for chime + TTS, then restores. Leave Default to inherit current volume.';
    // FIX-005: a11y — describe current state on slider via aria-label + title.
    const sliderLabel = isSet
      ? `Volume override slider, currently ${pct}%`
      : 'Volume override slider, currently default';
    const buttonAria = isSet
      ? 'Clear volume override (reset to default)'
      : 'Set volume override';
    return `
      <div class="ticker-volume-override">
        <span class="ticker-volume-override-label">Volume Override</span>
        <div class="ticker-volume-override-row">
          <input type="range" class="ticker-volume-slider" id="${idPrefix}-volume-override" min="0" max="100" step="5" value="${pct}" data-cleared="${dataCleared}" ${isSet ? '' : 'disabled'} aria-label="${sliderLabel}" title="${sliderLabel}" oninput="${ns}.onInput('${idPrefix}')">
          <span class="ticker-volume-value ${valueClass}" id="${idPrefix}-volume-value">${valueLabel}</span>
          <button type="button" id="${idPrefix}-volume-toggle" class="btn btn-secondary" style="padding:4px 10px;font-size:12px" aria-label="${buttonAria}" onclick="window.Ticker.AdminVolumeOverride.toggleDefault('${idPrefix}')">${buttonLabel}</button>
        </div>
        <span class="ticker-volume-help">${help}</span>
      </div>
    `;
  },

  /** Sync slider value display while user drags. */
  onInput(idPrefix) {
    const root = window.Ticker._adminPanel.shadowRoot;
    const slider = root.getElementById(`${idPrefix}-volume-override`);
    const valEl = root.getElementById(`${idPrefix}-volume-value`);
    const btn = root.getElementById(`${idPrefix}-volume-toggle`);
    if (!slider || !valEl) return;
    if (slider.dataset.cleared === 'true') {
      slider.dataset.cleared = 'false';
      slider.disabled = false;
      valEl.classList.remove('is-default');
      if (btn) {
        btn.textContent = 'Default';
        btn.setAttribute('aria-label', 'Clear volume override (reset to default)');
      }
    }
    valEl.textContent = `${slider.value}%`;
    // FIX-005: keep a11y labels in sync as the user drags.
    const label = `Volume override slider, currently ${slider.value}%`;
    slider.setAttribute('aria-label', label);
    slider.setAttribute('title', label);
  },

  /** Toggle between Default (no override) and Set (use slider). */
  toggleDefault(idPrefix) {
    const root = window.Ticker._adminPanel.shadowRoot;
    const slider = root.getElementById(`${idPrefix}-volume-override`);
    const valEl = root.getElementById(`${idPrefix}-volume-value`);
    const btn = root.getElementById(`${idPrefix}-volume-toggle`);
    if (!slider || !valEl) return;
    const wasCleared = slider.dataset.cleared === 'true';
    if (wasCleared) {
      slider.dataset.cleared = 'false';
      slider.disabled = false;
      valEl.textContent = `${slider.value}%`;
      valEl.classList.remove('is-default');
      if (btn) {
        btn.textContent = 'Default';
        btn.setAttribute('aria-label', 'Clear volume override (reset to default)');
      }
      const label = `Volume override slider, currently ${slider.value}%`;
      slider.setAttribute('aria-label', label);
      slider.setAttribute('title', label);
    } else {
      slider.dataset.cleared = 'true';
      slider.disabled = true;
      valEl.textContent = 'Default';
      valEl.classList.add('is-default');
      if (btn) {
        btn.textContent = 'Set';
        btn.setAttribute('aria-label', 'Set volume override');
      }
      const label = 'Volume override slider, currently default';
      slider.setAttribute('aria-label', label);
      slider.setAttribute('title', label);
    }
  },

  /**
   * Read the slider value as a float in [0,1], or null if the user
   * left it on "Default" (no override). Caller decides whether to
   * include in WS payload (omit on create, send null on edit-clear).
   */
  read(idPrefix) {
    const root = window.Ticker._adminPanel.shadowRoot;
    const slider = root.getElementById(`${idPrefix}-volume-override`);
    if (!slider) return null;
    if (slider.dataset.cleared === 'true') return null;
    const pct = parseInt(slider.value, 10);
    if (isNaN(pct)) return null;
    return Math.max(0, Math.min(1, pct / 100));
  },
};
