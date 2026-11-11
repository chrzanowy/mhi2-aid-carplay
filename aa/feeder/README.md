# aa-most-feeder

[Polska wersja: README.pl.md](README.pl.md)

Android Auto video for the cluster, sent along our CarPlay path: MacsInSpace hook in `gal` -> this program -> ring
`/ramdisk/carplay-alt-ring.bin` -> `altscreen-most-bridge` (omonob/mathsls, already on the unit) -> MOST -> AID 791.
Background: `docs/11-ring-altscreen.md`, `docs/06-audyt.md` A63-A68.

## How it works

- The hook starts it instead of its own player (`GAL_PLAYER_PATH`), with the stream address in `argv[1]`
  (`tcp://127.0.0.1:12346`). The stream is raw Annex B without framing; frame boundaries come from a NAL parser (AUD/SPS/PPS/SEI
  or a slice with `first_mb_in_slice == 0`) and from a gap of `PMCP_AA_IDLE_MS` (default 8 ms) after the last bytes.
- To the ring: avcC (type 1) on every SPS/PPS change, frames (type 2) as AVCC without AUD/SPS/PPS, because the bridge adds them itself.
  NTP 32.32 timestamp from the monotonic clock.
- ACK (`/tmp/gal_ack.sock`, 1 byte per frame): `most` mode limits the rate with a byte budget (`PMCP_AA_RATE_KBPS`,
  default 700, headroom `PMCP_AA_BURST_KB` 150), so the phone slows down before the bridge queue overflows.
- Pacing (v9, `PMCP_AA_PACE_KBPS`, default 0 = off; AA 3 / gamma settings: 2000 with `PMCP_AA_PACE_BURST_KB` 64): frames go
  into the ring no faster than this budget; the frames after a large one wait in order (their ACKs too). The status shows
  frames and KB per 10 s for the last 5 minutes, the longest gap between frames and the last large frames.
- MOST takeover (only `PMCP_AA_MODE=most`, on the first IDR): refused when the CarPlay supervisor or our bridge is running;
  `dmdt dc 72`, `dmdt sc 4 72`, 500 ms, bridge start through a watchdog. The watchdog holds the bridge and waits on a pipe from the feeder:
  when the feeder ends in any way (including SIGKILL from the hook after 300 ms), the watchdog stops the bridge (SIGTERM,
  `flush(0)` on `/dev/mlb/debug/isoTX2`, SIGKILL), waits 250 ms and hands the VW map back (`dmdt dc 70 33`, `dmdt sc 4 70`).
- `analyze` mode (default) takes over nothing: it reads, acknowledges and once a second writes a summary to
  `PMCP_AA_STATUS` (`/ramdisk/pmcp-aa-feeder.txt`): SPS (profile, level, resolution), PPS (CABAC/CAVLC), IDR intervals,
  frame sizes, bitrate, ACK. The file is overwritten, nothing grows.
- Settings: the hook starts the player with a fixed environment (only `IPL_CONFIG_DIR`, `LD_LIBRARY_PATH`, `PATH`), so on
  the unit the mode and rate come from `PMCP_AA_CONF` (default `/mnt/app/carplaymaps/aa/feeder.conf`, written by `pmcp.sh aa-on`).
  Only `PMCP_AA_MODE`, `PMCP_AA_RATE_KBPS`, `PMCP_AA_BURST_KB`, `PMCP_AA_IDLE_MS` are read from the file; environment
  variables take precedence (host tests).

## Direct MOST output (v11, `PMCP_AA_OUTPUT=direct`)

The default `PMCP_AA_OUTPUT=ring` is everything above, unchanged. With `direct` (only with `PMCP_AA_MODE=most`) the
feeder starts no `altscreen-most-bridge` and makes no ring:

- `aa/most/ts_mux.c` muxes the frames into the bridge's MPEG-TS byte for byte (PIDs, PAT/PMT/PCR every 327 packets,
  PCR from the packet count, PES layout, AUD and SPS/PPS before an IDR, 12032-byte blocks). Decisions that differ, as in
  harman-f's corrected bridge: whole AUs only, the first AU carries the discontinuity flag, and the PTS is set when the
  AU's first packet is built (lead over PCR ~100 ms, never negative).
- `aa/most/most_writer.c` opens `/dev/mlb/isoTX2` with the bridge's devctl sequence and writes whole blocks from a
  thread (EAGAIN: poll with a fall-back to 1 ms sleeps, or a blocking driver).
- Nothing is ever dropped and no IDR is ever waited for or requested. Backpressure goes to the phone: ACKs are held
  while more than `PMCP_AA_ACK_HIGH_PKTS` (1024) TS packets are queued, and released below `PMCP_AA_ACK_LOW_PKTS` (512).
- The guardian is the same; in this mode it runs no bridge and gives MOST back when the feeder closes the pipe (the
  feeder closes isoTX2 first). A write error, a short write or a stuck write gives MOST back at once; the session goes
  on as analysis.
