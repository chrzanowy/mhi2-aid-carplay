#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Host tests of the MOST bridge contract kit. Needs: cc, sh, awk, sed, grep.
# All state lives in one mktemp directory that is removed at the end.
HERE=$(cd "$(dirname "$0")" && pwd)
K=$(dirname "$HERE")
T=$(mktemp -d "${TMPDIR:-/tmp}/pmcp-contract.XXXXXX") || exit 2
PIDS=""
NOK=0
NBAD=0

cleanup() {
    for p in $PIDS; do kill "$p" 2>/dev/null; done
    rm -rf "$T"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

ok()  { NOK=$((NOK + 1)); echo "  ok   $1"; }
bad() { NBAD=$((NBAD + 1)); echo "  FAIL $1"; }
check() { # check "name" command...
    name=$1; shift
    if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi
}

# newenv NAME: fresh src dir / ring / idr marker for one test
newenv() {
    E=$T/$1
    mkdir -p "$E"
    D=$E/most-src
    R=$E/ring.bin
    I=$E/idr.request
    PMCP_MOST_SRC_DIR=$D
    PMCP_MOST_RING=$R
    PMCP_MOST_IDR=$I
    export PMCP_MOST_SRC_DIR PMCP_MOST_RING PMCP_MOST_IDR
}

waitgrep() { # waitgrep FILE PATTERN SECONDS
    n=0
    max=$(($3 * 20))
    while [ $n -lt $max ]; do
        grep -q "$2" "$1" 2>/dev/null && return 0
        sleep 0.05
        n=$((n + 1))
    done
    return 1
}

bg() { # bg LOGFILE cmd...   (sets BGPID)
    log=$1; shift
    "$@" >"$log" 2>&1 &
    BGPID=$!
    PIDS="$PIDS $BGPID"
}

tval() { # tval FILE EVENTPATTERN -> value of t= on the first matching line
    grep "$2" "$1" | head -n 1 | sed -n 's/.* t=\([0-9]*\)$/\1/p'
}

kvof() { # kvof FILE KEY -> value of KEY= in first line
    head -n 1 "$1" | tr ' ' '\n' | sed -n "s/^$2=//p"
}

CFLAGS="-std=c99 -Wall -Wextra -Werror -pedantic -O2 -I$K"
BIN=$T/bin
mkdir -p "$BIN"

echo "== build"
check "library compiles (-std=c99 -Wall -Wextra -Werror -pedantic)" \
    cc $CFLAGS -c "$K/pmcp_most_producer.c" -o "$BIN/lib.o"
check "fake_consumer builds" cc $CFLAGS "$K/fake_consumer.c" "$K/pmcp_most_producer.c" -o "$BIN/fake_consumer"
check "example_producer builds" cc $CFLAGS "$K/example_producer.c" "$K/pmcp_most_producer.c" -o "$BIN/example_producer"
check "test_unit builds" cc $CFLAGS "$HERE/test_unit.c" "$K/pmcp_most_producer.c" -o "$BIN/test_unit"
check "library also builds with -O0 -g" cc -std=c99 -Wall -Wextra -Werror -pedantic -O0 -g -I"$K" -c "$K/pmcp_most_producer.c" -o "$BIN/lib0.o"
cat >"$T/hdr.c" <<'EOT'
#include <stdio.h>
#include "pmcp_most_contract.h"
int main(void) { puts(PMCP_MOST_SRC_DIR_DEFAULT); puts(pmcp_most_src_dir()); puts(pmcp_most_ring_path()); return 0; }
EOT
check "header alone compiles" cc $CFLAGS "$T/hdr.c" -o "$BIN/hdr"
check "base dir macro override" sh -c "cc $CFLAGS -DPMCP_MOST_BASE_DIR='\"/xyz\"' '$T/hdr.c' -o '$BIN/hdr2' && [ \"\$('$BIN/hdr2' | head -n 1)\" = /xyz/most-src ]"
check "env override of src dir and ring path" sh -c "[ \"\$(PMCP_MOST_SRC_DIR=/a PMCP_MOST_RING=/b '$BIN/hdr' | tail -n 2 | tr '\\n' ' ')\" = '/a /b ' ]"
[ -x "$BIN/fake_consumer" ] && [ -x "$BIN/example_producer" ] && [ -x "$BIN/test_unit" ] || {
    echo "build failed, cannot continue"
    echo "CONTRACT TESTS: $NOK ok, $((NBAD + 1)) failed"
    exit 1
}

echo "== unit (parser, owner rules, session, limits)"
newenv unit
"$BIN/test_unit" unit "$D" >"$T/unit.out" 2>&1
while read -r line; do
    case $line in
        ok:*) ok "${line#ok: }" ;;
        FAIL:*) bad "${line#FAIL: }" ;;
    esac
