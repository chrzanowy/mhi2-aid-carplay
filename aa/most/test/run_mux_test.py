"""Host unit test for aa/most/ts_mux against the bridge-stage0 golden captures (python3 -I).

usage: python3 -I run_mux_test.py GOLDEN_ROOT OUT_DIR [CC]
  GOLDEN_ROOT  bridge-stage0/golden (one directory per scenario: input/input.h264, input/frames.jsonl, norm.json, ...)
  OUT_DIR      scratch directory for the replay binary and the runs

For every golden scenario the golden input is replayed through ts_mux on a virtual clock (ts_mux_replay.c), the TS
is decoded by the stage 0 analyser (ts_analyse.py, a verbatim copy) and compared by ts_compare.py --mode aa.
Accepted differences, each a documented decision (README of the bridge, "differences"):
  - discontinuity flag: set on our first AU (harman-f), and not on the golden's resume-after-reset IDRs (we never
    reset);
  - frames missing in the golden (its latency resets) are present here: --mode aa requires every input frame.
Everything else must be equal: transport checks, PIDs, PAT/PMT/PCR bytes and cadence, CC, and per frame the IDR /
random-access flags, AUD, SPS/PPS, NAL types, start codes, Annex-B size, packet count, byte-exact packetization and
the payload hash. Extra checks: the lead PTS - PCR(first packet) >= 4500 for every AU, and a 2 s device stall.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = [sys.executable, '-I']
fails = []


def check(cond, msg):
    print(('ok    ' if cond else 'FAILED ') + msg)
    if not cond:
        fails.append(msg)


def main():
    golden_root, out = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    cc = sys.argv[3] if len(sys.argv) > 3 else 'cc'
    os.makedirs(out, exist_ok=True)
    exe = os.path.join(out, 'ts_mux_replay')
    subprocess.check_call([cc, '-O2', '-Wall', '-Wextra', '-Werror', '-std=gnu99', '-pthread', '-o', exe,
                           os.path.join(HERE, 'ts_mux_replay.c'), os.path.join(HERE, '..', 'ts_mux.c')])
    for sc, extra in (('steady', []), ('burst', []), ('gap', []), ('large-idr', []), ('large-run', []),
                      ('steady-stall', ['--stall-at', '300', '--stall-ms', '2000'])):
        g = os.path.join(golden_root, sc)
        run = os.path.join(out, 'mux-' + sc)
        os.makedirs(os.path.join(run, 'input'), exist_ok=True)
        frames = [json.loads(l) for l in open(os.path.join(g, 'input', 'frames.jsonl'))]
        with open(os.path.join(run, 'input', 'frames.jsonl'), 'w') as f:
            for x in frames: f.write(json.dumps(x) + '\n')
        t = [x['t_us'] for x in frames if 'frame_no' in x and 'ring_seq' in x]
        with open(os.path.join(run, 'times.txt'), 'w') as f:
            f.write(''.join('%d\n' % v for v in t))
        r = subprocess.run([exe, os.path.join(g, 'input', 'input.h264'), os.path.join(run, 'times.txt'),
                            os.path.join(run, 'mlb.ts')] + extra, capture_output=True, text=True)
        summ = [l for l in r.stdout.split('\n') if l.startswith('summary')]
        check(r.returncode == 0, '%s: replay rc=%d %s %s' % (sc, r.returncode, summ, r.stderr.strip()[:200]))
        a = subprocess.run([*PY, os.path.join(HERE, 'ts_analyse.py'), run], capture_output=True, text=True)
        check(a.returncode == 0, '%s: analyser passes\n%s' % (sc, a.stdout.strip()))
        c = subprocess.run([*PY, os.path.join(HERE, 'ts_compare.py'), g, run, '--mode', 'aa', '--lead-min', '4500'],
                           capture_output=True, text=True)
        diffs = [l[5:] for l in c.stdout.split('\n') if l.startswith('DIFF ')]
        gn = json.load(open(os.path.join(g, 'norm.json')))
        cn = json.load(open(os.path.join(run, 'norm.json')))
        ct = json.load(open(os.path.join(run, 'timing.json')))
        other = [d for d in diffs if not d.startswith('au.discontinuity differs')]
        check(not other, '%s: only documented differences from the golden %s' % (sc, other))
        ga = {x['frame_no']: x for x in gn['aus'] if x['frame_no'] is not None}
        ca = {x['frame_no']: x for x in cn['aus'] if x['frame_no'] is not None}
        first = cn['aus'][0]['frame_no'] if cn['aus'] else None
        want_disc = {first}
        got_disc = {fn for fn, x in ca.items() if x['discontinuity']}
        gold_disc = {fn for fn, x in ga.items() if x['discontinuity']}
        check(got_disc == want_disc, '%s: discontinuity only on our first AU %s (golden had it on %s)'
              % (sc, sorted(got_disc), sorted(gold_disc)))
        dd = [fn for fn in set(ga) & set(ca) if ga[fn]['discontinuity'] != ca[fn]['discontinuity']]
        check(set(dd) <= (gold_disc | want_disc), '%s: discontinuity differs only there %s' % (sc, sorted(dd)))
        check(cn['output_aus'] == cn['input_frames'] and not cn['missing_frame_nos'],
              '%s: every input frame out once, in order (%d/%d; golden %d)' % (sc, cn['output_aus'], cn['input_frames'],
                                                                            gn['output_aus']))
        same = sum(1 for fn in set(ga) & set(ca) if all(ga[fn][k] == ca[fn][k] for k in
                   ('idr', 'random_access', 'aud_first', 'sps_pps', 'nal_types', 'start_codes', 'annexb_bytes',
                    'packets', 'packetization_exact', 'avcc_sha256')))
        check(same == len(set(ga) & set(ca)), '%s: %d/%d frames present in both identical apart from the flag'
              % (sc, same, len(set(ga) & set(ca))))
        check(ct['lead_90k_min'] is not None and ct['lead_90k_min'] >= 4500,
              '%s: PTS lead min=%s max=%s (golden %s..%s)' % (sc, ct['lead_90k_min'], ct['lead_90k_max'],
                                                             json.load(open(os.path.join(g, 'timing.json')))['lead_90k_min'],
                                                             json.load(open(os.path.join(g, 'timing.json')))['lead_90k_max']))
        print('   ', summ[0] if summ else '')
    print('FAILED CHECKS: %d' % len(fails))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
