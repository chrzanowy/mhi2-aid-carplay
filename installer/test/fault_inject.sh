#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Power-loss test for pmcp.sh (from review 1's harness). For every action of a full chain
# (install ... restore), kill pmcp.sh right before its 1st, 2nd, 3rd ... mutating command on the unit (mv/rm/touch,
# fault_inject.inc), then check what the NEXT BOOT would do and that the tool can still recover:
#   - boot: the lsd.sh block of the killed tree is executed; if it loads JARs without a trial (use=yes), HMI_BOOT must
#     be the one from before the action or a set the user confirmed earlier (nothing untested may load permanently);
#   - state is STOCK/VIDEO/JAVA/PARTIAL (never UNKNOWN), and restore (or nothing, for STOCK) gives the factory tree.
#   fault_inject.sh SD_BUILD_DIR SHELL
#   PMCP_FAULT_SCOPE=speedlimit runs native-limit actions with one retained companion package.
#   PMCP_PROFILE=MU1161 (default): firmware profile (profiles/<ID>/) whose backup folder and lsd.jxe size the unit copy uses.
#   PMCP_FAULT_QUICK=1: own chain only, no replay cross-check (daily); PMCP_FAULT_JOBS=N parallel workers (default 6).
set -u
SDB=$(cd "${1:?sd build dir}" && pwd); SH=${2:?shell}
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
H=$(cd "$(dirname "$0")" && pwd)
PROJ=$(cd "$H/../.." && pwd)       # this project (any folder name)
export PMCP_PROFILE="${PMCP_PROFILE:-MU1161}"
pf() { python3 -I "$PROJ/scripts/profile.py" get "$PMCP_PROFILE" "$1" || exit 99; }   # a profile value
BKROOT="${PMCP_BACKUP:-$REPO/backup/$(pf backup_dir)}"
BK="$BKROOT/$(pf appimg)"
BKSYS="$BKROOT/$(pf system)"
JXE_SIZE=$(pf lsd_jxe.size)
[ -n "$JXE_SIZE" ] && [ -d "$BK" ] || { echo "profile $PMCP_PROFILE: no lsd.jxe size or no backup at $BK"; exit 99; }
export PMCP_TEST_GAWK="${PMCP_TEST_GAWK:-$REPO/upstream/tools/gawk-3.1.5/gawk}"
W=$(mktemp -d /tmp/pmcp-fi.XXXX)
export PMCP_TEST_GEMLOG="$W/gem.log"   # the GEM button log outside the unit tree (the tree checks stay exact)
U="$W/unit/mnt/app"
FAILS=0; CASES=0
bad() { echo "  FAIL $*"; FAILS=$((FAILS+1)); }

