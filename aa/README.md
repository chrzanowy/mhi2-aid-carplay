# Android Auto on the AID (experimental, branch `experimental`)

[Polska wersja: README.pl.md](README.pl.md)

Status (2026-11-04, car-tested on a Passat B8, MU1161 / AID 791, Samsung Galaxy A16 with Android 16):

- **Works:** the Google Maps picture on the AID over the unit's own MOST path; switching from CarPlay to Android Auto
  without a restart; native VW arrows with distance from Google Maps manoeuvres (94 of 94 recognised on a test drive).
- **Open:** the phone sends one key frame (IDR) per session. When the AID loses the picture, at the start (about half of
  the connections) or now and then while driving, it stays dark or on its loading screen until the phone is plugged in
  again. Feeder v9 paces large frames and logs gaps between frames to narrow this down.
- **Open:** no VW arrow at the very first step of a route with Android Auto (its "depart" step is not mapped yet).

This branch is the release (`main`, v1.4.1) plus Android Auto. Everything CarPlay works exactly as in the release.

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
  format the CarPlay route guidance reader writes, to `/ramdisk/pmcp-aa-rg` (`hook/pmcp_rg.c`). The Java package
  **rg-aa** (rg + `rg/lanes/aa.py`) reads it while an Android Auto phone is connected and shows the VW arrows.
  Destination distance and arrival time stay in the Android Auto picture.

## Files in the unit

| In the unit | From | Notes |
|---|---|---|
| `/mnt/app/eso/bin/apps/gal` | `unit/gal.wrapper.sh` | wrapper: trial start, then Confirm (like the Java packages) |
| `carplaymaps/aa/gal.real` | the unit's factory `gal` (`3b422d47…`) | copy made by `aa-on`; the way back |
| `carplaymaps/aa/libgal_hook.so`, `libdmdt_flush.so` | `hook/build.sh <dir> gamma` | hook g2 |
| `carplaymaps/aa/aa-most-feeder` | `feeder/build.sh` | feeder v9 |
| `carplaymaps/aa/gal-hook.conf` | `unit/gal-hook-gamma.conf` | protocol 1.7, `GAL_PMCP_RG=1` |
| `carplaymaps/aa/feeder.conf` | `unit/feeder-gamma.conf` | MOST, 5 s wait, start sync, pacing |
| `carplaymaps/aa/AA_BOOT` | `pmcp.sh` | set id: `gamma-` + 8 hex of hook, feeder and hook settings |

Nothing changes in `/mnt/system`. Saved logs go to `carplaymaps/logs/` (`AA save log`).

## Safety

- **Trial start:** a new AA set runs with the hook during one unit start only. After a restart without `AA 2. Confirm`
  `gal` is factory again. `DISABLED` from the rescue card also switches the hook off.
- **Nothing on an SD card affects `gal`:** `hook/patch_no_sd.py` removes the hook's SD card and `/tmp` paths before the build.
- The feeder reads only its settings keys from `feeder.conf`, never paths.
- `AA remove`, "Remove everything" and the release card's "Remove experimental Android Auto" put the factory `gal` back,
  only from a copy with the factory hash.
- AA sets of earlier experimental cards are recognised (`AA_OLD`): status `old`, `AA 1` brings them up to date without
  removing anything first.

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
aa/feeder/build.sh build/aa-v9/feeder
rg/build.sh <converted lsd.jar> build/rg-mu1161-lanes-uturn-asf-m-aa lanes-uturn-asf-m-aa   # package rg-aa
python3 -I installer/build_sd.py build/sd
python3 -I installer/build_logcard.py build/card3-logs   # card 3 (logs), a separate SD card
```

`build_sd.py` accepts files only with pinned hashes.

In-car steps: [docs/en/13-experimental-guide.md](../docs/en/13-experimental-guide.md).
