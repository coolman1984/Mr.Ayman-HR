/* Seed / demo data for the Break Area Management System.
   Used only by the "Load Demo Data" button shown while the database is empty. */
'use strict';

const STATUSES = ['Good', 'Need Maintenance', 'Under Update'];
const CONDITIONS = ['Good', 'Need Repair', 'Damaged', 'Out of Service'];
const ACTIONS = ['Added', 'Removed', 'Replaced', 'Transferred', 'Maintenance', 'Condition Update'];
const PRIORITIES = ['Low', 'Medium', 'High'];
const PHOTO_CATEGORIES = ['Current', 'Before', 'After'];

const DEFAULT_ITEM_TYPES = [
  { id: 'chairs', name: 'Chairs', short: 'Chair', icon: 'chair' },
  { id: 'tables', name: 'Tables', short: 'Table', icon: 'table' },
  { id: 'tv', name: 'TV Screens', short: 'TV Screen', icon: 'tv' },
  { id: 'water', name: 'Water Dispensers', short: 'Water Dispenser', icon: 'dispenser' },
  { id: 'carpet', name: 'Carpets', short: 'Carpet', icon: 'rug' },
  { id: 'fridge', name: 'Refrigerators', short: 'Refrigerator', icon: 'fridge' },
  { id: 'other', name: 'Others', short: 'Other item', icon: 'box' }
];

