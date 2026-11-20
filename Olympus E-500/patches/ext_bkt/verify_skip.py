#!/usr/bin/env python3
"""Tests of the skip-unreachable-frames edits (skip.S) in ext_bkt (E-500 fw 1.3).

The real bytes of a STOCK and a PATCHED decoded image run in tools/mn103_sim.py:
  1. bkt_offset   stock n: identical to the stock function; preset n: (F_use + idx - LO) * step
  2. counter      the "#7 + 1, wrap" window: stock n as stock; preset n wraps at C_use
  3. n_eff        the app_seq_limit window: stock n as stock; preset n returns C, latches at PICTURE,
                  and never makes the limit < 1 (a counter left past C by a preset change -> #7 + 1)
  4. plan_hook    after a simulated prep: the plan written to RAM equals the frames an independent
                  AE model can expose (no clamping), the AE is re-run once iff F changed, the stored
                  outputs belong to the planned first frame, and frozen states change nothing
  5. bursts       idle prep -> full press -> every frame: offsets are exactly the planned frames,
                  every shot frame is exposable, and the counter wraps to 0 after C frames
Tests 2-5 run once per preset (the "focus"); every other preset n is extended as well.
Callee-saved registers (d2, d3, a2, a3) and sp must be unchanged after every call.

  python3 verify_skip.py <decoded_stock.bin> <decoded_patched.bin> [--presets -2:2,...] [--exhaustive]
"""
import argparse
import itertools
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
import mn103_sim  # noqa: E402

BASE = 0x40030020
M32 = 0xFFFFFFFF
BKT_OFFSET, COUNTER = 0x40124B1C, (0x40133288, 0x40133290)
NEFF = (0x400A1044, 0x400A104D)
PLAN_SITE = 0x40133359
SETTING_GET, STORE_GET, EXPO_BUILD, AE_CALC, AE_STORE = 0x400394A7, 0x4011B100, 0x40133595, 0x400BA9FD, 0x401337FA
WP, FL, CL, LT, STATE = 0xB00F675A, 0xB00F6729, 0xB00F6737, 0xB00F6753, 0xB00F671C
CTX = {0x8281: 0xB0164500, 0x8291: 0xB0164504, 0x80EA: 0xB0164508, 0x85F1: 0xB01644FC}   # key -> ctx variable
SAVED = ("d2", "d3", "a2", "a3", "sp")


def sx16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# ---------------------------------------------------------------- reference rules
class Ref:
    def __init__(self, table, focus):
        self.table = dict(table)                # {n: LO} for every preset
        self.n, self.lo = focus, self.table[focus]

    def ext_lo(self, n):
        return self.table.get(n & 0xFF)

    @staticmethod
    def validate(f, c, n):
        return (f, c) if c >= 1 and f + c <= n else (0, n)

    def wp(self, ram, n):
        w = ram.get("WP", 0)
        return self.validate(w & 0xFF, w >> 8, n)

    def latched(self, ram, n):
        if ram.get("LT", 0) == 1:
            return self.validate(ram.get("FL", 0), ram.get("CL", 0), n)
        return self.wp(ram, n)

    @staticmethod
    def stock_offset(n, idx, step):
        if idx == 0:
            return 0
        d = idx - n // 2
        if d <= 0:
            d -= 1
        return sx16(d * sx16(step))

    def bkt_offset(self, n, idx, step, ram):
        n, idx = n & 0xFF, idx & 0xFF
        lo = self.ext_lo(n)
        if lo is None:
            return self.stock_offset(n, idx, step)
        active = idx != 0 or ram.get("STATE", 0) in (2, 3)
        f = (self.latched if active else self.wp)(ram, n)[0]
        return sx16((f + idx - lo) * sx16(step))

    def counter(self, idx, n, ram):
        idx, n = idx & 0xFF, n & 0xFF
        c = self.latched(ram, n)[1] if self.ext_lo(n) is not None else n
        return 0 if idx + 1 >= c else idx + 1


# ---------------------------------------------------------------- simulator setup
def make_sims(stock, patched, sym):
    blob_lo, blob_hi = sym["ext_table"], max(sym.values()) + 0x40
    st = mn103_sim.Sim(stock, BASE, [(BKT_OFFSET, BKT_OFFSET + 40), COUNTER, NEFF])
    pa = mn103_sim.Sim(patched, BASE, [(BKT_OFFSET, BKT_OFFSET + 40), COUNTER, NEFF, (PLAN_SITE, PLAN_SITE + 8),
                                       (sym["ext_lo"], blob_hi)])
    return st, pa