fresh_unit() {
    rm -rf "$W/unit" "$W/sd"
    mkdir -p "$W/unit/ifs" "$W/unit/ramdisk" "$U/eso/bin/apps" "$U/eso/hmi/lsd/jars" "$U/armle/usr/bin" "$W/unit/mnt/persist/etc" \
        "$U/armle/lib/dll" "$W/unit/mnt/system/etc/mm"
    cp "$BK/armle/lib/dll/ipod-drvr-iap2.so" "$U/armle/lib/dll/"
    cp "$BKSYS/mm/iap2.cfg" "$W/unit/mnt/system/etc/mm/"
    mkfile -n $JXE_SIZE "$W/unit/ifs/lsd.jxe" 2>/dev/null || truncate -s $JXE_SIZE "$W/unit/ifs/lsd.jxe"
    cp "$BK/eso/bin/apps/dio_manager" "$U/eso/bin/apps/dio_manager"
    cp "$BK/eso/bin/apps/gal" "$U/eso/bin/apps/gal"
    cp "$BK/eso/hmi/lsd/lsd.sh" "$U/eso/hmi/lsd/lsd.sh"
    cp "$BK/eso/hmi/lsd/jars/"* "$U/eso/hmi/lsd/jars/"
    echo "factory persist content" > "$W/unit/mnt/persist/etc/ffs3.2ver"
    cp -R "$SDB/pmcp" "$W/sd"
    awk -v inc="$H/no_printf.inc" '{print} /^unset LD_PRELOAD$/ && !done {while ((getline l < inc) > 0) print l; done=1}' \
        "$W/sd/pmcp.sh" > "$W/sd/pmcp.sh.t" && mv "$W/sd/pmcp.sh.t" "$W/sd/pmcp.sh"
    grep -q '^printf() {' "$W/sd/pmcp.sh" || { echo "no_printf.inc not applied"; exit 99; }
    awk -v inc="$H/fault_inject.inc" '{print} /^unset LD_PRELOAD$/ && !done {while ((getline l < inc) > 0) print l; done=1}' \
        "$W/sd/pmcp.sh" > "$W/sd/pmcp-fi.sh"
}
# one shasum process for the whole tree (same lines as one per file); default: the unit
snapshot() { (cd "${1:-$W/unit}" && find . -type f ! -path './sdlog/*' -exec shasum -a 256 {} + | sort -k2); }
mode_digest() {
    _mode_file="$W/unit/mnt/persist/pmcp/native-speedlimit-mode"
    if [ -e "$_mode_file" ]; then shasum -a 256 < "$_mode_file" | cut -d' ' -f1; else echo absent; fi
}
# "v13:ACTION": the v1.3.0 release card (an earlier install that rg-update / java-update bring to this card); not a target
V13="${PMCP_V13_SD:-$SDB/../sd-v1.3.0}/pmcp/pmcp.sh"
# "exp:ACTION": an earlier experimental card (ab9fb348, Android Auto AA 3 / gamma), likewise only to prepare a unit
EXP="${PMCP_EXP_SD:-$SDB/../sd-ab9fb348}/pmcp/pmcp.sh"
# "x143:ACTION": the experimental card 84472aa9 (v1.4.3 + Android Auto, rg-aa in pmcp-guidance-aa2.jar), likewise
EXP143="${PMCP_EXP143_SD:-$SDB/../sd-84472aa9}/pmcp/pmcp.sh"
# "v151:ACTION": the v1.5.1 release card (ui e11bd8d3 in pmcp-ui.jar, which this card replaces with pmcp-ui2.jar)
V151="${PMCP_V151_SD:-$SDB/../sd-754c9d82}/pmcp/pmcp.sh"
# Earlier cards only prepare units for the update chains. Missing (a build from install.sh): those chains are skipped
# and named; PMCP_REQUIRE_OLD_CARDS=1 (release runs) makes a missing earlier card an error.
OLDCARDS=yes
for c in "$V13" "$EXP" "$EXP143" "$V151"; do
    [ -f "$c" ] && continue
    [ "${PMCP_REQUIRE_OLD_CARDS:-0}" = 1 ] && { echo "earlier card missing: $c"; exit 99; }
    echo "skip: earlier card not present ($c): the update chains with earlier cards are skipped"; OLDCARDS=no
done
run() { case "$1" in v13:*) _a=${1#v13:}; shift; PMCP_TEST_ROOT="$W/unit" $SH "$V13" $_a "$@" > "$W/out" 2>&1 ;;
                     exp:*) _a=${1#exp:}; shift; PMCP_TEST_ROOT="$W/unit" $SH "$EXP" $_a "$@" > "$W/out" 2>&1 ;;
                     x143:*) _a=${1#x143:}; shift; PMCP_TEST_ROOT="$W/unit" $SH "$EXP143" $_a "$@" > "$W/out" 2>&1 ;;
                     v151:*) _a=${1#v151:}; shift; PMCP_TEST_ROOT="$W/unit" $SH "$V151" $_a "$@" > "$W/out" 2>&1 ;;
                     fx:*) fx "${1#fx:}" > "$W/out" 2>&1 ;;
                     *) PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" "$@" > "$W/out" 2>&1 ;; esac; }
