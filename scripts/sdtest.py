#!/usr/bin/env python3
"""Fill an SD card with deterministic pseudo-random files, then verify them (like H2testw/f3).

  sdtest.py write  /Volumes/MIB   # fills free space with 1 GiB files (last one partial)
  sdtest.py verify /Volumes/MIB   # re-reads and compares; run after unmount/remount

Each 1 MiB block is generated from (file index, block index), so verification needs no
stored copy and detects fake capacity (wrap-around), bad sectors and silent corruption.
"""
import os
import random
import shutil
import sys
import time

BLOCK = 1 << 20
FILE_BLOCKS = 1024
RESERVE = 16 * BLOCK
PREFIX = "sdtest_"


def block(f, b):
    return random.Random(f * 1000003 + b).randbytes(BLOCK)


def write(root):
    total = 0
    t0 = time.time()
    f = 0
    while True:
        free = shutil.disk_usage(root).free - RESERVE
        n = min(FILE_BLOCKS, free // BLOCK)
        if n <= 0:
            break
        path = os.path.join(root, "%s%03d.bin" % (PREFIX, f))
        with open(path, "wb") as fh:
            for b in range(n):
                fh.write(block(f, b))
            fh.flush()
            os.fsync(fh.fileno())
        total += n
        print("wrote %s %4d MiB  total %.1f GiB  %.1f MB/s" % (
            os.path.basename(path), n, total / 1024, total * BLOCK / 1e6 / (time.time() - t0)), flush=True)
        f += 1
    print("WRITE_DONE files=%d MiB=%d" % (f, total))


def verify(root):
    names = sorted(n for n in os.listdir(root) if n.startswith(PREFIX))
    bad = 0
    total = 0
    t0 = time.time()
    for name in names:
        f = int(name[len(PREFIX):-4])
        with open(os.path.join(root, name), "rb") as fh:
            b = 0
            while True:
                data = fh.read(BLOCK)
                if not data:
                    break
                if data != block(f, b)[:len(data)]:
                    bad += 1
                    print("MISMATCH %s block %d" % (name, b), flush=True)
                b += 1
                total += 1
        print("verified %s  total %.1f GiB  %.1f MB/s  bad=%d" % (
            name, total / 1024, total * BLOCK / 1e6 / (time.time() - t0), bad), flush=True)
    print("VERIFY_%s files=%d MiB=%d bad_blocks=%d" % ("OK" if bad == 0 and names else "FAIL", len(names), total, bad))
    sys.exit(0 if bad == 0 and names else 1)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("write", "verify"):
        sys.exit(__doc__)
    {"write": write, "verify": verify}[sys.argv[1]](sys.argv[2])
