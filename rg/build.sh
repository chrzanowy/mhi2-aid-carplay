#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Package E (native route guidance, port of tomasz-twardzicki MU1427 v1.2.0) for MU1161:
#   - pmcp-rg.jar: Tomasz's PatchLive applied to OUR six NavSD classes + his bridge helpers compiled against
#     OUR converted lsd.jar, then his TestLive integration test on the desktop JVM;
#   - ipod-drvr-iap2.so: his driver patch chain reproduced on our driver (see rg/README.md);
#   - iap2.cfg: our factory file + his [ident] section;
#   - rgi-observer: his prebuilt reader (GPL, source release/reader.c), hash-pinned.
#
#   build.sh <converted MU1161 lsd.jar> <work dir> [lanes]
#
# "lanes": pmcp-rg.jar additionally carries Tomasz's MU1367 v1.4.0 native lane guidance (rg/lanes/, iAP2 0x5204 -> the
# factory LaneGuidance builder) and is tested with his TestLanes; driver, cfg and reader are the same.
# "lanes-uturn" (v1.3 package rglu): lanes + rg/lanes/uturn.py on the staged copies (U-turn lanes as VW 114/146).
# "lanes-uturn-asf": lanes-uturn + rg/lanes/asf.py (tomasz-twardzicki MU1367 v1.4.3, git 1d69473: bargraph before the
# maneuver, current road name in TurnToInfo, FeedRecovery), tested with his TestArrow, TestRoad and TestRecovery.
# "lanes-uturn-asf-m" (v1.4 package rg): lanes-uturn-asf + rg/lanes/maneuvers.py (arrow fallbacks where the
# strict mapping shows none: start of route, roundabout turns), tested with TestManeuvers.
# "lanes-uturn-asf-m-aa" (package rg since v1.5.0; the v1.4.x experimental cards' rg-aa): lanes-uturn-asf-m + rg/lanes/aa.py
# (Android Auto too: connection 3 reads /ramdisk/pmcp-aa-rg written by the AA gamma hook; CarPlay unchanged), tested with
# every lanes-uturn-asf-m suite and also with TestAa.
# "lanes-uturn-asf-m-aa-r" (package rg since v1.6.1): lanes-uturn-asf-m-aa + rg/lanes/v146.py (tomasz-twardzicki MU1367
# v1.4.5/v1.4.6 CarPlay guidance fixes: reroute episode with CALC_ROUTE, placeholder arrow, U-turn side, Apple Maps names),
# tested with every lanes-uturn-asf-m-aa suite (TestArrow/TestRoad with his reroute changes) plus his TestReroute,
# TestSourceName, TestUturnSide, TestPlaceholder, TestQuietQnx and our TestPmcp146.
# Since A166 (experimental) the -aa modes also carry com.pmcp.kv.KombiView (rg/kv/: which view the AID shows, logged to
# /ramdisk/pmcp-kombi-view.log) hooked into three more stock classes by rg/patcher/PatchKombiView.java (mostkombi
# ChangeDataRate, navigation MapViewerKombiNotifierModel, navsd ActiveRgType).
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # do not write __pycache__ into upstream/tomasz (review 2)

