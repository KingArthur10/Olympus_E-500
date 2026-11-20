#!/usr/bin/env python3
"""Data for the bracket preset menu (E-500 fw 1.3): option list, labels, layouts.

Used by build.py. Everything new lives in one blob in image-tail free space; the stock data
is only repointed (descriptor, display table entry, two layout-table slots). Each new layout
record is a copy of a stock record with only its position, id or row index changed.
Findings: notes/2026-11-18-menu-labels-and-layouts.md.

The 1/3-EV AE BKT submenu becomes a 3-column grid, filled column by column (the menu moves
through the options in list order with up/down):
    OFF        preset 1   preset 5
    3F 0.3EV   preset 2   preset 6
    3F 0.7EV   preset 3   (preset 7)
    3F 1.0EV   preset 4   (preset 8)
"""
import struct

import labelfont

BASE = 0x40030020
REC = 52                                # layout record size
# Stock data the menu uses [confirmed, see the note]
DESC_1_3 = 0x40224314                   # option descriptor, #6 with #131 = 0x55 (1/3 EV)
STOCK_VALUES, STOCK_CODES, STOCK_N = 0x402225F8, 0x402240DC, 4   # OFF, 3F 0.3, 3F 0.7, 3F 1.0
DISP_ENTRY = 0x40207508                 # value-display table entry for #6 {u32 id, ptr, u16 count, fn}
LAYOUT_TABLE, LAYOUT_COUNT = 0x401FF6C0, 4598
GRID_SLOTS = (1183, 1594)               # 1/3-EV AE BKT submenus (two menu contexts), repointed
TPL_INCLUDE = 0x401A5184                # layout 871 record 0: include panel background (layout 876)
TPL_BUTTON = 0x401A51B8                 # layout 871 record 1: 0xB0 button, row 0
TPL_LABEL = 0x401B3330                  # layout 1183 record 1: 0xB3 label row, row 0 ("OFF")
STOCK_ROW_LABELS = (0x401B3330, 0x401B3364, 0x401B3398, 0x401B33CC)   # 1183 rows 0..3
BUTTON_STYLES = (839, 840, 841)         # 168-px list buttons: selected, normal, disabled
TPL_VALUE = 768                         # layout: one image record ("3F 0.3EV") at 0xC4,0x10
VALUE_KINDS = ((7, 0xFE2), (6, 0xDD2))  # other value-display kinds: "BKT" icon for any ON code
LABEL_W = 96                            # stock list labels are 96 x 16
# New ids (stock has none there: resources >= 1467 are "no resource", layouts end at 4597)
EXT_RES, EXT_LAY = 0x7E00, 0x7F00
FIRST_CODE = 12                         # stock codes for #6 are 0..11; 128 is "not found"
# Grid geometry: 3 columns of 100-px buttons, rows at the stock list heights
COL_X, BTN_W, ROW_Y, ROW_PITCH, ROWS = (2, 106, 210), 100, 0x2A, 34, 4


