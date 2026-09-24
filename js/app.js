/* Break Area Management System – single page application.
   All data lives in the SQLite database of the local server (server/app.py).
   The page edits an in-memory copy (DB); save() sends only the rows that changed
   since the last load, and the server applies them in one transaction. */
'use strict';

let DB;
let SNAP = {};          // "entity|id" -> { s: row as JSON, ver } as last loaded from the server
let BASE_URL = location.origin + location.pathname;
const DEFAULT_SETTINGS = {
  systemName: 'Break Area Management System', factory: 'Beni Suef Factory', logoText: 'SAMSUNG', logoImage: '',
  inspectionDays: 30, satisfactionTarget: 80, locations: ['Production', 'Admin', 'Utility', 'Logistics', 'Other']
};

/* ============================== Login & permissions ============================== */
let ME = null;          // the logged-in user from the server: { username, full_name, perms, areas, ... }
const me = () => ME ? ME.full_name : '';
/* true when the user has at least one of the permissions. The server checks every request again -
   hiding buttons here is only so people are not offered things they cannot do. */
const can = (...perms) => !!ME && perms.some(p => ME.perms.includes(p));
const allAreas = () => !!ME && ME.areas == null;
const LOG_TABS = [['audit', 'Data Changes', 'logs.view'], ['activity', 'User Activity & Errors', 'logs.activity'], ['security', 'Logins & Security', 'logs.security']];
const canSettingsPage = () => can('settings.view', 'backups.manage', 'backups.restore', 'trash.restore', 'data.import');
/* route -> permission(s) needed to open it */
const PAGE_PERMS = {
  dashboard: ['dashboard.view'], areas: ['areas.view'], area: ['areas.view'], equipment: ['equipment.view'], transactions: ['transactions.view'],
  maintenance: ['maintenance.view'], reports: ['reports.view'], logs: ['logs.view', 'logs.activity', 'logs.security'], users: ['users.manage']
};
const canPage = top => top === 'settings' ? canSettingsPage() : top === 'account' ? true : can(...(PAGE_PERMS[top] || ['dashboard.view']));
const firstPage = () => ['dashboard', 'areas', 'maintenance', 'equipment', 'transactions', 'reports', 'logs', 'users', 'settings'].find(canPage) || 'account';

/* ============================== Server API ============================== */
async function api(method, url, body, { raw = false, blob = false } = {}) {
  const headers = {};
  if (body !== undefined && !raw) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(url, { method, headers, body: body === undefined ? undefined : raw ? body : JSON.stringify(body) });
  } catch (e) {
    throw new Error('Cannot reach the server. Check that the server window is open on the host PC.');
  }
  if (!res.ok) {
    let msg = res.status + ' ' + res.statusText;
    try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
    if (res.status === 401 && !url.startsWith('/api/auth/')) showLogin('Your session has ended. Please log in again.');
    throw new Error(msg);
  }
  return blob ? res.blob() : res.json();
}

const stable = v => JSON.stringify(v, (k, x) => x && typeof x === 'object' && !Array.isArray(x)
  ? Object.keys(x).sort().reduce((o, key) => { if (x[key] != null) o[key] = x[key]; return o; }, {}) : x);

/* The nested DB object as flat database rows: { "entity|id": { e, id, row } } */
function flatten(db) {
  const out = {};
  const put = (e, row) => { const { ver, ...r } = row; out[e + '|' + r.id] = { e, id: r.id, row: r }; };
  Object.entries(db.settings).forEach(([id, value]) => put('settings', { id, value }));
  db.itemTypes.forEach(t => put('itemTypes', t));
  db.areas.forEach(a => {
    const { inventory, photos, docs, issues, maintenance, inspections, surveys, ...base } = a;
    put('areas', base);
    inventory.forEach(x => put('inventory', { ...x, id: x.id || a.id + ':' + x.item, areaId: a.id }));
    [['photos', photos], ['docs', docs], ['maintenance', maintenance], ['inspections', inspections], ['surveys', surveys || []]]
      .forEach(([e, list]) => list.forEach(x => put(e, { ...x, areaId: a.id })));
    issues.forEach(i => {
      const { log, ...b } = i;
      put('issues', { ...b, areaId: a.id });
      (log || []).forEach((l, k) => put('issueLog', { ...l, id: l.id || i.id + ':' + k, issueId: i.id }));
    });
  });
  db.history.forEach(h => put('history', h));
  return out;
}

async function load() {
  const s = await api('GET', '/api/state');
  s.settings = { ...DEFAULT_SETTINGS, ...s.settings };
  s.areas.forEach(a => { a.surveys = a.surveys || []; a.issues.forEach(i => (i.log = i.log || [])); });
  const vers = {};
  const walk = (e, x) => { if (x.ver) vers[e + '|' + x.id] = x.ver; };
  (s.settingsVer ? Object.entries(s.settingsVer) : []).forEach(([id, ver]) => (vers['settings|' + id] = ver));
  s.itemTypes.forEach(x => walk('itemTypes', x));
  s.history.forEach(x => walk('history', x));
  s.areas.forEach(a => {
    walk('areas', a);
    a.inventory.forEach(x => walk('inventory', x));
    ['photos', 'docs', 'maintenance', 'inspections', 'surveys'].forEach(e => a[e].forEach(x => walk(e, x)));
    a.issues.forEach(i => { walk('issues', i); i.log.forEach(l => walk('issueLog', l)); });
  });
  DB = s;
  SNAP = {};
  const flat = flatten(DB);
  for (const k in flat) SNAP[k] = { s: stable(flat[k].row), ver: vers[k] };
  // settings filled from defaults are not in the database yet
  for (const k in SNAP) if (k.startsWith('settings|') && !vers[k]) delete SNAP[k];
}

/* Send every change made to DB since the last load. Returns true when saved. */
async function save(label = 'Change', { force = false } = {}) {
  const cur = flatten(DB), ops = [];
  if (!can('settings.edit')) for (const k in cur) if (k.startsWith('settings|')) delete cur[k];
  for (const k in cur) {
    const s = stable(cur[k].row), old = SNAP[k];
    if (!old || old.s !== s) ops.push({ e: cur[k].e, id: cur[k].id, op: 'put', row: cur[k].row, ver: old ? old.ver : undefined });
  }
  for (const k in SNAP) if (!cur[k] && !(k.startsWith('settings|') && !can('settings.edit'))) { const [e, ...id] = k.split('|'); ops.push({ e, id: id.join('|'), op: 'del', ver: SNAP[k].ver }); }
  if (!ops.length) return true;
  try {
    await api('POST', '/api/commit', { label, ops, force });
    track('save', label, ops.length + ' change(s)');
    await load();
    return true;
  } catch (err) {
    track('save-failed', label, err.message);
    closeModal();
    try { await load(); } catch (e) { /* keep the screen */ }
    rerender();
    toast('Not saved: ' + err.message, true, 8000);
    return false;
  }
}

async function uploadFile(file, name) {
  const r = await api('POST', '/api/upload?name=' + encodeURIComponent(name || file.name || 'file'), file, { raw: true });
  return r.src;
}
/* Uploads the original image untouched plus a small preview for lists and cards. */
async function uploadImage(file) {
  const src = await uploadFile(file);
  let thumb = '';
  try { thumb = await uploadFile(await resizeImage(file, 800, true), 'thumb.jpg'); } catch (e) { /* browser can't decode it (e.g. HEIC) */ }
  return { src, thumb };
}

/* ============================== Activity log ============================== */
const LOGQ = [];
const localIso = () => { const t = new Date(); return iso(t) + 'T' + [t.getHours(), t.getMinutes(), t.getSeconds()].map(pad).join(':'); };
function track(type, action, target = '', detail = '') {
  LOGQ.push({ ts: localIso(), user: me(), type, action: String(action || ''), target: String(target || '').slice(0, 200), page: location.hash || '#/dashboard', detail: String(detail || '') });
  if (LOGQ.length >= 40) flushLog();
}
function flushLog(beacon) {
  if (!LOGQ.length) return;
  const events = LOGQ.splice(0);
  const body = JSON.stringify({ events });
  if (beacon && navigator.sendBeacon) { navigator.sendBeacon('/api/log', new Blob([body], { type: 'application/json' })); return; }
  fetch('/api/log', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body })
    .catch(() => { if (LOGQ.length < 2000) LOGQ.unshift(...events); });
}
setInterval(flushLog, 4000);
addEventListener('pagehide', () => flushLog(true));
addEventListener('error', e => track('js-error', e.message, (e.filename || '') + ':' + (e.lineno || ''), e.error && e.error.stack));
addEventListener('unhandledrejection', e => track('js-error', String(e.reason && e.reason.message || e.reason), '', e.reason && e.reason.stack));
document.addEventListener('click', e => {
  const el = e.target.closest('button, a, [data-act], tr.click, label.btn');
  if (!el) return;
  const text = (el.textContent || el.title || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
  track('click', el.dataset.act || el.getAttribute('href') || el.tagName.toLowerCase(), text);
}, true);

/* ============================== Helpers ============================== */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const uid = () => Math.random().toString(36).slice(2, 10);
const pad = n => String(n).padStart(2, '0');
const iso = t => t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
const today = () => iso(new Date());
const addDays = (d, n) => { const t = new Date(d + 'T00:00:00'); t.setDate(t.getDate() + n); return iso(t); };
const daysFromToday = d => Math.round((new Date(d + 'T00:00:00') - new Date(today() + 'T00:00:00')) / 864e5);
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fmt = d => { if (!d) return '-'; const [y, m, dd] = d.split('-'); return `${dd}-${MON[+m - 1]}-${y}`; };
const initials = n => String(n || '?').split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
const fileSize = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';

const area = id => DB.areas.find(a => a.id === id);
const itemType = id => DB.itemTypes.find(t => t.id === id);
const itemName = id => id === 'area' ? 'Break Area' : (itemType(id) || { name: id }).name;
const itemShort = id => { if (id === 'area') return 'Break Area'; const t = itemType(id); return t ? (t.short || t.name) : id; };
const invEntry = (a, item) => a.inventory.find(i => i.item === item);
const qty = (a, item) => (invEntry(a, item) || {}).qty || 0;
const byDateDesc = (x, y) => (y.date || '').localeCompare(x.date || '') || (y.seq || 0) - (x.seq || 0);
const areaHistory = id => DB.history.filter(h => h.areaId === id).sort(byDateDesc);
const lastUpdate = a => DB.history.reduce((m, h) => h.areaId === a.id && h.date > m ? h.date : m, a.startDate || '');
const openIssues = a => a.issues.filter(i => i.status !== 'Closed');
const mainPhoto = a => a.photos.find(p => p.main) || a.photos[0];
const areaURL = id => BASE_URL + '#/area/' + id;
const setting = k => DB.settings[k];

function setQty(a, item, value, condition) {
  let e = invEntry(a, item);
  if (!e) { e = { item, qty: 0, condition: 'Good' }; a.inventory.push(e); }
  e.qty = Math.max(0, value);
  if (condition) e.condition = condition;
}
let lastSeq = 0;
function pushHistory(rec) {
  // time-based so two PCs saving at the same moment never produce the same record id
  const seq = lastSeq = Math.max(Date.now(), lastSeq + 1);
  DB.history.push({ id: 'h' + seq.toString(36) + uid().slice(0, 3), seq, ...rec });
}

function toast(msg, error, ms = 2600) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'show' + (error ? ' error' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ''), ms);
}

/* ============================== Satisfaction survey ============================== */
const MONTHS_FULL = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const monthName = m => { if (!m) return '-'; const [y, mm] = m.split('-'); return `${MONTHS_FULL[+mm - 1]} ${y}`; };
const monthShort = m => { const [y, mm] = m.split('-'); return `${MON[+mm - 1]} ${y.slice(2)}`; };
const satTarget = () => +setting('satisfactionTarget') || 80;
const pct = v => v == null ? '-' : (Math.round(v * 10) / 10) + '%';
const avg = list => list.length ? list.reduce((s, x) => s + x, 0) / list.length : null;
/* One value per month for an area (average of the departments surveyed that month), oldest first. */
function areaMonthly(a) {
  const m = {};
  (a.surveys || []).forEach(s => (m[s.month] = m[s.month] || []).push(+s.percentage));
  return Object.keys(m).sort().map(month => ({ month, value: avg(m[month]), n: m[month].length }));
}
const latestSat = a => { const m = areaMonthly(a); return m.length ? m[m.length - 1] : null; };
function satLevel(v) {
  const t = satTarget();
  return v == null ? '' : v >= t ? 'good' : v >= t - 15 ? 'warn' : 'bad';
}
const SAT_LABEL = { good: 'On target', warn: 'Below target', bad: 'Needs action' };
const satBadge = v => v == null ? '<span class="muted">-</span>'
  : `<span class="sat-pill ${satLevel(v)}" title="${SAT_LABEL[satLevel(v)]} (target ${satTarget()}%)">${pct(v)}</span>`;

/* ============================== Icons ============================== */
const IC = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  building: '<path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 9h1M14 9h1M9 13h1M14 13h1M9 17h1M14 17h1"/>',
  sofa: '<path d="M4 11V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3"/><path d="M2 13a2 2 0 0 1 4 0v2h12v-2a2 2 0 0 1 4 0v5H2z"/><path d="M5 18v2M19 18v2"/>',
  swap: '<path d="M7 4 3 8l4 4"/><path d="M3 8h14"/><path d="m17 20 4-4-4-4"/><path d="M21 16H7"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
  report: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M8 17v-3M12 17v-5M16 17v-2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  filter: '<path d="M22 3H2l8 9.5V19l4 2v-8.5z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  arrowLeft: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  chevL: '<path d="m15 18-6-6 6-6"/>',
  chevR: '<path d="m9 18 6-6-6-6"/>',
  chevD: '<path d="m6 9 6 6 6-6"/>',
  qr: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v.01M14 20h.01M17 20h4v-3"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  calCheck: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><path d="m9 16 2 2 4-4"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  chair: '<path d="M7 3h10v8H7z"/><path d="M5 11h14v3H5z"/><path d="M6 14v7M18 14v7"/>',
  table: '<path d="M3 8h18v3H3z"/><path d="M5 11v10M19 11v10"/><path d="M8 11v4h8v-4"/>',
  tv: '<rect x="2" y="5" width="20" height="13" rx="2"/><path d="M8 21h8M12 18v3"/>',
  dispenser: '<rect x="7" y="10" width="10" height="12" rx="1"/><path d="M9 10V7a3 3 0 0 1 6 0v3"/><path d="M10 15h4M11 18h2"/>',
  rug: '<rect x="4" y="5" width="16" height="14" rx="1"/><rect x="8" y="9" width="8" height="6"/><path d="M4 3v2M8 3v2M12 3v2M16 3v2M20 3v2M4 19v2M8 19v2M12 19v2M16 19v2M20 19v2"/>',
  fridge: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 10h14M9 5v2M9 13v3"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
  microwave: '<rect x="2" y="5" width="20" height="14" rx="2"/><rect x="5" y="8" width="10" height="8" rx="1"/><path d="M18 9v.01M18 12v.01M18 15v.01"/>',
  coffee: '<path d="M17 8h1a4 4 0 0 1 0 8h-1"/><path d="M3 8h14v9a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z"/><path d="M6 2v2M10 2v2M14 2v2"/>',
  plant: '<path d="M7 20h10l-1-6H8z"/><path d="M12 14V8"/><path d="M12 8c0-3 2-5 5-5 0 3-2 5-5 5zM12 10c0-2.5-2-4-4.5-4 0 2.5 2 4 4.5 4z"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
  file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
  printer: '<path d="M6 9V2h12v7"/><rect x="6" y="14" width="12" height="8"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  clipboard: '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="m9 14 2 2 4-4"/>',
  area: '<rect x="3" y="3" width="18" height="18" rx="1"/><path d="M3 9h4M3 15h4M9 3v4M15 3v4"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  smile: '<circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01M15 9h.01"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
  expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8"/><path d="M14 7h7v7"/>'
};
const ITEM_ICONS = ['chair', 'table', 'tv', 'dispenser', 'rug', 'fridge', 'microwave', 'coffee', 'plant', 'sofa', 'box'];
const ic = (n, cls = '') => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n] || IC.box}</svg>`;
const itemIcon = id => ic((itemType(id) || {}).icon || 'box');

/* ============================== Badges ============================== */
const STATUS_CLS = {
  'Good': 'b-green', 'Need Maintenance': 'b-orange', 'Under Update': 'b-blue',
  'Need Repair': 'b-orange', 'Damaged': 'b-red', 'Out of Service': 'b-gray',
  'Open': 'b-orange', 'In Progress': 'b-blue', 'Closed': 'b-green',
  'Scheduled': 'b-blue', 'Done': 'b-green', 'Active': 'b-green', 'Inactive': 'b-gray',
  'High': 'b-red', 'Medium': 'b-orange', 'Low': 'b-gray',
  'Added': 'b-green', 'Removed': 'b-red', 'Replaced': 'b-blue', 'Transferred': 'b-purple',
  'Maintenance': 'b-orange', 'Created': 'b-gray', 'Condition Update': 'b-gray',
  'Pass': 'b-green', 'Updated': 'b-green', 'Issues Found': 'b-orange', 'Overdue': 'b-red', 'Due Soon': 'b-orange', 'OK': 'b-green'
};
const STATUS_COLOR = { 'Good': '#22c55e', 'Need Maintenance': '#f59e0b', 'Under Update': '#3b82f6' };
const badge = (s, dot) => `<span class="badge ${STATUS_CLS[s] || 'b-gray'}">${dot ? '<i class="dot"></i>' : ''}${esc(s)}</span>`;
const TX_STYLE = {
  Added: ['plus', 'var(--green-l)', 'var(--green)'], Removed: ['minus', 'var(--red-l)', 'var(--red)'],
  Replaced: ['swap', 'var(--sky-l)', 'var(--sky)'], Transferred: ['swap', 'var(--purple-l)', 'var(--purple)'],
  Maintenance: ['wrench', 'var(--orange-l)', '#d97706'], Created: ['building', '#eef1f5', '#475467'],
  'Condition Update': ['clipboard', '#eef1f5', '#475467']
};
function txTitle(h) {
  const d = Math.abs((h.next ?? 0) - (h.prev ?? 0));
  const nm = d === 1 ? itemShort(h.item) : itemName(h.item);
  switch (h.action) {
    case 'Added': return `Added ${d} ${nm}`;
    case 'Removed': return `Removed ${d} ${nm}`;
    case 'Transferred': return `Transferred ${d} ${nm}`;
    case 'Replaced': return `Replaced ${itemShort(h.item)}`;
    case 'Maintenance': return `Maintenance for ${itemName(h.item)}`;
    case 'Created': return 'Break area created';
    default: return `${itemShort(h.item)} condition updated`;
  }
}
const histItem = h => h.action === 'Created' ? 'Initial Setup' : itemShort(h.item);

/* ============================== Placeholder photos ============================== */
function hash(s) { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function rng(seed) { let s = hash(seed) || 1; return () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return ((s >>> 0) % 10000) / 10000; }; }

function roomSVG(seed, variant = 'seating') {
  const r = rng(seed);
  const pick = a => a[Math.floor(r() * a.length)];
  const wall = pick(['#ebe6dc', '#dfe7ef', '#ece7f0', '#e4ebe1', '#f1e9de', '#e3e9f2']);
  const floor = pick(['#b98f66', '#a3a8ae', '#c6a882', '#8e99a6', '#bb9d78']);
  const ch = pick(['#1f4e9c', '#e07a2e', '#2f7d5b', '#c0392b', '#3b3f46', '#e0a800', '#6a4c93']);
  const top = '#f7f4ee';
  let s = `<svg viewBox="0 0 400 250" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">`;
  s += `<rect width="400" height="152" fill="${wall}"/><rect y="120" width="400" height="7" fill="${ch}" opacity=".8"/>`;
  s += `<rect x="55" y="0" width="100" height="6" fill="#fff"/><rect x="245" y="0" width="100" height="6" fill="#fff"/>`;
  s += `<rect y="150" width="400" height="100" fill="${floor}"/>`;
  for (let i = -2; i < 11; i++) s += `<line x1="${i * 48}" y1="250" x2="${130 + i * 15}" y2="150" stroke="#000" stroke-opacity=".07"/>`;
  s += `<rect y="148" width="400" height="4" fill="#000" opacity=".1"/>`;
  const windowEl = x => `<rect x="${x}" y="22" width="118" height="84" rx="2" fill="#cfe5f6" stroke="#fff" stroke-width="5"/><line x1="${x + 59}" y1="22" x2="${x + 59}" y2="106" stroke="#fff" stroke-width="4"/><path d="M${x + 8} 30h34l-20 40z" fill="#fff" opacity=".35"/>`;
  const plant = (x, y, k = 1) => `<rect x="${x - 9 * k}" y="${y - 20 * k}" width="${18 * k}" height="${20 * k}" rx="2" fill="#f2f2f2" stroke="#ccc"/><circle cx="${x}" cy="${y - 34 * k}" r="${14 * k}" fill="#3f8f4f"/><circle cx="${x - 10 * k}" cy="${y - 26 * k}" r="${10 * k}" fill="#4fa35f"/><circle cx="${x + 10 * k}" cy="${y - 27 * k}" r="${10 * k}" fill="#357f45"/>`;
  const tv = (x, y, w = 92) => `<rect x="${x}" y="${y}" width="${w}" height="${w * .57}" rx="3" fill="#15181d"/><rect x="${x + 4}" y="${y + 4}" width="${w - 8}" height="${w * .57 - 8}" fill="#274a7a"/><path d="M${x + 4} ${y + w * .45}l${w * .3}-${w * .2} ${w * .25} ${w * .12} ${w * .3}-${w * .18}v${w * .31 - 8}H${x + 4}z" fill="#3d6aa8" opacity=".8"/>`;
  const dispenser = (x, y, k = 1) => `<rect x="${x}" y="${y - 70 * k}" width="${30 * k}" height="${70 * k}" rx="3" fill="#fafafa" stroke="#bbb"/><rect x="${x + 9 * k}" y="${y - 50 * k}" width="${12 * k}" height="${8 * k}" fill="#555"/><ellipse cx="${x + 15 * k}" cy="${y - 88 * k}" rx="${13 * k}" ry="${19 * k}" fill="#8ec8f0" opacity=".85"/><rect x="${x + 11 * k}" y="${y - 74 * k}" width="${8 * k}" height="${5 * k}" fill="#6aa9d6"/>`;
  const tableSet = (cx, cy, k) => {
    const w = 78 * k, cw = 15 * k;
    let t = `<ellipse cx="${cx}" cy="${cy + 26 * k}" rx="${w * .6}" ry="${7 * k}" fill="#000" opacity=".12"/>`;
    for (const dx of [-.28, .28]) t += `<rect x="${cx + dx * w - cw / 2}" y="${cy - 26 * k}" width="${cw}" height="${24 * k}" rx="${3 * k}" fill="${ch}"/>`;
    t += `<rect x="${cx - w / 2}" y="${cy - 4 * k}" width="${w}" height="${9 * k}" rx="${2 * k}" fill="${top}" stroke="#d8d2c6"/>`;
    t += `<rect x="${cx - w / 2 + 6 * k}" y="${cy + 5 * k}" width="${3 * k}" height="${18 * k}" fill="#888"/><rect x="${cx + w / 2 - 9 * k}" y="${cy + 5 * k}" width="${3 * k}" height="${18 * k}" fill="#888"/>`;
    for (const dx of [-.28, .28]) t += `<rect x="${cx + dx * w - cw * .6}" y="${cy + 8 * k}" width="${cw * 1.2}" height="${26 * k}" rx="${3 * k}" fill="${ch}" stroke="#000" stroke-opacity=".15"/>`;
    return t;
  };

  if (variant === 'coffee') {
    s += windowEl(20);
    s += `<rect x="170" y="98" width="215" height="54" fill="#6b4f3a"/><rect x="165" y="92" width="225" height="9" rx="2" fill="#e8e3da"/>`;
    s += `<rect x="190" y="62" width="34" height="30" rx="3" fill="#2d2f33"/><rect x="198" y="80" width="10" height="8" fill="#fff"/><rect x="240" y="72" width="30" height="20" rx="2" fill="#c9ccd1"/>`;
    s += `<rect x="175" y="30" width="200" height="22" rx="2" fill="#fff" opacity=".7"/>`;
    for (let i = 0; i < 4; i++) s += `<rect x="${290 + i * 18}" y="80" width="10" height="12" rx="2" fill="#fff" stroke="#bbb"/>`;
    s += tableSet(95, 190, .85) + plant(380, 250, .9);
  } else if (variant === 'entrance') {
    s += `<rect x="150" y="30" width="100" height="122" fill="#9fb8cc" stroke="#6b7c8c" stroke-width="5"/><line x1="200" y1="30" x2="200" y2="152" stroke="#6b7c8c" stroke-width="4"/><rect x="185" y="85" width="4" height="18" fill="#444"/><rect x="211" y="85" width="4" height="18" fill="#444"/>`;
    s += `<rect x="150" y="8" width="100" height="16" rx="3" fill="#1428a0"/><text x="200" y="20" text-anchor="middle" font-family="Arial" font-size="10" font-weight="700" fill="#fff">BREAK AREA</text>`;
    s += plant(115, 160, 1.1) + plant(290, 160, 1.1);
    s += `<path d="M150 152h100l40 98H110z" fill="#6b6f75" opacity=".45"/>`;
  } else if (variant === 'water') {
    s += windowEl(260);
    s += dispenser(150, 175, 1.6) + dispenser(40, 160, 1.1) + plant(340, 240, 1);
  } else if (variant === 'carpet') {
    s += windowEl(140);
    s += `<path d="M90 170h220l55 70H35z" fill="${ch}" opacity=".8"/><path d="M115 180h170l38 48H77z" fill="none" stroke="#fff" stroke-width="3" opacity=".7"/>`;
    s += `<rect x="20" y="120" width="120" height="44" rx="8" fill="#5a6270"/><rect x="14" y="140" width="132" height="30" rx="8" fill="#6b7482"/>`;
    s += plant(365, 200, 1);
  } else {
    s += windowEl(18) + tv(270, 32) + dispenser(365, 155, .9);
    s += tableSet(110, 180, .9) + tableSet(265, 185, .9) + tableSet(190, 225, 1.05);
  }
  return s + '</svg>';
}
/* Real photos are shown complete inside their frame (object-fit: contain); a blurred copy of
   the same photo fills the empty edges. full=true uses the original file instead of the preview. */
