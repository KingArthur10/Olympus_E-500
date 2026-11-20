#!/usr/bin/env python3
"""List call sites of a function in a flat MN10300 image, with the immediate
loaded into d0 just before the call (useful for setting_get(id)-style APIs).

  tools/mn103_calls.py decoded.bin --base 0x40030020 --target 0x400394a7 [--id 8]
"""
import argparse
import struct


def call_sites(data, base, target):
    """Yield offsets of `call` (CD d16 / DD d32) instructions that reach target."""
    for op, fmt in ((0xDD, "<i"), (0xCD, "<h")):
        i = data.find(bytes([op]))
        while i >= 0:
            if i + 5 <= len(data) and base + i + struct.unpack_from(fmt, data, i + 1)[0] == target:
                yield i
            i = data.find(bytes([op]), i + 1)


def d0_imm(data, i):
    """Immediate moved into d0 right before offset i, if a simple form is present."""
    if data[i - 2] == 0x80:                 # mov imm8,d0
        return data[i - 1]
    if data[i - 3] == 0x2C:                 # mov imm16,d0
        return struct.unpack_from("<H", data, i - 2)[0]
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--base", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--target", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--id", type=lambda s: int(s, 0), action="append",
                    help="only show sites whose d0 immediate matches (repeatable)")
    args = ap.parse_args()
    data = open(args.image, "rb").read()
    for i in sorted(call_sites(data, args.base, args.target)):
        imm = d0_imm(data, i)
        if args.id and imm not in args.id:
            continue
        print(f"0x{args.base + i:08x}  d0={'?' if imm is None else imm}")


if __name__ == "__main__":
    main()
