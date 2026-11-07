#!/usr/bin/env python3
"""Assemble the pmcp tree for the M.I.B. SD card (SD#2) from pinned inputs. Host tool, read-only on inputs.

  python3 -I build_sd.py OUT_DIR

Every input is checked against its SHA-256 and size before use; the output must not exist yet.
The patched lsd.sh is generated here from the verified factory file, so the unit only copies
a file whose hash is known in advance. Output: OUT_DIR/pmcp/... (installer, payload, one script per GEM button in pmcp/menu/) and
OUT_DIR/esd/Launcher-sda0.esd (the M.I.B. 3.6.0 menu with one pmcp screen appended),
plus OUT_DIR/BUILD-MANIFEST.txt with every output hash.
"""
import hashlib
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent  # workspace: upstream/, backup/, archives/ next to this project
PROJ = HERE.parent         # this project (any folder name)
PMCP_BASE_VERSION = "pmcp-0.5.0-mu1161-791"   # release v1.5.0: CarPlay + Android Auto (aa/, installed separately)
PMCP_VERSION = None   # PMCP_BASE_VERSION + "-" + first 8 hex of payload manifest, pmcp.sh and menu (set in main): one id per build

# M.I.B. backup of the unit (folder named after the unit; every file read from it is pinned by sha256 below)
BACKUP = pathlib.Path(os.environ.get("PMCP_BACKUP", REPO / "backup/MU1161")) / "advanced/MU1161-appimg"
MATHSLS = REPO / "upstream/mathsls/MU1161/791_AID12.3/payload"  # git cdd576b02a282853bd764a82b9a94e6474f39052
TUNING = PROJ / "build/mu1161-791/tuning"
# The GEM menu file of the M.I.B. version on the user's SD card (MIB_V3.6.0.zip, esd/Launcher-sda0.esd).
# The unit links engdefs/z_Launcher-sda0.esd to this file on the card, so adding a screen here changes nothing on the unit.
MIB_ESD = (REPO / "archives/mib-3.6.0/Launcher-sda0.esd",
           "22739f7226f36d089e2e0485fe2b6874aba2ee6b7b57c807de7bc25c0fdc9121", 111474)
# Java packages (stage B+): name -> GEM label. Each needs a "JAR_<name>" entry in PAYLOAD.
JAVA_PACKAGES = [("nai", "nai: AID map stays while the iPhone navigates (NavActiveIgnore)"),
                 ("np", "np: CarPlay song title and artist on the AID"),
                 ("rg", "rg: route guidance: arrows, lanes, distance bar, street, ETA (needs Route guidance system)"),
                 ("zoom", "zoom: CarPlay map zoom with the steering wheel arrows"),
                 ("dn", "dn: CarPlay map day/night on the AID (sent again after start)"),
                 # optional (not in button 3), output off until enabled with speedlimit-mode
                 ("sl", "sl: native VW map speed limit in the AID road text (optional, output off until enabled)")]
# rg = everything for route guidance in one package: Tomasz's port + his lanes, our VW U-turn lanes, his MU1367
# v1.4.3 distance bar / street name / feed recovery, the maneuver fallbacks, the quiet-route hold (v1.4.3) and, since
# v1.5.0, the VW arrows from Android Auto (rg/build.sh lanes-uturn-asf-m-aa: lanes-uturn-asf-m + rg/lanes/aa.py; with
# connection 3 it reads the AA hook's mailbox /ramdisk/pmcp-aa-rg, CarPlay unchanged). The rg and rglu of v1.3, v1.4.x's
# rg and the experimental cards' rg-aa are replaced by java-update (JAVA_OLD below).
# Tried and not shipped (docs/en/14-fast-start-audit.md): day/night v2 and the cluster day/night module (no effect on
# Google Maps), AID fast start kf..kf4.
# No two packages replace the same class (checked in main).
# In-car set (chosen in the car, 2026-10-24): 1 clean map (default), 2 clean card, 3 map with showSpeedLimit (the variant the
# unit has had since 2026-10-23, name kept), 4 clean map 40 columns left. All with url-map-hybrid's area.
VARIANTS = ["map-clean", "card-clean", "url-map-hybrid", "map-clean-l40", "map-square", "map-square-fps40"]
# main GEM button: map-square (chosen 2026-10-25) at 40 fps with an IDR every 5 frames, kept after the lag test drive
# (2026-10-31: no lag difference, no artefacts; IDR every 10 gave artefacts). map-square is 30 fps.
START_VARIANT = "map-square-fps40"

