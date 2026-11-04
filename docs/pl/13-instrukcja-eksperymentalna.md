# Karta eksperymentalna: Android Auto na AID (instrukcja w aucie)

[English version](../en/13-experimental-guide.md) · Tło: [aa/README.pl.md](../../aa/README.pl.md)

Ta karta to karta wydania v1.4.2 plus jeden dodatkowy ekran, **pmcp_android_auto** (GEM: pmcp → pmcp_advanced →
pmcp_android_auto). Wszystko na ekranie głównym działa dokładnie jak na karcie wydania. Karta 2 (ratunkowa) jest ta sama.

## Najpierw

- Mapa CarPlay zainstalowana (ekran główny „2. Install the CarPlay map on the AID” albo „3. Install all features or
  update”). Android Auto korzysta z bridge'a mapy CarPlay.
- Strzałki VW z Google Maps: system prowadzenia włączony i pakiet **rg-aa** zamiast rg
  (pmcp_packages: „On rg-aa: rg + VW arrows from Android Auto (Google Maps); replaces rg (experimental)”).
  Z CarPlay rg-aa działa jak rg. Jak każda zmiana pakietów Java, to start próbny: „4. Confirm” w tym starcie.

## Włączenie Android Auto

1. pmcp_android_auto → **„AA 1. Android Auto on: Google Maps on the AID + VW arrows (also updates an earlier card's AA)”**
   (`aa-on`) → `PMCP_AA_ON_OK mode=gamma`. Aktualizuje też pliki AA z wcześniejszej karty eksperymentalnej (status „old”),
   bez wcześniejszego usuwania.
2. Restart radia (przytrzymaj pokrętło głośności ~10 s).
3. Telefon z Androidem na kablu, Android Auto, trasa w Google Maps. Pierwsza sesja Android Auto w tym starcie to **próba**.
4. Jeśli mapa AA jest na AID (może to potrwać ~10 s: feeder najpierw czeka na AID): w tym samym starcie
   **„AA 2. Confirm: AA works (only in the start of the AA trial)”** (`aa-confirm`) → `PMCP_AA_CONFIRM_OK`.
   Bez Confirm następny start ma znowu fabryczne Android Auto; **„AA 3. Try again: the next AA connection is a new trial”**
   (`aa-retry`) pozwala na jeszcze jedną próbę.

## Gdy obraz zniknie

Telefon wysyła jedną klatkę kluczową na sesję, więc zgubiony obraz (ciemny z artefaktami albo ekran ładowania AID) zostaje
do ponownego podłączenia telefonu. Żeby pomóc znaleźć przyczynę, **w tym samym starcie, bez odłączania**:

1. **„AA status and stream analysis (read-only)”** (`aa-status`): zdjęcie każdej strony. Najważniejsze linie:
   `dawkowanie:`, `przerwy:` (przerwy między klatkami), `klatki co 10s` / `KB co 10s` (ostatnie 5 minut),
   `duze klatki`, `sync startu:`, `pierwsze IDR`.
2. **„AA save log: copy this start's AA log to the unit (for the log card)”** (`aa-log-save`) →
   `PMCP_AA_LOG_SAVED file=logs/aa-log-N.txt`. Radio trzyma do 5 logów.
3. Potem odłącz i podłącz telefon.

W domu: karta 3 (logi, `installer/build_logcard.py`) w trybie aktualizacji kopiuje logi do `PMCP_LOGS/` na tej karcie
(radio tylko czyta). Potem **„AA delete saved logs (after the log card copied them)”** (`aa-log-clear`).

## Wyłączenie Android Auto

- **„AA remove (factory Android Auto back)”** (`aa-remove`): fabryczny `gal` z kopii sprawdzonej hashem, pliki
  i znaczniki AA usunięte. Restart przed ponownym podłączeniem telefonu z Androidem.
- „Remove everything” najpierw zdejmuje Android Auto, potem resztę.
- Karta wydania (v1.4.0 i nowsze) też to umie: advanced → „Remove experimental Android Auto” albo przycisk 3.

## Co mówi status

`Android Auto (experimental): off | on mode=gamma | old mode=… | unknown`

- **old**: pliki AA z wcześniejszej karty eksperymentalnej; „AA 1” je aktualizuje.
- **unknown** daje stan radia PARTIAL (pliki z różnych zestawów, przerwana akcja): „AA remove”, potem „AA 1”.