STOCK_JAR=${1:?converted lsd jar}; W=${2:?work dir}; MODE=${3:-base}
case "$MODE" in base|lanes|lanes-uturn|lanes-uturn-asf|lanes-uturn-asf-m|lanes-uturn-asf-m-aa|lanes-uturn-asf-m-aa-r) ;; *) echo "FAIL: third argument must be lanes, lanes-uturn, lanes-uturn-asf, lanes-uturn-asf-m, lanes-uturn-asf-m-aa, lanes-uturn-asf-m-aa-r or nothing" >&2; exit 1 ;; esac
ASF=no; case "$MODE" in *-asf|*-asf-m|*-asf-m-aa|*-asf-m-aa-r) ASF=yes ;; esac
MAN=no; case "$MODE" in *-asf-m|*-asf-m-aa|*-asf-m-aa-r) MAN=yes ;; esac
AA=no; case "$MODE" in *-aa|*-aa-r) AA=yes ;; esac
R146=no; case "$MODE" in *-aa-r) R146=yes ;; esac
H=$(cd "$(dirname "$0")" && pwd)
BT="$H/../buildtools"     # Guard (try/catch around every hook call), RefCheck (J9 API check)
REPO=$(cd "$H/../.." && pwd)
T="$REPO/upstream/tomasz"            # git 024dd159c4d99890c9b17ea500325e4d2b5dcbde
RG="$T/MU1427/route-guidance"
REL="$T/releases/CarPlay_Maps_VC_Full_Toolboxes/VW_SKODA_ALL_CarPlay_Maps_VC_FULL_MQB_Toolbox_V4/Custom/carplay_native_guidance"
BK="${PMCP_BACKUP:-$REPO/backup/MU1161}/advanced"   # M.I.B. backup of the unit
: "${ASM_DIR:?set ASM_DIR}"
PY="$REPO/upstream/tools/venv-elftools/bin/python"   # pyelftools 0.31 for Tomasz's patch scripts

sha() { shasum -a 256 "$1" | cut -d' ' -f1; }
fail() { echo "FAIL: $*" >&2; exit 1; }
pin() { [ "$(sha "$1")" = "$2" ] || fail "hash $1"; }

# converted MU1161 lsd.jar: a0cc737c (time-stamped) or 573b603a (same classes, jxe2jar_run.py fixed timestamps)
[ "$(sha "$STOCK_JAR")" = a0cc737ce40cf0ef95127fd9bf6d3c21a8ca2edeffe815a5d1adbbd2ae0f2599 ] || pin "$STOCK_JAR" 573b603a0b79b6c150d6c4363d5db2f9a1b644b21f81ab4a2329d5cdda0f1576
pin "$ASM_DIR/asm-9.7.jar" adf46d5e34940bdf148ecdd26a9ee8eea94496a72034ff7141066b3eea5c4e9d
pin "$ASM_DIR/asm-tree-9.7.jar" 62f4b3bc436045c1acb5c3ba2d8ec556ec3369093d7f5d06c747eb04b56d52b1
pin "$ASM_DIR/asm-analysis-9.7.jar" 7bc6bcbc21379948a0c8c467fb0f864206e5b818f6bc0b546872f5c9f941556f
pin "$RG/bridge/LiveModel.java" 54f7b09eb8b86ca2a92ddc048d5dfbe4d477a0f1eae40f53b5c878e0fd660df5
pin "$RG/bridge/JournalReader.java" 7dd3ecf803558dd637cd3a4f6a3186dfbe3707b554ed4dddd6c9cb7e81214b63
pin "$RG/bridge/MailboxReader.java" fb6e28aa0f420be94550e68b30411a4d18d67dd64db6911f1f859c0eea43baf3
pin "$RG/bridge/LiveBridge.java" 2803b5748792ebf8d9405c3505fa837265d676493461cac1298b8bcba53c4ef7
pin "$RG/bridge/PatchLive.java" ff9c5ccfb8ab252151dd0db6519c3e9950c679c5f0519063c06770d28a8b359f
pin "$RG/bridge/TestLive.java" 7668ca90552b237ead05bef3df728b7734ddf9af2072fbc7cd9ad4306d4ecb6b
pin "$REL/rgi-observer" b683cef78828bfab2b8cdf43e4ea82e5d7c16d0d47730936d936e82af6ee08ac
# native lane guidance, Tomasz's MU1367 v1.4.0 lane files (git 7925a83), copied unchanged into rg/lanes/
pin "$H/lanes/stage.py" 9d0eedcf4aed321b7add9673624c9317059b400d0760aa48e88d2c2f4ce06243
pin "$H/lanes/LaneData.java" c8cc876bea7609e41d66686b081c878ea9c2efb173625aa9d64b90972cf48f0c
pin "$H/lanes/TestLanes.java" 0a9d1a2ac6dc8aef6f3b1172ffe4e195d40ff6efc9ebe1d4611be2870427b760
if [ $ASF = yes ]; then
    # Tomasz's MU1367 v1.4.3 (git 1d69473) files, copied unchanged into rg/lanes/
    pin "$H/lanes/FeedRecovery.java" dffe76c5a6c8a92b4ee6a4ef99318c19d21ea66e47220ee5308e1289f2925d29   # src/guidance
    pin "$H/lanes/ArrowProgress.java" c77491b1fc2f02b88ca01dcb5f257a12e7af6f130d25353d647f35c4c6278452  # src/guidance
    pin "$H/lanes/RoadName.java" 311d65c480d6e19998a3c240ce6cf64b302adce7867baa19c3b69b79bc93f6b5       # src/guidance
    pin "$H/lanes/TestArrow.java" 9ed8fdc1c9272c04dde7d55e94d1c395588804a256254e473546754a7c07faf9      # tests/java
    pin "$H/lanes/TestRoad.java" fb9bac915fdf1ec1263ada4c6dd576e73c4e646fc42413175540a32c3e189984       # tests/java
    pin "$H/lanes/TestRecovery.java" ef41df9c6b048cc66730acd8a10fda3e8414f30bb457d0a55723c9afd9e5b703   # tests/java
    # Tomasz's MU1367 v1.4.4 (tag MU1367-v1.4.4, d20527f) files, copied unchanged into rg/lanes/ (quiet-route hold, hold.py)
    pin "$H/lanes/GuidanceEvidence.java" 23e5e5e603e3d2c76e53364f21646758217d4eb7d28175ef6a48bc7680096d3d  # src/guidance
    pin "$H/lanes/TestQuietHold.java" 0d243d38ed774f4cf3f6e8c2b840bdbb28f6df4d9d6ce8099ff6bb149d0bc39d     # tests/java
