#!/usr/bin/env python3
"""Generate the ext_bkt patch (E-500 fw 1.3): ascending bracket presets in the AE BKT menu.

  python3 build.py E0359999.BIN [--presets -2:2,-3:3,-3:4,-4:4,-5:5,-6:6] [--no-cont-resume] [--out patch.json]

Produces a pinned patch definition for tools/oly_patch.py. Each preset BOTTOM:TOP (EV, 1/3 EV
steps) is a new choice in the 1/3-EV AE BKT submenu, which becomes a 3-column grid: the stock
choices (OFF, 3F 0.3/0.7/1.0EV, unchanged) in column 1, the presets after them, labelled in
the camera's own font ("13F ±2", "22F -3+4"). A preset shoots N frames ascending from BOTTOM
to TOP while the shutter is held. Frames the camera can't expose (shutter limits in A/P/M,
aperture limits in S) are planned out before each burst and skipped (skip.S). By default it
also includes ../cont_resume (keep shooting past a full buffer while the shutter stays held
in continuous drive).
Requires mn10300-linux-gnu-{as,ld,objcopy,nm}.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "cont_resume"))
import cont_resume  # noqa: E402
import menu_data  # noqa: E402
import oly_fw  # noqa: E402
import verify_menu  # noqa: E402
import verify_skip  # noqa: E402
import verify_m_tv_ref  # noqa: E402

FIRMWARE = "E0359999.BIN"              # official E-500 firmware 1.3 (input file name)
FW_SHA256 = "e9f5431cb47bf1c73395337256fba6eedf576c03b06c4ef7dea0d387ca7c69ae"
BASE = 0x40030020
DEFAULT_PRESETS = "-2:2,-3:3,-3:4,-4:4,-5:5,-6:6"   # owner, 2026-11-18: 13F 19F 22F 25F 31F 37F

BKT_OFFSET = 0x40124B1C          # 40-byte bkt_offset: replaced by a jump to skip.S bkt_offset2
# M-mode shutter dial fix: #3000 reads in the #5 dial handlers -> m_tv_ref.S helpers (image-tail free space)
SETTING_GET, SHADOW_GET = 0x400394A7, 0x4007458F
TV_SITES_LIVE = [0x40071FF8, 0x40072024, 0x40072050, 0x40072095]   # `call setting_get,[d2,d3],12` (7 B)
TV_SITES_SHADOW = [0x4006E57E, 0x4006E5A5, 0x4006E5E7, 0x4006E627]  # `mov 3000,d0` + `call shadow_get,[d2],4` (8 B)
TV_HELPER_LIVE, TV_HELPER_SHADOW, TV_HELPER_MAX = 0x406F6B00, 0x406F6B80, 0x80
# Skip unreachable frames (skip.S, notes/2026-11-18-skip-unreachable-design.md)
SKIP_BLOB, SKIP_MAX = 0x406F6C00, 0x400
COUNTER_SITE = 0x40133288        # cam_bkt_counter_advance: "#7 + 1, wrap at #6" (8 B)
COUNTER_ORIG = "14408115a9c00300"
NEFF_SITE = 0x400A1044           # app_seq_limit: `mov 6,d0` + `call setting_get,[d2,d3],12` (9 B)
NEFF_ORIG = "8006dd6184f9ffc00c"
PLAN_SITE = 0x40133359           # cam_capture_prep: `call ae_store_outputs` (d16) + `ret [d2,d3,a2,a3],136` (8 B)
PLAN_ORIG = "cda104f04cdff088"
STORE_GET, EXPO_BUILD, AE_CALC, AE_STORE = 0x4011B100, 0x40133595, 0x400BA9FD, 0x401337FA
# Preset menu (menu.S + menu_data.py, notes/2026-11-18-menu-labels-and-layouts.md)
MENU_CODE, MENU_CODE_MAX = 0x406F7000, 0x100
MENU_DATA, MENU_DATA_MAX = 0x406F7100, 0x1F00
RES_SITE, RES_ORIG = 0x400FBA8D, "fac9bb05c64e"      # resource lookup: `cmp 1467,d1` + `bcc null` (6 B)
RES_STOCK, RES_RET = 0x400FBA93, 0x400FBADF
LAY_SITE, LAY_ORIG = 0x40076A4A, "fca2bcbe1640"      # layout lookup: `mov (0x4016BEBC),a2` (6 B)
LAY_BACK = 0x40076A50
VAL_SITE, VAL_ORIG = 0x4006071C, "8006dd898dfdffc00c"  # ae_bkt_validate: `mov 6,d0` + get (9 B)
FMT_SITE, FMT_ORIG = 0x4006231F, "8006dd8671fdffc00c"  # ui_fmt_bkt_count: `mov 6,d0` + get (9 B)
FMT5_SITE, FMT5_ORIG = 0x4006233F, "8020f8920c8035ca09"  # its 5-case: " 5" (9 B)


def parse_presets(s):
    """'-2:2,-3:4' -> [(n, lo_thirds, hi_thirds)] in 1/3 EV steps."""
    out = []
    for part in s.split(","):
        b, t = (Fraction(x) for x in part.split(":"))
        if (b * 3).denominator != 1 or (t * 3).denominator != 1 or not b <= 0 <= t:
            sys.exit(f"error: preset {part}: need BOTTOM <= 0 <= TOP, multiples of 1/3 EV")
        lo, hi = int(-b * 3), int(t * 3)
        n = lo + hi + 1
        if n in (0, 1, 3, 5) or n > 99:
            sys.exit(f"error: preset {part}: {n} frames (must be 2..99 and not 3 or 5, which stock uses)")
        if max(lo, hi) > 18:
            sys.exit(f"error: preset {part}: offsets beyond 6 EV")
        out.append((n, lo, hi))
    if len({n for n, _, _ in out}) != len(out):
        sys.exit("error: two presets have the same frame count (the menu tells them apart by it)")
    return out


def link(src, addr, as_syms, ld_syms, symbols=False, include=None):
    """Assemble src at addr; return the code (and {label: address} if symbols).
    include: {filename: text} written next to the source for `.include`."""
    with tempfile.TemporaryDirectory() as t:
        for name, text in (include or {}).items():
            with open(os.path.join(t, name), "w") as f:
                f.write(text)
        o, elf, bin_ = (os.path.join(t, x) for x in ("x.o", "x.elf", "x.bin"))
        subprocess.run(["mn10300-linux-gnu-as", "-I", t] + [f"--defsym={k}={v}" for k, v in as_syms.items()]
                       + ["-o", o, os.path.join(HERE, src)], check=True)
        subprocess.run(["mn10300-linux-gnu-ld", f"-Ttext=0x{addr:x}", "-e", "0", "-o", elf, o]
                       + [f"--defsym={k}=0x{v:x}" for k, v in ld_syms.items()], check=True)
        subprocess.run(["mn10300-linux-gnu-objcopy", "-O", "binary", "-j", ".text", elf, bin_], check=True)
        code = open(bin_, "rb").read()
        if not symbols:
            return code
        nm = subprocess.run(["mn10300-linux-gnu-nm", elf], check=True, capture_output=True, text=True).stdout
        syms = {f[2]: int(f[0], 16) for f in (l.split() for l in nm.splitlines()) if len(f) == 3 and f[1] == "t"}
        return code, syms


def presets_inc(presets):
    return "".join(f"        .byte   {n}, {lo}\n" for n, lo, _ in presets)


def link_skip(presets):
    return link("skip.S", SKIP_BLOB, {},
                {"setting_get_addr": SETTING_GET, "store_get_addr": STORE_GET, "expo_build_addr": EXPO_BUILD,
                 "ae_calc_addr": AE_CALC, "ae_store_addr": AE_STORE}, symbols=True,
                include={"presets.inc": presets_inc(presets)})


def apply(plain, edits):
    patched = bytearray(plain)
    for a, _, w, _ in edits:
        patched[a - BASE:a - BASE + len(w)] = w
    return bytes(patched)


def free(plain, addr, size):
    return plain[addr - BASE:addr - BASE + size] == b"\xff" * size


def skip_edits(plain, presets, quick=False):
    """Edits for skipping unreachable frames (and the ascending preset offsets); verified."""
    at = lambda a, k: plain[a - BASE:a - BASE + k]  # noqa: E731
    blob, sym = link_skip(presets)
    if len(blob) > SKIP_MAX or not free(plain, SKIP_BLOB, SKIP_MAX):
        sys.exit(f"error: skip.S is {len(blob)} B, or free space at 0x{SKIP_BLOB:08x} is not 0xFF")
    for site, orig in ((COUNTER_SITE, COUNTER_ORIG), (NEFF_SITE, NEFF_ORIG), (PLAN_SITE, PLAN_ORIG)):
        if at(site, len(orig) // 2).hex() != orig:
            sys.exit(f"error: unexpected bytes at 0x{site:08x}: {at(site, len(orig) // 2).hex()}")
    table = ", ".join(f"{n}F from -{lo}/3" for n, lo, _ in presets)
    edits = [
        (BKT_OFFSET, at(BKT_OFFSET, 40), link("site_jmp.S", BKT_OFFSET, {"PAD": 35}, {"target_addr": sym["bkt_offset2"]}),
         "bkt_offset -> jmp bkt_offset2: preset n -> (F+idx-LO)*step over the planned frames, else stock"),
        (SKIP_BLOB, at(SKIP_BLOB, len(blob)), blob,
         f"skip.S (free space): preset table ({table}), frame plan, bkt_offset2, counter_next, n_eff, plan_hook"),
        (COUNTER_SITE, at(COUNTER_SITE, 8), link("site_call.S", COUNTER_SITE, {"PAD": 1}, {"target_addr": sym["counter_next"]}),
         "cam_bkt_counter_advance: #7 wraps at the planned count C (stock n: at #6)"),
        (NEFF_SITE, at(NEFF_SITE, 9), link("site_call.S", NEFF_SITE, {"PAD": 2}, {"target_addr": sym["n_eff"]}),
         "app_seq_limit: frame count = planned C (latched at full press; limit at least 1) (stock n: #6)"),
        (PLAN_SITE, at(PLAN_SITE, 8), link("site_jmp.S", PLAN_SITE, {"PAD": 3}, {"target_addr": sym["plan_tramp"]}),
         "cam_capture_prep: store AE outputs via plan_tramp/plan_hook (plans the reachable frames first)"),
    ]
    patched = apply(plain, edits)
    cases = verify_skip.verify(plain, patched, presets, sym, quiet=True, quick=quick)
    edits[1] = edits[1][:3] + (edits[1][3] + f" (verified: {cases} cases)",)
    return edits, sym


def m_tv_edits(plain, presets, ext_lo_addr):
    """Edits for the M-mode shutter-dial fix; verified against the stock image."""
    at = lambda a, k: plain[a - BASE:a - BASE + k]  # noqa: E731
    edits = []
    for helper, shadow, getter in ((TV_HELPER_LIVE, 0, SETTING_GET), (TV_HELPER_SHADOW, 1, SHADOW_GET)):
        code = link("m_tv_ref.S", helper, {"SHADOW": shadow}, {"getter_addr": getter, "ext_lo_addr": ext_lo_addr})
        if len(code) > TV_HELPER_MAX or not free(plain, helper, TV_HELPER_MAX):
            sys.exit(f"error: m_tv_ref helper @0x{helper:08x}: {len(code)} B, or free space not 0xFF")
        edits.append((helper, at(helper, len(code)), code,
                      f"m_tv_ref ({'shadow' if shadow else 'live'} getter, free space): #5 dial reference = "
                      f"#5 in M mode with a preset bracket, else #3000"))
    for site in TV_SITES_LIVE:
        orig = at(site, 7)
        if orig[0] != 0xDD or orig[5:7] != b"\xc0\x0c" or \
                (site + struct.unpack_from("<i", orig, 1)[0]) & 0xFFFFFFFF != SETTING_GET or \
                at(site - 3, 3) != b"\x2c\xb8\x0b":
            sys.exit(f"error: unexpected bytes at 0x{site:08x}")
        edits.append((site, orig, link("site_call.S", site, {"PAD": 0}, {"target_addr": TV_HELPER_LIVE}),
                      "#5 dial handler: get(3000) -> m_tv_ref (live)"))
    for site in TV_SITES_SHADOW:
        orig = at(site, 8)
        if orig[:4] != b"\x2c\xb8\x0b\xcd" or orig[6:8] != b"\x80\x04" or \
                (site + 3 + struct.unpack_from("<h", orig, 4)[0]) & 0xFFFFFFFF != SHADOW_GET:
            sys.exit(f"error: unexpected bytes at 0x{site:08x}")
        edits.append((site, orig, link("site_call.S", site, {"PAD": 1}, {"target_addr": TV_HELPER_SHADOW}),
                      "#5 dial handler (shadow): mov 3000 + shadow_get(3000) -> m_tv_ref (shadow)"))
    return edits


def menu_edits(plain, presets, ext_lo_addr):
    """Edits for the preset menu: data blob, hooks, repointed descriptor / table / layouts."""
    at = lambda a, k: plain[a - BASE:a - BASE + k]  # noqa: E731
    data, info = menu_data.build(plain, presets, MENU_DATA)
    code, sym = link("menu.S", MENU_CODE,
                     {"EXT_RES": menu_data.EXT_RES, "EXT_RES_N": len(info["res_ids"]),
                      "EXT_LAY": menu_data.EXT_LAY, "EXT_LAY_N": info["lay_n"]},
                     {"ext_res_table_addr": info["res_table"], "ext_lay_table_addr": info["lay_table"],
                      "setting_get_addr": SETTING_GET, "ext_lo_addr": ext_lo_addr,
                      "res_stock_addr": RES_STOCK, "res_ret_addr": RES_RET, "lay_back_addr": LAY_BACK},
                     symbols=True)
    if len(code) > MENU_CODE_MAX or not free(plain, MENU_CODE, MENU_CODE_MAX):
        sys.exit(f"error: menu.S is {len(code)} B, or free space at 0x{MENU_CODE:08x} is not 0xFF")
    if len(data) > MENU_DATA_MAX or not free(plain, MENU_DATA, MENU_DATA_MAX):
        sys.exit(f"error: menu data is {len(data)} B, or free space at 0x{MENU_DATA:08x} is not 0xFF")
    for site, orig in ((RES_SITE, RES_ORIG), (LAY_SITE, LAY_ORIG), (VAL_SITE, VAL_ORIG), (FMT_SITE, FMT_ORIG),
                       (FMT5_SITE, FMT5_ORIG)):
        if at(site, len(orig) // 2).hex() != orig:
            sys.exit(f"error: unexpected bytes at 0x{site:08x}: {at(site, len(orig) // 2).hex()}")
    labels = ", ".join(info["texts"])
    lay_slot = lambda i: menu_data.LAYOUT_TABLE + 4 * i  # noqa: E731
    edits = [
        (MENU_CODE, at(MENU_CODE, len(code)), code,
         "menu.S (free space): res_hook, lay_hook, val_n6, fmt_n6"),
        (MENU_DATA, at(MENU_DATA, len(data)), data,
         f"menu data (free space): 1/3-EV option list + codes, labels {labels}, button/value/grid layouts, "
         f"#6 value-display table"),
        (RES_SITE, at(RES_SITE, 6), link("site_jmp.S", RES_SITE, {"PAD": 1}, {"target_addr": sym["res_hook"]}),
         f"resource lookup: ids 0x{menu_data.EXT_RES:x}.. -> preset label bitmaps (res_hook), else stock"),
        (LAY_SITE, at(LAY_SITE, 6), link("site_jmp.S", LAY_SITE, {"PAD": 1}, {"target_addr": sym["lay_hook"]}),
         f"layout lookup: ids 0x{menu_data.EXT_LAY:x}.. -> new layouts (lay_hook), else stock"),
        (VAL_SITE, at(VAL_SITE, 9), link("site_call.S", VAL_SITE, {"PAD": 2}, {"target_addr": sym["val_n6"]}),
         "ae_bkt_validate: get(6) -> val_n6 (a preset reads as 5: the stock 5F 0.3EV row)"),
        (FMT_SITE, at(FMT_SITE, 9), link("site_call.S", FMT_SITE, {"PAD": 2}, {"target_addr": sym["fmt_n6"]}),
         "ui_fmt_bkt_count: get(6) -> fmt_n6 (a preset takes the 5-case, with its digits in d1/a1)"),
        (FMT5_SITE, at(FMT5_SITE, 9), link("fmt_site.S", FMT5_SITE, {}, {}),
         "ui_fmt_bkt_count 5-case: characters from fmt_n6 (' 5' for a real 5, else the preset's two digits)"),
        (menu_data.DESC_1_3 + 4, at(menu_data.DESC_1_3 + 4, 10),
         struct.pack("<IIH", info["values"], info["codes"], info["count"] * 64),
         f"1/3-EV #6 option descriptor: values, codes, size -> {info['count']}-entry list (stock 4 + presets)"),
        (menu_data.DISP_ENTRY + 4, at(menu_data.DISP_ENTRY + 4, 6), struct.pack("<IH", info["disp"], info["disp_count"]),
         f"#6 value-display entry: table -> {info['disp_count']} entries (stock 21 + 3 per preset)"),
    ]
    for slot in menu_data.GRID_SLOTS:
        edits.append((lay_slot(slot), at(lay_slot(slot), 4), struct.pack("<I", info["grid"]),
                      f"layout {slot} (1/3-EV AE BKT submenu) -> the preset grid"))
    info["ext_lo"] = ext_lo_addr
    return edits, info


def build_edits(plain, presets, cont=True, quick=False):
    edits, sym = skip_edits(plain, presets, quick=quick)
    edits += m_tv_edits(plain, presets, sym["ext_lo"])
    menu, info = menu_edits(plain, presets, sym["ext_lo"])
    edits += menu
    if cont:
        edits += cont_resume.build_edits(plain)
    patched = apply(plain, edits)        # the helpers call skip.S's ext_lo: verify on the whole set
    for addr, cases in ((TV_HELPER_LIVE, verify_m_tv_ref.verify(plain, patched, presets, sym["ext_lo"], quiet=True)),
                        (MENU_DATA, verify_menu.verify(plain, patched, presets, info, quiet=True))):
        i = next(k for k, e in enumerate(edits) if e[0] == addr)
        edits[i] = edits[i][:3] + (edits[i][3] + f" (verified: {cases} cases)",)
    return edits, info


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("firmware", help=f"stock E-500 firmware 1.3 ({FIRMWARE}, checked by SHA-256)")
    ap.add_argument("--presets", default=DEFAULT_PRESETS,
                    help=f"comma-separated BOTTOM:TOP in EV, 1/3 EV steps (default {DEFAULT_PRESETS})")
    ap.add_argument("--no-cont-resume", action="store_true",
                    help="leave out ../cont_resume (stock stop when the buffer fills)")
    ap.add_argument("--out", default=os.path.join(HERE, "patch.json"))
    args = ap.parse_args()
    presets = parse_presets(args.presets)

    raw = oly_fw.read_checked(args.firmware, FW_SHA256, f"E-500 firmware 1.3 ({FIRMWARE})")
    _, _, payload = oly_fw.parse(raw)
    plain = oly_fw.decode(payload)
    try:
        edits, info = build_edits(plain, presets, cont=not args.no_cont_resume)
    except ValueError as e:
        sys.exit(f"error: {e}")

    spec = {
        "name": "ext_bkt",
        "params": {"presets": [{"bottom_ev": str(Fraction(-lo, 3)), "top_ev": str(Fraction(hi, 3)), "frames": n,
                                "frames_below_metered": lo, "label": t}
                               for (n, lo, hi), t in zip(presets, info["texts"])],
                   "step_ev": "1/3", "cont_resume": not args.no_cont_resume},
        "description": "E-500 fw 1.3: ascending AE bracket presets (" + ", ".join(info["texts"]) + ") as new "
                       "choices in the 1/3-EV AE BKT menu (a 3-column grid). Stock bracket choices unchanged."
                       " Frames outside the shutter/aperture limits are skipped. M-mode shutter dial works with"
                       " the presets."
                       + ("" if args.no_cont_resume else " Continuous drive keeps shooting past a full buffer "
                                                         "while the shutter stays fully pressed."),
        "firmware": FIRMWARE,
        "firmware_sha256": FW_SHA256,
        "base": f"0x{BASE:08x}",
        "edits": [{"addr": f"0x{a:08x}", "orig": o.hex(), "new": w.hex(), "why": why}
                  for a, o, w, why in sorted(edits)],
    }
    with open(args.out, "w") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for (n, lo, hi), t in zip(presets, info["texts"]):
        print(f"  {t:10s} {n:2d} frames, {Fraction(-lo, 3)} .. +{Fraction(hi, 3)} EV")
    print(f"{len(edits)} edits; wrote {args.out}")


if __name__ == "__main__":
    main()
