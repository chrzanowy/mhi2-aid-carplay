# Tutorial w aucie: instalacja krok po kroku (Passat B8, MHI2 MU1161, AID 791)

Wersja instalatora: **`pmcp-0.7.0-mu1161-791-…`** (końcówka to identyfikator buildu; jest w pierwszej linii
`BUILD-MANIFEST.txt`, w `PMCP_INSTRUKCJA.txt` na karcie 1 i na górze ekranu zielonego menu).
Wszystkie napisy zielonego menu są po angielsku (od v1.4); niżej cytowane dokładnie tak, jak na ekranie.

Wszystko robisz **podczas jednej wizyty w aucie**:

```
karta 1:  1. Check  →  2. Install CarPlay  →  restart  →  mapa OK?  →  4. Install additional features  →  restart (próbny)
          →  test  →  5. Confirm (ten sam start)  →  restart  →  działa od teraz
          (Android Auto, opcjonalnie: 3. Install Android Auto, zob. 13-instrukcja-android-auto.md)
```

## Karty

| Karta | Opis | Co robi | Uwagi |
|---|---|---|---|
| **1 – instalacyjna** | `INSTALL` | M.I.B. 3.6.0 + instalator, wszystko z zielonego menu, jedna akcja naraz | nic nie startuje samo |
| **2 – ratunkowa** | `RESCUE - DO NOT INSERT` | po włożeniu radio **samo** wchodzi w tryb aktualizacji i cofa zmiany Javy | tylko na awarię; nie trzymaj jej w slocie |

Obie karty robi pomocnik kopiowania z paczki wydania (`README-FIRST.txt`). Zawsze **tylko jedna karta w radiu**,
zawsze slot **SD1**.

## Zasady dla każdego kroku

- Zasilanie: prostownik/booster albo pracujący silnik (na zewnątrz). Zapłon ON.
- **Nie przerywaj** akcji w zielonym menu (bez „Wstecz”, nie wyjmuj karty), aż wynik pojawi się na ekranie.
- Każda akcja kończy się linią `PMCP_..._OK` (dobrze) albo `PMCP_FAIL ...` (nic nie zmieniono albo wycofano). Przy `FAIL`
  nic więcej nie naciskaj, zrób zdjęcie ekranu.
- Karta SD w zielonym menu jest tylko do odczytu, więc instalator zapisuje wynik każdego przycisku w radiu
  (`/mnt/persist/pmcp/gem.log`, ok. 64 KB; kopiuje go karta logów; przyciski tylko do odczytu jedynie dopisują tam wynik). **Fotografuj wynik każdej akcji.**
- Wejście do zielonego menu: przytrzymaj **MENU ~10 s** → `=>M.I.B.<=` → **`pmcp_stream_map_aid`**. Nagłówek musi pokazać
  wersję twojego buildu (`pmcp-0.7.0-mu1161-791-…`); inna wersja = stop.
- „Restart” = **przytrzymaj pokrętło głośności ~10 s** (radio się wyłącza i startuje). Wyłączenie i włączenie auta od razu
  to nie restart (radio jeszcze nie zasnęło).

---

## Krok 1. Sprawdzenie karty i radia (tylko odczyt)

1. Włóż **kartę 1**. Zielone menu → `=>M.I.B.<=` → `pmcp_stream_map_aid`.
2. **„1. Check card and unit (read-only)”**. Trwa kilka sekund (hashe liczy fabryczny `sha1sum` radia).
3. Oczekiwany wynik: **`PMCP_VERIFY_OK state=STOCK`**. W radiu nic się nie zmienia. Przy innym firmware zatrzyma się tutaj.

Gdy coś jest niejasne: **„0. Diagnostics (read-only, photograph the screen)”** (podmenu `pmcp_advanced` →
`features_advanced`) pokazuje stan radia i niczego nie zmienia. „RG last maneuver” (też tylko odczyt) pokazuje, co iPhone ostatnio wysłał i jaką strzałkę VW
daje ścisłe mapowanie; gdzie jest main 0, paczka prowadzenia może jeszcze pokazać strzałkę zastępczą (np. na starcie trasy
albo na rondzie).

## Krok 2. Instalacja mapy (etap A)

