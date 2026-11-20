#!/usr/bin/env python3
"""Negative controls for verify_skip.py: inject known bugs into skip.S; each must fail the build's checks.

  python3 negctl_skip.py <stock.BIN>
Restores skip.S afterwards. Exit status 0 only if every injected bug was caught.
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
import build  # noqa: E402
import oly_fw  # noqa: E402
import verify_skip  # noqa: E402

MUTATIONS = {
    "A limits lo/hi swapped": ("LIMITS  6, 36, 6, 34", "LIMITS  6, 34, 6, 36"),
    "scan start sign": ("        mul     d1,d0\n        add     d0,d2                   # value_0",
                        "        mul     d1,d0\n        sub     d0,d2                   # value_0"),
    "no re-prep": ("        cmp     d0,d2\n        beq     ph_store\n        mov     (8,sp),a0",
                   "        cmp     d0,d2\n        bra     ph_store\n        mov     (8,sp),a0"),
    "n_eff no latch": ("        mov     1,d3\n        movbu   d3,(LT)", "        mov     0,d3\n        movbu   d3,(LT)"),
    "counter uses WP": ("        call    latched_get,[d2,d3],12  # d1 = C", "        call    wp_get,[d2,d3],12  # d1 = C"),
    "stock path bge": ("        cmp     0,d1\n        bgt     bo_scale", "        cmp     0,d1\n        bge     bo_scale"),
    "no TAKE_READY2 freeze": ("ph_not2:\n        cmp     3,d0", "ph_not2:\n        cmp     99,d0"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock")
    args = ap.parse_args()
    plain = oly_fw.decode(oly_fw.parse(open(args.stock, "rb").read())[2])
    path = os.path.join(HERE, "skip.S")
    src = open(path).read()
    missed = 0
    with tempfile.TemporaryDirectory() as t:
        shutil.copy(path, os.path.join(t, "skip.S"))
        try:
            for name, (a, b) in MUTATIONS.items():
                if src.count(a) != 1:
                    sys.exit(f"error: mutation '{name}' no longer matches skip.S")
                open(path, "w").write(src.replace(a, b))
                try:
                    build.skip_edits(plain, build.parse_presets(build.DEFAULT_PRESETS), quick=True)
                    print("NOT CAUGHT:", name)
                    missed += 1
                except (AssertionError, verify_skip.mn103_sim.Unknown) as e:
                    print("caught:", name, "->", str(e.args[0])[:50] if e.args else e)
        finally:
            shutil.copy(os.path.join(t, "skip.S"), path)
    print("RESULT:", "all injected bugs caught" if not missed else f"{missed} NOT caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