runfi() { rm -f "$W/cnt"; PMCP_KILL_AT=$1 PMCP_FI_CNT=$W/cnt PMCP_FI_LOG=$W/filog PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp-fi.sh" "${@:2}" > "$W/outfi" 2>&1; }
# states the main menu's 2, 3 and 4 replace: files of a version this card does not support (another card's set)
fx() {
    case "$1" in
        aa-unknown) printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-11111111-22222222-33333333" > "$U/carplaymaps/aa/AA_BOOT" ;;
        java-unknown) echo X > "$U/eso/hmi/lsd/jars/pmcp-zz.jar"; read _s _j < "$U/carplaymaps/HMI_BOOT"
                      echo "$_s+zz-0479f0fa $_j pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT" ;;
        rg-unknown) printf 'Z' >> "$U/carplaymaps/rg/rgi-observer" ;;
        dio-mixed) echo junk > "$U/eso/bin/apps/dio_manager" ;;
        *) echo "PMCP_FAIL=FX_$1"; return 1 ;;
    esac
    echo "PMCP_FX_OK $1"
}
# the user confirmed the set during its trial boot
confirm_set() {
    if [ -s "$U/carplaymaps/aa/AA_BOOT" ]; then   # likewise for the AA set
        mkdir -p "$W/unit/mnt/persist/pmcp"; read s < "$U/carplaymaps/aa/AA_BOOT"
        rm -f "$W/unit/mnt/persist/pmcp"/aa-ok.*   # like pmcp.sh aa-confirm: one confirmed AA set
        touch "$W/unit/mnt/persist/pmcp/aa-trial.$s" "$W/unit/mnt/persist/pmcp/aa-ok.$s"
    fi
    [ -s "$U/carplaymaps/HMI_BOOT" ] || return 0
    mkdir -p "$W/unit/mnt/persist/pmcp"; read s rest < "$U/carplaymaps/HMI_BOOT"
    touch "$W/unit/mnt/persist/pmcp/trial.$s" "$W/unit/mnt/persist/pmcp/ok.$s"
    echo "set=$s use=yes" > "$W/unit/mnt/persist/pmcp/last-boot"
}
bootsim() {
    # A physical power loss clears MMX RAM, including a lock left by kill -9 in this harness.
    rm -rf "$W/unit/ramdisk"; mkdir -p "$W/unit/ramdisk"
    rm -rf "$W/bs"; cp -Rp "$W/unit" "$W/bs"; L="$W/bs/mnt/app/eso/hmi/lsd/lsd.sh"
    grep -q '>>> pmcp' "$L" || { echo "boot=factory-lsd"; return; }
    { echo 'BASE_DIR=/X; BOOTCLASSPATH=-Xbootclasspath/a:/ifs/lsd.jxe; RUN_MODE='
      sed -n '/^# >>> pmcp: CarPlay AID mod/,/^# <<< pmcp/p' "$L" \
        | sed -e "s#/mnt/app/carplaymaps#$W/bs/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/bs/mnt/persist/pmcp#g" \
              -e "s|( .PMCP_DIR/rg/rgi-observer.*) &|:|"
      echo 'echo "boot=$PMCP_USE"'; } > "$W/bs.sh"
    $SH "$W/bs.sh" 2>&1 | tail -1
}
# one AA connection on a fresh unit start: "use=yes|trial|no" from the gal wrapper (factory gal: gal=factory)
galsim() {
    G="$W/bs/mnt/app/eso/bin/apps/gal"
    head -1 "$G" 2>/dev/null | grep -q '^#!/bin/sh' || { echo "gal=factory"; return; }
    rm -rf "$W/bs/ramdisk"; mkdir -p "$W/bs/ramdisk"
    sed -e "s#/mnt/app/carplaymaps#$W/bs/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/bs/mnt/persist/pmcp#g" \
        -e "s#/ramdisk/#$W/bs/ramdisk/#g" -e 's#^exec "$REAL" "$@"#:#' "$G" > "$W/gs.sh"
    $SH "$W/gs.sh" >/dev/null 2>&1
    echo "gal=`sed -e 's/^set=[^ ]* //' -e 's/ capture=.*//' "$W/bs/ramdisk/pmcp-aa-last" 2>/dev/null`"
}
state() { run status; sed -n 's/^Unit state: //p' "$W/out"; }

