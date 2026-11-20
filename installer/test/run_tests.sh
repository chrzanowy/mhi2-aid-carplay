#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Host tests for pmcp.sh against a fake unit tree built from our MU1161 backup, plus an execution
# test of the generated lsd.sh blocks (trial boot) over several simulated boots, plus the firmware profile tests
# (scripts/profile.py: validate, detect, a broken profile is refused).
#   run_tests.sh SD_BUILD_DIR SHELL [SHELL...]
#   PMCP_PROFILE=MU1161 (default): the firmware profile whose values (backup folder, lsd.jxe size, stock hashes, version
#   tag) the tests expect; the same variable as for build_sd.py.
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
    [ $_sum -gt 255 ] && exit 255   # an exit status wraps at 256
    exit $_sum
fi
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
T=$(cd "$(dirname "$0")" && pwd)   # installer/test (no_printf.inc)
PROJ=$(cd "$T/../.." && pwd)       # this project (any folder name)
export PMCP_PROFILE="${PMCP_PROFILE:-MU1161}"
pf() { python3 -I "$PROJ/scripts/profile.py" get "$PMCP_PROFILE" "$1"; }   # a profile value (lists: one item per line)
# packages of the Java set that this profile does not have (their buttons stay and say "not yet supported"); none on MU1161
HAS_NP=no; case " $(pf packages | tr '\n' ' ')" in *" np "*) HAS_NP=yes ;; esac
UNSUP_PKGS=""
for _p in nai np rg zoom dn sl ui; do case " $(pf packages | tr '\n' ' ')" in *" $_p "*) ;; *) UNSUP_PKGS="$UNSUP_PKGS $_p" ;; esac; done
BKROOT="${PMCP_BACKUP:-$REPO/backup/$(pf backup_dir)}"
BK="$BKROOT/$(pf appimg)"
BKSYS="$BKROOT/$(pf system)"
JXE_SIZE=$(pf lsd_jxe.size)
VTAG=$(pf version_tag)
export PMCP_TEST_GAWK="${PMCP_TEST_GAWK:-$REPO/upstream/tools/gawk-3.1.5/gawk}"
FAILS=0
W=$(mktemp -d /tmp/pmcp-test.XXXX)
export PMCP_TEST_GEMLOG="$W/gem.log"   # the GEM button log outside the unit tree (the tree checks stay exact)
STOCK_LSD=$(pf stock.LSD | sed -n 2p)
LSD_JAVA=$(sed -n 's/^LSD_JAVA \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")
jsha() { sed -n "s/^JAR_$1 \([0-9a-f]*\) .*/\1/p" "$SDB/pmcp/pmcp.sh"; }
jid() { echo "$1-$(jsha "$1" | cut -c1-8)"; }
NAI_SHA=$(jsha nai); NP_SHA=$(jsha np)
NAI=$(jid nai); NP=$(jid np); RG=$(jid rg); ZOOM=$(jid zoom); DN=$(jid dn); UI=$(jid ui)
# this card's JAR file names on the unit (A188: pmcp-<package>-<sha8>.jar, NavActiveIgnore.jar for nai)
jf() { sed -n "s#^JAR_$1 [0-9a-f]* [0-9]* jars/##p" "$SDB/pmcp/pmcp.sh"; }
NPF=$(jf np); RGF=$(jf rg); ZOOMF=$(jf zoom); DNF=$(jf dn); SLF=$(jf sl); UIF=$(jf ui)
msha() { sed -n "s/^$1 \([0-9a-f]*\) .*/\1/p" "$SDB/pmcp/pmcp.sh"; }
# A188: make this card's package $1 in the unit's set an "earlier card's" version. Part name $2 (default $1, e.g. rgluasfm
# for a renamed package), JAR file $3 (default pmcp-<name>-old.jar), content one byte longer and sha8 0a1b2c3d, or with
# $4=same the same content under the other file name (an earlier card's name for this card's package). The set's
# ok./trial. markers follow the new set id, so a confirmed set stays confirmed.
old_java() {
    local n=$1 o=${2:-$1} nf=${3:-pmcp-${2:-$1}-old.jar} f line id jars nid njars s8 m
    f=$(jf "$n"); s8=$(jsha "$n" | cut -c1-8)
    line=$(cat "$U/carplaymaps/HMI_BOOT"); id=${line%% *}; jars=${line#* }
    if [ "${4:-}" = same ]; then nid=${id/$n-$s8/$o-$s8}; else nid=${id/$n-$s8/$o-0a1b2c3d}; fi
    njars=" $jars "; njars=${njars/ $f / $nf }; njars=${njars# }; njars=${njars% }
    mv "$U/eso/hmi/lsd/jars/$f" "$U/eso/hmi/lsd/jars/$nf"
    [ "${4:-}" = same ] || printf x >> "$U/eso/hmi/lsd/jars/$nf"
    echo "$nid $njars" > "$U/carplaymaps/HMI_BOOT"
    for m in ok trial; do [ -e "$W/unit/mnt/persist/pmcp/$m.$id" ] && mv "$W/unit/mnt/persist/pmcp/$m.$id" "$W/unit/mnt/persist/pmcp/$m.$nid"; done
    return 0
}
[ -n "$NAI_SHA" ] && [ -n "$NP_SHA" ] || { echo "no JAR hashes in the manifest"; exit 99; }
# simulate the lsd.sh block of the unit tree for one normal boot (or RUN_MODE=$1); prints "boot=USE set=ID jars=LIST"
unit_boot() {
    { echo "BASE_DIR=/X; BOOTCLASSPATH=-Xbootclasspath/a:/ifs/lsd.jxe; RUN_MODE=${1:-}"
      sed -n '/^# >>> pmcp: CarPlay AID mod/,/^# <<< pmcp/p' "$W/unit/mnt/app/eso/hmi/lsd/lsd.sh" \
        | sed -e "s#/mnt/app/carplaymaps#$W/unit/mnt/app/carplaymaps#g" -e "s#/mnt/persist/pmcp#$W/unit/mnt/persist/pmcp#g" \
              -e "s|( .PMCP_DIR/rg/rgi-observer.*) &|:|" -e "s|^ln -Ps .*|:|"
      echo 'echo "boot=$PMCP_USE set=$PMCP_SET jars=$PMCP_JARS"'; } > "$W/unit-boot.sh"
    $SH "$W/unit-boot.sh" 2>&1 | tail -1
}

ok()   { echo "  ok   $*"; }
bad()  { echo "  FAIL $*"; FAILS=$((FAILS+1)); }
expect_out() { grep -q -- "$1" "$W/out" && ok "$2" || { bad "$2 (wanted '$1')"; sed 's/^/       | /' "$W/out" | tail -8; }; }
# one shasum process for the whole tree (same lines as one per file)
snapshot() { (cd "$1" && find . -type f ! -path './sdlog/*' -exec shasum -a 256 {} + | sort -k2); }
h() { shasum -a 256 < "$1" | cut -d' ' -f1; }

fresh_unit() {
    rm -rf "$W/unit" "$W/sd"
    mkdir -p "$W/unit/ifs" "$W/unit/ramdisk" "$W/unit/mnt/app/eso/bin/apps" "$W/unit/mnt/app/eso/hmi/lsd/jars" "$W/unit/mnt/app/armle/usr/bin" "$W/unit/mnt/persist/etc" \
        "$W/unit/mnt/app/armle/lib/dll" "$W/unit/mnt/system/etc/mm"
    cp "$BK/armle/lib/dll/ipod-drvr-iap2.so" "$W/unit/mnt/app/armle/lib/dll/"
    cp "$BKSYS/mm/iap2.cfg" "$W/unit/mnt/system/etc/mm/"
    mkdir -p "$W/unit/mnt/system/etc/eso/production" "$W/unit/dev/mlb"
    cp "$BKSYS/eso/production/displaymanager.json" "$W/unit/mnt/system/etc/eso/production/"
    mkfile -n $JXE_SIZE "$W/unit/ifs/lsd.jxe" 2>/dev/null || truncate -s $JXE_SIZE "$W/unit/ifs/lsd.jxe"
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

# every run of this card's pmcp.sh: a command missing on the unit (no_printf.inc) is recorded, checked once per shell
run() { PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; noexec "$*"; }
noexec() { grep "cannot execute" "$W/out" | sed "s|^|$1: |" >> "$W/noexec"; }
# Earlier cards are only for the two release update tests ([50] v1.6.0, [55] v1.7.1). They are not in the repo: a build
# from install.sh skips those tests (and says so); release runs set PMCP_REQUIRE_OLD_CARDS=1, which makes a missing earlier
# card a failure. Every other earlier version is made from this card (old_java / old_aa, A188): pmcp.sh recognises earlier
# versions of its own packages and AA sets by name, so no earlier card is needed to test it.
SKIPS=0
card_ok() {
    [ -e "$1" ] && return 0
    if [ "${PMCP_REQUIRE_OLD_CARDS:-0}" = 1 ]; then bad "earlier card $2 missing: $1"
    else echo "  skip earlier card $2 not present ($1): its update test is skipped"; SKIPS=$((SKIPS+1)); fi
    return 1
}
STOCK_GAL=$(pf stock.GAL | sed -n 2p)
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
# a scenario on a fresh factory unit; factory = its tree
start_unit() { fresh_unit; factory=$(snapshot "$W/unit"); }
# restore, then the exact factory tree (/ramdisk left out: a simulated start writes there); $1 = the label
restore_exact() {
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "$1" || bad "$1: tree differs after restore"
}
# java-update or 4 replaced an earlier card's JAR: OLD file gone, NEW file holds this card's package PKG; $4 = the label
jar_replaced() {
    [ ! -e "$U/eso/hmi/lsd/jars/$1" ] && [ "$(h "$U/eso/hmi/lsd/jars/$2")" = "$(jsha "$3")" ] && ok "$4" \
        || bad "$4: $(ls "$U/eso/hmi/lsd/jars" | grep pmcp | tr '\n' ' ')"
}

for SH in "$@"; do
    echo "=== shell: $SH"
    rm -f "$W/noexec"
    U="$W/unit/mnt/app"

    if [ "${PMCP_TEST_SCOPE:-all}" != speedlimit ]; then
    echo "[0] firmware profiles (scripts/profile.py)"
    PP="$PROJ/scripts/profile.py"
    prof() { python3 -I "$PP" "$@" > "$W/pout" 2>&1; echo $? > "$W/prc"; }
    prof_is() { [ "$(cat "$W/prc")" = "$1" ] && ok "$2" || { bad "$2 (exit $(cat "$W/prc"), wanted $1)"; sed 's/^/       | /' "$W/pout" | tail -3; }; }
    prof validate; prof_is 0 "every profile validates"
    grep -qx "ok $PMCP_PROFILE" "$W/pout" && ok "validate lists $PMCP_PROFILE" || bad "validate output: $(cat "$W/pout")"
    prof detect "$(pf train)" "$(pf mu)"; prof_is 0 "detect: train and MU of $PMCP_PROFILE"
    [ "$(cat "$W/pout")" = "$PMCP_PROFILE" ] && ok "detect names $PMCP_PROFILE" || bad "detect printed: $(cat "$W/pout")"
    prof detect MHI2_XX_VWG13_P0000 "$(pf mu)"; prof_is 1 "detect: unknown train is an error"
    grep -q "no single profile" "$W/pout" && ok "unknown train: readable message" || bad "unknown train message: $(cat "$W/pout")"
    prof detect "$(pf train)" 9999; prof_is 1 "detect: known train, unknown MU is an error"
    prof detect MHI2_US_VWG13_P3662 1418; prof_is 1 "detect: MU1418 (no profile yet) is an error"
    prof detect "" ""; prof_is 1 "detect: empty train and MU is an error"
    prof get NOPE train; prof_is 1 "get: unknown profile is an error"
    prof get mu1161 train; prof_is 1 "get: a lower-case id is an error"
    prof get "$PMCP_PROFILE" no.such.key; prof_is 1 "get: unknown key is an error"
    prof pins "$PMCP_PROFILE"; prof_is 0 "pins"
    [ "$(wc -l < "$W/pout" | tr -d ' ')" = 7 ] && [ "$(sed -n 1p "$W/pout" | cut -d' ' -f1)" = "$(pf lsd_jxe.file)" ] && ok "pins: lsd.jxe and the six stock files" || bad "pins: $(cat "$W/pout")"
    # the pinned backup files really are what the profile says (the build and install.sh trust these)
    pins_bad=0
    while read -r rel want; do
        [ "$(h "$BKROOT/$rel")" = "$want" ] || { pins_bad=1; echo "       | backup file differs from its pin: $rel"; }
    done < "$W/pout"
    [ $pins_bad = 0 ] && ok "backup files match the profile pins" || bad "backup files differ from the profile pins"
    # a broken profile is refused: work on a copy of scripts/profile.py and the profile (profile.py reads profiles/ next to it)
    cat > "$W/mut.py" <<'PY'
import json, sys
path, expr = sys.argv[1], sys.argv[2]
d = json.load(open(path))
exec(expr)
json.dump(d, open(path, "w"))
PY
    pt_fresh() {
        rm -rf "$W/pt"; mkdir -p "$W/pt/scripts" "$W/pt/profiles"
        cp "$PP" "$W/pt/scripts/profile.py"; cp -R "$PROJ/profiles/$PMCP_PROFILE" "$W/pt/profiles/"
    }
    pt_mut() { python3 -I "$W/mut.py" "$W/pt/profiles/$PMCP_PROFILE/$1" "$2"; }
    pt_refused() {   # LABEL FILE EXPR: validate must fail on the mutated copy
        pt_fresh; pt_mut "$2" "$3"; python3 -I "$W/pt/scripts/profile.py" validate > "$W/pout" 2>&1; echo $? > "$W/prc"
        [ "$(cat "$W/prc")" != 0 ] && grep -q "^profile: " "$W/pout" && ok "refused: $1" || { bad "not refused: $1 ($(cat "$W/pout" | tail -1))"; }
    }
    pt_fresh; python3 -I "$W/pt/scripts/profile.py" validate > "$W/pout" 2>&1 && ok "control: an unmodified copy validates" || bad "control copy: $(cat "$W/pout")"
    pt_refused "stock hash in capitals" profile.json 'd["stock"]["LSD"][1] = d["stock"]["LSD"][1].upper()'
    pt_refused "stock hash too short" profile.json 'd["stock"]["DIO"][1] = d["stock"]["DIO"][1][:63]'
    pt_refused "stock hash not hex" profile.json 'd["stock"]["GAL"][1] = "z" * 64'
    pt_refused "lsd_jxe hash too short" profile.json 'd["lsd_jxe"]["sha256"] = d["lsd_jxe"]["sha256"][:40]'
    pt_refused "lsd.jar hash wrong" profile.json 'd["lsd_jar_sha256"][0] = "00"'
    pt_refused "empty lsd.jar hash list" profile.json 'd["lsd_jar_sha256"] = []'
    pt_refused "rg driver hash wrong" profile.json 'd["rg_driver_in_sha256"] = "x"'
    pt_refused "size not a number" profile.json 'd["stock"]["LSD"][2] = "16567"'
    pt_refused "size zero" profile.json 'd["lsd_jxe"]["size"] = 0'
    pt_refused "unknown key" profile.json 'd["surprise"] = 1'
    pt_refused "missing key (packages)" profile.json 'del d["packages"]'
    pt_refused "missing key (mu)" profile.json 'del d["mu"]'
    pt_refused "schema 2" profile.json 'd["schema"] = 2'
    pt_refused "id differs from the directory" profile.json 'd["id"] = "MU9999"'
    pt_refused "unknown package" profile.json 'd["packages"].append("zz")'
    pt_refused "package twice" profile.json 'd["packages"].append(d["packages"][0])'
    pt_refused "stock path with .." profile.json 'd["stock"]["LSD"][0] = "../x"'
    pt_refused "absolute stock path" profile.json 'd["stock"]["LSD"][0] = "/x"'
    pt_refused "stock key missing" profile.json 'del d["stock"]["GAL"]'
    pt_refused "lsd.sh state list without stock first" profile.json 'd["lsd_sh_states"] = ["toolbox_nai"]'
    pt_refused "bad version_tag" profile.json 'd["version_tag"] = "MU 1"'
    pt_refused "bad mathsls commit" profile.json 'd["mathsls_commit"] = "abc"'
    # review 2026-11-12: values that reach pmcp.sh or a path must be exactly shaped
    pt_refused "cluster with shell text" profile.json 'd["cluster"] = "791\"; touch /tmp/x; \""'
    pt_refused "version_tag with a final newline" profile.json 'd["version_tag"] += "\n"'
    pt_refused "mu with a final newline" profile.json 'd["mu"] += "\n"'
    pt_refused "appimg absolute" profile.json 'd["appimg"] = "/etc"'
    pt_refused "@system path escaping to /" profile.json 'd["stock"]["IAP2CFG"][0] = "@system//etc/x"'
    pt_refused "backup_dir not MU<mu>" profile.json 'd["backup_dir"] = "MU0000"'
    pt_refused "duplicate jar pin" profile.json 'd["lsd_jar_sha256"].append(d["lsd_jar_sha256"][0])'
    pt_refused "empty package list" profile.json 'd["packages"] = []'
    pt_refused "history: renamed to a name no package has" history.json 'd["java_renamed"]["rglu"] = "zz"'
    pt_refused "history: renamed from a package's own name" history.json 'd["java_renamed"]["np"] = "rg"'
    pt_refused "history duplicate row" history.json 'd["rg_known"].append(dict(d["rg_known"][0]))'
    pt_refused "history: sha1 wrong" history.json 'd["rg_known"][0]["sha1"] = "00"'
    pt_refused "history: sha256 in capitals" history.json 'd["rg_known"][0]["sha256"] = d["rg_known"][0]["sha256"].upper()'
    pt_refused "history: the removed java_old list" history.json 'd["java_old"] = []'
    pt_refused "history: unknown key" history.json 'd["rg_known"][0]["extra"] = 1'
    pt_refused "history: top-level key missing" history.json 'del d["rg_known"]'
    pt_fresh; rm "$W/pt/profiles/$PMCP_PROFILE/history.json"; python3 -I "$W/pt/scripts/profile.py" validate > "$W/pout" 2>&1; echo $? > "$W/prc"
    prof_is 1 "refused: no history.json"
    pt_fresh; echo '{' > "$W/pt/profiles/$PMCP_PROFILE/profile.json"; python3 -I "$W/pt/scripts/profile.py" validate > "$W/pout" 2>&1; echo $? > "$W/prc"
    prof_is 1 "refused: profile.json is not JSON"
    # two profiles with the same train and MU: detect must not pick one; with a different MU it tells them apart
    pt_fresh; cp -R "$W/pt/profiles/$PMCP_PROFILE" "$W/pt/profiles/MU9999"; python3 -I "$W/mut.py" "$W/pt/profiles/MU9999/profile.json" 'd["id"] = "MU9999"'
    python3 -I "$W/pt/scripts/profile.py" detect "$(pf train)" "$(pf mu)" > "$W/pout" 2>&1; echo $? > "$W/prc"
    prof_is 1 "detect: two profiles with the same train and MU is an error"
    python3 -I "$W/mut.py" "$W/pt/profiles/MU9999/profile.json" 'd["mu"] = "9999"; d["backup_dir"] = "MU9999"'
    python3 -I "$W/pt/scripts/profile.py" detect "$(pf train)" 9999 > "$W/pout" 2>&1; echo $? > "$W/prc"
    prof_is 0 "detect: a profile with another MU is found by its own MU"
    [ "$(cat "$W/pout")" = MU9999 ] && ok "detect names MU9999" || bad "detect printed: $(cat "$W/pout")"
    python3 -I "$W/pt/scripts/profile.py" detect "$(pf train)" "$(pf mu)" > "$W/pout" 2>&1; [ "$(cat "$W/pout")" = "$PMCP_PROFILE" ] && ok "detect still names $PMCP_PROFILE" || bad "detect printed: $(cat "$W/pout")"
    # the card builder refuses an unknown profile before it writes anything
    PMCP_PROFILE=NOPE python3 -I "$PROJ/installer/build_sd.py" "$W/nobuild" > "$W/pout" 2>&1; echo $? > "$W/prc"
    prof_is 1 "build_sd.py: unknown profile refused"
    [ ! -e "$W/nobuild" ] && ok "build_sd.py wrote nothing" || bad "build_sd.py created $W/nobuild"
    rm -rf "$W/pt" "$W/nobuild"

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
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NAI+$NP NavActiveIgnore.jar $NPF" ] && ok "HMI_BOOT in catalog order" || bad "HMI_BOOT: $(cat "$U/carplaymaps/HMI_BOOT")"
    # regression (2026-10-21): a helper overwrote the caller's "f", so the np JAR was staged as NavActiveIgnore.jar
    [ "$(h "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar")" = $NAI_SHA ] && [ "$(h "$U/eso/hmi/lsd/jars/$NPF")" = $NP_SHA ] \
        && ok "each JAR under its own name with its own hash" || bad "JAR names/hashes mixed up"
    run java-off nai; rc_is 0
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NP $NPF" ] && [ ! -e "$U/eso/hmi/lsd/jars/NavActiveIgnore.jar" ] && ok "nai off, np stays" || bad "after nai off"
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
    [ "$(cat "$U/carplaymaps/HMI_BOOT")" = "$NAI+$NP+$RG+$ZOOM+$DN NavActiveIgnore.jar $NPF $RGF $ZOOMF $DNF" ] && ok "HMI_BOOT with five JARs" || bad "HMI_BOOT: $(cat "$U/carplaymaps/HMI_BOOT")"
    run status; expect_out "Unit state: JAVA" "JAVA with five packages (set names parsed from HMI_BOOT)"
    run java-off zoom; rc_is 0; [ ! -e "$U/eso/hmi/lsd/jars/$ZOOMF" ] && ok "zoom off" || bad "zoom jar left"
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

    echo "[10] not $PMCP_PROFILE (lsd.jxe size)"
    BADSIZE=$((JXE_SIZE + 10232))
    fresh_unit; rm "$W/unit/ifs/lsd.jxe"; truncate -s $BADSIZE "$W/unit/ifs/lsd.jxe"
    run install map-clean; rc_is 1; expect_out "NOT_${PMCP_PROFILE}_LSD_JXE_SIZE_$BADSIZE" "size gate"

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
        if [ "$(basename "$m")" = reinstall.sh ]; then
            grep -q '^PLAN=`/bin/ksh $PMCP reinstall-plan map-square-fps40 2>&1`$' "$m" && grep -q '^OUT=`/bin/ksh $PMCP restore 2>&1`$' "$m" \
                && grep -q '^PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh$' "$m" && ok "button 10: plan (read-only), restore, then the plan" || bad "reinstall button"
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
            verify|status|restore|confirm|retry|aa-install|cp-log-save|log-clear|"map-install map-square-fps40"|java-retry|java-confirm|java-update|aa-remove|aa-on|aa-confirm|aa-retry|aa-status|aa-log-save|rg-system-on|rg-system-off|rg-update|speedlimit-status|"speedlimit-mode turnto"|"speedlimit-mode street"|"speedlimit-mode off"|"install "*|"switch "*|"java-on "*|"java-off "*) ;;
            "aa-output direct"|"aa-output ring") ;;
            "aa-capture 60"|"aa-capture off"|"aa-regrant on"|"aa-regrant off"|"aa-keepalive on"|"aa-keepalive off"|"bridge pmcp-most"|"bridge mathsls"|bridge-status|"most-sup pmcp"|"most-sup mathsls"|dm-diag|"dm-path pmcp"|"dm-path factory"|"dm-link drop"|"dm-link make")
                case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) ;; *) bad "experimental button on a release card: $args" ;; esac ;;
            *) bad "unexpected button command in $(basename "$m"): $args" ;;
        esac
        set -- $args
        case "$1" in
            install|switch) grep -q "^CORE_$2 " <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") || bad "variant $2 of $(basename "$m") not in manifest" ;;
            # a package the profile does not have yet keeps its button (it answers "not yet supported")
            java-on|java-off) case " $UNSUP_PKGS " in *" $2 "*) ;; *)
                grep -q "^JAR_$2 " <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") || bad "package $2 of $(basename "$m") not in manifest" ;; esac ;;
        esac
    done
    # build-time template blocks (NOAA / UNSUP) are fully resolved: no marker or placeholder left in pmcp.sh
    ! grep -q '#@@\|UNSUP_PKGS\|NOT_YET_SUPPORTED' "$SDB/pmcp/pmcp.sh" || [ -n "$UNSUP_PKGS" ] && ok "pmcp.sh: no template block marker left" || bad "pmcp.sh: template block marker or unsupported-package text in a full-set profile"
    # strict parse, as the unit's ksh reads it: bash 3.2 --posix fails where the unit does (an apostrophe in
    # "${x:-word}" opens a quote there; ksh93 and mksh accept it). Card 5606b961: every button died at pmcp.sh[1844].
    if [ -x /bin/bash ]; then
        _sp=0; for m in "$SDB"/pmcp/pmcp.sh "$SDB"/pmcp/bin/*.sh "$SDB"/pmcp/menu/*.sh; do
            [ -f "$m" ] || continue
            /bin/bash --posix -n "$m" 2>/dev/null || { bad "strict parse (unit ksh): $(basename "$m")"; _sp=1; }
        done
        [ $_sp = 0 ] && ok "strict parse (bash --posix, as the unit's ksh): pmcp.sh, bin, menu"
    fi
    nmenu=$(ls "$SDB"/pmcp/menu/*.sh | wc -l | tr -d ' ')
    nref=$(grep -c '/net/mmx/fs/sda0/pmcp/menu/' "$SDB/esd/Launcher-sda0.esd")
    [ "$nmenu" -gt 20 ] && [ "$nmenu" = "$nref" ] && ok "menu scripts: $nmenu, menu entries: $nref" || bad "menu scripts $nmenu vs entries $nref"
    grep -q "map-install map-square-fps40$" "$SDB/pmcp/menu/map-install.sh" && grep -q '"2. Install CarPlay: the map on the AID (also repairs or updates it)"' "$SDB/esd/Launcher-sda0.esd" \
        && ok "main install button 2 is map-square-fps40" || bad "main install button"
    [ ! -e "$SDB/pmcp/menu/install-map-square-fps40.sh" ] && ok "no second install button for the main layout" || bad "install-map-square-fps40 button left"
    main=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,/^screen pmcp_advanced/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    [ "$main" = "menu/verify.sh menu/map-install.sh menu/aa-install.sh menu/features-on.sh menu/confirm.sh menu/retry.sh menu/status.sh menu/restore.sh menu/log-clear.sh menu/reinstall.sh " ] \
        && ok "main screen: 1 check, 2 CarPlay, 3 Android Auto, 4 features, 5 confirm, 6 try again, 7 status, 8 remove, 9 delete saved logs, 10 reinstall" || bad "main screen: $main"
    labels=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,/^screen pmcp_advanced/p' | awk '/^script/{s=1;next} s&&/^    label/{print substr($0,14,1);s=0}' | tr -d '\n')
    [ "$labels" = 1234567891 ] && ok "main screen buttons numbered 1-10" || bad "main numbering: $labels"
    scr=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_stream_map_aid/,$p' | grep '^screen' | tr '\n' '|')
    _xs=""; case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) _xs="screen experimental pmcp_advanced|" ;; esac
    [ "$scr" = "screen pmcp_stream_map_aid =>M.I.B.<=|screen pmcp_advanced pmcp_stream_map_aid|screen diagnostics pmcp_advanced|screen features pmcp_advanced|screen aa_advanced pmcp_advanced|$_xs" ] \
        && ok "screens: pmcp_stream_map_aid > pmcp_advanced > diagnostics / features / aa_advanced${_xs:+ / experimental} (no map layout screen)" || bad "screens: $scr"
    adv=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen pmcp_advanced/,/^screen diagnostics/p' | sed -n 's/^    label   "\([0-9]\)\. \([a-z_]*\):.*/\1 \2/p' | tr '\n' '|')
    case "$adv" in "1 diagnostics|2 features|3 aa_advanced|"|"1 diagnostics|2 features|3 aa_advanced|4 experimental|") ok "pmcp_advanced: one line per screen, in screen order" ;; *) bad "pmcp_advanced lines: $adv" ;; esac
    feat=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen diagnostics/,/^screen features/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    case "$feat" in "menu/diag.sh menu/timeline.sh menu/rglast.sh menu/navdiag.sh menu/cp-log-save.sh "*) ok "diagnostics: diagnostics and the CarPlay log first" ;; *) bad "diagnostics: $feat" ;; esac
    case "$feat" in *java-*|*rg-system*|*rg-update*) bad "diagnostics still has on/off or update buttons: $feat" ;; *) ok "diagnostics: no on/off, no update buttons" ;; esac
    onoff=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen features/,/^screen aa_advanced/p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    # experimental cards: the WL package wl after ui (A220)
    _wl=""; [ -n "$(jsha wl)" ] && _wl="menu/java-on-wl.sh "; _wlo=""; [ -n "$_wl" ] && _wlo="menu/java-off-wl.sh "
    case "$onoff" in "menu/rg-system-on.sh menu/rg-system-off.sh menu/java-on-nai.sh "*"menu/java-on-sl.sh menu/java-on-ui.sh ${_wl}menu/java-off-nai.sh "*"menu/java-off-sl.sh menu/java-off-ui.sh ${_wlo}"|"menu/java-on-nai.sh "*"menu/java-off-ui.sh ${_wlo}") ok "features: RG system on/off, then every package on, then off (ui${_wl:+, then wl} last)" ;; *) bad "features: $onoff" ;; esac
    for _m in rg-update java-update; do
        [ ! -e "$SDB/pmcp/menu/$_m.sh" ] && ! grep -q "menu/$_m.sh" "$SDB/esd/Launcher-sda0.esd" && ok "no GEM button $_m (main 4 and 10 do it)" || bad "GEM button $_m still there"
    done
    ! grep -q '"0\. \|below 9\|Android Auto 0\.1\|map layouts' "$SDB/esd/Launcher-sda0.esd" && ok "menu texts: no 0., below 9, AA 0.1, map layouts" || bad "outdated menu text left"
    for _m in speedlimit-on speedlimit-cpi speedlimit-off; do
        [ ! -e "$SDB/pmcp/menu/$_m.sh" ] && ! grep -q "menu/$_m.sh" "$SDB/esd/Launcher-sda0.esd" && ok "no GEM button $_m (mode set on the page)" \
            || bad "GEM speed-limit mode button $_m still there"
    done
    ls "$SDB"/pmcp/menu/install-*.sh "$SDB"/pmcp/menu/switch-*.sh > /dev/null 2>&1 && bad "map layout buttons left" || ok "no map layout buttons (layouts stay on the card for 2 and 10)"
    ORIG="$REPO/archives/mib-3.6.0/Launcher-sda0.esd"
    head -c "$(stat -f %z "$ORIG")" "$SDB/esd/Launcher-sda0.esd" | cmp -s - "$ORIG" && ok "M.I.B. menu content unchanged (only appended)" || bad "M.I.B. menu prefix changed"
    for ref in $(grep -o '/net/mmx/fs/sda0/pmcp/menu/[a-z0-9-]*\.sh' "$SDB/esd/Launcher-sda0.esd"); do
        [ -f "$SDB/pmcp/menu/${ref##*/}" ] || bad "menu points to missing ${ref##*/}"
    done
    v=$(sed -n 's/^PMCP_VERSION="\(.*\)"$/\1/p' "$SDB/pmcp/pmcp.sh")
    case "$v" in pmcp-0.8.0-$VTAG-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ok "version carries a build id: $v" ;;
        pmcp-0.8.0-exp-$VTAG-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ok "experimental version carries a build id: $v" ;;
        *) bad "version $v" ;; esac
    aa=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen aa_advanced/,$p' | sed '/^screen experimental/,$d' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
    case "$v" in
    *-exp-*)
        [ "$aa" = "menu/aa-confirm.sh menu/aa-output-direct.sh menu/aa-output-ring.sh menu/aa-retry.sh menu/aa-status.sh menu/aa-log-save.sh menu/aa-remove.sh " ] \
            && ok "aa_advanced (experimental card): the release entries only" || bad "aa_advanced: $aa"
        # A199 (user 2026-11-15): the MOST bridge serves CarPlay, AA and wireless, so its buttons and the AA record live on
        # their own screen experimental
        _br=""; [ -e "$SDB/pmcp/payload/pmcp-most/altscreen-most-bridge" ] && _br="menu/bridge-pmcp-most.sh menu/bridge-mathsls.sh menu/bridge-status.sh menu/most-sup-pmcp.sh menu/most-sup-mathsls.sh "
        xp=$(tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen experimental/,$p' | grep -o 'menu/[a-z0-9-]*\.sh' | tr '\n' ' ')
        [ "$xp" = "${_br}menu/dm-diag.sh menu/dm-path-pmcp.sh menu/dm-path-factory.sh menu/dm-link-drop.sh menu/dm-link-make.sh menu/aa-capture-60.sh menu/aa-capture-off.sh menu/aa-regrant-on.sh menu/aa-regrant-off.sh menu/aa-keepalive-on.sh menu/aa-keepalive-off.sh " ] \
            && ok "experimental:${_br:+ MOST bridge switch and status,} VW encoder path/link/diag, AA record on/off, AA cluster re-grant on/off" || bad "experimental: $xp"
        sed '/^screen experimental/,$d' "$SDB/esd/Launcher-sda0.esd" | grep -q 'menu/bridge-\|menu/aa-capture-\|menu/aa-regrant-\|menu/aa-keepalive-\|rg-aa' && bad "experimental buttons outside the experimental screen" || ok "experimental buttons only on the experimental screen"
        grep -qi 'rg-aa' <(sed -n '/^screen pmcp_stream_map_aid/,$p' "$SDB/esd/Launcher-sda0.esd") && bad "menu still says rg-aa" || ok "menu: no rg-aa" ;;
    *)
        [ "$aa" = "menu/aa-confirm.sh menu/aa-output-direct.sh menu/aa-output-ring.sh menu/aa-retry.sh menu/aa-status.sh menu/aa-log-save.sh menu/aa-remove.sh " ] \
            && ok "aa_advanced (release card): confirm, output direct/bridge, retry, status, log save, remove (delete logs: main menu 9); no AA install there" || bad "aa_advanced: $aa"
        grep -qi 'experimental\|rg-aa' <(sed -n '/^screen pmcp_stream_map_aid/,$p' "$SDB/esd/Launcher-sda0.esd") && bad "menu still says experimental or rg-aa" || ok "menu: no 'experimental', no rg-aa"
        grep -q '^AAX_' <(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh") && bad "release card carries AAX_ keys" || ok "release card: no experimental AA set" ;;
    esac
    grep -q 'pmcp_CarPlay_AID\|pmcp_android_auto\|pmcp_packages\|pmcp_other_layouts\|pmcp_switch_layout\|features_advanced\|rg_features' "$SDB/esd/Launcher-sda0.esd" && bad "old screen names left" || ok "no old screen names"
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
    # update mode runs the rescue and log card scripts on RCC, which has no sync (car 2026-11-16): every flush goes through
    # flush(), which runs sync on MMX first (on -f mmx); the host runs below only reach its local fallback
    _us=0
    for _uf in "$PROJ/installer/rescue/pmcp-rescue.sh" "$PROJ/installer/logcard/pmcp-logs.sh"; do
        grep -q '^    if \[ -z "${PMCP_[A-Z]*_TEST_ROOT:-}" \]; then on -f mmx sync >/dev/null 2>&1 && return 0; fi$' "$_uf" || { bad "flush() without on -f mmx sync: $(basename "$_uf")"; _us=1; }
        _ub=$(grep -n 'sync' "$_uf" | grep -v '^[0-9]*: *#' | grep -v 'on -f mmx sync >/dev/null 2>&1 && return 0' \
            | grep -v '^[0-9]*:    sync >/dev/null 2>&1$' | grep -v 'for t in .* sync ')
        [ -z "$_ub" ] || { bad "bare sync in $(basename "$_uf"): $_ub"; _us=1; }
    done
    [ $_us = 0 ] && ok "update-mode scripts (rescue, log card): sync only through flush(), on MMX first (RCC has no sync)"
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

    # experimental dm-path pmcp (A218): displaymanager.json on our link; the rescue card puts the factory file back by size
    fresh_unit; run install map-clean; rc_is 0; run java-on nai; rc_is 0
    DMJR="$W/unit/mnt/system/etc/eso/production/displaymanager.json"; DMJS=$(h "$DMJR")
    cp "$DMJR" "$U/carplaymaps/rollback/displaymanager.json"
    sed 's#"device" : "/dev/mlb/isoTX2",#"device" : "/dev/pmcp-isoTX2",#' "$DMJR" > "$W/dmj"; cat "$W/dmj" > "$DMJR"
    rescue
    [ "$(h "$DMJR")" = "$DMJS" ] && ok "dm-path pmcp: factory displaymanager.json back" || bad "displaymanager.json not restored"
    grep -q "RESULT=OK" "$W/med/PMCP_RESCUE_LOG.txt" && ok "RESULT=OK" || bad "no RESULT=OK after the json"
    fresh_unit; run install map-clean; rc_is 0; run java-on nai; rc_is 0
    sed 's#"device" : "/dev/mlb/isoTX2",#"device" : "/dev/pmcp-isoTX2",#' "$DMJR" > "$W/dmj"; cat "$W/dmj" > "$DMJR"
    rescue
    grep -q "RESULT=UNSURE" "$W/med/PMCP_RESCUE_LOG.txt" && ok "our json without the factory copy: RESULT=UNSURE" || bad "json without copy reported OK"

    echo "[17] main screen 4: install additional features (the real menu script, one set, one trial)"
    # feat: main menu 4 (the real menu script); allon: what the old button 3 did, now 2 then 4 (map, then features)
    feat() {
        sed -e "s#/bin/ksh \$PMCP#$SH $W/sd/pmcp.sh#" "$W/sd/menu/features-on.sh" > "$W/features-on.sh"
        PMCP_TEST_ROOT="$W/unit" $SH "$W/features-on.sh" > "$W/out" 2>&1; echo $? > "$W/rc"; noexec "4 (features-on.sh)"
    }
    allon() {
        PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" map-install map-square-fps40 > "$W/out2" 2>&1; _rc2=$?
        grep "cannot execute" "$W/out2" | sed "s/^/map-install: /" >> "$W/noexec"
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
    o=$(unit_boot); case "$o" in "boot=trial set=$ALL jars="*"$RGF"*"$DNF:/X/lsd/jars/$UIF") ok "next start: one trial with all JARs" ;; *) bad "boot: $o" ;; esac
    run java-confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK set=$ALL" "one confirm for everything"
    allon; expect_out "everything was already on, nothing changed" "second press: nothing to do"
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "remove everything: factory state"
    [ "$(h "$W/unit/mnt/system/etc/mm/iap2.cfg")" = 1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37 ] && ok "factory iap2.cfg back" || bad "cfg after restore"

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

    echo "[19] earlier versions of this card's packages and AA set (made from this card, A188: recognised by name, no list)"
    U="$W/unit/mnt/app"; P="$W/unit/mnt/persist/pmcp"
    start_unit
    run map-install map-square-fps40; rc_is 0; run rg-system-on; rc_is 0
    for p in nai np rg sl ui; do run java-on $p; rc_is 0; done
    new_start; unit_boot > /dev/null; run java-confirm; rc_is 0; run speedlimit-mode turnto; rc_is 0
    # an earlier np (other content, other file name), a renamed rg (rgluasfm) and ui under an earlier card's file name
    old_java np; old_java rg rgluasfm; old_java ui ui pmcp-ui2.jar same
    run status; expect_out "Unit state: JAVA" "earlier versions: JAVA"
    expect_out "packages of an earlier card: np rgluasfm ui" "np, renamed rg and ui under an old name reported as earlier"
    o=$(unit_boot); case "$o" in "boot=yes "*pmcp-np-old.jar*pmcp-rgluasfm-old.jar*pmcp-ui2.jar) ok "the earlier confirmed set still loads" ;; *) bad "boot: $o" ;; esac
    # interrupted before the HMI_BOOT switch (a new JAR already there): the old confirmed set loads, java-update finishes
    cp "$W/sd/payload/jars/$NPF" "$U/eso/hmi/lsd/jars/$NPF"
    run status; expect_out "Unit state: JAVA" "new JAR before the switch: JAVA"; expect_out "packages of an earlier card: np" "old np still reported"
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK set=$NAI+$NP+$RG+$(jid sl)+$UI" "java-update: this card's np, rg and ui"
    jar_replaced pmcp-np-old.jar "$NPF" np "old np gone, this card's np in place"
    jar_replaced pmcp-rgluasfm-old.jar "$RGF" rg "rgluasfm -> rg"
    jar_replaced pmcp-ui2.jar "$UIF" ui "ui under its old file name -> this card's name"
    [ "$(cat "$P/native-speedlimit-mode" 2>/dev/null)" = turnto ] && ok "speed-limit mode kept" || bad "speed-limit mode lost"
    o=$(unit_boot); case "$o" in "boot=trial "*"$NPF"*"$RGF"*"$SLF"*"$UIF") ok "java-update: one trial start" ;; *) bad "boot: $o" ;; esac
    run java-update; rc_is 1; expect_out "JAVA_UPDATE_ALREADY_CURRENT" "second java-update: already current"
    # interrupted after the HMI_BOOT switch (old JAR still there): JAVA, trial confirmable, java-update removes the JAR
    echo "old" > "$U/eso/hmi/lsd/jars/pmcp-rg.jar"
    run status; expect_out "Unit state: JAVA" "unused old JAR: still JAVA"; expect_out "unused JAR files (not loaded): pmcp-rg.jar" "unused JAR reported"
    case " $(cat "$U/carplaymaps/HMI_BOOT") " in *" pmcp-rg.jar "*) bad "unused JAR in HMI_BOOT" ;; *) ok "unused JAR not in the boot list" ;; esac
    run java-confirm; rc_is 0; expect_out "PMCP_JAVA_CONFIRM_OK" "trial set confirmable with an unused JAR"
    run java-update; rc_is 0; expect_out "unused JARs of an interrupted update removed" "java-update removes the unused JAR"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-rg.jar" ] && ok "unused JAR gone" || bad "unused JAR left"
    run rg-system-off; rc_is 1; expect_out "TURN_OFF_JAVA_PACKAGE_RG_FIRST" "RG system stays while rg is on"
    # button 4 does the same: earlier np -> java-update in place (no reset), sl and its mode stay
    old_java np
    feat; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "4 runs java-update"; expect_out "PMCP_FEATURES_ON_OK" "4 done"
    grep -q "PMCP_FEATURES_RESET_OK" "$W/out" && bad "4 reset the Java set (sl would be lost)" || ok "4 did not reset the Java set"
    jar_replaced pmcp-np-old.jar "$NPF" np "4: old np gone, this card's np in place"
    [ "$(cat "$P/native-speedlimit-mode" 2>/dev/null)" = turnto ] && ok "4: speed-limit mode kept" || bad "4: speed-limit mode lost"
    restore_exact "restore after earlier versions: exact factory tree"
    # not an earlier version of ours: the set is mixed (PARTIAL) and 4 resets it with the verified factory files
    for bad_case in samename otherfile unknownpkg foreignfile damaged; do
        fresh_unit; run map-install map-square-fps40; rc_is 0; run java-on nai; rc_is 0; run java-on np; rc_is 0; confirm_now
        case $bad_case in
            samename) old_java np np "$NPF" ;;                       # other content under this card's file name: no safe swap
            otherfile) old_java np np "$ZOOMF" ;;                     # under another package's file name of this card
            unknownpkg) old_java np kf ;;                            # a name this card does not know
            foreignfile) old_java np np NowPlaying.jar ;;            # a JAR outside our name space
            damaged) printf x >> "$U/eso/hmi/lsd/jars/$NPF" ;;       # this card's np, damaged
        esac
        run status; expect_out "Unit state: PARTIAL" "$bad_case: PARTIAL"
        run java-update; rc_is 1
        feat; rc_is 0; expect_out "PMCP_FEATURES_RESET_OK" "$bad_case: 4 resets the Java part"; expect_out "PMCP_FEATURES_ON_OK" "$bad_case: 4 installs this card's set"
        case $bad_case in foreignfile) [ -e "$U/eso/hmi/lsd/jars/NowPlaying.jar" ] && ok "$bad_case: a JAR outside our name space is left alone" || bad "$bad_case: foreign JAR removed" ;; esac
        rm -f "$U/eso/hmi/lsd/jars/NowPlaying.jar"
        run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "$bad_case: restore exact" || bad "$bad_case: tree after restore"
    done
    # a stray pmcp-*.jar without carplaymaps (the factory lsd.sh never loads it) does not block a factory unit
    fresh_unit; echo stray > "$U/eso/hmi/lsd/jars/pmcp-stray.jar"
    run verify; rc_is 0; expect_out "PMCP_VERIFY_OK state=STOCK" "stray pmcp-*.jar without carplaymaps: still STOCK"
    run install map-clean; rc_is 0; expect_out "PMCP_INSTALL_OK" "install works next to it"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-stray.jar" ] && ok "install removes the leftover JAR of ours" || bad "stray JAR left by install"
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "restore: factory again"
    for gone in rglu rgluasfm rgl dn2 kf kf4; do
        run install map-clean > /dev/null; run java-on $gone; rc_is 1; expect_out "UNKNOWN_JAVA_PACKAGE_$gone" "$gone is not a package of this card"
        run restore > /dev/null
    done
    # Android Auto: aa-remove refuses without a verified factory gal copy and changes nothing; it cleans gal.pmcp-restore
    fresh_unit; run map-install map-clean; rc_is 0; run aa-install; rc_is 0
    cp "$U/carplaymaps/aa/gal.real" "$W/galreal"; printf x >> "$U/carplaymaps/aa/gal.real"; tampered=$(snapshot "$W/unit")
    run status; expect_out "Unit state: PARTIAL" "tampered factory gal copy: PARTIAL"
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_FACTORY_GAL_COPY_NOT_VERIFIED" "aa-remove: factory gal copy must verify"
    run restore; rc_is 1; [ "$tampered" = "$(snapshot "$W/unit")" ] && ok "bad gal copy: aa-remove and restore change nothing" || bad "changed with a bad gal copy"
    cp "$W/galreal" "$U/carplaymaps/aa/gal.real"
    run aa-remove; rc_is 0; expect_out "PMCP_AA_REMOVE_OK" "aa-remove ok"
    [ "$(h "$U/eso/bin/apps/gal")" = $STOCK_GAL ] && [ ! -e "$U/carplaymaps/aa" ] \
        && ! ls "$P" | grep -q "^aa-" && ok "factory gal back, AA files and markers gone" || bad "after aa-remove"
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_ALREADY_NOT_INSTALLED" "second aa-remove: nothing to do"
    cp "$U/eso/bin/apps/gal" "$U/eso/bin/apps/gal.pmcp-restore"
    run status; expect_out "Unit state: PARTIAL" "leftover gal.pmcp-restore of an interrupted AA off: PARTIAL"
    run aa-remove; rc_is 0; [ ! -e "$U/eso/bin/apps/gal.pmcp-restore" ] && ok "aa-remove cleans gal.pmcp-restore" || bad "gal.pmcp-restore left"
    # AA on a carplaymaps that is not a pmcp install (factory lsd.sh copy broken): aa-remove/restore write nothing
    run aa-install; rc_is 0; printf x >> "$U/carplaymaps/rollback/lsd.sh"; broken=$(snapshot "$W/unit")
    run aa-remove; rc_is 1; expect_out "AA_REMOVE_NOT_A_PMCP_INSTALL" "aa-remove refuses a non-pmcp carplaymaps"
    run restore; rc_is 1; [ "$broken" = "$(snapshot "$W/unit")" ] && ok "nothing written on a non-pmcp carplaymaps" || bad "wrote on a non-pmcp carplaymaps"
    fresh_unit

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
    truncate -s $JXE_SIZE "$W/unit/ifs/lsd.jxe"
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
    [ ! -e "$SLM" ] && [ ! -e "$U/eso/hmi/lsd/jars/$SLF" ] && ok "reader removal clears configuration and jar" || bad "reader removal left state"
    run speedlimit-mode off; rc_is 0
    run java-on sl; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    run speedlimit-mode turnto; rc_is 0
    o=$(unit_boot); case "$o" in "boot=yes "*"$RGF"*"$SLF") ok "rg and sl load together" ;; *) bad "boot: $o" ;; esac
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
    LOCKPKG=np; [ $HAS_NP = yes ] || LOCKPKG=dn
    run java-on $LOCKPKG; rc_is 1; expect_out "SPEEDLIMIT_LOCK_BUSY" "package change waits for the lock"
    run restore; rc_is 0; expect_out "PMCP_RESTORE_OK" "restore runs past a stale lock"
    [ ! -e "$SLP" ] && ok "full restore clears the mode" || bad "full restore left the mode"
    rm -rf "$SLL"

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
    case "$(cat "$AAD/AA_BOOT")" in gamma-c92a4c3e-*-716516eb) ok "set id gamma-hook-feeder-conf" ;; *) bad "AA_BOOT $(cat "$AAD/AA_BOOT")" ;; esac
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
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$NAI+$RG" ] && [ "$(h "$U/eso/hmi/lsd/jars/$RGF")" = "$(jsha rg)" ] \
        && ok "AA on + rg: set nai rg, its JAR" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
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
    # earlier AA sets (A188: any version of ours, no list): our wrapper, the verified factory gal copy and a well-formed
    # AA_BOOT = old, whatever the four set files hold; aa-on brings them up to date. A malformed AA_BOOT = PARTIAL.
    run aa-on; rc_is 0
    printf x >> "$AAD/libgal_hook.so"; printf '# older\n' >> "$AAD/feeder.conf"; echo "gamma-0a1b2c3d-5d2a0a02-716516eb" > "$AAD/AA_BOOT"
    run status; expect_out "Unit state: JAVA" "an earlier AA set: not PARTIAL"; expect_out "Android Auto: old mode=gamma" "status: old gamma"
    run aa-status; expect_out "Android Auto on brings them up to date" "aa-status says what to do"
    run aa-confirm; rc_is 1; expect_out "AA_CONFIRM_NEEDS_AA_ON_old" "no confirm on an earlier AA set"
    run aa-on; rc_is 0; [ "$(h "$AAD/libgal_hook.so")" = "$(msha AA_HOOK)" ] && [ "$(h "$AAD/feeder.conf")" = "$(msha AA_MODE)" ] \
        && ok "earlier set -> this card's hook and feeder settings" || bad "earlier AA set not updated"
    # this card's set id with other feeder settings (as card 030b7df2 had): old, aa-on replaces them (a new trial)
    printf '# other\n' >> "$AAD/feeder.conf"
    run status; expect_out "Android Auto: old mode=gamma" "this card's set id, other feeder settings: old"
    run aa-on; rc_is 0; [ "$(h "$AAD/feeder.conf")" = "$(msha AA_MODE)" ] && ok "feeder settings replaced" || bad "feeder.conf not replaced"
    # an earlier card's other mode (AA 3, sync17)
    printf x >> "$AAD/libgal_hook.so"; echo "sync17-dd72104b-27b32b35-99288ee3" > "$AAD/AA_BOOT"
    run status; expect_out "Android Auto: old mode=sync17" "earlier card's AA 3 (1.7): old"
    run aa-on; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma" "AA 3 (1.7) -> gamma"
    grep -q '^GAL_PMCP_RG=1$' "$AAD/gal-hook.conf" && [ "$(h "$AAD/libgal_hook.so")" = "$(msha AA_HOOK)" ] && ok "gamma hook and settings" || bad "after sync17 -> gamma"
    # a malformed AA_BOOT is not updated in place: PARTIAL, aa-on refused, 3 removes the set first
    echo "gamma-x" > "$AAD/AA_BOOT"
    run status; expect_out "Unit state: PARTIAL" "malformed AA_BOOT: PARTIAL"
    run aa-on; rc_is 1; expect_out "AA_NEEDS_STAGE_A_STATE_PARTIAL" "malformed AA_BOOT: aa-on refused"
    run aa-install; rc_is 0; expect_out "removing them first" "3 removes it first"; expect_out "PMCP_AA_ON_OK mode=gamma" "3 installs this card's set"
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
    tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" | head -1 | grep -q "^RESULT=OK copied=5 aa_logs=5 cp_logs=0 dm_diag=0$" && ok "log card: RESULT=OK" || bad "log card result: $(tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt")"
    : > "$U/carplaymaps/logs/._aa-log-1.txt"; mkdir -p "$U/carplaymaps/logs/odd"; : > "$U/carplaymaps/logs/odd/x"
    mkdir -p "$P"; : > "$U/carplaymaps/logs/aa-log-9.txt.pmcp-new"; echo "boot set=x" >> "$P/boot.log"; echo "boot set=old" > "$P/boot.log.1"
    : > "$P/aa-stream.h264"; : > "$P/aa-stream.h264.idx"; : > "$P/wifi-test.log"; : > "$P/wifi-test.log.1"
    axnew=""; [ -e "$P/aa-extra.conf" ] || { axnew=1; echo "PMCP_AA_OUTPUT=direct" > "$P/aa-extra.conf"; }
    : > "$P/aa-extra.conf.pmcp-new"; ax=$(h "$P/aa-extra.conf")
    run log-clear; rc_is 0; [ ! -e "$U/carplaymaps/logs" ] && ok "logs deleted (also unknown files and a subdirectory)" || bad "logs left"
    [ ! -e "$P/boot.log" ] && [ ! -e "$P/boot.log.1" ] && [ ! -e "$P/aa-stream.h264" ] && [ ! -e "$P/aa-stream.h264.idx" ] && [ ! -e "$P/wifi-test.log" ] && [ ! -e "$P/wifi-test.log.1" ] && ok "boot log, phone video and Wi-Fi test log deleted" || bad "left: $(ls "$P")"
    [ ! -e "$P/aa-extra.conf.pmcp-new" ] && [ "$(h "$P/aa-extra.conf")" = "$ax" ] && ok "log-clear: half-written AA switch file deleted, the chosen AA output kept" || bad "aa-extra.conf after log-clear"
    [ -n "$axnew" ] && rm -f "$P/aa-extra.conf"
    run aa-log-clear; rc_is 0; expect_out "PMCP_LOG_CLEAR_OK (nothing saved, nothing to delete)" "second press (older name aa-log-clear): OK, nothing to delete"
    mv "$U/carplaymaps/PMCP_VERSION" "$W/pv.keep"; mkdir -p "$U/carplaymaps/logs"; echo other > "$U/carplaymaps/logs/other-mod.log"
    run log-clear; rc_is 1; expect_out "LOG_CLEAR_CARPLAYMAPS_IS_NOT_A_PMCP_INSTALL_NOTHING_CHANGED" "carplaymaps not ours: refused"
    [ -e "$U/carplaymaps/logs/other-mod.log" ] && ok "another mod's logs/ left alone" || bad "another mod's logs deleted"
    rm -rf "$U/carplaymaps/logs"; mv "$W/pv.keep" "$U/carplaymaps/PMCP_VERSION"
    # A152: the GEM button log on the unit ($PERSIST/gem.log; the SD card is read-only in GEM)
    rung() { PMCP_TEST_GEMLOG= PMCP_TEST_ROOT="$W/unit" $SH "$W/sd/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; noexec "$*"; }
    mkdir -p "$P"; rm -f "$P"/gem.log*; rung aa-status; rc_is 0
    head -1 "$P/gem.log" | grep -q "^=== .* aa-status " && grep -q "^Unit state: VIDEO$" "$P/gem.log" && ok "gem.log: header and the button's output" || bad "gem.log: $(head -3 "$P/gem.log")"
    rm -f "$RD/pmcp-gal-hook.log"; rung aa-log-save; rc_is 1; grep -q "^PMCP_FAIL=AA_LOG_EMPTY" "$P/gem.log" && ok "gem.log: a FAIL is logged" || bad "gem.log without the FAIL"
    i=0; while [ $i -lt 120 ]; do rung aa-status; i=$((i + 1)); done
    s0=$(ls -ln "$P/gem.log" | awk '{print $5}'); s1=$(ls -ln "$P/gem.log.1" 2>/dev/null | awk '{print $5}')
    [ -n "$s1" ] && [ "$s0" -le 40000 ] && [ "$s1" -le 40000 ] && ok "gem.log bounded: $s0 + $s1 B" || bad "gem.log sizes $s0 / $s1"
    rung log-clear; rc_is 0; [ ! -e "$P/gem.log.1" ] && [ "$(grep -c '^===' "$P/gem.log")" = 1 ] && grep -q "log-clear" "$P/gem.log" \
        && ok "log-clear: gem.log starts again with this press" || bad "gem.log after clear: $(head -2 "$P/gem.log")"
    # boot.log (lsd.sh appends a line each start, never trimmed there): every button bounds it at ~2 x 16 KB
    _i=0; while [ $_i -lt 300 ]; do echo "boot set=nai-12345678+np-12345678 use=yes jars=/mnt/app/carplaymaps/lsd/jars/pmcp-nai.jar:x"; _i=$((_i+1)); done > "$P/boot.log"
    echo "boot set=newest" >> "$P/boot.log"; rm -f "$P/boot.log.1"; rung aa-status; rc_is 0
    [ ! -e "$P/boot.log" ] && tail -1 "$P/boot.log.1" | grep -q "^boot set=newest$" && ok "boot.log over 16 KB moved to boot.log.1" || bad "boot.log rotation: $(ls -ln "$P" | grep boot)"
    echo "boot set=after" > "$P/boot.log"; rung aa-status; rc_is 0; [ -s "$P/boot.log" ] && [ -s "$P/boot.log.1" ] && ok "small boot.log kept" || bad "small boot.log moved"
    echo "older" > "$P/gem.log.1"; rm -rf "$W/med3"; logcard
    cmp -s "$P/boot.log.1" "$W/med3/PMCP_LOGS/pmcp-boot-log-1.txt" && cmp -s "$P/boot.log" "$W/med3/PMCP_LOGS/pmcp-boot-log.txt" \
        && ok "log card: boot.log and boot.log.1 copied" || bad "log card boot.log: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    cmp -s "$P/gem.log" "$W/med3/PMCP_LOGS/pmcp-gem-log.txt" && cmp -s "$P/gem.log.1" "$W/med3/PMCP_LOGS/pmcp-gem-log-1.txt" \
        && ok "log card: gem.log and gem.log.1 copied" || bad "log card gem.log: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    echo "=== wifi-test run 2" > "$P/wifi-test.log"; echo "=== wifi-test run 1" > "$P/wifi-test.log.1"; rm -rf "$W/med3"; logcard
    cmp -s "$P/wifi-test.log" "$W/med3/PMCP_LOGS/pmcp-wifi-test.txt" && cmp -s "$P/wifi-test.log.1" "$W/med3/PMCP_LOGS/pmcp-wifi-test.1.txt" \
        && ok "log card: wifi-test.log and wifi-test.log.1 copied" || bad "log card wifi-test: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    rm -f "$P"/wifi-test.log*
    rm -rf "$W/u2"; mkdir -p "$W/u2"; PMCP_TEST_GEMLOG= PMCP_TEST_ROOT="$W/u2" $SH "$W/sd/pmcp.sh" status > /dev/null 2>&1
    [ ! -e "$W/u2/mnt/persist/pmcp" ] && ok "gem.log: no persist dir made on an untouched unit" || bad "persist made by status"
    rm -rf "$W/u2"; rm -f "$P"/gem.log* "$P"/boot.log*
    rm -rf "$W/med3"; logcard
    grep -q "^RESULT=NO_LOGS" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card without logs: RESULT=NO_LOGS" || bad "empty log card result"
    navlog 1 1; run aa-log-save; rc_is 0
    run aa-remove; rc_is 0; run status; expect_out "Unit state: VIDEO" "saved logs left by aa-remove do not matter"
    run restore; rc_is 0; run verify; expect_out "PMCP_VERIFY_OK state=STOCK" "restore with saved logs: factory state"
    [ ! -e "$U/carplaymaps" ] && ok "restore removed saved logs with carplaymaps" || bad "carplaymaps left"

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
    # files of ours that are not a set (malformed AA_BOOT; an earlier card's whole set is "old" since A188, [27]):
    # unknown, 3 removes them first, CarPlay stays
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-zz" > "$U/carplaymaps/aa/AA_BOOT"
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

    echo "[36] CarPlay log (diagnostics): saved for the log card (with the last bridge log), deleted with the AA logs"
    fresh_unit; factory=$(snapshot "$W/unit")
    run cp-log-save; rc_is 1; expect_out "CP_LOG_NEEDS_PMCP_STATE_STOCK" "factory unit: no log"
    run map-install map-square-fps40; new_start
    before=$(snapshot "$W/unit" | grep -v /logs/)
    run cp-log-save; rc_is 0; expect_out "PMCP_CP_LOG_SAVED file=logs/cp-log-1.txt" "log saved"; expect_out "supervisor_log=no" "no supervisor log yet"
    echo "supervisor line 1" > "$W/unit/ramdisk/carplay-cluster-supervisor.log"
    mkdir -p "$W/unit/ramdisk/carplaymaps-diagnostics"
    { echo "bridge: MOST write failed: Not enough memory"; i=2; while [ $i -le 250 ]; do echo "bridge line $i"; i=$((i+1)); done; } \
        > "$W/unit/ramdisk/carplaymaps-diagnostics/last-bridge.log"
    run cp-log-save; rc_is 0; expect_out "cp-log-2.txt" "second log"; expect_out "supervisor_log=yes" "with the supervisor log"
    L2="$U/carplaymaps/logs/cp-log-2.txt"
    grep -q "^bridge: MOST write failed: Not enough memory$" "$L2" && grep -q "^bridge line 200$" "$L2" && ! grep -q "^bridge line 201$" "$L2" \
        && grep -q "^--- carplaymaps-diagnostics/last-supervisor.log" "$L2" && ok "log content: last bridge log, first 200 lines" || bad "cp log: last-bridge.log"
    grep -q "^supervisor line 1$" "$L2" && grep -q "^--- state: VIDEO" "$L2" && [ "$(tail -1 "$L2")" = "--- end" ] && ok "log content: state, supervisor log, complete" || bad "cp log content"
    ! grep -q "^--- pmcp-kombi-view.log" "$L2" && ok "log content: no AID view section without a view log" || bad "cp log: empty view section"
    echo "kv old 1" > "$W/unit/ramdisk/pmcp-kombi-view.log.1"; echo "kv new 1" > "$W/unit/ramdisk/pmcp-kombi-view.log"
    run cp-log-save; rc_is 0; expect_out "cp-log-3.txt" "third log"
    L3="$U/carplaymaps/logs/cp-log-3.txt"
    sed -n '/^--- pmcp-kombi-view.log.1$/,/^--- end$/p' "$L3" | grep -q '^kv old 1$' && sed -n '/^--- pmcp-kombi-view.log$/,/^--- end$/p' "$L3" | grep -q '^kv new 1$' \
        && ok "log content: the AID view log, older part first" || bad "cp log: AID view log"
    rm -f "$W/unit/ramdisk/pmcp-kombi-view.log.1" "$W/unit/ramdisk/pmcp-kombi-view.log"
    [ "$before" = "$(snapshot "$W/unit" | grep -v /logs/ | grep -v /ramdisk/)" ] && ok "log save wrote only carplaymaps/logs" || bad "cp log save changed other files"
    for n in 4 5; do run cp-log-save; done; run cp-log-save; rc_is 1; expect_out "CP_LOGS_FULL_5" "sixth refused"
    rm -rf "$W/med3"; logcard
    [ "$(ls "$W/med3/PMCP_LOGS" | grep -c '^cp-log-[1-5].txt$')" = 5 ] && cmp -s "$L2" "$W/med3/PMCP_LOGS/cp-log-2.txt" && ok "log card: CarPlay logs copied" || bad "log card: $(ls "$W/med3/PMCP_LOGS" | tr '\n' ' ')"
    grep -q "^RESULT=OK copied=5 aa_logs=0 cp_logs=5 dm_diag=0$" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card: RESULT=OK with cp_logs=5" || bad "log card result"
    run log-clear; rc_is 0; [ ! -e "$U/carplaymaps/logs" ] && ok "main menu 9 removes the CarPlay logs" || bad "cp logs left"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
    echo "[37] main menu 3 and 4 with unsupported Android Auto AND unsupported Java files at once (no dead end)"
    fresh_unit; factory=$(snapshot "$W/unit")
    run map-install map-square-fps40; feat; run aa-install; confirm_now; S=$(cat "$U/carplaymaps/aa/AA_BOOT")
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-zz" > "$U/carplaymaps/aa/AA_BOOT"
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
    printf 'X' >> "$U/carplaymaps/aa/aa-most-feeder"; echo "gamma-zz" > "$U/carplaymaps/aa/AA_BOOT"
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
    grep -q "^RESULT=OK copied=2 aa_logs=1 cp_logs=1 dm_diag=0$" "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt" && ok "log card: one AA and one CarPlay log" || bad "log card: $(tail -2 "$W/med3/PMCP_LOGS/PMCP_LOGS_RESULT.txt")"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

    echo "[40] package ui (AID navigation configuration page, Save of trial starts): own JAR, in main 4, java-off and restore exact, shares the mode file"
    UI=$(jid ui)
    grep -q "java-on_ui" "$SDB/pmcp/menu/features-on.sh" && ok "main 4 installs ui (Save on the page)" || bad "main 4 leaves ui out"
    tr -d '\r' < "$SDB/esd/Launcher-sda0.esd" | sed -n '/^screen features/,/^screen aa_advanced/p' > "$W/feat.esd"
    grep -q '"On ui: AID navigation configuration in App-Connect settings, saves trial starts without the card"' "$W/feat.esd" \
        && grep -q '"Off ui: AID navigation configuration in App-Connect settings, saves trial starts without the card"' "$W/feat.esd" \
        && ok "features: On ui / Off ui" || bad "GEM ui buttons missing in features"
    fresh_unit; factory=$(snapshot "$W/unit")
    run install map-square-fps40; rc_is 0; run java-on nai; rc_is 0; unit_boot > /dev/null; run java-confirm; rc_is 0
    jars_before=$(cd "$U/eso/hmi/lsd/jars" && ls); boot_before=$(cat "$U/carplaymaps/HMI_BOOT")
    run java-on ui; rc_is 0; expect_out "PMCP_JAVA_ON_OK package=ui set=$NAI+$UI" "ui on, set nai+ui"
    [ "$(h "$U/eso/hmi/lsd/jars/$UIF")" = "$(jsha ui)" ] && ok "ui JAR in place" || bad "ui JAR"
    o=$(unit_boot); [ "$o" = "boot=trial set=$NAI+$UI jars=/X/lsd/jars/NavActiveIgnore.jar:/X/lsd/jars/$UIF" ] \
        && ok "next start: one trial loading the ui JAR" || bad "boot: $o"
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
    [ "$(h "$U/eso/hmi/lsd/jars/$UIF")" = "$(jsha ui)" ] && case "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" in *"+$UI"|*"+$UI+"*) true ;; *) false ;; esac \
        && ok "main 4 keeps ui in the set" || bad "after main 4: $(cat "$U/carplaymaps/HMI_BOOT")"
    run restore; rc_is 0
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"
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
    o=$(unit_boot); case "$o" in "boot=trial "*"$RGF:/X/lsd/jars/$SLF:/X/lsd/jars/$UIF") ok "rg, sl and ui load together" ;; *) bad "boot: $o" ;; esac
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
    before=$(aaf)   # new_start cleared this start's RAM trial marker
    run aa-output direct; rc_is 0; [ "$before" = "$(aaf)" ] && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" \
        && ok "(a) direct again: only aa-extra.conf" || bad "(a) direct: $(aaf)"
    run aa-output bogus; rc_is 1; expect_out "AA_OUTPUT_MUST_BE_direct_OR_ring" "aa-output: unknown value refused"
    grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" && ok "refused value: file unchanged" || bad "aa-extra.conf changed"
    run aa-status; expect_out "^AA switches: PMCP_AA_OUTPUT=direct $" "aa-status shows the switch (no tr on the unit)"
    if [ $EXPCARD = yes ]; then
        run aa-capture 60; rc_is 0; grep -qx 'PMCP_AA_CAPTURE_S=60' "$P/aa-extra.conf" && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" \
            && ok "experimental card: recording on, output kept" || bad "aa-extra.conf: $(cat "$P/aa-extra.conf")"
        [ "$before" = "$(aaf)" ] && ok "recording: no marker or set file changed" || bad "recording changed: $(aaf)"
        run aa-capture 5; rc_is 1; expect_out "AA_CAPTURE_MUST_BE_60_OR_off" "aa-capture: unknown value refused"
        run aa-capture off; rc_is 0; grep -qx 'PMCP_AA_CAPTURE_S=0' "$P/aa-extra.conf" && ok "recording off" || bad "capture off"
        # A203-AA reverse-gear test: the hook itself re-grants the cluster after a main-screen focus change when
        # aa-extra.conf has exactly PMCP_AA_SEC_REASSERT=3 (patch_reassert.py); the gal wrapper is not touched (an earlier
        # AA set is recognised by it)
        gal0=$(h "$U/eso/bin/apps/gal")
        run aa-regrant on; rc_is 0; expect_out "PMCP_AA_REGRANT_OK regrant=on" "aa-regrant on"
        grep -qx 'PMCP_AA_SEC_REASSERT=3' "$P/aa-extra.conf" && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" \
            && grep -qx 'PMCP_AA_CAPTURE_S=0' "$P/aa-extra.conf" && ok "re-grant on: the other switches kept" || bad "aa-extra.conf: $(cat "$P/aa-extra.conf")"
        [ "$before" = "$(aaf)" ] && [ "$gal0" = "$(h "$U/eso/bin/apps/gal")" ] && ok "re-grant: no marker, set file or wrapper changed (no trial)" || bad "re-grant changed: $(aaf)"
        run aa-output ring; rc_is 0; grep -qx 'PMCP_AA_SEC_REASSERT=3' "$P/aa-extra.conf" && ok "re-grant kept when the output changes" || bad "re-grant lost: $(cat "$P/aa-extra.conf")"
        run aa-output direct; rc_is 0
        run aa-capture 60; rc_is 0; grep -qx 'PMCP_AA_SEC_REASSERT=3' "$P/aa-extra.conf" && ok "re-grant kept when recording changes" || bad "re-grant lost on capture"
        run aa-capture off; rc_is 0
        run aa-regrant maybe; rc_is 1; expect_out "AA_REGRANT_MUST_BE_on_OR_off" "aa-regrant: unknown value refused"
        grep -qx 'PMCP_AA_SEC_REASSERT=3' "$P/aa-extra.conf" && ok "refused value: switch unchanged" || bad "aa-extra.conf changed"
        run aa-regrant off; rc_is 0; grep -qx 'PMCP_AA_SEC_REASSERT=0' "$P/aa-extra.conf" && ! grep -q 'PMCP_AA_SEC_REASSERT=3' "$P/aa-extra.conf" \
            && ok "re-grant off: line 0" || bad "re-grant off: $(cat "$P/aa-extra.conf")"
        # A215-AA: feeder v17 keep-alive switch (PMCP_AA_KEEPALIVE_MS 1000|0 in aa-extra.conf), the other lines kept
        run aa-keepalive off; rc_is 0; expect_out "PMCP_AA_KEEPALIVE_OK keepalive=off" "aa-keepalive off"
        grep -qx 'PMCP_AA_KEEPALIVE_MS=0' "$P/aa-extra.conf" && grep -qx 'PMCP_AA_SEC_REASSERT=0' "$P/aa-extra.conf" \
            && grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" && grep -qx 'PMCP_AA_CAPTURE_S=0' "$P/aa-extra.conf" \
            && ok "keep-alive off: the other switches kept" || bad "aa-extra.conf: $(cat "$P/aa-extra.conf")"
        [ "$before" = "$(aaf)" ] && ok "keep-alive: no marker or set file changed (no trial)" || bad "keep-alive changed: $(aaf)"
        run aa-regrant on; rc_is 0; grep -qx 'PMCP_AA_KEEPALIVE_MS=0' "$P/aa-extra.conf" && ok "keep-alive kept when re-grant changes" || bad "keep-alive lost: $(cat "$P/aa-extra.conf")"
        run aa-regrant off; rc_is 0
        run aa-keepalive 500; rc_is 1; expect_out "AA_KEEPALIVE_MUST_BE_on_OR_off" "aa-keepalive: unknown value refused"
        run aa-keepalive on; rc_is 0; grep -qx 'PMCP_AA_KEEPALIVE_MS=1000' "$P/aa-extra.conf" && ! grep -q 'PMCP_AA_KEEPALIVE_MS=0' "$P/aa-extra.conf" \
            && ok "keep-alive on: line 1000" || bad "keep-alive on: $(cat "$P/aa-extra.conf")"
    else
        run aa-capture 60; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "release card: no recording button action"
        run aa-regrant on; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "release card: no re-grant button action"
        run aa-keepalive off; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "release card: no keep-alive button action"
    fi
    run aa-on-exp; rc_is 1; expect_out "AA_EXPERIMENTAL_NOT_ON_THIS_CARD" "aa-on-exp: no experimental set since AA 1.0"
    run aa-install; rc_is 0; expect_out "PMCP_AA_INSTALL_OK (already installed" "3 again: nothing to do"
    grep -qx 'PMCP_AA_OUTPUT=direct' "$P/aa-extra.conf" && ok "3 with this card's set: switch kept" || bad "3 dropped the switch"
    run aa-remove; rc_is 0; run aa-install; rc_is 0; [ ! -e "$P/aa-extra.conf" ] && ok "3 after AA remove: no switch file, the set's default" || bad "aa-extra.conf left"
    run restore; rc_is 0; [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "restore: exact factory tree" || bad "tree after restore"

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
    for bad_case in foreign-lsd missing-jar odd-name count other-jar dup-jar symlink-jar; do
        jbase
        case $bad_case in
            foreign-lsd) echo "# another mod" >> "$U/eso/hmi/lsd/lsd.sh" ;;
            missing-jar) rm -f "$U/eso/hmi/lsd/jars/pmcp-zz.jar" ;;
            odd-name) read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s ${jars% *} ../pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT" ;;
            count) read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+yy-11111111 $jars" > "$U/carplaymaps/HMI_BOOT" ;;
            other-jar) echo X > "$U/eso/hmi/lsd/jars/Other.jar"; read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s ${jars% *} Other.jar" > "$U/carplaymaps/HMI_BOOT" ;;
            dup-jar) read s jars < "$U/carplaymaps/HMI_BOOT"; echo "$s+yy-11111111 $jars pmcp-zz.jar" > "$U/carplaymaps/HMI_BOOT" ;;
            symlink-jar) rm -f "$U/eso/hmi/lsd/jars/pmcp-zz.jar"; ln -s ../lsd.sh "$U/eso/hmi/lsd/jars/pmcp-zz.jar" ;;
        esac
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/')
        run aa-install; rc_is 1; expect_out "AA_INSTALL_NEEDS" "$bad_case: 3 refuses"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "$bad_case: nothing changed" || bad "$bad_case: 3 changed the unit"
    done

    echo "[50] v1.6.0 card (rg 4e32e7f7 in pmcp-guidance4.jar, ui, sl in turnto mode, AA on) -> main menu 4: rg replaced in place, sl, ui, AA and the mode stay"
    V160P="${PMCP_V160_SD:-$SDB/../sd-64553e3b}/pmcp/pmcp.sh"
    run160() { PMCP_TEST_ROOT="$W/unit" $SH "$V160P" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
    if card_ok "$V160P" 64553e3b; then
        start_unit
        run160 map-install map-square-fps40; rc_is 0; run160 rg-system-on; rc_is 0
        for p in nai np rg zoom dn sl ui; do run160 java-on $p; rc_is 0; done
        new_start; unit_boot > /dev/null; run160 java-confirm; rc_is 0
        run160 speedlimit-mode turnto; rc_is 0
        run160 aa-on; rc_is 0; aa_before=$(snapshot "$W/unit" | grep -e '/carplaymaps/aa/' -e '/apps/gal')
        run status; expect_out "packages of an earlier card: np rg" "v1.6.0 np and rg reported as an earlier card's package"
        grep -q -e "packages of an earlier card: rg ui" -e "earlier card: ui" "$W/out" && bad "v1.6.0 ui taken as an earlier package" || ok "v1.6.0 ui is this card's ui"
        # cards since A166 (and v1.7.0) carry a newer AA set: v1.6.0's AA 1.0 is then an earlier card's set
        if [ "$(sed -n 's/^AA_FEEDER \([0-9a-f]*\) .*/\1/p' "$SDB/pmcp/pmcp.sh")" = 0003c60c132b56990d6020fe1efad9e549397e9542db9f3d51624a8be4d905d3 ]; then
            expect_out "Android Auto: on" "v1.6.0 AA set is this card's"
        else
            expect_out "Android Auto: old mode=gamma" "v1.6.0 AA set is an earlier card's set here"
        fi
        feat; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "4: java-update replaces the v1.6.0 rg"; expect_out "PMCP_FEATURES_ON_OK" "4 done"
        grep -q "PMCP_FEATURES_RESET_OK" "$W/out" && bad "4 reset the Java set (sl would be lost)" || ok "4 did not reset the Java set"
        jar_replaced pmcp-guidance4.jar "$RGF" rg "pmcp-guidance4.jar gone, this card's rg in place"
        jar_replaced pmcp-ui2.jar "$UIF" ui "ui: the same package under this card's file name"
        case "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" in *"+$RG+"*"+$(jid sl)+"*"$UI") ok "set keeps sl and ui, new rg" ;; *) bad "set: $(cat "$U/carplaymaps/HMI_BOOT")" ;; esac
        new_start; o=$(unit_boot); case "$o" in "boot=trial "*"$RGF"*"$SLF:/X/lsd/jars/$UIF") ok "one trial start with the new rg, sl and ui" ;; *) bad "boot: $o" ;; esac
        run java-confirm; rc_is 0
        [ "$(cat "$W/unit/mnt/persist/pmcp/native-speedlimit-mode" 2>/dev/null)" = turnto ] && ok "speed-limit mode kept" || bad "speed-limit mode lost"
        [ "$aa_before" = "$(snapshot "$W/unit" | grep -e '/carplaymaps/aa/' -e '/apps/gal')" ] && ok "Android Auto files untouched" || bad "4 changed the AA files"
        run status; expect_out "Unit state: JAVA" "state JAVA"; grep -q -e "earlier card" -e "unused JAR" "$W/out" && bad "earlier package left" || ok "no earlier package left"
        restore_exact "restore: exact factory tree"
    fi

    # an earlier release card's unit: features in a trial-confirmed set, sl in turnto mode, AA with PMCP_AA_OUTPUT=direct
    runc() { _c=$1; shift; PMCP_TEST_ROOT="$W/unit" $SH "$_c/pmcp/pmcp.sh" "$@" > "$W/out" 2>&1; echo $? > "$W/rc"; }
    exp_unit() {   # $1 card dir
        start_unit
        runc "$1" map-install map-square-fps40; rc_is 0; runc "$1" rg-system-on; rc_is 0
        for p in nai np rg zoom dn sl ui; do runc "$1" java-on $p; rc_is 0; done
        new_start; unit_boot > /dev/null; runc "$1" java-confirm; rc_is 0
        runc "$1" speedlimit-mode turnto; rc_is 0
        runc "$1" aa-install; rc_is 0; runc "$1" aa-output direct; rc_is 0
        new_start; gal_start > /dev/null; runc "$1" aa-confirm; rc_is 0
    }

    # v1.7.x payload in the car (np 1f3b0dc0 in pmcp-np2.jar, AA hook cbf2e388; A185 replaces both, A188 gives every JAR
    # a file name with its content): 2 already installed, 4 replaces the JARs in place (no reset: sl, its mode and ui
    # stay), 3 brings this card's AA set and keeps the direct output
    v17x_update() {   # $1 card id
        run status; expect_out "packages of an earlier card: np" "$1: np is an earlier card's package"
        expect_out "Android Auto: old mode=gamma" "$1: its AA set is an earlier card's set"
        run map-install map-square-fps40; rc_is 0; expect_out "already installed" "$1: 2 says already installed"
        feat; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK" "$1: 4 runs java-update"; expect_out "PMCP_FEATURES_ON_OK" "$1: 4 done"
        grep -q "PMCP_FEATURES_RESET_OK" "$W/out" && bad "$1: 4 reset the Java set (sl would be lost)" || ok "$1: 4 did not reset the Java set"
        jar_replaced pmcp-np2.jar "$NPF" np "$1: pmcp-np2.jar gone, this card's np in place"
        jar_replaced pmcp-guidance7.jar "$RGF" rg "$1: rg under this card's file name"
        jar_replaced pmcp-sl2.jar "$SLF" sl "$1: sl under this card's file name"
        jar_replaced pmcp-ui2.jar "$UIF" ui "$1: ui under this card's file name"
        new_start; o=$(unit_boot); case "$o" in "boot=trial "*"$NPF"*"$RGF"*"$SLF:/X/lsd/jars/$UIF") ok "$1: one trial start with this card's JARs" ;; *) bad "$1 boot: $o" ;; esac
        run java-confirm; rc_is 0
        [ "$(cat "$W/unit/mnt/persist/pmcp/native-speedlimit-mode" 2>/dev/null)" = turnto ] && ok "$1: speed-limit mode kept" || bad "$1: speed-limit mode lost"
        run aa-install; rc_is 0; expect_out "PMCP_AA_ON_OK mode=gamma set=$S" "$1: 3 brings this card's AA set"
        expect_out "AA output kept: direct" "$1: 3 keeps the direct output"
        new_start; o=$(gal_start); [ "$o" = "$HOOKED" ] && ok "$1: first connection with the new AA set is a trial" || bad "$1: AA $o"
        run aa-confirm; rc_is 0
        run status; expect_out "Unit state: JAVA" "$1: state JAVA"; expect_out "Android Auto: on" "$1: AA on with this card's set"
        grep -q -e "earlier card" -e "unused JAR" "$W/out" && bad "$1: earlier package left" || ok "$1: no earlier package left"
        restore_exact "$1: restore gives the exact factory tree"
    }

    echo "[56] main menu 10 Reinstall (A188): remove everything, then this card's versions of what was on"
    reinst() {
        sed -e "s#/bin/ksh \$PMCP#$SH $W/sd/pmcp.sh#" "$W/sd/menu/reinstall.sh" > "$W/reinstall.sh"
        PMCP_TEST_ROOT="$W/unit" $SH "$W/reinstall.sh" > "$W/out" 2>&1; echo $? > "$W/rc"; noexec "10 (reinstall.sh)"
    }
    start_unit
    reinst; rc_is 0; expect_out "REINSTALL_NOTHING_INSTALLED_USE_2_3_4" "factory unit: nothing to reinstall"; expect_out "PMCP_FAIL=REINSTALL_NO_PLAN" "factory unit: stops"
    [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "factory unit: nothing changed" || bad "reinstall changed a factory unit"
    # a unit with a non-default layout, rg + nai np sl (sl in turnto mode), AA with the CarPlay-bridge output, an earlier
    # np and an earlier AA set (as another card left them)
    run map-install map-clean; rc_is 0; run rg-system-on; rc_is 0
    for p in nai np rg sl; do run java-on $p; rc_is 0; done
    new_start; unit_boot > /dev/null; run java-confirm; rc_is 0; run speedlimit-mode turnto; rc_is 0
    run aa-install; rc_is 0; run aa-output ring; rc_is 0
    old_java np; printf x >> "$U/carplaymaps/aa/libgal_hook.so"; echo "gamma-0a1b2c3d-5d2a0a02-716516eb" > "$U/carplaymaps/aa/AA_BOOT"
    reinst; rc_is 0; expect_out "PMCP_REINSTALL_OK" "reinstall done"
    expect_out "PMCP_PLAN map-install map-clean" "plan keeps the map layout"; expect_out "PMCP_PLAN java-on sl" "plan keeps sl"
    expect_out "PMCP_PLAN aa-output ring" "plan keeps the AA output"; expect_out "speed-limit mode now: turnto" "the speed-limit mode is reported"
    expect_out "PMCP_RESTORE_OK" "restore ran first"
    [ "$(cat "$U/carplaymaps/VARIANT")" = map-clean ] && ok "layout map-clean back" || bad "layout: $(cat "$U/carplaymaps/VARIANT")"
    [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$NAI+$NP+$RG+$(jid sl)" ] && ok "the same packages, this card's versions" || bad "set: $(cat "$U/carplaymaps/HMI_BOOT")"
    [ ! -e "$U/eso/hmi/lsd/jars/pmcp-np-old.jar" ] && [ "$(h "$U/eso/hmi/lsd/jars/$NPF")" = "$(jsha np)" ] && ok "earlier np gone" || bad "JARs: $(ls "$U/eso/hmi/lsd/jars" | grep pmcp | tr '\n' ' ')"
    [ "$(h "$U/carplaymaps/aa/libgal_hook.so")" = "$(msha AA_HOOK)" ] && grep -qx 'PMCP_AA_OUTPUT=ring' "$W/unit/mnt/persist/pmcp/aa-extra.conf" \
        && ok "this card's AA set, output ring kept" || bad "AA after reinstall"
    [ ! -e "$W/unit/mnt/persist/pmcp/native-speedlimit-mode" ] && ok "speed-limit mode set again only after Confirm" || bad "mode file written without a confirmed set"
    run status; expect_out "Unit state: JAVA" "after reinstall: JAVA"; expect_out "Android Auto: on mode=gamma" "after reinstall: AA on"
    o=$(unit_boot); case "$o" in "boot=trial "*) ok "first start is a trial" ;; *) bad "boot: $o" ;; esac
    # restore refuses (not a pmcp carplaymaps): nothing written, the plan is not run
    printf x >> "$U/carplaymaps/rollback/lsd.sh"; broken=$(snapshot "$W/unit")
    reinst; rc_is 0; expect_out "PMCP_FAIL=REINSTALL_" "not a pmcp install: reinstall stops"
    [ "$broken" = "$(snapshot "$W/unit")" ] && ok "not a pmcp install: nothing changed" || bad "reinstall wrote on a non-pmcp install"
    fresh_unit

    echo "[55] v1.7.1 release card 6ab6432c (v1.7.x payload) -> 2 already installed, 4 replaces the JARs in place, 3 the AA set"
    V171SD="${PMCP_V171_SD:-$SDB/../release-v1.7.1-6ab6432c/sd}"
    ls "$SDB/pmcp/menu" | grep -q -e wifi-test -e wl-diag && bad "this card has the experimental Wi-Fi buttons" || ok "this card has no wifi-test / wl-diag buttons"
    if card_ok "$V171SD/pmcp/pmcp.sh" 6ab6432c; then
        exp_unit "$V171SD"
        v17x_update 6ab6432c
    fi

    # Experimental cards: the MOST bridge the mathsls supervisor starts (bridge mathsls|pmcp-most, GEM experimental), the
    # pmcp-most dio_manager wrapper (contract owner src=wired kind=proxy + wired.session) and the bridge files in the
    # CarPlay log. Release cards: none of it (no button, no payload, no code, no action).
    echo "[57] MOST bridge switch: mathsls (default) and pmcp-most (experimental cards only)"
    MAN57=$(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh")
    msha() { echo "$MAN57" | sed -n "s/^$1 \([0-9a-f]*\) .*/\1/p"; }
    BR_M=$(msha BRIDGE); BR_P=$(msha PMCP_MOST); WR_M=$(msha WRAPPER); WR_P=$(msha PMCP_MOST_WRAPPER)
    AB="$U/carplaymaps/altscreen-most-bridge"; LDIO="$U/eso/bin/apps/dio_manager"; MK="$W/unit/mnt/persist/pmcp/most-bridge"
    MSD="$W/unit/ramdisk/most-src"
    if [ -z "$BR_P" ]; then
        case "$(head -1 "$SDB/BUILD-MANIFEST.txt")" in *-exp-*) bad "experimental card without the pmcp-most payload" ;; esac
        ls "$SDB/pmcp/menu" | grep -q '^bridge-' && bad "release card has Bridge buttons" || ok "release card: no Bridge buttons"
        grep -q 'Bridge:' "$SDB/esd/Launcher-sda0.esd" && bad "release menu has Bridge entries" || ok "release menu: no Bridge entries"
        [ ! -e "$SDB/pmcp/payload/pmcp-most" ] && [ -z "$WR_P" ] && ok "release card: no pmcp-most payload or wrapper" || bad "release card carries pmcp-most files"
        grep -q 'pmcp-most\|PMCP_MOST\|most-src\|BRIDGE_MARK\|do_bridge' "$SDB/pmcp/pmcp.sh" && bad "release pmcp.sh has pmcp-most code" || ok "release pmcp.sh: no pmcp-most code"
        start_unit; run map-install map-square-fps40; rc_is 0
        run bridge pmcp-most; rc_is 1; expect_out "PMCP_FAIL=UNKNOWN_ACTION_bridge" "release card: no bridge action"
        run bridge-status; rc_is 1; expect_out "PMCP_FAIL=UNKNOWN_ACTION_bridge-status" "release card: no bridge-status action"
        run most-sup pmcp; rc_is 1; expect_out "PMCP_FAIL=UNKNOWN_ACTION_most-sup" "release card: no most-sup action"
        run status; grep -q "MOST bridge" "$W/out" && bad "release status shows a MOST bridge line" || ok "release status: no MOST bridge line"
        restore_exact "release card: restore gives the exact factory tree"
    else
        # one start of the live dio_manager file in the fake unit (supervisor and pairing helper not started); prints
        # "exec pid=N" for the pid that dio_manager would get (the wrapper's own, exec keeps it)
        dio_start() {
            sed -e "s#/mnt/app/carplaymaps#$U/carplaymaps#g" -e "s#/ramdisk/#$W/unit/ramdisk/#g" \
                -e 's#^        "$SUPERVISOR" >/dev/null 2>&1$#        :#' -e 's#^            "$PAIR_HELPER" --server >/dev/null 2>&1$#            :#' \
                -e 's#^exec "$REAL" "$@"#echo "exec pid=$$"; exit 0#' "$LDIO" > "$W/dio-start.sh"
            env -u LD_PRELOAD $SH "$W/dio-start.sh" 2>&1 | tail -1
        }
        # contract line check (pmcp_most_contract.h 2.): one line, v=1 first, key=value pairs, <= 255 bytes with '\n'
        cline() {
            [ -f "$1" ] && [ "$(wc -l < "$1" | tr -d ' ')" = 1 ] && [ "$(wc -c < "$1" | tr -d ' ')" -le 255 ] \
                && awk 'NR==1 && $1=="v=1" { for (i = 1; i <= NF; i++) if ($i !~ /^[a-z_]+=[A-Za-z0-9_-]+$/) exit 1; exit 0 } { exit 1 }' "$1"
        }
        deadpid=$($SH -c 'echo $$')
        start_unit
        run bridge pmcp-most; rc_is 1; expect_out "BRIDGE_NEEDS_PMCP_MAP_STATE_STOCK" "factory unit: refused"
        run bridge-status; rc_is 0; expect_out "^MOST bridge: none (no CarPlay map installed" "bridge-status on a factory unit: no bridge"
        [ "$factory" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "factory unit: nothing written" || bad "refused switch wrote files"
        run map-install map-square-fps40; rc_is 0
        [ "$(h "$AB")" = "$BR_M" ] && [ "$(h "$LDIO")" = "$WR_M" ] && [ ! -e "$MK" ] && [ ! -e "$U/carplaymaps/bridge" ] \
            && ok "install: mathsls bridge and wrapper, no marker, no kept copies (the release card's file set)" || bad "install: bridge files"
        run status; expect_out "^MOST bridge: mathsls (${BR_M:0:8}, default)$" "status: mathsls and its sha8"
        expect_out "dio_manager wrapper: mathsls; chosen: mathsls (default)" "status: mathsls wrapper, default choice"
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/')
        run bridge mathsls; rc_is 0; expect_out "PMCP_BRIDGE_OK bridge=mathsls (already in use, nothing changed)" "mathsls again: already"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/')" ] && ok "mathsls again: no file changed" || bad "mathsls again changed files"
        rm -rf "$MSD"; dio_start > /dev/null
        [ ! -e "$MSD" ] && ok "mathsls wrapper writes no contract file" || bad "mathsls wrapper wrote $MSD"

        run bridge pmcp-most; rc_is 0; expect_out "PMCP_BRIDGE_OK bridge=pmcp-most (${BR_P:0:8})" "switch to pmcp-most"
        [ "$(h "$AB")" = "$BR_P" ] && [ -x "$AB" ] && [ "$(h "$LDIO")" = "$WR_P" ] && [ -x "$LDIO" ] && [ "$(cat "$MK")" = pmcp-most ] \
            && ok "pmcp-most: bridge at the supervisor's path, pmcp-most wrapper, marker" || bad "pmcp-most files"
        [ "$(h "$U/carplaymaps/bridge/mathsls")" = "$BR_M" ] && [ "$(h "$U/carplaymaps/bridge/pmcp-most")" = "$BR_P" ] \
            && [ "$(h "$U/carplaymaps/bridge/dio_manager.wrapper-pmcp-most.sh")" = "$WR_P" ] && ok "both bridges and the pmcp-most wrapper kept on the unit" || bad "kept copies"
        [ -z "$(find "$W/unit" -name '*.pmcp-new')" ] && ok "no staging leftovers" || bad "leftovers: $(find "$W/unit" -name '*.pmcp-new')"
        run status; expect_out "^MOST bridge: pmcp-most (${BR_P:0:8}, experimental)$" "status: pmcp-most and its sha8"
        expect_out "dio_manager wrapper: pmcp-most (writes the MOST owner); chosen: pmcp-most" "status: pmcp-most wrapper and choice"
        grep -q "interrupted" "$W/out" && bad "status calls a finished switch interrupted" || ok "status: switch complete"
        expect_out "Unit state: VIDEO" "pmcp-most wrapper: the map part is ours (VIDEO)"
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')
        run map-install map-square-fps40; rc_is 0; expect_out "already installed" "2 with pmcp-most: already installed"
        run bridge pmcp-most; rc_is 0; expect_out "already in use, nothing changed" "pmcp-most again: already"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')" ] && ok "2 and pmcp-most again change no file" || bad "2 or the second press changed files"

        echo "  - wrapper: MOST contract owner and wired.session"
        grep -Eq '(^|[^a-z_-])(printf|tr|cut)( |$)' "$LDIO" && bad "pmcp-most wrapper uses printf/tr/cut" || ok "pmcp-most wrapper: no printf, tr, cut"
        rm -rf "$MSD"; o=$(dio_start); p=${o#exec pid=}
        case "$p" in ""|*[!0-9]*) bad "wrapper did not reach the exec: $o" ;; *) ok "wrapper reaches the exec of dio_manager" ;; esac
        [ "$(cat "$MSD/owner")" = "v=1 src=wired pid=$p gen=1 since_ms=0 kind=proxy" ] && cline "$MSD/owner" \
            && ok "owner: v=1 src=wired pid=<dio_manager pid> gen=1 since_ms=0 kind=proxy" || bad "owner: $(cat "$MSD/owner" 2>&1)"
        [ "$(cat "$MSD/wired.session")" = "v=1 state=start gen=1 pid=$p ts_ms=0 reason=start" ] && cline "$MSD/wired.session" \
            && ok "wired.session: v=1 state=start gen=1 pid=<same> ts_ms=0 reason=start" || bad "session: $(cat "$MSD/wired.session" 2>&1)"
        [ "$(ls "$MSD" | tr '\n' ' ')" = "owner wired.session " ] && ok "no tmp file left in most-src" || bad "most-src: $(ls "$MSD")"
        o=$(dio_start); p=${o#exec pid=}
        grep -qx "v=1 src=wired pid=$p gen=2 since_ms=0 kind=proxy" "$MSD/owner" && grep -qx "v=1 state=start gen=2 pid=$p ts_ms=0 reason=start" "$MSD/wired.session" \
            && ok "next dio_manager start: gen 2 (earlier wired owner replaced)" || bad "second start: $(cat "$MSD/owner")"
        echo "v=1 src=aa pid=$$ gen=7 since_ms=5 kind=in" > "$MSD/owner"; rm -f "$MSD/wired.session"
        dio_start > /dev/null
        [ "$(cat "$MSD/owner")" = "v=1 src=aa pid=$$ gen=7 since_ms=5 kind=in" ] && [ ! -e "$MSD/wired.session" ] \
            && ok "live owner of another source (aa): wrapper backs off, writes nothing" || bad "took a live aa owner: $(cat "$MSD/owner")"
        echo "v=1 src=aa pid=$deadpid gen=7 since_ms=5 kind=in" > "$MSD/owner"
        o=$(dio_start); p=${o#exec pid=}
        grep -qx "v=1 src=wired pid=$p gen=8 since_ms=0 kind=proxy" "$MSD/owner" && grep -q " gen=8 " "$MSD/wired.session" \
            && ok "dead owner: taken, gen 7 -> 8" || bad "dead owner: $(cat "$MSD/owner")"
        echo "v=1 src=wireless pid=$$ gen=4294967295 since_ms=5 kind=proxy" > "$MSD/owner"
        o=$(dio_start); p=${o#exec pid=}
        grep -qx "v=1 src=wired pid=$p gen=1 since_ms=0 kind=proxy" "$MSD/owner" && ok "live Wi-Fi owner: the cable wins; gen 4294967295 -> 1 (0 skipped)" || bad "wireless owner: $(cat "$MSD/owner")"
        echo "garbage" > "$MSD/owner"
        dio_start > /dev/null; grep -q "^v=1 src=wired pid=[0-9]* gen=1 " "$MSD/owner" && ok "unparsable owner: taken, gen 1" || bad "garbage owner: $(cat "$MSD/owner")"
        rm -rf "$MSD"; echo x > "$MSD"
        o=$(dio_start); case "$o" in "exec pid="[0-9]*) ok "most-src not creatable: dio_manager still starts" ;; *) bad "wrapper stopped: $o" ;; esac
        rm -f "$MSD"

        echo "  - CarPlay log with the bridge files"
        new_start; mkdir -p "$W/unit/ramdisk/pmcp-most" "$MSD"
        echo "bridge: older half" > "$W/unit/ramdisk/pmcp-most/bridge.log.1"; echo "bridge: newer half" > "$W/unit/ramdisk/pmcp-most/bridge.log"
        echo "boot_ms=43001 up_ms=40002 pid=456 latency-reset seq=9 queued=2058 discarded=2050 limit=2048 resets=1" > "$W/unit/ramdisk/pmcp-most/events.log"
        echo "boot_ms=12001 up_ms=9002 pid=455 start stage=2" > "$W/unit/ramdisk/pmcp-most/events.log.1"
        echo "v=1 src=wired pid=123 gen=3 since_ms=0 kind=proxy" > "$MSD/owner"
        echo "v=1 state=start gen=3 pid=123 ts_ms=0 reason=start" > "$MSD/wired.session"
        echo "v=1 ready=1 pid=456 owner_gen=3 ring_gen=2 seq=10 frames=10 drops=0 overruns=0 latency_resets=0 age_ms=5 queue_pkts=0 queue_hi=9 reclaims=0 most_errno=0 up_ms=1000" > "$MSD/consumer"
        run cp-log-save; rc_is 0; expect_out "PMCP_CP_LOG_SAVED file=logs/cp-log-1.txt" "cp log saved"
        L56="$U/carplaymaps/logs/cp-log-1.txt"
        grep -qx -- "--- MOST bridge: pmcp-most (chosen: pmcp-most)" "$L56" && ok "cp log: active bridge and choice" || bad "cp log: bridge line"
        [ "$(sed -n '/^--- pmcp-most\/bridge.log.1 /,/^--- pmcp-most\/bridge.log /p' "$L56" | sed -n 2p)" = "bridge: older half" ] \
            && [ "$(sed -n '/^--- pmcp-most\/bridge.log (/,/^--- most-src\/owner /p' "$L56" | sed -n 2p)" = "bridge: newer half" ] \
            && ok "cp log: bridge.log.1 then bridge.log" || bad "cp log: bridge logs"
        [ "$(sed -n '/^--- pmcp-most\/events.log /,/^--- pmcp-most\/bridge.log.1 /p' "$L56" | sed -n 2p)" = "boot_ms=43001 up_ms=40002 pid=456 latency-reset seq=9 queued=2058 discarded=2050 limit=2048 resets=1" ] \
            && [ "$(sed -n '/^--- pmcp-most\/events.log.1 /,/^--- pmcp-most\/events.log /p' "$L56" | sed -n 2p)" = "boot_ms=12001 up_ms=9002 pid=455 start stage=2" ] \
            && ok "cp log: events.log.1 then events.log (rotated bridge events) before the bridge logs" || bad "cp log: events.log"
        grep -qx "v=1 src=wired pid=123 gen=3 since_ms=0 kind=proxy" "$L56" && grep -qx "v=1 state=start gen=3 pid=123 ts_ms=0 reason=start" "$L56" \
            && grep -q "^v=1 ready=1 pid=456 " "$L56" && [ "$(tail -1 "$L56")" = "--- end" ] && ok "cp log: owner, wired.session, consumer; complete" || bad "cp log: contract files"
        run status; expect_out "bridge status (this start): v=1 ready=1 pid=456" "status: the bridge's consumer line"
        before=$(snapshot "$W/unit")
        run bridge-status; rc_is 0
        expect_out "^MOST bridge: pmcp-most (${BR_P:0:8}, experimental)$" "bridge-status: pmcp-most and its sha8"
        expect_out "bridge status (this start): v=1 ready=1 pid=456" "bridge-status: the consumer line"
        expect_out "^  v=1 src=wired pid=123 gen=3 since_ms=0 kind=proxy$" "bridge-status: owner"
        expect_out "^  v=1 state=start gen=3 pid=123 ts_ms=0 reason=start$" "bridge-status: wired.session"
        expect_out "^  boot_ms=43001 up_ms=40002 pid=456 latency-reset seq=9 queued=2058 " "bridge-status: the event file"
        [ "$(tail -1 "$W/out")" = "  bridge: newer half" ] && ok "bridge-status: ends with the newest bridge.log line" || bad "bridge-status log tail: $(tail -1 "$W/out")"
        [ "$before" = "$(snapshot "$W/unit")" ] && ok "bridge-status is read-only" || bad "bridge-status changed files"
        run log-clear; rc_is 0; [ ! -e "$U/carplaymaps/logs" ] && [ "$(cat "$MK")" = pmcp-most ] && ok "9 deletes the CarPlay log, keeps the bridge choice (a marker)" || bad "log-clear"

        echo "  - back to mathsls, interrupted switch, foreign bridge file, restore"
        run bridge mathsls; rc_is 0; expect_out "PMCP_BRIDGE_OK bridge=mathsls (${BR_M:0:8})" "switch back to mathsls"
        [ "$(h "$AB")" = "$BR_M" ] && [ "$(h "$LDIO")" = "$WR_M" ] && [ ! -e "$MK" ] && ok "mathsls: bridge, mathsls wrapper, no marker" || bad "mathsls files"
        rm -rf "$MSD"; dio_start > /dev/null; [ ! -e "$MSD" ] && ok "mathsls wrapper again: no contract file" || bad "owner written with the mathsls wrapper"
        echo pmcp-most > "$MK"
        run status; expect_out "the switch was interrupted: press the same Bridge button again" "marker and bridge differ: status says interrupted"
        run bridge mathsls; rc_is 0; [ ! -e "$MK" ] && ok "pressing mathsls again finishes it" || bad "marker left"
        echo junk >> "$AB"
        run status; expect_out "MOST bridge: not this card's file" "foreign bridge file reported"
        run bridge pmcp-most; rc_is 0; [ "$(h "$AB")" = "$BR_P" ] && ok "a Bridge button replaces a foreign bridge file" || bad "foreign bridge not replaced"
        restore_exact "restore from pmcp-most: exact factory tree"
        start_unit; run map-install map-square-fps40; run bridge pmcp-most; rc_is 0
        cp "$SDB/pmcp/payload/pmcp-most/altscreen-most-bridge" "$W/pm.bak"; printf 'X' >> "$W/sd/payload/pmcp-most/altscreen-most-bridge"
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')
        run bridge mathsls; rc_is 1; expect_out "HASH_MISMATCH_PMCP_MOST" "corrupted payload: refused"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')" ] && ok "corrupted payload: nothing changed" || bad "corrupted payload changed files"
        cp "$W/pm.bak" "$W/sd/payload/pmcp-most/altscreen-most-bridge"
        restore_exact "restore after a refused switch (pmcp-most active): exact factory tree"

        echo "  - MOST supervisor switch (most-sup pmcp|mathsls, stage 5)"
        SV="$U/carplaymaps/carplay-cluster-supervisor"; SM="$W/unit/mnt/persist/pmcp/most-sup"
        SU_M=$(msha SUPERVISOR); SU_P=$(msha PMCP_MOST_SUP)
        [ -n "$SU_P" ] && [ "$(h "$SDB/pmcp/payload/pmcp-most/pmcp-most-sup")" = "$SU_P" ] && ok "payload: pmcp-most-sup pinned" || bad "pmcp-most-sup payload"
        start_unit; run map-install map-square-fps40; rc_is 0
        before=$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')
        run most-sup pmcp; rc_is 1; expect_out "MOST_SUP_PMCP_NEEDS_BRIDGE_PMCP_MOST_FIRST" "our supervisor needs the pmcp-most bridge"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/ramdisk/' | grep -v '/persist/pmcp/gem.log')" ] && ok "refused: nothing changed" || bad "refused most-sup changed files"
        run most-sup mathsls; rc_is 0; expect_out "PMCP_MOST_SUP_OK supervisor=mathsls (already in use, nothing changed)" "mathsls: already"
        run bridge pmcp-most; rc_is 0
        run most-sup pmcp; rc_is 0; expect_out "PMCP_MOST_SUP_OK supervisor=pmcp (${SU_P:0:8})" "switch to our supervisor"
        [ "$(h "$SV")" = "$SU_P" ] && [ -x "$SV" ] && [ "$(cat "$SM")" = pmcp ] && ok "ours at the wrappers' path, marker pmcp" || bad "most-sup pmcp files"
        [ "$(h "$U/carplaymaps/bridge/carplay-cluster-supervisor.mathsls")" = "$SU_M" ] && [ "$(h "$U/carplaymaps/bridge/pmcp-most-sup")" = "$SU_P" ] \
            && ok "both supervisors kept in carplaymaps/bridge" || bad "kept supervisor copies"
        run status; expect_out "MOST supervisor: pmcp; chosen: pmcp" "status: our supervisor"
        run map-install map-square-fps40; rc_is 0; expect_out "already installed" "2 with our supervisor: already installed"
        run most-sup pmcp; rc_is 0; expect_out "already in use, nothing changed" "pmcp again: already"
        echo pmcp > "$SM.x"; rm -f "$SM"
        run status; expect_out "the supervisor switch was interrupted" "marker missing: status says interrupted"
        rm -f "$SM.x"; run most-sup pmcp; rc_is 0; [ "$(cat "$SM")" = pmcp ] && ok "pressing pmcp again finishes it" || bad "marker not back"
        run bridge mathsls; rc_is 0; expect_out "MOST supervisor: mathsls again" "bridge mathsls also puts mathsls's supervisor back"
        [ "$(h "$SV")" = "$SU_M" ] && [ ! -e "$SM" ] && ok "mathsls supervisor and no marker" || bad "supervisor after bridge mathsls"
        run bridge mathsls; rc_is 0; expect_out "already in use, nothing changed" "bridge mathsls again: already"
        run bridge pmcp-most; run most-sup pmcp; rc_is 0
        mkdir -p "$W/unit/ramdisk/pmcp-most"; echo "up_ms=1 supervisor-started pid=7" > "$W/unit/ramdisk/pmcp-most/sup.log"
        run cp-log-save; rc_is 0; grep -qx "up_ms=1 supervisor-started pid=7" "$U/carplaymaps/logs/cp-log-1.txt" && ok "cp log: supervisor log" || bad "cp log: sup.log"
        run bridge-status; rc_is 0; expect_out "^  up_ms=1 supervisor-started pid=7$" "bridge-status: supervisor log tail"
        cp "$SDB/pmcp/payload/pmcp-most/pmcp-most-sup" "$W/sup.bak"; printf 'X' >> "$W/sd/payload/pmcp-most/pmcp-most-sup"
        run most-sup mathsls; rc_is 1; expect_out "HASH_MISMATCH_PMCP_MOST_SUP" "corrupted payload: refused"
        cp "$W/sup.bak" "$W/sd/payload/pmcp-most/pmcp-most-sup"
        restore_exact "restore with our supervisor: exact factory tree"
    fi

    # MOST supervisor stage 5 (docs 23, A218): the factory VW encoder's MOST path. Every card: the lsd.sh block makes the
    # link, and restore / the last java-off / the rescue card put the factory displaymanager.json back when it is ours
    # (verified copy in rollback/). Experimental cards: dm-path pmcp|factory, dm-link drop|make, dm-diag.
    echo "[58] VW encoder MOST path: link in lsd.sh, factory displaymanager.json back on every card, dm-* (experimental)"
    DMJF="$W/unit/mnt/system/etc/eso/production/displaymanager.json"
    DMF=0374c1f236a947a4d728085034e2c96d21f6f0dc4a727bcc379468612bb1ded0
    LSDP="$SDB/pmcp/payload/lsd/lsd.sh"
    grep -qx 'ln -Ps /dev/mlb/isoTX2 /dev/pmcp-isoTX2 2>/dev/null' "$LSDP" && ok "lsd.sh block makes the encoder link" || bad "no link line in lsd.sh"
    l_ln=$(grep -n '^ln -Ps /dev/mlb/isoTX2 ' "$LSDP" | cut -d: -f1); l_if=$(grep -n 'RUN_MODE}" != swdl' "$LSDP" | cut -d: -f1)
    [ -n "$l_ln" ] && [ -n "$l_if" ] && [ "$l_ln" -lt "$l_if" ] && ok "link line before the update-mode / DISABLED condition" || bad "link line order ($l_ln/$l_if)"
    # what dm-path pmcp leaves, made by hand (also for release cards, which cannot make it)
    dm_ours() {
        cp "$DMJF" "$U/carplaymaps/rollback/displaymanager.json"
        sed 's#"device" : "/dev/mlb/isoTX2",#"device" : "/dev/pmcp-isoTX2",#' "$DMJF" > "$W/dmj"; cat "$W/dmj" > "$DMJF"
    }
    start_unit; run map-install map-square-fps40; rc_is 0; run java-on nai; rc_is 0
    dm_ours; [ "$(wc -c < "$DMJF" | tr -d ' ')" = 5984 ] && ok "setup: our displaymanager.json is one byte longer" || bad "setup size"
    run status; expect_out "VW encoder MOST path: pmcp" "status shows the encoder path"
    run java-off nai; rc_is 0; [ "$(h "$DMJF")" = $DMF ] && [ ! -e "$U/carplaymaps/rollback/displaymanager.json" ] \
        && ok "last java-off: factory displaymanager.json back first (the factory lsd.sh makes no link)" || bad "java-off left our json"
    run java-on nai; rc_is 0; dm_ours
    restore_exact "restore with our displaymanager.json: exact factory tree"
    start_unit; run map-install map-square-fps40; rc_is 0; run java-on nai; rc_is 0
    echo "changed by someone else" >> "$DMJF"; cp "$DMJF" "$W/dmj.other"
    run restore; rc_is 0; cmp -s "$DMJF" "$W/dmj.other" && ok "restore leaves a displaymanager.json that is not ours" || bad "restore touched a foreign json"
    echo "  - an earlier card's lsd.sh (v1.4.2-v1.8.0 block bff3fbf4): java-update replaces it in place, one trial"
    sed '/^# MOST supervisor (stage 5/,/^ln -Ps /d' "$LSDP" > "$W/lsd-old.sh"
    [ "$(h "$W/lsd-old.sh")" = bff3fbf48872780e40d780f61a4e96a554d2b09edbb3f985c405f831eca6e8e5 ] \
        && ok "this card's block minus the link lines = the v1.4.2-v1.8.0 lsd.sh (history lsd_known)" || bad "earlier lsd.sh: $(h "$W/lsd-old.sh")"
    start_unit; run map-install map-square-fps40; rc_is 0; run java-on nai; rc_is 0; run java-on zoom; rc_is 0
    SID=$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT"); unit_boot > /dev/null; run java-confirm; rc_is 0
    cat "$W/lsd-old.sh" > "$U/eso/hmi/lsd/lsd.sh"
    run status; expect_out "Unit state: JAVA" "earlier lsd.sh: still JAVA (the set works as it is)"
    expect_out "lsd.sh of an earlier card (4. Install additional features replaces it)" "status names the earlier lsd.sh"
    o=$(unit_boot); case "$o" in "boot=yes set=$SID "*) ok "earlier lsd.sh: the confirmed set loads" ;; *) bad "boot with earlier lsd.sh: $o" ;; esac
    run java-on dn; rc_is 1; expect_out "JAVA_SET_HAS_AN_EARLIER_LSD_SH_RUN_JAVA_UPDATE_FIRST" "java-on waits for java-update"
    run java-update; rc_is 0; expect_out "PMCP_JAVA_UPDATE_OK set=$SID" "java-update: same set"
    expect_out "lsd.sh: an earlier card's block replaced by this card's" "java-update says lsd.sh was replaced"
    [ "$(h "$U/eso/hmi/lsd/lsd.sh")" = "$(h "$LSDP")" ] && ok "this card's lsd.sh in place" || bad "lsd.sh not replaced"
    [ ! -e "$W/unit/mnt/persist/pmcp/ok.$SID" ] && [ ! -e "$W/unit/mnt/persist/pmcp/trial.$SID" ] && ok "trial and confirm markers of the set reset" || bad "markers: $(ls "$W/unit/mnt/persist/pmcp")"
    o=$(unit_boot); case "$o" in "boot=trial set=$SID "*) ok "next start: one trial with the new lsd.sh" ;; *) bad "boot after update: $o" ;; esac
    run java-confirm; rc_is 0; run java-update; rc_is 1; expect_out "JAVA_UPDATE_ALREADY_CURRENT" "java-update again: already current"
    run status; grep -q "lsd.sh of an earlier card" "$W/out" && bad "status still names an earlier lsd.sh" || ok "status: lsd.sh current"
    restore_exact "restore after the lsd.sh update: exact factory tree"
    if sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh" | grep -q '^DM_JSON '; then
        echo "  - experimental: dm-path, dm-link, dm-diag"
        for b in dm-diag dm-path-pmcp dm-path-factory dm-link-drop dm-link-make; do
            [ -f "$SDB/pmcp/menu/$b.sh" ] && grep -q "$b" "$SDB/esd/Launcher-sda0.esd" || bad "button $b missing"
        done; ok "five VW encoder buttons on the experimental screen"
        start_unit; run map-install map-square-fps40; rc_is 0
        before=$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')
        run dm-path pmcp; rc_is 1; expect_out "DM_PATH_PMCP_NEEDS_JAVA_STATE_VIDEO" "dm-path pmcp without this card's Java set: refused"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')" ] && ok "refused: nothing changed" || bad "refused dm-path changed files"
        run java-on nai; rc_is 0
        run dm-path pmcp; rc_is 0; expect_out "PMCP_DM_PATH_OK path=pmcp (from the next unit start" "dm-path pmcp"
        DMP=$(sed -n "/^MANIFEST='/,/^'/p" "$SDB/pmcp/pmcp.sh" | sed -n 's/^DM_JSON \([0-9a-f]*\) .*/\1/p')
        [ "$(h "$DMJF")" = "$DMP" ] && [ "$(h "$U/carplaymaps/rollback/displaymanager.json")" = $DMF ] \
            && ok "our displaymanager.json live, verified factory copy kept" || bad "dm-path pmcp files"
        [ "$(grep -c 'isoTX2' "$DMJF")" = 1 ] && grep -q '"device" : "/dev/pmcp-isoTX2",' "$DMJF" && [ "$(wc -c < "$DMJF" | tr -d ' ')" = 5984 ] \
            && ok "only the MOST encoder device changed (one byte longer)" || bad "json content"
        diff "$U/carplaymaps/rollback/displaymanager.json" "$DMJF" | grep -c '^[<>]' | grep -qx 2 && ok "one line differs from the factory file" || bad "json diff"
        [ -z "$(find "$W/unit" -name '*.pmcp-new' -o -name '*.pmcp-restore')" ] && ok "no staging leftovers" || bad "leftovers"
        before=$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')
        run dm-path pmcp; rc_is 0; expect_out "path=pmcp (already, nothing changed)" "dm-path pmcp again: already"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')" ] && ok "again: no file changed" || bad "second press changed files"
        run status; expect_out "VW encoder MOST path: pmcp" "status: pmcp path"
        echo "  - dm-link (this start only; a plain symlink in the fake unit)"
        mkdir -p "$W/unit/dev/mlb"; rm -f "$W/unit/dev/pmcp-isoTX2"
        before=$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')
        run dm-link make; rc_is 0; expect_out "PMCP_DM_LINK_OK link=present (was missing; this start only) path=pmcp" "dm-link make"
        [ -L "$W/unit/dev/pmcp-isoTX2" ] && [ "$(readlink "$W/unit/dev/pmcp-isoTX2")" = "$W/unit/dev/mlb/isoTX2" ] && ok "link to the MOST device" || bad "link"
        run dm-link make; rc_is 0; expect_out "link=present (was present" "dm-link make again: fine"
        run dm-link drop; rc_is 0; expect_out "PMCP_DM_LINK_OK link=missing (was present" "dm-link drop"
        expect_out "keeps it until the next AID view change" "drop: says the held channel stays"
        [ ! -L "$W/unit/dev/pmcp-isoTX2" ] && ok "link removed" || bad "link left"
        run dm-link drop; rc_is 0; expect_out "link=missing (was missing" "drop again: fine"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')" ] && ok "dm-link writes no file" || bad "dm-link changed files"
        run dm-link sideways; rc_is 1; expect_out "DM_LINK_MUST_BE_drop_OR_make" "dm-link: bad argument"
        echo "  - dm-diag (read-only, one file for the log card)"
        run dm-link make; before=$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log')
        run dm-diag; rc_is 0; expect_out "PMCP_DM_DIAG_OK file=logs/dm-diag-1.txt" "dm-diag saved"
        expect_out "VW encoder MOST path: pmcp; link: present" "dm-diag: path and link on screen"
        D58="$U/carplaymaps/logs/dm-diag-1.txt"
        grep -q '"device" : "/dev/pmcp-isoTX2",' "$D58" && [ "$(tail -1 "$D58")" = "--- end" ] && ok "dm-diag file: json line, complete" || bad "dm-diag file"
        [ "$before" = "$(snapshot "$W/unit" | grep -v '/persist/pmcp/gem.log' | grep -v '/carplaymaps/logs/')" ] && ok "dm-diag writes only its log file" || bad "dm-diag changed other files"
        rm -rf "$W/lc58" "$W/lcm"; mkdir -p "$W/lc58/net" "$W/lcm"; ln -s "$W/unit" "$W/lc58/net/mmx"
        PMCP_LOGCARD_TEST_ROOT="$W/lc58" $SH "$PROJ/installer/logcard/pmcp-logs.sh" "$W/lcm" >/dev/null 2>&1
        cmp -s "$W/lcm/PMCP_LOGS/dm-diag-1.txt" "$D58" && grep -q "RESULT=OK .*dm_diag=1" "$W/lcm/PMCP_LOGS/PMCP_LOGS_RESULT.txt" \
            && ok "log card copies dm-diag-1.txt" || bad "log card: dm-diag"
        run log-clear; rc_is 0; [ ! -e "$D58" ] && ok "main menu 9 deletes it" || bad "log-clear left dm-diag"
        run dm-path factory; rc_is 0; expect_out "PMCP_DM_PATH_OK path=factory (from the next unit start)" "dm-path factory"
        [ "$(h "$DMJF")" = $DMF ] && [ ! -e "$U/carplaymaps/rollback/displaymanager.json" ] && ok "factory json back, copy removed" || bad "dm-path factory files"
        run dm-path factory; rc_is 0; expect_out "path=factory (already, nothing changed)" "dm-path factory again: already"
        run dm-path pmcp; rc_is 0
        cp "$W/sd/payload/dm/displaymanager.json" "$W/dm.bak"; printf 'X' >> "$W/sd/payload/dm/displaymanager.json"
        run dm-path factory; rc_is 0; run dm-path pmcp; rc_is 1; expect_out "HASH_MISMATCH_DM_JSON" "corrupted payload: refused"
        [ "$(h "$DMJF")" = $DMF ] && ok "corrupted payload: factory json stays" || bad "corrupted payload changed json"
        cp "$W/dm.bak" "$W/sd/payload/dm/displaymanager.json"
        run dm-path pmcp; rc_is 0
        restore_exact "restore after dm-path pmcp: exact factory tree"
        start_unit; run map-install map-square-fps40; run java-on nai
        echo "changed by someone else" >> "$DMJF"
        run dm-path pmcp; rc_is 1; expect_out "DM_JSON_NOT_FACTORY_NOTHING_CHANGED_other" "foreign json: dm-path pmcp refused"
        run dm-path factory; rc_is 1; expect_out "DM_JSON_NOT_OURS_NOTHING_CHANGED" "foreign json: dm-path factory refused"
    else
        ls "$SDB/pmcp/menu" | grep -q '^dm-' && bad "release card has dm buttons" || ok "release card: no dm buttons"
        start_unit; run map-install map-square-fps40; rc_is 0
        run dm-path pmcp; rc_is 1; expect_out "PMCP_FAIL=UNKNOWN_ACTION_dm-path" "release card: no dm-path action"
        [ ! -e "$SDB/pmcp/payload/dm" ] && ok "release card: no encoder json payload" || bad "release card carries dm payload"
    fi

    # WL project's HMI hook (A220): experimental cards only, a regular Java package, not in main menu 4
    echo "[59] package wl (WL HMI hook): experimental cards only, not in main 4, own JAR, full Java lifecycle"
    if [ -n "$(jsha wl)" ]; then
        WL=$(jid wl); WLF=$(jf wl)
        [ "$WLF" = "pmcp-wl-$(jsha wl | cut -c1-8).jar" ] && [ "$(h "$SDB/pmcp/payload/jars/$WLF")" = "$(jsha wl)" ] && ok "payload: $WLF" || bad "wl payload"
        grep -q 'java-on_wl' "$SDB/pmcp/menu/features-on.sh" && bad "wl in main menu 4" || ok "wl is not in main menu 4"
        [ -f "$SDB/pmcp/menu/java-on-wl.sh" ] && [ -f "$SDB/pmcp/menu/java-off-wl.sh" ] && ok "wl on/off buttons" || bad "wl buttons"
        start_unit; run map-install map-square-fps40; rc_is 0; run java-on nai; rc_is 0
        run java-on wl; rc_is 0; expect_out "PMCP_JAVA_ON_OK package=wl set=$NAI+$WL" "java-on wl: set nai+wl"
        [ -f "$U/eso/hmi/lsd/jars/$WLF" ] && ok "wl JAR on the unit" || bad "wl JAR missing"
        o=$(unit_boot); case "$o" in "boot=trial set=$NAI+$WL jars="*"/X/lsd/jars/$WLF") ok "next start: trial, wl loaded last" ;; *) bad "boot: $o" ;; esac
        run java-confirm; rc_is 0
        run java-off wl; rc_is 0; [ ! -e "$U/eso/hmi/lsd/jars/$WLF" ] && [ "$(cut -d' ' -f1 "$U/carplaymaps/HMI_BOOT")" = "$NAI" ] \
            && ok "java-off wl: JAR removed, set nai" || bad "java-off wl"
        run java-on wl; rc_is 0
        restore_exact "restore with wl: exact factory tree"
    else
        ls "$SDB/pmcp/menu" | grep -q 'java-on-wl' && bad "release card has wl buttons" || ok "release card: no wl buttons"
        grep -q '^JAR_wl ' "$SDB/pmcp/pmcp.sh" && bad "release card carries the wl JAR" || ok "release card: no wl JAR"
    fi

    [ -s "$W/noexec" ] && { bad "pmcp.sh called a command the unit does not have ($(wc -l < "$W/noexec" | tr -d ' ') runs)"; sort -u "$W/noexec" | head -5 | sed 's/^/       | /'; } \
        || ok "no run of this card's pmcp.sh called a command missing on the unit (printf, tr, cut)"
done

rm -rf "$W"
[ "$SKIPS" = 0 ] || echo "SKIPPED (earlier cards not present, update tests only): $SKIPS"
echo "FAILED CHECKS: $FAILS"
[ $FAILS -gt 255 ] && exit 255   # an exit status wraps at 256
exit $FAILS
