# Instalacja M.I.B. i backup jednostki

Auto: Passat B8 MY2018, Discover Pro MHI2 (5NA035042A, H54), `MHI2_ER_VWG13_P4512`, MU1161, AID 791.
Karta: microSD (np. 32 GB) w adapterze, FAT32/MBR, M.I.B. **V3.6.0** (`MIB_V3.6.0.zip`, SHA-256 `4bfc6e72…`),
pliki zweryfikowane hashami, autostart wyłączony (`_Swdlautorun.txt`). Przed użyciem sprawdź pełną pojemność
karty razem z adapterem (np. [`scripts/sdtest.py`](../../scripts/sdtest.py)); wynik powinien być 0 błędów.

**Czas:** ok. 1 h w aucie (minimum), ok. 2 h z opcjonalnym pełnym backupem. **Ryzyko:** niskie, bo instalacja M.I.B. i backup nie flashują firmware.

---

## 0. Przygotowanie (przed wyjściem do auta)

- [ ] Karta SD z M.I.B. w **dobrym adapterze**, blokada zapisu **odblokowana**.
- [ ] Telefon do zdjęć ekranu.
- [ ] **Zasilanie**, jedno z dwóch:
  - ładowarka lub zasilacz z trybem „supply”, najlepiej ≥ 10 A, na akumulator albo punkty rozruchowe;
  - albo silnik na chodzie, **na zewnątrz, nie w garażu**. Przy samym backupie, bez flashowania, to wystarczy.
  - Mały maintainer 1–2 A nie nadąży za włączonym zapłonem przez godzinę.
- [ ] Wolny czas bez pośpiechu. Niczego nie przerywamy w połowie.
- [ ] Opcjonalnie: laptop z VCDS i kablem (HEX-V2 / HEX-NET) do odczytów z sekcji 7.

## 1. Stan wyjściowy: zdjęcia, zanim cokolwiek zmienimy

1. Zapłon **ON** (albo silnik), drzwi zamknięte, telefon odłączony od CarPlay.
2. Przytrzymaj **MENU przez ok. 3 s**. Otworzy się menu serwisowe (czerwone).
3. Wejdź w informacje o wersji i **zrób zdjęcia ekranów z wersjami**. Szukamy:
   - train `MHI2_ER_VWG13_P4512` (zanotuj, czy z `_1`);
   - MU `1161`;
   - numeru części i HW.
   - Train powinien zaczynać się od **MHI2**. Gdyby był `MIB2_...`, **przerwij**:
     to oznaka blokady OBD z wcześniejszych modyfikacji.
4. Jeśli masz VCDS: teraz zrób odczyty z **sekcji 7** (Auto-Scan, kodowanie i adaptacja 5F), zanim cokolwiek zmienimy.
5. Opcjonalnie, do porównania z [modelem ramki AID](../aid-frame-map.pl.html): zdjęcia AID **na wprost** w obu
   widokach (małe i duże tarcze) z fabryczną mapą.

## 2. Instalacja M.I.B.

1. Włóż kartę do slotu **SD1**. W Passacie B8 sloty są w schowku pasażera; wybierz ten oznaczony „1”.
   Jeśli nie ma oznaczeń, nie zgaduj: sprawdź w instrukcji auta, który slot to SD1.
2. **MENU 3 s** → menu serwisowe → **Software update** („Aktualizacja oprogramowania” albo „SW update”).
3. Źródło: **SD card (SD1)** → jeśli zapyta o tryb, wybierz **Standard** → pakiet **„M.I.B. Launcher V1.0”**.
4. Na liście powinien być **jeden** pakiet: **Launcher – Y**. Jeśli widzisz cokolwiek innego, **przerwij**.
5. **Start update**.
6. Jednostka **zrestartuje się ok. 3 razy**, w sumie ok. 5–10 minut.
   - Nie wyjmuj karty.
   - Nie naciskaj niczego.
   - Nie wyłączaj zapłonu.
