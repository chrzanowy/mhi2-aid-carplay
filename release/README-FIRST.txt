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
  3. The helper asks which card to make. Make CARD 2 (RESCUE) first, then run it again
     for CARD 1 (INSTALL). Insert an empty card when it asks.
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

  The buttons in the green menu are in Polish. Translations:
    Sprawdz = Check                 Instaluj obraz = Install picture
    Zmien wariant = Change variant  Status instalacji = Installation status
    Wlacz = Enable                  Wylacz = Disable
    Potwierdz = Confirm             Ponow probny start = Repeat trial boot
    Przywroc pliki fabryczne = Restore factory files
    Diagnostyka = Diagnostics       (tylko odczyt) = (read-only, changes nothing)
    WYNIK=OK = result OK            RATUNEK = rescue

  PHASE 1 - map picture on the dashboard

  Step 1. Test the rescue card (CARD 2) once, while everything works.
    a) Insert CARD 2 and wait up to 60 seconds. The unit goes into update mode by itself
       and may restart a few times. If it asks a question, choose Continue.
    b) When the normal screen is back, remove the card.
    c) On your computer, open PMCP_RATUNEK_LOG.txt on the card. Near the end it must say
       WYNIK=OK, and the last line must be  === PMCP RATUNEK koniec ===
       Anything else: STOP here and ask for help.
    d) On the card, rename  _Swdlautorun.txt  to  Swdlautorun.txt  (remove the "_").
       This re-arms the card. Put it away somewhere safe.

  Step 2. Check (changes nothing)
    Insert CARD 1. Hold the MENU button about 10 seconds -> green menu opens.
    Go to  =>M.I.B.<=  ->  pmcp_CarPlay_AID.
    The top line must show:  @@VERSION@@
    Press  "1. Sprawdz karte i radio (tylko odczyt)".
    Expected:  PMCP_VERIFY_OK state=STOCK
    Anything else: STOP, take a photo, ask for help. Nothing was changed.

  Step 3. Install the map picture
    Press  "2. Instaluj obraz CarPlay na AID: map-square (etap A)".
    Expected:  PMCP_INSTALL_OK ...    Then restart (volume knob 10 s).
    Connect the iPhone, start navigation in Apple Maps or Google Maps, and switch the
    dashboard to the navigation/map view (buttons on the right side of the steering wheel).
    No picture on the dashboard? On the iPhone: Settings -> General -> CarPlay -> your car ->
    "Forget This Car", then connect again.
    Other map layouts: submenu pmcp_zmien_wariant -> "Zmien wariant na: ..." -> restart.

  PHASE 2 - arrows, arrival time, song title, zoom (only if phase 1 went well)

  Step 4. Unlock phase 2: on your computer, create an EMPTY file named  ODBLOKUJ_ETAP_B
    inside the  pmcp  folder of CARD 1 (no extension!).
       Windows: in the pmcp folder, right-click -> New -> Text Document, name it
                ODBLOKUJ_ETAP_B (turn on View -> "File name extensions" so it is not
                saved as ODBLOKUJ_ETAP_B.txt)
       Mac:     in Terminal type   touch /Volumes/<card name>/pmcp/ODBLOKUJ_ETAP_B

  Step 5. Enable the features ONE AT A TIME, in submenu  pmcp_etap_B_java :
       1. "Wlacz: NavActiveIgnore ..."      (map stays on while the iPhone navigates)
       2. "Wlacz: Tytul i wykonawca ..."    (song title)
       3. "System RG: wlacz ..."  -> restart -> check that CarPlay still connects
          (if it does not: "System RG: wylacz", restart, and skip 4)
       4. "Wlacz: Prowadzenie ..."          (arrows, distance, arrival time)
       5. "Wlacz: Zoom ..."                 (zoom with the steering-wheel arrows)
       6. "Wlacz: Dzien/noc ..."            (day/night map colours)
    For each "Wlacz" (enable):
       - restart (volume knob 10 s). This first start is a TRIAL.
       - if everything works: open the green menu again and press
         "Potwierdz ..." (Confirm) - IN THE SAME START, without switching the car off.
       - if anything is wrong or the screen stays black: just restart again. Without
         "Potwierdz" the next start is the original factory one. Nothing to fix.

  To remove everything: "Przywroc pliki fabryczne" (restore factory files), then restart.

  EMERGENCY (black screen that does not come back after several restarts):
    insert CARD 2 (rescue) and wait. It removes the phase 2 changes by itself.
    Then in the green menu: "Przywroc pliki fabryczne".

  Full guide with photos: docs/in-car-guide.md
