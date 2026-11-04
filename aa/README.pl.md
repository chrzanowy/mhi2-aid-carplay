# Android Auto na AID (eksperymentalne, gałąź `experimental`)

[English version: README.md](README.md)

Stan (2026-11-04, testy w Passacie B8, MU1161 / AID 791, Samsung Galaxy A16 z Androidem 16):

- **Działa:** obraz Google Maps na AID przez własną ścieżkę MOST radia; przełączenie z CarPlay na Android Auto bez
  restartu; natywne strzałki VW z dystansem z manewrów Google Maps (94 z 94 rozpoznane w jeździe testowej).
- **Otwarte:** telefon wysyła jedną klatkę kluczową (IDR) na sesję. Gdy AID zgubi obraz, na starcie (mniej więcej co drugie
  podłączenie) albo czasem w trakcie jazdy, zostaje ciemny albo na ekranie ładowania aż do ponownego podłączenia telefonu.
  Feeder v9 dawkuje duże klatki i zapisuje przerwy między klatkami, żeby to zawęzić.
- **Otwarte:** brak strzałki VW na pierwszym kroku trasy z Android Auto (krok „wyjazd” nie jest jeszcze mapowany).

Ta gałąź to wydanie (`main`, v1.4.2) plus Android Auto. Wszystko z CarPlay działa dokładnie jak w wydaniu.

## Jak to działa

Obraz idzie tą samą drogą co nasza mapa CarPlay. Radio niczego nie dekoduje ani nie koduje:

```
telefon AA -> gal (odbiornik AA radia) + hook -> aa-most-feeder -> ring /ramdisk/carplay-alt-ring.bin
           -> altscreen-most-bridge (bridge mapy CarPlay) -> MOST -> AID dekoduje H.264
```

- Hook (MacsInSpace [mib-cluster-map](https://github.com/MacsInSpace/mib-cluster-map) @ `07361db`, zbudowany bez żadnej
  ścieżki do karty SD) zgłasza telefonowi drugi ekran 800x480 („licznik”) w protokole 1.7 i zamiast go dekodować oddaje
  strumień H.264 naszemu feederowi.
- Feeder (`feeder/`) przejmuje kanał wideo MOST do AID, czeka aż AID będzie gotowy, potem wpisuje klatki do tego samego
  ringu, którego używa mapa CarPlay. Dawkuje duże klatki i zbiera statystyki do `AA status`.
- Hook czyta też komunikaty nawigacji Google Maps (0x8006 następny krok, 0x8007 dystans) i zapisuje ten sam format
  skrzynki, który pisze czytnik prowadzenia CarPlay, do `/ramdisk/pmcp-aa-rg` (`hook/pmcp_rg.c`). Pakiet Java **rg-aa**
  (rg + `rg/lanes/aa.py`) czyta ją przy podłączonym telefonie z Android Auto i pokazuje strzałki VW. Dystans do celu
  i czas przyjazdu zostają w obrazie Android Auto.

## Pliki w radiu

| W radiu | Skąd | Uwagi |
|---|---|---|
| `/mnt/app/eso/bin/apps/gal` | `unit/gal.wrapper.sh` | wrapper: start próbny, potem Confirm (jak pakiety Java) |
| `carplaymaps/aa/gal.real` | fabryczny `gal` radia (`3b422d47…`) | kopia robiona przez `aa-on`; droga powrotu |
| `carplaymaps/aa/libgal_hook.so`, `libdmdt_flush.so` | `hook/build.sh <katalog> gamma` | hook g2 |
| `carplaymaps/aa/aa-most-feeder` | `feeder/build.sh` | feeder v9 |
| `carplaymaps/aa/gal-hook.conf` | `unit/gal-hook-gamma.conf` | protokół 1.7, `GAL_PMCP_RG=1` |
| `carplaymaps/aa/feeder.conf` | `unit/feeder-gamma.conf` | MOST, 5 s czekania, synchronizacja startu, dawkowanie |
| `carplaymaps/aa/AA_BOOT` | `pmcp.sh` | id zestawu: `gamma-` + 8 znaków hasha hooka, feedera i ustawień hooka |

W `/mnt/system` nic się nie zmienia. Zapisane logi trafiają do `carplaymaps/logs/` (`AA save log`).

## Bezpieczeństwo

- **Start próbny:** nowy zestaw AA działa z hookiem tylko przez jeden start radia. Po restarcie bez `AA 2. Confirm` `gal`
  jest znowu fabryczny. `DISABLED` z karty ratunkowej też wyłącza hook.
- **Nic na karcie SD nie wpływa na `gal`:** `hook/patch_no_sd.py` usuwa przed buildem ścieżki hooka do kart SD i `/tmp`.
- Feeder czyta z `feeder.conf` tylko swoje klucze ustawień, nigdy ścieżek.
- `AA remove`, „Remove everything” i „Remove experimental Android Auto” z karty wydania przywracają fabryczny `gal`, tylko
  z kopii z fabrycznym hashem.
- Zestawy AA z wcześniejszych kart eksperymentalnych są rozpoznawane (`AA_OLD`): status `old`, `AA 1` je aktualizuje bez
  wcześniejszego usuwania.

## Czego się dowiedzieliśmy (szczegóły: audyt A-AA1..A-AA30 w notatkach projektu)

- Pierwsza IDR strumienia ma ok. 1 KB i jest czarna; mapa przychodzi w klatkach P po niej. AID musi być gotowy, zanim
  telefon zacznie: feeder przejmuje MOST, czeka 5 s i przez 3 s powtarza pierwszą IDR, wstrzymując jej ACK.
- Prośba do telefonu o nową klatkę kluczową nie działa: ponowne wysłanie konfiguracji wideo zrywa połączenie ok. 9 s później,
  cykl fokusu daje ~3 fps i reset po ~130 s.
- Producent CarPlay trzyma 16 MB plik ringu zmapowany, więc jego usunięcie zapychało `/ramdisk`; feeder używa go ponownie.
- Pełne komunikaty nawigacji Google Maps wymagają protokołu 1.7.

## Testy na komputerze i build

```
python3 -I aa/feeder/test/run_host_test.py <feeder zbudowany na komputer>   # cc -O2 -Wall -Wextra -Werror -std=gnu99
aa/hook/test/run_keyframe_test.sh ; aa/hook/test/run_rg_test.sh
aa/hook/build.sh   build/aa-g2 gamma     # obraz Dockera qnx65-armv7-toolchain:8.5; dwa buildy, muszą być identyczne
aa/feeder/build.sh build/aa-v9/feeder
rg/build.sh <skonwertowany lsd.jar> build/rg-mu1161-lanes-uturn-asf-m-aa lanes-uturn-asf-m-aa   # pakiet rg-aa
python3 -I installer/build_sd.py build/sd
python3 -I installer/build_logcard.py build/karta3-logi   # karta 3 (logi), osobna karta SD
```

`build_sd.py` przyjmuje pliki tylko z przypiętymi hashami.

Kroki w aucie: [docs/pl/13-instrukcja-eksperymentalna.md](../docs/pl/13-instrukcja-eksperymentalna.md).
