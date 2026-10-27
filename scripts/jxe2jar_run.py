#!/usr/bin/env python3
"""Run the reviewed upstream luka-dev/jxe2jar converter on an IBM J9 .jxe image.

  python3 -I jxe2jar_run.py <jxe2jar/src> lsd.jxe out.jar
  python3 -I jxe2jar_run.py --check out.jar

The converter (stdlib-only: struct/io/zipfile/argparse) is pinned at commit
9eeb45bbf14bf8afe3452c7be96a4d1f0206a286 in upstream/tools/jxe2jar/repo. Under -I the
script directory is not on sys.path, so its src dir is added explicitly here. The .jxe is
only read; the output jar must not exist yet. --check counts .class entries and verifies
the CAFEBABE magic and class-file version of each.

The converter stamps every entry with the time of the run. The output is rewritten with one fixed timestamp
(same entries, order, bytes and attributes), so the jar's SHA-256 depends only on the .jxe and the converter
(normalised MU1161 jar: 573b603a...; same classes as the earlier time-stamped a0cc737c... jar).
  python3 -I jxe2jar_run.py --normalise in.jar out.jar   (normalise an existing jar)
"""
import os
import runpy
import struct
import sys
import zipfile


def check(jar):
    n, bad, versions = 0, [], {}
    with zipfile.ZipFile(jar) as z:
        for name in z.namelist():
            if not name.endswith(".class"):
                continue
            n += 1
            head = z.open(name).read(8)
            if head[:4] != b"\xca\xfe\xba\xbe":
                bad.append(name)
                continue
            ver = struct.unpack(">H", head[6:8])[0]
            versions[ver] = versions.get(ver, 0) + 1
    print(f"{n} classes, {len(bad)} bad magic, major versions {sorted(versions.items())}")
    for name in bad[:20]:
        print("  bad:", name)


def normalise(src, dst):
    if os.path.exists(dst):
        sys.exit(f"refusing to overwrite {dst}")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst + ".tmp", "w") as zout:
        for old in zin.infolist():
            new = zipfile.ZipInfo(old.filename, date_time=(1980, 1, 1, 0, 0, 0))
            new.compress_type, new.external_attr, new.create_system = old.compress_type, old.external_attr, 3
            zout.writestr(new, zin.read(old))
    os.replace(dst + ".tmp", dst)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        return check(sys.argv[2])
    if len(sys.argv) == 4 and sys.argv[1] == "--normalise":
        return normalise(*(os.path.abspath(p) for p in sys.argv[2:]))
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    src, jxe, out = (os.path.abspath(p) for p in sys.argv[1:])
    if os.path.exists(out):
        sys.exit(f"refusing to overwrite {out}")
    if not zipfile.ZipFile(jxe).getinfo("rom.classes"):
        sys.exit("no rom.classes in input")
    sys.path.insert(0, src)
    sys.argv = [os.path.join(src, "jxe2jar.py"), jxe, out]
    runpy.run_path(sys.argv[0], run_name="__main__")
    os.rename(out, out + ".raw")
    normalise(out + ".raw", out)
    os.remove(out + ".raw")
    check(out)


if __name__ == "__main__":
    main()
