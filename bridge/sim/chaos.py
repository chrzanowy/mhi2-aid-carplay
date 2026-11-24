#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""fake-car stage 4 (docs/28): random seeded drives, long runs and shrinking of a failing drive.

usage: python3 -I chaos.py BUILD_DIR [--seeds N] [--first S] [--steps M] [--shrink K]
       python3 -I chaos.py BUILD_DIR --replay FILE.json          (a saved sequence, e.g. a shrunk one)
(run_sim.sh must have built BUILD_DIR.) Every drive is fakecar.chaos_gen(seed, steps) played by fakecar.chaos_run:
liveness of the AID at every calm check point plus all the common invariants. A failing drive is shrunk by dropping
steps while the same kind of failure still comes back (at most K replays; each replay costs the drive's real time,
and a timing failure may not come back). Results: BUILD_DIR/chaos/seed-<n>.json (sequence, failures, shrunk).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS = sys.argv[1:]
BUILD = os.path.abspath(ARGS[0])
sys.argv = [os.path.join(HERE, 'fakecar.py'), BUILD, '--none']
sys.path.insert(0, HERE)
import fakecar as fc   # noqa: E402


def opt(name, default):
    return type(default)(ARGS[ARGS.index(name) + 1]) if name in ARGS else default


def kinds(failures):
    """'chaos-7-r3: step 12 (aa_plug) AID shows aa' -> 'AID shows aa' (the kind, without run name and step)."""
    return {re.sub(r'^[^:]*: (step \d+ \([^)]*\) )?', '', f) for f in failures}


def shrink(seed, seq, failures, budget):
    want = kinds(failures)
    best = seq
    n = 0
    i = 0
    while i < len(best) - 1 and n < budget:      # never drop the final 'end'
        cand = best[:i] + best[i + 1:]
        n += 1
        got = fc.chaos_run('chaos-%d-s%d' % (seed, n), cand)
        if got and kinds(got) & want:
            best = cand                          # still fails the same way without step i: keep it out
            print('  shrink %d: %d steps still fail (%s)' % (n, len(best), sorted(kinds(got) & want)), flush=True)
        else:
            i += 1
    return best, n


def main():
    out_dir = os.path.join(BUILD, 'chaos')
    os.makedirs(out_dir, exist_ok=True)
    if '--replay' in ARGS:
        path = ARGS[ARGS.index('--replay') + 1]
        seq = json.load(open(path))
        seq = seq.get('shrunk') or seq.get('seq') if isinstance(seq, dict) else seq
        fails = fc.chaos_run('chaos-replay', seq)
        print('REPLAY: %d failed %s' % (len(fails), fails))
        return 1 if fails else 0
    seeds, first, steps, budget = opt('--seeds', 3), opt('--first', 1), opt('--steps', 30), opt('--shrink', 12)
    bad = 0
    t0 = time.time()
    for seed in range(first, first + seeds):
        seq = fc.chaos_gen(seed, steps)
        fails = fc.chaos_run('chaos-%d' % seed, seq)
        rec = dict(seed=seed, steps=steps, seq=seq, failures=fails)
        print('seed %d: %d steps, %s' % (seed, steps, 'ok' if not fails else 'FAILED %s' % fails), flush=True)
        if fails:
            bad += 1
            rec['shrunk'], rec['shrink_runs'] = shrink(seed, seq, fails, budget)
            print('  shrunk to %d steps after %d replays' % (len(rec['shrunk']), rec['shrink_runs']), flush=True)
        with open(os.path.join(out_dir, 'seed-%d.json' % seed), 'w') as f:
            json.dump(rec, f, indent=1)
    print('CHAOS: %d seeds, %d failed, %.0f min' % (seeds, bad, (time.time() - t0) / 60))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
