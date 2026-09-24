/* Break Area Management System – single page application.
   Data is kept in the browser (localStorage) so the prototype runs without a server. */
'use strict';

const KEY = 'bams-data-v1';
let DB;

/* ============================== Storage ============================== */
function load() {
  try {
    const s = localStorage.getItem(KEY);
    if (s) { DB = JSON.parse(s); return; }
  } catch (e) { /* fall through to seed */ }
  DB = buildSeed();
  save();
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(DB)); return true; }
  catch (e) { toast('Storage is full – remove some photos or documents', true); return false; }
}

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
const areaURL = id => location.href.split('#')[0] + '#/area/' + id;
const setting = k => DB.settings[k];

function setQty(a, item, value, condition) {
  let e = invEntry(a, item);
  if (!e) { e = { item, qty: 0, condition: 'Good' }; a.inventory.push(e); }
  e.qty = Math.max(0, value);
  if (condition) e.condition = condition;
}
function pushHistory(rec) {
  DB.seq = (DB.seq || 1000) + 1;
  DB.history.push({ id: 'h' + DB.seq, seq: DB.seq, ...rec });
}

function toast(msg, error) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'show' + (error ? ' error' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ''), 2600);
}

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
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>'
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
const photoHTML = p => p && p.src
  ? `<img src="${p.src}" alt="${esc(p.caption)}" loading="lazy">`
  : roomSVG(p ? (p.seed || p.id) : 'x', p ? p.variant : 'seating');

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
function exportCSV(name, head, rows) {
  const cell = v => { v = v == null ? '' : String(v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
  const text = [head, ...rows].map(r => r.map(cell).join(',')).join('\r\n');
  download(name + '_' + today() + '.csv', '﻿' + text, 'text/csv;charset=utf-8');
  toast('Exported ' + rows.length + ' rows');
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
    <h2>${esc(title)}</h2><div>${esc(setting('factory'))} · Printed ${fmt(today())} by ${esc(setting('userName'))}</div>
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
  $('#user').innerHTML = `<div class="avatar">${esc(initials(s.userName))}</div><div class="who"><b>${esc(s.userName)}</b><small>${esc(s.userRole)}</small></div>`;
  $('.menu-btn').innerHTML = ic('menu');

  const top = route[0];
  const areasOpen = top === 'areas' || top === 'area';
  const link = (href, icon, label, active, extra = '') => `<a href="${href}" class="${active ? 'active' : ''}">${ic(icon)}<span>${label}</span>${extra}</a>`;
  $('#sidebar').innerHTML = `<div class="nav">
      ${link('#/dashboard', 'dashboard', 'Dashboard', top === 'dashboard')}
      ${link('#/areas', 'building', 'Break Areas', areasOpen, ic(areasOpen ? 'chevD' : 'chevR', 'chev'))}
      ${areasOpen ? `<div class="sub">
        <a href="#/areas" class="${top === 'areas' && route[1] !== 'new' || top === 'area' ? 'active' : ''}">All Break Areas</a>
        <a href="#/areas/new" class="${route[1] === 'new' ? 'active' : ''}">Add New Break Area</a></div>` : ''}
      ${link('#/equipment', 'sofa', 'Furniture &amp; Equipment', top === 'equipment')}
      ${link('#/transactions', 'swap', 'Transactions', top === 'transactions')}
      ${link('#/maintenance', 'wrench', 'Maintenance', top === 'maintenance')}
      ${link('#/reports', 'report', 'Reports', top === 'reports')}
      ${link('#/settings', 'settings', 'Settings', top === 'settings')}
    </div>
    <div class="side-foot"><b>Better Break Areas</b>for a better workplace.</div>`;
}

const parseRoute = () => (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/');

function render() {
  const route = parseRoute();
  document.body.classList.remove('nav-open');
  renderShell(route);
  const v = $('#view');
  const [top, id] = route;
  if (top === 'area' && area(id)) v.innerHTML = viewArea(area(id));
  else if (top === 'areas' && id === 'new') v.innerHTML = viewAreaForm();
  else if (top === 'areas') v.innerHTML = viewAreas();
  else if (top === 'equipment') v.innerHTML = viewEquipment();
  else if (top === 'transactions') v.innerHTML = viewTransactions();
  else if (top === 'maintenance') v.innerHTML = viewMaintenance();
  else if (top === 'reports') v.innerHTML = viewReports();
  else if (top === 'settings') v.innerHTML = viewSettings();
  else v.innerHTML = viewDashboard();
  $$('[data-results]', v).forEach(el => RESULTS[el.dataset.results](el));
}
function rerender() { const y = scrollY; render(); scrollTo(0, y); }

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

/* ============================== Dashboard ============================== */
const F = { dash: { q: '', status: '' }, areas: { q: '', loc: '', status: '', active: '' }, tx: { q: '', area: '', item: '', action: '', from: '', to: '' }, hist: { item: '', action: '' }, photoTab: 'All' };

function viewDashboard() {
  const A = DB.areas;
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
    <div class="card"><div class="card-h"><h3>Furniture &amp; Equipment Overview</h3><span class="sp"></span><a class="link" href="#/equipment">Details</a></div>${vbars(equip)}</div>
    <div class="card"><div class="card-h"><h3>Break Areas by Location</h3></div>${hbars(locs)}</div>
  </div>

  <div class="card mb">
    <div class="card-h"><h3>Recent Updates</h3><span class="sp"></span><a class="link" href="#/transactions">View All</a></div>
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
      <div class="card-h"><h3>Recent Transactions</h3><span class="sp"></span><a class="link" href="#/transactions">View All</a></div>
      <ul class="tx-list">${tx.map(txRow).join('') || '<li class="muted">No transactions yet</li>'}</ul>
    </div>
  </div>`;
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
  areas(el) {
    const rows = filteredAreas();
    el.innerHTML = rows.map(a => {
      const nd = daysFromToday(a.nextInspection);
      return `<tr class="click" data-act="go" data-href="#/area/${a.id}">
        <td><span class="thumb-s ph">${photoHTML(mainPhoto(a))}</span></td><td><b>${esc(a.name)}</b></td><td>${esc(a.location)}</td><td>${esc(a.building)} / ${esc(a.floor)}</td>
        <td class="num">${a.capacity}</td><td class="num">${qty(a, 'chairs')}</td><td class="num">${qty(a, 'tables')}</td><td class="num">${qty(a, 'tv')}</td><td class="num">${qty(a, 'water')}</td>
        <td>${esc(a.responsible)}</td><td>${badge(a.status)}</td><td class="${nd < 0 ? 'overdue' : ''}">${fmt(a.nextInspection)}</td>
        <td class="num">${openIssues(a).length || '-'}</td><td>${fmt(lastUpdate(a))}</td></tr>`;
    }).join('') || `<tr><td colspan="14" class="empty">No break areas match the filters</td></tr>`;
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
    ...DB.itemTypes.map(t => qty(a, t.id)), a.lastInspection, a.nextInspection, openIssues(a).length, lastUpdate(a), areaURL(a.id)]);
}
const areaHead = () => ['Break Area', 'Location', 'Building', 'Floor', 'Start Date', 'Area Size (m2)', 'Capacity', 'Responsible', 'Status', 'Operational',
  ...DB.itemTypes.map(t => t.name), 'Last Inspection', 'Next Inspection', 'Open Issues', 'Last Update', 'Profile Link'];

function viewAreas() {
  const f = F.areas;
  const opt = (list, v) => list.map(x => `<option ${v === x ? 'selected' : ''}>${esc(x)}</option>`).join('');
  return `<div class="page-head"><h2>Break Areas</h2><span class="muted" id="areaCount"></span>
    <div class="actions">
      <button class="btn" data-act="exportAreas">${ic('download')}Export Excel</button>
      <button class="btn" data-act="printLabelsFiltered">${ic('qr')}Print QR Labels</button>
      <a class="btn primary" href="#/areas/new">${ic('plus')}Add New Break Area</a>
    </div></div>
  <div class="card">
    <div class="card-h filters">
      <label class="search">${ic('search')}<input data-f="areas.q" data-res="areas" placeholder="Search name, building, person..." value="${esc(f.q)}"></label>
      <select data-f="areas.loc" data-res="areas"><option value="">All locations</option>${opt(setting('locations'), f.loc)}</select>
      <select data-f="areas.status" data-res="areas"><option value="">All statuses</option>${opt(STATUSES, f.status)}</select>
      <select data-f="areas.active" data-res="areas"><option value="">Active &amp; inactive</option>${opt(['Active', 'Inactive'], f.active)}</select>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Break Area</th><th>Location</th><th>Building / Floor</th><th class="num">Capacity</th><th class="num">Chairs</th><th class="num">Tables</th><th class="num">TV</th><th class="num">Water</th><th>Responsible</th><th>Status</th><th>Next Inspection</th><th class="num">Open Issues</th><th>Last Update</th></tr></thead>
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
    ${inp('responsible', 'Responsible Person', a.responsible ?? setting('userName'))}
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
  const a = { id, inventory: [], photos: [], docs: [], issues: [], maintenance: [], inspections: [], lastInspection: '', nextInspection: addDays(d.startDate || today(), setting('inspectionDays')), inspectedBy: '' };
  applyAreaFields(a, d);
  DB.itemTypes.forEach(t => { const q = +d['qty_' + t.id] || 0; if (q > 0) a.inventory.push({ item: t.id, qty: q, condition: d['cond_' + t.id] }); });
  for (const f of form.photos.files) {
    if (!f.type.startsWith('image/')) continue;
    a.photos.push({ id: uid(), caption: f.name.replace(/\.[^.]+$/, ''), category: 'Current', date: today(), src: await resizeImage(f), main: !a.photos.length });
  }
  if (!a.photos.length) a.photos.push({ id: uid(), caption: 'Seating Area', variant: 'seating', seed: id + 'seating', category: 'Current', date: today(), main: true });
  DB.areas.push(a);
  const summary = a.inventory.map(i => `${i.qty} ${itemName(i.item)}`).join(', ');
  pushHistory({ areaId: id, date: a.startDate, item: 'Initial Setup', action: 'Created', prev: null, next: null, details: 'Break area created' + (summary ? ' with ' + summary : ''), by: setting('userName') });
  if (save()) { toast(a.name + ' created'); location.hash = '#/area/' + id; }
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
    ['plus', '#16a34a', 'Add New Item', 'invModal'], ['alert', '#dc2626', 'Report Issue', 'issueModal'],
    ['calendar', '#f59e0b', 'Schedule Maintenance', 'maintModal'], ['upload', '#1d4ed8', 'Upload Photo / Document', 'uploadModal']
  ];
  const tasks = [...a.issues.map(i => ({ ...i, kind: 'Issue' })), ...a.maintenance.map(m => ({ ...m, kind: 'Maintenance', title: m.details }))].sort(byDateDesc);

  return `
  <div class="page-head">
    <a class="btn" href="#/areas">${ic('arrowLeft')}Back to Break Areas</a>
    <h2>${esc(a.name)}</h2>${badge(a.active === false ? 'Inactive' : 'Active')}
    <span class="loc">${ic('pin')}${esc(a.location)} Area</span>
    <div class="actions">
      <button class="btn" data-act="editArea" data-id="${a.id}">${ic('edit')}Edit</button>
      <button class="btn" data-act="toHistory">${ic('history')}View History</button>
      <button class="btn primary" data-act="invModal" data-id="${a.id}">${ic('plus')}Add New</button>
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
      ${qa.map(([i, c, l, act]) => `<button class="qa-item" data-act="${act}" data-id="${a.id}"><span class="qa-ic" style="background:${c}">${ic(i)}</span>${l}</button>`).join('')}
    </div>
    <div class="card d-photos">
      <div class="card-h"><h3>Photos</h3><span class="muted">(${a.photos.length})</span><span class="sp"></span>
        <div class="tabs">${['All', ...PHOTO_CATEGORIES].map(t => `<button data-act="photoTab" data-tab="${t}" class="${F.photoTab === t ? 'on' : ''}">${t}</button>`).join('')}</div></div>
      <div class="thumbs">
        ${photos.map(p => `<div class="thumb" data-act="viewPhoto" data-id="${a.id}" data-pid="${p.id}"><div class="ph">${photoHTML(p)}</div><span>${esc(p.caption)}</span></div>`).join('')}
        <div class="thumb add" data-act="uploadModal" data-id="${a.id}"><div class="ph">${ic('plus')}</div><span>Add Photo</span></div>
      </div>
    </div>
  </div>

  <div class="detail-mid">
    <div class="card">
      <div class="card-h"><h3>Inventory / Contents</h3><span class="sp"></span><button class="btn sm" data-act="invModal" data-id="${a.id}">${ic('edit')}Update</button></div>
      <div class="inv">${a.inventory.map(e => `<div class="inv-tile" data-act="invModal" data-id="${a.id}" data-item="${e.item}" title="${esc(e.note || '')}">
        ${itemIcon(e.item)}<div class="n">${esc(itemName(e.item))}</div><div class="q">${e.qty}</div>${badge(e.condition || 'Good')}</div>`).join('') || '<p class="muted">No items recorded yet.</p>'}</div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Inspection</h3><span class="sp"></span>${inspState}</div>
      <div class="insp-row">${ic('calCheck')}<div><small>Last Inspection</small><b>${fmt(a.lastInspection)}</b></div></div>
      <div class="insp-row">${ic('calendar')}<div><small>Next Inspection</small><b class="${nd != null && nd < 0 ? 'overdue' : ''}">${fmt(a.nextInspection)}</b></div></div>
      <div class="insp-row">${ic('user')}<div><small>Inspected By</small><b>${esc(a.inspectedBy || '-')}</b></div></div>
      <button class="btn sm" style="margin-top:8px;width:100%" data-act="inspModal" data-id="${a.id}">${ic('clipboard')}Record Inspection</button>
    </div>
    <div class="card">
      <div class="card-h"><h3>Open Issues</h3></div>
      <div class="issue-counts">
        <div style="background:var(--orange-l);color:#b45309"><b>${oi.length}</b>Open</div>
        <div style="background:var(--green-l);color:#15803d"><b>${closed}</b>Closed</div>
      </div>
      <ul class="issue-list">${oi.slice(0, 3).map(i => `<li data-act="issueView" data-id="${a.id}" data-iid="${i.id}">${badge(i.priority)}<span>${esc(i.title)}</span></li>`).join('')}</ul>
      <button class="link" data-act="issueModal" data-id="${a.id}">${ic('alert')} Report New Issue</button>
    </div>
  </div>

  <div class="card mb" id="history">
    <div class="card-h"><h3>Update History</h3><span class="sp"></span>
      <div class="filters">
        <select data-f="hist.item" data-res="hist"><option value="">All items</option>${histItems.map(x => `<option ${f.item === x ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select>
        <select data-f="hist.action" data-res="hist"><option value="">All actions</option>${['Created', ...ACTIONS].map(x => `<option ${f.action === x ? 'selected' : ''}>${x}</option>`).join('')}</select>
        <button class="btn sm" data-act="exportHist" data-id="${a.id}">${ic('download')}Export</button>
      </div>
    </div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>#</th><th>Date</th><th>Item</th><th>Action</th><th class="num">Previous Qty</th><th class="num">New Qty</th><th>Details</th><th>Updated By</th></tr></thead>
    <tbody data-results="hist" data-area="${a.id}"></tbody></table></div>
  </div>

  <div class="grid2">
    <div class="card">
      <div class="card-h"><h3>Issues &amp; Maintenance</h3><span class="sp"></span><button class="btn sm" data-act="maintModal" data-id="${a.id}">${ic('calendar')}Schedule</button></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th>Type</th><th>Description</th><th>Status</th><th></th></tr></thead><tbody>
      ${tasks.map(t => `<tr><td>${fmt(t.date)}</td><td>${t.kind === 'Issue' ? badge(t.priority) : '<span class="badge b-purple">Maintenance</span>'}</td>
        <td class="wrap">${esc(t.title)}${t.item ? ` <span class="muted">· ${esc(itemShort(t.item))}</span>` : ''}</td><td>${badge(t.status)}</td>
        <td>${t.kind === 'Issue' ? `<button class="btn sm" data-act="issueView" data-id="${a.id}" data-iid="${t.id}">Follow up</button>`
          : t.status !== 'Done' ? `<button class="btn sm" data-act="maintDone" data-id="${a.id}" data-mid="${t.id}">Complete</button>` : ''}</td></tr>`).join('')
        || '<tr><td colspan="5" class="empty">No issues or maintenance recorded</td></tr>'}
      </tbody></table></div>
    </div>
    <div class="card">
      <div class="card-h"><h3>Documents &amp; Reports</h3><span class="sp"></span><button class="btn sm" data-act="uploadModal" data-id="${a.id}" data-cat="Document">${ic('upload')}Upload</button></div>
      <ul class="doc-list">${a.docs.map(d => `<li>${ic('file')}<div class="t"><b>${esc(d.name)}</b><small>${fmt(d.date)} · ${fileSize(d.size)}${d.caption ? ' · ' + esc(d.caption) : ''}</small></div>
        <button class="icon-btn" title="Download" data-act="docDownload" data-id="${a.id}" data-did="${d.id}">${ic('download')}</button>
        <button class="icon-btn" title="Delete" data-act="docDelete" data-id="${a.id}" data-did="${d.id}">${ic('trash')}</button></li>`).join('')
        || '<li class="muted">No documents uploaded yet (inspection reports, invoices, layouts...)</li>'}</ul>
    </div>
  </div>`;
}
function filteredHist(a) {
  return areaHistory(a.id).filter(h => (!F.hist.item || histItem(h) === F.hist.item) && (!F.hist.action || h.action === F.hist.action));
}

/* ============================== Modals ============================== */
function modal(title, body, { submit = 'Save', onSubmit, wide = false, extra = '' } = {}) {
  const m = $('#modal');
  m.innerHTML = `<div class="modal-back" data-act="closeModal"></div>
    <form class="modal ${wide ? 'wide' : ''}" novalidate>
      <div class="modal-h"><h3>${title}</h3><button type="button" class="icon-btn" data-act="closeModal" aria-label="Close">${ic('x')}</button></div>
      <div class="modal-b">${body}</div>
      <div class="modal-f">${extra}<span class="sp"></span><button type="button" class="btn" data-act="closeModal">${onSubmit ? 'Cancel' : 'Close'}</button>${onSubmit ? `<button class="btn primary">${submit}</button>` : ''}</div>
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
    } finally { btn.disabled = false; }
  };
  const first = $('input:not([type=hidden]),select,textarea', form);
  if (first && matchMedia('(min-width: 821px)').matches) first.focus();
  return form;
}
function closeModal() { const m = $('#modal'); m.classList.remove('open'); m.innerHTML = ''; }

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
    <label>Updated By<input name="by" value="${esc(setting('userName'))}" required></label>
    <label class="full">Details / Remarks<textarea name="details" placeholder="e.g. Added 10 new chairs from supplier X"></textarea></label>
  </div>`;
  const form = modal(`Update Inventory – ${esc(a.name)}`, body, {
    submit: 'Save Update',
    onSubmit(d) {
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
      if (save()) toast('Inventory updated');
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
  sync();
}

function issueModal(a) {
  modal(`Report Issue – ${esc(a.name)}`, `<div class="form-grid">
    <label class="full">Issue Title<input name="title" required placeholder="e.g. Broken chair, water leak..."></label>
    <label>Related Item<select name="item"><option value="">General / Area</option>${itemOptions('')}</select></label>
    <label>Priority<select name="priority">${options(PRIORITIES, 'Medium')}</select></label>
    <label>Date<input type="date" name="date" value="${today()}"></label>
    <label>Reported By<input name="by" value="${esc(setting('userName'))}" required></label>
    <label class="full">Details<textarea name="details"></textarea></label>
    <label class="full check"><input type="checkbox" name="flag" ${a.status === 'Good' ? 'checked' : ''}> Set break area status to "Need Maintenance"</label>
  </div>`, {
    submit: 'Report Issue',
    onSubmit(d) {
      a.issues.push({ id: uid(), date: d.date, title: d.title.trim(), item: d.item, priority: d.priority, status: 'Open', reportedBy: d.by, details: d.details, log: [] });
      if (d.flag) a.status = 'Need Maintenance';
      if (save()) toast('Issue reported');
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
    submit: 'Save Follow-up', wide: true,
    extra: `<button type="button" class="btn danger" data-act="issueDelete" data-id="${a.id}" data-iid="${i.id}">${ic('trash')}Delete</button>`,
    onSubmit(d) {
      if (!d.text.trim() && d.status === i.status) { toast('Add a note or change the status', true); return false; }
      i.log = i.log || [];
      i.log.push({ date: d.date, by: setting('userName'), text: (d.status !== i.status ? `Status changed to ${d.status}. ` : '') + d.text.trim() });
      i.status = d.status;
      i.closedDate = d.status === 'Closed' ? d.date : '';
      if (save()) toast('Issue updated');
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
    onSubmit(d) {
      a.maintenance.push({ id: uid(), date: d.date, item: d.item, assignedTo: d.assignedTo, details: d.details.trim(), status: 'Scheduled' });
      if (d.status !== 'Keep current status') a.status = d.status;
      if (save()) toast('Maintenance scheduled');
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
    onSubmit(d) {
      m.status = 'Done'; m.doneDate = d.date; m.notes = d.notes;
      a.status = d.status;
      const q = m.item ? qty(a, m.item) : null;
      pushHistory({ areaId: a.id, date: d.date, item: m.item || 'area', action: 'Maintenance', prev: q, next: q, details: m.details + (d.notes ? '. ' + d.notes : ''), by: m.assignedTo });
      if (save()) toast('Maintenance completed');
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
  ${a.inspections.length ? `<b>Previous inspections</b><table class="tbl" style="margin-top:6px"><thead><tr><th>Date</th><th>By</th><th>Result</th><th>Notes</th></tr></thead><tbody>
    ${[...a.inspections].sort(byDateDesc).map(i => `<tr><td>${fmt(i.date)}</td><td>${esc(i.by)}</td><td>${badge(i.result)}</td><td class="wrap">${esc(i.notes || '')}</td></tr>`).join('')}</tbody></table>` : ''}`, {
    submit: 'Save Inspection', wide: true,
    onSubmit(d) {
      a.inspections.push({ id: uid(), date: d.date, by: d.by, result: d.result, notes: d.notes });
      if (!a.lastInspection || d.date >= a.lastInspection) { a.lastInspection = d.date; a.inspectedBy = d.by; a.nextInspection = d.next; }
      if (save()) toast('Inspection recorded');
    }
  });
  form.date.addEventListener('change', () => { form.next.value = addDays(form.date.value, days); });
}