done <"$T/unit.out"
[ -s "$T/unit.out" ] || bad "unit produced no output"

echo "== end to end: example_producer -> ring -> fake_consumer"
newenv e2e
bg "$T/e2e.cons" "$BIN/fake_consumer" --duration 20
CP=$BGPID
waitgrep "$T/e2e.cons" "event=start" 5 || bad "consumer started"
"$BIN/example_producer" --src wired --fps 60 --frames 120 >"$T/e2e.prod" 2>&1
check "producer exit 0" grep -q "event=stopped why=done frames=120" "$T/e2e.prod"
waitgrep "$T/e2e.cons" "state=stop" 3
sleep 0.3
kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
check "consumer got config" grep -q "^config seq=1 .*nal_len=4 sps=1" "$T/e2e.cons"
check "consumer got exactly 120 frames" test "$(grep -c '^frame ' "$T/e2e.cons")" -eq 120
check "no drops, no bad frames" sh -c "! grep -q 'event=drop\\|bad-frame\\|bad-config' '$T/e2e.cons'"
check "first frame is a keyframe, others not" sh -c "[ \"\$(grep '^frame ' '$T/e2e.cons' | head -n 1 | grep -c 'key=1')\" = 1 ] && [ \"\$(grep -c '^frame .*key=1' '$T/e2e.cons')\" = 1 ]"
check "consumer saw session start and stop (reason=done)" sh -c "grep -q 'event=session src=wired state=start' '$T/e2e.cons' && grep -q 'event=session src=wired state=stop gen=1 reason=done' '$T/e2e.cons'"
check "stop ends the stream (stream-end)" grep -q "event=stream-end src=wired" "$T/e2e.cons"
check "owner released at exit" test ! -e "$D/owner"
check "consumer wrote ready=0 on exit" grep -q "ready=0" "$D/consumer"
check "frame timestamps are NTP (seconds > 3.9e9)" sh -c "grep '^frame ' '$T/e2e.cons' | head -n 1 | sed -n 's/.* ts=\\([0-9]*\\)\\..*/\\1/p' | awk '{exit !(\$1 > 3900000000)}'"

echo "== wired preempts wireless"
newenv pre
bg "$T/pre.cons" "$BIN/fake_consumer" --duration 20
CP=$BGPID
waitgrep "$T/pre.cons" "event=start" 5
bg "$T/pre.wl" "$BIN/example_producer" --src wireless --fps 60 --duration 8
WP=$BGPID
waitgrep "$T/pre.cons" "^frame seq=10 " 5 || bad "wireless streaming before preemption"
"$BIN/example_producer" --src wired --fps 60 --frames 60 >"$T/pre.wd" 2>&1
wait "$WP" 2>/dev/null
tw=$(tval "$T/pre.wd" "event=acquired")
tp=$(tval "$T/pre.wl" "event=preempted")
tl=$(sed -n 's/.*last_frame_t=\([0-9]*\) .*/\1/p' "$T/pre.wl")
check "wired acquired owner while wireless was live (gen 2)" grep -q "event=acquired src=wired gen=2 " "$T/pre.wd"
check "wireless noticed preemption within 100 ms" test -n "$tw" -a -n "$tp" -a $((tp - tw)) -le 100
check "wireless last ring write within 100 ms of takeover" test -n "$tl" -a $((tl - tw)) -le 100
check "wireless exit reason is preempted" grep -q "event=stopped why=preempted" "$T/pre.wl"
check "wireless session file says state=stop reason=preempted" sh -c "grep -q 'state=stop' '$D/wireless.session' && grep -q 'reason=preempted' '$D/wireless.session'"
check "wireless exit did not remove the wired owner" sh -c "grep -q 'event=stopped' '$T/pre.wd' && grep -q 'event=preempted' '$T/pre.wl'"
check "wired streamed its 60 frames" grep -q "event=stopped why=done frames=60" "$T/pre.wd"
sleep 0.3
kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
check "consumer saw wireless stop but kept the wired stream" sh -c "grep -q 'event=session src=wireless state=stop' '$T/pre.cons' && ! grep -q 'stream-end src=wireless' '$T/pre.cons'"
check "owner free after wired exit" test ! -e "$D/owner"

