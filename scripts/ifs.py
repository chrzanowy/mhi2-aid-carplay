#!/usr/bin/env python3
"""Read-only reader for an uncompressed QNX imagefs (e.g. the output of lzoz.py).

  ifs.py ls      image.ifs
  ifs.py extract image.ifs out_dir

Directory entries follow the QNX image_dirent layout: attr (size u16, extattr u16,
ino, mode, gid, uid, mtime), then file (offset, size, path), symlink (sym_offset u16,
sym_size u16, path) or device (dev, rdev, path); offsets are relative to the image
header. Symlinks are written as <name>.symlink text files; paths are confined to out_dir.
"""
import os
import struct
import sys

S_IFMT, S_IFDIR, S_IFREG, S_IFLNK = 0o170000, 0o040000, 0o100000, 0o120000


def cstr(b, off):
    return b[off:b.index(b"\0", off)].decode("utf-8", "replace")


def entries(d):
    if d[:7] != b"imagefs":
        sys.exit("no imagefs header at offset 0")
    image_size, hdr_dir_size, dir_offset = struct.unpack_from("<III", d, 8)
    off = dir_offset
    while off < hdr_dir_size:
        size, _ext, ino, mode, gid, uid, mtime = struct.unpack_from("<HHIIIII", d, off)
        if size == 0:
            break
        body = off + 24
        t = mode & S_IFMT
        e = dict(mode=mode, mtime=mtime)
        if t == S_IFREG:
            e["offset"], e["size"] = struct.unpack_from("<II", d, body)
            e["path"] = cstr(d, body + 8)
        elif t == S_IFLNK:
            so, ss = struct.unpack_from("<HH", d, body)
            e["path"] = cstr(d, body + 4)
            e["target"] = d[body + 4 + so:body + 4 + so + ss].decode("utf-8", "replace")
        elif t == S_IFDIR:
            e["path"] = cstr(d, body)
        else:
            e["path"] = cstr(d, body + 8)
        yield e
        off += size


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("ls", "extract"):
        sys.exit(__doc__)
    d = open(sys.argv[2], "rb").read()
    if sys.argv[1] == "ls":
        for e in entries(d):
            t = {S_IFDIR: "d", S_IFREG: "f", S_IFLNK: "l"}.get(e["mode"] & S_IFMT, "?")
            print("%s %06o %10s %s%s" % (t, e["mode"] & 0o7777, e.get("size", ""), "/" + e["path"],
                                        " -> " + e["target"] if "target" in e else ""))
        return
    out = os.path.realpath(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    for e in entries(d):
        dst = os.path.realpath(os.path.join(out, e["path"]))
        if dst != out and not dst.startswith(out + os.sep):
            sys.exit("path escapes output: %r" % e["path"])
        t = e["mode"] & S_IFMT
        if t == S_IFDIR:
            os.makedirs(dst, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if t == S_IFREG:
            data = d[e["offset"]:e["offset"] + e["size"]]
            if len(data) != e["size"]:
                sys.exit("truncated file %s" % e["path"])
            with open(dst, "wb") as fh:
                fh.write(data)
            os.chmod(dst, 0o644)
        elif t == S_IFLNK:
            with open(dst + ".symlink", "w") as fh:
                fh.write(e["target"])


if __name__ == "__main__":
    main()
