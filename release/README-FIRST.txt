CarPlay map on the Active Info Display (virtual cockpit)
VW Passat B8 / MQB with Discover Pro MHI2 - ready-made SD cards
Build: @@VERSION@@
Polska wersja: README-FIRST.pl.txt
==========================================================================================

WHAT THIS DOES
  Shows the CarPlay map (Apple Maps, Google Maps) on the 12.3" digital dashboard (AID),
  with native VW turn arrows, lanes, distance bar, street name and arrival time, map zoom
  from the steering wheel, and the current song title.

WHO IT IS FOR
  Only this exact combination (it was tested on one car):
    - head unit Discover Pro MHI2, software MU1161, train MHI2_ER_VWG13_P4512
    - 12.3" Active Info Display, part number ending in 791
    - iPhone with CarPlay
  You do not need to know your software version: the installer in the car checks every file
  first. If your unit is different, it stops and changes nothing.

  You use this at your own risk. Not affiliated with Volkswagen, Harman or Apple.

WHAT YOU NEED
  - M.I.B. installed on the head unit, and a backup made with it
    (see docs/01-install-MIB-and-backup.md - do this first if you have not)
  - two SD cards, any size, formatted FAT32 (they must be EMPTY)
  - a Windows PC or a Mac with an SD card slot or reader
  - in the car: a battery charger, or the engine running (outdoors)

------------------------------------------------------------------------------------------
PART 1 - MAKE THE TWO SD CARDS (on your computer, about 5 minutes)
------------------------------------------------------------------------------------------
  1. Unpack this zip.
       Windows: right-click the zip -> "Extract All..." -> Extract.
       Mac: double-click the zip.
  2. Start the copy helper:
       Windows: double-click  Copy-to-SD-Windows.bat
                (if Windows says "Windows protected your PC": "More info" -> "Run anyway")
       Mac:     right-click  Copy-to-SD-macOS.command  -> Open -> Open
                (if the Mac refuses: System Settings -> Privacy & Security -> "Open Anyway")
  3. The helper asks what to do. Choose 1 to make CARD 1 (INSTALL), then start it again and
     choose 2 for CARD 2 (RESCUE). Insert an empty card when it asks.
     It copies the files, checks every single one, and ejects the card.
     It never formats and never deletes anything. A card that is not empty is refused.
  4. Write on the cards with a pen:
       CARD 1: "INSTALL"
       CARD 2: "RESCUE - DO NOT INSERT"

  Formatting a card as FAT32 (this ERASES it):
       Windows: File Explorer -> right-click the card -> Format -> File system "FAT32"
                (cards over 32 GB: Windows does not offer FAT32 - use a 32 GB card or smaller)
       Mac:     Disk Utility -> select the card -> Erase -> Format "MS-DOS (FAT)",
                Scheme "Master Boot Record"

