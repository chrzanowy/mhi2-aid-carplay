# Changelog

All releases are for one combination only: VW Passat B8 (MY2018), Discover Pro MHI2 **MU1161**, train
`MHI2_ER_VWG13_P4512`, AID part 791. Installer versions are `pmcp-<x.y.z>-mu1161-791-<build id>`.

## v1.7.1 (2026-11-13)

Installer version `pmcp-0.7.1-mu1161-791-<build id>`. **Nothing changes in the car:** the cards put the same files on
the unit as v1.7.0 (byte-identical apart from the build id), so updating from v1.7.0 is optional and 2, 3 and 4 answer
"already installed" / "nothing changed". Tested in the car on 2026-11-13 with an experimental card of this installer.

- **Firmware profiles:** the facts about the unit firmware (train, MU, pinned stock files, `lsd.jxe` / `lsd.jar` hashes,
  packages, files of earlier cards) moved from the code into `profiles/MU1161/` (`profile.json`, `history.json`), read and
  strictly validated by `scripts/profile.py`. This prepares ports to other firmware (the MU1418 beta is built on it).
- `install.sh` identifies the profile from the backup's `version.txt` (train and MU must match exactly one profile),
  stops on a backup with several `version.txt` files, and has `--check-backup` (identify and check only).
- `build_sd.py` takes `PMCP_PROFILE` (default `MU1161`); every package `build.sh` takes the profile id as its first
  argument; `rg/build.sh` and the driver gate patch take their pins from the profile.
- Tests: profile section (validation, detection, refused mutations), `installer/test/compare_cards.py` (cards of a
  refactor must be byte-identical apart from the build id), update test from the v1.7.0 card and the experimental
  cards f0b878e0 and 3403e8c5 ([55]: 2, 3 and 4 change no file; the experimental Wi-Fi buttons are not on this card).

## v1.7.0 (2026-11-12)

Installer version `pmcp-0.7.0-mu1161-791-<build id>`. v1.6.0 stays available as the previous stable release
(Android Auto 1.0) if you need to go back.

**Android Auto 1.1** (tested in the car on 2026-11-12 with experimental card 9c0c4493, Samsung Galaxy A16, Android 16;
this release ships the same files):

- **Road name, lanes, distance and time to the destination** from Google Maps on the cluster, as with CarPlay, but only
  while the AID does not show the Android Auto map: Google Maps draws them in its own picture, so with the map on the
  AID ours stay hidden and the AID shows them in its other views (trip computer, consumption, media) next to the VW
  arrow. The VW arrow and its distance stay in every view, as in 1.0. The AID's view comes from the HMI's own "cockpit
  map visible" signal (datapool 1110045), which followed every view switch in the car; a switch re-sends the values
  within 250 ms.
  - AA hook (`aa/hook/pmcp_rg.c`): the road name (`road_info`), the lanes and the destination's distance / time from
    Google Maps' navigation messages go into the rg mailbox as the iAP2 keys CarPlay uses (field numbers from kkrvch's
    mib-std2-kombibridge, confirmed by the raw dump). A road name that is not valid UTF-8 is sent empty. The road name
    is shown as Google Maps sends it (at some steps its direction text or the instruction, in the phone's language).
  - rg (`rg/lanes/aa11.py`, `pmcp-guidance7.jar`): the gate, with `com.pmcp.kv.KombiView` reading the AID's view.
- **Song title, artist and album** on the AID for Android Auto too (`pmcp-np2.jar`): the stock Android Auto target never
  subscribes to the phone's now-playing data; a fourth hook adds our own listener, as for CarPlay.
- **Feeder v15:** if the factory video encoder takes the AID video channel in the first 3 minutes after the radio
  starts, the feeder takes it back (at most 3 times) and sends the last key frame again, instead of leaving the AID
  without the map until the phone is reconnected. Reported on MU1367 by tomasz-twardzicki (v1.5.1-e).
- **Diagnostics:** the AA hook writes the raw navigation messages to `/ramdisk/pmcp-aa-rg-raw.txt` (rotated; it holds
  road names and the destination address, in RAM only until "AA save log"; read a saved AA log before posting it), rg writes which view the AID shows to `/ramdisk/pmcp-kombi-view.log`; "AA save log" copies both.
- **Update:** main menu 4 replaces `rg` (`pmcp-guidance4.jar`/`5`/`6` → `pmcp-guidance7.jar`) and `np` (`pmcp-np.jar` →
  `pmcp-np2.jar`) in place with one trial start and one confirmation; `sl`, `ui` and the speed-limit mode stay. Main menu
  3 brings Android Auto 1.0 (v1.6.0) and the experimental sets in place to 1.1 and keeps the chosen AA output. A unit
  with experimental card 9c0c4493 already has this release's files: 3 and 4 change nothing. Host tests [46], new [51]
  (experimental card b542b2d4) and [52] (9c0c4493).

CarPlay route guidance fixes from tomasz-twardzicki's MU1367 v1.4.5 and v1.4.6 (package `rg`, `rg/lanes/v146.py`,
build mode `lanes-uturn-asf-m-aa-r`). In the car since 2026-11-12 with experimental card 9c0c4493 (the same
`pmcp-guidance7.jar`): no problem found, though not every fix came up on that drive.

