#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp experimental Android Auto: replaces /mnt/app/eso/bin/apps/gal (smartphone_integrator starts it for every AA
# phone, see smartphone_integrator.json "children"/"gal"). Starts the factory gal, copied by pmcp.sh to aa/gal.real,
# with the gal hook only when the current AA set is confirmed or on its trial; otherwise exactly the factory gal
# (environment untouched).
#
# Trial: aa/AA_BOOT holds one set id (written by pmcp.sh with one mv). A new set runs with the hook during ONE unit start:
# the first AA connection after the change marks it (persist trial.<id> + /ramdisk marker), later connections in the
# same start see the /ramdisk marker. After a restart without "Confirm AA" (pmcp.sh aa-confirm) gal is factory again.
# /mnt/persist/pmcp/DISABLED (rescue card) or AA_DISABLED switch the hook off. No hashing here: pmcp.sh verified
# every file when it installed them, and gal must start within smartphone_integrator's startupTimeout.
AA=/mnt/app/carplaymaps/aa
REAL=$AA/gal.real
P=/mnt/persist/pmcp
if test ! -x "$REAL"; then
    echo "pmcp-aa: $REAL missing" > /ramdisk/pmcp-aa-last 2>/dev/null
    exit 127
fi
USE=no
SET=
if test ! -e $P/DISABLED && test ! -e $P/AA_DISABLED && test -s $AA/AA_BOOT && read SET < $AA/AA_BOOT && test -n "$SET"; then
    if test -e "$P/aa-ok.$SET"; then
        USE=yes
    elif test -e "/ramdisk/pmcp-aa-trial.$SET"; then
        USE=trial
    elif test ! -e "$P/aa-trial.$SET" && mkdir -p $P 2>/dev/null && touch "$P/aa-trial.$SET" 2>/dev/null \
        && test -e "$P/aa-trial.$SET" && touch "/ramdisk/pmcp-aa-trial.$SET" 2>/dev/null; then
        USE=trial
    fi
fi
# Capture (pmcp.sh aa-capture, analysis mode with a confirmed set): protocol 1.7 from the next AA connection to the end of
# that unit start, to log what Google Maps sends for navigation. The persist marker is removed before anything uses it, so
# the following unit start is 1.5 again whatever happens; /ramdisk/pmcp-aa-capture keeps reconnections of the start on 1.7.
CAPTURE=no
if test $USE != no; then
    if test -e /ramdisk/pmcp-aa-capture; then
        CAPTURE=yes
    elif test -e $P/aa-capture && rm -f $P/aa-capture 2>/dev/null && test ! -e $P/aa-capture \
        && touch /ramdisk/pmcp-aa-capture 2>/dev/null; then
        CAPTURE=yes
    fi
fi
echo "set=$SET use=$USE capture=$CAPTURE" > /ramdisk/pmcp-aa-last 2>/dev/null
if test $USE != no && test -r $AA/libgal_hook.so && test -r $AA/gal-hook.conf && test -x $AA/aa-most-feeder; then
    # The hook reads only this file (patch_no_sd.py removed the SD card and /tmp fallbacks) and starts only this player.
    export GAL_HOOK_CONF=$AA/gal-hook.conf
    export GAL_PLAYER_PATH=$AA/aa-most-feeder
    export GAL_HOOK_LOG=/ramdisk/pmcp-gal-hook.log
    export GAL_HOOK_LOG_MAX_KB=128   # /ramdisk: 20 MB, 16 MB of it the video ring
    if test $CAPTURE = yes; then
        # the environment wins over gal-hook.conf (the hook sets file keys with setenv(..., 0))
        export GAL_DUALSCREEN_AAP_MINOR=7
        export GAL_HOOK_NAV_LOG_MAX=60   # 0x8006 and 0x8007 each, whole message in hex
        export GAL_HOOK_LOG_MAX_KB=512
    fi
    export LD_PRELOAD=$AA/libgal_hook.so${LD_PRELOAD:+:$LD_PRELOAD}
fi
exec "$REAL" "$@"
