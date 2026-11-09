# Android Auto na AID (instrukcja w aucie)

[English version](../en/13-android-auto-guide.md) · Tło: [aa/README.pl.md](../../aa/README.pl.md)

Android Auto 0.1 (otwarta alfa, od v1.5.0): obraz Google Maps z telefonu z Androidem na AID i strzałki VW z Google Maps.
Instaluje się własnym przyciskiem na ekranie głównym (GEM: `pmcp_stream_map_aid`), **„3. Install Android Auto: Google
Maps on the AID + VW arrows (needs 2)”**, osobno od funkcji CarPlay: „4. Install additional features” ani go nie
instaluje, ani nie usuwa. Szczegóły (potwierdzenie AA, logi, usuwanie) są na ekranie `pmcp_advanced` → `aa_advanced`.
Karty eksperymentalne (nie wydania) dodają tam, i tylko tam, eksperymentalne oprogramowanie Android Auto; ekran główny
instaluje wersję stabilną.

## Najpierw

- Mapa CarPlay zainstalowana (ekran główny **„2. Install CarPlay: the map on the AID (also repairs or updates it)”**).
  Android Auto korzysta z drogi obrazu mapy CarPlay.
- Strzałki VW z Google Maps: na ekranie głównym **„4. Install additional features: route guidance, zoom, day/night, song
  title (needs 2)”**. Pakiet prowadzenia `rg` pokazuje strzałki i dla CarPlay, i dla Android Auto. Bez niego jest sam
  obraz. 3 i 4 można nacisnąć jedno po drugim: jeden restart, potem jedno „5. Confirm” w tym starcie potwierdza obie
  próby.

## Włączenie Android Auto

1. Ekran główny → **„3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)”** →
   `PMCP_AA_ON_OK mode=gamma`. Gdy zestaw tej karty już jest (status „on”, np. zainstalowany przez v1.5.0), odpowiada
   `PMCP_AA_INSTALL_OK (already installed: ..., nothing changed)`: nie trzeba restartu ani potwierdzenia. Znany tej karcie
   zestaw z wcześniejszej karty eksperymentalnej (status „old”) jest aktualizowany na miejscu. Pliki Android Auto, których ta karta nie obsługuje (np. z karty eksperymentalnej albo po przerwanej akcji),
   najpierw są usuwane: wraca fabryczny `gal`, tylko z kopii z fabrycznym hashem; inaczej zatrzymuje się i niczego nie
   zmienia. Potem instaluje się zestaw tej karty. Jeśli `rg` jeszcze nie jest włączony, pisze: „VW arrows from Google
   Maps need rg: main menu, 4. Install additional features.”
2. Restart radia (przytrzymaj pokrętło głośności ~10 s).
3. Telefon z Androidem na kablu, Android Auto, trasa w Google Maps. Pierwsza sesja Android Auto w tym starcie to **próba**.
4. Obraz pojawia się około 5 s po podłączeniu telefonu (najpierw musi być gotowy AID). Jeśli obraz Google Maps jest na
   AID: w tym samym starcie, najpierw z podłączonym telefonem, na ekranie głównym **„5. Confirm: everything works (in
   the first start after 3 or 4)”** → `PMCP_AA_CONFIRM_OK` i `PMCP_CONFIRM_OK`. Od tej pory Android Auto startuje
   z nim za każdym razem. Jeśli pisze „connect the phone first, then 5 again”, sesja Android Auto jeszcze nie ruszyła.
   (`aa_advanced` → „AA Confirm: AA works (only in the start of the AA trial; 5 does the same)” robi to samo tylko dla
   Android Auto.)
5. Bez Confirm następny start ma znowu fabryczne Android Auto (bez obrazu na AID, nic więcej się nie zmienia).
   **„6. Try again: the next start is a new trial”** (albo `aa_advanced` → „AA Try again: the next AA connection is a new
   trial”) pozwala na jeszcze jedną próbę; potem restart.

## Znane ograniczenia

- Strumień rusza około 5 s po podłączeniu telefonu.
- Czasem obraz startuje ciemny (albo AID pokazuje ekran ładowania), aż telefon wyśle następną klatkę kluczową. Pomaga
  ponowne podłączenie telefonu.
- Brak strzałki VW na pierwszym kroku trasy („wyjazd”).
- Dystans i czas do celu są w obrazie Google Maps, nie na pasku VW.
- Strzałka i pasek VW gasną około 10 s po tym, jak Google Maps przestaje wysyłać nawigację (np. Maps zamknięte bez
  zakończenia trasy); CarPlay trzyma cichą trasę 180 s.
- Karta 2 (ratunkowa) i pakiety Java mają jeden wspólny znacznik wyłączenia (`DISABLED`). „4. Install additional
  features” (i każde włączenie / aktualizacja Java) go usuwa, a z nim włącza z powrotem hook Android Auto wyłączony kartą
  ratunkową. Żeby Android Auto zostało wyłączone po karcie ratunkowej: „AA remove (factory Android Auto back)”.
