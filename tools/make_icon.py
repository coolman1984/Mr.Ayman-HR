"""Draws the program icon - a white coffee cup with steam on a rounded tile in the blue gradient of the Samsung UI kit - and
writes it as a Windows .ico file (or as SVG). The same drawing is used by the screens (APP_MARK in js/app.js, the page icon in
index.html), so the desktop shortcut, the installer, the window and the program look alike.
Pure Python, so the build needs no image files or extra packages.

    python tools/make_icon.py <output.ico>
    python tools/make_icon.py --svg          (prints the SVG of the same drawing)
"""
import struct
import sys
import zlib

TOP, BOTTOM, WHITE = (33, 137, 255), (20, 40, 160), (255, 255, 255)
# the drawing on a 64 x 64 grid (keep in step with APP_MARK in js/app.js)
TILE_R = 15
CUP = (19, 26, 43, 36)              # x0, y0, x1, y1 of the straight part; the bottom is half an ellipse
CUP_BOTTOM = (31, 36, 12, 11)       # cx, cy, rx, ry
HANDLE = (43, 34, 7, 3.5)           # cx, cy, outer r, inner r (right half only)
SAUCER = (15, 49, 47, 53)           # rounded bar
STEAM = [((26, 21), (23.5, 18), (28.5, 16), (26, 12)), ((35, 21), (32.5, 18), (37.5, 16), (35, 12))]
STEAM_W = 3.2

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
       '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2189FF"/><stop offset="1" stop-color="#1428A0"/></linearGradient></defs>'
       '<rect width="64" height="64" rx="15" fill="url(#g)"/>'
       '<g fill="#fff"><path d="M19 26h24v10a12 11 0 0 1-24 0z"/><path d="M43 27a7 7 0 0 1 0 14v-3.5a3.5 3.5 0 0 0 0-7z"/>'
       '<rect x="15" y="49" width="32" height="4" rx="2"/></g>'
       '<g fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"><path d="M26 21c-2.5-3 2.5-5 0-9"/><path d="M35 21c-2.5-3 2.5-5 0-9"/></g></svg>')


def _bezier(p0, p1, p2, p3, steps=24):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


STEAM_PTS = [_bezier(*s) for s in STEAM]


def _near_line(x, y, pts, half):
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
        if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= half * half:
            return True
    return False


def in_tile(x, y):
    cx, cy = min(max(x, TILE_R), 64 - TILE_R), min(max(y, TILE_R), 64 - TILE_R)
    return (x - cx) ** 2 + (y - cy) ** 2 <= TILE_R * TILE_R


def in_white(x, y):
    x0, y0, x1, y1 = CUP
    if x0 <= x <= x1 and y0 <= y <= y1:
        return True
    cx, cy, rx, ry = CUP_BOTTOM
    if y >= cy and ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
        return True
    hx, hy, ro, ri = HANDLE
    if x >= hx and ri * ri <= (x - hx) ** 2 + (y - hy) ** 2 <= ro * ro:
        return True
    sx0, sy0, sx1, sy1 = SAUCER
    r = (sy1 - sy0) / 2
    ccx = min(max(x, sx0 + r), sx1 - r)
    if (x - ccx) ** 2 + (y - (sy0 + r)) ** 2 <= r * r:
        return True
    if not (21 <= x <= 41 and 9.5 <= y <= 23.5):  # outside the steam: skip the slow check
        return False
    return any(_near_line(x, y, pts, STEAM_W / 2) for pts in STEAM_PTS)


def draw(n, ss=4):
    """n x n RGBA pixels; ss x ss samples per pixel give smooth edges"""
    px = []
    k = 64 / n
    for py in range(n):
        row = []
        for qx in range(n):
            tile = white = 0
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (qx + (sx + .5) / ss) * k, (py + (sy + .5) / ss) * k
                    if in_tile(x, y):
                        tile += 1
                        white += in_white(x, y)
            if not tile:
                row.append((0, 0, 0, 0))
                continue
            t = min(1.0, max(0.0, ((qx + .5) + (py + .5)) / (2 * n)))  # diagonal gradient like the SVG
            base = [TOP[i] * (1 - t) + BOTTOM[i] * t for i in range(3)]
            w = white / tile
            row.append(tuple(int(round(base[i] * (1 - w) + WHITE[i] * w)) for i in range(3)) + (int(round(255 * tile / (ss * ss))),))
        px.append(row)
    return px


def png(px):
    n = len(px)
    raw = b''.join(b'\x00' + bytes(v for p in row for v in p) for row in px)

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def ico(sizes=(256, 128, 64, 48, 32, 24, 16)):
    imgs = [png(draw(s, 2 if s >= 128 else 4)) for s in sizes]
    out = struct.pack('<HHH', 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    for s, d in zip(sizes, imgs):
        out += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(d), off)
        off += len(d)
    return out + b''.join(imgs)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == '--svg':
        print(SVG)
    elif sys.argv[1].endswith('.png'):
        with open(sys.argv[1], 'wb') as f:
            f.write(png(draw(256, 2)))
        print('icon written to', sys.argv[1])
    else:
        with open(sys.argv[1], 'wb') as f:
            f.write(ico())
        print('icon written to', sys.argv[1])
