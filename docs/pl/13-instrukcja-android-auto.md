# Android Auto na AID (instrukcja w aucie)

[English version](../en/13-android-auto-guide.md) · Tło: [aa/README.pl.md](../../aa/README.pl.md)

Android Auto 0.1 (otwarta alfa, od v1.5.0): obraz Google Maps z telefonu z Androidem na AID i strzałki VW z Google Maps.
Ma własny ekran w GEM, **pmcp_android_auto** (GEM: pmcp → pmcp_android_auto, na ekranie głównym), i instaluje się osobno
od CarPlay: „3. Install all features or update” ani go nie instaluje, ani nie usuwa.

## Najpierw

- Mapa CarPlay zainstalowana (ekran główny „2. Install the CarPlay map on the AID” albo „3. Install all features or
  update”). Android Auto korzysta z drogi obrazu mapy CarPlay.
- Strzałki VW z Google Maps: na ekranie głównym **„3. Install all features or update: map, route guidance, zoom,
  day/night, song title”**, restart, potem w tym starcie **„4. Confirm: everything works (only in the first start after
  3)”**. Pakiet prowadzenia `rg` pokazuje strzałki i dla CarPlay, i dla Android Auto. Bez niego jest sam obraz.

## Włączenie Android Auto

1. pmcp_android_auto → **„AA 1. Android Auto on: Google Maps on the AID + VW arrows (also updates an earlier card's AA)”**
   → `PMCP_AA_ON_OK mode=gamma`. Aktualizuje też pliki Android Auto z wcześniejszej karty eksperymentalnej (status
   „old”), bez wcześniejszego usuwania. Jeśli `rg` jeszcze nie jest włączony, pisze: „VW arrows from Google Maps need rg:
   main menu, 3. Install all features or update.”
2. Restart radia (przytrzymaj pokrętło głośności ~10 s).
3. Telefon z Androidem na kablu, Android Auto, trasa w Google Maps. Pierwsza sesja Android Auto w tym starcie to **próba**.
4. Obraz pojawia się około 5 s po podłączeniu telefonu (najpierw musi być gotowy AID). Jeśli obraz Google Maps jest na
   AID: w tym samym starcie **„AA 2. Confirm: AA works (only in the start of the AA trial)”** → `PMCP_AA_CONFIRM_OK`.
   Od tej pory Android Auto startuje z nim za każdym razem.
5. Bez Confirm następny start ma znowu fabryczne Android Auto (bez obrazu na AID, nic więcej się nie zmienia).
   **„AA 3. Try again: the next AA connection is a new trial”** pozwala na jeszcze jedną próbę; potem restart.

## Znane ograniczenia

- Strumień rusza około 5 s po podłączeniu telefonu.
- Czasem obraz startuje ciemny (albo AID pokazuje ekran ładowania), aż telefon wyśle następną klatkę kluczową. Pomaga
  ponowne podłączenie telefonu.
- Brak strzałki VW na pierwszym kroku trasy („wyjazd”).
- Dystans i czas do celu są w obrazie Google Maps, nie na pasku VW.

## Gdy coś nie działa: co sfotografować

**W tym samym starcie, bez odłączania telefonu:**

1. **„AA status and stream analysis (read-only)”**: zdjęcie każdej strony. Najważniejsze linie: `Android Auto:` (stan),
   `dawkowanie:`, `przerwy:` (przerwy między klatkami), `klatki co 10s` / `KB co 10s` (ostatnie 5 minut), `duze klatki`,
   `sync startu:`, `pierwsze IDR` i linie „Manoeuvres for rg”.
2. **„AA save log: copy this start's AA log to the unit (for the log card)”** → `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`.
   Radio trzyma do 5 logów.
3. **„Status (read-only)”** na ekranie głównym: też zdjęcie (zestaw Java, prowadzenie, Android Auto).
4. Potem odłącz i podłącz telefon.

W domu: karta 3 (logi, `installer/build_logcard.py`) w trybie aktualizacji kopiuje logi do `PMCP_LOGS/` na tej karcie
(radio tylko czyta). Potem **„AA delete saved logs (after the log card copied them)”**.

## Wyłączenie Android Auto

- **„AA remove (factory Android Auto back)”**: fabryczny `gal` (odbiornik Android Auto radia) wraca z kopii sprawdzonej
  hashem, pliki i znaczniki Android Auto są usuwane. CarPlay i pakiety Java zostają. Restart przed ponownym podłączeniem
  telefonu z Androidem.
- **„Remove everything (back to factory files)”** na ekranie głównym najpierw zdejmuje Android Auto, potem resztę.
- Karta 2 (ratunkowa) wyłącza hook Android Auto razem z naszymi pakietami Java; pliki usuwa potem „AA remove” albo
  „Remove everything”.

## Co mówi status

`Android Auto: off | on mode=gamma | old mode=… | unknown`

- **on**: zestaw Android Auto tej karty. „AA status” mówi też, czy jest potwierdzony, czy w próbie.
- **old**: pliki Android Auto z wcześniejszej karty; „AA 1” je aktualizuje.
- **unknown** daje stan radia PARTIAL (pliki z różnych zestawów, przerwana akcja): „AA remove”, potem „AA 1”.
