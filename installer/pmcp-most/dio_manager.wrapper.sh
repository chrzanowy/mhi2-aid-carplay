#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp experimental cards only (GEM "Bridge: use pmcp-most"): mathsls's dio_manager.wrapper.sh (GPL-3.0,
# upstream/mathsls/MU1161/791_AID12.3/payload/common, sha256 8c12f697...) unchanged, plus one block before the exec:
# the MOST contract owner for the wired CarPlay stream (docs/en/07-installer.md, "Experimental: own MOST bridge").

ROOT=/mnt/app/carplaymaps
REAL="$ROOT/stock_first/dio_manager.real"
CORE="$ROOT/core.so"
SEC="$ROOT/libcarplay-security-bridge.so"
PAIR_ROOT="$ROOT/security_bridge"
PAIR_HELPER="$PAIR_ROOT/carplay-pairing-helper"
PAIR_CORE="$PAIR_ROOT/libCarPlayPairingCore.so"
SUPERVISOR="$ROOT/carplay-cluster-supervisor"
BRIDGE="$ROOT/altscreen-most-bridge"
LOG=/ramdisk/carplaymaps-launcher.log
PIDFILE=/ramdisk/carplay-dio-manager.pid

log_line() {
    echo "$1" >> "$LOG" 2>/dev/null || true
}

if test ! -x "$REAL" || test ! -r "$CORE"; then
    log_line "fatal=runtime-missing"
    exit 127
fi

export IPL_CONFIG_DIR=/etc/eso/production
export IPL_CONFIG_DIR_DIO_MANAGER=/etc/eso/production
export PATH=/proc/boot:/sbin:/bin:/usr/bin:/usr/sbin:/armle/usr/bin:/armle/usr/sbin:/armle/sbin:/armle/bin
export LD_LIBRARY_PATH=/mnt/app/root/lib-target:/eso/lib:/mnt/app/usr/lib:/mnt/app/armle/lib:/mnt/app/armle/lib/dll:/mnt/app/armle/usr/lib
export CARPLAY_ALTSCREEN_ENABLE=1
export CARPLAY_ALTSCREEN_LOG=/dev/null
export CARPLAY_ALTSCREEN_CAPTURE_DIR=/ramdisk
unset CARPLAY_CLUSTER_INTRO
unset CARPLAY_CLUSTER_INTRO_FPS

echo $$ > "$PIDFILE" 2>/dev/null || true

if test -x "$SUPERVISOR" && test -x "$BRIDGE"; then
    (
        unset LD_PRELOAD
        "$SUPERVISOR" >/dev/null 2>&1
    ) &
    log_line "cluster-supervisor=start-requested"
fi

PRELOAD="$CORE"
if test -r "$SEC"; then
    PRELOAD="$CORE:$SEC"
    export CARPLAY_SECURITY_BRIDGE_LOG=/dev/null
    if test -x "$PAIR_HELPER" && test -r "$PAIR_CORE"; then
        (
            unset LD_PRELOAD
            export LD_LIBRARY_PATH="$PAIR_ROOT:$LD_LIBRARY_PATH"
            export CARPLAY_PAIRING_STORE="$PAIR_ROOT"
            "$PAIR_HELPER" --server >/dev/null 2>&1
        ) &
        log_line "pairing-helper=start-requested"
    fi
fi

if test -r "$ROOT/libcardshim.so"; then
    PRELOAD="$ROOT/libcardshim.so:$PRELOAD"
    log_line "cardshim=preloaded"
fi

# pmcp: MOST contract v1.1 (bridge/contract/pmcp_most_contract.h, 2.1 owner, 2.2 session). This wrapper holds the
# owner of the wired CarPlay stream on behalf of core.so (src=wired kind=proxy). Its pid stays the pid of dio_manager
# after the exec below, so the owner lives exactly as long as the process that writes the ring. Taken when there is no
# owner, its pid is dead, it is Wi-Fi (the cable wins) or an earlier start of this same wired source (only one factory
# dio_manager runs). gen = previous + 1, 0 skipped. The unit shell has no millisecond monotonic clock: since_ms=0 and
# ts_ms=0 (since_ms=0 = the 10 s age rule does not apply; the session start is written right away anyway). No 20 ms
# re-verify (no sub-second sleep in this shell). Best effort, in a subshell without LD_PRELOAD: any failure leaves the
# files as they were and dio_manager starts as before.
(
    unset LD_PRELOAD
    MS=/ramdisk/most-src
    mkdir -p $MS || exit 0
    G=0; OP=; OS=
    if test -f $MS/owner && read L < $MS/owner; then
        for W in $L; do
            case $W in gen=*) G=${W#gen=} ;; pid=*) OP=${W#pid=} ;; src=*) OS=${W#src=} ;; esac
        done
    fi
    # not a number, or 10 digits (near the u32 wrap, beyond this shell's 32-bit arithmetic): start again at 1
    case $G in ""|*[!0-9]*|??????????*) G=0 ;; esac
    case $OP in ""|*[!0-9]*) OP= ;; esac
    if test -n "$OP" && test "$OS" != wireless && test "$OS" != wired && kill -0 $OP; then
        exit 0
    fi
    N=$((G + 1))
    rm -f $MS/owner.tmp.$$ $MS/wired.session.tmp.$$
    echo "v=1 src=wired pid=$$ gen=$N since_ms=0 kind=proxy" > $MS/owner.tmp.$$ || exit 0
    mv -f $MS/owner.tmp.$$ $MS/owner || exit 0
    echo "v=1 state=start gen=$N pid=$$ ts_ms=0 reason=start" > $MS/wired.session.tmp.$$ || exit 0
    mv -f $MS/wired.session.tmp.$$ $MS/wired.session
) >/dev/null 2>&1

export LD_PRELOAD="$PRELOAD"
log_line "launch=carplay-maps-video-only"
exec "$REAL" "$@"

log_line "fatal=dio-manager-exec-failed"
exit 126
