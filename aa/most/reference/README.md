# bridge-stage0: golden reference of what altscreen-most-bridge writes to MOST

Stage 0 of our own MOST bridge. omonob's bridge source runs on macOS. It has the v1.x behaviour of
our unit's binary (`fed7dce4…`, v1.x + diasdio). A shim stands in for `/dev/mlb/isoTX2` and records
every byte and every devctl. The bridge is fed by a driver that writes the ring the way
`aa_most_feeder.c` (v10) does. The output is decoded into a normalized description that our own
bridge will be checked against.

Nothing outside `/tmp/bridge-stage0` was changed. Sources were copied into `third_party/`. There was
no network use: harman-f's input is a TCP socket on 127.0.0.1 only.

## 1. Build and run

```sh
cd /tmp/bridge-stage0
./build.sh                    # checks source sha256, applies the patch, builds 3 binaries into build/
./run_all.sh > run_all.log    # about 1.5 min: every golden directory, harman-f comparison, repeat run
python3 -I tools/run_scenario.py burst [--harman] [--out DIR] [--idr-on-request N] \
        [--bridge build/altscreen-most-bridge-host-stock] [--env HOST_MLB_MODE=block] [--h264 capture.h264]
python3 -I tools/ts_analyse.py golden/burst          # -> norm.json, timing.json, summary.txt
python3 -I tools/ts_compare.py golden/burst OUR_RUN [--mode cp|aa] [--lead-min 4500]
```

Binaries built into `build/`:

| Binary | What it is |
|---|---|
| `altscreen-most-bridge-host` | `-DALTSCREEN_V1X -DALTSCREEN_DIASDIO`: our unit's behaviour. This one makes the golden files. |
| `altscreen-most-bridge-host-stock` | v1.x without diasdio (stock `c846e505`), for comparison |
| `direct-ts-parity-host` | harman-f clean-room bridge, host build |

### Source version

- `altscreen_most_bridge.c` has exactly one commit in omonob's history: `2f5fd58` (Release 2.0). It is
  unchanged up to HEAD `5ba6f7f`.
- **No v1.x source exists in the repository.** v1.x was published only as binaries (`222e76a`…`02d3f35`).
- So the build uses v2 source plus `patches/omonob-v1x-diasdio.patch` (72 lines). The patch only adds
  `#ifdef` blocks:
  - `ALTSCREEN_DIASDIO`:
    - `queue_discard_all()` flushes only when `high_water_window == 0` and no longer zeroes
      `high_water_window`. This is binary 0x1b04–0x1b10, re-verified in the disassembly:
      `r4 = &g_queue - 8`, `+0x1c` = `high_water_window`.
    - `writer_recovered_after_reset()` needs `streak >= 1` instead of `>= 8` (binary 0x4174).
  - `ALTSCREEN_V1X`:
    - No intro-policy log line and no "intro skipped / reconnect IDR" startup path.
    - A ring generation change only logs `ring generation=%u` and restarts at sequence 1 (binary
      0x102e80–0x102ec8).
- The v2-only `cpmap_*` helpers are replaced by host headers (see the shim list).

## 2. Shim list (every host substitution)

| File | Replaces | What it does |
|---|---|---|
| `host/host_shim.h` (force-included with `-include`, after the real system headers) | `open64`, `write`, `close`; `ALT_FRAME_RING_PATH`, `ALT_FRAME_FORCE_IDR_PATH`, `INTRO_ONCE_PATH`, `INTRO_POLICY_PATH` | `open64` → `host_open64` (the simulated isoTX2). `write`/`close` → `host_write`/`host_close` (other fds pass through). The ring, force-IDR and intro-once paths come from the environment (`HOST_RING_PATH`, `HOST_IDR_PATH`, `HOST_INTRO_ONCE_PATH`). |
| `host/devctl.h` | QNX `<devctl.h>` | Declares `devctl()` |
| `host/host_mlb.c` (built separately, sees the real libc) | `/dev/mlb/isoTX2` + `devctl` | See below |
| `host/cpmap_resources.h` | v2 log limiter and video-cache lease | Plain `fprintf` + `fflush`, as v1.x does. The lease is a no-op. |
| `host/cpmap_intro_policy.h` | v2 intro policy | Always "every-connect", no files read. The intro plays only if `CARPLAY_CLUSTER_INTRO` is set, as in v1.x. |

