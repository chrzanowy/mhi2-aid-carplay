#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copy CARD 1 (install) or CARD 2 (rescue) from this package onto an EMPTY FAT32 SD card, then check every file.
# Never formats, never deletes anything that was on the card. Uses only tools built into macOS.
set -u
cd "$(dirname "$0")" || exit 1
HERE=$(pwd)
LOG="$HERE/copy-log-$(date +%Y%m%d-%H%M%S).txt"
exec > >(tee -a "$LOG") 2>&1

say()   { printf '%s\n' "$*"; }
ok()    { printf '  [ OK ] %s\n' "$*"; }
line()  { say "------------------------------------------------------------------------"; }
tty_read() { if { : < /dev/tty; } 2> /dev/null; then IFS= read -r REPLY < /dev/tty; else IFS= read -r REPLY; fi || REPLY=""; }
done_() { say ""; say "  Log saved to: $LOG"; printf '  Press Enter to close this window. '; tty_read; exit "$1"; }
fail()  {
    say ""; line
    say "  [STOP] $1"
    [ -n "${2:-}" ] && say "         $2"
    say "         Nothing on the card was deleted."
    line
    done_ 1
}
ask()   { printf '  ?  %s ' "$1"; tty_read; echo "     (answer: $REPLY)" >> "$LOG"; }
field() { diskutil info "$1" 2>/dev/null | sed -n "s/^ *$2: *//p" | head -1; }
SYSTEM='-name .fseventsd -o -name .Spotlight-V100 -o -name .Trashes -o -name .TemporaryItems -o -name System?Volume?Information'

