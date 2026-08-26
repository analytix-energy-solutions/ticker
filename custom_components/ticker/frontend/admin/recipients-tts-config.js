/** TTS engine and chime timing controls for the recipient dialog. */
window.Ticker = window.Ticker || {};

window.Ticker.AdminRecipientTtsConfig = {
  renderEngine(esc, escAttr, ttsOptions, ttsService, ttsEntityId) {
    const options = (ttsOptions.tts_entities || []).map(entity => {
      const selected = entity.entity_id === ttsEntityId ? 'selected' : '';
      return `<option value="${escAttr(entity.entity_id)}" ${selected}>${esc(entity.friendly_name)} (${esc(entity.entity_id)})</option>`;
    }).join('');
    const visible = ttsService.toLowerCase() === 'tts.speak' ? 'block' : 'none';
    return `
      <div class="form-group" id="dlg-tts-entity-group" style="margin-bottom:12px;display:${visible}">
        <label>TTS Engine Entity</label>
        <select class="form-select" id="dlg-tts-entity">
          <option value="">-- Use Home Assistant default --</option>
          ${options}
        </select>
        <span style="font-size:11px;color:var(--text-secondary);margin-top:2px;display:block">Selects the engine used by tts.speak, such as OpenAI TTS.</span>
      </div>`;
  },

  renderTiming(waitTimeout, fallbackGap) {
    return `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">
        <div><label style="display:block;margin-bottom:4px;font-size:13px;color:var(--text-secondary)">Chime wait timeout (seconds)</label><input type="number" id="dlg-chime-wait-timeout" min="0.5" max="60" step="0.5" value="${waitTimeout}" style="width:100%;padding:6px 8px;border-radius:4px;border:1px solid var(--divider);background:var(--bg-card);color:var(--text-primary)"></div>
        <div><label style="display:block;margin-bottom:4px;font-size:13px;color:var(--text-secondary)">Fallback gap (seconds)</label><input type="number" id="dlg-chime-tts-gap" min="0" max="10" step="0.5" value="${fallbackGap}" style="width:100%;padding:6px 8px;border-radius:4px;border:1px solid var(--divider);background:var(--bg-card);color:var(--text-primary)"></div>
      </div>
      <p style="margin:4px 0 0;font-size:11px;color:var(--text-secondary)">Timeout caps a stuck chime state. Fallback gap is used when the player does not expose chime playback state.</p>`;
  },

  onServiceChange(panel) {
    const root = panel.shadowRoot.getElementById('ticker-dialog-container');
    if (!root) return;
    const service = root.querySelector('#dlg-tts-service')?.value || '';
    const group = root.querySelector('#dlg-tts-entity-group');
    if (group) group.style.display = service.toLowerCase() === 'tts.speak' ? 'block' : 'none';
  },

  hasValues(root) {
    return !!root.querySelector('#dlg-tts-entity')?.value;
  },

  clear(root) {
    const engine = root.querySelector('#dlg-tts-entity');
    if (engine) engine.value = '';
    const group = root.querySelector('#dlg-tts-entity-group');
    if (group) group.style.display = 'block';
    const wait = root.querySelector('#dlg-chime-wait-timeout');
    if (wait) wait.value = '10';
    const gap = root.querySelector('#dlg-chime-tts-gap');
    if (gap) gap.value = '3';
  },
};
