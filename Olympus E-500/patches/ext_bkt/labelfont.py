#!/usr/bin/env python3
"""Menu label bitmaps for the E-500 (fw 1.3), built from the stock label font.

Menu labels are ROM bitmaps (notes/2026-11-18-menu-labels-and-layouts.md): a 12-byte header
{u16 w, u16 h, u32 data, u32 0} and 2-bit pixels, 4 per byte, LSB first, rows of ceil(w/4)
bytes. Pixel 0 = transparent, 1 = outline, 3 = fill. The glyphs are cut from stock labels
("3F 0.3EV", ISO "100".."800", "S-AF+MF"), so new labels match the stock look. '±' does not
exist in the font; it is drawn here in the same style ('+' raised, with a bar under it).
There is no '9' either; it is the '6' turned 180 degrees.

  python3 labelfont.py IMAGE "13F ±2EV" [...] [--png out.png]   # preview (decoded image)
"""
import argparse
import struct
import zlib

BASE = 0x40030020
RES_TABLE = 0x403CA43C           # ROM resources 576..1447: table of header pointers
RES_FIRST = 576
H = 16                           # label height (all list-row labels are 96 x 16)

# (resource id, text): glyph sources. Columns are split at fully transparent columns.
SOURCES = [
    (0x516, "3F0.3EV"), (0x517, "3F0.5EV"), (0x518, "3F0.7EV"), (0x519, "3F1.0EV"),
    (0x4F2, "S-AF+MF"),
    (0x53F, "100"), (0x540, "125"), (0x541, "160"), (0x542, "200"), (0x543, "250"),
    (0x544, "320"), (0x545, "400"), (0x546, "500"), (0x547, "640"), (0x548, "800"),
]
SPACE = 6                        # blank columns for ' ' (plus the 1-column gaps either side)
GAP = 1                          # blank columns between glyphs
DIGIT = 12                       # digit cell width
# Stock labels these rules must reproduce bit for bit (checked by selftest()).
SELFTEST = [(0x516, "3F 0.3EV"), (0x517, "3F 0.5EV"), (0x518, "3F 0.7EV"), (0x519, "3F 1.0EV")]


