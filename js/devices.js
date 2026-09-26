/* Break Area Management System – several PCs working together.
   - the small sync light in the top bar (every user)
   - Devices & Sync page (administrators only; the server checks every request)
   - first start of a new PC: create the administrator OR join an existing administrator PC
   - a data folder copied from another PC: decide what it is
   Loaded after js/app.js and uses its helpers (api, modal, toast, esc, ic, badge, ...). */
'use strict';

Object.assign(IC, {
  sync: '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
  plug: '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
  merge: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="12" r="3"/><path d="M6 9v6M9 6h3a3 3 0 0 1 3 3v0M9 18h3a3 3 0 0 0 3-3v0"/>'
});

/* ============================== sync light in the top bar ============================== */
let SYNC = null;
const SYNC_TEXT = {
  ok: ['All PCs up to date', 'Everything is shared with the other PCs.'],
  pending: ['Sharing changes…', 'Your work is saved on this PC and is being copied to the other PCs.'],
  offline: ['Working on this PC', 'The other PCs are switched off or out of reach. Everything you do is saved safely here and shared automatically when they are back.'],
  problem: ['Needs attention', 'Sharing data with another PC has a problem. Your work on this PC is saved. The administrator can see details in Devices & Sync.']
};
function syncIndicator(s) {
  SYNC = s || null;
  const el = $('#syncInd');
  if (!el) return;
  if (!s || s.state === 'single') { el.classList.add('hidden'); return; }
  const [label, tip] = SYNC_TEXT[s.state] || SYNC_TEXT.pending;
  el.className = 'sync-ind s-' + s.state;
  el.innerHTML = `<i class="dot"></i><span>${esc(label)}</span>`;
  el.title = tip + (s.files_missing ? ` ${s.files_missing} photo(s)/document(s) are still being copied.` : '');
  if (can('users.manage')) el.setAttribute('href', '#/devices'); else el.removeAttribute('href');
  const nav = $('#navSync');
  if (nav) nav.outerHTML = devicesNavBadge();
}
async function refreshSync() {
  try { syncIndicator((await api('GET', '/api/version')).sync); } catch (e) { /* next time */ }
}
function devicesNavBadge() {
  if (!SYNC || SYNC.state === 'single' || SYNC.state === 'ok') return '<span id="navSync"></span>';
  return `<span id="navSync" class="nav-dot s-${SYNC.state}" title="${esc((SYNC_TEXT[SYNC.state] || [''])[0])}"></span>`;
}

/* ============================== Devices & Sync page ============================== */
let DEV = null;
const DTAB = { tab: 'devices' };
const PEER_STATE = {
  online: ['Online', 'b-green'], syncing: ['Sharing…', 'b-blue'], offline: ['Switched off / not reachable', 'b-gray'],
  error: ['Problem', 'b-red'], unknown: ['Not contacted yet', 'b-gray']
};
const agoTs = ts => ts ? ago(ts) : 'never';