fi
if [ $R146 = yes ]; then
    # Tomasz's MU1367 v1.4.6 (tag MU1367-v1.4.6, 9ff2f1b; Java of v1.4.6-e d680311) files, copied unchanged into rg/lanes/v146/
    pin "$H/lanes/v146/GuidanceEvidence.java" a161bd22cb540783287a05d7d87065ede4a10651e0cb287ef4280a0d88cd8dca  # src/guidance
    pin "$H/lanes/v146/TestReroute.java" f207f2417d88ec821fff546c018ea63e9f6bbc131315134ecdf91b1249f9c977       # tests/java
    pin "$H/lanes/v146/TestSourceName.java" f40ea2b1f0fcd7c8f8b8edc6aeed83433b60576f0b694b15de49658e7c8af463    # tests/java
    pin "$H/lanes/v146/TestUturnSide.java" 340985174e32b2e6a7eadd7ad839c0896309c2b607c4a68441dfb154ffb95010     # tests/java
    pin "$H/lanes/v146/TestPlaceholder.java" 7090c9f8a0012577d935a9df2526262bbd7f7484fdfc4c0239b7b8d2951b6760   # tests/java
    pin "$H/lanes/v146/TestQuietQnx.java" fa3488097ff02ed862d40111b40f8d84f392171605e06b673d7279c55cf81214      # tests/java
fi
pin "$REL/driver/ipod-drvr-iap2.so" 3760797aed4886a6c4480e3a8de79be427a3d8587450a56c424721306ca15d8b
pin "$BK/MU1161-appimg/armle/lib/dll/ipod-drvr-iap2.so" 7149a3e75b1b19e89021841759f420a6eced456b6c697a3dd1f0e436abea0b8c
pin "$BK/MU1161-system/mm/iap2.cfg" 1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37