function buildSeed() {
  const pad = n => String(n).padStart(2, '0');
  const addDays = (d, n) => {
    const t = new Date(d + 'T00:00:00'); t.setDate(t.getDate() + n);
    return t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
  };

  const people = ['Ayman Essam', 'Ahmed Hassan', 'Mahmoud Ali', 'Sara Mostafa', 'Omar Khaled', 'Hany Adel'];
  const locOverride = { 3: 'Admin', 4: 'Utility', 9: 'Admin', 14: 'Admin', 17: 'Logistics', 21: 'Other' };
  const buildingFor = { Production: 'Main Building', Admin: 'Admin Building', Utility: 'Utility Building', Logistics: 'Warehouse', Other: 'Gate Area' };
  const statusOverride = { 3: 'Need Maintenance', 5: 'Need Maintenance', 10: 'Need Maintenance', 18: 'Need Maintenance', 12: 'Under Update', 20: 'Under Update' };
  const chairs = [30, 24, 16, 20, 24, 28, 22, 24, 26, 30, 20, 24, 28, 22, 26, 24, 30, 20, 24, 26, 24, 28];
  const tables = [6, 6, 4, 5, 6, 6, 5, 6, 5, 6, 5, 6, 5, 6, 5, 6, 5, 6, 5, 6, 5, 5];
  const floors = ['Ground Floor', 'Floor 1', 'Floor 2'];
  const photoSet = [
    ['Seating Area', 'seating'], ['Coffee Area', 'coffee'], ['Entrance Area', 'entrance'],
    ['Water Dispenser', 'water'], ['Carpet', 'carpet']
  ];

  let seq = 1;
  const areas = [];
  const history = [];
  const h = (areaId, date, item, action, prev, next, details, by) =>
    history.push({ id: 'h' + seq, seq: seq++, areaId, date, item, action, prev, next, details, by });

  for (let i = 1; i <= 22; i++) {
    const id = 'ba' + pad(i);
    const location = locOverride[i] || 'Production';
    const status = statusOverride[i] || 'Good';
    const startDate = i === 1 ? '2026-07-01' : addDays('2025-01-10', i * 23);
    const lastInspection = status === 'Need Maintenance' ? addDays('2026-08-05', i) : addDays('2026-09-01', i % 14);
    const needs = status !== 'Good';

    const inventory = [
      { item: 'chairs', qty: chairs[i - 1], condition: needs && i % 2 ? 'Need Repair' : 'Good' },
      { item: 'tables', qty: tables[i - 1], condition: 'Good' },
      { item: 'tv', qty: 1, condition: 'Good' },
      { item: 'water', qty: 1, condition: i === 10 ? 'Need Repair' : 'Good' },
      { item: 'carpet', qty: 1, condition: 'Good' },
      { item: 'fridge', qty: i % 3 === 0 ? 1 : 0, condition: 'Good' },
      { item: 'other', qty: i === 1 ? 3 : 2 + (i % 2), condition: 'Good', note: 'Microwave, Kettle, Notice Board' }
    ].filter(x => x.qty > 0 || x.item !== 'fridge');

    const photos = photoSet.map(([caption, variant], k) => ({
      id: id + 'p' + k, caption, variant, seed: id + variant, category: 'Current', date: startDate, main: k === 0
    }));

    const issues = [];
    if (i === 1) {
      issues.push({ id: 'is' + seq++, date: '2026-08-10', title: 'Loose chair legs', item: 'chairs', priority: 'Low', status: 'Closed', closedDate: '2026-08-14', reportedBy: 'Ahmed Hassan', details: 'Two chairs had loose legs.', log: [{ date: '2026-08-14', by: 'Maintenance Team', text: 'Fixed and tightened.' }] });
      issues.push({ id: 'is' + seq++, date: '2026-08-28', title: 'TV remote not working', item: 'tv', priority: 'Low', status: 'Closed', closedDate: '2026-09-02', reportedBy: 'Sara Mostafa', details: 'Remote control not responding.', log: [{ date: '2026-09-02', by: 'Maintenance Team', text: 'TV replaced with new 55" Smart TV.' }] });
    }
    if (status === 'Need Maintenance') {
      issues.push({ id: 'is' + seq++, date: addDays('2026-09-08', i % 5), title: i === 10 ? 'Water dispenser leaking' : 'Damaged chairs need repair', item: i === 10 ? 'water' : 'chairs', priority: i === 10 ? 'High' : 'Medium', status: 'Open', reportedBy: people[i % people.length], details: 'Reported during routine inspection.', log: [] });
      if (i === 3) issues.push({ id: 'is' + seq++, date: '2026-09-18', title: 'Air conditioner not cooling', item: 'other', priority: 'High', status: 'In Progress', reportedBy: 'Omar Khaled', details: 'AC unit in break area not cooling properly.', log: [{ date: '2026-09-19', by: 'Facility Team', text: 'Technician assigned.' }] });
    }

    // Monthly satisfaction survey: Jan–Aug 2026, one result per department using the area
    const depts = location === 'Production' ? ['Production – Line ' + (1 + i % 4), ...(i % 5 === 0 ? ['Quality'] : [])] : [location];
    const surveys = [];
    for (let m = 1; m <= 8; m++) {
      depts.forEach((dept, k) => {
        const base = 68 + (i * 7) % 22 + (status === 'Good' ? 4 : -6);
        const p = Math.max(40, Math.min(99, base + Math.round(Math.sin(i + m / 2) * 5) + m - k * 3));
        surveys.push({ id: id + 's' + m + k, month: '2026-' + pad(m), department: dept, percentage: p, respondents: 18 + (i * m) % 25, notes: '', by: 'HR Team' });
      });
    }

    areas.push({
      id, name: 'Break Area ' + pad(i), location, surveys,
      building: buildingFor[location], floor: floors[i % 3],
      startDate, size: 60 + (chairs[i - 1] * 3), capacity: chairs[i - 1] + 10,
      responsible: people[i % people.length], status, active: true,
      description: i === 1
        ? 'Break area for production employees. Includes seating, entertainment and refreshment facilities.'
        : `Break area serving ${location.toLowerCase()} employees.`,
      inventory, photos, docs: [], issues,
      maintenance: status === 'Under Update'
        ? [{ id: 'm' + seq++, date: '2026-09-30', item: 'chairs', assignedTo: 'Facility Team', details: 'Furniture upgrade in progress.', status: 'Scheduled' }]
        : [],
      inspections: [{ id: 'in' + seq++, date: lastInspection, by: 'Facility Team', result: needs ? 'Issues Found' : 'Pass', notes: '' }],
      lastInspection, nextInspection: addDays(lastInspection, 30), inspectedBy: 'Facility Team'
    });

    h(id, startDate, 'Initial Setup', 'Created', null, null, 'Break area created with initial furniture and equipment', 'Admin');
  }

  // Area 01 history (as in the concept)
  h('ba01', '2026-08-20', 'carpet', 'Added', 0, 1, 'Added 1 carpet', 'Ayman Essam');
  h('ba01', '2026-09-02', 'tv', 'Replaced', 1, 1, 'Replaced old TV with 55" Smart TV', 'Maintenance Team');
  // Recent transactions across the factory
  h('ba11', '2026-09-11', 'tv', 'Added', 0, 1, 'Installed new TV screen', 'Facility Team');
  h('ba05', '2026-09-12', 'chairs', 'Maintenance', 24, 24, 'Maintenance for chairs', 'Maintenance Team');
  h('ba07', '2026-09-13', 'tables', 'Removed', 7, 5, 'Removed 2 damaged tables', 'Mahmoud Ali');
  h('ba03', '2026-09-14', 'water', 'Replaced', 1, 1, 'Replaced water dispenser', 'Maintenance Team');
  h('ba01', '2026-09-15', 'chairs', 'Added', 20, 30, 'Added 10 new chairs', 'Ayman Essam');

  return {
    version: 1,
    settings: {
      systemName: 'Break Area Management System',
      factory: 'Beni Suef Factory',
      logoText: 'SAMSUNG',
      logoImage: '',
      userName: 'Ayman Essam',
      userRole: 'Admin',
      inspectionDays: 30,
      satisfactionTarget: 80,
      locations: ['Production', 'Admin', 'Utility', 'Logistics', 'Other']
    },
    itemTypes: DEFAULT_ITEM_TYPES.map(t => ({ ...t })),
    areas, history, seq
  };
}
