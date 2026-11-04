#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Host test of pmcp_rg.c against tomasz-twardzicki's rg bridge decoder (MailboxReader + LiveModel, unchanged, from
# upstream/tomasz 024dd159 MU1427/route-guidance/bridge, or PMCP_TOMASZ_BRIDGE). Needs cc and a JDK.
set -euo pipefail
H=$(cd "$(dirname "$0")/.." && pwd)
WS=$(cd "$H/../../../.." && pwd)   # workspace root: upstream/ next to publish/
BR="${PMCP_TOMASZ_BRIDGE:-$WS/upstream/tomasz/MU1427/route-guidance/bridge}"
W=$(mktemp -d /tmp/pmcp-rg-test.XXXXXX)
cc -O1 -g -Wall -Wextra -Werror -std=gnu99 -pthread -I"$H" "$H/pmcp_rg.c" "$H/test/rg_test.c" -o "$W/rg_test"
mkdir "$W/rg" "$W/classes"
GAL_PMCP_RG=1 GAL_PMCP_RG_STALE_MS=3000 GAL_PMCP_RG_END_MS=9000 GAL_PMCP_RG_DIR="$W/rg" GAL_PMCP_RG_STATUS="$W/rg.txt" "$W/rg_test"
echo "--- status file"; cat "$W/rg.txt"
javac -nowarn -d "$W/classes" "$BR/LiveModel.java" "$BR/MailboxReader.java" "$H/test/TestAaRg.java" 2>&1 | grep -v "^Note:" || true
java -cp "$W/classes" com.cpmap.rgi.TestAaRg "$W/rg"
# Optional: the same steps through the staged rgluasf(a) classes (rg/build.sh <lsd> <dir> lanes-uturn-asf-aa leaves them in
# <dir>/lanes/guidance-src); PMCP_RG_STAGED=<that guidance-src> PMCP_LSD_JAR=<converted MU1161 lsd.jar>
if [ -n "${PMCP_RG_STAGED:-}" ]; then
    mkdir "$W/staged"
    javac -nowarn -cp "${PMCP_LSD_JAR:?set PMCP_LSD_JAR}" -d "$W/staged" "$PMCP_RG_STAGED"/{LiveModel,MailboxReader,LaneData,RoadName,ArrowProgress,FeedRecovery,JournalReader}.java \
        "$H/test/TestAaRg.java" "$H/test/TestAaRgAsf.java" 2>&1 | grep -v "^Note:" || true
    java -cp "$W/staged:$PMCP_LSD_JAR" com.cpmap.rgi.TestAaRg "$W/rg"
    java -cp "$W/staged:$PMCP_LSD_JAR" com.cpmap.rgi.TestAaRgAsf "$W/rg"
fi
