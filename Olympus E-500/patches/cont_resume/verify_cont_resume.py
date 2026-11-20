#!/usr/bin/env python3
"""Exhaustive test of the cont_resume edit (E-500 fw 1.3).

Runs the bytes at 0x400A30F7 (the two stock checks in trig_can_resume) from a STOCK and
a PATCHED decoded image through a minimal MN10300 interpreter. Execution either falls
through to 0x400A310B (checks passed) or reaches 0x400A316F (fail). setting_get is
stubbed, and RAM flags come from a table. Checks, over every combination of flag and
setting values tested:
  * stock image   == stock rule  (6725 == 1 and 6736 == 1)      validates the interpreter
  * patched image == stock rule OR the new held-press rule (see cont_resume.S)

  python3 verify_cont_resume.py <decoded_stock.bin> <decoded_patched.bin>
"""
import argparse
import itertools
import struct

BASE = 0x40030020
START, PASS, FAIL = 0x400A30F7, 0x400A310B, 0x400A316F
SETTING_GET = 0x400394A7
M32 = 0xFFFFFFFF


class Unknown(Exception):
    pass


def run(img, ram, settings, junk, max_steps=500):
    """Return True (pass) / False (fail). ram: {addr: value}; settings: {id: value}."""
    rd = lambda a, k: img[a - BASE:a - BASE + k]  # noqa: E731
    sx8 = lambda b: b - 256 if b & 0x80 else b  # noqa: E731
    d0 = 0x5A5A5A5A
    z = n = v = 0
    stack = []
    pc = START

    def cmp(dst, src):
        nonlocal z, n, v
        r = (dst - src) & M32
        z, n = int(r == 0), r >> 31
        v = ((dst ^ src) & (dst ^ r)) >> 31 & 1

    for _ in range(max_steps):
        if pc == PASS and not stack:
            return True
        if pc == FAIL and not stack:
            return False
        c = rd(pc, 7)
        op = c[0]
        if op == 0xFC and c[1] in (0xA8, 0xAC):            # movbu/movhu (abs32),d0
            a = struct.unpack_from("<I", c, 2)[0]
            if a not in ram:
                raise Unknown(f"read of unmodelled RAM 0x{a:08x} at 0x{pc:08x}")
            d0 = ram[a] & (0xFF if c[1] == 0xA8 else 0xFFFF)
            pc += 6
        elif op == 0xA0:                                   # cmp imm8,d0
            cmp(d0, sx8(c[1]) & M32); pc += 2
        elif op == 0x80:                                   # mov imm8,d0
            d0 = sx8(c[1]) & M32; pc += 2
        elif op == 0x2C:                                   # mov imm16,d0 (sign-extended)
            d0 = struct.unpack_from("<h", c, 1)[0] & M32; pc += 3
        elif op == 0x00:                                   # clr d0
            d0 = 0; z, n, v = 1, 0, 0; pc += 1
        elif op == 0x14:                                   # extbu d0
            d0 &= 0xFF; pc += 1
        elif op == 0x18:                                   # exth d0
            d0 = (d0 & 0xFFFF) - (0x10000 if d0 & 0x8000 else 0) & M32; pc += 1
        elif op == 0x1C:                                   # exthu d0
            d0 &= 0xFFFF; pc += 1
        elif op == 0xCB:                                   # nop
            pc += 1
        elif op in (0xC8, 0xC9, 0xCA):                     # beq / bne / bra rel8
            take = {0xC8: z, 0xC9: not z, 0xCA: True}[op]
            pc = pc + sx8(c[1]) if take else pc + 2
        elif op == 0xDD:                                   # call d32,regs,imm8
            tgt = (pc + struct.unpack_from("<i", c, 1)[0]) & M32
            if tgt == SETTING_GET:
                if c[5:7] != b"\xc0\x0c":
                    raise Unknown("setting_get called with an unexpected frame")
                d0 = (settings[d0 & 0xFFFF] | junk) & M32
                pc += 7
            else:
                stack.append((pc + 7, c[5:7])); pc = tgt
        elif op == 0xDF:                                   # ret regs,imm8
            if not stack:
                raise Unknown("ret with empty stack")
            ret, frame = stack.pop()
            if c[1:3] != frame:
                raise Unknown(f"ret frame {c[1:3].hex()} != call frame {frame.hex()}")
            pc = ret
        else:
            raise Unknown(f"opcode {c[:3].hex()} at 0x{pc:08x}")
    raise Unknown("no exit")


def stock_rule(f25, f36):
    return f25 == 1 and f36 == 1


def new_rule(f25, f36, f43, f49, lim, s88, s7, s305, s307):
    if stock_rule(f25, f36):
        return True
    held = f36 == 1 and f25 == 2 and f43 == 1 and f49 != 1
    bracket_ok = (s88 & 0xFFFF) == 1 and (s7 & 0xFF) != 0 and (s305 & 0xFFFF) == 0 and (s307 & 0xFFFF) == 0
    return held and (lim == 0xFFFF or bracket_ok)


def verify(stock, patched, quiet=False):
    """Raise AssertionError on any mismatch; return the number of cases checked."""
    space = itertools.product(
        range(6), range(4), (0, 1, 2), (0, 1, 2),          # 6725, 6736, 6743, 6749
        (0xFFFF, 0, 3, 21, 0x7FFF, 0x8000),                # limit 6722 (u16 in RAM)
        (0, 1, 2), (0, 1, 21, 256), (0, 3), (0, 3),        # #88, #7, #305, #307
        (0, 0xABCD0000))                                   # junk in setting_get's upper bits
    checked = 0
    for f25, f36, f43, f49, lim, s88, s7, s305, s307, junk in space:
        ram = {0xB00F6725: f25, 0xB00F6736: f36, 0xB00F6743: f43, 0xB00F6749: f49, 0xB00F6722: lim}
        settings = {88: s88, 7: s7, 305: s305, 307: s307}
        o = run(stock, ram, settings, junk)
        w = run(patched, ram, settings, junk)
        key = (f25, f36, f43, f49, hex(lim), s88, s7, s305, s307, hex(junk))
        assert o == stock_rule(f25, f36), ("stock image != stock rule", key, o)
        # setting values are masked to their width, so junk in the upper bits must not matter
        assert w == new_rule(f25, f36, f43, f49, lim, s88, s7, s305, s307), ("patched != new rule", key, w)
        checked += 1
    if not quiet:
        print(f"OK: {checked} cases; stock image follows the stock rule, patched image the new rule")
    return checked


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock", help="decoded stock image")
    ap.add_argument("patched", help="decoded patched image")
    args = ap.parse_args()
    verify(open(args.stock, "rb").read(), open(args.patched, "rb").read())


if __name__ == "__main__":
    main()
