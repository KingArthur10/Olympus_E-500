#!/usr/bin/env python3
"""Independently check a patched Olympus "OE" firmware file against the stock file.

Deliberately does NOT import oly_fw.py: the deobfuscation is re-implemented here
from the documented rule (cipher[j] = ~plain[PERM16[j]] per 16-byte block), so a
bug in the main tooling cannot hide itself. Checks:
  * same size; header and trailer[0:0x1C] byte-identical to stock
  * u32 sum of header + decoded payload + trailer == 0 for both files
  * every decoded byte that differs lies inside an edit declared in the patch JSON,
    and each edit's orig/new bytes are present in stock/patched respectively
  * every raw (encoded) byte that differs lies in an edited 16-byte block or the checksum

  tools/oly_diffcheck.py <stock.BIN> <patched.BIN> <patch.json>
Exit status 0 only if every check passes.
"""
import argparse
import json
import struct
import sys

HDR = 0x20
PERM16 = (2, 0, 3, 1, 5, 7, 4, 6, 11, 10, 9, 8, 14, 12, 13, 15)


def decode(c):
    out = bytearray(len(c))
    for b in range(0, len(c), 16):
        for j in range(16):
            out[b + PERM16[j]] = c[b + j] ^ 0xFF
    return bytes(out)


def u32sum(b):
    return sum(struct.unpack(f"<{len(b) // 4}I", b)) & 0xFFFFFFFF


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock")
    ap.add_argument("patched")
    ap.add_argument("patch_json")
    args = ap.parse_args()
    st, pa = open(args.stock, "rb").read(), open(args.patched, "rb").read()
    spec = json.load(open(args.patch_json))
    base = int(spec["base"], 0)
    fails = []

    def check(ok, msg):
        print(("PASS  " if ok else "FAIL  ") + msg)
        if not ok:
            fails.append(msg)

    check(len(st) == len(pa), f"size {len(pa)} == stock {len(st)}")
    check(st[:HDR] == pa[:HDR], "header identical to stock")
    check(st[-HDR:-4] == pa[-HDR:-4], "trailer[0:0x1C] identical to stock")
    ds, dp = decode(st[HDR:-HDR]), decode(pa[HDR:-HDR])
    check(u32sum(st[:HDR] + ds + st[-HDR:]) == 0, "stock container sum == 0")
    check(u32sum(pa[:HDR] + dp + pa[-HDR:]) == 0, "patched container sum == 0")

    allowed = set()
    for e in spec["edits"]:
        off = int(e["addr"], 0) - base
        o, n = bytes.fromhex(e["orig"]), bytes.fromhex(e["new"])
        check(ds[off:off + len(o)] == o and dp[off:off + len(n)] == n,
              f"edit {e['addr']} ({len(o)} B): stock has orig, patched has new")
        allowed.update(range(off, off + len(o)))
    diffs = [i for i in range(len(ds)) if ds[i] != dp[i]]
    stray = [i for i in diffs if i not in allowed]
    check(not stray, f"{len(diffs)} decoded bytes differ, {len(stray)} outside declared edits"
          + (f" (first 0x{base + stray[0]:08x})" if stray else ""))
    blocks = {i // 16 for i in allowed}
    raw = [i for i in range(len(st)) if st[i] != pa[i]]
    raw_stray = [i for i in raw if not (i >= len(st) - 4 or (HDR <= i < len(st) - HDR and (i - HDR) // 16 in blocks))]
    check(not raw_stray, f"{len(raw)} raw bytes differ, {len(raw_stray)} outside edited blocks/checksum")
    print("RESULT:", "all checks passed" if not fails else f"{len(fails)} check(s) FAILED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
