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
# release v1.7.0: Android Auto 1.1 (road, lanes, destination, song title), CarPlay rg fixes
PMCP_BASE_VERSION = "pmcp-0.7.1-" + FW["version_tag"]
# Experimental card from the same tree (PMCP_BUILD_EXPERIMENTAL=1): "-exp-" in the version, plus the diagnostics buttons
# (AA record, AA output switches are in every card since AA 1.0). Same payload otherwise, so it never forces another set.
if os.environ.get("PMCP_BUILD_EXPERIMENTAL") == "1":
    PMCP_BASE_VERSION = "pmcp-0.7.1-exp-" + FW["version_tag"]
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
# only what the profile supports reaches the card, the GEM menu and the settings page
JAVA_PACKAGES = [x for x in JAVA_PACKAGES_ALL if x[0] in FW["packages"]]
# rg = everything for route guidance in one package: Tomasz's port + his lanes, our VW U-turn lanes, his MU1367
# v1.4.3 distance bar / street name / feed recovery, the maneuver fallbacks, the quiet-route hold (v1.4.3) and, since
# v1.5.0, the VW arrows from Android Auto (rg/build.sh lanes-uturn-asf-m-aa: lanes-uturn-asf-m + rg/lanes/aa.py; with
# connection 3 it reads the AA hook's mailbox /ramdisk/pmcp-aa-rg, CarPlay unchanged) and, since v1.7.0, tomasz-twardzicki's
# MU1367 v1.4.5/v1.4.6 CarPlay guidance fixes (rg/build.sh lanes-uturn-asf-m-aa-r: + rg/lanes/v146.py: reroute with
# CALC_ROUTE, placeholder arrow, U-turn side, Apple Maps names). The rg and rglu of v1.3, v1.4.x's and v1.5.0-v1.6.0's rg
# and the experimental cards' rg-aa are replaced by java-update (JAVA_OLD below).
# Tried and not shipped (docs/en/14-fast-start-audit.md): day/night v2 and the cluster day/night module (no effect on
# Google Maps), AID fast start kf..kf4.
# No two packages replace the same class (checked in main).
# In-car set (chosen in the car, 2026-10-24): 1 clean map (default), 2 clean card, 3 map with showSpeedLimit (the variant the
# unit has had since 2026-10-23, name kept), 4 clean map 40 columns left. All with url-map-hybrid's area.
VARIANTS = ["map-clean", "card-clean", "url-map-hybrid", "map-clean-l40", "map-square", "map-square-fps40"]
# main GEM button: map-square (chosen 2026-10-25) at 40 fps with an IDR every 5 frames, kept after the lag test drive
# (2026-10-31: no lag difference, no artefacts; IDR every 10 gave artefacts). map-square is 30 fps.
START_VARIANT = "map-square-fps40"

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
    # nowplaying/build.sh; since v1.7.0 (AA 1.1, A171): + Android Auto title (AndroidAutoTarget hook). Own file name
    # pmcp-np2.jar: v1.x's pmcp-np.jar keeps its one content (6b638868, JAVA_OLD). The same file as experimental card
    # 9c0c4493 (tested in the car 2026-11-12, A174)
    "JAR_np": (PROJ / "build/np-mu1161-aa11/pmcp-np.jar",
               "1f3b0dc0a0e27f349f051bc40ad92e38cd2da5a320050e6f57a73de15a6eea8e", 25007, "jars/pmcp-np2.jar"),
    # rg/build.sh <lsd> <dir> lanes-uturn-asf-m-aa-r (RC's rg 70f714fb = v1.6.0's rg 4e32e7f7 plus rg/lanes/v146.py,
    # tomasz-twardzicki MU1367 v1.4.5/v1.4.6) + com.pmcp.kv.KombiView (A166: which view the AID shows,
    # /ramdisk/pmcp-kombi-view.log) + rg/lanes/aa11.py (AA 1.1, A171: AA road name, lanes, destination only while the AID
    # does not show the AA map; KombiView.mapShown() = datapool 1110045). Own file name pmcp-guidance7.jar: pmcp-guidance5.jar
    # (RC test cards) and pmcp-guidance6.jar (experimental card b542b2d4) are in JAVA_OLD. The same file as experimental card
    # 9c0c4493 (tested in the car 2026-11-12, A174).
    "JAR_rg": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11/pmcp-rg.jar",
               "308714b29b1e7350f98771e78e34abd776cdb710123b2e9beb5c135bd3a8c04b", 64481, "jars/pmcp-guidance7.jar"),
    "JAR_zoom": (PROJ / "build/extras-mu1161-v2/pmcp-zoom.jar",
                 "046f48210dbee3177fbaa2a25f69154b56055f59b074fced1a0202700dd78d7b", 4740, "jars/pmcp-zoom.jar"),
    "JAR_dn": (PROJ / "build/extras-mu1161-v2/pmcp-dn.jar",
               "aabe871e87510177a333f1a76d69015f8bdeb994fba4ad1251e1b7f2b5afbd70", 11421, "jars/pmcp-dn.jar"),
    # Optional native-map limit reader, output is enabled separately after confirming the Java set.
    # (amjad-alarori's PR #3; since v1.4.1 without TurnToInfo, which rg owns: rg asks sl for the prefix by name). File
    # pmcp-sl2.jar: the PR's own card used pmcp-sl.jar for its sl with TurnToInfo (a unit with that set: Remove
    # everything first; its hashes are not known here, so it is not in JAVA_OLD)
    "JAR_sl": (PROJ / "build/sl-mu1161/pmcp-sl.jar",
               "37b5d9488b818e4a4de58dc9541b6618de364e5a46d81439c1f3206762e5249f", 16527, "jars/pmcp-sl2.jar"),
    # Optional settings page (ui/build.sh): the factory AbstractViewHandler with five guarded hooks + com.pmcp.ui. Its
    # speed-limit row writes the same mode file as speedlimit-mode, under the same lock and rules.
    "JAR_ui": (PROJ / "build/ui-mu1161/pmcp-ui.jar",
               "5fea8d94bdb45b6556e3a7eec660326a88aa485b4539408f75796e4d814bc395", 29485, "jars/pmcp-ui2.jar"),
    # Tomasz's driver patch + our log gate: his RGI receive log only with /dev/shmem/pmcp-rgi-debug (rg/driver/)
    "RG_DRIVER": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11/ipod-drvr-iap2-gated.so",
                  "519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3", 743272, "rg/ipod-drvr-iap2.so"),
    "RG_CFG": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-r-aa11/iap2.cfg",
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
    # destination into the rg mailbox (AA 1.1, A171); the same file as experimental card 9c0c4493 (car 2026-11-12, A174)
    "AA_HOOK": (PROJ / "aa/prebuilt/libgal_hook.so", "cbf2e388ab053c0468daab6a6d3e3e2bb27875cfb16c2e260147b37282baa3af", 141023, "aa/libgal_hook.so"),
    "AA_DMDT_FLUSH": (PROJ / "aa/prebuilt/libdmdt_flush.so", "4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f", 5328, "aa/libdmdt_flush.so"),
    # AA 1.0 (A153): feeder v14 = v13 (pmcp's own MOST writer, direct) + only direct|ring taken from PMCP_AA_OUTPUT
    # v1.7.0: feeder v15 = v14 + MOST taken back when the factory encoder grabs isoTX2 early after boot (A166; in the car
    # with cards b542b2d4 and 9c0c4493)
    "AA_FEEDER": (PROJ / "aa/prebuilt/aa-most-feeder", "395d99b756789e39b119eded68f90d4eceee269138d7f950447aa928ea464592", 58656, "aa/aa-most-feeder"),
    "AA_HOOK_CONF": (PROJ / "aa/unit/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839, "aa/gal-hook.conf"),
    "AA_MODE": (PROJ / "aa/unit/feeder-gamma.conf", "08daec96ae34f93557792ef2289e968b049f45c1b1f30802095302eae1a40a47", 1566, "aa/feeder.conf"),
})
# Experimental AA set (AAX_FEEDER: an experimental feeder next to the stable one, pmcp.sh aa-on-exp, set id
# gamma-<hook>-<that feeder>-<hook settings>): none since AA 1.0, whose stable set has the v13/v14 feeder. pmcp.sh keeps
# the mechanism for the next experimental feeder: add the key here again (experimental builds only, own feeder file).
# AA sets of earlier (experimental) cards: whole tuples of (sha256, sha1, size) for hook, feeder, hook settings, feeder
# settings, as they were on that card. pmcp.sh aa_state reports them as "old" with that card's AA_BOOT; aa-install (main menu 3) and aa-on
# brings them up to date. Only the hashes go to the card, so no earlier build is needed here.
# (profiles/<ID>/history.json, "aa_old": mode + the 4 files as [sha256, sha1, size], with a "note" per set)
AA_OLD = [(e["mode"], [tuple(f) for f in e["files"]]) for e in HIST["aa_old"]]

