#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build NavActiveIgnore.jar from a firmware's own HMI classes (converted lsd.jxe).
#
#   build.sh <profile> <converted lsd.jar> <work dir>
#
# Profiles pin the converted jar and the firmware's HMI property IDs. A new
# firmware (MU1161 after the backup) gets its own profile line, never a guess.
# Needs: JDK 11+ (javac, java, javap), python3, ASM 9.7 jars in $ASM_DIR.
set -euo pipefail

PROFILE=${1:?profile}; STOCK_JAR=${2:?converted lsd jar}; W=${3:?work dir}
H=$(cd "$(dirname "$0")" && pwd)
BT="$H/../buildtools"     # Guard (try/catch around every hook call), RefCheck (J9 API check)
: "${ASM_DIR:?set ASM_DIR to a directory with asm-9.7, asm-tree-9.7, asm-analysis-9.7}"

case "$PROFILE" in
    K4525) JAR_SHA=f996e81650e9d748a4d6d3d072f1739bbd718d7b55a27dc9acb80b21b5ec1a2b; CARPLAY_PROP=2910009; AA_PROP=2910005 ;;
    # Our car's backup (2026-10-21). The five patched classes are byte-identical to K4525.
    # a0cc737c = time-stamped conversion, 573b603a = the same classes from jxe2jar_run.py (fixed timestamps)
    MU1161) JAR_SHA=a0cc737ce40cf0ef95127fd9bf6d3c21a8ca2edeffe815a5d1adbbd2ae0f2599; JAR_SHA_ALT=573b603a0b79b6c150d6c4363d5db2f9a1b644b21f81ab4a2329d5cdda0f1576; CARPLAY_PROP=2910009; AA_PROP=2910005 ;;
    *) echo "unknown profile $PROFILE" >&2; exit 2 ;;
esac

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fail() { echo "FAIL: $*" >&2; exit 1; }

# ASM 9.7 from Maven Central (same bytes as the copies in jxe2jar and maxim-smirnov).
[ "$(sha "$ASM_DIR/asm-9.7.jar")" = adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d ] || fail "asm-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-tree-9.7.jar")" = 62f4b3bc436045c1acb5c3ba2d8ec556ec3369093d7f5d06c747eb04b56d52b1 ] || fail "asm-tree-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-analysis-9.7.jar")" = 7bc6bcbc21379948a0c8c467fb0f864206e5b818f6bc0b546872f5c9f941556f ] || fail "asm-analysis-9.7.jar hash"
JAR_GOT=$(sha "$STOCK_JAR")
[ "$JAR_GOT" = "$JAR_SHA" ] || [ "$JAR_GOT" = "${JAR_SHA_ALT:-none}" ] || fail "converted jar is not the pinned $PROFILE jar"

CP="$ASM_DIR/asm-9.7.jar:$ASM_DIR/asm-tree-9.7.jar:$ASM_DIR/asm-analysis-9.7.jar"
CLASSES="de/esolutions/fw/comm/dsi/carplay/impl/DSICarplayProxy
de/vw/mib/asl/internal/carplay/common/CarPlayModeHandling
de/vw/mib/asl/internal/navigation/api/impl/ASLNavigationServices
de/vw/mib/asl/internal/androidauto/target/NavigationListener
de/vw/mib/asl/internal/androidauto/target/RequestHandler"

[ ! -e "$W" ] || fail "work dir exists: $W"
mkdir -p "$W"/{stock,helper,out,pbin,report}
W=$(cd "$W" && pwd); STOCK_JAR=$(cd "$(dirname "$STOCK_JAR")" && pwd)/$(basename "$STOCK_JAR")

