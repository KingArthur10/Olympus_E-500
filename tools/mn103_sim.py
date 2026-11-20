#!/usr/bin/env python3
"""Minimal MN10300 interpreter for differential tests of firmware patches.

Executes a flat image by interpreting objdump's disassembly text, so the bytes under
test are decoded by binutils (no hand-written decoder). Only the instruction forms
the patch tests need are implemented; anything else raises Unknown, so nothing runs
silently wrong. Calls to addresses in `stubs` run a Python function instead.

Call frames follow the MN10300 `call`/`ret` convention: `call t,[regs],imm` stores
the return address at (sp), saves regs just below sp, then sp -= imm. Accesses to
(d8,sp) are checked against the current frame's local area (4 .. imm - 4*nregs - 1).

  python3 tools/mn103_sim.py <decoded.bin> <start> <stop>   # print the parsed listing
"""
import argparse
import bisect
import re
import struct
import subprocess
import tempfile

M32 = 0xFFFFFFFF
REGS = ("d0", "d1", "d2", "d3", "a0", "a1", "a2", "a3")


class Unknown(Exception):
    pass


def s32(v):
    v &= M32
    return v - (1 << 32) if v & 0x80000000 else v


def disassemble(image, base, ranges):
    """{addr: (size, mnemonic, operands)} for the given [start, stop) ranges of a flat image."""
    out = {}
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(image)
        f.flush()
        for start, stop in ranges:
            txt = subprocess.run(
                ["mn10300-linux-gnu-objdump", "-b", "binary", "-m", "mn10300", "-D", "-z",
                 f"--adjust-vma=0x{base:x}", f"--start-address=0x{start:x}", f"--stop-address=0x{stop:x}",
                 f.name], check=True, capture_output=True, text=True).stdout
            rows = []
            for line in txt.splitlines():
                m = re.match(r"\s*([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*(?:\t(\S+)\s*(.*))?$", line)
                if not m:
                    continue
                rows.append((int(m.group(1), 16), len(m.group(2).split()), m.group(3), (m.group(4) or "").strip()))
            # objdump splits long instructions over several lines; merge byte counts into the head line
            merged = []
            for a, n, mn, ops in rows:
                if mn is None and merged:
                    pa, pn, pmn, pops = merged[-1]
                    merged[-1] = (pa, pn + n, pmn, pops)
                else:
                    merged.append((a, n, mn, ops))
            for a, n, mn, ops in merged:
                out[a] = (n, mn, ops)
    return out