# Earlier pmcp route guidance files that rg-update may replace in place (pmcp.sh RG_KNOWN): (kind, sha256, sha1, size), only their
# hashes go to the card, so no earlier build is needed here. List and notes: history.json "rg_known".
RG_KNOWN = [(e["kind"], e["sha256"], e["sha1"], e["size"]) for e in HIST["rg_known"]]
# Java packages of earlier cards that java-update replaces (pmcp.sh JAVA_OLD): (name, sha256, sha1, size, jar file on the
# unit, successor); only their hashes go to the card. List and notes: history.json "java_old".
JAVA_OLD = [tuple(e[k] for k in fwprofile.JAVA_OLD_KEYS) for e in HIST["java_old"]]
if PROFILE_ID not in PAYLOAD_BY_PROFILE:
    sys.exit("no PAYLOAD pins for profile %s in build_sd.py (PAYLOAD_BY_PROFILE)" % PROFILE_ID)
PAYLOAD = {k: v for k, v in PAYLOAD_BY_PROFILE[PROFILE_ID].items()
           if not (k.startswith("JAR_") and k[4:] not in FW["packages"])}
if FW["lsd_sh_states"] != ["stock"]:
    sys.exit("profile %s: lsd_sh_states %r is not supported by this installer yet" % (PROFILE_ID, FW["lsd_sh_states"]))
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
# <<< pmcp"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_pinned(path, want_sha, want_size, label=""):
    data = pathlib.Path(path).read_bytes()
    if len(data) != want_size or (want_sha and sha(data) != want_sha):
        sys.exit("input mismatch: %s %s size=%d sha=%s" % (label, path, len(data), sha(data)))
    return data


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
# pmcp GEM button: 0. Diagnostics (generated by build_sd.py)
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
echo "Do not press Back and do not remove the SD card until PMCP_FEATURES_ON_OK or PMCP_FAIL is shown."
PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh
NEW=0
for A in %(actions)s; do
    echo "- ${A%%%%_*} ${A#*_}"
    OUT=`/bin/ksh $PMCP ${A%%%%_*} ${A#*_} 2>&1`
    echo "$OUT" | while read L; do case "$L" in PMCP_WARN*) ;; PMCP_*) echo "  $L" ;; esac; done
    case "$OUT" in
        *PMCP_FAIL=*_ALREADY_*) echo "  (already on)" ;;
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


