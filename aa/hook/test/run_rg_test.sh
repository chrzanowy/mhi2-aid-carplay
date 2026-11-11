#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Host test of pmcp_rg.c against tomasz-twardzicki's rg bridge decoder (MailboxReader + LiveModel, unchanged, from
# upstream/tomasz 024dd159 MU1427/route-guidance/bridge, or PMCP_TOMASZ_BRIDGE). Needs cc and a JDK.
set -euo pipefail
H=$(cd "$(dirname "$0")/.." && pwd)
WS=$(cd "$H/../../.." && pwd)   # workspace root: upstream/ next to the repository (as for rg/build.sh)
BR="${PMCP_TOMASZ_BRIDGE:-$WS/upstream/tomasz/MU1427/route-guidance/bridge}"
W=$(mktemp -d /tmp/pmcp-rg-test.XXXXXX)
cc -O1 -g -Wall -Wextra -Werror -std=gnu99 -pthread -I"$H" "$H/pmcp_rg.c" "$H/test/rg_test.c" -o "$W/rg_test"
mkdir "$W/rg" "$W/classes"
GAL_PMCP_RG=1 GAL_PMCP_RG_STALE_MS=3000 GAL_PMCP_RG_END_MS=9000 GAL_PMCP_RG_DIR="$W/rg" GAL_PMCP_RG_STATUS="$W/rg.txt" \
    GAL_PMCP_RG_RAW="$W/raw.txt" "$W/rg_test"
echo "--- status file"; cat "$W/rg.txt"
# A165: the raw dump has the navigation messages as protobuf trees, 0x8006 only when it changed
echo "--- raw dump"; cat "$W/raw.txt"
n6=$(grep -c ' 8006 len=' "$W/raw.txt" || true); n3=$(grep -c ' 8003 len=' "$W/raw.txt" || true)
grep -q '^t=[0-9]*\.[0-9]s 8006 len=[0-9]* | 1:{1:{1:' "$W/raw.txt" && [ "$n6" -ge 1 ] && [ "$n3" -ge 1 ] \
    && grep -q '^surowe: linie=' "$W/rg.txt" || { echo "FAIL: raw dump (8006=$n6 8003=$n3)"; exit 1; }
echo "ok    raw dump: 0x8006=$n6 0x8003=$n3 lines, nested fields decoded"
javac -nowarn -d "$W/classes" "$BR/LiveModel.java" "$BR/MailboxReader.java" "$H/test/TestAaRg.java" 2>&1 | grep -v "^Note:" || true
java -cp "$W/classes" com.cpmap.rgi.TestAaRg "$W/rg"
# Optional: the same steps through the staged rg classes (rg/build.sh <lsd> <dir> lanes-uturn-asf-m-aa leaves them in
# <dir>/lanes/guidance-src, and BuildInfo.java in <dir>/generated); PMCP_RG_STAGED=<that guidance-src>
# PMCP_LSD_JAR=<converted MU1161 lsd.jar>. LiveBridge is needed since v1.5.0 (ArrowProgress/RoadName/FeedRecovery ask it
# for the AA hold).
if [ -n "${PMCP_RG_STAGED:-}" ]; then
    mkdir "$W/staged"
    javac -nowarn -cp "${PMCP_LSD_JAR:?set PMCP_LSD_JAR}" -d "$W/staged" "$PMCP_RG_STAGED"/{LiveModel,MailboxReader,LaneData,RoadName,ArrowProgress,FeedRecovery,JournalReader,GuidanceEvidence,SpeedLimitText,LiveBridge}.java \
        "$PMCP_RG_STAGED/../../generated/BuildInfo.java" "$H/test/TestAaRg.java" "$H/test/TestAaRgAsf.java" 2>&1 | grep -v "^Note:" || true
    java -cp "$W/staged:$PMCP_LSD_JAR" com.cpmap.rgi.TestAaRg "$W/rg"
    java -cp "$W/staged:$PMCP_LSD_JAR" com.cpmap.rgi.TestAaRgAsf "$W/rg"
fi
