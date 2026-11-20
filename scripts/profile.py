#!/usr/bin/env python3
"""Firmware profiles (profiles/<ID>/profile.json): the facts about one unit firmware that the build pins.

  profile.py get <ID> <key[.sub...]>    value (lists: one item per line, objects: JSON)
  profile.py validate [<ID>...]         check every (or the given) profile against the schema below
  profile.py detect <train> <mu>        the one profile with exactly this train and MU, else exit 1
  profile.py list                       profile ids
  profile.py pins <ID>                  "<path in the M.I.B. backup folder> <sha256>" per line: lsd.jxe and the stock files
  (validate also checks profiles/<ID>/history.json, the older card files this profile's installer still replaces)

From Python: sys.path.insert(0, <repo>/scripts); import profile as fwprofile; p = fwprofile.load("MU1161").
Run with python3 -I. Standard library only. A profile is data the build trusts, so validation is strict:
unknown keys, wrong types, malformed hashes or a directory name that differs from "id" all stop the build.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "profiles")
HEX64 = re.compile(r"^[0-9a-f]{64}\Z")
ID = re.compile(r"^[A-Z0-9]+\Z")
PACKAGES = {"nai", "np", "rg", "zoom", "dn", "sl", "ui", "aa"}
STOCK_KEYS = {"IAP2DRV", "IAP2CFG", "LSD", "DIO", "GAL", "DMJSON"}
LSD_STATES = {"stock", "toolbox_nai"}
KEYS = {"schema": int, "id": str, "cluster": str, "version_tag": str, "label": str, "car": str, "train": str, "train_full": str,
        "mu": str, "backup_dir": str, "appimg": str, "system": str, "lsd_jxe": dict, "lsd_jar_sha256": list,
        "props": dict, "stock": dict, "lsd_sh_states": list, "mathsls_payload": str, "mathsls_commit": str,
        "rg_driver_in_sha256": str, "packages": list}


def _no_dups(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            fail("duplicate key %r in JSON" % (k,))
        d[k] = v
    return d


def _json(f):
    return json.load(f, object_pairs_hook=_no_dups)


def _relpath(v, what):
    """A path inside the backup folder: relative, not empty, no '..', no empty or '.' parts."""
    if not (isinstance(v, str) and v and not v.startswith("/") and "\\" not in v
            and all(x not in ("", ".", "..") for x in v.split("/"))):
        fail("%s: not a plain relative path: %r" % (what, v))


def _unique(v, what):
    if len(set(map(str, v))) != len(v):
        fail("%s: duplicate entries" % what)


def fail(msg):
    sys.exit("profile: " + msg)


def _hash(v, what):
    if not (isinstance(v, str) and HEX64.match(v)):
        fail("%s: not a lowercase sha256: %r" % (what, v))


def _size(v, what):
    if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
        fail("%s: not a positive size: %r" % (what, v))


def validate(p, pid):
    if set(p) != set(KEYS):
        fail("%s: keys differ from the schema: missing %s, unknown %s"
             % (pid, sorted(set(KEYS) - set(p)), sorted(set(p) - set(KEYS))))
    for k, t in KEYS.items():
        if not isinstance(p[k], t) or isinstance(p[k], bool):
            fail("%s: %s is not %s" % (pid, k, t.__name__))
    if p["schema"] != 1:
        fail("%s: schema %r, this tool knows 1" % (pid, p["schema"]))
    if p["id"] != pid or not ID.match(pid):
        fail("profile directory %s holds id %r" % (pid, p["id"]))
    if not p["train_full"].startswith(p["train"]):
        fail("%s: train_full %r does not start with train %r" % (pid, p["train_full"], p["train"]))
    if not re.match(r"^[0-9]{4}\Z", p["mu"]):
        fail("%s: mu %r" % (pid, p["mu"]))
    if not re.match(r"^[a-z0-9-]+\Z", p["version_tag"]):
        fail("%s: version_tag %r" % (pid, p["version_tag"]))
    j = p["lsd_jxe"]
    if set(j) != {"file", "size", "sha256"} or not isinstance(j["file"], str):
        fail("%s: lsd_jxe needs file, size, sha256" % pid)
    _size(j["size"], pid + " lsd_jxe.size")
    _hash(j["sha256"], pid + " lsd_jxe.sha256")
    if not p["lsd_jar_sha256"]:
        fail("%s: lsd_jar_sha256 is empty" % pid)
    for h in p["lsd_jar_sha256"]:
        _hash(h, pid + " lsd_jar_sha256")
    for k, v in p["props"].items():
        if not (isinstance(v, int) and not isinstance(v, bool)):
            fail("%s: props.%s is not an int" % (pid, k))
    if set(p["stock"]) != STOCK_KEYS:
        fail("%s: stock keys %s, expected %s" % (pid, sorted(p["stock"]), sorted(STOCK_KEYS)))
    for k, v in p["stock"].items():
        if not (isinstance(v, list) and len(v) == 3 and isinstance(v[0], str)):
            fail("%s: stock.%s is not [path, sha256, size]" % (pid, k))
        if v[0].startswith("/") or ".." in v[0].split("/"):
            fail("%s: stock.%s path %r" % (pid, k, v[0]))
        _hash(v[1], "%s stock.%s" % (pid, k))
        _size(v[2], "%s stock.%s" % (pid, k))
    if not p["lsd_sh_states"] or not set(p["lsd_sh_states"]) <= LSD_STATES or p["lsd_sh_states"][0] != "stock":
        fail("%s: lsd_sh_states %r (first must be stock; known %s)" % (pid, p["lsd_sh_states"], sorted(LSD_STATES)))
    if not set(p["packages"]) <= PACKAGES or len(set(p["packages"])) != len(p["packages"]):
        fail("%s: packages %r (known %s)" % (pid, p["packages"], sorted(PACKAGES)))
    _hash(p["rg_driver_in_sha256"], pid + " rg_driver_in_sha256")
    if not re.match(r"^[0-9a-f]{40}\Z", p["mathsls_commit"]):
        fail("%s: mathsls_commit %r" % (pid, p["mathsls_commit"]))
    if not re.match(r"^[0-9]{3}\Z", p["cluster"]):
        fail("%s: cluster %r (three digits, e.g. 791)" % (pid, p["cluster"]))
    if not re.match(r"^[A-Z0-9]+(_[A-Z0-9]+)+\Z", p["train"]):
        fail("%s: train %r" % (pid, p["train"]))
    if not re.match(r"^[A-Z0-9_]+\Z", p["train_full"]):
        fail("%s: train_full %r" % (pid, p["train_full"]))
    if p["backup_dir"] != "MU" + p["mu"]:
        fail("%s: backup_dir %r must be MU<mu>" % (pid, p["backup_dir"]))
    for k in ("appimg", "system", "mathsls_payload"):
        _relpath(p[k], "%s %s" % (pid, k))
    _relpath(p["lsd_jxe"]["file"], pid + " lsd_jxe.file")
    if "/" in p["lsd_jxe"]["file"]:
        fail("%s: lsd_jxe.file %r must be a file name" % (pid, p["lsd_jxe"]["file"]))
    for k, v in p["stock"].items():
        _relpath(v[0][len("@system/"):] if v[0].startswith("@system/") else v[0], "%s stock.%s" % (pid, k))
    if not p["packages"]:
        fail("%s: packages is empty" % pid)
    if not p["props"]:
        fail("%s: props is empty" % pid)
    for k in ("lsd_jar_sha256", "lsd_sh_states", "packages"):
        _unique(p[k], "%s %s" % (pid, k))
    for k in ("label", "car"):
        if not p[k] or "\n" in p[k] or "\r" in p[k]:
            fail("%s: %s must be one non-empty line" % (pid, k))
    return p


HEX40 = re.compile(r"^[0-9a-f]{40}\Z")
HISTORY_KEYS = {"schema", "java_renamed_note", "java_renamed", "rg_known_note", "rg_known", "lsd_known_note", "lsd_known"}


def _hist_hashes(h, h1, size, what):
    _hash(h, what)
    if not (isinstance(h1, str) and HEX40.match(h1)):
        fail("%s: not a lowercase sha1: %r" % (what, h1))
    _size(size, what)


def validate_history(h, pid):
    """history.json = what older cards of this profile left on a unit that this card must still recognise: renamed
    Java packages (by name) and the earlier pmcp route guidance files that replaced factory files (rg_known, hashes).
    Earlier Java packages and AA sets need no list since A188 (pmcp.sh recognises them by name / our wrapper)."""
    if not isinstance(h, dict) or set(h) != HISTORY_KEYS:
        fail("%s history: keys differ from the schema %s" % (pid, sorted(HISTORY_KEYS)))
    if h["schema"] != 2:
        fail("%s history: schema %r" % (pid, h["schema"]))
    for k in ("java_renamed_note", "rg_known_note", "lsd_known_note"):
        if not isinstance(h[k], str):
            fail("%s history: %s is not a string" % (pid, k))
    if not isinstance(h["java_renamed"], dict):
        fail("%s history: java_renamed is not an object" % pid)
    for old, new in h["java_renamed"].items():
        if not re.match(r"^[a-z0-9-]+\Z", old) or new not in PACKAGES or old in PACKAGES:
            fail("%s history: java_renamed %r -> %r (old: a name no package has, new: a package)" % (pid, old, new))
    if not isinstance(h["rg_known"], list) or not all(isinstance(e, dict) for e in h["rg_known"]):
        fail("%s history: rg_known is not a list of objects" % pid)
    for e in h["rg_known"]:
        if set(e) - {"note"} != {"kind", "sha256", "sha1", "size"} or e["kind"] not in ("DRIVER", "READER"):
            fail("%s history: rg_known entry needs kind DRIVER|READER, sha256, sha1, size: %r" % (pid, e))
        _hist_hashes(e["sha256"], e["sha1"], e["size"], pid + " history rg_known")
        if "note" in e and not isinstance(e["note"], str):
            fail("%s history: rg_known note is not a string" % pid)
    _unique([json.dumps({x: y for x, y in e.items() if x != "note"}, sort_keys=True) for e in h["rg_known"]],
            "%s history rg_known" % pid)
    if not isinstance(h["lsd_known"], list) or not all(isinstance(e, dict) for e in h["lsd_known"]):
        fail("%s history: lsd_known is not a list of objects" % pid)
    for e in h["lsd_known"]:
        if set(e) - {"note"} != {"sha256", "sha1", "size"}:
            fail("%s history: lsd_known entry needs sha256, sha1, size: %r" % (pid, e))
        _hist_hashes(e["sha256"], e["sha1"], e["size"], pid + " history lsd_known")
    _unique([e["sha256"] for e in h["lsd_known"]], "%s history lsd_known" % pid)
    return h


def ids():
    return sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "profile.json")))


def load(pid):
    if not (isinstance(pid, str) and ID.match(pid)):
        fail("bad profile id %r" % (pid,))
    path = os.path.join(ROOT, pid, "profile.json")
    if not os.path.isfile(path):
        fail("no profile %s (known: %s)" % (pid, " ".join(ids())))
    with open(path, encoding="utf-8") as f:
        return validate(_json(f), pid)


def load_history(pid):
    load(pid)
    path = os.path.join(ROOT, pid, "history.json")
    if not os.path.isfile(path):
        fail("%s: no history.json" % pid)
    with open(path, encoding="utf-8") as f:
        return validate_history(_json(f), pid)


def pins(p):
    """Files the build reads from the unit's M.I.B. backup folder, with their pins (stock paths: appimg, or system for @system/)."""
    out = [(p["lsd_jxe"]["file"], p["lsd_jxe"]["sha256"])]
    for k in ("LSD", "DIO", "IAP2DRV", "IAP2CFG", "GAL", "DMJSON"):
        path, h, _ = p["stock"][k]
        out.append((p["system"] + "/" + path[len("@system/"):] if path.startswith("@system/") else p["appimg"] + "/" + path, h))
    return out