EXTRA_VIEWS.devices = () => {
  const tabs = [['devices', 'PCs'], ['conflicts', 'Conflicts'], ['problems', 'Problems & Alerts'], ['history', 'Sync History']];
  return `<div class="page-head"><h2>Devices &amp; Sync</h2><span class="muted" id="devSub"></span>
    <div class="actions">
      <button class="btn" data-act="devSyncNow" title="Contact all PCs now">${ic('sync')}Share Now</button>
      <button class="btn" data-act="devVerify" title="Recalculate the fingerprints of the complete history">${ic('shield')}Check History</button>
      <span id="devAdd"></span>
    </div></div>
  <div class="card mb"><div class="tabs">${tabs.map(([k, l]) => `<button data-act="devTab" data-tab="${k}" class="${DTAB.tab === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
  <div data-async="devices"><p class="muted">Loading…</p></div>`;
};

ASYNC.devices = async el => {
  DEV = await api('GET', '/api/devices');
  $('#devAdd').innerHTML = DEV.me.role === 'authority' ? `<button class="btn primary" data-act="devInvite">${ic('plus')}Add a PC</button>` : '';
  $('#devSub').textContent = `This PC: ${DEV.me.name}${DEV.me.role === 'authority' ? ' (administrator PC)' : ''}`;
  syncIndicator(DEV.summary);
  if (DTAB.tab === 'conflicts') return devConflicts(el);
  if (DTAB.tab === 'history') return devHistory(el);
  if (DTAB.tab === 'problems') { el.innerHTML = devProblems(); return; }
  el.innerHTML = devSummary() + devRequests() + devTable() + devThisPC();
};

function devSummary() {
  const s = DEV.summary, others = DEV.nodes.filter(n => !n.self && n.status === 'active');
  const [label, tip] = s.state === 'single' ? ['Only this PC', 'No other PC has been added yet. Use "Add a PC" to share the data with other PCs.'] : (SYNC_TEXT[s.state] || SYNC_TEXT.pending);
  const cls = { ok: 'green', pending: 'blue', offline: 'gray', problem: 'red', single: 'gray' }[s.state] || 'gray';
  const agree = others.filter(n => n.status_now.agree === true).length;
  return `<div class="card mb dev-sum s-${s.state}"><div class="dev-sum-in">
      <div class="kic ${cls === 'gray' ? '' : cls}">${ic(s.state === 'problem' ? 'alert' : s.state === 'ok' ? 'checkCircle' : 'sync')}</div>
      <div><h3>${esc(label)}</h3><p class="muted">${esc(tip)}</p>
        ${others.length ? `<p><b>${s.online}</b> of <b>${others.length}</b> other PC(s) reachable now · data confirmed identical with <b>${agree}</b>
          ${s.files_missing ? ` · <b>${s.files_missing}</b> photo(s)/document(s) still being copied` : ''}</p>` : ''}</div></div></div>`;
}

function devRequests() {
  const reqs = (DEV.requests || []).filter(r => r.status === 'pending');
  if (!reqs.length) return '';
  return `<div class="card mb attention"><div class="card-h">${ic('plug')}<h3>PCs asking to join</h3></div>
    <p class="hint">Approve only if the confirmation number is the same as on the new PC's screen.</p>
    <table class="tbl"><thead><tr><th>PC name</th><th>Address</th><th>Asked</th><th>Confirmation number</th><th></th></tr></thead><tbody>
    ${reqs.map(r => `<tr><td><b>${esc(r.name)}</b></td><td class="mono">${esc(r.ip)}</td><td>${agoTs(r.created_at)}</td><td class="mono big-code">${esc(r.confirm)}</td>
      <td class="nowrap"><button class="btn sm primary" data-act="devDecide" data-id="${r.id}" data-ok="1">${ic('check')}Approve</button>
        <button class="btn sm" data-act="devDecide" data-id="${r.id}" data-ok="0">${ic('x')}Reject</button></td></tr>`).join('')}
    </tbody></table></div>`;
}

function peerLine(n) {
  const st = n.status_now || {};
  if (n.self) return `<span class="badge b-blue">This PC</span>`;
  if (n.status === 'revoked') return `<span class="badge b-gray">Removed ${n.revoked_at ? fmt(n.revoked_at.slice(0, 10)) : ''}</span>`;
  const [l, c] = PEER_STATE[st.state] || PEER_STATE.unknown;
  let extra = '';
  if (st.state === 'online') {
    const out = st.pending_out || 0, inn = st.pending_in || 0;
    extra = out || inn ? `<small>${out ? out + ' change(s) to send' : ''}${out && inn ? ' · ' : ''}${inn ? inn + ' to receive' : ''}</small>`
      : st.agree === true ? '<small class="ok-txt">Same data ✓</small>' : st.agree === false ? '<small class="bad-txt">Data differs – see Problems</small>' : '';
  } else if (st.state === 'offline') extra = `<small>last seen ${agoTs(st.last_seen)}</small>`;
  else if (st.state === 'error') extra = `<small class="bad-txt" title="${esc(st.last_error || '')}">${esc(short(st.last_error || '', 70))}</small>`;
  return `<span class="badge ${c}">${l}</span>${extra ? '<br>' + extra : ''}`;
}

function devTable() {
  const admin = DEV.me.role === 'authority';
  return `<div class="card mb"><div class="card-h">${ic('monitor')}<h3>PCs in this system</h3></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>PC</th><th>Address</th><th>Status</th><th>Last shared</th><th>Program</th><th>Added</th><th></th></tr></thead><tbody>
    ${DEV.nodes.map(n => `<tr class="${n.status === 'revoked' ? 'muted' : ''}">
      <td><b>${esc(n.name)}</b>${n.authority ? ' <span class="badge b-purple" title="User accounts and permissions are managed here">Administrator PC</span>' : ''}
        <br><small class="mono muted" title="Device identity">${esc(n.id)}</small></td>
      <td class="mono">${n.self ? esc((DEV.me.addresses || []).join(', ') + ' · port ' + DEV.me.port) : esc(n.address || '-')}</td>
      <td>${peerLine(n)}</td>
      <td class="nowrap">${n.self ? '-' : agoTs((n.status_now || {}).last_ok)}</td>
      <td class="nowrap">${n.self ? esc(DEV.me.app) : esc((n.status_now || {}).version || '-')}</td>
      <td class="nowrap">${n.enrolled_at ? fmt(n.enrolled_at.slice(0, 10)) : '-'}</td>
      <td class="nowrap">${admin && n.status === 'active' ? `<button class="btn sm" data-act="devEdit" data-id="${n.id}">${ic('edit')}Edit</button>
        ${n.self ? '' : `<button class="btn sm danger" data-act="devRevoke" data-id="${n.id}">${ic('trash')}Remove</button>`}` : ''}</td></tr>`).join('')}
    </tbody></table></div>
    ${admin ? '' : '<p class="hint">PCs can be added, changed or removed only on the administrator PC.</p>'}</div>`;
}

function devThisPC() {
  const v = DEV.last_verify, m = DEV.me;
  return `<div class="grid2">
    <div class="card"><div class="card-h">${ic('shield')}<h3>History protection</h3></div>
      <p>Every change on every PC is stored in a chained, signed history that is copied to all PCs. Editing or deleting old entries is detected.</p>
      <dl class="kv"><dt>Stored changes</dt><dd>${DEV.journal.changes.toLocaleString()} from ${DEV.journal.origins} PC(s)${DEV.journal.rejected ? ` · <b class="bad-txt">${DEV.journal.rejected} refused</b>` : ''}</dd>
        <dt>Last check</dt><dd>${v ? `${esc(v.ts.replace('T', ' '))} – ${v.ok ? '<b class="ok-txt">no problems ✓</b>' : `<b class="bad-txt">${v.problemCount} problem(s)</b>`} (${v.checked.toLocaleString()} changes)` : 'not yet'}</dd>
        <dt>Data fingerprint</dt><dd class="mono" title="Identical on PCs with the same data">${esc(m.fingerprint.slice(0, 16))}…</dd></dl></div>
    <div class="card"><div class="card-h">${ic('image')}<h3>Photos &amp; documents</h3></div>
      ${DEV.missing_files.length ? `<p>${DEV.missing_files.length} file(s) are still being copied from other PCs. They appear automatically when a PC that has them is reachable.</p>
        <ul class="small-list">${DEV.missing_files.slice(0, 8).map(f => `<li class="mono">${esc(f)}</li>`).join('')}</ul>`
        : '<p class="ok-txt">All photos and documents are on this PC ✓</p>'}</div></div>`;
}

function devProblems() {
  const al = DEV.alerts || [];
  if (!al.length) return `<div class="card"><p class="empty">No problems. ${ic('checkCircle')}</p></div>`;
  const KIND = { fork: 'Two different histories', signature: 'Invalid signature', rejected: 'Change refused', integrity: 'History check failed',
    clock: 'Wrong clock', divergence: 'Data differs', revoked: 'PC removed', 'revoked-pc': 'Removed PC tried to connect', 'unknown-pc': 'Unknown PC',
    auth: 'Impersonation attempt', replay: 'Repeated request refused', file: 'Damaged file copy', rollback: 'History restored', version: 'Update needed',
    'bad-data': 'Unreadable data' };
  return `<div class="card"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>When</th><th>What</th><th>Details</th><th>Times</th><th></th></tr></thead><tbody>
    ${al.map(a => `<tr class="${a.severity === 'error' ? 'err' : ''}"><td class="nowrap">${esc(a.last_ts.replace('T', ' '))}</td>
      <td><span class="badge ${a.severity === 'error' ? 'b-red' : 'b-orange'}">${esc(KIND[a.kind] || a.kind)}</span></td>
      <td class="wrap">${esc(a.detail)}</td><td class="num">${a.count}</td>
      <td><button class="btn sm" data-act="devAck" data-key="${esc(a.key)}" title="Hide until it happens again">${ic('check')}Seen</button></td></tr>`).join('')}
    </tbody></table></div></div>`;
}

async function devHistory(el) {
  const rows = await api('GET', '/api/devices/log?limit=300');
  const name = id => (DEV.nodes.find(n => n.id === id) || { name: id }).name;
  el.innerHTML = `<div class="card"><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>PC</th><th>Result</th><th>Received</th><th>Sent</th><th>Files</th><th>Duration</th><th>Details</th></tr></thead><tbody>
    ${rows.map(r => { const d = JSON.parse(r.detail || '{}');
      return `<tr class="${r.event === 'error' ? 'err' : ''}"><td class="nowrap">${esc(r.ts.replace('T', ' '))}</td><td>${esc(name(r.peer))}</td>
        <td><span class="badge ${r.event === 'ok' ? 'b-green' : r.event === 'offline' ? 'b-gray' : 'b-red'}">${esc(r.event)}</span></td>
        <td class="num">${d.pulled || 0}</td><td class="num">${d.pushed || 0}</td><td class="num">${d.files || 0}</td><td class="num">${d.ms != null ? d.ms + ' ms' : ''}</td>
        <td class="wrap log-detail" title="${esc(d.error || '')}">${esc(short(d.error || '', 90))}</td></tr>`; }).join('') || '<tr><td colspan="8" class="empty">No sync activity yet</td></tr>'}
    </tbody></table></div><p class="hint">Only rounds that moved something or had a problem are listed. Full details: data/logs/sync-YYYY-MM.jsonl</p></div>`;
}

/* ---------- conflicts ---------- */
const FIELD_NAME = { name: 'Name', status: 'Status', description: 'Description', responsible: 'Responsible', capacity: 'Capacity', condition: 'Condition',
  note: 'Notes', notes: 'Notes', value: 'Value', title: 'Title', priority: 'Priority', caption: 'Caption', main: 'Main photo', location: 'Location',
  building: 'Building', floor: 'Floor', details: 'Details', assignedTo: 'Assigned to', result: 'Result', percentage: 'Satisfaction %' };
const valTxt = v => v == null || v === '' ? '(empty)' : typeof v === 'object' ? JSON.stringify(v) : String(v);
const byTxt = b => b ? `${esc(b.actor || '?')} on <b>${esc(b.node_name || '?')}</b>, ${esc((b.ts || '').replace('T', ' '))}` : 'unknown';
let CONFLICTS = [];

async function devConflicts(el) {
  CONFLICTS = await api('GET', '/api/conflicts');
  const areaName = id => (area(id) || { name: id || '' }).name;
  const link = c => c.area && area(c.area) ? `<a class="link" href="#/area/${esc(c.area)}">${esc(areaName(c.area))}</a>` : esc(areaName(c.area));
  el.innerHTML = CONFLICTS.length ? CONFLICTS.map((c, i) => {
    const head = `<div class="card-h">${ic('merge')}<h3>${esc(c.title.replace(/s$/, ''))} “${esc(short(c.name, 50))}”</h3><span class="muted">${link(c)}</span></div>`;
    if (c.kind === 'conflict') return `<div class="card mb conflict">${head}
      ${Object.entries(c.detail).map(([f, list]) => `<p><b>${esc(FIELD_NAME[f] || f)}</b> was changed on two PCs at the same time. The value marked “shown” is used everywhere right now:</p>
        <table class="tbl"><tbody>${list.map(e => `<tr><td class="wrap"><b>${esc(valTxt(e.value))}</b></td><td>${byTxt(e.by)}</td>
          <td>${e.win ? '<span class="badge b-green">shown</span>' : ''}</td>
          <td><button class="btn sm" data-act="conflictKeep" data-i="${i}" data-f="${esc(f)}" data-v="${esc(JSON.stringify(e.value))}">${ic('check')}Use this</button></td></tr>`).join('')}</tbody></table>`).join('')}</div>`;
    if (c.kind === 'deleted-edit') return `<div class="card mb conflict">${head}
      <p>It was <b>deleted</b> by ${byTxt(c.delete_by)}, while it was <b>changed</b> on another PC by ${(c.edits_by || []).map(byTxt).join('; ')}.
        It stays deleted (nothing is lost: the changes are kept with it in the Recycle Bin).</p>
      <div class="filters"><button class="btn sm" data-act="conflictDel" data-i="${i}">${ic('trash')}Keep it deleted</button>
        <button class="btn sm primary" data-act="conflictRestore" data-i="${i}">${ic('restore')}Bring it back with the changes</button></div></div>`;
    if (c.kind === 'negative') return `<div class="card mb conflict">${head}
      <p>After combining the movements made on several PCs the quantity is <b>${esc(Object.values(c.detail)[0])}</b> (below zero).
        Items were probably removed twice. Please count the items and correct the inventory.</p></div>`;
    if (c.kind === 'duplicate') return `<div class="card mb conflict">${head}
      <p>This satisfaction result was entered <b>${c.detail.count} times</b> (probably on different PCs). Delete the extra entries in the break area.</p></div>`;
    return '';
  }).join('') : `<div class="card"><p class="empty">No conflicts. Changes made on different PCs fitted together. ${ic('checkCircle')}</p></div>`;
}

async function resolveConflict(body, done) {
  try { await api('POST', '/api/conflicts/resolve', body); await load(); rerender(); toast(done); }
  catch (e) { toast(e.message, true, 7000); }
}

Object.assign(ACT, {
  devTab: d => { DTAB.tab = d.tab; rerender(); },
  async devSyncNow() { try { await api('POST', '/api/devices/sync-now', {}); toast('Contacting all PCs…'); setTimeout(rerender, 2500); } catch (e) { toast(e.message, true); } },
  async devVerify() {
    toast('Checking the complete history…', false, 20000);
    try {
      const r = await api('POST', '/api/devices/verify', { all: true });
      toast(r.ok ? `History checked: ${r.checked.toLocaleString()} changes, no problems` : `${r.problemCount} problem(s) found – see Problems & Alerts`, !r.ok, 8000);
      rerender();
    } catch (e) { toast(e.message, true); }
  },
  async devInvite() {
    let r;
    try { r = await api('POST', '/api/devices/invite', {}); } catch (e) { return toast(e.message, true, 7000); }
    modal('Add a PC', `<ol class="steps">
        <li>Copy the program folder to the new PC <b>without</b> the <span class="mono">data</span> folder, and start it with <b>start.bat</b>.</li>
        <li>On the new PC choose <b>Join an existing system</b> and enter:
          <dl class="kv"><dt>Administrator PC address</dt><dd class="mono">${r.addresses.map(a => esc(a + ':' + r.port)).join('<br>') || esc('this PC\'s IP address:' + r.port)}</dd>
            <dt>Pairing code</dt><dd><span class="big-code mono">${esc(r.code)}</span></dd></dl></li>
        <li>Come back here: the PC appears under “PCs asking to join”. Approve it if its confirmation number matches.</li></ol>
      <p class="hint">The code works once and expires at ${esc(r.expires.replace('T', ' '))}. Nobody can join without your approval.</p>`,
    { extra: `<button type="button" class="btn" data-act="copyLink" data-url="${esc(r.code)}">${ic('copy')}Copy code</button>` });
    const poll = setInterval(() => { if (!$('#modal').classList.contains('open')) { clearInterval(poll); rerender(); } }, 1500);
  },
  async devDecide(d) {
    const ok = d.ok === '1';
    if (ok && !confirm('Is the confirmation number the same on the new PC\'s screen?\n\nOnly then approve.')) return;
    try { await api('POST', '/api/devices/decide', { id: d.id, approve: ok }); toast(ok ? 'PC added – the data is being copied to it' : 'Request rejected'); rerender(); }
    catch (e) { toast(e.message, true, 7000); }
  },
  devEdit(d) {
    const n = DEV.nodes.find(x => x.id === d.id);
    modal(`PC – ${esc(n.name)}`, `<div class="form-grid">
      <label>Name<input name="name" value="${esc(n.name)}" required></label>
      <label>Address (IP:port)<input name="address" class="mono" value="${esc(n.address || '')}" placeholder="192.168.1.20:8443"></label>
      <p class="full hint">The address is where the other PCs reach this PC. Change it when the PC gets a new IP address.</p></div>`, {
      submit: 'Save',
      async onSubmit(v) {
        try { await api('POST', '/api/devices/update', { id: n.id, name: v.name.trim(), address: n.self ? undefined : v.address.trim() }); }
        catch (e) { toast(e.message, true, 7000); return false; }
        toast('Saved'); rerender();
      }
    });
  },
  async devRevoke(d) {
    const n = DEV.nodes.find(x => x.id === d.id);
    if (!confirm(`Remove ${n.name} from the system?\n\nIt can no longer exchange data with the other PCs. Everything it did until now stays in the data and the history.\nUse this when a PC is replaced, lost or must not be used any more.`)) return;
    try { await api('POST', '/api/devices/revoke', { id: n.id }); toast(`${n.name} removed`); rerender(); }
    catch (e) { toast(e.message, true, 7000); }
  },
  async devAck(d) { try { await api('POST', '/api/devices/ack', { key: d.key }); rerender(); } catch (e) { toast(e.message, true); } },
  conflictKeep: d => { const c = CONFLICTS[+d.i]; resolveConflict({ entity: c.entity, id: c.id, action: 'value', field: d.f, value: JSON.parse(d.v) }, 'Conflict resolved on all PCs'); },
  conflictDel: d => { const c = CONFLICTS[+d.i]; resolveConflict({ entity: c.entity, id: c.id, action: 'keep-deleted' }, 'It stays deleted'); },
  conflictRestore: d => { const c = CONFLICTS[+d.i]; resolveConflict({ entity: c.entity, id: c.id, action: 'restore' }, 'Brought back on all PCs'); }
});

/* keep the Devices & Sync page current while it is open (not while a window is open over it) */
setInterval(() => {
  if (!ME || !DB || parseRoute()[0] !== 'devices' || $('#modal').classList.contains('open') || document.hidden) return;
  if (!['devices', 'problems'].includes(DTAB.tab)) return;
  const el = $('[data-async=devices]');
  if (el) ASYNC.devices(el).catch(() => { /* next time */ });
}, 5000);

/* ============================== first start: create or join ============================== */
function showSetup(local, st) {
  st = st || {};
  const node = st.node || {};
  if (node.role === 'member') return showReceiving();
  if (node.join) return showJoinWait(node.join);
  if (!local) {
    return authScreen(`<h2>System not set up yet</h2><p class="muted">This PC must first be set up <b>on the PC itself</b>
      (the PC running start.bat) by opening <b>http://localhost:${esc(location.port || '80')}/</b> there.</p>
      <button class="btn" data-act="reloadPage">${ic('restore')}Try again</button>`);
  }
  authScreen(`<h2>Welcome – set up this PC</h2>
    <div class="setup-choice">
      <button class="choice" data-act="setupCreate">${ic('user')}<b>This is the first (or only) PC</b><small>Create the administrator account. This PC becomes the administrator PC.</small></button>
      <button class="choice" data-act="setupJoin">${ic('plug')}<b>Join an existing system</b><small>The system already runs on the administrator PC. You need its address and a pairing code from the administrator.</small></button>
    </div>`);
}
function showCreate() {
  authScreen(`<h2>Create the administrator account</h2>
    <p class="muted">This is the first start. The administrator can add users, choose what each one may see and do, and review everything they did.</p>
    <form class="auth-form" data-form="setup">
      <label>Full name<input name="full_name" required autocomplete="name" placeholder="e.g. Ayman Essam"></label>
      <label>User name<input name="username" required autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="e.g. ayman"></label>
      <label>Password<input name="password" type="password" required autocomplete="new-password"></label>
      <label>Repeat password<input name="password2" type="password" required autocomplete="new-password"></label>
      <p class="hint">${pwRules()}</p>
      <p class="auth-msg" id="authMsg"></p>
      <button class="btn primary">${ic('check')}Create Administrator</button>
      <button type="button" class="btn" data-act="reloadPage">${ic('arrowLeft')}Back</button>
    </form>`);
}
function showJoin() {
  authScreen(`<h2>Join an existing system</h2>
    <p class="muted">Ask the administrator to open <b>Devices &amp; Sync → Add a PC</b> on the administrator PC. It shows the address and a pairing code.</p>
    <form class="auth-form" data-form="join">
      <label>Administrator PC address<input name="address" required class="mono" placeholder="e.g. 192.168.1.10:8443"></label>
      <label>Pairing code<input name="code" required class="mono" autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"></label>
      <label>Name of this PC<input name="name" required placeholder="e.g. HR Office PC" value=""></label>
      <p class="auth-msg" id="authMsg"></p>
      <button class="btn primary">${ic('plug')}Send Join Request</button>
      <button type="button" class="btn" data-act="reloadPage">${ic('arrowLeft')}Back</button>
    </form>`);
}
let JOIN_POLL;
function showJoinWait(j) {
  authScreen(`<h2>Waiting for the administrator</h2>
    <p>The request was sent to <b>${esc((j.authority || {}).name || 'the administrator PC')}</b>. Ask the administrator to approve it in <b>Devices &amp; Sync</b>.</p>
    <p>They must see the same confirmation number:</p><p class="big-code mono" id="joinCode">${esc(j.confirm)}</p>
    <p class="auth-msg" id="authMsg"></p>
    <button type="button" class="btn" data-act="joinCancel">${ic('x')}Cancel</button>`);
  clearInterval(JOIN_POLL);
  JOIN_POLL = setInterval(async () => {
    try {
      const r = await api('GET', '/api/join/status');
      if (r.status === 'approved') { clearInterval(JOIN_POLL); showReceiving(); }
      else if (r.status === 'rejected' || r.status === 'none') { clearInterval(JOIN_POLL); authScreen(`<h2>The request was not approved</h2><p>Ask the administrator for a new pairing code.</p>
        <button class="btn" data-act="reloadPage">${ic('restore')}Start again</button>`); }
    } catch (e) { /* keep waiting */ }
  }, 2000);
}
function showReceiving() {
  authScreen(`<h2>Approved – copying the data</h2><p>This PC now receives the user accounts and all data from the other PCs. This can take a few minutes the first time.</p>
    <p class="muted" id="authMsg">Please wait…</p>`);
  clearInterval(JOIN_POLL);
  JOIN_POLL = setInterval(async () => {
    try {
      const st = await api('GET', '/api/auth/status');
      if (st.hasUsers) { clearInterval(JOIN_POLL); showLogin('This PC is ready. Log in with your usual user name and password.'); }
    } catch (e) { /* keep waiting */ }
  }, 2000);
}
function showMoved(st) {
  if (!st.local) {
    return authScreen(`<h2>This PC needs a decision</h2><p>The data folder of this PC seems to come from another PC. Open the system <b>on this PC itself</b>
      (http://localhost:${esc(location.port || '80')}/) to decide.</p>`);
  }
  authScreen(`<h2>Is this the same computer?</h2>
    <p>The data folder was created on another computer (or this computer's name or network card changed).
      To protect the data, this PC does not share anything until you decide.</p>
    <div class="setup-choice">
      <button class="choice" data-act="movedSame">${ic('check')}<b>Yes, the same computer</b><small>Only its name or network card changed. Continue as before.</small></button>
      <button class="choice" data-act="movedNew">${ic('plug')}<b>No, this is a copy on a new PC</b><small>The copied data is set aside (nothing is deleted) and this PC is set up as a new PC that joins the system.</small></button>
    </div>`);
}
Object.assign(ACT, {
  setupCreate: () => showCreate(),
  setupJoin: () => showJoin(),
  async joinCancel() { try { await api('POST', '/api/join/cancel', {}); } catch (e) { /* ignore */ } location.reload(); },
  async movedSame() { await api('POST', '/api/node/moved', { choice: 'same' }); location.reload(); },
  async movedNew() {
    if (!confirm('Set this PC up as a new PC? The copied data folder is kept in data/copied-<date> and not used any more.')) return;
    await api('POST', '/api/node/moved', { choice: 'new' });
    authScreen(`<h2>Please restart</h2><p>Close the black server window and start <b>start.bat</b> again. Then choose “Join an existing system”.</p>`);
  }
});
document.addEventListener('submit', async e => {
  const f = e.target;
  if (f.dataset.form !== 'join') return;
  e.preventDefault();
  const d = Object.fromEntries(new FormData(f)), msg = $('#authMsg'), btn = $('button.primary', f);
  msg.textContent = '';
  btn.disabled = true;
  try {
    const r = await api('POST', '/api/join', { address: d.address.trim(), code: d.code.trim(), name: d.name.trim() });
    showJoinWait(r);
  } catch (err) { msg.textContent = err.message; }
  finally { btn.disabled = false; }
});

boot();
