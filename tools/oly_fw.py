#!/usr/bin/env python3
"""Olympus firmware container tool.

Currently understands the "OE" container seen in E-500 fw 1.3 (E0359999.BIN):
0x20-byte header, payload, 0x20-byte trailer that repeats header[0:0x1C] and
ends in a checksum u32. Field meanings are documented, with their confidence,
in the working notes.

Checksum: the trailer's last u32 makes the little-endian u32 sum of
header + DECODED payload + trailer equal 0 (firmware routine 0x40124F0B).

Payload obfuscation (E-500 fw 1.3): within each 16-byte block, bytes are
shuffled (cipher[j] = plain[PERM16[j]]) and every byte is inverted (XOR 0xFF).
"""
import argparse
import hashlib
import math
import struct
import sys
from collections import Counter

HDR_SIZE = 0x20
MAGIC = b"OE"
# cipher byte j of each 16-byte block holds plain byte PERM16[j]
PERM16 = (2, 0, 3, 1, 5, 7, 4, 6, 11, 10, 9, 8, 14, 12, 13, 15)
INV16 = tuple(PERM16.index(i) for i in range(16))
NOT = bytes(i ^ 0xFF for i in range(256))
FIELDS = ("magic", "f04", "base_addr", "payload_len", "version?", "f14", "f18", "checksum")


def read_checked(path, sha256, what):
    """Read a firmware file and exit unless its SHA-256 is the one a patch was made for."""
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        sys.exit(f"error: {e}")
    have = hashlib.sha256(raw).hexdigest()
    if have != sha256:
        sys.exit(f"error: {path} is not {what}\n  sha256 {have}\n  need   {sha256}")
    return raw


def parse(data):
    if data[:2] != MAGIC:
        raise ValueError(f"bad magic {data[:4].hex()}")
    hdr = struct.unpack_from("<8I", data, 0)
    plen = hdr[3]
    trailer_off = HDR_SIZE + plen
    if trailer_off + HDR_SIZE != len(data):
        raise ValueError(f"payload_len 0x{plen:x} inconsistent with file size 0x{len(data):x}")
    trl = struct.unpack_from("<8I", data, trailer_off)
    return hdr, trl, data[HDR_SIZE:trailer_off]


def _shuffle(data, perm):
    if len(data) % 16:
        raise ValueError(f"payload length 0x{len(data):x} not a multiple of 16")
    out = bytearray(len(data))
    for i, src in enumerate(perm):
        out[i::16] = data[src::16]
    return bytes(out)


def decode(payload):
    return _shuffle(payload, INV16).translate(NOT)


def encode(plain):
    return _shuffle(plain.translate(NOT), PERM16)


def u32_sum(b):
    return sum(struct.unpack(f"<{len(b) // 4}I", b)) & 0xFFFFFFFF


def checksum(header, plain, trailer):
    """Value for the trailer's last u32 that makes the plaintext container sum to 0."""
    return -u32_sum(header + plain + trailer[:HDR_SIZE - 4]) & 0xFFFFFFFF


def entropy(b):
    n = len(b)
    return -sum(c / n * math.log2(c / n) for c in Counter(b).values()) if n else 0.0


def cmd_info(args):
    data = open(args.file, "rb").read()
    print(f"file    {args.file}")
    print(f"size    {len(data)} (0x{len(data):x})")
    print(f"sha256  {hashlib.sha256(data).hexdigest()}")
    hdr, trl, payload = parse(data)
    print(f"{'field':<12} {'header':>10} {'trailer':>10}")
    for i, name in enumerate(FIELDS):
        mark = "" if hdr[i] == trl[i] else "  <- differs"
        print(f"{name:<12} 0x{hdr[i]:08x} 0x{trl[i]:08x}{mark}")
    trailer = data[HDR_SIZE + len(payload):]
    want = checksum(data[:HDR_SIZE], decode(payload), trailer)
    print(f"checksum     {'OK' if want == trl[7] else f'BAD (expected 0x{want:08x})'}")
    if args.entropy:
        win = args.entropy
        for off in range(0, len(payload), win):
            print(f"  payload+0x{off:07x}  H={entropy(payload[off:off + win]):.3f}")


def cmd_extract(args):
    data = open(args.file, "rb").read()
    _, _, payload = parse(data)
    with open(args.out, "wb") as f:
        f.write(payload)
    print(f"wrote {len(payload)} bytes to {args.out}")


def cmd_decode(args):
    data = open(args.file, "rb").read()
    _, _, payload = parse(data)
    plain = decode(payload)
    if encode(plain) != payload:
        sys.exit("error: decode/encode round-trip mismatch")
    with open(args.out, "wb") as f:
        f.write(plain)
    print(f"wrote {len(plain)} decoded bytes to {args.out} (round-trip verified)")


def cmd_encode(args):
    """Re-wrap a decoded payload using the header/trailer of a reference file."""
    ref = open(args.ref, "rb").read()
    hdr, trl, payload = parse(ref)
    plain = open(args.plain, "rb").read()
    if len(plain) != len(payload):
        sys.exit("error: decoded size differs from reference payload size")
    header = ref[:HDR_SIZE]
    trailer = ref[HDR_SIZE + len(payload):HDR_SIZE + len(payload) + HDR_SIZE - 4]
    trailer += struct.pack("<I", checksum(header, plain, trailer))
    out = header + encode(plain) + trailer
    with open(args.out, "wb") as f:
        f.write(out)
    same = "IDENTICAL to" if out == ref else "differs from"
    print(f"wrote {args.out}; checksum recomputed; {same} reference")
    print(f"sha256  {hashlib.sha256(out).hexdigest()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info", help="print container fields")
    p.add_argument("file")
    p.add_argument("--entropy", type=lambda s: int(s, 0), metavar="WINDOW",
                   help="also print payload entropy per WINDOW bytes (e.g. 0x80000)")
    p.set_defaults(func=cmd_info)
    p = sub.add_parser("extract", help="write raw (still obfuscated) payload")
    p.add_argument("file")
    p.add_argument("out")
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("decode", help="write deobfuscated payload")
    p.add_argument("file")
    p.add_argument("out")
    p.set_defaults(func=cmd_decode)
    p = sub.add_parser("encode", help="re-obfuscate a decoded payload into a container")
    p.add_argument("ref", help="original firmware file (header/trailer source)")
    p.add_argument("plain", help="decoded payload")
    p.add_argument("out")
    p.set_defaults(func=cmd_encode)
    args = ap.parse_args()
    try:
        args.func(args)
    except ValueError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
