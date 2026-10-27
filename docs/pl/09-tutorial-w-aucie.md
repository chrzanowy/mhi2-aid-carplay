# Tutorial: instalacja w aucie krok po kroku (Passat B8, MHI2 MU1161, AID 791)

Wersja instalatora: **`pmcp-0.2.0-mu1161-791-…`** (końcówka to skrót z Twojego buildu, zapisany w pierwszej linii
`BUILD-MANIFEST.txt` i w `PMCP_INSTRUKCJA.txt` na karcie).
Etykiety przycisków poniżej są dosłownie takie jak w GEM (bez polskich znaków).

## Karty

| Karta | Etykieta (proponowana) | Co robi | Uwaga |
|---|---|---|---|
| **1 – instalacyjna** (`installer/build_card_install.py`) | `MIB` | M.I.B. 3.6.0 + instalator pmcp, wszystko z GEM, jedna akcja naraz | nic nie startuje samo; trzymaj na niej też backup radia |
| **2 – ratunkowa** (`installer/build_rescue.py`) | `RATUNEK` | po włożeniu radio **samo** wchodzi w tryb aktualizacji i przywraca fabryczne HMI (cofa zmiany Java) | opisz ją „NIE WKŁADAĆ”; nie wozić w slocie |

Zawsze **tylko jedna karta w radiu**, zawsze slot **SD1**.

## Zasady na każdy krok

- Zasilanie: prostownik/booster albo pracujący silnik (na zewnątrz). Zapłon ON.
- Akcji w GEM **nie przerywać** (bez „Back”, bez wyjmowania karty), dopóki na ekranie nie pojawi się wynik.
- Każda akcja kończy się linią `PMCP_..._OK` (dobrze) albo `PMCP_FAIL ...` (nic nie zostało zmienione albo zostało cofnięte). Przy `FAIL`
  nic nie klikaj dalej i zrób zdjęcie ekranu.
- Karta SD jest w GEM tylko do odczytu, więc instalator nie zapisze logu na kartę (wypisuje `PMCP_WARN=SD_LOG_NOT_WRITABLE`
  i działa dalej). **Wynik każdej akcji fotografuj z ekranu.**
- Wejście do GEM: przytrzymaj **MENU ~10 s** → `=>M.I.B.<=` → **`pmcp_CarPlay_AID`**. W nagłówku musi być wersja
  Twojego buildu (`pmcp-0.2.0-mu1161-791-…`); inna wersja = stop.
- „Pełny restart radia” = **pokrętło głośności ~10 s** (radio gaśnie i startuje od nowa). Samo zgaszenie i zapalenie auta zaraz potem to
  nie jest restart (radio jeszcze nie śpi).

---

# FAZA 1 – test ratunku + obraz na AID (bez Javy)

### Krok 1. Test karty ratunkowej (karta 2) na zdrowym radiu

1. Radio działa normalnie. Włóż **kartę 2 (`RATUNEK`)** do SD1 i czekaj (do ~60 s).
2. Radio samo przejdzie w tryb aktualizacji, może się kilka razy zrestartować. Pytanie w menu aktualizacji → **Continue / Dalej**.
   Nie wyjmuj karty.
3. Gdy radio wróci do normalnego ekranu → wyjmij kartę 2.
4. Sprawdź kartę 2 na komputerze: `PMCP_RATUNEK_LOG.txt` kończy się `=== PMCP RATUNEK koniec ===`, przed tym `WYNIK=OK`;
   na karcie jest `_Swdlautorun.txt` (karta sama się rozbroiła).
5. Po sprawdzeniu uzbrój kartę 2 z powrotem (zmiana nazwy `_Swdlautorun.txt` na `Swdlautorun.txt`) i odłóż ją.

Jeśli radio nie weszło samo w tryb aktualizacji albo log jest inny niż `WYNIK=OK`: **stop**, nie przechodź do fazy 2.

### Krok 2. Sprawdzenie karty i radia (tylko odczyt)

