#!/usr/bin/env python3
"""Make the modified E-500 firmware (ext_bkt) from your own copy of the official firmware 1.3.

  python3 make_firmware.py E0359999.BIN E0359999-ext_bkt.BIN                  # default build (Python only)
  python3 make_firmware.py E0359999.BIN OUT.BIN --presets -2:2,-4:4,-6:6      # own presets (needs binutils)

Steps: check the input file by SHA-256, take the patch (the shipped patches/ext_bkt/patch.json,
or one built from the sources for --presets / --no-cont-resume / --rebuild), apply it with
tools/oly_patch.py, then check the result with tools/oly_diffcheck.py (an independent decoder:
only the declared bytes may differ). The default build must reproduce, bit for bit, the file
the author flashed and tested (REFERENCE_SHA256).
Building from the sources needs mn10300-linux-gnu-{as,ld,objcopy,nm,objdump} (binutils for
MN10300) and runs the offline verifiers (about a minute).
Read docs/safety.md before flashing: no recovery path is known if a flash goes wrong.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")
sys.path.insert(0, TOOLS)
import oly_fw  # noqa: E402

FIRMWARE = "E0359999.BIN"
FW_SHA256 = "e9f5431cb47bf1c73395337256fba6eedf576c03b06c4ef7dea0d387ca7c69ae"
PATCH = os.path.join(HERE, "patches", "ext_bkt", "patch.json")
BUILD = os.path.join(HERE, "patches", "ext_bkt", "build.py")
# ext_bkt r5 with the default options: flashed by the author on 2026-11-19 and working
REFERENCE = "r5"
REFERENCE_SHA256 = "f03a644c5fa8cb497071c0638de469900a646766b47d84f45e016f17b2e85cc3"
BINUTILS = ("as", "ld", "objcopy", "nm", "objdump")


def run(argv):
    r = subprocess.run([sys.executable] + argv)
    if r.returncode:
        sys.exit(f"error: {os.path.basename(argv[0])} failed (exit {r.returncode})")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("firmware", help=f"official E-500 firmware 1.3 ({FIRMWARE})")
    ap.add_argument("out", help="modified firmware file to write")
    ap.add_argument("--presets", help="BOTTOM:TOP in EV, comma-separated (see patches/ext_bkt/README.md); "
                                      "builds from the sources")
    ap.add_argument("--no-cont-resume", action="store_true",
                    help="leave out cont_resume (stock stop when the buffer fills); builds from the sources")
    ap.add_argument("--rebuild", action="store_true",
                    help="build the default patch from the sources too, and check it equals the shipped one")
    args = ap.parse_args()

    oly_fw.read_checked(args.firmware, FW_SHA256, f"E-500 firmware 1.3 ({FIRMWARE})")
    if os.path.exists(args.out) and os.path.samefile(args.firmware, args.out):
        sys.exit("error: the output would overwrite the input firmware")
    custom = args.presets is not None or args.no_cont_resume

    with tempfile.TemporaryDirectory() as tmp:
        patch = PATCH
        if custom or args.rebuild:
            missing = [t for t in BINUTILS if not shutil.which(f"mn10300-linux-gnu-{t}")]
            if missing:
                sys.exit("error: building from the sources needs binutils for MN10300; not found: "
                         + ", ".join(f"mn10300-linux-gnu-{t}" for t in missing))
            patch = os.path.join(tmp, "patch.json")
            run([BUILD, args.firmware, "--out", patch]
                + (["--presets", args.presets] if args.presets is not None else [])
                + (["--no-cont-resume"] if args.no_cont_resume else []))
            if not custom:
                if json.load(open(patch))["edits"] != json.load(open(PATCH))["edits"]:
                    sys.exit(f"error: the rebuilt patch differs from the shipped {PATCH}")
                print("rebuilt patch: identical edits to the shipped patch.json")
        run([os.path.join(TOOLS, "oly_patch.py"), args.firmware, patch, args.out])
        run([os.path.join(TOOLS, "oly_diffcheck.py"), args.firmware, args.out, patch])
        if custom:
            json_out = os.path.splitext(args.out)[0] + ".patch.json"
            shutil.copyfile(patch, json_out)

    sha = hashlib.sha256(open(args.out, "rb").read()).hexdigest()
    print()
    if custom:
        print(f"{args.out}: custom build, sha256 {sha}")
        print(f"  its patch definition: {json_out}")
        print("  Custom builds are verified offline but have not been tested on a camera.")
    elif sha == REFERENCE_SHA256:
        print(f"{args.out}: identical to ext_bkt {REFERENCE}, the build the author flashed and tested (sha256 {sha})")
    else:
        sys.exit(f"error: {args.out} sha256 {sha} is not the reference {REFERENCE_SHA256}")
    print("Before flashing, read docs/safety.md. You flash at your own risk.")


if __name__ == "__main__":
    main()
