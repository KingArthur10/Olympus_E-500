#!/usr/bin/env python3
"""Copy the repository into a new directory for public release, without vendor firmware.

  tools/export_public.py <dest_dir>

Copies the git-tracked files of HEAD's working tree (so nothing gitignored, like work/, and
nothing uncommitted is included), except:
  * anything under a `Firmware v*/` or `firmware v*/` directory (the official vendor files)
  * any file with a firmware extension (.bin, .fir, .zip) or that is a Git LFS pointer
  * the working notes: every CLAUDE.md and every `notes/` directory (owner decision, 2026-11-19)
  * .gitattributes (its only job here is putting the firmware in LFS)
In Markdown files, text between `<!-- private -->` and `<!-- /private -->` is removed (on one line,
or as whole marker lines around a block). Adds ignore rules for firmware files to .gitignore, so a
user's own copy is never committed.
Refuses to run with uncommitted changes, or into a non-empty directory or one inside this repo.
Fails (exit 1) if a copied file is larger than MAX_BYTES (a guard against stray images), or if a
Markdown link in the export points to a file that isn't in it.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

FIRMWARE_DIR = re.compile(r"(^|/)firmware v[^/]*/", re.IGNORECASE)
FIRMWARE_EXT = (".bin", ".fir", ".zip")
NOTES = re.compile(r"(^|/)notes/|(^|/)CLAUDE\.md$")
DROP = {".gitattributes"}
PRIVATE_INLINE = re.compile(r"<!-- private -->.*?<!-- /private -->")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")
MAX_BYTES = 1 << 20
IGNORE_FIRMWARE = """
# Vendor firmware is not distributed: use your own copy, anywhere outside the repo or here.
*.BIN
*.bin
*.FIR
*.fir
Firmware v*/
firmware v*/
"""


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args), check=True, capture_output=True, text=True).stdout


def strip_private(text):
    """Remove <!-- private --> ... <!-- /private --> blocks (whole marker lines) and inline spans."""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        mark = line.strip()
        if mark == "<!-- private -->":
            skip = True
        elif mark == "<!-- /private -->":
            if not skip:
                raise ValueError("unmatched <!-- /private -->")
            skip = False
        elif not skip:
            out.append(PRIVATE_INLINE.sub("", line))
    if skip:
        raise ValueError("unterminated <!-- private --> block")
    text = "".join(out)
    if "<!-- private -->" in text or "<!-- /private -->" in text:
        raise ValueError("a private marker is left over (inline spans must open and close on one line)")
    return text


def broken_links(dest, md):
    """Relative Markdown link targets in dest/md that don't exist in the export."""
    text = open(os.path.join(dest, md), encoding="utf-8").read()
    bad = []
    for target in MD_LINK.findall(text):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = urllib.parse.unquote(target.split("#")[0])
        if not os.path.exists(os.path.normpath(os.path.join(dest, os.path.dirname(md), path))):
            bad.append(f"{md}: {target}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dest")
    args = ap.parse_args()
    root = git(os.path.dirname(os.path.abspath(__file__)), "rev-parse", "--show-toplevel").strip()
    dest = os.path.abspath(args.dest)
    if os.path.commonpath([root, dest]) == root:
        sys.exit("error: the destination is inside this repository")
    if os.path.exists(dest) and os.listdir(dest):
        sys.exit("error: the destination is not empty")
    if git(root, "status", "--porcelain"):
        sys.exit("error: uncommitted changes; commit first so the export matches HEAD")

    files = [f for f in git(root, "ls-files", "-z").split("\0") if f]
    copied, dropped, big = [], [], []
    for f in files:
        src = os.path.join(root, f)
        with open(src, "rb") as fh:
            lfs = fh.read(40).startswith(b"version https://git-lfs")
        if FIRMWARE_DIR.search(f) or f.lower().endswith(FIRMWARE_EXT) or lfs or NOTES.search(f) or f in DROP:
            dropped.append(f)
            continue
        if os.path.getsize(src) > MAX_BYTES:
            big.append(f)
        out = os.path.join(dest, f)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if f.endswith(".md"):
            try:
                text = strip_private(open(src, encoding="utf-8").read())
            except ValueError as e:
                sys.exit(f"error: {f}: {e}")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write(text)
            shutil.copystat(src, out)
        else:
            shutil.copy2(src, out)
        copied.append(f)
    with open(os.path.join(dest, ".gitignore"), "a") as fh:
        fh.write(IGNORE_FIRMWARE)

    for f in dropped:
        if not NOTES.search(f):
            print(f"left out  {f}")
    notes = sum(1 for f in dropped if NOTES.search(f))
    print(f"left out  {notes} working-note files (CLAUDE.md, notes/)")
    print(f"copied {len(copied)} files to {dest} (from {git(root, 'rev-parse', '--short', 'HEAD').strip()}); "
          f"left out {len(dropped)}")
    bad = [b for f in copied if f.endswith(".md") for b in broken_links(dest, f)]
    for b in bad:
        print(f"broken link  {b}")
    if big:
        print("error: files over 1 MiB were copied, check them: " + ", ".join(big))
    if big or bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
