/**
 * Ticker Admin Panel
 * Smart notifications for Home Assistant
 * Brand: See branding/README.md
 */

class TickerAdminPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._activeTab = "categories";
    this._categories = [];
    this._users = [];
    this._subscriptions = {};
    this._queue = [];
    this._logs = [];
    this._logStats = {};
    this._expandedUsers = new Set();
    this._editingCategory = null;
    this._addingCategory = false;
    this._migrateFindings = [];
    this._migrateCurrentIndex = 0;
    this._migrateScanning = false;
    this._migrateConverting = false;
    this._migrateDeleting = false;
  }

  /**
   * Escape HTML special characters to prevent XSS attacks.
   * @param {string} str - The string to escape
   * @returns {string} - The escaped string
   */
  _esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#x27;');
  }

  /**
   * Escape a string for use in HTML attribute values.
   * @param {string} str - The string to escape
   * @returns {string} - The escaped string safe for attributes
   */
  _escAttr(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;');
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) { this._initialized = true; this._render(); this._loadData(); }
  }

  async _loadData() {
    await Promise.all([this._loadCategories(), this._loadUsers(), this._loadSubscriptions(), this._loadQueue(), this._loadLogs(), this._loadLogStats()]);
    this._render();
  }

  async _loadCategories() { try { const r = await this._hass.callWS({ type: "ticker/categories" }); this._categories = r.categories || []; } catch (e) { console.error(e); } }
  async _loadUsers() { try { const r = await this._hass.callWS({ type: "ticker/users" }); this._users = r.users || []; } catch (e) { console.error(e); } }
  async _loadSubscriptions() { try { const r = await this._hass.callWS({ type: "ticker/subscriptions" }); this._subscriptions = {}; for (const s of r.subscriptions || []) { if (!this._subscriptions[s.person_id]) this._subscriptions[s.person_id] = {}; this._subscriptions[s.person_id][s.category_id] = s; } } catch (e) { console.error(e); } }
  async _loadQueue() { try { const r = await this._hass.callWS({ type: "ticker/queue" }); this._queue = r.queue || []; } catch (e) { console.error(e); } }
  async _loadLogs() { try { const r = await this._hass.callWS({ type: "ticker/logs", limit: 100 }); this._logs = r.logs || []; } catch (e) { console.error(e); } }
  async _loadLogStats() { try { const r = await this._hass.callWS({ type: "ticker/logs/stats" }); this._logStats = r.stats || {}; } catch (e) { console.error(e); } }

  _isSubscribed(pid, cid) { const s = this._subscriptions[pid]; return s && s[cid] ? s[cid].mode !== "never" : true; }
  _genCatId(n) { return n.toLowerCase().trim().replace(/[àáâãäå]/g,"a").replace(/[èéêë]/g,"e").replace(/[ìíîï]/g,"i").replace(/[òóôõö]/g,"o").replace(/[ùúûü]/g,"u").replace(/[ñ]/g,"n").replace(/[ç]/g,"c").replace(/[^a-z0-9]+/g,"_").replace(/^_+|_+$/g,"").replace(/_+/g,"_"); }

  async _createCategory() {
    const n = this.shadowRoot.getElementById("new-category-name")?.value?.trim();
    const i = this.shadowRoot.getElementById("new-category-icon")?.value?.trim() || "mdi:bell";
    const c = this.shadowRoot.getElementById("new-category-color")?.value || null;
    if (!n) { this._showError("Enter a category name"); return; }
    const id = this._genCatId(n); if (!id) { this._showError("Invalid name"); return; }
    try { await this._hass.callWS({ type: "ticker/category/create", category_id: id, name: n, icon: i, color: c }); this._addingCategory = false; await this._loadCategories(); this._render(); this._showSuccess("Category created"); } catch (e) { this._showError(e.message); }
  }

  _toggleAddCategory() { this._addingCategory = !this._addingCategory; this._editingCategory = null; this._render(); }

  _startEditCategory(id) { this._editingCategory = this._editingCategory === id ? null : id; this._addingCategory = false; this._render(); }
  _cancelEditCategory() { this._editingCategory = null; this._addingCategory = false; this._render(); }

  async _saveCategory(id) {
    const n = this.shadowRoot.getElementById(`edit-name-${id}`)?.value?.trim();
    const i = this.shadowRoot.getElementById(`edit-icon-${id}`)?.value?.trim();
    const c = this.shadowRoot.getElementById(`edit-color-${id}`)?.value || null;
    if (!n) { this._showError("Name required"); return; }
    try { await this._hass.callWS({ type: "ticker/category/update", category_id: id, name: n, icon: i, color: c }); this._editingCategory = null; await this._loadCategories(); this._render(); this._showSuccess("Updated"); } catch (e) { this._showError(e.message); }
  }

  async _deleteCategory(id) { if (!confirm("Delete category?")) return; try { await this._hass.callWS({ type: "ticker/category/delete", category_id: id }); await this._loadCategories(); this._render(); } catch (e) { this._showError(e.message); } }
  async _toggleUserEnabled(pid, cur) { try { await this._hass.callWS({ type: "ticker/user/set_enabled", person_id: pid, enabled: !cur }); if (cur) this._expandedUsers.delete(pid); await this._loadUsers(); this._render(); } catch (e) { this._showError(e.message); } }
  _toggleUserExpanded(pid) { const u = this._users.find(x => x.person_id === pid); if (u && !u.enabled) return; this._expandedUsers.has(pid) ? this._expandedUsers.delete(pid) : this._expandedUsers.add(pid); this._render(); }
  async _toggleSubscription(pid, cid, cur) { try { await this._hass.callWS({ type: "ticker/subscription/set", person_id: pid, category_id: cid, mode: cur ? "never" : "always" }); await this._loadSubscriptions(); this._render(); } catch (e) { this._showError(e.message); } }
  async _sendTestNotification(pid) { try { const r = await this._hass.callWS({ type: "ticker/test_notification", person_id: pid }); const ok = r.results.filter(x => x.success).length; const fail = r.results.filter(x => !x.success).length; if (!fail) this._showSuccess(`Test sent via ${ok} service(s)`); else if (ok) this._showSuccess(`${ok} ok, ${fail} failed`); else this._showError("All failed"); } catch (e) { this._showError(e.message); } }
  async _clearQueueForPerson(pid) { if (!confirm("Clear queue?")) return; try { await this._hass.callWS({ type: "ticker/queue/clear", person_id: pid }); await this._loadQueue(); this._render(); this._showSuccess("Cleared"); } catch (e) { this._showError(e.message); } }
  async _removeQueueEntry(qid) { try { await this._hass.callWS({ type: "ticker/queue/remove", queue_id: qid }); await this._loadQueue(); this._render(); } catch (e) { this._showError(e.message); } }
  async _clearLogs() { if (!confirm("Clear logs?")) return; try { await this._hass.callWS({ type: "ticker/logs/clear" }); await Promise.all([this._loadLogs(), this._loadLogStats()]); this._render(); this._showSuccess("Cleared"); } catch (e) { this._showError(e.message); } }

  async _migrateScan() {
    console.log('[Ticker] Starting migration scan...');
    this._migrateScanning = true; this._migrateFindings = []; this._migrateCurrentIndex = 0; this._render();
    const startTime = Date.now();
    let findings = []; let error = null;
    try {
      console.log('[Ticker] Calling ticker/migrate/scan...');
      const r = await this._hass.callWS({ type: "ticker/migrate/scan" });
      console.log('[Ticker] Scan response:', r);
      findings = r.findings || [];
    } catch (e) {
      console.error('[Ticker] Scan error:', e);
      error = e.message || String(e);
    }
    // Ensure scanning shows for at least 2 seconds
    const elapsed = Date.now() - startTime;
    console.log('[Ticker] Elapsed:', elapsed, 'ms, waiting for 2s minimum');
    if (elapsed < 2000) await new Promise(resolve => setTimeout(resolve, 2000 - elapsed));
    this._migrateScanning = false; this._migrateFindings = findings;
    console.log('[Ticker] Rendering with', findings.length, 'findings');
    this._render();
    // Show message AFTER render so the element exists
    console.log('[Ticker] Showing message, error:', error);
    if (error) { this._showError(error); }
    else if (findings.length === 0) { this._showSuccess("Scan complete - no notification calls found in your automations or scripts."); }
    else { this._showSuccess(`Found ${findings.length} notification call${findings.length === 1 ? '' : 's'} to review.`); }
  }

  _migrateSkip() { if (this._migrateCurrentIndex < this._migrateFindings.length - 1) this._migrateCurrentIndex++; else { this._migrateFindings = []; this._migrateCurrentIndex = 0; this._showSuccess("Done!"); } this._render(); }

  async _migrateConvert(apply) {
    const f = this._migrateFindings[this._migrateCurrentIndex]; if (!f) return;
    const sel = this.shadowRoot.getElementById("migrate-category");
    const newIn = this.shadowRoot.getElementById("migrate-new-category");
    const titleIn = this.shadowRoot.getElementById("migrate-title");
    const messageIn = this.shadowRoot.getElementById("migrate-message");
    let catId = sel?.value, catName = "";
    const title = titleIn?.value || "";
    const message = messageIn?.value || "";
    
    // Warn for YAML-based files
    const isYamlFile = f.source_file && !f.source_file.includes(".storage");
    if (apply && isYamlFile) {
      const fileName = f.source_file.split('/').pop();
      const confirmed = confirm(
        "⚠️ YAML FILE MODIFICATION\n\n" +
        "File: " + f.source_file + "\n\n" +
        "IMPORTANT: This operation uses standard YAML processing which does NOT preserve:\n" +
        "  • Comments (inline and block)\n" +
        "  • Custom formatting and indentation\n" +
        "  • Quote styles\n" +
        "  • Blank lines\n\n" +
        "A backup will be created BEFORE any changes:\n" +
        "  config/ticker_migration_backups/" + fileName + ".[timestamp]\n\n" +
        "If you have important comments in your YAML, consider using 'Copy YAML' instead and applying changes manually.\n\n" +
        "Continue with auto-apply?"
      );
      if (!confirmed) return;
    }
    
    if (catId === "__new__") {
      const nn = newIn?.value?.trim(); if (!nn) { this._showError("Enter category name"); return; }
      catId = this._genCatId(nn); catName = nn;
      try { await this._hass.callWS({ type: "ticker/category/create", category_id: catId, name: nn, icon: "mdi:bell" }); await this._loadCategories(); } catch (e) { this._showError(e.message); return; }
    } else { const c = this._categories.find(x => x.id === catId); catName = c ? c.name : catId; }
    this._migrateConverting = true; this._render();
    try {
      const r = await this._hass.callWS({ type: "ticker/migrate/convert", finding: f, category_id: catId, category_name: catName, apply_directly: apply, title: title, message: message });
      if (r.success) { if (apply && r.applied) this._showSuccess(isYamlFile ? "Applied! Backup created." : "Applied!"); else { navigator.clipboard.writeText(r.yaml).then(() => this._showSuccess("YAML copied!")).catch(() => alert(r.yaml)); } this._migrateSkip(); }
      else this._showError(r.error || "Failed");
    } catch (e) { this._showError(e.message); }
    this._migrateConverting = false; this._render();
  }

  _getDuplicateFinding(f) {
    if (!f || !f.has_duplicate || !f.duplicate_finding_id) return null;
    return this._migrateFindings.find(x => x.finding_id === f.duplicate_finding_id) || null;
  }

  async _migrateDeleteDuplicate() {
    const f = this._migrateFindings[this._migrateCurrentIndex];
    if (!f) return;
    this._migrateDeleting = true; this._render();
    try {
      const r = await this._hass.callWS({ type: "ticker/migrate/delete", finding: f });
      if (r.success && r.deleted) {
        this._showSuccess("Duplicate deleted");
        // Remove this finding and its duplicate pair from the list
        const dupId = f.duplicate_finding_id;
        this._migrateFindings = this._migrateFindings.filter(x => x.finding_id !== f.finding_id);
        // Also clear the duplicate flag from the paired finding since it's no longer a duplicate
        const pairedFinding = this._migrateFindings.find(x => x.finding_id === dupId);
        if (pairedFinding) {
          pairedFinding.has_duplicate = false;
          pairedFinding.duplicate_finding_id = null;
          pairedFinding.is_first_in_duplicate_pair = false;
        }
        // Adjust current index if needed
        if (this._migrateCurrentIndex >= this._migrateFindings.length) {
          this._migrateCurrentIndex = Math.max(0, this._migrateFindings.length - 1);
        }
        if (this._migrateFindings.length === 0) {
          this._migrateCurrentIndex = 0;
          this._showSuccess("Done!");
        }
      } else {
        this._showError(r.error || "Failed to delete");
      }
    } catch (e) {
      this._showError(e.message);
    }
    this._migrateDeleting = false; this._render();
  }

  _fmtTime(iso) { return new Date(iso).toLocaleString(); }
  _showError(m) { const e = this.shadowRoot.getElementById("msg"); if (e) { e.textContent = m; e.className = "msg err"; e.style.display = "block"; setTimeout(() => e.style.display = "none", 10000); } }
  _showSuccess(m) { const e = this.shadowRoot.getElementById("msg"); if (e) { e.textContent = m; e.className = "msg ok"; e.style.display = "block"; setTimeout(() => e.style.display = "none", 3000); } }
  _switchTab(t) { this._activeTab = t; this._render(); }

  _render() {
    const css = `<style>:host{--t5:#06b6d4;--t4:#22d3ee;--t7:#0e7490;--tp:var(--primary-text-color,#212121);--ts:var(--secondary-text-color,#727272);--bc:var(--card-background-color,#fff);--bp:var(--primary-background-color,#fafafa);--dv:var(--divider-color,#e0e0e0)}.c{font-family:system-ui,-apple-system,sans-serif;padding:16px;max-width:1200px;margin:0 auto}.hd{display:flex;align-items:center;gap:16px;margin-bottom:24px}.hd h1{margin:0;font-size:24px;font-weight:600;color:var(--tp)}.hd svg{width:40px;height:40px}.tabs{display:flex;border-bottom:1px solid var(--dv);margin-bottom:24px;flex-wrap:wrap}.tab{padding:12px 24px;border:none;background:none;cursor:pointer;font-size:14px;font-weight:500;color:var(--ts);border-bottom:2px solid transparent}.tab:hover{color:var(--t5)}.tab.a{color:var(--t5);border-bottom-color:var(--t5)}.tb{background:var(--t5);color:#fff;padding:2px 6px;border-radius:10px;font-size:11px;margin-left:4px}.card{background:var(--bc);border-radius:8px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:16px}.ct{font-size:16px;font-weight:600;margin:0 0 16px;color:var(--tp)}.ch{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}.ch .ct{margin:0}.fr{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap}.fg{display:flex;flex-direction:column;gap:4px}.fg label{font-size:12px;font-weight:500;color:var(--ts)}.fg input,.fg select{padding:8px 12px;border:1px solid var(--dv);border-radius:4px;font-size:14px;background:var(--bc);color:var(--tp)}.fg input:focus,.fg select:focus{outline:none;border-color:var(--t5)}.fg input[type=color]{padding:2px;height:36px;width:60px;cursor:pointer}.btn{padding:8px 16px;border:none;border-radius:4px;font-size:14px;font-weight:500;cursor:pointer}.bp{background:var(--t5);color:#fff}.bp:hover{background:var(--t7)}.bs{background:var(--bp);color:var(--tp);border:1px solid var(--dv)}.bs:hover{background:var(--dv)}.bd{background:#ef4444;color:#fff}.bd:hover{background:#dc2626}.bsm{padding:4px 8px;font-size:12px}.btn:disabled{opacity:.5;cursor:not-allowed}.list{display:flex;flex-direction:column;gap:8px}.li{background:var(--bp);border-radius:4px;overflow:hidden}.li.dis{opacity:.6}.lih{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;cursor:pointer}.lih:hover{background:rgba(6,182,212,.05)}.lic{display:flex;flex-direction:column;gap:2px;flex:1}.lit{font-weight:500;color:var(--tp);display:flex;align-items:center;gap:8px}.lia{display:flex;align-items:center;gap:8px}.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:500;background:var(--t5);color:#fff}.bg-s{background:#22c55e}.bg-w{background:#f59e0b}.bg-d{background:#ef4444}.bg-g{background:#9ca3af}.bg-o{background:transparent;border:1px solid var(--t5);color:var(--t5)}.empty{text-align:center;padding:40px;color:var(--ts)}.msg{display:none;padding:12px 16px;border-radius:4px;margin-bottom:16px}.err{background:#fef2f2;border:1px solid #fecaca;color:#dc2626}.ok{background:#f0fdf4;border:1px solid #bbf7d0;color:#16a34a}.ns{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}.nst{padding:2px 6px;background:rgba(6,182,212,.1);border-radius:3px;font-size:11px;color:var(--t7)}.tog{position:relative;width:44px;height:24px;cursor:pointer;flex-shrink:0}.tog input{opacity:0;width:0;height:0}.tsl{position:absolute;inset:0;background:#ccc;border-radius:24px;transition:.3s}.tsl:before{position:absolute;content:"";height:18px;width:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s}.tog input:checked+.tsl{background:var(--t5)}.tog input:checked+.tsl:before{transform:translateX(20px)}.exp{width:20px;height:20px;color:var(--ts);transition:transform .2s;flex-shrink:0}.exp.open{transform:rotate(180deg)}.acc{padding:0 16px 16px;border-top:1px solid var(--dv);background:var(--bc)}.subs{display:flex;flex-direction:column;gap:8px;margin-top:12px}.subr{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;background:var(--bp);border-radius:4px}.subl{font-size:14px;color:var(--tp)}.subh{font-size:13px;font-weight:500;color:var(--ts);margin-top:12px;margin-bottom:4px}.cc{width:12px;height:12px;border-radius:50%;display:inline-block;margin-right:6px}.ef{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:12px 16px;background:var(--bc)}.ef input{padding:6px 10px;font-size:13px}.ef input[type=text]{min-width:120px}.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(100px,1fr));gap:12px;margin-bottom:16px}.sc{background:var(--bp);border-radius:6px;padding:12px;text-align:center}.sv{font-size:24px;font-weight:600;color:var(--t5)}.sl{font-size:12px;color:var(--ts);margin-top:2px}.sc.sent .sv{color:#22c55e}.sc.queued .sv{color:#3b82f6}.sc.skipped .sv{color:#f59e0b}.sc.failed .sv{color:#ef4444}.mf{background:var(--bp);border-radius:8px;padding:16px;margin-bottom:16px}.mfh{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px}.mfs{font-weight:600;color:var(--tp)}.mft{font-size:12px;color:var(--ts)}.mfd{background:var(--bc);border-radius:4px;padding:12px;margin-bottom:12px}.mdr{display:flex;margin-bottom:6px;font-size:13px}.mdl{color:var(--ts);width:100px;flex-shrink:0}.mdv{color:var(--tp);word-break:break-word}.ma{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.mp{font-size:13px;color:var(--ts);margin-bottom:12px}.spin{display:inline-block;width:16px;height:16px;border:2px solid var(--dv);border-top-color:var(--t5);border-radius:50%;animation:sp 1s linear infinite;margin-right:8px}@keyframes sp{to{transform:rotate(360deg)}}</style>`;
    const hdr = `<div class="hd"><svg viewBox="0 0 100 100" fill="none"><circle cx="50" cy="50" r="12" fill="#06b6d4"/><circle cx="50" cy="50" r="25" stroke="#06b6d4" stroke-width="4" fill="none"/><circle cx="50" cy="50" r="40" stroke="#06b6d4" stroke-width="3" fill="none" opacity=".6"/></svg><h1>Ticker Admin</h1></div>`;
    const qc = this._queue.length, lc = this._logs.length;
    const tabs = `<div class="tabs"><button class="tab ${this._activeTab==='categories'?'a':''}" onclick="this.getRootNode().host._switchTab('categories')">Categories</button><button class="tab ${this._activeTab==='users'?'a':''}" onclick="this.getRootNode().host._switchTab('users')">Users</button><button class="tab ${this._activeTab==='queue'?'a':''}" onclick="this.getRootNode().host._switchTab('queue')">Queue${qc?`<span class="tb">${qc}</span>`:''}</button><button class="tab ${this._activeTab==='logs'?'a':''}" onclick="this.getRootNode().host._switchTab('logs')">Logs${lc?`<span class="tb">${lc}</span>`:''}</button><button class="tab ${this._activeTab==='migrate'?'a':''}" onclick="this.getRootNode().host._switchTab('migrate')">Migrate</button></div>`;
    let ct = "";
    if (this._activeTab === "categories") ct = this._rCat();
    else if (this._activeTab === "users") ct = this._rUsr();
    else if (this._activeTab === "queue") ct = this._rQ();
    else if (this._activeTab === "logs") ct = this._rLog();
    else if (this._activeTab === "migrate") ct = this._rMig();
    this.shadowRoot.innerHTML = `${css}<div class="c">${hdr}${tabs}<div id="msg" class="msg"></div>${ct}</div>`;
  }

  _rCat() {
    const s = [...this._categories].sort((a,b) => a.is_default ? -1 : b.is_default ? 1 : (a.name||a.id).localeCompare(b.name||b.id));
    const l = s.map(c => this._rCatItem(c)).join("");
    return `<div class="card"><h2 class="ct">Categories</h2><p style="color:var(--ts);font-size:14px;margin-bottom:16px">Click category to edit settings.</p><div class="list">${l}${this._rNewCatItem()}</div></div>`;
  }

  _rNewCatItem() {
    const exp = this._addingCategory;
    const ei = `<svg class="exp ${exp?'open':''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6,9 12,15 18,9"></polyline></svg>`;
    const hdr = `<div class="lih" onclick="this.getRootNode().host._toggleAddCategory()" style="border-left:3px solid ${exp?'var(--t5)':'transparent'};background:${exp?'rgba(6,182,212,0.08)':'transparent'}"><div class="lic"><span class="lit"><ha-icon icon="mdi:plus-circle-outline" style="--mdc-icon-size:18px;color:var(--t5)"></ha-icon><span style="color:var(--t5)">Add new category</span></span></div><div class="lia">${ei}</div></div>`;
    if (!exp) return `<div class="li">${hdr}</div>`;
    const acc = `<div class="acc"><div class="fr" style="padding-top:12px"><div class="fg"><label>Name</label><input type="text" id="new-category-name" placeholder="e.g. Security" style="min-width:180px"></div><div class="fg"><label>Icon</label><input type="text" id="new-category-icon" placeholder="mdi:bell" style="width:100px"></div><div class="fg"><label>Color</label><input type="color" id="new-category-color" value="#06b6d4"></div></div><div style="display:flex;gap:8px;margin-top:16px"><button class="btn bp" onclick="this.getRootNode().host._createCategory()">Create Category</button><button class="btn bs" onclick="this.getRootNode().host._cancelEditCategory()">Cancel</button></div></div>`;
    return `<div class="li">${hdr}${acc}</div>`;
  }

  _rCatItem(c) {
    const escId = this._escAttr(c.id);
    const escName = this._esc(c.name || c.id);
    const escIcon = this._escAttr(c.icon || 'mdi:bell');
    const escColor = this._escAttr(c.color || '#06b6d4');
    const exp = this._editingCategory === c.id;
    const ei = `<svg class="exp ${exp?'open':''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6,9 12,15 18,9"></polyline></svg>`;
    
    // Calculate subscriber count
    const subCount = this._users.filter(u => this._isSubscribed(u.person_id, c.id)).length;
    const subText = `${subCount} subscriber${subCount !== 1 ? 's' : ''}`;
    
    const cd = c.color ? `<span class="cc" style="background:${escColor}"></span>` : '';
    const hdr = `<div class="lih" onclick="this.getRootNode().host._startEditCategory('${escId}')" style="border-left:3px solid ${exp?'var(--t5)':'transparent'};background:${exp?'rgba(6,182,212,0.08)':'transparent'}"><div class="lic"><span class="lit">${cd}<ha-icon icon="${escIcon}" style="--mdc-icon-size:18px"></ha-icon>${escName}${c.is_default?'<span class="badge bg-o">Default</span>':''}</span><span style="font-size:12px;color:var(--ts);margin-top:2px">${subText}</span></div><div class="lia">${ei}</div></div>`;
    
    if (!exp) return `<div class="li">${hdr}</div>`;
    
    const acc = `<div class="acc"><div class="fr" style="padding-top:12px"><div class="fg"><label>Name</label><input type="text" id="edit-name-${escId}" value="${this._escAttr(c.name || '')}" style="min-width:180px"></div><div class="fg"><label>Icon</label><input type="text" id="edit-icon-${escId}" value="${escIcon}" style="width:100px"></div><div class="fg"><label>Color</label><input type="color" id="edit-color-${escId}" value="${escColor}"></div></div><div style="display:flex;gap:8px;margin-top:16px"><button class="btn bp" onclick="this.getRootNode().host._saveCategory('${escId}')">Save</button><button class="btn bs" onclick="this.getRootNode().host._cancelEditCategory()">Cancel</button>${!c.is_default?`<button class="btn bd" onclick="this.getRootNode().host._deleteCategory('${escId}')">Delete</button>`:''}</div></div>`;
    return `<div class="li">${hdr}${acc}</div>`;
  }

  _rUsr() {
    const l = this._users.length ? `<div class="list">${this._users.map(u => this._rUsrItem(u)).join("")}</div>` : `<div class="empty">No users.</div>`;
    return `<div class="card"><h2 class="ct">Users & Subscriptions</h2><p style="color:var(--ts);font-size:14px;margin-bottom:16px">Click user to manage subscriptions.</p>${l}</div>`;
  }

  _rUsrItem(u) {
    const escPid = this._escAttr(u.person_id);
    const escName = this._esc(u.name);
    const exp = u.enabled && this._expandedUsers.has(u.person_id);
    const canExpand = u.enabled;
    const ei = canExpand ? `<svg class="exp ${exp?'open':''}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6,9 12,15 18,9"></polyline></svg>` : '';
    const nt = u.notify_services.length ? `<div class="ns">${u.notify_services.map(s=>`<span class="nst">${this._esc(s)}</span>`).join("")}</div>` : `<span class="badge bg-w">No services</span>`;
    const acc = exp ? this._rUsrSubs(u) : '';
    const hdrStyle = canExpand ? '' : 'cursor:default';
    return `<div class="li ${u.enabled?'':'dis'}"><div class="lih" onclick="this.getRootNode().host._toggleUserExpanded('${escPid}')" style="${hdrStyle}"><div class="lic"><span class="lit">${escName}${!u.enabled?'<span class="badge bg-g">Disabled</span>':''}</span>${nt}</div><div class="lia"><button class="btn bs bsm" onclick="event.stopPropagation();this.getRootNode().host._sendTestNotification('${escPid}')" ${!u.enabled?'disabled':''}>Test</button><label class="tog" onclick="event.stopPropagation()"><input type="checkbox" ${u.enabled?'checked':''} onchange="this.getRootNode().host._toggleUserEnabled('${escPid}',${u.enabled})"><span class="tsl"></span></label>${ei}</div></div>${acc}</div>`;
  }

  _rUsrSubs(u) {
    const escPid = this._escAttr(u.person_id);
    const s = [...this._categories].sort((a,b) => a.is_default ? -1 : b.is_default ? 1 : (a.name||a.id).localeCompare(b.name||b.id));
    if (!s.length) return `<div class="acc"><p style="color:var(--ts);font-size:14px;margin:12px 0 0">No categories.</p></div>`;
    const rows = s.map(c => {
      const escCid = this._escAttr(c.id);
      const escCname = this._esc(c.name || c.id);
      const escColor = this._escAttr(c.color || '');
      const sub = this._isSubscribed(u.person_id, c.id);
      const cd = c.color ? `<span class="cc" style="background:${escColor}"></span>` : '';
      return `<div class="subr"><span class="subl">${cd}${escCname}</span><label class="tog"><input type="checkbox" ${sub?'checked':''} onchange="this.getRootNode().host._toggleSubscription('${escPid}','${escCid}',${sub})"><span class="tsl"></span></label></div>`;
    }).join("");
    return `<div class="acc"><div class="subh">Include in notifications</div><div class="subs">${rows}</div></div>`;
  }

  _rQ() {
    if (!this._queue.length) return `<div class="card"><div class="empty">No queued notifications.</div></div>`;
    const pn = pid => { const u = this._users.find(x => x.person_id === pid); return u ? u.name : pid; };
    const cn = cid => { const c = this._categories.find(x => x.id === cid); return c ? c.name : cid; };
    const bp = {}; for (const e of this._queue) { if (!bp[e.person_id]) bp[e.person_id] = []; bp[e.person_id].push(e); }
    const sec = Object.entries(bp).map(([pid, es]) => {
      const escPid = this._escAttr(pid);
      const escPname = this._esc(pn(pid));
      const rows = es.map(e => {
        const escQid = this._escAttr(e.queue_id);
        const escTitle = this._esc(e.title);
        const escMessage = this._esc(e.message);
        const escCname = this._esc(cn(e.category_id));
        return `<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:10px 12px;background:var(--bp);border-radius:4px;margin-bottom:8px"><div style="flex:1"><div style="font-weight:500;color:var(--tp)">${escTitle}</div><div style="font-size:13px;color:var(--ts);margin:4px 0">${escMessage}</div><div style="font-size:11px;color:var(--ts)">Cat: ${escCname} · Q: ${this._fmtTime(e.created_at)} · Exp: ${this._fmtTime(e.expires_at)}</div></div><button class="btn bd bsm" onclick="this.getRootNode().host._removeQueueEntry('${escQid}')">×</button></div>`;
      }).join("");
      return `<div class="card"><div class="ch"><h2 class="ct">${escPname} <span class="badge">${es.length}</span></h2><button class="btn bd bsm" onclick="this.getRootNode().host._clearQueueForPerson('${escPid}')">Clear</button></div>${rows}</div>`;
    }).join("");
    return `<div class="card"><h2 class="ct">Queue</h2><p style="color:var(--ts);font-size:14px;margin-bottom:0">Waiting for arrival.</p></div>${sec}`;
  }

  _rLog() {
    const st = this._logStats, bo = st.by_outcome || {};
    const sg = `<div class="sg"><div class="sc"><div class="sv">${st.total||0}</div><div class="sl">Total</div></div><div class="sc sent"><div class="sv">${bo.sent||0}</div><div class="sl">Sent</div></div><div class="sc queued"><div class="sv">${bo.queued||0}</div><div class="sl">Queued</div></div><div class="sc skipped"><div class="sv">${bo.skipped||0}</div><div class="sl">Skipped</div></div><div class="sc failed"><div class="sv">${bo.failed||0}</div><div class="sl">Failed</div></div></div>`;
    if (!this._logs.length) return `<div class="card"><div class="ch"><h2 class="ct">Logs</h2></div>${sg}<div class="empty">No logs.</div></div>`;
    const pn = pid => { const u = this._users.find(x => x.person_id === pid); return u ? u.name : pid; };
    const cn = cid => { const c = this._categories.find(x => x.id === cid); return c ? c.name : cid; };
    const gb = o => { if (o==='sent') return '<span class="badge bg-s">Sent</span>'; if (o==='queued') return '<span class="badge">Queued</span>'; if (o==='skipped') return '<span class="badge bg-w">Skipped</span>'; if (o==='failed') return '<span class="badge bg-d">Failed</span>'; return `<span class="badge">${this._esc(o)}</span>`; };
    const rows = this._logs.map(l => {
      const escTitle = this._esc(l.title);
      const escMessage = this._esc(l.message);
      const escPname = this._esc(pn(l.person_id));
      const escCname = this._esc(cn(l.category_id));
      const escService = l.notify_service ? this._esc(l.notify_service) : '';
      const escReason = l.reason ? this._esc(l.reason) : '';
      return `<div style="padding:10px 14px;background:var(--bp);border-radius:4px;margin-bottom:6px"><div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px"><div style="flex:1"><div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">${gb(l.outcome)}<span style="font-weight:500;color:var(--tp)">${escTitle}</span></div><div style="font-size:13px;color:var(--ts);margin-bottom:4px">${escMessage}</div><div style="font-size:11px;color:var(--ts);display:flex;flex-wrap:wrap;gap:8px"><span>To: ${escPname}</span><span>·</span><span>Cat: ${escCname}</span>${escService?`<span>·</span><span>Via: ${escService}</span>`:''}${escReason?`<span>·</span><span style="font-style:italic">${escReason}</span>`:''}</div></div><div style="font-size:11px;color:var(--ts);white-space:nowrap">${this._fmtTime(l.timestamp)}</div></div></div>`;
    }).join("");
    return `<div class="card"><div class="ch"><h2 class="ct">Logs</h2><button class="btn bd bsm" onclick="this.getRootNode().host._clearLogs()">Clear</button></div><p style="color:var(--ts);font-size:14px;margin-bottom:16px">7 days, max 500.</p>${sg}${rows}</div>`;
  }

  _rMig() {
    if (!this._migrateFindings.length && !this._migrateScanning) return `<div class="card"><h2 class="ct">Migration Wizard</h2><p style="color:var(--ts);font-size:14px;margin-bottom:16px">Scan automations and scripts for notification calls and convert them to Ticker.</p><p style="color:var(--ts);font-size:13px;margin-bottom:16px"><b>Scans:</b> Automations, Scripts<br><b>Services:</b> notify.*, persistent_notification.*</p><button class="btn bp" onclick="this.getRootNode().host._migrateScan()"><ha-icon icon="mdi:magnify" style="--mdc-icon-size:18px;margin-right:6px"></ha-icon>Scan</button></div>`;
    if (this._migrateScanning) return `<div class="card"><h2 class="ct">Migration Wizard</h2><div style="text-align:center;padding:40px"><span class="spin"></span><span style="color:var(--ts)">Scanning...</span></div></div>`;
    if (!this._migrateFindings.length) return `<div class="card"><h2 class="ct">Migration Wizard</h2><div class="empty"><p>No notifications found.</p><button class="btn bs" onclick="this.getRootNode().host._migrateScan()" style="margin-top:16px">Scan Again</button></div></div>`;
    const f = this._migrateFindings[this._migrateCurrentIndex];
    const dup = this._getDuplicateFinding(f);
    const sd = f.service_data || {};
    const escSourceName = this._esc(f.source_name);
    const escSourceType = this._esc(f.source_type);
    const escSourceFile = this._esc(f.source_file || 'unknown');
    const escService = this._esc(f.service);
    const escTitle = this._escAttr(sd.title || '');
    const escMessage = this._escAttr(sd.message || '');
    const sortedCats = [...this._categories].sort((a,b) => a.is_default ? -1 : b.is_default ? 1 : (a.name||a.id).localeCompare(b.name||b.id));
    const catOpts = sortedCats.map(c => `<option value="${this._escAttr(c.id)}">${this._esc(c.name)}</option>`).join("") + `<option value="__new__">+ New category...</option>`;
    const prog = `<div class="mp">${this._migrateCurrentIndex + 1} of ${this._migrateFindings.length}</div>`;
    const extraData = Object.entries(sd).filter(([k]) => k !== 'title' && k !== 'message');
    const extraDataHtml = extraData.length ? `<div class="mdr"><div class="mdl">Extra data</div><div class="mdv" style="font-size:12px;color:var(--ts);font-family:monospace;white-space:pre-wrap">${extraData.map(([k,v]) => `${this._esc(k)}: ${this._esc(typeof v === 'object' ? JSON.stringify(v) : v)}`).join('\n')}</div></div>` : '';
    const isProcessing = this._migrateConverting || this._migrateDeleting;
    
    // If this finding has a duplicate, show side-by-side view
    if (dup) {
      const dupSd = dup.service_data || {};
      const escDupService = this._esc(dup.service);
      const escDupTarget = this._esc(JSON.stringify(dup.target || {}));
      const escTarget = this._esc(JSON.stringify(f.target || {}));
      const escDupTitle = this._esc(dupSd.title || '(none)');
      const escDupMessage = this._esc(dupSd.message || '(none)');
      const escCurTitle = this._esc(sd.title || '(none)');
      const escCurMessage = this._esc(sd.message || '(none)');
      
      return `<div class="card"><h2 class="ct">Migration Wizard</h2>${prog}
        <div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:6px;padding:12px 16px;margin-bottom:16px;display:flex;align-items:center;gap:10px">
          <ha-icon icon="mdi:content-duplicate" style="--mdc-icon-size:20px;color:#d97706"></ha-icon>
          <div style="flex:1">
            <div style="font-weight:600;color:#92400e">Duplicate Detected</div>
            <div style="font-size:13px;color:#a16207">This notification is identical to an adjacent one. You can delete this duplicate or keep both.</div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px">
          <div class="mf" style="margin-bottom:0;border:2px solid var(--t5)">
            <div style="font-size:11px;font-weight:600;color:var(--t5);margin-bottom:8px;text-transform:uppercase">Current (This One)</div>
            <div class="mfh" style="margin-bottom:8px"><div><div class="mfs">${escSourceName}</div><div class="mft">Index: ${this._esc(f.action_path)}</div></div><span class="badge">${escService}</span></div>
            <div class="mfd" style="margin-bottom:0">
              <div class="mdr"><div class="mdl">Title</div><div class="mdv">${escCurTitle}</div></div>
              <div class="mdr"><div class="mdl">Message</div><div class="mdv">${escCurMessage}</div></div>
              <div class="mdr"><div class="mdl">Target</div><div class="mdv" style="font-size:11px;font-family:monospace">${escTarget}</div></div>
            </div>
          </div>
          <div class="mf" style="margin-bottom:0;opacity:0.7">
            <div style="font-size:11px;font-weight:600;color:var(--ts);margin-bottom:8px;text-transform:uppercase">Adjacent Duplicate</div>
            <div class="mfh" style="margin-bottom:8px"><div><div class="mfs">${this._esc(dup.source_name)}</div><div class="mft">Index: ${this._esc(dup.action_path)}</div></div><span class="badge">${escDupService}</span></div>
            <div class="mfd" style="margin-bottom:0">
              <div class="mdr"><div class="mdl">Title</div><div class="mdv">${escDupTitle}</div></div>
              <div class="mdr"><div class="mdl">Message</div><div class="mdv">${escDupMessage}</div></div>
              <div class="mdr"><div class="mdl">Target</div><div class="mdv" style="font-size:11px;font-family:monospace">${escDupTarget}</div></div>
            </div>
          </div>
        </div>
        <div class="ma">${isProcessing ? '<span class="spin"></span>' : ''}<button class="btn bd" onclick="this.getRootNode().host._migrateDeleteDuplicate()" ${isProcessing?'disabled':''}>Delete This Duplicate</button><button class="btn bs" onclick="this.getRootNode().host._migrateSkip()" ${isProcessing?'disabled':''}>Keep Both</button></div>
      </div>`;
    }
    
    // Normal view (no duplicate)
    return `<div class="card"><h2 class="ct">Migration Wizard</h2>${prog}<div class="mf"><div class="mfh"><div><div class="mfs">${escSourceName}</div><div class="mft">${escSourceType} · from ${escSourceFile}</div></div><span class="badge">${escService}</span></div><div class="mfd"><div class="mdr"><div class="mdl">Title</div><div class="mdv"><input type="text" id="migrate-title" value="${escTitle}" style="width:100%;padding:6px 10px;border:1px solid var(--dv);border-radius:4px;font-size:13px;background:var(--bc);color:var(--tp)"></div></div><div class="mdr"><div class="mdl">Message</div><div class="mdv"><input type="text" id="migrate-message" value="${escMessage}" style="width:100%;padding:6px 10px;border:1px solid var(--dv);border-radius:4px;font-size:13px;background:var(--bc);color:var(--tp)"></div></div>${extraDataHtml}</div><div class="fr" style="margin-bottom:12px"><div class="fg"><label>Category</label><select id="migrate-category" style="min-width:180px" onchange="const n=this.getRootNode().getElementById('migrate-new-cat-row');n.style.display=this.value==='__new__'?'flex':'none'">${catOpts}</select></div><div class="fg" id="migrate-new-cat-row" style="display:none"><label>New name</label><input type="text" id="migrate-new-category" placeholder="Category name"></div></div><div class="ma">${this._migrateConverting ? '<span class="spin"></span>' : ''}<button class="btn bp" onclick="this.getRootNode().host._migrateConvert(true)" ${this._migrateConverting?'disabled':''}>Apply Directly</button><button class="btn bs" onclick="this.getRootNode().host._migrateConvert(false)" ${this._migrateConverting?'disabled':''}>Copy YAML</button><button class="btn bs" onclick="this.getRootNode().host._migrateSkip()" ${this._migrateConverting?'disabled':''}>Skip</button></div></div></div>`;
  }
}

customElements.define("ticker-admin-panel", TickerAdminPanel);
