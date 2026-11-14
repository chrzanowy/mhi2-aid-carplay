# Etap 1 pmcp-most: raport dla prowadzącego (2026-11-14)

## Co zrobione

- **upstream/:** most Tomasza z commita 59d6a4e, czyli `altscreen_most_bridge.c` + 5 nagłówków + LICENSE, bajt w bajt.
  Do tego `PROVENANCE.json` (repo, commit, ścieżki, sha256, licencja).
- **src/:** kopia z poprawkami oznaczonymi `pmcp:`. Zmienione są tylko 2 pliki: `altscreen_most_bridge.c` (+76 linii,
  4 usunięte: stare ciało `queue_discard_all`) i `cpmap_resources.h` (+17). Nowy jest `pmcp_most.h`. Zmiany:
  - Log trafia do `/ramdisk/pmcp-most/bridge.log`: `open` + `dup2` (efekt `freopen`), limit 64 KB ściśle,
    rotacja do `.1`, env `PMCP_MOST_LOG`.
  - Plik `/ramdisk/most-src/consumer` wg v0.2 §3:
    - odświeżany co 1 s z istniejącej pętli czytnika (bez nowego wątku);
    - zapis tmp + rename, pola przycięte wg doprecyzowań v0.2;
    - `ready=0` przy wyjściu;
    - env `PMCP_MOST_SRC_DIR`.
  - Pliki sesji §2:
    - `state=stop` właściciela (zgodny `gen`) kończy strumień jak SIGTERM (exit 0);
    - zniknięcie pliku przy martwym pid działa tak samo;
    - stop starszy niż start mostu jest ignorowany, żeby supervisor nie restartował mostu w pętli;
    - bez plików kontraktu most zachowuje się jak upstream.
  - `CPMAP_ANIMATION_STATE_DIR="/nonexistent"`.
  - Reset kolejki nie ucina klatki (błąd jest też w upstream). Writer zdejmuje pakiety po jednym, więc przy
    `latency-reset` mógł już wysłać początek najstarszej klatki z kolejki, a reszta szła do kosza: na isoTX2 trafiała
    ucięta klatka P. Teraz `queue_discard_all` zostawia resztę tej klatki (do następnego pakietu z PUSI) i wyrzuca
    tylko całe klatki.
  - Bez zmian: flaga AA (domyślnie CP), limit 2048, reclaim (dc 72 / sc 4 72, ENOMEM, 180 s, 3 próby).
  - Znaczniki `TODO(stage 1b)` pokazują, gdzie wejdzie bramka konsumenta z kontraktu v1.1. Jej nie implementowałem.
- **build.sh:** build QNX w dockerze (bez sieci). Robi dwa buildy i porównuje je (reprodukowalność), potem strip,
  NEEDED, sha256 i lista importów.
- **test/:** build hosta (tryb `ALTSCREEN_BRIDGE_FILE_OUTPUT` + shim ścieżek), producent ringu w C, harness w Python
  (`-I`), fałszywy dmdt.

## Wynik buildu QNX

- `altscreen-most-bridge`: 32076 B, sha256 `672f791e219ba134d226b7c607ffd2ee8b63781d4fa864882fa3f30f29048650`.
- Dwa buildy są identyczne.
- gcc 8.5.0.
- NEEDED: `libsocket.so.3`, `libc.so.3` (jak mathsls).

## Testy hosta

`BRIDGE TESTS: 51 ok, 0 failed`. Uruchomione 3 razy pod rząd, za każdym razem bez błędów, ok. 45 s na przebieg.

- Wynik ts_analyse jest OK na wejściu syntetycznym i na prawdziwym nagraniu AA z auta (150 klatek, zero zgubionych).
- `ts_compare --mode cp` upstream vs nasz = SAME, czyli nasze zmiany nie ruszają TS.
- Wymuszony IDR po zatorze:
  - przebieg: latency-reset (queued 2204 > 2048), znacznik, IDR od producenta, latency-resume-idr;
  - każdy ciąg zrzuconych klatek kończy się na IDR.
- ENOMEM:
  - dmdt dostaje dokładnie `dc 72`, `sc 4 72` ×3, za każdym razem resync obrazu;
  - czwarte ENOMEM daje „not-attempted” i wyjście;
  - poza oknem nie ma wywołania dmdt.
- Stop sesji: most kończy ok. 40 ms po `state=stop` (limit 1,5 s). Przy znikniętym pliku z martwym pid: ok. 85 ms.
- Log: rotacja przy 64 KB, oba pliki ≤ 64 KB, nie ma `.2`.

## Sprawdzenie importów

- 68 importów.
- Względem mostu mathsls jest 30 nowych. Większość importują już binarki, które działają na jednostce (supervisor
  i helpery mathsls, `core.so`, nasz `aa-most-feeder`).
- **Niepotwierdzone na libc MU1161:** `execve feof lseek lstat vfprintf`.
  - Wszystkie są w libc.so.3 z SDK QNX 6.5.0.
  - Wszystkie importuje binarka mostu Tomasza z MU1367 (QNX 6.5, jeździ w autach).
  - Kopii libc.so.3 z naszej jednostki nie ma w backup/MU1161: obraz MMX_fs0 nie zawiera tych nazw, bo libc leży w IFS.
  - Ryzyko niskie. Potwierdzi je pierwszy start na karcie exp (most nie wystartuje, jeśli symbolu brak).
- `__register_frame_info` / `__deregister_frame_info` to słabe symbole (WEAK), ma je też mathsls.
- Wyrzuciłem `strcpy` z naszego kodu, żeby nie dokładać niepotwierdzonych importów.

- Niestabilny test `force-idr` (ok. 1 na 10 przebiegów: „AU 40: payload matches no input frame”) to był właśnie ten
  błąd, a nie test. Upstream w tym samym scenariuszu: 4 z 30 przebiegów z uciętą klatką (36 z 550 pakietów pierwszej
  klatki zatoru). Po poprawce: 0 błędów w 100 przebiegach scenariusza; w 19 z nich reset wypadł w środku klatki i ta klatka wyszła
  cała. Do tego 5 pełnych przebiegów bez błędów.

## Otwarte ryzyka

1. **Licencja.** Upstream to „GNU GPL v3” bez „or later”, więc poprawione pliki upstream mają SPDX `GPL-3.0-only`.
   Nasze nowe pliki mają GPL-3.0-or-later. Odstępstwo od briefu, do decyzji prowadzącego.
2. **Wyjście po `state=stop`.** Most kończy się sam, więc supervisor mathsls zobaczy `bridge-exited`, przywróci OEM
   (`dc 70 33`) i po 2 s spróbuje znowu. Tak samo jak dziś po stream-timeout, ale dla Wi-Fi trzeba sprawdzić w aucie,
   czy nie robi to mignięcia.
3. `age_ms` liczony względem najpunktualniejszej ramki generacji (ring nie ma czasu zapisu), więc dryf zegara telefonu
   powoli go zawyża.
4. Ryzyka z etapu 0 zostają do auta:
   - core.so a force-IDR przy reconnect (do ~64 s czarnej mapy);
   - ENOMEM na MU1161 niepotwierdzone;
   - wyścig reclaim z `dc 70 33` supervisora.
5. Na hoście writer w trybie plikowym jest wolniejszy niż MOST, więc lead PTS rośnie. To artefakt, identyczny dla
   upstream.
6. **Nie zrobione:**
   - instalator, przełącznik GEM, pin w build_sd.py;
   - `cp-log-save` i przycisk 9 dla `/ramdisk/pmcp-most/`;
   - jazda testowa;
   - bramka v1.1 (etap 1b).
