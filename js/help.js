/* Break Area Management System – Help & User Guide (page #/help, also linked from Settings).
   Plain questions and answers, grouped by topic, with a search box. Sections marked admin are shown only to
   administrators (people who may manage users). Keep it in step with the program: every change of a screen
   updates its answer here (see CLAUDE.md). */
'use strict';

Object.assign(IC, {
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>'
});

const hb = s => `<b>${s}</b>`;
const HELP = [
  { id: 'start', title: 'Getting started', icon: 'dashboard', items: [
    ['What is this program?', `It keeps everything about the break areas of the factory in one place: the furniture and equipment in each
      break area, issues, maintenance, inspections, satisfaction results, photos and documents. Everything each person does is saved with
      their name.`],
    ['How do I open it?', `Use the way the administrator gave you:<ul>
      <li>${hb('Personal link')} – just open your link (save it as a bookmark). No user name or password.</li>
      <li>${hb('Desktop icon')} – on a PC where the program is installed, double-click ${hb('Break Area Management System')}.</li>
      <li>${hb('Address')} – type the address the administrator gave you (for example http://192.168.1.10:8080) into the browser.</li></ul>`],
    ['How do I log in and out?', `With a user name and password: type them and press ${hb('Log In')}. With a personal link you are logged in
      straight away. To log out click your name (top right) → ${hb('Log Out')}. Always log out on a shared PC.`],
    ['Why was I logged out by myself?', `After 30 minutes without using the program you are logged out for safety. Log in again (or open
      your link again). While you are typing, you are not logged out.`],
    ['What am I allowed to do?', `Click your name (top right) → ${hb('What I can do')}. It lists every page and action with a tick or a cross.
      If you need more, ask the administrator.`],
    ['How do I change my password?', `Click your name → ${hb('Change Password')}. People who log in with a personal link have no password.`],
    ['I do not see a page or a button.', `Your account does not have that permission. The administrator can add it in
      ${hb('Users & Permissions')}.`]
  ]},
  { id: 'areas', title: 'Break areas', icon: 'building', items: [
    ['How do I find a break area?', `${hb('Break Areas')} in the menu. Use the search box (name, building, person) and the location and status
      filters. Click a break area to open its page.`],
    ['What is on a break area page?', `Its details and status, the inventory (furniture and equipment), open issues and maintenance, photos
      and documents, inspection dates, satisfaction results, a QR code and the full history of changes (${hb('View History')}).`],
    ['How do I add a new break area?', `${hb('Break Areas')} → ${hb('Add New Break Area')}. Fill in the name, location and details, the first
      contents, then ${hb('Create Break Area')}.`],
    ['How do I change or delete a break area?', `Open it → ${hb('Edit')}. There you can change details and status, or delete it.
      Deleted break areas can be brought back from ${hb('Settings → Recycle Bin')}.`],
    ['What are the QR codes for?', `Every break area has a QR code. Print it (${hb('View / Print')} on the break area, or
      ${hb('Reports → Print QR Labels')}) and stick it in the break area. Scanning it with a phone in the company network opens that
      break area's page.`]
  ]},
  { id: 'inventory', title: 'Furniture, equipment and transactions', icon: 'sofa', items: [
    ['How do I add or remove items?', `Open the break area → ${hb('Add New Item')} (or ${hb('Add New')} in the inventory). Choose the item,
      the action (${hb('Added')}, ${hb('Removed')}, ${hb('Replaced')}, ${hb('Transferred')}), the quantity and the condition. Every movement is
      saved in ${hb('Transactions')}.`],
    ['How do I move items to another break area?', `Choose the action ${hb('Transferred')} and the break area it goes to. It is removed from
      one and added to the other in one step.`],
    ['Where do I see the totals?', `${hb('Furniture & Equipment')} shows every item type with totals and how many are not in good
      condition. ${hb('Export Excel')} gives the full list.`],
    ['How do I add a new kind of item (e.g. "Microwave")?', `${hb('Furniture & Equipment')} → ${hb('Add Item Type')} (needs the permission
      "Add, edit and delete item types").`],
    ['A quantity shows below zero.', `Items were probably removed on two PCs at the same time. Count them in the break area and correct the
      number. The administrator also sees it in ${hb('Devices & Sync → To decide')}.`]
  ]},
  { id: 'issues', title: 'Issues, maintenance and inspections', icon: 'wrench', items: [
    ['How do I report a problem?', `Open the break area → ${hb('Report Issue')}. Write what is wrong, choose the item and the priority.
      The bell at the top shows how many issues are open.`],
    ['How do I follow up or close an issue?', `Open the issue, choose the new status (${hb('Open')}, ${hb('In Progress')}, ${hb('Closed')})
      and write what was done. Every step is kept in the issue's log.`],
    ['How do I plan maintenance?', `Open the break area → ${hb('Schedule Maintenance')}. When it is done, open it on the
      ${hb('Maintenance')} page and complete it.`],
    ['How do inspections work?', `Record an inspection on the break area. The next inspection date is calculated from the inspection
      frequency in ${hb('Settings')}. The ${hb('Maintenance')} page shows what is due or overdue.`]
  ]},
  { id: 'surveys', title: 'Satisfaction results', icon: 'check', items: [
    ['How do I enter a satisfaction result?', `Open the break area → satisfaction section → ${hb('Add Result')}: month, department and
      the percentage. The target (e.g. 85%) is set in ${hb('Settings')}.`],
    ['The same result shows twice.', `It was entered on two PCs. Delete the extra one on the break area page.`]
  ]},
  { id: 'files', title: 'Photos and documents', icon: 'image', items: [
    ['How do I add photos or documents?', `Open the break area → ${hb('Upload Photo / Document')}. Photos keep their full quality; you can
      choose the main photo (${hb('Set as Main Photo')}). Files up to 50 MB.`],
    ['A photo says "Photo is being copied".', `It was added on another PC and is still on its way. It appears by itself in a moment.`]
  ]},
  { id: 'reports', title: 'Reports, printing and Excel', icon: 'report', items: [
    ['Which reports are there?', `${hb('Reports')} has: Break Area Register, Inventory by Break Area, Update History, Issues, Inspection
      Schedule, Satisfaction Survey, Summary by Location and QR labels. Each can be filtered, printed or saved as PDF
      (${hb('Print / PDF')}) and exported to Excel.`],
    ['How do I save something as PDF?', `${hb('Print / PDF')} → in the print window choose ${hb('Save as PDF')} as the printer.`],
    ['Can I export everything?', `${hb('Settings → Export Everything')} gives one Excel file with all data and logs (needs the permission
      "Complete database export").`]
  ]},
  { id: 'logs', title: 'Activity log – who did what', icon: 'activity', items: [
    ['Where do I see who changed something?', `${hb('Activity Log → Data Changes')}: every added, changed or deleted record with the old and
      new value, the person, the time and the PC. Filter by person, type, PC and date; ${hb('Export Excel')}.`],
    ['Who can see clicks and logins?', `${hb('User Activity & Errors')} and ${hb('Logins & Security')} are only for administrators.`]
  ]},
  { id: 'first', title: 'First steps after installing', icon: 'settings', admin: true, items: [
    ['What do I do first?', `<ol><li>Create your administrator account (first screen, on the PC itself).</li>
      <li>${hb('Settings')}: system name, factory, locations, inspection frequency, satisfaction target, logo.</li>
      <li>If you chose to try it with sample data: delete it (next question).</li>
      <li>Add your break areas (${hb('Break Areas → Add New Break Area')}).</li>
      <li>Add the people (${hb('Users & Permissions → Add Person')}).</li>
      <li>Optional: add other PCs (${hb('Devices & Sync → Add a PC')}) and choose a backup administrator PC.</li></ol>`],
    ['How do I delete the sample data?', `At the very first start you choose: an empty system, or sample break areas to try everything.
      ${hb('Settings → Delete Sample Data')} and type ${hb('DELETE')}. A backup is made first and everything stays in the
      ${hb('Recycle Bin')}, so nothing is lost. It is never loaded again by itself (${hb('Load Sample Data')} brings it back on purpose).`],
    ['Does the PC with the program have to stay on?', `Yes, for everybody who uses it from another PC or phone (for example with a
      personal link). The program starts by itself after somebody ${hb('signs in to Windows')} on that PC and runs in the background –
      you may ${hb('lock')} the screen (Windows key + L), but do not sign out or switch the PC off during working hours. If it was
      closed, double-click the desktop icon.`],
    ['How do I update the program to a new version?', `Run the new ${hb('BAMS-Setup.exe')} on the administrator PC, then on every other PC that
      has the program. It updates in place: all data stays. People who use a personal link need nothing.`],
    ['Where is the data kept?', `In ${hb('C:\\ProgramData\\BAMS')} on every PC with the program (database, photos, logs, backups and
      settings). The program itself is in C:\\Program Files\\BAMS. Never copy the data folder to another PC.`]
  ]},
  { id: 'people', title: 'People, links and permissions', icon: 'users', admin: true, items: [
    ['How do I add a person?', `${hb('Users & Permissions → Add Person')}: type the name, choose a profile, press ${hb('Create')}.
      The person's ${hb('personal link')} and QR code appear. Send the link to that person only, or open it once on their PC or phone
      and save it as a bookmark. They need nothing installed.`],
    ['Link or user name and password – which one?', `${hb('Personal link')} is the easiest for everyday users. ${hb('User name and password')}
      is needed for administrators and deputies. You choose it in the person's window and can change it later.`],
    ['How do I set what someone may do?', `Tick or untick the boxes in the person's window – one box per page and per action.
      ${hb('Select all')} gives everything except the orange ${hb('administrator rights')}; ${hb('Clear all')} removes every tick.
      A profile ticks the boxes for you.`],
    ['What are profiles?', `Ready-made sets of ticks: Full access, Administrator, Data Entry, Maintenance Team, Viewer, Visitor – and your
      own (${hb('Profiles → New Profile')}). When you change a profile, everybody who has it can be updated at once.`],
    ['How do I give someone administrator rights (a deputy)?', `Open the person, choose ${hb('User name and password')}, give a temporary
      password and choose the profile ${hb('Administrator')}. They can then manage people on the administrator PC (from any browser) –
      and, if you set one up, on the backup administrator PC while the administrator PC is off. Take it back the same way at any time.`],
    ['Somebody lost their link, or it got into the wrong hands.', `Open the person → ${hb('Show Link')} → ${hb('New link')}. The old link
      stops working at once on every PC.`],
    ['Someone is on holiday or left the company.', `Holiday: ${hb('Account → Disabled')}. Left: ${hb('Delete')}. Everything they did stays in
      the logs with their name.`],
    ['Someone forgot the password or is locked out.', `Open the person → ${hb('Reset Password')} (a new temporary password) or
      ${hb('Unlock')}. After 5 wrong passwords an account is locked for 15 minutes by itself.`],
    ['Can I limit someone to some break areas?', `Yes: in the person's window → ${hb('More options')} → ${hb('Only the selected break areas')}.`],
    ['Where do I see logins and link use?', `${hb('Users & Permissions → Logins & Security Log')}, and ${hb('Devices & Sync → Personal links')}
      shows when and on which PC each link was last used.`]
  ]},
  { id: 'pcs', title: 'Several PCs, delegation and the sync light', icon: 'sync', admin: true, items: [
    ['How do I add another PC?', `Install ${hb('BAMS-Setup.exe')} on it and choose ${hb('Join an existing system')}. On the administrator PC
      open ${hb('Devices & Sync → Add a PC')} and type the code shown there into the new PC. Approve the new PC only if both screens show
      the same 6-digit number.`],
    ['What if the administrator PC is switched off or I am away?', `Everybody keeps working and the PCs keep sharing. Only people,
      permissions and PCs cannot be changed – unless you set up a ${hb('backup administrator PC')}: ${hb('Devices & Sync')} →
      ${hb('Make backup admin')} next to a trusted PC. From then on people with administrator rights can manage people there too.
      ${hb('End backup admin')} takes it back.`],
    ['What does the light at the top mean?', `Green: all PCs have the same data. Yellow: changes are being shared. Grey: other PCs are off
      (normal). Red: a problem – open ${hb('Devices & Sync → Warnings')}.`],
    ['"To decide" shows something.', `Two PCs changed the same thing at the same time. Choose the right value (${hb('Use this')}), or decide
      whether a deleted record stays deleted. Your decision reaches every PC.`],
    ['A warning says "PC not sharing".', `That PC has not shared its data for more than 3 days. Check that it is switched on and in the
      network; if it is not used any more, ${hb('Remove')} it.`],
    ['A PC is lost or broken.', `${hb('Devices & Sync → Remove')}. Install the program on the new PC and add it.`]
  ]},
  { id: 'backup', title: 'Backups, Recycle Bin and recovery', icon: 'restore', admin: true, items: [
    ['Are backups made automatically?', `Yes: at every start, every 6 hours when something changed, and before risky actions. You can make
      one with ${hb('Settings → Backup Now')}. They are kept in C:\\ProgramData\\BAMS\\backups on the PC.`],
    ['How do I keep a copy on a USB drive or another disk?', `On the PC with the program: ${hb('Settings → Backups → Choose a second backup folder')},
      for example E:\\BAMS-Backups. From then on every backup is also copied there. If the copy fails (drive not connected), the Backups
      card shows it. With several PCs every PC also keeps all the data, which is a second protection.`],
    ['How do I restore a backup?', `${hb('Settings → Backups → Restore')}. The data goes back to that moment on every PC. The current data is
      saved first, so a restore can be undone. People, logs and history are never rolled back.`],
    ['I deleted something by mistake.', `${hb('Settings → Recycle Bin')} – choose it and restore. Nothing is ever erased.`],
    ['I forgot the administrator password.', `A deputy administrator can reset it in ${hb('Users & Permissions')}. Otherwise, on the
      administrator PC, ask IT to run ${hb('"C:\\Program Files\\BAMS\\BAMS.exe" tool reset-admin')} (program stopped) – it prints a new
      temporary password.`]
  ]},
  { id: 'trouble', title: 'Problems and questions', icon: 'alert', items: [
    ['The page says "Cannot connect to the server".', `The PC with the program is off, or you are not in the company network. Open the
      program from its desktop icon on that PC; if it still does not open, restart that PC.`],
    ['My link says "This link does not work any more".', `The administrator made a new link or switched it off. Ask for your new link.`],
    ['I see "Please tell the administrator".', `Sharing with the other PCs has a problem. Your work on this PC is saved. Tell the
      administrator.`],
    ['A change does not appear on another PC.', `It arrives within seconds when both PCs are on and in the network. If one is off, it arrives
      when it is back.`],
    ['Someone else changed the same record.', `You are told to refresh instead of overwriting their change. Refresh and repeat your change.`]
  ]}
];

