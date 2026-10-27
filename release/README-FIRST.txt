CarPlay map on the Active Info Display (virtual cockpit)
VW Passat B8 / MQB with Discover Pro MHI2 - ready-made SD cards
Build: @@VERSION@@
==========================================================================================

WHAT THIS DOES
  Shows the CarPlay map (Apple Maps, Google Maps) on the 12.3" digital dashboard (AID),
  with native VW turn arrows, distance and arrival time, map zoom from the steering wheel,
  and the current song title.

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
  3. The helper asks what to do. Choose 2 to make CARD 2 (RESCUE) first, then start it again
     and choose 1 for CARD 1 (INSTALL). Insert an empty card when it asks.
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

  PHASE 1 - map picture on the dashboard

  Step 1. Test the rescue card (CARD 2) once, while everything works.
    Insert CARD 2 and wait up to 60 seconds. The unit goes into update mode by itself and
    may restart a few times. If it asks a question, choose Continue. When the normal screen
    is back, remove the card. (Its result is checked on the computer in step 4.)

  Step 2. Check (changes nothing)
    Insert CARD 1. Hold the MENU button about 10 seconds -> green menu opens.
    Go to  =>M.I.B.<=  ->  pmcp_CarPlay_AID.
    The top line must show:  @@VERSION@@
    Press  "1. Check card and unit (read-only)".
    Expected:  PMCP_VERIFY_OK state=STOCK
    Anything else: STOP, take a photo, ask for help. Nothing was changed.

  Step 3. Install the map picture
    Press  "2. Install the CarPlay map on the AID".
    Expected:  PMCP_INSTALL_OK ...    Then restart (volume knob 10 s).
    Connect the iPhone, start navigation in Apple Maps or Google Maps, and switch the
    dashboard to the navigation/map view (buttons on the right side of the steering wheel).
    No picture on the dashboard? On the iPhone: Settings -> General -> CarPlay -> your car ->
    "Forget This Car", then connect again.

  PHASE 2 - arrows, arrival time, song title, zoom (only if phase 1 went well)

  Step 4. On your computer: start the copy helper again and choose 3. It shows the result of
    the rescue card test (it must say WYNIK=OK, "result OK"), re-arms the rescue card, and
    then unlocks the features on CARD 1. If the test did not pass, it stops: do not continue.

  Step 5. In the car, with CARD 1: press  "3. Install all features: arrows, ETA, zoom, song title".
    Expected:  PMCP_ALL_ON_OK
    Restart (volume knob 10 s). This first start is a TRIAL.
    Check: CarPlay connects, the map is on the dashboard, and during navigation the VW
    turn arrow, distance and arrival time appear (the arrow shows once the car moves).
      - Everything works: open the green menu again and press
        "4. Confirm: everything works" - IN THE SAME START, without switching the car off.
        Done: from now on it loads at every start.
      - Something is wrong, or the screen stays black: just restart again (volume knob 10 s).
        Without Confirm the next start is the original factory one. Nothing to fix.
        To try once more: "5. Try again", then restart.

  To remove everything: "Remove everything (back to factory files)", then restart.
  "Status (read-only)" shows what is installed.

  EMERGENCY (black screen that does not come back after several restarts):
    insert CARD 2 (rescue) and wait. It removes the phase 2 changes by itself.
    Then in the green menu: "Remove everything (back to factory files)".

  Single features and other map layouts are in the submenu  pmcp_advanced  (Polish labels,
  explained in docs/in-car-guide.md).