1. **„2. Install CarPlay: the map on the AID (also repairs or updates it)”** → oczekiwane
   `PMCP_INSTALL_OK stage=A variant=map-square-fps40 ...`.
   (`map-square-fps40` to układ domyślny: układ forka mathsls, sama mapa, bliżej kwadratu, najlepszy z pięciu po dłuższej
   jeździe; 40 klatek na sekundę jak u mathsls, w jeździe testowej bez większego opóźnienia niż 30. `map-square` to to samo
   przy 30. Po kroku 3 manewr, ETA i dystans pokazuje natywnie VW.) Gdy mapa jest już zainstalowana, ten sam przycisk
   przełącza z powrotem na `map-square-fps40` (`PMCP_SWITCH_OK`) albo pokazuje `PMCP_MAP_INSTALL_OK (already installed ...)`.
   Gdy pliki mapy są pomieszane, usuwa wszystko (zweryfikowane pliki fabryczne) i instaluje mapę od nowa; potem naciśnij
   ponownie 3 i/lub 4. Pliki innego moda: nic nie jest zmieniane.
2. Restart (pokrętło ~10 s).
3. Podłącz iPhone'a (CarPlay), włącz Apple Maps albo Google Maps i **uruchom prowadzenie do celu**. Na AID przełącz widok na
   nawigację/mapę. Sterowanie AID w tym aucie (prawa strona kierownicy): **przyciski widoku** (układ licznika), między nimi
   **OK**, obok **góra/dół** (zakładki/menu licznika). Lewa strona kierownicy to asystenci.
   Ustaw zakładkę **Nawigacja** (góra/dół), potem przejdź przyciskami widoku przez układy: mapa CarPlay jest w małej tarczy
   w środku i w dużym układzie na całą szerokość.
4. Sprawdź: mapa CarPlay na AID, nic nie wchodzi pod tarcze i paski VW.

**Jeśli na AID nie ma obrazu:**
1. W iPhonie: Ustawienia → Ogólne → CarPlay → to auto → **„Zapomnij to auto”**, podłącz ponownie.
2. Dalej nic: zielone menu → **`pmcp_advanced` → `carplay_advanced`** → „Switch map layout to: map-clean” (szersze
   i niższe okno mapy), restart.
3. Inne układy w tym samym podmenu (każda zmiana → restart; układy: [mapa ramki AID](../aid-frame-map.pl.html)):
   `card-clean` (z kartą manewru iPhone'a), `url-map-hybrid` (mapa z parametrem ograniczenia prędkości, który w aucie nic
   nie pokazał), `map-clean-l40` (mapa 40 kolumn w lewo), `map-clean` (200 / 108 / 400 / 296).
   Powrót do domyślnego: „Switch map layout to: map-square-fps40”.

Bez mapy na AID nie przechodź do kroku 3. Etap A nie zmienia startu ekranu radia: najgorszy skutek to brak obrazu CarPlay,
a zielone menu z „8. Remove everything (back to factory files)” działa zawsze.

## Krok 3. Instalacja dodatkowych funkcji (albo aktualizacja)

**„4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)”** → oczekiwane
**`PMCP_FEATURES_ON_OK`**. (Przycisk 3 to Android Auto, opcjonalnie: [13-instrukcja-android-auto.md](13-instrukcja-android-auto.md).)

Uruchamia po kolei: przywrócenie fabrycznych plików prowadzenia i Javy w wersji, której ta karta nie obsługuje
(zweryfikowane kopie; np. zestaw Java z nieznaną paczką albo po karcie ratunkowej; pomijane, gdy niepotrzebne),
aktualizację wcześniejszego systemu prowadzenia i zestawu Java (przy nowej instalacji pomijana), system prowadzenia (łatany
sterownik iAP2, `iap2.cfg`, czytnik) i pięć paczek Java (NavActiveIgnore, tytuł utworu, prowadzenie `rg` ze strzałkami,
pasami, paskiem odległości, nazwą ulicy i ETA, zoom, dzień/noc). Nie rusza mapy (to jest 2) i nie instaluje opcjonalnej
paczki ograniczeń prędkości `sl`. Wszystkie trafiają do **jednego zestawu**, więc jest jeden start próbny i jedno
potwierdzenie. Wymaga 2; gdy są pliki Android Auto w wersji, której ta karta nie obsługuje, zatrzymuje się z komunikatem
(najpierw naciśnij 3). Zatrzymuje się na pierwszym błędzie (`PMCP_FAIL=FEATURES_STOPPED_AT_...`; wcześniejsze kroki
zostają, ekran pokazuje które). Ponowne naciśnięcie, gdy wszystko jest włączone, niczego nie zmienia.