def resource(plain, rid):
    """(w, h, pixel rows) of a ROM resource id in 576..1447."""
    p = struct.unpack_from("<I", plain, RES_TABLE - BASE + 4 * (rid - RES_FIRST))[0]
    w, h, dp = struct.unpack_from("<HHI", plain, p - BASE)
    stride = (w + 3) // 4
    rows = [[(plain[dp - BASE + y * stride + x // 4] >> (2 * (x % 4))) & 3 for x in range(w)]
            for y in range(h)]
    return w, h, rows


def glyphs(plain):
    """{char: list of pixel columns (each H values)} cut from the stock labels."""
    out = {}
    for rid, text in SOURCES:
        w, h, rows = resource(plain, rid)
        if h != H:
            raise ValueError(f"resource 0x{rid:x} is {w}x{h}, expected height {H}")
        cols = [[rows[y][x] for y in range(h)] for x in range(w)]
        runs, x = [], 0
        while x < w:
            if any(cols[x]):
                s = x
                while x < w and any(cols[x]):
                    x += 1
                runs.append(cols[s:x])
            else:
                x += 1
        if len(runs) != len(text):
            raise ValueError(f"resource 0x{rid:x}: {len(runs)} glyphs, expected {text!r}")
        for ch, g in zip(text, runs):
            if ch in out and out[ch] != g:
                raise ValueError(f"glyph {ch!r} differs between sources")
            out[ch] = g
    out["±"] = plus_minus(out["+"], out["-"])
    out["9"] = [list(reversed(c)) for c in reversed(out["6"])]   # no '9' in the font: '6' turned 180°
    return out


def plus_minus(plus, minus):
    """'±': the '+' glyph raised 2 rows (its outline clipped at row 0) over a bar from '-'."""
    w = len(plus)
    rows = [[plus[x][y] for x in range(w)] for y in range(H)]
    up = [rows[y + 2] if y + 2 < H else [0] * w for y in range(H)]
    up[0] = [1 if v else 0 for v in up[0]]           # keep a closed outline at the top
    # bar: the '-' glyph's filled rows and outline, widened to the '+' width, at rows 12..15
    mrows = [y for y in range(H) if any(minus[x][y] == 3 for x in range(len(minus)))]
    bar_h = len(mrows)
    top = H - bar_h - 2
    for y in range(top - 1, H):
        up[y] = [0] * w
    for y in range(top - 1, top + bar_h + 1):
        for x in range(w):
            inner = top <= y < top + bar_h and 0 < x < w - 1
            up[y][x] = 3 if inner else 1
    return [[up[y][x] for y in range(H)] for x in range(w)]


def render(font, text):
    """Pixel rows (H x width) for text, glyphs separated by GAP blank columns."""
    cols = []
    for i, ch in enumerate(text):
        if i:
            cols += [[0] * H] * GAP
        if ch != " " and ch not in font:
            raise ValueError(f"no glyph for {ch!r} in the label font")
        if ch == " ":
            cols += [[0] * H] * SPACE
        elif ch.isdigit() and len(font[ch]) < DIGIT:   # tabular digits: narrow ones centred
            left = (DIGIT - len(font[ch])) // 2
            cols += [[0] * H] * left + font[ch] + [[0] * H] * (DIGIT - len(font[ch]) - left)
        else:
            cols += font[ch]
    return [[c[y] for c in cols] for y in range(H)]


def pad(rows, width, left=None):
    """Place rows in a bitmap `width` wide, centred unless `left` is given."""
    w = len(rows[0])
    if w > width:
        raise ValueError(f"label is {w} px wide, more than {width}")
    if left is None:
        left = (width - w) // 2
    return [[0] * left + r + [0] * (width - w - left) for r in rows]


def selftest(plain, font):
    """The stock '3F x.xEV' labels must come out of render() identical (at x = 3 in 96)."""
    for rid, text in SELFTEST:
        w, h, rows = resource(plain, rid)
        if pad(render(font, text), w, left=3) != rows:
            raise ValueError(f"font rules do not reproduce stock label 0x{rid:x} {text!r}")


def encode(rows):
    """2-bit LSB-first packed pixel data, rows of ceil(w/4) bytes."""
    w = len(rows[0])
    stride = (w + 3) // 4
    out = bytearray(stride * len(rows))
    for y, r in enumerate(rows):
        for x, v in enumerate(r):
            out[y * stride + x // 4] |= v << (2 * (x % 4))
    return bytes(out)


def png(path, images, scale=3, gap=4):
    """Write images (lists of pixel rows) stacked vertically, for previews."""
    pal = [(24, 24, 24), (235, 235, 235), (255, 80, 80), (60, 140, 255)]
    W = max(len(r[0]) for r in images) * scale
    lines = []
    for im in images:
        for row in im:
            line = bytearray()
            for v in row:
                line += bytes(pal[v]) * scale
            line += bytes([0, 70, 0]) * (W - len(row) * scale)
            lines += [bytes(line)] * scale
        lines += [bytes([0, 70, 0]) * W] * gap

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b))
    raw = b"".join(b"\0" + ln for ln in lines)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, len(lines), 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", help="decoded stock image (oly_fw.py decode)")
    ap.add_argument("text", nargs="+")
    ap.add_argument("--png")
    a = ap.parse_args()
    plain = open(a.image, "rb").read()
    font = glyphs(plain)
    selftest(plain, font)
    ims = []
    for t in a.text:
        r = render(font, t)
        print(f"{t!r}: {len(r[0])} px")
        ims.append(pad(r, max(96, len(r[0]))))
    if a.png:
        png(a.png, ims)


if __name__ == "__main__":
    main()