def put_ram(sim, ram):
    sim.wr(WP, 2, ram.get("WP", 0))
    sim.wr(FL, 1, ram.get("FL", 0))
    sim.wr(CL, 1, ram.get("CL", 0))
    sim.wr(LT, 1, ram.get("LT", 0))
    sim.wr(STATE, 2, ram.get("STATE", 0))


def get_ram(sim):
    return {"WP": sim.rd(WP, 2), "FL": sim.rd(FL, 1), "CL": sim.rd(CL, 1), "LT": sim.rd(LT, 1)}


ENTRY = {"d2": 0x13572468, "d3": 0x24681357, "a2": 0x600000A2, "a3": 0x600000A3}


def check_saved(before, after, key):
    for k in SAVED:
        assert after[k] == before[k], (f"{k} not preserved", key)


RAM_STATES = [
    {},                                                         # boot: all zero
    {"WP": 3 | 12 << 8},                                        # plan F=3 C=12
    {"WP": 0 | 22 << 8},                                        # full plan
    {"WP": 20 | 10 << 8},                                       # invalid (F + C > n)
    {"WP": 5 | 0 << 8},                                         # invalid (C == 0)
    {"WP": 3 | 12 << 8, "LT": 1, "FL": 7, "CL": 9},             # latched, different from WP
    {"WP": 3 | 12 << 8, "LT": 1, "FL": 30, "CL": 30},           # latched but invalid
    {"WP": 3 | 12 << 8, "LT": 0, "FL": 7, "CL": 9},             # stale latch, not valid
]


# ---------------------------------------------------------------- 1. bkt_offset
def test_bkt_offset(st, pa, ref, exhaustive=False):
    checked = 0
    if exhaustive:      # every n and idx; stock n only in the boot RAM state
        values = range(256)
        space = itertools.product(values, values, (0x55, 0xAA, 0x100, 0xFFAB), (0,))
    else:
        space = itertools.product(
            sorted({0, 1, 2, 3, 4, 5, 6, 13, 37, 255} | {m + d for m in ref.table for d in (-1, 0, 1)}),
            (0, 1, 2, 3, 5, 8, 9, 12, 20, 21, 22, 30, 255), (0x55, 0xAA, 0x100, 0xFFAB), (0, 0xABCDEF00))
    for n, idx, step, junk in space:
        ext = ref.ext_lo(n) is not None
        rams = RAM_STATES if ext else RAM_STATES[:2 - exhaustive]
        for ram, state in itertools.product(rams, (0, 1, 2, 3, 4) if not exhaustive or ext else (0,)):
            ram = dict(ram, STATE=state)
            regs = dict(ENTRY, d0=n | junk, d1=idx | junk, a0=step | (junk & 0xFFFF0000))
            out = []
            for sim in (st, pa):
                sim.reset()
                put_ram(sim, ram)
                before = dict(sim.r, **regs)
                r = sim.call(BKT_OFFSET, ("d2", "d3"), 8, **regs)
                check_saved(before, r, (n, idx, step, ram))
                out.append(r["d0"])
            want = ref.bkt_offset(n, idx, step, ram) & M32
            key = (n, idx, hex(step), hex(junk), ram)
            if ref.ext_lo(n) is None:
                assert out[0] == out[1], ("bkt_offset differs from stock", key, hex(out[0]), hex(out[1]))
            assert out[1] == want, ("bkt_offset != rule", key, hex(out[1]), hex(want))
            assert out[0] == (ref.stock_offset(n, idx, step) & M32), ("stock sim != stock rule", key)
            checked += 1
    return checked