function photoHTML(p, full) {
  if (!p || !p.src) return roomSVG(p ? (p.seed || p.id) : 'x', p ? p.variant : 'seating');
  const u = esc(full ? p.src : (p.thumb || p.src));
  return `<img class="bg" src="${u}" alt="" aria-hidden="true" loading="lazy"><img class="fit" src="${u}" alt="${esc(p.caption)}" loading="lazy">`;
}

/* ============================== QR ============================== */
function qrSVG(text) {
  try {
    const q = qrcode(0, 'M');
    q.addData(text);
    q.make();
    return q.createSvgTag({ cellSize: 4, margin: 2, scalable: true });
  } catch (e) { return '<div class="muted">QR unavailable</div>'; }
}

/* ============================== Export / print ============================== */
function download(name, content, type) {
  const b = content instanceof Blob ? content : new Blob([content], { type });
  const u = URL.createObjectURL(b);
  const a = document.createElement('a');
  a.href = u; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(u), 1500);
}
async function exportXLSX(name, head, rows, sheet) {
  try {
    const b = await api('POST', '/api/xlsx', { filename: name + '_' + today(), sheets: [{ name: sheet || name.replace(/_/g, ' '), head, rows }] }, { blob: true });
    download(name + '_' + today() + '.xlsx', b);
    track('export', name, rows.length + ' rows');
    toast('Exported ' + rows.length + ' rows');
  } catch (e) { toast('Export failed: ' + e.message, true); }
}
function printHTML(html) {
  const p = $('#print');
  p.innerHTML = html;
  document.body.classList.add('printing');
  const done = () => { document.body.classList.remove('printing'); p.innerHTML = ''; window.removeEventListener('afterprint', done); };
  window.addEventListener('afterprint', done);
  setTimeout(() => window.print(), 50);
}
function printTable(title, head, rows) {
  printHTML(`<div class="print-report"><div class="logo">${esc(setting('logoText'))}</div>
    <h2>${esc(title)}</h2><div>${esc(setting('factory'))} · Printed ${fmt(today())} by ${esc(me())}</div>
    <table><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
}
function labelHTML(a) {
  return `<div class="label"><div class="logo">${esc(setting('logoText'))}</div><div class="qr">${qrSVG(areaURL(a.id))}</div>
    <h3>${esc(a.name)}</h3><p>${esc(a.location)} · ${esc(a.building)} / ${esc(a.floor)}</p><p>Scan to view break area profile</p></div>`;
}
const printLabels = list => printHTML(`<div class="labels">${list.map(labelHTML).join('')}</div>`);

/* ============================== Shell ============================== */
function renderShell(route) {
  const s = DB.settings;
  document.title = s.systemName;
  $('#brand').innerHTML = s.logoImage ? `<img src="${s.logoImage}" alt="logo">` : `<span class="logo">${esc(s.logoText)}</span>`;
  $('#sysName').textContent = s.systemName;
  $('#factoryName').textContent = s.factory;
  const open = DB.areas.reduce((n, a) => n + openIssues(a).length, 0);
  $('#bell').innerHTML = ic('bell') + (open ? `<span class="cnt">${open}</span>` : '');
  $('#user').innerHTML = `<div class="avatar">${esc(initials(me()))}</div><div class="who"><b>${esc(me())}</b><small>${esc(ME.title || ME.role || ME.username)} ▾</small></div>`;
  $('#user').dataset.act = 'accountMenu';
  $('#user').title = 'My account, change password, log out';
  $('.menu-btn').innerHTML = ic('menu');

  const top = route[0];
  const areasOpen = top === 'areas' || top === 'area';
  $('#bell').classList.toggle('hidden', !can('maintenance.view'));
  const link = (href, icon, label, active, extra = '') => canPage(href.slice(2)) ? `<a href="${href}" class="${active ? 'active' : ''}">${ic(icon)}<span>${label}</span>${extra}</a>` : '';
  $('#sidebar').innerHTML = `<div class="nav">
      ${link('#/dashboard', 'dashboard', 'Dashboard', top === 'dashboard')}
      ${link('#/areas', 'building', 'Break Areas', areasOpen, can('areas.create') ? ic(areasOpen ? 'chevD' : 'chevR', 'chev') : '')}
      ${areasOpen && can('areas.create') ? `<div class="sub">
        <a href="#/areas" class="${top === 'areas' && route[1] !== 'new' || top === 'area' ? 'active' : ''}">All Break Areas</a>
        <a href="#/areas/new" class="${route[1] === 'new' ? 'active' : ''}">Add New Break Area</a></div>` : ''}
      ${link('#/equipment', 'sofa', 'Furniture &amp; Equipment', top === 'equipment')}
      ${link('#/transactions', 'swap', 'Transactions', top === 'transactions')}
      ${link('#/maintenance', 'wrench', 'Maintenance', top === 'maintenance')}
      ${link('#/reports', 'report', 'Reports', top === 'reports')}
      ${link('#/logs', 'activity', 'Activity Log', top === 'logs')}
      ${link('#/users', 'users', 'Users &amp; Permissions', top === 'users')}
      ${link('#/settings', 'settings', 'Settings', top === 'settings')}
    </div>
    <div class="side-foot"><b>Better Break Areas</b>for a better workplace.</div>`;
}

const parseRoute = () => (location.hash.replace(/^#\/?/, '') || firstPage()).split('/');

function render() {
  if (!DB || !ME) return; // login screen is showing
  const route = parseRoute();
  document.body.classList.remove('nav-open');
  renderShell(route);
  const v = $('#view');
  const [top, id] = route;
  if (!canPage(top) || (top === 'areas' && id === 'new' && !can('areas.create'))) v.innerHTML = viewNoAccess();
  else if (top === 'area' && area(id)) v.innerHTML = viewArea(area(id));
  else if (top === 'area') v.innerHTML = `<div class="card welcome"><div class="kic">${ic('alert')}</div><h2>Break area not found</h2>
    <p>It was deleted${allAreas() ? '' : ', or it is not one of the break areas assigned to you'}.</p><a class="btn" href="#/areas">Back to Break Areas</a></div>`;
  else if (top === 'areas' && id === 'new') v.innerHTML = viewAreaForm();
  else if (top === 'areas') v.innerHTML = viewAreas();
  else if (top === 'equipment') v.innerHTML = viewEquipment();
  else if (top === 'transactions') v.innerHTML = viewTransactions();
  else if (top === 'maintenance') v.innerHTML = viewMaintenance();
  else if (top === 'reports') v.innerHTML = viewReports();
  else if (top === 'settings') v.innerHTML = viewSettings();
  else if (top === 'logs') v.innerHTML = viewLogs();
  else if (top === 'users') v.innerHTML = viewUsers();
  else if (top === 'account') v.innerHTML = viewAccount();
  else if (top === 'dashboard') v.innerHTML = viewDashboard();
  else v.innerHTML = viewNoAccess();
  $$('[data-results]', v).forEach(el => RESULTS[el.dataset.results](el));
  $$('[data-async]', v).forEach(el => ASYNC[el.dataset.async](el).catch(err => {
    el.innerHTML = `<p class="empty">Could not load: ${esc(err.message)}</p>`;
  }));
}
function rerender() { const y = scrollY; render(); scrollTo(0, y); }
function viewNoAccess() {
  return `<div class="card welcome"><div class="kic orange">${ic('alert')}</div><h2>No access</h2>
    <p>Your account does not have permission to open this page. If you need it for your work, ask the system administrator.</p>
    <a class="btn primary" href="#/${firstPage()}">Go to my start page</a></div>`;
}

/* ============================== Charts ============================== */
function donut(data, centerLabel) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const R = 42, C = 2 * Math.PI * R;
  let off = 0;
  const segs = data.map(d => {
    const len = d.value / total * C;
    const seg = `<circle cx="60" cy="60" r="${R}" fill="none" stroke="${d.color}" stroke-width="16" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 60 60)"/>`;
    off += len;
    return seg;
  }).join('');
  return `<div class="donut-wrap"><svg class="donut" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r="${R}" fill="none" stroke="#eef2f8" stroke-width="16"/>${segs}
      <text x="60" y="60" text-anchor="middle" class="c-num">${data.reduce((s, d) => s + d.value, 0)}</text>
      <text x="60" y="75" text-anchor="middle" class="c-lbl">${centerLabel}</text></svg>
    <div class="legend">${data.map(d => `<div><i style="background:${d.color}"></i>${esc(d.label)}<b>${d.value}</b></div>`).join('')}</div></div>`;
}
function vbars(data) {
  const max = Math.max(1, ...data.map(d => d.value));
  return `<div class="vbars">${data.map(d => `<div class="vbar"><span class="v">${d.value}</span><div class="b" style="height:${Math.max(2, d.value / max * 100)}%"></div></div>`).join('')}</div>
    <div class="vlabels">${data.map(d => `<div>${ic(d.icon)}${esc(d.label)}</div>`).join('')}</div>`;
}
function hbars(data) {
  const max = Math.max(1, ...data.map(d => d.value));
  return data.map(d => `<div class="hbar"><span>${esc(d.label)}</span><div class="t"><div class="f" style="width:${d.value / max * 100}%"></div></div><b>${d.value}</b></div>`).join('');
}
/* Monthly satisfaction line (0–100 %) with a dashed target line. points: [{month, value, n}] oldest first. */
function satLine(points, { h = 230, compact = false } = {}) {
  if (!points.length) return '<p class="empty">No survey results yet.</p>';
  const W = 640, H = h, L = compact ? 8 : 38, R = compact ? 8 : 18, T = 14, B = compact ? 10 : 30;
  const t = satTarget();
  const lo = Math.max(0, Math.floor((Math.min(t, ...points.map(p => p.value)) - 10) / 10) * 10);
  const x = i => points.length === 1 ? (L + W - R) / 2 : L + i * (W - L - R) / (points.length - 1);
  const y = v => T + (100 - v) / (100 - lo) * (H - T - B);
  let s = `<svg class="sat-line" viewBox="0 0 ${W} ${H}" role="img" aria-label="Monthly satisfaction">`;
  if (!compact) for (let v = lo; v <= 100; v += 10) {
    s += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  }
  s += `<line class="target" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/>`;
  if (!compact) s += `<text class="target-l" x="${W - R}" y="${y(t) - 5}" text-anchor="end">Target ${t}%</text>`;
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join('');
  if (points.length > 1) s += `<path class="fill" d="${d}L${x(points.length - 1)} ${H - B}L${x(0)} ${H - B}Z"/><path class="ln" d="${d}"/>`;
  const step = points.length > 1 ? (W - L - R) / (points.length - 1) : W;
  points.forEach((p, i) => {
    const tip = `${monthName(p.month)}: ${pct(p.value)}` + (p.n > 1 ? ` (average of ${p.n})` : '') + ` – ${SAT_LABEL[satLevel(p.value)]}`;
    s += `<g class="pt" data-tip="${esc(tip)}"><rect class="hit" x="${x(i) - step / 2}" y="0" width="${step}" height="${H}"/>
      <line class="guide" x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${H - B}"/><circle cx="${x(i)}" cy="${y(p.value)}" r="${compact ? 3 : 4.5}"/></g>`;
    if (!compact && (points.length <= 12 || i % 2 === points.length % 2)) s += `<text class="ax" x="${x(i)}" y="${H - 10}" text-anchor="middle">${monthShort(p.month)}</text>`;
  });
  const lp = points[points.length - 1];
  if (!compact) s += `<text class="last-l" x="${x(points.length - 1) - 8}" y="${y(lp.value) - 10}" text-anchor="end">${pct(lp.value)}</text>`;
  return s + '</svg>';
}

/* ============================== Dashboard ============================== */
const F = {
  dash: { q: '', status: '' }, areas: { q: '', loc: '', status: '', active: '' }, tx: { q: '', area: '', item: '', action: '', from: '', to: '' },
  hist: { item: '', action: '' }, photoTab: 'All', sat: { loc: '', month: '' },
  log: { tab: 'audit', q: '', user: '', type: '', from: '', to: '' }
};

function viewWelcome() {
  return `<div class="card welcome">
    <div class="kic">${ic('database')}</div>
    <h2>Welcome to the ${esc(setting('systemName'))}</h2>
    <p>${allAreas() ? 'The database is empty. Start by adding your first break area, bring over the data from the old browser version, or load demo data to try the system.'
      : 'No break areas are assigned to your account yet. Ask the system administrator to give you access to your break areas.'}</p>
    <div class="filters" style="justify-content:center">
      ${can('areas.create') && allAreas() ? `<a class="btn primary" href="#/areas/new">${ic('plus')}Add First Break Area</a>` : ''}
      ${can('data.import') ? `<label class="btn">${ic('upload')}Import Old Version Backup (JSON)<input type="file" accept=".json,application/json" data-act-change="importBackup" hidden></label>
      <button class="btn" data-act="loadDemo">${ic('database')}Load Sample Data</button>` : ''}
    </div>
    ${can('data.import') ? '<p class="hint">To move data from the old version: open the old index.html, go to Settings &rarr; Download Backup (JSON), then import that file here.</p>' : ''}
  </div>`;
}

function viewSatisfactionCard() {
  return `<div class="card mb">
    <div class="card-h">${ic('smile')}<h3>Break Area Satisfaction</h3><span class="hint">Monthly survey results from the departments using each area</span><span class="sp"></span>
      <div class="filters"><select data-f="sat.loc" data-res="sat"><option value="">All locations</option>${options(setting('locations'), F.sat.loc)}</select>
      ${can('export.excel') ? `<button class="btn sm" data-act="exportSurveys">${ic('download')}Export</button>` : ''}</div>
    </div>
    <div data-results="sat"></div>
  </div>`;
}