1. Włóż **kartę 1 (`MIB`)**. GEM → `=>M.I.B.<=` → `pmcp_CarPlay_AID`.
2. **„1. Check card and unit (read-only)”**. Trwa kilka sekund (hashe liczy fabryczny `sha1sum` radia).
3. Oczekiwany wynik: **`PMCP_VERIFY_OK state=STOCK`**. Nic w radiu się nie zmienia.

Gdy coś jest niejasne, **„0. Diagnostyka (tylko odczyt, zrob zdjecia ekranu)”** (podmenu `pmcp_advanced`) pokazuje stan radia i niczego nie zmienia.

### Krok 3. Instalacja obrazu CarPlay na AID (etap A)

1. **„2. Install the CarPlay map on the AID”** → oczekiwane `PMCP_INSTALL_OK stage=A variant=map-square ...`.
   (`map-square` to wariant domyślny: układ forka mathsls, sama mapa, bliżej kwadratu; najlepszy z pięciu po dłuższej jeździe.
   Manewr, ETA i dystans pokazuje natywnie VW po kroku 8.)
2. Pełny restart radia (pokrętło ~10 s).
3. Podłącz iPhone'a (CarPlay), włącz Apple Maps albo Google Maps i **uruchom prowadzenie do celu**. Na AID przełącz widok na nawigację/mapę.
   Sterowanie AID w tym aucie (prawa strona kierownicy): **przyciski widoku** (układ licznika), między nimi **OK**,
   obok **góra/dół** (zakładki/menu licznika). Lewa strona kierownicy to asystenci (nie dotyczy AID).
   Ustaw zakładkę **Nawigacja** (góra/dół), potem przejdź przyciskami widoku przez układy: mapa CarPlay jest w małej
   tarczy w środku i w dużym układzie na całą szerokość.
4. Sprawdź: mapa CarPlay na AID, czy nic nie wchodzi pod tarcze i paski VW. Zrób zdjęcie AID na wprost.

**Jeśli na AID nie ma obrazu:**
1. W iPhonie: Ustawienia → Ogólne → CarPlay → to auto → **„Zapomnij to auto”**, podłącz ponownie.
2. Dalej nic: GEM → podmenu **`pmcp_advanced` → `pmcp_zmien_wariant`** → „Zmien wariant na: map-clean” (szersze i niższe okno mapy), restart.
3. Inny układ (`pmcp_zmien_wariant`, każda zmiana → restart, bez „4. Confirm”; układy: [mapa ramki AID](../aid-frame-map.pl.html)):
   `card-clean` (z kartą iPhone'a, gdy natywne prowadzenie jeszcze nie działa), `url-map-hybrid` (mapa z parametrem
   ograniczenia prędkości, który w aucie nic nie pokazał), `map-clean-l40` (mapa 40 kolumn w lewo),
   `map-clean` (szerszy i niższy niż map-square: 200 / 108 / 400 / 296).
   Powrót do domyślnego: „Zmien wariant na: map-square”.

Zmiana wariantu podmienia tylko jeden plik (`core.so`), Javy nie dotyka. Etap A nie rusza HMI: najgorszy skutek to brak obrazu
CarPlay; GEM i „Remove everything (back to factory files)” działają zawsze.

### Krok 4. Status

1. **„Status (read-only)”** → powinno być `state=VIDEO`. Zrób zdjęcie ekranu.
2. Do fazy 2 przechodź dopiero, gdy krok 1 dał `WYNIK=OK`, a obraz na AID jest w porządku.

---

# FAZA 2 – paczki Java (funkcje na AID)

Paczki Java zmieniają start HMI (ekran radia), więc każda przechodzi przez **start próbny**:

```
Wlacz: X  →  pełny restart  →  START PRÓBNY (zestaw ładuje się 1 raz)
                                   │
              wszystko działa? ────┤
                 TAK                │ NIE / czarny ekran
     w TYM SAMYM starcie GEM:       │ pokrętło ~10 s → następny start fabryczny
     „4. Confirm: ...”              │ (nic nie potwierdzasz), potem GEM: „Wylacz: X”
     → zestaw ładuje się zawsze     │
```

