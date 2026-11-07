#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build the optional CarPlay settings page package (ui) from the exact MU1161 AbstractViewHandler.
#   ASM_DIR=/path/to/asm-9.7 build.sh <converted lsd.jar> <fresh work dir>
# Requires JDK 11+ (host tests use MethodHandles.privateLookupIn and Path.of) and Python 3. JAVA_HOME may select the JDK.
set -euo pipefail

STOCK_JAR=${1:?converted lsd jar}; W=${2:?fresh work dir}
H=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$H/.." && pwd)
: "${ASM_DIR:?set ASM_DIR to a directory with ASM 9.7 jars}"
JAVA=java; JAVAC=javac
if [ -n "${JAVA_HOME:-}" ]; then
    JAVA="$JAVA_HOME/bin/java"; JAVAC="$JAVA_HOME/bin/javac"
fi

fail() { echo "FAIL: $*" >&2; exit 1; }
sha() { python3 -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1"; }
# converted MU1161 lsd.jar: 573b603a (jxe2jar_run.py, fixed timestamps) or a0cc737c (same classes, time-stamped);
# the patcher also pins the one class it reads (AbstractViewHandler 7afadc2e)
case "$(sha "$STOCK_JAR")" in
    573b603a0b79b6c150d6c4363d5db2f9a1b644b21f81ab4a2329d5cdda0f1576|a0cc737ce40cf0ef95127fd9bf6d3c21a8ca2edeffe815a5d1adbbd2ae0f2599) ;;
    *) fail "converted jar is not the pinned MU1161 image" ;;
esac
[ "$(sha "$ASM_DIR/asm-9.7.jar")" = adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d ] || fail "asm-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-tree-9.7.jar")" = 62f4b3bc436045c1acb5c3ba2d8ec556ec3369093d7f5d06c747eb04b56d52b1 ] || fail "asm-tree-9.7.jar hash"
[ "$(sha "$ASM_DIR/asm-analysis-9.7.jar")" = 7bc6bcbc21379948a0c8c467fb0f864206e5b818f6bc0b546872f5c9f941556f ] || fail "asm-analysis-9.7.jar hash"
[ ! -e "$W" ] || fail "use a fresh output directory"
mkdir -p "$W"/{stock,helpers,tools,patched,tests,hook-only}
W=$(cd "$W" && pwd)
STOCK_JAR=$(cd "$(dirname "$STOCK_JAR")" && pwd)/$(basename "$STOCK_JAR")
ASM_DIR=$(cd "$ASM_DIR" && pwd)
AVH=de/vw/mib/view/internal/AbstractViewHandler.class

CP="$ASM_DIR/asm-9.7.jar:$ASM_DIR/asm-tree-9.7.jar:$ASM_DIR/asm-analysis-9.7.jar"
TOOLS_CP="$W/tools:$CP"

python3 -I - "$STOCK_JAR" "$W/stock" "$AVH" <<'PY'
from pathlib import Path
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    target = Path(sys.argv[2]) / sys.argv[3]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(z.read(sys.argv[3]))
PY

# helpers: Java 8 language against the unit's own classes; the patcher rewrites them to class version 46
"$JAVAC" --release 8 -g:none -Xlint:-options -nowarn -cp "$STOCK_JAR" -d "$W/helpers" "$H"/src/com/pmcp/ui/*.java
"$JAVAC" -g:none -nowarn -cp "$CP" -d "$W/tools" "$REPO/buildtools/Guard.java" "$REPO/buildtools/RefCheck.java" \
    "$REPO/navactiveignore/patcher/Verify.java" "$H"/patcher/*.java
"$JAVA" -cp "$TOOLS_CP" PatchMenuHook "$W/stock" "$W/helpers" "$W/patched"
"$JAVA" -cp "$TOOLS_CP" TestMenuHookPatch "$W/stock" "$W/patched"

python3 -I - "$W/patched" "$W/pmcp-ui.jar" <<'PY'
from pathlib import Path
import hashlib, struct, sys, zipfile
root, target = Path(sys.argv[1]), Path(sys.argv[2])
classes = sorted(root.rglob('*.class'))
if not classes:
    raise ValueError('No generated classes')
with zipfile.ZipFile(target, 'x') as z:
    entries = [('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\nCreated-By: MU1161 pmcp CarPlay settings page\n\n')]
    for path in classes:
        data = path.read_bytes()
        if data[:4] != b'\xca\xfe\xba\xbe' or struct.unpack('>H', data[6:8])[0] != 46:
            raise ValueError('Generated class is not J9 version 46 ' + str(path))
        entries.append((path.relative_to(root).as_posix(), data))
    for name, data in entries:
        item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.create_system = 3
        item.external_attr = 0o100644 << 16
        z.writestr(item, data)
print('UI_JAR', target.stat().st_size, hashlib.sha256(target.read_bytes()).hexdigest())
PY

"$JAVA" -cp "$TOOLS_CP" RefCheck "$STOCK_JAR" "$W/pmcp-ui.jar"
classes=()
while IFS= read -r path; do classes+=("$path"); done < <(find "$W/patched" -name '*.class' | LC_ALL=C sort)
"$JAVA" -cp "$TOOLS_CP" Verify "$W/patched" "$STOCK_JAR" "${classes[@]}"

# host tests: real factory widget classes, the patched AbstractViewHandler first on the class path
"$JAVAC" -g -nowarn -cp "$W/pmcp-ui.jar:$STOCK_JAR:$CP" -d "$W/tests" "$H"/test/com/pmcp/ui/*.java
"$JAVA" -Xverify:all -cp "$W/tests:$W/pmcp-ui.jar:$STOCK_JAR:$CP" com.pmcp.ui.TestUi
# the patched class alone, no helper classes: every hooked lifecycle method still completes
mkdir -p "$W/hook-only/$(dirname "$AVH")"
cp "$W/patched/$AVH" "$W/hook-only/$AVH"
"$JAVA" -Xverify:all -cp "$W/tests:$W/hook-only:$STOCK_JAR:$CP" com.pmcp.ui.TestNoHelper

python3 -I - "$STOCK_JAR" "$W/pmcp-ui.jar" "$W/patched" "$W/BUILD-VALIDATION.json" <<'PY'
from pathlib import Path
import hashlib, json, sys
stock, jar, classes, target = map(Path, sys.argv[1:])
report = {
    'firmware': 'MHI2_ER_VWG13_P4512_1 MU1161',
    'source_stock_jar_sha256': hashlib.sha256(stock.read_bytes()).hexdigest(),
    'stock_class': 'de/vw/mib/view/internal/AbstractViewHandler 7afadc2e226ef2b3444ea0e138e82fda5d839401d58e2beb0bcc00170972ddd6',
    'jar_sha256': hashlib.sha256(jar.read_bytes()).hexdigest(),
    'jar_size': jar.stat().st_size,
    'generated_classes': len(list(classes.rglob('*.class'))),
    'hooks': 5,
    'j9_api_check': 'pass',
    'bytecode_verification': 'pass',
    'patch_diff_test': 'pass',
    'host_tests': 'pass',
    'missing_helper_test': 'pass',
    'qnx_execution_tested': False,
    'in_car_tested': False,
}
target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
PY
echo "UI_BUILD_OK $W/pmcp-ui.jar"