# ---------------------------------------------------------------- 2. counter
def test_counter(st, pa, ref):
    checked = 0
    for n, idx in itertools.product((1, 2, 3, 5, 13, ref.n - 1, ref.n, ref.n + 1, 37, 255),
                                    (0, 1, 2, 4, 8, 11, 12, 20, 21, 22, 36, 254, 255)):
        rams = RAM_STATES if ref.ext_lo(n) is not None else RAM_STATES[:2]
        for ram in rams:
            regs = dict(ENTRY, d0=idx, d2=n)
            out = []
            for sim in (st, pa):
                sim.reset()
                put_ram(sim, ram)
                for k, v in regs.items():
                    sim.r[k] = v
                before = dict(sim.r)
                r = sim.run(COUNTER[0], until=COUNTER[1])
                check_saved(before, r, (n, idx, ram))
                out.append(r["d0"] & 0xFF)
            key = (n, idx, ram)
            if ref.ext_lo(n) is None:
                assert out[0] == out[1], ("counter differs from stock", key, out)
            assert out[1] == ref.counter(idx, n, ram), ("counter != rule", key, out, ref.counter(idx, n, ram))
            checked += 1
    return checked


# ---------------------------------------------------------------- 3. n_eff
def test_neff(st, pa, ref):
    checked = 0
    s7s = sorted({0, 1, 7, 9, 12, 21, 22, 30, 40, ref.n})     # incl. #7 == C for the RAM states' plans
    for s6, s7, state in itertools.product((0, 3, 5, ref.n - 1, ref.n, 37), s7s, (0, 1, 2, 3, 4)):
        for ram in RAM_STATES:
            settings = {6: s6, 7: s7}
            stub = {SETTING_GET: lambda sim, regs, imm, s=settings: sim.r.update(
                d0=s[sim.r["d0"] & 0xFFFF], d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)}
            out = []
            for sim in (st, pa):
                sim.reset()
                sim.stubs = stub
                put_ram(sim, dict(ram, STATE=state))
                for k, v in ENTRY.items():
                    sim.r[k] = v
                before = dict(sim.r)
                r = sim.run(NEFF[0], until=NEFF[1])
                check_saved(before, r, (s6, s7, state, ram))
                out.append((r["d0"], get_ram(sim)))
            key = (s6, s7, state, ram)
            if ref.ext_lo(s6) is None:
                assert out[1] == out[0], ("n_eff differs from stock", key, out)
                continue
            got, gram = out[1]
            exp_ram = {"WP": ram.get("WP", 0), "FL": ram.get("FL", 0), "CL": ram.get("CL", 0), "LT": ram.get("LT", 0)}
            if state in (2, 3):
                if s7 == 0:
                    f, c = ref.wp(ram, s6)
                    exp_ram.update(FL=f, CL=c, LT=1)
                    want = c
                else:
                    c = ref.latched(ram, s6)[1]
                    want = c if c > s7 else s7 + 1      # limit = want - #7, at least 1
            else:
                exp_ram["LT"] = 0
                want = ref.wp(ram, s6)[1]
            assert got == want and gram == exp_ram, ("n_eff != rule", key, got, want, gram, exp_ram)
            checked += 1
    return checked


# ---------------------------------------------------------------- AE / camera model for 4 and 5
P0, P1, P2, OUT, ARR = 0x60001000, 0x60001100, 0x60001200, 0x60001300, 0x60001300 - 16