function viewDashboard() {
  const A = DB.areas;
  if (!A.length) return viewWelcome();
  const tot = id => A.reduce((s, a) => s + qty(a, id), 0);
  const kpis = [['building', 'Total Break Areas', A.length], ['chair', 'Total Chairs', tot('chairs')], ['table', 'Total Tables', tot('tables')], ['tv', 'TV Screens', tot('tv')], ['dispenser', 'Water Dispensers', tot('water')]];
  const statusData = STATUSES.map(s => ({ label: s, value: A.filter(a => a.status === s).length, color: STATUS_COLOR[s] }));
  const equip = DB.itemTypes.map(t => ({ label: t.name, value: tot(t.id), icon: t.icon }));
  const locs = [...new Set([...setting('locations'), ...A.map(a => a.location)])]
    .map(l => ({ label: l, value: A.filter(a => a.location === l).length })).filter(l => l.value).sort((x, y) => y.value - x.value);
  const recent = [...A].sort((x, y) => lastUpdate(y).localeCompare(lastUpdate(x))).slice(0, 9);
  const tx = DB.history.filter(h => h.action !== 'Created').sort(byDateDesc).slice(0, 6);

  return `
  <div class="kpis">${kpis.map(([i, l, v]) => `<div class="card kpi"><div class="kic">${ic(i)}</div><div><div class="lbl">${l}</div><div class="val">${v.toLocaleString()}</div></div></div>`).join('')}</div>

  <div class="row3">
    <div class="card"><div class="card-h"><h3>Break Areas by Status</h3></div>${donut(statusData, 'Break Areas')}</div>
    <div class="card"><div class="card-h"><h3>Furniture &amp; Equipment Overview</h3><span class="sp"></span>${can('equipment.view') ? '<a class="link" href="#/equipment">Details</a>' : ''}</div>${vbars(equip)}</div>
    <div class="card"><div class="card-h"><h3>Break Areas by Location</h3></div>${hbars(locs)}</div>
  </div>

  <div class="card mb">
    <div class="card-h"><h3>Recent Updates</h3><span class="sp"></span>${can('transactions.view') ? '<a class="link" href="#/transactions">View All</a>' : ''}</div>
    <div class="carousel">
      <button class="car-btn l" data-act="scrollTrack" data-dir="-1" aria-label="Previous">${ic('chevL')}</button>
      <div class="track" id="track">${recent.map(a => `
        <div class="upd" data-act="go" data-href="#/area/${a.id}">
          <div class="ph">${photoHTML(mainPhoto(a))}</div>
          <div class="meta"><div>${esc(a.name)}<small>Updated ${fmt(lastUpdate(a))}</small></div>${badge(a.status === 'Good' ? 'Updated' : a.status)}</div>
        </div>`).join('')}</div>
      <button class="car-btn r" data-act="scrollTrack" data-dir="1" aria-label="Next">${ic('chevR')}</button>
    </div>
  </div>

  <div class="row-2">
    <div class="card">
      <div class="card-h"><h3>Break Area Details</h3><span class="sp"></span>
        <div class="filters">
          <label class="search">${ic('search')}<input data-f="dash.q" data-res="dash" placeholder="Search break area..." value="${esc(F.dash.q)}"></label>
          <select data-f="dash.status" data-res="dash"><option value="">All statuses</option>${STATUSES.map(s => `<option ${F.dash.status === s ? 'selected' : ''}>${s}</option>`).join('')}</select>
        </div>
      </div>
      <div class="tbl-wrap scroll"><table class="tbl"><thead><tr><th>#</th><th>Break Area Name</th><th>Location</th><th class="num">Chairs</th><th class="num">Tables</th><th class="num">TV</th><th class="num">Water Dispenser</th><th>Status</th><th>Last Update</th></tr></thead>
      <tbody data-results="dash"></tbody></table></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Recent Transactions</h3><span class="sp"></span>${can('transactions.view') ? '<a class="link" href="#/transactions">View All</a>' : ''}</div>
      <ul class="tx-list">${tx.map(txRow).join('') || '<li class="muted">No transactions yet</li>'}</ul>
    </div>
  </div>

  ${can('surveys.view') ? `<div style="margin-top:14px">${viewSatisfactionCard()}</div>` : ''}`;
}
function txRow(h) {
  const [i, bg, fg] = TX_STYLE[h.action] || TX_STYLE['Condition Update'];
  const a = area(h.areaId);
  return `<li data-act="go" data-href="#/area/${h.areaId}"><span class="tx-ic" style="background:${bg};color:${fg}">${ic(i)}</span>
    <span class="t"><b>${esc(txTitle(h))}</b><small>${esc(a ? a.name : '')}</small></span><time>${fmt(h.date)}</time></li>`;
}

const RESULTS = {
  dash(el) {
    const q = F.dash.q.toLowerCase();
    const rows = DB.areas.filter(a => (!q || (a.name + ' ' + a.location + ' ' + a.responsible).toLowerCase().includes(q)) && (!F.dash.status || a.status === F.dash.status));
    el.innerHTML = rows.map((a, i) => `<tr class="click" data-act="go" data-href="#/area/${a.id}"><td>${i + 1}</td><td><b>${esc(a.name)}</b></td><td>${esc(a.location)}</td>
      <td class="num">${qty(a, 'chairs')}</td><td class="num">${qty(a, 'tables')}</td><td class="num">${qty(a, 'tv')}</td><td class="num">${qty(a, 'water')}</td>
      <td>${badge(a.status)}</td><td>${fmt(lastUpdate(a))}</td></tr>`).join('') || `<tr><td colspan="9" class="empty">No break areas match your search</td></tr>`;
  },
  sat(el) {
    const A = DB.areas.filter(a => !F.sat.loc || a.location === F.sat.loc);
    const byMonth = {};
    A.forEach(a => areaMonthly(a).forEach(m => (byMonth[m.month] = byMonth[m.month] || []).push(m.value)));
    const all = Object.keys(byMonth).sort();
    if (!all.length) {
      el.innerHTML = `<p class="empty">No survey results yet. Open a break area and use <b>Satisfaction Survey &rarr; Add Result</b> to enter the monthly percentage.</p>`;
      return;
    }
    const sel = byMonth[F.sat.month] ? F.sat.month : all[all.length - 1];
    const points = all.slice(-12).map(m => ({ month: m, value: avg(byMonth[m]), n: byMonth[m].length }));
    const cur = avg(byMonth[sel]), prevM = all[all.indexOf(sel) - 1], prev = prevM ? avg(byMonth[prevM]) : null;
    const rank = A.map(a => { const m = areaMonthly(a).find(x => x.month === sel); return m && { a, v: m.value }; }).filter(Boolean).sort((x, y) => y.v - x.v);
    const below = rank.filter(r => r.v < satTarget()).length;
    const diff = prev == null ? null : Math.round((cur - prev) * 10) / 10;
    const tiles = [
      ['smile', `Average – ${monthName(sel)}`, pct(cur), `<span class="sat-pill ${satLevel(cur)}">${SAT_LABEL[satLevel(cur)]}</span>`],
      ['trend', 'Change vs previous month', diff == null ? '-' : (diff > 0 ? '+' : '') + diff + ' pts', prevM ? `${monthName(prevM)}: ${pct(prev)}` : 'No earlier month'],
      ['building', 'Areas surveyed', `${rank.length} / ${A.length}`, A.length - rank.length ? `${A.length - rank.length} missing this month` : 'All areas surveyed'],
      ['alert', `Below target (${satTarget()}%)`, below, below ? 'Need follow-up' : 'All on target']
    ];
    el.innerHTML = `<div class="sat-tiles">${tiles.map(([i, l, v, sub]) => `<div class="sat-tile"><div class="kic">${ic(i)}</div><div><div class="lbl">${l}</div><div class="val">${v}</div><div class="hint">${sub}</div></div></div>`).join('')}</div>
      <div class="sat-charts">
        <div><div class="sub-h">Average satisfaction per month <span class="hint">(last ${points.length} month${points.length > 1 ? 's' : ''})</span></div>${satLine(points)}</div>
        <div><div class="sub-h">By break area
          <select data-f="sat.month" data-res="sat" class="sm">${[...all].reverse().map(m => `<option value="${m}" ${m === sel ? 'selected' : ''}>${monthName(m)}</option>`).join('')}</select></div>
          <div class="sat-rank">${rank.map(r => `<div class="sat-row click" data-act="go" data-href="#/area/${r.a.id}" data-tip="${esc(r.a.name)} – ${esc(monthName(sel))}: ${pct(r.v)} (${SAT_LABEL[satLevel(r.v)]})">
            <span class="n">${esc(r.a.name)}</span><div class="t"><div class="f ${satLevel(r.v)}" style="width:${r.v}%"></div><i class="tg" style="left:${satTarget()}%"></i></div><b>${pct(r.v)}</b></div>`).join('')}</div>
          <div class="sat-legend"><span><i class="good"></i>On target</span><span><i class="warn"></i>Below target</span><span><i class="bad"></i>Needs action (&lt; ${satTarget() - 15}%)</span><span><i class="tgt"></i>Target</span></div>
        </div>
      </div>`;
  },
  areas(el) {
    const rows = filteredAreas();
    el.innerHTML = rows.map(a => {
      const nd = daysFromToday(a.nextInspection);
      return `<tr class="click" data-act="go" data-href="#/area/${a.id}">
        <td><span class="thumb-s ph">${photoHTML(mainPhoto(a))}</span></td><td><b>${esc(a.name)}</b></td><td>${esc(a.location)}</td><td>${esc(a.building)} / ${esc(a.floor)}</td>
        <td class="num">${a.capacity}</td><td class="num">${qty(a, 'chairs')}</td><td class="num">${qty(a, 'tables')}</td><td class="num">${qty(a, 'tv')}</td><td class="num">${qty(a, 'water')}</td>
        <td>${esc(a.responsible)}</td><td>${badge(a.status)}</td><td class="num">${satBadge((latestSat(a) || {}).value)}</td><td class="${nd < 0 ? 'overdue' : ''}">${fmt(a.nextInspection)}</td>
        <td class="num">${openIssues(a).length || '-'}</td><td>${fmt(lastUpdate(a))}</td></tr>`;
    }).join('') || `<tr><td colspan="15" class="empty">No break areas match the filters</td></tr>`;
    const c = $('#areaCount'); if (c) c.textContent = rows.length + ' of ' + DB.areas.length;
  },
  tx(el) {
    const rows = filteredTx();
    el.innerHTML = rows.map(h => {
      const a = area(h.areaId);
      return `<tr><td>${fmt(h.date)}</td><td><a class="link" href="#/area/${h.areaId}">${esc(a ? a.name : h.areaId)}</a></td><td>${esc(histItem(h))}</td><td>${badge(h.action)}</td>
      <td class="num">${h.prev ?? '-'}</td><td class="num">${h.next ?? '-'}</td><td class="wrap">${esc(h.details)}</td><td>${esc(h.by)}</td></tr>`;
    }).join('') || `<tr><td colspan="8" class="empty">No transactions match the filters</td></tr>`;
    const c = $('#txCount'); if (c) c.textContent = rows.length + ' records';
  },
  hist(el) {
    const a = area(el.dataset.area);
    const rows = filteredHist(a);
    el.innerHTML = rows.map((h, i) => `<tr><td>${i + 1}</td><td>${fmt(h.date)}</td><td>${esc(histItem(h))}</td><td>${badge(h.action)}</td>
      <td class="num">${h.prev ?? '-'}</td><td class="num">${h.next ?? '-'}</td><td class="wrap">${esc(h.details)}</td><td>${esc(h.by)}</td></tr>`).join('')
      || `<tr><td colspan="8" class="empty">No history records</td></tr>`;
  }
};

/* ============================== Break areas list ============================== */
function filteredAreas() {
  const f = F.areas, q = f.q.toLowerCase();
  return DB.areas.filter(a =>
    (!q || [a.name, a.location, a.building, a.floor, a.responsible, a.description].join(' ').toLowerCase().includes(q)) &&
    (!f.loc || a.location === f.loc) && (!f.status || a.status === f.status) &&
    (!f.active || (f.active === 'Active') === (a.active !== false)));
}
function areaRows(list) {
  return list.map(a => [a.name, a.location, a.building, a.floor, a.startDate, a.size, a.capacity, a.responsible, a.status, a.active === false ? 'Inactive' : 'Active',
    ...DB.itemTypes.map(t => qty(a, t.id)), a.lastInspection, a.nextInspection, openIssues(a).length,
    (latestSat(a) || {}).month || '', latestSat(a) ? Math.round(latestSat(a).value * 10) / 10 : '', lastUpdate(a), areaURL(a.id)]);
}
const areaHead = () => ['Break Area', 'Location', 'Building', 'Floor', 'Start Date', 'Area Size (m2)', 'Capacity', 'Responsible', 'Status', 'Operational',
  ...DB.itemTypes.map(t => t.name), 'Last Inspection', 'Next Inspection', 'Open Issues', 'Last Survey Month', 'Last Satisfaction %', 'Last Update', 'Profile Link'];

function viewAreas() {
  const f = F.areas;
  const opt = (list, v) => list.map(x => `<option ${v === x ? 'selected' : ''}>${esc(x)}</option>`).join('');
  return `<div class="page-head"><h2>Break Areas</h2><span class="muted" id="areaCount"></span>
    <div class="actions">
      ${can('export.excel') ? `<button class="btn" data-act="exportAreas">${ic('download')}Export Excel</button>` : ''}
      ${can('report.labels') ? `<button class="btn" data-act="printLabelsFiltered">${ic('qr')}Print QR Labels</button>` : ''}
      ${can('areas.create') && allAreas() ? `<a class="btn primary" href="#/areas/new">${ic('plus')}Add New Break Area</a>` : ''}
    </div></div>
  <div class="card">
    <div class="card-h filters">
      <label class="search">${ic('search')}<input data-f="areas.q" data-res="areas" placeholder="Search name, building, person..." value="${esc(f.q)}"></label>
      <select data-f="areas.loc" data-res="areas"><option value="">All locations</option>${opt(setting('locations'), f.loc)}</select>
      <select data-f="areas.status" data-res="areas"><option value="">All statuses</option>${opt(STATUSES, f.status)}</select>
      <select data-f="areas.active" data-res="areas"><option value="">Active &amp; inactive</option>${opt(['Active', 'Inactive'], f.active)}</select>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Break Area</th><th>Location</th><th>Building / Floor</th><th class="num">Capacity</th><th class="num">Chairs</th><th class="num">Tables</th><th class="num">TV</th><th class="num">Water</th><th>Responsible</th><th>Status</th><th class="num">Satisfaction</th><th>Next Inspection</th><th class="num">Open Issues</th><th>Last Update</th></tr></thead>
    <tbody data-results="areas"></tbody></table></div>
  </div>`;
}