# every chain ends with restore (factory again), so a chain can be left out without changing the others
OWN=("install map-square-fps40" "rg-system-on" "java-on rg" "java-on sl" "java-on ui" \
     "speedlimit-mode turnto" "speedlimit-mode street" "speedlimit-mode off" "java-off sl" "java-off ui" "java-on zoom" "restore" \
     "install map-square-fps40" "aa-on" "rg-system-on" "java-on rg" "java-on nai" "aa-remove" "aa-on" "restore")
# the main menu (2, 3, 4) over versions this card does not support
MAIN=("map-install map-square-fps40" "aa-install" "fx:aa-unknown" "aa-install" "rg-system-on" "java-on rg" "java-on nai" \
      "fx:java-unknown" "fx:rg-unknown" "features-reset" "rg-system-on" "java-on np" "fx:dio-mixed" "map-install map-square-fps40" "restore")
OWN+=("${MAIN[@]}")
# AA 1.0 (A153): the output switch (no trial), and main menu 3 over a Java part this card does not support (left as
# it is); experimental cards also record. An experimental AA set (AAX_FEEDER) would be swapped in and out as well.
XAA=("map-install map-square-fps40" "java-on nai" "aa-install" "aa-output ring" "aa-output direct" "aa-remove" \
     "fx:java-unknown" "aa-install" "aa-output ring" "restore")
case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) XAA+=("map-install map-square-fps40" "aa-install" "aa-capture 60" "aa-capture off" "restore") ;; esac
grep -q '^AAX_FEEDER ' <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") && \
    XAA+=("map-install map-square-fps40" "aa-install" "aa-on-exp" "aa-output direct" "aa-install" "aa-on-exp" "aa-remove" "aa-on-exp" "restore")
OWN+=("${XAA[@]}")
if [ "$OLDCARDS" = yes ]; then
CHAIN=("v13:install map-clean" "v13:java-on nai" "v13:rg-system-on" "v13:java-on rglu" "rg-update" "java-update" "java-on np" \
       "switch map-clean-l40" "java-off np" "java-off rg" "rg-system-off" "java-off nai" "restore" \
       "install map-square-fps40" "rg-system-on" "java-on rg" "java-on sl" "java-on ui" \
       "speedlimit-mode turnto" "speedlimit-mode street" "speedlimit-mode off" "java-off sl" "java-off ui" "java-on zoom" "restore" \
       "exp:install map-clean" "exp:aa-on gamma" "aa-remove" "exp:aa-on most" "restore" \
       "install map-square-fps40" "aa-on" "rg-system-on" "java-on rg" "java-on nai" "aa-remove" "aa-on" "restore" \
       "exp:install map-clean" "exp:aa-on gamma" "aa-on" "restore" \
       "x143:install map-square-fps40" "x143:rg-system-on" "x143:java-on nai" "x143:java-on rg-aa" "x143:aa-on" "java-update" "aa-on" "restore" \
       "v151:map-install map-square-fps40" "v151:rg-system-on" "v151:java-on nai" "v151:java-on sl" "v151:java-on ui" \
       "java-update" "restore" \
       "${MAIN[@]}" "${XAA[@]}")
else
CHAIN=("${OWN[@]}")
fi
# quick mode (daily work): the card's own actions only; the full run (earlier cards, replay cross-check) before RC
[ "${PMCP_FAULT_QUICK:-0}" = 1 ] && CHAIN=("${OWN[@]}")
if [ "${PMCP_FAULT_SCOPE:-all}" = speedlimit ]; then
    # turnto needs rg in the set (rg writes TurnToInfo since v1.4); street (CurrentPositionInfo trial) does not
    CHAIN=("install map-clean" "rg-system-on" "java-on rg" "java-on sl" "speedlimit-mode turnto" "speedlimit-mode street" \
           "speedlimit-mode off" "java-off sl" "restore")