(cd "$W/stock" && for c in $CLASSES; do unzip -q "$STOCK_JAR" "$c.class"; done)
javac --release 8 -nowarn -cp "$STOCK_JAR" -d "$W/helper" "$H/src/de/vw/mib/navactiveignore/NavActiveIgnore.java"
javac -nowarn -cp "$CP" -d "$W/pbin" "$H/patcher/Patch.java" "$H/patcher/Verify.java" "$BT/Guard.java" "$BT/RefCheck.java"
java -cp "$CP:$W/pbin" Patch "$W/stock" "$W/helper" "$W/out" "$CARPLAY_PROP" "$AA_PROP"
java -cp "$CP:$W/pbin" Verify "$W/out" "$STOCK_JAR" $(find "$W/out" -name '*.class' | sort)

# Every class must be major 46 (factory J9), whatever desktop Java accepts.
for f in $(find "$W/out" -name '*.class'); do
    [ "$(xxd -s 6 -l 2 -p "$f")" = 002e ] || fail "class version not 46: $f"
done

# Review report: normalised javap diff, stock vs patched, per replaced class.
for c in $CLASSES; do
    n=$(basename "$c")
    norm() { sed -E "s/#[0-9]+(, *[0-9]+)?//; s#${c}\\.##g; s/^ *[0-9]+: //; s/[[:space:]]+/ /g"; }
    javap -p -c -constants -cp "$W/stock" "${c//\//.}" | norm > "$W/report/$n.stock.txt"
    javap -p -c -constants -cp "$W/out:$STOCK_JAR" "${c//\//.}" | norm > "$W/report/$n.patched.txt"
    diff "$W/report/$n.stock.txt" "$W/report/$n.patched.txt" > "$W/report/$n.diff" || true
done

# Deterministic jar: sorted entries, fixed timestamp, so the hash is reproducible.
python3 -I - "$W/out" "$W/NavActiveIgnore.jar" "$PROFILE" <<'EOF'
import os, sys, zipfile
src, dst, profile = sys.argv[1:]
files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.endswith('.class'))
def add(z, name, data):
    i = zipfile.ZipInfo(name, date_time=(2026, 10, 20, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED
    i.external_attr = 0o100644 << 16; z.writestr(i, data)
with zipfile.ZipFile(dst, 'w') as z:
    add(z, 'META-INF/MANIFEST.MF', ('Manifest-Version: 1.0\nCreated-By: NavActiveIgnore ' + profile + ' (ASM patch of stock lsd.jxe classes)\n').encode())
    for f in files: add(z, f, open(os.path.join(src, f), 'rb').read())
EOF

# J9 CDC API check: every reference in the jar must resolve against the unit's own classes.
java -cp "$CP:$W/pbin" RefCheck "$STOCK_JAR" "$W/NavActiveIgnore.jar"

# Host test: load every replaced class from the jar under -Xverify:all, helper behaviour.
mkdir -p "$W/test"
javac -nowarn -cp "$W/NavActiveIgnore.jar:$STOCK_JAR" -d "$W/test" "$H/test/TestNai.java"
java -Xverify:all -cp "$W/test:$W/NavActiveIgnore.jar:$STOCK_JAR" TestNai > "$W/test/result.txt" || { cat "$W/test/result.txt"; fail "host test"; }
tail -1 "$W/test/result.txt"

{
    echo "profile=$PROFILE"
    echo "stock_jar_sha256=$JAR_GOT"
    echo "carplay_nav_property=$CARPLAY_PROP"
    echo "aa_nav_property=$AA_PROP"
    for c in $CLASSES; do echo "stock $c $(sha "$W/stock/$c.class")"; done
    for f in $(cd "$W/out" && find . -name '*.class' | sort); do echo "out ${f#./} $(sha "$W/out/$f")"; done
    echo "jar_sha256=$(sha "$W/NavActiveIgnore.jar")"
    echo "jar_size=$(stat -f %z "$W/NavActiveIgnore.jar" 2>/dev/null || stat -c %s "$W/NavActiveIgnore.jar")"
} > "$W/manifest.txt"
cat "$W/manifest.txt"
echo "built $W/NavActiveIgnore.jar"