- **Reroute.** When the phone recalculates the route (route states 1, 5, 0, 3, 1, then a start step at 0 m), the AID
  shows the VW "calculating route" symbol and keeps the distance, the distance bar, the street and the arrival data until
  the phone reports a real distance again. Once the phone is back to guiding, that wait is at most 20 s or 5 s without
  a phone message; then the new route's arrow shows without the old distance. While the phone stays in "calculating"
  (states 3/5) without going back to guiding, the symbol is held like any quiet route, up to 180 s. Before, every
  reroute looked like a new trip and the countdown started over. A stop during a reroute ends guidance 1.5 s later; route end, a new
  destination, another app, disconnect and VW navigation still end it at once.
- **Apple Maps on a Polish phone.** Apple Maps can alternate its name ("Apple Maps" / "Mapy Apple") within one route.
  Each change was taken as another app and cleared the stored manoeuvres and lanes, so arrows and lanes came back only a
  few turns later. Names containing the word "Apple" are now the same app. `guidance-evidence.txt` (in the CarPlay log
  and "RG last maneuver") adds `route_clears` and `source_flips` (no road or destination text).
- **U-turn arrow side.** A U-turn at exactly 180° carries no side. The main arrow now follows the driving side the phone
  sends (right-hand traffic: left U-turn, matching the U-turn lane), and a 180° lane becomes the right U-turn only in
  left-hand traffic. Android Auto arrows are unchanged (our hook sends the side in the angle's sign).
- **Placeholder arrow.** An active CarPlay route without any manoeuvre yet shows the straight VW "direction to
  destination" arrow (no distance) instead of an empty arrow field. Our start-of-route and roundabout fallbacks stay as
  they were; a known manoeuvre we do not map (highway change, roundabout exit without angle) stays empty.
- **CarPlay log** (GEM "CP save log") also saves the first 200 lines of the supervisor's copy of the last exited map
  bridge and supervisor run (`/ramdisk/carplaymaps-diagnostics/last-bridge.log`, `last-supervisor.log`), to see whether
  the map drop about 46 s after start is the bridge's "MOST write failed: Not enough memory" that Tomasz found on MU1367.
- **Update:** main menu 4 replaces `rg` in place (`pmcp-guidance4.jar` → `pmcp-guidance7.jar`, see Android Auto 1.1) with one trial start and
  one confirmation; `sl`, `ui`, the speed-limit mode and Android Auto stay. Host tests: [48] v1.5.1, [49] v1.5.0 and new [50] v1.6.0
  units.
- **Fix (since v1.6.0): "AA status" on the unit printed "tr: cannot execute"** and an empty "AA switches" line: the
  unit has no `tr`. The line now comes from `awk`. The installer tests replace `tr` and `cut` like `printf` (PR #5) and
  fail when any run of `pmcp.sh` calls a command the unit does not have. The CarPlay log line "installed:" is now
  "map stream installed by card:": it names the card that last wrote the map stream, which may be older than the card
  in the slot.
- **Not taken:** compressed album artwork; his map stream default of 27 fps (our core runs the car-tested 40 fps with an
  IDR every 5 frames, `map-square-fps40`; 30 fps is `map-square`); the v1.5.1-e boot-time MOST reclaim (a rebuilt
  bridge; we ship mathsls' MU1161 bridge binary).

### Credits for this release

- **tomasz-twardzicki** (MHI2-Carplay-Maps, GPL-3.0): reroute handling and placeholder arrow (MU1367 v1.4.5,
  `6610cbb`), U-turn side and Apple Maps names with their evidence fields (MU1367 v1.4.6, `d680311`), and the tests
  `TestReroute`, `TestSourceName`, `TestUturnSide`, `TestPlaceholder`, `TestQuietQnx`.

## v1.6.0 (2026-11-11)

Installer version `pmcp-0.6.0-mu1161-791-<build id>`. v1.5.1 stays available as the previous stable release (Android
Auto 0.1 over the CarPlay bridge) if you need to go back.

**Android Auto 1.0**: the first stable Android Auto on the AID (no longer alpha). The picture goes to the AID through
pmcp's own MOST writer instead of the CarPlay bridge; the bridge stays as a fallback output.

- **Own MOST output (direct) by default.** Feeder v14 (`aa/feeder`): it writes the stream to the AID video channel itself
  (TS mux + MOST writer in `aa/most`), no frame pacing and no bridge queue in between. Tested in the car over several
  drives (up to 20 min per session) with no MOST error, no frame lost and no held ACK. The decoder's lead is kept at
  about 80-130 ms; the start hold is 1.5 s instead of 3 s.
- **Output switch on the settings page:** App-Connect > Settings > AID navigation configuration > "Android Auto
  output": "pmcp MOST writer (default)" or "CarPlay bridge (fallback)". Active when this card's Android Auto set is on;
  it writes the same line as GEM and applies at the next phone connection.
- **Settings page in a new file (`pmcp-ui2.jar`).** From v1.5.1, main menu 4 replaces the v1.5.1 page in place and
  keeps `sl` and its speed-limit mode (an update test from a v1.5.1 unit is in the host tests).
- **Output switch without a trial.** GEM `aa_advanced`: "AA output: pmcp MOST writer (default, from the next
  connection)" and "AA output: CarPlay bridge (fallback, from the next connection)". The switch is one line in
  `/mnt/persist/pmcp/aa-extra.conf` (`PMCP_AA_OUTPUT=direct|ring`); it changes no file of the set and no confirmation,
  so no restart and no 5 are needed. Feeder v14 takes only `direct` or `ring` from that line; any other value is ignored
  and the set's default (direct) applies.
- **Main menu 3 updates every earlier Android Auto in place**: the v1.5.0/v1.5.1 set (feeder v10), and the experimental
  sets of earlier cards (feeders v11, v12, v13). The first connection afterwards is a trial (5 or "Save" on the page).
  The output the user chose (direct or bridge) is kept across such an update; a recording switch is not.
- **3 no longer waits for 4** when only the Java part is of a version this card does not support and is plainly ours
  (lsd.sh ours or factory, every JAR of the set present, ours by name or known to this card). Android Auto never touches
  the Java part; 4 replaces it as before. Anything else still stops with "press 4, then 3".
- **GEM button log on the unit.** The SD card is read-only in GEM, so every pmcp button's output now also goes to
  `/mnt/persist/pmcp/gem.log` (at most ~2 x 32 KB). The log card copies it. Read-only buttons ("1. Check", "7. Status",
  AA status) still change nothing installed; their output is appended to gem.log too (only once pmcp made
  `/mnt/persist/pmcp`).
- **"AA delete saved logs"** deletes everything pmcp saved for the log card (AA and CarPlay logs, the recorded phone
  video, the boot log, the button log); with nothing to delete it answers OK instead of a FAIL.
- **"AA save log"** also saves the feeder's full status of the last 3 sessions of that start, so a lost picture can be
  read after the phone was plugged in again.
- Experimental cards (`pmcp-...-exp-...`, built from the same tree with `PMCP_BUILD_EXPERIMENTAL=1`) carry the same
  Android Auto set plus "AA record" (60 s of the phone's video for the log card).

Known issue: after leaving Android Auto on the main screen and coming back, the phone may slow down the picture for the
AID and, rarely, stop it (the AID shows its loading screen). Plugging the phone in again brings it back. The same
happened with the CarPlay bridge; the cause is on the phone's side of the protocol and is still being looked at.

## v1.5.1 (2026-11-10)

A new GEM menu (one button per part, stable versions only) and a settings page on the unit. Installer version
`pmcp-0.5.1-mu1161-791-<build id>`. Android Auto stays 0.1, as in v1.5.0.

- **Settings page on the unit: App-Connect > Settings > "AID navigation configuration"** (package `ui`,
  `pmcp-ui.jar`). It uses the factory look (native rows, drop-down list, touch, back button) and has two rows:
  - **Changes**: shows whether this start is a trial, e.g. "Not saved (trial start)", "Not saved (restart
    first)", "Saved", "Android Auto not saved", "Android Auto: connect the phone", "Off (rescue card)".
  - **Speed limit**: Off / Before street name / Street name (trial). It writes the same file as
    `pmcp.sh speedlimit-mode` (`/mnt/persist/pmcp/native-speedlimit-mode`), under the same lock and rules: `sl` in a
    confirmed, running Java set; "Before street name" also needs `rg`. The change applies within about a second, no
    restart.
- **"Save: everything works" on the unit, no SD card needed.** It does the same as GEM "5. Confirm", during a trial
  start only:
  - CarPlay features: the set's trial marker exists and this start is its trial (`last-boot` "set=SET use=trial").
  - Android Auto: its trial marker and this start's RAM marker exist.
  - Never after the rescue card.
  - Without Save (or 5), the next start loads none of our JARs, as before.
- **Speed-limit mode moved from GEM to the page.** The three GEM mode buttons are gone. "Speed limit status: mode and
  native VW limit data (read-only)" stays in `features_advanced`; `pmcp.sh speedlimit-mode` stays for the command line.
- **"4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)" now also
  installs `ui`.** "On ui" / "Off ui" are in `features_advanced`. `sl` stays optional.
- **Known limits of `ui`:**
  - MU1161 with the 1280x640 VW skin only; on any other view size the page stays factory and logs why.
  - If a trial start is not saved, the next start is factory HMI (no JARs), so the page is not there. Use GEM
    "6. Try again: the next start is a new trial".
  - Save cannot check the card, the firmware or the installed files (GEM 5 can). It relies on the trial running in
    this start.
  - The marker file is synced, its directory is not: a power cut right after Save can lose it. The next start is then
    factory, which is the safe side.
  - Cards v1.5.0 and older see a Java set with `ui` as PARTIAL and change nothing. Press "Off ui" first, or use a card
    of v1.5.1 or later.
  - Off switch for one start: `/ramdisk/pmcp-ui-off`. Log: `/ramdisk/pmcp-ui.log`. A lifecycle error in the
    App-Connect settings view turns the page off until the next start.

### New GEM menu

- **Main screen `pmcp_stream_map_aid`** (was `pmcp_CarPlay_AID`): "1. Check card and unit", "2. Install CarPlay",
  "3. Install Android Auto", "4. Install additional features", "5. Confirm", "6. Try again", "7. Status",
  "8. Remove everything", then `pmcp_advanced`.
  - 2, 3 and 4 each update their own part and replace a version this card does not support:
    - 3: an Android Auto set of another card (e.g. an experimental one) is removed first. This needs a factory `gal`
      copy with the factory hash; without one nothing is written.
    - 4: route guidance or Java files this card does not know (an unknown package, the state the rescue card leaves)
      go back to the verified factory files first, then this card's set is installed. 4 no longer touches the map.
    - 2: switches to the main layout; when the map files are mixed it removes everything, then installs the map.
    - Every one checks this card's files and the factory copies it needs before it writes anything. With unsupported
      Android Auto files and unsupported Java files at once, 3 asks for 4 first; 4 then resets the Java files and asks
      for 3.
  - "5. Confirm" confirms the CarPlay features and Android Auto, whichever is in its trial; "6. Try again" covers both.
    After the rescue card, 6 gives every set a new trial, also a set that was confirmed before.
- "8. Remove everything" also removes `pmcp-*.jar` files listed by a Java set this card does not know.
- **`pmcp_advanced`** with `features_advanced` (diagnostics, logs, speed limit, route guidance system, single
  packages), `carplay_advanced` (map layouts) and `aa_advanced` (Android Auto confirm, try again, status, logs,
  remove). Android Auto is installed only from the main screen.
- **CarPlay log:** "CP save log" keeps this start's supervisor log, route guidance status and boot log for the log
  card (card 3), which now copies CarPlay logs too. "Delete saved logs" removes AA and CarPlay logs.
- **Updating from v1.5.0:**
  1. On the new card, press "2. Install CarPlay …" (usually "already installed"), "3. Install Android Auto …" if you
     use it, then "4. Install additional features …" (it adds `ui` and keeps what is current).
  2. Restart the unit (volume knob ~10 s).
  3. In that trial start, GEM "5. Confirm: everything works (in the first start after 3 or 4)", or on the unit
     App-Connect > Settings > AID navigation configuration > Changes > "Save: everything works".
  - Speed-limit users: the saved mode stays; change it on the page from now on.
  - From v1.4.x: the same three buttons, restart, then 5 or Save.
- Tests: new host tests [32]–[39] for the main menu; the power-loss chain covers 2, 3 and 4 over unsupported versions
  and checks that pressing the same button again finishes an interrupted run.
- **Installer tests run about twice as fast:** the full pre-release set takes ~15 min instead of 30–40, with the same
  checks.
  - The shells (ksh, mksh) run in parallel in one run, each in its own work dir.
  - The power-loss test runs the chain once and keeps the tree before each action, then runs the kill cases in
    parallel workers; in full mode it cross-checks the kept trees against a replay.
  - One `shasum` per tree snapshot. `PMCP_FAULT_QUICK=1` gives a short daily run.

## v1.5.0 (2026-11-07)

Android Auto on the AID, as a separate feature next to CarPlay. Installer version `pmcp-0.5.0-mu1161-791-<build id>`.

- **Android Auto 0.1 (open alpha).** The Google Maps picture from an Android phone on the AID, over the head unit's own
  MOST path, and the native VW arrows from Google Maps. Car-tested with a Samsung Galaxy A16 (Android 16).
  - Feeder v10: start sync (the AID is ready before the phone's first key frame), pacing at 6 Mbit/s with a 20 ms gap
    and no bursts into the video ring, no focus cycle when the bridge asks for a key frame (it broke the phone's
    session).
  - Every new Android Auto set runs once as a trial and stays only after "AA 2. Confirm", like the Java packages. The
    rescue card switches it off too.
  - The VW arrow, bar and street name end 10 s after Google Maps goes quiet (Maps closed or crashed without ending the
    route); before, they stayed up to 60 s. CarPlay keeps its 180 s quiet-route hold.
  - Known limits of 0.1:
    - the stream starts about 5 s after the phone connects; now and then the picture starts dark until the phone's
      next key frame;
    - no VW arrow at the very first step of a route; destination distance and arrival time stay in the Google Maps
      picture;
    - the rescue card's `DISABLED` marker is shared by Android Auto and the Java packages: button 3 (or any Java on /
      update) removes it and so switches an Android Auto hook the rescue card had switched off back on ("AA remove"
      keeps it off);
    - "AA save log" can answer `AA_LOG_COPY_SHORT` during an active Android Auto session: unplug the phone and save
      again in the same start;
    - `guidance-evidence.txt` counts Android Auto and CarPlay messages together.
- **Its own GEM screen.** `pmcp_android_auto` is on the main screen (not under Advanced), with "AA 1. Android Auto on",
  "AA 2. Confirm", "AA 3. Try again", status, log save/clear and "AA remove". Button 3 neither installs nor removes
  Android Auto; "Remove everything" still removes it and puts the factory `gal` back.
- **One `rg` with the Android Auto arrows.** `rg` (`pmcp-guidance4.jar`) now also reads the Android Auto hook's
  manoeuvres while an Android phone is connected. With CarPlay or no phone it behaves exactly like the v1.4.3 `rg`:
  every rg test suite gives the same results, and a new check proves it reads nothing of Android Auto then. During a
  switch between CarPlay and Android Auto nothing of the previous source is shown. The separate package `rg-aa` of the
  experimental cards is gone.
- **Upgrade paths (button 3, one trial start, one Confirm).**
  - v1.4.x: `rg` (`pmcp-guidance.jar`, `pmcp-guidance2.jar`, `pmcp-guidance3.jar`) → `pmcp-guidance4.jar`.
  - Experimental cards (`rg-aa` in `pmcp-guidance-aa.jar` or `pmcp-guidance-aa2.jar`) → `rg`; their Android Auto stays
    as it is. "AA 1" then brings an earlier Android Auto set up to date (status "old" → "on"); the set of the
    experimental card b2bcbbe3 is already this card's. An earlier set that differs only in its feeder settings (card
    030b7df2, 2 Mbit/s) has the same set id: "AA 1" drops its confirmation, so the new settings get a trial start.
  - An Android Auto set this card does not know (status "unknown"): button 3 stops and asks for "AA remove" on the
    Android Auto screen first; the unit state message says the same instead of "run restore".
- **Docs.** README: CarPlay and Android Auto on the AID, with an Android Auto section and photo. In-car guide:
  [docs/en/13-android-auto-guide.md](docs/en/13-android-auto-guide.md) /
  [docs/pl/13-instrukcja-android-auto.md](docs/pl/13-instrukcja-android-auto.md).
- **Tests:** upgrades from v1.4.2, v1.4.3-style units and the experimental cards f2a7ceb5, 84472aa9 and b2bcbbe3; button
  3 on a unit without Android Auto creates no Android Auto file; power loss during java-update on an Android Auto unit;
  a confirmed 030b7df2 set gets a trial after "AA 1".
- **`install.sh` tests without earlier cards (fix, broken since v1.4.0).** The host tests stopped with "earlier cards
  missing" (exit 99) unless the cards of earlier releases were on the computer, so step 9 of `install.sh` failed for
  everyone who did not pass `--skip-host-tests`. The update tests that need an earlier card are now skipped and named
  ("skip earlier card … not present"); every other test still runs. Release builds are tested with all earlier cards
  (`PMCP_REQUIRE_OLD_CARDS=1`).
- **Card 3 (logs)** for Android Auto problem reports: how to build it (`installer/build_logcard.py`) is in the Android
  Auto guide and README-FIRST; it is not made by `install.sh`.

### Credits for this release

- **[MacsInSpace/mib-cluster-map](https://github.com/MacsInSpace/mib-cluster-map)**: the `gal` hook Android Auto on
  the AID builds on (commit `07361db`, built without SD-card paths, `aa/hook/`).

## v1.4.3 (2026-11-07)

Source release only: no card zip. The v1.4.2 cards stay the download; to use v1.4.3, build it with `install.sh`.
The quiet-route hold has host tests but has not been tried in a car with AID 791 yet. The next release with cards
is v1.5.0.

Apple Maps guidance no longer drops out after 5 s without a new message. Port of tomasz-twardzicki's MU1367 v1.4.4.

- **Quiet-route hold (package `rg`, `rg/lanes/hold.py`).** Apple Maps sends only changes and does not resend
  maneuvers. The reader's 5-second STALE record used to reset the route and every output expired 5 s after the last
  message. After a quiet stretch the arrow came back as a placeholder and the lanes were missing until the next
  maneuver. Now an active route, its arrow, distance bar, lanes and street name are held for up to 180 s of phone
  silence. The route still ends at once on:
  - route end from the phone;
  - CarPlay disconnect;
  - a new reader session;
  - the reader's "invalid" record;
  - VW navigation taking over.
- **One bad message no longer blocks the rest.** A message that fails validation is dropped on its own instead of
  blocking the whole 16-message window. An unreadable route update clears the route.
- **Diagnostics.** `guidance-evidence.txt` (Tomasz's `GuidanceEvidence.java`, at most 4 KiB) records message counts,
  quiet gaps, rejected message shapes (keys and sizes only, never road text) and the phone app's name. "RG last
  maneuver" shows it together with `adapter-status.txt`, and explains a STALE mailbox instead of "unknown format".
- **Unchanged:** our reader `pmcp-r1` and the iAP2 driver (same hashes as v1.4.0-v1.4.2). Only the Java side is ported.
- **Known limit:** if a phone app stops guiding without sending a route end while CarPlay stays connected, the last
  arrow can stay up to 180 s (as in Tomasz's v1.4.4).
- **Update:** button 3 replaces `rg` (`pmcp-guidance2.jar` → `pmcp-guidance3.jar`) with one trial start and one
  Confirm. `sl` and the speed-limit mode stay.
- **Tests:** Tomasz's v1.4.4 tests on our sources (`TestQuietHold`). New `TestHoldPmcp` checks that disconnect, a new
  session, an invalid record and a route end still clear a held route, and that a rejected maneuver message keeps it.
  New: v1.4.2 → v1.4.3 update test; rglast with the evidence file and a STALE mailbox.
- **Experimental cards on v1.4.3:** button 3 also replaces the Android Auto guidance package of the experimental
  v1.4.3 cards (`pmcp-guidance-aa2.jar` → `pmcp-guidance3.jar`), after taking Android Auto off, as before. Test [26].

## v1.4.2 (2026-11)

Fix for the speed-limit modes of v1.4.1, from amjad-alarori's PR #5.

- **Speed-limit mode works on the unit.** The GEM shell on MU1161 has no `printf`, so in v1.4.1 every "Speed limit: …"
  mode button stopped with `printf: cannot execute` and `SPEEDLIMIT_MODE_STAGE_FAILED`, and the mode was not saved.
  The mode file is now written with `echo` (the mode is always `off`, `street` or `turnto`). Found and confirmed in a
  car by amjad-alarori.
- **Tests:** every test run of `pmcp.sh` (`run_tests.sh`, `fault_inject.sh`) now has `printf` replaced by a stand-in
  that fails like the unit (`installer/test/no_printf.inc`). The v1.4.1 card fails 15 checks this way; v1.4.2 passes.
- **Update from v1.4.1:** nothing to change on the unit. The JARs, the driver, the reader and the rescue card are the
  same as v1.4.1; use the v1.4.2 card 1 for the speed-limit buttons. From v1.4.0 or earlier: button 3, as before.

## v1.4.1 (2026-11)

Optional native VW speed limit on the AID, from amjad-alarori's PR #3, adapted to v1.4.

- **Package `sl`** (`speedlimit/`, by amjad-alarori). It reads the car's own speed limit (VW navigation map data,
  `DSITrafficRegulation`), not the phone's. It is not part of button 3: install it with "On sl: …", then Confirm. In
  `pmcp_advanced`:
  - "Speed limit: in front of the street name (top bar and dial; needs sl and rg)": `Limit 50 km/h | <street>` in the
    field that `rg` fills with the iPhone's street name. The AID shows that field in the top bar and in the right dial.
  - "Speed limit TRIAL: in CurrentPositionInfo only (photograph where it shows)": the limit only in the NavSD
    CurrentPositionInfo street, to find out where AID 791 shows that field.
  - "Speed limit: off (street name as before)" and "Speed limit status: …" (read-only).

  The mode is kept across starts; a new install of `sl` starts with it off; "Remove everything" and "Off sl" clear it.
- **`rg` and `sl` together.** Both packages used to replace the factory `TurnToInfo` class, and only one of two such
  JARs can load. `sl` no longer touches that class. `rg` asks `sl` for the prefix by name
  (`rg/lanes/SpeedLimitText.java`), so `rg` alone behaves exactly as in v1.4.0. The text is cut to the factory 75-byte
  budget without splitting a letter. The build refuses two packages with the same class.
- **Update from v1.4.0:** button 3 replaces v1.4.0's `rg` (`pmcp-guidance.jar` → `pmcp-guidance2.jar`) with one trial
  start and one Confirm. The driver and the reader are unchanged.
- The mode is cleared when it can no longer show or should not come back by itself: "Off rg" resets the "in front of
  the street name" mode, and the rescue card removes the mode (make a new rescue card for v1.4.1). On the unit the
  package file is `pmcp-sl2.jar`. A unit that ran PR #3's own card: "Remove everything" first.
- The speed-limit lock is taken only by mode and package changes; a lock left by a killed script never blocks Confirm,
  Try again or Remove everything. In the CurrentPositionInfo trial the text is also cut to 75 bytes.
- Tests:
  - host tests of the prefix without `sl`, with a stand-in and with the real `sl` JAR (also in `install.sh`);
  - a v1.4.0 → v1.4.1 scenario;
  - `sl` in the power-loss chain, including both modes.

### Credits for this release

- **amjad-alarori**: the speed-limit package, its installer actions and its tests (commit `4f71f38`, his authorship
  kept).

## v1.4.0 "rg-main" (2026-11)

One route guidance package with everything that works in the car, a more robust route guidance reader and iAP2
driver, and the whole installer in English. Updating from v1.0–v1.3 needs only button 3 and one Confirm.

### Route guidance

- **One Java package `rg`** replaces `rg` and `rglu`. It carries:
  - the native VW arrow, distance to the manoeuvre, distance and time to destination (tomasz-twardzicki's MU1427 v1.2.0
    port);
  - native VW lane guidance (Tomasz's MU1367 v1.4.0) with VW U-turn lane symbols 114/146 (`rg/lanes/uturn.py`);
  - the native **distance bar** before the manoeuvre, the **current street name**, and faster recovery of the feed after
    a read error (Tomasz's MU1367 v1.4.3, `rg/lanes/asf.py`);
  - **maneuver fallbacks** (`rg/lanes/maneuvers.py`). They apply only where Tomasz's strict mapping gives no arrow
    because iOS left a field out:
    - an arrow right at the **start of the route**;
    - **roundabout turns** (the roundabout symbol with the exit direction);
    - U-turns, ramps and destination left/right without an angle.

    The table comes from harman-f's MibrRgiManeuvers (Skoda MU1440, same VW BAP elements). Exits 28–46 without an angle
    get no arrow; the exit number is not guessed. The full rule table is at the top of
    [`rg/lanes/maneuvers.py`](rg/lanes/maneuvers.py); host test `TestManeuvers` (48,826 checks; every arrow it
    gives is one the strict mapping can also give).
  - Car-tested 2026-11-04: start arrow, street name and distance bar.
- **Reader `rgi-observer` pmcp-r1** (`rg/reader/reader.c`, derived from Tomasz's `release/reader.c`). The old reader ended
  for good when the iAP2 driver did not answer for 1.5 s, and the arrows were then gone until the next unit start. Now:
  - after 1 s without data the supervisor writes one "invalid" record, so no stale arrow stays on screen;
  - after 10 s it kills the stuck worker and starts a new one with a growing delay;
  - it never ends by itself;
  - a file lock keeps a second reader out;
  - `status.txt` counts restarts, timeouts and kills.

  A prebuilt binary is in the repository (`rg/reader/prebuilt/`, sha256 `3166df9b…`), so `install.sh` still needs no
  Docker; `rg/reader/build.sh` rebuilds it with the QNX 6.5 toolchain. Host test: `rg/reader/test_reader.py`.
- **iAP2 driver with a log gate** (`rg/driver/`, sha256 `519ea3c5…`). Tomasz's driver patch logs every route guidance
  message byte by byte into `/dev/shmem/iap2.log`. That log now runs only while `/dev/shmem/pmcp-rgi-debug` exists; it
  is off by default. The 76 bytes of the gate are in the repository (`rg/driver/log-gate.bin`, built from
  `log-gate.S`). The patch checks every word it changes. Emulation test: `rg/driver/test_log_gate.py`.

### Installer

- **Everything in English:**
  - GEM labels and screen names: `pmcp_advanced`, `pmcp_other_layouts`, `pmcp_switch_layout`, `pmcp_packages`;
  - the package buttons start with the package name (`On rg: …`);
  - status messages and the rescue card.
- **Button 3 updates earlier installs.** It runs, in order:
  1. `rg-update`: the v1.0–v1.3 driver and reader are replaced in place, the factory copies are kept;
  2. `java-update`: `rg`/`rglu` of v1.2–v1.3 and the experimental `rglua`, `rgluasf`, `rgluasfa`, `rgluasfm`,
     `rgluasfma` become `rg`;
  3. the main map;
  4. the route guidance system;
  5. every package.

  It gives one new Java set, one trial start and one Confirm. Earlier files are recognised by SHA-256 and size only;
  anything else stays `PARTIAL` or `UNKNOWN` and is not touched. The new `rg` JAR has a file name no earlier card used,
  so an interrupted update never leaves an unconfirmed JAR under a confirmed set.
- New status values:
  - `Route guidance system: old`: an earlier card's driver or reader;
  - `packages of an earlier card: …`.
- **Android Auto from the experimental branch is not part of this release, but this card can always take it off**
  (`aa-remove`: "Remove experimental Android Auto", also the first step of button 3 and of "Remove everything"):
  - it writes only on a pmcp install and only from a factory `gal` copy with the factory hash;
  - running it again finishes an interrupted run.

  Until it is off, every other action reports `UNKNOWN` and changes nothing.
- **Rescue card in English:**
  - renamed files: `pmcp-rescue/pmcp-rescue.sh`, `PMCP_RESCUE_README.txt`, `PMCP_RESCUE_LOG.txt`;
  - log results `RESULT=OK` / `RESULT=UNSURE`;
  - it restores both driver sizes, 743196 (v1.0–v1.3) and 743272 (v1.4);
  - a rescue card made before v1.4 does not restore the v1.4 driver, so make a new one.

  The copy helpers read both log names.
- `RG last maneuver` notes that it shows the strict mapping; the `rg` package may still draw a fallback arrow there.
- Tests:
  - `run_tests.sh`: the real v1.3.0 card and the last experimental card run against the simulated unit (v1.3.0 → v1.4
    with button 3, rgluasfm → rg, experimental Android Auto taken off by aa-remove / button 3 / restore, a bad factory
    `gal` copy refused, a modified old JAR not trusted, an interrupted `java-update` finished by running it again, exact
    factory tree after every restore);
  - `fault_inject.sh`: the power-loss chain starts from a v1.3.0 install and goes through `rg-update`, `java-update`,
    and `aa-remove` and `restore` on a unit with experimental Android Auto; Android Auto is never left without a
    factory `gal`.
- JAR files of ours that the boot list does not name (left by an interrupted update) are never loaded. Status lists
  them, and `java-update` and `restore` remove them.

### Not in this release

- Speed limit from the phone as a number: the iAP2 route guidance messages carry none, according to maxim-smirnov's
  research on iOS 26.6 and 27. `showSpeedLimit=yes` (variant `url-map-hybrid`) only asks the phone to draw a sign in the
  video, and none was seen on this unit.
- Android Auto, AID fast start and cluster day/night experiments stay on branch `experimental`.

### Credits for this release

- **tomasz-twardzicki** (MHI2-Carplay-Maps, GPL-3.0), for:
  - the route guidance this package is built on: the MU1427 port and its strict iAP2 → VW maneuver mapping
    (`LiveModel.map`);
  - lane guidance (MU1367 v1.4.0);
  - the distance bar, street name and feed recovery (MU1367 v1.4.3);
  - the reader that pmcp-r1 is derived from;
  - the iAP2 driver patch.

  His v1.4.2 took our U-turn lane symbols back upstream.
- **harman-f** (mhi2_altscreen_carplay, GPL-3.0, `MibrRgiManeuvers.java` @ `c01bbdc`): the maneuver table behind the
  fallbacks.
- **luka-dev**: iAP2 route guidance decoding and maneuver type names.
- **maxim-smirnov** (mhi2-carplay-cluster): speed-limit research.

## v1.3.0 (2026-10-31)

- Route guidance with native VW lane guidance and U-turn lanes (package `rglu`: Tomasz's MU1367 lanes plus VW lane symbols
  114/146), confirmed in the car.
- Main map `map-square-fps40` (map-square at 40 fps, as mathsls).
- Button 3 "Install all features or update" brings an earlier install to the card's set with one trial start and one
  Confirm.
- Read-only buttons: start timeline, RG last maneuver, navigation diagnostics.
- Docs: AID fast start audit (nothing of it shipped).

## v1.2.0 (2026-10-27)

- One visit to the car: 1. Check → 2. Install map → restart → 3. Install all features → restart (trial) → 4. Confirm.
- Features are no longer locked behind the rescue card; the trial start and the rescue card remain.
- Copy helper option 3 re-arms the rescue card and shows the result of its last run.

## v1.1.0 (2026-10-27)

- Simplified main GEM screen; single packages and map layouts under `pmcp_advanced`.
- "Install all features": every package in one set, one trial start, one Confirm.

## v1.0.0 (2026-10-27)

- Ready-made SD cards (install card and rescue card), copy helpers for Windows and macOS, `make_release.py`.
- `install.sh` builds both cards from your own M.I.B. backup.
- `map-square` as the default layout.

## Initial version (2026-10-24)

- Installer, `core.so` layout variants, NavActiveIgnore, native route guidance port, now playing, steering-wheel zoom
  and day/night for MU1161 + AID 791. Builds on omonob, M.I.B., tomasz-twardzicki and mathsls (see README).
