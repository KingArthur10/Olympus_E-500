#!/usr/bin/env python3
"""Check that every instruction form in patched code also occurs in the stock code.

A form is (mnemonic, opcode byte, plus the next byte's high nibble for F-prefixed opcodes).
Forms the stock firmware never uses are listed, because the CPU might not implement them
(e.g. AM33 extensions). Also assemble patch sources under `.mn10300`, which rejects AM33.

  tools/mn103_forms.py <stock_decoded.bin> <patched_decoded.bin> START:STOP [START:STOP ...]
      [--stock-range 0x40030020:0x40167000] [--base 0x40030020]
Exit status 0 only if every form is seen in the stock code range.
"""
import argparse
import re
import subprocess
import sys
import tempfile


def forms(image, base, ranges):
    out = {}
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(image)
        f.flush()
        for lo, hi in ranges:
            txt = subprocess.run(["mn10300-linux-gnu-objdump", "-b", "binary", "-m", "mn10300", "-D", "-z",
                                  f"--adjust-vma=0x{base:x}", f"--start-address=0x{lo:x}",
                                  f"--stop-address=0x{hi:x}", f.name],
                                 check=True, capture_output=True, text=True).stdout
            for line in txt.splitlines():
                m = re.match(r"\s*([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(\S+)", line)
                if not m:
                    continue
                b = m.group(2).split()
                key = (m.group(3), b[0] + b[1][0] if b[0].startswith("f") and len(b) > 1 else b[0])
                out.setdefault(key, line.strip())
    return out


def rng(s):
    lo, hi = s.split(":")
    return int(lo, 0), int(hi, 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock")
    ap.add_argument("patched")
    ap.add_argument("ranges", nargs="+", type=rng, help="START:STOP ranges of patched code")
    ap.add_argument("--stock-range", type=rng, default=(0x40030020, 0x40167000))
    ap.add_argument("--base", type=lambda x: int(x, 0), default=0x40030020)
    args = ap.parse_args()
    stock = forms(open(args.stock, "rb").read(), args.base, [args.stock_range])
    mine = forms(open(args.patched, "rb").read(), args.base, args.ranges)
    missing = [v for k, v in mine.items() if k not in stock]
    print(f"{len(mine)} instruction forms in patched code, {len(missing)} not in stock:")
    for v in missing:
        print("  " + v)
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
