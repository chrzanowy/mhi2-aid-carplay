#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Packages F (pmcp-zoom.jar: steering-wheel zoom) and G (pmcp-dn.jar: day/night resend) from MU1161's own classes.
#
#   build.sh <converted MU1161 lsd.jar> <work dir>
set -euo pipefail

STOCK_JAR=${1:?converted lsd jar}; W=${2:?work dir}
H=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$H/../.." && pwd)
BT="$H/../buildtools"     # Guard (try/catch around every hook call), RefCheck (J9 API check)
: "${ASM_DIR:?set ASM_DIR}"

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fail() { echo "FAIL: $*" >&2; exit 1; }
pin() { [ "$(sha "$1")" = "$2" ] || fail "hash $1"; }

# converted MU1161 lsd.jar: a0cc737c (time-stamped) or 573b603a (same classes, jxe2jar_run.py fixed timestamps)
[ "$(sha "$STOCK_JAR")" = a0cc737ce40cf0ef95127fd9bf6d3c21a8ca2edeffe815a5d1adbbd2ae0f2599 ] || pin "$STOCK_JAR" 573b603a0b79b6c150d6c4363d5db2f9a1b644b21f81ab4a2329d5cdda0f1576
pin "$ASM_DIR/asm-9.7.jar" adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d
pin "$ASM_DIR/asm-tree-9.7.jar" 62f4b3bc436045c1acb5c3ba2d8ec556ec3369093d7f5d06c747eb04b56d52b1
pin "$ASM_DIR/asm-analysis-9.7.jar" 7bc6bcbc21379948a0c8c467fb0f864206e5b818f6bc0b546872f5c9f941556f

CP="$ASM_DIR/asm-9.7.jar:$ASM_DIR/asm-tree-9.7.jar:$ASM_DIR/asm-analysis-9.7.jar"
[ ! -e "$W" ] || fail "work dir exists: $W"
mkdir -p "$W"/{stock,helper,pbin,report,test,zoom,dn}
W=$(cd "$W" && pwd); STOCK_JAR=$(cd "$(dirname "$STOCK_JAR")" && pwd)/$(basename "$STOCK_JAR")

KP=de/esolutions/fw/dsi/keypanel/DSIKeyPanelDispatcher
AH=de/vw/mib/asl/internal/carplay/target/ASLHandler
(cd "$W/stock" && unzip -q "$STOCK_JAR" "$KP.class" "$AH.class")
javac --release 8 -nowarn -cp "$STOCK_JAR" -d "$W/helper" "$H"/src/com/pmcp/zoom/*.java "$H"/src/com/pmcp/dn/*.java
javac -nowarn -cp "$CP" -d "$W/pbin" "$H/patcher/PatchExtras.java" "$H/patcher/Verify.java" "$BT/Guard.java" "$BT/RefCheck.java"
ZH=$(cd "$W/helper" && find com/pmcp/zoom -name '*.class' | sed 's/\.class$//' | sort)
DH=$(cd "$W/helper" && find com/pmcp/dn -name '*.class' | sed 's/\.class$//' | sort)
java -cp "$CP:$W/pbin" PatchExtras zoom "$W/stock" "$W/helper" "$W/zoom" $ZH
java -cp "$CP:$W/pbin" PatchExtras dn "$W/stock" "$W/helper" "$W/dn" $DH
java -cp "$CP:$W/pbin" Verify "$W/zoom" "$STOCK_JAR" $(find "$W/zoom" -name '*.class' | sort)
java -cp "$CP:$W/pbin" Verify "$W/dn" "$STOCK_JAR" $(find "$W/dn" -name '*.class' | sort)
for f in $(find "$W/zoom" "$W/dn" -name '*.class'); do [ "$(xxd -s 6 -l 2 -p "$f")" = 002e ] || fail "class version not 46: $f"; done

for pair in "zoom:$KP" "dn:$AH"; do
    d=${pair%%:*}; c=${pair#*:}; n=$(basename "$c")
    norm() { sed -E "s/#[0-9]+(, *[0-9]+)?//; s#${c}\\.##g; s/^ *[0-9]+: //; s/[[:space:]]+/ /g"; }
    javap -p -c -constants -cp "$W/stock" "${c//\//.}" | norm > "$W/report/$n.stock.txt"
    javap -p -c -constants -cp "$W/$d:$STOCK_JAR" "${c//\//.}" | norm > "$W/report/$n.patched.txt"
    diff "$W/report/$n.stock.txt" "$W/report/$n.patched.txt" > "$W/report/$n.diff" || true
done

for d in zoom dn; do
python3 -I - "$W/$d" "$W/pmcp-$d.jar" "$d" <<'EOF'
import os, sys, zipfile
src, dst, name = sys.argv[1:]
files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.endswith('.class'))
def add(z, n, data):
    i = zipfile.ZipInfo(n, date_time=(2026, 10, 21, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED
    i.external_attr = 0o100644 << 16; z.writestr(i, data)
with zipfile.ZipFile(dst, 'w') as z:
    add(z, 'META-INF/MANIFEST.MF', ('Manifest-Version: 1.0\nCreated-By: pmcp package %s, MU1161\n' % name).encode())
    for f in files: add(z, f, open(os.path.join(src, f), 'rb').read())
EOF
done

java -cp "$CP:$W/pbin" RefCheck "$STOCK_JAR" "$W/pmcp-zoom.jar" "$W/pmcp-dn.jar"

javac -nowarn -cp "$W/pmcp-zoom.jar:$W/pmcp-dn.jar:$STOCK_JAR" -d "$W/test" "$H/test/TestExtras.java"
java -Xverify:all -cp "$W/test:$W/pmcp-zoom.jar:$W/pmcp-dn.jar:$STOCK_JAR" com.pmcp.dn.TestExtras > "$W/test/result.txt" || { cat "$W/test/result.txt"; fail "host test"; }
tail -1 "$W/test/result.txt"
# guard: the patched key dispatcher with the helper classes missing must not throw a LinkageError
mkdir -p "$W/test/noguard" && (cd "$W/test/noguard" && unzip -q "$W/pmcp-zoom.jar" && rm -r com/pmcp/zoom)
javac -nowarn -d "$W/test" "$H/test/TestZoomGuard.java"
java -Xverify:all -cp "$W/test:$W/test/noguard:$STOCK_JAR" TestZoomGuard > "$W/test/guard.txt" || { cat "$W/test/guard.txt"; fail "guard test"; }
tail -1 "$W/test/guard.txt"
for f in pmcp-zoom.jar pmcp-dn.jar; do echo "$f $(sha "$W/$f") $(wc -c < "$W/$f" | tr -d ' ')"; done | tee "$W/manifest.txt"
echo "built $W"
