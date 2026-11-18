# pmcp-most, stage 1: our build of the CarPlay MOST bridge

`altscreen-most-bridge` takes CarPlay cluster-map video from the AltScreen ring
(`/ramdisk/carplay-alt-ring.bin`, written by `core.so`). It packs the frames into MPEG-TS and writes them to MOST
`/dev/mlb/isoTX2` on the VW MHI2 head unit (QNX 6.5, armv7, MU1161, AID 791).

Stage 1 means two things:

- the open-source bridge of Tomasz Twardzicki, built with our toolchain;
- a few small additions, so that it can replace mathsls's closed binary under the unchanged mathsls supervisor.

Project plan and contract: `passat-mhi2-carplay/docs/23-wlasny-most.md`. The "Kontrakt v0.2" section is binding for
the file formats.

## Provenance and attribution

- **Source:** https://github.com/tomasz-twardzicki/MHI2-Carplay-Maps, branch `feature/mu1367-v1.5.0-e-android-auto`,
  commit `59d6a4e`, `MU1367/integration/src/runtime/vc-runtime/runtime/`.
- **Authors:** the original CarPlay Maps VC altscreen bridge is by **omonob**. The reclaim, the 2048-packet limit and
  the AA flag are by **Tomasz Twardzicki**. mathsls is credited for the ring/TS format (format only, no code).
- **Licence:** upstream is GNU GPL v3. The patched upstream files carry `SPDX-License-Identifier: GPL-3.0-only`, because
  upstream grants no "or later". Our new files (`src/pmcp_most.h`, `src/pmcp_gate.c`, `test/`, `build.sh`) are
  GPL-3.0-or-later.
- `upstream/` holds the verbatim files plus `PROVENANCE.json`: repository, commit, source path, sha256 and size of each
  file, and the licence.
  - Never edit `upstream/`.
  - The test suite checks the hashes.

## Layout

| Path | What |
|---|---|
| `upstream/` | verbatim import + `LICENSE` + `PROVENANCE.json` |
| `src/` | working copy: upstream files plus changes marked `pmcp:` (copy-with-markers, no patch series), the new `pmcp_most.h` and `pmcp_gate.c` (consumer gate, verbatim functions of the contract kit) |
| `build.sh` | QNX build (docker `qnx65-armv7-toolchain:8.5`, no network) |
| `test/` | host build + tests (`run_tests.sh`, `harness.py`, `producer.c`, `shim/`, `fake_dmdt.sh`) |
| `contract/` | contract kit; the bridge uses its header `pmcp_most_producer.h` and a verbatim copy of its gate functions |

### Patch discipline

- Only `src/altscreen_most_bridge.c` and `src/cpmap_resources.h` differ from upstream. The other four headers are
  byte-identical copies.
- Every changed hunk contains a `pmcp` marker. The test `provenance` enforces this.
- Review the changes with `diff -u upstream/altscreen_most_bridge.c src/altscreen_most_bridge.c` and
  `diff -u upstream/cpmap_resources.h src/cpmap_resources.h`.

## Differences from upstream

1. **Log** (`pmcp_log_init`, `pmcp_log_reserve`).
   - stderr is moved to `/ramdisk/pmcp-most/bridge.log` with `open` + `dup2`, the same effect as `freopen` but without
     losing stderr if the open fails. The directory is created when missing.
   - Override with env `PMCP_MOST_LOG`; `-` keeps the inherited stderr.
   - The cap is 64 KB. Before a line that would not fit, the file is renamed to `bridge.log.1` (one rotation) and a new
     file is started. The hook sits in `cpmap_log_fprintf`, under its mutex.
   - Why: the mathsls supervisor sends the bridge's stderr to `/dev/null` (stage0 section 8).