def menu_entries():
    # (file name, pmcp arguments, GEM label). ASCII only: GEM fonts and the esd parser are not tested with other letters.
    # Main screen pmcp_stream_map_aid: one button per part, stable versions only; each replaces a version this card
    # does not support. Everything else is under pmcp_advanced (features_advanced, carplay_advanced, aa_advanced).
    top = [("verify", "verify", "1. Check card and unit (read-only)"),
           ("map-install", "map-install " + START_VARIANT, "2. Install CarPlay: the map on the AID (also repairs or updates it)"),
           ("aa-install", "aa-install", "3. Install Android Auto: Google Maps on the AID + VW arrows (needs 2)"),
           ("features-on", FEATURES, "4. Install additional features: route guidance, zoom, day/night, song title, settings page (needs 2)"),
           ("confirm", "confirm", "5. Confirm: everything works (in the first start after 3 or 4)"),
           ("retry", "retry", "6. Try again: the next start is a new trial"),
           ("status", "status", "7. Status (read-only)"),
           ("restore", "restore", "8. Remove everything (back to factory files)")]
    feat = [("diag", None, "0. Diagnostics (read-only, photograph the screen)"),
            ("timeline", TIMELINE, "Start timeline: seconds from unit start to CarPlay, MOST, navigation (read-only)"),
            ("rglast", RGLAST, "RG last maneuver: what the iPhone sent and which VW arrow it gives (read-only)"),
            ("navdiag", NAVDIAG, "Navigation diagnostics: why the VW navigation does not start (read-only)"),
            ("cp-log-save", "cp-log-save", "CP save log: copy this start's CarPlay log to the unit (for the log card)"),
            ("log-clear", "aa-log-clear", "Delete saved logs, CarPlay and AA (after the log card copied them)"),
            # package sl (On sl, then 5. Confirm), then one of these; the mode is kept across starts
            # the speed-limit mode is set on the unit: App-Connect > Settings > AID navigation configuration (package ui); pmcp.sh
            # speedlimit-mode stays for the tests and the command line
            ("speedlimit-status", "speedlimit-status", "Speed limit status: mode and native VW limit data (read-only)"),
            ("rg-system-on", "rg-system-on", "Route guidance system on (iAP2 driver, iap2.cfg, reader)"),
            ("rg-system-off", "rg-system-off", "Route guidance system off (factory iAP2 driver and iap2.cfg)"),
            ("rg-update", "rg-update", "Route guidance system update (driver and reader of this card, RG stays on)"),
            ("java-update", "java-update", "Java update: packages of an earlier card -> this card's (rglu -> rg)")]
    feat += [("java-on-" + n, "java-on " + n, "On " + label) for n, label in JAVA_PACKAGES] + \
            [("java-off-" + n, "java-off " + n, "Off " + label) for n, label in JAVA_PACKAGES]
    cp = [("install-" + v, "install " + v, "Install map layout: " + v) for v in VARIANTS if v != START_VARIANT] + \
         [("switch-" + v, "switch " + v, "Switch map layout to: " + v) for v in VARIANTS]
    return top, feat, cp, AA_MENU + AA_EXP_MENU


