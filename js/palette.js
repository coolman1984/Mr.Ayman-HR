/* Search everything (Ctrl K, or the Search button at the top): pages, break areas, serial numbers, plans and quick actions.
   Idea taken from the sibling project Trip Orders; written for this program's look. Only the keyboard or the mouse is needed. */
(function () {
  'use strict';
  let box = null, list = [], sel = 0;

  function items() {
    const out = [];
    const pages = [['dashboard', 'Dashboard', 'dashboard'], ['areas', 'Break Areas', 'building'], ['equipment', 'Furniture & Equipment', 'sofa'], ['transactions', 'Transactions', 'swap'],
      ['maintenance', 'Maintenance', 'wrench'], ['reports', 'Reports', 'report'], ['logs', 'Activity Log', 'activity'], ['users', 'Users & Permissions', 'users'],
      ['devices', 'Devices & Sync', 'sync'], ['settings', 'Settings', 'settings'], ['help', 'Help', 'help']];
    pages.filter(p => canPage(p[0])).forEach(p => out.push({ t: p[1], s: 'Page', icon: p[2], go: '#/' + p[0] }));
    DB.areas.forEach(a => out.push({ t: a.name, s: `Break area · ${a.location}`, icon: 'building', go: '#/area/' + a.id, k: [a.building, a.responsible, a.floor].join(' ') }));
    DB.areas.forEach(a => (a.pieces || []).forEach(p => out.push({ t: p.serial, s: `${itemShort(p.item)} · ${a.name}`, icon: 'plan', go: '#/area/' + a.id, k: 'serial number ' + itemName(p.item) })));
    DB.areas.forEach(a => (a.plans || []).filter(isOpenPlan).forEach(p => out.push({ t: p.title, s: `Plan · ${a.name}`, icon: 'plan', go: '#/area/' + a.id })));
    DB.areas.forEach(a => (a.notes || []).forEach(n => out.push({ t: n.text.slice(0, 90), s: `${n.kind} · ${a.name}`, icon: 'edit', go: '#/area/' + a.id })));
    DB.areas.forEach(a => a.issues.filter(i => i.status !== 'Closed').forEach(i => out.push({ t: i.title, s: `Open issue · ${a.name}`, icon: 'alert', go: '#/area/' + a.id })));
    if (can('areas.create') && allAreas()) out.push({ t: 'Add New Break Area', s: 'Action', icon: 'plus', go: '#/areas/new' });
    return out;
  }
  const score = (it, q) => {
    const t = it.t.toLowerCase(), all = (it.t + ' ' + it.s + ' ' + (it.k || '')).toLowerCase();
    if (!q) return it.s === 'Page' ? 1 : 0;
    if (t === q) return 100;
    if (t.startsWith(q)) return 80;
    if (t.includes(q)) return 60;
    return q.split(/\s+/).every(w => all.includes(w)) ? 30 : 0;
  };
  function render() {
    const res = box.querySelector('.pal-list');
    res.innerHTML = list.length ? list.map((it, i) => `<div class="pal-item ${i === sel ? 'on' : ''}" data-i="${i}">${ic(it.icon)}<div><b>${esc(it.t)}</b><small>${esc(it.s)}</small></div></div>`).join('')
      : '<div class="pal-empty">Nothing found</div>';
    const on = res.querySelector('.on');
    if (on) on.scrollIntoView({ block: 'nearest' });
  }
  function filter(q) {
    q = q.trim().toLowerCase();
    list = items().map(it => [score(it, q), it]).filter(x => x[0] > 0).sort((a, b) => b[0] - a[0]).slice(0, 40).map(x => x[1]);
    sel = 0; render();
  }
  function go(i) {
    const it = list[i];
    if (!it) return;
    close();
    location.hash = it.go;
  }
  function close() { if (box) { box.remove(); box = null; } document.removeEventListener('keydown', onKey, true); }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(list.length - 1, sel + 1); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); render(); }
    else if (e.key === 'Enter') { e.preventDefault(); go(sel); }
  }
  function open() {
    if (box || typeof DB === 'undefined' || !DB || !ME) return;
    box = document.createElement('div');
    box.className = 'pal-back';
    box.innerHTML = `<div class="pal" role="dialog" aria-modal="true" aria-label="Search"><div class="pal-in">${ic('search')}<input id="palQ" placeholder="Search break areas, serial numbers, plans, issues, pages…" autocomplete="off"><kbd>Esc</kbd></div><div class="pal-list"></div>
      <div class="pal-foot"><span><kbd>↑</kbd><kbd>↓</kbd> choose</span><span><kbd>Enter</kbd> open</span></div></div>`;
    document.body.appendChild(box);
    box.addEventListener('mousedown', e => { if (e.target === box) close(); });
    box.addEventListener('click', e => { const it = e.target.closest('.pal-item'); if (it) go(+it.dataset.i); });
    box.querySelector('#palQ').addEventListener('input', e => filter(e.target.value));
    document.addEventListener('keydown', onKey, true);
    filter('');
    box.querySelector('#palQ').focus();
  }
  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.code === 'KeyK') { e.preventDefault(); box ? close() : open(); }  // e.code: works on any keyboard layout
  });
  document.addEventListener('click', e => { if (e.target.closest('#searchBtn')) open(); });
  window.SearchEverything = { open, close };
})();