echo "== owner: dead pid, live pid, gen"
newenv own
"$BIN/test_unit" deaddir "$D" 7 wireless
"$BIN/example_producer" --src wireless --frames 3 --create-ring >"$T/own.a" 2>&1
check "dead-pid owner taken over, gen = 7+1" grep -q "event=acquired src=wireless gen=8 " "$T/own.a"
check "owner file removed after clean exit" test ! -e "$D/owner"
"$BIN/test_unit" deaddir "$D" 4294967295 aa
"$BIN/example_producer" --src aa --frames 3 >"$T/own.b" 2>&1
check "gen wraps past 0 (0xFFFFFFFF -> 1)" grep -q "event=acquired src=aa gen=1 " "$T/own.b"
sleep 30 &
LP=$!
PIDS="$PIDS $LP"
"$BIN/test_unit" putowner "$D" wireless "$LP" 3
"$BIN/example_producer" --src aa --frames 3 >"$T/own.c" 2>&1; rc=$?
check "live owner => busy (exit 3), owner file untouched" sh -c "[ $rc = 3 ] && grep -q 'event=busy' '$T/own.c' && grep -q 'pid=$LP gen=3' '$D/owner'"
"$BIN/example_producer" --src wired --frames 3 >"$T/own.d" 2>&1
check "wired takes a live wireless owner, gen 3+1" grep -q "event=acquired src=wired gen=4 " "$T/own.d"
kill "$LP" 2>/dev/null

echo "== v1.1: old v1 owner line (no kind) still works"
newenv v1
mkdir -p "$D"
printf 'v=1 src=wireless pid=%s gen=5 since_ms=1\n' "$$" >"$D/owner"
"$BIN/test_unit" owner-show "$D" >"$T/v1.show" 2>&1
check "v1 owner line without kind parses (src pid gen)" grep -q "^wireless $$ 5$" "$T/v1.show"
"$BIN/example_producer" --src aa --frames 3 --create-ring >"$T/v1.a" 2>&1; rc=$?
check "v1 line without kind (live pid, old since_ms, no session) = stale in-kind owner, taken by aa gen 6" sh -c "[ $rc = 0 ] && grep -q 'event=acquired src=aa gen=6 ' '$T/v1.a'"

echo "== v1.1: two concurrent takers on a dead owner (200 rounds)"
newenv race
"$BIN/test_unit" race "$D" 200 >"$T/race.out" 2>&1
while read -r line; do
    case $line in
        ok:*) ok "${line#ok: }" ;;
        FAIL:*) bad "${line#FAIL: }" ;;
    esac
done <"$T/race.out"
[ -s "$T/race.out" ] || bad "race produced no output"