- **Bez „4. Confirm” każdy następny start jest fabryczny** (bez naszych JAR-ów). Chcesz spróbować jeszcze raz →
  „5. Try again: the next start is a new trial”, restart.
- „4. Confirm” działa **tylko w starcie próbnym** (sprawdzane przez instalator). Nie gaś auta między restartem a potwierdzeniem.
- Każde „Wlacz” tworzy nowy zestaw (wcześniej włączone paczki zostają w nim) → znowu start próbny i znowu „4. Confirm”.
  „Wylacz” wraca do zestawu bez tej paczki: jeśli ten zestaw był już kiedyś potwierdzony, ładuje się od razu, jeśli nie – też próbnie.
  Po restarcie **„Status”** pokazuje linię `This boot: set=... use=trial` (start próbny, trzeba „4. Confirm”) albo `use=yes` (zestaw potwierdzony).
- **Jedna paczka naraz**, po każdej zdjęcie wyniku z ekranu.

### Krok 5. Odblokowanie fazy 2 (na komputerze)

Dopiero po dobrym logu z kroku 1 i działającym kroku 3. Najprościej: pomocnik kopiowania z paczki wydania, opcja **3**.
Sprawdza log karty ratunkowej (`WYNIK=OK` i linia końcowa), ponownie uzbraja kartę 2 i zakłada na karcie 1 pusty plik
**`pmcp/ODBLOKUJ_ETAP_B`**. Ręcznie: załóż ten pusty plik sam (np. `touch /Volumes/MIB/pmcp/ODBLOKUJ_ETAP_B`). Bez niego
wszystkie przyciski fazy 2 odmawiają.

**Szybka ścieżka (zalecana):** ekran główny **„3. Install all features: arrows, ETA, zoom, song title”** → `PMCP_ALL_ON_OK`
→ restart → jeden start próbny ze wszystkim → jeśli CarPlay, mapa i prowadzenie działają: **„4. Confirm: everything works”**
w tym samym starcie. Zastępuje kroki 6–10.

Kroki 6–10 niżej włączają paczki po jednej (przydatne, żeby znaleźć tę, która sprawia kłopot). Są w podmenu
**`pmcp_advanced` → `pmcp_etap_B_java`**.

### Krok 6. NavActiveIgnore – mapa na AID przy prowadzeniu z iPhone'a

1. **„Wlacz: NavActiveIgnore (mapa na AID przy prowadzeniu w iPhonie)”** → `PMCP_JAVA_ON_OK package=nai set=...`.
2. Pełny restart → start próbny.
3. Sprawdź: radio wstaje normalnie (ekran, radio FM, menu, nawigacja VW, CarPlay). W Apple Maps uruchom prowadzenie: mapa CarPlay
   **zostaje** na AID (bez paczki AID może przejść na ekran „nawigacja w telefonie”).
4. OK → **„4. Confirm: everything works (only in the first start after 3)”** → `PMCP_JAVA_CONFIRM_OK`.

### Krok 7. Tytuł i wykonawca utworu

1. **„Wlacz: Tytul i wykonawca utworu CarPlay na AID”** → restart → start próbny.
2. Sprawdź: muzyka z CarPlay (Spotify/Apple Music) → na AID w widoku mediów tytuł i wykonawca. Reszta HMI jak w kroku 6.
3. OK → „4. Confirm”.

### Krok 8. Prowadzenie: strzałki, dystans, czas (dwa etapy)

**8a. System RG** (sterownik CarPlay/iAP2, nie Java):
1. **„System RG: wlacz (sterownik iAP2, iap2.cfg, czytnik)”** → `PMCP_RG_SYSTEM_ON_OK`.
2. Pełny restart. Sprawdź **tylko, czy CarPlay łączy się normalnie** (przewodowo, kilka razy podłącz/odłącz).
3. CarPlay nie działa → **„System RG: wylacz (fabryczny sterownik i iap2.cfg)”**, restart, zdjęcie ekranu. Bez „4. Confirm” (to nie Java).

