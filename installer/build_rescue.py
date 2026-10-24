#!/usr/bin/env python3
"""Build the pmcp rescue card (a separate SD card) from the pinned M.I.B. 3.6.0 zip. Host tool.

  python3 -I build_rescue.py OUT_DIR

Output = the M.I.B. 3.6.0 tree exactly as in the zip, with three changes:
  - _Swdlautorun.txt renamed to Swdlautorun.txt (armed: the unit enters update mode by itself);
  - Launcher/stuff.sh: our rescue runs first and saves its log last; M.I.B.'s own lines are unchanged;
  - pmcp-ratunek/pmcp-ratunek.sh added, plus PMCP_RATUNEK_README.txt.
metainfo2.txt and Launcher/final/finalScript.sh (SHA1 checked by metainfo2) stay untouched; stuff.sh is
outside metainfo2's reach (M.I.B.'s own comment in stuff.sh). The card carries no pmcp installer.
"""
import hashlib
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
PROJ = HERE.parent         # this project (any folder name)
ZIP = PROJ / "mib/downloads/MIB_V3.6.0.zip"
ZIP_SHA = "4bfc6e725b5cc60c3c8c73081609dabfe1a2016b5d8671e2438592e673a98086"
PREFIX = "M.I.B._More-Incredible-Bash-3.6.0/"
STUFF_SHA = "bac7f77c6b267f438a57d1dca92550d9ead0e4ad5b4c8505e480b180e0096964"
FINAL_SHA1 = "ba391875e14a8794b683cc02556990fcb555fe08"

STUFF_HEAD = """# >>> pmcp rescue card: undo our HMI start changes first, without any redirect (see pmcp-ratunek.sh)
if [ -f ${2}/pmcp-ratunek/pmcp-ratunek.sh ]; then
\t/bin/ksh ${2}/pmcp-ratunek/pmcp-ratunek.sh ${1} ${2}
fi
# <<< pmcp
"""
STUFF_TAIL = """
# >>> pmcp rescue card: the card is writable now (M.I.B. remounted it), move the RAM log there
if [ -f ${2}/pmcp-ratunek/pmcp-ratunek.sh ]; then
\t/bin/ksh ${2}/pmcp-ratunek/pmcp-ratunek.sh --save-log ${2}
fi
# <<< pmcp
"""

README = """KARTA RATUNKOWA pmcp (Passat B8, MHI2 MU1161, M.I.B. 3.6.0)
==============================================================

Kiedy: po wlaczeniu paczki Java (etap B) HMI nie wstaje: czarny ekran albo logo w kolko,
nie da sie wejsc do zielonego menu. Najpierw sprobuj: pokretlo glosnosci ~10 s (restart);
niepotwierdzony zestaw JAR-ow laduje sie tylko raz (start probny). Ta karta jest druga siatka
bezpieczenstwa: na wypadek, gdyby zepsuty zestaw zostal potwierdzony.

Jak dziala: Swdlautorun.txt w katalogu glownym -> radio samo wchodzi w tryb aktualizacji
(RUN_MODE=swdl; nasz blok w lsd.sh w tym trybie nic nie laduje, HMI aktualizacji jest fabryczne)
-> M.I.B. 3.6.0 -> Launcher/stuff.sh -> pmcp-ratunek/pmcp-ratunek.sh, ktory:
  1. przywraca fabryczny lsd.sh (kopia z /mnt/app/carplaymaps/rollback/),
  2. usuwa nasze JAR-y (NavActiveIgnore.jar, pmcp-*.jar),
  3. zapisuje /mnt/persist/pmcp/DISABLED (nasz blok w lsd.sh nic nie laduje),
  4. przywraca fabryczny sterownik iAP2 i iap2.cfg, jesli byl wlaczony System RG (paczka E).
Obraz CarPlay (etap A) zostaje. Potem w GEM: pmcp -> "Przywroc pliki fabryczne".
Radio przy okazji instaluje ponownie M.I.B. 3.6.0 (ta sama wersja co teraz), jak przy SD#1.

TO MUSI BYC OSOBNA KARTA. Nie kopiuj na nia pmcp/. Nie zostawiaj jej w aucie.
Po kazdym uzyciu M.I.B. sam ja rozbraja (Swdlautorun.txt -> _Swdlautorun.txt).
Ponowne uzbrojenie: zmien nazwe z powrotem na Swdlautorun.txt.

TEST NA ZDROWYM AUCIE (przed odblokowaniem etapu B):
 1. Zasilanie jak przy SD#1 (prostownik albo silnik na zewnatrz), zaplon ON, radio dziala.
 2. Wloz karte do SD1 i czekaj (do ~60 s): radio samo przejdzie w tryb aktualizacji, moze sie
    kilka razy zrestartowac. Pytanie w menu aktualizacji: Continue / Dalej. Nie wyjmuj karty.
 3. Gdy radio wroci do normalnego ekranu: wyjmij karte.
 4. Na karcie: PMCP_RATUNEK_LOG.txt musi konczyc sie linia "=== PMCP RATUNEK koniec ===",
    przed nia "WYNIK=OK". Na karcie ma byc _Swdlautorun.txt (rozbrojona).
    Daj mi ten log do sprawdzenia. Dopiero wtedy tworzymy na karcie pmcp plik ODBLOKUJ_ETAP_B.
 5. Uzbroj karte ponownie i odloz.
"""


