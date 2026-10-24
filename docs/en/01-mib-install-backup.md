# Installing M.I.B. and backing up the unit

Car: Passat B8 MY2018, Discover Pro MHI2 (5NA035042A, H54), `MHI2_ER_VWG13_P4512`, MU1161, AID 791.
Card: microSD (e.g. 32 GB) in an adapter, FAT32/MBR, M.I.B. **V3.6.0** (`MIB_V3.6.0.zip`, SHA-256 `4bfc6e72…`),
files verified by hash, autostart disabled (`_Swdlautorun.txt`). Before use, test the full capacity of the card
together with its adapter (e.g. [`scripts/sdtest.py`](../../scripts/sdtest.py)); the result should be 0 errors.

**Time:** about 1 h in the car (minimum), about 2 h with the optional full backup. **Risk:** low, because installing
M.I.B. and making the backup do not flash any firmware.

---

## 0. Preparation (before going to the car)

- [ ] SD card with M.I.B. in a **good adapter**, write-protect switch **unlocked**.
- [ ] A phone for photographing the screen.
- [ ] **Power**, one of:
  - a charger or power supply with a "supply" mode, ideally ≥ 10 A, on the battery or the jump-start points;
  - or the engine running, **outdoors, not in a garage**. For a backup alone, with no flashing, this is enough.
  - A small 1–2 A maintainer cannot keep up with the ignition on for an hour.
- [ ] Time without hurry. Nothing gets interrupted halfway.
- [ ] Optional: a laptop with VCDS and a cable (HEX-V2 / HEX-NET) for the readouts in section 7.

## 1. Starting state: photos before anything changes

1. Ignition **ON** (or engine running), doors closed, phone disconnected from CarPlay.
2. Hold **MENU for about 3 s**. The (red) service menu opens.
3. Go to the version information and **photograph the version screens**. Look for:
   - train `MHI2_ER_VWG13_P4512` (note whether it ends in `_1`);
   - MU `1161`;
   - part number and HW.
   - The train should start with **MHI2**. If it reads `MIB2_...`, **stop**:
     that indicates an OBD lock left by earlier modifications.
4. If you have VCDS: do the readouts from **section 7** now (Auto-Scan, 5F coding and adaptation), before anything
   changes.
5. Optional, for comparison with the [AID frame model](../aid-frame-map.html): photos of the AID taken **straight on**
   in both views (small and big dials) with the stock map.

## 2. Installing M.I.B.

1. Insert the card into slot **SD1**. In the Passat B8 the slots are in the passenger glovebox; use the one marked "1".
   If there are no markings, do not guess: check the car's manual to find which slot is SD1.
2. **MENU 3 s** → service menu → **Software update** (may be labelled "SW update").
3. Source: **SD card (SD1)** → if asked for a mode, choose **Standard** → package **"M.I.B. Launcher V1.0"**.
4. The list should show **one** package: **Launcher – Y**. If you see anything else, **stop**.
5. **Start update**.
6. The unit **restarts about 3 times**, about 5–10 minutes in total.
   - Do not remove the card.
   - Do not press anything.
   - Do not switch the ignition off.
7. At the end you get a summary with **Launcher: Y**. Leave that screen.
8. A prompt like **"Start diagnostic tester: Main unit/version…"** → press **CANCEL**.
9. Photograph the summary.

During installation M.I.B. automatically makes a **basic backup** (EEPROM, FEC, versions, storage) and enables
developer mode, which GEM needs.

## 3. Entering GEM

1. After installation wait until the system has fully started. **GEM can be unavailable for up to 5 minutes**
   after a cold start.
2. Hold **MENU for about 10 s**. The green menu (GEM) opens.
3. Select **`=>M.I.B.<=`**.
4. Useful: in developer mode, **MEDIA for 3 s** saves a screenshot to the SD card.

## 4. Backup, in order, each step to completion

Wait for the completion message in every step.
**Never press Back and never remove the card while a step is running.**

Photograph the screen after each step.

### 4a. Minimum (required, about 30–40 min)