echo "== v1.1: proxy owner preempted by wired, consumer cuts the old writer"
newenv prx
bg "$T/prx.cons" "$BIN/fake_consumer" --duration 25
CP=$BGPID
waitgrep "$T/prx.cons" "event=start" 5
bg "$T/prx.supa" "$BIN/test_unit" supervisor "$D" wireless proxy 15000
SA=$BGPID
waitgrep "$T/prx.supa" "event=acquired" 5 || bad "proxy supervisor A acquired"
bg "$T/prx.wra" "$BIN/test_unit" rawwriter "$R" 0 1 "$E/stopA" 15000 100
WA=$BGPID
waitgrep "$T/prx.cons" "^frame seq=[0-9]* size=104 " 5 || bad "old proxy writer reaches the consumer"
check "owner line says kind=proxy" grep -q " kind=proxy" "$D/owner"
bg "$T/prx.supb" "$BIN/test_unit" supervisor "$D" wired proxy 3000
SB=$BGPID
waitgrep "$T/prx.supb" "event=acquired" 5 || bad "wired supervisor acquired over wireless proxy"
waitgrep "$T/prx.cons" "event=owner-cut" 3 || bad "consumer cut on owner gen change"
sleep 0.6   # grace: the old writer (core.so) keeps writing
touch "$E/stopA"
sleep 0.3
bg "$T/prx.wrb" "$BIN/test_unit" rawwriter "$R" 0 1 - 1500 200
WB=$BGPID
waitgrep "$T/prx.cons" "^frame seq=[0-9]* size=204 " 5 || bad "new writer frames accepted"
sleep 0.5
check "wireless supervisor noticed preemption" grep -q "event=preempted" "$T/prx.supa"
check "owner cut reported once" test "$(grep -c 'event=owner-cut' "$T/prx.cons")" -eq 1
nold=$(grep -c "event=drop reason=owner-cut .*size=104" "$T/prx.cons")
check "old writer frames written during the grace were dropped ($nold)" test "$nold" -ge 5
check "no old-writer frame reaches the output after the cut" sh -c "awk '/event=owner-cut/ {f=1} f && /^frame .*size=104 / {n++} END {exit n > 0}' '$T/prx.cons'"
check "nothing passes between the cut and the new avcC" sh -c "awk '/event=owner-cut/ {f=1} f && /^config / {exit 0} f && /^frame / {exit 1}' '$T/prx.cons'"
nnew=$(grep -c "^frame .*size=204 " "$T/prx.cons")
check "new writer frames accepted after its avcC ($nnew)" test "$nnew" -ge 20
check "ring generation bumped by the cut" sh -c "grep -q 'event=owner-cut owner_gen=2 ring_gen=2 kind=proxy' '$T/prx.cons'"
kill "$CP" "$SA" "$SB" "$WA" "$WB" 2>/dev/null; wait 2>/dev/null

echo "== v1.1: gate holds while the old proxy writer is alive"
newenv gh1
bg "$T/gh1.cons" "$BIN/fake_consumer" --duration 25
CP=$BGPID
waitgrep "$T/gh1.cons" "event=start" 5
bg "$T/gh1.za" "$BIN/test_unit" zombie "$D" wireless "$R" 2500 100
ZA=$BGPID
waitgrep "$T/gh1.za" "event=acquired" 5 || bad "old proxy writer acquired"
waitgrep "$T/gh1.cons" "^frame seq=[0-9]* size=104 " 5 || bad "old proxy writer reaches the consumer"
bg "$T/gh1.supb" "$BIN/test_unit" supervisor "$D" wired proxy 6000
SB=$BGPID
waitgrep "$T/gh1.supb" "event=acquired" 5 || bad "wired supervisor acquired"
bg "$T/gh1.wrb" "$BIN/test_unit" rawwriter "$R" 0 1 - 4500 200
WB=$BGPID
waitgrep "$T/gh1.cons" "event=gate-open" 6 || bad "gate opened after the old writer exited"
sleep 0.6
tdone=$(tval "$T/gh1.za" "event=writer-done")
topen=$(tval "$T/gh1.cons" "event=gate-open")
check "new avcC was held while the old writer lived (gate-held drop)" grep -q "event=drop reason=gate-held" "$T/gh1.cons"
check "no frame at all between the cut and the gate opening" sh -c "awk '/event=owner-cut/ {f=1} /event=gate-open/ {f=0} f && /^frame / {n++} END {exit n > 0}' '$T/gh1.cons'"
check "no old-writer frame ever reaches the output after the cut" sh -c "awk '/event=owner-cut/ {f=1} f && /^frame .*size=104 / {n++} END {exit n > 0}' '$T/gh1.cons'"
check "gate opened right after the old pid exited (reason=pid-exit, <= 300 ms)" sh -c "grep -q 'event=gate-open reason=pid-exit gate_forced=0' '$T/gh1.cons' && [ -n '$tdone' ] && [ -n '$topen' ] && [ $topen -ge $tdone ] && [ $((topen - tdone)) -le 300 ]"
check "held avcC emitted when the gate opened (new source did not resend)" sh -c "awk '/event=gate-open/ {f=1; next} f && /^config / {exit 0} f && /^frame / {exit 1}' '$T/gh1.cons'"
check "new writer frames accepted after the gate opened" test "$(grep -c '^frame .*size=204 ' "$T/gh1.cons")" -ge 20
kill "$CP" "$ZA" "$SB" "$WB" 2>/dev/null; wait 2>/dev/null

