# Experimental card: Android Auto on the AID (in-car guide)

[Polska wersja](../pl/13-instrukcja-eksperymentalna.md) · Background: [aa/README.md](../../aa/README.md)

This card is the v1.4.1 release card plus one extra screen, **pmcp_android_auto** (GEM: pmcp → pmcp_advanced →
pmcp_android_auto). Everything on the main screen works exactly as on the release card. Card 2 (rescue) is the same.

## Before

- The CarPlay map is installed (main screen "2. Install the CarPlay map on the AID", or "3. Install all features or
  update"). Android Auto uses the CarPlay map's bridge.
- For VW arrows from Google Maps: the route guidance system on and the package **rg-aa** instead of rg
  (pmcp_packages: "On rg-aa: rg + VW arrows from Android Auto (Google Maps); replaces rg (experimental)").
  rg-aa behaves like rg with CarPlay. Like every Java package change, it is a trial start: "4. Confirm" in that start.

## Android Auto on

1. pmcp_android_auto → **"AA 1. Android Auto on: Google Maps on the AID + VW arrows (also updates an earlier card's AA)"**
   (`aa-on`) → `PMCP_AA_ON_OK mode=gamma`. It also updates the AA files of an earlier experimental card (status "old"),
   with no removal first.
2. Restart the unit (hold the volume knob ~10 s).
3. Android phone on the cable, Android Auto, a route in Google Maps. The first Android Auto session of this start is a
   **trial**.
4. If the AA map shows on the AID (it may take ~10 s: the feeder waits for the AID first): in the same start
   **"AA 2. Confirm: AA works (only in the start of the AA trial)"** (`aa-confirm`) → `PMCP_AA_CONFIRM_OK`.
   Without Confirm the next start has the factory Android Auto again; **"AA 3. Try again: the next AA connection is a new
   trial"** (`aa-retry`) allows one more trial.

## When the picture is lost

The phone sends one key frame per session, so a lost picture (dark with artefacts, or the AID's loading screen) stays
until the phone is plugged in again. To help find the cause, **in the same start, without unplugging**:

1. **"AA status and stream analysis (read-only)"** (`aa-status`): photograph every page. Most useful lines:
   `dawkowanie:` (pacing), `przerwy:` (gaps between frames), `klatki co 10s` / `KB co 10s` (frames and KB per 10 s, the
   last 5 minutes), `duze klatki` (large frames), `sync startu:`, `pierwsze IDR`.
2. **"AA save log: copy this start's AA log to the unit (for the log card)"** (`aa-log-save`) →
   `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`. Up to 5 logs are kept.
3. Then unplug and plug in the phone.

At home: card 3 (logs, `installer/build_logcard.py`) in update mode copies the logs to `PMCP_LOGS/` on that card (it only
reads the unit). Afterwards **"AA delete saved logs (after the log card copied them)"** (`aa-log-clear`).

## Android Auto off

- **"AA remove (factory Android Auto back)"** (`aa-remove`): the factory `gal` back from its hash-checked copy, the AA
  files and markers removed. Restart before connecting the Android phone again.
- "Remove everything" takes Android Auto off first, then the rest.
- The release card (v1.4.0 and later) can also do it: advanced → "Remove experimental Android Auto", or button 3.

## What the status says

`Android Auto (experimental): off | on mode=gamma | old mode=… | unknown`

- **old**: the AA files of an earlier experimental card; "AA 1" updates them.
- **unknown** makes the unit state PARTIAL (files from different sets, an interrupted action): "AA remove", then "AA 1".
