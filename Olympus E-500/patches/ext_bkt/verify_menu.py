#!/usr/bin/env python3
"""Tests of the bracket preset menu (menu.S + menu_data.py) in ext_bkt (E-500 fw 1.3).

The real bytes of a STOCK and a PATCHED decoded image run in tools/mn103_sim.py:
  1. resource lookup 0x400FBA83, every id 0..0xFFFF: patched == stock, except the preset
     label ids, which return their new headers (registers d0-d3, a2, a3, sp checked)
  2. layout lookup 0x40076A4A, every id 0..0xFFFF: the layout pointer passed on is the
     stock one, except the new layout ids and the two repointed submenus (-> the grid)
  3. ae_bkt_validate: a preset n gives exactly what stock gives for #6 = 5, any other #6
     exactly stock (return value and RAM writes)
  4. ui_fmt_bkt_count's character window, #6 = 0..255: stock, except presets -> stock's 5-case
     with the preset's two digits
Then the patched data, read back from the image as the firmware reads it:
  5. 1/3-EV option list: stock entries 0-3 (byte for byte), then {n, 0x55, 1} per preset;
     codes 0-3 then new unique codes; other EV-step lists untouched
  6. grid (layouts 1183 and 1594): panel, one button and one label per option, at the option's
     index, inside the panel, not overlapping; each label bitmap (looked up through the
     patched resource table) is exactly the font rendering of the option's text
  7. value display (#6 entry): stock entries unchanged; each preset code -> a layout whose image
     is that preset's label; the other kinds -> the stock "BKT" layouts
  8. no stock layout record refers to an id in the new resource / layout ranges

  python3 verify_menu.py <decoded_stock.bin> <decoded_patched.bin> [--presets ...] [--png out.png]
"""
import argparse
import itertools
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
sys.path.insert(0, HERE)
import labelfont  # noqa: E402
import menu_data as md  # noqa: E402
import mn103_sim  # noqa: E402

BASE = 0x40030020
M32 = 0xFFFFFFFF
RES_FN, RES_END = 0x400FBA83, 0x400FBB3A
LANG_PTR, LANG_CHECK = 0xB013F98C, 0x400FBB3A
LAY_FN, LAY_CALL = 0x40076A4A, 0x40076A60
VAL_FN, VAL_END = 0x4006071C, 0x40060900
FMT_START, FMT_END = 0x4006231E, 0x40062356
SETTING_GET = 0x400394A7
SKIP_END, MENU_CODE = 0x406F7000, (0x406F7000, 0x406F7100)   # skip.S (from ext_lo on), menu.S
SAVED = ("d2", "d3", "a2", "a3", "sp")
PANEL = (0, 0x23, 0x138, 0x93)          # layout 876: x, y, w, h


def hooks(info):
    """Code ranges of the helpers, starting at instructions (skip.S begins with its preset table)."""
    return [(info["ext_lo"], SKIP_END), MENU_CODE]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def rd(img, a, k):
    return img[a - BASE:a - BASE + k]


# ---------------------------------------------------------------- 1. resource lookup
def test_res(stock, patched, info):
    rng = [(RES_FN, RES_END)]
    st, pa = mn103_sim.Sim(stock, BASE, rng), mn103_sim.Sim(patched, BASE, rng + hooks(info))
    fake_lang, fake_t8, fake_t12 = 0x62000000, 0x62001000, 0x62003000
    want_ext = {rid: struct.unpack_from("<I", patched, info["res_table"] - BASE + 4 * k)[0]
                for k, rid in enumerate(info["res_ids"])}
    for sim in (st, pa):
        sim.reset()
        sim.stubs = {LANG_CHECK: lambda s, regs, imm: s.r.update(d0=1, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)}
        sim.wr(LANG_PTR, 4, fake_lang)
        sim.wr(fake_lang + 8, 4, fake_t8)
        sim.wr(fake_lang + 12, 4, fake_t12)
        for i in range(576):
            sim.wr(fake_t8 + 4 * i, 4, 0x63000000 + i)
        for i in range(3):
            sim.wr(fake_t12 + 4 * i, 4, 0x64000000 + i)
        sim.base_mem = dict(sim.mem)
    checked = 0
    for rid in range(0x10000):
        out = []
        for sim in (st, pa):
            sim.mem = dict(sim.base_mem)
            sim.frames = []
            sim.r.update(d0=rid, d1=0x77777777, d2=0x13572468, d3=0x24681357, a0=0x600000A0, a1=0x600000A1,
                         a2=0x600000A2, a3=0x600000A3, sp=0x7F000000)
            before = dict(sim.r)
            r = sim.call(RES_FN, ("d2", "d3", "a2", "a3"), 24, d1=0, **{"d0": rid})
            for k in SAVED:
                assert r[k] == before[k], ("res: register not preserved", hex(rid), k)
            out.append(r)
        s, p = out
        if rid in want_ext:
            assert p["a0"] == want_ext[rid] and s["a0"] == 0, ("res: preset id", hex(rid), hex(s["a0"]), hex(p["a0"]))
        else:
            assert p["a0"] == s["a0"], ("res: differs from stock", hex(rid), hex(s["a0"]), hex(p["a0"]))
        for k in ("d0", "d1"):
            assert p[k] == s[k], ("res: register differs from stock", hex(rid), k, hex(s[k]), hex(p[k]))
        checked += 1
    return checked