What `host_mlb.c` does:

- **Recording.**
  - Every accepted byte is appended to the "device" file (`argv[1]`, `mlb.ts`).
  - `mlb.ts.log` gets one line per `open`, per `devctl` (code, direction, size, value, status), per
    accepted `write` (size, ret, offset, number of EAGAINs before it, blocked µs, FIFO level) and per
    `close`.
  - EAGAIN returns are counted on the next accepted write, not logged one by one.
- **Back-pressure model.**
  - A driver FIFO of `HOST_MLB_DEPTH` bytes (default 24064 = 2 blocks), drained at `HOST_MLB_BPS`
    (default 12288000 bit/s) from the START devctl on.
  - A write that does not fit returns −1/EAGAIN by default (`HOST_MLB_MODE=eagain`; the bridge opens
    `O_NONBLOCK`). With `HOST_MLB_MODE=block` it sleeps until the write fits.
  - `HOST_MLB_PARTIAL=1` accepts whole TS packets (short writes).
  - `HOST_MLB_STALL_AT_BLOCK`/`HOST_MLB_STALL_MS` stop the drain once; `HOST_MLB_FAIL_AT_BLOCK`
    injects EIO.
- **devctl.**
  - Readback values come from `HOST_MLB_IFACE`, `HOST_MLB_PKTSIZE` and `HOST_MLB_BLKCOUNT`, default 0.
    The real MU1161 values are unknown (CONTRACT U2).
  - Statuses: `HOST_MLB_FLUSH_STATUS` (25 = ENOTTY, as on MU1440) and `HOST_MLB_START_STATUS`.

The harman-f build is a separate copy in `build/harman`. Its hard-coded `/tmp/mibr-*` paths are rewritten
by `sed` to `build/harman-run/`. Without `__QNXNTO__` it has no devctl and writes to a regular file,
paced by its own 12.288 Mbit/s clock.

## 3. Driver (`tools/ring_driver.py`, Python with `-I`)

**Ring protocol, as `aa_most_feeder.c` does it:**

- Waits until the bridge has created the ring: CPRG, version 1, size 0x1000710.
- Continues from the header's `write_sequence`.
- `ring_put` writes, in order:
  1. `committed = 0`;
  2. type, size, flags = 0, frame_no, NTP lo/hi;
  3. the data;
  4. `committed = N`;
  5. header `write_sequence = N`.
- Every step is separated by `OSMemoryBarrier()`, a real `dmb` on arm64.
- The NTP 32.32 time comes from `CLOCK_MONOTONIC` at put time.
- Frames are AVCC with 4-byte lengths. AUD, SPS and PPS are stripped.
- SPS and PPS go into an avcC record (type 1, frame_no 0), built byte for byte like `send_avcc()`, before
  the first frame.
- frame_no counts from 1.

**Stream:**

- `h264synth.py` (copied from `aa/feeder/test`): parse-valid SPS (800×480, Baseline 3.1), PPS and slice
  headers, followed by random payload bytes 1..255. The payload has no zero bytes, so no start-code
  emulation.
- Bytes are a function of (seed, frame index, idr, size) only, so every run sends the same frames.
- Pacing: 30 fps against a monotonic deadline. Burst frames are written back to back.

**Force-IDR:**

- With `--idr-on-request N` (default 1), the request file is removed when it appears, and the N-th
  frame after that is sent as an IDR. This is CarPlay's core.so, or the AA hook with `KF_BRIDGE=1`.