7. Na końcu podsumowanie z **Launcher: Y**. Wyjdź z tego ekranu.
8. Pytanie typu **„Start diagnostic tester: Main unit/version…”** → naciśnij **CANCEL**.
9. Zrób zdjęcie podsumowania.

Podczas instalacji M.I.B. automatycznie robi **podstawowy backup** (EEPROM, FEC, wersje, storage)
i włącza tryb deweloperski, który jest potrzebny do GEM.

## 3. Wejście do GEM

1. Po instalacji odczekaj, aż system się w pełni uruchomi. **GEM może być niedostępny do 5 minut**
   po zimnym starcie.
2. Przytrzymaj **MENU przez ok. 10 s**. Otworzy się zielone menu (GEM).
3. Wybierz pozycję **`=>M.I.B.<=`**.
4. Przydatne: w trybie deweloperskim **MEDIA przez 3 s** robi zrzut ekranu na kartę SD.

## 4. Backup, po kolei, każdy do końca

W każdym kroku czekaj na komunikat o zakończeniu.
**Nigdy nie naciskaj Back i nie wyjmuj karty w trakcie.**

Zdjęcie ekranu po każdym kroku.

### 4a. Minimum (obowiązkowe, ok. 30–40 min)

| # | Ścieżka w M.I.B. | Czas | Co zapisuje | Po co |
|---|---|---|---|---|
| 1 | **Backup → „Backup ~5 minutes”** | ~5 min | EEPROM, pełny zrzut flasha RCC (z persist i efs-persist, czyli FEC), MMX fs0, `lsd.jxe`, numer seryjny | dane unikalne dla jednostki; `lsd.jxe` nie leży w `/mnt/app` |
| 2 | **Advanced Backup → „app.img to folder structure”** | 10–20 min | cały `/mnt/app` jako pliki: `lsd.sh`, `dio_manager`, biblioteki CarPlay | oryginały plików, które mod podmienia; hashe do bramek instalatora |
| 3 | **Advanced Backup → „system folder”** | 10–15 min | `/mnt/system`, w tym `/etc/mm/iap2.cfg` | konfiguracja potrzebna do natywnego prowadzenia |

Po tych trzech krokach mamy wszystko, czego potrzebujemy do pracy i do cofnięcia moda.

### 4b. Opcjonalnie: pełny backup (ok. 45–90 min)

Tylko jeśli masz czas i zasilanie. Daje dodatkową wygodę, gdyby trzeba było odtwarzać całą jednostkę.
Można go zrobić także innym razem.

| Ścieżka w M.I.B. | Czas | Co dokłada do 4a |
|---|---|---|
| **Advanced Backup → „ALL”** | 45–90 min | surowy obraz `app.img`, obrazy RCC (ifs-root, ifs-emergency, IPL, efs) i MMX, special/persist, mowa, Gracenote, baza stacji, BoardBook, lista plików z hashami, **fwdump** (zrzut w układzie pakietu aktualizacji) |

Nie wyłączaj zapłonu i nie gaś silnika, dopóki nie pojawi się „All done!”.
Gdyby ALL przerwało się błędem albo zapełniło kartę, nic się nie stało: minimum z 4a już jest.

Zawsze pomijamy **„Navigation DB”** (~1 h): mapy mają kilkanaście GB, nie zmieszczą się na karcie,
a w razie potrzeby można je wgrać z oficjalnej aktualizacji map.

## 5. SVM fix (dopiero po backupie)

1. **M.I.B. → Advanced Settings → Fix SVM**.
2. Usuwa błąd „Software Version Management” (B201A), który pojawia się po każdej instalacji pakietu.
   Robimy to **po** backupie, żeby backup zawierał stan sprzed jakichkolwiek zmian.

## 6. Zakończenie

