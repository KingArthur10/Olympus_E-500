#!/usr/bin/env python3
"""Exhaustive test of the M-mode shutter-dial fix (m_tv_ref) in ext_bkt (E-500 fw 1.3).

Each of the 8 patched windows in the #5 dial handlers (stock: `mov 3000,d0` then a getter
call) is run from a STOCK and a PATCHED decoded image in tools/mn103_sim.py (the patched helper
also runs skip.S's ext_lo). The two getters (setting_get, shadow_get) are stubbed: they
return table values and clobber d1/a0/a1. Checks, for every combination of settings tested:
  * stock image: d0 == getter(3000)                               validates the interpreter
  * patched:     d0 == getter(5) if M mode, AE BKT on and #6 is a preset n, else
                 getter(3000), bit for bit
  * d2, d3, a2, a3 and sp are the same on exit as on entry (callers rely on them)

  python3 verify_m_tv_ref.py <decoded_stock.bin> <decoded_patched.bin> [--presets -2:2,...]
"""
import argparse
import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
import mn103_sim  # noqa: E402

BASE = 0x40030020
SETTING_GET, SHADOW_GET = 0x400394A7, 0x4007458F
# (window start, window end, getter) for each `mov 3000,d0` + getter call
WINDOWS = [(0x40071FF5, 0x40071FFF, SETTING_GET), (0x40072021, 0x4007202B, SETTING_GET),
           (0x4007204D, 0x40072057, SETTING_GET), (0x40072092, 0x4007209C, SETTING_GET),
           (0x4006E57E, 0x4006E586, SHADOW_GET), (0x4006E5A5, 0x4006E5AD, SHADOW_GET),
           (0x4006E5E7, 0x4006E5EF, SHADOW_GET), (0x4006E627, 0x4006E62F, SHADOW_GET)]
M32 = 0xFFFFFFFF
HELPERS = [(0x406F6B00, 0x406F6B80), (0x406F6B80, 0x406F6C00)]   # m_tv_ref (live, shadow)
SKIP_END = 0x406F7000                   # skip.S code runs from ext_lo (after the preset table) to here
FRAMES = {SETTING_GET: (["d2", "d3"], 12), SHADOW_GET: (["d2"], 4)}
ENTRY = {"d0": 0x11111111, "d1": 0x22222222, "d2": 0x33333333, "d3": 0x44444444,
         "a0": 0x55555555, "a1": 0x66666666, "a2": 0x77777777, "a3": 0x88888888}


def sims(stock, patched, ext_lo):
    ranges = [(a, b) for a, b, _ in WINDOWS]
    return mn103_sim.Sim(stock, BASE, ranges), mn103_sim.Sim(patched, BASE, ranges + HELPERS + [(ext_lo, SKIP_END)])


def run(sim, start, end, getter, vals):
    """Execute a window with the getter stubbed (it must be called with its stock frame)."""
    def stub(s, regs, imm):
        if (regs, imm) != FRAMES[getter]:
            raise mn103_sim.Unknown(f"getter 0x{getter:08x} called with frame {regs},{imm}")
        s.r.update(d0=vals[s.r["d0"] & 0xFFFF] & M32, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)
    sim.reset()
    sim.stubs = {getter: stub}
    sim.r.update(ENTRY)
    return sim.run(start, until=end, max_steps=2000)


def verify(stock, patched, presets, ext_lo, quiet=False):
    """Raise AssertionError on any mismatch; return the number of cases checked."""
    ns = {n for n, _, _ in presets}
    space = itertools.product(
        (0, 4, 5, 6, 7, 0x10006),          # #40 exposure mode (6 = M); last has junk above 16 bits
        (0, 1, 2, 0x10001),                # #88 AE BKT
        sorted({0, 3, 5, 255} | {m + d for m in ns for d in (-1, 0, 1, 256)}),   # #6 frames (u8 in the store)
        (0x0000, 0x0100, 0xFD00, 0xFFFFFD00, 0x8000, 0x0C00),  # #5 (both representations of -768)
        (0x0C00, 0xFFFFFA00, 0x02FD),      # #3000
        WINDOWS)
    st, pa = sims(stock, patched, ext_lo)
    checked = 0
    for s40, s88, s6, s5, s3000, (start, end, getter) in space:
        vals = {40: s40, 88: s88, 6: s6, 5: s5, 3000: s3000}
        o = run(st, start, end, getter, vals)
        w = run(pa, start, end, getter, vals)
        key = (hex(start), s40, s88, s6, hex(s5), hex(s3000))
        assert o["d0"] == s3000 & M32, ("stock image != getter(3000)", key, hex(o["d0"]))
        ext = (s40 & 0xFFFF) == 6 and (s88 & 0xFFFF) == 1 and (s6 & 0xFF) in ns
        assert w["d0"] == ((s5 if ext else s3000) & M32), ("patched d0 wrong", key, hex(w["d0"]))
        for reg in ("d2", "d3", "a2", "a3", "sp"):
            assert w[reg] == o[reg], (f"{reg} not preserved", key)
        checked += 1
    if not quiet:
        print(f"OK: {checked} cases over {len(WINDOWS)} call sites; stock -> #3000, "
              f"patched -> #5 only for M + AE BKT + #6 in {sorted(ns)}")
    return checked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", help="decoded stock image")
    ap.add_argument("patched", help="decoded patched image")
    ap.add_argument("--presets", default=None, help="as build.py --presets (default: build.py's)")
    args = ap.parse_args()
    sys.path.insert(0, HERE)
    import build
    presets = build.parse_presets(args.presets or build.DEFAULT_PRESETS)
    verify(open(args.stock, "rb").read(), open(args.patched, "rb").read(), presets,
           build.link_skip(presets)[1]["ext_lo"])


if __name__ == "__main__":
    main()