# mounted FAT32 cards that hold FILE (cards are recognised by their content, not by name)
cards_with() {
    for v in /Volumes/*; do
        [ -e "$v/$1" ] || continue
        case "$(field "$v" 'File System Personality')" in *FAT32*) echo "$v" ;; esac
    done
}

wait_card() {   # wait_card FILE WHAT -> VOL
    while :; do
        ask "Insert $2 and wait until it shows in Finder, then press Enter."
        VOL=$(cards_with "$1" | head -1)
        [ -n "$VOL" ] && return
        say "    $2 was not found. Make sure it is inserted (and not another card)."
    done
}

unlock_flow() {
    say ""
    say "  Step 1 of 2: the rescue card test result"
    wait_card PMCP_RESCUE_MANIFEST.txt "CARD 2 (RESCUE), after the test in the car,"
    say "    card: $(basename "$VOL")"
    RLOG="$VOL/PMCP_RATUNEK_LOG.txt"
    [ -f "$RLOG" ] || fail "There is no test result on the rescue card yet." "Do step 1 of PART 2 in the car first (insert card 2, wait, Continue)."
    say "    last lines of the rescue log:"
    tail -n 4 "$RLOG" | tr -d '\r' | sed 's/^/      | /'
    if ! grep -q 'WYNIK=OK' "$RLOG" || ! tr -d '\r' < "$RLOG" | sed '/^$/d' | tail -n 1 | grep -q '=== PMCP RATUNEK koniec ==='; then
        fail "The rescue card test did NOT pass (no WYNIK=OK at the end of the log)." \
            "Do not unlock the features. Keep the log file PMCP_RATUNEK_LOG.txt and ask for help."
    fi
    ok "rescue test passed (WYNIK=OK)"
    if [ -f "$VOL/_Swdlautorun.txt" ] && [ ! -e "$VOL/Swdlautorun.txt" ]; then
        mv "$VOL/_Swdlautorun.txt" "$VOL/Swdlautorun.txt" || fail "Could not re-arm the rescue card." "Rename _Swdlautorun.txt to Swdlautorun.txt on the card yourself."
    fi
    [ -f "$VOL/Swdlautorun.txt" ] || fail "The rescue card has no autostart file." "Make CARD 2 again with option 2."
    sync
    ok "rescue card re-armed (it will start by itself again when inserted)"
    diskutil eject "$VOL" > /dev/null 2>&1 && ok "rescue card ejected. Keep it OUT of the car, label: RESCUE - DO NOT INSERT"
    say ""
    say "  Step 2 of 2: unlock the features on CARD 1"
    wait_card PMCP_CARD_MANIFEST.txt "CARD 1 (INSTALL)"
    say "    card: $(basename "$VOL")"
    [ -d "$VOL/pmcp" ] || fail "This card has no pmcp folder." "Make CARD 1 again with option 1."
    : > "$VOL/pmcp/ODBLOKUJ_ETAP_B" && [ -f "$VOL/pmcp/ODBLOKUJ_ETAP_B" ] || fail "Could not write to CARD 1." "Is the card locked (small switch on its side)?"
    rm -f "$VOL/pmcp/._ODBLOKUJ_ETAP_B"
    sync
    ok "features unlocked on CARD 1 (file pmcp/ODBLOKUJ_ETAP_B)"
    diskutil eject "$VOL" > /dev/null 2>&1 && ok "card ejected, you can remove it"
    say ""
    line
    say "  DONE. Next in the car: green menu -> pmcp_CarPlay_AID -> 3. Install all features."
    line
    done_ 0
}

say ""
say "  CarPlay map on the AID - SD card copy helper"
line
say "  What do you want to do?"
say "    2 = make CARD 2, RESCUE  (make this one first; only for emergencies, it starts by itself)"
say "    1 = make CARD 1, INSTALL (used from the green menu in the car)"
say "    3 = after the rescue card test in the car: check its result, re-arm it, unlock features on CARD 1"
ask "Type 1, 2 or 3 and press Enter:"
[ "$REPLY" = 3 ] && unlock_flow
case "$REPLY" in
    1) SRC="$HERE/card1-install"; MAN=PMCP_CARD_MANIFEST.txt; NAME="CARD 1 (INSTALL)"; LABEL="INSTALL" ;;
    2) SRC="$HERE/card2-rescue";  MAN=PMCP_RESCUE_MANIFEST.txt; NAME="CARD 2 (RESCUE)"; LABEL="RESCUE - DO NOT INSERT" ;;
    *) fail "Please type 1, 2 or 3." "Start the helper again." ;;
esac
[ -f "$SRC/$MAN" ] || fail "The folder $(basename "$SRC") is missing next to this helper." "Unpack the whole zip first, then start the helper from the unpacked folder."

# manifest lines: <sha256>  <size>  <path>; card 1's first line is the build name
LIST=$(mktemp -t pmcp-list)
sed -n 's/^\([0-9a-f]\{64\}\)  *\([0-9][0-9]*\)  \(.*\)$/\1 \2 \3/p' "$SRC/$MAN" > "$LIST"
COUNT=$(wc -l < "$LIST" | tr -d ' ')
say ""
say "  Step 1 of 4: checking the files of $NAME in this package ($COUNT files)..."
bad=0
while read -r h s p; do
    [ "$(shasum -a 256 "$SRC/$p" 2>/dev/null | cut -d' ' -f1)" = "$h" ] || { say "    damaged or missing: $p"; bad=$((bad + 1)); }
done < "$LIST"
[ $bad -eq 0 ] || fail "$bad files in this package are damaged." "Download the zip again and unpack it again."
ok "all $COUNT files are complete"
NEED_KB=$(( $(awk '{s += $2} END {print s}' "$LIST") / 1024 + 4096 ))

say ""
say "  Step 2 of 4: choose the SD card"
while :; do
    ask "Insert an EMPTY SD card (FAT32) for $NAME, wait until it shows in Finder, then press Enter."
    CARDS=""
    for v in /Volumes/*; do
        [ -d "$v" ] || continue
        [ "$(field "$v" 'Mount Point')" = / ] && continue
        case "$(field "$v" 'File System Personality')" in *FAT32*) ;; *) continue ;; esac
        case "$(field "$v" 'Removable Media')/$(field "$v" 'Device Location')" in Removable/*|*/External) ;; *) continue ;; esac
        CARDS="$CARDS$v
"
    done
    CARDS=$(printf '%s' "$CARDS" | sed '/^$/d')
    [ -n "$CARDS" ] && break
    say "    No FAT32 SD card found. Cards in other formats are not shown."
    say "    To format a card (this ERASES it): Disk Utility -> select the card -> Erase ->"
    say "    Format \"MS-DOS (FAT)\", Scheme \"Master Boot Record\"."
done
N=$(printf '%s\n' "$CARDS" | wc -l | tr -d ' ')
if [ "$N" = 1 ]; then
    VOL=$CARDS