const HELP_F = { q: '' };
EXTRA_VIEWS.help = () => {
  const admin = can('users.manage');
  const q = HELP_F.q.trim().toLowerCase();
  const plain = h => h.replace(/<[^>]+>/g, ' ').toLowerCase();
  const sections = HELP.filter(s => admin || !s.admin).map(s => ({ ...s, items: s.items.filter(([t, a]) => !q || (t + ' ' + plain(a)).toLowerCase().includes(q)) }))
    .filter(s => s.items.length);
  const count = sections.reduce((n, s) => n + s.items.length, 0);
  return `<div class="page-head"><h2>Help &amp; User Guide</h2><span class="muted">${count} answers</span></div>
    <div class="card mb help-top">
      <label class="search wide">${ic('search')}<input id="helpQ" data-help-q placeholder="Search the help, e.g. link, password, delete, backup…" value="${esc(HELP_F.q)}"></label>
      <div class="help-toc">${sections.map(s => `<button type="button" class="help-chip" data-act="helpJump" data-id="${s.id}">${ic(s.icon)}${esc(s.title)}${s.admin ? ' <span class="badge b-purple">admin</span>' : ''}</button>`).join('')}</div>
    </div>
    ${sections.map(s => `<div class="card mb help-sec" id="help-${s.id}"><div class="card-h">${ic(s.icon)}<h3>${esc(s.title)}</h3>
        ${s.admin ? '<span class="badge b-purple">For administrators</span>' : ''}</div>
      ${s.items.map(([t, a]) => `<details class="help-q"${q ? ' open' : ''}><summary>${esc(t)}</summary><div class="help-a">${a}</div></details>`).join('')}</div>`).join('')
      || '<div class="card"><p class="empty">Nothing found. Try another word, or ask the administrator.</p></div>'}
    ${ABOUT ? `<p class="about-line">${esc(ABOUT.product)} · version ${esc(ABOUT.version)} · ${esc(ABOUT.copyright)}</p>` : ''}`;
};
document.addEventListener('input', e => {
  if (!e.target.matches || !e.target.matches('[data-help-q]')) return;
  HELP_F.q = e.target.value;
  const pos = e.target.selectionStart;
  rerender();
  const inp = $('#helpQ');
  if (inp) { inp.focus(); inp.setSelectionRange(pos, pos); }
});
Object.assign(ACT, {
  helpJump: d => { const s = $('#help-' + d.id); if (s) s.scrollIntoView({ behavior: 'smooth' }); }
});