Aktualizacja wcześniejszej instalacji: 2, potem (jeśli używasz) 3, potem 4, zob. [Aktualizacja z wcześniejszej wersji](#aktualizacja-z-wcześniejszej-wersji).

## Krok 4. Start próbny, test, potwierdzenie

Java zmienia start ekranu radia, więc nowy zestaw przechodzi **start próbny**:

```
4. Install additional features  →  restart  →  START PRÓBNY (zestaw ładuje się raz)
                                              │
                         wszystko działa? ────┤
                            TAK                │ NIE / czarny ekran
            w TYM SAMYM starcie, zielone menu: │ pokrętło ~10 s → następny start fabryczny
            „5. Confirm: everything works”     │ (nic nie potwierdzone, nic do naprawy)
            → zestaw ładuje się przy każdym starcie
```

1. Restart (pokrętło ~10 s). Ten start jest próbny.
2. Sprawdź:
   - radio startuje normalnie (ekran, radio, menu) i **CarPlay się łączy** (po kablu; raz odłącz i podłącz);
   - pasy: na skrzyżowaniu z pasami wyświetlanie pasów VW na AID (pasy ruchu muszą być włączone w ustawieniach VW i wysyłane
     przez aplikację w telefonie); pas do zawracania ma własną strzałkę;
   - szczegóły prowadzenia: strzałka od razu na starcie trasy, pasek odległości odliczający przed manewrem, nazwa bieżącej
     ulicy i symbol ronda z kierunkiem zjazdu przy skrętach na rondzie;
   - prowadzenie w Apple Maps: mapa CarPlay **zostaje** na AID (NavActiveIgnore); czas i dystans do celu na pasku VW i w lewej
     tarczy; strzałka manewru i dystans do manewru (strzałka pojawia się po ruszeniu). Google Maps i Waze: sprawdź, czy też
     działa (nie wiadomo, czy wysyłają te dane);
   - muzyka z CarPlay (Spotify/Apple Music): tytuł i wykonawca w widoku mediów AID;
   - widok mapy na AID: **krótkie** naciśnięcie strzałki góra/dół na kierownicy przybliża/oddala (przytrzymanie nic nie robi);
   - dzień/noc: po starcie w dzień ze zgaszonymi światłami (nie AUTO) mapa na AID jest jasna; przy włączonych światłach ciemna.
3. Wszystko działa → **„5. Confirm: everything works (in the first start after 3 or 4)”** → `PMCP_CONFIRM_OK`.
   Tylko w starcie próbnym (instalator to sprawdza): nie wyłączaj auta między restartem a potwierdzeniem.
   Ten sam przycisk potwierdza też Android Auto, gdy jest w próbie (najpierw podłącz telefon); gdy w próbie jest tylko
   jedno z dwóch, potwierdza to jedno i pisze, dlaczego nie drugie.
   Bez karty to samo robi radio: App-Connect → Settings → **AID navigation configuration** → wiersz **Changes** → „Save: everything
   works” (paczka `ui`, instaluje ją przycisk 4).
4. Coś nie działa albo ekran zostaje czarny → restart (pokrętło ~10 s): następny start jest fabryczny. Żeby spróbować
   ponownie: **„6. Try again: the next start is a new trial”**, restart. Żeby znaleźć funkcję, która sprawia kłopot, włączaj je
   po jednej ([zaawansowane](#zaawansowane-funkcje-po-jednej)).

## Krok 5. Restart

Jeszcze jeden restart. Od teraz zestaw ładuje się przy każdym starcie. **„7. Status (read-only)”** pokazuje `state=JAVA`,
zestaw i `This boot: set=... use=yes`.

## Aktualizacja z wcześniejszej wersji

Te same kroki dla v1.6.0, v1.5.x, v1.4.x i v1.0-v1.3. Z v1.5.x i v1.6.0 przycisk 3 daje Android Auto 1.1, a 4 dodaje
albo aktualizuje stronę ustawień (`ui`), prowadzenie i tytuły utworów, więc restart i 5
(albo „Save: everything works” na stronie) są potrzebne. Tylko gdy wszystkie trzy (2, 3 i 4) odpowiadają „already
installed” / „everything was already on, nothing changed” (karta z tymi samymi funkcjami), nie trzeba ani restartu,
ani 5.

1. Zrób **kartę 1 z tego wydania** i włóż ją. **„1. Check card and unit (read-only)”** → `PMCP_VERIFY_OK state=JAVA`.
   „7. Status (read-only)” może pokazać „Route guidance system: old” i „packages of an earlier card: rglu”: tak ma być,
   przycisk 4 je zastępuje.
2. **„2. Install CarPlay: the map on the AID (also repairs or updates it)”** → zwykle
   `PMCP_MAP_INSTALL_OK (already installed ...)`.
3. Tylko jeśli używasz Android Auto: **„3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)”** →
   `PMCP_AA_ON_OK mode=gamma` albo `PMCP_AA_INSTALL_OK (already installed: ..., nothing changed)`, gdy zestaw tej karty
   (np. z v1.5.0) już jest. Znany tej karcie zestaw z wcześniejszej karty eksperymentalnej jest aktualizowany na miejscu;
   zestaw, którego ta karta nie obsługuje, najpierw jest usuwany (wraca fabryczny `gal`), potem instaluje się zestaw
   z tej karty.
4. **„4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)”** → `PMCP_FEATURES_ON_OK`
   (albo `PMCP_FEATURES_ON_OK (everything was already on, nothing changed)`). Zastępuje wcześniejszy sterownik iAP2 i czytnik plikami z tej karty (kopie fabryczne zostają) i tworzy jeden nowy
   zestaw Java, w którym `rglu` (albo `rg`, albo eksperymentalne `rg-aa`) staje się nowym `rg`, i dodaje `ui` (stronę ustawień).
5. Tylko jeśli 3 albo 4 coś zainstalowały: restart, ten start jest **próbny**. Sprawdź, czy CarPlay się łączy, potem strzałki (także od razu na starcie trasy),
   pasy, pasek odległości i nazwę ulicy. Z Android Auto: w tym starcie podłącz też telefon.
6. **„5. Confirm: everything works (in the first start after 3 or 4)”** w tym samym starcie albo w radiu App-Connect >
   Settings > AID navigation configuration > Changes > „Save: everything works”; potem restart.
7. Zrób **nową kartę 2** (pomocnik kopiowania, opcja 2): karty ratunkowe sprzed v1.4 nie przywracają sterownika iAP2 z v1.4.

Android Auto w aucie i jego usuwanie: [13-instrukcja-android-auto.md](13-instrukcja-android-auto.md).

---

# Awaria: karta 2 (ratunkowa)

Tylko gdy po potwierdzeniu ekran zostaje czarny albo radio się ciągle restartuje, a pokrętło nie pomaga:

1. Włóż **kartę 2** do SD1 i czekaj (do ~60 s). Radio samo wchodzi w tryb aktualizacji, może się kilka razy zrestartować.
   Na pytanie w menu aktualizacji → **Continue** (Dalej). Nie wyjmuj karty podczas aktualizacji.
2. Gdy radio wróci do normalnego ekranu → wyjmij kartę 2. Część Java i system prowadzenia są cofnięte (fabryczny `lsd.sh`,
   nasze JAR-y usunięte, `/mnt/persist/pmcp/DISABLED`, fabryczny sterownik iAP2 i `iap2.cfg`); mapa zostaje.
3. Karta 1 → „8. Remove everything (back to factory files)”, jeśli ma zniknąć także mapa.
4. M.I.B. po użyciu rozbraja kartę 2 (`Swdlautorun.txt` → `_Swdlautorun.txt`), więc nie zapętli się. Ponowne uzbrojenie na
   komputerze: pomocnik kopiowania, opcja **3** (pokazuje też wynik: `PMCP_RESCUE_LOG.txt`, `RESULT=OK`, na końcu
   `=== PMCP RESCUE end ===`; karta sprzed v1.4 zapisuje `PMCP_RATUNEK_LOG.txt` z `WYNIK=OK`).

Opcjonalnie: kartę 2 można raz przetestować na sprawnym radiu przed krokiem 1. Na radiu bez naszych plików nie zmienia nic
naszego (po drodze ponownie instaluje się M.I.B. 3.6.0). Potem uzbrój ją opcją 3.

# Wycofanie i awarie

| Sytuacja | Co robić |
|---|---|
| Brak obrazu na AID | iPhone: „Zapomnij to auto”, podłącz ponownie; potem inny układ (krok 2) |
| Czarny ekran / logo w kółko w starcie próbnym | pokrętło ~10 s; następny start jest fabryczny |
| Któraś funkcja źle działa | restart bez potwierdzenia (fabryczny), potem funkcje po jednej ([zaawansowane](#zaawansowane-funkcje-po-jednej)) |
| CarPlay nie łączy się po kroku 3 | `pmcp_advanced` → `features_advanced` → „Route guidance system off (factory iAP2 driver and iap2.cfg)”, restart |
| Czarny ekran po potwierdzeniu | **karta 2** (awaria wyżej), potem karta 1 → „8. Remove everything (back to factory files)” |
| Wycofanie wszystkiego | „8. Remove everything (back to factory files)” → `PMCP_RESTORE_OK` → restart (radio fabryczne) |
| Każdy `PMCP_FAIL` albo coś niejasnego | nic więcej nie naciskaj, zdjęcie ekranu, „0. Diagnostics” (tylko odczyt) |

Jedyna dozwolona aktualizacja firmware to oficjalna K4525. Nigdy cross-flash z innego modelu.

---

# Zaawansowane: funkcje po jednej

Zamiast kroku 3 funkcje można włączać po jednej w **`pmcp_advanced` → `features_advanced`**. Każde „On ...” tworzy
nowy zestaw → restart → start próbny → test → „5. Confirm”. „Off ...” wraca do zestawu bez tej paczki: jeśli ten zestaw był
wcześniej potwierdzony, ładuje się od razu; jeśli nie, też jest próbny. Po restarcie „Status” pokazuje
`This boot: set=... use=trial` (próbny, potrzebne Confirm) albo `use=yes` (potwierdzony).

1. **„On nai: AID map stays while the iPhone navigates (NavActiveIgnore)”**. Sprawdź: prowadzenie w Apple Maps, mapa CarPlay
   zostaje na AID.
2. **„On np: CarPlay song title and artist on the AID”**.
3. Prowadzenie, dwie części:
   - **„Route guidance system on (iAP2 driver, iap2.cfg, reader)”** (nie Java, bez Confirm) → restart → sprawdź **tylko,
     czy CarPlay się łączy**. Jeśli nie: **„Route guidance system off (factory iAP2 driver and iap2.cfg)”**, restart i pomiń
     następny punkt.
   - **„On rg: route guidance: arrows, lanes, distance bar, street, ETA (needs Route guidance system)”**.
   - Z wcześniejszej karty: **„Route guidance system update (driver and reader of this card, RG stays on)”** i **„Java
     update: packages of an earlier card -> this card's (rglu -> rg)”** (jeden start próbny, potem „5. Confirm”); przycisk 4
     uruchamia oba sam.
4. **„On zoom: CarPlay map zoom with the steering wheel arrows”**. Obserwuj, czy nie przeszkadza w menu licznika (te same strzałki).
5. **„On dn: CarPlay map day/night on the AID (sent again after start)”**. Kluczowy przypadek (zgłoszony przez innego
   właściciela 791, omonob #51): auto na zewnątrz w dzień, światła zgaszone (nie AUTO) → start → mapa musi być jasna. Bez tej
   paczki mapa zostaje ciemna, aż włączysz światła.
6. Opcjonalnie, tylko tutaj (przycisk 4 jej nie instaluje): **„On sl: native VW map speed limit in the AID road text
   (optional, output off until enabled)”**, zob. [16-native-speed-limits.md](../en/16-native-speed-limits.md).

W `features_advanced` są też przyciski logów do wsparcia: **„CP save log: copy this start's CarPlay log to the unit (for
the log card)”** i, gdy karta logów (karta 3) już je skopiowała, **„Delete saved logs, CarPlay and AA (after the log card
copied them)”**.

Jeśli mapa na AID wraca na kilka sekund do mapy VW około 46 s po starcie, naciśnij „CP save log” chwilę po jej powrocie:
log zawiera wtedy kopię supervisora z mostu, który się zakończył (`last-bridge.log`). Linia
`MOST write failed: Not enough memory` oznacza, że w czasie startu fabryczny enkoder wideo zajął kanał wideo AID
(przyczyna, którą tomasz-twardzicki znalazł na MU1367).

## Ściąga

```
INSTALACJA:  karta 1 → 1. Check (STOCK) → 2. Install CarPlay → restart → mapa na AID?
             → 4. Install additional features → restart (próbny) → test → 5. Confirm → restart → gotowe
AKTUALIZACJA: nowa karta 1 → 1. Check (JAVA) → 2 → (3, jeśli używasz Android Auto) → 4 → restart (próbny) → test
             → 5. Confirm → restart → nowa karta 2
AWARIA:      start próbny zepsuty → pokrętło 10 s → start fabryczny;   po Confirm zepsute → karta 2 → 8. Remove everything
RATUNEK:     po użyciu karty 2: pomocnik kopiowania opcja 3 na komputerze ponownie ją uzbraja
```
