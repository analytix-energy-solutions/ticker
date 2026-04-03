/**
 * Ticker Conditions UI Component
 * Reusable component for editing F-2/F-2b conditions with AND/OR grouping.
 * Supports zone, time, and entity state conditions organized in a
 * condition_tree (recursive group nodes). Legacy flat rules[] arrays
 * are auto-wrapped in a root AND group on set.
 * Brand: See branding/README.md
 */
const _tickerUtils = (window.Ticker && window.Ticker.utils) || {
  esc: s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'),
  escAttr: s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;'),
};
const _emptyTree = () => ({ type: 'group', operator: 'AND', children: [] });

class TickerConditionsUI extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._tree = _emptyTree();
    this._zones = []; this._entities = [];
    this._disabled = false; this._hideZone = false; this._hideQueue = false;
    this._expandedPaths = new Set();
    this._deliverWhenMet = false; this._queueUntilMet = false;
    this._dispatchTimer = null;
  }
  static get observedAttributes() { return ['disabled', 'hide-zone', 'hide-queue']; }
  attributeChangedCallback(name, _o, newValue) {
    const f = newValue !== null;
    if (name === 'disabled') this._disabled = f;
    else if (name === 'hide-zone') this._hideZone = f;
    else if (name === 'hide-queue') this._hideQueue = f;
    this._render();
  }
  set rules(v) {
    this._tree = Array.isArray(v) ? { type:'group', operator:'AND', children: v||[] } : (v || _emptyTree());
    this._render();
  }
  get rules() { return this._flatLeaves(this._tree); }
  set tree(v) { this._tree = v || _emptyTree(); this._render(); }
  get tree() { return this._tree; }
  set zones(v) { this._zones = v || []; this._render(); }
  set entities(v) { this._entities = v || []; this._render(); }
  set deliverWhenMet(v) { this._deliverWhenMet = !!v; this._render(); }
  get deliverWhenMet() { return this._deliverWhenMet; }
  set queueUntilMet(v) { this._queueUntilMet = !!v; this._render(); }
  get queueUntilMet() { return this._queueUntilMet; }
  connectedCallback() { this._render(); }
  _esc(s) { return _tickerUtils.esc(s); }
  _escAttr(s) { return _tickerUtils.escAttr(s); }

  // --- Tree helpers ---
  _flatLeaves(n) {
    if (!n) return [];
    if (n.type === 'group') { const o=[]; for (const c of (n.children||[])) o.push(...this._flatLeaves(c)); return o; }
    return [n];
  }
  _getNode(path) { let n = this._tree; for (const i of path) n = n.children[i]; return n; }
  _clone(n) { return JSON.parse(JSON.stringify(n)); }
  _setNode(path, node) {
    if (!path.length) return node;
    const r = this._clone(this._tree); let p = r;
    for (let i = 0; i < path.length-1; i++) p = p.children[path[i]];
    p.children[path[path.length-1]] = node; return r;
  }
  _removeNode(path) {
    const r = this._clone(this._tree); let p = r;
    for (let i = 0; i < path.length-1; i++) p = p.children[path[i]];
    p.children.splice(path[path.length-1], 1); return r;
  }
  _pathKey(p) { return JSON.stringify(p); }
  _isExpanded(p) { return this._expandedPaths.has(this._pathKey(p)); }
  _toggleExpand(p) { const k=this._pathKey(p); this._expandedPaths.has(k)?this._expandedPaths.delete(k):this._expandedPaths.add(k); this._render(); }

  // --- Mutations ---
  _addRule(type) {
    const r = { type };
    if (type==='zone') r.zone_id = this._zones.length ? this._zones[0].zone_id : 'zone.home';
    else if (type==='time') { r.after='08:00'; r.before='22:00'; r.days=[1,2,3,4,5,6,7]; }
    else if (type==='state') { r.entity_id=''; r.state=''; }
    const t = this._clone(this._tree);
    if (!t.children.length) { this._deliverWhenMet=true; this._queueUntilMet=!this._hideQueue; }
    t.children.push(r);
    this._expandedPaths.add(this._pathKey([t.children.length-1]));
    this._tree=t; this._dispatchTreeChanged(true); this._render();
  }
  _removeNodeAt(path) {
    this._expandedPaths.delete(this._pathKey(path));
    this._tree = this._cleanSingle(this._removeNode(path), true);
    this._dispatchTreeChanged(true); this._render();
  }
  /** Collapse non-root groups with only one child. isRoot prevents root collapse. */
  _cleanSingle(n, isRoot) {
    if (n.type !== 'group') return n;
    n.children = n.children.map(c => this._cleanSingle(c, false));
    if (!isRoot && n.children.length === 1) return n.children[0];
    return n;
  }
  _updateRuleAt(path, field, value) {
    const n=this._clone(this._getNode(path)); n[field]=value;
    this._tree=this._setNode(path,n); this._dispatchTreeChanged();
  }
  _toggleDayAt(path, day) {
    const n=this._clone(this._getNode(path)); const d=[...(n.days||[])];
    const i=d.indexOf(day); if(i>=0)d.splice(i,1); else{d.push(day);d.sort((a,b)=>a-b);}
    n.days=d; this._tree=this._setNode(path,n); this._dispatchTreeChanged(); this._render();
  }
  _toggleOperator(pp) {
    const g=this._clone(this._getNode(pp)); g.operator=g.operator==='AND'?'OR':'AND';
    this._tree=this._setNode(pp,g); this._dispatchTreeChanged(true); this._render();
  }
  _groupAt(pp, ci) {
    const t=this._clone(this._tree); let p=t; for(const i of pp) p=p.children[i];
    const ng={type:'group',operator:p.operator,children:[p.children[ci],p.children[ci+1]]};
    p.children.splice(ci,2,ng); this._tree=t; this._dispatchTreeChanged(true); this._render();
  }
  _ungroupAt(path) {
    if(!path.length) return;
    const t=this._clone(this._tree); let p=t;
    for(let i=0;i<path.length-1;i++) p=p.children[path[i]];
    const idx=path[path.length-1]; const g=p.children[idx];
    p.children.splice(idx,1,...(g.children||[]));
    this._tree=t; this._dispatchTreeChanged(true); this._render();
  }
  _toggleDeliverWhenMet() { this._deliverWhenMet=!this._deliverWhenMet; this._dispatchTreeChanged(true); this._render(); }
  _toggleQueueUntilMet() { this._queueUntilMet=!this._queueUntilMet; this._dispatchTreeChanged(true); this._render(); }

  _dispatchTreeChanged(imm=false) {
    if(this._dispatchTimer){clearTimeout(this._dispatchTimer);this._dispatchTimer=null;}
    const go=()=>{this._dispatchTimer=null;this.dispatchEvent(new CustomEvent('rules-changed',{
      detail:{condition_tree:this._tree,deliver_when_met:this._deliverWhenMet,queue_until_met:this._queueUntilMet},
      bubbles:true,composed:true}));};
    imm?go():this._dispatchTimer=setTimeout(go,400);
  }

  // --- Entity input ---
  _onEntityInput(pathStr, value) {
    const path=JSON.parse(pathStr), oldDom=(this._getNode(path).entity_id||'').split('.')[0];
    this._updateRuleAt(path,'entity_id',value);
    const pid=pathStr.replace(/[\[\],]/g,'_');
    const dl=this.shadowRoot.getElementById(`entity-list-${pid}`);
    if(dl){if(!value||value.length<2){dl.innerHTML='';}else{
      const q=value.toLowerCase(),m=[];
      for(let i=0;i<this._entities.length&&m.length<20;i++){const e=this._entities[i];
        if(e.entity_id.toLowerCase().includes(q)||(e.name&&e.name.toLowerCase().includes(q)))m.push(e);}
      dl.innerHTML=m.map(e=>`<option value="${this._escAttr(e.entity_id)}">${this._esc(e.name||e.entity_id)}</option>`).join('');
    }}
    const newDom=(value||'').split('.')[0];
    if(newDom!==oldDom){const sel=this.shadowRoot.getElementById(`state-select-${pid}`);
      if(sel){const sg=this._stateSugg(value),cur=this._getNode(path).state||'',hc=!cur||sg.includes(cur);
        let h='<option value="">Select state...</option>';
        if(cur&&!hc)h+=`<option value="${this._escAttr(cur)}" selected>${this._esc(cur)}</option>`;
        h+=sg.map(s=>`<option value="${this._escAttr(s)}" ${s===cur?'selected':''}>${this._esc(s)}</option>`).join('');
        sel.innerHTML=h;}}
  }
  _zoneName(id) { const z=this._zones.find(z=>z.zone_id===id); return z?z.name:id.replace('zone.',''); }
  _stateSugg(eid) {
    if(!eid)return['on','off']; const d=eid.split('.')[0];
    const m={'binary_sensor':['on','off'],'switch':['on','off'],'light':['on','off'],'fan':['on','off'],
      'input_boolean':['on','off'],'lock':['locked','unlocked'],'cover':['open','closed','opening','closing'],
      'alarm_control_panel':['armed_away','armed_home','armed_night','disarmed','triggered'],
      'climate':['off','heat','cool','heat_cool','auto','dry','fan_only'],
      'media_player':['off','on','playing','paused','idle','standby'],
      'vacuum':['cleaning','docked','idle','paused','returning'],
      'person':['home','not_home','away'],'device_tracker':['home','not_home','away'],
      'sun':['above_horizon','below_horizon'],'weather':['sunny','cloudy','partlycloudy','rainy','snowy','fog']};
    return m[d]||['on','off'];
  }
  _typeName(t) { return {zone:'Zone',time:'Time',state:'Entity State'}[t]||t; }
  _summary(r) {
    if(r.type==='zone') return `In ${this._zoneName(r.zone_id)}`;
    if(r.type==='time'){const dn=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
      const ds=(r.days||[]).map(d=>dn[d-1]).join(', ');return `${r.after} - ${r.before}${ds?` (${ds})`:''}`;  }
    if(r.type==='state') return r.entity_id?`${r.entity_id} = ${r.state}`:'Not configured';
    return 'Unknown';
  }

  // --- Rendering ---
  _render() {
    const styles=window.Ticker.conditionsStyles||'', leaves=this._flatLeaves(this._tree);
    let content='';
    if(!leaves.length) content='<div class="empty-state">No conditions configured. Add a condition to control when notifications are delivered.</div>';
    else content=`<div class="rules-container">${this._renderChildren(this._tree.children,[])}</div>`;
    const zb=this._hideZone?'':`<button class="add-rule-btn" data-action="add-zone" ${this._disabled?'disabled':''}>+ Zone</button>`;
    const add=`<div class="add-rule-section">${zb}
      <button class="add-rule-btn" data-action="add-time" ${this._disabled?'disabled':''}>+ Time</button>
      <button class="add-rule-btn" data-action="add-state" ${this._disabled?'disabled':''}>+ Entity State</button>
    </div>${this._infoText()}`;
    const acts=leaves.length?this._actionsHtml():'';
    this.shadowRoot.innerHTML=`${styles}${content}${add}${acts}`;
    this._wireEvents();
  }

  _wireEvents() {
    const sr=this.shadowRoot;
    sr.querySelectorAll('.add-rule-btn').forEach(b=>b.addEventListener('click',()=>{
      const a=b.dataset.action;
      if(a==='add-zone')this._addRule('zone');else if(a==='add-time')this._addRule('time');else if(a==='add-state')this._addRule('state');
    }));
    sr.querySelectorAll('.operator-pill:not(.group-op-pill)').forEach(p=>p.addEventListener('click',()=>this._toggleOperator(JSON.parse(p.dataset.parentpath))));
    sr.querySelectorAll('.group-btn').forEach(b=>{if(!b.disabled)b.addEventListener('click',()=>this._groupAt(JSON.parse(b.dataset.parentpath),parseInt(b.dataset.childidx)));});
    sr.querySelectorAll('[data-toggle-path]').forEach(e=>e.addEventListener('click',()=>this._toggleExpand(JSON.parse(e.dataset.togglePath))));
    sr.querySelectorAll('[data-delete-path]').forEach(b=>b.addEventListener('click',ev=>{ev.stopPropagation();this._removeNodeAt(JSON.parse(b.dataset.deletePath));}));
    sr.querySelectorAll('[data-ungroup-path]').forEach(b=>b.addEventListener('click',()=>this._ungroupAt(JSON.parse(b.dataset.ungroupPath))));
    sr.querySelectorAll('.group-op-pill').forEach(p=>p.addEventListener('click',()=>this._toggleOperator(JSON.parse(p.dataset.grouppath))));
    sr.querySelectorAll('[data-action-toggle]').forEach(c=>c.addEventListener('change',()=>{c.dataset.actionToggle==='deliver'?this._toggleDeliverWhenMet():this._toggleQueueUntilMet();}));
    sr.querySelectorAll('[data-zone-path]').forEach(s=>s.addEventListener('change',()=>this._updateRuleAt(JSON.parse(s.dataset.zonePath),'zone_id',s.value)));
    sr.querySelectorAll('[data-time-after-path]').forEach(i=>i.addEventListener('change',()=>this._updateRuleAt(JSON.parse(i.dataset.timeAfterPath),'after',i.value)));
    sr.querySelectorAll('[data-time-before-path]').forEach(i=>i.addEventListener('change',()=>this._updateRuleAt(JSON.parse(i.dataset.timeBeforePath),'before',i.value)));
    sr.querySelectorAll('[data-day-toggle]').forEach(b=>b.addEventListener('click',()=>this._toggleDayAt(JSON.parse(b.dataset.dayPath),parseInt(b.dataset.dayToggle))));
    sr.querySelectorAll('[data-entity-path]').forEach(i=>i.addEventListener('input',()=>this._onEntityInput(i.dataset.entityPath,i.value)));
    sr.querySelectorAll('[data-state-path]').forEach(s=>s.addEventListener('change',()=>this._updateRuleAt(JSON.parse(s.dataset.statePath),'state',s.value)));
  }

  _renderChildren(children, pp) {
    const parent=pp.length===0?this._tree:this._getNode(pp), op=parent.operator||'AND';
    return children.map((c,i)=>{
      const cp=[...pp,i];
      const html=c.type==='group'?this._renderGroup(c,cp):this._renderLeaf(c,cp);
      return html+(i<children.length-1?this._opRow(op,pp,i,pp.length):'');
    }).join('');
  }
  _opRow(op, pp, ci, depth) {
    const s=JSON.stringify(pp), isOr=op==='OR', cg=depth<2&&!this._disabled;
    return `<div class="operator-row"><span class="operator-pill ${isOr?'or':''}" data-parentpath='${s}'>${this._esc(op)}</span>`+
      `<button class="group-btn" data-parentpath='${s}' data-childidx="${ci}" ${cg?'':'disabled'} title="Group these conditions">&#9654;</button></div>`;
  }
  _renderGroup(g, path) {
    const ps=JSON.stringify(path), op=g.operator||'AND', isOr=op==='OR';
    return `<div class="group-card"><div class="group-header"><span class="group-label">Group</span>`+
      `<span class="group-op-pill operator-pill ${isOr?'or':''}" data-grouppath='${ps}'>${this._esc(op)}</span>`+
      `<button class="rule-delete" data-ungroup-path='${ps}' title="Ungroup">&times;</button></div>`+
      `<div class="group-body">${this._renderChildren(g.children||[],path)}</div></div>`;
  }
  _renderLeaf(rule, path) {
    const ps=JSON.stringify(path), isE=this._isExpanded(path);
    const cont=isE?this._leafContent(rule,path):'';
    return `<div class="rule-item ${isE?'expanded':''}"><div class="rule-header" data-toggle-path='${ps}'>`+
      `<div class="rule-header-left"><span class="chevron ${isE?'expanded':''}">&#9654;</span>`+
      `<span class="rule-type-badge">${this._esc(this._typeName(rule.type))}</span>`+
      `<span class="rule-summary">${this._esc(this._summary(rule))}</span></div>`+
      `<button class="rule-delete" data-delete-path='${ps}' ${this._disabled?'disabled':''} title="Remove rule">&times;</button>`+
      `</div>${cont}</div>`;
  }
  _leafContent(rule, path) {
    const da=this._disabled?'disabled':'', ps=JSON.stringify(path);
    if(rule.type==='zone'){const opts=this._zones.map(z=>
      `<option value="${this._escAttr(z.zone_id)}" ${z.zone_id===rule.zone_id?'selected':''}>${this._esc(z.name)}</option>`).join('');
      return `<div class="rule-content"><div class="form-group"><label class="form-label">Zone</label><select class="form-select" data-zone-path='${ps}' ${da}>${opts}</select></div></div>`;}
    if(rule.type==='time'){const dn=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'],days=rule.days||[];
      const db=dn.map((n,i)=>{const d=i+1;return `<button class="day-btn ${days.includes(d)?'selected':''}" data-day-toggle="${d}" data-day-path='${ps}' ${da}>${n}</button>`;}).join('');
      return `<div class="rule-content"><div class="form-group"><label class="form-label">Time Window</label><div class="time-inputs">`+
        `<input type="time" class="time-input" value="${this._escAttr(rule.after||'08:00')}" data-time-after-path='${ps}' ${da}>`+
        `<span class="time-separator">to</span><input type="time" class="time-input" value="${this._escAttr(rule.before||'22:00')}" data-time-before-path='${ps}' ${da}>`+
        `</div></div><div class="form-group"><label class="form-label">Days</label><div class="days-selector">${db}</div></div></div>`;}
    if(rule.type==='state'){const pid=ps.replace(/[\[\],]/g,'_'),sg=this._stateSugg(rule.entity_id),cur=rule.state||'',hc=!cur||sg.includes(cur);
      const co=!hc?`<option value="${this._escAttr(cur)}" selected>${this._esc(cur)}</option>`:'';
      const so=sg.map(s=>`<option value="${this._escAttr(s)}" ${s===cur?'selected':''}>${this._esc(s)}</option>`).join('');
      return `<div class="rule-content"><div class="form-row"><div class="form-group" style="flex:2"><label class="form-label">Entity</label>`+
        `<input type="text" class="form-input" list="entity-list-${pid}" id="entity-input-${pid}" placeholder="Start typing to search..." value="${this._escAttr(rule.entity_id||'')}" data-entity-path='${ps}' ${da}>`+
        `<datalist id="entity-list-${pid}"></datalist></div><div class="form-group" style="flex:1"><label class="form-label">State</label>`+
        `<select class="form-select" id="state-select-${pid}" data-state-path='${ps}' ${da}><option value=""${!cur?' selected':''}>Select state...</option>${co}${so}</select></div></div></div>`;}
    return '';
  }
  _infoText() {
    const l=this._flatLeaves(this._tree);if(l.length<2)return'';
    const hasOr=this._hasOr(this._tree);
    return `<div class="info-text">${hasOr?'Conditions are evaluated per group logic shown above.':'All conditions must be met.'}</div>`;
  }
  _hasOr(n) { if(n.type!=='group')return false; if(n.operator==='OR'&&(n.children||[]).length>1)return true; return(n.children||[]).some(c=>this._hasOr(c)); }
  _actionsHtml() {
    const qt=this._hideQueue?'':`<label class="action-toggle"><input type="checkbox" ${this._queueUntilMet?'checked':''} data-action-toggle="queue" ${this._disabled?'disabled':''}> Queue until all conditions met</label>`;
    return `<div class="ruleset-actions"><label class="action-toggle"><input type="checkbox" ${this._deliverWhenMet?'checked':''} data-action-toggle="deliver" ${this._disabled?'disabled':''}> Deliver when all conditions met</label>${qt}</div>`;
  }
}
customElements.define("ticker-conditions-ui", TickerConditionsUI);