def sha(b, algo="sha256"):
    return hashlib.new(algo, b).hexdigest()


def main():
    out = pathlib.Path(sys.argv[1])
    if out.exists():
        sys.exit("output exists: %s" % out)
    data = ZIP.read_bytes()
    if sha(data) != ZIP_SHA:
        sys.exit("M.I.B. zip is not the pinned 3.6.0")
    with zipfile.ZipFile(ZIP) as z:
        names = [n for n in z.namelist() if n.startswith(PREFIX)]
        for n in names:
            rel = n[len(PREFIX):]
            if not rel:
                continue
            dst = out / rel
            if n.endswith("/"):
                dst.mkdir(parents=True, exist_ok=True)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(n))
    stuff = (out / "Launcher/stuff.sh").read_bytes()
    if sha(stuff) != STUFF_SHA:
        sys.exit("stuff.sh differs from M.I.B. 3.6.0")
    if sha((out / "Launcher/final/finalScript.sh").read_bytes(), "sha1") != FINAL_SHA1:
        sys.exit("finalScript.sh differs from metainfo2")
    text = stuff.decode("ascii")
    first, rest = text.split("\n", 1)
    assert first == "#!/bin/ksh"
    (out / "Launcher/stuff.sh").write_bytes((first + "\n" + STUFF_HEAD + rest + STUFF_TAIL).encode("ascii"))
    arm = out / "_Swdlautorun.txt"
    if not arm.exists() or (out / "Swdlautorun.txt").exists():
        sys.exit("unexpected autorun files in the zip")
    arm.rename(out / "Swdlautorun.txt")
    (out / "pmcp-ratunek").mkdir()
    (out / "pmcp-ratunek/pmcp-ratunek.sh").write_bytes((HERE / "rescue/pmcp-ratunek.sh").read_bytes())
    (out / "PMCP_RATUNEK_README.txt").write_text(README)
    if (out / "pmcp").exists():
        sys.exit("rescue card must not contain the pmcp installer")
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            lines.append("%s  %8d  %s" % (sha(p.read_bytes()), p.stat().st_size, p.relative_to(out)))
    (out / "PMCP_RESCUE_MANIFEST.txt").write_text("\n".join(lines) + "\n")
    print("files:", len(lines))
    for l in lines:
        if any(k in l for k in ("stuff.sh", "pmcp-ratunek", "Swdlautorun", "metainfo2", "finalScript")):
            print(l)


if __name__ == "__main__":
    main()
