# Beta: other units than the stable one

The stable releases (`main`, tags `vX.Y.Z`) are for one unit only: VW Passat B8, Discover Pro MHI2 **MU1161**
(`MHI2_ER_VWG13_P4512`), AID part 791. Betas on the `beta` branch add other units, one firmware profile at a time
(see [docs/en/07-installer.md](docs/en/07-installer.md#firmware-profiles)). What each beta does is in
[BETA-CHANGELOG.md](BETA-CHANGELOG.md).

A beta has passed every offline test (the same installer tests and power-loss tests as a stable release, run against
the unit's own files), but **nothing in it has been tried in a car of that type yet**. You are the first. The installer
is the same fail-closed one as in the stable releases: every button checks all files first and changes nothing when
something does not match, and "Remove everything" brings back the factory files.

## Current beta: MU1418 (US Golf, `MHI2_US_VWG13_P3662`, AID 791)

### Before you start

- Only for a unit with exactly this firmware: train `MHI2_US_VWG13_P3662`, MU **1418**, AID part 791. The card checks
  this on the unit and stops on anything else.
- You need M.I.B. (More Incredible Bash) already on the unit, as for making the backup. The cards are built from
  your own backup.
- Wired CarPlay (cable). Wireless adapters often never send the cockpit picture.
- Power: engine running or a charger connected. Never install or test while driving.
- Three SD cards (FAT32, 2-32 GB), one card in the unit at a time, always slot **SD1**:
  - **card 1 (install)**: the installer, adds a `pmcp_stream_map_aid` screen to the M.I.B. menu. Nothing starts by itself.
  - **card 2 (rescue)**: only for an emergency. It starts by itself, so keep it **out** of the car until needed.
  - **card 3 (logs)**: copies saved logs from the unit to the card. Also starts by itself; keep it out until needed.
- If you used MIB Toolbox's **NavActiveIgnore**: that is fine. The card recognises it, saves it and replaces it with
  its own version when you install the additional features (step 4). After "Remove everything" you can install the
  Toolbox one again from the Toolbox.

The menu is the same as in the stable release. Android Auto (button 3 and everything under `aa_advanced`), song title
and the settings page are **not yet supported** on this unit: those buttons say so and change nothing. Skip them.

Take a photo of the screen after every button. The photos are the most useful report.

### Visit 1: only the map (please stop here and report first)

1. Insert card 1. Hold **MENU** for about 10 s (green engineering menu), open **=>M.I.B.<=**, then
   **pmcp_stream_map_aid**. The first line must be the version of your card, `pmcp-0.7.0-mu1418-791-<8 characters>`.
   Anything else: stop.
2. Press **"1. Check card and unit (read-only)"**. Expected: `PMCP_VERIFY_OK state=STOCK`. Photo.
3. Press **"2. Install CarPlay: the map on the AID (also repairs or updates it)"**. Expected: `PMCP_INSTALL_OK`. Photo.
4. Restart the unit: hold the volume knob for about 10 s.
5. Connect the iPhone with the cable. Once after installing: iPhone Settings > General > CarPlay > this car >
   **Forget This Car**, then connect again.
6. On the AID, switch to the navigation map view with the steering wheel buttons. Expected: the CarPlay map.
7. Start a route in Apple Maps (or Google Maps) on the phone and drive a few turns. Watch whether the AID **keeps
   the CarPlay map** during the route, or switches back to the car's own map or to another view.
8. Before switching the car off: green menu > pmcp_stream_map_aid > **pmcp_advanced** > **features_advanced** >
   **"CP save log: copy this start's CarPlay log to the unit (for the log card)"**. Photo.

To get the log to a computer: insert card 3, wait up to 60 s, answer **Continue** if asked, do not pull it while it
works. When the normal screen is back, remove it: the logs are in its `PMCP_LOGS` folder. Send that folder.

**No map at all after step 6?** Stop here, take photos, save the log (step 8). You can go back to factory any time with
**"8. Remove everything (back to factory files)"**.

### Visit 2: route guidance, zoom, day/night (only after visit 1 worked)

1. Card 1, green menu > pmcp_stream_map_aid. Press **"4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)"**.
   It says that song title and settings page are not yet supported on this unit and installs the rest.
   Expected: `PMCP_FEATURES_ON_OK`. Photo.
2. Restart (volume knob ~10 s). This start is a **trial**.
3. Test with a route: VW arrows, lanes and distance on the AID, street name, zoom with the steering wheel arrows (short
   press), day/night of the map.
4. Everything works: in **the same start**, press **"5. Confirm: everything works (in the first start after 3 or 4)"**.
   Then restart once more.
5. Something is wrong: save the log as in visit 1, step 8, and just restart **without** Confirm. The next start loads
   none of the new Java parts again (the map stays). Report what you saw.

### If something goes wrong

- Black or frozen screen: hold the volume knob for about 10 s. The next start loads none of our Java parts.
- The normal screen does not come back after a confirmed install: insert **card 2 (rescue)**, wait, remove it when the
  normal screen is back (its `PMCP_RESCUE_LOG.txt` ends with `RESULT=OK`). It disarms itself after one use.
- Back to factory: card 1 > **"8. Remove everything (back to factory files)"**.

### What to report

On the issue where you got the beta: the version from the first line of the menu, photos of every button result, what
the AID showed (map yes/no, kept during the route yes/no, arrows and lanes), and the `PMCP_LOGS` folder from card 3.