STOCK = {
    "IAP2DRV": (BACKUP / "armle/lib/dll/ipod-drvr-iap2.so", "7149a3e75b1b19e89021841759f420a6eced456b6c697a3dd1f0e436abea0b8c", 739925),
    "IAP2CFG": (BACKUP.parent / "MU1161-system/mm/iap2.cfg", "1539c79dd415eddeb59ea215c7a9b0ec4be3632fe066be3aefdff11bd19cdf37", 5951),
    "LSD": (BACKUP / "eso/hmi/lsd/lsd.sh", "97bbd4ecb51045b34c2a41955d9f53e1f144d174bff1aa8560e911525808e8d8", 16567),
    "DIO": (BACKUP / "eso/bin/apps/dio_manager", "609e42723ab3e36c7be5ceade81e03672ba4acd251f8eeb8b100e074aaf3c250", 686249),
    # Android Auto receiver: aa-on replaces it by the AA wrapper and keeps this factory file as carplaymaps/aa/gal.real
    "GAL": (BACKUP / "eso/bin/apps/gal", "3b422d47a16dd473dc426aa3a88348bfee0da0e7585993a3566df242339346f9", 1269219),
}

# key -> (source, sha256, size, path inside payload/)
PAYLOAD = {
    "BRIDGE": (MATHSLS / "profiles/MU1161/791/altscreen-most-bridge",
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
    "JAR_np": (PROJ / "build/np-mu1161-v2/pmcp-np.jar",
               "6b638868e65a6e573117cbf249850bb29e7b9aac3cd0502c2830652411f1dc23", 17928, "jars/pmcp-np.jar"),
    # rg/build.sh <lsd> <dir> lanes-uturn-asf-m-aa (the same bytes as the experimental card 84472aa9's rg-aa); a file name
    # no earlier card used (java-update keeps the old set intact)
    "JAR_rg": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-150/pmcp-rg.jar",
               "01221496a8670e1a2de3b54a1aa1ed8512a9931c92c1823da98e018d44c71d7c", 53309, "jars/pmcp-guidance4.jar"),
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
    # Tomasz's driver patch + our log gate: his RGI receive log only with /dev/shmem/pmcp-rgi-debug (rg/driver/)
    "RG_DRIVER": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-150/ipod-drvr-iap2-gated.so",
                  "519ea3c5ba08427ea20d62817747af390ac7256bad447da5fcfda388d10b9ed3", 743272, "rg/ipod-drvr-iap2.so"),
    "RG_CFG": (PROJ / "build/rg-mu1161-lanes-uturn-asf-m-aa-150/iap2.cfg",
               "c61407d9c6cd0d2529afedad0c9a120d5da5a504739e273bbb3dbea1e0b9b491", 6079, "rg/iap2.cfg"),
    # rgi-observer pmcp-r1 (rg/reader/, prebuilt in the repository): a stuck driver read costs one invalid record, not the reader
    "RG_READER": (PROJ / "rg/reader/prebuilt/rgi-observer",
                  "3166df9b91119475f93043ac8c150e2641732e602161839a137a1907d4ef11df", 13552, "rg/rgi-observer"),
}
# Android Auto 0.1 (aa/README.md), one mode "gamma": MacsInSpace's gal hook (pinned commit, no SD card paths,
# aa/hook/build.sh gamma: Google Maps manoeuvres -> rg mailbox), our feeder (aa/feeder, v10: start sync + pacing without bursts) and the
# gal wrapper. Built into build/ by those scripts (docker, QNX 6.5 toolchain).
AA_GAMMA = PROJ / "build/aa-g2"    # hook g2 (A-AA24): liveness / unknown-type fixes
AA_KF5 = PROJ / "build/aa-kf5"     # libdmdt_flush.so (unchanged since AA 1)
AA_FEED = PROJ / "build/aa-v10"    # feeder v10 (A-AA33)
PAYLOAD.update({
    "AA_WRAPPER": (PROJ / "aa/unit/gal.wrapper.sh", "57b63037a7d82d45f47773ec76e99ad659490f6d29d540f20de90930f0d65137", 3259, "aa/gal.wrapper.sh"),
    "AA_HOOK": (AA_GAMMA / "hook/libgal_hook.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823, "aa/libgal_hook.so"),
    "AA_DMDT_FLUSH": (AA_KF5 / "hook/libdmdt_flush.so", "4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f", 5328, "aa/libdmdt_flush.so"),
    "AA_FEEDER": (AA_FEED / "feeder/aa-most-feeder", "c5f8b0ef3821b3a533cd762fab14ff984fffa0afe4fd66185e16ea57413149a7", 34856, "aa/aa-most-feeder"),
    "AA_HOOK_CONF": (PROJ / "aa/unit/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839, "aa/gal-hook.conf"),
    "AA_MODE": (PROJ / "aa/unit/feeder-gamma.conf", "ac7157dabd7ae3ec61e8b9c453451b5716154b2b068d552dd96a94a83852e75d", 1219, "aa/feeder.conf"),
})
# AA sets of earlier (experimental) cards (whole tuples: hook, feeder, hook settings, feeder settings, each from the card it was
# on; pmcp.sh aa_state reports them as "old" with that card's AA_BOOT, aa-on brings them up to date). All modes of those
# cards count: this card has only gamma, aa-on ("AA 1") replaces any of them.
AA_OLD = [
    # AA 3 (1.5) feeder v6 (card 892eed6f)
    ("sync15", [(PROJ / "build/sd-892eed6f/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/aa-most-feeder-v6", "a71e02fc8a20e3d0080d0a04cf301e85a3c06fb32dc0b95b71e0c7244cae9f7c", 28744),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/feeder-sync15.conf", "50f6b4e78e589c75841afe36640dbd655a027bdf1edef7d8fb1884a446f2237c", 358)]),
    # AA 3 (1.7) feeder v6 (card 892eed6f)
    ("sync17", [(PROJ / "build/sd-892eed6f/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/aa-most-feeder-v6", "a71e02fc8a20e3d0080d0a04cf301e85a3c06fb32dc0b95b71e0c7244cae9f7c", 28744),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-892eed6f/pmcp/payload/aa/feeder-sync17.conf", "28d3de87de2621c118d441f044d49960817d1d7669ceb2e6ff4c7891e4d073e4", 282)]),
    # AA 3 (1.5) v7 with probe C (card 9766265d)
    ("sync15", [(PROJ / "build/sd-9766265d/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/feeder-sync15.conf", "9dc1cda65298c89f05d14c62ef72c22902602e8dbff5556ef2598cf2b1403f7a", 708)]),
    # AA 3 (1.7) v7 with probe C (card 9766265d)
    ("sync17", [(PROJ / "build/sd-9766265d/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/feeder-sync17.conf", "08b43660b37df4837436d197968b96e8f216bc483ad1b945bcfb5164d9b72c3c", 802)]),
    # gamma hook g1, probe C (card 662eb7a8)
    ("gamma", [(PROJ / "build/sd-662eb7a8/pmcp/payload/aa/libgal_hook-gamma.so", "aa0b97fc61ec554c0ca81340fe04d53214afe0c3b7c0ac2b891b15d9e7014ddc", 131136),
              (PROJ / "build/sd-662eb7a8/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-662eb7a8/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-662eb7a8/pmcp/payload/aa/feeder-gamma.conf", "e09c810b52e35ee24484b57494752ee0a8aa5f805a301834f553cb66944842ad", 825)]),
    # gamma hook g2, probe C (card 9766265d)
    ("gamma", [(PROJ / "build/sd-9766265d/pmcp/payload/aa/libgal_hook-gamma.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-9766265d/pmcp/payload/aa/feeder-gamma.conf", "e09c810b52e35ee24484b57494752ee0a8aa5f805a301834f553cb66944842ad", 825)]),
    # AA 3 (1.5) v7 without probe C (card a32f55db)
    ("sync15", [(PROJ / "build/sd-a32f55db/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/feeder-sync15.conf", "c29014492e545971404c6d46775bc82d36666bd8d3aedd5c0548e8aee37f5a51", 686)]),
    # AA 3 (1.7) v7 without probe C (card a32f55db)
    ("sync17", [(PROJ / "build/sd-a32f55db/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/feeder-sync17.conf", "3588fc0dac530d9b2cd6caaaafbd532aa7990af04baa8ec3b980c4271036b21a", 780)]),
    # gamma hook g2, v7 without probe C (card a32f55db)
    ("gamma", [(PROJ / "build/sd-a32f55db/pmcp/payload/aa/libgal_hook-gamma.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/aa-most-feeder-sync", "27b32b35168e43e9f31e397f6cbf0cf1390cd2d7ca486dd93644e693739c1778", 29476),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-a32f55db/pmcp/payload/aa/feeder-gamma.conf", "1f14e9d60c5cc939d53f195f8805738f1758a6e819b1aec3bdc8538fd26ffff5", 803)]),
    # AA 3 (1.5) feeder v8, 5 s (card fc01e707)
    ("sync15", [(PROJ / "build/sd-fc01e707/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/feeder-sync15.conf", "c29014492e545971404c6d46775bc82d36666bd8d3aedd5c0548e8aee37f5a51", 686)]),
    # AA 3 (1.7) feeder v8, 5 s (card fc01e707)
    ("sync17", [(PROJ / "build/sd-fc01e707/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/feeder-sync17.conf", "3588fc0dac530d9b2cd6caaaafbd532aa7990af04baa8ec3b980c4271036b21a", 780)]),
    # gamma g2, feeder v8, 5 s (card fc01e707)
    ("gamma", [(PROJ / "build/sd-fc01e707/pmcp/payload/aa/libgal_hook-gamma.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-fc01e707/pmcp/payload/aa/feeder-gamma.conf", "1f14e9d60c5cc939d53f195f8805738f1758a6e819b1aec3bdc8538fd26ffff5", 803)]),
    # AA 3 (1.5) feeder v8, 10 s (card 2d4483e5)
    ("sync15", [(PROJ / "build/sd-2d4483e5/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/feeder-sync15.conf", "83ce7aecd794219bda21103b425d720bee100135bab904fca3b5b0d234237013", 755)]),
    # AA 3 (1.7) feeder v8, 10 s (card 2d4483e5)
    ("sync17", [(PROJ / "build/sd-2d4483e5/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/feeder-sync17.conf", "ae2771afc6ef1344ded3d1054afa1b28b1c892010eecaf4d46e2e680f5cc5953", 849)]),
    # gamma g2, feeder v8, 10 s (card 2d4483e5)
    ("gamma", [(PROJ / "build/sd-2d4483e5/pmcp/payload/aa/libgal_hook-gamma.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-2d4483e5/pmcp/payload/aa/feeder-gamma.conf", "c8d19ef4c522726366b44c402fbec0f47b45387f228b87d26fbf39ecfd58ca09", 872)]),
    # AA 3 (1.5) feeder v8, 5 s + start sync 3 s (card ab9fb348)
    ("sync15", [(PROJ / "build/sd-ab9fb348/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/gal-hook.conf", "4a6de359a582ff79ad791882ba6d24178f40ec20c912bbc2f6e211a86504bddc", 1514),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/feeder-sync15.conf", "325f2a753f243b71b52422715e885937e5d2134ea74170965ec4b1316dbdd721", 958)]),
    # AA 3 (1.7) feeder v8, 5 s + start sync 3 s (card ab9fb348)
    ("sync17", [(PROJ / "build/sd-ab9fb348/pmcp/payload/aa/libgal_hook.so", "dd72104b416d11c455c35101f0869b2d36bc0c28eafa8e8fa46e2bf71fc80a9c", 120396),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/gal-hook-17.conf", "99288ee3709ced0080ef18d8f5f314a3c36b690001ddba73b37838572a474323", 1578),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/feeder-sync17.conf", "374c0f580779febd49e4ba2d0ad065c8174ebce3b0840ff9cf2bab68497af490", 1052)]),
    # gamma g2, feeder v8, 5 s + start sync 3 s (card ab9fb348)
    ("gamma", [(PROJ / "build/sd-ab9fb348/pmcp/payload/aa/libgal_hook-gamma.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/aa-most-feeder-sync", "5ec1a19129b0cf8f45445f514bcc813395f127a11e98abdb524fa9864e38e652", 30048),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/gal-hook-gamma.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-ab9fb348/pmcp/payload/aa/feeder-gamma.conf", "65452c93449c1afc44fef6e70d00bd228ffd5d8580f9256b02876ae9c25bad9e", 1075)]),
    # gamma g2, feeder v9 (cards f2a7ceb5 / fd0c7a7c, v1.4.1 / v1.4.2 experimental)
    ("gamma", [(PROJ / "build/sd-f2a7ceb5/pmcp/payload/aa/libgal_hook.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-f2a7ceb5/pmcp/payload/aa/aa-most-feeder", "5d2a0a026321196c1a2745dcb8e32f896e7fb3cace7a036bb910357f54afc630", 33464),
              (PROJ / "build/sd-f2a7ceb5/pmcp/payload/aa/gal-hook.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-f2a7ceb5/pmcp/payload/aa/feeder.conf", "eaae73415ec6a2a3f4351764dcfdb96cd87d90aa3034cadd03bec52a09aad97a", 857)]),
    # gamma g2, feeder v10 at 2 Mbit/s (card 030b7df2)
    ("gamma", [(PROJ / "build/sd-030b7df2/pmcp/payload/aa/libgal_hook.so", "bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05", 132823),
              (PROJ / "build/sd-030b7df2/pmcp/payload/aa/aa-most-feeder", "c5f8b0ef3821b3a533cd762fab14ff984fffa0afe4fd66185e16ea57413149a7", 34856),
              (PROJ / "build/sd-030b7df2/pmcp/payload/aa/gal-hook.conf", "716516eb36b50f7b7230ff36ad8057713ba2b1c97c2fd0b55afe2c8f17559173", 1839),
              (PROJ / "build/sd-030b7df2/pmcp/payload/aa/feeder.conf", "c26c69a8562f4773edbbbf287ecf20e52d208f27135b944df04c6f8bbf70dccc", 1160)]),
]

# Earlier pmcp route guidance files that rg-update may replace in place (pmcp.sh RG_KNOWN): the v1.0-v1.3 driver and
# Tomasz's reader. (kind, sha256, sha1, size): only their hashes go to the card, so no earlier build is needed here.
RG_KNOWN = [
    ("DRIVER", "76926bde9bdf1e06fdfe57fd324bbd8772bcb2a98a58ac444b4822e25a331b48", "7613f35cb8597dbaedd16fd83260a14c7f2d654f", 743196),
    ("READER", "b683cef78828bfab2b8cdf43e4ea82e5d7c16d0d47730936d936e82af6ee08ac", "1b6cb87d2aa1148f28996f72cb00349519b19077", 16606),
]
# Java packages of earlier cards that java-update replaces (pmcp.sh JAVA_OLD): (name, sha256, sha1, size, jar file on the
# unit, successor). v1.2/v1.3 rg and rglu, v1.4.x rg, and the experimental cards' rg variants (rg/build.sh modes base,
# lanes-uturn, lanes-uturn-aa, -asf, -asf-aa, -asf-m, -asf-m-aa): all become rg. Only their hashes go to the card.
JAVA_OLD = [
    ("rg", "717fb53c667c612e6f3b483ea93620559eaa23404a2e237d255f5af40798a754", "f748313879a40e3c8d69304dcfbfbbf003a412c6", 34082, "pmcp-rg.jar", "rg"),
    ("rglu", "72ab72214ee91a0d95ba0ec4d57a65cbee95d8ee82cb23af82fcb6b082591a33", "29b4bbcacc1c4251b7a47efd3c11445ba33e41f8", 38529, "pmcp-rglu.jar", "rg"),
    ("rglua", "a9a25b1eb9aeed1347bb9c6c38aef3549dc2416d844c10b203fd175319f62161", "809f18a0deb12667fe651c5309a6be5c63a3849a", 38832, "pmcp-rglua.jar", "rg"),
    ("rgluasf", "a092ef2a617cd63cde454d2bb18e8ea249f374770474ac030e5aea53edc373ed", "4fa0c5b25cbddc70b7c672ce58043fbd8eb3f68d", 47187, "pmcp-rgluasf.jar", "rg"),
    ("rgluasfa", "b3a35c9b40ae4bb5360189178b18218005a194f4585ee491a916bfce539c034d", "385c81be0210bdbd9f599a7739124d528f3d8770", 47510, "pmcp-rgluasfa.jar", "rg"),
    ("rgluasfm", "13ca11c4e2a5fbe155165071f69fbee0e2b5b318e87fbfc079a9f76fefb62770", "517763a46b37afac546ec45e24b72cf15307ad9a", 47817, "pmcp-rgluasfm.jar", "rg"),
    ("rgluasfma", "de39c893d8ea86abe4f57bc350fd7bd2d9b4a79f9023fc28a430cc2a20957ace", "ca03f2696567e24866b30e370159835a2cfae3db", 48161, "pmcp-rgluasfma.jar", "rg"),
    # v1.4.0 rg (the same bytes as rgluasfm, under the v1.4.0 file name); v1.4.1 adds the speed-limit prefix hook
    ("rg", "13ca11c4e2a5fbe155165071f69fbee0e2b5b318e87fbfc079a9f76fefb62770", "517763a46b37afac546ec45e24b72cf15307ad9a", 47817, "pmcp-guidance.jar", "rg"),
    # v1.4.1/v1.4.2 rg (speed-limit prefix hook); v1.4.3 adds the quiet-route hold for Apple Maps (rg/lanes/hold.py)
    ("rg", "8e25ae00d155c1cf47cb7661b376c93464ea505141bf83d915b1867047f437cb", "e7222ae3bf7a796ba7a87b09774bf073d9d74689", 49045, "pmcp-guidance2.jar", "rg"),
    # v1.4.3 rg (quiet-route hold, without the Android Auto reader)
    ("rg", "7b1874847c5cf9714ed3b7e24c948b425aafc367c03a884d6309c8fda93c8661", "3cdf677c3824956b2da7546e9d69578af51030f6", 52951, "pmcp-guidance3.jar", "rg"),
    # experimental cards f2a7ceb5 / 030b7df2 / b2bcbbe3 (v1.4.1/v1.4.2 + Android Auto): rg-aa = rg with the AA reader
    ("rg-aa", "4f9215bfacb61e12cf2f1444a8b9297d2fa925d48bacd6ca6b778140088e9dc9", "c7125f3321201df065594a0ee84daecbcb3bcd67", 49388, "pmcp-guidance-aa.jar", "rg"),
    # experimental card 84472aa9 (v1.4.3 + Android Auto): rg-aa with the quiet-route hold, the same bytes as this card's rg
    # (only the file name and the package name differ, so java-update copies it once more under pmcp-guidance4.jar)
    ("rg-aa", "01221496a8670e1a2de3b54a1aa1ed8512a9931c92c1823da98e018d44c71d7c", "9af25147b2bad492cde17451966f689a37cd077f", 53309, "pmcp-guidance-aa2.jar", "rg"),
]
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
        sys.exit("lsd.sh lines around J9 differ from the MU1161 factory file: %r" % lines[j - 2:j + 2])
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

# "Install all features": the same pmcp.sh actions as the advanced buttons, run one after another, so all Java packages
# land in one set (one trial boot, one Confirm). Stops at the first failure; "already on" counts as done.
ALL_ON_SCRIPT = """#!/bin/ksh
# pmcp GEM button: %(label)s (generated by build_sd.py)
if [ -f /net/rcc/dev/shmem/backup.mib ] || [ -f /net/rcc/dev/shmem/reboot.mib ] || [ -f /net/rcc/dev/shmem/flash.mib ]; then
    echo "M.I.B. is busy with another task, try again later."
    exit 0
fi
trap '' 2
echo "pmcp: %(label)s"
echo "Do not press Back and do not remove the SD card until PMCP_ALL_ON_OK or PMCP_FAIL is shown."
PMCP=/net/mmx/fs/sda0/pmcp/pmcp.sh
NEW=0
for A in %(actions)s; do
    echo "- ${A%%%%_*} ${A#*_}"
    OUT=`/bin/ksh $PMCP ${A%%%%_*} ${A#*_} 2>&1`
    echo "$OUT" | while read L; do case "$L" in PMCP_WARN*) ;; PMCP_*) echo "  $L" ;; esac; done
    case "$OUT" in
        *PMCP_FAIL=*_ALREADY_*) echo "  (already on)" ;;
        *PMCP_FAIL*) echo "PMCP_FAIL=ALL_ON_STOPPED_AT_$A"
                     echo "The steps before this one were done. Take a photo, then use Status, or Remove everything."
                     trap 2; exit 0 ;;
        *PMCP_*_OK*) NEW=1 ;;
        *) echo "PMCP_FAIL=ALL_ON_NO_RESULT_FROM_$A"; trap 2; exit 0 ;;
    esac
done
if [ $NEW = 1 ]; then
    echo "PMCP_ALL_ON_OK"
    echo "Restart the unit (hold the volume knob ~10 s). That first start is a TRIAL."
    echo "If the map and CarPlay work: open this menu again and press 4. Confirm, in that same start."
    echo "Without Confirm the next start is the factory one again."
else
    echo "PMCP_ALL_ON_OK (everything was already on, nothing changed)"
fi
trap 2
exit 0
"""


def menu_entries():
    # (file name, pmcp arguments, GEM label). ASCII only: GEM fonts and the esd parser are not tested with other letters.
    # Main screen: the simple path. Everything else (variants, single packages) is under pmcp_advanced.
    top = [("verify", "verify", "1. Check card and unit (read-only)"),
           ("install-" + START_VARIANT, "install " + START_VARIANT, "2. Install the CarPlay map on the AID"),
           ("all-on", ALL_ON, "3. Install all features or update: map, route guidance, zoom, day/night, song title"),
           ("java-confirm", "java-confirm", "4. Confirm: everything works (only in the first start after 3)"),
           ("java-retry", "java-retry", "5. Try again: the next start is a new trial"),
           ("status", "status", "Status (read-only)"),
           ("restore", "restore", "Remove everything (back to factory files)")]
    adv = [("diag", None, "0. Diagnostics (read-only, photograph the screen)"),
           ("timeline", TIMELINE, "Start timeline: seconds from unit start to CarPlay, MOST, navigation (read-only)"),
           ("rglast", RGLAST, "RG last maneuver: what the iPhone sent and which VW arrow it gives (read-only)"),
           ("navdiag", NAVDIAG, "Navigation diagnostics: why the VW navigation does not start (read-only)"),
           # package sl (On sl, then 4. Confirm), then one of these; the mode is kept across starts
           ("speedlimit-on", "speedlimit-mode turnto", "Speed limit: in front of the street name (top bar and dial; needs sl and rg)"),
           ("speedlimit-cpi", "speedlimit-mode street", "Speed limit TRIAL: in CurrentPositionInfo only (photograph where it shows)"),
           ("speedlimit-off", "speedlimit-mode off", "Speed limit: off (street name as before)"),
           ("speedlimit-status", "speedlimit-status", "Speed limit status: mode and native VW limit data (read-only)")]
    inst = [("install-" + v, "install " + v, "Install map layout: " + v) for v in VARIANTS if v != START_VARIANT]
    sw = [("switch-" + v, "switch " + v, "Switch map layout to: " + v) for v in VARIANTS]
    rg = [("rg-system-on", "rg-system-on", "Route guidance system on (iAP2 driver, iap2.cfg, reader)"),
          ("rg-system-off", "rg-system-off", "Route guidance system off (factory iAP2 driver and iap2.cfg)"),
          ("rg-update", "rg-update", "Route guidance system update (driver and reader of this card, RG stays on)"),
          ("java-update", "java-update", "Java update: packages of an earlier card -> this card's (rglu -> rg)")]
    java = rg + [("java-on-" + n, "java-on " + n, "On " + label) for n, label in JAVA_PACKAGES] + \
           [("java-off-" + n, "java-off " + n, "Off " + label) for n, label in JAVA_PACKAGES]
    return top, adv, inst, sw, java, AA_MENU


# Android Auto (aa/), its own screen pmcp_android_auto on the main screen; installed separately from CarPlay (button 3
# neither installs nor removes it; Remove everything removes it)
AA_MENU = [("aa-on", "aa-on", "AA 1. Android Auto on: Google Maps on the AID + VW arrows (also updates an earlier card's AA)"),
           ("aa-confirm", "aa-confirm", "AA 2. Confirm: AA works (only in the start of the AA trial)"),
           ("aa-retry", "aa-retry", "AA 3. Try again: the next AA connection is a new trial"),
           ("aa-status", "aa-status", "AA status and stream analysis (read-only)"),
           ("aa-log-save", "aa-log-save", "AA save log: copy this start's AA log to the unit (for the log card)"),
           ("aa-log-clear", "aa-log-clear", "AA delete saved logs (after the log card copied them)"),
           ("aa-remove", "aa-remove", "AA remove (factory Android Auto back)")]


# actions of "Install all features or update", in order (Android Auto stays as it is: it has its own screen): an earlier
# card's RG driver/reader and Java packages replaced by
# this card's (rg-update, java-update), the main map (an older install gets START_VARIANT, already there: skipped), the
# route guidance system (rg needs it), then every package except the optional sl. Steps already done answer *_ALREADY_* and are skipped, so
# the same button brings any earlier pmcp install to this card's set.
ALL_ON = ["rg-update", "java-update", "switch_" + START_VARIANT, "rg-system-on"] + ["java-on_" + n for n, _ in JAVA_PACKAGES if n != "sl"]


def menu_script(args, label):
    if args is None:
        return DIAG_SCRIPT
    if args is TIMELINE:
        return TIMELINE_SCRIPT
    if args is NAVDIAG:
        return NAVDIAG_SCRIPT
    if args is RGLAST:
        return RGLAST_SCRIPT
    if args is ALL_ON:
        return ALL_ON_SCRIPT % dict(label=label, actions=" ".join(a if "_" in a else a + "_" for a in args))
    return MENU_SCRIPT % dict(label=label, args=args)


def esd_block(version, top, adv, inst, sw, java, aa):
    def kv(text):
        return ['keyValue', '    value   String sys 0x00000000 0', '    label   "%s"' % text, '    poll    0', '']
    def sc(name, label):
        return ['script', '    value   sys 1 0x0100 "/net/mmx/fs/sda0/pmcp/menu/%s.sh"' % name, '    label   "%s"' % label, '']
    out = ['', '#' * 91, '#', '# Main -> M.I.B. -> pmcp: CarPlay map on AID (Passat B8 MU1161 / 791), added on the SD card only',
           '#', '#' * 91, 'screen pmcp_CarPlay_AID =>M.I.B.<=', '']
    out += kv(version) + kv("Every action checks all files first and changes nothing on a mismatch. Photograph each result.")
    out += kv("After 2 and after 3: restart the unit (hold the volume knob ~10 s).")
    out += kv("Android Auto has its own screen: pmcp_android_auto (below).")
    for n, _, l in top:
        out += sc(n, l)
    out += ['screen pmcp_android_auto pmcp_CarPlay_AID', '']
    out += kv("Android Auto 0.1: Google Maps on the AID. AA 1, connect the phone, then AA 2 in that start.")
    out += kv("VW arrows from Google Maps: rg (main menu, 3). Lost picture: AA status, then AA save log.")
    for n, _, l in aa:
        out += sc(n, l)
    out += ['screen pmcp_advanced pmcp_CarPlay_AID', '']
    out += kv("Advanced: diagnostics (read-only), single packages and other map layouts.")
    for n, _, l in adv:
        out += sc(n, l)
    out += ['screen pmcp_other_layouts pmcp_advanced', '']
    for n, _, l in inst:
        out += sc(n, l)
    out += ['screen pmcp_switch_layout pmcp_advanced', '']
    for n, _, l in sw:
        out += sc(n, l)
    out += ['screen pmcp_packages pmcp_advanced', '']
    out += kv("The first start after a change is a trial: if everything works, press 4. Confirm in that start.")
    out += kv("Without Confirm the next start is the factory one (then: 5. Try again).")
    out += kv("Black screen: hold the volume knob ~10 s, the next start loads none of our JARs.")
    for n, _, l in java:
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
        for src, h, size in files:
            data = read_pinned(src, h, size, "AA_OLD_" + mode)
            pairs[h] = hashlib.sha1(data).hexdigest()
            hs.append("%s %d" % (h, size))
        assert [f[1:3] for f in files] != cur_aa, "AA_OLD tuple equals this card's AA set"
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