echo "== v1.1: old writer that never exits, gate forced at 3000 ms"
newenv gh2
bg "$T/gh2.cons" "$BIN/fake_consumer" --duration 25
CP=$BGPID
waitgrep "$T/gh2.cons" "event=start" 5
bg "$T/gh2.za" "$BIN/test_unit" zombie "$D" wireless "$R" 20000 100
ZA=$BGPID
waitgrep "$T/gh2.za" "event=acquired" 5 || bad "old proxy writer acquired"
waitgrep "$T/gh2.cons" "^frame seq=[0-9]* size=104 " 5 || bad "old proxy writer reaches the consumer"
bg "$T/gh2.supb" "$BIN/test_unit" supervisor "$D" wired proxy 9000
SB=$BGPID
waitgrep "$T/gh2.supb" "event=acquired" 5 || bad "wired supervisor acquired"
bg "$T/gh2.wrb" "$BIN/test_unit" rawwriter "$R" 0 1 - 7000 200
WB=$BGPID
waitgrep "$T/gh2.cons" "event=gate-open" 8 || bad "gate forced open"
sleep 0.5
tcut=$(tval "$T/gh2.cons" "event=owner-cut")
topen=$(tval "$T/gh2.cons" "event=gate-open")
check "forced open reported with gate_forced=1" grep -q "event=gate-open reason=forced gate_forced=1" "$T/gh2.cons"
check "gate opened at 3000 ms after the cut (got $((topen - tcut)) ms)" sh -c "[ -n '$tcut' ] && [ -n '$topen' ] && [ $((topen - tcut)) -ge 3000 ] && [ $((topen - tcut)) -le 3300 ]"
check "nothing passed between the cut and the forced open" sh -c "awk '/event=owner-cut/ {f=1} /event=gate-open/ {f=0} f && /^frame / {n++} END {exit n > 0}' '$T/gh2.cons'"
check "held avcC emitted at the forced open" sh -c "awk '/event=gate-open/ {f=1; next} f && /^config / {exit 0} f && /^frame / {exit 1}' '$T/gh2.cons'"
check "new writer frames accepted after the forced open" test "$(grep -c '^frame .*size=204 ' "$T/gh2.cons")" -ge 20
kill "$CP" "$ZA" "$SB" "$WB" 2>/dev/null; wait 2>/dev/null

echo "== IDR marker"
newenv idr
bg "$T/idr.cons" "$BIN/fake_consumer" --idr-every 1 --duration 20
CP=$BGPID
waitgrep "$T/idr.cons" "event=start" 5
"$BIN/example_producer" --src wired --fps 30 --duration 4 --gop 0 >"$T/idr.prod" 2>&1
sleep 0.2
kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
ncons=$(grep -c "event=idr-consumed" "$T/idr.prod")
check "producer consumed >= 3 IDR markers (got $ncons)" test "$ncons" -ge 3
viol=$(awk '/event=idr-consumed/ {w=1; next} /^frame / { if (w && $3 != "key=1") v++; if (!w && $3 == "key=1" && n++ > 0) v++; w=0 } END {print v+0}' "$T/idr.prod")
check "frame right after each IDR marker is a keyframe, no other keyframes (gop 0)" test "$viol" -eq 0
nkey=$(grep -c "^frame .*key=1" "$T/idr.cons")
check "consumer sees $nkey keyframes = 1 + markers" test "$nkey" -eq $((ncons + 1))
check "marker file consumed (not left behind by producer)" sh -c "grep -c 'event=idr-request' '$T/idr.cons' | awk '{exit !(\$1 >= 3)}'"

echo "== consumer status file"
newenv st
bg "$T/st.cons" "$BIN/fake_consumer" --duration 6
CP=$BGPID
waitgrep "$T/st.cons" "event=start" 5
bg "$T/st.prod" "$BIN/example_producer" --src aa --fps 30 --duration 5
"$BIN/test_unit" status-watch "$D" 4 >"$T/st.out" 2>&1
while read -r line; do
    case $line in
        ok:*) ok "${line#ok: }" ;;
        FAIL:*) bad "${line#FAIL: }" ;;
    esac
