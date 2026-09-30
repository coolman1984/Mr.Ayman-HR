"""Builds js/icons.js - the icon pack of the program - from the Lucide icon set (ISC License, see docs/ICONS_LICENSE.txt).

  python tools/make_icons.py <folder with the Lucide *.svg files>

Get the set once (it is not part of the repository):
  npm pack lucide-static   (unpack it, the icons are in package/icons)

Only the icons listed below are taken, so the program stays small. PACK maps our icon name -> Lucide name; GROUPS is what the
item type window shows (in this order). Our names never change, so icons saved in the data keep working.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'js', 'icons.js')

# our name -> lucide name. The first block keeps the names that older data already uses.
PACK = {
    'chair': 'armchair', 'table': 'table-2', 'tv': 'tv', 'dispenser': 'glass-water', 'fridge': 'refrigerator', 'box': 'package',
    'microwave': 'microwave', 'coffee': 'coffee', 'plant': 'flower-2', 'sofa': 'sofa',
    # seating, tables, storage
    'stool': 'circle-dot', 'bench': 'rectangle-horizontal', 'bed': 'bed-single', 'desk': 'lamp-desk', 'locker': 'lock-keyhole',
    'shelf': 'library', 'cabinet': 'archive', 'drawer': 'inbox', 'basket': 'shopping-basket', 'whiteboard': 'presentation',
    'noticeboard': 'pin', 'mirror': 'frame', 'door': 'door-open', 'window': 'app-window', 'curtain': 'blinds',
    # electronics
    'monitor': 'monitor', 'projector': 'projector', 'speaker': 'speaker', 'radio': 'radio', 'wifi': 'wifi', 'router': 'router',
    'plug': 'plug', 'extension': 'plug-zap', 'charger': 'battery-charging', 'phone': 'smartphone', 'tablet': 'tablet',
    'camera': 'camera', 'cctv': 'cctv', 'headphones': 'headphones', 'printer': 'printer', 'computer': 'laptop', 'keyboard': 'keyboard',
    'clock': 'clock', 'game': 'gamepad-2', 'music': 'music', 'tvstand': 'tv-minimal',
    # appliances, kitchen
    'kettle': 'cooking-pot', 'toaster': 'sandwich', 'oven': 'flame', 'washer': 'washing-machine', 'freezer': 'snowflake',
    'icemaker': 'ice-cream-bowl', 'utensils': 'utensils', 'cutlery': 'utensils-crossed', 'cup': 'cup-soda', 'bottle': 'milk',
    'water': 'droplets', 'glass': 'glass-water', 'food': 'apple', 'snack': 'cookie', 'soup': 'soup', 'salad': 'salad',
    # climate and light
    'fan': 'fan', 'aircon': 'air-vent', 'heater': 'heater', 'thermometer': 'thermometer', 'light': 'lightbulb', 'lamp': 'lamp',
    'floorlamp': 'lamp-floor', 'power': 'zap', 'sun': 'sun', 'wind': 'wind',
    # cleaning, hygiene, safety
    'bin': 'trash-2', 'recycle': 'recycle', 'spray': 'spray-can', 'cleaning': 'brush-cleaning', 'sparkles': 'sparkles', 'shower': 'shower-head',
    'bath': 'bath', 'soap': 'hand-heart', 'extinguisher': 'fire-extinguisher', 'alarm': 'siren', 'firstaid': 'briefcase-medical',
    'shield': 'shield-check', 'warning': 'triangle-alert', 'lock': 'lock', 'key': 'key-round', 'smoke': 'cigarette-off',
    # decoration, leisure, information
    'flower': 'flower', 'leaf': 'leaf', 'sprout': 'sprout', 'tree': 'tree-deciduous', 'picture': 'image', 'book': 'book-open',
    'newspaper': 'newspaper', 'megaphone': 'megaphone', 'dice': 'dices', 'trophy': 'trophy', 'heart': 'heart', 'smile': 'smile',
    # tools and materials
    'wrench': 'wrench', 'hammer': 'hammer', 'paint': 'paintbrush', 'bucket': 'paint-bucket', 'ruler': 'ruler', 'toolbox': 'toolbox',
    'cog': 'cog', 'boxes': 'boxes', 'package': 'package-open', 'ladder': 'move-vertical', 'rope': 'cable',
    # user interface icons the screens need
    'help': 'circle-help', 'link': 'link', 'sync': 'refresh-cw', 'merge': 'git-merge', 'plan': 'flag', 'target': 'target', 'lightbulb': 'lightbulb',
    'listcheck': 'list-checks', 'repeat': 'repeat', 'import': 'file-up', 'word': 'file-text', 'sheet': 'file-spreadsheet', 'command': 'command',
}

GROUPS = [
    ('Seating and tables', ['chair', 'sofa', 'stool', 'bench', 'table', 'desk', 'bed', 'locker', 'shelf', 'cabinet', 'drawer', 'basket']),
    ('Screens and electronics', ['tv', 'monitor', 'tvstand', 'projector', 'speaker', 'radio', 'computer', 'keyboard', 'phone', 'tablet', 'camera', 'cctv',
                                 'headphones', 'printer', 'wifi', 'router', 'plug', 'extension', 'charger', 'clock', 'game', 'music']),
    ('Kitchen and drinks', ['fridge', 'freezer', 'microwave', 'oven', 'kettle', 'toaster', 'coffee', 'dispenser', 'water', 'glass', 'cup', 'bottle',
                            'icemaker', 'utensils', 'cutlery', 'food', 'snack', 'soup', 'salad', 'washer']),
    ('Climate and light', ['fan', 'aircon', 'heater', 'thermometer', 'light', 'lamp', 'floorlamp', 'power', 'sun', 'wind', 'curtain', 'window', 'door']),
    ('Cleaning and safety', ['bin', 'recycle', 'spray', 'cleaning', 'sparkles', 'shower', 'bath', 'soap', 'extinguisher', 'alarm', 'firstaid', 'shield',
                             'warning', 'lock', 'key', 'smoke']),
    ('Decoration and leisure', ['plant', 'flower', 'leaf', 'sprout', 'tree', 'rug', 'picture', 'mirror', 'whiteboard', 'noticeboard', 'book', 'newspaper',
                                'megaphone', 'dice', 'trophy', 'heart', 'smile']),
    ('Tools and other', ['box', 'boxes', 'package', 'toolbox', 'wrench', 'hammer', 'paint', 'bucket', 'ruler', 'cog', 'ladder', 'rope']),
]


def inner(svg):
    m = re.search(r'<svg[^>]*>(.*)</svg>', svg, re.S)
    body = re.sub(r'\s+', ' ', m.group(1)).strip()
    return re.sub(r'>\s+<', '><', body)


def main(folder):
    icons, missing = {}, []
    for ours, lucide in PACK.items():
        path = os.path.join(folder, lucide + '.svg')
        if not os.path.exists(path):
            missing.append(f'{ours} -> {lucide}')
            continue
        with open(path, encoding='utf-8') as f:
            icons[ours] = inner(f.read())
    if missing:
        sys.exit('These Lucide icons do not exist (fix PACK): ' + ', '.join(missing))
    groups = [(g, [n for n in names if n in icons or n == 'rug']) for g, names in GROUPS]
    lines = ['/* Icon pack of the Break Area Management System: icons from Lucide (ISC License, see docs/ICONS_LICENSE.txt).',
             '   Generated by tools/make_icons.py - do not edit by hand. Our icon names never change, so saved data keeps its icons. */',
             "'use strict';", 'const ICON_PACK = {']
    lines += [f"  {k}: '{v}'," for k, v in icons.items()]
    lines += ['};', 'const ICON_GROUPS = [' + ', '.join("['%s', [%s]]" % (g, ', '.join("'%s'" % n for n in names)) for g, names in groups) + '];', '']
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    print(f'{len(icons)} icons in {len(groups)} groups -> {OUT}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
