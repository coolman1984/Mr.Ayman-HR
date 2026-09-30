"""Bring break areas, their contents and their serial numbers in from an Excel workbook.

The rules that make it safe to use (also twice with the same file):
  * nothing that already exists is changed: a break area with the same name, an item a break area already has and a serial
    number that is already used are skipped and listed (never overwritten, never added up twice);
  * headers are found by their names in the first rows of every sheet (English names and a few usual variants), in any order;
  * a sheet with an Item and a Quantity column is read as contents, a sheet with a Name column as break areas;
  * every problem is a line for the person (sheet, row, reason), not a crash; nothing is saved by this module -
    it returns a plan that the screen shows and applies in one saved change.
"""
import datetime as dt
import re

import xlsx_read

STATUSES = ('Good', 'Need Maintenance', 'Under Update')
CONDITIONS = ('Good', 'Need Repair', 'Damaged', 'Out of Service')
AREA_COLS = {
    'name': ('break area', 'break area name', 'name', 'area', 'room'),
    'location': ('location', 'zone', 'section'),
    'building': ('building',),
    'floor': ('floor', 'level'),
    'capacity': ('capacity', 'persons', 'people', 'seats'),
    'responsible': ('responsible', 'responsible person', 'person', 'owner', 'manager'),
    'size': ('size', 'area size', 'area size (m2)', 'm2', 'size m2'),
    'status': ('status',),
    'startDate': ('start date', 'start', 'opened', 'opening date'),
    'description': ('description', 'notes', 'remarks'),
}
INV_COLS = {
    'area': ('break area', 'break area name', 'area', 'room', 'name'),
    'item': ('item', 'item type', 'equipment', 'type', 'furniture', 'category'),
    'qty': ('quantity', 'qty', 'count', 'number', 'amount'),
    'condition': ('condition', 'state'),
    'serials': ('serial numbers', 'serial number', 'serial', 'serials', 'sn', 's/n'),
    'note': ('notes', 'note', 'remarks', 'comment'),
}
MAX_ROWS = 20000


def norm(v):
    return re.sub(r'\s+', ' ', re.sub(r'[*:]', '', str(v if v is not None else ''))).strip().lower()


def text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime('%Y-%m-%d')
    return re.sub(r'\s+', ' ', str(v)).strip()


def find_header(sheet, cols):
    """(row number, {field: column}) of the first of the first 15 rows that names at least two fields, or None."""
    for r in range(1, min(sheet.max_row, 15) + 1):
        seen = {}
        for c in range(1, sheet.max_col + 1):
            h = norm(sheet.value(r, c))
            for field, names in cols.items():
                if h in names and field not in seen:
                    seen[field] = c
                    break
        if len(seen) >= 2:
            return r, seen
    return None


def number(v):
    try:
        if isinstance(v, bool) or v in (None, ''):
            return None
        return float(str(v).replace(',', '.').strip())
    except ValueError:
        return None


def serial_list(v):
    return [x for x in (re.sub(r'\s+', ' ', p).strip() for p in re.split(r'[\r\n,;]+', text(v))) if x]


