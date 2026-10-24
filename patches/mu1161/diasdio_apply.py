#!/usr/bin/env python3
"""Apply or revert the MU1367 / 791 AID 12.3 artifact fix on a CarPlay Maps VC payload.

The payload directory is the one that contains common/ and profiles/, for example:
  MU1367/791_AID12.3/payload                      (this repository)
  /Volumes/<SD>/Custom/carplay_maps_vc/payload    (MQB Toolbox SD card)
  /Volumes/<SD>/CarPlayMapsVC/payload             (M.I.B. MU1367_791 SD card)

Every file is checked against the known stock and patched SHA-256 before anything
is written. Unknown builds are refused and nothing is changed.
"""
import argparse
import hashlib
import pathlib
import sys

FILES = {
    "common/altscreen-most-bridge": {
        "stock": "c846e505da704f101815a4658f1b815930d0b6f779d435349b864ef96056c8f3",
        "patched": "fed7dce45f923384fec47861c448b753913f0561ed7e2a279860a5d13f8a44f4",
        # (file offset, stock bytes, patched bytes), ARM little-endian
        "edits": [
            # Queue flush only when no access unit is part-written (packet_pos == 0).
            (0x1B04, "0030a0e3", "1c6094e5"),  # mov r3,#0         -> ldr r6,[r4,#0x1c]
            (0x1B08, "1c3084e5", "000056e3"),  # str r3,[r4,#0x1c] -> cmp r6,#0
            (0x1B0C, "0c2084e5", "0c208405"),  # str r2,[r4,#0xc]  -> streq r2,[r4,#0xc]
            (0x1B10, "143084e5", "14608405"),  # str r3,[r4,#0x14] -> streq r6,[r4,#0x14]
            # Request a fresh IDR under congestion: drop the writer fast-streak > 7 condition.
            (0x4174, "07005383", "00005383"),  # cmphi r3,#7 -> cmphi r3,#0
        ],
    },
    "profiles/MU1367/791/core.so": {
        "stock": "00b48a8fe876e6ff405124b87ed9eace1bcb079220ff7f02b866f42676477a4a",
        "patched": "4e2777b2d06fec693235828ce31259230e33992a931bb6b0369545e8f9ee230f",
        "edits": [
            (0x2A70, "2820a0e3", "1e20a0e3"),  # maxFPS 40 -> 30
            (0x2B9C, "6e3fa0e3", "ae3100e3"),  # safeArea height: mov r3,#440 -> movw r3,#430
            (0x4370, "1420a0e3", "0520a0e3"),  # forced IDR every 20 -> 5 frames
            (0x452C, "1420a0e3", "0520a0e3"),  # same period, logged value
        ],
    },
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", type=pathlib.Path, help="payload directory containing common/ and profiles/")
    parser.add_argument("--revert", action="store_true", help="restore the stock bytes instead")
    args = parser.parse_args()

    source, target = ("patched", "stock") if args.revert else ("stock", "patched")
    pending = []
    for rel, spec in FILES.items():
        path = args.payload / rel
        if not path.is_file():
            sys.exit(f"missing: {path}")
        data = bytearray(path.read_bytes())
        digest = sha256(data)
        if digest == spec[target]:
            print(f"already {target}: {rel}")
            continue
        if digest != spec[source]:
            sys.exit(f"unknown build, nothing changed: {rel} ({digest})")
        for offset, stock, patched in spec["edits"]:
            old, new = bytes.fromhex(stock), bytes.fromhex(patched)
            if args.revert:
                old, new = new, old
            if data[offset:offset + len(old)] != old:
                sys.exit(f"unexpected bytes at {rel}+{offset:#x}, nothing changed")
            data[offset:offset + len(new)] = new
        if sha256(data) != spec[target]:
            sys.exit(f"result hash mismatch, nothing changed: {rel}")
        pending.append((path, rel, data))

    for path, rel, data in pending:
        path.write_bytes(data)
        print(f"{target}: {rel}")


if __name__ == "__main__":
    main()