1. Wyjdź z GEM i odczekaj kilkanaście sekund bez żadnych operacji.
2. Wyjmij kartę.
3. Sprawdź, czy wszystko działa normalnie: radio, CarPlay, AID z mapą, kamera.
4. Skopiuj zawartość karty na komputer i zweryfikuj backup:
   - kompletność;
   - `RCC_fs0.bin` i EEPROM;
   - rozmiar `lsd.jxe`;
   - pliki `lsd.sh` i `dio_manager`;
   - `/etc/mm/iap2.cfg` z folderu system.
   - Do tego kopia zapasowa backupu w dwóch miejscach.

Backup trafia na kartę do `/backup/<MU>-<TRAIN>-<FAZIT>/`, logi do `/backup/logs/`.

## 7. VCDS: odczyt diagnostyczny (tylko odczyt, niczego nie zmieniamy)

**Zasada:** w VCDS wyłącznie czytamy i zapisujemy do pliku albo robimy zdjęcia. **Nie naciskamy „Do It!”**,
nie zmieniamy kodowania ani adaptacji i nie kasujemy błędów, zanim nie są zapisane.
Zasilanie jak przy backupie (ładowarka albo silnik na zewnątrz), zapłon ON.

**Kiedy:** najlepiej dwa razy:
- **przed** instalacją M.I.B. (punkt 1): stan fabryczny;
- **po** Fix SVM (punkt 5): kontrola, że B201A zniknął i nic więcej się nie pojawiło.

### 7a. Auto-Scan całego auta (obowiązkowe, ok. 5–10 min)

