#!/bin/ksh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp log card: runs in update mode (RUN_MODE=swdl) at the END of M.I.B.'s Launcher/stuff.sh, when M.I.B. has made the
# card writable. Chain as on the rescue card: Swdlautorun.txt -> software update -> M.I.B. finalScript.sh -> stuff.sh.
#
# Read-only on the unit. It copies to PMCP_LOGS/ on this card:
#   - the AA logs saved in GEM by "AA save log" (pmcp.sh aa-log-save): /mnt/app/carplaymaps/logs/aa-log-*.txt;
#   - the CarPlay logs saved by "CP save log" (pmcp.sh cp-log-save): /mnt/app/carplaymaps/logs/cp-log-*.txt;
#   - pmcp's boot log, GEM button log and markers from /mnt/persist/pmcp (boot.log, gem.log, last-boot, the marker list).
# Existing files on the card are never overwritten (a number is added). Nothing on the unit is changed or deleted:
# "Delete saved logs" in GEM does that once the copies are checked on a computer.
# Lessons of the rescue card apply: M.I.B.'s PATH, no action behind a redirect, the result line last.
#
#   pmcp-logs.sh MEDIUM

N=${PMCP_LOGCARD_TEST_ROOT:-}/net/mmx
export PATH=/proc/boot:/sbin:/bin:/usr/bin:/usr/sbin:/net/mmx/bin:/net/mmx/usr/bin:/net/mmx/usr/sbin:/net/mmx/sbin:/net/mmx/mnt/app/armle/bin:/net/mmx/mnt/app/armle/sbin:/net/mmx/mnt/app/armle/usr/bin:/net/mmx/mnt/app/armle/usr/sbin
export LD_LIBRARY_PATH=/net/mmx/mnt/app/root/lib-target:/net/mmx/mnt/eso/lib:/net/mmx/eso/lib:/net/mmx/mnt/app/usr/lib:/net/mmx/mnt/app/armle/lib:/net/mmx/mnt/app/armle/lib/dll:/net/mmx/mnt/app/armle/usr/lib
[ -n "${PMCP_LOGCARD_TEST_ROOT:-}" ] && export PATH=/bin:/usr/bin

MED="${1:-$N/fs/sda0}"
OUT="$MED/PMCP_LOGS"
LOGS="$N/mnt/app/carplaymaps/logs"
PERSIST="$N/mnt/persist/pmcp"

[ -n "${PMCP_LOGCARD_TEST_ROOT:-}" ] || mount -uw "$MED" 2>/dev/null
mkdir -p "$OUT" 2>/dev/null
RES="$OUT/PMCP_LOGS_RESULT.txt"

log() { echo "$*" >> "$RES" 2>/dev/null; }

size_of() {
    l=`ls -ln "$1" 2>/dev/null` || return 1
    set -- $l
    echo "$5"
}

# first free name on the card: NAME, NAME-2, NAME-3 ... (never overwrite)
free_name() {
    _b=${1%.txt}
    _d="$OUT/$1"; _i=2
    while [ -e "$_d" ]; do _d="$OUT/$_b-$_i.txt"; _i=$((_i + 1)); done
    echo "$_d"
}

COPIED=0
FAILED=0
copy_one() {
    _dst=`free_name "$2"`
    cp "$1" "$_dst" 2>/dev/null
    if [ -n "`size_of "$1"`" ] && [ "`size_of "$_dst"`" = "`size_of "$1"`" ]; then
        COPIED=$((COPIED + 1)); log "copied $1 -> ${_dst##*/} (`size_of "$_dst"` B)"
    else
        FAILED=$((FAILED + 1)); log "FAILED $1 -> ${_dst##*/}"
    fi
}

log "=== PMCP LOGS start"
log "`date 2>&1`"
log "medium=$MED"
AA=0
for f in "$LOGS"/aa-log-*.txt; do
    [ -f "$f" ] || continue
    AA=$((AA + 1))
    copy_one "$f" "${f##*/}"
done
CP=0
for f in "$LOGS"/cp-log-*.txt; do
    [ -f "$f" ] || continue
    CP=$((CP + 1))
    copy_one "$f" "${f##*/}"
done
[ -f "$PERSIST/boot.log" ] && copy_one "$PERSIST/boot.log" pmcp-boot-log.txt
[ -f "$PERSIST/last-boot" ] && copy_one "$PERSIST/last-boot" pmcp-last-boot.txt
# GEM button log (pmcp.sh: every button's output; the SD card is read-only in GEM), older half first
[ -f "$PERSIST/gem.log.1" ] && copy_one "$PERSIST/gem.log.1" pmcp-gem-log-1.txt
[ -f "$PERSIST/gem.log" ] && copy_one "$PERSIST/gem.log" pmcp-gem-log.txt
# experimental cards: phone video recorded by the experimental feeder (GEM "AA record"), for the pmcp bridge host tests
[ -f "$PERSIST/aa-stream.h264" ] && copy_one "$PERSIST/aa-stream.h264" aa-stream.h264
[ -f "$PERSIST/aa-stream.h264.idx" ] && copy_one "$PERSIST/aa-stream.h264.idx" aa-stream.h264.idx
log "markers in /mnt/persist/pmcp: `ls "$PERSIST" 2>&1`"
sync 2>/dev/null
if [ $FAILED -gt 0 ]; then
    log "RESULT=FAILED copied=$COPIED failed=$FAILED aa_logs=$AA cp_logs=$CP"
elif [ $((AA + CP)) -eq 0 ]; then
    log "RESULT=NO_LOGS copied=$COPIED (run AA save log or CP save log in GEM first)"
else
    log "RESULT=OK copied=$COPIED aa_logs=$AA cp_logs=$CP"
fi
log "=== PMCP LOGS end"
sync 2>/dev/null
exit 0