CP="$ASM_DIR/asm-9.7.jar:$ASM_DIR/asm-tree-9.7.jar:$ASM_DIR/asm-analysis-9.7.jar"
NAV=de/vw/mib/bap/mqbab2/navsd/functions
[ ! -e "$W" ] || fail "work dir exists: $W"
mkdir -p "$W"/{stock,helpers,patcher,patched,tests,generated,report,driver}
W=$(cd "$W" && pwd); STOCK_JAR=$(cd "$(dirname "$STOCK_JAR")" && pwd)/$(basename "$STOCK_JAR")
LB="$RG/bridge"; EXTRA=""; ID=pmcp-mu1161-rg-1; WHAT="Tomasz MU1427 v1.2.0 port"; TL="$H/lanes/TestLanes.java"
if [ "$MODE" != base ]; then
    # Tomasz's lane edits on the pinned bridge sources (LiveModel, LiveBridge, PatchLive, TestLive) + LaneData
    LB=$(python3 -I "$H/lanes/apply_lanes.py" "$T" "$W/lanes" | tail -1)
    [ -f "$LB/LaneData.java" ] && [ -f "$LB/PatchLive.java" ] || fail "lane sources not staged"
    EXTRA="$LB/LaneData.java"; ID=pmcp-mu1161-rg-lanes-1; WHAT="Tomasz MU1427 v1.2.0 port + MU1367 v1.4.0 lanes"
    if [ "$MODE" != lanes ]; then
        python3 -I "$H/lanes/uturn.py" "$LB" "$H/lanes/TestLanes.java" || fail "uturn.py"
        TL="$LB/TestLanes.java"; ID=pmcp-mu1161-rg-lanes-2; WHAT="$WHAT + VW U-turn lanes"
    fi
    if [ $ASF = yes ]; then
        python3 -I "$H/lanes/asf.py" "$LB" "$H/lanes" || fail "asf.py"
        EXTRA="$EXTRA $LB/FeedRecovery.java $LB/ArrowProgress.java $LB/RoadName.java"
        # optional native speed-limit prefix from package sl (speedlimit/), looked up by name: rg/lanes/slhook.py
        python3 -I "$H/lanes/slhook.py" "$LB" "$H/lanes" || fail "slhook.py"
        EXTRA="$EXTRA $LB/SpeedLimitText.java"
        # quiet-route hold for Apple Maps (Tomasz's MU1367 v1.4.4, Java only): rg/lanes/hold.py
        python3 -I "$H/lanes/hold.py" "$LB" "$H/lanes" || fail "hold.py"
        EXTRA="$EXTRA $LB/GuidanceEvidence.java"
        ID=pmcp-mu1161-rg-lanes-asf-2; WHAT="$WHAT + MU1367 v1.4.3 bargraph, road name, feed recovery + v1.4.4 quiet-route hold"
    fi
    if [ $MAN = yes ]; then
        python3 -I "$H/lanes/maneuvers.py" "$LB" "$H/lanes" || fail "maneuvers.py"
        ID=pmcp-mu1161-rg-lanes-asfm-2; WHAT="$WHAT + harman-f maneuver fallbacks"
    fi
    if [ $AA = yes ]; then
        python3 -I "$H/lanes/aa.py" "$LB" || fail "aa.py"
        ID=pmcp-mu1161-rg-lanes-asfm-aa-1; WHAT="$WHAT + Android Auto (pmcp gamma)"
    fi
    if [ $R146 = yes ]; then
        # tomasz-twardzicki MU1367 v1.4.5/v1.4.6 CarPlay guidance fixes (after aa.py, so aa.py's output is unchanged)
        python3 -I "$H/lanes/v146.py" "$LB" "$H/lanes" || fail "v146.py"
        cp "$H/lanes/TestPmcp146.java" "$LB/TestPmcp146.java"
        ID=pmcp-mu1161-rg-lanes-asfm-aa-r-1; WHAT="$WHAT + MU1367 v1.4.5/v1.4.6 reroute, placeholder, U-turn side, Apple names"
    fi
fi

