#!/bin/ksh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp rescue card: runs in update mode (RUN_MODE=swdl). The HMI there is factory as far as we are concerned:
# our lsd.sh block does nothing when RUN_MODE=swdl (build_sd.py LSD_PRE, review 1 finding 3).
# Chain: Swdlautorun.txt in the SD root -> the unit enters software update (MIBRoot) ->
# M.I.B. 3.6.0 Launcher/final/finalScript.sh -> Launcher/stuff.sh -> this script (on RCC).
# Pattern: luka-dev rescue card (confirmed in a car, mib2q-carplay-rgi issue #24) and
# ProManiFest2122 port_k3346/ratunek (MU1438). Written for our layout, MU1161.
#
# It undoes ONLY what the HMI reads at start, so the HMI comes up as factory:
#   1. lsd.sh: replaced by the factory copy kept in /mnt/app/carplaymaps/rollback/lsd.sh
#      (only if the live one is not the factory size and the copy is exactly the factory size
#      and does not contain our block);
#   2. our JARs in /mnt/app/eso/hmi/lsd/jars (NavActiveIgnore.jar, pmcp-*.jar) are removed;
#   3. /mnt/persist/pmcp/DISABLED is written, so our lsd.sh block (if 1 failed) loads nothing;
#      last-boot is removed, so GEM "Potwierdz" cannot confirm anything until the next real trial boot;
#   4. package E system part (patched iAP2 driver, iap2.cfg [ident]) back to the factory copies kept in
#      /mnt/app/carplaymaps/rollback, by size (only if live = our size and copy = factory size); the reader stops
#      because SYSTEM_ON is removed. mm-ipod is not the HMI, but CarPlay itself must work after a rescue.
# The video part (dio_manager wrapper, /mnt/app/carplaymaps) stays; "Przywroc" in GEM removes it later.
# On a unit without pmcp it changes nothing and only writes the log (test before stage B).
#
# Lessons from ProManiFest2122 (first in-car test left no log): in update mode the script runs on RCC
# with a poor PATH, and the SD card is read-only until M.I.B. remounts it. So: M.I.B.'s PATH, log to RAM
# first, never put an action behind a log redirect.
#
#   pmcp-ratunek.sh HW MEDIUM          rescue (called at the start of stuff.sh)
#   pmcp-ratunek.sh --save-log MEDIUM  only move the RAM log to the card (end of stuff.sh)

N=${PMCP_RESCUE_TEST_ROOT:-}/net/mmx
SHM=${PMCP_RESCUE_TEST_ROOT:-}/net/rcc/dev/shmem
export PATH=/proc/boot:/sbin:/bin:/usr/bin:/usr/sbin:/net/mmx/bin:/net/mmx/usr/bin:/net/mmx/usr/sbin:/net/mmx/sbin:/net/mmx/mnt/app/armle/bin:/net/mmx/mnt/app/armle/sbin:/net/mmx/mnt/app/armle/usr/bin:/net/mmx/mnt/app/armle/usr/sbin
export LD_LIBRARY_PATH=/net/mmx/mnt/app/root/lib-target:/net/mmx/mnt/eso/lib:/net/mmx/eso/lib:/net/mmx/mnt/app/usr/lib:/net/mmx/mnt/app/armle/lib:/net/mmx/mnt/app/armle/lib/dll:/net/mmx/mnt/app/armle/usr/lib
[ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] && export PATH=/bin:/usr/bin

MODE=rescue
if [ "$1" = "--save-log" ]; then MODE=log; MED="${2:-$N/fs/sda0}"; else MED="${2:-$N/fs/sda0}"; fi
LOGFILE="$MED/PMCP_RATUNEK_LOG.txt"
RAM="$SHM/pmcp-ratunek.log"
( : >> "$RAM" ) 2>/dev/null || RAM=/tmp/pmcp-ratunek.log

APP="$N/mnt/app"
LSD="$APP/eso/hmi/lsd/lsd.sh"
JARS="$APP/eso/hmi/lsd/jars"
ROOT="$APP/carplaymaps"
PERSIST="$N/mnt/persist/pmcp"
FACTORY_LSD_SIZE=16567
DRV="$APP/armle/lib/dll/ipod-drvr-iap2.so"
CFG="$N/mnt/system/etc/mm/iap2.cfg"
FACTORY_DRV_SIZE=739925
OUR_DRV_SIZE=743196
FACTORY_CFG_SIZE=5951
OUR_CFG_SIZE=6079

log() { echo "$*" >> "$RAM" 2>/dev/null; }

save_log() {
    if [ ! -s "$RAM" ]; then rm -f "$RAM" 2>/dev/null; return 0; fi
    [ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] || mount -uw "$MED" 2>/dev/null
    if cat "$RAM" >> "$LOGFILE" 2>/dev/null; then
        rm -f "$RAM" 2>/dev/null
        sync 2>/dev/null
    fi
    return 0
}

if [ "$MODE" = log ]; then
    save_log
    exit 0
fi

size_of() {
    l=`ls -ln "$1" 2>/dev/null` || return 1
    set -- $l
    echo "$5"
}

# true if FILE contains our lsd.sh block marker (shell builtins only)
has_pmcp_block() {
    while read line; do
        case "$line" in *">>> pmcp"*) return 0 ;; esac
    done < "$1"
    return 1
}