else
    i=0
    while read -r v; do i=$((i + 1)); say "    $i) $(basename "$v")  ($(field "$v" 'Disk Size' | cut -d'(' -f1))"; done <<< "$CARDS"
    ask "Type the number of the card:"
    VOL=$(sed -n "${REPLY}p" <<< "$CARDS" 2>/dev/null)
    [ -n "$VOL" ] || fail "No card with that number."
fi
DEV=$(field "$VOL" 'Device Identifier')
SIZE=$(field "$VOL" 'Disk Size' | cut -d'(' -f1)
say "    card: $(basename "$VOL")  ($SIZE, FAT32, device $DEV)"
OTHER=$(cd "$VOL" && eval "find . -mindepth 1 \\( $SYSTEM \\) -prune -o -print" | head -1)
[ -z "$OTHER" ] || fail "The card $(basename "$VOL") is not empty (for example: ${OTHER#./})." \
    "Use an empty card, or copy its files somewhere safe and erase it in Disk Utility."
FREE_KB=$(df -Pk "$VOL" | awk 'NR==2 {print $4}')
[ "$FREE_KB" -gt "$NEED_KB" ] || fail "The card is too small ($((FREE_KB / 1024)) MB free, $((NEED_KB / 1024)) MB needed)."
ok "the card is empty and large enough"
ask "Copy $NAME to the card '$(basename "$VOL")'? Type YES to continue:"
[ "$REPLY" = YES ] || [ "$REPLY" = yes ] || fail "Not confirmed." "Start the helper again when you are ready."

say ""
say "  Step 3 of 4: copying $COUNT files (the card's autostart file, if any, is copied last)..."
i=0
copy() {
    mkdir -p "$VOL/$(dirname "$1")" && cp -X "$SRC/$1" "$VOL/$1.pmcp-tmp" && mv -f "$VOL/$1.pmcp-tmp" "$VOL/$1" \
        || fail "Copying $1 failed." "The card may be full, locked or faulty. Do not use it in the car."
}
while read -r h s p; do
    [ "$p" = Swdlautorun.txt ] && continue
    copy "$p"; i=$((i + 1))
    [ $((i % 50)) -eq 0 ] && say "    $i / $COUNT"
done < "$LIST"
grep -q ' Swdlautorun.txt$' "$LIST" && copy Swdlautorun.txt
copy "$MAN"
# macOS adds hidden "._" files on FAT cards; the card was empty, so every one of them is ours
eval "find \"\$VOL\" \\( $SYSTEM \\) -prune -o -name '._*' -type f -print" | while read -r f; do rm -f "$f"; done
sync
ok "copied"

say ""
say "  Step 4 of 4: checking every file on the card (read back from the card itself)..."
diskutil unmount "$VOL" > /dev/null 2>&1 || fail "Could not unmount the card for the check." "Close any Finder window showing the card and start again."
diskutil mount "$DEV" > /dev/null 2>&1 || fail "Could not mount the card again." "Remove and re-insert the card, then start the helper again."
VOL=$(field "$DEV" 'Mount Point')
bad=0
while read -r h s p; do
    [ "$(shasum -a 256 "$VOL/$p" 2>/dev/null | cut -d' ' -f1)" = "$h" ] || { say "    differs on the card: $p"; bad=$((bad + 1)); }
done < "$LIST"
cmp -s "$SRC/$MAN" "$VOL/$MAN" || bad=$((bad + 1))
JUNK=$(eval "find \"\$VOL\" \\( $SYSTEM \\) -prune -o -name '._*' -print" | head -3)
[ -z "$JUNK" ] || { say "    hidden macOS files left: $JUNK"; bad=$((bad + 1)); }
[ $bad -eq 0 ] || fail "$bad files on the card are wrong." "Do NOT use this card in the car. Try another card."
ok "all $COUNT files on the card are correct"
diskutil eject "$VOL" > /dev/null 2>&1 && ok "card ejected, you can remove it" || say "    Eject the card in Finder before removing it."
rm -f "$LIST"

say ""
line
say "  DONE: $NAME is ready. Write on it:  $LABEL"
if [ "$LABEL" = INSTALL ]; then
    say "  Next: follow PART 2 in README-FIRST.txt (start with the rescue card test)."
else
    say "  Next: start this helper again and make CARD 1 (INSTALL)."
fi
line
done_ 0