# ---- HMI JAR -------------------------------------------------------------------------------------------
CLASSES="ManeuverDescriptor DistanceToNextManeuver RGStatus LaneGuidance DistanceToDestination TimeToDestination"
[ $ASF = no ] || CLASSES="$CLASSES TurnToInfo"
(cd "$W/stock" && for c in $CLASSES; do
    unzip -q "$STOCK_JAR" "$NAV/$c.class"; done)
echo 'package com.cpmap.rgi; public final class BuildInfo { public static final String ID="'"$ID"'"; public static final boolean RELEASE=true; }' > "$W/generated/BuildInfo.java"
javac --release 8 -nowarn -cp "$STOCK_JAR" -d "$W/helpers" \
    "$LB/LiveModel.java" "$LB/JournalReader.java" "$LB/MailboxReader.java" "$LB/LiveBridge.java" $EXTRA "$W/generated/BuildInfo.java"
javac -nowarn -cp "$CP" -d "$W/patcher" "$LB/PatchLive.java" "$H/patcher/GuardLive.java" "$BT/Guard.java" "$BT/RefCheck.java" \
    "$H/../hmiextras/patcher/Verify.java"
java -cp "$W/patcher:$CP" PatchLive "$W/stock" "$W/helpers" "$W/patched"
G="${MODE%-uturn}"; [ $ASF = no ] || G=lanes-asf   # lanes-uturn: same classes as lanes; -asf-m(-aa): as lanes-asf
java -cp "$W/patcher:$CP" GuardLive "$W/stock" "$W/patched" "$G"
if [ $AA = yes ]; then
    # A166: AID view signals (rg/kv, rg/patcher/PatchKombiView.java), helper compiled into the same jar
    KVC="de/vw/mib/asl/internal/mostkombi/streamsink/usecases/ChangeDataRate de/vw/mib/asl/internal/navigation/map/kombi/MapViewerKombiNotifierModel $NAV/ActiveRgType"
    mkdir -p "$W/kvstock"; (cd "$W/kvstock" && for c in $KVC; do unzip -q "$STOCK_JAR" "$c.class"; done)
    javac --release 8 -nowarn -cp "$STOCK_JAR" -d "$W/patched" "$H/kv/com/pmcp/kv/KombiView.java"
    javac -nowarn -cp "$CP:$W/patcher" -d "$W/patcher" "$H/patcher/PatchKombiView.java"
    java -cp "$W/patcher:$CP" PatchKombiView "$W/kvstock" "$W/patched"
fi
java -cp "$W/patcher:$CP" Verify "$W/patched" "$STOCK_JAR" $(find "$W/patched" -name '*.class' | sort)
for f in $(find "$W/patched" -name '*.class'); do [ "$(xxd -s 6 -l 2 -p "$f")" = 002e ] || fail "class version not 46: $f"; done
for f in $(cd "$W/helpers" && find . -name '*.class'); do [ -f "$W/patched/$f" ] || fail "helper class not packaged: $f"; done
python3 -I - "$W/patched" "$W/pmcp-rg.jar" "$WHAT" <<'EOF'
import os, sys, zipfile
src, dst, what = sys.argv[1:]
files = sorted(os.path.relpath(os.path.join(d, f), src) for d, _, fs in os.walk(src) for f in fs if f.endswith('.class'))
def add(z, name, data):
    i = zipfile.ZipInfo(name, date_time=(2026, 10, 21, 0, 0, 0)); i.compress_type = zipfile.ZIP_DEFLATED
    i.external_attr = 0o100644 << 16; z.writestr(i, data)
with zipfile.ZipFile(dst, 'w') as z:
    add(z, 'META-INF/MANIFEST.MF', ('Manifest-Version: 1.0\nCreated-By: pmcp package E (route guidance, %s), MU1161\n' % what).encode())
    for f in files: add(z, f, open(os.path.join(src, f), 'rb').read())
