#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyframe interval experiment on the fake car (docs/28; WL question 2026-11-24): can the AID picture be recovered
on demand instead of a forced IDR every 5 frames?

usage: python3 -I kf_experiment.py BUILD_DIR [quick]      (run_sim.sh must have built BUILD_DIR first)

CarPlay over Wi-Fi at 30 fps (the car plays the WL contract files; the producer = the WL receiver's core.so side).
Matrix: periodic IDR every 5 / 15 / 30 frames or none (only the first + on request) x the producer's answer to an IDR
request after 3 frames (~100 ms), 15 frames (~500 ms) or never (request lost) x disturbance:
  reverse  the channel drains at 3 % for 5 s (A203/A208 stress, harder than the car showed)
  steal    the VW encoder takes isoTX2 (reclaim)
  starve   the bridge gets no CPU for 3 s (SIGSTOP/SIGCONT): the 64-slot ring overruns
Then silent loss: 1 % of the accepted blocks lost on MOST/AID (the bridge never sees it) per periodic interval.
Reported per run: freeze = the longest gap between two pictures on the AID around the disturbance; key_after = time
from the end of the disturbance to the next keyframe on the AID; bridge latency resets, IDR requests, ring drops.
"""
import os
import re
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.abspath(sys.argv[1])
QUICK = 'quick' in sys.argv[2:]
sys.argv = [os.path.join(HERE, 'fakecar.py'), BUILD, '--none']
sys.path.insert(0, HERE)
import fakecar as fc   # noqa: E402

GOPS = [5, 15, 30, 0]
REQS = [3, 15, -1]
DISTS = ['reverse', 'steal', 'starve']
if QUICK:
    GOPS, REQS, DISTS = [5, 0], [3], ['starve']


def events(car, word):
    n = 0
    d = os.path.join(car.ram, 'pmcp-most')
    for f in ('events.log.1', 'events.log'):
        p = os.path.join(d, f)
        if os.path.exists(p):
            n += sum(1 for l in open(p, errors='replace') if word in l)
    return n


def drops(car):
    p = os.path.join(car.ram, 'pmcp-most', 'bridge.log')
    text = ''
    for f in (p + '.1', p):
        if os.path.exists(f):
            text += open(f, errors='replace').read()
    m = re.findall(r'complete frames=\d+ keys=\d+ drops=(\d+)', text)
    return int(m[-1]) if m else -1


def cp_handles(car):
    return [h for h in car.chan.handles.values() if h.tag == 'cp']


def run(dist, gop, req, loss=0.0, seconds=6.0):
    name = 'kf-%s-g%d-r%d%s' % (dist, gop, req, '-loss' if loss else '')
    saved = dict(fc.PARAMS)
    fc.PARAMS['chan_loss'] = loss
    try:
        car = fc.Car(name)
        car.boot()
        time.sleep(1)
        car.wl_start(fps=30, gop=gop, idr_on_request=req)
        time.sleep(4)
        t_d = fc.now()
        if dist == 'reverse':
            car.reverse(5)
        elif dist == 'steal':
            car.vw_steal_in(0)
            time.sleep(0.2)
        elif dist == 'starve':
            pids = car.bridge_pids()
            for p in pids:
                os.kill(p, signal.SIGSTOP)
            car.bb.rec('car', 'starve bridge %s' % pids)
            time.sleep(3)
            for p in pids:
                os.kill(p, signal.SIGCONT)
        t_e = fc.now()
        time.sleep(seconds)
        car.wl_stop('done')
        time.sleep(1.5)
        car.shutdown()
    finally:
        fc.PARAMS.clear()
        fc.PARAMS.update(saved)
    pics = sorted(t for h in cp_handles(car) for t in h.pic_times)
    keys = sorted(t for h in cp_handles(car) for t in h.key_times)
    win = [t for t in pics if t_d - 0.5 <= t <= t_e + seconds]
    freeze = max((b - a for a, b in zip(win, win[1:])), default=None)
    ka = [t for t in keys if t >= t_e]
    key_after = ka[0] - t_e if ka else None
    if key_after is None and [t for t in pics if t > t_e + 0.5] == []:
        freeze = float('inf')   # no picture after the disturbance at all: the AID never recovered
    broken = sum(b - a for h in cp_handles(car) for a, b in h.broken)
    open_b = [h.broken_since for h in cp_handles(car) if h.broken_since is not None]
    span = (pics[-1] - pics[0]) if len(pics) > 1 else 1.0
    if open_b and pics:
        broken += max(0.0, pics[-1] - min(open_b))
    return dict(name=name, dist=dist, gop=gop, req=req, freeze=freeze, key_after=key_after,
                resets=events(car, 'latency-reset'), idr_req=events(car, 'idr-request'), drops=drops(car),
                keys_per_s=len(keys) / span if span else 0, broken_pct=100.0 * broken / span if span else 0)


def fmt(x, unit='s'):
    if x == float('inf'):
        return 'NO RECOVERY'
    return '-' if x is None else ('%.2f %s' % (x, unit)).strip()


def main():
    rows = []
    for dist in DISTS:
        for gop in GOPS:
            for req in REQS:
                r = run(dist, gop, req)
                rows.append(r)
                print('%-24s freeze=%s key_after=%s resets=%d idr_req=%d drops=%d' % (
                    r['name'], fmt(r['freeze']), fmt(r['key_after']), r['resets'], r['idr_req'], r['drops']),
                    flush=True)
    loss_rows = []
    for gop in ([5, 0] if QUICK else GOPS):
        r = run('none', gop, 3, loss=0.01, seconds=10.0)
        loss_rows.append(r)
        print('%-24s broken=%.1f%% keys/s=%.1f idr_req=%d' % (r['name'], r['broken_pct'], r['keys_per_s'],
                                                              r['idr_req']), flush=True)
    out = ['# Keyframe experiment (fake car, %s)' % time.strftime('%Y-%m-%d %H:%M'), '',
           'GOP = periodic IDR every N frames at 30 fps (0 = only the first + on request); request answered after N',
           'frames (3 ~ 100 ms, 15 ~ 500 ms, -1 = lost). freeze = longest picture gap on the AID around the',
           'disturbance; key_after = from the end of the disturbance to the next keyframe on the AID.', '',
           '| disturbance | GOP | IDR request | freeze | key_after | bridge resets | IDR requests | ring drops |',
           '|---|---|---|---|---|---|---|---|']
    for r in rows:
        out.append('| %s | %s | %s | %s | %s | %d | %d | %d |' % (
            r['dist'], r['gop'] or 'none', {3: '100 ms', 15: '500 ms', -1: 'lost'}[r['req']], fmt(r['freeze']),
            fmt(r['key_after']), r['resets'], r['idr_req'], r['drops']))
    out += ['', 'Silent loss (1 % of the blocks lost after the bridge; the bridge cannot see it):', '',
            '| GOP | keyframes/s on the AID | broken picture time | IDR requests |', '|---|---|---|---|']
    for r in loss_rows:
        out.append('| %s | %.1f | %.1f %% | %d |' % (r['gop'] or 'none', r['keys_per_s'], r['broken_pct'],
                                                  r['idr_req']))
    path = os.path.join(BUILD, 'kf-experiment.md')
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
    print('\n'.join(out))
    print('written', path)


if __name__ == '__main__':
    main()