fi
# one action of the chain: kill it before its 1st, 2nd, ... mutating command and check each result
one_target() {
    t=$1; target=${CHAIN[$t]}
    # the tree before this action: its template from the single chain run (see below)
    rm -rf "$W/unit" "$W/tpl"; cp -Rp "$TPL/$t" "$W/unit"; cp -Rp "$TPL/$t" "$W/tpl"
    before_boot=$(cat "$W/tpl/mnt/app/carplaymaps/HMI_BOOT" 2>/dev/null)
    before_aa=$(cat "$W/tpl/mnt/app/carplaymaps/aa/AA_BOOT" 2>/dev/null)
    before_mode=$(mode_digest)
    case "$target" in
        "speedlimit-mode "*) after_mode=$(printf '%s\n' "${target#speedlimit-mode }" | shasum -a 256 | cut -d' ' -f1) ;;
        *) after_mode="$before_mode" ;;
    esac
    n=1
    while :; do
        rm -rf "$W/unit"; cp -Rp "$W/tpl" "$W/unit"
        runfi $n $target
        if ! grep -q "FI_KILLED" "$W/outfi" && grep -q "_OK" "$W/outfi" && ! grep -q "PMCP_FAIL" "$W/outfi"; then
            echo "[$target] completes after $((n-1)) mutating commands"; break
        fi
        CASES=$((CASES+1))
        killed=$(tail -1 "$W/filog" 2>/dev/null | sed "s#$W##g")
        case "$target" in
            "speedlimit-mode "*)
                now_mode=$(mode_digest)
                [ "$now_mode" = "$before_mode" ] || [ "$now_mode" = "$after_mode" ] \
                    || bad "[$target] kill@$n ($killed): partially published mode file"
                ;;
        esac
        bs=$(bootsim)
        now_boot=$(cat "$U/carplaymaps/HMI_BOOT" 2>/dev/null)
        # use=yes is fine for the set from before the action, or for a set the user had confirmed before (its own ok
        # marker existed before the action, e.g. java-off back to an earlier set); anything else loads untested
        now_id=${now_boot%% *}
        if [ "$bs" = "boot=yes" ] && [ "$now_boot" != "$before_boot" ] && [ ! -e "$W/tpl/mnt/persist/pmcp/ok.$now_id" ]; then
            bad "[$target] kill@$n ($killed): untested set loads without a trial: '$now_boot' (was '$before_boot')"
        fi
        # the gal wrapper may run the hook without a trial only for a set confirmed before the action
        gs=$(galsim)
        now_aa=$(cat "$U/carplaymaps/aa/AA_BOOT" 2>/dev/null)
        if [ "$gs" = "gal=use=yes" ] && [ "$now_aa" != "$before_aa" ] && [ ! -e "$W/tpl/mnt/persist/pmcp/aa-ok.$now_aa" ]; then
            bad "[$target] kill@$n ($killed): untested AA set runs the hook without a trial: '$now_aa' (was '$before_aa')"
        fi
        # use=yes after a change: the hook, feeder and hook settings are the ones the AA_BOOT id names
        # (id = mode-hook8-feeder8-conf8), and with the id unchanged feeder.conf is the one from before the action.
        # A state left exactly as it was before the action (fx:aa-unknown: its files under its own confirmed id) is not
        # this action's doing.
        _ad="$U/carplaymaps/aa"; _same=yes
        for _f in AA_BOOT libgal_hook.so aa-most-feeder gal-hook.conf feeder.conf; do
            cmp -s "$_ad/$_f" "$W/tpl/mnt/app/carplaymaps/aa/$_f" || _same=no
        done
        if [ "$gs" = "gal=use=yes" ] && [ $_same = no ]; then
            _want=$(echo "$now_aa" | cut -d- -f2-4)
            _have="$(shasum -a 256 "$_ad/libgal_hook.so" | cut -c1-8)-$(shasum -a 256 "$_ad/aa-most-feeder" | cut -c1-8)-$(shasum -a 256 "$_ad/gal-hook.conf" | cut -c1-8)"
            [ "$_want" = "$_have" ] || bad "[$target] kill@$n ($killed): hook runs with files of another set: AA_BOOT '$now_aa', files $_have"
            if [ "$now_aa" = "$before_aa" ] && ! cmp -s "$_ad/feeder.conf" "$W/tpl/mnt/app/carplaymaps/aa/feeder.conf"; then
                bad "[$target] kill@$n ($killed): confirmed set '$now_aa' runs with another feeder.conf"
            fi
        fi
        case "$gs" in "gal=pmcp-aa: "*) bad "[$target] kill@$n ($killed): gal wrapper without the factory gal copy (AA dead)" ;; esac
        if [ "$target" = rg-update ]; then
            # an interrupted update is finished by running it again
            run rg-update; grep -q "PMCP_RG_UPDATE_OK\|RG_UPDATE_ALREADY_CURRENT" "$W/out" && run status && grep -q "Route guidance system: on" "$W/out" \
                || bad "[$target] kill@$n ($killed): rg-update again did not finish: $(grep PMCP_FAIL "$W/out")"
        fi
        if [ "$target" = java-update ]; then
            # an earlier card's JAR left behind, no longer listed by HMI_BOOT: status names it as unused
            _stray=""
            for _j in "$U"/eso/hmi/lsd/jars/pmcp-*.jar; do
                [ -e "$_j" ] && ! grep -q " ${_j##*/}" "$U/carplaymaps/HMI_BOOT" 2>/dev/null && _stray="$_stray ${_j##*/}"
            done
            if [ -n "$_stray" ]; then
                run status
                for _j in $_stray; do
                    grep "unused JAR files (not loaded):" "$W/out" | grep -qF " $_j" \
                        || bad "[$target] kill@$n ($killed): status does not name the unused JAR $_j"
                done
            fi
            # an interrupted Java update is finished by running it again
            run java-update; grep -q "PMCP_JAVA_UPDATE_OK\|JAVA_UPDATE_ALREADY_CURRENT" "$W/out" && run status && grep -q "Unit state: JAVA" "$W/out" \
                && ! grep -q "earlier card\|unused JAR" "$W/out" \
                || bad "[$target] kill@$n ($killed): java-update again did not finish: $(grep PMCP_FAIL "$W/out")"
        fi
        case "$target" in
            "map-install "*|aa-install|aa-on-exp|features-reset)
                # the main menu's own repair: the same button pressed again finishes the interrupted run
                rm -rf "$W/rerun"; cp -Rp "$W/unit" "$W/rerun"; mv "$W/unit" "$W/unit.k"; mv "$W/rerun" "$W/unit"
                run $target
                if grep -q "PMCP_FAIL" "$W/out" && ! grep -q "PMCP_FAIL=.*_ALREADY_" "$W/out"; then
                    bad "[$target] kill@$n ($killed): pressing it again did not finish: $(grep PMCP_FAIL "$W/out")"
                fi
                rm -rf "$W/unit"; mv "$W/unit.k" "$W/unit" ;;
        esac
        # Android Auto must never be left dead: gal is the factory file, or a wrapper with a verified factory copy
        GALH=$(shasum -a 256 < "$U/eso/bin/apps/gal" | cut -d' ' -f1)
        if [ "$GALH" != 3b422d47a16dd473dc426aa3a88348bfee0da0e7585993a3566df242339346f9 ] \
            && [ "$(shasum -a 256 < "$U/carplaymaps/aa/gal.real" 2>/dev/null | cut -d' ' -f1)" != 3b422d47a16dd473dc426aa3a88348bfee0da0e7585993a3566df242339346f9 ]; then
            bad "[$target] kill@$n ($killed): gal is not factory and no verified factory copy (Android Auto dead)"
        fi
        # AA left half done (killed aa-on / aa-remove, or restore before its AA step finished): aa-remove finishes it
        if run status && grep -q "Android Auto: unknown" "$W/out"; then
            run aa-remove; grep -q PMCP_AA_REMOVE_OK "$W/out" || bad "[$target] kill@$n ($killed): aa-remove again did not finish: $(grep PMCP_FAIL "$W/out")"
        fi
        st=$(state)
        case "$st" in
            PARTIAL|VIDEO|JAVA)
                run restore
                if ! grep -q PMCP_RESTORE_OK "$W/out"; then bad "[$target] kill@$n ($killed): restore failed: $(grep PMCP_FAIL "$W/out")"
                elif [ "$(snapshot)" != "$FACTORY" ]; then bad "[$target] kill@$n ($killed): restore left a non-factory tree"
                else res="restore->factory"; fi ;;
            STOCK)
                run install map-clean && run restore
                [ "$(snapshot)" = "$FACTORY" ] && res="STOCK (install+restore ok)" || bad "[$target] kill@$n ($killed): STOCK, tree differs after install+restore" ;;
            *) bad "[$target] kill@$n ($killed): state '$st' (tool locked out)"; res="" ;;
        esac
        echo "[$target] kill@$n ($killed) [$bs $gs] state=$st ${res:-}"
        res=""
        n=$((n+1))
        [ $n -gt 80 ] && { bad "[$target] more than 80 mutating commands"; break; }
    done
}