function resizeImage(file, max = 1280) {
  return new Promise((res, rej) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      res(c.toDataURL('image/jpeg', .78));
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error('bad image')); };
    img.src = url;
  });
}
const readDataURL = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });

function uploadModal(a, cat = 'Current') {
  modal(`Upload Photo / Document – ${esc(a.name)}`, `<div class="form-grid">
    <label class="full">Files<input type="file" name="files" multiple required accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt"></label>
    <label>Category<select name="category">${options([...PHOTO_CATEGORIES.map(c => [c, c + ' Photo']), ['Document', 'Document / Report']], cat)}</select></label>
    <label>Caption / Title<input name="caption" placeholder="e.g. Seating area after renovation"></label>
    <p class="full hint">Images are resized automatically. Documents up to 2 MB each in this prototype (the server version has no such limit).</p>
  </div>`, {
    submit: 'Upload',
    async onSubmit(d, form) {
      const files = [...form.files.files];
      if (!files.length) { toast('Choose at least one file', true); return false; }
      let added = 0;
      for (const f of files) {
        const isImg = f.type.startsWith('image/');
        const caption = d.caption.trim() || f.name.replace(/\.[^.]+$/, '');
        if (isImg && d.category !== 'Document') {
          a.photos.push({ id: uid(), caption, category: d.category, date: today(), src: await resizeImage(f) });
          added++;
        } else {
          if (f.size > 2 * 1048576) { toast(`${f.name} is larger than 2 MB`, true); continue; }
          a.docs.push({ id: uid(), name: f.name, caption: d.caption.trim(), size: f.size, type: f.type, date: today(), src: await readDataURL(f) });
          added++;
        }
      }
      if (!added) return false;
      if (d.category === 'Before' || d.category === 'After') F.photoTab = d.category;
      if (save()) toast(added + ' file(s) uploaded');
    }
  });
}

