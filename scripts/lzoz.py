#!/usr/bin/env python3
"""Unpack an eso LZOZ container (MMX2 mifs-stage2.img) into the raw QNX imagefs.

  lzoz.py mifs-stage2.img out.ifs

Format per maxim-smirnov/mhi2-carplay-cluster docs/reference/MHI2_MU1439_PORT.md:
"LZOZ", u32 block size (2 MiB), u32 compressed length per block until 0, data from
0x800 with every block padded to 512 bytes. Algorithm lzo1z; block 0 is decoded on
its own, every later block uses block 0's output as preset dictionary.
Needs liblzo2 (brew install lzo).
"""
import ctypes
import ctypes.util
import struct
import sys

LIB_PATHS = ["/opt/homebrew/lib/liblzo2.2.dylib", "/usr/local/lib/liblzo2.2.dylib",
             ctypes.util.find_library("lzo2")]


def load():
    for p in LIB_PATHS:
        if p:
            try:
                return ctypes.CDLL(p)
            except OSError:
                pass
    sys.exit("liblzo2 not found")


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    d = open(sys.argv[1], "rb").read()
    if d[:4] != b"LZOZ":
        sys.exit("not an LZOZ container")
    bs = struct.unpack_from("<I", d, 4)[0]
    sizes = []
    off = 8
    while off < 0x800:
        (n,) = struct.unpack_from("<I", d, off)
        if n == 0:
            break
        sizes.append(n)
        off += 4
    lzo = load()
    wrk = ctypes.create_string_buffer(1 << 16)
    out = []
    pos = 0x800
    dict0 = None
    for i, n in enumerate(sizes):
        src = d[pos:pos + n]
        if len(src) != n:
            sys.exit("block %d truncated" % i)
        dst = ctypes.create_string_buffer(bs)
        dlen = ctypes.c_size_t(bs)
        if i == 0:
            rc = lzo.lzo1z_decompress_safe(src, ctypes.c_size_t(n), dst, ctypes.byref(dlen), wrk)
        else:
            rc = lzo.lzo1z_decompress_dict_safe(src, ctypes.c_size_t(n), dst, ctypes.byref(dlen), wrk,
                                                dict0, ctypes.c_size_t(len(dict0)))
        if rc != 0:
            sys.exit("block %d: lzo error %d" % (i, rc))
        block = dst.raw[:dlen.value]
        if i == 0:
            dict0 = block
        out.append(block)
        pos += (n + 0x1FF) & ~0x1FF
    data = b"".join(out)
    open(sys.argv[2], "wb").write(data)
    print("blocks %d, out %d bytes, container data ends at 0x%x of 0x%x" % (len(sizes), len(data), pos, len(d)))


if __name__ == "__main__":
    main()