# Android Auto details, screen aa_advanced. The stable set is installed by main menu 3 (aa-install); the main menu's
# 5 and 6 confirm / try again Android Auto too. Release cards keep the AA logs and status (support).
AA_MENU = [("aa-confirm", "aa-confirm", "AA Confirm: AA works (only in the start of the AA trial; 5 does the same)"),
           # AA 1.0: the output, no trial (also on the settings page); direct is the set's default
           ("aa-output-direct", "aa-output direct", "AA output: pmcp MOST writer (default, from the next connection)"),
           ("aa-output-ring", "aa-output ring", "AA output: CarPlay bridge (fallback, from the next connection)"),
           ("aa-retry", "aa-retry", "AA Try again: the next AA connection is a new trial"),
           ("aa-status", "aa-status", "AA status and stream analysis (read-only)"),
           ("aa-log-save", "aa-log-save", "AA save log: copy this start's AA log to the unit (for the log card)"),
           ("aa-log-clear", "aa-log-clear", "AA delete saved logs, AA and CarPlay (after the log card copied them)"),
           ("aa-remove", "aa-remove", "AA remove (factory Android Auto back)")]
# experimental builds only: their extra Android Auto software (empty on release cards)
AA_EXP_MENU = [] if "-exp-" not in PMCP_BASE_VERSION else [
    ("aa-capture-60", "aa-capture 60", "AA record: first 60 s of the phone video at each connection (for the log card)"),
    ("aa-capture-off", "aa-capture off", "AA record: off")]


# main menu 4, in order: unsupported route guidance / Java files back to factory (features-reset), an earlier card's
# RG driver/reader and Java packages replaced by this card's (rg-update, java-update), the route guidance system (rg
# needs it), then every package except the optional sl (ui included: its page saves trial starts on the unit). Steps already done answer *_ALREADY_* and are skipped, so the
# same button brings any earlier pmcp install to this card's set. The map (2) and Android Auto (3) are not touched.
FEATURES = ["features-reset", "rg-update", "java-update", "rg-system-on"] + ["java-on_" + n for n, _ in JAVA_PACKAGES if n != "sl"]


def menu_script(args, label):
    if args is None:
        return DIAG_SCRIPT
    if args is TIMELINE:
        return TIMELINE_SCRIPT
    if args is NAVDIAG:
        return NAVDIAG_SCRIPT
    if args is RGLAST:
        return RGLAST_SCRIPT
    if args is FEATURES:
        return FEATURES_SCRIPT % dict(label=label, actions=" ".join(a if "_" in a else a + "_" for a in args))
    return MENU_SCRIPT % dict(label=label, args=args)


