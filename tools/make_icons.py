"""Builds js/icons.js - the icon pack of the program - from the Lucide icon set (ISC License, see docs/ICONS_LICENSE.txt).

  python tools/make_icons.py <folder of the unpacked lucide-static package>   (the folder that holds icons/ and tags.json)

Get the set once (it is not part of the repository):
  npm pack lucide-static   (unpack it into an empty folder; pass the "package" folder)

Only the icons listed below are taken, so the program stays small. Our icon names never change, so icons saved in the data
keep working:
- PACK maps the short names of the first icon pack (2.6) to Lucide names. Never rename or remove one.
- GROUPS is what the icon picker shows, in this order. An entry is either a PACK name or a Lucide name; a Lucide name
  becomes our name in camelCase ("washing-machine" -> "washingMachine").
- A name that the screens already define in js/app.js (IC) keeps the screen icon and is only listed in the picker.
ICON_TAGS holds search words per icon (the Lucide tags), so "water" also finds the dispenser.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'js', 'icons.js')

# our name -> lucide name. The first pack (2.6); older data uses these names.
PACK = {
    'chair': 'armchair', 'table': 'table-2', 'tv': 'tv', 'dispenser': 'glass-water', 'fridge': 'refrigerator', 'box': 'package',
    'microwave': 'microwave', 'coffee': 'coffee', 'plant': 'flower-2', 'sofa': 'sofa',
    'stool': 'circle-dot', 'bench': 'rectangle-horizontal', 'bed': 'bed-single', 'desk': 'lamp-desk', 'locker': 'lock-keyhole',
    'shelf': 'library', 'cabinet': 'archive', 'drawer': 'inbox', 'basket': 'shopping-basket', 'whiteboard': 'presentation',
    'noticeboard': 'pin', 'mirror': 'frame', 'door': 'door-open', 'window': 'app-window', 'curtain': 'blinds',
    'monitor': 'monitor', 'projector': 'projector', 'speaker': 'speaker', 'radio': 'radio', 'wifi': 'wifi', 'router': 'router',
    'plug': 'plug', 'extension': 'plug-zap', 'charger': 'battery-charging', 'phone': 'smartphone', 'tablet': 'tablet',
    'camera': 'camera', 'cctv': 'cctv', 'headphones': 'headphones', 'printer': 'printer', 'computer': 'laptop', 'keyboard': 'keyboard',
    'clock': 'clock', 'game': 'gamepad-2', 'music': 'music', 'tvstand': 'tv-minimal',
    'kettle': 'cooking-pot', 'toaster': 'sandwich', 'oven': 'flame', 'washer': 'washing-machine', 'freezer': 'snowflake',
    'icemaker': 'ice-cream-bowl', 'utensils': 'utensils', 'cutlery': 'utensils-crossed', 'cup': 'cup-soda', 'bottle': 'milk',
    'water': 'droplets', 'glass': 'glass-water', 'food': 'apple', 'snack': 'cookie', 'soup': 'soup', 'salad': 'salad',
    'fan': 'fan', 'aircon': 'air-vent', 'heater': 'heater', 'thermometer': 'thermometer', 'light': 'lightbulb', 'lamp': 'lamp',
    'floorlamp': 'lamp-floor', 'power': 'zap', 'sun': 'sun', 'wind': 'wind',
    'bin': 'trash-2', 'recycle': 'recycle', 'spray': 'spray-can', 'cleaning': 'brush-cleaning', 'sparkles': 'sparkles', 'shower': 'shower-head',
    'bath': 'bath', 'soap': 'hand-heart', 'extinguisher': 'fire-extinguisher', 'alarm': 'siren', 'firstaid': 'briefcase-medical',
    'shield': 'shield-check', 'warning': 'triangle-alert', 'lock': 'lock', 'key': 'key-round', 'smoke': 'cigarette-off',
    'flower': 'flower', 'leaf': 'leaf', 'sprout': 'sprout', 'tree': 'tree-deciduous', 'picture': 'image', 'book': 'book-open',
    'newspaper': 'newspaper', 'megaphone': 'megaphone', 'dice': 'dices', 'trophy': 'trophy', 'heart': 'heart', 'smile': 'smile',
    'wrench': 'wrench', 'hammer': 'hammer', 'paint': 'paintbrush', 'bucket': 'paint-bucket', 'ruler': 'ruler', 'toolbox': 'toolbox',
    'cog': 'cog', 'boxes': 'boxes', 'package': 'package-open', 'ladder': 'move-vertical', 'rope': 'cable',
    # user interface icons the screens need
    'help': 'circle-help', 'link': 'link', 'sync': 'refresh-cw', 'merge': 'git-merge', 'plan': 'flag', 'target': 'target', 'lightbulb': 'lightbulb',
    'listcheck': 'list-checks', 'repeat': 'repeat', 'import': 'file-up', 'word': 'file-text', 'sheet': 'file-spreadsheet', 'command': 'command',
}

GROUPS = [
    ('Seating and furniture', [
        'chair', 'sofa', 'stool', 'bench', 'rocking-chair', 'table', 'table-properties', 'desk', 'bed', 'bed-double', 'locker', 'shelf',
        'shelving-unit', 'library-big', 'cabinet', 'archive-restore', 'drawer', 'basket', 'shopping-cart', 'container', 'vault',
        'mirror-round', 'mirror-rectangular', 'towel-rack', 'umbrella', 'parasol', 'tent', 'lectern', 'podium',
        'columns-3', 'rows-3', 'layout-grid', 'grid-2x2', 'square']),
    ('Screens and electronics', [
        'tv', 'tv-2', 'tv-minimal-play', 'tvstand', 'monitor', 'monitor-play', 'monitor-speaker', 'monitor-smartphone', 'projector',
        'presentation', 'speaker', 'boom-box', 'radio', 'radio-receiver', 'computer', 'laptop-2', 'pc-case', 'keyboard', 'mouse',
        'phone', 'phone-call', 'tablet', 'tablet-smartphone', 'smartphone-charging', 'camera', 'webcam', 'video', 'cctv', 'headphones',
        'headset', 'mic', 'printer', 'printer-3d', 'scan-barcode', 'scan-qr-code', 'barcode', 'qr-code', 'credit-card-reader',
        'wifi', 'router', 'antenna', 'satellite-dish', 'bluetooth', 'cable', 'usb', 'hdmi-port', 'ethernet-port', 'plug', 'plug-2',
        'extension', 'unplug', 'charger', 'battery-full', 'battery-low', 'battery-warning', 'hard-drive', 'server', 'cpu',
        'memory-stick', 'clock', 'alarm-clock', 'watch', 'timer', 'hourglass', 'calculator', 'game', 'gamepad', 'joystick',
        'music', 'disc-3', 'turntable', 'cassette-tape']),
    ('Kitchen and appliances', [
        'fridge', 'freezer', 'microwave', 'oven', 'kettle', 'toaster', 'blender', 'cooking-pot', 'chef-hat', 'coffee', 'dispenser',
        'faucet', 'water', 'droplet', 'glass', 'cup', 'bottle', 'milk', 'bottle-wine', 'beer', 'wine', 'martini', 'can-soda',
        'icemaker', 'utensils', 'cutlery', 'fork-knife', 'hand-platter', 'concierge-bell', 'washer', 'soap-dispenser-droplet',
        'thermometer-snowflake', 'thermometer-sun', 'flame-kindling', 'weight', 'scale', 'paper-bag', 'shopping-bag', 'carton']),
    ('Food and snacks', [
        'food', 'banana', 'cherry', 'citrus', 'grape', 'carrot', 'broccoli', 'leafy-green', 'salad', 'soup', 'sandwich', 'pizza',
        'hamburger', 'croissant', 'egg-fried', 'egg', 'beef', 'drumstick', 'ham', 'fish', 'shrimp', 'wheat', 'bean', 'snack',
        'cake', 'cake-slice', 'cupcake', 'dessert', 'donut', 'candy', 'lollipop', 'popsicle', 'ice-cream-cone', 'ice-cream-bowl',
        'popcorn', 'cookie', 'nut', 'vegan']),
    ('Climate, light and power', [
        'fan', 'aircon', 'heater', 'thermometer', 'snowflake', 'sun', 'sun-dim', 'moon', 'cloud', 'cloud-sun', 'cloud-rain', 'wind',
        'waves', 'light', 'lightbulb-off', 'lamp', 'floorlamp', 'lamp-ceiling', 'lamp-wall-up', 'lamp-wall-down', 'flashlight',
        'spotlight', 'power', 'zap-off', 'power-off', 'bolt', 'solar-panel', 'ev-charger', 'fuel', 'gauge', 'utility-pole',
        'curtain', 'window', 'app-window-mac', 'door', 'door-closed', 'door-closed-locked', 'door-stairwell']),
    ('Cleaning and hygiene', [
        'bin', 'trash', 'recycle', 'spray', 'cleaning', 'broom', 'broom-sparkles', 'mop', 'mop-sparkles', 'brush', 'sparkles',
        'sparkle', 'bubbles', 'shower', 'bath', 'toilet', 'toothbrush', 'soap', 'tube-lotion', 'hand', 'robot-vacuum', 'droplets',
        'droplet-off', 'shredder', 'germ', 'virus', 'shirt']),
    ('Safety and health', [
        'extinguisher', 'flame', 'alarm', 'alarm-smoke', 'bell-ring', 'firstaid', 'cross', 'heart-pulse', 'stethoscope', 'pill',
        'pill-bottle', 'syringe', 'thermometer', 'bandage', 'ambulance', 'hospital', 'accessibility', 'shield', 'shield-alert',
        'shield-plus', 'shield-user', 'hard-hat', 'glasses', 'ear', 'warning', 'octagon-alert', 'circle-alert', 'ban', 'construction',
        'traffic-cone', 'cone', 'biohazard', 'radiation', 'skull', 'life-buoy', 'smoke', 'cigarette', 'lock', 'lock-open', 'key',
        'fingerprint', 'id-card', 'id-card-lanyard']),
    ('Building and rooms', [
        'house', 'building', 'building-2', 'factory', 'warehouse', 'store', 'hotel', 'school', 'university', 'landmark', 'church',
        'mosque', 'castle', 'tent-tree', 'fence', 'brick-wall', 'land-plot', 'map', 'map-pin', 'map-pinned',
        'navigation', 'compass', 'signpost', 'milestone', 'route', 'parking-meter', 'square-parking', 'house-plug', 'house-wifi',
        'door-closed-package', 'bridge', 'dam', 'tower-control', 'lighthouse']),
    ('Decoration and plants', [
        'plant', 'rug', 'plant-pot', 'flower', 'rose', 'leaf', 'sprout', 'clover', 'shrub', 'tree', 'tree-pine', 'tree-palm', 'trees',
        'picture', 'images', 'mirror', 'wallpaper', 'palette', 'paintbrush-2', 'gem', 'crown', 'star', 'stars', 'heart',
        'ribbon', 'gift', 'balloon', 'party-popper', 'sticker', 'flag', 'flag-triangle-right', 'medal', 'award', 'trophy', 'mountain',
        'rainbow', 'feather', 'amphora', 'origami', 'shell', 'bird', 'birdhouse', 'cat', 'dog', 'fish-symbol', 'paw-print']),
    ('Leisure and sport', [
        'dice', 'dice-6', 'puzzle', 'toy-brick', 'chess-knight', 'chess-king', 'playing-cards', 'tic-tac-toe', 'book', 'book-open-text',
        'library', 'newspaper', 'bookmark', 'dumbbell', 'biceps-flexed', 'bike', 'volleyball', 'rugby-ball', 'goal', 'target',
        'whistle', 'sport-shoe', 'footprints', 'person-standing', 'guitar', 'piano', 'drum', 'music-2', 'mic-vocal', 'film',
        'clapperboard', 'theater', 'drama', 'ticket', 'ferris-wheel', 'roller-coaster', 'kayak', 'sailboat', 'tickets', 'smile',
        'laugh', 'meh', 'frown', 'thumbs-up', 'thumbs-down', 'handshake', 'heart-handshake']),
    ('Office and information', [
        'whiteboard', 'noticeboard', 'pin', 'megaphone', 'speech', 'message-square', 'messages-square', 'mail', 'mailbox', 'inbox',
        'send', 'bell', 'calendar', 'calendar-days', 'calendar-clock', 'calendar-check', 'clipboard', 'clipboard-list',
        'clipboard-check', 'notebook', 'notebook-pen', 'notepad-text', 'sticky-note', 'file', 'files', 'file-text', 'file-check',
        'file-spreadsheet', 'folder', 'folder-open', 'archive', 'briefcase', 'pen', 'pencil', 'highlighter', 'eraser', 'scissors',
        'paperclip', 'stamp', 'signature', 'tag', 'tags', 'receipt', 'wallet', 'banknote', 'coins', 'piggy-bank', 'credit-card',
        'chart-bar', 'chart-column', 'chart-pie', 'chart-line', 'trending-up', 'trending-down', 'kanban', 'list-todo', 'list-checks',
        'info', 'help', 'languages', 'globe', 'graduation-cap']),
    ('Tools and maintenance', [
        'toolbox', 'tool-case', 'wrench', 'hammer', 'drill', 'axe', 'pickaxe', 'shovel', 'pocket-knife',
        'anvil', 'nut', 'bolt', 'cog', 'settings-2', 'paint', 'paint-roller', 'bucket', 'pipette', 'ruler', 'ruler-dimension-line',
        'pencil-ruler', 'drafting-compass', 'ladder', 'rope', 'magnet', 'spool', 'scale-3d', 'cylinder', 'barrel', 'boxes', 'box',
        'package', 'package-check', 'package-plus', 'package-x', 'package-search', 'wrench-off', 'hard-hat', 'construction',
        'brick-wall', 'plug-zap', 'unplug', 'sliders-horizontal']),
    ('Transport and logistics', [
        'truck', 'truck-electric', 'forklift', 'van', 'car', 'car-front', 'bus', 'bus-front', 'motorbike', 'scooter', 'bike',
        'train-front', 'tram-front', 'plane', 'ship', 'ship-cargo', 'tractor', 'trailer', 'caravan', 'container', 'luggage',
        'backpack', 'handbag', 'baggage-claim', 'briefcase-conveyor-belt', 'hand-coins', 'road', 'fuel', 'parking-circle']),
    ('People and work', [
        'user', 'users', 'user-plus', 'user-check', 'user-cog', 'user-round', 'users-round', 'contact', 'baby', 'person-standing',
        'accessibility', 'hand-helping', 'hand-heart', 'helping-hand', 'brain', 'eye', 'ear', 'clock-check', 'timer-reset',
        'calendar-check-2', 'briefcase-business', 'presentation', 'school-2', 'award', 'badge-check', 'medal', 'crown', 'star-check']),
    ('Status and signs', [
        'check', 'check-check', 'circle-check', 'circle-check-big', 'circle-x', 'circle-plus', 'circle-minus', 'circle-dot',
        'circle-pause', 'circle-play', 'circle-stop', 'circle-help', 'badge-alert', 'badge-info', 'badge-plus', 'octagon-x',
        'triangle', 'circle', 'hexagon', 'diamond', 'pentagon', 'octagon', 'shapes', 'arrow-up', 'arrow-down', 'arrow-left-right',
        'arrow-up-down', 'refresh-cw', 'rotate-ccw', 'repeat', 'history', 'hourglass', 'loader', 'zap', 'flame', 'snowflake',
        'eye-off', 'bell-off', 'volume-2', 'volume-x', 'wifi-off', 'battery', 'signal', 'activity', 'radar', 'thumbs-up',
        'hash', 'percent', 'infinity', 'link', 'qr-code', 'scan', 'search', 'zoom-in', 'filter', 'sync', 'merge', 'plan', 'lightbulb',
        'listcheck', 'import', 'word', 'sheet', 'command', 'panel-left-open', 'panel-left-close', 'maximize', 'minimize']),
]


def camel(lucide):
    first, *rest = lucide.split('-')
    return first + ''.join(p[:1].upper() + p[1:] for p in rest)


def inner(svg):
    m = re.search(r'<svg[^>]*>(.*)</svg>', svg, re.S)
    body = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.S)
    body = re.sub(r'\s+', ' ', body).strip()
    return re.sub(r'>\s+<', '><', body)


def screen_icons():
    """names the screens define themselves (IC in js/app.js): they keep their own drawing"""
    with open(os.path.join(ROOT, 'js', 'app.js'), encoding='utf-8') as f:
        text = f.read()
    block = text.split('const IC = {', 1)[1].split('\n};', 1)[0]
    return set(re.findall(r"^\s{2}(\w+): '<", block, re.M))


def main(folder):
    icons_dir = os.path.join(folder, 'icons')
    with open(os.path.join(folder, 'tags.json'), encoding='utf-8') as f:
        tags = json.load(f)
    screens = screen_icons()
    lucide_of = dict(PACK)
    groups, missing, seen = [], [], set()
    for title, entries in GROUPS:
        names = []
        for e in entries:
            ours = e if e in PACK or e in screens else camel(e)
            if ours not in PACK and ours not in screens:
                lucide_of.setdefault(ours, e)
            if ours not in seen:  # an icon is shown once, in the first group that lists it
                seen.add(ours)
                names.append(ours)
        groups.append((title, names))
    icons = {}
    for ours, lucide in lucide_of.items():
        if ours in screens and ours not in PACK:
            continue
        path = os.path.join(icons_dir, lucide + '.svg')
        if not os.path.exists(path):
            missing.append(f'{ours} -> {lucide}')
            continue
        with open(path, encoding='utf-8') as f:
            icons[ours] = inner(f.read())
    if missing:
        sys.exit('These Lucide icons do not exist (fix GROUPS or PACK): ' + ', '.join(missing))
    # a new name whose drawing is already offered (Lucide aliases such as palmtree / tree-palm) is left out of the picker;
    # PACK names always stay offered (they are saved in item types)
    drawn, kept = set(), []
    for g, names in groups:
        out = []
        for n in names:
            if n not in icons and n not in screens:
                continue
            body = icons.get(n, 'screen:' + n)
            if body in drawn and n not in PACK:
                icons.pop(n, None)
                continue
            drawn.add(body)
            out.append(n)
        kept.append((g, out))
    groups = kept
    offered = {n for _, names in groups for n in names}
    words = {}
    for n in sorted(offered):
        # search words: our Lucide name, or for a name the screens draw, the Lucide icon of the same name
        lucide = lucide_of.get(n) or re.sub(r'([a-z])([A-Z])', r'\1-\2', n).lower()
        w = [lucide.replace('-', ' ')] + tags.get(lucide, [])[:10]
        w = ' '.join(dict.fromkeys(x.lower() for x in w if x and x.lower() != n.lower()))
        words[n] = re.sub(r"[^a-z0-9 ]", '', w)
    lines = ['/* Icon pack of the Break Area Management System: icons from Lucide (ISC License, see docs/ICONS_LICENSE.txt).',
             '   Generated by tools/make_icons.py - do not edit by hand. Our icon names never change, so saved data keeps its icons. */',
             "'use strict';", 'const ICON_PACK = {']
    lines += [f"  {k}: '{v}'," for k, v in icons.items()]
    lines += ['};', 'const ICON_GROUPS = [']
    lines += ["  ['%s', [%s]]," % (g, ', '.join("'%s'" % n for n in names)) for g, names in groups]
    lines += ['];', '/* search words per icon (Lucide tags), used by the icon picker */', 'const ICON_TAGS = {']
    lines += [f"  {k}: '{v}'," for k, v in words.items() if v]
    lines += ['};', '']
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))
    print(f'{len(icons)} icons in the pack, {len(offered)} offered in {len(groups)} groups -> {OUT}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
