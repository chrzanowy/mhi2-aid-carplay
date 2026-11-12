# Sourced by run_tests.sh and fault_inject.sh (needs pf, BK, PMCP_PROFILE): which lsd.sh state the fake unit starts in.
#   PMCP_TEST_LSD_STATE=stock|toolbox_nai   default: toolbox_nai for a profile that has it (toolbox_nai in lsd_sh_states), else stock
# stock = the factory lsd.sh and no Toolbox jar; toolbox_nai = the unit as the M.I.B. backup of such a unit has it (lsd.sh with
# MIB Toolbox's NavActiveIgnore line, jars/NavActiveIgnore.jar of Toolbox).
HAS_TBX=no
case " $(pf lsd_sh_states | tr '\n' ' ')" in *" toolbox_nai "*) HAS_TBX=yes ;; esac
LSD_TEST_STATE="${PMCP_TEST_LSD_STATE:-$([ $HAS_TBX = yes ] && echo toolbox_nai || echo stock)}"
case "$LSD_TEST_STATE" in stock) ;; toolbox_nai) [ $HAS_TBX = yes ] || { echo "profile $PMCP_PROFILE has no toolbox_nai state"; exit 99; } ;;
    *) echo "PMCP_TEST_LSD_STATE=$LSD_TEST_STATE unknown"; exit 99 ;; esac
# the file of the backup that holds the factory lsd.sh text (by hash, as build_sd.py does), and Toolbox's lsd.sh and jar
FACTORY_LSD_SRC=""
for _c in "$BK/eso/hmi/lsd/lsd.sh.bu" "$BK/eso/hmi/lsd/lsd.sh"; do
    [ -f "$_c" ] && [ "$(shasum -a 256 < "$_c" | cut -d' ' -f1)" = "$(pf stock.LSD | sed -n 2p)" ] && { FACTORY_LSD_SRC=$_c; break; }
done
TBX_JAR_NAME=""
if [ $HAS_TBX = yes ]; then TBX_JAR_NAME=$(pf toolbox_nai.jar | sed -n 1p); TBX_JAR_NAME=${TBX_JAR_NAME##*/}; fi
# the unit's lsd.sh and jars/ (U = the unit's mnt/app): the factory file, or Toolbox's with its jar
lsd_state_into_unit() {
    if [ "$LSD_TEST_STATE" = toolbox_nai ]; then
        cp "$BK/eso/hmi/lsd/lsd.sh" "$1/eso/hmi/lsd/lsd.sh"
        cp "$BK/eso/hmi/lsd/jars/"* "$1/eso/hmi/lsd/jars/"
    else
        [ -n "$FACTORY_LSD_SRC" ] || { echo "no factory lsd.sh in the backup $BK"; exit 99; }
        cp "$FACTORY_LSD_SRC" "$1/eso/hmi/lsd/lsd.sh"
        cp "$BK/eso/hmi/lsd/jars/"* "$1/eso/hmi/lsd/jars/"
        [ -z "$TBX_JAR_NAME" ] || rm -f "$1/eso/hmi/lsd/jars/$TBX_JAR_NAME"
    fi
}