class Sim:
    def reset(self):
        """Clear RAM, registers, flags and frames (the decoded listing is kept)."""
        self.mem = {}
        self.r = {k: 0 for k in REGS}
        self.r["sp"] = 0x7F000000
        self.mdr = 0
        self.z = self.n = self.c = self.v = 0
        self.frames = []

    def __init__(self, image, base, ranges, stubs=None):
        self.img, self.base = image, base
        self.code = disassemble(image, base, ranges)
        self.stubs = stubs or {}
        self.mem = {}                      # sparse RAM/stack, byte-addressed
        self.r = {k: 0 for k in REGS}
        self.r["sp"] = 0x7F000000
        self.mdr = 0
        self.z = self.n = self.c = self.v = 0
        self.frames = []                   # (return address, regs, imm, frame sp)
        self.trace = None

    # ---- memory
    def rd(self, a, k):
        a &= M32
        v = 0
        for i in range(k):
            if (a + i) in self.mem:
                b = self.mem[a + i]
            elif self.base <= a + i < self.base + len(self.img):
                b = self.img[a + i - self.base]
            else:
                raise Unknown(f"read of unmodelled memory 0x{a + i:08x}")
            v |= b << (8 * i)
        return v

    def wr(self, a, k, v):
        a &= M32
        if self.base <= a < self.base + len(self.img):
            raise Unknown(f"write into image at 0x{a:08x}")
        for i in range(k):
            self.mem[a + i] = (v >> (8 * i)) & 0xFF

    # ---- operands
    def _sp_check(self, off, k):
        if self.frames:
            _, regs, imm, _ = self.frames[-1]
            top = imm - 4 * len(regs)
            if not (4 <= off and off + k <= top):
                raise Unknown(f"(d8,sp) access {off}..{off + k - 1} outside locals 4..{top - 1}")

    def addr_of(self, opnd, k):
        m = re.fullmatch(r"\((-?\d+|0x[0-9a-f]+),(sp|a[0-3])\)", opnd)
        if m:
            off = int(m.group(1), 0)
            if m.group(2) == "sp":
                self._sp_check(off, k)
            return (self.r[m.group(2)] + off) & M32
        m = re.fullmatch(r"\((d[0-3]|a[0-3]),(a[0-3])\)", opnd)      # (Di,Am): register index
        if m:
            return (self.r[m.group(1)] + self.r[m.group(2)]) & M32
        m = re.fullmatch(r"\((a[0-3]|sp)\)", opnd)
        if m:
            if m.group(1) == "sp":
                self._sp_check(0, k)
            return self.r[m.group(1)]
        m = re.fullmatch(r"\((0x[0-9a-f]+)\)", opnd)
        if m:
            return int(m.group(1), 16)
        return None

    def val(self, opnd, k=4):
        if opnd in self.r:
            return self.r[opnd]
        if opnd == "mdr":
            return self.mdr
        if re.fullmatch(r"-?\d+|0x[0-9a-f]+", opnd):
            return int(opnd, 0) & M32
        a = self.addr_of(opnd, k)
        if a is None:
            raise Unknown(f"operand {opnd}")
        return self.rd(a, k)

    def setf(self, res, a=None, b=None, sub=False):
        res &= M32
        self.z = int(res == 0)
        self.n = res >> 31
        if a is not None:
            if sub:
                self.c = int((a & M32) < (b & M32))
                self.v = (((a ^ b) & (a ^ res)) >> 31) & 1
            else:
                self.c = int((a & M32) + (b & M32) > M32)
                self.v = ((~(a ^ b) & (a ^ res)) >> 31) & 1
        else:
            self.c = self.v = 0

    # ---- execution
    def call(self, target, regs=(), imm=4, **setregs):
        """Call target as `call target,[regs],imm` from a fake caller; return the register dict."""
        for k, v in setregs.items():
            self.r[k] = v & M32
        fake = 0xFFFFFFF0 - 0x10 * len(self.frames)    # distinct per nesting level
        depth = len(self.frames)
        self._push_frame(fake, list(regs), imm)
        return self.run(target, until=fake, depth=depth)

    def _push_frame(self, ret, regs, imm):
        sp = self.r["sp"]
        self.wr(sp, 4, ret)
        saved = {k: self.r[k] for k in regs}
        self.frames.append((ret, regs, imm, saved))
        self.r["sp"] = (sp - imm) & M32

    def _pop_frame(self, regs, imm):
        if not self.frames:
            raise Unknown("ret with no frame")
        ret, fregs, fimm, saved = self.frames.pop()
        if list(regs) != fregs or imm != fimm:
            raise Unknown(f"ret [{','.join(regs)}],{imm} != call [{','.join(fregs)}],{fimm}")
        self.r["sp"] = (self.r["sp"] + imm) & M32
        if self.rd(self.r["sp"], 4) != ret:
            raise Unknown("return address on the stack was overwritten")
        self.r.update(saved)
        return ret

    def run(self, pc, until, depth=0, max_steps=200000):
        """Execute from pc until pc == until with `depth` frames left (0: back at the top)."""
        for _ in range(max_steps):
            if pc == until and len(self.frames) == depth:
                return dict(self.r)
            if pc not in self.code:
                raise Unknown(f"no decoded instruction at 0x{pc:08x}")
            size, mn, ops = self.code[pc]
            if self.trace is not None:
                self.trace.append((pc, mn, ops))
            nxt = pc + size
            pc = self.step(pc, nxt, mn, ops)
        raise Unknown("step limit")

    def _branch(self, mn, ops, nxt):
        t = int(ops, 16)
        nv = self.n ^ self.v
        take = {"beq": self.z, "bne": not self.z, "blt": nv, "bge": not nv,
                "bgt": not (self.z or nv), "ble": self.z or nv, "bcs": self.c, "bcc": not self.c,
                "bhi": not (self.c or self.z), "bls": self.c or self.z, "bra": True}[mn]
        return t if take else nxt

    def step(self, pc, nxt, mn, ops):
        r = self.r
        a = [x.strip() for x in re.split(r",(?![^\[]*\])(?![^(]*\))", ops)] if ops else []
        if mn in ("beq", "bne", "blt", "bge", "bgt", "ble", "bcs", "bcc", "bhi", "bls", "bra"):
            return self._branch(mn, ops, nxt)
        if mn == "jmp":
            if not re.fullmatch(r"0x[0-9a-f]+", ops):
                raise Unknown(f"jmp {ops}")
            return int(ops, 16)
        if mn == "call":
            m = re.fullmatch(r"(0x[0-9a-f]+),\[([^\]]*)\],(\d+)", ops)
            if not m:
                raise Unknown(f"call {ops}")
            tgt, regs, imm = int(m.group(1), 16), [x for x in m.group(2).split(",") if x], int(m.group(3))
            if tgt in self.stubs:
                self.stubs[tgt](self, regs, imm)
                return nxt
            self._push_frame(nxt, regs, imm)
            return tgt
        if mn in ("ret", "retf"):
            m = re.fullmatch(r"\[([^\]]*)\],(\d+)", ops)
            if not m:
                raise Unknown(f"{mn} {ops}")
            return self._pop_frame([x for x in m.group(1).split(",") if x], int(m.group(2)))
        if mn == "nop":
            return nxt
        if mn in ("mov", "movbu", "movhu"):
            k = {"mov": 4, "movbu": 1, "movhu": 2}[mn]
            src, dst = a
            if dst in r or dst == "mdr":
                if src in r or src == "mdr" or re.fullmatch(r"-?\d+|0x[0-9a-f]+", src):
                    v = self.val(src)
                    if mn != "mov":
                        raise Unknown(f"{mn} {ops}")
                else:
                    v = self.val(src, k)
                if dst == "mdr":
                    self.mdr = v & M32
                else:
                    r[dst] = v & M32
            else:
                ad = self.addr_of(dst, k)
                if ad is None:
                    raise Unknown(f"{mn} {ops}")
                self.wr(ad, k, self.val(src) & ((1 << (8 * k)) - 1))
            return nxt
        if mn in ("extbu", "extb", "exthu", "exth"):
            d = a[0]
            v = r[d]
            if mn == "extbu":
                v &= 0xFF
            elif mn == "extb":
                v = (v & 0xFF) - (0x100 if v & 0x80 else 0)
            elif mn == "exthu":
                v &= 0xFFFF
            else:
                v = (v & 0xFFFF) - (0x10000 if v & 0x8000 else 0)
            r[d] = v & M32
            return nxt
        if mn == "clr":
            r[a[0]] = 0
            self.z, self.n, self.c, self.v = 1, 0, 0, 0
            return nxt
        if mn == "asl2":                                    # Dn <<= 2
            d = a[0]
            r[d] = (r[d] << 2) & M32
            self.setf(r[d])
            return nxt
        if mn in ("inc", "inc4"):
            d = a[0]
            r[d] = (r[d] + (4 if mn == "inc4" else 1)) & M32
            return nxt
        if mn in ("add", "sub"):
            src, d = a
            x, y = r[d], self.val(src)
            if mn == "add":
                res = x + y
                self.setf(res, x, y)
            else:
                res = x - y
                self.setf(res, x, y, sub=True)
            r[d] = res & M32
            return nxt
        if mn == "cmp":
            src, d = a
            x, y = r[d], self.val(src)
            self.setf(x - y, x, y, sub=True)
            return nxt
        if mn == "mul":
            src, d = a
            p = s32(r[d]) * s32(r[src])
            r[d] = p & M32
            self.mdr = (p >> 32) & M32
            self.setf(r[d])
            return nxt
        if mn == "ext":                                     # MDR = sign extension of Dn
            self.mdr = M32 if r[a[0]] & 0x80000000 else 0
            return nxt
        if mn == "div":                                     # signed MDR:Dn / Dm -> Dn, remainder -> MDR
            src, d = a
            num = (self.mdr << 32) | r[d]
            num = num - (1 << 64) if num & (1 << 63) else num
            den = s32(r[src])
            if den == 0:
                raise Unknown("division by zero")
            q = abs(num) // abs(den) * (1 if (num >= 0) == (den > 0) else -1)
            rem = num - q * den
            r[d] = q & M32
            self.mdr = rem & M32
            self.setf(r[d])
            return nxt
        if mn in ("and", "or", "xor"):
            src, d = a
            y = self.val(src)
            r[d] = {"and": r[d] & y, "or": r[d] | y, "xor": r[d] ^ y}[mn] & M32
            self.setf(r[d])
            return nxt
        if mn in ("asl", "lsr", "asr"):
            src, d = a
            sh = self.val(src) & 31
            x = r[d]
            r[d] = {"asl": x << sh, "lsr": x >> sh, "asr": s32(x) >> sh}[mn] & M32
            self.setf(r[d])
            return nxt
        raise Unknown(f"unimplemented {mn} {ops} at 0x{pc:08x}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("start", type=lambda x: int(x, 0))
    ap.add_argument("stop", type=lambda x: int(x, 0))
    ap.add_argument("--base", type=lambda x: int(x, 0), default=0x40030020)
    args = ap.parse_args()
    code = disassemble(open(args.image, "rb").read(), args.base, [(args.start, args.stop)])
    for addr in sorted(code):
        n, mn, ops = code[addr]
        print(f"{addr:08x} {n} {mn} {ops}")


if __name__ == "__main__":
    main()
