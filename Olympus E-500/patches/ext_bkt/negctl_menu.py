#!/usr/bin/env python3
"""Negative controls for the preset menu checks: inject known bugs; each must fail the build.

  python3 negctl_menu.py <stock.BIN>
Mutates menu.S, menu_data.py, m_tv_ref.S and skip.S (n_eff guard) one at a time, runs the
build's edits and checks (skip.S tests in quick mode), and restores every file afterwards.
Exit status 0 only if every injected bug was caught.
"""
import argparse
import importlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "tools"))
import build  # noqa: E402
import menu_data  # noqa: E402
import mn103_sim  # noqa: E402
import oly_fw  # noqa: E402

MUTATIONS = {
    "res: range test inverted": ("menu.S", "        bcc     rh_none                 # not ours",
                                 "        bcs     rh_none                 # not ours"),
    "res: one id too many": ("menu.S", "        cmp     EXT_RES_N,d1", "        cmp     EXT_RES_N+1,d1"),
    "lay: lower bound": ("menu.S", "        cmp     EXT_LAY,d1\n        bcs     lh_stock",
                         "        cmp     EXT_LAY+1,d1\n        bcs     lh_stock"),
    "validator: preset as 3": ("menu.S", "        mov     5,d0\n        ret     [d2,d3],12\nvn_stock:",
                               "        mov     3,d0\n        ret     [d2,d3],12\nvn_stock:"),
    "fmt: tens digit": ("menu.S", "        add     0x30,d0\n        mov     d0,d1",
                        "        add     0x31,d0\n        mov     d0,d1"),
    "labels in the wrong rows": ("menu_data.py", "    rids = stock_rids + res_ids\n",
                                 "    rids = stock_rids + res_ids[::-1]\n"),
    "code collides with stock": ("menu_data.py", "FIRST_CODE = 12 ", "FIRST_CODE = 11 "),
    "value display: one layout": ("menu_data.py", "        disp_tab += struct.pack(\"<3I\", 1, code, lid)",
                                  "        disp_tab += struct.pack(\"<3I\", 1, code, lay_value[0])"),
    "grid columns overlap": ("menu_data.py", "COL_X, BTN_W, ROW_Y, ROW_PITCH, ROWS = (2, 106, 210),",
                             "COL_X, BTN_W, ROW_Y, ROW_PITCH, ROWS = (2, 100, 210),"),
    "button style not narrowed": ("menu_data.py", "            set16(r, 8, w - d)", "            set16(r, 8, w)"),
    "M dial: preset test inverted": ("m_tv_ref.S", "        cmp     -1,d0\n        beq     stock",
                                     "        cmp     -1,d0\n        bne     stock"),
    "n_eff: limit can be 0": ("skip.S", "        bgt     ne_ret", "        bge     ne_ret"),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stock")
    args = ap.parse_args()
    plain = oly_fw.decode(oly_fw.parse(open(args.stock, "rb").read())[2])
    presets = build.parse_presets(build.DEFAULT_PRESETS)
    files = sorted({f for f, _, _ in MUTATIONS.values()})
    missed = 0
    with tempfile.TemporaryDirectory() as t:
        for f in files:
            shutil.copy(os.path.join(HERE, f), os.path.join(t, f))
        try:
            for name, (f, a, b) in MUTATIONS.items():
                path = os.path.join(HERE, f)
                src = open(os.path.join(t, f)).read()
                if src.count(a) != 1:
                    sys.exit(f"error: mutation '{name}' no longer matches {f}")
                open(path, "w").write(src.replace(a, b))
                importlib.reload(menu_data)
                try:
                    build.build_edits(plain, presets, cont=False, quick=True)
                    print("NOT CAUGHT:", name)
                    missed += 1
                except (AssertionError, ValueError, mn103_sim.Unknown) as e:
                    print("caught:", name, "->", str(e.args[0])[:60] if e.args else e)
                finally:
                    shutil.copy(os.path.join(t, f), path)
        finally:
            for f in files:
                shutil.copy(os.path.join(t, f), os.path.join(HERE, f))
            importlib.reload(menu_data)
    print("RESULT:", "all injected bugs caught" if not missed else f"{missed} NOT caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
