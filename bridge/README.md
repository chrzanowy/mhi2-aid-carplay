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
  upstream grants no "or later". Our new files (`src/pmcp_most.h`, `test/`, `build.sh`) are GPL-3.0-or-later.
- `upstream/` holds the verbatim files plus `PROVENANCE.json`: repository, commit, source path, sha256 and size of each
  file, and the licence.
  - Never edit `upstream/`.
  - The test suite checks the hashes.

## Layout

| Path | What |
|---|---|
| `upstream/` | verbatim import + `LICENSE` + `PROVENANCE.json` |
| `src/` | working copy: upstream files plus changes marked `pmcp:` (copy-with-markers, no patch series) and the new `pmcp_most.h` |
| `build.sh` | QNX build (docker `qnx65-armv7-toolchain:8.5`, no network) |
| `test/` | host build + tests (`run_tests.sh`, `harness.py`, `producer.c`, `shim/`, `fake_dmdt.sh`) |
| `contract/` | contract kit (separate work, not part of this stage) |

### Patch discipline

- Only `src/altscreen_most_bridge.c` and `src/cpmap_resources.h` differ from upstream. The other four headers are
  byte-identical copies.
- Every changed hunk contains a `pmcp` marker. The test `provenance` enforces this.
- Review the changes with `diff -u upstream/altscreen_most_bridge.c src/altscreen_most_bridge.c` (about 76 added lines,
  4 removed: the old body of `queue_discard_all`, see item 5) and `diff -u upstream/cpmap_resources.h src/cpmap_resources.h`.

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
   - Written with tmp + rename. Field limits are clamped as in the v0.2 clarifications (at most 253 B).
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

`TODO(stage 1b)` markers show where the contract v1.1 consumer gate goes (from `contract/`): a change of the owner's
`gen` bumps the ring generation and drops frames until a new avcC. It is not implemented in stage 1.

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
bridge/test/run_tests.sh [steady real-h264 parity force-idr enomem session log provenance]
```

How the tests run:

- They build the bridge with clang/cc in upstream's `ALTSCREEN_BRIDGE_FILE_OUTPUT` mode: a regular file instead of
  isoTX2, no devctl.
- `test/shim/host_shim.h` maps the ring, force-IDR, cache-lock and dmdt paths, and the reclaim window, to environment
  variables, so each test runs in its own `test/build/runs/<test>/`.
- They also build the unmodified upstream bridge, a build with upstream's ENOMEM hook
  (`ALTSCREEN_BRIDGE_TEST_ENOMEM_AT_BLOCKS=100`, `_REPEAT=60`) and the AA-flag variant (compile only).
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
- **log:** rotation at 64 KB; one `.1` only.
- **provenance:** upstream sha256 and `pmcp` markers.

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
- Contract v1.1 consumer gate (stage 1b), shared output library with AA (stage 3), own supervisor (stage 5).
