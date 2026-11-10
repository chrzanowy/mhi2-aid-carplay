# Android Auto on the AID (in-car guide)

[Polska wersja](../pl/13-instrukcja-android-auto.md) · Background: [aa/README.md](../../aa/README.md)

Android Auto 1.0 (since v1.6.0; 0.1 open alpha in v1.5.x): the Google Maps picture from an Android phone on the AID, and
the VW arrows from Google Maps. The picture goes through pmcp's own MOST writer; "AA output: CarPlay bridge (fallback,
from the next connection)" in `aa_advanced` switches to the CarPlay bridge (no restart, no 5). It is installed with its own button on the main screen (GEM: `pmcp_stream_map_aid`), **"3. Install
Android Auto: Google Maps on the AID + VW arrows (needs 2)"**, separately from the CarPlay features: "4. Install
additional features" neither installs nor removes it. The details (AA confirm, logs, removal) are on the screen
`pmcp_advanced` → `aa_advanced`. Experimental cards (not releases) add "AA record" there (diagnostics); the main
screen installs the stable version. If the AID shows its loading screen after you left Android Auto on the main screen
and came back: plug the phone in again (known issue).

## Before

- The CarPlay map is installed (main screen **"2. Install CarPlay: the map on the AID (also repairs or updates it)"**).
  Android Auto uses the CarPlay map's video path.
- For the VW arrows from Google Maps: main screen **"4. Install additional features: route guidance, zoom, day/night,
  song title, settings page (needs 2)"**. Its route guidance package `rg` shows the arrows for CarPlay and for Android Auto. Without it
  you get the picture only. 3 and 4 can be pressed one after the other: one restart, then one "5. Confirm" in that
  start confirms both trials.

## Android Auto on

1. Main screen → **"3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)"** →
   `PMCP_AA_ON_OK mode=gamma`. If this card's set is already there (status "on", e.g. installed by v1.5.0) it answers
   `PMCP_AA_INSTALL_OK (already installed: ..., nothing changed)`: nothing to restart or confirm. An earlier
   experimental card's set that this card knows (status "old") is updated in place. Android Auto files this card does not support (e.g. from an experimental card, or an interrupted action) are removed first:
   the factory `gal` comes back, only from its copy with the factory hash; otherwise it stops and changes nothing. Then
   this card's set is installed. If `rg` is not on yet, it says: "VW arrows from Google Maps need rg: main menu,
   4. Install additional features."
2. Restart the unit (hold the volume knob ~10 s).
3. Android phone on the cable, Android Auto, a route in Google Maps. The first Android Auto session of this start is a
   **trial**.
4. The picture comes about 5 s after the phone connects (the AID has to be ready first). If the Google Maps picture is
   on the AID: in the same start, with the phone connected first, main screen **"5. Confirm: everything works (in the
   first start after 3 or 4)"** → `PMCP_AA_CONFIRM_OK` and `PMCP_CONFIRM_OK`. From then on Android Auto starts with it
   every time. If it says "connect the phone first, then 5 again", the Android Auto session has not started yet.
   (`aa_advanced` → "AA Confirm: AA works (only in the start of the AA trial; 5 does the same)" does the same for
   Android Auto only.)
