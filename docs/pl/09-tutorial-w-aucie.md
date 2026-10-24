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
2. **„1. Sprawdz karte i radio (tylko odczyt)”**. Trwa kilka sekund (hashe liczy fabryczny `sha1sum` radia).
3. Oczekiwany wynik: **`PMCP_VERIFY_OK state=STOCK`**. Nic w radiu się nie zmienia.

Gdy coś jest niejasne, **„0. Diagnostyka (tylko odczyt, zrob zdjecia ekranu)”** pokazuje stan radia i niczego nie zmienia.

### Krok 3. Instalacja obrazu CarPlay na AID (etap A)

1. **„2. Instaluj obraz CarPlay na AID: map-clean (etap A)”** → oczekiwane `PMCP_INSTALL_OK stage=A variant=map-clean ...`.
   (`map-clean` to wariant domyślny: sama mapa bez karty manewru iPhone'a, znacznik w dobrej wysokości; manewr, ETA i dystans
   pokazuje natywnie VW po kroku 8.)
2. Pełny restart radia (pokrętło ~10 s).
3. Podłącz iPhone'a (CarPlay), włącz Apple Maps albo Google Maps i **uruchom prowadzenie do celu**. Na AID przełącz widok na nawigację/mapę.
   Sterowanie AID w tym aucie (prawa strona kierownicy): **przyciski widoku** (układ licznika), między nimi **OK**,
   obok **góra/dół** (zakładki/menu licznika). Lewa strona kierownicy to asystenci (nie dotyczy AID).
   Ustaw zakładkę **Nawigacja** (góra/dół), potem przejdź przyciskami widoku przez układy: mapa CarPlay jest w małej
   tarczy w środku i w dużym układzie na całą szerokość.
4. Sprawdź: mapa CarPlay na AID, czy nic nie wchodzi pod tarcze i paski VW. Zrób zdjęcie AID na wprost.

**Jeśli na AID nie ma obrazu:**
1. W iPhonie: Ustawienia → Ogólne → CarPlay → to auto → **„Zapomnij to auto”**, podłącz ponownie.
2. Dalej nic: GEM → podmenu **`pmcp_zmien_wariant`** → „Zmien wariant na: map-square” (układ forka mathsls, który działa u innych), restart.
3. Inny układ (`pmcp_zmien_wariant`, każda zmiana → restart, bez „Potwierdz”; układy: [mapa ramki AID](../aid-frame-map.pl.html)):
   `card-clean` (z kartą iPhone'a, gdy natywne prowadzenie jeszcze nie działa), `url-map-hybrid` (mapa z parametrem
   ograniczenia prędkości, który w aucie nic nie pokazał), `map-clean-l40` (mapa 40 kolumn w lewo),
   `map-square` (układ forka mathsls: węższy i wyższy, bliżej kwadratu; znacznik ok. 30 kolumn w lewo i 20 wierszy wyżej).
   Powrót do domyślnego: „Zmien wariant na: map-clean”.

Zmiana wariantu podmienia tylko jeden plik (`core.so`), Javy nie dotyka. Etap A nie rusza HMI: najgorszy skutek to brak obrazu
CarPlay; GEM i „Przywroc pliki fabryczne” działają zawsze.

### Krok 4. Status

1. **„Status instalacji (tylko odczyt)”** → powinno być `state=VIDEO`. Zrób zdjęcie ekranu.
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
     „Potwierdz: ...”               │ (nic nie potwierdzasz), potem GEM: „Wylacz: X”
     → zestaw ładuje się zawsze     │