2. **Consumer status** `/ramdisk/most-src/consumer` (contract v0.2 section 3).
   - Key order: `v=1 ready pid owner_gen ring_gen seq frames drops overruns latency_resets age_ms queue_pkts queue_hi
     reclaims most_errno up_ms`.
   - Written every 1000 ms by the existing 1 ms reader loop: no new thread, and nothing in the writer thread.
   - Written with tmp + rename. Field limits are clamped as in contract v1.2 (at most 255 B; the pid is the full QNX pid, since stage 1c).
   - `ready=0` is written on exit.
   - Override the directory with env `PMCP_MOST_SRC_DIR`.
   - `ready` = isoTX2 open and START devctl returned 0. `most_errno` = the last MOST open/write errno.
   - `age_ms` = lateness of the last consumed frame. It is measured against the most punctual frame of the current ring
     generation, as local monotonic time minus the media NTP time. The ring carries no write time, so slow clock drift
     between the phone and the unit adds to it over long sessions.
3. **Session files** `/ramdisk/most-src/<src>.session` (section 2).
   - Polled every 100 ms. `<src>` comes from `owner`; if there is no owner file, the last source seen is used.
   - The stream ends at once, the same way as the supervisor's SIGTERM (`on_signal`, clean exit 0), when either:
     - the session says `state=stop` with the owner's `gen`; or
     - the file vanished after we saw `state=start`, and its pid is dead.
   - A stop whose `ts_ms` is older than the bridge's start is ignored and logged once. Otherwise a stale stop file would
     make the supervisor restart the bridge in a loop.
   - With no contract files the behaviour is exactly upstream.
4. `CPMAP_ANIMATION_STATE_DIR` defaults to `/nonexistent`, so the MU1367 Java UI state path is never read.
5. **No truncated frame after a queue reset** (`queue_discard_all`; a bug in upstream too).
   - The writer pops the queue packet by packet between PAT/PMT/PCR, so at a `latency-reset` (backlog > 2048), a
     `latency-resume-idr`, a ring-generation change or a reclaim resync it may already have sent the first packets of the
     oldest queued access unit. Upstream then dropped the rest: a truncated P-frame went to isoTX2 just before the
     discontinuity and the wait for the IDR.
   - Now the remaining packets of that AU (up to the next PUSI packet) stay in the queue; only whole AUs are dropped.
     Every push is one whole AU, so the head of the queue is either a PUSI packet or the tail of the AU being sent.
     The video CC therefore jumps only at the first AU after the reset, which carries the discontinuity flag.
   - Found by the flaky `force-idr` test: `ts_analyse` "AU 40: payload matches no input frame" (36 of the 550 packets of
     the first burst frame). Upstream build, same scenario: 4 of 30 runs; ours before the fix: 3 of 30. After the fix: 0 of 100,
     with the reset landing inside a frame in 19 of them (that frame went out whole).
6. Unchanged on purpose:
   - the AA flag `ALTSCREEN_AA_SINGLE_IDR` (off by default: CarPlay behaviour);
   - `TS_LOW_LATENCY_LIMIT_PACKETS 2048`;
   - the reclaim: ENOMEM → `dmdt dc 72` then `sc 4 72`, at most 3 times, within 180 s of boot;
   - the intro code (not used: the wrapper unsets `CARPLAY_CLUSTER_INTRO`);
   - argv, the binary name, signals and exit codes.

