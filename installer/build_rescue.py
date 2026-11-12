#!/usr/bin/env python3
"""Build the pmcp rescue card (a separate SD card) from the pinned M.I.B. 3.6.0 zip. Host tool.

  [PMCP_PROFILE=MU1161] python3 -I build_rescue.py OUT_DIR   (the profile only names the unit in the README)

Output = the M.I.B. 3.6.0 tree exactly as in the zip, with three changes:
  - _Swdlautorun.txt renamed to Swdlautorun.txt (armed: the unit enters update mode by itself);
  - Launcher/stuff.sh: our rescue runs first and saves its log last; M.I.B.'s own lines are unchanged;
  - pmcp-rescue/pmcp-rescue.sh added, plus PMCP_RESCUE_README.txt.
metainfo2.txt and Launcher/final/finalScript.sh (SHA1 checked by metainfo2) stay untouched; stuff.sh is
outside metainfo2's reach (M.I.B.'s own comment in stuff.sh). The card carries no pmcp installer.
"""
import hashlib
import os
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


def _load_profile():
    # scripts/profile.py shares its name with a stdlib module, so load it by path (python3 -I has no script dir on sys.path)
    import importlib.util
    spec = importlib.util.spec_from_file_location("pmcp_fwprofile", PROJ / "scripts/profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load(os.environ.get("PMCP_PROFILE", "MU1161"))   # same profile as the build_sd.py run


FW = _load_profile()

def rescue_script():
    """installer/rescue/pmcp-rescue.sh with this profile's factory sizes. A profile with toolbox_nai on its unit (MIB Toolbox's
    NavActiveIgnore.jar, not ours): the rescue never deletes that jar, and it replaces lsd.sh only when it holds our block
    (Toolbox's lsd.sh is a known state, not something to undo)."""
    tbx = "toolbox_nai" in FW["lsd_sh_states"]
    text = (HERE / "rescue/pmcp-rescue.sh").read_text()
    out = []
    for line in text.split("\n"):
        if line.endswith("  #@@OWN_NAI"):
            if tbx:
                continue
            line = line[:-len("  #@@OWN_NAI")]
        if line.endswith("  #@@TBX_ONLY"):   # only for a profile whose unit may run MIB Toolbox's NavActiveIgnore
            if not tbx:
                continue
            line = line[:-len("  #@@TBX_ONLY")]
        out.append(line)
    text = "\n".join(out)
    for k, v in {"@@FACTORY_LSD_SIZE@@": FW["stock"]["LSD"][2], "@@FACTORY_DRV_SIZE@@": FW["stock"]["IAP2DRV"][2],
                 "@@FACTORY_CFG_SIZE@@": FW["stock"]["IAP2CFG"][2],
                 "@@OUR_CFG_SIZE@@": FW["stock"]["IAP2CFG"][2] + 128,   # build_sd.py asserts: iap2.cfg + the 128 B [ident] block
                 # toolbox profile: replace an lsd.sh with our block, or one that is neither factory nor Toolbox's (cut short, foreign)
                 "@@LSD_NOT_FACTORY@@": ('{ has_pmcp_block "$LSD" || { [ "`size_of "$LSD"`" != "$FACTORY_LSD_SIZE" ]'
                                         ' && [ "`size_of "$LSD"`" != "$TOOLBOX_LSD_SIZE" ]; }; }') if tbx
                                        else '[ "`size_of "$LSD"`" != "$FACTORY_LSD_SIZE" ]',
                 "@@TOOLBOX_LSD_SIZE@@": FW["toolbox_nai"]["lsd_sh"][1] if tbx else 0}.items():
        assert k in text or (k == "@@TOOLBOX_LSD_SIZE@@" and not tbx), k
        text = text.replace(k, str(v))
    assert "@@" not in text
    return text.encode()


STUFF_HEAD = """# >>> pmcp rescue card: undo our HMI start changes first, without any redirect (see pmcp-rescue.sh)
if [ -f ${2}/pmcp-rescue/pmcp-rescue.sh ]; then
\t/bin/ksh ${2}/pmcp-rescue/pmcp-rescue.sh ${1} ${2}
fi
# <<< pmcp
"""
STUFF_TAIL = """
# >>> pmcp rescue card: the card is writable now (M.I.B. remounted it), move the RAM log there
if [ -f ${2}/pmcp-rescue/pmcp-rescue.sh ]; then
\t/bin/ksh ${2}/pmcp-rescue/pmcp-rescue.sh --save-log ${2}
fi
# <<< pmcp
"""

README = """CARD 2 - RESCUE: CarPlay map on the AID (VW MHI2 %(id)s, M.I.B. 3.6.0)
========================================================================

When: after "Install all features" the head unit screen stays black or keeps restarting, and
holding the volume knob ~10 s does not help (normally an unconfirmed start falls back to factory
by itself; this card is the second safety net).

What it does: insert it in slot SD1 and wait up to 60 s. The unit enters update mode by itself
(answer Continue if asked; do NOT pull the card while it updates). It then:
  1. puts back the factory lsd.sh,
  2. removes our Java files (%(javafiles)s),
  3. writes /mnt/persist/pmcp/DISABLED (nothing of ours loads at start),
  4. puts back the factory iAP2 driver and iap2.cfg if the route guidance system was on.
The map picture stays. Afterwards, in the green menu: "Remove everything (back to factory files)".
The unit also re-installs M.I.B. 3.6.0 on the way, as when M.I.B. was installed.

When the normal screen is back: remove the card. Its result is in PMCP_RESCUE_LOG.txt on this
card ("RESULT=OK").

After each use M.I.B. disarms the card (Swdlautorun.txt -> _Swdlautorun.txt), so it cannot loop.
To re-arm it: on a computer run the copy helper and choose 3, or rename _Swdlautorun.txt back to
Swdlautorun.txt yourself.

This must be a SEPARATE card. Do not copy pmcp/ onto it. Keep it OUT of the car until needed.
"""


def sha(b, algo="sha256"):
    return hashlib.new(algo, b).hexdigest()


def mib_card(out, head, tail):
    """The pinned M.I.B. 3.6.0 tree in OUT, armed, with HEAD/TAIL added around M.I.B.'s own stuff.sh lines
    (also used by build_logcard.py, the Android Auto log card)."""
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
    (out / "Launcher/stuff.sh").write_bytes((first + "\n" + head + rest + tail).encode("ascii"))
    arm = out / "_Swdlautorun.txt"
    if not arm.exists() or (out / "Swdlautorun.txt").exists():
        sys.exit("unexpected autorun files in the zip")
    arm.rename(out / "Swdlautorun.txt")


def write_manifest(out, name, keys):
    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            lines.append("%s  %8d  %s" % (sha(p.read_bytes()), p.stat().st_size, p.relative_to(out)))
    (out / name).write_text("\n".join(lines) + "\n")
    print("files:", len(lines))
    for l in lines:
        if any(k in l for k in keys):
            print(l)


def main():
    out = pathlib.Path(sys.argv[1])
    mib_card(out, STUFF_HEAD, STUFF_TAIL)
    (out / "pmcp-rescue").mkdir()
    (out / "pmcp-rescue/pmcp-rescue.sh").write_bytes(rescue_script())
    (out / "PMCP_RESCUE_README.txt").write_text(README % {"id": FW["id"], "javafiles": "pmcp-*.jar" if "toolbox_nai" in FW["lsd_sh_states"]
                                                                  else "NavActiveIgnore.jar, pmcp-*.jar"})
    if (out / "pmcp").exists():
        sys.exit("rescue card must not contain the pmcp installer")
    write_manifest(out, "PMCP_RESCUE_MANIFEST.txt", ("stuff.sh", "pmcp-rescue", "Swdlautorun", "metainfo2", "finalScript"))

if __name__ == "__main__":
    main()