- „AA save log” w trakcie aktywnej sesji Android Auto może odpowiedzieć `AA_LOG_COPY_SHORT` (log urósł w czasie
  kopiowania). Odłącz telefon i naciśnij jeszcze raz w tym samym starcie.
- `guidance-evidence.txt` (liczniki wiadomości rg, obok `adapter-status.txt`) liczy Android Auto i CarPlay razem.

## Gdy coś nie działa: co sfotografować

**W tym samym starcie, bez odłączania telefonu:**

1. `aa_advanced` → **„AA status and stream analysis (read-only)”**: zdjęcie każdej strony. Najważniejsze linie: `Android Auto:` (stan),
   `dawkowanie:`, `przerwy:` (przerwy między klatkami), `klatki co 10s` / `KB co 10s` (ostatnie 5 minut), `duze klatki`,
   `sync startu:`, `pierwsze IDR` i linie „Manoeuvres for rg”.
2. **„AA save log: copy this start's AA log to the unit (for the log card)”** → `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`.
   Radio trzyma do 5 logów. Jeśli pokaże `AA_LOG_COPY_SHORT`: odłącz telefon i naciśnij jeszcze raz (ten sam start).
3. **„7. Status (read-only)”** na ekranie głównym: też zdjęcie (zestaw Java, prowadzenie, Android Auto).
4. Potem odłącz i podłącz telefon.

Przy problemie z CarPlay: `features_advanced` → **„CP save log: copy this start's CarPlay log to the unit (for the log
card)”** → `PMCP_CP_LOG_SAVED file=logs/cp-log-N.txt`.

W domu: karta 3 (logi) w trybie aktualizacji kopiuje logi Android Auto i CarPlay do `PMCP_LOGS/` na tej karcie (radio
tylko czyta). Potem **„AA delete saved logs, AA and CarPlay (after the log card copied them)”** (`aa_advanced`; to samo
co „Delete saved logs, CarPlay and AA (after the log card copied them)” w `features_advanced`).

### Karta 3 (logi)

`install.sh` jej nie buduje. Na komputerze, w repozytorium (potrzebny ten sam zip M.I.B. 3.6.0 w `mib/downloads/` co dla
karty ratunkowej):

```
python3 -I installer/build_logcard.py build/karta3-logi
```

Zawartość `build/karta3-logi` skopiuj na pustą kartę FAT32 (osobną, nie kartę 1 ani 2). W aucie: slot SD1, odczekaj do
60 s, na pytanie odpowiedz Continue, nie wyjmuj karty w trakcie aktualizacji. Żeby pobrać logi, karta uruchamia pełny
`stuff.sh` M.I.B. 3.6.0 w trybie aktualizacji (SWDL), jak przy instalacji M.I.B.: radio po drodze instaluje ponownie
M.I.B. 3.6.0. Na końcu `PMCP_LOGS/PMCP_LOGS_RESULT.txt` kończy się `RESULT=OK copied=N aa_logs=A cp_logs=C` (albo
`RESULT=NO_LOGS`: w GEM nic wcześniej nie zapisano). M.I.B. rozbraja kartę po każdym użyciu
(`Swdlautorun.txt` -> `_Swdlautorun.txt`); żeby użyć jej ponownie, zmień nazwę z powrotem na komputerze. Szczegóły:
`PMCP_LOGS_README.txt` na karcie.

## Wyłączenie Android Auto

- `aa_advanced` → **„AA remove (factory Android Auto back)”**: fabryczny `gal` (odbiornik Android Auto radia) wraca z kopii sprawdzonej
  hashem, pliki i znaczniki Android Auto są usuwane. CarPlay i pakiety Java zostają. Restart przed ponownym podłączeniem
  telefonu z Androidem.
- **„8. Remove everything (back to factory files)”** na ekranie głównym najpierw zdejmuje Android Auto, potem resztę.
- Karta 2 (ratunkowa) wyłącza hook Android Auto razem z naszymi pakietami Java; pliki usuwa potem „AA remove” albo
  „8. Remove everything”.

## Co mówi status

`Android Auto: off | on mode=gamma | old mode=… | unknown`

- **on**: zestaw Android Auto tej karty (także ten zainstalowany przez v1.5.0, to ten sam zestaw). „AA status” mówi
  też, czy jest potwierdzony, czy w próbie.
- **old**: pliki Android Auto z wcześniejszej karty eksperymentalnej, znane tej karcie (`AA_OLD`); „3. Install Android
  Auto” na ekranie głównym je aktualizuje.
- **unknown** daje stan radia PARTIAL (pliki z różnych zestawów, przerwana akcja, nieznany zestaw karty eksperymentalnej):
  „3. Install Android Auto” na ekranie głównym najpierw je usuwa (wraca fabryczny `gal`) i instaluje zestaw tej karty.