# targets of this run (the earlier cards' actions and fx: only prepare units)
is_target() {
    case "${CHAIN[$1]}" in v13:*|exp:*|x143:*|v151:*|fx:*) return 1 ;; esac
    if [ "${PMCP_FAULT_SCOPE:-all}" = speedlimit ]; then
        case "${CHAIN[$1]}" in "java-on sl"|"java-off sl"|"speedlimit-mode "*) ;; *) return 1 ;; esac
    fi
    return 0
}
TARGETS=()
for ((t=0; t<${#CHAIN[@]}; t++)); do is_target $t && TARGETS+=($t); done
LAST=${TARGETS[${#TARGETS[@]}-1]}

# The chain runs once. The tree before each target action is kept as that action's template (cp -Rp: modes, links,
# empty dirs and /ramdisk included); a kill case starts from it instead of replaying the chain from a factory unit.
prep() { run ${CHAIN[$1]}; grep -q "_OK" "$W/out" && ! grep -q "PMCP_FAIL" "$W/out" || { echo "prep ${CHAIN[$1]} failed"; cat "$W/out"; exit 99; }; confirm_set; }
TPL="$W/templates"; mkdir -p "$TPL"
fresh_unit; FACTORY=$(snapshot)
for ((p=0; p<=LAST; p++)); do
    is_target $p && cp -Rp "$W/unit" "$TPL/$p"
    [ $p -lt $LAST ] && prep $p
done
# full mode: a few templates against a replay from a factory unit (first, middle, last target, first after an fx)
if [ "${PMCP_FAULT_QUICK:-0}" != 1 ]; then
    _fx=""; for ((p=0; p<=LAST; p++)); do
        case "${CHAIN[$p]}" in fx:*) _seen=1 ;; *) [ -n "${_seen:-}" ] && is_target $p && { _fx=$p; break; } ;; esac
    done
    for t in ${TARGETS[0]} ${TARGETS[${#TARGETS[@]}/2]} $LAST $_fx; do
        fresh_unit
        for ((p=0; p<t; p++)); do prep $p; done
        [ "$(snapshot)" = "$(snapshot "$TPL/$t")" ] && echo "template $t (${CHAIN[$t]}) = replay" \
            || bad "template $t (${CHAIN[$t]}) differs from a replay of the chain"
    done
fi

# kill cases in parallel: each worker has its own work dir and card copy; output is printed in chain order
JOBS=${PMCP_FAULT_JOBS:-6}
MAINW=$W
for ((k=0; k<JOBS; k++)); do
    (
        W="$MAINW/w$k"; U="$W/unit/mnt/app"; mkdir -p "$W"; cp -Rp "$MAINW/sd" "$W/sd"
        FAILS=0; CASES=0; i=0
        for t in "${TARGETS[@]}"; do
            [ $((i % JOBS)) = $k ] && one_target $t > "$MAINW/log.$t" 2>&1
            i=$((i+1))
        done
        echo "$CASES $FAILS" > "$W/result"
    ) &
done
wait
W=$MAINW
for t in "${TARGETS[@]}"; do cat "$W/log.$t" 2>/dev/null || bad "[${CHAIN[$t]}] no result (worker died)"; done
for ((k=0; k<JOBS; k++)); do
    if read _c _f < "$W/w$k/result" 2>/dev/null; then CASES=$((CASES+_c)); FAILS=$((FAILS+_f)); else bad "worker $k gave no result"; fi
done
rm -rf "$W"
echo "FAULT CASES: $CASES, FAILED: $FAILS"
[ $FAILS -gt 255 ] && exit 255   # an exit status wraps at 256
exit $FAILS
