# aa-most-feeder

[English version: README.md](README.md)

Obraz Android Auto dla licznika puszczony naszą drogą CarPlay: hook MacsInSpace w `gal` -> ten program -> ring
`/ramdisk/carplay-alt-ring.bin` -> `altscreen-most-bridge` (omonob/mathsls, już w radiu) -> MOST -> AID 791.
Tło: `docs/11-ring-altscreen.md`, `docs/06-audyt.md` A63-A68.

## Jak działa

- Hook uruchamia go zamiast swojego playera (`GAL_PLAYER_PATH`), z adresem strumienia w `argv[1]`
  (`tcp://127.0.0.1:12346`). Strumień to surowe Annex B bez ramek; granice klatek wyznacza parser NAL (AUD/SPS/PPS/SEI
  albo slice z `first_mb_in_slice == 0`) oraz przerwa `PMCP_AA_IDLE_MS` (domyślnie 8 ms) po ostatnich bajtach.
- Do ringu: avcC (typ 1) przy każdej zmianie SPS/PPS, klatki (typ 2) jako AVCC bez AUD/SPS/PPS, bo bridge dokleja je sam.
  Znacznik czasu NTP 32.32 z zegara monotonicznego.
- ACK (`/tmp/gal_ack.sock`, 1 bajt na klatkę): tryb `most` ogranicza tempo budżetem bajtów (`PMCP_AA_RATE_KBPS`,
  domyślnie 700, zapas `PMCP_AA_BURST_KB` 150), więc telefon zwalnia zanim kolejka bridge'a się przepełni.
- Dawkowanie (v9, `PMCP_AA_PACE_KBPS`, domyślnie 0 = wyłączone; ustawienia AA 3 / gamma: 2000 i `PMCP_AA_PACE_BURST_KB` 64):
  klatki trafiają do ringu nie szybciej niż ten budżet; klatki po dużej czekają w kolejności (ich ACK też). Status pokazuje
  klatki i KB co 10 s z ostatnich 5 minut, najdłuższą przerwę między klatkami i ostatnie duże klatki.
- Przejęcie MOST (tylko `PMCP_AA_MODE=most`, przy pierwszym IDR): odmowa, gdy działa supervisor CarPlay albo nasz bridge;
  `dmdt dc 72`, `dmdt sc 4 72`, 500 ms, start bridge przez strażnika. Strażnik trzyma bridge i czeka na rurkę od feedera:
  gdy feeder skończy się w dowolny sposób (także SIGKILL od hooka po 300 ms), strażnik zatrzymuje bridge (SIGTERM,
  `flush(0)` na `/dev/mlb/debug/isoTX2`, SIGKILL), czeka 250 ms i oddaje mapę VW (`dmdt dc 70 33`, `dmdt sc 4 70`).
- Tryb `analyze` (domyślny) niczego nie przejmuje: czyta, potwierdza i co sekundę zapisuje podsumowanie do
  `PMCP_AA_STATUS` (`/ramdisk/pmcp-aa-feeder.txt`): SPS (profil, poziom, rozdzielczość), PPS (CABAC/CAVLC), odstępy IDR,
  rozmiary klatek, bitrate, ACK. Plik jest nadpisywany, nic nie rośnie.
- Ustawienia: hook uruchamia odtwarzacz ze stałym środowiskiem (tylko `IPL_CONFIG_DIR`, `LD_LIBRARY_PATH`, `PATH`), więc w
  radiu tryb i tempo idą z `PMCP_AA_CONF` (domyślnie `/mnt/app/carplaymaps/aa/feeder.conf`, wgrywa `pmcp.sh aa-on`).
  Z pliku czytane są tylko `PMCP_AA_MODE`, `PMCP_AA_RATE_KBPS`, `PMCP_AA_BURST_KB`, `PMCP_AA_IDLE_MS`; zmienne
  środowiska mają pierwszeństwo (testy hosta).

## Budowa i test

```
aa/feeder/build.sh build/aa/feeder                                   # QNX 6.5 armv7, obraz qnx65-armv7-toolchain:8.5
cc -O2 -Wall -Wextra -std=gnu99 -o /tmp/pmcp-aa/feeder-host aa/feeder/aa_most_feeder.c
python3 -I aa/feeder/test/run_host_test.py /tmp/pmcp-aa/feeder-host  # atrapy hooka, bridge'a (format ringu) i dmdt
```

Test: pełna sesja `most` (kolejność dmdt, avcC, 60/60 klatek AVCC, ciągłe seq, rosnący czas, ACK na klatkę), SIGKILL
feedera w trakcie (strażnik oddaje MOST, bridge nie zostaje), tryb `analyze` (brak dmdt i ringu, poprawne podsumowanie),
hamowanie ACK przy 200 KB/s (i prawdziwy czas maksymalnego opóźnienia), tryb `most` z `feeder.conf` (klucze ścieżek
w pliku ignorowane).

Instalacja w radiu: `aa/README.md` (wrapper `gal`, start próbny, przyciski GEM). Nic z tego nie było jeszcze uruchamiane
w radiu.
