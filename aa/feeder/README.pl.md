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

## Bezpośrednie wyjście MOST (v11, `PMCP_AA_OUTPUT=direct`)

Domyślne `PMCP_AA_OUTPUT=ring` to wszystko powyżej, bez zmian. Z `direct` (tylko przy `PMCP_AA_MODE=most`) feeder nie
uruchamia `altscreen-most-bridge` i nie tworzy ringu:

- `aa/most/ts_mux.c` składa klatki w MPEG-TS bridge'a bajt w bajt (PID-y, PAT/PMT/PCR co 327 pakietów, PCR z licznika
  pakietów, układ PES, AUD oraz SPS/PPS przed IDR, bloki 12032 B). Celowe różnice, jak w poprawionym bridge'u harman-f:
  tylko całe AU, pierwsze AU ma flagę discontinuity, PTS ustawiany przy budowie pierwszego pakietu AU (wyprzedzenie
  nad PCR ok. 100 ms, nigdy ujemne).
- `aa/most/most_writer.c` otwiera `/dev/mlb/isoTX2` z sekwencją devctl bridge'a i zapisuje całe bloki z osobnego wątku
  (EAGAIN: poll z przejściem na sen 1 ms, albo sterownik blokujący).
- Nic nie jest gubione, nikt nie czeka na IDR ani o niego nie prosi. Hamowanie idzie do telefonu: ACK są wstrzymane,
  gdy w kolejce jest więcej niż `PMCP_AA_ACK_HIGH_PKTS` (1024) pakietów TS, i puszczane poniżej `PMCP_AA_ACK_LOW_PKTS` (512).
- Strażnik ten sam; w tym trybie nie uruchamia bridge'a i oddaje MOST, gdy feeder zamknie rurkę (feeder najpierw zamyka
  isoTX2). Błąd zapisu, krótki zapis albo zawieszony zapis oddaje MOST od razu; sesja trwa dalej jako analiza.
- Ustawienia (także z `feeder.conf`): `PMCP_AA_OUTPUT`, `PMCP_AA_ACK_HIGH_PKTS`, `PMCP_AA_ACK_LOW_PKTS`,
  `PMCP_AA_QUEUE_KB` (8192), `PMCP_AA_MOST_WAIT` (`auto`|`poll`|`sleep`|`block`), `PMCP_AA_MOST_STALL_MS` (5000),
  `PMCP_AA_LEAD_MS` / `_MIN_MS` / `_MAX_MS` (100/50/130, v12: 200), `PMCP_AA_DISC_FIRST` (1). `PMCP_AA_RATE_KBPS` ma w tym trybie
  domyślnie 0. Tylko ze środowiska: `PMCP_AA_MOST_DEV` (`/dev/mlb/isoTX2`).
- v12 (po teście w aucie A147): w trybie direct nie ma dawkowania v10 (`PMCP_AA_PACE_*` tam ignorowane; trzymało klatki
  do 405 ms bez potrzeby) i jest `PMCP_AA_MOST_SLEEP_US` (6500, 0 = kroki 1 ms jak w v11): pierwszy sen po przyjętym
  bloku przeczekuje większość ~7,9 ms, których sterownik potrzebuje na blok 12032 B (v11 budził się ~4 razy na blok).
- v13 (po teście w aucie A152): zapas PTS jest zbijany powyżej 130 ms (`PMCP_AA_LEAD_MAX_MS`, było 200: zapas stał
  na ~150 ms); przytrzymanie na starcie w trybie direct to `PMCP_AA_DIRECT_SYNC_HOLD_MS` (1500; `PMCP_AA_SYNC_HOLD_MS`=3000
  z feeder.conf zostaje dla bridge'a); zdarzenia MOST notują też przerwy telefonu od 1,5 s i 3 s ciszy ze stanem ACK i
  kolejki w tej chwili oraz każde wstrzymanie/puszczenie ACK; pełny status 3 ostatnich sesji zostaje jako
  `<status>-prev1..3` (GEM „AA save log” je kopiuje); linia sesji ma przerwy i liczbę ACK.

Diagnostyka w obu wyjściach: strażnik trzyma pierwsze 30 linii bridge'a (odczyty devctl) obok ostatnich;
`PMCP_AA_CAPTURE_S=N` (domyślnie 0) nagrywa jednostki dostępu z telefonu przez N s do `PMCP_AA_CAPTURE_PATH` (tylko ze
środowiska, domyślnie `/mnt/persist/pmcp/aa-stream.h264`, najwyżej 6 MB, Annex B z AUD w każdym AU, plus `.idx` z czasami).
v12/v13: na partycji zostaje 8 MB (v13: 4 MB) wolnego; gdy całe nagranie się nie mieści, jest przycinane na granicy AU (min. 256 KB),
a status pokazuje errno, wolne miejsce i ile zapisano.

## Budowa i test

```
aa/feeder/build.sh build/aa/feeder                                   # QNX 6.5 armv7, obraz qnx65-armv7-toolchain:8.5
S="aa/feeder/aa_most_feeder.c aa/most/ts_mux.c aa/most/most_writer.c"
cc -O2 -Wall -Wextra -Werror -std=gnu99 -pthread -o /tmp/pmcp-aa/feeder-host $S
cc -O2 -Wall -Wextra -Werror -std=gnu99 -pthread -DMOST_HOST_SIM -o /tmp/pmcp-aa/feeder-host-sim $S aa/most/test/host_mlb.c
python3 -I aa/feeder/test/run_host_test.py /tmp/pmcp-aa/feeder-host  # atrapy hooka, bridge'a (format ringu) i dmdt
python3 -I aa/feeder/test/run_direct_test.py /tmp/pmcp-aa/feeder-host-sim [bridge-stage0/golden]   # wyjście direct
python3 -I aa/most/test/run_mux_test.py bridge-stage0/golden /tmp/pmcp-aa/mux   # ts_mux wobec nagrań golden
```

Test direct symuluje isoTX2 plikiem `host_mlb.c` z bridge-stage0 (tempo, EAGAIN albo blokowanie, krótkie zapisy, przestoje,
EIO, statusy devctl) i dekoduje TS analizatorem `ts_analyse.py` z bridge-stage0 (oba skopiowane bez zmian do
`aa/most/test/`).

Test: pełna sesja `most` (kolejność dmdt, avcC, 60/60 klatek AVCC, ciągłe seq, rosnący czas, ACK na klatkę), SIGKILL
feedera w trakcie (strażnik oddaje MOST, bridge nie zostaje), tryb `analyze` (brak dmdt i ringu, poprawne podsumowanie),
hamowanie ACK przy 200 KB/s (i prawdziwy czas maksymalnego opóźnienia), tryb `most` z `feeder.conf` (klucze ścieżek
w pliku ignorowane).

Instalacja w radiu: `aa/README.md` (wrapper `gal`, start próbny, przyciski GEM). Nic z tego nie było jeszcze uruchamiane
w radiu.
