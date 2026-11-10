# In-car guide: step-by-step installation (Passat B8, MHI2 MU1161, AID 791)

Installer version: **`pmcp-0.5.1-mu1161-791-…`** (the suffix identifies the build; it is the first line of
`BUILD-MANIFEST.txt` and is shown in `PMCP_INSTRUKCJA.txt` on card 1 and at the top of the green menu screen).
All green menu labels are in English (since v1.4), quoted below exactly as on the screen.

Everything is done in **one visit to the car**:

```
card 1:  1. Check  →  2. Install CarPlay  →  restart  →  map OK?  →  4. Install additional features  →  restart (trial)
         →  test  →  5. Confirm (same start)  →  restart  →  works from now on
         (Android Auto, optional: 3. Install Android Auto, see 13-android-auto-guide.md)
```

## Cards

| Card | Label | What it does | Note |
|---|---|---|---|
| **1 – install** | `INSTALL` | M.I.B. 3.6.0 + the installer, everything from the green menu, one action at a time | nothing starts by itself |
| **2 – rescue** | `RESCUE - DO NOT INSERT` | when inserted, the unit enters update mode **by itself** and undoes the Java changes | emergencies only; keep it out of the slot |

Both cards are made with the copy helper from the release zip (`README-FIRST.txt`). Always **only one card in the unit**,
always slot **SD1**.

## Rules for every step

- Power: battery charger/booster, or the engine running (outdoors). Ignition ON.
- **Do not interrupt** an action in the green menu (no "Back", do not pull the card) until the result is on the screen.
- Every action ends with a `PMCP_..._OK` line (good) or `PMCP_FAIL ...` (nothing was changed, or it was rolled back). On `FAIL`
  do not press anything else; take a photo of the screen.
- The SD card is read-only in the green menu, so the installer keeps each button's result on the unit
  (`/mnt/persist/pmcp/gem.log`, about 64 KB; the log card copies it; read-only buttons only add their output to it). **Photograph the result of every action.**
- Entering the green menu: hold **MENU for ~10 s** → `=>M.I.B.<=` → **`pmcp_stream_map_aid`**. The header must show the version
  of your build (`pmcp-0.5.1-mu1161-791-…`); a different version = stop.
- "Restart" = **hold the volume knob for ~10 s** (the unit switches off and boots again). Switching the car off and on
  again right away is not a restart (the unit has not gone to sleep yet).

---

## Step 1. Check the card and the unit (read-only)

