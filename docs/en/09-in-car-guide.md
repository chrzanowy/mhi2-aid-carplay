# In-car guide: step-by-step installation (Passat B8, MHI2 MU1161, AID 791)

Installer version: **`pmcp-0.2.0-mu1161-791-…`** (the suffix is a hash of your build, written in the first line of
`BUILD-MANIFEST.txt` and in `PMCP_INSTRUKCJA.txt` on the card).
Button labels below are exactly as they appear in GEM: Polish without diacritics. At first use each one is followed by
its meaning in parentheses.

## Cards

| Card | Label (suggested) | What it does | Note |
|---|---|---|---|
| **1 – install** (`installer/build_card_install.py`) | `MIB` | M.I.B. 3.6.0 + the pmcp installer, everything from GEM, one action at a time | nothing starts by itself; keep the unit backup on it as well |
| **2 – rescue** (`installer/build_rescue.py`) | `RATUNEK` | when inserted, the unit enters update mode **by itself** and restores the stock HMI (undoes the Java changes) | mark it "DO NOT INSERT"; do not leave it in the slot |

Always **only one card in the unit**, always slot **SD1**.

## Rules for every step

- Power: battery charger/booster, or the engine running (outdoors). Ignition ON.
- **Do not interrupt** a GEM action (no "Back", do not pull the card) until the result is on the screen.
- Every action ends with a `PMCP_..._OK` line (good) or `PMCP_FAIL ...` (nothing was changed, or it was rolled back). On `FAIL`
  do not press anything else; take a photo of the screen.
- The SD card is read-only in GEM, so the installer cannot write its log to the card (it prints `PMCP_WARN=SD_LOG_NOT_WRITABLE`
  and continues). **Photograph the result of every action.**
- Entering GEM: hold **MENU for ~10 s** → `=>M.I.B.<=` → **`pmcp_CarPlay_AID`**. The header must show the version
  of your build (`pmcp-0.2.0-mu1161-791-…`); a different version = stop.
- "Full unit restart" = **hold the volume knob for ~10 s** (the unit switches off and boots again). Switching the car off and on
  again right away is not a restart (the unit has not gone to sleep yet).

---

# PHASE 1 – rescue test + picture on the AID (no Java)

### Step 1. Test the rescue card (card 2) on a healthy unit

1. The unit works normally. Insert **card 2 (`RATUNEK`)** into SD1 and wait (up to ~60 s).
2. The unit enters update mode by itself and may restart several times. On the question in the update menu → **Continue**.
   Do not pull the card.
3. When the unit is back on its normal screen → remove card 2.
4. Check card 2 on a computer: `PMCP_RATUNEK_LOG.txt` ends with `=== PMCP RATUNEK koniec ===`, preceded by `WYNIK=OK`
   (result OK); the card has `_Swdlautorun.txt` (the card disarmed itself).
5. After checking, re-arm card 2 (rename `_Swdlautorun.txt` to `Swdlautorun.txt`) and put it away.

If the unit did not enter update mode by itself, or the log shows anything other than `WYNIK=OK`: **stop**, do not go on to phase 2.

### Step 2. Check the card and the unit (read-only)