**8b. Paczka Java:**
1. **„Wlacz: Prowadzenie: strzalki, dystans, czas na AID (wymaga Systemu RG)”** → restart → start próbny.
2. Sprawdź: prowadzenie w Apple Maps → na AID czas i dystans do celu (pasek VW i lewa tarcza), strzałka manewru i dystans
   do manewru (strzałka pojawia się, gdy auto ruszy). Google Maps i Waze: sprawdź, czy też działa (nie wiadomo, czy wysyłają te dane).
3. OK → „4. Confirm”.

### Krok 9. Zoom mapy z kierownicy

1. **„Wlacz: Zoom mapy CarPlay strzalkami na kierownicy”** → restart → start próbny.
2. Sprawdź: widok mapy na AID, **krótkie** naciśnięcie strzałki góra/dół na kierownicy → przybliża/oddala. Przytrzymanie nic nie robi.
   Zwróć uwagę, czy to nie przeszkadza w menu licznika (te same strzałki).
3. OK → „4. Confirm”.

### Krok 10. Dzień/noc mapy na AID

1. **„Wlacz: Dzien/noc mapy CarPlay na AID (ponowne wyslanie po starcie)”** → restart → start próbny.
2. Sprawdź: po starcie mapa na AID ma właściwy tryb (noc przy światłach/w ciemności, dzień w dzień), także po restarcie radia.
   **Najważniejszy przypadek** (zgłoszony przez innego właściciela 791, omonob #51): auto na zewnątrz w dzień, światła wyłączone
   (nie AUTO) → start → mapa ma być jasna. Bez tej paczki mapa zostaje ciemna, dopóki nie włączysz świateł.
   Warto sprawdzić to samo raz **przed** włączeniem paczki (po fazie 1), żeby wiedzieć, czy problem w ogóle u Ciebie występuje.
3. OK → „4. Confirm”.

---

# Wycofanie i awarie

| Sytuacja | Co robisz |
|---|---|
| Brak obrazu na AID | iPhone: „Zapomnij to auto”, podłącz ponownie; potem inny wariant (krok 3) |
| Paczka działa źle, HMI wstaje | GEM → `pmcp_etap_B_java` → „Wylacz: X” → restart → „Status”: przy `This boot: ... use=trial` sprawdź i „4. Confirm” |
| Czarny ekran / logo w kółko w starcie próbnym | pokrętło ~10 s; następny start jest fabryczny. Potem „Wylacz: X” |
| Czarny ekran po potwierdzeniu (zepsuty zestaw potwierdzony) | **karta 2** (jak w kroku 1). Potem karta 1 → „Remove everything (back to factory files)” |
| CarPlay nie łączy się po Systemie RG | „System RG: wylacz”, restart |
| Wszystko wycofać | „Remove everything (back to factory files)” → `PMCP_RESTORE_OK` → restart (radio fabryczne) |
| Cokolwiek `PMCP_FAIL` albo niejasne | nic dalej nie klikaj, zdjęcie ekranu, „0. Diagnostyka” (tylko odczyt) |

Karta 2 cofa tylko Javę i System RG (obraz z etapu A zostaje); resztę sprząta „Remove everything (back to factory files)”.
Po użyciu karta 2 sama się rozbraja: przed następnym razem trzeba ją znów uzbroić na komputerze.

Jedyna dozwolona aktualizacja firmware to oficjalna K4525. Nigdy nie wgrywaj firmware z innego modelu (cross-flash).

## Ściąga

```
FAZA 1:  karta 2 (test, log WYNIK=OK) → karta 1: Sprawdz (STOCK) → Instaluj map-square → restart → AID?
FAZA 2:  ODBLOKUJ_ETAP_B (komputer) → [Wlacz X → restart → test → 4. Confirm] dla: nai, np, (System RG → restart → CarPlay OK) rg, zoom, dn
AWARIA:  pokrętło 10 s → start fabryczny;  potwierdzony zły zestaw → karta 2 → Remove everything
```