5. Without Confirm the next start has the factory Android Auto again (no picture on the AID, nothing else changes).
   **"6. Try again: the next start is a new trial"** (or `aa_advanced` → "AA Try again: the next AA connection is a new
   trial") allows one more trial; then restart.

## Known limits

- The stream starts about 5 s after the phone connects.
- Now and then the picture starts dark (or the AID shows its loading screen) until the phone sends its next key frame.
  Plugging the phone in again helps.
- No VW arrow at the very first step of a route ("depart").
- Destination distance and arrival time are shown in the Google Maps picture, not on the VW bar.
- The VW arrow and bar end about 10 s after Google Maps stops sending navigation (for example after Maps closed without
  ending the route); CarPlay keeps a quiet route for 180 s.
- Card 2 (rescue) and the Java packages share one switch-off marker (`DISABLED`). "4. Install additional features"
  (and any Java on / update) removes it, and with it switches the Android Auto hook the rescue card had switched off
  back on. To keep Android Auto off after the rescue card: "AA remove (factory Android Auto back)".
- "AA save log" during an active Android Auto session can answer `AA_LOG_COPY_SHORT` (the log grew while it was
  copied). Unplug the phone and press it again in the same start.
- `guidance-evidence.txt` (rg's message counts, next to `adapter-status.txt`) counts Android Auto and CarPlay together.

## If something goes wrong: what to photograph

**In the same start, without unplugging the phone:**

1. `aa_advanced` → **"AA status and stream analysis (read-only)"**: photograph every page. Most useful lines: `Android Auto:` (the state),
   `dawkowanie:` (pacing), `przerwy:` (gaps between frames), `klatki co 10s` / `KB co 10s` (frames and KB per 10 s, the
   last 5 minutes), `duze klatki` (large frames), `sync startu:`, `pierwsze IDR`, and the "Manoeuvres for rg" lines.
2. **"AA save log: copy this start's AA log to the unit (for the log card)"** → `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`.
   Up to 5 logs are kept. If it says `AA_LOG_COPY_SHORT`: unplug the phone and press it again (same start).
3. **"7. Status (read-only)"** on the main screen: photograph it too (Java set, route guidance, Android Auto).
4. Then unplug and plug in the phone.

For a CarPlay problem: `features_advanced` → **"CP save log: copy this start's CarPlay log to the unit (for the log
card)"** → `PMCP_CP_LOG_SAVED file=logs/cp-log-N.txt`.

At home: card 3 (logs) in update mode copies the Android Auto and CarPlay logs to `PMCP_LOGS/` on that card (it only
reads the unit). Afterwards **"AA delete saved logs, AA and CarPlay (after the log card copied them)"** (`aa_advanced`;
the same as "Delete saved logs, CarPlay and AA (after the log card copied them)" in `features_advanced`).

### Card 3 (logs)

`install.sh` does not build it. On the computer, from the repository (needs the same M.I.B. 3.6.0 zip in
`mib/downloads/` as the rescue card):

```
python3 -I installer/build_logcard.py build/card3-logs
```

Copy the contents of `build/card3-logs` to an empty FAT32 card (a separate card, not card 1 or 2). In the car: slot
SD1, wait up to 60 s, answer Continue if asked, do not pull the card while it updates. To fetch the logs the card runs the
full M.I.B. 3.6.0 `stuff.sh` in update mode (SWDL), as when M.I.B. was installed: the unit re-installs M.I.B. 3.6.0 on
the way. At the end `PMCP_LOGS/PMCP_LOGS_RESULT.txt` ends with `RESULT=OK copied=N aa_logs=A cp_logs=C` (or
`RESULT=NO_LOGS`: nothing was saved in GEM first). M.I.B. disarms the card after each use
(`Swdlautorun.txt` -> `_Swdlautorun.txt`); rename it back on a computer to use it again. Details:
`PMCP_LOGS_README.txt` on the card.

## Android Auto off

- `aa_advanced` → **"AA remove (factory Android Auto back)"**: the factory `gal` (the unit's Android Auto receiver) comes back from its
  hash-checked copy, and the Android Auto files and markers are removed. CarPlay and the Java packages stay. Restart
  before connecting the Android phone again.
- **"8. Remove everything (back to factory files)"** on the main screen takes Android Auto off first, then the rest.
- Card 2 (rescue) switches the Android Auto hook off together with our Java packages; "AA remove" or "8. Remove
  everything" then takes the files away.

## What the status says

`Android Auto: off | on mode=gamma | old mode=… | unknown`

- **on**: this card's Android Auto set (also the one installed by v1.5.0, which is the same set). "AA status" also
  says whether it is confirmed or in its trial.
- **old**: the Android Auto files of an earlier experimental card that this card knows (`AA_OLD`); main screen
  "3. Install Android Auto" updates them.
- **unknown** makes the unit state PARTIAL (files from different sets, an interrupted action, an experimental card's
  set this card does not know): main screen "3. Install Android Auto" removes them first (factory `gal` back) and installs this card's set.