7. **Consumer gate, contract v1.1 (stage 1b)** (`pmcp_owner_poll`, `pmcp_gate_filter`, `pmcp_gate_tick` in
   `pmcp_most.h`; the gate itself is `src/pmcp_gate.c`).
   - `owner` is read every 20 ms from the reader loop (`v=1`, `src`, `gen`, `pid`, `kind`; missing kind = `in`). The
     writer thread is never involved.
   - The first owner seen in a run only records gen/pid/kind. A later different `gen` is a **cut**: the ring generation
     is bumped by the bridge (no foreign-generation handling follows), reading restarts at `cut_seq + 1`, queued whole
     AUs are discarded, the wait-for-keyframe state is entered, and the log gets `owner-cut` and `gate-closed`.
   - `cut_seq` is the ring `write_sequence` read at the **previous** owner poll (decision OQ3 (a)), so an avcC written
     between the owner change and the moment the bridge notices it still opens the gate. Video slots in the re-read
     range that went out before the cut are skipped, not sent twice.
   - While closed, every slot is a drop except a type-1 avcC written after the cut. It opens the gate at once if the
     previous owner's pid is gone; otherwise it is held until that pid exits or 100 ms (`in`) / 3000 ms (`proxy`) after
     the cut pass (`reason=forced`, `gate_forced` + 1). On opening the held avcC is applied and the IDR marker created;
     log `gate-open reason=… gate_forced=…` and `gate-stats cuts=… forced=… gate_drops=… wait_ms=…`.
   - The gate counters are **not** in the consumer status line: the line is already 255 B in the worst case, so
     `gate_cuts`/`gate_forced` would break the 255 B limit. They are in `bridge.log` only (also a `gate-stats` line at
     exit).
   - No owner file at all: no gate, upstream behaviour (`parity` test, ts_compare SAME).
   - Why a copy of the kit functions: the bridge links `src/pmcp_gate.c`, which holds `pmcp_pid_alive`,
     `pmcp_owner_preempt_ms` and the kit's "consumer gate" section byte for byte (the `provenance` test checks it).
     Linking the whole kit object adds six libc imports not proven on MU1161 (`link nanosleep strcpy strncpy strtoll
     strtoull`): ld 2.19 keeps the dynamic references even with `--gc-sections`.
