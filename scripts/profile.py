#!/usr/bin/env python3
"""Firmware profiles (profiles/<ID>/profile.json): the facts about one unit firmware that the build pins.

  profile.py get <ID> <key[.sub...]>    value (lists: one item per line, objects: JSON)
  profile.py validate [<ID>...]         check every (or the given) profile against the schema below
  profile.py detect <train> <mu>        the one profile with exactly this train and MU, else exit 1
  profile.py list                       profile ids

From Python: sys.path.insert(0, <repo>/scripts); import profile as fwprofile; p = fwprofile.load("MU1161").
Run with python3 -I. Standard library only. A profile is data the build trusts, so validation is strict:
unknown keys, wrong types, malformed hashes or a directory name that differs from "id" all stop the build.
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "profiles")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^[A-Z0-9]+$")
PACKAGES = {"nai", "np", "rg", "zoom", "dn", "sl", "ui", "aa"}
STOCK_KEYS = {"IAP2DRV", "IAP2CFG", "LSD", "DIO", "GAL"}
LSD_STATES = {"stock", "toolbox_nai"}
KEYS = {"schema": int, "id": str, "cluster": str, "version_tag": str, "label": str, "car": str, "train": str,
        "mu": str, "backup_dir": str, "appimg": str, "system": str, "lsd_jxe": dict, "lsd_jar_sha256": list,
        "props": dict, "stock": dict, "lsd_sh_states": list, "mathsls_payload": str, "mathsls_commit": str,
        "rg_driver_in_sha256": str, "packages": list}


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
    if not re.match(r"^[0-9]{4}$", p["mu"]):
        fail("%s: mu %r" % (pid, p["mu"]))
    if not re.match(r"^[a-z0-9-]+$", p["version_tag"]):
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
    if not re.match(r"^[0-9a-f]{40}$", p["mathsls_commit"]):
        fail("%s: mathsls_commit %r" % (pid, p["mathsls_commit"]))
    return p


def ids():
    return sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "profile.json")))


def load(pid):
    if not (isinstance(pid, str) and ID.match(pid)):
        fail("bad profile id %r" % (pid,))
    path = os.path.join(ROOT, pid, "profile.json")
    if not os.path.isfile(path):
        fail("no profile %s (known: %s)" % (pid, " ".join(ids())))
    with open(path, encoding="utf-8") as f:
        return validate(json.load(f), pid)


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
            load(i)
            print("ok " + i)
    elif len(argv) == 4 and argv[1] == "detect":
        print(detect(argv[2], argv[3]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