# ---------------------------------------------------------------- 2. layout lookup
def test_lay(stock, patched, info):
    rng = [(LAY_FN, LAY_CALL + 7)]
    st, pa = mn103_sim.Sim(stock, BASE, rng), mn103_sim.Sim(patched, BASE, rng + hooks(info))
    want_ext = {md.EXT_LAY + k: struct.unpack_from("<I", patched, info["lay_table"] - BASE + 4 * k)[0]
                for k in range(info["lay_n"])}
    want_ext.update({slot: info["grid"] for slot in md.GRID_SLOTS})      # the repointed submenus
    checked = 0
    for lid in range(0x10000):
        out = []
        for sim in (st, pa):
            sim.reset()
            sp = sim.r["sp"]
            sim.wr(sp + 20, 4, 0x1234)              # the caller's x / y arguments
            sim.wr(sp + 24, 4, 0x5678)
            sim.r.update(d0=0xC0, d1=lid | 0xABCD0000, d2=0x13572468, d3=0x24681357, a2=0x600000A2, a3=0x600000A3)
            before = dict(sim.r)
            r = sim.run(LAY_FN, until=LAY_CALL)
            for k in ("d0", "d2", "d3", "a3", "sp"):
                assert r[k] == before[k], ("lay: register changed", hex(lid), k)
            out.append((sim.rd(sp + 4, 4), sim.rd(sp + 8, 4), r["d1"]))
        s, p = out
        word = lambda img: struct.unpack_from("<I", img, md.LAYOUT_TABLE - BASE + 4 * lid)[0]  # noqa: E731
        assert s[0] == word(stock), ("lay: stock sim != stock rule", hex(lid))
        assert p[1:] == s[1:], ("lay: arguments differ", hex(lid))
        if lid in want_ext:
            assert p[0] == want_ext[lid], ("lay: new id", hex(lid), hex(p[0]))
        else:   # the stock rule (table[id], unbounded) on the patched image: past entry 4597 that
            # reads whatever follows the table, which the patch may have changed
            assert p[0] == word(patched), ("lay: differs from the stock rule", hex(lid), hex(p[0]))
            if lid < md.LAYOUT_COUNT:
                assert p == s, ("lay: differs from stock", hex(lid), s, p)
        checked += 1
    return checked


# ---------------------------------------------------------------- 3. validator
def test_val(stock, patched, presets, info):
    rng = [(VAL_FN, VAL_END)]
    st, pa = mn103_sim.Sim(stock, BASE, rng), mn103_sim.Sim(patched, BASE, rng + hooks(info))
    ns = {n for n, _, _ in presets}
    checked = 0

    def run(sim, vals):
        calls = []

        def get(s, regs, imm):
            assert (regs, imm) == (["d2", "d3"], 12), "setting_get frame"
            s.r.update(d0=vals[s.r["d0"] & 0xFFFF] & M32, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)

        def other(s, regs, imm, tgt):
            calls.append((tgt, s.r["d0"], s.r["d1"], s.r["a0"], s.r["a1"]))
            s.r.update(d0=0x5A5A0000, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)
        sim.reset()
        sim.stubs = {SETTING_GET: get, 0x40124371: lambda s, r, i: other(s, r, i, 0x40124371)}
        sim.r.update(d2=0x13572468, d3=0x24681357, a2=0x600000A2, a3=0x600000A3)
        before = dict(sim.r)
        r = sim.call(VAL_FN, ("d2", "d3", "a2", "a3"), 24)
        for k in SAVED:
            assert r[k] == before[k], ("val: register not preserved", vals, k)
        mem = {a: v for a, v in sim.mem.items() if a < 0x7E000000}        # RAM writes (not the stack)
        return r["d0"], mem, calls

    for s6, s131, s8, s3 in itertools.product(sorted({0, 2, 3, 4, 5, 6, 255} | ns | {m + 1 for m in ns}),
                                              (0x55, 0x80, 0x100), (0, 0x55, 0x80, 0xAA, 0x100),
                                              (-0x300, -0x155, -0x100, 0, 0xAA, 0x155, 0x200, 0x300)):
        vals = {6: s6, 131: s131, 8: s8, 3: s3}
        got = run(pa, vals)
        want = run(st, {**vals, 6: 5} if s6 in ns else vals)
        assert got == want, ("val: differs", vals, got, want)
        checked += 1
    return checked


