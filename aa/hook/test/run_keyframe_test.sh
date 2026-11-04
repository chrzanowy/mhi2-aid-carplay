#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Host test of patch_keyframe.py and patch_config_kf.py (see keyframe_test.c): the pinned MacsInSpace focus_ctl.c and vc_stream_out.c after both
# pmcp patches, built with the host compiler and run against fake gal / phone / player. Uses /tmp/gal_ack.sock.
#
#   run_keyframe_test.sh [workdir]
set -euo pipefail
H=$(cd "$(dirname "$0")/.." && pwd)
WS=$(cd "$H/../../.." && pwd)
MACS="${PMCP_MACS:-$WS/upstream/macsinspace}"
COMMIT=$(sed -n 's/^COMMIT=\([0-9a-f]*\).*/\1/p' "$H/build.sh")
W=${1:-$(mktemp -d /tmp/pmcp-kf-test.XXXXXX)}
mkdir -p "$W/src"
git -C "$MACS" archive "$COMMIT" src | tar -x -C "$W/src"
python3 -I "$H/patch_no_sd.py" "$W/src"
python3 -I "$H/patch_keyframe.py" "$W/src"
python3 -I "$H/patch_config_kf.py" "$W/src"
cc -O1 -g -Wall -Wextra -std=gnu99 -pthread -I"$W/src/src" \
    "$W/src/src/focus_ctl.c" "$W/src/src/vc_stream_out.c" "$H/test/keyframe_test.c" -o "$W/keyframe_test"
"$W/keyframe_test"