EOF
java -cp "$W/patcher:$CP" RefCheck "$STOCK_JAR" "$W/pmcp-rg.jar"
javac -nowarn -cp "$W/patched:$STOCK_JAR" -d "$W/tests" "$LB/TestLive.java" ${EXTRA:+"$TL"} \
    $([ $AA = yes ] && echo "$LB/TestAa.java") \
    $([ $R146 = yes ] && echo "$LB/TestReroute.java $LB/TestSourceName.java $LB/TestUturnSide.java $LB/TestPlaceholder.java $LB/TestQuietQnx.java $LB/TestPmcp146.java") $([ $ASF = yes ] && echo "$LB/TestArrow.java $LB/TestRoad.java $LB/TestRecovery.java $LB/TestQuietHold.java $LB/TestHoldPmcp.java $LB/TestSpeedLimitText.java") \
    $([ $MAN = yes ] && echo "$LB/TestManeuvers.java")
java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestLive > "$W/tests/result.json" || { cat "$W/tests/result.json"; fail "TestLive"; }
cat "$W/tests/result.json"; echo
if [ "$MODE" != base ]; then
    # lanes on OUR guarded classes: decoder, model, and the factory LaneGuidance builder (six-lane window, OEM setting)
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestLanes > "$W/tests/lanes.txt" || { cat "$W/tests/lanes.txt"; fail "TestLanes"; }
    grep -q '^LANES_PASS ' "$W/tests/lanes.txt" || fail "TestLanes: no LANES_PASS"; cat "$W/tests/lanes.txt"
fi
if [ $ASF = yes ]; then
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestArrow > "$W/tests/arrow.txt" || { cat "$W/tests/arrow.txt"; fail "TestArrow"; }
    grep -q '^ARROW_PROGRESS_PASS ' "$W/tests/arrow.txt" || fail "TestArrow: no ARROW_PROGRESS_PASS"; cat "$W/tests/arrow.txt"
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestRoad > "$W/tests/road.txt" || { cat "$W/tests/road.txt"; fail "TestRoad"; }
    grep -q '^ROAD_NAME_PASS ' "$W/tests/road.txt" || fail "TestRoad: no ROAD_NAME_PASS"; cat "$W/tests/road.txt"
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestRecovery "$W/tests/recovery" > "$W/tests/recovery.txt" || { cat "$W/tests/recovery.txt"; fail "TestRecovery"; }
    grep -q '^RECOVERY_PASS ' "$W/tests/recovery.txt" || fail "TestRecovery: no RECOVERY_PASS"; cat "$W/tests/recovery.txt"
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestQuietHold "$W/tests/quiet" > "$W/tests/quiet.txt" || { cat "$W/tests/quiet.txt"; fail "TestQuietHold"; }
    grep -q '^QUIET_HOLD_PASS ' "$W/tests/quiet.txt" || fail "TestQuietHold: no QUIET_HOLD_PASS"; cat "$W/tests/quiet.txt"
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestHoldPmcp "$W/tests/holdpmcp" > "$W/tests/holdpmcp.txt" || { cat "$W/tests/holdpmcp.txt"; fail "TestHoldPmcp"; }
    grep -q '^HOLD_PMCP_PASS ' "$W/tests/holdpmcp.txt" || fail "TestHoldPmcp: no HOLD_PMCP_PASS"; cat "$W/tests/holdpmcp.txt"
    # SpeedLimitText without sl, then with a stand-in sl helper (never packaged)
    mkdir -p "$W/slfake"; javac --release 8 -nowarn -d "$W/slfake" "$H/lanes/slfake/com/pmcp/sl/NativeSpeedLimit.java"
    for m in absent fake; do
        java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR$([ $m = fake ] && echo ":$W/slfake")" com.cpmap.rgi.TestSpeedLimitText $m \
            > "$W/tests/sl-$m.txt" || { cat "$W/tests/sl-$m.txt"; fail "TestSpeedLimitText $m"; }
        grep -q '^SPEED_LIMIT_TEXT_PASS ' "$W/tests/sl-$m.txt" || fail "TestSpeedLimitText $m: no PASS"; cat "$W/tests/sl-$m.txt"
    done