def plan(data, state):
    """data: the .xlsx bytes; state: what the program has now ({'areas', 'itemTypes', 'settings'}). Returns the plan (see module text)."""
    wb = xlsx_read.read(data)
    out = {'sheets': [], 'areas': [], 'itemTypes': [], 'inventory': [], 'skipped': [], 'warnings': [], 'existingAreas': 0}
    areas_now = {norm(a['name']): a for a in state['areas']}
    types_now = {}
    for t in state['itemTypes']:
        for k in (t['name'], t.get('short') or t['name'], t['id']):
            types_now[norm(k)] = t
    locations = (state.get('settings') or {}).get('locations') or ['Production']
    used_serials = {norm(p['serial']): a['name'] for a in state['areas'] for p in a.get('pieces', [])}
    new_areas, new_types, pair_seen = {}, {}, set()
    inv_items = []

    def skip(sheet, row, why):
        out['skipped'].append({'sheet': sheet, 'row': row, 'reason': why})

    rows_total = 0
    for sh in wb.sheets:
        if sh.hidden:
            continue
        inv, ar = find_header(sh, INV_COLS), find_header(sh, AREA_COLS)
        kind = 'inventory' if inv and 'item' in inv[1] and ('qty' in inv[1] or 'area' in inv[1]) else 'areas' if ar and 'name' in ar[1] else None
        out['sheets'].append({'name': sh.name, 'kind': kind or 'ignored', 'rows': max(0, sh.max_row - (inv or ar or (0, 0))[0]) if kind else 0})
        if not kind:
            out['warnings'].append(f'Sheet "{sh.name}" was ignored: no header row with break area or item columns was found.')
            continue
        head, cols = (ar if kind == 'areas' else inv)
        for r in range(head + 1, sh.max_row + 1):
            get = lambda f: sh.value(r, cols[f]) if f in cols else None
            if not any(sh.value(r, c) not in (None, '') for c in range(1, sh.max_col + 1)):
                continue
            rows_total += 1
            if rows_total > MAX_ROWS:
                out['warnings'].append(f'Only the first {MAX_ROWS} rows were read.')
                break
            if kind == 'areas':
                name = text(get('name'))
                if not name:
                    skip(sh.name, r, 'no break area name')
                elif norm(name) in areas_now:
                    out['existingAreas'] += 1
                    skip(sh.name, r, f'"{name}" already exists (left as it is)')
                elif norm(name) in new_areas:
                    skip(sh.name, r, f'"{name}" appears twice in the file')
                else:
                    status = text(get('status'))
                    st = next((s for s in STATUSES if s.lower() == status.lower()), None)
                    if status and not st:
                        out['warnings'].append(f'{sh.name} row {r}: status "{status}" is not known, "Good" is used.')
                    size, cap = number(get('size')), number(get('capacity'))
                    a = {'key': 'n' + str(len(new_areas) + 1), 'name': name, 'location': text(get('location')) or locations[0], 'building': text(get('building')),
                         'floor': text(get('floor')), 'capacity': int(cap) if cap is not None and cap >= 0 else None, 'responsible': text(get('responsible')),
                         'size': size if size is not None and size >= 0 else None, 'status': st or 'Good', 'startDate': text(get('startDate')),
                         'description': text(get('description')), 'sheet': sh.name, 'row': r}
                    new_areas[norm(name)] = a
                    out['areas'].append(a)
            else:
                inv_items.append((sh.name, r, text(get('area')), text(get('item')), get('qty'), text(get('condition')), serial_list(get('serials')), text(get('note'))))
    # contents need the break areas of the file, so they are matched after all sheets are read
    for sheet, r, area_name, item_name, qty_raw, cond_raw, serials, note in inv_items:
        if not area_name or not item_name:
            skip(sheet, r, 'the break area or the item is missing')
            continue
        existing, fresh = areas_now.get(norm(area_name)), new_areas.get(norm(area_name))
        if not existing and not fresh:
            skip(sheet, r, f'break area "{area_name}" is not in the system and not in this file')
            continue
        t = types_now.get(norm(item_name))
        if not t:
            t = new_types.get(norm(item_name))
            if not t:
                t = {'key': 't' + str(len(new_types) + 1), 'name': item_name if item_name.endswith('s') else item_name + 's', 'short': item_name}
                new_types[norm(item_name)] = t
                out['itemTypes'].append(t)
        ref_item = {'id': t['id']} if 'id' in t else {'key': t['key']}
        ref_area = {'id': existing['id']} if existing else {'key': fresh['key']}
        pair = (existing['id'] if existing else fresh['key'], t.get('id') or t['key'])
        have = existing and any(e['item'] == t.get('id') for e in existing.get('inventory', []))
        if have or pair in pair_seen:
            skip(sheet, r, f'{area_name} already has {item_name} (left as it is)' if have else f'{area_name} / {item_name} appears twice in the file')
            continue
        qty = number(qty_raw)
        if qty_raw not in (None, '') and (qty is None or qty < 0 or qty != int(qty)):
            out['warnings'].append(f'{sheet} row {r}: quantity "{text(qty_raw)}" is not a whole number - the row was skipped.')
            skip(sheet, r, 'the quantity is not a whole number')
            continue
        good = []
        for s in serials:
            if norm(s) in used_serials:
                out['warnings'].append(f'{sheet} row {r}: serial number {s} is already used in {used_serials[norm(s)]} - left out.')
            else:
                used_serials[norm(s)] = area_name
                good.append(s)
        qty = int(qty) if qty is not None else max(1, len(good))
        if len(good) > qty:
            qty = len(good)  # a piece with a serial number is a piece
            out['warnings'].append(f'{sheet} row {r}: more serial numbers than pieces - the quantity was raised to {qty}.')
        cond = next((c for c in CONDITIONS if c.lower() == cond_raw.lower()), None)
        if cond_raw and not cond:
            out['warnings'].append(f'{sheet} row {r}: condition "{cond_raw}" is not known, "Good" is used.')
        pair_seen.add(pair)
        out['inventory'].append({'area': ref_area, 'item': ref_item, 'areaName': area_name, 'itemName': t['short'] if 'short' in t else item_name, 'qty': qty,
                                 'condition': cond or 'Good', 'note': note, 'serials': good, 'sheet': sheet, 'row': r})
    out['counts'] = {'areas': len(out['areas']), 'itemTypes': len(out['itemTypes']), 'inventory': len(out['inventory']),
                     'serials': sum(len(i['serials']) for i in out['inventory']), 'skipped': len(out['skipped'])}
    return out


TEMPLATE = {
    'Break Areas': (['Break Area', 'Location', 'Building', 'Floor', 'Capacity', 'Responsible', 'Area Size (m2)', 'Status', 'Start Date', 'Description'],
                    [['Canteen East', 'Production', 'Main Building', 'Ground Floor', 40, 'Ahmed Hassan', 120, 'Good', '2025-03-01', 'Break area of line 3 and 4'],
                     ['Canteen West', 'Admin', 'Admin Building', 'Floor 1', 25, 'Sara Mostafa', 80, 'Good', '', '']]),
    'Contents': (['Break Area', 'Item', 'Quantity', 'Condition', 'Serial Numbers', 'Notes'],
                 [['Canteen East', 'Chairs', 30, 'Good', '', ''],
                  ['Canteen East', 'TV Screens', 2, 'Good', 'TV-55-0142, TV-55-0143', 'Samsung 55 inch'],
                  ['Canteen West', 'Refrigerators', 1, 'Good', 'FR-2291', '']]),
}