1. Insert **card 1**. Green menu → `=>M.I.B.<=` → `pmcp_stream_map_aid`.
2. **"1. Check card and unit (read-only)"**. Takes a few seconds (hashes are computed by the unit's factory `sha1sum`).
3. Expected result: **`PMCP_VERIFY_OK state=STOCK`**. Nothing on the unit changes. On any other firmware the check stops here.

Read-only buttons in `pmcp_advanced` → `features_advanced`, all of them change nothing: "Start timeline" (seconds from
unit start to CarPlay, MOST, navigation), "RG last maneuver" (what the iPhone last sent for guidance and which VW arrow the strict mapping gives;
where it says main 0 the guidance package may still show a fallback arrow, e.g. at the start of a route or at a roundabout)
and "Navigation diagnostics" (why the VW navigation does not start).

If anything is unclear, **"0. Diagnostics (read-only, photograph the screen)"** (submenu `pmcp_advanced` →
`features_advanced`) shows the unit's state and changes nothing.

## Step 2. Install the map (stage A)

1. **"2. Install CarPlay: the map on the AID (also repairs or updates it)"** → expect
   `PMCP_INSTALL_OK stage=A variant=map-square-fps40 ...`.
   (`map-square-fps40` is the default layout: the mathsls fork's layout, map only, closer to square, best of five after a
   longer drive; 40 frames per second like mathsls, no more lag than 30 in a test drive. `map-square` is the same at 30.
   After step 3 VW shows the manoeuvre, ETA and distance natively.) On a unit where the map is already installed the same
   button switches back to `map-square-fps40` (`PMCP_SWITCH_OK`) or says `PMCP_MAP_INSTALL_OK (already installed ...)`.
   If the map files are mixed, it removes everything (verified factory files) and installs the map again; then press 3
   and/or 4 again. Files of another mod: nothing is changed.
2. Restart (knob ~10 s).
3. Connect the iPhone (CarPlay), open Apple Maps or Google Maps and **start guidance to a destination**. Switch the AID view to
   navigation/map. AID controls in this car (right side of the steering wheel): **view buttons** (cluster layout), **OK**
   between them, **up/down** next to them (cluster tabs/menu). The left side of the wheel is for driver assistance.
   Select the **Navigation** tab (up/down), then step through the layouts with the view buttons: the CarPlay map appears in
   the small centre dial and in the large full-width layout.
4. Check: CarPlay map on the AID, nothing running under the VW dials and bars.

**If the AID shows no picture:**
1. On the iPhone: Settings → General → CarPlay → this car → **"Forget This Car"**, reconnect.
2. Still nothing: green menu → **`pmcp_advanced` → `carplay_advanced`** → "Switch map layout to: map-clean"
   (wider and lower map window), restart.
3. Other layouts in the same submenu (each change → restart; layouts: [AID frame map](../aid-frame-map.html)):
   `card-clean` (with the iPhone's manoeuvre card), `url-map-hybrid` (map with the speed-limit parameter, which showed
   nothing in the car), `map-clean-l40` (map 40 columns to the left), `map-clean` (200 / 108 / 400 / 296).
   Back to the default: "Switch map layout to: map-square-fps40".

Do not go on to step 3 without a map on the AID. Stage A does not touch how the head unit screen starts: the worst
outcome is no CarPlay picture, and the green menu with "8. Remove everything (back to factory files)" always works.

## Step 3. Install the additional features (or update)

**"4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)"** → expect
**`PMCP_FEATURES_ON_OK`**. (Button 3 is Android Auto, optional: [13-android-auto-guide.md](13-android-auto-guide.md).)

It runs, one after another: route guidance and Java files of a version this card does not support back to factory
(verified copies; e.g. a Java set with an unknown package, or after the rescue card; skipped when not needed), the update
of an earlier route guidance system and Java set (skipped on a new install), the route guidance system (patched iAP2
driver, `iap2.cfg`, reader) and the five Java packages (NavActiveIgnore, song title, route guidance `rg` with arrows,
lanes, distance bar, street name and ETA, zoom, day/night). It does not touch the map (that is 2) and does not install
the optional speed-limit package `sl`. They all land in **one set**, so there is one trial start and one confirmation.
It needs 2; if Android Auto files of a version this card does not support are present, it stops and says so (press 3
first). It stops at the first failure (`PMCP_FAIL=FEATURES_STOPPED_AT_...`; the steps before it stay done, the screen says
which). Pressing it again when everything is on changes nothing.

Updating an earlier install: 2, then (if used) 3, then 4, see [Updating from an earlier version](#updating-from-an-earlier-version).

## Step 4. Trial start, test, confirm

Java changes how the head unit screen starts, so the new set goes through a **trial start**:

```
4. Install additional features  →  restart  →  TRIAL START (the set loads once)
                                              │
                        everything works? ────┤
                            YES                │ NO / black screen
            in the SAME start, green menu:     │ knob ~10 s → next start is factory
            "5. Confirm: everything works"     │ (nothing confirmed, nothing to fix)
            → the set loads at every start     │
```

1. Restart (knob ~10 s). This start is the trial.
2. Check:
   - the unit starts normally (screen, radio, menus) and **CarPlay connects** (wired; plug/unplug once);
   - lanes: at a junction with lanes, the VW lane display on the AID (lane guidance must be on in the VW settings and sent by
     the phone app); a U-turn lane shows its own arrow;
   - route guidance details: an arrow right at the start of the route, the distance bar counting down before a manoeuvre,
     the current street name, and the roundabout symbol with the exit direction at roundabout turns;
   - guidance in Apple Maps: the CarPlay map **stays** on the AID (NavActiveIgnore); time and distance to destination on the
     VW bar and in the left dial; the turn arrow and the distance to the manoeuvre (the arrow appears once the car moves).
     Google Maps and Waze: check whether they work too (it is not known whether they send this data);
   - CarPlay music (Spotify/Apple Music): title and artist in the AID media view;
   - map view on the AID: a **short** press of the up/down arrow on the wheel zooms in/out (holding does nothing);
   - day/night: after a start in daylight with the lights off (not AUTO) the AID map is light; with the lights on, dark.
3. Everything works → **"5. Confirm: everything works (in the first start after 3 or 4)"** → `PMCP_CONFIRM_OK`.
   Only in the trial start (the installer checks this): do not switch the car off between the restart and Confirm.
   The same button also confirms Android Auto when it is in its trial (connect the phone first); if only one of the two
   is in its trial, it confirms that one and says why the other is not.
   Without the card the unit does the same: App-Connect > Settings > **AID navigation configuration** > row **Changes** > "Save:
   everything works" (package `ui`, installed by button 4).
4. Something is wrong or the screen stays black → restart (knob ~10 s): the next start is factory. To try again:
   **"6. Try again: the next start is a new trial"**, restart. To find out which feature is the problem, enable them one at a
   time ([advanced](#advanced-one-feature-at-a-time)).

## Step 5. Restart

Restart once more. From now on the set loads at every start. **"7. Status (read-only)"** shows `state=JAVA`, the set and
`This boot: set=... use=yes`.

## Updating from an earlier version

The same steps for v1.5.0, v1.4.x and v1.0-v1.3. From v1.5.0, 4 adds the settings page (`ui`), so the restart and 5
(or "Save: everything works" on the page) are needed. Only when 2, 3 and 4 all answer "already installed" /
"everything was already on, nothing changed" (a card with the same features) are no restart and no 5 needed.

1. Make **card 1 from this release** and insert it. **"1. Check card and unit (read-only)"** → `PMCP_VERIFY_OK state=JAVA`.
   "7. Status (read-only)" may show "Route guidance system: old" and "packages of an earlier card: rglu": that is
   expected, button 4 replaces them.
2. **"2. Install CarPlay: the map on the AID (also repairs or updates it)"** → usually
   `PMCP_MAP_INSTALL_OK (already installed ...)`.
3. Only if you use Android Auto: **"3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)"** →
   `PMCP_AA_ON_OK mode=gamma`, or `PMCP_AA_INSTALL_OK (already installed: ..., nothing changed)` when this card's set
   (e.g. from v1.5.0) is already there. A set of an earlier experimental card that this card knows is updated in place;
   a set this card does not support is removed first (factory `gal` back), then this card's set is installed.
4. **"4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)"** → `PMCP_FEATURES_ON_OK`
   (or `PMCP_FEATURES_ON_OK (everything was already on, nothing changed)`). It replaces the earlier iAP2 driver and reader by this card's (the factory copies stay) and makes one new Java set in
   which `rglu` (or `rg`, or the experimental `rg-aa`) becomes the new `rg`, and adds `ui` (the settings page).
5. Only if 3 or 4 installed something: restart, this start is the **trial**. Check that CarPlay connects, then the arrows (also right at the start of a route),
   lanes, the distance bar and the street name. With Android Auto: connect the phone in this start as well.
6. **"5. Confirm: everything works (in the first start after 3 or 4)"** in the same start, or on the unit App-Connect >
   Settings > AID navigation configuration > Changes > "Save: everything works"; then restart.
7. Make a **new card 2** (copy helper option 2): rescue cards made before v1.4 do not restore the v1.4 iAP2 driver.

Android Auto in the car, and how to remove it: [13-android-auto-guide.md](13-android-auto-guide.md).

---

# Emergency: card 2 (rescue)

Only if, after Confirm, the screen stays black or keeps restarting and the knob does not help:

1. Insert **card 2** into SD1 and wait (up to ~60 s). The unit enters update mode by itself and may restart several times.
   On the question in the update menu → **Continue**. Do not pull the card while it updates.
2. When the unit is back on its normal screen → remove card 2. The Java part and the route guidance system are undone
   (factory `lsd.sh`, our JARs removed, `/mnt/persist/pmcp/DISABLED`, factory iAP2 driver and `iap2.cfg`); the map stays.
3. Card 1 → "8. Remove everything (back to factory files)" if you want the map gone as well.
4. M.I.B. disarms card 2 after use (`Swdlautorun.txt` → `_Swdlautorun.txt`), so it cannot loop. Re-arm it on a computer:
   copy helper, option **3** (it also shows the result: `PMCP_RESCUE_LOG.txt`, `RESULT=OK`, ending with
   `=== PMCP RESCUE end ===`; a card made before v1.4 writes `PMCP_RATUNEK_LOG.txt` with `WYNIK=OK`).

Optional: card 2 can be tested once on a working unit before step 1. On a unit without our files it changes nothing of
ours (M.I.B. 3.6.0 is installed again on the way). Re-arm it afterwards with option 3.

# Rollback and failures

| Situation | What to do |
|---|---|
| No picture on the AID | iPhone: "Forget This Car", reconnect; then another layout (step 2) |
| Black screen / boot logo looping in the trial start | knob ~10 s; the next start is factory |
| A feature misbehaves | restart without Confirm (factory), then enable features one at a time ([advanced](#advanced-one-feature-at-a-time)) |
| CarPlay does not connect after step 3 | `pmcp_advanced` → `features_advanced` → "Route guidance system off (factory iAP2 driver and iap2.cfg)", restart |
| Black screen after Confirm | **card 2** (emergency above), then card 1 → "8. Remove everything (back to factory files)" |
| Roll back everything | "8. Remove everything (back to factory files)" → `PMCP_RESTORE_OK` → restart (factory unit) |
| Any `PMCP_FAIL` or anything unclear | do not press anything else, photograph the screen, "0. Diagnostics" (read-only) |

The only allowed firmware update is the official K4525. Never cross-flash firmware from another model.

---

# Advanced: one feature at a time

Instead of step 3, the features can be enabled one by one in **`pmcp_advanced` → `features_advanced`**. Every "On ..."
makes a new set → restart → trial start → test → "5. Confirm". "Off ..." goes back to the set without that package: if that set was confirmed before, it loads straight away; if not, it is a trial too. After a restart "Status" shows
`This boot: set=... use=trial` (trial, Confirm needed) or `use=yes` (confirmed).

1. **"On nai: AID map stays while the iPhone navigates (NavActiveIgnore)"**.
   Check: guidance in Apple Maps, the CarPlay map stays on the AID.
2. **"On np: CarPlay song title and artist on the AID"**.
3. Route guidance, two parts:
   - **"Route guidance system on (iAP2 driver, iap2.cfg, reader)"** (not Java, no Confirm) → restart → check **only that
     CarPlay connects**. If not: **"Route guidance system off (factory iAP2 driver and iap2.cfg)"**, restart, and skip
     the next item.
   - **"On rg: route guidance: arrows, lanes, distance bar, street, ETA (needs Route guidance system)"**.
   - From an earlier card: **"Route guidance system update (driver and reader of this card, RG stays on)"** and
     **"Java update: packages of an earlier card -> this card's (rglu -> rg)"** (one trial start, then "5. Confirm");
     button 4 runs both by itself.
4. **"On zoom: CarPlay map zoom with the steering wheel arrows"**. Watch whether it gets in the way of the cluster menu
   (same arrows).
5. **"On dn: CarPlay map day/night on the AID (sent again after start)"**.
   The key case (reported by another 791 owner, omonob #51): car outdoors in daylight, lights off (not AUTO) → start → the
   map must be light. Without this package the map stays dark until the lights are switched on.
6. Optional, only here (button 4 does not install it): **"On sl: native VW map speed limit in the AID road text (optional,
   output off until enabled)"**, see [16-native-speed-limits.md](16-native-speed-limits.md).

`features_advanced` also has the log buttons for support: **"CP save log: copy this start's CarPlay log to the unit (for
the log card)"** and, after the log card (card 3) copied them, **"Delete saved logs, CarPlay and AA (after the log card
copied them)"**.

## Cheat sheet

```
INSTALL:    card 1 → 1. Check (STOCK) → 2. Install CarPlay → restart → map on the AID?
            → 4. Install additional features → restart (trial) → test → 5. Confirm → restart → done
UPDATE:     new card 1 → 1. Check (JAVA) → 2 → (3 if Android Auto is used) → 4 → restart (trial) → test → 5. Confirm
            → restart → make a new card 2
FAILURE:    trial start broken → knob 10 s → factory start;   after Confirm broken → card 2 → 8. Remove everything
RESCUE:     after using card 2: copy helper option 3 on a computer re-arms it
```
