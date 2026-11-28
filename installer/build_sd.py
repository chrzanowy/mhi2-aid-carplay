#!/usr/bin/env python3
"""Assemble the pmcp tree for the M.I.B. SD card (SD#2) from pinned inputs. Host tool, read-only on inputs.

  [PMCP_PROFILE=MU1161] python3 -I build_sd.py OUT_DIR

PMCP_PROFILE (default MU1161) names the firmware profile: profiles/<ID>/profile.json holds the facts about the unit
(stock file pins, jxe size, backup folder, packages), profiles/<ID>/history.json the older cards' files this installer
still replaces. The pins of this tool's own build results (PAYLOAD) stay below, per profile.
Every input is checked against its SHA-256 and size before use; the output must not exist yet.
The patched lsd.sh is generated here from the verified factory file, so the unit only copies
a file whose hash is known in advance. Output: OUT_DIR/pmcp/... (installer, payload, one script per GEM button in pmcp/menu/) and
OUT_DIR/esd/Launcher-sda0.esd (the M.I.B. 3.6.0 menu with one pmcp screen appended),
plus OUT_DIR/BUILD-MANIFEST.txt with every output hash.
"""
import hashlib
import importlib.util
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent  # workspace: upstream/, backup/, archives/ next to this project
PROJ = HERE.parent         # this project (any folder name)


