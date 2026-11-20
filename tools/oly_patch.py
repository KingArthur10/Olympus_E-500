#!/usr/bin/env python3
"""Apply a JSON patch definition to an Olympus "OE" firmware file.

The patch file pins the exact input firmware (SHA-256), and every edit lists
the ORIGINAL bytes; the tool refuses to apply if anything differs. Output is
re-encoded with a recomputed checksum and verified by decoding it again.

  tools/oly_patch.py <firmware.BIN> <patch.json> <out.BIN>

Patch JSON:
  {"firmware_sha256": "...", "base": "0x40030020",
   "edits": [{"addr": "0x...", "orig": "hex", "new": "hex", "why": "..."}]}
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import oly_fw  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("firmware")
    ap.add_argument("patch")
    ap.add_argument("out")
    args = ap.parse_args()

    raw = open(args.firmware, "rb").read()
    spec = json.load(open(args.patch))
    sha = hashlib.sha256(raw).hexdigest()
    if sha != spec["firmware_sha256"]:
        sys.exit(f"error: firmware sha256 {sha} does not match patch ({spec['firmware_sha256']})")

    base = int(spec["base"], 0)
    hdr, trl, payload = oly_fw.parse(raw)
    plain = bytearray(oly_fw.decode(payload))

    spans = []
    for e in spec["edits"]:
        addr = int(e["addr"], 0)
        orig, new = bytes.fromhex(e["orig"]), bytes.fromhex(e["new"])
        if len(orig) != len(new):
            sys.exit(f"error: 0x{addr:08x}: orig/new length differ ({len(orig)} vs {len(new)})")
        off = addr - base
        if not 0 <= off <= len(plain) - len(orig):
            sys.exit(f"error: 0x{addr:08x} outside image")
        if any(off < b and a < off + len(orig) for a, b in spans):
            sys.exit(f"error: 0x{addr:08x} overlaps another edit")
        if plain[off:off + len(orig)] != orig:
            sys.exit(f"error: 0x{addr:08x}: original bytes differ\n  have {plain[off:off + len(orig)].hex()}\n  want {orig.hex()}")
        spans.append((off, off + len(orig)))
        plain[off:off + len(new)] = new
        changed = sum(a != b for a, b in zip(orig, new))
        print(f"0x{addr:08x}  {len(orig):3d} B  {changed:3d} changed  {e['why']}")

    header = raw[:oly_fw.HDR_SIZE]
    trailer = raw[oly_fw.HDR_SIZE + len(payload):-4]
    out = header + oly_fw.encode(bytes(plain)) + trailer + \
        oly_fw.checksum(header, bytes(plain), trailer).to_bytes(4, "little")

    # independent re-check of the produced file
    h2, t2, p2 = oly_fw.parse(out)
    dec = oly_fw.decode(p2)
    assert dec == bytes(plain), "re-decode mismatch"
    assert oly_fw.checksum(out[:oly_fw.HDR_SIZE], dec, out[oly_fw.HDR_SIZE + len(p2):]) == t2[7], "checksum"
    diff = sum(a != b for a, b in zip(oly_fw.decode(payload), dec))
    allowed = sum(e - s for s, e in spans)
    assert diff <= allowed, "bytes changed outside declared edits"

    with open(args.out, "wb") as f:
        f.write(out)
    print(f"decoded bytes changed: {diff} (all inside {len(spans)} declared edits)")
    print(f"wrote {args.out}\nsha256  {hashlib.sha256(out).hexdigest()}")


if __name__ == "__main__":
    main()
