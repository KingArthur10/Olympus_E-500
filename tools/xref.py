#!/usr/bin/env python3
"""Find little-endian 32-bit references to addresses in a flat decoded image.

Example (E-500 fw 1.3: decoded payload offset 0 is at 0x40030020):
  tools/xref.py decoded.bin --base 0x40030020 --string autobkt_error
  tools/xref.py decoded.bin --base 0x40030020 --addr 0x4020dc14
Hits are printed as image addresses; disassemble around them with
  mn10300-linux-gnu-objdump -b binary -m mn10300 -D --adjust-vma=<base> ...
"""
import argparse
import struct


def find_all(data, needle):
    i = data.find(needle)
    while i >= 0:
        yield i
        i = data.find(needle, i + 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image")
    ap.add_argument("--base", type=lambda s: int(s, 0), required=True,
                    help="address of image offset 0")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--addr", type=lambda s: int(s, 0), action="append")
    g.add_argument("--string", action="append", help="NUL-terminated ASCII string to locate first")
    args = ap.parse_args()
    data = open(args.image, "rb").read()

    targets = []
    if args.addr:
        targets = [(f"0x{a:08x}", a) for a in args.addr]
    else:
        for s in args.string:
            # require a NUL before and after so we match whole strings
            for off in find_all(data, b"\0" + s.encode() + b"\0"):
                targets.append((repr(s), args.base + off + 1))
    for label, addr in targets:
        refs = list(find_all(data, struct.pack("<I", addr)))
        print(f"{label} @ 0x{addr:08x}: {len(refs)} ref(s)")
        for r in refs:
            # MN10300 imm32 operands follow a 2-byte opcode (FC xx); show those bytes for context
            ctx = data[max(0, r - 2):r].hex()
            print(f"  0x{args.base + r:08x}  (preceded by {ctx})")


if __name__ == "__main__":
    main()