| # | Path in M.I.B. | Time | What it saves | Why |
|---|---|---|---|---|
| 1 | **Backup → "Backup ~5 minutes"** | ~5 min | EEPROM, full RCC flash dump (including persist and efs-persist, i.e. FEC), MMX fs0, `lsd.jxe`, serial number | data unique to the unit; `lsd.jxe` is not in `/mnt/app` |
| 2 | **Advanced Backup → "app.img to folder structure"** | 10–20 min | all of `/mnt/app` as files: `lsd.sh`, `dio_manager`, CarPlay libraries | originals of the files the mod replaces; hashes for the installer's gates |
| 3 | **Advanced Backup → "system folder"** | 10–15 min | `/mnt/system`, including `/etc/mm/iap2.cfg` | configuration needed for native route guidance |

After these three steps you have everything needed for the work and for reverting the mod.

### 4b. Optional: full backup (about 45–90 min)

Only if you have the time and the power. It is extra comfort in case the whole unit ever has to be restored.
It can also be done another time.

| Path in M.I.B. | Time | What it adds to 4a |
|---|---|---|
| **Advanced Backup → "ALL"** | 45–90 min | raw `app.img` image, RCC images (ifs-root, ifs-emergency, IPL, efs) and MMX, special/persist, speech, Gracenote, station database, BoardBook, file list with hashes, **fwdump** (dump in the layout of an update package) |

Do not switch the ignition off or stop the engine until "All done!" appears.
If ALL fails with an error or fills the card, no harm done: the 4a minimum is already there.

Always skip **"Navigation DB"** (~1 h): the maps are well over ten GB, will not fit on the card, and can be
reinstalled from an official map update if ever needed.

## 5. SVM fix (only after the backup)

1. **M.I.B. → Advanced Settings → Fix SVM**.
2. It clears the "Software Version Management" fault (B201A) that appears after every package installation.
   Do this **after** the backup, so the backup holds the state from before any change.

## 6. Finishing

1. Leave GEM and wait a dozen or so seconds without doing anything.
2. Remove the card.
3. Check that everything works normally: radio, CarPlay, AID with the map, camera.
4. Copy the card contents to a computer and verify the backup:
   - completeness;
   - `RCC_fs0.bin` and EEPROM;
   - size of `lsd.jxe`;
   - the files `lsd.sh` and `dio_manager`;
   - `/etc/mm/iap2.cfg` from the system folder.
   - Also keep a copy of the backup in two places.

The backup is written to the card under `/backup/<MU>-<TRAIN>-<FAZIT>/`, logs under `/backup/logs/`.

## 7. VCDS: diagnostic readout (read only, nothing is changed)

**Rule:** in VCDS you only read and save to a file or take photos. **Do not press "Do It!"**, do not change coding or
adaptation, and do not clear faults before they are saved.
Power as for the backup (charger or engine running outdoors), ignition ON.

**When:** ideally twice:
- **before** installing M.I.B. (step 1): the factory state;
- **after** Fix SVM (step 5): to check that B201A is gone and nothing else has appeared.

### 7a. Auto-Scan of the whole car (required, about 5–10 min)