8. **IDR request under congestion** (`writer_recovered_after_reset`, `PMCP_RECOVERY_FAST_STREAK_REQUIRED`).
   - After a latency reset the bridge asks for an IDR only when the writer has recovered: at least 8 blocks completed
     since the reset **and** a streak of fast (≤ 30 ms) MOST writes. Upstream required a streak of 8; any slow write
     reset it, so under congestion the request was never made and the map stayed frozen. Now one fast write is
     enough; the 8-blocks condition stays (blocks complete whatever their speed, so it cannot starve).
   - Analysis and fix by **diasdio** (omonob/MHI2-Carplay-Maps#1, binary patch `cmphi r3,#7` → `#0` at 0x4174 of the
     v1.x bridge); offsets and packaging by **ramasauskas** (`mu1367-791-artifact-fix`). diasdio's other bridge fix (no
     queue flush in a part-written AU) is item 5, found independently here.
   - Found by the new test, ours on top: once the IDR has been requested, the writer-recovered check is not repeated
     for the AUs that follow. Before, the requested IDR was dropped as "writer not recovered" whenever it arrived just
     after a slow write (streak 0), and no second request was ever made: the map stayed frozen (3 of 5 test runs with
     the streak-1 rule; with upstream's streak 8 the same trap exists, it is only reached less often).
9. **Logging for the car (stage 1c)**. The first car test (2026-11-16, audit A201) lost the cold-start flash: the
   64 KB log rotated in about two minutes.
   - `avcC ready` is logged only when the avcC changes, and once after a new ring generation or owner cut. The phone
     repeats the same avcC before every IDR (about every 5th frame), and logging each one filled the log. The repeats
     are counted (`pmcp avcc_repeats=…` at exit).
   - **Event file** `/ramdisk/pmcp-most/events.log` (next to the log; env `PMCP_MOST_EVENTS`, `-` = none). It is
     appended by every bridge run of this start and rotated like the log: a line that would take it past half of
     `PMCP_MOST_EVENTS_LIMIT` (64 KB) moves it to `events.log.1` first, so both files together stay within 64 KB
     and no file on `/ramdisk` only grows (user decision 2026-11-18; until then it stopped at 64 KB with
     `events-full`). Events are rare, so the cold start normally stays in the two files. A run that finds the file
     rotated by another run reopens it.
     - Every line: `boot_ms=` (monotonic, from unit start), `up_ms=` (from this bridge's start), `pid=`, then the event.
     - Events: `start`, `most-open` / `most-open-failed`, `most-error errno=`, `reclaim attempt=…`,
       `reclaim-not-attempted`, `reclaim-resync`, `latency-reset … queued= discarded=`, `idr-request`, `idr-resume`,
       `chain-gap`, `ring-overrun` and `frame-gap` (at most 40 of each per run), `ring-generation`, `owner-cut`,
       `gate-open`, `session-stop`, `avcC` (changed), `video-start`, `writer-stopped`, `exit` (counters).
     - `frame-gap`: a consumed video frame ≥ 250 ms after the previous one, with the gap in local time (`gap_ms`) and
       in the phone's media time (`media_ms`). The two together say whether the phone or the unit paused.
     - One `write()` per line on an `O_APPEND` file, under its own mutex. Only rare events, so the writer thread's
       ~8 ms MOST writes are unaffected.
   - Consumer `pid`: the full QNX pid. Contract v1.2 clamps it at 2147483647 instead of 9999999, which hid the real
     pid in the car. `most_errno` now goes down to -9999, so the worst-case line is exactly 255 B.
   - The installer copies `events.log.1` and `events.log` into the CarPlay log (before `bridge.log.1`), and "Bridge
     status" shows the last 15 lines of `events.log`. The file is in `/ramdisk`, so a unit restart removes it; it is not a persistent log.
10. **Thread priority (stage 2, 2026-11-18)**. After tomasz-twardzicki MU1367 v1.5.3, measured there in a car: with
    the reverse camera on, the CPU reaches 98-100 % for seconds; the navigation renderer threads run at 10, the
    priority the bridge inherited, so the bridge got no CPU long enough to overrun the ring (a resource manager serves
    a write at its client's priority, so devp-iso-mmx (16) ran our writes at 10 too). Stage 2 raises the main (ring
    reader) thread to 14 before MOST open, and checks the writer thread of `aa/most/most_writer.c` (default attributes,
    so it inherits 14) after every `most_start`, the reclaim included. Only raised, never lowered
    (`PMCP_MOST_PRIORITY`, 0 = off). Logged as `priority thread=main|writer before= target= policy= status=` in
    `bridge.log` and `events.log`. `aa/` is not changed; the AA feeder does the same in its own code (AA session).

## Build (QNX)

```sh
bridge/build.sh OUTDIR            # PMCP_MOST_AA=1 also builds the AA variant
```

- gcc 8.5 from the image; flags `-O2 -Wall -Wextra -Werror -Wno-unused-function -std=gnu99 -march=armv7-a
  -mfloat-abi=softfp -mfpu=vfpv3-d16 -ffile-prefix-map`; linked with `-lsocket` like mathsls's binary.
- The script builds twice and fails unless both builds are identical.
- It strips the binary, then prints NEEDED, size and sha256, and writes the list of imported symbols to
  `OUTDIR/altscreen-most-bridge.imports.txt`.

## Host tests

```sh
bridge/test/run_tests.sh [steady real-h264 parity force-idr slow-recovery enomem session gate log provenance]
```

How the tests run:

- They build the bridge with clang/cc in upstream's `ALTSCREEN_BRIDGE_FILE_OUTPUT` mode: a regular file instead of
  isoTX2, no devctl.
- `test/shim/host_shim.h` maps the ring, force-IDR, cache-lock and dmdt paths, and the reclaim window, to environment
  variables, so each test runs in its own `test/build/runs/<test>/`.
- They also build the unmodified upstream bridge, a build with upstream's ENOMEM hook
  (`ALTSCREEN_BRIDGE_TEST_ENOMEM_AT_BLOCKS=100`, `_REPEAT=60`), two slow-write builds (`PMCP_TEST_SLOW_WRITE_EVERY=4`,
  35 ms: every 4th write from block 50 is slow; one with the fixed rule, one with the old streak of 8) and the AA-flag
  variant (compile only).
- `test/producer.c` writes the ring as docs/11 describes. Input is either:
  - a real Annex-B capture: `PMCP_TEST_H264`, by default the AA car capture
    `passat-mhi2-carplay/build/car-logs-20261110b/aa-stream.h264` if present; or
  - synthetic Baseline frames.
- The output TS is checked with the AA team's `aa/most/test/ts_analyse.py` and `ts_compare.py --mode cp`.
- Prints `BRIDGE TESTS: N ok, M failed` and exits non-zero on any failure.

What the tests cover:

- **steady, real-h264:** valid TS; every frame out.
- **status:** keys, size, 1 Hz, `ready`, exit.
- **parity:** the same input through upstream and our build gives the same TS (`ts_compare` SAME).
- **force-idr:** a backlog overflow leads to `latency-reset`, then the marker, then the producer's IDR, then
  `latency-resume-idr`; every drop run ends on an IDR.
- **enomem:**
  - dmdt is called `dc 72`, `sc 4 72` three times, resync each time, and the fourth ENOMEM is not attempted;
  - outside the window there is no dmdt call.
- **session:** stop within 1.5 s (measured about 40 ms); a stale stop is ignored; a vanished file with a dead pid ends
  the stream.
- **slow-recovery:** every 4th MOST write takes 35 ms; after the backlog reset the IDR is requested within 500 ms
  (measured about 140 ms) and the stream resumes on it. Control: with the old rule (streak 8) no IDR request at all.
- **gate:** owner switch gen 5 → 6 by `producer --switch-after` (old stream under a forked idle child's pid, new stream
  with its own avcC; the old stream keeps writing, keyframes included, after the switch):
  - `gate-held` (old `proxy` pid dies after 1 s): no old frame written > 40 ms after the switch reaches the output;
    the gate opens on the pid exit (about 1030 ms), the held avcC is applied, the IDR marker is created and the new
    stream starts on an IDR with the discontinuity flag;
  - `gate-forced` (old `proxy` pid never exits): forced open at 3000 ms, `gate_forced=1`; the status file keeps its
    1 s refresh through the held gate;
  - `gate-in` (old `in` pid never exits): forced at 100 ms;
  - `gate-oq3`: owner, avcC and IDR written back to back before the bridge's next owner poll; the gate still opens on
    that avcC (cut_seq from the previous poll);
  - every case: exactly one `owner-cut` (the first owner seen does not cut), no foreign `ring generation=` line,
    ts_analyse OK, exit 0.
- **log:** rotation at 64 KB; one `.1` only.
- **provenance:** upstream sha256, `pmcp` markers, and `src/pmcp_gate.c` identical to the kit's functions.

Host artefact: in file mode the writer is paced at about 9.6 Mbit/s instead of 12.288 Mbit/s, so the PTS lead over PCR
grows. This is the same for upstream and does not exist on the unit.

## Not done yet

- Installer and card integration:
  - a profile file plus the `build_sd.py` pin;
  - a GEM switch (default mathsls);
  - `cp-log-save` collecting `bridge.log*`;
  - the log-clear button (main 9) covering `/ramdisk/pmcp-most/`.
- Car test: cold starts (does the flicker of A184 disappear?), the ENOMEM/reclaim hypothesis on MU1161, and force-IDR
  after a phone reconnect (stage0 risk 2).
- The unit's own `libc.so.3` was not available offline. Six imports are proven only against the QNX 6.5.0 SDK libc and
  Tomasz's MU1367 binaries (see NOTES-stage1.md).
- Shared output library with AA (stage 3), own supervisor (stage 5).
- A gate that never gets an avcC after the cut stays closed (spec OPEN-QUESTIONS 3): core.so is not known to resend
  avcC on a ring generation change.
