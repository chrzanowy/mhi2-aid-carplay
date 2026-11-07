# Android Auto on the AID (in-car guide)

[Polska wersja](../pl/13-instrukcja-android-auto.md) · Background: [aa/README.md](../../aa/README.md)

Android Auto 0.1 (open alpha, since v1.5.0): the Google Maps picture from an Android phone on the AID, and the VW arrows
from Google Maps. It has its own screen in GEM, **pmcp_android_auto** (GEM: pmcp → pmcp_android_auto, on the main
screen), and is installed separately from CarPlay: "3. Install all features or update" neither installs nor removes it.

## Before

- The CarPlay map is installed (main screen "2. Install the CarPlay map on the AID", or "3. Install all features or
  update"). Android Auto uses the CarPlay map's video path.
- For the VW arrows from Google Maps: main screen **"3. Install all features or update: map, route guidance, zoom,
  day/night, song title"**, restart, then **"4. Confirm: everything works (only in the first start after 3)"** in that
  start. Its route guidance package `rg` shows the arrows for CarPlay and for Android Auto. Without it you get the
  picture only.

## Android Auto on

1. pmcp_android_auto → **"AA 1. Android Auto on: Google Maps on the AID + VW arrows (also updates an earlier card's AA)"**
   → `PMCP_AA_ON_OK mode=gamma`. It also updates the Android Auto files of an earlier experimental card (status
   "old"), with no removal first. If `rg` is not on yet, it says: "VW arrows from Google Maps need rg: main menu,
   3. Install all features or update."
2. Restart the unit (hold the volume knob ~10 s).
3. Android phone on the cable, Android Auto, a route in Google Maps. The first Android Auto session of this start is a
   **trial**.
4. The picture comes about 5 s after the phone connects (the AID has to be ready first). If the Google Maps picture is
   on the AID: in the same start **"AA 2. Confirm: AA works (only in the start of the AA trial)"** →
   `PMCP_AA_CONFIRM_OK`. From then on Android Auto starts with it every time.
5. Without Confirm the next start has the factory Android Auto again (no picture on the AID, nothing else changes).
   **"AA 3. Try again: the next AA connection is a new trial"** allows one more trial; then restart.

## Known limits

- The stream starts about 5 s after the phone connects.
- Now and then the picture starts dark (or the AID shows its loading screen) until the phone sends its next key frame.
  Plugging the phone in again helps.
- No VW arrow at the very first step of a route ("depart").
- Destination distance and arrival time are shown in the Google Maps picture, not on the VW bar.
- The VW arrow and bar end about 10 s after Google Maps stops sending navigation (for example after Maps closed without
  ending the route); CarPlay keeps a quiet route for 180 s.
- Card 2 (rescue) and the Java packages share one switch-off marker (`DISABLED`). "3. Install all features or update"
  (and any Java on / update) removes it, and with it switches the Android Auto hook the rescue card had switched off
  back on. To keep Android Auto off after the rescue card: "AA remove (factory Android Auto back)".
- "AA save log" during an active Android Auto session can answer `AA_LOG_COPY_SHORT` (the log grew while it was
  copied). Unplug the phone and press it again in the same start.
- `guidance-evidence.txt` (rg's message counts, next to `adapter-status.txt`) counts Android Auto and CarPlay together.

## If something goes wrong: what to photograph

**In the same start, without unplugging the phone:**

1. **"AA status and stream analysis (read-only)"**: photograph every page. Most useful lines: `Android Auto:` (the state),
   `dawkowanie:` (pacing), `przerwy:` (gaps between frames), `klatki co 10s` / `KB co 10s` (frames and KB per 10 s, the
   last 5 minutes), `duze klatki` (large frames), `sync startu:`, `pierwsze IDR`, and the "Manoeuvres for rg" lines.
2. **"AA save log: copy this start's AA log to the unit (for the log card)"** → `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`.
   Up to 5 logs are kept. If it says `AA_LOG_COPY_SHORT`: unplug the phone and press it again (same start).
3. **"Status (read-only)"** on the main screen: photograph it too (Java set, route guidance, Android Auto).
4. Then unplug and plug in the phone.

At home: card 3 (logs) in update mode copies the logs to `PMCP_LOGS/` on that card (it only reads the unit). Afterwards
**"AA delete saved logs (after the log card copied them)"**.

### Card 3 (logs)

`install.sh` does not build it. On the computer, from the repository (needs the same M.I.B. 3.6.0 zip in
`mib/downloads/` as the rescue card):

```
python3 -I installer/build_logcard.py build/card3-logs
```

Copy the contents of `build/card3-logs` to an empty FAT32 card (a separate card, not card 1 or 2). In the car: slot
SD1, wait up to 60 s, answer Continue if asked, do not pull the card while it updates. To fetch the logs the card runs the
full M.I.B. 3.6.0 `stuff.sh` in update mode (SWDL), as when M.I.B. was installed: the unit re-installs M.I.B. 3.6.0 on
the way. At the end `PMCP_LOGS/PMCP_LOGS_RESULT.txt` ends with `RESULT=OK`. M.I.B. disarms the card after each use
(`Swdlautorun.txt` -> `_Swdlautorun.txt`); rename it back on a computer to use it again. Details:
`PMCP_LOGS_README.txt` on the card.

## Android Auto off

- **"AA remove (factory Android Auto back)"**: the factory `gal` (the unit's Android Auto receiver) comes back from its
  hash-checked copy, and the Android Auto files and markers are removed. CarPlay and the Java packages stay. Restart
  before connecting the Android phone again.
- **"Remove everything (back to factory files)"** on the main screen takes Android Auto off first, then the rest.
- Card 2 (rescue) switches the Android Auto hook off together with our Java packages; "AA remove" or "Remove
  everything" then takes the files away.

## What the status says

`Android Auto: off | on mode=gamma | old mode=… | unknown`

- **on**: this card's Android Auto set. "AA status" also says whether it is confirmed or in its trial.
- **old**: the Android Auto files of an earlier card; "AA 1" updates them.
- **unknown** makes the unit state PARTIAL (files from different sets, an interrupted action): "AA remove", then "AA 1".