- Settings (also from `feeder.conf`): `PMCP_AA_OUTPUT`, `PMCP_AA_ACK_HIGH_PKTS`, `PMCP_AA_ACK_LOW_PKTS`,
  `PMCP_AA_QUEUE_KB` (8192), `PMCP_AA_MOST_WAIT` (`auto`|`poll`|`sleep`|`block`), `PMCP_AA_MOST_STALL_MS` (5000),
  `PMCP_AA_LEAD_MS` / `_MIN_MS` / `_MAX_MS` (100/50/130, v12: 200), `PMCP_AA_DISC_FIRST` (1). `PMCP_AA_RATE_KBPS` defaults to 0
  in this mode. Environment only: `PMCP_AA_MOST_DEV` (`/dev/mlb/isoTX2`).
- v12 (after the car test A147): no v10 pacing in direct mode (`PMCP_AA_PACE_*` ignored there; it held frames up to
  405 ms for nothing), and `PMCP_AA_MOST_SLEEP_US` (6500, 0 = v11's 1 ms steps): the first sleep after an accepted block
  waits out most of the ~7.9 ms the driver needs per 12032-byte block (v11 woke ~4 times per block).
- v13 (after the car test A152): the PTS lead is rebased down above 130 ms (`PMCP_AA_LEAD_MAX_MS`, was 200: the lead
  sat at ~150 ms); the start sync hold in direct mode is `PMCP_AA_DIRECT_SYNC_HOLD_MS` (1500; feeder.conf's
  `PMCP_AA_SYNC_HOLD_MS`=3000 stays for the bridge); the MOST events also note phone gaps of 1.5 s or more and a 3 s
  stall with the ACK and queue state at that moment, and every ACK hold on/off; the full status of the last 3 sessions
  is kept as `<status>-prev1..3` (GEM "AA save log" copies them); the session line has the gaps and ACK counts.
- v15 (A165, after tomasz-twardzicki's MU1367 v1.5.1-e): while the radio boots, the factory video encoder takes isoTX2
  by itself and the next write fails (ENOMEM on MU1367). Direct used to give MOST back for the rest of the session. Now
  a write error or a 5 s refused block in the first `PMCP_AA_RECLAIM_S` of uptime (180, 0 = off) takes MOST back, at
  most `PMCP_AA_RECLAIM_MAX` times (3): dmdt release again, the same open and devctl sequence, the discontinuity flag
  on the next AU, then SPS/PPS and the last IDR again. The status line `ponowne przejecie MOST:` counts it.

Diagnostics in both outputs: the guardian keeps the bridge's first 30 lines (devctl read-backs) besides the last ones;
`PMCP_AA_CAPTURE_S=N` (default 0) records the phone's access units for N s to `PMCP_AA_CAPTURE_PATH` (environment only,
default `/mnt/persist/pmcp/aa-stream.h264`, at most 6 MB, Annex B with an AUD per AU, plus `.idx` with the times).
v12/v13: 8 MB (v13: 4 MB) stay free on the partition; if the whole capture does not fit it is cut at an AU boundary (at least 256 KB),
and the status shows errno, the free space and what was written.

## Build and test

```
aa/feeder/build.sh build/aa/feeder                                   # QNX 6.5 armv7, image qnx65-armv7-toolchain:8.5
S="aa/feeder/aa_most_feeder.c aa/most/ts_mux.c aa/most/most_writer.c"
cc -O2 -Wall -Wextra -Werror -std=gnu99 -pthread -o /tmp/pmcp-aa/feeder-host $S
cc -O2 -Wall -Wextra -Werror -std=gnu99 -pthread -DMOST_HOST_SIM -o /tmp/pmcp-aa/feeder-host-sim $S aa/most/test/host_mlb.c
python3 -I aa/feeder/test/run_host_test.py /tmp/pmcp-aa/feeder-host  # stubs for the hook, the bridge (ring format) and dmdt
python3 -I aa/feeder/test/run_direct_test.py /tmp/pmcp-aa/feeder-host-sim [bridge-stage0/golden]   # direct output
python3 -I aa/most/test/run_mux_test.py bridge-stage0/golden /tmp/pmcp-aa/mux   # ts_mux against the golden captures
```

The direct test simulates isoTX2 with bridge-stage0's `host_mlb.c` (rate, EAGAIN or blocking, short writes, stalls,
EIO, devctl statuses) and decodes the TS with bridge-stage0's `ts_analyse.py` (both copied to `aa/most/test/`;
`host_mlb.c` since v15 also takes `HOST_MLB_FAIL_ERRNO` / `HOST_MLB_FAIL_REPEAT` and appends on a reopen).

Test: a full `most` session (dmdt order, avcC, 60/60 AVCC frames, continuous seq, increasing time, ACK per frame), SIGKILL
of the feeder mid-run (the watchdog hands MOST back, no bridge left behind), `analyze` mode (no dmdt and no ring, correct summary),
ACK throttling at 200 KB/s (and the real maximum delay time), `most` mode from `feeder.conf` (path keys
in the file are ignored).

Installation on the unit: `aa/README.md` (`gal` wrapper, trial start, GEM buttons). None of this has been run
on the unit yet.
