#!/usr/bin/env python3
"""Build the pmcp log card (a separate SD card) from the pinned M.I.B. 3.6.0 zip. Host tool.

  python3 -I build_logcard.py OUT_DIR

In GEM the SD card is read-only, so the AA logs saved in the unit (pmcp.sh aa-log-save) reach a computer through this
card: it runs in update mode like the rescue card, but only READS the unit. Output = the M.I.B. 3.6.0 tree as in the zip
(build_rescue.mib_card: same pinned zip, same checks), armed, with one block appended to Launcher/stuff.sh that runs
pmcp-logs/pmcp-logs.sh at the end (the card is writable then), plus PMCP_LOGS_README.txt. No rescue script, no installer.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))   # python3 -I leaves the script directory out
from build_rescue import HERE, mib_card, write_manifest  # noqa: E402

STUFF_TAIL = """
# >>> pmcp log card: the card is writable now (M.I.B. remounted it); copy the saved AA logs to it, read-only on the unit
if [ -f ${2}/pmcp-logs/pmcp-logs.sh ]; then
\t/bin/ksh ${2}/pmcp-logs/pmcp-logs.sh ${2}
fi
# <<< pmcp
"""

README = """CARD 3 - LOGS: copy the saved Android Auto logs to this card (VW MHI2 MU1161, M.I.B. 3.6.0)
=========================================================================================

Before: in GEM -> pmcp_CarPlay_AID -> pmcp_android_auto (the Android Auto screen, on the pmcp main screen), "AA save log:
copy this start's AA log to the unit (for the log card)" in the same start as the AA session (the log lives in RAM until
the next start). The unit keeps up to 5 saved logs in /mnt/app/carplaymaps/logs.

What it does: insert it in slot SD1 and wait up to 60 s. The unit enters update mode by itself (answer Continue if
asked; do NOT pull the card while it updates). At the end it copies to PMCP_LOGS/ on this card:
  - the saved AA logs (aa-log-1.txt ...),
  - pmcp's boot log.
It changes NOTHING on pmcp's files (it only reads them). To get there it runs the full M.I.B. 3.6.0 stuff.sh in update
mode (SWDL), as when M.I.B. was installed: the unit re-installs M.I.B. 3.6.0 on the way.

When the normal screen is back: remove the card. PMCP_LOGS/PMCP_LOGS_RESULT.txt ends with "RESULT=OK".
After the copies are checked on a computer: GEM -> pmcp_CarPlay_AID -> pmcp_android_auto, "AA delete saved logs (after
the log card copied them)".

After each use M.I.B. disarms the card (Swdlautorun.txt -> _Swdlautorun.txt). To use it again, rename
_Swdlautorun.txt back to Swdlautorun.txt on a computer.

This must be a SEPARATE card: not the pmcp card (card 1), not the rescue card (card 2). Keep it out of the car until needed.
"""


def main():
    out = pathlib.Path(sys.argv[1])
    mib_card(out, "", STUFF_TAIL)
    (out / "pmcp-logs").mkdir()
    (out / "pmcp-logs/pmcp-logs.sh").write_bytes((HERE / "logcard/pmcp-logs.sh").read_bytes())
    (out / "PMCP_LOGS_README.txt").write_text(README)
    if (out / "pmcp").exists() or (out / "pmcp-rescue").exists():
        sys.exit("log card must not contain the pmcp installer or the rescue script")
    write_manifest(out, "PMCP_LOGS_MANIFEST.txt", ("stuff.sh", "pmcp-logs", "Swdlautorun", "metainfo2", "finalScript"))


if __name__ == "__main__":
    main()