state() {
    for f in "$LSD" "$ROOT/rollback/lsd.sh" "$JARS/NavActiveIgnore.jar" "$JARS"/pmcp-*.jar "$PERSIST/DISABLED" "$PERSIST/last-boot" \
        "$DRV" "$ROOT/rollback/ipod-drvr-iap2.so" "$CFG" "$ROOT/rollback/iap2.cfg" "$ROOT/rg/SYSTEM_ON"; do
        if [ -e "$f" ]; then log "  jest: $f (`size_of "$f"` B)"; else log "  brak: $f"; fi
    done
}

restore_by_size() {
    [ "`size_of "$1"`" = "$3" ] && [ "`size_of "$2"`" = "$4" ] || return 0
    rm -f "$1.pmcp-ratunek" 2>/dev/null
    cp "$2" "$1.pmcp-ratunek" 2>/dev/null
    if [ "`size_of "$1.pmcp-ratunek"`" = "$4" ]; then
        chmod "$5" "$1.pmcp-ratunek" 2>/dev/null
        mv -f "$1.pmcp-ratunek" "$1" 2>/dev/null
    else
        rm -f "$1.pmcp-ratunek" 2>/dev/null
    fi
}

# One attempt; no action is behind a redirect to the log.
attempt() {
    [ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] || mount -uw "$N/mnt/app" 2>/dev/null
    if [ -d "$ROOT" ]; then
        [ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] || mount -uw "$N/mnt/persist" 2>/dev/null
        mkdir -p "$PERSIST" 2>/dev/null
        touch "$PERSIST/DISABLED" 2>/dev/null
        rm -f "$PERSIST/last-boot" 2>/dev/null
        rm -f "$ROOT/rg/SYSTEM_ON" 2>/dev/null
    fi
    # same file, factory copy by size: FILE COPY OUR_SIZE FACTORY_SIZE
    restore_by_size "$DRV" "$ROOT/rollback/ipod-drvr-iap2.so" "$OUR_DRV_SIZE" "$FACTORY_DRV_SIZE" 755
    if [ "`size_of "$CFG"`" = "$OUR_CFG_SIZE" ]; then
        [ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] || mount -uw "$N/mnt/system" 2>/dev/null
        restore_by_size "$CFG" "$ROOT/rollback/iap2.cfg" "$OUR_CFG_SIZE" "$FACTORY_CFG_SIZE" 644
    fi
    if [ "`size_of "$LSD"`" != "$FACTORY_LSD_SIZE" ] && [ "`size_of "$ROOT/rollback/lsd.sh"`" = "$FACTORY_LSD_SIZE" ] \
        && ! has_pmcp_block "$ROOT/rollback/lsd.sh"; then
        rm -f "$LSD.pmcp-ratunek" 2>/dev/null
        cp "$ROOT/rollback/lsd.sh" "$LSD.pmcp-ratunek" 2>/dev/null
        if [ "`size_of "$LSD.pmcp-ratunek"`" = "$FACTORY_LSD_SIZE" ] && ! has_pmcp_block "$LSD.pmcp-ratunek"; then
            chmod 755 "$LSD.pmcp-ratunek" 2>/dev/null
            mv -f "$LSD.pmcp-ratunek" "$LSD" 2>/dev/null
        else
            rm -f "$LSD.pmcp-ratunek" 2>/dev/null
        fi
    fi
    rm -f "$JARS/NavActiveIgnore.jar" 2>/dev/null
    for j in "$JARS"/pmcp-*.jar; do [ -e "$j" ] && rm -f "$j" 2>/dev/null; done
    sync 2>/dev/null
}

# Done when MMX is reachable and the HMI start is factory as far as we are concerned.
done_ok() {
    [ -d "$JARS" ] || return 1
    [ ! -e "$JARS/NavActiveIgnore.jar" ] || return 1
    for j in "$JARS"/pmcp-*.jar; do [ -e "$j" ] && return 1; done
    [ -s "$LSD" ] || return 1
    has_pmcp_block "$LSD" && return 1
    [ "`size_of "$DRV"`" != "$OUR_DRV_SIZE" ] || return 1
    [ "`size_of "$CFG"`" != "$OUR_CFG_SIZE" ] || return 1
    return 0
}

log "=== PMCP RATUNEK start ==="
log "`date 2>&1`"
log "nosnik=$MED hw=$1"
for t in rm cp mv cat mount ls sync sleep mkdir touch chmod; do log "`type "$t" 2>&1`"; done
[ -n "${PMCP_RESCUE_TEST_ROOT:-}" ] || mount -uw "$MED" 2>/dev/null
log "--- PRZED:"
state

OK=0
i=0
while [ $i -lt 6 ]; do
    attempt
    if done_ok; then OK=1; break; fi
    log "proba $i: MMX nieosiagalny albo zmiany sie nie udaly, ponawiam za 10 s"
    sleep ${PMCP_RESCUE_TEST_SLEEP:-10}
    i=$((i + 1))
done

log "--- PO:"
state
if [ $OK -eq 1 ]; then
    log "WYNIK=OK (start HMI fabryczny; potem w GEM: pmcp -> Przywroc pliki fabryczne)"
else
    log "WYNIK=NIEPEWNY (MMX nieosiagalny albo pliki nadal sa; pokaz ten log)"
fi
log "=== PMCP RATUNEK koniec ==="
save_log
exit 0