def detect(train, mu):
    hits = [i for i in ids() if load(i)["train"] == train and load(i)["mu"] == mu]
    if len(hits) != 1:
        fail("no single profile for train %s MU%s (matches: %s; known: %s)"
             % (train, mu, " ".join(hits) or "none", " ".join(ids())))
    return hits[0]


def get(p, key):
    v = p
    for part in key.split("."):
        if not isinstance(v, dict) or part not in v:
            fail("%s: no key %s" % (p["id"], key))
        v = v[part]
    return v


def main(argv):
    if len(argv) >= 2 and argv[1] == "list":
        print("\n".join(ids()))
    elif len(argv) == 4 and argv[1] == "get":
        v = get(load(argv[2]), argv[3])
        if isinstance(v, list):
            print("\n".join(str(x) if not isinstance(x, (list, dict)) else json.dumps(x) for x in v))
        elif isinstance(v, dict):
            print(json.dumps(v, sort_keys=True))
        else:
            print(v)
    elif len(argv) >= 2 and argv[1] == "validate":
        for i in argv[2:] or ids():
            load_history(i)
            print("ok " + i)
    elif len(argv) == 3 and argv[1] == "pins":
        print("\n".join("%s %s" % x for x in pins(load(argv[2]))))
    elif len(argv) == 4 and argv[1] == "detect":
        print(detect(argv[2], argv[3]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
