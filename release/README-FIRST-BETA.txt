CarPlay map on the Active Info Display (virtual cockpit) - BETA
VW Golf (US) with Discover Pro MHI2 MU1418 - ready-made SD cards
Build: @@VERSION@@
==========================================================================================

THIS IS A BETA
  Every offline test passed (the same installer tests as the stable release, run against
  this unit's own files), but nothing in it has been tried in a car of this type yet.
  You are the first. The installer is the same careful one as in the stable release:
  every button checks all files first and changes nothing when something does not match,
  and "8. Remove everything" brings back the factory files.

  You use this at your own risk. Not affiliated with Volkswagen, Harman or Apple.

WHO IT IS FOR
  Only this exact unit:
    - head unit Discover Pro MHI2, software MU1418, train MHI2_US_VWG13_P3662
    - Active Info Display, part number ending in 791
    - iPhone with CarPlay, on a cable (wireless adapters often never send the dashboard picture)
  The card checks this in the car and stops on anything else.

WHAT WORKS IN THIS BETA
  The CarPlay map on the dashboard, VW turn arrows, lanes, distance bar and street name,
  map zoom from the steering wheel, day/night of the map, optional native speed limit.
  NOT YET: Android Auto, the song title, the settings page. The menu is the same as in the
  stable release; those buttons say "not yet supported on this unit" and change nothing.
  Skip them.

  If you installed NavActiveIgnore with MIB Toolbox: that is fine. The card recognises it,
  saves it, and replaces it with its own version in step 4 (visit 2). After "8. Remove
  everything" you can install the Toolbox one again from the Toolbox.

WHAT YOU NEED
  - M.I.B. on the head unit (as for your backup)
  - three SD cards, any size, formatted FAT32 (they must be EMPTY)
  - a Windows PC or a Mac with an SD card slot or reader
  - in the car: a battery charger, or the engine running (outdoors)

------------------------------------------------------------------------------------------
PART 1 - MAKE THE SD CARDS (on your computer)
------------------------------------------------------------------------------------------
  1. Unpack this zip.
       Windows: right-click the zip -> "Extract All..." -> Extract.
       Mac: double-click the zip.
  2. Start the copy helper:
       Windows: double-click  Copy-to-SD-Windows.bat
                (if Windows says "Windows protected your PC": "More info" -> "Run anyway")
       Mac:     right-click  Copy-to-SD-macOS.command  -> Open -> Open
                (if the Mac refuses: System Settings -> Privacy & Security -> "Open Anyway")
  3. Run it three times, one empty card each time:
       2 = CARD 2, RESCUE   write on it: "RESCUE - DO NOT INSERT"
       1 = CARD 1, INSTALL  write on it: "INSTALL"
       4 = CARD 3, LOGS     write on it: "LOGS"
     It copies the files, checks every single one, and ejects the card.
     It never formats and never deletes anything. A card that is not empty is refused.

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
    - Ignition ON, battery charger connected or engine running. Never while driving.
    - Take a photo of the screen after every button. The photos are the most useful report.
    - Never pull the card or press Back while an action runs. Wait for a line that starts
      with PMCP_..._OK (good) or PMCP_FAIL (nothing was changed, or it was undone).
    - "Restart" = hold the volume knob for about 10 seconds.
    - CARD 2 and CARD 3 start by themselves when inserted: keep them OUT of the car
      until you need them.

  VISIT 1 - ONLY THE MAP (please stop after this visit and report first)
    1. Insert CARD 1. Hold the MENU button about 10 seconds -> green menu opens.
       Go to  =>M.I.B.<=  ->  pmcp_stream_map_aid.
       The top line must show:  @@VERSION@@
    2. Press  "1. Check card and unit (read-only)".
       Expected:  PMCP_VERIFY_OK state=STOCK
       Anything else: STOP, take a photo. Nothing was changed.
    3. Press  "2. Install CarPlay: the map on the AID (also repairs or updates it)".
       Expected:  PMCP_INSTALL_OK ...
    4. Restart (volume knob 10 s).
    5. Connect the iPhone with the cable. Once after installing: on the iPhone
       Settings -> General -> CarPlay -> your car -> "Forget This Car", then connect again.
    6. Switch the dashboard to the navigation map view (steering wheel buttons).
       Expected: the CarPlay map.
    7. Start a route in Apple Maps (or Google Maps) and drive a few turns. Watch whether the
       dashboard KEEPS the CarPlay map during the route, or switches back to the car's own
       map or to another view.
    8. Before switching the car off: green menu -> pmcp_stream_map_aid -> pmcp_advanced ->
       features_advanced -> "CP save log: copy this start's CarPlay log to the unit (for the log card)".

    Then copy the log to the card: insert CARD 3, wait up to 60 seconds, choose Continue if
    asked, do not pull it while it works. When the normal screen is back, remove it. On a
    computer the logs are in its PMCP_LOGS folder. Send that folder with your photos.
    (CARD 3 disarms itself after one use. To use it again, run the helper's option 4 on an
    empty card, or rename _Swdlautorun.txt back to Swdlautorun.txt on the card.)

    No map at all after step 6? Stop here, take photos, save the log (step 8).

  VISIT 2 - ROUTE GUIDANCE, ZOOM, DAY/NIGHT (only after visit 1 worked)
    1. CARD 1, green menu -> pmcp_stream_map_aid ->
       "4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)".
       It says that song title and settings page are not yet supported on this unit, and
       installs the rest. Expected:  PMCP_FEATURES_ON_OK
    2. Restart (volume knob 10 s). This start is a TRIAL.
    3. Test with a route: VW turn arrows, lanes and distance on the dashboard, street name,
       zoom with the steering wheel arrows (short press), day/night of the map.
    4. Everything works: in THIS SAME START press
       "5. Confirm: everything works (in the first start after 3 or 4)".
       Expected: PMCP_CONFIRM_OK. Then restart once more.
    5. Something is wrong: save the log (visit 1, step 8) and just restart WITHOUT Confirm.
       The next start loads none of the new parts again (the map stays).

  To remove everything: "8. Remove everything (back to factory files)", then restart.
  "7. Status (read-only)" shows what is installed.

------------------------------------------------------------------------------------------
EMERGENCY - CARD 2 (RESCUE)
------------------------------------------------------------------------------------------
  Black or frozen screen: first hold the volume knob ~10 s. The next start loads none of the
  Java parts.
  Only if, after you pressed Confirm, the screen stays black or keeps restarting, and holding
  the volume knob does not help:
    1. Insert CARD 2 in slot SD1 and wait up to 60 seconds. The unit goes into update mode by
       itself and may restart a few times. If it asks a question, choose Continue.
    2. When the normal screen is back, remove the card. Its PMCP_RESCUE_LOG.txt ends with
       RESULT=OK when the rescue worked. It disarms itself after one use.

------------------------------------------------------------------------------------------
WHAT TO REPORT
------------------------------------------------------------------------------------------
  On the GitHub issue where you got this beta: the top line of the menu (the build), photos of
  every button result, what the dashboard showed (map yes/no, kept during the route yes/no,
  arrows and lanes), and the PMCP_LOGS folder from CARD 3.
  Details: docs/BETA.md and docs/BETA-CHANGELOG.md in this package.
