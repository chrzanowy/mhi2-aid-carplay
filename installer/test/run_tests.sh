#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Host tests for pmcp.sh against a fake unit tree built from our MU1161 backup, plus an execution
# test of the generated lsd.sh blocks (trial boot) over several simulated boots.
#   run_tests.sh SD_BUILD_DIR SHELL [SHELL...]
#   PMCP_TEST_SCOPE=speedlimit runs the optional reader cases against a fresh unit.
# Each scenario starts from a fresh factory tree. Exit status is the number of failed checks.
set -u
SDB=$(cd "${1:?sd build dir}" && pwd); shift
# Several shells: one run, each shell in its own process and work dir, in parallel. Output is printed per shell, FAIL
# lines carry the shell name, and the exit status is the sum of all failed checks.
if [ $# -gt 1 ] && [ -z "${PMCP_TEST_ONE_SHELL:-}" ]; then
    _P=$(mktemp -d /tmp/pmcp-par.XXXX); _i=0
    for _s in "$@"; do PMCP_TEST_ONE_SHELL=1 bash "$0" "$SDB" "$_s" > "$_P/$_i.log" 2>&1 & _i=$((_i+1)); done
    wait
    _i=0; _sum=0; _skip=0
    for _s in "$@"; do
        _n=$(basename "$_s")
        sed "s#^  FAIL #  FAIL [$_n] #" "$_P/$_i.log" | grep -v '^FAILED CHECKS: \|^SKIPPED '
        _f=$(sed -n 's/^FAILED CHECKS: //p' "$_P/$_i.log"); [ -n "$_f" ] || { echo "  FAIL [$_n] no result (run died)"; _f=1; }
        _k=$(sed -n 's/^SKIPPED (earlier cards not present, update tests only): //p' "$_P/$_i.log")
        _sum=$((_sum + _f)); _skip=$((_skip + ${_k:-0})); _i=$((_i+1))
    done
    rm -rf "$_P"
    [ "$_skip" = 0 ] || echo "SKIPPED (earlier cards not present, update tests only): $_skip"
    echo "FAILED CHECKS: $_sum"
    exit $_sum
fi
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
T=$(cd "$(dirname "$0")" && pwd)   # installer/test (no_printf.inc)
BK="${PMCP_BACKUP:-$REPO/backup/MU1161}/advanced/MU1161-appimg"
export PMCP_TEST_GAWK="${PMCP_TEST_GAWK:-$REPO/upstream/tools/gawk-3.1.5/gawk}"
FAILS=0
W=$(mktemp -d /tmp/pmcp-test.XXXX)
export PMCP_TEST_GEMLOG="$W/gem.log"   # the GEM button log outside the unit tree (the tree checks stay exact)
STOCK_LSD=97bbd4ecb51045b34c2a41955d9f53e1f144d174bff1aa8560e911525808e8d8
LSD_JAVA=$(sed -n 's/^LSD_JAVA \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")
jsha() { sed -n "s/^JAR_$1 \([0-9a-f]*\) .*/\1/p" "$SDB/pmcp/pmcp.sh"; }
jid() { echo "$1-$(jsha "$1" | cut -c1-8)"; }
NAI_SHA=$(jsha nai); NP_SHA=$(jsha np)
NAI=$(jid nai); NP=$(jid np); RG=$(jid rg); ZOOM=$(jid zoom); DN=$(jid dn); UI=$(jid ui)
[ -n "$NAI_SHA" ] && [ -n "$NP_SHA" ] || { echo "no JAR hashes in the manifest"; exit 99; }
# simulate the lsd.sh block of the unit tree for one normal boot (or RUN_MODE=$1); prints "boot=USE set=ID jars=LIST"
unit_boot() {
    { echo "BASE_DIR=/X; BOOTCLASSPATH=-Xbootclasspath/a:/ifs/lsd.jxe; RUN_MODE=${1:-}"
      sed -n '/^# >>> pmcp: CarPlay AID mod/,/^# <<< pmcp/p' "$W/unit/mnt/app/eso/hmi/lsd/lsd.sh" \
        | sed -e "s#/mnt/app/carplaymaps#$W/unit/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/unit/mnt/persist/pmcp#g" \
              -e "s|( .PMCP_DIR/rg/rgi-observer.*) &|:|"
      echo 'echo "boot=$PMCP_USE set=$PMCP_SET jars=$PMCP_JARS"'; } > "$W/unit-boot.sh"
    $SH "$W/unit-boot.sh" 2>&1 | tail -1
}

ok()   { echo "  ok   $*"; }
bad()  { echo "  FAIL $*"; FAILS=$((FAILS+1)); }
expect_out() { grep -q -- "$1" "$W/out" && ok "$2" || { bad "$2 (wanted '$1')"; sed 's/^/       | /' "$W/out" | tail -8; }; }
# one shasum process for the whole tree (same lines as one per file)
snapshot() { (cd "$1" && find . -type f ! -path './sdlog/*' -print0 | xargs -0 shasum -a 256 | sort -k2); }
h() { shasum -a 256 < "$1" | cut -d' ' -f1; }

fresh_unit() {
    rm -rf "$W/unit" "$W/sd"
    mkdir -p "$W/unit/ifs" "$W/unit/ramdisk" "$W/unit/mnt/app/eso/bin/apps" "$W/unit/mnt/app/eso/hmi/lsd/jars" "$W/unit/mnt/app/armle/usr/bin" "$W/unit/mnt/persist/etc" \
        "$W/unit/mnt/app/armle/lib/dll" "$W/unit/mnt/system/etc/mm"
    cp "$BK/armle/lib/dll/ipod-drvr-iap2.so" "$W/unit/mnt/app/armle/lib/dll/"
    cp "$BK/../MU1161-system/mm/iap2.cfg" "$W/unit/mnt/system/etc/mm/"
    mkfile -n 55830309 "$W/unit/ifs/lsd.jxe" 2>/dev/null || truncate -s 55830309 "$W/unit/ifs/lsd.jxe"
    cp "$BK/eso/bin/apps/dio_manager" "$W/unit/mnt/app/eso/bin/apps/dio_manager"
    cp "$BK/eso/bin/apps/gal" "$W/unit/mnt/app/eso/bin/apps/gal"
    mkdir -p "$W/unit/ramdisk"
    cp "$BK/eso/hmi/lsd/lsd.sh" "$W/unit/mnt/app/eso/hmi/lsd/lsd.sh"
    cp "$BK/eso/hmi/lsd/jars/"* "$W/unit/mnt/app/eso/hmi/lsd/jars/"
    echo "factory persist content" > "$W/unit/mnt/persist/etc/ffs3.2ver"
    cp -R "$SDB/pmcp" "$W/sd"
    awk -v inc="$T/no_printf.inc" '{print} /^unset LD_PRELOAD$/ && !done {while ((getline l < inc) > 0) print l; done=1}' \
        "$W/sd/pmcp.sh" > "$W/sd/pmcp.sh.t" && mv "$W/sd/pmcp.sh.t" "$W/sd/pmcp.sh"
    grep -q '^printf() {' "$W/sd/pmcp.sh" || { echo "no_printf.inc not applied"; exit 99; }
}

run() { PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
# earlier cards, run against the same fake unit: the v1.3.0 release and the last experimental card (Android Auto)
V13D="${PMCP_V13_SD:-$SDB/../sd-v1.3.0}/pmcp"
V13="$V13D/pmcp.sh"
EXP="${PMCP_EXP_SD:-$SDB/../sd-ab9fb348}/pmcp/pmcp.sh"
# the v1.4.0 release card (rg in pmcp-guidance.jar, no speed limit)
V140="${PMCP_V140_SD:-$SDB/../release-v1.4.0/sd}/pmcp/pmcp.sh"
# the v1.4.2 release card (rg in pmcp-guidance2.jar with the speed-limit hook, sl, no quiet-route hold)
V142="${PMCP_V142_SD:-$SDB/../release-v1.4.2-5a55ffff/sd}/pmcp/pmcp.sh"
# Earlier cards are only for the update tests. They are not in the repo: a build from install.sh skips those tests
# (and says so); release runs set PMCP_REQUIRE_OLD_CARDS=1, which makes a missing earlier card a failure.
SKIPS=0
card_ok() {
    [ -e "$1" ] && return 0
    if [ "${PMCP_REQUIRE_OLD_CARDS:-0}" = 1 ]; then bad "earlier card $2 missing: $1"
    else echo "  skip earlier card $2 not present ($1): its update test is skipped"; SKIPS=$((SKIPS+1)); fi
    return 1
}
run140() { PMCP_TEST_ROOT="$W/unit" $SH "$V140" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
run142() { PMCP_TEST_ROOT="$W/unit" $SH "$V142" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
# the experimental card f2a7ceb5 (v1.4.1 + Android Auto, rg-aa in pmcp-guidance-aa.jar); only [25] needs it
EXP141="${PMCP_EXP141_SD:-$SDB/../sd-f2a7ceb5}/pmcp/pmcp.sh"
runexp141() { PMCP_TEST_ROOT="$W/unit" $SH "$EXP141" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
# the experimental card 84472aa9 (v1.4.3 + Android Auto: rg 7b187484 in pmcp-guidance3.jar, rg-aa 01221496 in
# pmcp-guidance-aa2.jar, AA set of card 030b7df2) and b2bcbbe3 (v1.4.2 + AA 0.1: this card's AA set, rg-aa 4f9215bf)
EXP143="${PMCP_EXP143_SD:-$SDB/../sd-84472aa9}/pmcp/pmcp.sh"
runexp143() { PMCP_TEST_ROOT="$W/unit" $SH "$EXP143" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
EXPB2="${PMCP_EXPB2_SD:-$SDB/../sd-b2bcbbe3}/pmcp/pmcp.sh"
runexpb2() { PMCP_TEST_ROOT="$W/unit" $SH "$EXPB2" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
run13() { PMCP_TEST_ROOT="$W/unit" $SH "$V13" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
runexp() { PMCP_TEST_ROOT="$W/unit" $SH "$EXP" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
STOCK_GAL=3b422d47a16dd473dc426aa3a88348bfee0da0e7585993a3566df242339346f9
gal_start() {
    sed -e "s#/mnt/app/carplaymaps#$W/unit/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/unit/mnt/persist/pmcp#g" \
        -e "s#/ramdisk/#$W/unit/ramdisk/#g" \
        -e 's#^exec "$REAL" "$@"#echo "real=${REAL\#\#*/} preload=${LD_PRELOAD:-} conf=${GAL_HOOK_CONF:-} player=${GAL_PLAYER_PATH:-}"#' \
        "$W/unit/mnt/app/eso/bin/apps/gal" > "$W/gal-start.sh"
    o=$(env -u LD_PRELOAD $SH "$W/gal-start.sh" 2>&1 | tail -1)
    echo "$(cat "$W/unit/ramdisk/pmcp-aa-last" 2>/dev/null | sed -e 's/^set=[^ ]* //' -e 's/ capture=no$//') $o" | sed "s#$W/unit##g"
}
# the capture settings the wrapper would export for gal (empty = gal-hook.conf decides)
gal_env() {
    sed -e "s#/mnt/app/carplaymaps#$W/unit/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/unit/mnt/persist/pmcp#g" \
        -e "s#/ramdisk/#$W/unit/ramdisk/#g" \
        -e 's#^exec "$REAL" "$@"#echo "minor=${GAL_DUALSCREEN_AAP_MINOR:-} nav=${GAL_HOOK_NAV_LOG_MAX:-} kb=${GAL_HOOK_LOG_MAX_KB:-}"#' \
        "$W/unit/mnt/app/eso/bin/apps/gal" > "$W/gal-env.sh"
    env -u LD_PRELOAD -u GAL_DUALSCREEN_AAP_MINOR -u GAL_HOOK_NAV_LOG_MAX -u GAL_HOOK_LOG_MAX_KB $SH "$W/gal-env.sh" 2>&1 | tail -1
}
new_start() { rm -rf "$W/unit/ramdisk"; mkdir -p "$W/unit/ramdisk"; }

confirm_now() { mkdir -p "$W/unit/mnt/persist/pmcp"; read s rest < "$U/carplaymaps/HMI_BOOT"; touch "$W/unit/mnt/persist/pmcp/ok.$s"; }
rc_is() { [ "$(cat "$W/rc")" = "$1" ] && ok "exit $1" || { bad "exit $(cat "$W/rc"), wanted $1"; sed 's/^/       | /' "$W/out" | tail -5; }; }

for SH in "$@"; do
    echo "=== shell: $SH"
    U="$W/unit/mnt/app"

    if [ "${PMCP_TEST_SCOPE:-all}" != speedlimit ]; then
    echo "[1] verify on factory unit"
    fresh_unit; before=$(snapshot "$W/unit")
    run verify; rc_is 0; expect_out "PMCP_VERIFY_OK state=STOCK" "state STOCK"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "verify wrote nothing to the unit" || bad "verify changed the unit"

    echo "[2] unknown variant refused before any write"
    run install nonsense; rc_is 1; expect_out "PMCP_FAIL=UNKNOWN_VARIANT_nonsense" "unknown variant"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[2b] Java actions: no unlock file needed, but they need stage A"
    run java-on nai; rc_is 1; expect_out "JAVA_NEEDS_STAGE_A_STATE_STOCK" "needs stage A"
    grep -q "STAGE_B_LOCKED" "$W/out" && bad "Java still locked" || ok "no lock without an unlock file"
    run java-on nonsense; rc_is 1; expect_out "UNKNOWN_JAVA_PACKAGE_nonsense" "unknown package"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[3] install map-clean (stage A: video only)"
    run install map-clean; rc_is 0; expect_out "PMCP_INSTALL_OK stage=A variant=map-clean" "install ok"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = $STOCK_LSD ] && ok "lsd.sh still factory" || bad "lsd.sh changed in stage A"
    [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && ok "no NAI jar in stage A" || bad "NAI jar in stage A"
    [ "$(h "$U/eso/bin/apps/dio_manager")" = 8c12f6974adf9c8c9eb746e7d033e7fb35a9605e49c31ff2129e8ba938b2633d ] && ok "dio_manager is wrapper" || bad "dio_manager"
    [ "$(h "$U/carplaymaps/stock_first/dio_manager.real")" = 609e42723ab3e36c7be5ceade81e03672ba4acd251f8eeb8b100e074aaf3c250 ] && ok "factory dio saved" || bad "factory dio copy"
    [ "$(h "$U/carplaymaps/core.so")" = c5f4870427d6d24bf78908497beb27e4e881d64374b58c564e7395d809efe2f4 ] && ok "core.so map-clean" || bad "core.so"
    [ -e "$U/carplaymaps/CLUSTER_AUTO_ENABLE" ] && ok "auto-enable marker" || bad "marker"
    ls -a "$U" | grep -q '^\.carplaymaps-new' && bad "staging dir left behind" || ok "no staging leftovers"
    run status; expect_out "Unit state: VIDEO" "state VIDEO"

    echo "[3b] java-on nai, confirm, retry"
    run java-on nai; rc_is 0; expect_out "PMCP_JAVA_ON_OK package=nai set=$NAI" "java-on ok"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = "$LSD_JAVA" ] && ok "lsd.sh has the pmcp block" || bad "lsd.sh"
    [ "$(h "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar")" = $NAI_SHA ] && ok "NAI jar" || bad "NAI jar"
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NAI NavActiveIgnore.jar" ] && ok "HMI_BOOT = set id + JARs" || bad "HMI_BOOT: $(cat "$U/carplaymaps/HMI_BOOT")"
    run status; expect_out "Unit state: JAVA" "state JAVA"
    run java-on nai; rc_is 1; expect_out "JAVA_PACKAGE_ALREADY_ON_nai" "second java-on refused"
    run java-confirm; rc_is 1; expect_out "NO_TRIAL_BOOT_YET_FOR_SET" "confirm before any boot refused"
    # review 1, finding 2: confirm only during the trial boot of this set
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI jars=/X/lsd/jars/NavActiveIgnore.jar" ] && ok "boot 1: trial" || bad "boot 1: $o"
    o=$(unit_boot); [ "$o" = "boot=no set=$NAI jars=" ] && ok "boot 2 without confirm: factory" || bad "boot 2: $o"
    run java-confirm; rc_is 1; expect_out "NOT_IN_TRIAL_BOOT_OF_THIS_SET" "confirm on the factory boot after an unconfirmed trial refused"
    o=$(unit_boot); [ "$o" = "boot=no set=$NAI jars=" ] && ok "still factory (nothing confirmed)" || bad "boot 3: $o"
    run java-retry; rc_is 0; [ ! -e "$W/unit/mnt/persist/pmcp/trial.$NAI" ] && ok "retry clears trial" || bad "trial left"
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI jars=/X/lsd/jars/NavActiveIgnore.jar" ] && ok "after retry: trial again" || bad "retry boot: $o"
    o=$(unit_boot swdl); [ "$o" = "boot=no set= jars=" ] && ok "update mode (RUN_MODE=swdl): block loads nothing" || bad "swdl boot: $o"
    run java-confirm; rc_is 1; expect_out "NOT_IN_TRIAL_BOOT_OF_THIS_SET" "update-mode boot cleared last-boot: no confirm"
    o=$(unit_boot); [ "$o" = "boot=no set=$NAI jars=" ] && ok "trial used up" || bad "boot: $o"
    run java-retry; rc_is 0; o=$(unit_boot); [ "$o" = "boot=trial set=$NAI jars=/X/lsd/jars/NavActiveIgnore.jar" ] && ok "trial again" || bad "boot: $o"
    run java-confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK set=$NAI" "confirm during the trial boot"
    [ -e "$W/unit/mnt/persist/pmcp/ok.$NAI" ] && ok "ok marker" || bad "ok marker"
    run java-confirm; rc_is 1; expect_out "SET_ALREADY_CONFIRMED" "second confirm refused"
    o=$(unit_boot); [ "$o" = "boot=yes set=$NAI jars=/X/lsd/jars/NavActiveIgnore.jar" ] && ok "confirmed set loads on every boot" || bad "boot: $o"
    touch "$W/unit/mnt/persist/pmcp/DISABLED"; o=$(unit_boot); [ "$o" = "boot=no set= jars=" ] && ok "DISABLED: factory boot" || bad "DISABLED boot: $o"
    run java-confirm; rc_is 1; expect_out "JAVA_DISABLED_BY_RESCUE_CARD" "confirm refused while DISABLED"
    rm "$W/unit/mnt/persist/pmcp/DISABLED"
    run java-retry; rc_is 0; [ ! -e "$W/unit/mnt/persist/pmcp/trial.$NAI" ] && ok "retry clears trial" || bad "trial left"
    [ -z "$(find "$U" -name '*.pmcp-*')" ] && ok "no .pmcp-* leftovers" || bad "leftovers: $(find "$U" -name '*.pmcp-*')"

    echo "[3c] java-off nai back to stage A, then on again"
    run java-off nai; rc_is 0; expect_out "PMCP_JAVA_OFF_OK" "java-off ok"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = $STOCK_LSD ] && ok "lsd.sh factory again" || bad "lsd.sh"
    [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && ok "NAI jar removed" || bad "NAI jar left"
    run status; expect_out "Unit state: VIDEO" "back to VIDEO"
    run java-off nai; rc_is 1; expect_out "JAVA_OFF_NEEDS_JAVA_STATE_VIDEO" "java-off on VIDEO refused"
    run java-on nai; rc_is 0
    installed=$(snapshot "$W/unit")

    echo "[3d] two Java packages: order, set id, removing one keeps the other"
    run java-on np; rc_is 0; expect_out "set=$NAI+$NP" "set id for nai+np"
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NAI+$NP NavActiveIgnore.jar pmcp-np.jar" ] && ok "HMI_BOOT in catalog order" || bad "HMI_BOOT: $(cat "$U/carplaymaps/HMI_BOOT")"
    # regression (2026-10-21): a helper overwrote the caller's "f", so the np JAR was staged as NavActiveIgnore.jar
    [ "$(h "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar")" = $NAI_SHA ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-np.jar")" = $NP_SHA ] \
        && ok "each JAR under its own name with its own hash" || bad "JAR names/hashes mixed up"
    run java-off nai; rc_is 0
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NP pmcp-np.jar" ] && [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && ok "nai off, np stays" || bad "after nai off"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = "$LSD_JAVA" ] && ok "lsd.sh keeps the block while a package is on" || bad "lsd.sh"
    run status; expect_out "Unit state: JAVA" "still JAVA"
    run java-on nai; rc_is 0; expect_out "set=$NAI+$NP" "same set id again (catalog order)"
    installed=$(snapshot "$W/unit")

    echo "[3e] route guidance (package E): system part and Java package"
    run java-on rg; rc_is 1; expect_out "JAVA_RG_NEEDS_RG_SYSTEM_ON" "java rg refused without RG system"
    run rg-system-on; rc_is 0; expect_out "PMCP_RG_SYSTEM_ON_OK" "rg-system-on ok"
    [ "$(h "$U/armle/lib/dll/ipod-drvr-iap2.so")" = 519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3 ] && ok "patched driver active" || bad "driver"
    [ "$(h "$W/unit/mnt/system/etc/mm/iap2.cfg")" = c61407d9c6cd0d2529afedad0c9a120d5da5a504739e273bbb3dbea1e0b9b491 ] && ok "iap2.cfg with [ident]" || bad "cfg"
    run rg-system-on; rc_is 1; expect_out "RG_SYSTEM_ALREADY_ON" "second rg-system-on refused"
    run java-on rg; rc_is 0; expect_out "set=$NAI+$NP+$RG" "set with rg"
    run rg-system-off; rc_is 1; expect_out "TURN_OFF_JAVA_PACKAGE_RG_FIRST" "rg-system-off refused while JAR rg on"
    run status; expect_out "Route guidance system: on" "status shows RG on"
    run java-off rg; rc_is 0
    run rg-system-off; rc_is 0; expect_out "PMCP_RG_SYSTEM_OFF_OK" "rg-system-off ok"
    [ "$(h "$U/armle/lib/dll/ipod-drvr-iap2.so")" = 7149a3e75b1b19e89021841759f420a6eced456b6c697a3dd1f0e436abea0b8c ] && ok "factory driver back" || bad "driver not factory"
    [ "$(h "$W/unit/mnt/system/etc/mm/iap2.cfg")" = 1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37 ] && ok "factory cfg back" || bad "cfg not factory"
    run rg-system-on; rc_is 0; run java-on rg; rc_is 0

    echo "[3f] packages F (zoom) and G (day/night)"
    run java-on zoom; rc_is 0
    run java-on dn; rc_is 0; expect_out "set=$NAI+$NP+$RG+$ZOOM+$DN" "all five packages in catalog order"
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NAI+$NP+$RG+$ZOOM+$DN NavActiveIgnore.jar pmcp-np.jar pmcp-guidance4.jar pmcp-zoom.jar pmcp-dn.jar" ] && ok "HMI_BOOT with five JARs" || bad "HMI_BOOT: $(cat "$U/carplaymaps/HMI_BOOT")"
    run status; expect_out "Unit state: JAVA" "JAVA with five packages (set names parsed from HMI_BOOT)"
    run java-off zoom; rc_is 0; [ ! -e "$U/eso/hmi/lsd/jars/pmcp-zoom.jar" ] && ok "zoom off" || bad "zoom jar left"
    run java-on zoom; rc_is 0
    installed=$(snapshot "$W/unit")

    echo "[4] second install refused"
    run install card-clean; rc_is 1; expect_out "UNIT_NOT_FACTORY_STATE_JAVA" "refused on JAVA"
    [ "$installed" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[5] switch to card-clean"
    run switch card-clean; rc_is 0; expect_out "PMCP_SWITCH_OK variant=card-clean" "switch ok"
    run switch card-clean; rc_is 1; expect_out "SWITCH_ALREADY_card-clean" "same map again: already, nothing done"
    [ "$(h "$U/carplaymaps/core.so")" = a4054ff9f1e7175ef9365e9f51990eb4ed3c58121ccfe4a6651e039e362552ac ] && ok "core.so card-clean" || bad "core.so after switch"
    run status; expect_out "variant card-clean" "status shows variant"

    echo "[6] restore (from JAVA + RG system) returns the exact factory tree, other /mnt/persist data kept"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "restore ok"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit byte-identical to factory" || { bad "unit differs from factory"; diff <(echo "$before") <(snapshot "$W/unit") | head; }

    echo "[7] restore again refused, nothing changes"
    run restore; rc_is 1; expect_out "RESTORE_NEEDS_PMCP_INSTALL_STATE_STOCK" "refused on STOCK"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[8] corrupted payload byte: refused before any write"
    fresh_unit; before=$(snapshot "$W/unit")
    printf 'X' | dd of="$W/sd/payload/common/libCarPlayPairingCore.so" bs=1 seek=4096 conv=notrunc 2>/dev/null
    run install map-clean; rc_is 1; expect_out "HASH_MISMATCH_PAIR_CORE" "corruption detected"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[9] corrupted gawk self test: refused"
    fresh_unit
    printf 'Y' | dd of="$W/sd/bin/selftest.bin" bs=1 seek=10 conv=notrunc 2>/dev/null
    run verify; rc_is 1; expect_out "HASH_MISMATCH_SELFTEST" "self test catches it"

    echo "[9b] GEM runs us with a UTF-8 locale (unit 2026-10-23): pmcp.sh forces C, hashes still right"
    fresh_unit
    LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 LC_CTYPE=en_US.UTF-8 run verify; rc_is 0; expect_out "PMCP_VERIFY_OK state=STOCK" "verify ok under UTF-8"
    o=$(LC_ALL=en_US.UTF-8 "$PMCP_TEST_GAWK" -f "$W/sd/bin/sha256.awk" "$W/sd/bin/selftest.bin" 2>/dev/null)
    [ -z "$o" ] && ok "sha256.awk prints no hash when its byte table is broken" || bad "sha256.awk printed '$o' under UTF-8"

    echo "[9c] log not writable (SD read-only in GEM, no gem.log): warning only, actions still run"
    fresh_unit; echo x > "$W/unit/sdlog"
    PMCP_TEST_GEMLOG="$W/unit/sdlog/gem.log" run install map-clean; rc_is 0; expect_out "PMCP_WARN=NO_LOG_WRITABLE" "install warns"; expect_out "PMCP_INSTALL_OK" "install still runs"
    fresh_unit; echo x > "$W/unit/sdlog"
    PMCP_TEST_GEMLOG="$W/unit/sdlog/gem.log" run verify; rc_is 0; expect_out "PMCP_WARN=NO_LOG_WRITABLE" "verify warns"; expect_out "PMCP_VERIFY_OK" "verify still runs"
    fresh_unit; echo x > "$W/unit/sdlog"
    run verify; rc_is 0; ! grep -q "PMCP_WARN" "$W/out" && ok "SD read-only but gem.log writable: no warning" || bad "warned with gem.log"
    rm -f "$W/unit/sdlog"

    echo "[10] not MU1161 (lsd.jxe size)"
    fresh_unit; rm "$W/unit/ifs/lsd.jxe"; truncate -s 55840541 "$W/unit/ifs/lsd.jxe"
    run install map-clean; rc_is 1; expect_out "NOT_MU1161_LSD_JXE_SIZE_55840541" "size gate"

    echo "[11] modified factory lsd.sh: refused"
    fresh_unit; echo "# local edit" >> "$W/unit/mnt/app/eso/hmi/lsd/lsd.sh"; before=$(snapshot "$W/unit")
    run install map-clean; rc_is 1; expect_out "UNIT_NOT_FACTORY_STATE_UNKNOWN" "unknown state"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[12] another mod present (generic CarPlayNavigationPatch.jar): refused"
    fresh_unit; echo x > "$W/unit/mnt/app/eso/hmi/lsd/jars/CarPlayNavigationPatch.jar"; before=$(snapshot "$W/unit")
    run install map-clean; rc_is 1; expect_out "UNIT_NOT_FACTORY_STATE_UNKNOWN" "other mod detected"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "unit changed"

    echo "[13] interrupted state (dio back to factory by hand): PARTIAL, restore completes"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-clean; rc_is 0; run java-on nai; rc_is 0
    cp "$BK/eso/bin/apps/dio_manager" "$W/unit/mnt/app/eso/bin/apps/dio_manager"
    run status; expect_out "Unit state: PARTIAL" "PARTIAL detected"
    run install map-clean; rc_is 1; expect_out "UNIT_NOT_FACTORY_STATE_PARTIAL" "install refused on PARTIAL"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "restore from PARTIAL"
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "factory tree after PARTIAL restore" || bad "tree differs"

    echo "[13a] rescue-card result (factory lsd.sh, JAR gone, DISABLED): VIDEO, java-on again works, restore completes"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-clean-l40; rc_is 0; run java-on nai; rc_is 0
    cp "$BK/eso/hmi/lsd/lsd.sh" "$U/eso/hmi/lsd/lsd.sh"; rm "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar"
    mkdir -p "$W/unit/mnt/persist/pmcp"; touch "$W/unit/mnt/persist/pmcp/DISABLED"
    run status; expect_out "Unit state: VIDEO" "VIDEO after rescue (video still installed)"
    run java-on nai; rc_is 0; [ ! -e "$W/unit/mnt/persist/pmcp/DISABLED" ] && ok "java-on clears DISABLED" || bad "DISABLED left"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "factory tree after rescue + restore" || bad "tree differs"

    echo "[13b] interrupted staging leftovers are cleaned on the next install"
    fresh_unit
    mkdir -p "$W/unit/mnt/app/.carplaymaps-new-999/stock_first"; echo junk > "$W/unit/mnt/app/eso/bin/apps/dio_manager.pmcp-new"
    mkdir -p "$W/unit/mnt/app/.carplaymaps-old-998"; mkdir -p "$W/unit/mnt/persist/pmcp"; touch "$W/unit/mnt/persist/pmcp/ok.$NAI"
    run install map-clean; rc_is 0; expect_out "removing leftover" "leftovers removed"
    [ -z "$(find "$W/unit/mnt/app" -name '.carplaymaps-new-*' -o -name '.carplaymaps-old-*' -o -name '*.pmcp-*')" ] && ok "no leftovers" || bad "leftovers remain"
    [ ! -e "$W/unit/mnt/persist/pmcp" ] && ok "old ok/trial markers removed by install" || bad "old markers kept"

    echo "[13d] restore interrupted after carplaymaps was moved away: tool still works"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-clean; rc_is 0
    mv "$U/carplaymaps" "$U/.carplaymaps-old-777"; cp "$BK/eso/bin/apps/dio_manager" "$U/eso/bin/apps/dio_manager"
    run status; expect_out "Unit state: STOCK" "STOCK with only a leftover dir"
    run install map-clean; rc_is 0; run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && [ -z "$(ls -a "$U" | grep carplaymaps)" ] && ok "factory tree, leftover gone" || bad "tree differs"

    echo "[13e] verify with an unwritable log dir still checks the payload"
    fresh_unit
    printf 'X' | dd of="$W/sd/payload/common/libCarPlayPairingCore.so" bs=1 seek=4096 conv=notrunc 2>/dev/null
    mkdir -p "$W/unit/sdlog"; chmod 500 "$W/unit/sdlog"
    run verify; rc_is 1; expect_out "HASH_MISMATCH_PAIR_CORE" "corruption found without a log dir"
    grep -q "can't create\|cannot create\|Permission denied" "$W/out" && bad "log redirect errors on screen" || ok "no log redirect noise"
    chmod 700 "$W/unit/sdlog"

    echo "[13c] JAR with a wrong hash in the unit: not JAVA, restore still works"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-clean; rc_is 0; run java-on nai; rc_is 0
    printf 'Z' | dd of="$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" bs=1 seek=100 conv=notrunc 2>/dev/null
    run status; expect_out "Unit state: PARTIAL" "tampered JAR detected"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "factory tree" || bad "tree differs"

    echo "[14] GEM menu: buttons and menu file"
    for m in "$SDB"/pmcp/menu/*.sh; do
        $SH -n "$m" 2>/dev/null || bad "syntax $(basename "$m")"
        if [ "$(basename "$m")" = rglast.sh ]; then
            grep -q '^/bin/ksh /net/mmx/fs/sda0/pmcp/bin/rglast.sh$' "$m" && ! grep -q 'pmcp.sh' "$m" && ok "rglast button runs bin/rglast.sh only" || bad "rglast button"
            continue
        fi
        if [ "$(basename "$m")" = navdiag.sh ]; then
            grep -q '^/bin/ksh /net/mmx/fs/sda0/pmcp/bin/navdiag.sh$' "$m" && ! grep -q 'pmcp.sh' "$m" && ok "navdiag button runs bin/navdiag.sh only" || bad "navdiag button"
            continue
        fi
        if [ "$(basename "$m")" = timeline.sh ]; then
            grep -q '^/bin/ksh /net/mmx/fs/sda0/pmcp/bin/timeline.sh$' "$m" && ! grep -q 'pmcp.sh' "$m" && ok "timeline button runs bin/timeline.sh only" || bad "timeline button"
            continue
        fi
        if [ "$(basename "$m")" = diag.sh ]; then
            grep -q '^/bin/ksh /net/mmx/fs/sda0/pmcp/bin/diag.sh$' "$m" && ! grep -q 'pmcp.sh' "$m" && ok "diag button runs bin/diag.sh only" || bad "diag button"
            continue
        fi
        if [ "$(basename "$m")" = features-on.sh ]; then
            acts=$(sed -n 's/^for A in \(.*\); do$/\1/p' "$m")
            [ "$acts" = "features-reset_ rg-update_ java-update_ rg-system-on_ java-on_nai java-on_np java-on_rg java-on_zoom java-on_dn java-on_ui" ] && grep -q '^PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh$' "$m" \
                && ok "button 4: reset of unsupported files, updates, RG system, then nai np rg zoom dn ui (map and AA stay)" || bad "features-on actions: $acts"
            continue
        fi
        args=$(sed -n 's#^/bin/ksh /net/mmx/fs/sda0/pmcp/pmcp.sh ##p' "$m")
        case "$args" in
            verify|status|restore|confirm|retry|aa-install|cp-log-save|"map-install map-square-fps40"|java-retry|java-confirm|java-update|aa-remove|aa-on|aa-confirm|aa-retry|aa-status|aa-log-save|aa-log-clear|rg-system-on|rg-system-off|rg-update|speedlimit-status|"speedlimit-mode turnto"|"speedlimit-mode street"|"speedlimit-mode off"|"install "*|"switch "*|"java-on "*|"java-off "*) ;;
            "aa-output direct"|"aa-output ring") ;;
            "aa-capture 60"|"aa-capture off")
                case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) ;; *) bad "experimental button on a release card: $args" ;; esac ;;
            *) bad "unexpected button command in $(basename "$m"): $args" ;;
        esac
        set -- $args
        case "$1" in
            install|switch) grep -q "^CORE_$2 " <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") || bad "variant $2 of $(basename "$m") not in manifest" ;;
            java-on|java-off) grep -q "^JAR_$2 " <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") || bad "package $2 of $(basename "$m") not in manifest" ;;
        esac
    done
    nmenu=$(ls "$SDB"/pmcp/menu/*.sh | wc -l | tr -d ' ')
    nref=$(grep -c '/net/mmx/fs/sda0/pmcp/menu/' "$SDB/esd/Launcher-sda0.esd")
    [ "$nmenu" -gt 20 ] && [ "$nmenu" = "$nref" ] && ok "menu scripts: $nmenu, menu entries: $nref" || bad "menu scripts $nmenu vs entries $nref"
    grep -q "map-install map-square-fps40$" "$SDB/pmcp/menu/map-install.sh" && grep -q '"2. Install CarPlay: the map on the AID (also repairs or updates it)"' "$SDB/esd/Launcher-sda0.esd" \
        && ok "main install button 2 is map-square-fps40" || bad "main install button"
    [ ! -e "$SDB/pmcp/menu/install-map-square-fps40.sh" ] && ok "no second install button for the main layout" || bad "install-map-square-fps40 button left"
    main=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,/^screen pmcp_advanced/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    [ "$main" = "menu/verify.sh menu/map-install.sh menu/aa-install.sh menu/features-on.sh menu/confirm.sh menu/retry.sh menu/status.sh menu/restore.sh " ] \
        && ok "main screen: 1 check, 2 CarPlay, 3 Android Auto, 4 features, 5 confirm, 6 try again, 7 status, 8 remove" || bad "main screen: $main"
    labels=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,/^screen pmcp_advanced/p' | awk '/^script/{s=1;next} s&&/^    label/{print substr($0,14,1);s=0}' | tr -d '\n')
    [ "$labels" = 12345678 ] && ok "main screen buttons numbered 1-8" || bad "main numbering: $labels"
    scr=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,$p' | grep '^screen' | tr '\n' '|')
    [ "$scr" = "screen pmcp_stream_map_aid =>M.I.B.<=|screen pmcp_advanced pmcp_stream_map_aid|screen features_advanced pmcp_advanced|screen carplay_advanced pmcp_advanced|screen aa_advanced pmcp_advanced|" ] \
        && ok "screens: pmcp_stream_map_aid > pmcp_advanced > features / carplay / aa_advanced" || bad "screens: $scr"
    feat=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen features_advanced/,/^screen carplay_advanced/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    case "$feat" in "menu/diag.sh menu/timeline.sh menu/rglast.sh menu/navdiag.sh menu/cp-log-save.sh menu/log-clear.sh menu/speedlimit-status.sh menu/rg-system-on.sh "*"menu/java-update.sh menu/java-on-nai.sh "*"menu/java-on-sl.sh menu/java-on-ui.sh "*"menu/java-off-sl.sh menu/java-off-ui.sh ") ok "features_advanced: diagnostics, CarPlay log, speed-limit status only (mode on the page), RG system, packages (ui last)" ;; *) bad "features_advanced: $feat" ;; esac
    for _m in speedlimit-on speedlimit-cpi speedlimit-off; do
        [ ! -e "$SDB/pmcp/menu/$_m.sh" ] && ! grep -q "menu/$_m.sh" "$SDB/esd/Launcher-sda0.esd" && ok "no GEM button $_m (mode set on the page)" \
            || bad "GEM speed-limit mode button $_m still there"
    done
    cpa=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen carplay_advanced/,/^screen aa_advanced/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    [ "$cpa" = "menu/install-map-clean.sh menu/install-card-clean.sh menu/install-url-map-hybrid.sh menu/install-map-clean-l40.sh menu/install-map-square.sh menu/switch-map-clean.sh menu/switch-card-clean.sh menu/switch-url-map-hybrid.sh menu/switch-map-clean-l40.sh menu/switch-map-square.sh menu/switch-map-square-fps40.sh " ] \
        && ok "carplay_advanced: other layouts (install, switch)" || bad "carplay_advanced: $cpa"
    ORIG="$REPO/archives/mib-3.6.0/Launcher-sda0.esd"
    head -c "$(stat -f %z "$ORIG")" "$SDB/esd/Launcher-sda0.esd" | cmp -s - "$ORIG" && ok "M.I.B. menu content unchanged (only appended)" || bad "M.I.B. menu prefix changed"
    for ref in $(grep -o '/net/mmx/fs/sda0/pmcp/menu/[a-z0-9-]*\.sh' "$SDB/esd/Launcher-sda0.esd"); do
        [ -f "$SDB/pmcp/menu/${ref##*/}" ] || bad "menu points to missing ${ref##*/}"
    done
    v=$(sed -n 's/^PMCP_VERSION="\(.*\)"$/\1/p' "$SDB/pmcp/pmcp.sh")
    case "$v" in pmcp-0.5.1-mu1161-791-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ok "version carries a build id: $v" ;;
        pmcp-0.5.1-exp-mu1161-791-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ok "experimental version carries a build id: $v" ;;
        *) bad "version $v" ;; esac
    aa=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen aa_advanced/,$p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    case "$v" in
    *-exp-*)
        [ "$aa" = "menu/aa-confirm.sh menu/aa-output-direct.sh menu/aa-output-ring.sh menu/aa-retry.sh menu/aa-status.sh menu/aa-log-save.sh menu/aa-log-clear.sh menu/aa-remove.sh menu/aa-capture-60.sh menu/aa-capture-off.sh " ] \
            && ok "aa_advanced (experimental card): the release entries, then AA record on/off" || bad "aa_advanced: $aa"
        sed -n '/^screen pmcp_stream_map_aid/,/^screen aa_advanced/p' "$SDB/esd/Launcher-sda0.esd" | grep -qi 'experimental\|rg-aa' && bad "experimental outside aa_advanced" || ok "experimental entries only on aa_advanced"
        grep -qi 'rg-aa' <(sed -n '/^screen pmcp_stream_map_aid/,$p' "$SDB/esd/Launcher-sda0.esd") && bad "menu still says rg-aa" || ok "menu: no rg-aa" ;;
    *)
        [ "$aa" = "menu/aa-confirm.sh menu/aa-output-direct.sh menu/aa-output-ring.sh menu/aa-retry.sh menu/aa-status.sh menu/aa-log-save.sh menu/aa-log-clear.sh menu/aa-remove.sh " ] \
            && ok "aa_advanced (release card): confirm, output direct/bridge, retry, status, log save/clear, remove; no AA install there" || bad "aa_advanced: $aa"
        grep -qi 'experimental\|rg-aa' <(sed -n '/^screen pmcp_stream_map_aid/,$p' "$SDB/esd/Launcher-sda0.esd") && bad "menu still says experimental or rg-aa" || ok "menu: no 'experimental', no rg-aa"
        grep -q '^AAX_' <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") && bad "release card carries AAX_ keys" || ok "release card: no experimental AA set" ;;
    esac
    grep -q 'pmcp_CarPlay_AID\|pmcp_android_auto\|pmcp_packages\|pmcp_other_layouts\|pmcp_switch_layout' "$SDB/esd/Launcher-sda0.esd" && bad "old screen names left" || ok "no old screen names"
    grep -q '"java-on rg-aa\|java-on-rg-aa' "$SDB/esd/Launcher-sda0.esd" "$SDB"/pmcp/menu/*.sh && bad "rg-aa button left" || ok "no rg-aa package button"
    grep -q "$v" "$SDB/esd/Launcher-sda0.esd" && [ "$(head -1 "$SDB/BUILD-MANIFEST.txt")" = "$v" ] && ok "same id in GEM and BUILD-MANIFEST" || bad "version id mismatch"

    echo "[15] lsd.sh trial boot block, executed over simulated boots"
    B="$W/boot"; rm -rf "$B"; mkdir -p "$B/app/carplaymaps" "$B/persist"
    sed -n '/^# >>> pmcp: CarPlay AID mod/,/^# <<< pmcp/p' "$SDB/pmcp/payload/lsd/lsd.sh" > "$B/pre.sh"
    [ "$(grep -c '' "$B/pre.sh")" -gt 10 ] && ok "block extracted" || bad "block not found"
    [ "$(grep -c '>>> pmcp' "$SDB/pmcp/payload/lsd/lsd.sh")" = 1 ] && ok "exactly one pmcp block (no watcher after J9)" || bad "pmcp block count"
    diff <(cat "$BK/eso/hmi/lsd/lsd.sh") <(sed '/^# >>> pmcp: CarPlay AID mod/,/^# <<< pmcp/d' "$SDB/pmcp/payload/lsd/lsd.sh") >/dev/null \
        && ok "patched lsd.sh = factory + the block only" || bad "lsd.sh differs outside the block"
    # boot [RUN_MODE] -> prints BOOTCLASSPATH
    boot() {
        { echo "BASE_DIR=/ramdisk/hmi; BOOTCLASSPATH=-Xbootclasspath/a:/ifs/lsd.jxe; RUN_MODE=${1:-}"
          sed -e "s#/mnt/app/carplaymaps#$B/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$B/persist/pmcp#g" "$B/pre.sh"
          echo 'echo "BCP=$BOOTCLASSPATH"; wait'
        } > "$B/run.sh"
        $SH "$B/run.sh" 2>&1
    }
    echo "nai-823adeb0 NavActiveIgnore.jar" > "$B/app/carplaymaps/HMI_BOOT"
    o=$(boot); case "$o" in *"/p:/ramdisk/hmi/lsd/jars/NavActiveIgnore.jar"*) ok "boot 1 (trial) loads the JAR" ;; *) bad "boot 1: $o" ;; esac
    [ "$(cat "$B/persist/pmcp/last-boot")" = "set=nai-823adeb0 use=trial" ] && ok "last-boot says trial" || bad "last-boot: $(cat "$B/persist/pmcp/last-boot")"
    [ ! -e "$B/persist/pmcp/ok.nai-823adeb0" ] && ok "no automatic ok" || bad "ok written without the user"
    o=$(boot); case "$o" in *"/p:"*) bad "unconfirmed trial loaded again: $o" ;; *) ok "boot 2 without confirm is factory" ;; esac
    [ "$(cat "$B/persist/pmcp/last-boot")" = "set=nai-823adeb0 use=no" ] && ok "last-boot says no" || bad "last-boot: $(cat "$B/persist/pmcp/last-boot")"
    touch "$B/persist/pmcp/ok.nai-823adeb0"
    o=$(boot); case "$o" in *NavActiveIgnore*) ok "confirmed set loads" ;; *) bad "confirmed: $o" ;; esac
    o=$(boot swdl); case "$o" in *"/p:"*) bad "update mode loaded JARs: $o" ;; *) ok "RUN_MODE=swdl: factory boot even with ok" ;; esac
    [ ! -e "$B/persist/pmcp/last-boot" ] && ok "update mode removes last-boot" || bad "last-boot left in update mode"
    echo "nai-823adeb0+np-11111111 NavActiveIgnore.jar pmcp-np.jar" > "$B/app/carplaymaps/HMI_BOOT"
    o=$(boot); case "$o" in *"NavActiveIgnore.jar:/ramdisk/hmi/lsd/jars/pmcp-np.jar"*) ok "new set: trial loads both JARs" ;; *) bad "new set trial: $o" ;; esac
    o=$(boot); case "$o" in *"/p:"*) bad "unconfirmed trial loaded again: $o" ;; *) ok "next boot after the unconfirmed trial is factory" ;; esac
    touch "$B/persist/pmcp/DISABLED"; rm -f "$B/persist/pmcp/trial."*
    o=$(boot); case "$o" in *"/p:"*) bad "DISABLED ignored: $o" ;; *) ok "DISABLED (rescue card) gives a factory boot" ;; esac
    [ ! -e "$B/persist/pmcp/last-boot" ] && ok "DISABLED: no last-boot (nothing to confirm)" || bad "last-boot while DISABLED"
    rm -rf "$B/persist/pmcp"; chmod 500 "$B/persist"
    o=$(boot); case "$o" in *"/p:"*) bad "unwritable persist still loaded JARs: $o" ;; *) ok "unwritable /mnt/persist gives a factory boot" ;; esac
    chmod 700 "$B/persist"
    echo "nai-823adeb0" > "$B/app/carplaymaps/HMI_BOOT"
    o=$(boot); case "$o" in *"/p:"*) bad "id without JARs loaded: $o" ;; *) ok "HMI_BOOT without JARs gives a factory boot" ;; esac
    rm -f "$B/app/carplaymaps/HMI_BOOT"
    o=$(boot); case "$o" in *"/p:"*) bad "no HMI_BOOT still loaded: $o" ;; *) ok "no HMI_BOOT gives a factory boot" ;; esac
    echo "[15b] reader start: only with SYSTEM_ON and a loading Java set"
    echo "rg-11111111 pmcp-rg.jar" > "$B/app/carplaymaps/HMI_BOOT"; rm -rf "$B/persist/pmcp"
    mkdir -p "$B/app/carplaymaps/rg"; printf '#!/bin/sh\necho "$@" > %s/reader-started\n' "$B" > "$B/app/carplaymaps/rg/rgi-observer"; chmod 755 "$B/app/carplaymaps/rg/rgi-observer"
    rm -f "$B/reader-started"; boot >/dev/null; sleep 1
    [ ! -e "$B/reader-started" ] && ok "no SYSTEM_ON: reader not started" || bad "reader started without SYSTEM_ON"
    touch "$B/app/carplaymaps/rg/SYSTEM_ON"; rm -rf "$B/persist/pmcp"
    boot >/dev/null; sleep 1
    grep -q "start-live /dev/ipod0/rgi-events /ramdisk/carplay-route-guidance" "$B/reader-started" 2>/dev/null && ok "SYSTEM_ON + trial set: reader started with Tomasz's arguments" || bad "reader not started"
    rm -f "$B/reader-started"; touch "$B/persist/pmcp/DISABLED"; boot >/dev/null; sleep 1
    [ ! -e "$B/reader-started" ] && ok "DISABLED: reader not started" || bad "reader started while DISABLED"
    rm -f "$B/persist/pmcp/DISABLED"

    echo "[16] rescue card script (pmcp-rescue.sh) against the fake unit"
    RS="${PMCP_RESCUE_SD:-$SDB/../sd-rescue-v3}/pmcp-rescue/pmcp-rescue.sh"
    rescue() { # rescue -> runs the rescue as stuff.sh would, then the log step; medium = $W/med
        rm -rf "$W/rr" "$W/med"; mkdir -p "$W/rr/net/rcc/dev/shmem" "$W/med"; ln -s "$W/unit" "$W/rr/net/mmx"
        PMCP_RESCUE_TEST_ROOT="$W/rr" PMCP_RESCUE_TEST_SLEEP=0 $SH "$RS" HW "$W/med" >/dev/null 2>&1
        PMCP_RESCUE_TEST_ROOT="$W/rr" $SH "$RS" --save-log "$W/med" >/dev/null 2>&1
    }
    fresh_unit; factory=$(snapshot "$W/unit")
    rescue
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "healthy factory unit: nothing changed" || bad "rescue changed a factory unit"
    grep -q "RESULT=OK" "$W/med/PMCP_RESCUE_LOG.txt" && tail -1 "$W/med/PMCP_RESCUE_LOG.txt" | grep -q "PMCP RESCUE end" \
        && ok "log on the card: RESULT=OK ... end" || bad "log missing or incomplete"
    [ -z "$(ls "$W/rr/net/rcc/dev/shmem")" ] && ok "RAM log moved and cleared" || bad "RAM log left"

    fresh_unit; run install map-clean; rc_is 0; run java-on nai; rc_is 0
    rescue
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = $STOCK_LSD ] && ok "JAVA unit: factory lsd.sh back" || bad "lsd.sh not restored"
    [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && ok "JAR removed" || bad "JAR left"
    [ -e "$W/unit/mnt/persist/pmcp/DISABLED" ] && ok "DISABLED written" || bad "no DISABLED"
    [ -e "$U/carplaymaps/core.so" ] && [ "$(h "$U/eso/bin/apps/dio_manager")" = 8c12f6974adf9c8c9eb746e7d033e7fb35a9605e49c31ff2129e8ba938b2633d ] \
        && ok "video part left in place" || bad "video part touched"
    grep -q "RESULT=OK" "$W/med/PMCP_RESCUE_LOG.txt" && ok "RESULT=OK" || bad "no RESULT=OK"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "GEM restore after rescue"

    fresh_unit; run install map-clean; rc_is 0; run java-on nai; rc_is 0
    rm "$U/carplaymaps/rollback/lsd.sh"
    rescue
    [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && [ -e "$W/unit/mnt/persist/pmcp/DISABLED" ] && ok "no factory copy: JAR removed + DISABLED" || bad "fallback failed"
    grep -q "RESULT=UNSURE" "$W/med/PMCP_RESCUE_LOG.txt" && ok "honest RESULT=UNSURE when lsd.sh still has our block" || bad "should be NIEPEWNY"

    fresh_unit; run install map-clean; rc_is 0; run rg-system-on; rc_is 0; run java-on rg; rc_is 0
    mkdir -p "$W/unit/mnt/persist/pmcp"; echo "set=$RG use=trial" > "$W/unit/mnt/persist/pmcp/last-boot"
    echo turnto > "$W/unit/mnt/persist/pmcp/native-speedlimit-mode"
    rescue
    [ ! -e "$W/unit/mnt/persist/pmcp/native-speedlimit-mode" ] && ok "speed-limit mode removed (not back after Try again)" || bad "speed-limit mode left"
    [ "$(h "$U/armle/lib/dll/ipod-drvr-iap2.so")" = 7149a3e75b1b19e89021841759f420a6eced456b6c697a3dd1f0e436abea0b8c ] && ok "RG: factory iAP2 driver back" || bad "driver not restored"
    [ "$(h "$W/unit/mnt/system/etc/mm/iap2.cfg")" = 1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37 ] && ok "RG: factory iap2.cfg back" || bad "cfg not restored"
    [ ! -e "$U/carplaymaps/rg/SYSTEM_ON" ] && [ ! -e "$W/unit/mnt/persist/pmcp/last-boot" ] && ok "SYSTEM_ON and last-boot removed" || bad "SYSTEM_ON/last-boot left"
    grep -q "RESULT=OK" "$W/med/PMCP_RESCUE_LOG.txt" && ok "RESULT=OK" || bad "no RESULT=OK"
    run java-confirm; rc_is 1; expect_out "JAVA_NEEDS\|JAVA_CONFIRM_NEEDS_JAVA_STATE\|NOT_IN_TRIAL\|DISABLED" "no confirm after a rescue"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "GEM restore after an RG rescue"

    fresh_unit; run install map-clean; rc_is 0; run java-on nai; rc_is 0
    rm "$U/eso/hmi/lsd/lsd.sh"; rm "$U/carplaymaps/rollback/lsd.sh"
    rescue
    grep -q "RESULT=UNSURE" "$W/med/PMCP_RESCUE_LOG.txt" && ok "lsd.sh missing: RESULT=UNSURE, not OK" || bad "missing lsd.sh reported OK"

    echo "[17] main screen 4: install additional features (the real menu script, one set, one trial)"
    # feat: main menu 4 (the real menu script); allon: what the old button 3 did, now 2 then 4 (map, then features)
    feat() {
        sed -e "s#/bin/ksh \$PMCP#$SH $W/sd/pmcp.sh#" "$W/sd/menu/features-on.sh" > "$W/features-on.sh"
        PMCP_TEST_ROOT="$W/unit" $SH "$W/features-on.sh" > "$W/out" 2>&1; echo $? > "$W/rc"
    }
    allon() {
        PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" map-install map-square-fps40 > "$W/out2" 2>&1; _rc2=$?
        feat; cat "$W/out2" "$W/out" > "$W/out3"; mv "$W/out3" "$W/out"
        [ $_rc2 = 0 ] || echo $_rc2 > "$W/rc"
    }
    fresh_unit; factory=$(snapshot "$W/unit")
    feat; rc_is 0; expect_out "PMCP_FAIL=FEATURES_STOPPED_AT_features-reset_" "4 without the map (2): stops at the first step"
    expect_out "2. Install CarPlay first" "4 without the map: says press 2"
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "without the map: unit unchanged" || bad "features without stage A changed the unit"
    run map-install map-square-fps40; rc_is 0; expect_out "PMCP_INSTALL_OK stage=A variant=map-square-fps40" "2 on a factory unit installs the map"
    run map-install map-square-fps40; rc_is 0; expect_out "already installed: variant map-square-fps40, nothing changed" "2 again: already installed"
    allon; rc_is 0; expect_out "PMCP_FEATURES_ON_OK" "all features on"; expect_out "PMCP_RG_SYSTEM_ON_OK" "RG system on"
    ALL="$NAI+$NP+$RG+$ZOOM+$DN+$UI"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "one set with all six packages (with ui)" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ -e "$U/carplaymaps/rg/SYSTEM_ON" ] && ok "RG system marker" || bad "no SYSTEM_ON"
    o=$(unit_boot); case "$o" in "boot=trial set=$ALL jars="*pmcp-guidance4.jar*pmcp-dn.jar:/X/lsd/jars/pmcp-ui.jar) ok "next start: one trial with all JARs" ;; *) bad "boot: $o" ;; esac
    run java-confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK set=$ALL" "one confirm for everything"
    allon; expect_out "everything was already on, nothing changed" "second press: nothing to do"
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "remove everything: factory state"
    [ "$(h "$W/unit/mnt/system/etc/mm/iap2.cfg")" = 1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37 ] && ok "factory iap2.cfg back" || bad "cfg after restore"
    # update a v1.3.0 install (its button 3: map-square-fps40, RG, nai np zoom dn rglu, confirmed) with the same button
    if card_ok "$V13" v1.3.0; then
    fresh_unit; factory=$(snapshot "$W/unit")
    run13 install map-square; rc_is 0; run13 rg-system-on; rc_is 0
    for n in nai np zoom dn rglu; do run13 java-on $n; rc_is 0; done
    confirm_now; old_set=$(cat "$U/carplaymaps/HMI_BOOT")
    run status; expect_out "Unit state: JAVA" "v1.3.0 install: JAVA for this card"; expect_out "Route guidance system: old" "RG of v1.3.0: old"
    expect_out "packages of an earlier card: rglu" "rglu reported as an earlier card's package"
    run java-on zoom; rc_is 1; expect_out "JAVA_SET_HAS_OLD_PACKAGES_RUN_JAVA_UPDATE_FIRST" "single package refused until java-update"
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$old_set" ] && ok "refusal changed nothing" || bad "HMI_BOOT changed"
    allon; rc_is 0; expect_out "PMCP_RG_UPDATE_OK" "update: RG driver and reader replaced"
    expect_out "PMCP_JAVA_UPDATE_OK" "update: Java packages replaced"; expect_out "PMCP_SWITCH_OK variant=map-square-fps40" "update: main map switched"
    expect_out "PMCP_FEATURES_ON_OK" "update done"
    [ "$(h "$U/armle/lib/dll/ipod-drvr-iap2.so")" = 519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3 ] \
        && [ "$(h "$U/carplaymaps/rg/rgi-observer")" = 3166df9b91119475f93043ac8c150e2641732e602161839a137a1907d4ef11df ] \
        && ok "update: new driver and reader" || bad "driver/reader after update"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "update: set nai np rg zoom dn ui" || bad "update set: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rglu.jar" ] && ok "update: pmcp-rglu.jar removed" || bad "old JAR left"
    o=$(unit_boot); case "$o" in "boot=trial set=$ALL jars="*) ok "update: next start is a trial" ;; *) bad "update boot: $o" ;; esac
    run java-confirm; rc_is 0
    allon; expect_out "everything was already on, nothing changed" "after the update: nothing to do"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore after the v1.3.0 update: exact factory tree" || bad "tree after restore"
    fi

    echo "[20] start timeline button (fake pidin/sloginfo; real script, host awk)"
    mkdir -p "$W/tl/bin"
    cat > "$W/tl/bin/pidin" <<'PEOF'
#!/bin/sh
case "$1" in
info) echo "CPU:ARM Release:6.5.0  FreeMem:200MB/1024MB BootTime:Oct 29 07:59:58 2026" ;;
times) echo "     pid name                       start time        utime        stime"
  if [ -n "$TL_NOSEC" ]; then echo "       1 procnto                    Oct 29 07:59   1s 2s"; echo "  401433 dio_manager                Oct 29 08:00   1s 2s"
  else echo "       1 procnto                    Oct 29 07:59:58      1s     2s"
       echo "   12300 smartphone_integrator      Oct 29 08:00:11      1s     2s"
       echo "  401433 dio_manager                Oct 29 08:00:23      1s     2s"
       echo "  401990 carplay-cluster-supervisor Oct 29 08:00:24      1s     2s"
       echo "  455000 navigation                 Oct 29 08:00:57      1s     2s"
       echo "  455111 unrelated-proc             Oct 29 08:01:00      1s     2s"; fi ;;
esac
PEOF
    printf '#!/bin/sh\necho "Oct 29 08:01:02  5 14 0 navi: map ready"\n' > "$W/tl/bin/sloginfo"
    chmod 755 "$W/tl/bin/pidin" "$W/tl/bin/sloginfo"
    sed -e "s#^export PATH=.*#export PATH=$W/tl/bin:/bin:/usr/bin#" -e "s#^AWK=.*#AWK=$PMCP_TEST_GAWK#" "$SDB/pmcp/bin/timeline.sh" > "$W/tl/t.sh"
    $SH "$W/tl/t.sh" > "$W/out" 2>&1
    mkdir -p "$W/tl/rd"
    echo "t_us=21437000 event=oem-most-release value1=0 value2=0" > "$W/tl/rd/carplay-cluster-supervisor.log"
    echo "launch=carplay-maps-video-only" > "$W/tl/rd/carplaymaps-launcher.log"
    PMCP_RAMDISK="$W/tl/rd" $SH "$W/tl/t.sh" > "$W/out" 2>&1
    expect_out "PMCP_TIMELINE_DONE" "timeline runs to the end"
    expect_out "^   21.4  event=oem-most-release" "supervisor event in seconds since unit start"
    expect_out "launch=carplay-maps-video-only" "launcher log shown"
    expect_out "^   25  401433 dio_manager" "dio_manager at +25 s"
    expect_out "^   59  455000 navigation" "navigation at +59 s"
    grep -q unrelated "$W/out" && bad "unrelated process listed" || ok "only the relevant processes"
    expect_out "navi: map ready" "system log line"
    TL_NOSEC=1 $SH "$W/tl/t.sh" > "$W/out" 2>&1
    expect_out "no start time with seconds; raw lines" "no seconds: raw lines instead of wrong numbers"

    echo "[21] RG last maneuver button (synthetic mailbox: route, U-turn without junction, right turn, U-turn by angle, lanes)"
    mkdir -p "$W/rgm"; rm -f "$W/rgm/adapter-status.txt" "$W/rgm/guidance-evidence.txt"   # left by the previous shell's pass
    echo "52474d31010000005f0100000900000001000000000000000000000000000000524749310100000040810000000000000700000005000000050000000000000000000000000000000000000000000000000000000000000000000000000000000100000001521300070000000000000000060000000100050001010008000d000300040200000002522300070000000000000000060000000100060001000300050003040005000800000d000447c582c3b3776e6100030000000252210007000000000000000006000000010006000100040005000302000500080000050009000006000b005a0400000002521c000700000000000000000600000001000600010005000500030400050009000006000bff560500000004523c000700000000000000000600000001000600010005001500020006000000000005000100000600020000001b0002000600000001000500010200060002ff4c00060003ff4c" | xxd -r -p > "$W/rgm/latest.bin"
    echo "RG status=live polls=1" > "$W/rgm/status.txt"
    sed -e "s#^AWK=.*#AWK=$PMCP_TEST_GAWK#" "$SDB/pmcp/bin/rglast.sh" > "$W/rgm/t.sh"
    PMCP_RG_MAILBOX="$W/rgm" $SH "$W/rgm/t.sh" > "$W/out" 2>&1
    expect_out "PMCP_RGLAST_DONE" "rglast runs to the end"
    expect_out "route state=1 next maneuver idx=3" "route message: state and next maneuver"
    expect_out "idx=3 type=4 side=0 junction=- angle=- -> arrow 0 0 (junction missing" "U-turn without junction: no arrow (shown why)"
    expect_out "idx=4 type=2 side=0 junction=0 angle=90 -> arrow 13 turn" "right turn: arrow"
    expect_out "idx=5 type=4 side=- junction=0 angle=-170 -> arrow 25 64" "U-turn by signed angle"
    expect_out "lanes idx=5 \[pos=0 st=0 a=0/0|0\] \[pos=1 st=2 a=-180/128|114 hl=-180/128|114\]" "lanes: positions, status, angle -> direction byte"
    expect_out "no $W/rgm/guidance-evidence.txt" "no evidence file: says so"
    # rg's own files (v1.4.3): output state and the quiet-route evidence are shown as they are
    echo "RG build=pmcp-mu1161-rg-lanes-asfm-2 mode=2" > "$W/rgm/adapter-status.txt"
    printf 'format=1 hold_ms=180000 route=3 quiet=12\nsources=Maps:3 current=Maps changes=0\n' > "$W/rgm/guidance-evidence.txt"
    PMCP_RG_MAILBOX="$W/rgm" $SH "$W/rgm/t.sh" > "$W/out" 2>&1
    expect_out "^--- adapter-status.txt" "adapter status shown"; expect_out "asfm-2 mode=2" "adapter status content"
    expect_out "^--- guidance-evidence.txt" "evidence shown"; expect_out "current=Maps changes=0" "evidence content"
    # a 32-byte STALE record (no snapshot) while rg holds the route
    echo "52474d3101000000200000000a00000003000000881300000100000000000000" | xxd -r -p > "$W/rgm/latest.bin"
    PMCP_RG_MAILBOX="$W/rgm" $SH "$W/rgm/t.sh" > "$W/out" 2>&1
    expect_out "mailbox: record 10 kind 3 (stale: no new phone message for 5 s; rg holds the route up to 180 s), no snapshot" "STALE record explained, not unknown format"
    expect_out "PMCP_RGLAST_DONE" "rglast runs to the end on a STALE record"
    PMCP_RG_MAILBOX="$W/none" $SH "$W/rgm/t.sh" > "$W/out" 2>&1
    expect_out "no $W/none/latest.bin" "no mailbox: says so"

    echo "[19] earlier cards: v1.3.0 rg, experimental rgluasfm, experimental Android Auto, removed packages"
    if card_ok "$V13" v1.3.0 && card_ok "$EXP" ab9fb348; then
    fresh_unit; factory=$(snapshot "$W/unit")
    run13 install map-square-fps40; rc_is 0; run13 rg-system-on; rc_is 0; run13 java-on nai; rc_is 0; run13 java-on rg; rc_is 0
    confirm_now
    # interrupted before the HMI_BOOT switch (new JAR already in place): the old confirmed set loads, java-update finishes
    run rg-update; rc_is 0; cp "$W/sd/payload/jars/pmcp-guidance4.jar" "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar"
    run status; expect_out "Unit state: JAVA" "new JAR before the switch: JAVA"; expect_out "packages of an earlier card: rg" "old rg still reported"
    o=$(unit_boot); case "$o" in "boot=yes set=$NAI+rg-717fb53c jars="*pmcp-rg.jar) ok "old confirmed set still loads, new JAR not" ;; *) bad "boot: $o" ;; esac
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK set=$NAI+$RG" "java-update finishes from there"
    run restore; rc_is 0
    run13 install map-square-fps40; rc_is 0; run13 rg-system-on; rc_is 0; run13 java-on nai; rc_is 0; run13 java-on rg; rc_is 0
    confirm_now
    run java-update; rc_is 1; expect_out "JAVA_UPDATE_NEEDS_RG_SYSTEM_ON_old" "java-update to rg needs this card's RG files first"
    run rg-update; rc_is 0; expect_out "driver: replaced, reader: replaced" "rg-update replaces both"
    run rg-update; rc_is 1; expect_out "RG_UPDATE_ALREADY_CURRENT" "second rg-update: already current"
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK set=$NAI+$RG" "v1.3.0 rg -> rg"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rg.jar" ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] && ok "old pmcp-rg.jar gone, pmcp-guidance4.jar in place" || bad "JARs after java-update"
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI+$RG jars=/X/lsd/jars/NavActiveIgnore.jar:/X/lsd/jars/pmcp-guidance4.jar" ] && ok "java-update: trial boot" || bad "boot: $o"
    run java-update; rc_is 1; expect_out "JAVA_UPDATE_ALREADY_CURRENT" "second java-update: already current"
    # interrupted after the HMI_BOOT switch (old JAR still there): JAVA, trial confirmable, java-update removes the JAR
    cp "$V13D/payload/jars/pmcp-rg.jar" "$U/eso/hmi/lsd/jars/pmcp-rg.jar"
    run status; expect_out "Unit state: JAVA" "unused old JAR: still JAVA"; expect_out "unused JAR files (not loaded): pmcp-rg.jar" "unused JAR reported"
    case " $(cat "$U/carplaymaps/HMI_BOOT") " in *" pmcp-rg.jar "*) bad "unused JAR in HMI_BOOT" ;; *) ok "unused JAR not in the boot list" ;; esac
    run java-confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK set=$NAI+$RG" "trial set confirmable with an unused JAR"
    run java-update; rc_is 0; expect_out "unused JARs of an interrupted update removed" "java-update removes the unused JAR"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rg.jar" ] && ok "unused JAR gone" || bad "unused JAR left"
    run rg-system-off; rc_is 1; expect_out "TURN_OFF_JAVA_PACKAGE_RG_FIRST" "RG system stays while rg is on"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: exact factory tree" || bad "tree after restore"
    # the earlier experimental card (ab9fb348): RG with rgluasfm (its driver and reader are this card's), Android Auto gamma
    # on. On this branch its AA set is "old" (not UNKNOWN): every other action still works, aa-on brings it up to date.
    runexp install map-square-fps40; rc_is 0; runexp rg-system-on; rc_is 0; runexp java-on nai; rc_is 0; runexp java-on rgluasfm; rc_is 0
    confirm_now; runexp aa-on gamma; rc_is 0
    run status; expect_out "Unit state: JAVA" "earlier experimental card's AA: JAVA"; expect_out "Android Auto: old mode=gamma" "its AA set: old gamma"
    expect_out "packages of an earlier card: rgluasfm" "rgluasfm reported as an earlier card's package"
    run aa-confirm; rc_is 1; expect_out "AA_CONFIRM_NEEDS_AA_ON_old" "no confirm on an old AA set"
    # aa-remove refuses without a verified factory gal copy, and changes nothing
    cp "$U/carplaymaps/aa/gal.real" "$W/galreal"; printf x >> "$U/carplaymaps/aa/gal.real"; tampered=$(snapshot "$W/unit")
    run status; expect_out "Unit state: PARTIAL" "tampered factory gal copy: PARTIAL"
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_FACTORY_GAL_COPY_NOT_VERIFIED" "aa-remove: factory gal copy must verify"
    run restore; rc_is 1; [ "$tampered" = "$(snapshot "$W/unit")" ] && ok "bad gal copy: aa-remove and restore change nothing" || bad "changed with a bad gal copy"
    cp "$W/galreal" "$U/carplaymaps/aa/gal.real"
    run aa-remove; rc_is 0; expect_out "PMCP_AA_REMOVE_OK" "aa-remove ok"
    [ "$(h "$U/eso/bin/apps/gal")" = $STOCK_GAL ] && [ ! -e "$U/carplaymaps/aa" ] \
        && ! ls "$W/unit/mnt/persist/pmcp" | grep -q "^aa-" && ok "factory gal back, AA files and markers gone" || bad "after aa-remove"
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_ALREADY_NOT_INSTALLED" "second aa-remove: nothing to do"
    cp "$U/eso/bin/apps/gal" "$U/eso/bin/apps/gal.pmcp-restore"
    run status; expect_out "Unit state: PARTIAL" "leftover gal.pmcp-restore of an interrupted AA off: PARTIAL"
    run aa-remove; rc_is 0; [ ! -e "$U/eso/bin/apps/gal.pmcp-restore" ] && ok "aa-remove cleans gal.pmcp-restore" || bad "gal.pmcp-restore left"
    run status; expect_out "Unit state: JAVA" "after AA remove: JAVA"; expect_out "Android Auto: off" "AA off"
    allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: rgluasfm -> rg"; expect_out "PMCP_FEATURES_ON_OK" "button 3 done"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "set nai np rg zoom dn ui" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rgluasfm.jar" ] && ok "pmcp-rgluasfm.jar removed" || bad "old JAR left"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore after the experimental card: exact factory tree" || bad "tree after restore"
    # button 3 on a unit with the earlier card's AA and rgluasfma: AA stays (old), rgluasfma -> rg (AA arrows included), one set
    runexp install map-square-fps40; rc_is 0; runexp rg-system-on; rc_is 0; runexp java-on rgluasfma; rc_is 0
    confirm_now; runexp aa-on gamma; rc_is 0; aa_before=$(cat "$U/carplaymaps/aa/AA_BOOT")
    allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: rgluasfma updated"
    expect_out "PMCP_FEATURES_ON_OK" "button 3 on an AA unit done"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "set nai np rg zoom dn ui" || bad "after button 3: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rgluasfma.jar" ] \
        && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance.jar" ] && ok "pmcp-guidance4.jar only" || bad "JARs after button 3: $(ls "$U/eso/hmi/lsd/jars" | grep pmcp | tr '\n' ' ')"
    [ "$(cat "$U/carplaymaps/aa/AA_BOOT")" = "$aa_before" ] && ok "button 3 leaves Android Auto alone" || bad "AA changed by button 3"
    run status; expect_out "Android Auto: old mode=gamma" "AA still the earlier card's set"
    run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "aa-on brings the earlier card's AA set up to date"
    run status; expect_out "Unit state: JAVA" "JAVA with AA on"; expect_out "Android Auto: on mode=gamma" "AA on gamma"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore with AA on: factory" || bad "tree after restore"
    # an earlier card's AA mode this card does not know (AA 2, most): unknown -> PARTIAL; aa-remove and restore still work
    runexp install map-clean; rc_is 0; runexp aa-on most; rc_is 0
    run status; expect_out "Unit state: PARTIAL" "earlier card's AA 2: PARTIAL"
    run aa-remove; rc_is 0; run status; expect_out "Unit state: VIDEO" "AA 2 removed: VIDEO"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: factory" || bad "tree after restore"
    # AA on a carplaymaps that is not a pmcp install (factory lsd.sh copy broken): aa-remove/restore write nothing
    runexp install map-clean; rc_is 0; runexp aa-on most; rc_is 0; printf x >> "$U/carplaymaps/rollback/lsd.sh"; broken=$(snapshot "$W/unit")
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_NOT_A_PMCP_INSTALL" "aa-remove refuses a non-pmcp carplaymaps"
    run restore; rc_is 1; [ "$broken" = "$(snapshot "$W/unit")" ] && ok "nothing written on a non-pmcp carplaymaps" || bad "wrote on a non-pmcp carplaymaps"
    fresh_unit
    # Remove everything straight on a unit with an earlier card's AA
    runexp install map-clean; rc_is 0; runexp aa-on most; rc_is 0
    run restore; rc_is 0; expect_out "taking it off first" "restore takes AA off first"
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore with an earlier card's AA: exact factory tree" || bad "tree after restore with AA"
    # an earlier card's JAR with a wrong hash is not trusted: PARTIAL, restore
    run13 install map-square-fps40; rc_is 0; run13 rg-system-on; rc_is 0; run13 java-on rglu; rc_is 0
    printf x >> "$U/eso/hmi/lsd/jars/pmcp-rglu.jar"
    run status; expect_out "Unit state: PARTIAL" "modified old JAR: PARTIAL"; run java-update; rc_is 1
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: factory" || bad "tree after restore"
    for gone in rglu rgluasfm rgl dn2 kf kf4; do
        run install map-clean > /dev/null; run java-on $gone; rc_is 1; expect_out "UNKNOWN_JAVA_PACKAGE_$gone" "$gone is not a package of this card"
        run restore > /dev/null
    done
    fi

    fi
    echo "[22] optional native speed-limit reader: confirmed opt-in, persistent mode, disable and removal"
    fresh_unit
    SLP="$W/unit/mnt/persist/pmcp"; SLM="$SLP/native-speedlimit-mode"
    SLL="$W/unit/ramdisk/pmcp-speedlimit.lock"
    before=$(snapshot "$W/unit")
    run speedlimit-status; rc_is 0; expect_out "Saved native speed-limit mode: off (default)" "absent mode defaults off"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "reader status is read-only" || bad "reader status changed files"
    run speedlimit-mode off; rc_is 0
    [ ! -e "$SLP" ] && ok "disable on factory unit creates no configuration" || bad "disable created persist files"
    mkdir -p "$SLP"
    printf street > "$SLM"
    run speedlimit-status; rc_is 0; expect_out "mode: invalid (reader output is off)" "mode without final LF reported invalid"
    printf 'street\n\n' > "$SLM"
    run speedlimit-status; rc_is 0; expect_out "mode: invalid (reader output is off)" "mode with an extra LF reported invalid"
    printf 'street\n' > "$SLM"
    run speedlimit-status; rc_is 0; expect_out "mode: street" "exact current-road mode reported valid"
    printf 'turnto\n' > "$SLM"
    run speedlimit-status; rc_is 0; expect_out "mode: turnto" "exact next-road mode reported valid"
    printf 'off\n' > "$SLM"
    run speedlimit-status; rc_is 0; expect_out "mode: off" "exact disabled mode reported valid"
    run speedlimit-mode unknown; rc_is 1; expect_out "UNKNOWN_SPEEDLIMIT_MODE" "unknown mode refused"
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_NEEDS_JAVA_STATE_STOCK" "enable needs Java install"
    run install map-square; rc_is 0; run java-on nai; rc_is 0; run rg-system-on; rc_is 0; run java-on rg; rc_is 0
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_PACKAGE_NOT_INSTALLED" "enable needs sl package"
    mkdir -p "$SLP"; echo turnto > "$SLM"
    run java-on sl; rc_is 0; expect_out "PMCP_JAVA_ON_OK package=sl" "install optional reader"
    [ ! -e "$SLM" ] && ok "install clears stale mode to off" || bad "reader installed with stale active mode"
    read slset sljars < "$U/carplaymaps/HMI_BOOT"
    slboot=$(cat "$U/carplaymaps/HMI_BOOT")
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_CONFIRM_JAVA_SET_FIRST" "enable before trial refused"
    unit_boot > /dev/null
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_CONFIRM_JAVA_SET_FIRST" "unconfirmed running trial refused"
    run java-confirm; rc_is 0
    run speedlimit-mode turnto; rc_is 0; expect_out "PMCP_SPEEDLIMIT_MODE_OK mode=turnto" "confirmed running trial can enable"
    [ "$(cat "$SLM")" = turnto ] && [ "$slboot" = "$(cat "$U/carplaymaps/HMI_BOOT")" ] \
        && ok "mode saved without changing Java set" || bad "mode or Java set changed incorrectly"
    unit_boot > /dev/null
    [ "$(cat "$SLM")" = turnto ] && ok "mode survives a confirmed boot" || bad "mode lost at reboot"
    run speedlimit-mode street; rc_is 0
    [ "$(cat "$SLM")" = street ] && ok "CLI can select current-road text" || bad "street mode not saved"
    echo "set=$slset use=no" > "$SLP/last-boot"
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_NOT_RUNNING_THIS_SET" "fallback cannot enable despite old ok marker"
    [ "$(cat "$SLM")" = street ] && ok "failed enable preserves saved mode" || bad "failed enable changed mode"
    echo "set=other use=yes" > "$SLP/last-boot"
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_NOT_RUNNING_THIS_SET" "stale other-set boot cannot enable"
    echo "set=$slset use=yes" > "$SLP/last-boot"
    touch "$SLP/DISABLED"
    run speedlimit-mode turnto; rc_is 1; expect_out "JAVA_DISABLED_BY_RESCUE_CARD" "rescue-disabled set cannot enable"
    # Disable must still work when the card, firmware and running-set checks all fail.
    echo corrupt > "$W/sd/bin/selftest.bin"
    truncate -s 1 "$W/unit/ifs/lsd.jxe"
    run speedlimit-mode off; rc_is 0; expect_out "PMCP_SPEEDLIMIT_MODE_OK mode=off" "disable bypasses card and firmware checks"
    [ "$(cat "$SLM")" = off ] && ok "fallback disable is persistent" || bad "fallback disable failed"
    printf 'PMCP_NATIVE_SPEEDLIMIT\nvalue=70\n' > "$W/unit/ramdisk/pmcp-speedlimit.state"
    before=$(snapshot "$W/unit")
    run speedlimit-status; rc_is 0; expect_out "value=70" "status shows reader snapshot even during fallback"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "snapshot viewing is read-only" || bad "snapshot viewer changed files"
    cp "$SDB/pmcp/bin/selftest.bin" "$W/sd/bin/selftest.bin"
    truncate -s 55830309 "$W/unit/ifs/lsd.jxe"
    rm -f "$SLP/DISABLED"
    run speedlimit-mode turnto; rc_is 0
    mkdir "$SLL"; echo owner > "$SLL/owner"
    run speedlimit-mode off; rc_is 1; expect_out "SPEEDLIMIT_LOCK_BUSY" "competing mode action refused"
    [ "$(cat "$SLM")" = turnto ] && [ "$(cat "$SLL/owner")" = owner ] && ok "loser preserves owner's lock and mode" || bad "loser changed lock or mode"
    run java-off sl; rc_is 1; expect_out "SPEEDLIMIT_LOCK_BUSY" "Java removal shares the mode lock"
    rm -rf "$SLL"
    run java-off nai; rc_is 0
    [ "$(cat "$SLM")" = turnto ] && ok "removing another package preserves the mode" || bad "unrelated removal cleared mode"
    run java-off sl; rc_is 0
    [ ! -e "$SLM" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-sl2.jar" ] && ok "reader removal clears configuration and jar" || bad "reader removal left state"
    run speedlimit-mode off; rc_is 0
    run java-on sl; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    run speedlimit-mode turnto; rc_is 0
    o=$(unit_boot); case "$o" in "boot=yes "*pmcp-guidance4.jar*pmcp-sl2.jar) ok "rg and sl load together" ;; *) bad "boot: $o" ;; esac
    # without rg nothing writes TurnToInfo text: turnto is refused, the CurrentPositionInfo trial (street) is not
    run java-off rg; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    [ ! -e "$SLM" ] && ok "removing rg resets turnto to off" || bad "turnto kept without rg"
    run speedlimit-mode turnto; rc_is 1; expect_out "SPEEDLIMIT_TURNTO_NEEDS_RG_PACKAGE" "turnto needs rg"
    run speedlimit-mode street; rc_is 0; expect_out "PMCP_SPEEDLIMIT_MODE_OK mode=street" "CurrentPositionInfo trial without rg"
    # a lock left by a killed script blocks only mode and package changes, never Confirm, Try again or Remove everything
    mkdir "$SLL"
    run java-retry; rc_is 0; run java-confirm; rc_is 1; expect_out "SET_ALREADY_CONFIRMED" "confirm runs past a stale lock (set confirmed already)"
    expect_out_not() { grep -q "$1" "$W/out" && bad "$2" || ok "$2"; }
    expect_out_not "SPEEDLIMIT_LOCK_BUSY" "java-confirm does not wait for the lock"
    run java-on np; rc_is 1; expect_out "SPEEDLIMIT_LOCK_BUSY" "package change waits for the lock"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "restore runs past a stale lock"
    [ ! -e "$SLP" ] && ok "full restore clears the mode" || bad "full restore left the mode"
    rm -rf "$SLL"

    echo "[23] v1.4.0 card -> this card: button 3's rg-update and java-update, then sl"
    if card_ok "$V140" v1.4.0; then
    fresh_unit; factory=$(snapshot "$W/unit")
    run140 install map-square-fps40; rc_is 0; run140 rg-system-on; rc_is 0; run140 java-on nai; rc_is 0; run140 java-on rg; rc_is 0
    confirm_now
    run status; expect_out "packages of an earlier card: rg" "v1.4.0 rg reported as an earlier card's package"
    run rg-update; rc_is 1; expect_out "RG_UPDATE_ALREADY_CURRENT" "v1.4.0 driver and reader are this card's"
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK set=$NAI+$RG" "v1.4.0 rg -> this card's rg"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance.jar" ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] \
        && ok "pmcp-guidance.jar gone, pmcp-guidance4.jar in place" || bad "JARs after java-update from v1.4.0"
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI+$RG jars=/X/lsd/jars/NavActiveIgnore.jar:/X/lsd/jars/pmcp-guidance4.jar" ] && ok "one trial start" || bad "boot: $o"
    run java-confirm; rc_is 0
    run java-on sl; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    run speedlimit-mode turnto; rc_is 0
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: exact factory tree" || bad "restore after v1.4.0 -> v1.4.1 left changes"
    fi

    echo "[24] v1.4.2 card -> this card: java-update replaces rg (pmcp-guidance2.jar -> pmcp-guidance4.jar), sl and its mode stay"
    if card_ok "$V142" v1.4.2; then
    fresh_unit; factory=$(snapshot "$W/unit")
    run142 install map-square-fps40; rc_is 0; run142 rg-system-on; rc_is 0; run142 java-on nai; rc_is 0; run142 java-on rg; rc_is 0
    run142 java-on sl; rc_is 0; unit_boot > /dev/null; run142 java-confirm; rc_is 0
    run142 speedlimit-mode turnto; rc_is 0; expect_out "PMCP_SPEEDLIMIT_MODE_OK mode=turnto" "v1.4.2 card saves turnto"
    run status; expect_out "packages of an earlier card: rg" "v1.4.2 rg reported as an earlier card's package"
    run rg-update; rc_is 1; expect_out "RG_UPDATE_ALREADY_CURRENT" "v1.4.2 driver and reader are this card's"
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "v1.4.2 rg -> this card's rg"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance2.jar" ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] \
        && ok "pmcp-guidance2.jar gone, pmcp-guidance4.jar in place" || bad "JARs after java-update from v1.4.2"
    o=$(unit_boot); case "$o" in "boot=trial "*pmcp-guidance4.jar*pmcp-sl2.jar) ok "one trial start with the new rg and sl" ;; *) bad "boot: $o" ;; esac
    run java-confirm; rc_is 0
    [ "$(cat "$SLM" 2>/dev/null)" = turnto ] && ok "speed-limit mode kept across the rg update" || bad "speed-limit mode lost"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: exact factory tree" || bad "restore after v1.4.2 -> v1.4.3 left changes"
    fi

    echo "[25] experimental card f2a7ceb5 (AA on, rg-aa) -> button 3 of this card: AA stays, rg-aa -> rg (pmcp-guidance4.jar)"
    ALL="$NAI+$NP+$RG+$ZOOM+$DN+$UI"
    no_aa_change() { grep -q "PMCP_AA_\(ON\|REMOVE\)_OK" "$W/out" && bad "$1: button 3 changed Android Auto" || ok "$1: button 3 ran no AA action"; }
    if card_ok "$EXP141" f2a7ceb5; then
        fresh_unit; factory=$(snapshot "$W/unit")
        runexp141 install map-square-fps40; rc_is 0; runexp141 rg-system-on; rc_is 0; runexp141 java-on nai; rc_is 0
        runexp141 java-on rg-aa; rc_is 0; confirm_now; runexp141 aa-on; rc_is 0
        grep -q "pmcp-guidance-aa.jar" "$U/carplaymaps/HMI_BOOT" && ok "f2a7ceb5 unit: rg-aa in the set, AA on" || bad "f2a7ceb5 setup: $(cat "$U/carplaymaps/HMI_BOOT")"
        aa_before=$(cat "$U/carplaymaps/aa/AA_BOOT"); aa_files=$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$')
        run status; expect_out "packages of an earlier card: rg-aa" "rg-aa 4f9215bf reported as an earlier card's package"
        expect_out "Android Auto: old mode=gamma" "its AA set (feeder v9): old"
        allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: rg-aa -> rg"
        expect_out "PMCP_FEATURES_ON_OK" "button 3 done"; no_aa_change "f2a7ceb5"
        [ "$(cat "$U/carplaymaps/aa/AA_BOOT")" = "$aa_before" ] && [ "$aa_files" = "$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$')" ] \
            && ok "AA_BOOT and every AA file unchanged by button 3" || bad "AA changed by button 3"
        [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "set nai np rg zoom dn ui" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
        [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance-aa.jar" ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] \
            && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance-aa2.jar" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance3.jar" ] \
            && ok "pmcp-guidance-aa.jar gone, pmcp-guidance4.jar (rg) in place" || bad "JARs after button 3 from f2a7ceb5: $(ls "$U/eso/hmi/lsd/jars" | grep pmcp | tr '\n' ' ')"
        o=$(unit_boot); case "$o" in "boot=trial set=$ALL jars="*pmcp-guidance4.jar*) ok "one trial start with rg" ;; *) bad "boot: $o" ;; esac
        run java-confirm; rc_is 0
        # AA 1 then brings the AA set itself up to date (a newer set: new AA_BOOT, a new AA trial)
        run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "AA 1: the earlier card's AA set brought up to date"
        grep -q "need rg" "$W/out" && bad "aa-on asks for rg although rg is on" || ok "rg on: aa-on does not ask for an arrows package"
        [ "$(cat "$U/carplaymaps/aa/AA_BOOT")" != "$aa_before" ] && [ "$(h "$U/carplaymaps/aa/feeder.conf")" = ac7157dabd7ae3ec61e8b9c453451b5716154b2b068d552dd96a94a83852e75d ] \
            && ok "AA_BOOT changed only by AA 1 (newer AA set)" || bad "AA after AA 1: $(cat "$U/carplaymaps/aa/AA_BOOT")"
        run status; expect_out "Android Auto: on mode=gamma" "AA on"
        run restore; rc_is 0
        [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore after f2a7ceb5 -> this card: exact factory tree" || bad "tree after restore"
    fi

    echo "[26] experimental card 84472aa9 (v1.4.3 + AA on, rg-aa 01221496 in pmcp-guidance-aa2.jar) -> button 3: AA stays, rg-aa -> rg (pmcp-guidance4.jar)"
    if card_ok "$EXP143" 84472aa9; then
        fresh_unit; factory=$(snapshot "$W/unit")
        runexp143 install map-square-fps40; rc_is 0; runexp143 rg-system-on; rc_is 0; runexp143 java-on nai; rc_is 0
        runexp143 java-on rg-aa; rc_is 0; confirm_now; runexp143 aa-on; rc_is 0
        grep -q "pmcp-guidance-aa2.jar" "$U/carplaymaps/HMI_BOOT" && ok "84472aa9 unit: rg-aa 01221496 in the set" || bad "setup: $(cat "$U/carplaymaps/HMI_BOOT")"
        aa_before=$(cat "$U/carplaymaps/aa/AA_BOOT"); aa_files=$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-')
        run status; expect_out "packages of an earlier card: rg-aa" "rg-aa 01221496 reported as an earlier card's package"
        expect_out "Android Auto: old mode=gamma" "its AA set (2 Mbit/s): old"
        allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: rg-aa -> rg"; expect_out "PMCP_FEATURES_ON_OK" "button 3 done"; no_aa_change "84472aa9"
        [ "$(cat "$U/carplaymaps/aa/AA_BOOT")" = "$aa_before" ] && [ "$aa_files" = "$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-')" ] \
            && ok "AA files, AA_BOOT and AA markers untouched" || bad "AA changed by button 3"
        [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance-aa2.jar" ] \
            && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] && ok "pmcp-guidance-aa2.jar -> pmcp-guidance4.jar (this card's rg)" || bad "after button 3: $(cat "$U/carplaymaps/HMI_BOOT")"
        o=$(unit_boot); case "$o" in "boot=trial set=$ALL jars="*pmcp-guidance4.jar*) ok "one trial start" ;; *) bad "boot: $o" ;; esac
        run java-confirm; rc_is 0
        allon; expect_out "everything was already on, nothing changed" "second press: nothing to do"
        run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "AA 1 updates the 2 Mbit/s set"
        grep -q '^PMCP_AA_PACE_KBPS=6000$' "$U/carplaymaps/aa/feeder.conf" && ok "6 Mbit/s settings" || bad "feeder.conf not updated"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore with AA: exact factory tree" || bad "tree after restore"
    fi

    echo "[27] Android Auto (its own screen, mode gamma): gal wrapper, trial start, confirm, rg arrows, removal"
    AAH=/mnt/app/carplaymaps/aa; AAD="$U/carplaymaps/aa"
    HOOKED="use=trial real=gal.real preload=$AAH/libgal_hook.so conf=$AAH/gal-hook.conf player=$AAH/aa-most-feeder"
    fresh_unit; factory=$(snapshot "$W/unit")
    run aa-on; rc_is 1; expect_out "AA_NEEDS_STAGE_A_STATE_STOCK" "AA needs stage A"
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "unit unchanged" || bad "aa-on on a factory unit changed it"
    run install map-square-fps40; rc_is 0
    run status; expect_out "Android Auto: off" "status: AA off"
    run aa-on most; rc_is 1; expect_out "AA_MODE_UNKNOWN_most" "only gamma on this card"
    run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "aa-on: gamma"; expect_out "VW arrows from Google Maps need rg: main menu, 4. Install additional features." "without rg: says rg (button 3) gives the arrows"
    [ "$(h "$AAD/gal.real")" = $STOCK_GAL ] && ok "factory gal copied" || bad "gal.real"
    [ "$(h "$U/eso/bin/apps/gal")" != $STOCK_GAL ] && head -1 "$U/eso/bin/apps/gal" | grep -q '^#!/bin/sh' && ok "gal is the wrapper" || bad "gal not replaced"
    grep -q '^GAL_PMCP_RG=1$' "$AAD/gal-hook.conf" && grep -q '^GAL_DUALSCREEN_AAP_MINOR=7$' "$AAD/gal-hook.conf" && ok "hook settings: 1.7 + rg feed" || bad "gal-hook.conf"
    grep -q '^PMCP_AA_MODE=most$' "$AAD/feeder.conf" && grep -q '^PMCP_AA_PACE_KBPS=6000$' "$AAD/feeder.conf" && grep -q '^PMCP_AA_SYNC_HOLD_MS=3000$' "$AAD/feeder.conf" \
        && ! grep -q 'KF_METHOD\|KF_TAKE' "$AAD/feeder.conf" && ok "feeder settings: MOST, pacing, start sync, no probe" || bad "feeder.conf"
    [ -x "$AAD/aa-most-feeder" ] && [ -x "$AAD/gal.real" ] && [ ! -e "$U/carplaymaps/.aa-new" ] && ok "executables, no staging leftovers" || bad "aa files"
    case "$(cat "$AAD/AA_BOOT")" in gamma-bdd76a85-*-716516eb) ok "set id gamma-hook-feeder-conf" ;; *) bad "AA_BOOT $(cat "$AAD/AA_BOOT")" ;; esac
    run status; expect_out "Unit state: VIDEO" "still VIDEO with AA"; expect_out "Android Auto: on mode=gamma" "status: AA on"
    run aa-on; rc_is 1; expect_out "AA_ALREADY_ON" "second aa-on refused"
    run aa-confirm; rc_is 1; expect_out "AA_NO_TRIAL_YET" "confirm before any AA connection refused"
    new_start
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "1st AA connection: trial with the hook" || bad "gal 1: $o"
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "reconnect in the same start: still the trial" || bad "gal 2: $o"
    new_start
    o=$(gal_start); [ "$o" = "use=no real=gal.real preload= conf= player=" ] && ok "next start without confirm: factory gal" || bad "gal 3: $o"
    run aa-confirm; rc_is 1; expect_out "AA_NOT_IN_THE_TRIAL_START" "confirm outside the trial start refused"
    run aa-retry; rc_is 0; new_start
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "after retry: trial again" || bad "gal 4: $o"
    run aa-status; rc_is 0; expect_out "TRIAL in this start" "status shows the trial"; expect_out "No stream analysis yet" "no analysis yet"
    printf 'PMCP AA FEEDER v9 mode=most czas=12s\ndawkowanie: 2000 kbit/s zapas 64 KB opoznione=3\n' > "$W/unit/ramdisk/pmcp-aa-feeder.txt"
    printf 'RG AA: komunikaty 0x8003=1 0x8006=3 0x8007=9 prowadzenie=tak\nmanewry rozpoznane=3 nierozpoznane=0\n' > "$W/unit/ramdisk/pmcp-aa-rg.txt"
    run aa-status; expect_out "  dawkowanie: 2000 kbit/s" "status shows the feeder summary"; expect_out "  manewry rozpoznane=3 nierozpoznane=0" "status shows the manoeuvre feed"
    run aa-confirm; rc_is 0; expect_out "PMCP_AA_CONFIRM_OK set=gamma-" "confirm in the trial start"
    run aa-confirm; rc_is 1; expect_out "AA_ALREADY_CONFIRMED" "second confirm refused"
    new_start
    o=$(gal_start); [ "$o" = "${HOOKED/use=trial/use=yes}" ] && ok "confirmed: hook on every start" || bad "gal 5: $o"
    touch "$W/unit/mnt/persist/pmcp/DISABLED"
    o=$(gal_start); [ "$o" = "use=no real=gal.real preload= conf= player=" ] && ok "rescue card DISABLED: factory gal" || bad "gal 6: $o"
    rm "$W/unit/mnt/persist/pmcp/DISABLED"
    # rg carries the Android Auto arrows (since v1.5.0): no separate package; rg needs the RG system as before
    run java-on rg-aa; rc_is 1; expect_out "UNKNOWN_JAVA_PACKAGE_rg-aa" "rg-aa is not a package of this card"
    run java-on rg; rc_is 1; expect_out "JAVA_RG_NEEDS_RG_SYSTEM_ON_off" "rg needs the RG system"
    run rg-system-on; rc_is 0; run java-on nai; rc_is 0; run java-on rg; rc_is 0; confirm_now
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$NAI+$RG" ] && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] \
        && ok "AA on + rg: set nai rg, pmcp-guidance4.jar" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ "$(h "$AAD/gal.real")" = $STOCK_GAL ] && case "$(cat "$AAD/AA_BOOT")" in gamma-*) true ;; *) false ;; esac && ok "java-on rg leaves AA as it is" || bad "AA after java-on rg"
    run rg-system-off; rc_is 1; expect_out "TURN_OFF_JAVA_PACKAGE" "RG system stays while rg is on"
    run aa-status; rc_is 0; run status; expect_out "Unit state: JAVA" "Java + AA: JAVA"
    run aa-remove; rc_is 0; expect_out "PMCP_AA_REMOVE_OK" "aa-remove"
    [ "$(h "$U/eso/bin/apps/gal")" = $STOCK_GAL ] && [ ! -e "$AAD" ] && ok "factory gal, aa/ removed" || bad "aa-remove left files"
    ls "$W/unit/mnt/persist/pmcp" | grep -q '^aa-' && bad "AA markers left" || ok "AA markers removed"
    run status; expect_out "Unit state: JAVA" "Java untouched by aa-remove"
    run aa-on; rc_is 0; expect_out "is a TRIAL" "after aa-remove the same set starts with a new trial (markers were removed)"
    grep -q "need rg" "$W/out" && bad "aa-on asks for rg although rg is on" || ok "rg on: aa-on does not ask for an arrows package"
    new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "aa-on after aa-remove: trial" || bad "gal after re-install: $o"
    cp "$AAD/gal.real" "$U/eso/bin/apps/gal"
    run status; expect_out "Unit state: PARTIAL" "interrupted AA (aa/ without the wrapper): PARTIAL"
    run aa-remove; rc_is 0; run status; expect_out "Unit state: JAVA" "aa-remove repairs it"
    # earlier cards' AA sets (AA_OLD): whole tuple + its own AA_BOOT = old; a mix = PARTIAL, never old
    OLDC="${PMCP_EXP_SD:-$SDB/../sd-ab9fb348}/pmcp/payload/aa"; OLDG1="${PMCP_AA_OLDG1:-$SDB/../sd-662eb7a8}/pmcp/payload/aa"
    OLD9="${PMCP_AA_OLD9:-$SDB/../sd-f2a7ceb5}/pmcp/payload/aa"; OLD10="${PMCP_AA_OLD10:-$SDB/../sd-030b7df2}/pmcp/payload/aa"
    OLD7="${PMCP_AA_OLD7:-$SDB/../sd-9766265d}/pmcp/payload/aa"
    if card_ok "$OLDC" ab9fb348 && card_ok "$OLDG1" 662eb7a8 && card_ok "$OLD9" f2a7ceb5 && card_ok "$OLD10" 030b7df2 \
        && card_ok "$OLD7" 9766265d; then
    run aa-on; rc_is 0
    cp "$OLDC/aa-most-feeder-sync" "$AAD/aa-most-feeder"; cp "$OLDC/feeder-gamma.conf" "$AAD/feeder.conf"
    echo "gamma-bdd76a85-5ec1a191-716516eb" > "$AAD/AA_BOOT"
    run status; expect_out "Unit state: JAVA" "card ab9fb348's gamma set: not PARTIAL"; expect_out "Android Auto: old mode=gamma" "status: old gamma"
    run aa-status; expect_out "Android Auto on brings them up to date" "aa-status says what to do"
    run aa-on; rc_is 0; [ "$(h "$AAD/aa-most-feeder")" != "$(h "$OLDC/aa-most-feeder-sync")" ] && grep -q PACE_KBPS "$AAD/feeder.conf" && ok "feeder v8 -> v9, pacing settings" || bad "not updated"
    # card f2a7ceb5 / fd0c7a7c (feeder v9) -> v10 (A-AA33): the set on the unit before the v10 card
    cp "$OLD9/aa-most-feeder" "$AAD/aa-most-feeder"; cp "$OLD9/feeder.conf" "$AAD/feeder.conf"; cp "$OLD9/libgal_hook.so" "$AAD/libgal_hook.so"; cp "$OLD9/gal-hook.conf" "$AAD/gal-hook.conf"
    echo "gamma-bdd76a85-5d2a0a02-716516eb" > "$AAD/AA_BOOT"
    run status; expect_out "Android Auto: old mode=gamma" "card f2a7ceb5's gamma set (feeder v9): old"
    run aa-on; rc_is 0; [ "$(h "$AAD/aa-most-feeder")" = c5f8b0ef3821b3a533cd762fab14ff984fffa0afe4fd66185e16ea57413149a7 ] && grep -q '^PMCP_AA_PACE_GAP_MS=20$' "$AAD/feeder.conf" && grep -q '^PMCP_AA_KF_BRIDGE=0$' "$AAD/feeder.conf" && ok "feeder v9 -> v10, gap + no focus cycle" || bad "v9 not updated"
    # card 030b7df2 (feeder v10, 2 Mbit/s pacing) -> 6 Mbit/s settings (A-AA34): same AA_BOOT, only feeder.conf differs
    cp "$OLD10/feeder.conf" "$AAD/feeder.conf"
    run status; expect_out "Android Auto: old mode=gamma" "card 030b7df2's set (2 Mbit/s): old"
    run aa-on; rc_is 0; grep -q '^PMCP_AA_PACE_KBPS=6000$' "$AAD/feeder.conf" && ok "030b7df2 -> 6 Mbit/s pacing" || bad "030b7df2 settings not updated"
    cp "$OLDG1/libgal_hook-gamma.so" "$AAD/libgal_hook.so"
    run status; expect_out "Unit state: PARTIAL" "a mix (g1 hook in the current set): PARTIAL"
    run aa-on; rc_is 1; expect_out "AA_NEEDS_STAGE_A_STATE_PARTIAL" "mix: aa-on refused"
    cp "$OLDG1/aa-most-feeder-sync" "$AAD/aa-most-feeder"; cp "$OLDG1/gal-hook-gamma.conf" "$AAD/gal-hook.conf"; cp "$OLDG1/feeder-gamma.conf" "$AAD/feeder.conf"
    echo "gamma-aa0b97fc-27b32b35-716516eb" > "$AAD/AA_BOOT"
    run status; expect_out "Android Auto: old mode=gamma" "whole gamma g1 set with its AA_BOOT: old"
    cp "$OLD7/libgal_hook.so" "$AAD/libgal_hook.so"; cp "$OLD7/aa-most-feeder-sync" "$AAD/aa-most-feeder"; cp "$OLD7/gal-hook-17.conf" "$AAD/gal-hook.conf"
    cp "$OLD7/feeder-sync17.conf" "$AAD/feeder.conf"; echo "sync17-dd72104b-27b32b35-99288ee3" > "$AAD/AA_BOOT"
    run status; expect_out "Android Auto: old mode=sync17" "earlier card's AA 3 (1.7): old"
    run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "AA 3 (1.7) -> gamma"
    grep -q '^GAL_PMCP_RG=1$' "$AAD/gal-hook.conf" && [ "$(h "$AAD/libgal_hook.so")" = bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05 ] && ok "gamma hook and settings" || bad "after sync17 -> gamma"
    fi
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "restore with AA on: factory state"
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: every file as at the start" || bad "restore: unit differs from factory"

    echo "[28] AA saved logs and the log card"
    P="$W/unit/mnt/persist/pmcp"; RD="$W/unit/ramdisk"
    LC="$(cd "$(dirname "$0")/.." && pwd)/logcard/pmcp-logs.sh"
    logcard() { # the log card script as stuff.sh runs it at the end; medium = $W/med3
        rm -rf "$W/lr"; mkdir -p "$W/lr/net" "$W/med3"; ln -s "$W/unit" "$W/lr/net/mmx"
        PMCP_LOGCARD_TEST_ROOT="$W/lr" $SH "$LC" "$W/med3" >/dev/null 2>&1
    }
    navlog() { # a hook log with N 0x8006 and M 0x8007 lines
        : > "$RD/pmcp-gal-hook.log"
        i=0; while [ $i -lt $1 ]; do echo "t event=aap.nav_msg channel=12 msg_id=0x8006 bytes=40 n=$((i+1)) hex=80060a26" >> "$RD/pmcp-gal-hook.log"; i=$((i+1)); done
        i=0; while [ $i -lt $2 ]; do echo "t event=aap.nav_msg channel=12 msg_id=0x8007 bytes=20 n=$((i+1)) hex=80070a0e" >> "$RD/pmcp-gal-hook.log"; i=$((i+1)); done
    }
    fresh_unit; run install map-square-fps40; rc_is 0; run aa-on; rc_is 0
    new_start
    run aa-log-save; rc_is 1; expect_out "AA_LOG_EMPTY" "nothing to save without a hook log"
    navlog 3 2; echo "set=x use=yes" > "$RD/pmcp-aa-last"
    before=$(snapshot "$W/unit" | grep -v /logs/)
    run aa-log-save; rc_is 0; expect_out "PMCP_AA_LOG_SAVED file=logs/aa-log-1.txt" "log saved"
    expect_out "nav_0x8006=3 nav_0x8007=2" "counts in the save result"
    L1="$U/carplaymaps/logs/aa-log-1.txt"
    grep -q "msg_id=0x8007 bytes=20 n=2" "$L1" && grep -q "^set=x use=yes$" "$L1" && [ "$(tail -1 "$L1")" = "--- end" ] \
        && ok "saved file: hook log, gal start line, complete" || bad "saved file content"
    [ ! -e "$L1.pmcp-new" ] && ok "no temp file left" || bad "temp file left"
    ! grep -q "^--- pmcp-aa-feeder.txt-prev" "$L1" && ok "no earlier feeder status: no prev section" || bad "prev section without a file"
    echo "PMCP AA FEEDER v13 prev1" > "$RD/pmcp-aa-feeder.txt-prev1"; echo "PMCP AA FEEDER v13 prev3" > "$RD/pmcp-aa-feeder.txt-prev3"
    run aa-log-save; rc_is 0; L2="$U/carplaymaps/logs/aa-log-2.txt"
    grep -q "^--- pmcp-aa-feeder.txt-prev1$" "$L2" && grep -q "^PMCP AA FEEDER v13 prev3$" "$L2" && ! grep -q "prev2" "$L2" \
        && [ "$(tail -1 "$L2")" = "--- end" ] && ok "feeder v13: earlier sessions' status in the log" || bad "prev status missing in the log"
    rm -f "$RD"/pmcp-aa-feeder.txt-prev*
    [ "$before" = "$(snapshot "$W/unit" | grep -v /logs/)" ] && ok "log save wrote only carplaymaps/logs" || bad "log save changed other files"
    run aa-status; expect_out "Navigation messages logged in this start: 0x8006=3 0x8007=2" "status counts"
    expect_out "Saved AA logs (for the log card): aa-log-1.txt" "status lists saved logs"
    for n in 3 4 5; do run aa-log-save; done
    rc_is 0; [ -e "$U/carplaymaps/logs/aa-log-5.txt" ] && ok "five logs kept" || bad "fifth log missing"
    run aa-log-save; rc_is 1; expect_out "AA_LOGS_FULL_5" "sixth refused (nothing deleted)"
    run status; expect_out "Unit state: VIDEO" "saved logs do not change the unit state"
    before=$(snapshot "$W/unit")
    rm -rf "$W/med3"; logcard
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "log card: unit unchanged (read-only)" || bad "log card changed the unit"
    [ "$(ls "$W/med3/PMCP_LOGS" | grep -c '^aa-log-[1-5].txt$')" = 5 ] && cmp -s "$L1" "$W/med3/PMCP_LOGS/aa-log-1.txt" \
        && ok "log card: five logs copied, identical" || bad "log card copies: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" | head -1 | grep -q "^RESULT=OK copied=5 aa_logs=5 cp_logs=0$" && ok "log card: RESULT=OK" || bad "log card result: $(tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt")"
    : > "$U/carplaymaps/logs/._aa-log-1.txt"; mkdir -p "$U/carplaymaps/logs/odd"; : > "$U/carplaymaps/logs/odd/x"
    : > "$U/carplaymaps/logs/aa-log-9.txt.pmcp-new"; echo "boot set=x" >> "$P/boot.log"
    : > "$P/aa-stream.h264"; : > "$P/aa-stream.h264.idx"
    run aa-log-clear; rc_is 0; [ ! -e "$U/carplaymaps/logs" ] && ok "logs deleted (also unknown files and a subdirectory)" || bad "logs left"
    [ ! -e "$P/boot.log" ] && [ ! -e "$P/aa-stream.h264" ] && [ ! -e "$P/aa-stream.h264.idx" ] && ok "boot log and phone video deleted" || bad "left: $(ls "$P")"
    run aa-log-clear; rc_is 0; expect_out "PMCP_AA_LOG_CLEAR_OK (nothing saved, nothing to delete)" "second press: OK, nothing to delete"
    # A152: the GEM button log on the unit ($PERSIST/gem.log; the SD card is read-only in GEM)
    rung() { PMCP_TEST_GEMLOG= PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
    mkdir -p "$P"; rm -f "$P"/gem.log*; rung aa-status; rc_is 0
    head -1 "$P/gem.log" | grep -q "^=== .* aa-status " && grep -q "^Unit state: VIDEO$" "$P/gem.log" && ok "gem.log: header and the button's output" || bad "gem.log: $(head -3 "$P/gem.log")"
    rm -f "$RD/pmcp-gal-hook.log"; rung aa-log-save; rc_is 1; grep -q "^PMCP_FAIL=AA_LOG_EMPTY" "$P/gem.log" && ok "gem.log: a FAIL is logged" || bad "gem.log without the FAIL"
    i=0; while [ $i -lt 120 ]; do rung aa-status; i=$((i + 1)); done
    s0=$(ls -ln "$P/gem.log" | awk '{print $5}'); s1=$(ls -ln "$P/gem.log.1" 2>/dev/null | awk '{print $5}')
    [ -n "$s1" ] && [ "$s0" -le 40000 ] && [ "$s1" -le 40000 ] && ok "gem.log bounded: $s0 + $s1 B" || bad "gem.log sizes $s0 / $s1"
    rung aa-log-clear; rc_is 0; [ ! -e "$P/gem.log.1" ] && [ "$(grep -c '^===' "$P/gem.log")" = 1 ] && grep -q "aa-log-clear" "$P/gem.log" \
        && ok "aa-log-clear: gem.log starts again with this press" || bad "gem.log after clear: $(head -2 "$P/gem.log")"
    echo "older" > "$P/gem.log.1"; rm -rf "$W/med3"; logcard
    cmp -s "$P/gem.log" "$W/med3/PMCP_LOGS/pmcp-gem-log.txt" && cmp -s "$P/gem.log.1" "$W/med3/PMCP_LOGS/pmcp-gem-log-1.txt" \
        && ok "log card: gem.log and gem.log.1 copied" || bad "log card gem.log: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    rm -rf "$W/u2"; mkdir -p "$W/u2"; PMCP_TEST_GEMLOG= PMCP_TEST_ROOT="$W/u2" $SH "$W/sd/pmcp.sh" status > /dev/null 2>&1
    [ ! -e "$W/u2/mnt/persist/pmcp" ] && ok "gem.log: no persist dir made on an untouched unit" || bad "persist made by status"
    rm -rf "$W/u2"; rm -f "$P"/gem.log*
    rm -rf "$W/med3"; logcard
    grep -q "^RESULT=NO_LOGS" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card without logs: RESULT=NO_LOGS" || bad "empty log card result"
    navlog 1 1; run aa-log-save; rc_is 0
    run aa-remove; rc_is 0; run status; expect_out "Unit state: VIDEO" "saved logs left by aa-remove do not matter"
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "restore with saved logs: factory state"
    [ ! -e "$U/carplaymaps" ] && ok "restore removed saved logs with carplaymaps" || bad "carplaymaps left"

    echo "[29] v1.4.3-style unit (rg 7b187484 in pmcp-guidance3.jar, no AA) -> button 3: pmcp-guidance4.jar, no AA file"
    if card_ok "$EXP143" 84472aa9; then
        fresh_unit; factory=$(snapshot "$W/unit")
        # card 84472aa9's rg is the v1.4.3 release rg (same bytes, same file pmcp-guidance3.jar)
        runexp143 install map-square-fps40; rc_is 0; runexp143 rg-system-on; rc_is 0
        for n in nai np rg zoom dn; do runexp143 java-on $n; rc_is 0; done
        confirm_now
        [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance3.jar")" = 7b1874847c5cf9714ed3b7e24c948b425aafc367c03a884d6309c8fda93c8661 ] && ok "v1.4.3 rg in pmcp-guidance3.jar" || bad "setup: no v1.4.3 rg"
        run status; expect_out "packages of an earlier card: rg" "v1.4.3 rg reported as an earlier card's package"; expect_out "Android Auto: off" "AA off"
        allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: v1.4.3 rg -> rg"; expect_out "PMCP_FEATURES_ON_OK" "button 3 done"
        [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance3.jar" ] \
            && [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] && ok "pmcp-guidance3.jar -> pmcp-guidance4.jar" || bad "after button 3: $(cat "$U/carplaymaps/HMI_BOOT")"
        [ ! -e "$U/carplaymaps/aa" ] && [ ! -e "$U/carplaymaps/.aa-new" ] && [ "$(h "$U/eso/bin/apps/gal")" = $STOCK_GAL ] \
            && ! ls "$U/eso/bin/apps" | grep -q 'gal\.' && ! ls "$W/unit/mnt/persist/pmcp" | grep -q '^aa-' \
            && ok "button 3 without AA: no AA file created, factory gal" || bad "button 3 created AA files"
        run status; expect_out "Android Auto: off" "AA still off"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit")" ] && ok "restore: exact factory tree" || bad "tree after restore"

    fi

    echo "[30] unit with card b2bcbbe3's AA set (feeder c5f8b0ef, feeder.conf ac7157da): this card's own set, nothing to update"
    if card_ok "$EXPB2" b2bcbbe3; then
        fresh_unit; factory=$(snapshot "$W/unit")
        runexpb2 install map-square-fps40; rc_is 0; runexpb2 rg-system-on; rc_is 0; runexpb2 java-on nai; rc_is 0; runexpb2 java-on rg-aa; rc_is 0
        confirm_now; runexpb2 aa-on; rc_is 0
        S=$(cat "$U/carplaymaps/aa/AA_BOOT"); touch "$W/unit/mnt/persist/pmcp/aa-trial.$S" "$W/unit/mnt/persist/pmcp/aa-ok.$S"
        aa_files=$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-')
        run status; expect_out "Android Auto: on mode=gamma" "b2bcbbe3's AA set: on (this card's set)"
        run aa-status; rc_is 0; expect_out "set $S: confirmed" "its confirmation is kept"
        run aa-on; rc_is 1; expect_out "AA_ALREADY_ON" "AA 1: nothing to update"
        allon; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "button 3: its rg-aa -> rg"; no_aa_change "b2bcbbe3"
        [ "$aa_files" = "$(snapshot "$W/unit" | grep '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-')" ] && ok "AA untouched" || bad "AA changed"
        [ "$(h "$U/eso/hmi/lsd/jars/pmcp-guidance4.jar")" = "$(jsha rg)" ] && [ ! -e "$U/eso/hmi/lsd/jars/pmcp-guidance-aa.jar" ] && ok "pmcp-guidance-aa.jar -> pmcp-guidance4.jar" || bad "JARs after button 3"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    fi

    echo "[31] confirmed AA set of card 030b7df2 (same set id, feeder.conf 2 Mbit/s) -> AA 1: new settings get a trial"
    if card_ok "$EXP143" 84472aa9; then
        fresh_unit; factory=$(snapshot "$W/unit")
        runexp143 install map-square-fps40; rc_is 0; runexp143 aa-on; rc_is 0
        S=$(cat "$U/carplaymaps/aa/AA_BOOT"); P="$W/unit/mnt/persist/pmcp"; mkdir -p "$P"
        [ "$S" = gamma-bdd76a85-c5f8b0ef-716516eb ] && ok "030b7df2 set has this card's set id ($S)" || bad "set id $S"
        grep -q '^PMCP_AA_PACE_KBPS=2000$' "$U/carplaymaps/aa/feeder.conf" && ok "2 Mbit/s settings" || bad "setup feeder.conf"
        touch "$P/aa-trial.$S" "$P/aa-ok.$S"
        new_start; o=$(gal_start); case "$o" in "use=yes "*) ok "confirmed: hook on every start" ;; *) bad "before AA 1: $o" ;; esac
        run status; expect_out "Android Auto: old mode=gamma" "status: old (earlier card's set)"
        run aa-install; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "3 updates it in place, same set id"
        grep -q "removing them first" "$W/out" && bad "3 removed an earlier card's set instead of updating it" || ok "earlier card's set: updated in place, not removed"
        expect_out "That first Android Auto session in this start is a TRIAL" "AA 1 announces a trial"
        grep -q "confirmed before" "$W/out" && bad "AA 1 kept the old confirmation" || ok "no 'confirmed before'"
        [ ! -e "$P/aa-ok.$S" ] && [ ! -e "$P/aa-trial.$S" ] && ok "old confirmation and trial markers removed" || bad "markers left: $(ls "$P")"
        grep -q '^PMCP_AA_PACE_KBPS=6000$' "$U/carplaymaps/aa/feeder.conf" && ok "6 Mbit/s settings" || bad "feeder.conf not updated"
        run status; expect_out "Android Auto: on mode=gamma" "status: on"
        new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "next start: trial with the hook" || bad "trial start: $o"
        o=$(gal_start); case "$o" in "use=trial "*) ok "reconnection in the trial start: still the trial" ;; *) bad "reconnect: $o" ;; esac
        new_start; o=$(gal_start); case "$o" in "use=no real=gal.real preload= "*) ok "without AA 2 Confirm: factory gal, no hook" ;; *) bad "start after the trial: $o" ;; esac
        # an AA set this card does not know (here: feeder.conf changed): AA remove first, not restore
        echo "#" >> "$U/carplaymaps/aa/feeder.conf"
        run status; expect_out "Android Auto: unknown" "changed feeder.conf: unknown"
        expect_out "3. Install Android Auto replaces them" "PARTIAL reason points at main menu 3"
        before=$(snapshot "$W/unit")
        feat; expect_out "FEATURES_NEED_ANDROID_AUTO_REPLACED_FIRST_PRESS_3" "button 4 stops"
        [ "$before" = "$(snapshot "$W/unit")" ] && ok "button 4: nothing changed" || bad "button 4 changed the unit"
        expect_out "3. Install Android Auto" "button 4 says: 3. Install Android Auto first"
        run aa-remove; rc_is 0; run status; expect_out "Android Auto: off" "after AA remove: off"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    fi
    echo "[32] main menu 3: Install Android Auto (stable); an AA set this card does not support is removed first"
    fresh_unit; factory=$(snapshot "$W/unit")
    run aa-install; rc_is 1; expect_out "AA_INSTALL_NEEDS_CARPLAY_FIRST_PRESS_2" "3 on a factory unit: press 2 first"
    [ "$factory" = "$(snapshot "$W/unit")" ] && ok "3 without the map: unit unchanged" || bad "3 changed a factory unit"
    run map-install map-square-fps40; rc_is 0
    run aa-install; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "3 installs this card's Android Auto"
    expect_out "need rg: main menu, 4. Install additional features" "without rg: points at 4"
    expect_out "press 5. Confirm" "points at 5. Confirm"
    S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    before=$(snapshot "$W/unit")
    run aa-install; rc_is 0; expect_out "PMCP_AA_INSTALL_OK (already installed" "3 again: already installed, OK"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "3 again: nothing changed" || bad "3 again changed the unit"
    # another card's set (e.g. an experimental feeder): unknown, 3 replaces it, CarPlay stays
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-11111111-22222222-33333333" > "$U/carplaymaps/aa/AA_BOOT"
    mkdir -p "$W/unit/mnt/persist/pmcp"; touch "$W/unit/mnt/persist/pmcp/aa-ok.gamma-11111111-22222222-33333333"
    cpfiles=$(snapshot "$W/unit" | grep -v '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-\|/ramdisk/')
    run status; expect_out "Android Auto: unknown" "other set: unknown"; expect_out "3. Install Android Auto replaces them" "status points at 3"
    run aa-install; rc_is 0; expect_out "removing them first" "3 removes the unsupported set first"
    expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "then installs this card's set"
    [ "$(h "$U/carplaymaps/aa/aa-most-feeder")" = "$(sed -n 's/^AA_FEEDER \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")" ] && ok "this card's feeder" || bad "feeder after 3"
    [ ! -e "$W/unit/mnt/persist/pmcp/aa-ok.gamma-11111111-22222222-33333333" ] && ok "the old set's confirmation removed" || bad "old aa-ok left"
    expect_out "That first Android Auto session in this start is a TRIAL" "the stable set gets a trial"
    [ "$cpfiles" = "$(snapshot "$W/unit" | grep -v '/carplaymaps/aa/\|/apps/gal$\|/persist/pmcp/aa-\|/ramdisk/')" ] && ok "CarPlay files untouched" || bad "3 changed CarPlay files"
    run status; expect_out "Android Auto: on mode=gamma" "status: on"
    # fail-closed: unsupported set and no factory gal copy with the factory hash -> nothing written
    cp "$U/carplaymaps/aa/gal.real" "$W/galreal"
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; printf 'Y' >> "$U/carplaymaps/aa/gal.real"
    before=$(snapshot "$W/unit")
    run aa-install; rc_is 1; expect_out "AA_REMOVE_FACTORY_GAL_COPY_NOT_VERIFIED" "no verified factory gal copy: stops"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "fail-closed: nothing changed" || bad "3 changed the unit without a factory gal copy"
    cp "$W/galreal" "$U/carplaymaps/aa/gal.real"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[33] main menu 5 and 6: one Confirm and one Try again for the CarPlay features and Android Auto"
    fresh_unit; factory=$(snapshot "$W/unit")
    run confirm; rc_is 1; expect_out "CONFIRM_NOTHING_INSTALLED_THAT_HAS_A_TRIAL" "factory unit: nothing to confirm"
    run retry; rc_is 1; expect_out "RETRY_NOTHING_INSTALLED_THAT_HAS_A_TRIAL" "factory unit: nothing to try again"
    run map-install map-square-fps40; rc_is 0; feat; rc_is 0; run aa-install; rc_is 0; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    run confirm; rc_is 1; expect_out "CarPlay features: no trial start yet" "before the restart: no Java trial"
    expect_out "Android Auto: no trial yet" "no AA trial yet"; expect_out "CONFIRM_NOTHING_IN_ITS_TRIAL_NOW" "nothing confirmed"
    new_start; o=$(unit_boot); case "$o" in "boot=trial set=$ALL "*) ok "restart: the Java set's trial" ;; *) bad "boot: $o" ;; esac
    run confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK set=$ALL" "5 confirms the Java set"
    expect_out "Android Auto: no trial yet (connect the phone" "and says the phone comes first for AA"; expect_out "PMCP_CONFIRM_OK confirmed=1" "one confirmed"
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "phone connected: the AA trial" || bad "AA trial: $o"
    run confirm; rc_is 0; expect_out "CarPlay features (set $ALL): already confirmed" "Java: already confirmed"
    expect_out "PMCP_AA_CONFIRM_OK set=$S" "5 now confirms Android Auto"
    [ -e "$W/unit/mnt/persist/pmcp/aa-ok.$S" ] && [ -e "$W/unit/mnt/persist/pmcp/ok.$ALL" ] && ok "both confirmation markers" || bad "markers: $(ls "$W/unit/mnt/persist/pmcp")"
    run confirm; rc_is 1; expect_out "CONFIRM_NOTHING_IN_ITS_TRIAL_NOW" "third press: nothing left to confirm"
    run retry; rc_is 1; expect_out "RETRY_EVERYTHING_ALREADY_CONFIRMED" "6 with everything confirmed: nothing to do"
    new_start; o=$(unit_boot); case "$o" in "boot=yes set=$ALL "*) ok "next start: the confirmed set" ;; *) bad "boot: $o" ;; esac
    o=$(gal_start); case "$o" in "use=yes "*) ok "next AA connection: confirmed" ;; *) bad "AA: $o" ;; esac
    run restore; rc_is 0
    # both trials in the same start, confirmed with one press; a missed trial: 6, restart, 5
    fresh_unit; run map-install map-square-fps40; feat; run aa-install; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    new_start; unit_boot >/dev/null; gal_start >/dev/null
    run confirm; rc_is 0; expect_out "PMCP_CONFIRM_OK confirmed=2" "one press confirms both"
    run restore; rc_is 0
    fresh_unit; run map-install map-square-fps40; feat; run aa-install; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    new_start; unit_boot >/dev/null; gal_start >/dev/null
    new_start; o=$(unit_boot); case "$o" in "boot=no "*) ok "trial missed: factory start" ;; *) bad "boot: $o" ;; esac
    o=$(gal_start); case "$o" in "use=no "*) ok "trial missed: factory AA" ;; *) bad "AA: $o" ;; esac
    run confirm; rc_is 1; expect_out "this is not their trial start (6. Try again" "5 outside the trial: points at 6"
    run retry; rc_is 0; expect_out "PMCP_JAVA_RETRY_OK set=$ALL" "6: new Java trial"; expect_out "PMCP_AA_RETRY_OK set=$S" "6: new AA trial"
    new_start; o=$(unit_boot); case "$o" in "boot=trial "*) ok "after 6: Java trial again" ;; *) bad "boot: $o" ;; esac
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "after 6: AA trial again" || bad "AA: $o"
    run confirm; rc_is 0; expect_out "PMCP_CONFIRM_OK confirmed=2" "then 5 confirms both"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[34] main menu 4: Java or route guidance files this card does not support are replaced"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat; rc_is 0; confirm_now
    # a Java set this card does not know (as a card with a package unknown here leaves it, e.g. a newer card)
    echo X > "$U/eso/hmi/lsd/jars/pmcp-zz.jar"
    read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+zz-0479f0fa $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT"
    run status; expect_out "Unit state: PARTIAL" "unknown package: PARTIAL"; expect_out "4. Install additional features replaces them" "status points at 4"
    run java-on sl; rc_is 1; expect_out "JAVA_NEEDS_STAGE_A_STATE_PARTIAL" "single package refused while the set is unknown"
    feat; rc_is 0; expect_out "PMCP_FEATURES_RESET_OK" "4 resets the unknown Java set"; expect_out "PMCP_FEATURES_ON_OK" "4 installs this card's set"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-zz.jar" ] && ok "the unknown pmcp-zz.jar removed" || bad "pmcp-zz.jar left"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$ALL" ] && ok "this card's set" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
    run status; expect_out "Unit state: JAVA" "JAVA again"
    # a file listed by the unknown set outside the pmcp-*.jar names is never removed
    echo X > "$U/eso/hmi/lsd/jars/other.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+x-12345678 $jars other.jar ../lsd.sh" > "$U/carplaymaps/HMI_BOOT"
    feat; rc_is 0; expect_out "PMCP_FEATURES_RESET_OK" "4 resets it"
    [ -e "$U/eso/hmi/lsd/jars/other.jar" ] && [ -e "$U/eso/hmi/lsd/lsd.sh" ] && ok "only our JAR names removed (other.jar, ../lsd.sh stay)" || bad "a foreign file was removed"
    rm -f "$U/eso/hmi/lsd/jars/other.jar"
    # the rescue card's state, then 4
    rescue
    feat; rc_is 0; expect_out "PMCP_FEATURES_ON_OK" "4 after the rescue card"
    [ ! -e "$W/unit/mnt/persist/pmcp/DISABLED" ] && ok "DISABLED removed" || bad "DISABLED left"
    run status; expect_out "Unit state: JAVA" "after the rescue card + 4: JAVA"; expect_out "Route guidance system: on" "RG on"
    # an unknown reader: back to factory, then this card's
    printf 'Z' >> "$U/carplaymaps/rg/rgi-observer"
    run status; expect_out "Route guidance system: unknown" "changed reader: RG unknown"
    feat; rc_is 0; expect_out "PMCP_FEATURES_RESET_OK" "4 resets the route guidance system"; expect_out "PMCP_RG_SYSTEM_ON_OK" "and installs it again"
    [ "$(h "$U/carplaymaps/rg/rgi-observer")" = "$(sed -n 's/^RG_READER \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")" ] && ok "this card's reader" || bad "reader"
    # fail-closed: unknown driver without a factory copy -> nothing changed
    printf 'Z' >> "$U/armle/lib/dll/ipod-drvr-iap2.so"; mv "$U/carplaymaps/rollback/ipod-drvr-iap2.so" "$W/drv"
    before=$(snapshot "$W/unit")
    feat; expect_out "FEATURES_RESET_FACTORY_IAP2_DRIVER_COPY_NOT_VERIFIED_NOTHING_CHANGED" "no factory driver copy: stops"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "fail-closed: nothing changed" || bad "4 changed the unit without a factory driver copy"
    mv "$W/drv" "$U/carplaymaps/rollback/ipod-drvr-iap2.so"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[35] main menu 2: the main layout, and mixed map files replaced (everything removed first)"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; run switch map-clean; rc_is 0
    run map-install map-square-fps40; rc_is 0; expect_out "PMCP_SWITCH_OK variant=map-square-fps40" "2 brings the main layout back"
    feat; run aa-install; rc_is 0
    echo junk > "$U/eso/bin/apps/dio_manager"
    run status; expect_out "Unit state: PARTIAL" "changed dio_manager: PARTIAL"; expect_out "2. Install CarPlay repairs it" "status points at 2"
    feat; expect_out "PMCP_FAIL=FEATURES_STOPPED_AT_features-reset_" "4 stops"; expect_out "2. Install CarPlay first" "4 says press 2"
    run aa-install; rc_is 0; expect_out "PMCP_AA_INSTALL_OK (already installed" "3: Android Auto itself is fine (already installed)"
    run map-install map-square-fps40; rc_is 0; expect_out "removing everything first" "2 removes everything first"
    expect_out "PMCP_RESTORE_OK" "restore"; expect_out "PMCP_INSTALL_OK stage=A variant=map-square-fps40" "then the map"
    expect_out "press 3 and/or 4 now" "says 3 and 4 again"
    run status; expect_out "Unit state: VIDEO" "VIDEO"; expect_out "Android Auto: off" "AA off"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    # another mod's carplaymaps (no pmcp version file): nothing written
    mkdir -p "$U/carplaymaps"; echo x > "$U/carplaymaps/other"; before=$(snapshot "$W/unit")
    run map-install map-square-fps40; rc_is 1; expect_out "MAP_INSTALL_NOT_A_PMCP_INSTALL_NOTHING_CHANGED" "another mod: stops"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "another mod: nothing changed" || bad "2 changed another mod's files"
    rm -rf "$U/carplaymaps"

    echo "[36] CarPlay log (features_advanced): saved for the log card, deleted with the AA logs"
    fresh_unit; factory=$(snapshot "$W/unit")
    run cp-log-save; rc_is 1; expect_out "CP_LOG_NEEDS_PMCP_STATE_STOCK" "factory unit: no log"
    run map-install map-square-fps40; new_start
    before=$(snapshot "$W/unit" | grep -v /logs/)
    run cp-log-save; rc_is 0; expect_out "PMCP_CP_LOG_SAVED file=logs/cp-log-1.txt" "log saved"; expect_out "supervisor_log=no" "no supervisor log yet"
    echo "supervisor line 1" > "$W/unit/ramdisk/carplay-cluster-supervisor.log"
    run cp-log-save; rc_is 0; expect_out "cp-log-2.txt" "second log"; expect_out "supervisor_log=yes" "with the supervisor log"
    L2="$U/carplaymaps/logs/cp-log-2.txt"
    grep -q "^supervisor line 1$" "$L2" && grep -q "^--- state: VIDEO" "$L2" && [ "$(tail -1 "$L2")" = "--- end" ] && ok "log content: state, supervisor log, complete" || bad "cp log content"
    [ "$before" = "$(snapshot "$W/unit" | grep -v /logs/ | grep -v /ramdisk/)" ] && ok "log save wrote only carplaymaps/logs" || bad "cp log save changed other files"
    for n in 3 4 5; do run cp-log-save; done; run cp-log-save; rc_is 1; expect_out "CP_LOGS_FULL_5" "sixth refused"
    rm -rf "$W/med3"; logcard
    [ "$(ls "$W/med3/PMCP_LOGS" | grep -c '^cp-log-[1-5].txt$')" = 5 ] && cmp -s "$L2" "$W/med3/PMCP_LOGS/cp-log-2.txt" && ok "log card: CarPlay logs copied" || bad "log card: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    grep -q "^RESULT=OK copied=5 aa_logs=0 cp_logs=5$" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card: RESULT=OK with cp_logs=5" || bad "log card result"
    run aa-log-clear; rc_is 0; [ ! -e "$U/carplaymaps/logs" ] && ok "Delete saved logs removes the CarPlay logs" || bad "cp logs left"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    echo "[37] main menu 3 and 4 with unsupported Android Auto AND unsupported Java files at once (no dead end)"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat; run aa-install; confirm_now; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-11111111-22222222-33333333" > "$U/carplaymaps/aa/AA_BOOT"
    # AA 1.0: a set naming a JAR that is not there is not "plainly ours" (java_part_tolerable), so 3 still says 4 first
    read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+zz-0479f0fa $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT"
    run status; expect_out "4. Install additional features replaces them; Android Auto files too: then 3" "status: 4, then 3"
    before=$(snapshot "$W/unit")
    run aa-install; rc_is 1; expect_out "AA_INSTALL_NEEDS_THE_FEATURES_REPAIRED_FIRST_PRESS_4_THEN_3" "3 first: says 4, then 3"
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "3: nothing changed" || bad "3 changed the unit"
    feat; expect_out "PMCP_FEATURES_RESET_OK" "4 resets the Java set although AA is unsupported"
    expect_out "PMCP_FAIL=FEATURES_STOPPED_AT_java-update_" "then stops before installing"; expect_out "3. Install Android Auto" "and says 3"
    [ ! -e "$U/carplaymaps/HMI_BOOT" ] && ok "unknown set removed" || bad "HMI_BOOT left"
    run aa-install; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "3 now replaces Android Auto"
    feat; expect_out "PMCP_FEATURES_ON_OK" "4 again: this card's features"; run status; expect_out "Unit state: JAVA" "JAVA"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    # AA 1.0: the same with a plainly ours unknown package (its JAR there): 3 first works and leaves Java as it is
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat; run aa-install; confirm_now
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-11111111-22222222-33333333" > "$U/carplaymaps/aa/AA_BOOT"
    echo X > "$U/eso/hmi/lsd/jars/pmcp-zz.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+zz-0479f0fa $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT"
    j0=$(snapshot "$W/unit" | grep '/eso/hmi/lsd/\|/carplaymaps/HMI_BOOT')
    run aa-install; rc_is 0; expect_out "left as it is" "3 first: Java left"; expect_out "removing them first" "unknown AA removed"
    expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "then this card's AA"
    [ "$j0" = "$(snapshot "$W/unit" | grep '/eso/hmi/lsd/\|/carplaymaps/HMI_BOOT')" ] && ok "Java part untouched by 3" || bad "3 changed Java"
    feat; expect_out "PMCP_FEATURES_ON_OK" "then 4: this card's features"; run status; expect_out "Unit state: JAVA" "JAVA"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[38] after the rescue card: 5 refuses, 6 gives both a new trial (also confirmed sets)"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat; run aa-install; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    new_start; unit_boot >/dev/null; gal_start >/dev/null; run confirm; expect_out "PMCP_CONFIRM_OK confirmed=2" "both confirmed"
    touch "$W/unit/mnt/persist/pmcp/DISABLED"
    run confirm; rc_is 1; expect_out "switched off by the rescue card (6. Try again" "5: switched off by the rescue card"
    run retry; rc_is 0; expect_out "PMCP_JAVA_RETRY_OK" "6: Java"; expect_out "PMCP_AA_RETRY_OK" "6: AA"; expect_out "rescue card switch-off removed" "DISABLED removed"
    [ ! -e "$W/unit/mnt/persist/pmcp/DISABLED" ] && [ ! -e "$W/unit/mnt/persist/pmcp/ok.$ALL" ] && [ ! -e "$W/unit/mnt/persist/pmcp/aa-ok.$S" ] \
        && ok "no confirmation left: both start with a trial" || bad "markers: $(ls "$W/unit/mnt/persist/pmcp")"
    new_start; o=$(unit_boot); case "$o" in "boot=trial "*) ok "next start: Java trial" ;; *) bad "boot: $o" ;; esac
    o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "next AA connection: trial" || bad "AA: $o"
    # outside the AA trial start only: the AA-side message
    run confirm; expect_out "PMCP_CONFIRM_OK confirmed=2" "confirmed again"
    rm -f "$W/unit/mnt/persist/pmcp/aa-ok.$S"; new_start
    run confirm; rc_is 1; expect_out "Android Auto: this is not its trial start (6. Try again" "AA outside its trial start"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[39] PARTIAL with intact map files: layout switch allowed; CarPlay log in PARTIAL; log card with both kinds"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat
    echo X > "$U/eso/hmi/lsd/jars/pmcp-zz.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+zz-0479f0fa $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT"
    run switch map-clean; rc_is 0; expect_out "PMCP_SWITCH_OK variant=map-clean" "switch in PARTIAL (map files intact)"
    new_start; run cp-log-save; rc_is 0; grep -q "^--- state: PARTIAL" "$U/carplaymaps/logs/cp-log-1.txt" && ok "CarPlay log in PARTIAL: state recorded" || bad "cp log in PARTIAL"
    echo "x event=aap.nav_msg msg_id=0x8006 bytes=1" > "$W/unit/ramdisk/pmcp-gal-hook.log"
    run aa-log-save; rc_is 0
    rm -rf "$W/med3"; logcard
    grep -q "^RESULT=OK copied=2 aa_logs=1 cp_logs=1$" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card: one AA and one CarPlay log" || bad "log card: $(tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt")"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[40] package ui (AID navigation configuration page, Save of trial starts): own JAR, in main 4, java-off and restore exact, shares the mode file"
    UI=$(jid ui)
    grep -q "java-on_ui" "$SDB/pmcp/menu/features-on.sh" && ok "main 4 installs ui (Save on the page)" || bad "main 4 leaves ui out"
    tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen features_advanced/,/^screen carplay_advanced/p' > "$W/feat.esd"
    grep -q '"On ui: AID navigation configuration in App-Connect settings, saves trial starts without the card"' "$W/feat.esd" \
        && grep -q '"Off ui: AID navigation configuration in App-Connect settings, saves trial starts without the card"' "$W/feat.esd" \
        && ok "features_advanced: On ui / Off ui" || bad "GEM ui buttons missing in features_advanced"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-square-fps40; rc_is 0; run java-on nai; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    jars_before=$(cd "$U/eso/hmi/lsd/jars" && ls); boot_before=$(cat "$U/carplaymaps/HMI_BOOT")
    run java-on ui; rc_is 0; expect_out "PMCP_JAVA_ON_OK package=ui set=$NAI+$UI" "ui on, set nai+ui"
    [ "$(h "$U/eso/hmi/lsd/jars/pmcp-ui.jar")" = "$(jsha ui)" ] && ok "pmcp-ui.jar in place" || bad "pmcp-ui.jar"
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI+$UI jars=/X/lsd/jars/NavActiveIgnore.jar:/X/lsd/jars/pmcp-ui.jar" ] \
        && ok "next start: one trial loading pmcp-ui.jar" || bad "boot: $o"
    o=$(unit_boot); [ "$o" = "boot=no set=$NAI+$UI jars=" ] && ok "without Confirm: the next start is factory" || bad "boot: $o"
    run java-retry; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    run java-off ui; rc_is 0; expect_out "PMCP_JAVA_OFF_OK package=ui" "ui off"
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$boot_before" ] && [ "$(cd "$U/eso/hmi/lsd/jars" && ls)" = "$jars_before" ] \
        && ok "ui off: the set and the jars folder as before" || bad "after ui off: $(cat "$U/carplaymaps/HMI_BOOT")"
    o=$(unit_boot); [ "$o" = "boot=yes set=${boot_before%% *} jars=/X/lsd/jars/NavActiveIgnore.jar" ] \
        && ok "ui off: the confirmed earlier set loads" || bad "boot: $o"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore after ui: exact factory tree" || bad "restore after ui left changes"
    # main 4 on a set with ui: this card knows ui, so features-reset keeps it and the set grows by the features
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; rc_is 0; run java-on ui; rc_is 0
    feat; rc_is 0; expect_out "PMCP_FEATURES_ON_OK" "main 4 with ui on"
    [ "$(h "$U/eso/hmi/lsd/jars/pmcp-ui.jar")" = "$(jsha ui)" ] && case "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" in *"+$UI"|*"+$UI+"*) true ;; *) false ;; esac \
        && ok "main 4 keeps ui in the set" || bad "after main 4: $(cat "$U/carplaymaps/HMI_BOOT")"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    # a card from before the gem menu (v1.4.2 release; likewise v1.5.0) does not know ui and cannot reset an unknown set:
    # it sees PARTIAL and changes nothing; "Off ui" on this card first, then that card sees a normal Java set
    if card_ok "$V142" v1.4.2; then
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-square-fps40; rc_is 0; run java-on nai; rc_is 0; run java-on ui; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    run142 status; expect_out "Unit state: PARTIAL" "v1.4.2 card: a set with ui is PARTIAL"
    before=$(snapshot "$W/unit")
    run142 java-update; rc_is 1
    [ "$before" = "$(snapshot "$W/unit")" ] && ok "v1.4.2 card changes nothing on a set with ui" || bad "v1.4.2 card changed files"
    run java-off ui; rc_is 0
    run142 status; expect_out "Unit state: JAVA" "after Off ui on this card: v1.4.2 card sees a normal Java set"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    fi
    # ui as the only package: java-off ui gives the factory lsd.sh
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-square-fps40; rc_is 0; run java-on ui; rc_is 0
    run java-off ui; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=VIDEO" "ui as the only package: off gives stage A"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = "$STOCK_LSD" ] && ok "factory lsd.sh back" || bad "lsd.sh after ui off"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    # with rg and sl: the page writes the mode sl owns; ui off keeps it, sl off clears it
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-square-fps40; rc_is 0; run rg-system-on; rc_is 0; run java-on rg; rc_is 0; run java-on sl; rc_is 0
    run java-on ui; rc_is 0
    o=$(unit_boot); case "$o" in "boot=trial "*pmcp-guidance4.jar:/X/lsd/jars/pmcp-sl2.jar:/X/lsd/jars/pmcp-ui.jar) ok "rg, sl and ui load together" ;; *) bad "boot: $o" ;; esac
    run java-confirm; rc_is 0
    run speedlimit-mode turnto; rc_is 0
    run java-off ui; rc_is 0
    [ "$(cat "$SLM" 2>/dev/null)" = turnto ] && ok "ui off keeps the mode (it belongs to sl)" || bad "ui off changed the mode"
    run java-on ui; rc_is 0; mkdir "$SLL"
    run java-off ui; rc_is 1; expect_out "SPEEDLIMIT_LOCK_BUSY" "ui on/off shares the mode lock (like every package change)"
    rm -rf "$SLL"
    run java-off sl; rc_is 0
    [ ! -e "$SLM" ] && ok "sl off clears the mode, ui stays" || bad "mode left after sl off"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore after rg+sl+ui: exact factory tree" || bad "tree after restore"
    P="$W/unit/mnt/persist/pmcp"; RDK="$W/unit/ramdisk"; SF=$(sed -n 's/^AA_FEEDER \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")
    case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) EXPCARD=yes ;; *) EXPCARD=no ;; esac
    HOOKEDY=$(echo "$HOOKED" | sed 's/^use=trial/use=yes/')
    # set files, AA_BOOT and the AA markers (what a trial protects): the output switch must not change any of them
    aaf() { (cd "$U/carplaymaps/aa" && for f in *; do echo "$f $(h "$f")"; done); ls "$P" 2>/dev/null | grep '^aa-ok\.\|^aa-trial\.'; ls "$RDK" 2>/dev/null | grep '^pmcp-aa-trial\.'; }
    echo "[45] AA 1.0: main menu 3 installs the direct set; the output switch changes no set file, no AA_BOOT, no marker (no trial)"
    fresh_unit; factory=$(snapshot "$W/unit")
    ! grep -q '^AAX_' <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") && ok "no experimental AA set: AA 1.0 is the stable one" || bad "AAX_ key on the card"
    run aa-output direct; rc_is 1; expect_out "AA_SWITCH_NEEDS_THIS_CARDS_AA_SET_ON_off" "output switch without AA refused"
    run map-install map-square-fps40; feat; run aa-install; rc_is 0; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    case "$S" in gamma-*-"$(echo "$SF" | cut -c1-8)"-*) ok "3: the set id carries the AA 1.0 feeder: $S" ;; *) bad "set $S" ;; esac
    [ "$(h "$U/carplaymaps/aa/aa-most-feeder")" = "$SF" ] && grep -qx 'PMCP_AA_OUTPUT=direct' "$U/carplaymaps/aa/feeder.conf" \
        && ok "3: AA 1.0 feeder, its feeder.conf says direct" || bad "3: feeder or feeder.conf"
    new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "first connection: trial" || bad "AA: $o"
    run confirm; rc_is 0; expect_out "PMCP_AA_CONFIRM_OK set=$S" "5 confirms"
    before=$(aaf); tree0=$(snapshot "$W/unit" | grep -v '/ramdisk/\|/mnt/persist/pmcp/aa-extra.conf\|/mnt/persist/pmcp/gem.log')
    run aa-output ring; rc_is 0; expect_out "PMCP_AA_OUTPUT_OK output=ring" "aa-output ring"
    ! grep -q 'TRIAL' "$W/out" && ok "no trial for an output change (A153)" || bad "trial message: $(cat "$W/out")"
    grep -qx 'PMCP_AA_OUTPUT=ring' "$P/aa-extra.conf" && ok "aa-extra.conf: PMCP_AA_OUTPUT=ring" || bad "aa-extra.conf: $(cat "$P/aa-extra.conf" 2>&1)"
    [ "$before" = "$(aaf)" ] && [ "$tree0" = "$(snapshot "$W/unit" | grep -v '/ramdisk/\|/mnt/persist/pmcp/aa-extra.conf\|/mnt/persist/pmcp/gem.log')" ] \
        && ok "(a) ring: only aa-extra.conf changed (set files, AA_BOOT, markers, everything else as before)" || bad "(a) the switch changed: $(aaf)"
    new_start; o=$(gal_start); [ "$o" = "$HOOKEDY" ] && ok "after the switch: still confirmed, hooked without a trial" || bad "AA: $o"
    run aa-output direct; rc_is 0; [ "$before" = "$(aaf)" ] && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" \
        && ok "(a) direct again: only aa-extra.conf" || bad "(a) direct: $(aaf)"
    run aa-output bogus; rc_is 1; expect_out "AA_OUTPUT_MUST_BE_direct_OR_ring" "aa-output: unknown value refused"
    grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" && ok "refused value: file unchanged" || bad "aa-extra.conf changed"
    run aa-status; expect_out "AA switches: PMCP_AA_OUTPUT=direct" "aa-status shows the switch"
    if [ $EXPCARD = yes ]; then
        run aa-capture 60; rc_is 0; grep -qx 'PMCP_AA_CAPTURE_S=60' "$P/aa-extra.conf" && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" \
            && ok "experimental card: recording on, output kept" || bad "aa-extra.conf: $(cat "$P/aa-extra.conf")"
        [ "$before" = "$(aaf)" ] && ok "recording: no marker or set file changed" || bad "recording changed: $(aaf)"
        run aa-capture 5; rc_is 1; expect_out "AA_CAPTURE_MUST_BE_60_OR_off" "aa-capture: unknown value refused"
        run aa-capture off; rc_is 0; grep -qx 'PMCP_AA_CAPTURE_S=0' "$P/aa-extra.conf" && ok "recording off" || bad "capture off"
    else
        run aa-capture 60; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "release card: no recording button action"
    fi
    run aa-on-exp; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "aa-on-exp: no experimental set since AA 1.0"
    run aa-install; rc_is 0; expect_out "PMCP_AA_INSTALL_OK (already installed" "3 again: nothing to do"
    grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" && ok "3 with this card's set: switch kept" || bad "3 dropped the switch"
    run aa-remove; rc_is 0; run aa-install; rc_is 0; [ ! -e "$P/aa-extra.conf" ] && ok "3 after AA remove: no switch file, the set's default" || bad "aa-extra.conf left"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[46] AA 1.0: main menu 3 brings every earlier AA set (v10 of v1.5.1, v11, v12, v13) to this card's set in place"
    V151SD="${PMCP_V151_SD:-$SDB/../sd-754c9d82}"; OLD11SD="${PMCP_AA_OLD11:-$SDB/../sd-a55867ab}"
    NEW12SD="${PMCP_AA_V12:-$SDB/../sd-15d19b43}"; V13SD="${PMCP_AA_V13:-$SDB/../sd-d82f8c73}"
    runc() { _c=$1; shift; PMCP_TEST_ROOT="$W/unit" $SH "$_c/pmcp/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
    for oc in "$V151SD:754c9d82:aa-install" "$OLD11SD:a55867ab:aa-on" "$NEW12SD:15d19b43:aa-on direct" "$V13SD:d82f8c73:aa-on-exp ring"; do
        od=${oc%%:*}; rest=${oc#*:}; oid=${rest%%:*}; how=${rest#*:}
        card_ok "$od/pmcp/pmcp.sh" "$oid" || continue
        fresh_unit; factory=$(snapshot "$W/unit")
        runc "$od" install map-square-fps40; rc_is 0
        case "$how" in
            aa-install) runc "$od" aa-install; rc_is 0 ;;
            aa-on) runc "$od" aa-on; rc_is 0 ;;
            "aa-on direct") runc "$od" aa-on; rc_is 0; runc "$od" aa-output direct; rc_is 0 ;;
            "aa-on-exp ring") runc "$od" aa-install; rc_is 0; runc "$od" aa-on-exp; rc_is 0; runc "$od" aa-output ring; rc_is 0
                              runc "$od" aa-capture 60; rc_is 0; echo x > "$P/aa-stream.h264" ;;
        esac
        O=$(cat "$U/carplaymaps/aa/AA_BOOT"); new_start; o=$(gal_start); runc "$od" confirm; rc_is 0
        [ -e "$P/aa-ok.$O" ] && ok "$oid: its set $O confirmed" || bad "$oid: confirm $(cat "$W/out" | tail -3)"
        run status; expect_out "Android Auto: old mode=gamma" "$oid: its set is old on this card"
        galw=$(h "$U/eso/bin/apps/gal"); real=$(h "$U/carplaymaps/aa/gal.real")
        run aa-install; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "$oid: 3 brings this card's set"
        [ "$(h "$U/carplaymaps/aa/aa-most-feeder")" = "$SF" ] && [ "$(h "$U/eso/bin/apps/gal")" = "$galw" ] && [ "$(h "$U/carplaymaps/aa/gal.real")" = "$real" ] \
            && ok "$oid: in place (AA 1.0 feeder, wrapper and factory gal copy untouched)" || bad "$oid: files after 3"
        case "$how" in *direct) want=direct ;; *ring) want=ring ;; *) want= ;; esac
        if [ -n "$want" ]; then
            expect_out "AA output kept: $want" "$oid: 3 says the output is kept"
            [ "$(grep '^PMCP_AA_' "$P/aa-extra.conf")" = "PMCP_AA_OUTPUT=$want" ] \
                && ok "$oid: the chosen output ($want) kept, recording switch gone" || bad "$oid: aa-extra.conf $(cat "$P/aa-extra.conf" 2>&1)"
        else
            [ ! -e "$P/aa-extra.conf" ] && ok "$oid: no switch file" || bad "$oid: aa-extra.conf $(cat "$P/aa-extra.conf")"
        fi
        [ ! -e "$P/aa-ok.$O" ] && [ ! -e "$P/aa-stream.h264" ] && ok "$oid: old confirmation and recording gone" || bad "$oid: left $(ls "$P")"
        new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "$oid: first connection with AA 1.0 is a trial" || bad "$oid: AA $o"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "$oid: restore exact" || bad "$oid: tree after restore"
    done

    echo "[47] AA 1.0: main menu 3 leaves a Java part this card does not support when it is plainly ours; otherwise it refuses"
    jbase() { fresh_unit; run map-install map-square-fps40; run java-on nai; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
              echo X > "$U/eso/hmi/lsd/jars/pmcp-zz.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"
              echo "$s+zz-0479f0fa $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT"; }
    jtree() { snapshot "$W/unit" | grep '/eso/hmi/lsd/\|/carplaymaps/HMI_BOOT'; }
    jbase; run status; expect_out "Unit state: PARTIAL" "unknown package zz: Java part PARTIAL"; j0=$(jtree)
    run aa-install; rc_is 0; expect_out "Java part of a version this card does not support: left as it is" "3 says the Java part stays"
    expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "3 installs AA over it"; [ "$j0" = "$(jtree)" ] && ok "Java part untouched (lsd.sh, JARs, HMI_BOOT)" || bad "3 changed the Java part"
    new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "AA trial as usual" || bad "AA: $o"
    feat; expect_out "PMCP_FEATURES_RESET_OK" "4 then replaces the Java part"; run status; expect_out "Android Auto: on" "AA stays on"
    for bad_case in foreign-lsd missing-jar odd-name count other-jar; do
        jbase
        case $bad_case in
            foreign-lsd) echo "# another mod" >> "$U/eso/hmi/lsd/lsd.sh" ;;
            missing-jar) rm -f "$U/eso/hmi/lsd/jars/pmcp-zz.jar" ;;
            odd-name) read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s ${jars% *} ../pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT" ;;
            count) read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+yy-11111111 $jars" > "$U/carplaymaps/HMI_BOOT" ;;
            other-jar) echo X > "$U/eso/hmi/lsd/jars/Other.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s ${jars% *} Other.jar" > "$U/carplaymaps/HMI_BOOT" ;;
        esac
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/')
        run aa-install; rc_is 1; expect_out "AA_INSTALL_NEEDS" "$bad_case: 3 refuses"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "$bad_case: nothing changed" || bad "$bad_case: 3 changed the unit"
    done

done

rm -rf "$W"
[ "$SKIPS" = 0 ] || echo "SKIPPED (earlier cards not present, update tests only): $SKIPS"
echo "FAILED CHECKS: $FAILS"
exit $FAILS
