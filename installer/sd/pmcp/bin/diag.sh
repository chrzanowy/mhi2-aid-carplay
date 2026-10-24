#!/bin/ksh
# SPDX-License-Identifier: GPL-3.0-or-later
# pmcp diagnostics, GEM button "0. Diagnostyka". Writes nothing to the unit; only tries to write its own log on the SD card.
# Answers three questions from the 2026-10-23 verify failures in the car:
#   G: what gawk 3.1.5 on MMX does with bytes >= 128 under each locale (byte table size must be 256)
#   S: whether the factory sha1sum/cksum (RCC /usr/bin) or the M.I.B. sha1sum on the card give the known values
#   W: why the SD card refused our log, and whether a remount fixes it
# Every command runs with stderr shown and its exit code printed; nothing stops the script early.
SD="${0%/bin/*}"
CARD="${SD%/*}"
G=/mnt/app/armle/usr/bin/gawk
E=/mnt/app/armle/usr/bin/env
ALL=""
p() { echo "$*"; ALL="$ALL$*
"; }
run1() { _l=$1; shift; _o=`"$@" 2>&1`; _rc=$?; p "$_l rc=$_rc: $_o"; }

p "pmcp diag card=$CARD"
if [ -s /ifs/lsd.jxe ]; then p "node: MMX (local /ifs/lsd.jxe)"; else p "node: not MMX (no local /ifs/lsd.jxe)"; fi
p "env here: LANG=${LANG:-} LC_ALL=${LC_ALL:-} LC_CTYPE=${LC_CTYPE:-} uid=`id -u 2>&1`"
on -f mmx $E 2>&1 | while read _x; do case "$_x" in LANG=*|LC_*) p "env on mmx: $_x" ;; esac; done

p "--- G: want tab=256 c200=1 (byte table ok)"
T='BEGIN { for (i = 0; i < 256; i++) o[sprintf("%c", i)] = i; n = 0; for (k in o) n++; printf "tab=%d c200=%d", n, length(sprintf("%c", 200)) }'
run1 "G1 plain      " on -f mmx $G "$T"
run1 "G2 C          " on -f mmx $E LC_ALL=C LANG=C $G "$T"
run1 "G3 POSIX      " on -f mmx $E LC_ALL=POSIX LANG=POSIX $G "$T"
run1 "G4 C-TRAD     " on -f mmx $E LC_ALL=C-TRADITIONAL LANG=C-TRADITIONAL $G "$T"
run1 "G5 ISO8859-1  " on -f mmx $E LC_ALL=en_US.ISO8859-1 LANG=en_US.ISO8859-1 $G "$T"
run1 "G6 env -i     " on -f mmx $E -i $G "$T"
p "G7 sha256.awk selftest, want e18b45a1...7d8b 792:"
run1 "G7 C         " on -f mmx $E LC_ALL=C LANG=C $G -f /fs/sda0/pmcp/bin/sha256.awk /fs/sda0/pmcp/bin/selftest.bin
run1 "G8 C-TRAD    " on -f mmx $E LC_ALL=C-TRADITIONAL LANG=C-TRADITIONAL $G -f /fs/sda0/pmcp/bin/sha256.awk /fs/sda0/pmcp/bin/selftest.bin

p "--- S: selftest.bin want sha1 dc0366dcc875627998ffc61777e6030fb6a3c165"
p "    and cksum 3465140931 792"
run1 "S1 rcc sha1   " on -f rcc /usr/bin/sha1sum /net/mmx/fs/sda0/pmcp/bin/selftest.bin
run1 "S2 rcc cksum  " on -f rcc /usr/bin/cksum /net/mmx/fs/sda0/pmcp/bin/selftest.bin
run1 "S3 card sha1  " on -f rcc "$CARD/apps/sbin/sha1sum" /net/mmx/fs/sda0/pmcp/bin/selftest.bin
run1 "S4 here sha1  " /net/rcc/usr/bin/sha1sum "$SD/bin/selftest.bin"
p "S5 factory lsd.sh want sha1 a100c0c85b2b7c5ec413aa1d115e4352758a2f16:"
run1 "S5 rcc sha1   " on -f rcc /usr/bin/sha1sum /net/mmx/mnt/app/eso/hmi/lsd/lsd.sh

p "--- W: SD card"
on -f mmx mount 2>&1 | while read _x; do case "$_x" in *sda0*|*sd0*) p "mount: $_x" ;; esac; done
run1 "W1 touch      " touch "$SD/diag.w"
run1 "W2 mount here " mount -uw "$CARD"
run1 "W3 mount mmx  " on -f mmx mount -uw /fs/sda0
run1 "W4 touch      " touch "$SD/diag.w"
run1 "W5 mkdir log  " mkdir -p "$SD/log"
rm -f "$SD/diag.w" 2>/dev/null
F="$SD/log/diag-$$.txt"
if ( echo "$ALL" > "$F" ) 2>/dev/null; then p "PMCP_DIAG_DONE log=$F"; else p "PMCP_DIAG_DONE (no log on SD: please photograph every screen, scroll down)"; fi
exit 0
