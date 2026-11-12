#!/usr/bin/env python3
"""Compare two built card trees (build_sd.py / build_card_install.py / build_rescue.py / build_logcard.py output).

  compare_cards.py <before> <after>

For refactors that must not change behaviour: every file must be byte-identical, except that the build id (the 8 hex
after "pmcp-<x.y.z>-[exp-]<tag>-") may differ. Files that differ only in the build id are reported as such; in
BUILD-MANIFEST.txt the hash and size of exactly those files may differ too. Anything else is a difference: exit 1.
"""
import hashlib
import os
import re
import sys

BUILD_ID = re.compile(rb"(pmcp-\d+\.\d+\.\d+-(?:exp-)?[a-z0-9]+(?:-[a-z0-9]+)*?-)[0-9a-f]{8}(?![0-9a-f])")


def tree(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = p
    return out


def mask(b):
    return BUILD_ID.sub(rb"\1########", b)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    a, b = tree(sys.argv[1]), tree(sys.argv[2])
    bad = []
    for k in sorted(set(a) ^ set(b)):
        bad.append("only in %s: %s" % ("before" if k in a else "after", k))
    idonly = set()
    manifests = []
    for k in sorted(set(a) & set(b)):
        x, y = open(a[k], "rb").read(), open(b[k], "rb").read()
        if x == y:
            continue
        if os.path.basename(k) == "BUILD-MANIFEST.txt":
            manifests.append((k, x, y))
        elif mask(x) == mask(y):
            idonly.add(k)
        else:
            bad.append("differs: %s" % k)
    for k, x, y in manifests:
        base = os.path.dirname(k)

        def rows(t):
            r = []
            for line in mask(t).decode("utf-8", "replace").splitlines():
                parts = line.split()
                if len(parts) >= 3 and os.path.normpath(os.path.join(base, parts[-1])) in idonly:
                    line = "<build-id-only> " + parts[-1]
                r.append(line)
            return r
        if rows(x) != rows(y):
            bad.append("differs: %s (beyond build-id-only files)" % k)
    for k in sorted(idonly):
        print("build id only: " + k)
    for line in bad:
        print(line)
    n = len(set(a) & set(b)) - len(idonly) - len(manifests)
    print("%d identical, %d build-id only, %d manifest(s), %d problem(s)" % (n, len(idonly), len(manifests), len(bad)))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
