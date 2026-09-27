"""Draws the program icon (a white table and two chairs on a blue tile) and writes it as a Windows .ico file.
Pure Python, so the build needs no image files or extra packages.

    python tools/make_icon.py <output.ico>
"""
import struct
import sys
import zlib

NAVY, BLUE, WHITE = (20, 40, 110, 255), (31, 111, 235, 255), (255, 255, 255, 255)


def draw(n):
    px = [[(0, 0, 0, 0)] * n for _ in range(n)]
    r = n * 0.18  # rounded corners

    def inside_tile(x, y):
        cx = min(max(x, r), n - 1 - r)
        cy = min(max(y, r), n - 1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def rect(x0, y0, x1, y1, c):
        for y in range(int(y0 * n), int(y1 * n)):
            for x in range(int(x0 * n), int(x1 * n)):
                px[y][x] = c
    for y in range(n):
        for x in range(n):
            if inside_tile(x, y):
                t = y / n
                px[y][x] = tuple(int(BLUE[i] * (1 - t) + NAVY[i] * t) for i in range(3)) + (255,)
    rect(0.22, 0.40, 0.78, 0.47, WHITE)   # table top
    rect(0.30, 0.47, 0.36, 0.74, WHITE)   # table legs
    rect(0.64, 0.47, 0.70, 0.74, WHITE)
    rect(0.10, 0.52, 0.18, 0.74, WHITE)   # chair left: back + seat
    rect(0.10, 0.60, 0.26, 0.65, WHITE)
    rect(0.82, 0.52, 0.90, 0.74, WHITE)   # chair right
    rect(0.74, 0.60, 0.90, 0.65, WHITE)
    rect(0.14, 0.24, 0.86, 0.30, WHITE)   # roof line of the break area
    return px


def png(px):
    n = len(px)
    raw = b''.join(b'\x00' + bytes(v for p in row for v in p) for row in px)

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', n, n, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b'')


def ico(sizes=(256, 64, 48, 32, 16)):
    imgs = [png(draw(s)) for s in sizes]
    out = struct.pack('<HHH', 0, 1, len(imgs))
    off = 6 + 16 * len(imgs)
    for s, d in zip(sizes, imgs):
        out += struct.pack('<BBBBHHII', s % 256, s % 256, 0, 0, 1, 32, len(d), off)
        off += len(d)
    return out + b''.join(imgs)


if __name__ == '__main__':
    with open(sys.argv[1], 'wb') as f:
        f.write(ico())
    print('icon written to', sys.argv[1])