```

- **Bez „Potwierdz” każdy następny start jest fabryczny** (bez naszych JAR-ów). Chcesz spróbować jeszcze raz →
  „Ponow probny start obecnego zestawu”, restart.
- „Potwierdz” działa **tylko w starcie próbnym** (sprawdzane przez instalator). Nie gaś auta między restartem a potwierdzeniem.
- Każde „Wlacz” tworzy nowy zestaw (wcześniej włączone paczki zostają w nim) → znowu start próbny i znowu „Potwierdz”.
  „Wylacz” wraca do zestawu bez tej paczki: jeśli ten zestaw był już kiedyś potwierdzony, ładuje się od razu, jeśli nie – też próbnie.
  Po restarcie **„Status instalacji”** pokazuje linię `This boot: set=... use=trial` (start próbny, trzeba „Potwierdz”) albo `use=yes` (zestaw potwierdzony).
- **Jedna paczka naraz**, po każdej zdjęcie wyniku z ekranu.

### Krok 5. Odblokowanie fazy 2 (na komputerze)

Dopiero po dobrym logu z kroku 1 i działającym kroku 3: na karcie 1 załóż pusty plik **`pmcp/ODBLOKUJ_ETAP_B`**
(np. `touch /Volumes/MIB/pmcp/ODBLOKUJ_ETAP_B`). Bez niego wszystkie przyciski fazy 2 odmawiają.

Wszystkie akcje fazy 2 są w podmenu **`pmcp_etap_B_java`**.

### Krok 6. NavActiveIgnore – mapa na AID przy prowadzeniu z iPhone'a

1. **„Wlacz: NavActiveIgnore (mapa na AID przy prowadzeniu w iPhonie)”** → `PMCP_JAVA_ON_OK package=nai set=...`.
2. Pełny restart → start próbny.
3. Sprawdź: radio wstaje normalnie (ekran, radio FM, menu, nawigacja VW, CarPlay). W Apple Maps uruchom prowadzenie: mapa CarPlay
   **zostaje** na AID (bez paczki AID może przejść na ekran „nawigacja w telefonie”).
4. OK → **„Potwierdz: HMI dziala z obecnym zestawem (tylko w starcie probnym)”** → `PMCP_JAVA_CONFIRM_OK`.

### Krok 7. Tytuł i wykonawca utworu

1. **„Wlacz: Tytul i wykonawca utworu CarPlay na AID”** → restart → start próbny.
2. Sprawdź: muzyka z CarPlay (Spotify/Apple Music) → na AID w widoku mediów tytuł i wykonawca. Reszta HMI jak w kroku 6.
3. OK → „Potwierdz”.

### Krok 8. Prowadzenie: strzałki, dystans, czas (dwa etapy)

**8a. System RG** (sterownik CarPlay/iAP2, nie Java):
1. **„System RG: wlacz (sterownik iAP2, iap2.cfg, czytnik)”** → `PMCP_RG_SYSTEM_ON_OK`.
2. Pełny restart. Sprawdź **tylko, czy CarPlay łączy się normalnie** (przewodowo, kilka razy podłącz/odłącz).
3. CarPlay nie działa → **„System RG: wylacz (fabryczny sterownik i iap2.cfg)”**, restart, zdjęcie ekranu. Bez „Potwierdz” (to nie Java).

**8b. Paczka Java:**
1. **„Wlacz: Prowadzenie: strzalki, dystans, czas na AID (wymaga Systemu RG)”** → restart → start próbny.
2. Sprawdź: prowadzenie w Apple Maps → na AID czas i dystans do celu (pasek VW i lewa tarcza), strzałka manewru i dystans
   do manewru (strzałka pojawia się, gdy auto ruszy). Google Maps i Waze: sprawdź, czy też działa (nie wiadomo, czy wysyłają te dane).
3. OK → „Potwierdz”.

### Krok 9. Zoom mapy z kierownicy

1. **„Wlacz: Zoom mapy CarPlay strzalkami na kierownicy”** → restart → start próbny.
2. Sprawdź: widok mapy na AID, **krótkie** naciśnięcie strzałki góra/dół na kierownicy → przybliża/oddala. Przytrzymanie nic nie robi.
   Zwróć uwagę, czy to nie przeszkadza w menu licznika (te same strzałki).
3. OK → „Potwierdz”.

### Krok 10. Dzień/noc mapy na AID

1. **„Wlacz: Dzien/noc mapy CarPlay na AID (ponowne wyslanie po starcie)”** → restart → start próbny.
2. Sprawdź: po starcie mapa na AID ma właściwy tryb (noc przy światłach/w ciemności, dzień w dzień), także po restarcie radia.
   **Najważniejszy przypadek** (zgłoszony przez innego właściciela 791, omonob #51): auto na zewnątrz w dzień, światła wyłączone
   (nie AUTO) → start → mapa ma być jasna. Bez tej paczki mapa zostaje ciemna, dopóki nie włączysz świateł.
   Warto sprawdzić to samo raz **przed** włączeniem paczki (po fazie 1), żeby wiedzieć, czy problem w ogóle u Ciebie występuje.
3. OK → „Potwierdz”.

---

# Wycofanie i awarie

| Sytuacja | Co robisz |
|---|---|
| Brak obrazu na AID | iPhone: „Zapomnij to auto”, podłącz ponownie; potem inny wariant (krok 3) |
| Paczka działa źle, HMI wstaje | GEM → `pmcp_etap_B_java` → „Wylacz: X” → restart → „Status”: przy `This boot: ... use=trial` sprawdź i „Potwierdz” |
| Czarny ekran / logo w kółko w starcie próbnym | pokrętło ~10 s; następny start jest fabryczny. Potem „Wylacz: X” |
| Czarny ekran po potwierdzeniu (zepsuty zestaw potwierdzony) | **karta 2** (jak w kroku 1). Potem karta 1 → „Przywroc pliki fabryczne” |
| CarPlay nie łączy się po Systemie RG | „System RG: wylacz”, restart |
| Wszystko wycofać | „Przywroc pliki fabryczne” → `PMCP_RESTORE_OK` → restart (radio fabryczne) |
| Cokolwiek `PMCP_FAIL` albo niejasne | nic dalej nie klikaj, zdjęcie ekranu, „0. Diagnostyka” (tylko odczyt) |

Karta 2 cofa tylko Javę i System RG (obraz z etapu A zostaje); resztę sprząta „Przywroc pliki fabryczne”.
Po użyciu karta 2 sama się rozbraja: przed następnym razem trzeba ją znów uzbroić na komputerze.

Jedyna dozwolona aktualizacja firmware to oficjalna K4525. Nigdy nie wgrywaj firmware z innego modelu (cross-flash).

## Ściąga

```
FAZA 1:  karta 2 (test, log WYNIK=OK) → karta 1: Sprawdz (STOCK) → Instaluj map-clean → restart → AID?
FAZA 2:  ODBLOKUJ_ETAP_B (komputer) → [Wlacz X → restart → test → Potwierdz] dla: nai, np, (System RG → restart → CarPlay OK) rg, zoom, dn
AWARIA:  pokrętło 10 s → start fabryczny;  potwierdzony zły zestaw → karta 2 → Przywroc
```