1. Insert **card 1 (`MIB`)**. GEM → `=>M.I.B.<=` → `pmcp_CarPlay_AID`.
2. **"1. Sprawdz karte i radio (tylko odczyt)"** (check card and unit, read-only). Takes a few seconds (hashes are computed
   by the unit's factory `sha1sum`).
3. Expected result: **`PMCP_VERIFY_OK state=STOCK`**. Nothing on the unit changes.

If anything is unclear, **"0. Diagnostyka (tylko odczyt, zrob zdjecia ekranu)"** (diagnostics, read-only, photograph the
screen) shows the unit's state and changes nothing.

### Step 3. Install the CarPlay picture on the AID (stage A)

1. **"2. Instaluj obraz CarPlay na AID: map-clean (etap A)"** (install the CarPlay picture on the AID, stage A) → expect
   `PMCP_INSTALL_OK stage=A variant=map-clean ...`.
   (`map-clean` is the default variant: map only, without the iPhone's manoeuvre card, position marker at the right height;
   after step 8 VW shows the manoeuvre, ETA and distance natively.)
2. Full unit restart (knob ~10 s).
3. Connect the iPhone (CarPlay), open Apple Maps or Google Maps and **start guidance to a destination**. Switch the AID view to navigation/map.
   AID controls in this car (right side of the steering wheel): **view buttons** (cluster layout), **OK** between them,
   **up/down** next to them (cluster tabs/menu). The left side of the wheel is for driver assistance (not the AID).
   Select the **Navigation** tab (up/down), then step through the layouts with the view buttons: the CarPlay map appears in
   the small centre dial and in the large full-width layout.
4. Check: CarPlay map on the AID, nothing running under the VW dials and bars. Take a straight-on photo of the AID.

**If the AID shows no picture:**
1. On the iPhone: Settings → General → CarPlay → this car → **"Forget This Car"**, reconnect.
2. Still nothing: GEM → submenu **`pmcp_zmien_wariant`** (change variant) → "Zmien wariant na: map-square" (change variant to:
   map-square; the mathsls fork's layout, which works for others), restart.
3. Another layout (`pmcp_zmien_wariant`, each change → restart, no "Potwierdz" (confirm); layouts: [AID frame map](../aid-frame-map.html)):
   `card-clean` (with the iPhone's card, while native guidance is not working yet), `url-map-hybrid` (map with the
   speed-limit parameter, which showed nothing in the car), `map-clean-l40` (map 40 columns to the left),
   `map-square` (the mathsls fork's layout: narrower and taller, closer to square; marker about 30 columns left and 20 rows up).
   Back to the default: "Zmien wariant na: map-clean".

Changing the variant swaps only one file (`core.so`) and does not touch Java. Stage A does not touch the HMI: the worst outcome is no
CarPlay picture; GEM and "Przywroc pliki fabryczne" (restore factory files) always work.

### Step 4. Status

1. **"Status instalacji (tylko odczyt)"** (installation status, read-only) → should show `state=VIDEO`. Photograph the screen.
2. Go on to phase 2 only when step 1 gave `WYNIK=OK` and the picture on the AID is fine.

---

# PHASE 2 – Java packages (features on the AID)

Java packages change how the HMI (the head unit screen) starts, so each one goes through a **trial boot**:

```
Wlacz: X  →  full restart  →  TRIAL BOOT (the set loads once)
                                   │
             everything works? ────┤
                 YES                │ NO / black screen
     in the SAME boot, GEM:         │ knob ~10 s → next boot is stock
     "Potwierdz: ..."               │ (confirm nothing), then GEM: "Wylacz: X"
     → the set loads every time     │
```

- **Without "Potwierdz" every following boot is stock** (without our JARs). To try again →
  "Ponow probny start obecnego zestawu" (repeat trial boot of the current set), restart.
- "Potwierdz" works **only in a trial boot** (the installer checks this). Do not switch the car off between the restart and the confirmation.
- Every "Wlacz" (enable) creates a new set (packages enabled earlier stay in it) → another trial boot and another "Potwierdz".
  "Wylacz" (disable) goes back to the set without that package: if that set was confirmed before, it loads straight away; if not, it is a trial too.
  After a restart **"Status instalacji"** shows a line `This boot: set=... use=trial` (trial boot, "Potwierdz" needed) or `use=yes` (set confirmed).
- **One package at a time**, photograph the result after each one.

### Step 5. Unlock phase 2 (on a computer)

Only after a good log in step 1 and a working step 3: create an empty file **`pmcp/ODBLOKUJ_ETAP_B`** on card 1
(e.g. `touch /Volumes/MIB/pmcp/ODBLOKUJ_ETAP_B`). Without it every phase 2 button refuses.

All phase 2 actions are in the submenu **`pmcp_etap_B_java`**.

### Step 6. NavActiveIgnore – map on the AID while the iPhone is guiding

1. **"Wlacz: NavActiveIgnore (mapa na AID przy prowadzeniu w iPhonie)"** (enable NavActiveIgnore, map on the AID during iPhone
   guidance) → `PMCP_JAVA_ON_OK package=nai set=...`.
2. Full restart → trial boot.
3. Check: the unit starts normally (screen, FM radio, menus, VW navigation, CarPlay). Start guidance in Apple Maps: the CarPlay map
   **stays** on the AID (without the package the AID may switch to the "navigation on phone" screen).
4. OK → **"Potwierdz: HMI dziala z obecnym zestawem (tylko w starcie probnym)"** (confirm: HMI works with the current set,
   trial boot only) → `PMCP_JAVA_CONFIRM_OK`.

### Step 7. Track title and artist

1. **"Wlacz: Tytul i wykonawca utworu CarPlay na AID"** (enable CarPlay track title and artist on the AID) → restart → trial boot.
2. Check: music from CarPlay (Spotify/Apple Music) → title and artist in the AID media view. The rest of the HMI as in step 6.
3. OK → "Potwierdz".

### Step 8. Guidance: arrows, distance, time (two stages)

**8a. RG system** (CarPlay/iAP2 driver, not Java):
1. **"System RG: wlacz (sterownik iAP2, iap2.cfg, czytnik)"** (RG system: enable; iAP2 driver, iap2.cfg, reader) → `PMCP_RG_SYSTEM_ON_OK`.
2. Full restart. Check **only that CarPlay connects normally** (wired, plug/unplug a few times).
3. CarPlay does not work → **"System RG: wylacz (fabryczny sterownik i iap2.cfg)"** (RG system: disable; stock driver and
   iap2.cfg), restart, photograph the screen. No "Potwierdz" (this is not Java).

**8b. Java package:**
1. **"Wlacz: Prowadzenie: strzalki, dystans, czas na AID (wymaga Systemu RG)"** (enable guidance: arrows, distance, time on
   the AID; needs the RG system) → restart → trial boot.
2. Check: guidance in Apple Maps → on the AID time and distance to destination (VW bar and left dial), turn arrow and
   distance to the manoeuvre (the arrow appears once the car moves). Google Maps and Waze: check whether it works too
   (it is not known whether they send this data).
3. OK → "Potwierdz".

### Step 9. Map zoom from the steering wheel

1. **"Wlacz: Zoom mapy CarPlay strzalkami na kierownicy"** (enable CarPlay map zoom with the steering-wheel arrows) → restart → trial boot.
2. Check: map view on the AID, a **short** press of the up/down arrow on the wheel → zooms in/out. Holding does nothing.
   Watch whether it gets in the way of the cluster menu (same arrows).
3. OK → "Potwierdz".

### Step 10. Day/night for the AID map

1. **"Wlacz: Dzien/noc mapy CarPlay na AID (ponowne wyslanie po starcie)"** (enable day/night for the CarPlay map on the AID,
   resent after boot) → restart → trial boot.
2. Check: after boot the AID map is in the right mode (night with lights on/in the dark, day in daylight), also after a unit restart.
   **The key case** (reported by another 791 owner, omonob #51): car outdoors in daylight, lights off
   (not AUTO) → start → the map must be light. Without this package the map stays dark until you switch the lights on.
   It is worth checking the same case once **before** enabling the package (after phase 1), to know whether your car has the problem at all.
3. OK → "Potwierdz".

---

# Rollback and failures

| Situation | What to do |
|---|---|
| No picture on the AID | iPhone: "Forget This Car", reconnect; then another variant (step 3) |
| A package misbehaves, HMI starts | GEM → `pmcp_etap_B_java` → "Wylacz: X" → restart → "Status": with `This boot: ... use=trial` check and "Potwierdz" |
| Black screen / boot logo looping in a trial boot | knob ~10 s; the next boot is stock. Then "Wylacz: X" |
| Black screen after confirming (a broken set was confirmed) | **card 2** (as in step 1). Then card 1 → "Przywroc pliki fabryczne" |
| CarPlay does not connect after the RG system | "System RG: wylacz", restart |
| Roll back everything | "Przywroc pliki fabryczne" → `PMCP_RESTORE_OK` → restart (stock unit) |
| Any `PMCP_FAIL` or anything unclear | do not press anything else, photograph the screen, "0. Diagnostyka" (read-only) |

Card 2 undoes only Java and the RG system (the stage A picture stays); "Przywroc pliki fabryczne" cleans up the rest.
After use card 2 disarms itself: re-arm it on a computer before the next use.

The only allowed firmware update is the official K4525. Never cross-flash firmware from another model.

## Cheat sheet

```
PHASE 1:  card 2 (test, log WYNIK=OK) → card 1: Sprawdz (STOCK) → Instaluj map-clean → restart → AID?
PHASE 2:  ODBLOKUJ_ETAP_B (computer) → [Wlacz X → restart → test → Potwierdz] for: nai, np, (System RG → restart → CarPlay OK) rg, zoom, dn
FAILURE:  knob 10 s → stock boot;  bad set confirmed → card 2 → Przywroc
```