done <"$T/st.out"
check "owner_gen reported while streaming" sh -c "grep -q 'owner_gen=[1-9]' '$D/consumer'"
wait "$CP" 2>/dev/null
check "status after run: ready=0 and frames > 0" sh -c "grep -q ' ready=0 ' '$D/consumer' && ! grep -q ' frames=0 ' '$D/consumer'"
check "status line <= 255 B" sh -c "[ \$(wc -c <'$D/consumer') -le 255 ]"
check "status first key is v=1" sh -c "head -c 4 '$D/consumer' | grep -q '^v=1 '"
check "ring_gen reported" grep -q "ring_gen=[1-9]" "$D/consumer"

echo "== atomic replace stress (reader never sees a partial line)"
newenv stress
"$BIN/test_unit" stress-writer "$D" 1 >/dev/null 2>&1
bg "$T/sw.out" "$BIN/test_unit" stress-writer "$D" 60000
SW=$BGPID
"$BIN/test_unit" stress-reader "$D" 60000 >"$T/sr.out" 2>&1
srrc=$?
cat "$T/sr.out" | sed 's/^/  /'
check "reader: every read was a complete, consistent line" test $srrc -eq 0
wait "$SW"
check "writer finished without error" test $? -eq 0

echo "== overrun: slow consumer loses frames, producer never blocks"
newenv ovr
bg "$T/ovr.cons" "$BIN/fake_consumer" --overrun-after 20 --stall-ms 1500 --duration 20
CP=$BGPID
waitgrep "$T/ovr.cons" "event=start" 5
s0=$(date +%s)
"$BIN/example_producer" --src wired --fps 100 --frames 300 >"$T/ovr.prod" 2>&1
s1=$(date +%s)
check "producer finished on time while consumer stalled" test $((s1 - s0)) -le 6
waitgrep "$T/ovr.cons" "event=exit" 1
sleep 0.5
kill "$CP" 2>/dev/null; wait "$CP" 2>/dev/null
check "consumer reported event=overrun" grep -q "event=overrun" "$T/ovr.cons"
check "consumer resumed after the overrun" sh -c "awk '/event=overrun/ {f=1} f && /^frame / {n++} END {exit !(n > 5)}' '$T/ovr.cons'"
check "overrun counted in status (overruns>=1)" sh -c "! grep -q ' overruns=0 ' '$D/consumer'"

echo "== ring generation"
newenv gen
"$BIN/fake_consumer" --duration 1 >"$T/g1.out" 2>&1
"$BIN/fake_consumer" --duration 1 >"$T/g2.out" 2>&1
g1=$(sed -n 's/.*ring_gen=\([0-9]*\).*/\1/p' "$T/g1.out" | head -n 1)
g2=$(sed -n 's/.*ring_gen=\([0-9]*\).*/\1/p' "$T/g2.out" | head -n 1)
check "new ring: generation 1, restart: +1 ($g1 -> $g2)" test "$g1" = 1 -a "$g2" = 2
"$BIN/test_unit" ring-gen "$R" 4294967295 >/dev/null
"$BIN/fake_consumer" --duration 1 >"$T/g3.out" 2>&1
check "generation wraps 0xFFFFFFFF -> 1 (0 skipped)" grep -q "ring_gen=1$" "$T/g3.out"
# producer re-sends config after the consumer bumped the generation
newenv gen2
bg "$T/g4.prod" "$BIN/example_producer" --src wireless --fps 50 --duration 5 --create-ring
GP=$BGPID
sleep 1
"$BIN/fake_consumer" --duration 2 >"$T/g4.cons" 2>&1
wait "$GP" 2>/dev/null
check "producer re-sent config after generation change" sh -c "grep -q '^config ' '$T/g4.cons' && awk '/^config / {f=1} f && /^frame / {n++} END {exit !(n > 10)}' '$T/g4.cons'"

echo "== wireless/aa/wired name checks"
newenv names
check "bad src rejected by the example (usage, exit 2)" sh -c "'$BIN/example_producer' --src bogus >/dev/null 2>&1; [ \$? = 2 ]"
check "missing ring without --create-ring is an error (exit 1)" sh -c "'$BIN/example_producer' --src aa --frames 1 >/dev/null 2>&1; [ \$? = 1 ]"

echo "CONTRACT TESTS: $NOK ok, $NBAD failed"
[ "$NBAD" -eq 0 ]