fi
if [ $MAN = yes ]; then
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestManeuvers > "$W/tests/maneuvers.txt" || { cat "$W/tests/maneuvers.txt"; fail "TestManeuvers"; }
    grep -q '^MANEUVERS_PASS ' "$W/tests/maneuvers.txt" || fail "TestManeuvers: no MANEUVERS_PASS"; cat "$W/tests/maneuvers.txt"
fi
if [ $AA = yes ]; then
    mkdir -p "$W/tests/kv"; javac -nowarn -cp "$W/pmcp-rg.jar:$STOCK_JAR" -d "$W/tests/kv" "$H/kv/test/TestKombiView.java"
    java -Xverify:all -cp "$W/tests/kv:$W/pmcp-rg.jar:$STOCK_JAR" com.pmcp.kv.TestKombiView "$W/tests/kv/kombi-view.log" > "$W/tests/kv.txt" \
        || { cat "$W/tests/kv.txt"; fail "TestKombiView"; }
    grep -q '^KOMBI_VIEW_PASS' "$W/tests/kv.txt" || fail "TestKombiView: no PASS"; cat "$W/tests/kv.txt"
    java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.TestAa > "$W/tests/aa.json" || { cat "$W/tests/aa.json"; fail "TestAa"; }
    cat "$W/tests/aa.json"; echo
