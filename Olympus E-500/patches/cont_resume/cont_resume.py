#!/usr/bin/env python3
"""Generate the cont_resume patch (E-500 fw 1.3): keep shooting past a full buffer.

  python3 cont_resume.py E0359999.BIN [--out patch.json]

Stock: when the buffer fills, the trigger parks in TAKE_READY2 and resumes only on a
*fresh* full press (flag 0xB00F6725 == 1). cont_resume also resumes while the full
press is still held from the burst (6725 == 2), in continuous drive only, for plain
bursts and for unfinished AE brackets. Everything else is stock.
ext_bkt/build.py includes these edits by default; this script builds them alone.
Requires mn10300-linux-gnu-{as,ld,objcopy}.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, HERE)
import oly_fw  # noqa: E402
import verify_cont_resume  # noqa: E402

FIRMWARE = "E0359999.BIN"              # official E-500 firmware 1.3 (input file name)
FW_SHA256 = "e9f5431cb47bf1c73395337256fba6eedf576c03b06c4ef7dea0d387ca7c69ae"
BASE = 0x40030020

SITE = 0x400A30F7       # trig_can_resume: `6725 == 1` and `6736 == 1` checks (20 bytes)
SITE_ORIG = "fca825670fb0a001c970fca836670fb0a001c966"
FAIL = 0x400A316F       # trig_can_resume: `clr d0; ret [],4`
HELPER = 0x406F6A00     # image tail free space (0xFF to 0x4071FFE0, no references)
HELPER_MAX = 0x100
SETTING_GET = 0x400394A7


def link(src, addr, syms):
    with tempfile.TemporaryDirectory() as t:
        o, elf, bin_ = (os.path.join(t, x) for x in ("x.o", "x.elf", "x.bin"))
        subprocess.run(["mn10300-linux-gnu-as", "-o", o, os.path.join(HERE, src)], check=True)
        subprocess.run(["mn10300-linux-gnu-ld", f"-Ttext=0x{addr:x}", "-e", "0", "-o", elf, o]
                       + [f"--defsym={k}=0x{v:x}" for k, v in syms.items()], check=True)
        subprocess.run(["mn10300-linux-gnu-objcopy", "-O", "binary", "-j", ".text", elf, bin_], check=True)
        return open(bin_, "rb").read()


def build_edits(plain):
    """Return [(addr, orig, new, why)] for a decoded stock image; exit on any surprise."""
    at = lambda a, k: plain[a - BASE:a - BASE + k]  # noqa: E731
    helper = link("cont_resume.S", HELPER, {"setting_get_addr": SETTING_GET})
    site = link("site.S", SITE, {"helper_addr": HELPER, "fail_addr": FAIL})
    if len(site) != 20:
        sys.exit(f"error: site code is {len(site)} bytes (need 20)")
    if len(helper) > HELPER_MAX:
        sys.exit(f"error: helper is {len(helper)} bytes (> {HELPER_MAX})")
    if at(SITE, 20).hex() != SITE_ORIG:
        sys.exit(f"error: unexpected bytes at 0x{SITE:08x}: {at(SITE, 20).hex()}")
    if at(HELPER, HELPER_MAX) != b"\xff" * HELPER_MAX:
        sys.exit(f"error: free space at 0x{HELPER:08x} is not 0xFF")
    patched = bytearray(plain)
    patched[SITE - BASE:SITE - BASE + 20] = site
    patched[HELPER - BASE:HELPER - BASE + len(helper)] = helper
    cases = verify_cont_resume.verify(bytes(plain), bytes(patched), quiet=True)
    return [
        (SITE, at(SITE, 20), site,
         f"trig_can_resume: shutter/ready checks -> call cont_resume_ok (verified: {cases} cases)"),
        (HELPER, at(HELPER, len(helper)), helper,
         "cont_resume_ok (free space): stock checks, plus resume while full press held in continuous drive"),
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("firmware", help=f"stock E-500 firmware 1.3 ({FIRMWARE}, checked by SHA-256)")
    ap.add_argument("--out", default=os.path.join(HERE, "patch.json"))
    args = ap.parse_args()
    raw = oly_fw.read_checked(args.firmware, FW_SHA256, f"E-500 firmware 1.3 ({FIRMWARE})")
    _, _, payload = oly_fw.parse(raw)
    edits = build_edits(oly_fw.decode(payload))
    spec = {
        "name": "cont_resume",
        "description": "E-500 fw 1.3: in continuous drive, keep shooting while the shutter stays fully "
                       "pressed after the buffer fills (stock needs a re-press). Single drive unchanged.",
        "firmware": FIRMWARE,
        "firmware_sha256": FW_SHA256,
        "base": f"0x{BASE:08x}",
        "edits": [{"addr": f"0x{a:08x}", "orig": o.hex(), "new": w.hex(), "why": why}
                  for a, o, w, why in edits],
    }
    with open(args.out, "w") as f:
        json.dump(spec, f, indent=2)
        f.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