- `N = -1` only removes the file, like the AA feeder v10 default.

**Real capture:** none was found. `passat-mhi2-carplay/build` has no `*.h264`, `*.ts` or ring dumps. The
only matches were `aa-capture.sh` scripts and `*pairing*` binaries. `--h264 FILE` replays any Annex-B
file, one AU per AUD. A self-replay of the steady input was tested and matched the golden: SAME.

## 4. Scenarios and results (`golden/<scenario>/`)

Each directory contains:

- `mlb.ts` — every byte written to MOST;
- `mlb.ts.log` — devctl and write log;
- `bridge.stderr`;
- `input/frames.jsonl` and `input/input.h264`;
- `norm.json`, `timing.json` and `summary.txt`;
- `harman/` — the same set from harman-f, plus `compare.txt`.

| Scenario | Input | Result (golden bridge) |
|---|---|---|
| **(a) steady** | IDR 20 KB + 149 P frames of 1.5–6 KB, 30 fps | All 150 AUs out. PTS lead over PCR 8 982–9 798 (≈ 9000 target). 0 resets. |
| **(b) burst** | 30 steady frames, then **48 frames of 6–12 KB at once**, then 60 steady | `latency-reset` at frame 63 (57 on another run): queued = 1042 > 1024. Frames dropped until the IDR. `latency-request-idr` at 80, `latency-resume-idr` at 82 (an IDR, discontinuity flag set). **Lead goes negative (−2009)**: the AUs queued before the reset are sent with PTS behind PCR. |
| **(c) gap** | frame_no 41 skipped (40 → 42) | `predictive-chain-gap previous=40 current=42`, then `latency-reset`. Frames 42–45 dropped; request at 44, resume on the IDR at 46. |
| **(d) large-idr** | IDR 110 KB, large P frames of 60–110 KB every 15 frames, a second IDR mid-stream | No frames lost, no reset. Lead drops to 3 708 (< 4 500, the bridge's own minimum), because the frame after a 110 KB AU waits about 80 ms behind it. |
| (e) large-run | 4 consecutive P frames of ≈100 KB at 30 fps | Reset at frame 35 (queued 1236). Frames 35–38 dropped, resume on the IDR at 39. Lead −835. |
| burst-no-idr | (b) with requests ignored (AA feeder v10 default) | Frames **57–138 all dropped**, up to the end of input. The bridge never resumes without an IDR. |
| burst-stock | (b) on v1.x without diasdio | The reset really flushes the TS queue. Frames 35–56 were already queued and are lost. **AU 34 (frame 35) goes out truncated**: its first packets had been sent. The analyser flags it ("payload matches no input frame"). |
| steady-block | (a), the driver blocks instead of EAGAIN | Same as (a) |
| steady-stall | (a), MOST stalls for 200 ms after block 300 | No reset (backlog < 1024). Lead jumps to 27 554 after the stall. |
| steady-rerun | (a) again | `ts_compare` against (a): **SAME** (strict + normalized) |

**(b) and (c) reproduce the car behaviour.**

- The bridge drops every new frame (first `latency-wait-writer`, then `latency-request-idr`) until a
  keyframe arrives. Only then does output resume, with discontinuity + random-access flags.
- If no IDR comes, nothing more is ever shown (burst-no-idr). This is A-AA33.
- With diasdio the TS queue is never actually flushed: video CC breaks = 0 in every diasdio run.
- The logged `discarded=` / `latency_packets_discarded=` counts are therefore fictitious. They print
  the queue count, not anything removed.

**Checks on every golden run:**

- whole 12032-byte writes only;
- devctl sequence 0x4004050c, 0x4004050d, 0x40040510, 0x40040506, then 0x80040509 with value 64;
- PAT/PMT/PCR byte-exact at n % 327 = 0/1/2;
- PCR = 45000 + n·705/64;
- CC correct;
- 100 % of AUs byte-exact against the packetization rule;
- every AU payload matched to its input frame, in order;
- SPS/PPS identical to the avcC.

**Shutdown:** `MOST write failed: Operation timed out` at the end of every run is a shutdown artefact.
SIGTERM sets `g_stop` while `write_full` waits on EAGAIN, so it returns −1 with a stale errno. This is
not a real error.

## 5. Analyser normalized format

`tools/ts_analyse.py RUN_DIR` (reuses the checks of the spike's `ts_check.py` / `ref_mux.py`) writes the
files below.

### `norm.json` (deterministic, compared strictly)

- **`transport`:**
  - `block_bytes`, `blocks`, `capture_whole_blocks`;
  - `write_sizes` (set) and `partial_writes`;
  - `devctl`: `[code, dir, size, value, status]` in order;
  - `psi_cadence_ok`, `pat_pmt_bytes_ok`, `pcr_formula_ok`, `null_packets_ok`;
  - `cc_breaks` per PAT / PMT / null / video;
  - `pids`.
- **`aus[]`**, in output order, one entry per AU:
  - `frame_no` (matched input) and `idr`;
  - `random_access` and `discontinuity`: first-packet adaptation flags;
  - `aud_first`: `09 f0` with a 4-byte start code;
  - `sps_pps` and `sps_pps_match_avcc`;
  - `nal_types` and `start_codes`;
  - `pes_header_ok`;
  - `annexb_bytes` and `packets`;
  - `packetization_exact`: the AU is rebuilt from its own PES bytes, flags and first CC with the
    bridge's `enqueue_pes()` rule, then compared byte for byte;
  - `avcc_sha256`: hash of the AU converted back to the feeder's AVCC bytes.
- **Input coverage:**
  - `input_frames` and `output_aus`;
  - **`missing_frame_nos`**: every input frame not in the output is listed here;
  - **`drop_runs`**: `first`, `last`, `resumed_at`, `resumed_with_idr`;
  - `input_avcc_sha256` per frame.
- **`events`:** latency-reset, chain-gap, request, resume, overrun, with their sequence numbers.
- **`errors`.**

### `timing.json` (timing-dependent, reported only)

- Per AU:
  - `first_packet` and `last_packet`;
  - `pts` and `pts_step`;
  - `pcr_at_first_packet`;
  - `lead_90k` = PTS − PCR(n of its first packet);
  - the input NTP time and put time.
- Packet counts per PID.
- The positions of video CC breaks.
- Event counts.
- Write statistics: EAGAINs, blocked µs.

### Which fields depend on timing, and why

- **Where an AU starts in the packet stream** (`first_packet`), **how many null packets** there are,
  and **null CC values**. The writer takes whatever is queued when it builds a block, and the main
  thread polls the ring every 1 ms. The *rules* are deterministic and checked exactly: cadence slots,
  PCR formula, PAT/PMT bytes and CC.
- **PTS.** It is `origin + Δ(feeder NTP)·90000`, where `origin` = the transport clock at the first frame
  + 9000. Both depend on wall time. Rebases and the `+1` forcing depend on queue state. Compare PTS
  *steps* against NTP steps, and `lead_90k`, with a tolerance.
- **Which frames are dropped, and the event sequence numbers.**
  - A reset fires when a frame finds more than 1024 packets queued. That depends on how fast the
    writer has drained.
  - The resume point depends on when the request file is seen.
  - The invariant is checked instead: the same number of drop runs, each ending on an IDR.
  - In AA mode: no drops at all.
- **Which input frame becomes the IDR after a request.** The driver decides this live, so the two
  inputs differ there. `ts_compare` skips frames whose input hashes differ.
- **Video CC breaks.** These happen only if packets are really discarded (stock bridge), and the count
  depends on the queue.

`tools/ts_compare.py GOLDEN CANDIDATE --mode cp|aa [--lead-min N]`:

- **strict:** the transport fields, and the AU fields of every frame whose input is identical;
- **normalized:** the drop-run pattern (cp), or zero drops (aa);
- **timing:** reported as notes, with an optional `--lead-min` gate.

## 6. harman-f `direct_ts_parity` on the same input (`golden/*/harman/compare.txt`)

It builds cleanly on the host (`-Wall`, no warnings).

**Same as the golden:**

- PIDs, PAT/PMT sections and CRC;
- cadence phase 0/1/2 every 327 packets;
- PCR formula, PCR CC fixed at 0, null packets;
- PES header;
- AUD + SPS/PPS insertion;
- **TS packetization byte-exact on 100 % of AUs**;
- the same payloads.

**Differences:**

1. **Discontinuity flag on the first AU.**
   - harman sets 0x80 at stream start. The v1.x bridge does **not**.
   - `g_discontinuity_pending` is in .bss = 0. It is set only at 0x101b6c (recovery), 0x103064 /
     0x1032e8 (intro start/end) and 0x1037f4 (intro-live-resume).
   - CONTRACT.md §3 ("…after a reset, intro or start") is wrong about "start" for our binary.
   - The v2 source sets it at start only through the intro-skipped path.
2. **Recovery.**
   - harman drops whole queued AUs at an AU boundary: `PARITY_SAFE_RECOVERY reason=latency
     discarded_aus=21`. It keeps the AU being sent, waits for an IDR and asks at once. There is no
     wait-writer phase.
   - So it loses the stale backlog instead of sending it late, and its lead never goes negative
     (burst min +2 899, against −2 009 in the golden).
   - It reset earlier in (b) (frame 43 vs 57–63) and recovered sooner in (c) (42–43 vs 42–45).
3. **PTS origin.** It is about 4 900–6 300 ticks (55–70 ms) lower than the bridge's for the same input
   timing: a different origin rule. Steps follow the same NTP deltas.
4. **Not comparable on the host:**
   - devctl, and the timing of write sizes and EAGAIN. Its devctl code exists only under `__QNXNTO__`.
   - From its source: the same five calls, but it **fails closed** if any readback fails or flush
     returns anything but 0/ENOTTY. Our bridge only logs them.

## 7. Open questions / limits

1. **The device model is assumed.** The real isoTX2 behaviour is unknown: EAGAIN vs blocking, FIFO depth,
   drain rate, short writes (CONTRACT U1/U10). The reset/recovery timing depends on it, because
   `writer_recovered_after_reset` counts writes of 30 ms or less. Both modes and stalls are available.
   Real numbers need `blocks=` / `hist_write_us=` lines from the car.
2. **The v1.x behaviour is v2 source + patch**, checked against the disassembly only for the patched
   spots, generation handling, discontinuity stores and log strings. The other parts rest on the
   spike's statement that the muxer, queue, recovery, clock and MOST code are the same.
3. **No real H.264 or car TS capture exists.** The golden is built on synthetic Baseline frames. A
   capture would need the U6(b) LD_PRELOAD shim on the car, or an `aa-capture` dump.
4. **Stage 1 needs a decision on CP mode.** Should it reproduce the golden *including* its defects,
   or not? The defects are:
   - late PTS after a backlog (lead < 0);
   - fictitious `discarded=` counts;
   - the 1024-packet reset on large frames;
   - no discontinuity flag at start.
   harman-f's AU-boundary recovery is the obvious alternative.
5. **devctl readback values on MU1161** (interface, packet size, block count) and the flush status are
   unknown. Defaults of 0 are used.
6. **A feeder frame larger than 256 KiB** is dropped before `ring_put` and gets no frame_no, so the
   bridge sees **no** chain gap and the predictive chain breaks silently. This is not a golden scenario:
   the driver mirrors it but the synthetic plan never exceeds 110 KB.
