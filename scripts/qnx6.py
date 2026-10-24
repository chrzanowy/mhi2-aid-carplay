#!/usr/bin/env python3
"""Read-only QNX6 (Power-Safe) filesystem reader for MIB2 images such as app.img.

  qnx6.py info    image.img
  qnx6.py ls      image.img            # every path with type and size
  qnx6.py extract image.img out_dir    # regular files, directories and symlinks

Layout follows the Linux qnx6 driver: optional 0x2000 boot area, superblock area
of 0x1000, block numbers relative to the end of the first superblock area,
inodes of 128 bytes in the inode file, 32-byte directory entries, names longer
than 27 bytes stored in the long-filename file. Symlinks are written as text
files named <name>.symlink so nothing outside out_dir can be touched.
"""
import os
import struct
import sys

MAGIC = 0x68191122
SB_AREA = 0x1000
PTRS = 16
S_IFMT, S_IFDIR, S_IFREG, S_IFLNK = 0o170000, 0o040000, 0o100000, 0o120000


class Fs:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.size = os.fstat(self.f.fileno()).st_size
        sbs = []
        for off in (0, 0x2000):
            if self.read(off, 4) == struct.pack("<I", MAGIC):
                sbs.append(off)
        if not sbs:
            sys.exit("no QNX6 superblock at 0x0 or 0x2000")
        self.sb_off = sbs[-1] if len(sbs) > 1 else sbs[0]
        sb = self.read(self.sb_off, 512)
        (self.serial,) = struct.unpack_from("<Q", sb, 8)
        (self.blocksize, self.num_inodes, self.free_inodes, self.num_blocks,
         self.free_blocks) = struct.unpack_from("<5I", sb, 48)
        self.data_off = self.sb_off + SB_AREA
        # The backup superblock at the end may be newer; prefer the higher serial.
        end_sb = self.data_off + self.num_blocks * self.blocksize
        if end_sb + 512 <= self.size and self.read(end_sb, 4) == struct.pack("<I", MAGIC):
            sb2 = self.read(end_sb, 512)
            if struct.unpack_from("<Q", sb2, 8)[0] > self.serial:
                sb = sb2
                (self.serial,) = struct.unpack_from("<Q", sb, 8)
        self.inode_root = self.root_node(sb, 72)
        self.longfile_root = self.root_node(sb, 232)
        self.ppb = self.blocksize // 4

    def read(self, off, n):
        self.f.seek(off)
        return self.f.read(n)

    def block(self, n):
        return self.read(self.data_off + n * self.blocksize, self.blocksize)

    @staticmethod
    def root_node(b, off):
        size = struct.unpack_from("<Q", b, off)[0]
        ptrs = struct.unpack_from("<16I", b, off + 8)
        levels = b[off + 72]
        return size, ptrs, levels

    def blocks(self, ptrs, levels, count):
        """Yield the first `count` data block numbers of a pointer tree."""
        out = []

        def walk(ptr, level):
            if len(out) >= count or ptr == 0xFFFFFFFF:
                return
            if level == 0:
                out.append(ptr)
                return
            for p in struct.unpack("<%dI" % self.ppb, self.block(ptr)):
                if len(out) >= count:
                    return
                walk(p, level - 1)

        for p in ptrs:
            walk(p, levels)
            if len(out) >= count:
                break
        return out

    def data(self, size, ptrs, levels):
        n = (size + self.blocksize - 1) // self.blocksize
        bl = self.blocks(ptrs, levels, n)
        if len(bl) < n:
            raise ValueError("short pointer tree")
        return b"".join(self.block(b) for b in bl)[:size]

    def chunks(self, size, ptrs, levels):
        n = (size + self.blocksize - 1) // self.blocksize
        left = size
        for b in self.blocks(ptrs, levels, n):
            d = self.block(b)[:left]
            left -= len(d)
            yield d

    def inode(self, ino):
        off = (ino - 1) * 128
        bs = self.blocksize
        bl = self.blocks(self.inode_root[1], self.inode_root[2], off // bs + 1)
        raw = self.block(bl[off // bs])[off % bs:off % bs + 128]
        size = struct.unpack_from("<Q", raw, 0)[0]
        mode = struct.unpack_from("<H", raw, 32)[0]
        mtime = struct.unpack_from("<I", raw, 20)[0]
        ptrs = struct.unpack_from("<16I", raw, 36)
        levels = raw[100]
        return dict(size=size, mode=mode, mtime=mtime, ptrs=ptrs, levels=levels)

    def longname(self, idx):
        bl = self.blocks(self.longfile_root[1], self.longfile_root[2], idx + 1)
        b = self.block(bl[idx])
        n = struct.unpack_from("<H", b, 0)[0]
        return b[2:2 + n]

    def listdir(self, ino):
        node = self.inode(ino)
        d = self.data(node["size"], node["ptrs"], node["levels"])
        for i in range(0, len(d), 32):
            child, nlen = struct.unpack_from("<IB", d, i)
            if child == 0:
                continue
            if nlen <= 27:
                name = d[i + 5:i + 5 + nlen]
            else:
                name = self.longname(struct.unpack_from("<I", d, i + 8)[0])
            if name in (b".", b".."):
                continue
            yield name.decode("utf-8", "replace"), child

    def walk(self, ino=1, prefix=""):
        for name, child in sorted(self.listdir(ino)):
            if "/" in name or name in ("", ".", ".."):
                raise ValueError("bad name %r" % name)
            node = self.inode(child)
            path = prefix + "/" + name
            yield path, child, node
            if node["mode"] & S_IFMT == S_IFDIR:
                yield from self.walk(child, path)


def kind(mode):
    return {S_IFDIR: "d", S_IFREG: "f", S_IFLNK: "l"}.get(mode & S_IFMT, "?")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("info", "ls", "extract"):
        sys.exit(__doc__)
    fs = Fs(sys.argv[2])
    if sys.argv[1] == "info":
        print("superblock 0x%x serial %d blocksize %d blocks %d (free %d) inodes %d (free %d)"
              % (fs.sb_off, fs.serial, fs.blocksize, fs.num_blocks, fs.free_blocks,
                 fs.num_inodes, fs.free_inodes))
        return
    if sys.argv[1] == "ls":
        for path, _, n in fs.walk():
            extra = ""
            if kind(n["mode"]) == "l":
                extra = " -> " + fs.data(n["size"], n["ptrs"], n["levels"]).decode("utf-8", "replace")
            print("%s %06o %10d %s%s" % (kind(n["mode"]), n["mode"] & 0o7777, n["size"], path, extra))
        return
    out = os.path.realpath(sys.argv[3])
    os.makedirs(out, exist_ok=True)
    for path, _, n in fs.walk():
        dst = os.path.realpath(os.path.join(out, path.lstrip("/")))
        if not dst.startswith(out + os.sep):
            sys.exit("path escapes output: %r" % path)
        k = kind(n["mode"])
        if k == "d":
            os.makedirs(dst, exist_ok=True)
        elif k == "l":
            with open(dst + ".symlink", "wb") as fh:
                fh.write(fs.data(n["size"], n["ptrs"], n["levels"]))
        elif k == "f":
            with open(dst, "wb") as fh:
                for c in fs.chunks(n["size"], n["ptrs"], n["levels"]):
                    fh.write(c)
            os.chmod(dst, 0o644)
            os.utime(dst, (n["mtime"], n["mtime"]))


if __name__ == "__main__":
    main()
