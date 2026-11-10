#!/usr/bin/env python3
"""Run one scenario against the host bridge (and optionally harman-f) and save the golden files.

usage: python3 -I tools/run_scenario.py SCENARIO [--bridge build/altscreen-most-bridge-host]
         [--out golden/SCENARIO] [--harman] [--idr-on-request N] [--env K=V ...] [--drain S]

golden/<scenario>/
  mlb.ts            every byte the bridge wrote to the simulated isoTX2 (12032-byte blocks)
  mlb.ts.log        open / devctl (code, value, status) / every accepted write (size, ret, EAGAINs) / close
  bridge.stderr     the bridge's own log
  input/frames.jsonl, input/input.h264   what the driver put into the ring
  norm.json, timing.json, summary.txt    analyser output
  harman/...        the same for harman-f direct_ts_parity (with --harman)
"""
import argparse, os, shutil, signal, subprocess, sys, time

S = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = [sys.executable, '-I']


def run_bridge(a, out, run):
    os.makedirs(os.path.join(out, 'input'), exist_ok=True)
    env = {'PATH': '/usr/bin:/bin', 'HOST_RING_PATH': os.path.join(run, 'ring.bin'),
           'HOST_IDR_PATH': os.path.join(run, 'force-idr.request'),
           'HOST_INTRO_ONCE_PATH': os.path.join(run, 'intro-played')}
    for kv in a.env:
        k, v = kv.split('=', 1); env[k] = v
    ts = os.path.join(out, 'mlb.ts')
    err = open(os.path.join(out, 'bridge.stderr'), 'wb')
    br = subprocess.Popen([os.path.join(S, a.bridge), ts], cwd=run, env=env, stdout=err, stderr=err)
    try:
        drv = [*PY, os.path.join(S, 'tools/ring_driver.py'), '--scenario', a.scenario,
               '--out', os.path.join(out, 'input'), '--ring', env['HOST_RING_PATH'],
               '--idr-path', env['HOST_IDR_PATH'], '--idr-on-request', str(a.idr_on_request)]
        if a.h264: drv += ['--h264', a.h264]
        rc = subprocess.call(drv, cwd=run)
        time.sleep(a.drain)
    finally:
        br.send_signal(signal.SIGTERM)
        try: br.wait(10)
        except subprocess.TimeoutExpired: br.kill(); br.wait()
    err.close()
    if os.path.exists(os.path.join(run, 'force-idr.request')):
        open(os.path.join(out, 'input', 'idr-request-left'), 'w').write('request file present at stop\n')
    return rc


def run_harman(a, out, run):
    hd = os.path.join(out, 'harman'); os.makedirs(os.path.join(hd, 'input'), exist_ok=True)
    env = {'PATH': '/usr/bin:/bin', 'MIBR_PARITY_STATUS': '0'}
    port = 17300 + (os.getpid() % 500)
    err = open(os.path.join(hd, 'bridge.stderr'), 'wb')
    hr = os.path.join(S, 'build/harman-run')
    drv = subprocess.Popen([*PY, os.path.join(S, 'tools/ring_driver.py'), '--scenario', a.scenario,
                            '--out', os.path.join(hd, 'input'), '--m1au', str(port),
                            '--idr-path', os.path.join(hr, 'mibr-alt111-recovery.request'),
                            '--idr-path', os.path.join(hr, 'mibr-alt111-keyframe-only'),
                            '--idr-on-request', str(a.idr_on_request), '--ignore-requests-first', '3']
                           + (['--h264', a.h264] if a.h264 else []), cwd=run)
    time.sleep(0.5)
    hb = subprocess.Popen([os.path.join(S, 'build/direct-ts-parity-host'), f'tcp://127.0.0.1:{port}',
                           os.path.join(hd, 'mlb.ts')], cwd=run, env=env, stdout=err, stderr=err)
    drv.wait()
    try: hb.wait(20)
    except subprocess.TimeoutExpired: hb.send_signal(signal.SIGTERM); hb.wait(5)
    err.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('scenario')
    ap.add_argument('--bridge', default='build/altscreen-most-bridge-host')
    ap.add_argument('--out')
    ap.add_argument('--harman', action='store_true')
    ap.add_argument('--idr-on-request', type=int, default=1)
    ap.add_argument('--env', action='append', default=[])
    ap.add_argument('--drain', type=float, default=1.5)
    ap.add_argument('--h264')
    a = ap.parse_args()
    if a.h264: a.h264 = os.path.abspath(a.h264)
    out = os.path.abspath(a.out or os.path.join(S, 'golden', a.scenario))
    run = os.path.join(S, 'run', os.path.basename(out))
    for d in (out, run):
        shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    run_bridge(a, out, run)
    rc = subprocess.call([*PY, os.path.join(S, 'tools/ts_analyse.py'), out])
    if a.harman:
        run_harman(a, out, run)
        subprocess.call([*PY, os.path.join(S, 'tools/ts_analyse.py'), os.path.join(out, 'harman')])
        subprocess.call([*PY, os.path.join(S, 'tools/ts_compare.py'), out, os.path.join(out, 'harman')])
    shutil.rmtree(run, ignore_errors=True)   # the 16 MB ring is not kept
    sys.exit(rc)


if __name__ == '__main__':
    main()