fi
if [ $R146 = yes ]; then
    # each in its own JVM (static evidence counters and LiveBridge.INSTANCE start fresh)
    for t in TestReroute:REROUTE_PASS TestSourceName:SOURCE_NAME_PASS TestUturnSide:UTURN_SIDE_PASS TestPlaceholder:PLACEHOLDER_PASS \
             TestQuietQnx:QUIET_FACTORY_J9_PASS TestPmcp146:PMCP146_PASS; do
        c=${t%%:*}; m=${t#*:}
        java -Xverify:all -cp "$W/tests:$W/pmcp-rg.jar:$STOCK_JAR" com.cpmap.rgi.$c > "$W/tests/$c.txt" 2>&1 || { cat "$W/tests/$c.txt"; fail "$c"; }
        grep -q "^$m " "$W/tests/$c.txt" || fail "$c: no $m"; cat "$W/tests/$c.txt"
    done
fi
for c in $CLASSES; do
    norm() { sed -E "s/#[0-9]+(, *[0-9]+)?//; s#$NAV/$c\\.##g; s/^ *[0-9]+: //; s/[[:space:]]+/ /g"; }
    javap -p -c -constants -cp "$W/stock" "${NAV//\//.}.$c" | norm > "$W/report/$c.stock.txt"
    javap -p -c -constants -cp "$W/pmcp-rg.jar:$STOCK_JAR" "${NAV//\//.}.$c" | norm > "$W/report/$c.patched.txt"
    diff "$W/report/$c.stock.txt" "$W/report/$c.patched.txt" > "$W/report/$c.diff" || true
done

# ---- driver: Tomasz's chain on a "virtual MU1427 stock" (our code + his usage block), then our usage block back
"$PY" -I - "$BK/MU1161-appimg/armle/lib/dll/ipod-drvr-iap2.so" "$REL/driver/ipod-drvr-iap2.so" "$W/driver/virtual-mu1427-stock.so" <<'EOF'
import hashlib, sys
ours = open(sys.argv[1], 'rb').read(); his = open(sys.argv[2], 'rb').read()
A, B = 0xae3f0, 0xae490      # QNX usage block (DATE, version, TAGID, debuglink CRC): the only stock difference
virt = ours[:A] + his[A:B] + ours[B:]
assert hashlib.sha256(virt).hexdigest() == "0ac13f43d3fb259eee328c272fa1211bb558b6e2cd97c6e38ef38e4e71469d51", "not MU1427 code"
open(sys.argv[3], 'wb').write(virt)
EOF
"$PY" -I "$RG/patch-activation.py" "$W/driver/virtual-mu1427-stock.so" "$W/driver/b4-mu1427.so"
pin "$W/driver/b4-mu1427.so" 3760797aed4886a6c4480e3a8de79be427a3d8587450a56c424721306ca15d8b
python3 -I - "$BK/MU1161-appimg/armle/lib/dll/ipod-drvr-iap2.so" "$W/driver/b4-mu1427.so" "$W/ipod-drvr-iap2.so" <<'EOF'
import sys
ours = open(sys.argv[1], 'rb').read(); b4 = open(sys.argv[2], 'rb').read()
A, B = 0xae3f0, 0xae490
out = b4[:A] + ours[A:B] + b4[B:]
allowed = set(range(0x94, 0xb4))
for h in (0x63f0, 0x909c, 0x9260, 0xe138, 0x10ba8, 0x133a0): allowed.update(range(h, h + 4))
bad = [i for i in range(len(ours)) if ours[i] != out[i] and i not in allowed]
assert not bad, "unexpected changes %r" % [hex(i) for i in bad[:10]]
open(sys.argv[3], 'wb').write(out)
EOF

# ---- iap2.cfg: our factory file + Tomasz's [ident] section --------------------------------------------
cp "$BK/MU1161-system/mm/iap2.cfg" "$W/iap2.cfg"
printf '# pmcp route guidance (tomasz-twardzicki MU1427 B1 identification)\n[ident]\nsendmsgs=0x5200,0x5203\nrecvmsgs=0x5201,0x5202,0x5204\n' >> "$W/iap2.cfg"
cp "$REL/rgi-observer" "$W/rgi-observer"
# pmcp reader pmcp-r1 (rg/reader/reader.c, survives a stuck driver read), prebuilt in the repository so no QNX toolchain is
# needed; rg/reader/build.sh rebuilds it in docker
pin "$H/reader/prebuilt/rgi-observer" 3166df9b91119475f93043ac8c150e2641732e602161839a137a1907d4ef11df
cp "$H/reader/prebuilt/rgi-observer" "$W/rgi-observer-pmcp"

# ---- pmcp driver variant: Tomasz's RGI receive log only with /dev/shmem/pmcp-rgi-debug -----------
# rg/driver/log-gate.S assembled at 0xb571c, appended to the injected segment; one branch moved. The 76 assembled bytes are
# in the repository (rg/driver/log-gate.bin, pinned), so no QNX toolchain is needed; PMCP_GATE_REBUILD=1 assembles them
# again in docker (rg/driver/build-gate.sh) and must give the same bytes.
if [ "${PMCP_GATE:-1}" = 1 ]; then
    mkdir -p "$W/driver/gate"
    if [ "${PMCP_GATE_REBUILD:-0}" = 1 ]; then
        "$H/driver/build-gate.sh" "$W/driver/gate" > "$W/driver/gate/build.txt" 2>&1 || { cat "$W/driver/gate/build.txt"; fail "log gate build"; }
    else
        cp "$H/driver/log-gate.bin" "$W/driver/gate/log-gate.bin"
    fi
    pin "$W/driver/gate/log-gate.bin" c0c553567165efbfb3ccf63592ab3a7c8afe910a3ba4a5dcb85509820cebfc55
    python3 -I "$H/driver/patch-log-gate.py" "$W/ipod-drvr-iap2.so" "$W/driver/gate/log-gate.bin" "$W/ipod-drvr-iap2-gated.so"
    pin "$W/ipod-drvr-iap2-gated.so" 519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3
fi

{
    for f in pmcp-rg.jar ipod-drvr-iap2.so iap2.cfg rgi-observer ipod-drvr-iap2-gated.so rgi-observer-pmcp; do [ -f "$W/$f" ] || continue; echo "$f $(sha "$W/$f") $(wc -c < "$W/$f" | tr -d ' ')"; done
} | tee "$W/manifest.txt"
echo "built $W"