function viewPhoto(a, pid) {
  const p = a.photos.find(x => x.id === pid);
  if (!p) return uploadModal(a);
  modal(esc(p.caption), `<div class="viewer"><div class="ph">${photoHTML(p)}</div>
    <p class="muted" style="margin:10px 0 0">${badge(p.category)} &nbsp;Uploaded ${fmt(p.date)}${p.main ? ' · <b>Main photo</b>' : ''}${p.src ? '' : ' · Placeholder image – upload a real photo to replace it'}</p></div>`, {
    wide: true,
    extra: `<button type="button" class="btn danger" data-act="photoDelete" data-id="${a.id}" data-pid="${p.id}">${ic('trash')}Delete</button>
      ${p.main ? '' : `<button type="button" class="btn" data-act="photoMain" data-id="${a.id}" data-pid="${p.id}">${ic('star')}Set as Main Photo</button>`}`
  });
}

function qrModal(a) {
  const url = areaURL(a.id);
  modal(`QR Code – ${esc(a.name)}`, `<div style="text-align:center">
    <div style="max-width:260px;margin:0 auto">${qrSVG(url)}</div>
    <p style="word-break:break-all" class="muted">${esc(url)}</p>
    <p class="hint">Scanning opens this break area profile (contents, status, latest updates and history).
    ${location.protocol === 'file:' ? '<br><b>Note:</b> the app is opened from a local file, so phones can only use this QR after the system is hosted on a server.' : ''}</p></div>`, {
    extra: `<button type="button" class="btn" data-act="copyLink" data-url="${esc(url)}">${ic('copy')}Copy Link</button>
      <button type="button" class="btn primary" data-act="printLabel" data-id="${a.id}">${ic('printer')}Print Label</button>`
  });
}