# ---------------------------------------------------------------- 4. count formatter
def test_fmt(stock, patched, presets, info):
    rng = [(FMT_START, FMT_END + 2)]
    st, pa = mn103_sim.Sim(stock, BASE, rng), mn103_sim.Sim(patched, BASE, rng + hooks(info))
    ns = {n for n, _, _ in presets}
    checked = 0
    five = None
    for n in [5] + list(range(256)):
        out = []
        for sim in (st, pa):
            sim.reset()
            sim.stubs = {SETTING_GET: lambda s, regs, imm: s.r.update(
                d0=n if s.r["d0"] == 6 else 0xBAD, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)}
            sp = sim.r["sp"]
            sim.wr(sp + 12, 2, 0x5858)
            sim.r.update(d3=0x24681357, a2=0x600000A2, a3=0x600000A3)
            r = sim.run(FMT_START, until=FMT_END)
            out.append((sim.rd(sp + 12, 1), sim.rd(sp + 13, 1), r["d2"], r["d3"], r["a2"], r["a3"], r["sp"]))
        s, p = out
        five = five or s                                 # stock's run for #6 = 5: " 5", d2 = 0
        if n in ns:                                      # a preset: the 5-case with its own two digits
            assert p[:2] == (0x30 + n // 10, 0x30 + n % 10) and p[2:] == five[2:], ("fmt: preset", n, s, p)
        else:
            assert p == s, ("fmt: differs from stock", n, s, p)
        checked += 1
    return checked


# ---------------------------------------------------------------- data model of the patched image
class Image:
    """Reads the patched data the way the firmware does (resources and layouts with the hooks)."""

    def __init__(self, img, info):
        self.img, self.info = img, info

    def ptr(self, a):
        return struct.unpack_from("<I", self.img, a - BASE)[0]

    def resource(self, rid):
        """(w, h, pixel rows) or None. Stock ROM ids 576..1447, plus the new ids (as res_hook)."""
        k = rid - md.EXT_RES
        if 0 <= k < len(self.info["res_ids"]):
            hdr = self.ptr(self.info["res_table"] + 4 * k)
        elif 576 <= rid < 1448:
            hdr = self.ptr(labelfont.RES_TABLE + 4 * (rid - 576))
        else:
            return None
        w, h, dp, z = struct.unpack_from("<HHII", self.img, hdr - BASE)
        assert z == 0, ("resource header +8 not 0", hex(rid))
        stride = (w + 3) // 4
        return w, h, [[(self.img[dp - BASE + y * stride + x // 4] >> (2 * (x % 4))) & 3 for x in range(w)]
                      for y in range(h)]

    def layout(self, lid):
        k = lid - md.EXT_LAY
        if 0 <= k < self.info["lay_n"]:
            p = self.ptr(self.info["lay_table"] + 4 * k)
        else:
            assert lid < md.LAYOUT_COUNT, ("layout id out of range", hex(lid))
            p = self.ptr(md.LAYOUT_TABLE + 4 * lid)
        out = []
        for i in range(64):
            r = self.img[p - BASE + md.REC * i:p - BASE + md.REC * (i + 1)]
            if u16(r, 0) == 0:
                assert r == bytes(md.REC), ("non-zero terminator", hex(lid))
                return out
            out.append(r)
        raise AssertionError(("no terminator", hex(lid)))


def rects(im, lid):
    out = []
    for r in im.layout(lid):
        assert u16(r, 0) == 6, ("button style has a non-rectangle", hex(lid))
        x, y, w, h = (struct.unpack_from("<h", r, o)[0] for o in (4, 6, 8, 10))
        out.append((x, y, w, h, u16(r, 16)))
    return out


def test_data(stock, patched, presets, info, font):
    sim, pim = Image(stock, info), Image(patched, info)
    checked = 0
    n_opt = md.STOCK_N + len(presets)
    texts = [md.label_text(*p) for p in presets]
    # 5. option list
    desc = rd(patched, md.DESC_1_3, 20)
    assert rd(stock, md.DESC_1_3, 4) == desc[:4] and rd(stock, md.DESC_1_3 + 14, 6) == desc[14:], "descriptor fields"
    vals_a, codes_a, size = struct.unpack_from("<IIH", desc, 4)
    assert size == 64 * n_opt, "descriptor size"
    values = rd(patched, vals_a, size)
    codes = struct.unpack_from(f"<{n_opt}I", patched, codes_a - BASE)
    assert values[:256] == rd(stock, md.STOCK_VALUES, 256), "stock entries changed"
    assert codes[:4] == (0, 1, 2, 3) and len(set(codes)) == n_opt and 128 not in codes, ("codes", codes)
    assert set(codes[4:]).isdisjoint(range(12)), "preset code collides with a stock code"
    for k, (n, lo, hi) in enumerate(presets):
        assert values[256 + 64 * k:256 + 64 * (k + 1)] == struct.pack("<3I", n, 0x55, 1) + bytes(52), ("entry", k)
    entries = [values[64 * k:64 * (k + 1)] for k in range(n_opt)]
    assert len(set(entries)) == n_opt, "two option entries are equal (memcmp could not tell them apart)"
    for a in (0x40224328, 0x4022433C):                  # 1/2-EV and 1-EV lists: untouched
        assert rd(patched, a, 20) == rd(stock, a, 20), hex(a)
    checked += n_opt
    # 6. grid
    stock_texts = {0x516: "3F 0.3EV", 0x518: "3F 0.7EV", 0x519: "3F 1.0EV"}
    btn = [rects(pim, md.EXT_LAY + i) for i in range(3)]
    for i, style in enumerate(md.BUTTON_STYLES):       # same as the stock styles, 68 px narrower
        s = rects(sim, style)
        assert len(s) == len(btn[i]) and all(
            (b[1], b[3], b[4]) == (a[1], a[3], a[4]) and (b[2] == a[2] - 68 if a[2] > 2 else b[2] == a[2])
            and (b[0] == a[0] - 68 if a[0] > 2 else b[0] == a[0]) for a, b in zip(s, btn[i])), ("button style", i)
    for slot in md.GRID_SLOTS:
        recs = pim.layout(slot)
        assert u16(recs[0], 0) == 0x15 and u16(recs[0], 2) == 876, "grid must start with the panel"
        buttons = [r for r in recs[1:] if r[20] == 0xB0]
        labels = [r for r in recs[1:] if r[20] == 0xB3]
        assert len(buttons) == len(labels) == n_opt and len(recs) == 1 + 2 * n_opt, "grid record count"
        boxes = []
        for k in range(n_opt):
            b = [r for r in buttons if u16(r, 24) == k]
            lab = [r for r in labels if u16(r, 24) == k]
            assert len(b) == len(lab) == 1, ("row index", k)
            b, lab = b[0], lab[0]
            assert b[22] == lab[22] == 3, "rows must follow the menu cursor (source 3)"
            assert [u16(b, 26 + 2 * i) for i in range(3)] == [md.EXT_LAY, md.EXT_LAY + 1, md.EXT_LAY + 2]
            bx, by = struct.unpack_from("<hh", b, 4)
            boxes.append((bx, by, bx + md.BTN_W, by + 32))            # normal style: 100 x 32
            assert by - 2 >= PANEL[1] and by + 34 <= PANEL[1] + PANEL[3], ("selected button outside the panel", k)
            lx, ly = struct.unpack_from("<hh", lab, 4)
            assert (lx, ly) == (bx + md.BTN_W // 2, by + 16), ("label not centred on its button", k)
            rid = u16(lab, 2)
            text = texts[k - md.STOCK_N] if k >= md.STOCK_N else stock_texts.get(rid)
            if rid == 0x20F:
                assert k == 0, "OFF must be option 0"
            else:
                w, h, px = pim.resource(rid)
                want = labelfont.pad(labelfont.render(font, text), w, left=3 if k < md.STOCK_N else None)
                assert (w, h) == (96, 16) and px == want, ("label bitmap", k, text)
            checked += 1
        x0, y0, pw, ph = PANEL
        for i, (ax, ay, bx2, by2) in enumerate(boxes):
            assert x0 <= ax and bx2 <= x0 + pw and y0 <= ay and by2 <= y0 + ph, ("button outside the panel", i)
            for j, (cx, cy, dx, dy) in enumerate(boxes[:i]):
                assert ax >= dx or bx2 <= cx or ay >= dy or by2 <= cy, ("buttons overlap", i, j)
    # 7. value display
    dp, dn = struct.unpack_from("<IH", rd(patched, md.DISP_ENTRY + 4, 6))
    tab = [struct.unpack_from("<3I", patched, dp - BASE + 12 * i) for i in range(dn)]
    assert rd(patched, dp, 21 * 12) == rd(stock, 0x40206298, 21 * 12), "stock display entries changed"
    for k, code in enumerate(codes[md.STOCK_N:]):
        kinds = {kind: lay for kind, c, lay in tab if c == code}
        assert set(kinds) == {1, 7, 6} and kinds[7] == 0xFE2 and kinds[6] == 0xDD2, ("display kinds", code, kinds)
        recs = pim.layout(kinds[1])
        assert len(recs) == 1 and u16(recs[0], 0) == 3 and struct.unpack_from("<hh", recs[0], 4) == (0xC4, 0x10)
        w, h, px = pim.resource(u16(recs[0], 2))
        assert px == labelfont.pad(labelfont.render(font, texts[k]), w), ("display label", texts[k])
        checked += 1
    assert len(tab) == 21 + 3 * len(presets) and len({(kd, c) for kd, c, _ in tab}) == len(tab), "display table"
    # 8. id collisions
    ids = set()
    for lid in range(md.LAYOUT_COUNT):
        for r in sim.layout(lid):
            ids.add(u16(r, 2))
            if r[20] == 0xB0:
                ids.update(u16(r, 26 + 2 * i) for i in range(3))
    for lo, n in ((md.EXT_RES, len(info["res_ids"])), (md.EXT_LAY, info["lay_n"])):
        assert not ids & set(range(lo, lo + n)), ("stock layouts use a new id", hex(lo))
    return checked


def preview(patched, info, path, sel=None):
    """PNG of the grid as the patched data describes it (rectangles + label bitmaps; colours approximate)."""
    im = Image(patched, info)
    font = labelfont.glyphs(patched)
    W, H, S = 320, 240, 2
    px = [[(16, 16, 16)] * W for _ in range(H)]
    col = {0xF: (240, 240, 240), 1: (40, 100, 200), 2: (20, 50, 110), 5: (70, 70, 70), 7: (40, 40, 40)}

    def rect(x, y, w, h, c):
        for yy in range(max(0, y), min(H, y + h)):
            for xx in range(max(0, x), min(W, x + w)):
                px[yy][xx] = col.get(c, (255, 0, 255))
    x0, y0, pw, ph = PANEL
    rect(x0, y0, pw, ph, 7)
    recs = im.layout(md.GRID_SLOTS[0])
    sel = sel if sel is not None else md.STOCK_N + 2
    for r in recs[1:]:
        k, (x, y) = u16(r, 24), struct.unpack_from("<hh", r, 4)
        if r[20] == 0xB0:
            for rx, ry, rw, rh, c in rects(im, u16(r, 26 + 2 * (0 if k == sel else 1))):
                rect(x + rx, y + ry, rw, rh, c)
        else:
            res = im.resource(u16(r, 2))
            if res is None:                              # OFF is language-dependent (not in the image)
                bm = labelfont.render(font, "0FF")
                res = (len(bm[0]), len(bm), bm)
            w, h, bm = res
            for yy in range(h):
                for xx in range(w):
                    v = bm[yy][xx]
                    if v:
                        px[y - h // 2 + yy][x - w // 2 + xx] = (230, 230, 230) if v == 1 else \
                            ((255, 255, 255) if k == sel else (110, 170, 255))
    raw = b"".join(b"\0" + bytes(c for p in row for c in p * S) for row in px for _ in range(S))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W * S, H * S, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def verify(stock, patched, presets, info, quiet=False):
    font = labelfont.glyphs(stock)
    counts = {"data": test_data(stock, patched, presets, info, font), "fmt": test_fmt(stock, patched, presets, info),
              "validator": test_val(stock, patched, presets, info), "layout ids": test_lay(stock, patched, info),
              "resource ids": test_res(stock, patched, info)}
    if not quiet:
        print("OK: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return sum(counts.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", help="decoded stock image")
    ap.add_argument("patched", help="decoded patched image")
    ap.add_argument("--presets", default=None, help="as build.py --presets (default: build.py's)")
    ap.add_argument("--png", help="also write a preview of the grid")
    args = ap.parse_args()
    import build
    presets = build.parse_presets(args.presets or build.DEFAULT_PRESETS)
    stock, patched = open(args.stock, "rb").read(), open(args.patched, "rb").read()
    _, info = md.build(stock, presets, build.MENU_DATA)
    info["ext_lo"] = build.link_skip(presets)[1]["ext_lo"]
    verify(stock, patched, presets, info)
    if args.png:
        preview(patched, info, args.png)


if __name__ == "__main__":
    main()