def esd_block(version, top, feat, cp, aa):
    def kv(text):
        return ['keyValue', '    value   String sys 0x00000000 0', '    label   "%s"' % text, '    poll    0', '']
    def sc(name, label):
        return ['script', '    value   sys 1 0x0100 "/net/mmx/fs/sda0/pmcp/menu/%s.sh"' % name, '    label   "%s"' % label, '']
    out = ['', '#' * 91, '#', '# Main -> M.I.B. -> pmcp: CarPlay and Android Auto map on the AID (%s %s / %s), added on the SD card only' % (FW["car"], FW["id"], FW["cluster"]),
           '#', '#' * 91, 'screen pmcp_stream_map_aid =>M.I.B.<=', '']
    out += kv(version) + kv("Every button checks all files first and changes nothing on a mismatch. Photograph each result.")
    out += kv("2, 3 and 4 also replace versions this card does not support. Then restart (hold the volume knob ~10 s).")
    out += kv("9. Advanced: pmcp_advanced (below): single features, map layouts, Android Auto details, logs.")
    for n, _, l in top:
        out += sc(n, l)
    out += ['screen pmcp_advanced pmcp_stream_map_aid', '']
    out += kv("1. features_advanced: diagnostics, logs, speed limit, single packages.")
    out += kv("2. carplay_advanced: map layouts.  3. aa_advanced: Android Auto details and logs.")
    out += ['screen features_advanced pmcp_advanced', '']
    out += kv("The first start after a change is a trial: if everything works, press 5. Confirm in that start.")
    out += kv("Without Confirm the next start is the factory one (then: 6. Try again).")
    out += kv("Black screen: hold the volume knob ~10 s, the next start loads none of our JARs.")
    for n, _, l in feat:
        out += sc(n, l)
    out += ['screen carplay_advanced pmcp_advanced', '']
    for n, _, l in cp:
        out += sc(n, l)
    out += ['screen aa_advanced pmcp_advanced', '']
    out += kv("Android Auto 0.1: main menu 3, connect the phone, then 5. Confirm in that start.")
    out += kv("VW arrows from Google Maps: rg (main menu 4). Lost picture: AA status, then AA save log.")
    for n, _, l in aa:
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
    # java-update relies on new file names: an earlier card's JAR file is never overwritten while its set is active
    ours = {rel.rsplit("/", 1)[-1] for k, (src, h, size, rel) in PAYLOAD.items() if k.startswith("JAR_")}
    cur = {(k[4:], h[:8]) for k, (src, h, size, rel) in PAYLOAD.items() if k.startswith("JAR_")}
    olds = [(name, h[:8]) for name, h, h1, size, jar, succ in JAVA_OLD]
    if len(set(olds)) != len(olds) or set(olds) & cur or len({o[4] for o in JAVA_OLD}) != len(JAVA_OLD):
        sys.exit("JAVA_OLD: a (name, sha8) twice or equal to this card's package, or a JAR file name twice")
    for name, h, h1, size, jar, succ in JAVA_OLD:
        if len(h1) != 40 or len(h) != 64:
            sys.exit("JAVA_OLD entry %s: bad hash length" % name)
        if jar in ours or not jar.startswith("pmcp-") or ("JAR_" + succ) not in PAYLOAD:
            sys.exit("JAVA_OLD entry %s: file %s reused, outside pmcp-*.jar (rescue card) or no successor" % (name, jar))

    lsd_patched = patch_lsd(stock["LSD"])
    (pm / "payload/lsd/lsd.sh").parent.mkdir(parents=True, exist_ok=True)
    (pm / "payload/lsd/lsd.sh").write_bytes(lsd_patched)
    rows.append(("LSD_JAVA", sha(lsd_patched), len(lsd_patched), "lsd/lsd.sh"))

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
    old = []
    for name, h, h1, size, jar, succ in JAVA_OLD:
        pairs[h] = h1
        old.append("%s %s %d %s %s" % (name, h, size, jar, succ))
    aa_old = []
    cur_aa = [PAYLOAD[k][1:3] for k in ("AA_HOOK", "AA_FEEDER", "AA_HOOK_CONF", "AA_MODE")]
    for mode, files in AA_OLD:
        hs = []
        for h, h1, size in files:
            pairs[h] = h1
            hs.append("%s %d" % (h, size))
        assert [(f[0], f[2]) for f in files] != cur_aa, "AA_OLD tuple equals this card's AA set"
        if "AAX_FEEDER" in PAYLOAD:
            assert [(f[0], f[2]) for f in files] != [cur_aa[0], PAYLOAD["AAX_FEEDER"][1:3]] + cur_aa[2:], \
                "AA_OLD tuple equals this card's experimental AA set"
        # the set id (mode + hook, feeder, hook settings) does not cover feeder.conf: pmcp.sh aa-on drops the markers of
        # such a set, so its confirmation does not carry over to this card's settings (card 030b7df2: same id, 2 Mbit/s)
        if mode == "gamma" and [f[0][:8] for f in files[:3]] == [c[0][:8] for c in cur_aa[:3]]:
            print("WARNING: AA_OLD set %s (feeder.conf %s) has this card's AA set id: AA 1 removes its confirmation, the "
                  "next AA connection is a trial" % ("-".join([mode] + [f[0][:8] for f in files[:3]]), files[3][0][:8]))
        if "AAX_FEEDER" in PAYLOAD and mode == "gamma" and \
                [f[0][:8] for f in files[:3]] == [cur_aa[0][0][:8], PAYLOAD["AAX_FEEDER"][1][:8], cur_aa[2][0][:8]]:
            print("WARNING: AA_OLD set %s (feeder.conf %s) has this card's EXPERIMENTAL AA set id: aa-on-exp removes its "
                  "confirmation, the next AA connection is a trial" % ("-".join([mode] + [f[0][:8] for f in files[:3]]),
                                                                       files[3][0][:8]))
        aa_old.append(mode + " " + " ".join(hs))
    for key, h, size, rel in rows:
        data = (pm / "payload" / rel).read_bytes()
        assert sha(data) == h and len(data) == size, key
        pairs[h] = hashlib.sha1(data).hexdigest()
    hashmap = "\n".join("%s %s" % kv for kv in sorted(pairs.items()))
    # build id: payload manifest, installer template and the whole menu (labels and button scripts)
    menus = menu_entries()
    menu_text = esd_block("@@VERSION@@", *menus) + "".join(n + "\n" + menu_script(a, l) for scr in menus for n, a, l in scr)
    global PMCP_VERSION
    PMCP_VERSION = PMCP_BASE_VERSION + "-" + sha((manifest + "\n" + "\n".join(known) + "\n" + "\n".join(old) + "\n"
                                                   + "\n".join(aa_old) + "\n"
                                                   + (HERE / "template/pmcp.sh.in").read_text() + menu_text).encode())[:8]
    tpl = (HERE / "template/pmcp.sh.in").read_text()
    for k, v in {
        "@@PMCP_VERSION@@": PMCP_VERSION, "@@MANIFEST@@": manifest,
        "@@SELFTEST_SHA@@": sha(selftest), "@@SELFTEST_SIZE@@": str(len(selftest)),
        "@@HASHMAP@@": hashmap, "@@RG_KNOWN@@": "\n".join(known), "@@JAVA_OLD@@": "\n".join(old), "@@AA_OLD@@": "\n".join(aa_old),
        "@@STOCK_JXE_SIZE@@": str(FW["lsd_jxe"]["size"]), "@@PROFILE_ID@@": FW["id"], "@@PROFILE_CLUSTER@@": FW["cluster"],
        "@@STOCK_GAL_SHA@@": STOCK["GAL"][1], "@@STOCK_GAL_SIZE@@": str(STOCK["GAL"][2]),
        "@@STOCK_LSD_SHA@@": STOCK["LSD"][1], "@@STOCK_LSD_SIZE@@": str(STOCK["LSD"][2]),
        "@@STOCK_DIO_SHA@@": STOCK["DIO"][1], "@@STOCK_DIO_SIZE@@": str(STOCK["DIO"][2]),
        "@@STOCK_DRV_SHA@@": STOCK["IAP2DRV"][1], "@@STOCK_DRV_SIZE@@": str(STOCK["IAP2DRV"][2]),
        "@@STOCK_CFG_SHA@@": STOCK["IAP2CFG"][1], "@@STOCK_CFG_SIZE@@": str(STOCK["IAP2CFG"][2]),
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