def label_text(n, lo, hi):
    """'13F ±2' for -2..+2 EV, '22F -3+4' for -3..+4 EV. lo, hi: thirds below / above metered."""
    ev = lambda x: str(x // 3) if x % 3 == 0 else f"{x / 3:.1f}"  # noqa: E731
    rng = f"±{ev(hi)}" if lo == hi else f"-{ev(lo)}+{ev(hi)}"
    return f"{n}F {rng}"


class Blob:
    def __init__(self, base):
        self.base, self.data = base, bytearray()

    def put(self, b, align=4):
        while len(self.data) % align:
            self.data.append(0)
        a = self.base + len(self.data)
        self.data += b
        return a


def u16(b, off):
    return struct.unpack_from("<H", b, off)[0]


def set16(rec, off, v):
    struct.pack_into("<H", rec, off, v & 0xFFFF)


def layout_records(plain, idx):
    """The records of stock layout idx (up to its type-0 terminator, which must be all zero)."""
    p = struct.unpack_from("<I", plain, LAYOUT_TABLE - BASE + 4 * idx)[0]
    out = []
    for k in range(64):
        r = plain[p - BASE + REC * k:p - BASE + REC * (k + 1)]
        if u16(r, 0) == 0:
            if r != bytes(REC):
                raise ValueError(f"layout {idx}: terminator not zero")
            return out
        out.append(bytearray(r))
    raise ValueError(f"layout {idx}: no terminator")


def narrow_button(recs, w_old=168, w_new=100):
    """Rectangle records of a list button, made w_new wide (outer w_old, inner w_old-4, right edge)."""
    out = []
    d = w_old - w_new
    for r in recs:
        if u16(r, 0) != 6:
            raise ValueError("button style record is not a rectangle")
        r = bytearray(r)
        x, w = u16(r, 4), u16(r, 8)
        if w in (w_old, w_old - 4):
            set16(r, 8, w - d)
        elif x == w_old - 4 and w == 2:
            set16(r, 4, x - d)
        else:
            raise ValueError(f"unexpected button rectangle x={x} w={w}")
        out.append(r)
    return out


def build(plain, presets, base):
    """presets: [(n, lo_thirds, hi_thirds)]. Returns (blob bytes, info dict)."""
    at = lambda a, k: plain[a - BASE:a - BASE + k]  # noqa: E731
    if not 1 <= len(presets) <= 3 * ROWS - STOCK_N:
        raise ValueError(f"{len(presets)} presets: the grid holds 1..{3 * ROWS - STOCK_N}")
    desc = at(DESC_1_3, 20)
    if (u16(desc, 0), u16(desc, 2)) != (6, 0x55) or struct.unpack_from("<II", desc, 4) != (STOCK_VALUES, STOCK_CODES) \
            or (u16(desc, 12), u16(desc, 14), desc[17]) != (STOCK_N * 64, 64, 6):
        raise ValueError("1/3-EV #6 descriptor not as expected")
    if struct.unpack_from("<4I", at(STOCK_CODES, 16)) != (0, 1, 2, 3):
        raise ValueError("stock codes not 0..3")
    disp = at(DISP_ENTRY, 16)
    if struct.unpack_from("<IIH", disp) != (6, 0x40206298, 21):
        raise ValueError("value-display entry for #6 not as expected")
    blob = Blob(base)
    font = labelfont.glyphs(plain)
    labelfont.selftest(plain, font)
    codes = list(range(FIRST_CODE, FIRST_CODE + len(presets)))

    # option list: the 4 stock entries (as stock: "3F 1.0EV" is restored), then the presets
    values = bytearray(at(STOCK_VALUES, STOCK_N * 64))
    for n, lo, hi in presets:
        values += struct.pack("<3I", n, 0x55, 1) + bytes(52)
    a_values = blob.put(bytes(values))
    a_codes = blob.put(struct.pack(f"<{STOCK_N + len(presets)}I", 0, 1, 2, 3, *codes))

    # label bitmaps and resource headers {w, h, data, 0}
    texts = [label_text(n, lo, hi) for n, lo, hi in presets]
    headers = []
    for t in texts:
        try:
            rows = labelfont.pad(labelfont.render(font, t), LABEL_W)
        except ValueError as e:
            raise ValueError(f"label \"{t}\": {e}") from None
        a_bits = blob.put(labelfont.encode(rows))
        headers.append(blob.put(struct.pack("<HHII", LABEL_W, labelfont.H, a_bits, 0)))
    a_res_table = blob.put(struct.pack(f"<{len(headers)}I", *headers))
    res_ids = [EXT_RES + k for k in range(len(presets))]

    # layouts: 3 button styles, one value display per preset
    lay_ptrs = []
    for style in BUTTON_STYLES:
        lay_ptrs.append(blob.put(b"".join(narrow_button(layout_records(plain, style), 168, BTN_W)) + bytes(REC)))
    value_tpl = layout_records(plain, TPL_VALUE)
    if len(value_tpl) != 1 or u16(value_tpl[0], 0) != 3 or u16(value_tpl[0], 2) != 0x516:
        raise ValueError("value-display template layout not as expected")
    for rid in res_ids:
        r = bytearray(value_tpl[0])
        set16(r, 2, rid)
        lay_ptrs.append(blob.put(bytes(r) + bytes(REC)))
    a_lay_table = blob.put(struct.pack(f"<{len(lay_ptrs)}I", *lay_ptrs))
    lay_btn = (EXT_LAY, EXT_LAY + 1, EXT_LAY + 2)
    lay_value = [EXT_LAY + 3 + k for k in range(len(presets))]

    # the grid: panel background, buttons, labels (stock draw order)
    inc, btn_t, lab_t = at(TPL_INCLUDE, REC), at(TPL_BUTTON, REC), at(TPL_LABEL, REC)
    if (u16(inc, 0), u16(inc, 2)) != (0x15, 876) or (u16(btn_t, 0), btn_t[20], u16(btn_t, 26)) != (8, 0xB0, 839) \
            or (u16(lab_t, 0), lab_t[20], u16(lab_t, 2)) != (8, 0xB3, 0x20F):
        raise ValueError("grid templates not as expected")
    stock_rids = [u16(at(a, REC), 2) for a in STOCK_ROW_LABELS]
    if stock_rids != [0x20F, 0x516, 0x518, 0x519]:
        raise ValueError(f"stock row labels {stock_rids}")
    rids = stock_rids + res_ids
    recs = [bytes(inc)]
    cells = []
    for k in range(len(rids)):
        col, row = divmod(k, ROWS)
        x, y = COL_X[col], ROW_Y + ROW_PITCH * row
        cells.append((x, y))
        b = bytearray(btn_t)
        set16(b, 4, x)
        set16(b, 6, y)
        set16(b, 24, k)
        for i, lid in enumerate(lay_btn):
            set16(b, 26 + 2 * i, lid)
        recs.append(bytes(b))
    for k, (rid, (x, y)) in enumerate(zip(rids, cells)):
        r = bytearray(lab_t)
        set16(r, 2, rid)
        set16(r, 4, x + BTN_W // 2)
        set16(r, 6, y + 16)
        set16(r, 24, k)
        recs.append(bytes(r))
    a_grid = blob.put(b"".join(recs) + bytes(REC))

    # value-display table for #6: stock entries, then {kind, code, layout} for each preset
    stock_disp = at(0x40206298, 21 * 12)
    disp_tab = bytearray(stock_disp)
    for code, lid in zip(codes, lay_value):
        disp_tab += struct.pack("<3I", 1, code, lid)
        for kind, lay in VALUE_KINDS:
            disp_tab += struct.pack("<3I", kind, code, lay)
    a_disp = blob.put(bytes(disp_tab))

    info = {
        "values": a_values, "codes": a_codes, "count": STOCK_N + len(presets), "texts": texts,
        "res_table": a_res_table, "res_ids": res_ids, "lay_table": a_lay_table, "lay_n": len(lay_ptrs),
        "lay_btn": lay_btn, "lay_value": lay_value, "grid": a_grid, "disp": a_disp,
        "disp_count": len(disp_tab) // 12, "preset_codes": codes, "cells": cells,
    }
    return bytes(blob.data), info