1. VCDS → **Auto-Scan** → wybierz podwozie (Passat B8 / 3G) → **Start**.
2. Po zakończeniu **Save**. Plik `.txt` trafia do `C:\Ross-Tech\VCDS\Logs\`. Skopiuj go na pendrive.
3. **Nie** naciskaj „Clear all DTCs”.

Z Auto-Scanu bierzemy:
- **5F (Information Electr.):** numer części (`5NA035042A`), HW `H54`, wersja SW / train, **kodowanie**, błędy;
- **17 (Instruments):** numer części licznika, czyli potwierdzenie AID **791** (końcówka numeru `…920 791…`), wersja SW, kodowanie;
- pełną listę błędów przed modem, żeby później odróżnić nowe od starych.

### 7b. 5F: kodowanie (ok. 2 min)

1. **Select → 5F → Coding – 07**.
2. Zrób zdjęcie ekranu i skopiuj **cały ciąg Long Coding** (zaznacz, Ctrl+C, wklej do notatnika i zapisz).
3. **Cancel** / wyjdź bez zmian. Jeśli VCDS otworzy Long Coding Helper, zamknij go **bez zapisywania**.

### 7c. 5F: adaptacja „Dashboard display configuration” (najważniejsze, ok. 5 min)

To jest blok, z którego HMI czyta konfigurację mapy na AID (w kodzie `DashboardDisplayConfig`, 10 bajtów).
Numery 1172/171/172/1176 z dekompilacji HMI ([04-lsd-jxe-dekompilacja.md](04-lsd-jxe-dekompilacja.md)) to **wewnętrzne ID HMI, a nie numeracja VCDS**.
W VCDS szukamy po nazwie.

1. **Select → 5F → Adaptation – 10**.
2. Na liście kanałów znajdź **„Dashboard display configuration”**. Może się nazywać nieco inaczej:
   szukaj słów *Dashboard*, *display configuration*, *Navigation map*, *Kombi*.
3. Wybierz kanał i **zrób zdjęcie każdej podwartości**. Interesują nas:

| Pozycja w bloku | ID w HMI | Nazwa w VCDS (spodziewana) | Spodziewana wartość | Co to znaczy |
|---|---|---|---|---|
| bajt 0 | 1172 | Navigation map MOST transmission mode | **MOST streaming (2)** | strumień mapy po MOST |
| bajt 1 | 171 | Navigation map compression mode | **H.264 (1)** | kodek |
| bajt 2 | 172 | Navigation map resolution | **0 = 800×480** (1 = 800×298, 2 = 1010×376) | rozmiar mapy dla AID; potwierdza strumień 800×480 |
| bajty 3–5 | 1173, 174, 175 | Crossroad detail map … (transmisja, kompresja, rozdzielczość) | zanotować | mapa skrzyżowań |
| bajt 6, bit 4 | 1176 | Navigation map switch | zanotować | przenoszenie mapy między ekranami |
| bajt 6, bity 0–3; bajt 7 | 1174, 177, 178, 1175, 1218 | pozostałe pozycje | zanotować | — |

4. Jeśli VCDS pokazuje kanał jako surowy ciąg hex zamiast podwartości, sfotografuj cały ciąg
   (pierwsze 3 bajty to odpowiednio 1172, 171, 172).
5. Wyjdź **bez** „Do It!”.
6. Jeśli takiego kanału nie ma, zrób zdjęcia **całej rozwijanej listy kanałów** 5F i przejdź do 7d.

Jeśli fabryczna mapa VW działa na AID, to bajty 0 i 1 muszą być 2 i 1. Wtedy nic w kodowaniu nie zmieniamy.
Bajt 2 potwierdza tylko rozdzielczość.

### 7d. Opcjonalnie: pełna mapa adaptacji 5F (ok. 15–30 min)

Zapis wszystkich kanałów adaptacji do pliku, na wypadek gdyby czegoś brakowało w 7c.

1. **Applications → Controller Channels Map**.
2. Adres **5F**, tryb **Adaptation (UDS)**, **Start**.
3. Plik `.csv` trafia do `C:\Ross-Tech\VCDS\Logs\`. Skopiuj go.

Mapa kanałów tylko czyta. Mimo to nie przerywaj jej w połowie i nie wyłączaj zapłonu w trakcie.

### Co zachować z VCDS

- Auto-Scan przed i po (`.txt`);
- Long Coding 5F (tekst);
- zdjęcia „Dashboard display configuration” albo surowy hex;
- opcjonalnie mapę kanałów 5F (`.csv`).

---

## ⛔ Czego nie ruszać w M.I.B.

- **PATCH AIO**, addFec, CarPlay activation (patchowanie i flashowanie);
- **CarPlay Maps VC** w M.I.B. (instalator ma odwróconą logikę wykrywania patcha nawigacji);
- **NavActiveIgnore**, EU Conversion, TMC, SWDL FW Updates, SWDL Cleaner;
- **Block 5F External Access** (zmienia train w EEPROM na `MIB2_…` i blokuje aktualizacje);
- Restore, Install SSHD, Individual Script.

Na tym etapie używamy wyłącznie trzech kroków backupu z 4a, opcjonalnie **ALL**, oraz **Fix SVM**.

## Gdyby coś poszło nie tak

- **Czarny ekran lub brak reakcji po restarcie:**
  1. przytrzymaj pokrętło głośności ok. 10 s (twardy restart);
  2. jeśli nie pomoże: wyłącz zapłon, zamknij auto, odczekaj kilkanaście minut, aż wszystko uśnie,
     i spróbuj ponownie;
  3. ostateczność według wiki M.I.B.: wyjęcie bezpiecznika jednostki albo odłączenie akumulatora.
- **Błąd instalacji lub brak pakietu na liście:** nie próbuj innych opcji, zrób zdjęcie.
- **Błąd w trakcie backupu:** zrób zdjęcie, dokończ pozostałe kroki; logi będą w `/backup/logs/`.

## Skróty klawiszowe (VW)

| Funkcja | Skrót |
|---|---|
| Menu serwisowe | `MENU` ~3 s |
| GEM (po instalacji M.I.B.) | `MENU` ~10 s |
| Zrzut ekranu na SD (tryb deweloperski) | `MEDIA` ~3 s |
| Twardy restart jednostki | pokrętło głośności ~10 s |
