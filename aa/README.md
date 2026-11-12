# Android Auto on the AID (Android Auto 1.0 since v1.6.0; 0.1 open alpha in v1.5.x)

[Polska wersja: README.pl.md](README.pl.md)

Status (2026-11-07, car-tested on a Passat B8, MU1161 / AID 791, Samsung Galaxy A16 with Android 16):

- **Works:** the Google Maps picture on the AID over the unit's own MOST path; switching from CarPlay to Android Auto
  without a restart; native VW arrows with distance from Google Maps manoeuvres (94 of 94 recognised on a test drive).
- **Known limits:** the stream starts about 5 s after the phone connects; now and then the picture starts dark until the
  phone's next key frame (feeder v10: start sync, pacing at 6 Mbit/s without bursts, no focus cycle); no VW arrow at the
  very first step of a route ("depart" is not mapped yet).

**Android Auto 1.0 (feeder v14, audit A152/A153):** the default output is pmcp's own MOST writer (`most/`, "direct"):
the feeder muxes the stream to TS and writes it to `/dev/mlb/isoTX2` itself, with no frame pacing and no CarPlay bridge
in between; the CarPlay bridge path below stays as the fallback output ("AA output: CarPlay bridge", or
`PMCP_AA_OUTPUT=ring` in `/mnt/persist/pmcp/aa-extra.conf`, no trial). Known issue: after leaving Android Auto on the main
screen and coming back, the phone may slow down the cluster stream and, rarely, stop it; plugging the phone in again
brings it back.

Android Auto is installed with its own main-screen button in GEM, "3. Install Android Auto: Google Maps on the AID + VW
arrows (needs 2)"; its details (AA confirm, status, logs, removal) are on the screen `pmcp_advanced` → `aa_advanced`.
"4. Install additional features" neither installs nor removes it. CarPlay works exactly as without it.

## How it works

The picture takes the same path as our CarPlay map. The unit neither decodes nor encodes video:

```
AA phone -> gal (the unit's AA receiver) + hook -> aa-most-feeder -> ring /ramdisk/carplay-alt-ring.bin
         -> altscreen-most-bridge (the CarPlay map's bridge) -> MOST -> the AID decodes H.264
```

- The hook (MacsInSpace's [mib-cluster-map](https://github.com/MacsInSpace/mib-cluster-map) @ `07361db`, built without any
  SD card path) offers the phone a second 800x480 "cluster" display at protocol 1.7 and hands its H.264 stream to our
  feeder instead of decoding it.
- The feeder (`feeder/`) takes the AID's MOST video channel, waits until the AID is ready, then writes the frames into the
  same ring the CarPlay map uses. It paces large frames and keeps statistics for `AA status`.
- The hook also reads Google Maps' navigation messages (0x8006 next step, 0x8007 distance) and writes the same mailbox
  format the CarPlay route guidance reader writes, to `/ramdisk/pmcp-aa-rg` (`hook/pmcp_rg.c`). The route guidance
  package **rg** (since v1.5.0 with `rg/lanes/aa.py`; the experimental cards had it as a separate package `rg-aa`) reads
  it while an Android Auto phone is connected and shows the VW arrows. With CarPlay or no phone it never reads it.
  Destination distance and arrival time stay in the Android Auto picture.

## Files in the unit

| In the unit | From | Notes |
|---|---|---|
| `/mnt/app/eso/bin/apps/gal` | `unit/gal.wrapper.sh` | wrapper: trial start, then Confirm (like the Java packages) |
| `carplaymaps/aa/gal.real` | the unit's factory `gal` (`3b422d47…`) | copy made by `aa-on`; the way back |
| `carplaymaps/aa/libgal_hook.so`, `libdmdt_flush.so` | `hook/build.sh <dir> gamma` | hook g2 |
| `carplaymaps/aa/aa-most-feeder` | `feeder/build.sh` | feeder v10 |
| `carplaymaps/aa/gal-hook.conf` | `unit/gal-hook-gamma.conf` | protocol 1.7, `GAL_PMCP_RG=1` |
| `carplaymaps/aa/feeder.conf` | `unit/feeder-gamma.conf` | MOST, 5 s wait, start sync, pacing 6 Mbit/s, 20 ms gap |
| `carplaymaps/aa/AA_BOOT` | `pmcp.sh` | set id: `gamma-` + 8 hex of hook, feeder and hook settings |

Nothing changes in `/mnt/system`. Saved logs go to `carplaymaps/logs/` (`AA save log`; `CP save log` for
CarPlay).

## Safety

- **Trial start:** a new AA set runs with the hook during one unit start only. After a restart without "5. Confirm"
  (or `aa_advanced` → "AA Confirm") `gal` is factory again. `DISABLED` from the rescue card also switches the hook off.
- **Nothing on an SD card affects `gal`:** `hook/patch_no_sd.py` removes the hook's SD card and `/tmp` paths before the build.
- The feeder reads only its settings keys from `feeder.conf`, never paths.
- `AA remove` and "8. Remove everything" put the factory `gal` back, only from a copy with the factory hash.
- AA sets of earlier experimental cards are recognised (`AA_OLD`): status `old`, main menu 3 brings them up to date without removing
  anything first. A set it does not know (status `unknown`) is removed first, only from the factory `gal` copy with the
  factory hash, otherwise it stops and changes nothing.

## What we learned (details: audit A-AA1..A-AA30 in the project notes)

- The phone's first IDR of a stream is about 1 KB and black; the map comes in the P frames after it. The AID has to be
  ready before the phone starts: the feeder takes MOST, waits 5 s, and repeats the first IDR for 3 s while its ACK is held.
- Asking the phone for a new key frame does not work: re-sending the video setup drops the connection about 9 s later; a
  focus cycle makes the phone stream at ~3 fps and reset ~130 s later.
- CarPlay's producer keeps the 16 MB ring file mapped, so deleting it filled `/ramdisk`; the feeder reuses it in place.
- Full Google Maps navigation messages need protocol 1.7.

## Host tests and build

```
python3 -I aa/feeder/test/run_host_test.py <feeder built for the host>   # cc -O2 -Wall -Wextra -Werror -std=gnu99
aa/hook/test/run_keyframe_test.sh ; aa/hook/test/run_rg_test.sh
aa/hook/build.sh   build/aa-g2 gamma     # Docker image qnx65-armv7-toolchain:8.5; two builds, must be identical
aa/feeder/build.sh build/aa-v10/feeder
rg/build.sh MU1161 <converted lsd.jar> build/rg-mu1161-lanes-uturn-asf-m-aa lanes-uturn-asf-m-aa   # package rg
python3 -I installer/build_sd.py build/sd
python3 -I installer/build_logcard.py build/card3-logs   # card 3 (logs), a separate SD card
```

`build_sd.py` accepts files only with pinned hashes.

## TODO (hook, `aa/hook/pmcp_rg.c`; not changed in 0.1, the car-tested bytes stay)

- The writer thread holds the mutex during file I/O (mailbox and status writes), so gal's reader thread can wait on a
  slow `/ramdisk` write in `pmcp_rg_message()`.
- `pthread_cond_timedwait` uses an absolute `CLOCK_REALTIME` deadline: a step back of the clock (GPS time set) stops the
  heartbeats until the clock catches up. Use `CLOCK_MONOTONIC` (`pthread_condattr_setclock`) or a relative wait.
- `write_status()`: when `fclose` fails the status `.tmp` file is not removed (`write_file()` does unlink its `.tmp`).

In-car steps: [docs/en/13-android-auto-guide.md](../docs/en/13-android-auto-guide.md).