def _load_profile_module():
    # scripts/profile.py shares its name with a stdlib module, so load it by path (python3 -I has no script dir on sys.path)
    spec = importlib.util.spec_from_file_location("pmcp_fwprofile", PROJ / "scripts/profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fwprofile = _load_profile_module()
PROFILE_ID = os.environ.get("PMCP_PROFILE", "MU1161")
FW = fwprofile.load(PROFILE_ID)               # facts about this unit firmware (exits on a malformed profile)
HIST = fwprofile.load_history(PROFILE_ID)     # earlier cards of this profile (hashes only)
# release v1.9.0: Android Auto feeder v17 (AA map keep-alive), rg component 1, earlier lsd.sh replaced in place
PMCP_BASE_VERSION = "pmcp-0.9.0-" + FW["version_tag"]
# Experimental card from the same tree (PMCP_BUILD_EXPERIMENTAL=1): "-exp-" in the version, plus the diagnostics buttons
# (AA record, AA output switches are in every card since AA 1.0). Same payload otherwise, so it never forces another set.
if os.environ.get("PMCP_BUILD_EXPERIMENTAL") == "1":
    PMCP_BASE_VERSION = "pmcp-0.9.0-exp-" + FW["version_tag"]
IS_EXP = "-exp-" in PMCP_BASE_VERSION
PMCP_VERSION = None   # PMCP_BASE_VERSION + "-" + first 8 hex of payload manifest, pmcp.sh and menu (set in main): one id per build

# M.I.B. backup of the unit (folder named after the unit; every file read from it is pinned by sha256 below)
BACKUP_ROOT = pathlib.Path(os.environ.get("PMCP_BACKUP", REPO / "backup" / FW["backup_dir"]))
BACKUP = BACKUP_ROOT / FW["appimg"]
SYSTEM = BACKUP_ROOT / FW["system"]
MATHSLS = REPO / "upstream/mathsls" / FW["mathsls_payload"]  # pinned commit: profile mathsls_commit
TUNING = PROJ / "build" / FW["version_tag"] / "tuning"
# The GEM menu file of the M.I.B. version on the user's SD card (MIB_V3.6.0.zip, esd/Launcher-sda0.esd).
# The unit links engdefs/z_Launcher-sda0.esd to this file on the card, so adding a screen here changes nothing on the unit.
MIB_ESD = (REPO / "archives/mib-3.6.0/Launcher-sda0.esd",
           "22739f7226f36d089e2e0485fe2b6874aba2ee6b7b57c807de7bc25c0fdc9121", 111474)
# Java packages (stage B+): name -> GEM label. Each needs a "JAR_<name>" entry in PAYLOAD.
JAVA_PACKAGES_ALL = [("nai", "nai: AID map stays while the iPhone navigates (NavActiveIgnore)"),
                      ("np", "np: CarPlay song title and artist on the AID"),
                      ("rg", "rg: route guidance: arrows, lanes, distance bar, street, ETA (needs Route guidance system)"),
                      ("zoom", "zoom: CarPlay map zoom with the steering wheel arrows"),
                      ("dn", "dn: CarPlay map day/night on the AID (sent again after start)"),
                      # optional (not in button 3), output off until enabled with speedlimit-mode
                      ("sl", "sl: native VW map speed limit in the AID road text (optional, output off until enabled)"),
                      # in main 4: the settings page in App-Connect settings, also "Save" for a trial start (ui/README.md)
                      ("ui", "ui: AID navigation configuration in App-Connect settings, saves trial starts without the card")]
# Experimental cards only: the wireless CarPlay HMI hook of the WL project (separate private repo; the JAR is pinned
# here and lives outside git, build/wl-<sha8>/pmcp-wl.jar). Not in main menu 4; inactive without a WL session file.
# WL commit 9c1c8d6 (A250): replaces one factory class, the SI HsmTarget; new classes only in com.wlcp.hmi. Run-time
# identity check of the factory classes it relies on (com/wlcp/hmi/Identity): on a mismatch wl stays off for that start.
# 9c1c8d6: CarPlay screen restored after a refused take (V5-5/V5-6), HFP drop off unless /mnt/persist/wlcp/HFP_DROP_ON
WL_JAR_PIN = ("build/wl-f8a84c89/pmcp-wl.jar", "f8a84c89401ee82533643e28766936c58791d2fab4e1933442256566ba4dc0a0", 43488)
if os.environ.get("PMCP_BUILD_EXPERIMENTAL") == "1" and WL_JAR_PIN:
    JAVA_PACKAGES_ALL.append(("wl", "wl: wireless CarPlay HMI hook (experimental; inactive without a WL session)"))
# only what the profile supports reaches the card, the GEM menu and the settings page
JAVA_PACKAGES = [x for x in JAVA_PACKAGES_ALL if x[0] in FW["packages"]]
# The GEM menu is the same for every profile: a package or Android Auto that the profile does not have keeps its button,
# which says "not yet supported" and changes nothing (pmcp.sh blocks NOAA / UNSUP). Empty for a profile with every package.
UNSUPPORTED = [n for n, _ in JAVA_PACKAGES_ALL if n not in FW["packages"]]
# rg = everything for route guidance in one package: Tomasz's port + his lanes, our VW U-turn lanes, his MU1367
# v1.4.3 distance bar / street name / feed recovery, the maneuver fallbacks, the quiet-route hold (v1.4.3) and, since
# v1.5.0, the VW arrows from Android Auto (rg/build.sh lanes-uturn-asf-m-aa: lanes-uturn-asf-m + rg/lanes/aa.py; with
# connection 3 it reads the AA hook's mailbox /ramdisk/pmcp-aa-rg, CarPlay unchanged) and, since v1.7.0, tomasz-twardzicki's
# MU1367 v1.4.5/v1.4.6 CarPlay guidance fixes (rg/build.sh lanes-uturn-asf-m-aa-r: + rg/lanes/v146.py: reroute with
# CALC_ROUTE, placeholder arrow, U-turn side, Apple Maps names). The rg and rglu of v1.3, v1.4.x's and v1.5.0-v1.6.0's rg
# and the experimental cards' rg-aa are replaced by java-update (recognised by name, history.json "java_renamed").
# Tried and not shipped (docs/en/14-fast-start-audit.md): day/night v2 and the cluster day/night module (no effect on
# Google Maps), AID fast start kf..kf4.
# No two packages replace the same class (checked in main).
# In-car set (chosen in the car, 2026-10-24): 1 clean map (default), 2 clean card, 3 map with showSpeedLimit (the variant the
# unit has had since 2026-10-23, name kept), 4 clean map 40 columns left. All with url-map-hybrid's area.
VARIANTS = ["map-clean", "card-clean", "url-map-hybrid", "map-clean-l40", "map-square", "map-square-fps40"]
# main GEM button: map-square (chosen 2026-10-25) at 40 fps with an IDR every 5 frames, kept after the lag test drive
# (2026-10-31: no lag difference, no artefacts; IDR every 10 gave artefacts). map-square is 30 fps.
START_VARIANT = "map-square-fps40"
# experimental cards: keyframe A/B with our bridge pmcp-most (2026-11-24, user): an IDR every 5 (START_VARIANT), 10 or 30
# frames, switched by the experimental screen (only core.so; a release card's main 2 switches it to its own default)
KF_AB = ["map-square-fps40-kf10", "map-square-fps40-kf30"]
if IS_EXP:
    VARIANTS = VARIANTS + KF_AB

# Pins of the unit's factory files come from the profile: path relative to the backup's appimg folder, "@system/..." to its
# system folder. Android Auto receiver (GAL): aa-on replaces it by the AA wrapper and keeps this factory file as
# carplaymaps/aa/gal.real
STOCK = {k: ((SYSTEM / path[len("@system/"):]) if path.startswith("@system/") else (BACKUP / path), h, size)
         for k, (path, h, size) in FW["stock"].items()}

# Pins of this tool's own build results and of the vendored files, per profile (reviewed after each change; not facts about
# the unit, so they are not in profile.json). key -> (source, sha256, size, path inside payload/)
PAYLOAD_BY_PROFILE = {}
PAYLOAD_BY_PROFILE["MU1161"] = {
    "BRIDGE": (MATHSLS / "profiles" / FW["id"] / FW["cluster"] / "altscreen-most-bridge",
               "fed7dce45f923384fec47861c448b753913f0561ed7e2a279860a5d13f8a44f4", 67835, "common/altscreen-most-bridge"),
    "SUPERVISOR": (MATHSLS / "common/carplay-cluster-supervisor",
                   "8e6ac3a85f04c3faca4850c9f09021bdd628fa1653d718f9c3db3be9d8057569", 56849, "common/carplay-cluster-supervisor"),
    "SEC": (MATHSLS / "common/libcarplay-security-bridge.so",
            "1cef6a3906ae781710a939246eea6c84b40545c04bdd0fd3b0871f195c7808e9", 52642, "common/libcarplay-security-bridge.so"),
    "PAIR_HELPER": (MATHSLS / "common/carplay-pairing-helper",
                    "ffb7d4df6d1e262f175276d43c8c5de7d54a63701dc3adc91d7e1b70ef7f44f7", 62527, "common/carplay-pairing-helper"),
    "PAIR_CORE": (MATHSLS / "common/libCarPlayPairingCore.so",
                  "90c348f99abcc54b5a486c8394d9a5cf0f484a4b68d91b222ffa6e96cc6e3b0d", 881665, "common/libCarPlayPairingCore.so"),
    "WRAPPER": (MATHSLS / "common/dio_manager.wrapper.sh",
                "8c12f6974adf9c8c9eb746e7d033e7fb35a9605e49c31ff2129e8ba938b2633d", 2063, "common/dio_manager.wrapper.sh"),
    # v2 (2026-10-22, review 2): every hook call guarded, RefCheck against the unit's java.* classes
    "JAR_nai": (PROJ / "build/nai-mu1161-v2/NavActiveIgnore.jar",
            "dbd031ecb28a2ec91c4704e133f4e2126cf1fe11498f673bc2e07fc0b1aaa7ab", 13285, "jars/NavActiveIgnore.jar"),
    # nowplaying/build.sh; since v1.7.0 (AA 1.1, A171): + Android Auto title (AndroidAutoTarget hook). A185: + the AA
    # track event log /ramdisk/pmcp-aa-np.log (lengths and flags only; aa-log-save copies it). Earlier
    # cards had pmcp-np.jar (v1.x, 6b638868) and pmcp-np2.jar (v1.7.x, 1f3b0dc0); java-update replaces them by name
    "JAR_np": (PROJ / "build/np-mu1161-aa12/pmcp-np.jar",
               "ab2b27e8fbe695c0212a02802e89a158bbf4853c3b87358facb1ad4d6e8ece53", 26579, "jars/pmcp-np-ab2b27e8.jar"),
    # rg/build.sh <lsd> <dir> lanes-uturn-asf-m-aa-r (RC's rg 70f714fb = v1.6.0's rg 4e32e7f7 plus rg/lanes/v146.py,
    # tomasz-twardzicki MU1367 v1.4.5/v1.4.6) + com.pmcp.kv.KombiView (A166: which view the AID shows,
    # /ramdisk/pmcp-kombi-view.log) + rg/lanes/aa11.py (AA 1.1, A171: AA road name, lanes, destination only while the AID
    # does not show the AA map; KombiView.mapShown() = datapool 1110045). v1.7.x had the same file as
    # pmcp-guidance7.jar (experimental card 9c0c4493, in the car 2026-11-12, A174); earlier ones pmcp-guidance*.jar.
    # A220: + rg/lanes/component.py (route-guidance display component 1 as well as 16, wireless CarPlay); was 308714b2.
    "JAR_rg": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11-wl/pmcp-rg.jar",
               "ad5798b8219a6529e8ebb84a26eddd61c872f20de88ec1ffd8499f0b8ac7947c", 66373, "jars/pmcp-rg-ad5798b8.jar"),
    "JAR_zoom": (PROJ / "build/extras-mu1161-v2/pmcp-zoom.jar",
                 "046f48210dbee3177fbaa2a25f69154b56055f59b074fced1a0202700dd78d7b", 4740, "jars/pmcp-zoom-046f4821.jar"),
    "JAR_dn": (PROJ / "build/extras-mu1161-v2/pmcp-dn.jar",
               "aabe871e87510177a333f1a76d69015f8bdeb994fba4ad1251e1b7f2b5afbd70", 11421, "jars/pmcp-dn-aabe871e.jar"),
    # Optional native-map limit reader, output is enabled separately after confirming the Java set.
    # (amjad-alarori's PR #3; since v1.4.1 without TurnToInfo, which rg owns: rg asks sl for the prefix by name). v1.4.1-v1.7.x
    # had it as pmcp-sl2.jar; the PR's own card's pmcp-sl.jar (sl with TurnToInfo) is replaced by name like any earlier sl
    "JAR_sl": (PROJ / "build/sl-mu1161/pmcp-sl.jar",
               "37b5d9488b818e4a4de58dc9541b6618de364e5a46d81439c1f3206762e5249f", 16527, "jars/pmcp-sl-37b5d948.jar"),
    # Optional settings page (ui/build.sh): the factory AbstractViewHandler with five guarded hooks + com.pmcp.ui. Its
    # speed-limit row writes the same mode file as speedlimit-mode, under the same lock and rules.
    "JAR_ui": (PROJ / "build/ui-mu1161/pmcp-ui.jar",
               "5fea8d94bdb45b6556e3a7eec660326a88aa485b4539408f75796e4d814bc395", 29485, "jars/pmcp-ui-5fea8d94.jar"),
    # Tomasz's driver patch + our log gate: his RGI receive log only with /dev/shmem/pmcp-rgi-debug (rg/driver/)
    "RG_DRIVER": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11-wl/ipod-drvr-iap2-gated.so",
                  "519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3", 743272, "rg/ipod-drvr-iap2.so"),
    "RG_CFG": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11-wl/iap2.cfg",
               "c61407d9c6cd0d2529afedad0c9a120d5da5a504739e273bbb3dbea1e0b9b491", 6079, "rg/iap2.cfg"),
    # rgi-observer pmcp-r1 (rg/reader/, prebuilt in the repository): a stuck driver read costs one invalid record, not the reader
    "RG_READER": (PROJ / "rg/reader/prebuilt/rgi-observer",
                  "3166df9b91119475f93043ac8c150e2641732e602161839a137a1907d4ef11df", 13552, "rg/rgi-observer"),
}
# Android Auto 0.1 (aa/README.md), one mode "gamma": MacsInSpace's gal hook (pinned commit, no SD card paths,
# aa/hook/build.sh gamma: Google Maps manoeuvres -> rg mailbox), our feeder (aa/feeder, v10: start sync + pacing without bursts) and the
# gal wrapper. Built into build/ by those scripts (docker, QNX 6.5 toolchain).
# The three QNX binaries are prebuilt in aa/prebuilt/ (built with Docker, see aa/prebuilt/README.md), so install.sh
# needs no QNX toolchain: hook g2 (A-AA24), libdmdt_flush.so (unchanged since AA 1), feeder v10 (A-AA33).
PAYLOAD_BY_PROFILE["MU1161"].update({
    "AA_WRAPPER": (PROJ / "aa/unit/gal.wrapper.sh", "57b63037a7d82d45f47773ec76e99ad659490f6d29d540f20de90930f0d65137", 3259, "aa/gal.wrapper.sh"),
    # v1.7.0: hook g2 + raw dump of the navigation messages (/ramdisk/pmcp-aa-rg-raw.txt, A166) + road name, lanes and
    # destination into the rg mailbox (AA 1.1, A171); v1.7.0/v1.7.1 had cbf2e388 (an earlier set, "old"). Since A185: file writes
    # outside the rg mutex, the raw dump no longer rewrites latest.bin, 0x8006 dedupe over the whole message (review A176)
    "AA_HOOK": (PROJ / "aa/prebuilt/libgal_hook.so", "c92a4c3ef81ad14ed92ade628567f720f6c4adf6ddf410f15aeeec81ffc61a5e", 143597, "aa/libgal_hook.so"),
    "AA_DMDT_FLUSH": (PROJ / "aa/prebuilt/libdmdt_flush.so", "4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f", 5328, "aa/libdmdt_flush.so"),
    # AA 1.0 (A153): feeder v14 = v13 (pmcp's own MOST writer, direct) + only direct|ring taken from PMCP_AA_OUTPUT
    # v1.7.0: feeder v15 = v14 + MOST taken back when the factory encoder grabs isoTX2 early after boot (A166; in the car
    # with cards b542b2d4 and 9c0c4493)
    "AA_FEEDER": (PROJ / "aa/prebuilt/aa-most-feeder", "48d6fc5670d2fd64453ccf54be0c789789ca995a02f1d41fbebab312406c3155", 70840, "aa/aa-most-feeder"),
    "AA_HOOK_CONF": (PROJ / "aa/unit/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839, "aa/gal-hook.conf"),
    "AA_MODE": (PROJ / "aa/unit/feeder-gamma.conf", "08daec96ae34f93557792ef2289e968b049f45c1b1f30802095302eae1a40a47", 1566, "aa/feeder.conf"),
})
# pmcp-most (bridge/, docs 23-wlasny-most.md): our build of the MOST bridge, every MU1161 card since v2.0 (A227), next to
# mathsls's BRIDGE (pmcp.sh bridge pmcp-most|mathsls, GEM diagnostics; default pmcp-most). Prebuilt and pinned in
# bridge/prebuilt (README there), so install.sh needs no QNX toolchain. The ONE line to change after a rebuild:
# bridge/build.sh OUTDIR prints the size and sha256; copy the file to bridge/prebuilt.
# Since 2026-11-16 (A203): stage 2 (PMCP_MOST_LIB=1, src/pmcp_most_lib.c on the AA MOST output library); stage 1c was 8c104a06.
# 2026-11-18: stage 2 with thread priority 14 and the rotated event file (was 175eee71).
PMCP_MOST_PIN = ("bridge/prebuilt/altscreen-most-bridge", "70f18b161237ebf401d6aa418bd8c4d220a8f7870afb443e37134d7081ef0b12", 39156)
# MOST supervisor v1 (stage 5, bridge/src/pmcp_most_sup.c; PMCP_MOST_SUP=1 bridge/build.sh OUTDIR, then bridge/prebuilt):
# every MU1161 card, it goes with pmcp-most (bridge pmcp-most|mathsls sets the matching supervisor); experimental cards
# also have pmcp.sh most-sup pmcp|mathsls on its own
PMCP_MOST_SUP_PIN = ("bridge/prebuilt/pmcp-most-sup", "fbc73f076a88b5322e2c7464be915ee0717c7818f4b22ea8e5ad6dc685f8b4e6", 23396)
if PROFILE_ID == "MU1161":
    PAYLOAD_BY_PROFILE["MU1161"].update({
        "PMCP_MOST": (PROJ / PMCP_MOST_PIN[0], PMCP_MOST_PIN[1], PMCP_MOST_PIN[2], "pmcp-most/altscreen-most-bridge"),
        "PMCP_MOST_SUP": (PROJ / PMCP_MOST_SUP_PIN[0], PMCP_MOST_SUP_PIN[1], PMCP_MOST_SUP_PIN[2], "pmcp-most/pmcp-most-sup"),
        # mathsls's WRAPPER + the contract owner block (src=wired kind=proxy, wired.session): live with pmcp-most only
        "PMCP_MOST_WRAPPER": (PROJ / "installer/pmcp-most/dio_manager.wrapper.sh",
                              "52031e8435dfed0329cb8d6fd83b6de184b0bee07529fa370c321c3e2d7d4859", 4301,
                              "pmcp-most/dio_manager.wrapper.sh"),
    })
if IS_EXP and PROFILE_ID == "MU1161":
    # the WL HMI hook (Java package wl, experimental only; see WL_JAR_PIN)
    PAYLOAD_BY_PROFILE["MU1161"]["JAR_wl"] = (PROJ / WL_JAR_PIN[0], WL_JAR_PIN[1], WL_JAR_PIN[2],
                                             "jars/pmcp-wl-%s.jar" % WL_JAR_PIN[1][:8])
# Experimental AA set (AAX_FEEDER: an experimental feeder next to the stable one, pmcp.sh aa-on-exp, set id
# gamma-<hook>-<that feeder>-<hook settings>): none since AA 1.0, whose stable set has the v13/v14 feeder. pmcp.sh keeps
# the mechanism for the next experimental feeder: add the key here again (experimental builds only, own feeder file).
# Earlier cards' Java packages and AA sets need no list (A188): pmcp.sh recognises an earlier version of one of this
# card's packages by its name (java_parts) and an earlier AA set by our wrapper, the verified factory gal copy and a
# well-formed AA_BOOT (aa_state "old"). Only renamed packages are listed, by name: history.json "java_renamed".
JAVA_RENAMED = sorted(HIST["java_renamed"].items())

# Earlier pmcp route guidance files that rg-update may replace in place (pmcp.sh RG_KNOWN): (kind, sha256, sha1, size), only their
# hashes go to the card, so no earlier build is needed here. List and notes: history.json "rg_known".
RG_KNOWN = [(e["kind"], e["sha256"], e["sha1"], e["size"]) for e in HIST["rg_known"]]
# Earlier pmcp MOST supervisor / bridge files (pmcp.sh MOST_KNOWN, A247): history.json "most_known".
MOST_KNOWN = [(e["kind"], e["sha256"], e["sha1"], e["size"]) for e in HIST.get("most_known", [])]
# Earlier lsd.sh files of ours (factory lsd.sh + an earlier block) that java-update replaces in place (pmcp.sh LSD_KNOWN,
# history.json "lsd_known"): (sha256, sha1, size)
LSD_KNOWN = [(e["sha256"], e["sha1"], e["size"]) for e in HIST["lsd_known"]]
if PROFILE_ID not in PAYLOAD_BY_PROFILE:
    sys.exit("no PAYLOAD pins for profile %s in build_sd.py (PAYLOAD_BY_PROFILE)" % PROFILE_ID)
PAYLOAD = {k: v for k, v in PAYLOAD_BY_PROFILE[PROFILE_ID].items()
           if not (k.startswith("JAR_") and k[4:] not in FW["packages"])
           and not (k.startswith("AA_") and "aa" not in FW["packages"])
           and not (k.startswith("RG_") and "rg" not in FW["packages"])}
HAS_AA = "aa" in FW["packages"]
if FW["lsd_sh_states"] != ["stock"]:
    sys.exit("profile %s: lsd_sh_states %r is not supported by this installer yet" % (PROFILE_ID, FW["lsd_sh_states"]))

def render_template(tpl):
    """The profile-dependent parts of template/pmcp.sh.in. Lines "#@@NAME_BEGIN" ... "#@@NAME_END" are dropped with their
    content unless the profile has the feature (AA / NOAA: with / without the Android Auto package; UNSUP: some package of
    the profile is missing; EXP: experimental builds only), and the marker lines themselves are always dropped. For a profile with every package the result
    is the text the template had without these blocks."""
    import re
    on = {"AA": HAS_AA, "NOAA": not HAS_AA, "UNSUP": bool(UNSUPPORTED), "EXP": IS_EXP}
    out, skip = [], 0
    for line in tpl.split("\n"):
        m = re.match(r"^#@@([A-Z]+)_(BEGIN|END)$", line)
        if not m:
            if not skip:
                out.append(line)
            continue
        if m.group(1) not in on:
            sys.exit("template: unknown block %s" % m.group(1))
        if m.group(2) == "BEGIN":
            if skip or "open" in on:
                sys.exit("template: nested block")
            skip = 0 if on[m.group(1)] else 1
            on["open"] = m.group(1)
        else:
            if on.pop("open", None) != m.group(1):
                sys.exit("template: block %s closed wrongly" % m.group(1))
            skip = 0
    if "open" in on:
        sys.exit("template: block %s not closed" % on["open"])
    return "\n".join(out)


for name in VARIANTS:
    PAYLOAD["CORE_" + name] = (TUNING / name / "core.so", None, 75099, "core/%s/core.so" % name)

TUNING_SHA = {
    "card-narrow": "3d6b823a92a71db7a79be6e382b754cb09959e71fb1ca6092089c0c4560c9229",
    "card-wide": "d58965ee8f932e905d5c888b7cbdab04cac43a9eb8d92ef6ff629dcfba66bedf",
    "card-narrow-hi": "a1b856b42e5268d810a56ec457d8e8a32370e321dbf34b017396c97f968c5d36",
    "map-diasdio": "4e2777b2d06fec693235828ce31259230e33992a931bb6b0369545e8f9ee230f",
    "map-crop340": "281a0c989d317d66e3243c1969c4c863518ade7bf5e6595121ebef8b93afdac2",
    "map-kf30": "6b581e5bbfa16085f94f36c9bebf395d3fb5ba113098efd9e81b91c39ea91d66",
    # package C (long URLs, build_core.py 2026-10-21)
    "url-card-noeta": "e5c2f37dcf631997bb95e8f3108d3d05e9ddf397225ab3068eff5993263f3324",
    "url-card-noeta-left": "ed63c05c5fa0f6e8fefc140d9257b34aeeb028da7bb4cb06c7ee9a1c36aae5f1",
    "url-card-noeta-right": "55cf67fcd3bbf853c1862b82a26d4b7e959bfc3077f43c6222eeb11c5bd25dcb",
    "url-card-noeta-speed": "0119ed2ae2d4dd900896811ef93caa24ba047c68c7f8dc0e26c08239c7401a64",
    "url-map-speed": "e12eb877cbfcdaea8c5dc7cc21a8fe32c122b07a4c6192629a5b167b97b52393",
    # hybrid mathsls + Tomasz (Tomasz width, 240x144 mm, card below the VW bar), build_core.py 2026-10-22
    "url-card-hybrid": "22afe97e219747969301157d3736c5a60e77418975b0fea75d98648c52c6039e",
    # same card position, safe-area bottom at row 460 (h 352 above every tested blank-card value), review 3 HIGH-1
    "url-card-hybrid-tall": "e6b6dac37b0098f1ab6cf4e48bae7d5ef915c53ed1d056458151127fa8c4a07a",
    # map without card, url-card-hybrid area / bottom row 364 (in-car 2026-10-23: no card in Apple nor Google with /map)
    "url-map-hybrid": "d7236f3065509a9cc3b79b48cc727575a71486e040d33ead7f2eecb0d89e3a3e",
    "url-map-hybrid-hi": "43a9e11775e6508b3580ef9e0a80428a461bbc0b275b1d2af763380722e289c8",
    # url-map-hybrid moved left by 80 / 160 columns (Google marker right of the map-window centre, 2026-10-24)
    "url-map-hybrid-l80": "f8f65a35e1e39082cd6a22dfdf2eb51d7600e4e5cf7addb7a76f52691360c6d8",
    "url-map-hybrid-l160": "a684edd2036c7dd9780ff3ed80822f69d5f6cd41c21993266abbb32489beef7d",
    # final set: clean map / clean card / clean map 40 columns left (url-map-hybrid area), 2026-10-24
    "map-clean": "c5f4870427d6d24bf78908497beb27e4e881d64374b58c564e7395d809efe2f4",
    "card-clean": "a4054ff9f1e7175ef9365e9f51990eb4ed3c58121ccfe4a6651e039e362552ac",
    "map-clean-l40": "0dbbebb0e47826fa39f9a1c28624ee6892b275f4a99865c091e39d43e79578ac",
    # mathsls's area 240/60/320/340 (closer to square) with the clean map URL, 2026-10-24
    "map-square": "f4d83fd2e33e20513e5856da554716e1b6a055a88bf69fe928beb52fadbe8028",
    # map-square latency A/B: maxFPS 40 (base value, as mathsls) / 20 / forced IDR every 10 frames, 2026-10-25
    "map-square-fps40": "f826ff0ab78ca595ef7e0c836ba183ae28c7cb7309f2ef6966d3a0c738a99050",
    # keyframe A/B with pmcp-most (2026-11-24): fps40 with an IDR every 30 frames (only 0x4370/0x452c differ, 5 -> 30)
    "map-square-fps40-kf30": "825178d0114b4791a8bfcbe915e8d87f7a44687ca17b3ba15a1ce89c0e98b4ec",
    "map-square-fps40-kf10": "88aa23c23e0d1ec93ded4c074e8c74681f074adc56ffdbedcb5c59ef833213f9",
    "map-square-fps20": "7d3c6009f8d2613603e70d80d10ed2fb6df2744cef77a068f74f769ee091a93d",
    "map-square-kf10": "a14f5a0b0d7ebe9a7e392549120d31634bf717839325faf36a89c8f8d81e24b5",
}

# Java stage (B and later): one fixed block in lsd.sh, before J9 starts. Which JARs load is read at boot from
# /mnt/app/carplaymaps/HMI_BOOT ("set-id jar jar ...", written by pmcp.sh with a single mv, so the id and the list
# always belong together). Every new set gets one trial boot (marker on /mnt/persist/pmcp); it becomes permanent only
# when the user presses "Potwierdz" in GEM during that boot (pmcp.sh java-confirm checks last-boot). There is no
# automatic confirmation: a running J9 does not prove a working HMI (review 1, findings 2 and 4).
# Never in update mode (RUN_MODE=swdl), so the rescue card always meets a factory HMI (review 1, finding 3).
# Any missing tool or unwritable marker means a factory boot. /mnt/persist/pmcp/DISABLED (rescue card) disables it.
LSD_PRE = r"""# >>> pmcp: CarPlay AID mod. Removing this block gives factory behaviour.
# MOST supervisor (stage 5, docs 23): the factory encoder's MOST path as a link in the process manager's namespace, made
# at every start (also update mode and DISABLED), before the MOST driver exists. Unused while displaymanager.json has the
# factory path; with "dm-path pmcp" (experimental cards) the encoder opens the MOST channel through this link only.
ln -Ps /dev/mlb/isoTX2 /dev/pmcp-isoTX2 2>/dev/null
PMCP_DIR=/mnt/app/carplaymaps
PMCP_P=/mnt/persist/pmcp
PMCP_JARS=""
PMCP_SET=""
PMCP_LIST=""
PMCP_USE=no
rm -f $PMCP_P/last-boot 2>/dev/null
if [ "${RUN_MODE}" != swdl ] && [ -s $PMCP_DIR/HMI_BOOT ] && [ ! -e $PMCP_P/DISABLED ] && mkdir -p $PMCP_P 2>/dev/null; then
    read PMCP_SET PMCP_LIST < $PMCP_DIR/HMI_BOOT
    if [ -n "$PMCP_SET" ] && [ -n "$PMCP_LIST" ]; then
        if [ -e "$PMCP_P/ok.$PMCP_SET" ]; then
            PMCP_USE=yes
        elif [ ! -e "$PMCP_P/trial.$PMCP_SET" ] && touch "$PMCP_P/trial.$PMCP_SET" 2>/dev/null && [ -e "$PMCP_P/trial.$PMCP_SET" ]; then
            PMCP_USE=trial
        fi
    fi
    if [ $PMCP_USE != no ]; then
        for PMCP_J in $PMCP_LIST; do
            PMCP_JARS="$PMCP_JARS${PMCP_JARS:+:}$BASE_DIR/lsd/jars/$PMCP_J"
        done
    fi
    echo "set=$PMCP_SET use=$PMCP_USE" > $PMCP_P/last-boot 2>/dev/null
    echo "boot set=$PMCP_SET use=$PMCP_USE jars=${PMCP_JARS:-none}" >> $PMCP_P/boot.log 2>/dev/null
fi
[ -n "$PMCP_JARS" ] && BOOTCLASSPATH="$BOOTCLASSPATH -Xbootclasspath/p:$PMCP_JARS"
# Route guidance reader (package E, Tomasz's rgi-observer): only with the patched driver installed by pmcp and a
# Java set loading; in the background so it can never delay the HMI start.
if [ -n "$PMCP_JARS" ] && [ -x $PMCP_DIR/rg/rgi-observer ] && [ -e $PMCP_DIR/rg/SYSTEM_ON ]; then
    ( $PMCP_DIR/rg/rgi-observer start-live /dev/ipod0/rgi-events /ramdisk/carplay-route-guidance >/dev/null 2>&1 ) &
fi
# MOST supervisor (A247): also started here, so CarPlay over Wi-Fi without the cable gets the map (it makes the ring the
# Wi-Fi producer waits for; before, only the dio_manager wrapper started it, i.e. the cable). Our verified copy runs only
# when the active supervisor is the same program, else it exits. Never in update mode or with DISABLED; in the background.
if [ "${RUN_MODE}" != swdl ] && [ ! -e $PMCP_P/DISABLED ] && [ -x $PMCP_DIR/bridge/pmcp-most-sup ]; then
    ( unset LD_PRELOAD; $PMCP_DIR/bridge/pmcp-most-sup --boot >/dev/null 2>&1 ) &
fi
# <<< pmcp"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def template_for_id(tpl):
    """The template text that goes into the build id: on a release build without the EXP blocks (markers included), so
    experimental-only code never changes a release card's id or bytes."""
    if IS_EXP:
        return tpl
    out, skip = [], False
    for line in tpl.split("\n"):
        if line == "#@@EXP_BEGIN":
            skip = True
        elif line == "#@@EXP_END":
            skip = False
        elif not skip:
            out.append(line)
    return "\n".join(out)


def read_pinned(path, want_sha, want_size, label=""):
    data = pathlib.Path(path).read_bytes()
    if len(data) != want_size or (want_sha and sha(data) != want_sha):
        sys.exit("input mismatch: %s %s size=%d sha=%s" % (label, path, len(data), sha(data)))
    return data


DM_FACTORY_DEVICE = b'"device" : "/dev/mlb/isoTX2",'
DM_PMCP_DEVICE = b'"device" : "/dev/pmcp-isoTX2",'


def patch_dm_json(stock):
    """displaymanager.json with the MOST encoder's device on our link; nothing else changes."""
    if stock.count(b"isoTX2") != 1 or stock.count(DM_FACTORY_DEVICE) != 1 or b"pmcp" in stock:
        sys.exit("displaymanager.json structure unexpected (MOST encoder device)")
    out = stock.replace(DM_FACTORY_DEVICE, DM_PMCP_DEVICE)
    assert len(out) == len(stock) + 1
    return out


def patch_lsd(stock):
    """Insert LSD_PRE before the 'export LD_PRELOAD' that precedes J9; nothing else changes."""
    text = stock.decode("ascii")
    lines = text.split("\n")
    j9 = [i for i, l in enumerate(lines) if l.lstrip().startswith("$J9 ")]
    if len(j9) != 1 or "-Xbootclasspath/p:" in text or "pmcp" in text:
        sys.exit("lsd.sh structure unexpected: J9 lines %r" % j9)
    j = j9[0]
    expect = ['export LD_PRELOAD=/lib/libecpp-ne.so.4:/mnt/app/root/lib-target/libcgdrv.so', 'info "lsd.sh J9 started" ',
              '$J9 $VMOPTIONS $BOOTCLASSPATH -jxe $HMI_JXE &', 'unset LD_PRELOAD']
    if lines[j - 2:j + 2] != expect:
        sys.exit("lsd.sh lines around J9 differ from the %s factory file: %r" % (PROFILE_ID, lines[j - 2:j + 2]))
    out = lines[:j - 2] + LSD_PRE.split("\n") + lines[j - 2:]
    return "\n".join(out).encode("ascii")


MENU_SCRIPT = """#!/bin/ksh
# pmcp GEM button: %(label)s (generated by build_sd.py)
if [ -f /net/rcc/dev/shmem/backup.mib ] || [ -f /net/rcc/dev/shmem/reboot.mib ] || [ -f /net/rcc/dev/shmem/flash.mib ]; then
    echo "M.I.B. is busy with another task, try again later."
    exit 0
fi
trap '' 2
echo "pmcp: %(label)s"
echo "Do not press Back and do not remove the SD card until PMCP_..._OK or PMCP_FAIL is shown."
/bin/ksh /net/mmx/fs/sda0/pmcp/pmcp.sh %(args)s
trap 2
exit 0
"""


# the diagnostics button runs bin/diag.sh directly: it must work even when pmcp.sh stops at its self test
DIAG_SCRIPT = """#!/bin/ksh
# pmcp GEM button: Diagnostics (generated by build_sd.py)
trap '' 2
/bin/ksh /net/mmx/fs/sda0/pmcp/bin/diag.sh
trap 2
exit 0
"""

# start timeline, read-only like the diagnostics, runs bin/timeline.sh directly
TIMELINE = "timeline"
TIMELINE_SCRIPT = """#!/bin/ksh
# pmcp GEM button: start timeline (generated by build_sd.py)
trap '' 2
/bin/ksh /net/mmx/fs/sda0/pmcp/bin/timeline.sh
trap 2
exit 0
"""

# read-only navigation diagnostics: navigation start markers in /mnt/persist, processes, system log
NAVDIAG = "navdiag"
NAVDIAG_SCRIPT = """#!/bin/ksh
# pmcp GEM button: navigation diagnostics (generated by build_sd.py)
trap '' 2
/bin/ksh /net/mmx/fs/sda0/pmcp/bin/navdiag.sh
trap 2
exit 0
"""


# last route guidance messages from the iPhone and the VW arrow they give, read-only like the diagnostics
RGLAST = "rglast"
RGLAST_SCRIPT = """#!/bin/ksh
# pmcp GEM button: route guidance, last maneuvers (generated by build_sd.py)
trap '' 2
/bin/ksh /net/mmx/fs/sda0/pmcp/bin/rglast.sh
trap 2
exit 0
"""

# Main menu 4 "Install additional features": the same pmcp.sh actions as the advanced buttons, run one after another, so all
# Java packages land in one set (one trial boot, one Confirm). Stops at the first failure; "already on" counts as done.
FEATURES_SCRIPT = """#!/bin/ksh
# pmcp GEM button: %(label)s (generated by build_sd.py)
if [ -f /net/rcc/dev/shmem/backup.mib ] || [ -f /net/rcc/dev/shmem/reboot.mib ] || [ -f /net/rcc/dev/shmem/flash.mib ]; then
    echo "M.I.B. is busy with another task, try again later."
    exit 0
fi
trap '' 2
echo "pmcp: %(label)s"
%(note)secho "Do not press Back and do not remove the SD card until PMCP_FEATURES_ON_OK or PMCP_FAIL is shown."
PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh
NEW=0
for A in %(actions)s; do
    echo "- ${A%%%%_*} ${A#*_}"
    OUT=`/bin/ksh $PMCP ${A%%%%_*} ${A#*_} 2>&1`
    echo "$OUT" | while read L; do case "$L" in PMCP_WARN*|PMCP_FAIL=*_ALREADY_*) ;; PMCP_*) echo "  $L" ;; esac; done
    case "$OUT" in
        *PMCP_FAIL=*_ALREADY_*) echo "  (nothing to do, skipped)" ;;
        *PMCP_FAIL=*PRESS_2*) echo "PMCP_FAIL=FEATURES_STOPPED_AT_$A"
                     echo "The CarPlay map is missing or its files are mixed: main menu, 2. Install CarPlay first, then 4 again."
                     trap 2; exit 0 ;;
        *PMCP_FAIL=*PRESS_3*|*PMCP_FAIL=*AA_REMOVE_FIRST*) echo "PMCP_FAIL=FEATURES_STOPPED_AT_$A"
                     echo "Android Auto files of a version this card does not support: main menu, 3. Install Android Auto"
                     echo "first (it replaces them), then 4 again. CarPlay and the rest stay as they are."
                     trap 2; exit 0 ;;
        *PMCP_FAIL*) echo "PMCP_FAIL=FEATURES_STOPPED_AT_$A"
                     echo "The steps before this one were done. Take a photo, then use 7. Status, or 8. Remove everything."
                     trap 2; exit 0 ;;
        *PMCP_*_OK*) NEW=1 ;;
        *) echo "PMCP_FAIL=FEATURES_NO_RESULT_FROM_$A"; trap 2; exit 0 ;;
    esac
done
if [ $NEW = 1 ]; then
    echo "PMCP_FEATURES_ON_OK"
    echo "Restart the unit (hold the volume knob ~10 s). That first start is a TRIAL."
    echo "If the map and CarPlay work: open this menu again and press 5. Confirm, in that same start."
    echo "Without Confirm the next start is the factory one again."
else
    echo "PMCP_FEATURES_ON_OK (everything was already on, nothing changed)"
fi
trap 2
exit 0
"""

# Main menu 10 "Reinstall" (A188, user 2026-11-15): remove everything (8), then put back this card's versions of what was
# on: the map layout, the route guidance system, the same Java packages, Android Auto with its output. The plan is read
# (read-only) before restore and kept in this script's memory. Each step is one pmcp.sh action, so an interruption leaves
# the unit factory or with the steps done so far, both states 2, 3 and 4 handle.
REINSTALL = "reinstall"
REINSTALL_SCRIPT = """#!/bin/ksh
# pmcp GEM button: %(label)s (generated by build_sd.py)
if [ -f /net/rcc/dev/shmem/backup.mib ] || [ -f /net/rcc/dev/shmem/reboot.mib ] || [ -f /net/rcc/dev/shmem/flash.mib ]; then
    echo "M.I.B. is busy with another task, try again later."
    exit 0
fi
trap '' 2
echo "pmcp: %(label)s"
echo "Do not press Back and do not remove the SD card until PMCP_REINSTALL_OK or PMCP_FAIL is shown."
PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh
PLAN=`/bin/ksh $PMCP reinstall-plan %(variant)s 2>&1`
echo "$PLAN" | while read L; do case "$L" in PMCP_PLAN*|PMCP_NOTE*|PMCP_FAIL*) echo "$L" ;; esac; done
case "$PLAN" in
    *PMCP_REINSTALL_PLAN_OK*) ;;
    *) echo "PMCP_FAIL=REINSTALL_NO_PLAN (nothing was changed)"; trap 2; exit 0 ;;
esac
echo "- restore"
OUT=`/bin/ksh $PMCP restore 2>&1`
echo "$OUT" | while read L; do case "$L" in PMCP_WARN*) ;; PMCP_*) echo "  $L" ;; esac; done
case "$OUT" in
    *PMCP_RESTORE_OK*) ;;
    *) echo "PMCP_FAIL=REINSTALL_STOPPED_AT_restore"
       echo "Remove everything did not finish: take a photo, then 7. Status and 8. Remove everything."
       trap 2; exit 0 ;;
esac
STEPS=`echo "$PLAN" | sed -n 's/^PMCP_PLAN //p'`
STOP=0
while read A B; do
    [ -n "$A" ] || continue
    echo "- $A $B"
    OUT=`/bin/ksh $PMCP $A $B 2>&1 </dev/null`
    echo "$OUT" | while read L; do case "$L" in PMCP_WARN*|PMCP_FAIL=*_ALREADY_*) ;; PMCP_*) echo "  $L" ;; esac; done
    case "$OUT" in
        *PMCP_FAIL=*_ALREADY_*) echo "  (nothing to do, skipped)" ;;
        *PMCP_FAIL*) echo "PMCP_FAIL=REINSTALL_STOPPED_AT_${A}_$B"
                     echo "The unit has the factory files plus the steps before this one. Take a photo; then 2, 3 or 4."
                     STOP=1; break ;;
        *PMCP_*_OK*) ;;
        *) echo "PMCP_FAIL=REINSTALL_NO_RESULT_FROM_${A}_$B"; STOP=1; break ;;
    esac
done <<EOF
$STEPS
EOF
[ $STOP = 0 ] || { trap 2; exit 0; }
echo "PMCP_REINSTALL_OK"
echo "Restart the unit (hold the volume knob ~10 s). That first start is a TRIAL."
echo "If everything works: open this menu again and press 5. Confirm, in that same start."
echo "A speed-limit mode (if one was on) is set again after the Confirm."
trap 2
exit 0
"""


def menu_entries():
    # (file name, pmcp arguments, GEM label). ASCII only: GEM fonts and the esd parser are not tested with other letters.
    # Main screen pmcp_stream_map_aid: one button per part, stable versions only; each replaces a version this card
    # does not support. Everything else is under pmcp_advanced (diagnostics, features, aa_advanced; experimental cards:
    # experimental).
    # Screen names diagnostics and features, one line per screen on pmcp_advanced (A199, user 2026-11-15).
    # Menu cleanup (A198-AA, user 2026-11-15): no map layout screen (the layouts stay in the repo and on the card: 2 and
    # 10 use them), no RG/Java update buttons (main 4 and 10 do it), on/off of single parts on their own screen.
    top = [("verify", "verify", "1. Check card and unit (read-only)"),
           ("map-install", "map-install " + START_VARIANT, "2. Install CarPlay: the map on the AID (also repairs or updates it)"),
           ("aa-install", "aa-install", "3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)"),
           ("features-on", FEATURES, "4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)"),
           ("confirm", "confirm", "5. Confirm: everything works (in the first start after 3 or 4)"),
           ("retry", "retry", "6. Try again: the next start is a new trial"),
           ("status", "status", "7. Status (read-only)"),
           ("restore", "restore", "8. Remove everything (back to factory files)"),
           # the one button that deletes what pmcp saved for the log card, CarPlay and Android Auto alike (user, 2026-11-13)
           ("log-clear", "log-clear", "9. Delete saved logs: CarPlay and Android Auto (after the log card copied them)"),
           # A188 (user 2026-11-15): one button for "start again" instead of updating an install this card does not know
           ("reinstall", REINSTALL, "10. Reinstall: remove everything, then this card's versions of what was on")]
    feat = [("diag", None, "Diagnostics (read-only, photograph the screen)"),
            ("timeline", TIMELINE, "Start timeline: seconds from unit start to CarPlay, MOST, navigation (read-only)"),
            ("rglast", RGLAST, "RG last maneuver: what the iPhone sent and which VW arrow it gives (read-only)"),
            ("navdiag", NAVDIAG, "Navigation diagnostics: why the VW navigation does not start (read-only)"),
            ("cp-log-save", "cp-log-save", "CP save log: copy this start's CarPlay log to the unit (for the log card)"),
            # package sl (On sl, then 5. Confirm), then one of these; the mode is kept across starts
            # the speed-limit mode is set on the unit: App-Connect > Settings > AID navigation configuration (package ui); pmcp.sh
            # speedlimit-mode stays for the tests and the command line
            ("speedlimit-status", "speedlimit-status", "Speed limit status: mode and native VW limit data (read-only)"),
            ]
    feat = [e for e in feat if not (e[0] == "speedlimit-status" and "sl" not in FW["packages"])]
    # v2.0 (A227): the MOST bridge on every card with pmcp-most; each switch also sets the matching MOST supervisor; no
    # card confirm, no trial (the supervisor starts the chosen bridge at the next phone connection)
    if "PMCP_MOST" in PAYLOAD:
        feat += [("bridge-pmcp-most", "bridge pmcp-most", "Bridge: pmcp-most (default, own MOST bridge; from the next phone connection)"),
                 ("bridge-mathsls", "bridge mathsls", "Bridge: mathsls (fallback; from the next phone connection)"),
                 ("bridge-status", "bridge-status", "Bridge status (read-only)")]
    onoff = ([("rg-system-on", "rg-system-on", "Route guidance system on (iAP2 driver, iap2.cfg, reader)"),
              ("rg-system-off", "rg-system-off", "Route guidance system off (factory iAP2 driver and iap2.cfg)")]
             if "rg" in FW["packages"] else []) + \
            [("java-on-" + n, "java-on " + n, "On " + label) for n, label in JAVA_PACKAGES_ALL] + \
            [("java-off-" + n, "java-off " + n, "Off " + label) for n, label in JAVA_PACKAGES_ALL]
    return top, feat, onoff, AA_MENU, EXP_MENU


# Android Auto details, screen aa_advanced. The stable set is installed by main menu 3 (aa-install); the main menu's
# 5 and 6 confirm / try again Android Auto too. Release cards keep the AA logs and status (support).
AA_MENU = [("aa-confirm", "aa-confirm", "AA Confirm: AA works (only in the start of the AA trial; 5 does the same)"),
           # AA 1.0: the output, no trial (also on the settings page); direct is the set's default
           ("aa-output-direct", "aa-output direct", "AA output: pmcp MOST writer (default, from the next connection)"),
           ("aa-output-ring", "aa-output ring", "AA output: CarPlay bridge (fallback, from the next connection)"),
           ("aa-retry", "aa-retry", "AA Try again: the next AA connection is a new trial"),
           ("aa-status", "aa-status", "AA status and stream analysis (read-only)"),
           ("aa-log-save", "aa-log-save", "AA save log: copy this start's AA log to the unit (for the log card)"),
           ("aa-remove", "aa-remove", "AA remove (factory Android Auto back)")]
# experimental builds only (empty on release cards): screen experimental, the MOST supervisor on its own (the bridge
# switch is on diagnostics on every card since v2.0), the VW encoder path, then the AA tests
EXP_MENU = [] if not IS_EXP else [
    # keyframe A/B (docs 28): core.so only, a full unit reboot after each; a release card's main 2 puts its default back
    ("map-kf5", "switch " + START_VARIANT, "Map keyframe A/B: IDR every 5 frames (default; reboot after)"),
    ("map-kf10", "switch map-square-fps40-kf10", "Map keyframe A/B: IDR every 10 frames (test; reboot after)"),
    ("map-kf30", "switch map-square-fps40-kf30", "Map keyframe A/B: IDR every 30 frames (test; reboot after)")] + ([
    # MOST supervisor v1 (stage 5) on its own; a Bridge button sets the matching one again
    ("most-sup-pmcp", "most-sup pmcp", "MOST supervisor: pmcp (needs Bridge pmcp-most; from the next phone connection)"),
    ("most-sup-mathsls", "most-sup mathsls", "MOST supervisor: mathsls (test; from the next phone connection)")]
    if "PMCP_MOST" in PAYLOAD else []) + [
    # MOST supervisor stage 5 (docs 23, A218): the factory VW encoder's MOST path. dm-path from the next unit start;
    # dm-link only for this start (the lsd.sh block makes the link again at every start); dm-diag read-only
    ("dm-diag", "dm-diag", "VW encoder: MOST path, link, its log lines and open files (read-only, saved for the log card)"),
    ("dm-path-pmcp", "dm-path pmcp", "VW encoder: MOST through our link (from the next unit start)"),
    ("dm-path-factory", "dm-path factory", "VW encoder: factory MOST path (default, from the next unit start)"),
    ("dm-link-drop", "dm-link drop", "VW encoder link: remove (this start only; test)"),
    ("dm-link-make", "dm-link make", "VW encoder link: make again (this start only)"),
    ("aa-capture-60", "aa-capture 60", "AA record: first 60 s of the phone video at each connection (for the log card)"),
    ("aa-capture-off", "aa-capture off", "AA record: off"),
    # A203-AA reverse-gear test: the AA hook re-grants the cluster after a main-screen focus change (aa-extra.conf)
    ("aa-regrant-on", "aa-regrant on", "AA cluster re-grant after the main screen changes (reverse camera test): on"),
    ("aa-regrant-off", "aa-regrant off", "AA cluster re-grant: off (default)"),
    # A215-AA: feeder v17 "nothing changed" pictures while the phone is silent (aa-extra.conf)
    ("aa-keepalive-on", "aa-keepalive on", "AA map keep-alive while the phone sends nothing: on (default)"),
    ("aa-keepalive-off", "aa-keepalive off", "AA map keep-alive: off (test only)")]


# main menu 4, in order: unsupported route guidance / Java files back to factory (features-reset), an earlier card's
# RG driver/reader and Java packages replaced by this card's (rg-update, java-update), the route guidance system (rg
# needs it), then every package except the optional sl (ui included: its page saves trial starts on the unit). Steps already done answer *_ALREADY_* and are skipped (shown as "(nothing to do, skipped)", not as PMCP_FAIL; A222), so the
# same button brings any earlier pmcp install to this card's set. The map (2) and Android Auto (3) are not touched.
FEATURE_NAMES = [("rg", "route guidance"), ("zoom", "zoom"), ("dn", "day/night"), ("np", "song title"), ("ui", "settings page")]
FEATURES_NOTE = "" if not UNSUPPORTED else 'echo "Not yet supported on this unit (%s), skipped: %s."\n' % (
    FW["id"], ", ".join(t for n, t in FEATURE_NAMES if n in UNSUPPORTED) or ", ".join(UNSUPPORTED))
FEATURES = ["features-reset"] + (["rg-update"] if "rg" in FW["packages"] else []) + ["java-update"] \
    + (["rg-system-on"] if "rg" in FW["packages"] else []) + ["java-on_" + n for n, _ in JAVA_PACKAGES if n not in ("sl", "wl")]


def menu_script(args, label):
    if args is None:
        return DIAG_SCRIPT
    if args is TIMELINE:
        return TIMELINE_SCRIPT
    if args is NAVDIAG:
        return NAVDIAG_SCRIPT
    if args is RGLAST:
        return RGLAST_SCRIPT
    if args is REINSTALL:
        return REINSTALL_SCRIPT % dict(label=label, variant=START_VARIANT)
    if args is FEATURES:
        return FEATURES_SCRIPT % dict(label=label, actions=" ".join(a if "_" in a else a + "_" for a in args), note=FEATURES_NOTE)
    return MENU_SCRIPT % dict(label=label, args=args)


def esd_block(version, top, feat, onoff, aa, exp):
    def kv(text):
        return ['keyValue', '    value   String sys 0x00000000 0', '    label   "%s"' % text, '    poll    0', '']
    def sc(name, label):
        return ['script', '    value   sys 1 0x0100 "/net/mmx/fs/sda0/pmcp/menu/%s.sh"' % name, '    label   "%s"' % label, '']
    out = ['', '#' * 91, '#', '# Main -> M.I.B. -> pmcp: CarPlay and Android Auto map on the AID (%s %s / %s), added on the SD card only' % (FW["car"], FW["id"], FW["cluster"]),
           '#', '#' * 91, 'screen pmcp_stream_map_aid =>M.I.B.<=', '']
    out += kv(version) + kv("Every button checks all files first and changes nothing on a mismatch. Photograph each result.")
    out += kv("2, 3 and 4 also replace versions this card does not support. Then restart (hold the volume knob ~10 s).")
    out += kv("Advanced: pmcp_advanced (below 10): diagnostics, saving logs, single features on/off, Android Auto details.")
    for n, _, l in top:
        out += sc(n, l)
    out += ['screen pmcp_advanced pmcp_stream_map_aid', '']
    out += kv("1. diagnostics: checks, CarPlay log, speed limit status, MOST bridge (pmcp-most or mathsls).")
    out += kv("2. features: route guidance system and single packages on/off.")
    out += kv("3. aa_advanced: Android Auto details and logs.")
    if exp:
        out += kv("4. experimental: MOST supervisor, VW encoder MOST path, AA tests (experimental cards only).")
    out += ['screen diagnostics pmcp_advanced', '']
    for n, _, l in feat:
        out += sc(n, l)
    out += ['screen features pmcp_advanced', '']
    out += kv("The first start after a change is a trial: if everything works, press 5. Confirm in that start.")
    out += kv("Without Confirm the next start is the factory one (then: 6. Try again).")
    out += kv("Black screen: hold the volume knob ~10 s, the next start loads none of our JARs.")
    for n, _, l in onoff:
        out += sc(n, l)
    out += ['screen aa_advanced pmcp_advanced', '']
    out += kv("Android Auto: main menu 3, connect the phone, then 5. Confirm in that start.")
    out += kv("VW arrows from Google Maps: rg (main menu 4). Lost picture: AA status, then AA save log.")
    for n, _, l in aa:
        out += sc(n, l)
    if exp:
        out += ['screen experimental pmcp_advanced', '']
        out += kv("Experimental card only. A release card has none of these buttons: before it, VW encoder: factory MOST path.")
        for n, _, l in exp:
            out += sc(n, l)
    return "\r\n".join(out) + "\r\n"


def main():
    out = pathlib.Path(sys.argv[1])
    if out.exists():
        sys.exit("output exists: %s" % out)
    pm = out / "pmcp"
    (pm / "bin").mkdir(parents=True)
    (pm / "payload").mkdir()
    (out / "esd").mkdir()
    (pm / "menu").mkdir()

    stock = {k: read_pinned(p, h, s, k) for k, (p, h, s) in STOCK.items()}
    rows = []
    for key, (src, h, size, rel) in PAYLOAD.items():
        if h is None:
            h = TUNING_SHA[key[5:]]
        data = read_pinned(src, h, size, key)
        dst = pm / "payload" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        rows.append((key, h, size, rel))

    # Java packages are loaded together (one -Xbootclasspath/p list): no two may replace the same class.
    owner = {}
    for key, (src, h, size, rel) in PAYLOAD.items():
        if key.startswith("JAR_"):
            import zipfile
            with zipfile.ZipFile(pm / "payload" / rel) as z:
                for n in z.namelist():
                    if n.endswith(".class"):
                        if n in owner:
                            sys.exit("class %s is in both %s and %s" % (n, owner[n], key))
                        owner[n] = key
    if {k for k in PAYLOAD if k.startswith("JAR_")} != {"JAR_" + n for n, _ in JAVA_PACKAGES}:
        sys.exit("JAVA_PACKAGES and JAR_* payload entries differ")
    # java-update relies on new file names: an earlier card's JAR file is never overwritten while its set is active.
    # A188: the file name carries the content (pmcp-<package>-<sha8>.jar), so new content always gets a new name and no
    # list of earlier names is needed. NavActiveIgnore.jar keeps its stock-mod name; its content may not change under it.
    for k, (src, h, size, rel) in PAYLOAD.items():
        if not k.startswith("JAR_"):
            continue
        want = "jars/NavActiveIgnore.jar" if k == "JAR_nai" else "jars/pmcp-%s-%s.jar" % (k[4:], h[:8])
        if rel != want:
            sys.exit("%s: the unit file must be %s (got %s)" % (k, want, rel))
        if k == "JAR_nai" and h[:8] != "dbd031ec":
            sys.exit("JAR_nai: new content needs a new file name (NavActiveIgnore.jar is dbd031ec on every earlier card)")
    for old, new in JAVA_RENAMED:
        if ("JAR_" + new) not in PAYLOAD or ("JAR_" + old) in PAYLOAD or not old.replace("-", "").isalnum():
            sys.exit("java_renamed %s -> %s: the new name must be a package of this card, the old one not" % (old, new))

    lsd_patched = patch_lsd(stock["LSD"])
    (pm / "payload/lsd/lsd.sh").parent.mkdir(parents=True, exist_ok=True)
    (pm / "payload/lsd/lsd.sh").write_bytes(lsd_patched)
    rows.append(("LSD_JAVA", sha(lsd_patched), len(lsd_patched), "lsd/lsd.sh"))
    if IS_EXP:
        # experimental cards (dm-path pmcp): the factory displaymanager.json with only the MOST encoder's device changed to
        # the link the lsd.sh block makes (one line, one byte longer: the rescue card tells the two apart by size)
        dm_pmcp = patch_dm_json(stock["DMJSON"])
        (pm / "payload/dm/displaymanager.json").parent.mkdir(parents=True, exist_ok=True)
        (pm / "payload/dm/displaymanager.json").write_bytes(dm_pmcp)
        rows.append(("DM_JSON", sha(dm_pmcp), len(dm_pmcp), "dm/displaymanager.json"))

    selftest = bytes(range(256)) * 3 + b"\n\n\0\r\nend-without-newline"
    (pm / "bin/selftest.bin").write_bytes(selftest)
    shutil.copyfile(HERE / "sd/pmcp/bin/sha256.awk", pm / "bin/sha256.awk")
    shutil.copyfile(HERE / "sd/pmcp/bin/diag.sh", pm / "bin/diag.sh")
    shutil.copyfile(HERE / "sd/pmcp/bin/timeline.sh", pm / "bin/timeline.sh")
    shutil.copyfile(HERE / "sd/pmcp/bin/navdiag.sh", pm / "bin/navdiag.sh")
    shutil.copyfile(HERE / "sd/pmcp/bin/rglast.sh", pm / "bin/rglast.sh")

    manifest = "\n".join("%s %s %d %s" % r for r in rows)
    # SHA-256 -> SHA-1 of the same bytes, for the unit's factory sha1sum (pmcp.sh hash_of/sha1_for)
    pairs = {sha(selftest): hashlib.sha1(selftest).hexdigest()}
    for data in stock.values():
        pairs[sha(data)] = hashlib.sha1(data).hexdigest()
    known = []
    for kind, h, h1, size in RG_KNOWN:
        pairs[h] = h1
        known.append("%s %s %d" % (kind, h, size))
    most_known = []
    for kind, h, h1, size in MOST_KNOWN:
        if h == PMCP_MOST_SUP_PIN[1]:
            sys.exit("history most_known lists this card's own supervisor %s" % h[:8])
        pairs[h] = h1
        most_known.append("%s %s %d" % (kind, h, size))
    renamed = "\n".join("%s %s" % kv for kv in JAVA_RENAMED)
    lsd_known = []
    for h, h1, size in LSD_KNOWN:
        if h == sha(lsd_patched):
            sys.exit("history lsd_known lists this card's own lsd.sh %s" % h[:8])
        pairs[h] = h1
        lsd_known.append("%s %d" % (h, size))
    for key, h, size, rel in rows:
        data = (pm / "payload" / rel).read_bytes()
        assert sha(data) == h and len(data) == size, key
        pairs[h] = hashlib.sha1(data).hexdigest()
    hashmap = "\n".join("%s %s" % kv for kv in sorted(pairs.items()))
    # build id: payload manifest, installer template and the whole menu (labels and button scripts)
    menus = menu_entries()
    menu_text = esd_block("@@VERSION@@", *menus) + "".join(n + "\n" + menu_script(a, l) for scr in menus for n, a, l in scr)
    global PMCP_VERSION
    PMCP_VERSION = PMCP_BASE_VERSION + "-" + sha((manifest + "\n" + "\n".join(known) + "\n" + renamed + "\n"
                                                  + "\n".join(lsd_known) + "\n"
                                                  + template_for_id((HERE / "template/pmcp.sh.in").read_text())
                                                  + menu_text).encode())[:8]
    tpl = render_template((HERE / "template/pmcp.sh.in").read_text())
    # @@UNSUP_PKGS@@ only lives in the UNSUP block, which render_template keeps only for a profile with unsupported packages
    unsup_values = {"@@UNSUP_PKGS@@": " ".join(UNSUPPORTED)} if UNSUPPORTED else {}
    for k, v in {**unsup_values,
        "@@PMCP_VERSION@@": PMCP_VERSION, "@@MANIFEST@@": manifest,
        "@@SELFTEST_SHA@@": sha(selftest), "@@SELFTEST_SIZE@@": str(len(selftest)),
        "@@HASHMAP@@": hashmap, "@@RG_KNOWN@@": "\n".join(known), "@@JAVA_RENAMED@@": renamed,
        "@@LSD_KNOWN@@": "\n".join(lsd_known),
        "@@MOST_KNOWN@@": "\n".join(most_known),
        "@@STOCK_JXE_SIZE@@": str(FW["lsd_jxe"]["size"]), "@@PROFILE_ID@@": FW["id"], "@@PROFILE_CLUSTER@@": FW["cluster"],
        "@@STOCK_GAL_SHA@@": STOCK["GAL"][1], "@@STOCK_GAL_SIZE@@": str(STOCK["GAL"][2]),
        "@@STOCK_LSD_SHA@@": STOCK["LSD"][1], "@@STOCK_LSD_SIZE@@": str(STOCK["LSD"][2]),
        "@@STOCK_DIO_SHA@@": STOCK["DIO"][1], "@@STOCK_DIO_SIZE@@": str(STOCK["DIO"][2]),
        "@@STOCK_DRV_SHA@@": STOCK["IAP2DRV"][1], "@@STOCK_DRV_SIZE@@": str(STOCK["IAP2DRV"][2]),
        "@@STOCK_CFG_SHA@@": STOCK["IAP2CFG"][1], "@@STOCK_CFG_SIZE@@": str(STOCK["IAP2CFG"][2]),
        "@@STOCK_DMJ_SHA@@": STOCK["DMJSON"][1], "@@STOCK_DMJ_SIZE@@": str(STOCK["DMJSON"][2]),
    }.items():
        assert k in tpl, k
        tpl = tpl.replace(k, v)
    assert "@@" not in tpl
    (pm / "pmcp.sh").write_text(tpl)
    for name, args, label in [e for scr in menus for e in scr]:
        script = menu_script(args, label)
        (pm / "menu" / (name + ".sh")).write_text(script)
    esd = read_pinned(*MIB_ESD, label="MIB_ESD").decode("ascii")
    assert "pmcp" not in esd and esd.endswith("\r\n")
    (out / "esd/Launcher-sda0.esd").write_bytes((esd + esd_block(PMCP_VERSION, *menus)).encode("ascii"))

    lines = []
    for p in sorted(out.rglob("*")):
        if p.is_file():
            lines.append("%s  %8d  %s" % (sha(p.read_bytes()), p.stat().st_size, p.relative_to(out)))
    (out / "BUILD-MANIFEST.txt").write_text(PMCP_VERSION + "\n" + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