1. VCDS → **Auto-Scan** → choose the chassis (Passat B8 / 3G) → **Start**.
2. When done, **Save**. The `.txt` file goes to `C:\Ross-Tech\VCDS\Logs\`. Copy it to a USB stick.
3. Do **not** press "Clear all DTCs".

What to take from the Auto-Scan:
- **5F (Information Electr.):** part number (`5NA035042A`), HW `H54`, SW version / train, **coding**, faults;
- **17 (Instruments):** the cluster part number, which confirms AID **791** (number ending `…920 791…`), SW version,
  coding;
- the full fault list before the mod, so new faults can later be told apart from old ones.

### 7b. 5F: coding (about 2 min)

1. **Select → 5F → Coding – 07**.
2. Photograph the screen and copy the **whole Long Coding string** (select, Ctrl+C, paste into a text editor, save).
3. **Cancel** / leave without changes. If VCDS opens the Long Coding Helper, close it **without saving**.

### 7c. 5F: "Dashboard display configuration" adaptation (most important, about 5 min)

This is the block from which the HMI reads the AID map configuration (`DashboardDisplayConfig` in the code, 10 bytes).
The numbers 1172/171/172/1176 from the HMI decompilation ([04-lsd-jxe-decompilation.md](04-lsd-jxe-decompilation.md))
are **internal HMI IDs, not VCDS numbering**. In VCDS, search by name.

1. **Select → 5F → Adaptation – 10**.
2. In the channel list find **"Dashboard display configuration"**. The name may differ slightly:
   look for *Dashboard*, *display configuration*, *Navigation map*, *Kombi*.
3. Select the channel and **photograph every sub-value**. Of interest:

| Position in block | HMI ID | Expected VCDS name | Expected value | Meaning |
|---|---|---|---|---|
| byte 0 | 1172 | Navigation map MOST transmission mode | **MOST streaming (2)** | map stream over MOST |
| byte 1 | 171 | Navigation map compression mode | **H.264 (1)** | codec |
| byte 2 | 172 | Navigation map resolution | **0 = 800×480** (1 = 800×298, 2 = 1010×376) | map size for the AID; confirms the 800×480 stream |
| bytes 3–5 | 1173, 174, 175 | Crossroad detail map … (transmission, compression, resolution) | note it | junction detail map |
| byte 6, bit 4 | 1176 | Navigation map switch | note it | moving the map between screens |
| byte 6, bits 0–3; byte 7 | 1174, 177, 178, 1175, 1218 | remaining positions | note it | — |

4. If VCDS shows the channel as a raw hex string instead of sub-values, photograph the whole string
   (the first 3 bytes are 1172, 171 and 172 respectively).
5. Leave **without** "Do It!".
6. If there is no such channel, photograph **the whole drop-down channel list** of 5F and go on to 7d.

If the stock VW map works on the AID, bytes 0 and 1 must be 2 and 1. In that case nothing in the coding is changed.
Byte 2 only confirms the resolution.

### 7d. Optional: full 5F adaptation map (about 15–30 min)

Saves all adaptation channels to a file, in case something is missing in 7c.

1. **Applications → Controller Channels Map**.
2. Address **5F**, mode **Adaptation (UDS)**, **Start**.
3. The `.csv` file goes to `C:\Ross-Tech\VCDS\Logs\`. Copy it.

The channel map only reads. Even so, do not interrupt it halfway and do not switch the ignition off while it runs.

### What to keep from VCDS

- Auto-Scan before and after (`.txt`);
- 5F Long Coding (text);
- photos of "Dashboard display configuration" or the raw hex;
- optionally the 5F channel map (`.csv`).

---

## ⛔ What not to touch in M.I.B.

- **PATCH AIO**, addFec, CarPlay activation (patching and flashing);
- **CarPlay Maps VC** in M.I.B. (its installer has inverted logic for detecting the navigation patch);
- **NavActiveIgnore**, EU Conversion, TMC, SWDL FW Updates, SWDL Cleaner;
- **Block 5F External Access** (changes the train in EEPROM to `MIB2_…` and blocks updates);
- Restore, Install SSHD, Individual Script.

At this stage use only the three backup steps from 4a, optionally **ALL**, and **Fix SVM**.

## If something goes wrong

- **Black screen or no response after a restart:**
  1. hold the volume knob for about 10 s (hard restart);
  2. if that does not help: switch the ignition off, lock the car, wait a dozen or so minutes until everything is
     asleep, and try again;
  3. last resort per the M.I.B. wiki: pull the unit's fuse or disconnect the battery.
- **Installation error or package missing from the list:** do not try other options, take a photo.
- **Error during the backup:** take a photo and finish the remaining steps; logs will be in `/backup/logs/`.

## Key shortcuts (VW)

| Function | Shortcut |
|---|---|
| Service menu | `MENU` ~3 s |
| GEM (after installing M.I.B.) | `MENU` ~10 s |
| Screenshot to SD (developer mode) | `MEDIA` ~3 s |
| Hard restart of the unit | volume knob ~10 s |