------------------------------------------------------------------------------------------
PART 2 - IN THE CAR
------------------------------------------------------------------------------------------
  Rules for every step:
    - Only ONE card in the head unit at a time, always slot SD1.
    - Ignition ON, battery charger connected or engine running.
    - Take a photo of the screen after every action (there is no log file).
    - Never pull the card or press Back while an action runs. Wait for a line that starts
      with PMCP_..._OK (good) or PMCP_FAIL (nothing was changed, or it was undone).
    - "Restart" = hold the volume knob for about 10 seconds.

  Take both cards to the car. You only need CARD 1. CARD 2 (rescue) is for emergencies.

  Step 1. Check (changes nothing)
    Insert CARD 1. Hold the MENU button about 10 seconds -> green menu opens.
    Go to  =>M.I.B.<=  ->  pmcp_stream_map_aid.
    The top line must show:  @@VERSION@@
    Press  "1. Check card and unit (read-only)".
    Expected:  PMCP_VERIFY_OK state=STOCK
    Anything else: STOP, take a photo, ask for help. Nothing was changed.

  Step 2. Install the map
    Press  "2. Install CarPlay: the map on the AID (also repairs or updates it)".
    Expected:  PMCP_INSTALL_OK ...
    Restart (volume knob 10 s).
    Connect the iPhone, start navigation in Apple Maps or Google Maps, and switch the
    dashboard to the navigation/map view (buttons on the right side of the steering wheel).
    No picture on the dashboard? On the iPhone: Settings -> General -> CarPlay -> your car ->
    "Forget This Car", then connect again. Still nothing: do not go on to step 3.

  Step 3. Install the rest (only if the map works)
    Green menu -> pmcp_stream_map_aid ->
    "4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)".
    (Already have an earlier version installed? See UPDATING below.)
    Expected:  PMCP_FEATURES_ON_OK
    Android Auto (optional, Android phone): also press
    "3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)".
    Expected:  PMCP_AA_ON_OK mode=gamma. See docs/en/13-android-auto-guide.md.
    Restart (volume knob 10 s). This start is a TRIAL.

  Step 4. Test, then confirm
    Check: CarPlay connects, the map is on the dashboard, and during navigation the VW turn
    arrow, distance and arrival time appear (the arrow shows once the car moves), plus lanes,
    the distance bar before a turn and the street name.
      - With Android Auto: connect the Android phone too and check the map on the dashboard.
      - Everything works: open the green menu and press
        "5. Confirm: everything works (in the first start after 3 or 4)"
        IN THIS SAME START (do not switch the car off before it). Expected: PMCP_CONFIRM_OK
      - Something is wrong, or the screen stays black: just restart (volume knob 10 s).
        Without Confirm the next start is the original factory one. Nothing to fix.
        To try once more: "6. Try again: the next start is a new trial", then restart.

  Step 5. Restart once more (volume knob 10 s). Done: it works like this from now on.

  To remove everything: "8. Remove everything (back to factory files)", then restart.
  "7. Status (read-only)" shows what is installed.

  UPDATING from an earlier version (v1.0 - v1.5.1):
    1. Make CARD 1 from this package. In the car: "1. Check card and unit (read-only)".
       Expected: PMCP_VERIFY_OK state=JAVA. "7. Status (read-only)" may show
       "Route guidance system: old" and "packages of an earlier card: rglu" - that is expected.
    2. "2. Install CarPlay: the map on the AID ..."  ->  usually
       PMCP_MAP_INSTALL_OK (already installed ...)
    3. Only if you use Android Auto: "3. Install Android Auto: ..."  ->  PMCP_AA_ON_OK,
       or PMCP_AA_INSTALL_OK (already installed: ...) (it updates an experimental card's
       Android Auto; a version this card does not support is removed first and replaced).
    4. "4. Install additional features: ..."  ->  PMCP_FEATURES_ON_OK
       (it replaces the earlier route guidance files and packages, also an experimental rg-aa)
       From v1.5.x, 3 brings Android Auto 1.0 and 4 the new settings page, so steps 5 and 6
       are needed. Only if 2, 3 and 4
       all say "already installed" / "everything was already on, nothing changed" (an update
       to a card with the same features), nothing changed - no restart and no 5 needed.
    5. Only if 3 or 4 installed something: restart, this start is a TRIAL. Check the arrows, lanes, street name (and Android Auto,
       if you pressed 3: connect the phone).
    6. "5. Confirm: everything works ..." in this same start, then restart. Or, without the
       card: App-Connect > Settings > AID navigation configuration > Changes >
       "Save: everything works".
    7. Coming from v1.0 - v1.3: make a NEW CARD 2 with the copy helper (option 2): rescue
       cards made before v1.4 do not restore the new route guidance driver.

------------------------------------------------------------------------------------------
EMERGENCY - CARD 2 (RESCUE)
------------------------------------------------------------------------------------------
  Only if, after you pressed Confirm, the screen stays black or keeps restarting, and holding
  the volume knob ~10 s does not help:
    1. Insert CARD 2 in slot SD1 and wait up to 60 seconds. The unit goes into update mode by
       itself and may restart a few times. If it asks a question, choose Continue.
       Do NOT pull the card while it updates.
    2. When the normal screen is back, remove the card. The features are off again; the map
       picture stays. In the green menu: "8. Remove everything (back to factory files)" if you
       want to undo the map too.
    3. The card disarms itself after use, so it cannot run again by accident. To make it ready
       for the next time: on your computer start the copy helper and choose 3 (it also shows
       the result of the run; RESULT=OK = it worked).
  Optional: you can test CARD 2 once on a working unit before step 1. It changes nothing on a
  unit without our files. Re-arm it afterwards with the copy helper, option 3.

  Single features, other map layouts, Android Auto details and the log buttons are in the
  submenu  pmcp_advanced  (screens features_advanced, carplay_advanced, aa_advanced;
  explained in docs/in-car-guide.md).

------------------------------------------------------------------------------------------
CARD 3 (LOGS) - only for problem reports (Android Auto or CarPlay)
------------------------------------------------------------------------------------------
  Not in this package and not made by install.sh. It copies the logs saved with "AA save log"
  (aa_advanced) and "CP save log" (features_advanced) to the card. Its result file ends with
  RESULT=OK copied=N aa_logs=A cp_logs=C (or RESULT=NO_LOGS: nothing was saved first).
  Build it on a computer from the repository (needs the M.I.B. 3.6.0 zip in mib/downloads/,
  as for the rescue card):
      python3 -I installer/build_logcard.py build/card3-logs
  Copy that folder's contents to a separate empty FAT32 card. To fetch the logs it runs the
  full M.I.B. 3.6.0 stuff.sh in update mode (SWDL), as when M.I.B. was installed. See
  docs/en/13-android-auto-guide.md.
