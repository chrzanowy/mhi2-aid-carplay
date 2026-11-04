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

## Build and test

```
aa/feeder/build.sh build/aa/feeder                                   # QNX 6.5 armv7, image qnx65-armv7-toolchain:8.5
cc -O2 -Wall -Wextra -std=gnu99 -o /tmp/pmcp-aa/feeder-host aa/feeder/aa_most_feeder.c
python3 -I aa/feeder/test/run_host_test.py /tmp/pmcp-aa/feeder-host  # stubs for the hook, the bridge (ring format) and dmdt
```

Test: a full `most` session (dmdt order, avcC, 60/60 AVCC frames, continuous seq, increasing time, ACK per frame), SIGKILL
of the feeder mid-run (the watchdog hands MOST back, no bridge left behind), `analyze` mode (no dmdt and no ring, correct summary),
ACK throttling at 200 KB/s (and the real maximum delay time), `most` mode from `feeder.conf` (path keys
in the file are ignored).

Installation on the unit: `aa/README.md` (`gal` wrapper, trial start, GEM buttons). None of this has been run
on the unit yet.
