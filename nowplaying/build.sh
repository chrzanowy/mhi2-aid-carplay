#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Package D: build pmcp-np.jar (CarPlay track title / artist / album on the cluster) from MU1161's own classes.
#
#   build.sh <converted lsd.jar> <work dir>
#
# Needs: JDK 11+ (tested with 25) (javac, java, javap), python3, ASM 9.7 jars in $ASM_DIR.
set -euo pipefail

STOCK_JAR=${1:?converted lsd jar}; W=${2:?work dir}
H=$(cd "$(dirname "$0")" && pwd)
BT="$H/../buildtools"     # Guard (try/catch around every hook call), RefCheck (J9 API check)
: "${ASM_DIR:?set ASM_DIR to a directory with asm-9.7, asm-tree-9.7, asm-analysis-9.7}"
JAR_SHA=a0cc737ce40cf0ef95127fd9bf6d3c21a8ca2edeffe815a5d1adbbd2ae0f2599   # MU1161, our backup

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fail() { echo "FAIL: $*" >&2; exit 1; }

[ "$(sha "$ASM_DIR/asm-9.7.jar")" = adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d ] || fail "asm-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-tree-9.7.jar")" = 62f4b3bc436045c1acb5c3ba2d8ec556ec3369093d7f5d06c747eb04b56d52b1 ] || fail "asm-tree-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-analysis-9.7.jar")" = 7bc6bcbc21379948a0c8c467fb0f864206e5b818f6bc0b546872f5c9f941556f ] || fail "asm-analysis-9.7.jar hash"
[ "$(sha "$STOCK_JAR")" = "$JAR_SHA" ] || fail "converted jar is not the pinned MU1161 jar"

CP="$ASM_DIR/asm-9.7.jar:$ASM_DIR/asm-tree-9.7.jar:$ASM_DIR/asm-analysis-9.7.jar"
CLASSES="de/vw/mib/asl/internal/carplay/target/HsmTarget
de/vw/mib/bap/mqbab2/audiosd/functions/CurrentStationInfo"

[ ! -e "$W" ] || fail "work dir exists: $W"
mkdir -p "$W"/{stock,helper,out,pbin,report,test}
W=$(cd "$W" && pwd); STOCK_JAR=$(cd "$(dirname "$STOCK_JAR")" && pwd)/$(basename "$STOCK_JAR")

(cd "$W/stock" && for c in $CLASSES; do unzip -q "$STOCK_JAR" "$c.class"; done)
javac --release 8 -nowarn -cp "$STOCK_JAR" -d "$W/helper" "$H"/src/com/pmcp/np/*.java
javac -nowarn -cp "$CP" -d "$W/pbin" "$H/patcher/PatchNp.java" "$H/patcher/Verify.java" "$BT/Guard.java" "$BT/RefCheck.java"
java -cp "$CP:$W/pbin" PatchNp "$W/stock" "$W/helper" "$W/out"
java -cp "$CP:$W/pbin" Verify "$W/out" "$STOCK_JAR" $(find "$W/out" -name '*.class' | sort)

for f in $(find "$W/out" -name '*.class'); do
    [ "$(xxd -s 6 -l 2 -p "$f")" = 002e ] || fail "class version not 46: $f"
done
# every helper class the compiler produced must be in the jar (no forgotten inner class)
for f in $(cd "$W/helper" && find . -name '*.class'); do
    [ -f "$W/out/$f" ] || fail "helper class not packaged: $f"
done

for c in $CLASSES; do
    n=$(basename "$c")
    norm() { sed -E "s/#[0-9]+(, *[0-9]+)?//; s#${c}\\.##g; s/^ *[0-9]+: //; s/[[:space:]]+/ /g"; }
    javap -p -c -constants -cp "$W/stock" "${c//\//.}" | norm > "$W/report/$n.stock.txt"
    javap -p -c -constants -cp "$W/out:$STOCK_JAR" "${c//\//.}" | norm > "$W/report/$n.patched.txt"
    diff "$W/report/$n.stock.txt" "$W/report/$n.patched.txt" > "$W/report/$n.diff" || true
done

python3 -I - "$W/out" "$W/pmcp-np.jar" <<'EOF'
import os, sys, zipfile
src, dst = sys.argv[1:]
files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.endswith('.class'))
def add(z, name, data):
    i = zipfile.ZipInfo(name, date_time=(2026, 10, 21, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED
    i.external_attr = 0o100644 << 16; z.writestr(i, data)
with zipfile.ZipFile(dst, 'w') as z:
    add(z, 'META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\nCreated-By: pmcp package D (now playing), MU1161\n')
    for f in files: add(z, f, open(os.path.join(src, f), 'rb').read())
EOF

java -cp "$CP:$W/pbin" RefCheck "$STOCK_JAR" "$W/pmcp-np.jar"

javac -nowarn -cp "$W/pmcp-np.jar:$STOCK_JAR" -d "$W/test" "$H/test/TestNp.java"
java -Xverify:all -cp "$W/test:$W/pmcp-np.jar:$STOCK_JAR" com.pmcp.np.TestNp > "$W/test/result.txt" || { cat "$W/test/result.txt"; fail "host test"; }
tail -1 "$W/test/result.txt"

{
    echo "stock_jar_sha256=$JAR_SHA"
    for c in $CLASSES; do echo "stock $c $(sha "$W/stock/$c.class")"; done
    for f in $(cd "$W/out" && find . -name '*.class' | sort); do echo "out ${f#./} $(sha "$W/out/$f")"; done
    echo "jar_sha256=$(sha "$W/pmcp-np.jar")"
    echo "jar_size=$(wc -c < "$W/pmcp-np.jar" | tr -d ' ')"
} > "$W/manifest.txt"
cat "$W/manifest.txt"
echo "built $W/pmcp-np.jar"