function editArea(a) {
  modal(`Edit – ${esc(a.name)}`, areaFields(a), {
    submit: 'Save Changes', wide: true,
    extra: `<button type="button" class="btn danger" data-act="deleteArea" data-id="${a.id}">${ic('trash')}Delete Break Area</button>`,
    onSubmit(d) {
      const before = { status: a.status, responsible: a.responsible };
      applyAreaFields(a, d);
      const changes = [];
      if (before.status !== a.status) changes.push(`Status: ${before.status} → ${a.status}`);
      if (before.responsible !== a.responsible) changes.push(`Responsible: ${before.responsible} → ${a.responsible}`);
      if (changes.length) pushHistory({ areaId: a.id, date: today(), item: 'area', action: 'Condition Update', prev: null, next: null, details: changes.join('; '), by: setting('userName') });
      if (save()) toast('Break area updated');
    }
  });
}

/* ============================== Equipment ============================== */
function viewEquipment() {
  const A = DB.areas;
  return `<div class="page-head"><h2>Furniture &amp; Equipment</h2>
    <div class="actions"><button class="btn" data-act="exportEquip">${ic('download')}Export Excel</button><button class="btn primary" data-act="itemTypeModal">${ic('plus')}Add Item Type</button></div></div>
  <div class="kpis">${DB.itemTypes.map(t => {
    const total = A.reduce((s, a) => s + qty(a, t.id), 0);
    const bad = A.reduce((s, a) => { const e = invEntry(a, t.id); return s + (e && e.qty && e.condition !== 'Good' ? 1 : 0); }, 0);
    return `<div class="card kpi"><div class="kic ${bad ? 'orange' : ''}">${ic(t.icon)}</div><div><div class="lbl">${esc(t.name)}</div><div class="val">${total}</div>
      <div class="hint">${A.filter(a => qty(a, t.id)).length} areas${bad ? ` · <span style="color:#b45309">${bad} need attention</span>` : ''}</div></div></div>`;
  }).join('')}</div>
  <div class="card mb"><div class="card-h"><h3>Inventory by Break Area</h3><span class="sp"></span><span class="hint">Click a row to update its contents</span></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Break Area</th><th>Location</th>${DB.itemTypes.map(t => `<th class="num">${esc(t.name)}</th>`).join('')}<th class="num">Total Items</th></tr></thead>
    <tbody>${A.map(a => `<tr class="click" data-act="go" data-href="#/area/${a.id}"><td><b>${esc(a.name)}</b></td><td>${esc(a.location)}</td>
      ${DB.itemTypes.map(t => { const e = invEntry(a, t.id); return `<td class="num">${e && e.qty ? (e.condition !== 'Good' ? `<span class="badge ${STATUS_CLS[e.condition]}" title="${e.condition}">${e.qty}</span>` : e.qty) : '-'}</td>`; }).join('')}
      <td class="num"><b>${a.inventory.reduce((s, e) => s + e.qty, 0)}</b></td></tr>`).join('')}</tbody>
    <tfoot><tr><td>Total</td><td></td>${DB.itemTypes.map(t => `<td class="num">${A.reduce((s, a) => s + qty(a, t.id), 0)}</td>`).join('')}<td class="num">${A.reduce((s, a) => s + a.inventory.reduce((x, e) => x + e.qty, 0), 0)}</td></tr></tfoot></table></div>
    <p class="hint">Highlighted numbers mean the item condition is not "Good".</p></div>
  <div class="card"><div class="card-h"><h3>Item Types</h3></div>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Name</th><th>Singular</th><th>Code</th><th></th></tr></thead><tbody>
    ${DB.itemTypes.map(t => `<tr><td>${ic(t.icon)}</td><td><b>${esc(t.name)}</b></td><td>${esc(t.short || '')}</td><td class="muted">${esc(t.id)}</td>
      <td><button class="btn sm" data-act="itemTypeModal" data-tid="${t.id}">${ic('edit')}Edit</button></td></tr>`).join('')}</tbody></table></div></div>`;
}
function itemTypeModal(tid) {
  const t = tid ? itemType(tid) : null;
  modal(t ? 'Edit Item Type' : 'Add Item Type', `<div class="form-grid">
    <label>Name (plural)<input name="name" required value="${esc(t ? t.name : '')}" placeholder="e.g. Microwaves"></label>
    <label>Singular<input name="short" value="${esc(t ? t.short : '')}" placeholder="e.g. Microwave"></label>
    <label class="full">Icon<select name="icon">${options(ITEM_ICONS, t ? t.icon : 'box')}</select></label></div>`, {
    submit: t ? 'Save' : 'Add',
    onSubmit(d) {
      if (t) Object.assign(t, { name: d.name.trim(), short: d.short.trim() || d.name.trim(), icon: d.icon });
      else {
        let id = d.name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || uid();
        while (itemType(id)) id += '_';
        DB.itemTypes.push({ id, name: d.name.trim(), short: d.short.trim() || d.name.trim(), icon: d.icon });
      }
      if (save()) toast('Item type saved');
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
    <div class="actions"><button class="btn" data-act="printTx">${ic('printer')}Print</button><button class="btn" data-act="exportTx">${ic('download')}Export Excel</button></div></div>
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
    <div class="actions"><button class="btn" data-act="exportIssues">${ic('download')}Export Issues</button></div></div>
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
        <td><button class="btn sm" data-act="maintDone" data-id="${m.a.id}" data-mid="${m.id}">Complete</button></td></tr>`).join('') || '<tr><td colspan="5" class="empty">Nothing scheduled</td></tr>'}
      </tbody></table></div></div>
    <div class="card"><div class="card-h"><h3>Inspection Schedule</h3><span class="sp"></span><span class="hint">Every ${setting('inspectionDays')} days</span></div>
      <div class="tbl-wrap scroll"><table class="tbl"><thead><tr><th>Break Area</th><th>Last</th><th>Next</th><th>Status</th><th></th></tr></thead><tbody>
      ${insp.map(a => `<tr><td><a class="link" href="#/area/${a.id}">${esc(a.name)}</a></td><td>${fmt(a.lastInspection)}</td><td>${fmt(a.nextInspection)}</td><td>${badge(inspStatus(a))}</td>
        <td><button class="btn sm" data-act="inspModal" data-id="${a.id}">Record</button></td></tr>`).join('')}
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
    ${Object.entries(REPORTS).map(([k, r]) => `<div class="card report-card" data-report="${k}">
      <div class="card-h" style="margin:0">${ic('report')}<h3>${r.title}</h3></div><p>${r.desc}</p>
      ${r.dated ? `<div class="filters"><input type="date" name="from" title="From"><input type="date" name="to" title="To"></div>` : ''}
      <div class="filters"><button class="btn sm" data-act="runReport" data-k="${k}" data-mode="csv">${ic('download')}Export Excel</button>
      <button class="btn sm" data-act="runReport" data-k="${k}" data-mode="print">${ic('printer')}Print / PDF</button></div></div>`).join('')}
    <div class="card report-card"><div class="card-h" style="margin:0">${ic('qr')}<h3>QR Code Labels</h3></div>
      <p>Print QR labels for all break areas to stick at each entrance.</p>
      <div class="filters"><button class="btn sm" data-act="printAllLabels">${ic('printer')}Print All Labels</button></div></div>
  </div>`;
}

/* ============================== Settings ============================== */
function viewSettings() {
  const s = DB.settings;
  return `<div class="page-head"><h2>Settings</h2></div>
  <div class="grid2">
    <form class="card" data-form="settings">
      <div class="card-h">${ic('settings')}<h3>General</h3></div>
      <div class="form-grid">
        <label class="full">System Name<input name="systemName" value="${esc(s.systemName)}"></label>
        <label>Factory / Site<input name="factory" value="${esc(s.factory)}"></label>
        <label>Logo Text<input name="logoText" value="${esc(s.logoText)}"></label>
        <label>Current User<input name="userName" value="${esc(s.userName)}"></label>
        <label>Role<input name="userRole" value="${esc(s.userRole)}"></label>
        <label>Inspection frequency (days)<input type="number" min="1" name="inspectionDays" value="${s.inspectionDays}"></label>
        <label>Logo Image (optional)<input type="file" name="logo" accept="image/*"></label>
        <label class="full">Locations <span class="hint">(one per line)</span><textarea name="locations" rows="5">${esc(s.locations.join('\n'))}</textarea></label>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">${s.logoImage ? `<button type="button" class="btn" data-act="removeLogo">Remove logo image</button>` : ''}<span class="sp"></span><button class="btn primary">${ic('check')}Save Settings</button></div>
    </form>
    <div class="card">
      <div class="card-h">${ic('download')}<h3>Data &amp; Backup</h3></div>
      <p class="muted">In this prototype all data is stored in this browser. Take a backup regularly, or move it to another PC with Import.</p>
      <div class="filters mb">
        <button class="btn" data-act="backup">${ic('download')}Download Backup (JSON)</button>
        <label class="btn">${ic('upload')}Import Backup<input type="file" accept=".json,application/json" data-act-change="importBackup" hidden></label>
      </div>
      <p class="muted">Reset removes all changes and restores the demo data.</p>
      <button class="btn danger" data-act="resetData">${ic('trash')}Reset Demo Data</button>
      <p class="hint" style="margin-top:14px">Storage used: ${fileSize(new Blob([localStorage.getItem(KEY) || '']).size)} of ~5 MB browser limit.</p>
    </div>
  </div>`;
}

/* ============================== Events ============================== */
const ACT = {
  go: d => { location.hash = d.href; },
  toggleNav: () => document.body.classList.toggle('nav-open'),
  closeModal,
  scrollTrack: d => { const t = $('#track'); t.scrollBy({ left: d.dir * t.clientWidth * .7 }); },
  toHistory: () => $('#history').scrollIntoView({ behavior: 'smooth' }),
  photoTab: d => { F.photoTab = d.tab; rerender(); },
  editArea: d => editArea(area(d.id)),
  invModal: d => invModal(area(d.id), d.item),
  issueModal: d => issueModal(area(d.id)),
  issueView: d => issueView(area(d.id), d.iid),
  issueDelete: d => {
    const a = area(d.id);
    if (!confirm('Delete this issue?')) return;
    a.issues = a.issues.filter(i => i.id !== d.iid);
    save(); closeModal(); rerender(); toast('Issue deleted');
  },
  maintModal: d => maintModal(area(d.id)),
  maintDone: d => maintDone(area(d.id), d.mid),
  inspModal: d => inspModal(area(d.id)),
  uploadModal: d => uploadModal(area(d.id), d.cat),
  viewPhoto: d => viewPhoto(area(d.id), d.pid),
  photoMain: d => { const a = area(d.id); a.photos.forEach(p => (p.main = p.id === d.pid)); save(); closeModal(); rerender(); toast('Main photo updated'); },
  photoDelete: d => {
    const a = area(d.id);
    if (!confirm('Delete this photo?')) return;
    const wasMain = (a.photos.find(p => p.id === d.pid) || {}).main;
    a.photos = a.photos.filter(p => p.id !== d.pid);
    if (wasMain && a.photos[0]) a.photos[0].main = true;
    save(); closeModal(); rerender(); toast('Photo deleted');
  },
  docDownload: d => { const doc = area(d.id).docs.find(x => x.id === d.did); if (doc) { const l = document.createElement('a'); l.href = doc.src; l.download = doc.name; l.click(); } },
  docDelete: d => { const a = area(d.id); if (!confirm('Delete this document?')) return; a.docs = a.docs.filter(x => x.id !== d.did); save(); rerender(); toast('Document deleted'); },
  qrModal: d => qrModal(area(d.id)),
  printLabel: d => printLabels([area(d.id)]),
  printAllLabels: () => printLabels(DB.areas),
  printLabelsFiltered: () => printLabels(filteredAreas()),
  copyLink: d => { navigator.clipboard?.writeText(d.url).then(() => toast('Link copied'), () => toast('Copy failed', true)); },
  deleteArea: d => {
    const a = area(d.id);
    if (!confirm(`Delete ${a.name} and all its history? This cannot be undone.`)) return;
    DB.areas = DB.areas.filter(x => x.id !== a.id);
    DB.history = DB.history.filter(h => h.areaId !== a.id);
    save(); closeModal(); location.hash = '#/areas'; toast('Break area deleted');
  },
  exportAreas: () => exportCSV('break_areas', areaHead(), areaRows(filteredAreas())),
  exportHist: d => { const a = area(d.id); exportCSV(a.name.replace(/\s+/g, '_') + '_history', TX_HEAD, txExportRows(filteredHist(a))); },
  exportTx: () => exportCSV('transactions', TX_HEAD, txExportRows(filteredTx())),
  printTx: () => printTable('Transactions', TX_HEAD, txExportRows(filteredTx()).map(r => [fmt(r[0]), ...r.slice(1)])),
  clearTx: () => { F.tx = { q: '', area: '', item: '', action: '', from: '', to: '' }; rerender(); },
  exportEquip: () => exportCSV('inventory_by_area', REPORTS.inventory.head(), REPORTS.inventory.rows()),
  exportIssues: () => exportCSV('issues', REPORTS.issues.head(), REPORTS.issues.rows()),
  itemTypeModal: d => itemTypeModal(d.tid),
  runReport: (d, el) => {
    const r = REPORTS[d.k], card = el.closest('.card');
    const from = card.querySelector('[name=from]')?.value || '', to = card.querySelector('[name=to]')?.value || '';
    const rows = r.rows(from, to);
    if (d.mode === 'csv') exportCSV(d.k, r.head(), rows);
    else printTable(r.title + (from || to ? ` (${from ? fmt(from) : '…'} – ${to ? fmt(to) : '…'})` : ''), r.head(), rows);
  },
  backup: () => download('break_areas_backup_' + today() + '.json', JSON.stringify(DB, null, 1), 'application/json'),
  removeLogo: () => { DB.settings.logoImage = ''; save(); rerender(); },
  resetData: () => { if (!confirm('Reset all data to the demo data? All your changes will be lost.')) return; DB = buildSeed(); save(); location.hash = '#/dashboard'; rerender(); toast('Demo data restored'); }
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
document.addEventListener('input', onFilter);
document.addEventListener('change', async e => {
  onFilter(e);
  if (e.target.dataset.actChange === 'importBackup') {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const data = JSON.parse(await f.text());
      if (!data.areas || !data.settings) throw new Error('invalid');
      if (!confirm(`Import backup with ${data.areas.length} break areas? Current data will be replaced.`)) return;
      DB = data; save(); rerender(); toast('Backup imported');
    } catch (err) { toast('Invalid backup file', true); }
  }
});

document.addEventListener('submit', async e => {
  const f = e.target;
  if (f.dataset.form === 'newArea') { e.preventDefault(); await submitNewArea(f); }
  if (f.dataset.form === 'settings') {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f));
    Object.assign(DB.settings, {
      systemName: d.systemName.trim() || 'Break Area Management System', factory: d.factory.trim(), logoText: d.logoText.trim(),
      userName: d.userName.trim() || 'User', userRole: d.userRole.trim(), inspectionDays: Math.max(1, +d.inspectionDays || 30),
      locations: d.locations.split('\n').map(x => x.trim()).filter(Boolean)
    });
    if (f.logo.files[0]) DB.settings.logoImage = await resizeImage(f.logo.files[0], 400);
    if (save()) { rerender(); toast('Settings saved'); }
  }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
window.addEventListener('hashchange', () => { F.hist = { item: '', action: '' }; F.photoTab = 'All'; render(); scrollTo(0, 0); });

load();
render();