/* ============================== Area form ============================== */
function areaFields(a = {}) {
  const inp = (n, l, v, type = 'text', req = '') => `<label>${l}<input name="${n}" type="${type}" value="${esc(v ?? '')}" ${req} ${type === 'number' ? 'min="0"' : ''}></label>`;
  const sel = (n, l, list, v) => `<label>${l}<select name="${n}">${list.map(x => `<option ${x === v ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>`;
  return `<div class="form-grid">
    ${inp('name', 'Break Area Name / Number *', a.name, 'text', 'required')}
    ${sel('location', 'Location', setting('locations'), a.location)}
    ${inp('building', 'Building', a.building)}
    ${inp('floor', 'Floor', a.floor)}
    ${inp('startDate', 'Start Date', a.startDate || today(), 'date')}
    ${inp('size', 'Area Size (m²)', a.size, 'number')}
    ${inp('capacity', 'Capacity (persons)', a.capacity, 'number')}
    ${inp('responsible', 'Responsible Person', a.responsible ?? me())}
    ${sel('status', 'Current Status', STATUSES, a.status || 'Good')}
    ${sel('active', 'Operational', ['Active', 'Inactive'], a.active === false ? 'Inactive' : 'Active')}
    <label class="full">Description<textarea name="description">${esc(a.description || '')}</textarea></label>
  </div>`;
}
function applyAreaFields(a, d) {
  Object.assign(a, {
    name: d.name.trim(), location: d.location, building: d.building.trim(), floor: d.floor.trim(), startDate: d.startDate,
    size: +d.size || 0, capacity: +d.capacity || 0, responsible: d.responsible.trim(), status: d.status,
    active: d.active !== 'Inactive', description: d.description.trim()
  });
}
function viewAreaForm() {
  const n = DB.areas.length + 1;
  return `<div class="page-head"><a class="btn" href="#/areas">${ic('arrowLeft')}Back to Break Areas</a><h2>Add New Break Area</h2></div>
  <form id="newAreaForm" data-form="newArea">
    <div class="grid2 mb">
      <div class="card"><div class="card-h">${ic('building')}<h3>Break Area Master Data</h3></div>${areaFields({ name: 'Break Area ' + pad(n) })}</div>
      <div>
        <div class="card mb"><div class="card-h">${ic('sofa')}<h3>Initial Contents</h3><span class="sp"></span><span class="hint">Quantity & condition at setup</span></div>
          <div class="form-grid">${DB.itemTypes.map(t => `<div class="fld">${esc(t.name)}<div style="display:flex;gap:6px"><input style="width:90px" type="number" min="0" name="qty_${t.id}" value="0"><select style="flex:1" name="cond_${t.id}">${CONDITIONS.map(c => `<option>${c}</option>`).join('')}</select></div></div>`).join('')}</div>
        </div>
        <div class="card"><div class="card-h">${ic('camera')}<h3>Photos</h3></div>
          <label class="fld">Break area photos (optional)<input type="file" name="photos" accept="image/*" multiple></label>
          <p class="hint">Photos are resized automatically. You can add more photos and documents later.</p>
        </div>
      </div>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end"><a class="btn" href="#/areas">Cancel</a><button class="btn primary">${ic('check')}Create Break Area</button></div>
  </form>`;
}
async function submitNewArea(form) {
  const d = Object.fromEntries(new FormData(form));
  if (!d.name.trim()) return toast('Name is required', true);
  let n = DB.areas.length + 1, id;
  do { id = 'ba' + pad(n++); } while (area(id));
  const a = { id, inventory: [], photos: [], docs: [], issues: [], maintenance: [], inspections: [], surveys: [], lastInspection: '', nextInspection: addDays(d.startDate || today(), setting('inspectionDays')), inspectedBy: '' };
  applyAreaFields(a, d);
  DB.itemTypes.forEach(t => { const q = +d['qty_' + t.id] || 0; if (q > 0) a.inventory.push({ item: t.id, qty: q, condition: d['cond_' + t.id] }); });
  const btn = $('button.primary', form);
  btn.disabled = true;
  try {
    for (const f of form.photos.files) {
      if (!f.type.startsWith('image/')) continue;
      a.photos.push({ id: uid(), caption: f.name.replace(/\.[^.]+$/, ''), category: 'Current', date: today(), ...await uploadImage(f), main: !a.photos.length });
    }
  } catch (e) { btn.disabled = false; return toast('Photo upload failed: ' + e.message, true); }
  if (!a.photos.length) a.photos.push({ id: uid(), caption: 'Seating Area', variant: 'seating', seed: id + 'seating', category: 'Current', date: today(), main: true });
  DB.areas.push(a);
  const summary = a.inventory.map(i => `${i.qty} ${itemName(i.item)}`).join(', ');
  pushHistory({ areaId: id, date: a.startDate, item: 'Initial Setup', action: 'Created', prev: null, next: null, details: 'Break area created' + (summary ? ' with ' + summary : ''), by: me() });
  if (await save('Create break area – ' + a.name)) { toast(a.name + ' created'); location.hash = '#/area/' + id; }
  else btn.disabled = false;
}

/* ============================== Area detail ============================== */
function viewArea(a) {
  const mp = mainPhoto(a);
  const photos = a.photos.filter(p => F.photoTab === 'All' || p.category === F.photoTab);
  const oi = openIssues(a), closed = a.issues.length - oi.length;
  const nd = a.nextInspection ? daysFromToday(a.nextInspection) : null;
  const inspState = nd == null ? '' : nd < 0 ? `<span class="badge b-red">Overdue ${-nd}d</span>` : nd <= 7 ? `<span class="badge b-orange">In ${nd}d</span>` : '';
  const f = F.hist;
  const histItems = [...new Set(areaHistory(a.id).map(histItem))];
  const qa = [
    ['plus', '#16a34a', 'Add New Item', 'invModal', 'inventory.edit'], ['alert', '#dc2626', 'Report Issue', 'issueModal', 'issues.create'],
    ['calendar', '#f59e0b', 'Schedule Maintenance', 'maintModal', 'maintenance.create'], ['upload', '#1d4ed8', 'Upload Photo / Document', 'uploadModal', 'files.upload']
  ].filter(q => can(q[4]));
  const tasks = [...a.issues.map(i => ({ ...i, kind: 'Issue' })), ...a.maintenance.map(m => ({ ...m, kind: 'Maintenance', title: m.details }))].sort(byDateDesc);

  return `
  <div class="page-head">
    <a class="btn" href="#/areas">${ic('arrowLeft')}Back to Break Areas</a>
    <h2>${esc(a.name)}</h2>${badge(a.active === false ? 'Inactive' : 'Active')}
    <span class="loc">${ic('pin')}${esc(a.location)} Area</span>
    <div class="actions">
      ${can('areas.edit', 'areas.delete') ? `<button class="btn" data-act="editArea" data-id="${a.id}">${ic('edit')}Edit</button>` : ''}
      <button class="btn" data-act="toHistory">${ic('history')}View History</button>
      ${can('inventory.edit') ? `<button class="btn primary" data-act="invModal" data-id="${a.id}">${ic('plus')}Add New</button>` : ''}
    </div>
  </div>

  <div class="detail-top">
    <div class="card d-photo" data-act="viewPhoto" data-id="${a.id}" data-pid="${mp ? mp.id : ''}">
      <div class="ph">${photoHTML(mp)}</div>${mp ? `<span class="cap">${esc(mp.caption)}</span>` : ''}
    </div>
    <div class="card d-info">
      <div class="card-h"><h3>Basic Information</h3></div>
      <dl class="kv">
        <dt>Break Area Name</dt><dd>${esc(a.name)}</dd>
        <dt>Location</dt><dd>${esc(a.location)} Area</dd>
        <dt>Building / Floor</dt><dd>${esc(a.building)} – ${esc(a.floor)}</dd>
        <dt>Start Date</dt><dd>${fmt(a.startDate)}</dd>
        <dt>Area Size</dt><dd>${a.size || '-'} m²</dd>
        <dt>Capacity</dt><dd>${a.capacity || '-'} Persons</dd>
        <dt>Current Status</dt><dd>${badge(a.status, true)}</dd>
        <dt>Responsible Person</dt><dd>${esc(a.responsible || '-')}</dd>
        <dt>Description</dt><dd style="font-weight:500">${esc(a.description || '-')}</dd>
      </dl>
    </div>
    <div class="card d-qr">
      <div class="card-h" style="align-self:stretch"><h3>QR Code</h3></div>
      <div class="qr">${qrSVG(areaURL(a.id))}</div>
      <div class="code">${esc(a.id.toUpperCase())}</div>
      <button class="btn sm" data-act="qrModal" data-id="${a.id}">${ic('eye')}View / Print</button>
    </div>
    <div class="card d-qa">
      <div class="card-h"><h3>Quick Actions</h3></div>
      ${qa.map(([i, c, l, act]) => `<button class="qa-item" data-act="${act}" data-id="${a.id}"><span class="qa-ic" style="background:${c}">${ic(i)}</span>${l}</button>`).join('')
        || '<p class="muted">Your account can view this break area but not change it.</p>'}
    </div>
    <div class="card d-photos">
      <div class="card-h"><h3>Photos</h3><span class="muted">(${a.photos.length})</span><span class="sp"></span>
        <div class="tabs">${['All', ...PHOTO_CATEGORIES].map(t => `<button data-act="photoTab" data-tab="${t}" class="${F.photoTab === t ? 'on' : ''}">${t}</button>`).join('')}</div></div>
      <div class="thumbs">
        ${photos.map(p => `<div class="thumb" data-act="viewPhoto" data-id="${a.id}" data-pid="${p.id}"><div class="ph">${photoHTML(p)}</div><span>${esc(p.caption)}</span></div>`).join('')}
        ${can('files.upload') ? `<div class="thumb add" data-act="uploadModal" data-id="${a.id}"><div class="ph">${ic('plus')}</div><span>Add Photo</span></div>` : ''}
      </div>
    </div>
  </div>

  <div class="detail-mid">
    <div class="card">
      <div class="card-h"><h3>Inventory / Contents</h3><span class="sp"></span>${can('inventory.edit', 'inventory.delete') ? `<button class="btn sm" data-act="invModal" data-id="${a.id}">${ic('edit')}Update</button>` : ''}</div>
      <div class="inv">${a.inventory.map(e => `<div class="inv-tile" ${can('inventory.edit', 'inventory.delete') ? `data-act="invModal" data-id="${a.id}" data-item="${e.item}"` : 'style="cursor:default"'} title="${esc(e.note || '')}">
        ${itemIcon(e.item)}<div class="n">${esc(itemName(e.item))}</div><div class="q">${e.qty}</div>${badge(e.condition || 'Good')}</div>`).join('') || '<p class="muted">No items recorded yet.</p>'}</div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Inspection</h3><span class="sp"></span>${inspState}</div>
      <div class="insp-row">${ic('calCheck')}<div><small>Last Inspection</small><b>${fmt(a.lastInspection)}</b></div></div>
      <div class="insp-row">${ic('calendar')}<div><small>Next Inspection</small><b class="${nd != null && nd < 0 ? 'overdue' : ''}">${fmt(a.nextInspection)}</b></div></div>
      <div class="insp-row">${ic('user')}<div><small>Inspected By</small><b>${esc(a.inspectedBy || '-')}</b></div></div>
      ${can('inspections.create', 'inspections.delete') ? `<button class="btn sm" style="margin-top:8px;width:100%" data-act="inspModal" data-id="${a.id}">${ic('clipboard')}${can('inspections.create') ? 'Record Inspection' : 'Inspections'}</button>` : ''}
    </div>
    <div class="card">
      <div class="card-h"><h3>Open Issues</h3></div>
      <div class="issue-counts">
        <div style="background:var(--orange-l);color:#b45309"><b>${oi.length}</b>Open</div>
        <div style="background:var(--green-l);color:#15803d"><b>${closed}</b>Closed</div>
      </div>
      <ul class="issue-list">${oi.slice(0, 3).map(i => `<li data-act="issueView" data-id="${a.id}" data-iid="${i.id}">${badge(i.priority)}<span>${esc(i.title)}</span></li>`).join('')}</ul>
      ${can('issues.create') ? `<button class="link" data-act="issueModal" data-id="${a.id}">${ic('alert')} Report New Issue</button>` : ''}
    </div>
  </div>

  <div class="hist-row">
  ${can('surveys.view') ? viewSurveyBox(a) : ''}
  <div class="card" id="history">
    <div class="card-h"><h3>Update History</h3><span class="sp"></span>
      <div class="filters">
        <select data-f="hist.item" data-res="hist"><option value="">All items</option>${histItems.map(x => `<option ${f.item === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
        <select data-f="hist.action" data-res="hist"><option value="">All actions</option>${['Created', ...ACTIONS].map(x => `<option ${f.action === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
        ${can('export.excel') ? `<button class="btn sm" data-act="exportHist" data-id="${a.id}">${ic('download')}Export</button>` : ''}
        ${can('logs.view') ? `<button class="btn sm" data-act="areaLog" data-id="${a.id}" title="Every change made to this break area, by whom and when">${ic('activity')}Change Log</button>` : ''}
      </div>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>#</th><th>Date</th><th>Item</th><th>Action</th><th class="num">Previous Qty</th><th class="num">New Qty</th><th>Details</th><th>Updated By</th></tr></thead>
    <tbody data-results="hist" data-area="${a.id}"></tbody></table></div>
  </div>
  </div>

  <div class="grid2">
    <div class="card">
      <div class="card-h"><h3>Issues &amp; Maintenance</h3><span class="sp"></span>${can('maintenance.create') ? `<button class="btn sm" data-act="maintModal" data-id="${a.id}">${ic('calendar')}Schedule</button>` : ''}</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Status</th><th></th></tr></thead><tbody>
      ${tasks.map(t => `<tr><td>${fmt(t.date)}</td><td>${t.kind === 'Issue' ? badge(t.priority) : '<span class="badge b-purple">Maintenance</span>'}</td>
        <td class="wrap">${esc(t.title)}${t.item ? ` <span class="muted">· ${esc(itemShort(t.item))}</span>` : ''}</td><td>${badge(t.status)}</td>
        <td>${t.kind === 'Issue' ? `<button class="btn sm" data-act="issueView" data-id="${a.id}" data-iid="${t.id}">Follow up</button>`
          : `<span class="nowrap">${t.status !== 'Done' && can('maintenance.complete') ? `<button class="btn sm" data-act="maintDone" data-id="${a.id}" data-mid="${t.id}">Complete</button>` : ''}
            ${can('maintenance.delete') ? `<button class="icon-btn" title="Delete this maintenance" data-act="maintDelete" data-id="${a.id}" data-mid="${t.id}">${ic('trash')}</button>` : ''}</span>`}</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">No issues or maintenance recorded</td></tr>'}
      </tbody></table></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Documents &amp; Reports</h3><span class="sp"></span>${can('files.upload') ? `<button class="btn sm" data-act="uploadModal" data-id="${a.id}" data-cat="Document">${ic('upload')}Upload</button>` : ''}</div>
      <ul class="doc-list">${a.docs.map(d => `<li>${ic('file')}<div class="t"><b>${esc(d.name)}</b><small>${fmt(d.date)} · ${fileSize(d.size)}${d.caption ? ' · ' + esc(d.caption) : ''}</small></div>
        ${can('files.download') ? `<button class="icon-btn" title="Download" data-act="docDownload" data-id="${a.id}" data-did="${d.id}">${ic('download')}</button>` : ''}
        ${can('files.delete') ? `<button class="icon-btn" title="Delete" data-act="docDelete" data-id="${a.id}" data-did="${d.id}">${ic('trash')}</button>` : ''}</li>`).join('')
        || '<li class="muted">No documents uploaded yet (inspection reports, invoices, layouts...)</li>'}</ul>
    </div>
  </div>`;
}
function viewSurveyBox(a) {
  const monthly = areaMonthly(a);
  const last = monthly[monthly.length - 1], prev = monthly[monthly.length - 2];
  const diff = last && prev ? Math.round((last.value - prev.value) * 10) / 10 : null;
  const list = [...a.surveys].sort((x, y) => y.month.localeCompare(x.month) || (x.department || '').localeCompare(y.department || ''));
  return `<div class="card survey-box">
    <div class="card-h">${ic('smile')}<h3>Satisfaction Survey</h3><span class="sp"></span>
      ${can('surveys.create') ? `<button class="btn sm primary" data-act="surveyModal" data-id="${a.id}">${ic('plus')}Add Result</button>` : ''}</div>
    ${last ? `<div class="sv-sum">
        <div><small>Latest – ${esc(monthName(last.month))}</small><b>${pct(last.value)}</b>
          <span class="sat-pill ${satLevel(last.value)}">${SAT_LABEL[satLevel(last.value)]}</span></div>
        <div class="delta ${diff == null ? '' : diff >= 0 ? 'up' : 'down'}">${diff == null ? '' : (diff >= 0 ? '▲ +' : '▼ ') + diff + ' pts'}<small>${prev ? 'vs ' + esc(monthShort(prev.month)) : ''}</small></div>
      </div>
      ${monthly.length > 1 ? `<div class="sv-spark">${satLine(monthly.slice(-12), { h: 90, compact: true })}</div>` : ''}` : ''}
    <ul class="sv-list">${list.map(s => `<li>
        <div class="m"><b>${esc(monthName(s.month))}</b>${s.department ? `<small>${esc(s.department)}</small>` : ''}</div>
        <div class="t"><div class="f ${satLevel(+s.percentage)}" style="width:${+s.percentage}%"></div></div>
        <b class="p">${pct(+s.percentage)}</b>
        ${can('surveys.edit', 'surveys.delete') ? `<button class="icon-btn" title="Edit" data-act="surveyModal" data-id="${a.id}" data-sid="${s.id}">${ic('edit')}</button>` : '<span></span>'}
      </li>`).join('') || '<li class="empty">No survey results yet.<br>Add the monthly satisfaction percentage here.</li>'}</ul>
    <p class="hint">Target: ${satTarget()}%${can('settings.edit') ? ' (change in Settings)' : ''}</p>
  </div>`;
}
function surveyModal(a, sid) {
  const s = sid ? a.surveys.find(x => x.id === sid) : null;
  const depts = [...new Set(DB.areas.flatMap(x => x.surveys.map(y => y.department)).filter(Boolean))];
  const thisMonth = today().slice(0, 7);
  modal(`${s ? 'Edit' : 'Add'} Satisfaction Result – ${esc(a.name)}`, `<div class="form-grid">
    <label>Month *<input type="month" name="month" required value="${esc(s ? s.month : thisMonth)}" max="${thisMonth}"></label>
    <label>Satisfaction % *<input type="number" name="percentage" required min="0" max="100" step="0.1" value="${s ? s.percentage : ''}" placeholder="e.g. 85"></label>
    <label>Department <span class="hint">(optional)</span><input name="department" list="deptList" value="${esc(s ? s.department || '' : '')}" placeholder="e.g. Production – Line 2">
      <datalist id="deptList">${depts.map(d => `<option value="${esc(d)}">`).join('')}</datalist></label>
    <label>Respondents <span class="hint">(optional)</span><input type="number" name="respondents" min="0" value="${s && s.respondents != null ? s.respondents : ''}"></label>
    <label class="full">Notes<textarea name="notes" placeholder="Main comments from the survey...">${esc(s ? s.notes || '' : '')}</textarea></label>
    <p class="full hint">One result per month per department. If several departments share this area, add one line for each; the area's monthly value is their average.</p>
  </div>`, {
    submit: s ? 'Save Changes' : 'Add Result', allow: can(s ? 'surveys.edit' : 'surveys.create'),
    extra: s && can('surveys.delete') ? `<button type="button" class="btn danger" data-act="surveyDelete" data-id="${a.id}" data-sid="${s.id}">${ic('trash')}Delete</button>` : '',
    async onSubmit(d) {
      const p = +d.percentage;
      if (!/^\d{4}-\d{2}$/.test(d.month)) { toast('Choose the month', true); return false; }
      if (d.percentage === '' || !(p >= 0 && p <= 100)) { toast('Percentage must be between 0 and 100', true); return false; }
      const dept = d.department.trim();
      const dup = a.surveys.find(x => x !== s && x.month === d.month && (x.department || '').toLowerCase() === dept.toLowerCase());
      if (dup) { toast(`${monthName(d.month)}${dept ? ' / ' + dept : ''} already has a result (${pct(+dup.percentage)}). Edit that one instead.`, true, 5000); return false; }
      const row = { month: d.month, percentage: p, department: dept, respondents: d.respondents === '' ? null : +d.respondents, notes: d.notes.trim(), by: me() };
      if (s) Object.assign(s, row); else a.surveys.push({ id: uid(), ...row });
      if (!(await save(`${s ? 'Edit' : 'Add'} satisfaction ${monthName(d.month)} ${pct(p)} – ${a.name}`))) return false;
      toast('Satisfaction result saved');
    }
  });
}

function filteredHist(a) {
  return areaHistory(a.id).filter(h => (!F.hist.item || histItem(h) === F.hist.item) && (!F.hist.action || h.action === F.hist.action));
}

/* ============================== Modals ============================== */
/* allow: false shows the form read-only (the user may look but not change) */
function modal(title, body, { submit = 'Save', onSubmit, wide = false, extra = '', cls = '', locked = false, allow = true } = {}) {
  const m = $('#modal');
  if (!allow) onSubmit = undefined;
  track('open', 'dialog', title.replace(/<[^>]+>/g, ''));
  m.dataset.locked = locked ? '1' : '';
  m.innerHTML = `<div class="modal-back" ${locked ? '' : 'data-act="closeModal"'}></div>
    <form class="modal ${wide ? 'wide' : ''} ${cls}" novalidate>
      <div class="modal-h"><h3>${title}</h3>${locked ? '' : `<button type="button" class="icon-btn" data-act="closeModal" aria-label="Close">${ic('x')}</button>`}</div>
      <div class="modal-b">${body}</div>
      <div class="modal-f">${extra}<span class="sp"></span>${locked ? '' : `<button type="button" class="btn" data-act="closeModal">${onSubmit ? 'Cancel' : 'Close'}</button>`}${onSubmit ? `<button class="btn primary">${submit}</button>` : ''}</div>
    </form>`;
  m.classList.add('open');
  const form = $('form', m);
  form.onsubmit = async e => {
    e.preventDefault();
    if (!onSubmit) return;
    const bad = $$('[required]', form).find(el => !String(el.value).trim());
    if (bad) { bad.focus(); return toast('Please fill the required fields', true); }
    const btn = $('.modal-f .primary', form); btn.disabled = true;
    try {
      const ok = await onSubmit(Object.fromEntries(new FormData(form)), form);
      if (ok !== false) { closeModal(); rerender(); }
    } catch (err) {
      track('js-error', 'dialog submit', title, err.stack || err.message);
      toast('Error: ' + err.message, true, 6000);
    } finally { btn.disabled = false; }
  };
  if (!allow) $$('.modal-b input, .modal-b select, .modal-b textarea', form).forEach(el => (el.disabled = true));
  const first = $('input:not([type=hidden]),select,textarea', form);
  if (first && matchMedia('(min-width: 821px)').matches) first.focus();
  return form;
}
function closeModal() { const m = $('#modal'); m.classList.remove('open'); m.innerHTML = ''; m.dataset.locked = ''; }

const options = (list, v) => list.map(x => Array.isArray(x)
  ? `<option value="${esc(x[0])}" ${x[0] === v ? 'selected' : ''}>${esc(x[1])}</option>`
  : `<option ${x === v ? 'selected' : ''}>${esc(x)}</option>`).join('');
const itemOptions = v => options(DB.itemTypes.map(t => [t.id, t.name]), v);

function invModal(a, presetItem) {
  const item = presetItem || 'chairs';
  const e = invEntry(a, item);
  const body = `<div class="form-grid">
    <label>Item<select name="item" required>${itemOptions(item)}</select></label>
    <label>Action<select name="action">${options(ACTIONS, 'Added')}</select></label>
    <label data-show="qty">Quantity<input name="qty" type="number" min="1" value="1"></label>
    <label>Current Quantity<input name="cur" disabled value="${e ? e.qty : 0}"></label>
    <label>Condition after update<select name="condition">${options(CONDITIONS, e ? e.condition : 'Good')}</select></label>
    <label>Date<input name="date" type="date" value="${today()}" required></label>
    <label class="full hidden" data-show="transfer">Transfer to<select name="target">${options(DB.areas.filter(x => x.id !== a.id).map(x => [x.id, x.name + ' – ' + x.location]))}</select></label>
    <label>Updated By<input name="by" value="${esc(me())}" required></label>
    <label class="full">Details / Remarks<textarea name="details" placeholder="e.g. Added 10 new chairs from supplier X"></textarea></label>
  </div>`;
  const form = modal(`Update Inventory – ${esc(a.name)}`, body, {
    submit: 'Save Update', allow: can('inventory.edit'),
    extra: can('inventory.delete') ? `<button type="button" class="btn danger" data-act="invDelete" data-id="${a.id}" title="Remove the selected item from this break area's inventory">${ic('trash')}Delete Item</button>` : '',
    async onSubmit(d) {
      const prev = qty(a, d.item), n = Math.floor(+d.qty || 0);
      const moves = ['Added', 'Removed', 'Transferred'].includes(d.action);
      if (moves && n <= 0) { toast('Enter a quantity greater than 0', true); return false; }
      if ((d.action === 'Removed' || d.action === 'Transferred') && n > prev) { toast(`Only ${prev} ${itemName(d.item)} available`, true); return false; }
      const next = d.action === 'Added' ? prev + n : d.action === 'Removed' || d.action === 'Transferred' ? prev - n : prev;
      let details = d.details.trim();
      if (d.action === 'Transferred') {
        const t = area(d.target);
        if (!t) { toast('Choose a destination break area', true); return false; }
        const tp = qty(t, d.item);
        setQty(t, d.item, tp + n, d.condition);
        pushHistory({ areaId: t.id, date: d.date, item: d.item, action: 'Transferred', prev: tp, next: tp + n, details: `Received ${n} from ${a.name}` + (details ? '. ' + details : ''), by: d.by });
        details = `Transferred ${n} to ${t.name}` + (details ? '. ' + details : '');
      }
      setQty(a, d.item, next, d.condition);
      pushHistory({ areaId: a.id, date: d.date, item: d.item, action: d.action, prev, next, details: details || txTitle({ action: d.action, item: d.item, prev, next }), by: d.by });
      if (!(await save(`${d.action} ${itemName(d.item)} – ${a.name}`))) return false;
      toast('Inventory updated');
    }
  });
  const sync = () => {
    const act = form.elements.action.value;
    $('[data-show=qty]', form).classList.toggle('hidden', !['Added', 'Removed', 'Transferred'].includes(act));
    $('[data-show=transfer]', form).classList.toggle('hidden', act !== 'Transferred');
    const en = invEntry(a, form.item.value);
    form.cur.value = en ? en.qty : 0;
  };
  form.addEventListener('change', ev => {
    if (ev.target.name === 'item') { const en = invEntry(a, form.item.value); form.condition.value = en ? en.condition : 'Good'; }
    sync();
  });
  if (!can('inventory.edit')) form.item.disabled = false; // still lets a user who may only delete pick the item
  sync();
}

function issueModal(a) {
  modal(`Report Issue – ${esc(a.name)}`, `<div class="form-grid">
    <label class="full">Issue Title<input name="title" required placeholder="e.g. Broken chair, water leak..."></label>
    <label>Related Item<select name="item"><option value="">General / Area</option>${itemOptions('')}</select></label>
    <label>Priority<select name="priority">${options(PRIORITIES, 'Medium')}</select></label>
    <label>Date<input type="date" name="date" value="${today()}"></label>
    <label>Reported By<input name="by" value="${esc(me())}" required></label>
    <label class="full">Details<textarea name="details"></textarea></label>
    <label class="full check"><input type="checkbox" name="flag" ${a.status === 'Good' ? 'checked' : ''}> Set break area status to "Need Maintenance"</label>
  </div>`, {
    submit: 'Report Issue',
    async onSubmit(d) {
      a.issues.push({ id: uid(), date: d.date, title: d.title.trim(), item: d.item, priority: d.priority, status: 'Open', reportedBy: d.by, details: d.details, log: [] });
      if (d.flag) a.status = 'Need Maintenance';
      if (!(await save(`Report issue "${d.title.trim()}" – ${a.name}`))) return false;
      toast('Issue reported');
    }
  });
}

function issueView(a, iid) {
  const i = a.issues.find(x => x.id === iid);
  if (!i) return;
  modal(`Issue – ${esc(i.title)}`, `
    <dl class="kv mb"><dt>Break Area</dt><dd>${esc(a.name)}</dd><dt>Related Item</dt><dd>${i.item ? esc(itemName(i.item)) : 'General'}</dd>
      <dt>Priority</dt><dd>${badge(i.priority)}</dd><dt>Status</dt><dd>${badge(i.status)}</dd><dt>Reported</dt><dd>${fmt(i.date)} by ${esc(i.reportedBy)}</dd>
      ${i.closedDate ? `<dt>Closed</dt><dd>${fmt(i.closedDate)}</dd>` : ''}<dt>Details</dt><dd style="font-weight:500">${esc(i.details || '-')}</dd></dl>
    <b>Follow-up log</b>
    <ul class="log">${(i.log || []).map(l => `<li><small>${fmt(l.date)} · ${esc(l.by)}</small>${esc(l.text)}</li>`).join('') || '<li class="muted">No follow-up yet</li>'}</ul>
    <div class="form-grid" style="margin-top:12px">
      <label>Update Status<select name="status">${options(['Open', 'In Progress', 'Closed'], i.status)}</select></label>
      <label>Date<input type="date" name="date" value="${today()}"></label>
      <label class="full">Follow-up Note<textarea name="text" placeholder="Action taken, technician assigned, parts ordered..."></textarea></label>
    </div>`, {
    submit: 'Save Follow-up', wide: true, allow: can('issues.followup'),
    extra: can('issues.delete') ? `<button type="button" class="btn danger" data-act="issueDelete" data-id="${a.id}" data-iid="${i.id}">${ic('trash')}Delete</button>` : '',
    async onSubmit(d) {
      if (!d.text.trim() && d.status === i.status) { toast('Add a note or change the status', true); return false; }
      i.log = i.log || [];
      i.log.push({ id: uid(), date: d.date, by: me(), text: (d.status !== i.status ? `Status changed to ${d.status}. ` : '') + d.text.trim() });
      i.status = d.status;
      i.closedDate = d.status === 'Closed' ? d.date : '';
      if (!(await save(`Issue follow-up "${i.title}" – ${a.name}`))) return false;
      toast('Issue updated');
    }
  });
}

function maintModal(a) {
  modal(`Schedule Maintenance – ${esc(a.name)}`, `<div class="form-grid">
    <label>Item<select name="item"><option value="">General / Area</option>${itemOptions('')}</select></label>
    <label>Planned Date<input type="date" name="date" value="${addDays(today(), 7)}" required></label>
    <label>Assigned To<input name="assignedTo" value="Maintenance Team" required></label>
    <label>Set status<select name="status">${options(['Keep current status', 'Under Update', 'Need Maintenance'], 'Keep current status')}</select></label>
    <label class="full">Work Description<textarea name="details" required placeholder="e.g. Replace damaged chair cushions"></textarea></label>
  </div>`, {
    submit: 'Schedule',
    async onSubmit(d) {
      a.maintenance.push({ id: uid(), date: d.date, item: d.item, assignedTo: d.assignedTo, details: d.details.trim(), status: 'Scheduled' });
      if (d.status !== 'Keep current status') a.status = d.status;
      if (!(await save(`Schedule maintenance – ${a.name}`))) return false;
      toast('Maintenance scheduled');
    }
  });
}
function maintDone(a, mid) {
  const m = a.maintenance.find(x => x.id === mid);
  if (!m) return;
  modal('Complete Maintenance', `<p><b>${esc(m.details)}</b><br><span class="muted">${m.item ? esc(itemName(m.item)) + ' · ' : ''}${esc(m.assignedTo)}</span></p>
    <div class="form-grid"><label>Completion Date<input type="date" name="date" value="${today()}"></label>
    <label>Area status after work<select name="status">${options(STATUSES, 'Good')}</select></label>
    <label class="full">Notes<textarea name="notes"></textarea></label></div>`, {
    submit: 'Mark as Done',
    async onSubmit(d) {
      m.status = 'Done'; m.doneDate = d.date; m.notes = d.notes;
      a.status = d.status;
      const q = m.item ? qty(a, m.item) : null;
      pushHistory({ areaId: a.id, date: d.date, item: m.item || 'area', action: 'Maintenance', prev: q, next: q, details: m.details + (d.notes ? '. ' + d.notes : ''), by: m.assignedTo });
      if (!(await save(`Complete maintenance – ${a.name}`))) return false;
      toast('Maintenance completed');
    }
  });
}

function inspModal(a) {
  const days = setting('inspectionDays');
  const form = modal(`Record Inspection – ${esc(a.name)}`, `<div class="form-grid">
    <label>Inspection Date<input type="date" name="date" value="${today()}" required></label>
    <label>Inspected By<input name="by" value="${esc(a.inspectedBy || 'Facility Team')}" required></label>
    <label>Result<select name="result">${options(['Pass', 'Issues Found'], 'Pass')}</select></label>
    <label>Next Inspection<input type="date" name="next" value="${addDays(today(), days)}"></label>
    <label class="full">Notes<textarea name="notes"></textarea></label>
  </div>
  ${a.inspections.length ? `<b>Previous inspections</b><table class="tbl" style="margin-top:6px"><thead><tr><th>Date</th><th>By</th><th>Result</th><th>Notes</th><th></th></tr></thead><tbody>
    ${[...a.inspections].sort(byDateDesc).map(i => `<tr><td>${fmt(i.date)}</td><td>${esc(i.by)}</td><td>${badge(i.result)}</td><td class="wrap">${esc(i.notes || '')}</td>
      <td>${can('inspections.delete') ? `<button type="button" class="icon-btn" title="Delete this inspection" data-act="inspDelete" data-id="${a.id}" data-iid="${i.id}">${ic('trash')}</button>` : ''}</td></tr>`).join('')}</tbody></table>` : ''}`, {
    submit: 'Save Inspection', wide: true, allow: can('inspections.create'),
    async onSubmit(d) {
      a.inspections.push({ id: uid(), date: d.date, by: d.by, result: d.result, notes: d.notes });
      if (!a.lastInspection || d.date >= a.lastInspection) { a.lastInspection = d.date; a.inspectedBy = d.by; a.nextInspection = d.next; }
      if (!(await save(`Record inspection – ${a.name}`))) return false;
      toast('Inspection recorded');
    }
  });
  form.date.addEventListener('change', () => { form.next.value = addDays(form.date.value, days); });
}

/* Scales an image down (never up). Returns a JPEG data URL, or a Blob when asBlob is true. */
function resizeImage(file, max = 1280, asBlob = false) {
  return new Promise((res, rej) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      if (asBlob) c.toBlob(b => (b ? res(b) : rej(new Error('bad image'))), 'image/jpeg', .82);
      else res(c.toDataURL('image/jpeg', .78));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error('bad image')); };
    img.src = url;
  });
}

function uploadModal(a, cat = 'Current') {
  modal(`Upload Photo / Document – ${esc(a.name)}`, `<div class="form-grid">
    <label class="full">Files<input type="file" name="files" multiple required accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.zip"></label>
    <label>Category<select name="category">${options([...PHOTO_CATEGORIES.map(c => [c, c + ' Photo']), ['Document', 'Document / Report']], cat)}</select></label>
    <label>Caption / Title<input name="caption" placeholder="e.g. Seating area after renovation"></label>
    <p class="full hint">Photos are stored in their original full quality on the server. Files up to 50 MB each.</p>
  </div>`, {
    submit: 'Upload',
    async onSubmit(d, form) {
      const files = [...form.files.files];
      if (!files.length) { toast('Choose at least one file', true); return false; }
      let added = 0;
      for (const f of files) {
        const isImg = f.type.startsWith('image/');
        const caption = d.caption.trim() || f.name.replace(/\.[^.]+$/, '');
        try {
          if (isImg && d.category !== 'Document') {
            a.photos.push({ id: uid(), caption, category: d.category, date: today(), ...await uploadImage(f) });
          } else {
            a.docs.push({ id: uid(), name: f.name, caption: d.caption.trim(), size: f.size, type: f.type, date: today(), src: await uploadFile(f) });
          }
          added++;
        } catch (e) { toast(`${f.name}: ${e.message}`, true, 6000); }
      }
      if (!added) return false;
      if (d.category === 'Before' || d.category === 'After') F.photoTab = d.category;
      if (!(await save(`Upload ${added} file(s) – ${a.name}`))) return false;
      toast(added + ' file(s) uploaded');
    }
  });
}

function viewPhoto(a, pid) {
  const p = a.photos.find(x => x.id === pid);
  if (!p) return can('files.upload') ? uploadModal(a) : undefined;
  const i = a.photos.indexOf(p), prev = a.photos[i - 1], next = a.photos[i + 1];
  const nav = (x, dir) => x ? `<button type="button" class="lb-nav ${dir}" data-act="viewPhoto" data-id="${a.id}" data-pid="${x.id}" aria-label="${dir === 'l' ? 'Previous' : 'Next'} photo">${ic(dir === 'l' ? 'chevL' : 'chevR')}</button>` : '';
  modal(esc(p.caption), `<div class="viewer">
      <div class="ph">${photoHTML(p, true)}</div>${nav(prev, 'l')}${nav(next, 'r')}
    </div>
    <p class="muted" style="margin:10px 0 0">${badge(p.category)} &nbsp;Uploaded ${fmt(p.date)} · Photo ${i + 1} of ${a.photos.length}${p.main ? ' · <b>Main photo</b>' : ''}${p.src ? '' : ' · Placeholder image – upload a real photo to replace it'}</p>`, {
    cls: 'lightbox',
    extra: `${can('files.delete') ? `<button type="button" class="btn danger" data-act="photoDelete" data-id="${a.id}" data-pid="${p.id}">${ic('trash')}Delete</button>` : ''}
      ${p.main || !can('files.upload') ? '' : `<button type="button" class="btn" data-act="photoMain" data-id="${a.id}" data-pid="${p.id}">${ic('star')}Set as Main Photo</button>`}
      ${p.src ? `<a class="btn" href="${esc(p.src)}" target="_blank" rel="noopener">${ic('expand')}Open Original</a>` : ''}`
  });
}

function qrModal(a) {
  const url = areaURL(a.id);
  modal(`QR Code – ${esc(a.name)}`, `<div style="text-align:center">
    <div style="max-width:260px;margin:0 auto">${qrSVG(url)}</div>
    <p style="word-break:break-all" class="muted">${esc(url)}</p>
    <p class="hint">Scanning opens this break area profile (contents, status, latest updates and history).
    Phones must be on the same company network as the server PC.</p></div>`, {
    extra: `<button type="button" class="btn" data-act="copyLink" data-url="${esc(url)}">${ic('copy')}Copy Link</button>
      ${can('report.labels') ? `<button type="button" class="btn primary" data-act="printLabel" data-id="${a.id}">${ic('printer')}Print Label</button>` : ''}`
  });
}

function editArea(a) {
  modal(`Edit – ${esc(a.name)}`, areaFields(a), {
    submit: 'Save Changes', wide: true, allow: can('areas.edit'),
    extra: can('areas.delete') ? `<button type="button" class="btn danger" data-act="deleteArea" data-id="${a.id}">${ic('trash')}Delete Break Area</button>` : '',
    async onSubmit(d) {
      const before = { status: a.status, responsible: a.responsible };
      applyAreaFields(a, d);
      const changes = [];
      if (before.status !== a.status) changes.push(`Status: ${before.status} → ${a.status}`);
      if (before.responsible !== a.responsible) changes.push(`Responsible: ${before.responsible} → ${a.responsible}`);
      if (changes.length) pushHistory({ areaId: a.id, date: today(), item: 'area', action: 'Condition Update', prev: null, next: null, details: changes.join('; '), by: me() });
      if (!(await save(`Edit break area – ${a.name}`))) return false;
      toast('Break area updated');
    }
  });
}

/* ============================== Equipment ============================== */
function viewEquipment() {
  const A = DB.areas;
  return `<div class="page-head"><h2>Furniture &amp; Equipment</h2>
    <div class="actions">${can('export.excel') ? `<button class="btn" data-act="exportEquip">${ic('download')}Export Excel</button>` : ''}${can('itemtypes.manage') ? `<button class="btn primary" data-act="itemTypeModal">${ic('plus')}Add Item Type</button>` : ''}</div></div>
  <div class="kpis">${DB.itemTypes.map(t => {
    const total = A.reduce((s, a) => s + qty(a, t.id), 0);
    const bad = A.reduce((s, a) => { const e = invEntry(a, t.id); return s + (e && e.qty && e.condition !== 'Good' ? 1 : 0); }, 0);
    return `<div class="card kpi"><div class="kic ${bad ? 'orange' : ''}">${ic(t.icon)}</div><div><div class="lbl">${esc(t.name)}</div><div class="val">${total}</div>
      <div class="hint">${A.filter(a => qty(a, t.id)).length} areas${bad ? ` · <span style="color:#b45309">${bad} need attention</span>` : ''}</div></div></div>`;
  }).join('')}</div>
  <div class="card mb"><div class="card-h"><h3>Inventory by Break Area</h3><span class="sp"></span><span class="hint">Click a row to open the break area</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Break Area</th><th>Location</th>${DB.itemTypes.map(t => `<th class="num">${esc(t.name)}</th>`).join('')}<th class="num">Total Items</th></tr></thead>
    <tbody>${A.map(a => `<tr class="click" data-act="go" data-href="#/area/${a.id}"><td><b>${esc(a.name)}</b></td><td>${esc(a.location)}</td>
      ${DB.itemTypes.map(t => { const e = invEntry(a, t.id); return `<td class="num">${e && e.qty ? (e.condition !== 'Good' ? `<span class="badge ${STATUS_CLS[e.condition]}" title="${e.condition}">${e.qty}</span>` : e.qty) : '-'}</td>`; }).join('')}
      <td class="num"><b>${a.inventory.reduce((s, e) => s + e.qty, 0)}</b></td></tr>`).join('')}</tbody>
    <tfoot><tr><td>Total</td><td></td>${DB.itemTypes.map(t => `<td class="num">${A.reduce((s, a) => s + qty(a, t.id), 0)}</td>`).join('')}<td class="num">${A.reduce((s, a) => s + a.inventory.reduce((x, e) => x + e.qty, 0), 0)}</td></tr></tfoot></table></div>
    <p class="hint">Highlighted numbers mean the item condition is not "Good".</p></div>
  <div class="card"><div class="card-h"><h3>Item Types</h3></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Name</th><th>Singular</th><th>Code</th><th></th></tr></thead><tbody>
    ${DB.itemTypes.map(t => `<tr><td>${ic(t.icon)}</td><td><b>${esc(t.name)}</b></td><td>${esc(t.short || '')}</td><td class="muted">${esc(t.id)}</td>
      <td>${can('itemtypes.manage') ? `<button class="btn sm" data-act="itemTypeModal" data-tid="${t.id}">${ic('edit')}Edit</button>` : ''}</td></tr>`).join('')}</tbody></table></div></div>`;
}
function itemTypeModal(tid) {
  const t = tid ? itemType(tid) : null;
  modal(t ? 'Edit Item Type' : 'Add Item Type', `<div class="form-grid">
    <label>Name (plural)<input name="name" required value="${esc(t ? t.name : '')}" placeholder="e.g. Microwaves"></label>
    <label>Singular<input name="short" value="${esc(t ? t.short : '')}" placeholder="e.g. Microwave"></label>
    <label class="full">Icon<select name="icon">${options(ITEM_ICONS, t ? t.icon : 'box')}</select></label></div>`, {
    submit: t ? 'Save' : 'Add',
    extra: t ? `<button type="button" class="btn danger" data-act="itemTypeDelete" data-tid="${t.id}">${ic('trash')}Delete Item Type</button>` : '',
    async onSubmit(d) {
      if (t) Object.assign(t, { name: d.name.trim(), short: d.short.trim() || d.name.trim(), icon: d.icon });
      else {
        let id = d.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || uid();
        while (itemType(id)) id += '_';
        DB.itemTypes.push({ id, name: d.name.trim(), short: d.short.trim() || d.name.trim(), icon: d.icon });
      }
      if (!(await save(`${t ? 'Edit' : 'Add'} item type – ${d.name.trim()}`))) return false;
      toast('Item type saved');
    }
  });
}

/* ============================== Transactions ============================== */
function filteredTx() {
  const f = F.tx, q = f.q.toLowerCase();
  return DB.history.filter(h => {
    const a = area(h.areaId);
    return (!q || [a ? a.name : '', h.details, h.by, itemName(h.item), h.action].join(' ').toLowerCase().includes(q)) &&
      (!f.area || h.areaId === f.area) && (!f.item || h.item === f.item) && (!f.action || h.action === f.action) &&
      (!f.from || h.date >= f.from) && (!f.to || h.date <= f.to);
  }).sort(byDateDesc);
}
const txExportRows = list => list.map(h => [h.date, (area(h.areaId) || {}).name, histItem(h), h.action, h.prev ?? '', h.next ?? '', h.details, h.by]);
const TX_HEAD = ['Date', 'Break Area', 'Item', 'Action', 'Previous Qty', 'New Qty', 'Details / Remarks', 'Updated By'];

function viewTransactions() {
  const f = F.tx;
  return `<div class="page-head"><h2>Transactions</h2><span class="muted" id="txCount"></span>
    <div class="actions">${can('print') ? `<button class="btn" data-act="printTx">${ic('printer')}Print</button>` : ''}${can('export.excel') ? `<button class="btn" data-act="exportTx">${ic('download')}Export Excel</button>` : ''}</div></div>
  <div class="card">
    <div class="card-h filters">
      <label class="search">${ic('search')}<input data-f="tx.q" data-res="tx" placeholder="Search details, person..." value="${esc(f.q)}"></label>
      <select data-f="tx.area" data-res="tx"><option value="">All break areas</option>${options(DB.areas.map(a => [a.id, a.name]), f.area)}</select>
      <select data-f="tx.item" data-res="tx"><option value="">All items</option>${itemOptions(f.item)}</select>
      <select data-f="tx.action" data-res="tx"><option value="">All actions</option>${options(['Created', ...ACTIONS], f.action)}</select>
      <label class="fld" style="flex-direction:row;align-items:center">From<input type="date" data-f="tx.from" data-res="tx" value="${f.from}"></label>
      <label class="fld" style="flex-direction:row;align-items:center">To<input type="date" data-f="tx.to" data-res="tx" value="${f.to}"></label>
      <button class="btn sm" data-act="clearTx">Clear</button>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr>${TX_HEAD.map((h, i) => `<th class="${i === 4 || i === 5 ? 'num' : ''}">${h}</th>`).join('')}</tr></thead><tbody data-results="tx"></tbody></table></div>
  </div>`;
}

/* ============================== Maintenance ============================== */
function allIssues() { return DB.areas.flatMap(a => a.issues.map(i => ({ ...i, a }))); }
function inspStatus(a) { const d = daysFromToday(a.nextInspection || today()); return d < 0 ? 'Overdue' : d <= 7 ? 'Due Soon' : 'OK'; }

function viewMaintenance() {
  const iss = allIssues();
  const open = iss.filter(i => i.status !== 'Closed').sort((x, y) => PRIORITIES.indexOf(y.priority) - PRIORITIES.indexOf(x.priority) || x.date.localeCompare(y.date));
  const month = today().slice(0, 7);
  const maint = DB.areas.flatMap(a => a.maintenance.filter(m => m.status !== 'Done').map(m => ({ ...m, a }))).sort((x, y) => x.date.localeCompare(y.date));
  const insp = [...DB.areas].sort((x, y) => (x.nextInspection || '').localeCompare(y.nextInspection || ''));
  const k = [
    ['alert', 'Open Issues', iss.filter(i => i.status === 'Open').length, 'orange'],
    ['wrench', 'In Progress', iss.filter(i => i.status === 'In Progress').length, ''],
    ['checkCircle', 'Closed This Month', iss.filter(i => i.status === 'Closed' && (i.closedDate || '').startsWith(month)).length, 'green'],
    ['calendar', 'Scheduled Maintenance', maint.length, 'purple'],
    ['clipboard', 'Inspections Overdue', DB.areas.filter(a => inspStatus(a) === 'Overdue').length, 'red']
  ];
  return `<div class="page-head"><h2>Inspection &amp; Maintenance</h2>
    <div class="actions">${can('export.excel') ? `<button class="btn" data-act="exportIssues">${ic('download')}Export Issues</button>` : ''}</div></div>
  <div class="kpis">${k.map(([i, l, v, c]) => `<div class="card kpi"><div class="kic ${c}">${ic(i)}</div><div><div class="lbl">${l}</div><div class="val">${v}</div></div></div>`).join('')}</div>
  <div class="card mb"><div class="card-h"><h3>Open Issues</h3><span class="muted">(${open.length})</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Reported</th><th>Break Area</th><th>Issue</th><th>Item</th><th>Priority</th><th>Status</th><th class="num">Age (days)</th><th>Reported By</th><th></th></tr></thead><tbody>
    ${open.map(i => `<tr><td>${fmt(i.date)}</td><td><a class="link" href="#/area/${i.a.id}">${esc(i.a.name)}</a></td><td class="wrap">${esc(i.title)}</td><td>${i.item ? esc(itemShort(i.item)) : 'General'}</td>
      <td>${badge(i.priority)}</td><td>${badge(i.status)}</td><td class="num">${-daysFromToday(i.date)}</td><td>${esc(i.reportedBy)}</td>
      <td><button class="btn sm" data-act="issueView" data-id="${i.a.id}" data-iid="${i.id}">Follow up</button></td></tr>`).join('') || '<tr><td colspan="9" class="empty">No open issues 🎉</td></tr>'}
    </tbody></table></div></div>
  <div class="grid2">
    <div class="card"><div class="card-h"><h3>Scheduled Maintenance</h3></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Planned</th><th>Break Area</th><th>Work</th><th>Assigned To</th><th></th></tr></thead><tbody>
      ${maint.map(m => `<tr><td class="${daysFromToday(m.date) < 0 ? 'overdue' : ''}">${fmt(m.date)}</td><td><a class="link" href="#/area/${m.a.id}">${esc(m.a.name)}</a></td><td class="wrap">${esc(m.details)}</td><td>${esc(m.assignedTo)}</td>
        <td class="nowrap">${can('maintenance.complete') ? `<button class="btn sm" data-act="maintDone" data-id="${m.a.id}" data-mid="${m.id}">Complete</button>` : ''}
          ${can('maintenance.delete') ? `<button class="icon-btn" title="Delete this maintenance" data-act="maintDelete" data-id="${m.a.id}" data-mid="${m.id}">${ic('trash')}</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">Nothing scheduled</td></tr>'}
      </tbody></table></div></div>
    <div class="card"><div class="card-h"><h3>Inspection Schedule</h3><span class="sp"></span><span class="hint">Every ${setting('inspectionDays')} days</span></div>
      <div class="tbl-wrap scroll"><table class="tbl"><thead><tr><th>Break Area</th><th>Last</th><th>Next</th><th>Status</th><th></th></tr></thead><tbody>
      ${insp.map(a => `<tr><td><a class="link" href="#/area/${a.id}">${esc(a.name)}</a></td><td>${fmt(a.lastInspection)}</td><td>${fmt(a.nextInspection)}</td><td>${badge(inspStatus(a))}</td>
        <td>${can('inspections.create', 'inspections.delete') ? `<button class="btn sm" data-act="inspModal" data-id="${a.id}">${can('inspections.create') ? 'Record' : 'View'}</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div></div>
  </div>`;
}

/* ============================== Reports ============================== */
const REPORTS = {
  register: { title: 'Break Area Register', desc: 'Master data of all break areas with contents, status and inspection dates.', head: areaHead, rows: () => areaRows(DB.areas) },
  inventory: {
    title: 'Inventory by Break Area', desc: 'Quantity and condition of every item in each break area.',
    head: () => ['Break Area', 'Location', 'Item', 'Quantity', 'Condition', 'Notes'],
    rows: () => DB.areas.flatMap(a => a.inventory.map(e => [a.name, a.location, itemName(e.item), e.qty, e.condition, e.note || '']))
  },
  history: {
    title: 'Update History', desc: 'All inventory changes (added, removed, replaced, transferred, maintenance) in a date range.', dated: true,
    head: () => TX_HEAD, rows: (from, to) => txExportRows(DB.history.filter(h => (!from || h.date >= from) && (!to || h.date <= to)).sort(byDateDesc))
  },
  issues: {
    title: 'Issues Report', desc: 'All reported issues with priority, status, age and follow-up.', dated: true,
    head: () => ['Reported', 'Break Area', 'Issue', 'Item', 'Priority', 'Status', 'Closed', 'Reported By', 'Last Follow-up'],
    rows: (from, to) => allIssues().filter(i => (!from || i.date >= from) && (!to || i.date <= to)).sort(byDateDesc)
      .map(i => [i.date, i.a.name, i.title, i.item ? itemName(i.item) : 'General', i.priority, i.status, i.closedDate || '', i.reportedBy, (i.log || []).slice(-1).map(l => l.text)[0] || ''])
  },
  inspections: {
    title: 'Inspection Schedule', desc: 'Last and next inspection per break area, including overdue ones.',
    head: () => ['Break Area', 'Location', 'Last Inspection', 'Inspected By', 'Next Inspection', 'Status'],
    rows: () => [...DB.areas].sort((x, y) => (x.nextInspection || '').localeCompare(y.nextInspection || '')).map(a => [a.name, a.location, a.lastInspection, a.inspectedBy, a.nextInspection, inspStatus(a)])
  },
  satisfaction: {
    title: 'Satisfaction Survey', desc: 'Monthly satisfaction % of every break area and department, compared with the target.', dated: true,
    head: () => ['Month', 'Break Area', 'Location', 'Department', 'Satisfaction %', 'Respondents', 'Target %', 'Result', 'Notes', 'Entered By'],
    rows: (from, to) => DB.areas.flatMap(a => a.surveys.map(s => ({ a, s })))
      .filter(({ s }) => (!from || s.month >= from.slice(0, 7)) && (!to || s.month <= to.slice(0, 7)))
      .sort((x, y) => y.s.month.localeCompare(x.s.month) || x.a.name.localeCompare(y.a.name))
      .map(({ a, s }) => [monthName(s.month), a.name, a.location, s.department || '', +s.percentage, s.respondents ?? '', satTarget(), SAT_LABEL[satLevel(+s.percentage)], s.notes || '', s.by || ''])
  },
  locations: {
    title: 'Summary by Location', desc: 'Number of break areas, capacity and equipment totals per location.',
    head: () => ['Location', 'Break Areas', 'Capacity', ...DB.itemTypes.map(t => t.name), 'Open Issues'],
    rows: () => [...new Set(DB.areas.map(a => a.location))].map(l => {
      const L = DB.areas.filter(a => a.location === l);
      return [l, L.length, L.reduce((s, a) => s + (+a.capacity || 0), 0), ...DB.itemTypes.map(t => L.reduce((s, a) => s + qty(a, t.id), 0)), L.reduce((s, a) => s + openIssues(a).length, 0)];
    })
  }
};
function viewReports() {
  return `<div class="page-head"><h2>Reports</h2></div>
  <div class="report-grid">
    ${Object.entries(REPORTS).filter(([k]) => can('report.' + k) && (k !== 'satisfaction' || can('surveys.view'))).map(([k, r]) => `<div class="card report-card" data-report="${k}">
      <div class="card-h" style="margin:0">${ic('report')}<h3>${r.title}</h3></div><p>${r.desc}</p>
      ${r.dated ? `<div class="filters"><input type="date" name="from" title="From"><input type="date" name="to" title="To"></div>` : ''}
      <div class="filters"><button class="btn sm" data-act="runReport" data-k="${k}" data-mode="xlsx">${ic('download')}Export Excel</button>
      ${can('print') ? `<button class="btn sm" data-act="runReport" data-k="${k}" data-mode="print">${ic('printer')}Print / PDF</button>` : ''}</div></div>`).join('')}
    ${can('report.labels') ? `<div class="card report-card"><div class="card-h" style="margin:0">${ic('qr')}<h3>QR Code Labels</h3></div>
      <p>Print QR labels for all break areas to stick at each entrance.</p>
      <div class="filters"><button class="btn sm" data-act="printAllLabels">${ic('printer')}Print All Labels</button></div></div>` : ''}
    ${can('report.full') && allAreas() ? `<div class="card report-card"><div class="card-h" style="margin:0">${ic('database')}<h3>Complete Database Export</h3></div>
      <p>One Excel workbook with every table (areas, surveys, inventory, issues, photos, documents…), deleted records and the full activity logs – for documentation.</p>
      <div class="filters"><button class="btn sm primary" data-act="fullExport">${ic('download')}Export Everything</button></div></div>` : ''}
  </div>
  ${!Object.keys(REPORTS).some(k => can('report.' + k)) && !can('report.labels', 'report.full') ? '<p class="empty">No reports are enabled for your account. Ask the administrator.</p>' : ''}`;
}

/* ============================== Settings ============================== */
function viewSettings() {
  const s = DB.settings, ro = can('settings.edit') ? '' : 'disabled';
  return `<div class="page-head"><h2>Settings</h2></div>
  <div class="grid2 mb">
    ${can('settings.view') ? `<form class="card" data-form="settings"><fieldset class="plain" ${ro}>
      <div class="card-h">${ic('settings')}<h3>General</h3></div>
      <div class="form-grid">
        <label class="full">System Name<input name="systemName" value="${esc(s.systemName)}"></label>
        <label>Factory / Site<input name="factory" value="${esc(s.factory)}"></label>
        <label>Logo Text<input name="logoText" value="${esc(s.logoText)}"></label>
        <label>Inspection frequency (days)<input type="number" min="1" name="inspectionDays" value="${s.inspectionDays}"></label>
        <label>Satisfaction target (%)<input type="number" min="1" max="100" name="satisfactionTarget" value="${satTarget()}"></label>
        <label class="full">Logo Image (optional)<input type="file" name="logo" accept="image/*"></label>
        <label class="full">Locations <span class="hint">(one per line)</span><textarea name="locations" rows="5">${esc(s.locations.join('\n'))}</textarea></label>
      </div>
      ${ro ? '<p class="hint" style="margin-top:12px">You can see the settings but not change them.</p>'
        : `<div style="display:flex;gap:8px;margin-top:12px">${s.logoImage ? `<button type="button" class="btn" data-act="removeLogo">Remove logo image</button>` : ''}<span class="sp"></span><button class="btn primary">${ic('check')}Save Settings</button></div>`}
    </fieldset></form>` : ''}
    <div class="card">
      <div class="card-h">${ic('database')}<h3>Server &amp; Database</h3></div>
      ${can('settings.view') ? '<div data-async="serverInfo"><p class="muted">Loading…</p></div>' : ''}
      <div class="filters" style="margin-top:12px">
        ${can('report.full') && allAreas() ? `<button class="btn primary" data-act="fullExport">${ic('download')}Full Excel Export (all data + logs)</button>` : ''}
        ${can('data.import') ? `<label class="btn">${ic('upload')}Import Old Version (JSON)<input type="file" accept=".json,application/json" data-act-change="importBackup" hidden></label>` : ''}
      </div>
      ${can('data.import') && allAreas() ? `<div class="start-fresh">
        <div><b>Start real use</b><small>The system comes filled with sample data so everyone can see how it works.
          When you are ready, delete it all in one step and add your real break areas.</small></div>
        ${DB.areas.length ? `<button class="btn danger" data-act="clearAll">${ic('trash')}Delete All Sample Data</button>`
          : `<button class="btn" data-act="loadDemo">${ic('database')}Load Sample Data</button>`}
      </div>` : ''}
    </div>
  </div>
  <div class="grid2">
    ${can('backups.manage', 'backups.restore') ? `<div class="card">
      <div class="card-h">${ic('restore')}<h3>Backups</h3><span class="sp"></span>${can('backups.manage') ? `<button class="btn sm primary" data-act="backupNow">${ic('download')}Backup Now</button>` : ''}</div>
      <div data-async="backups"><p class="muted">Loading…</p></div>
    </div>` : ''}
    ${can('trash.restore') ? `<div class="card">
      <div class="card-h">${ic('trash')}<h3>Recycle Bin</h3><span class="hint">Nothing is ever erased – deleted records can be restored</span></div>
      <div data-async="trash"><p class="muted">Loading…</p></div>
    </div>` : ''}
  </div>`;
}

/* ============================== Activity log ============================== */
const ENTITY_NAME = {
  areas: 'Break Area', inventory: 'Inventory', surveys: 'Satisfaction', photos: 'Photo', docs: 'Document', issues: 'Issue',
  issueLog: 'Issue Follow-up', maintenance: 'Maintenance', inspections: 'Inspection', history: 'Transaction', itemTypes: 'Item Type', settings: 'Setting'
};
const OP_BADGE = { insert: ['Added', 'b-green'], update: ['Changed', 'b-blue'], delete: ['Deleted', 'b-red'] };
const ACTIVITY_TYPES = ['session', 'navigate', 'click', 'open', 'filter', 'save', 'save-failed', 'denied', 'export', 'backup', 'restore', 'js-error', 'server-error'];
const SECURITY_EVENTS = [['login', 'Logged in'], ['logout', 'Logged out'], ['login-failed', 'Wrong password / user name'], ['login-blocked', 'Login blocked (locked / disabled)'],
  ['account-locked', 'Account locked'], ['session-expired', 'Logged out automatically'], ['password-changed', 'Changed own password'],
  ['password-change-failed', 'Password change failed'], ['password-reset', 'Password reset by admin'], ['user-created', 'User created'],
  ['user-changed', 'User / permissions changed'], ['user-disabled', 'User disabled'], ['user-deleted', 'User deleted'], ['user-unlocked', 'User unlocked'],
  ['forced-logout', 'Logged out by admin'], ['access-denied', 'Access denied'], ['backup-restored', 'Backup restored'], ['setup', 'First setup'], ['admin-reset', 'Admin password reset on server']];
const SEC_LABEL = Object.fromEntries(SECURITY_EVENTS);
const SEC_BAD = /failed|blocked|locked|denied|reset|deleted|disabled/;
let LOGDATA = { rows: [], total: 0, users: [] };

function viewLogs() {
  const tabs = LOG_TABS.filter(t => can(t[2]));
  if (!tabs.some(t => t[0] === F.log.tab)) F.log = { ...F.log, tab: tabs[0][0], type: '', area: '' };
  const f = F.log, audit = f.tab === 'audit';
  const types = audit ? Object.entries(OP_BADGE).map(([k, [l]]) => [k, l]) : f.tab === 'security' ? SECURITY_EVENTS : ACTIVITY_TYPES;
  return `<div class="page-head"><h2>Activity Log</h2><span class="muted" id="logCount"></span>
    <div class="actions"><button class="btn" data-act="logRefresh">${ic('history')}Refresh</button><button class="btn" data-act="logExport">${ic('download')}Export Excel</button></div></div>
  <div class="card">
    <div class="card-h filters">
      <div class="tabs">${tabs.map(([k, l]) => `<button data-act="logTab" data-tab="${k}" class="${f.tab === k ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>
      <label class="search">${ic('search')}<input data-logf="q" placeholder="Search..." value="${esc(f.q)}"></label>
      <select data-logf="user"><option value="">All users</option>${options(LOGDATA.users, f.user)}</select>
      <select data-logf="type"><option value="">All types</option>${options(types, f.type)}</select>
      ${audit ? `<select data-logf="area"><option value="">All break areas</option>${options(DB.areas.map(a => [a.id, a.name]), f.area)}</select>` : ''}
      <label class="fld" style="flex-direction:row;align-items:center">From<input type="date" data-logf="from" value="${f.from}"></label>
      <label class="fld" style="flex-direction:row;align-items:center">To<input type="date" data-logf="to" value="${f.to}"></label>
      <button class="btn sm" data-act="logClear">Clear</button>
    </div>
    <div data-async="logTable"><p class="muted">Loading…</p></div>
  </div>`;
}
const logQuery = (offset = 0, limit = 200) => {
  const f = F.log, p = new URLSearchParams({ q: f.q, user: f.user, type: f.type, area: f.tab === 'audit' ? f.area || '' : '', from: f.from, to: f.to, offset, limit });
  return api('GET', `/api/${f.tab}?${p}`);
};
const short = (v, n = 60) => { v = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v); return v.length > n ? v.slice(0, n) + '…' : v; };
function auditDetail(r) {
  const parse = s => { try { return JSON.parse(s || 'null'); } catch (e) { return null; } };
  if (r.op === 'update') {
    return Object.entries(parse(r.changes) || {}).map(([k, [o, n]]) => `<div><b>${esc(k)}</b>: <s>${esc(short(o))}</s> → ${esc(short(n))}</div>`).join('');
  }
  const x = parse(r.op === 'delete' ? r.before : r.after) || {};
  const keys = ['name', 'title', 'caption', 'month', 'department', 'percentage', 'item', 'qty', 'action', 'details', 'text', 'value', 'status'];
  return esc(keys.filter(k => x[k] != null && x[k] !== '').map(k => `${k}: ${short(x[k], 50)}`).join(' · '));
}
function logRowsHTML(rows) {
  if (F.log.tab === 'audit') return rows.map(r => {
    const [l, c] = OP_BADGE[r.op] || [r.op, 'b-gray'];
    const a = area(r.area_id);
    return `<tr><td class="nowrap">${esc(r.ts.replace('T', ' '))}</td><td>${esc(r.user)}</td><td class="muted">${esc(r.ip)}</td><td class="wrap">${esc(r.label)}</td>
      <td>${esc(ENTITY_NAME[r.entity] || r.entity)}${a ? `<br><a class="link" href="#/area/${a.id}">${esc(a.name)}</a>` : ''}</td><td><span class="badge ${c}">${l}</span></td><td class="wrap log-detail">${auditDetail(r)}</td></tr>`;
  }).join('');
  if (F.log.tab === 'security') return rows.map(r => `<tr class="${SEC_BAD.test(r.event) ? 'err' : ''}"><td class="nowrap">${esc(r.ts.replace('T', ' '))}</td><td>${esc(r.user)}</td>
    <td class="muted">${esc(r.ip)}</td><td><span class="badge ${SEC_BAD.test(r.event) ? 'b-red' : r.event === 'login' ? 'b-green' : 'b-gray'}">${esc(SEC_LABEL[r.event] || r.event)}</span></td>
    <td class="wrap">${esc(r.target)}</td><td class="wrap log-detail">${esc(r.detail)}</td></tr>`).join('');
  return rows.map(r => `<tr class="${/error|failed|denied/.test(r.type) ? 'err' : ''}"><td class="nowrap">${esc(r.ts.replace('T', ' '))}</td><td>${esc(r.user)}</td><td class="muted">${esc(r.ip)}</td>
    <td><span class="badge ${/error|failed|denied/.test(r.type) ? 'b-red' : r.type === 'save' ? 'b-green' : 'b-gray'}">${esc(r.type)}</span></td><td class="wrap">${esc(r.action)}</td><td class="wrap">${esc(r.target)}</td>
    <td class="muted">${esc(r.page)}</td><td class="wrap log-detail" title="${esc(r.detail)}">${esc(short(r.detail, 120))}</td></tr>`).join('');
}
function logTableHTML() {
  const audit = F.log.tab === 'audit';
  const head = audit ? ['Time', 'User', 'PC (IP)', 'Action', 'Record', 'Change', 'Details']
    : F.log.tab === 'security' ? ['Time', 'User', 'PC (IP)', 'Event', 'Account / Target', 'Details'] : ['Time', 'User', 'PC (IP)', 'Type', 'Action', 'Target', 'Page', 'Detail'];
  return `<div class="tbl-wrap"><table class="tbl log-tbl"><thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead>
    <tbody>${logRowsHTML(LOGDATA.rows) || `<tr><td colspan="${head.length}" class="empty">No records match the filters</td></tr>`}</tbody></table></div>
    ${LOGDATA.rows.length < LOGDATA.total ? `<div style="text-align:center;margin-top:10px"><button class="btn" data-act="logMore">Load more (${LOGDATA.total - LOGDATA.rows.length} remaining)</button></div>` : ''}`;
}

/* Sections that load their data from the server after the page is drawn */
const ASYNC = {
  async logTable(el) {
    LOGDATA = await logQuery();
    el.innerHTML = logTableHTML();
    const c = $('#logCount'); if (c) c.textContent = LOGDATA.total.toLocaleString() + ' records';
    const us = $('[data-logf=user]');
    if (us) us.innerHTML = `<option value="">All users</option>${options(LOGDATA.users, F.log.user)}`;
  },
  async serverInfo(el) {
    const i = await api('GET', '/api/info');
    const counts = Object.entries(i.counts).filter(([k]) => k !== 'Settings').map(([k, v]) => `<span><b>${v.toLocaleString()}</b> ${esc(k)}</span>`).join('');
    el.innerHTML = `<dl class="kv">
      <dt>Open from other PCs</dt><dd>${i.urls.map(u => `<div><a class="link" href="${esc(u)}">${esc(u)}</a></div>`).join('')}</dd>
      <dt>Database folder</dt><dd class="mono">${esc(i.dataDir)}</dd>
      <dt>Backup folder</dt><dd class="mono">${esc(i.backupDir)}${i.extraBackupDirs.map(d => `<div>+ ${esc(d)}</div>`).join('')}</dd>
      <dt>Automatic backup</dt><dd>Every ${i.backupIntervalHours} hours when data changed, and at every server start</dd>
      <dt>Database size</dt><dd>${fileSize(i.dbSize)} · Photos &amp; documents ${fileSize(i.uploadsSize)}</dd>
    </dl>
    ${i.lastBackupError ? `<p class="err-box">${ic('alert')} Last backup problem: ${esc(i.lastBackupError)}</p>` : ''}
    <div class="counts">${counts}</div>`;
  },
  async backups(el) {
    const list = await api('GET', '/api/backups');
    const kind = { auto: 'Automatic', startup: 'Server start', manual: 'Manual', 'pre-import': 'Before import', 'pre-restore': 'Before restore' };
    el.innerHTML = list.length ? `<div class="tbl-wrap scroll"><table class="tbl"><thead><tr><th>Date &amp; Time</th><th>Type</th><th class="num">Size</th><th></th></tr></thead><tbody>
      ${list.map(b => `<tr><td>${esc(b.time.replace('T', ' '))}</td><td>${esc(kind[b.kind] || b.kind)}</td><td class="num">${fileSize(b.size)}</td>
        <td>${can('backups.restore') ? `<button class="btn sm" data-act="backupRestore" data-name="${esc(b.name)}" data-time="${esc(b.time)}">${ic('restore')}Restore</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div><p class="hint">${list.length} backups. Restoring first saves the current data as a new backup, so a restore can always be undone.</p>`
      : '<p class="empty">No backups yet – click "Backup Now".</p>';
  },
  async trash(el) {
    const list = await api('GET', '/api/trash');
    el.innerHTML = list.length ? `<ul class="trash-list">${list.map(g => `<li>
        <div><b>${esc(g.label || 'Deleted records')}</b>
          <small>${esc((g.ts || '').replace('T', ' '))} · by ${esc(g.user || '?')} · ${Object.entries(g.items).map(([k, v]) => `${v} ${esc(k)}`).join(', ')}</small>
          ${g.names.length ? `<small class="muted">${g.names.map(n => esc(short(n, 40))).join(' · ')}</small>` : ''}</div>
        <button class="btn sm" data-act="trashRestore" data-txn="${esc(g.txn)}">${ic('restore')}Restore</button></li>`).join('')}</ul>`
      : '<p class="empty">The recycle bin is empty.</p>';
  }
};

/* ============================== Login screens ============================== */
function authScreen(html) {
  document.body.classList.add('locked');
  closeModal();
  $('#auth').innerHTML = `<div class="auth-card"><div class="logo">${esc((DB && setting('logoText')) || 'SAMSUNG')}</div>${html}</div>`;
  const first = $('#auth input');
  if (first) first.focus();
}
const pwRules = () => `At least ${(ME && ME.minPasswordLength) || 8} characters with letters and a number or symbol. Not your name or user name.`;

function showLogin(msg = '') {
  if (document.body.classList.contains('locked') && $('#loginForm')) { if (msg) $('#authMsg').textContent = msg; return; }
  ME = null;
  authScreen(`<h2>Break Area Management System</h2><p class="muted">Log in with your user name and password.</p>
    <form id="loginForm" class="auth-form" data-form="login" autocomplete="on">
      <label>User name<input name="username" autocomplete="username" required autocapitalize="none" spellcheck="false"></label>
      <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
      <p class="auth-msg" id="authMsg">${esc(msg)}</p>
      <button class="btn primary">${ic('user')}Log In</button>
    </form>
    <p class="hint">Forgot your password? Ask the system administrator to set a new one.</p>`);
}
function showSetup(local) {
  authScreen(local ? `<h2>Create the administrator account</h2>
    <p class="muted">This is the first start. The administrator can add users, choose what each one may see and do, and review everything they did.</p>
    <form class="auth-form" data-form="setup">
      <label>Full name<input name="full_name" required autocomplete="name" placeholder="e.g. Ayman Essam"></label>
      <label>User name<input name="username" required autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="e.g. ayman"></label>
      <label>Password<input name="password" type="password" required autocomplete="new-password"></label>
      <label>Repeat password<input name="password2" type="password" required autocomplete="new-password"></label>
      <p class="hint">${pwRules()}</p>
      <p class="auth-msg" id="authMsg"></p>
      <button class="btn primary">${ic('check')}Create Administrator</button>
    </form>`
    : `<h2>System not set up yet</h2><p class="muted">The administrator account must first be created <b>on the server PC itself</b>
      (the PC running start.bat) by opening <b>http://localhost:${esc(location.port || '80')}/</b> there.</p>
      <button class="btn" data-act="reloadPage">${ic('restore')}Try again</button>`);
}
async function afterLogin(user) {
  ME = user;
  document.body.classList.remove('locked');
  $('#auth').innerHTML = '';
  await start();
}
async function submitAuth(form) {
  const d = Object.fromEntries(new FormData(form));
  const msg = $('#authMsg'), btn = $('button.primary', form);
  msg.textContent = '';
  if (form.dataset.form === 'setup' && d.password !== d.password2) { msg.textContent = 'The two passwords are not the same.'; return; }
  btn.disabled = true;
  try {
    const user = await api('POST', form.dataset.form === 'setup' ? '/api/auth/setup' : '/api/auth/login', d);
    await afterLogin(user);
  } catch (e) {
    msg.textContent = e.message;
    if (form.password) { form.password.value = ''; form.password.focus(); }
  } finally { btn.disabled = false; }
}

/* ============================== My account ============================== */
function passwordModal(forced) {
  modal(forced ? 'Choose your own password' : 'Change My Password', `<div class="form-grid">
    ${forced ? '<p class="full">You are using a temporary password from the administrator. Choose your own password to continue – nobody else, not even the administrator, will know it.</p>' : ''}
    <label class="full">Current password<input type="password" name="old" required autocomplete="current-password"></label>
    <label>New password<input type="password" name="new" required autocomplete="new-password"></label>
    <label>Repeat new password<input type="password" name="new2" required autocomplete="new-password"></label>
    <p class="full hint">${pwRules()} Other PCs where you are logged in will be logged out.</p></div>`, {
    submit: 'Change Password', locked: forced,
    extra: forced ? `<button type="button" class="btn" data-act="logout">${ic('arrowLeft')}Log out</button>` : '',
    async onSubmit(d) {
      if (d.new !== d.new2) { toast('The two new passwords are not the same', true); return false; }
      try { ME = await api('POST', '/api/auth/password', { old: d.old, new: d.new }); }
      catch (e) { toast(e.message, true, 6000); return false; }
      toast('Password changed');
      if (forced) setTimeout(() => start(), 0);
    }
  });
}
function accountMenu() {
  modal('My Account', `<div class="acct">
      <div class="avatar lg">${esc(initials(me()))}</div>
      <div><b>${esc(ME.full_name)}</b><div class="muted">${esc(ME.username)}${ME.title ? ' · ' + esc(ME.title) : ''}</div>
        <div class="muted">${esc(ME.role || 'Custom')} · ${allAreas() ? 'All break areas' : ME.areas.length + ' break area(s)'} · ${ME.perms.length} permissions</div></div>
    </div>
    <p class="hint">For your security you are logged out automatically after ${ME.sessionIdleMinutes} minutes without activity.
      Always log out when you leave a shared PC.</p>`, {
    extra: `<a class="btn" href="#/account" data-act="closeModal">${ic('eye')}What I can do</a>
      <button type="button" class="btn" data-act="changePassword">${ic('edit')}Change Password</button>
      <button type="button" class="btn danger" data-act="logout">${ic('arrowLeft')}Log Out</button>`
  });
}
const permGroupsHTML = (perms, input) => ME.permissions.map(([g, list]) => `<fieldset class="perm-group">
    <legend>${input ? `<label class="check"><input type="checkbox" data-group="${esc(g)}"> ${esc(g)}</label>` : esc(g)}</legend>
    ${list.map(([p, l]) => input
      ? `<label class="check"><input type="checkbox" name="perm" value="${p}" ${perms.includes(p) ? 'checked' : ''}> ${esc(l)}</label>`
      : `<div class="perm ${perms.includes(p) ? 'yes' : 'no'}">${ic(perms.includes(p) ? 'check' : 'x')}${esc(l)}</div>`).join('')}
  </fieldset>`).join('');
function viewAccount() {
  return `<div class="page-head"><h2>My Permissions</h2><span class="muted">${esc(ME.full_name)} · ${esc(ME.role || 'Custom')}</span>
    <div class="actions"><button class="btn" data-act="changePassword">${ic('edit')}Change Password</button></div></div>
  <div class="card mb"><div class="card-h">${ic('building')}<h3>Break areas</h3></div>
    <p>${allAreas() ? 'You can work with <b>all break areas</b>.' : `You can only see and work with: <b>${ME.areas.map(id => esc((area(id) || { name: id }).name)).join(', ') || 'none'}</b>`}</p></div>
  <div class="card"><div class="card-h">${ic('check')}<h3>What your account may do</h3><span class="hint">Set by the system administrator</span></div>
    <div class="perm-grid">${permGroupsHTML(ME.perms, false)}</div></div>`;
}

/* ============================== Users & permissions (administrator) ============================== */
let USERS = { users: [], permissions: [], roles: {} };
const ago = ts => {
  if (!ts) return 'Never';
  const m = Math.round((new Date() - new Date(ts)) / 60000);
  return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : fmt(ts.slice(0, 10));
};
function viewUsers() {
  return `<div class="page-head"><h2>Users &amp; Permissions</h2><span class="muted" id="userCount"></span>
    <div class="actions">${can('logs.security') ? `<button class="btn" data-act="securityLog">${ic('activity')}Logins &amp; Security Log</button>` : ''}
      <button class="btn primary" data-act="userEdit">${ic('plus')}Add User</button></div></div>
  <div class="card"><div data-async="users"><p class="muted">Loading…</p></div></div>
  <p class="hint">Every user logs in with a personal user name and password. Everything each user does is recorded in the Activity Log with their name.
    Disable or delete an account as soon as the person leaves – their history stays in the logs.</p>`;
}
function userRowsHTML() {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Name</th><th>User name</th><th>Role</th><th>Break areas</th><th class="num">Permissions</th><th>Status</th><th>Last login</th><th></th></tr></thead><tbody>
    ${USERS.users.map(u => `<tr class="click" data-act="userEdit" data-uid="${u.id}">
      <td><b>${esc(u.full_name)}</b>${u.title ? `<br><small class="muted">${esc(u.title)}</small>` : ''}</td><td class="mono">${esc(u.username)}</td>
      <td>${esc(u.role || 'Custom')}</td><td>${u.areas == null ? 'All' : u.areas.length}</td><td class="num">${u.perms.length} / ${USERS.permissions.flatMap(g => g[1]).length}</td>
      <td class="nowrap">${u.active ? badge('Active') : badge('Inactive')} ${u.online ? '<span class="badge b-green" title="Logged in now">● Online</span>' : ''}
        ${u.locked ? '<span class="badge b-red">Locked</span>' : ''} ${u.must_change ? '<span class="badge b-orange" title="Must choose a new password at the next login">New password</span>' : ''}</td>
      <td class="nowrap" title="${esc(u.last_login || '')} ${esc(u.last_ip || '')}">${ago(u.last_login)}</td>
      <td><button class="btn sm" data-act="userEdit" data-uid="${u.id}">${ic('edit')}Edit</button></td></tr>`).join('')}
  </tbody></table></div>`;
}
const genPassword = () => {
  const c = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789', a = new Uint32Array(10);
  crypto.getRandomValues(a);
  return [...a].map(x => c[x % c.length]).join('').replace(/^(.{4})(.{4})(.{2})$/, '$1-$2-$3') + '7';
};
function userEdit(uid) {
  const u = uid ? USERS.users.find(x => x.id === uid) : null;
  const perms = u ? u.perms : USERS.roles['Data Entry'];
  const scoped = u && u.areas != null;
  const roleOpts = [...Object.keys(USERS.roles), 'Custom'];
  const form = modal(u ? `User – ${esc(u.full_name)}` : 'Add User', `<div class="form-grid">
      <label>Full name *<input name="full_name" required value="${esc(u ? u.full_name : '')}" placeholder="e.g. Sara Mostafa"></label>
      <label>User name * <span class="hint">(for logging in)</span><input name="username" required value="${esc(u ? u.username : '')}" autocapitalize="none" spellcheck="false" placeholder="e.g. sara.m"></label>
      <label>Job title / department<input name="title" value="${esc(u ? u.title || '' : '')}" placeholder="e.g. HR Specialist"></label>
      ${u ? `<label>Account<select name="active">${options([['1', 'Active – can log in'], ['0', 'Disabled – cannot log in']], u.active ? '1' : '0')}</select></label>`
        : `<label>Temporary password *<span style="display:flex;gap:6px"><input name="password" required value="${genPassword()}" style="flex:1" class="mono">
          <button type="button" class="btn sm" data-act="genPw">New</button></span></label>`}
      <label class="full check"><input type="checkbox" name="must_change" ${!u || u.must_change ? 'checked' : ''}> Must choose a new password at the next login (recommended)</label>
      <label class="full">Notes<input name="notes" value="${esc(u ? u.notes || '' : '')}" placeholder="optional"></label>
    </div>
    <h4 class="sec-h">${ic('building')} Break areas this user can see and work with</h4>
    <div class="filters"><label class="check"><input type="radio" name="scope" value="all" ${scoped ? '' : 'checked'}> All break areas (also new ones)</label>
      <label class="check"><input type="radio" name="scope" value="some" ${scoped ? 'checked' : ''}> Only the selected break areas</label></div>
    <div class="area-picks ${scoped ? '' : 'hidden'}">${DB.areas.map(a => `<label class="check"><input type="checkbox" name="area" value="${a.id}" ${scoped && u.areas.includes(a.id) ? 'checked' : ''}> ${esc(a.name)} <span class="muted">${esc(a.location)}</span></label>`).join('')
      || '<p class="muted">No break areas yet.</p>'}</div>
    <h4 class="sec-h">${ic('check')} Permissions – what this user can see and do
      <span class="sp"></span><label class="fld" style="flex-direction:row;align-items:center;gap:6px">Quick role<select name="role">${options(roleOpts, u ? (u.role || 'Custom') : 'Data Entry')}</select></label></h4>
    <div class="perm-grid">${permGroupsHTML(perms, true)}</div>
    ${u ? `<p class="hint">Created ${esc((u.created_at || '').replace('T', ' '))} by ${esc(u.created_by || '-')} · Last changed ${esc((u.updated_at || '').replace('T', ' '))} by ${esc(u.updated_by || '-')}
      · Password set ${esc((u.pw_changed_at || '').replace('T', ' '))} · Last login ${esc((u.last_login || 'never').replace('T', ' '))} ${esc(u.last_ip || '')}</p>` : ''}`, {
    submit: u ? 'Save Changes' : 'Create User', wide: true, cls: 'user-modal',
    extra: u ? `<button type="button" class="btn" data-act="userReset" data-uid="${u.id}">${ic('edit')}Reset Password</button>
      ${u.locked ? `<button type="button" class="btn" data-act="userUnlock" data-uid="${u.id}">${ic('check')}Unlock</button>` : ''}
      ${u.online ? `<button type="button" class="btn" data-act="userLogout" data-uid="${u.id}">${ic('arrowLeft')}Log Out Now</button>` : ''}
      ${can('logs.activity') ? `<button type="button" class="btn" data-act="userActivity" data-uid="${u.id}">${ic('activity')}Activity</button>` : ''}
      ${u.id !== ME.id ? `<button type="button" class="btn danger" data-act="userDelete" data-uid="${u.id}">${ic('trash')}Delete</button>` : ''}` : '',
    async onSubmit(d, f) {
      const perms = $$('input[name=perm]:checked', f).map(x => x.value);
      const areas = d.scope === 'some' ? $$('input[name=area]:checked', f).map(x => x.value) : null;
      if (areas && !areas.length && !confirm('No break area is selected – this user will not see any break area. Continue?')) return false;
      if (!perms.length && !confirm('No permission is selected – this user will not be able to see anything. Continue?')) return false;
      const body = { id: u ? u.id : undefined, ver: u ? u.ver : undefined, full_name: d.full_name, username: d.username.trim(), title: d.title,
        notes: d.notes, role: d.role, perms, areas, active: u ? d.active === '1' : true, must_change: !!d.must_change, password: d.password };
      try { await api('POST', '/api/users/save', body); }
      catch (e) { toast(e.message, true, 7000); return false; }
      if (!u) {
        modal('User created', `<p><b>${esc(d.full_name)}</b> can now log in on any PC in the network with:</p>
          <dl class="kv"><dt>Address</dt><dd class="mono">${esc(BASE_URL)}</dd><dt>User name</dt><dd class="mono">${esc(body.username)}</dd><dt>Password</dt><dd class="mono">${esc(d.password)}</dd></dl>
          <p class="hint">Give the password to the person privately. ${body.must_change ? 'They must choose their own password at the first login.' : ''} It is not shown again.</p>`);
        await ASYNC.users($('[data-async=users]'));
        return false;
      }
      toast('User saved');
      if (u.id === ME.id) { ME = await api('GET', '/api/me'); }
    }
  });
  const sync = () => {
    $$('fieldset.perm-group', form).forEach(g => {
      const boxes = $$('input[name=perm]', g), on = boxes.filter(b => b.checked).length;
      const all = $('input[data-group]', g); all.checked = on === boxes.length; all.indeterminate = on > 0 && on < boxes.length;
    });
  };
  const matchRole = () => {
    const cur = $$('input[name=perm]:checked', form).map(x => x.value).sort().join();
    form.role.value = Object.keys(USERS.roles).find(r => [...USERS.roles[r]].sort().join() === cur) || 'Custom';
  };
  form.addEventListener('change', e => {
    const t = e.target;
    if (t.name === 'role' && USERS.roles[t.value]) $$('input[name=perm]', form).forEach(b => (b.checked = USERS.roles[t.value].includes(b.value)));
    else if (t.dataset.group) { $$('input[name=perm]', t.closest('fieldset')).forEach(b => (b.checked = t.checked)); matchRole(); }
    else if (t.name === 'perm') matchRole();
    if (t.name === 'scope') $('.area-picks', form).classList.toggle('hidden', t.value !== 'some');
    sync();
  });
  sync();
}
ASYNC.users = async el => {
  USERS = await api('GET', '/api/users');
  el.innerHTML = userRowsHTML();
  const c = $('#userCount'); if (c) c.textContent = USERS.users.length + ' users · ' + USERS.users.filter(u => u.online).length + ' online now';
};
async function userAction(action, uid, confirmText, done) {
  const u = USERS.users.find(x => x.id === uid);
  if (!u || (confirmText && !confirm(confirmText.replace('{name}', u.full_name)))) return;
  try { await api('POST', '/api/users/' + action, { id: uid }); closeModal(); toast(done.replace('{name}', u.full_name)); rerender(); }
  catch (e) { toast(e.message, true, 7000); }
}
function userReset(uid) {
  const u = USERS.users.find(x => x.id === uid);
  if (!u) return;
  modal(`Reset Password – ${esc(u.full_name)}`, `<div class="form-grid">
    <label class="full">New temporary password<span style="display:flex;gap:6px"><input name="password" class="mono" style="flex:1" required value="${genPassword()}">
      <button type="button" class="btn sm" data-act="genPw">New</button></span></label>
    <p class="full hint">${esc(u.full_name)} is logged out everywhere, must log in with this password and then choose their own. The account is also unlocked.</p></div>`, {
    submit: 'Set Password',
    async onSubmit(d) {
      try { await api('POST', '/api/users/reset', { id: uid, password: d.password }); }
      catch (e) { toast(e.message, true, 7000); return false; }
      modal('Password reset', `<p>Give this temporary password to <b>${esc(u.full_name)}</b> privately:</p><p class="big-pw mono">${esc(d.password)}</p>
        <p class="hint">User name: <b class="mono">${esc(u.username)}</b>. It is not shown again.</p>`);
      return false;
    }
  });
}

/* Sample data (js/data.js) – loaded automatically the very first time the system starts */
async function loadSample() {
  const seed = buildSeed();
  const { userName, userRole, ...settings } = seed.settings;
  DB = { ...DB, settings: { ...DEFAULT_SETTINGS, ...settings }, itemTypes: seed.itemTypes, areas: seed.areas, history: seed.history };
  return save('Load sample data', { force: true });
}

/* ============================== Import ============================== */
async function dataURLToBlob(u) { return (await fetch(u)).blob(); }
const extOf = type => ({ 'image/png': '.png', 'image/gif': '.gif', 'image/webp': '.webp', 'application/pdf': '.pdf' }[type] || '.jpg');
async function importOldBackup(file) {
  let data;
  try { data = JSON.parse(await file.text()); } catch (e) { return toast('This is not a valid backup file', true); }
  if (!data.areas || !data.settings || !data.history) return toast('This is not a backup of the Break Area system', true);
  if (!confirm(`Import ${data.areas.length} break areas from "${file.name}"?\n\nThe current data will be replaced. A backup of the current database is taken automatically first, and replaced records stay in the Recycle Bin.`)) return;
  toast('Importing… please wait', false, 60000);
  try {
    for (const a of data.areas) {
      a.surveys = a.surveys || [];
      a.issues = a.issues || []; a.docs = a.docs || []; a.photos = a.photos || []; a.maintenance = a.maintenance || []; a.inspections = a.inspections || []; a.inventory = a.inventory || [];
      for (const p of a.photos) if (p.src && p.src.startsWith('data:')) {
        const b = await dataURLToBlob(p.src);
        p.src = await uploadFile(b, 'photo' + extOf(b.type));
        p.thumb = await uploadFile(await resizeImage(b, 800, true), 'thumb.jpg').catch(() => '');
      }
      for (const d of a.docs) if (d.src && d.src.startsWith('data:')) d.src = await uploadFile(await dataURLToBlob(d.src), d.name);
    }
    const { userName, userRole, ...settings } = data.settings;
    if (settings.logoImage && settings.logoImage.startsWith('data:')) { const b = await dataURLToBlob(settings.logoImage); settings.logoImage = await uploadFile(b, 'logo' + extOf(b.type)); }
    DB = { settings: { ...DEFAULT_SETTINGS, ...settings }, itemTypes: data.itemTypes || DEFAULT_ITEM_TYPES, areas: data.areas, history: data.history };
  } catch (e) { toast('Import failed: ' + e.message, true, 8000); await load(); return rerender(); }
  if (await save(`Import old version backup "${file.name}"`, { force: true })) { location.hash = '#/dashboard'; rerender(); toast('Backup imported'); }
}

/* ============================== Events ============================== */
const ACT = {
  go: d => { location.hash = d.href; },
  toggleNav: () => document.body.classList.toggle('nav-open'),
  closeModal,
  accountMenu,
  changePassword: () => passwordModal(false),
  async logout() {
    flushLog();
    try { await api('POST', '/api/auth/logout', {}); } catch (e) { /* logged out anyway */ }
    DB = null; SNAP = {};
    location.hash = '';
    showLogin('You have been logged out.');
  },
  reloadPage: () => location.reload(),
  genPw: (d, el) => { el.closest('label').querySelector('input').value = genPassword(); },
  userEdit: d => userEdit(d.uid),
  userReset: d => userReset(d.uid),
  userUnlock: d => userAction('unlock', d.uid, '', '{name} unlocked'),
  userLogout: d => userAction('logout', d.uid, 'Log {name} out on all PCs now?', '{name} was logged out'),
  userDelete: d => userAction('delete', d.uid, 'Delete the account of {name}?\n\nThey can never log in again. Everything they did stays in the logs with their name. (To block someone only for a while, choose "Disabled" instead.)', 'Account of {name} deleted'),
  userActivity: d => {
    const u = USERS.users.find(x => x.id === d.uid);
    closeModal();
    F.log = { tab: 'activity', q: '', user: `${u.full_name} (${u.username})`, type: '', area: '', from: '', to: '' };
    location.hash = '#/logs';
  },
  securityLog: () => { F.log = { tab: 'security', q: '', user: '', type: '', area: '', from: '', to: '' }; location.hash = '#/logs'; },
  scrollTrack: d => { const t = $('#track'); t.scrollBy({ left: d.dir * t.clientWidth * .7 }); },
  toHistory: () => $('#history').scrollIntoView({ behavior: 'smooth' }),
  photoTab: d => { F.photoTab = d.tab; rerender(); },
  editArea: d => editArea(area(d.id)),
  invModal: d => invModal(area(d.id), d.item),
  issueModal: d => issueModal(area(d.id)),
  issueView: d => issueView(area(d.id), d.iid),
  async issueDelete(d) {
    const a = area(d.id), i = a.issues.find(x => x.id === d.iid);
    if (!i || !confirm('Delete this issue?')) return;
    a.issues = a.issues.filter(x => x !== i);
    if (await save(`Delete issue "${i.title}" – ${a.name}`)) { closeModal(); rerender(); toast('Issue deleted'); }
  },
  async invDelete(d) {
    const a = area(d.id), item = $('#modal form').item.value, e = invEntry(a, item);
    if (!e) return toast(`${itemName(item)} is not in this break area's inventory`, true);
    if (!confirm(`Delete ${itemName(item)} (quantity ${e.qty}) from ${a.name}'s inventory?`)) return;
    a.inventory = a.inventory.filter(x => x !== e);
    pushHistory({ areaId: a.id, date: today(), item, action: 'Removed', prev: e.qty, next: 0, details: `${itemName(item)} deleted from the inventory`, by: me() });
    if (await save(`Delete inventory item ${itemName(item)} – ${a.name}`)) { closeModal(); rerender(); toast('Item deleted'); }
  },
  async maintDelete(d) {
    const a = area(d.id), m = a.maintenance.find(x => x.id === d.mid);
    if (!m || !confirm(`Delete this maintenance?\n\n${m.details}`)) return;
    a.maintenance = a.maintenance.filter(x => x !== m);
    if (await save(`Delete maintenance "${m.details}" – ${a.name}`)) { rerender(); toast('Maintenance deleted'); }
  },
  async inspDelete(d) {
    const a = area(d.id), i = a.inspections.find(x => x.id === d.iid);
    if (!i || !confirm(`Delete the inspection of ${fmt(i.date)}?`)) return;
    a.inspections = a.inspections.filter(x => x !== i);
    if (a.lastInspection === i.date) { // show the latest remaining inspection instead
      const last = [...a.inspections].sort(byDateDesc)[0];
      a.lastInspection = last ? last.date : '';
      a.inspectedBy = last ? last.by : '';
    }
    if (await save(`Delete inspection ${i.date} – ${a.name}`)) { closeModal(); rerender(); toast('Inspection deleted'); }
  },
  async itemTypeDelete(d) {
    const t = itemType(d.tid);
    if (!t) return;
    const used = DB.areas.filter(a => qty(a, t.id) > 0);
    if (used.length) return toast(`${t.name} are still in ${used.length} break area(s). Set their quantity to 0 or delete them from the inventory first.`, true, 7000);
    if (!confirm(`Delete the item type "${t.name}"?`)) return;
    DB.itemTypes = DB.itemTypes.filter(x => x !== t);
    DB.areas.forEach(a => (a.inventory = a.inventory.filter(e => e.item !== t.id)));
    if (await save(`Delete item type – ${t.name}`)) { closeModal(); rerender(); toast('Item type deleted'); }
  },
  maintModal: d => maintModal(area(d.id)),
  maintDone: d => maintDone(area(d.id), d.mid),
  inspModal: d => inspModal(area(d.id)),
  uploadModal: d => uploadModal(area(d.id), d.cat),
  viewPhoto: d => viewPhoto(area(d.id), d.pid),
  surveyModal: d => surveyModal(area(d.id), d.sid),
  async surveyDelete(d) {
    const a = area(d.id), s = a.surveys.find(x => x.id === d.sid);
    if (!s || !confirm(`Delete the ${monthName(s.month)} result (${pct(+s.percentage)})?`)) return;
    a.surveys = a.surveys.filter(x => x !== s);
    if (await save(`Delete satisfaction ${monthName(s.month)} – ${a.name}`)) { closeModal(); rerender(); toast('Result deleted'); }
  },
  exportSurveys: () => exportXLSX('satisfaction_survey', REPORTS.satisfaction.head(), REPORTS.satisfaction.rows(), 'Satisfaction Survey'),
  async photoMain(d) {
    const a = area(d.id);
    a.photos.forEach(p => (p.main = p.id === d.pid));
    if (await save(`Set main photo – ${a.name}`)) { closeModal(); rerender(); toast('Main photo updated'); }
  },
  async photoDelete(d) {
    const a = area(d.id);
    if (!confirm('Delete this photo?')) return;
    const wasMain = (a.photos.find(p => p.id === d.pid) || {}).main;
    a.photos = a.photos.filter(p => p.id !== d.pid);
    if (wasMain && a.photos[0]) a.photos[0].main = true;
    if (await save(`Delete photo – ${a.name}`)) { closeModal(); rerender(); toast('Photo deleted'); }
  },
  docDownload: d => {
    const doc = area(d.id).docs.find(x => x.id === d.did);
    if (doc) { const l = document.createElement('a'); l.href = doc.src; l.download = doc.name; document.body.appendChild(l); l.click(); l.remove(); }
  },
  async docDelete(d) {
    const a = area(d.id), doc = a.docs.find(x => x.id === d.did);
    if (!doc || !confirm('Delete this document?')) return;
    a.docs = a.docs.filter(x => x !== doc);
    if (await save(`Delete document "${doc.name}" – ${a.name}`)) { rerender(); toast('Document deleted'); }
  },
  qrModal: d => qrModal(area(d.id)),
  printLabel: d => printLabels([area(d.id)]),
  printAllLabels: () => printLabels(DB.areas),
  printLabelsFiltered: () => printLabels(filteredAreas()),
  copyLink: d => { navigator.clipboard?.writeText(d.url).then(() => toast('Link copied'), () => toast('Copy failed', true)); },
  async deleteArea(d) {
    const a = area(d.id);
    if (!confirm(`Delete ${a.name}?\n\nIts photos, documents, surveys and history are kept in the database and can be restored from Settings → Recycle Bin.`)) return;
    DB.areas = DB.areas.filter(x => x.id !== a.id);
    DB.history = DB.history.filter(h => h.areaId !== a.id);
    if (await save(`Delete break area – ${a.name}`)) { closeModal(); location.hash = '#/areas'; toast('Break area deleted'); }
  },
  areaLog: d => { F.log = { tab: 'audit', q: '', user: '', type: '', area: d.id, from: '', to: '' }; location.hash = '#/logs'; },
  exportAreas: () => exportXLSX('break_areas', areaHead(), areaRows(filteredAreas())),
  exportHist: d => { const a = area(d.id); exportXLSX(a.name.replace(/\s+/g, '_') + '_history', TX_HEAD, txExportRows(filteredHist(a))); },
  exportTx: () => exportXLSX('transactions', TX_HEAD, txExportRows(filteredTx())),
  printTx: () => printTable('Transactions', TX_HEAD, txExportRows(filteredTx()).map(r => [fmt(r[0]), ...r.slice(1)])),
  clearTx: () => { F.tx = { q: '', area: '', item: '', action: '', from: '', to: '' }; rerender(); },
  exportEquip: () => exportXLSX('inventory_by_area', REPORTS.inventory.head(), REPORTS.inventory.rows()),
  exportIssues: () => exportXLSX('issues', REPORTS.issues.head(), REPORTS.issues.rows()),
  itemTypeModal: d => itemTypeModal(d.tid),
  runReport: (d, el) => {
    const r = REPORTS[d.k], card = el.closest('.card');
    const from = card.querySelector('[name=from]')?.value || '', to = card.querySelector('[name=to]')?.value || '';
    const rows = r.rows(from, to);
    if (d.mode === 'xlsx') exportXLSX(d.k, r.head(), rows, r.title);
    else printTable(r.title + (from || to ? ` (${from ? fmt(from) : '…'} – ${to ? fmt(to) : '…'})` : ''), r.head(), rows);
  },
  async fullExport() {
    toast('Preparing the Excel file…', false, 30000);
    try {
      download(`BAMS_Full_Export_${today()}.xlsx`, await api('GET', '/api/export.xlsx', undefined, { blob: true }));
      toast('Full export downloaded');
    } catch (e) { toast('Export failed: ' + e.message, true); }
  },
  async removeLogo() { DB.settings.logoImage = ''; if (await save('Remove logo image')) rerender(); },
  async loadDemo() {
    if (DB.areas.length && !confirm('Replace the current data with the sample data?')) return;
    if (await loadSample()) { rerender(); toast('Sample data loaded'); }
  },
  async clearAll() {
    const n = DB.areas.length;
    const answer = prompt(`This deletes ALL ${n} break areas with their inventory, photos, documents, issues, surveys and history, so you can start with your real data.\n\nA backup is made first, and everything stays restorable from the Recycle Bin.\n\nType DELETE to confirm:`);
    if ((answer || '').trim().toUpperCase() !== 'DELETE') return toast('Nothing was deleted');
    DB.areas = []; DB.history = [];
    if (await save(`Delete all data – start fresh (${n} break areas)`, { force: true })) { location.hash = '#/dashboard'; rerender(); toast('All data deleted – you can now add your real break areas'); }
  },
  async backupNow() {
    try { const r = await api('POST', '/api/backups', {}); toast('Backup created: ' + r.name); rerender(); }
    catch (e) { toast('Backup failed: ' + e.message, true, 8000); }
  },
  async backupRestore(d) {
    if (!confirm(`Restore the backup from ${d.time.replace('T', ' ')}?\n\nALL data will go back to that moment for every user. The current data is saved as a new backup first, so you can undo this.`)) return;
    try {
      const r = await api('POST', '/api/backups/restore', { name: d.name });
      await load(); rerender();
      toast('Backup restored. Previous data saved as ' + r.safety, false, 8000);
    } catch (e) { toast('Restore failed: ' + e.message, true, 8000); }
  },
  async trashRestore(d) {
    try { await api('POST', '/api/trash/restore', { txn: d.txn }); await load(); rerender(); toast('Records restored'); }
    catch (e) { toast('Restore failed: ' + e.message, true, 8000); }
  },
  logTab: d => { F.log = { tab: d.tab, q: '', user: '', type: '', area: '', from: '', to: '' }; rerender(); },
  logRefresh: () => rerender(),
  logClear: () => { F.log = { tab: F.log.tab, q: '', user: '', type: '', area: '', from: '', to: '' }; rerender(); },
  async logMore(d, el) {
    el.disabled = true;
    try {
      const r = await logQuery(LOGDATA.rows.length);
      LOGDATA.rows.push(...r.rows);
      $('[data-async=logTable]').innerHTML = logTableHTML();
    } catch (e) { el.disabled = false; toast(e.message, true); }
  },
  async logExport() {
    const audit = F.log.tab === 'audit', rows = [];
    try {
      for (let off = 0; off < 50000; off += 1000) {
        const r = await logQuery(off, 1000);
        rows.push(...r.rows);
        if (rows.length >= r.total || !r.rows.length) break;
      }
    } catch (e) { return toast('Export failed: ' + e.message, true); }
    if (audit) exportXLSX('data_changes_log', ['Time', 'User', 'IP', 'Action', 'Table', 'Record ID', 'Break Area', 'Operation', 'Changes / Record'],
      rows.map(r => [r.ts, r.user, r.ip, r.label, ENTITY_NAME[r.entity] || r.entity, r.entity_id, (area(r.area_id) || {}).name || r.area_id || '', (OP_BADGE[r.op] || [r.op])[0], r.op === 'update' ? r.changes : r.after || r.before]), 'Data Changes');
    else if (F.log.tab === 'security') exportXLSX('security_log', ['Time', 'User', 'IP', 'Event', 'Account / Target', 'Details'],
      rows.map(r => [r.ts, r.user, r.ip, SEC_LABEL[r.event] || r.event, r.target, r.detail]), 'Logins & Security');
    else exportXLSX('user_activity_log', ['Time', 'User', 'IP', 'Type', 'Action', 'Target', 'Page', 'Detail'],
      rows.map(r => [r.ts, r.user, r.ip, r.type, r.action, r.target, r.page, r.detail]), 'User Activity');
  }
};

document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]');
  if (!el || !ACT[el.dataset.act]) return;
  if (el.tagName === 'A' && !el.dataset.href) return;
  e.preventDefault();
  ACT[el.dataset.act](el.dataset, el, e);
});

function onFilter(e) {
  const el = e.target;
  if (!el.dataset || !el.dataset.f) return;
  const [grp, key] = el.dataset.f.split('.');
  F[grp][key] = el.value;
  const target = $(`[data-results="${el.dataset.res}"]`);
  if (target) RESULTS[el.dataset.res](target);
}
let logTimer;
function onLogFilter(e) {
  const el = e.target;
  if (!el.dataset || !el.dataset.logf) return;
  F.log[el.dataset.logf] = el.value;
  clearTimeout(logTimer);
  logTimer = setTimeout(() => {
    const t = $('[data-async=logTable]');
    if (t) ASYNC.logTable(t).catch(err => toast(err.message, true));
  }, e.type === 'input' ? 350 : 0);
}
document.addEventListener('input', e => { onFilter(e); if (e.target.tagName === 'INPUT' && e.target.type !== 'date') onLogFilter(e); });
document.addEventListener('change', async e => {
  onFilter(e);
  if (e.target.dataset.f) track('filter', e.target.dataset.f, e.target.value);
  if (e.target.dataset.logf && (e.target.tagName === 'SELECT' || e.target.type === 'date')) onLogFilter(e);
  if (e.target.dataset.actChange === 'importBackup') {
    const f = e.target.files[0];
    e.target.value = '';
    if (f) await importOldBackup(f);
  }
});

document.addEventListener('submit', async e => {
  const f = e.target;
  if (f.dataset.form === 'login' || f.dataset.form === 'setup') { e.preventDefault(); await submitAuth(f); }
  if (f.dataset.form === 'newArea') { e.preventDefault(); await submitNewArea(f); }
  if (f.dataset.form === 'settings') {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f));
    Object.assign(DB.settings, {
      systemName: d.systemName.trim() || 'Break Area Management System', factory: d.factory.trim(), logoText: d.logoText.trim(),
      inspectionDays: Math.max(1, +d.inspectionDays || 30), satisfactionTarget: Math.min(100, Math.max(1, +d.satisfactionTarget || 80)),
      locations: d.locations.split('\n').map(x => x.trim()).filter(Boolean)
    });
    if (f.logo.files[0]) {
      try { DB.settings.logoImage = await uploadFile(await resizeImage(f.logo.files[0], 400, true), 'logo.jpg'); }
      catch (err) { return toast('Logo upload failed: ' + err.message, true); }
    }
    if (await save('Edit settings')) { rerender(); toast('Settings saved'); }
  }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#modal').dataset.locked) closeModal(); });
window.addEventListener('hashchange', () => {
  if (!ME || !DB) return;
  if (!$('#modal').dataset.locked) closeModal();
  F.hist = { item: '', action: '' }; F.photoTab = 'All';
  track('navigate', location.hash);
  render(); scrollTo(0, 0);
});

/* Hover tooltip for chart points and bars ([data-tip]) */
const TIP = document.createElement('div');
TIP.id = 'tip';
document.body.appendChild(TIP);
document.addEventListener('mouseover', e => {
  const el = e.target.closest('[data-tip]');
  TIP.classList.toggle('show', !!el);
  if (el) TIP.textContent = el.dataset.tip;
});
document.addEventListener('mousemove', e => {
  if (!TIP.classList.contains('show')) return;
  const x = Math.min(e.clientX + 14, innerWidth - TIP.offsetWidth - 8);
  TIP.style.transform = `translate(${x}px, ${e.clientY + 16}px)`;
});

/* Pick up changes made on other PCs (only when the user is not in the middle of something) */
setInterval(async () => {
  if (!DB || !ME || document.hidden || $('#modal').classList.contains('open')) return;
  if (/^#\/(areas\/new|settings)/.test(location.hash)) return;
  const ae = document.activeElement;
  if (ae && /^(INPUT|TEXTAREA|SELECT)$/.test(ae.tagName) && ae.closest('#view')) return;
  try {
    const { version, me: mv } = await api('GET', '/api/version');
    if (mv !== ME.ver) { // the administrator changed this account - apply the new permissions right away
      ME = await api('GET', '/api/me');
      if (ME.must_change) return start();
      await load(); rerender();
      toast('Your permissions were updated by the administrator', false, 5000);
    } else if (version !== DB.version) { await load(); rerender(); }
  } catch (e) { /* server briefly unreachable – try again next time */ }
}, 10000);

const serverDown = e => {
  document.body.classList.add('locked');
  $('#auth').innerHTML = `<div class="auth-card"><div class="kic red" style="margin:0 auto 10px">${ic('alert')}</div><h2>Cannot connect to the server</h2>
    <p>${esc(e.message)}</p><p class="hint">Start the system with <b>start.bat</b> on the server PC, then open the address shown in its window.
    Opening index.html directly from the folder does not work.</p><button class="btn" data-act="reloadPage">${ic('restore')}Try again</button></div>`;
};
/* After a successful login: load the data the user may see and show their start page */
async function start() {
  if (ME.must_change) {
    authScreen(`<h2>Welcome, ${esc(ME.full_name)}</h2><p class="muted">Please choose your own password to continue.</p>`);
    return passwordModal(true);
  }
  document.body.classList.remove('locked');
  $('#auth').innerHTML = '';
  try { await load(); } catch (e) { if (ME) serverDown(e); return; }
  if (!DB.initialized && !DB.areas.length && can('data.import')) {
    try {
      const r = await api('POST', '/api/first-run', {});
      if (r.loadSample) await loadSample();
      else await load(); // another PC is loading it right now
    } catch (e) { /* the welcome screen offers "Load Sample Data" */ }
  }
  if (!canPage(parseRoute()[0])) history.replaceState(null, '', '#/' + firstPage());
  render();
  track('session', 'open', navigator.userAgent);
  try {
    const info = await api('GET', '/api/info');
    // QR codes must point to an address phones can reach, not "localhost"
    if (/^(localhost|127\.|\[::1\])/.test(location.hostname)) {
      const lan = info.urls.find(u => /\/\/\d+\.\d+\.\d+\.\d+/.test(u)) || info.urls[0];
      if (lan) { BASE_URL = lan; if (!$('#modal').classList.contains('open')) rerender(); }
    }
  } catch (e) { /* QR falls back to the current address */ }
}
async function boot() {
  let st;
  try { st = await api('GET', '/api/auth/status'); } catch (e) { return serverDown(e); }
  if (!st.hasUsers) return showSetup(st.local);
  if (!st.me) return showLogin();
  await afterLogin(st.me);
}
boot();