class Camera:
    """Independent model of the bits of cam_capture_prep / ae_calc that the plan depends on."""

    def __init__(self, sim, ref, scene):
        self.sim, self.ref, self.sc = sim, ref, scene
        self.stores, self.preps, self.last_off = [], 0, None

    def clamp(self, v, lo, hi):
        return max(lo, min(hi, v))

    def settings_key(self, key):
        sc = self.sc
        return {0x8281: sc["n"], 0x8291: sc["idx"], 0x80EA: sc["step"], 0x85F1: sc["bkt_on"]}[key]

    def install(self):
        sim, sc = self.sim, self.sc
        for key, ctxvar in CTX.items():
            sim.wr(ctxvar, 4, 0x61000000 + key)              # each context pointer is distinct
        sim.wr(P0 + 3, 1, sc["mode"])
        sim.wr(P0 + 6, 1, sc["flash"])
        for i, p in enumerate((P0, P1, P2, OUT)):
            sim.wr(ARR + 4 * i, 4, p)
        sim.stubs = {STORE_GET: self.store_get, EXPO_BUILD: self.expo_build, AE_CALC: self.ae_calc,
                     AE_STORE: self.ae_store}

    def store_get(self, sim, regs, imm):
        key, idx, ctx = sim.r["d0"] & 0xFFFF, sim.r["d1"], sim.r["a0"]
        assert idx == 0 and ctx == 0x61000000 + key, ("store_get context", hex(key), hex(ctx))
        sim.r.update(d0=self.settings_key(key), d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)

    def offset(self):
        sc, sim = self.sc, self.sim
        saved = dict(sim.r)
        r = sim.call(BKT_OFFSET, ("d2", "d3"), 8, d0=sc["n"], d1=sc["idx"], a0=sc["step"])
        sim.r.update({k: saved[k] for k in ("d0", "d1", "a0", "a1")})
        return sx16(r["d0"])

    def expo_build(self, sim, regs, imm):
        assert sim.r["a0"] == P1, "expo_build p1"
        self._build()
        sim.r.update(d0=0xDEAD0000, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)

    def _build(self):
        sc, sim = self.sc, self.sim
        off = self.offset() if sc["bkt_on"] == 1 and sc["n"] else 0
        self.last_off = off
        m = sc["mode"] == 6
        sim.wr(P1 + 0, 2, (sc["user_tv"] - (off if m else 0)) & 0xFFFF)
        sim.wr(P1 + 2, 2, sc["iso"])
        sim.wr(P1 + 4, 2, sc["user_av"] & 0xFFFF)
        sim.wr(P1 + 6, 2, (sc["comp"] + (0 if m else off)) & 0xFFFF)

    def ae(self, p1_tv, comp):
        """(Tv, Av, err, exposable) for the given exposure params."""
        sc = self.sc
        lo, hi, alo, ahi = sc["lo"], sc["hi"], sc["av_lo"], sc["av_hi"]
        ev = sc["ev"] - comp
        mode = sc["mode"]
        if mode == 6:
            tv_raw = sx16(p1_tv)
            tv = self.clamp(tv_raw, -1536, 3072)
            av = self.clamp(sc["user_av"], alo, ahi)
            ok = max(lo, -1536) <= tv_raw <= min(hi, 3072)
            return tv, av, ev - tv - av, ok
        if mode == 4:
            av = self.clamp(sc["user_av"], alo, ahi)
            tv = self.clamp(ev - av, lo, hi)
        elif mode == 5:
            tv = self.clamp(self.clamp(sc["user_tv"], -1536, 3072), lo, hi)
            av = self.clamp(ev - tv, alo, ahi)
        elif mode in (3, 7):
            tv0 = self.clamp(ev - (alo + ahi) // 2, lo, hi)
            av = self.clamp(ev - tv0, alo, ahi)
            tv = self.clamp(ev - av, lo, hi)
        else:                                               # scene modes: anything
            av, tv = self.clamp(sc["user_av"], alo, ahi), self.clamp(ev - sc["user_av"], lo, hi)
        err = ev - tv - av
        return tv, av, err, err == 0

    def ae_calc(self, sim, regs, imm):
        assert sim.r["a0"] == ARR, "ae_calc array"
        self._calc()
        sim.r.update(d0=0xDEAD0000, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)

    def _calc(self):
        sc, sim = self.sc, self.sim
        tv, av, err, _ = self.ae(sim.rd(P1, 2), sx16(sim.rd(P1 + 6, 2)))
        for off, v in ((2, tv), (6, av), (12, sc["av_lo"]), (14, sc["av_hi"]), (22, err), (34, sc["hi"]),
                       (36, sc["lo"])):
            sim.wr(OUT + off, 2, v & 0xFFFF)
        self.preps += 1

    def ae_store(self, sim, regs, imm):
        assert (sim.r["a0"], sim.r["d0"], sim.r["a1"]) == (OUT, P1, P0), "ae_store args"
        self.stores.append((self.last_off, sx16(sim.rd(OUT + 2, 2)), sx16(sim.rd(OUT + 6, 2))))
        sim.r.update(d0=0x5700E5, d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)

    def prep(self):
        """A full cam_capture_prep: build, AE, then the (patched) store path."""
        self._build()
        self._calc()
        sim = self.sim
        regs = dict(ENTRY, a0=OUT, d0=P1, a1=P0, a2=P2)
        before = dict(sim.r, **regs)
        r = sim.call(PLAN_SITE, ("d2", "d3", "a2", "a3"), 136, **regs)
        check_saved(before, r, ("prep", self.sc))
        assert r["d0"] == 0x5700E5, "plan_hook must return ae_store's d0"

    def frame_ok(self, j):
        """Ground truth: can frame j (offset (j - LO) * step) be exposed as asked?"""
        sc = self.sc
        o = (j - self.ref.lo) * sx16(sc["step"])
        if sc["mode"] == 6:
            return self.ae(sc["user_tv"] - o, 0)[3]
        return self.ae(0, sc["comp"] + o)[3]

    def no_plan(self):
        sc = self.sc
        return sc["flash"] == 1 or sc["mode"] not in (3, 4, 5, 6, 7) or (sc["mode"] != 6 and sc["iso"] == 0) \
            or (sc["mode"] == 6 and sc["user_tv"] == -32768)

    def truth_plan(self):
        """(F, C) the plan must produce: the exposable frames, or one frame at the nearer end."""
        n = self.sc["n"]
        if self.no_plan():
            return 0, n
        ok = [j for j in range(n) if self.frame_ok(j)]
        if ok:
            return ok[0], ok[-1] - ok[0] + 1
        sc = self.sc
        o_last = (n - 1 - self.ref.lo) * sx16(sc["step"])     # frame n - 1 gets the most exposure
        if sc["mode"] == 6:
            too_bright = sc["user_tv"] - o_last > min(sc["hi"], 3072)
        else:
            too_bright = self.ae(0, sc["comp"] + o_last)[2] > 0
        return (n - 1 if too_bright else 0), 1


def scenes(ref, rng, count):
    n = ref.n
    out = []
    for _ in range(count):
        mode = rng.choice((3, 4, 4, 4, 5, 6, 6, 7, 8))
        sc = {"n": n, "idx": 0, "step": 0x55, "bkt_on": 1, "mode": mode,
              "flash": 1 if rng.random() < 0.08 else 0, "iso": 0 if rng.random() < 0.08 else 100,
              "user_av": rng.choice((256 * 2, 256 * 4, 256 * 5 + 85, 256 * 8)),
              "user_tv": rng.choice((-32768, -1536, -768, 0, 256 * 6, 256 * 8, 256 * 11, 3072)) if mode == 6
              else rng.choice((0, 256 * 6, 256 * 9)),
              "comp": rng.choice((0, 0, -256, 256, 2 * 256)),
              "ev": rng.randint(-8 * 256, 22 * 256),
              "lo": rng.choice((-1536, -1536, -1024, 0, 512)), "hi": rng.choice((3072, 3072, 1792, 1280)),
              "av_lo": rng.choice((256 * 2, 256 * 3)), "av_hi": rng.choice((256 * 8, 256 * 10))}
        out.append(sc)
    return out


# ---------------------------------------------------------------- 4. plan_hook
def test_plan(pa, ref, rng, count):
    checked = 0
    frozen_kinds = [None, "idx", "state2", "state3", "bkt_off", "stock_n"]
    for sc0 in scenes(ref, rng, count):
        for start_wp in (0, 4 | 10 << 8, 9 | 1 << 8, 0 | 22 << 8):
            for frozen in frozen_kinds:
                sc = dict(sc0)
                state = 0
                if frozen == "idx":
                    sc["idx"] = 5
                elif frozen == "state2":
                    state = 2
                elif frozen == "state3":
                    state = 3
                elif frozen == "bkt_off":
                    sc["bkt_on"] = 0
                elif frozen == "stock_n":
                    sc["n"] = 3
                pa.reset()
                cam = Camera(pa, ref, sc)
                cam.install()
                put_ram(pa, {"WP": start_wp, "STATE": state})
                f_before = ref.wp({"WP": start_wp}, sc["n"])[0] if frozen != "stock_n" else None
                cam.prep()
                wp = pa.rd(WP, 2)
                key = (sc, hex(start_wp), frozen)
                assert len(cam.stores) == 1, ("ae_store must run exactly once", key, cam.stores)
                if frozen is not None:
                    assert wp == start_wp, ("frozen plan changed", key, hex(wp))
                    assert cam.preps == 1, ("frozen plan re-ran AE", key)
                    checked += 1
                    continue
                f, c = cam.truth_plan()
                assert (wp & 0xFF, wp >> 8) == (f, c), ("plan != truth", key, (wp & 0xFF, wp >> 8), (f, c))
                assert cam.preps == (1 if f == f_before else 2), ("re-prep count", key, cam.preps)
                want_off = (f - ref.lo) * sx16(sc["step"])
                assert cam.stores[0][0] == want_off, ("stored outputs not for frame F", key, cam.stores, want_off)
                checked += 1
    return checked


# ---------------------------------------------------------------- 5. bursts
def test_bursts(pa, ref, rng, count):
    checked = 0
    for sc in scenes(ref, rng, count):
        pa.reset()
        cam = Camera(pa, ref, dict(sc, idx=0))
        cam.install()
        put_ram(pa, {"WP": rng.choice((0, 4 | 10 << 8)), "STATE": 1})
        cam.prep()                                       # metering while half-pressed
        cam.prep()                                       # settles
        f, c = cam.truth_plan()
        exposable = not cam.no_plan() and any(cam.frame_ok(j) for j in range(sc["n"]))
        pa.wr(STATE, 2, 2)                               # full press: PICTURE
        settings = {6: sc["n"], 7: 0}
        pa.stubs[SETTING_GET] = lambda sim, regs, imm: sim.r.update(
            d0=settings[sim.r["d0"] & 0xFFFF], d1=0xDEAD0001, a0=0xDEAD0002, a1=0xDEAD0003)
        limit = pa.run(NEFF[0], until=NEFF[1])["d0"]
        assert limit == c, ("limit != planned count", sc, limit, (f, c))
        wp = pa.rd(WP, 2)
        for k in range(limit):
            cam.sc["idx"] = k
            j = f + k
            off = cam.offset()
            assert off == (j - ref.lo) * sx16(sc["step"]), ("frame offset", sc, k, off)
            if exposable:
                assert cam.frame_ok(j), ("shot an unexposable frame", sc, k, j)
            pa.r.update(ENTRY, d0=k, d2=sc["n"])
            nxt = pa.run(COUNTER[0], until=COUNTER[1])["d0"] & 0xFF
            assert nxt == (0 if k == limit - 1 else k + 1), ("counter", sc, k, nxt)
            cam.sc["idx"] = nxt
            stores = len(cam.stores)
            cam.prep()                                   # re-prep after the counter advance (frozen)
            assert len(cam.stores) == stores + 1 and pa.rd(WP, 2) == wp, ("plan changed mid-burst", sc, k)
        checked += 1
    return checked


def verify(stock, patched, presets, sym, quiet=False, plans=300, bursts=200, seed=1, exhaustive=False, quick=False):
    """presets: [(n, LO, HI)]. Tests 2-5 per preset; quick: fewer AE scenes per preset."""
    table = {n: lo for n, lo, _ in presets}
    st, pa = make_sims(stock, patched, sym)
    rng = random.Random(seed)
    if quick:
        plans, bursts = max(1, plans // 4), max(1, bursts // 4)
    counts = {"bkt_offset": 0, "counter": 0, "n_eff": 0, "plan_hook": 0, "bursts": 0}
    for i, (n, _, _) in enumerate(presets):
        ref = Ref(table, n)
        if i == 0:
            counts["bkt_offset"] += test_bkt_offset(st, pa, ref, exhaustive)
        counts["counter"] += test_counter(st, pa, ref)
        counts["n_eff"] += test_neff(st, pa, ref)
        counts["plan_hook"] += test_plan(pa, ref, rng, plans)
        counts["bursts"] += test_bursts(pa, ref, rng, bursts)
    if not quiet:
        print("OK: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return sum(counts.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", help="decoded stock image")
    ap.add_argument("patched", help="decoded patched image")
    ap.add_argument("--presets", default=None, help="as build.py --presets (default: build.py's)")
    ap.add_argument("--plans", type=int, default=1000)
    ap.add_argument("--bursts", type=int, default=500)
    ap.add_argument("--exhaustive", action="store_true", help="bkt_offset over every n and idx in 0..255 (slow)")
    args = ap.parse_args()
    sys.path.insert(0, HERE)
    import build
    presets = build.parse_presets(args.presets or build.DEFAULT_PRESETS)
    sym = build.link_skip(presets)[1]
    verify(open(args.stock, "rb").read(), open(args.patched, "rb").read(), presets, sym,
           plans=args.plans, bursts=args.bursts, exhaustive=args.exhaustive)


if __name__ == "__main__":
    main()
