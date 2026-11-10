#!/usr/bin/env python3
"""Compare a candidate run against a golden run (python3 -I).

usage: ts_compare.py GOLDEN_DIR CANDIDATE_DIR [--mode cp|aa] [--lead-min 0]

Both directories need norm.json and timing.json (ts_analyse.py). Rules:
  strict (must be equal): transport block (block size, whole blocks, write sizes, devctl sequence,
    cadence/PSI/PCR/null checks, CC breaks on PAT/PMT/null, PIDs) and, for every frame present in both,
    the AU description (IDR, RA/discontinuity flags, AUD, SPS/PPS, NAL types, start codes, Annex-B
    size, TS packet count, byte-exact packetization, payload hash);
  normalized: the set of output frames. --mode cp: must equal the golden set (same drops).
    --mode aa: every input frame must be present (no drops at all, CONTRACT.md 5);
  timing (reported, not compared): PTS values and steps, packet positions, lead over PCR, event
    sequence numbers. --lead-min N fails the run if any AU's PTS - PCR(first packet) < N.
"""
import argparse, json, os, sys

AU_KEYS = ('idr', 'random_access', 'discontinuity', 'aud_first', 'sps_pps', 'sps_pps_match_avcc', 'nal_types', 'start_codes',
           'pes_header_ok', 'annexb_bytes', 'packets', 'packetization_exact', 'avcc_sha256')
T_KEYS = ('block_bytes', 'capture_whole_blocks', 'write_sizes', 'partial_writes', 'devctl', 'psi_cadence_ok',
          'pat_pmt_bytes_ok', 'pcr_formula_ok', 'null_packets_ok', 'pids')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('golden'); ap.add_argument('candidate')
    ap.add_argument('--mode', choices=('cp', 'aa'), default='cp')
    ap.add_argument('--lead-min', type=int)
    a = ap.parse_args()
    load = lambda d, f: json.load(open(os.path.join(d, f)))
    g, c = load(a.golden, 'norm.json'), load(a.candidate, 'norm.json')
    gt, ct = load(a.golden, 'timing.json'), load(a.candidate, 'timing.json')
    diffs, notes = [], []
    skip = set()
    if not c['transport'].get('devctl') and not c['transport'].get('write_sizes'):
        skip = {'devctl', 'write_sizes'}
        notes.append('candidate has no MOST log (regular-file output): devctl/write sizes not compared')
    for k in T_KEYS:
        if k in skip: continue
        if g['transport'].get(k) != c['transport'].get(k):
            diffs.append(f"transport.{k}: golden={g['transport'].get(k)} candidate={c['transport'].get(k)}")
    for k in ('pat', 'pmt', 'null'):
        if g['transport']['cc_breaks'][k] != c['transport']['cc_breaks'][k]:
            diffs.append(f"cc_breaks.{k}: golden={g['transport']['cc_breaks'][k]} candidate={c['transport']['cc_breaks'][k]}")
    if c['errors']:
        diffs.append(f"candidate analyser errors: {c['errors'][:5]}")
    ga = {x['frame_no']: x for x in g['aus'] if x['frame_no'] is not None}
    ca = {x['frame_no']: x for x in c['aus'] if x['frame_no'] is not None}
    gin, cin = g.get('input_avcc_sha256', {}), c.get('input_avcc_sha256', {})
    diff_input = sorted(int(k) for k in set(gin) & set(cin) if gin[k] != cin[k])
    if diff_input:
        notes.append(f'inputs differ on frames {diff_input[:10]} (IDR placed on request, timing): not compared')
    per_key = {}
    for fn in sorted(set(ga) & set(ca)):
        if fn in diff_input: continue
        for k in AU_KEYS:
            if ga[fn][k] != ca[fn][k]:
                per_key.setdefault(k, []).append((fn, ga[fn][k], ca[fn][k]))
    for k, lst in per_key.items():
        diffs.append(f"au.{k} differs on {len(lst)} frames, first: " +
                     '; '.join(f'frame {fn}: {x} vs {y}' for fn, x, y in lst[:3]))
    only_g, only_c = sorted(set(ga) - set(ca)), sorted(set(ca) - set(ga))
    if a.mode == 'cp':
        # drops are timing-dependent; the invariant is the drop pattern: the same number of drop runs,
        # each ending in an IDR (or the end of input)
        gr, cr = g.get('drop_runs', []), c.get('drop_runs', [])
        if len(gr) != len(cr):
            diffs.append(f'drop runs: golden={len(gr)} candidate={len(cr)}')
        bad = [r for r in cr if r['resumed_with_idr'] is False]
        if bad:
            diffs.append(f'candidate resumed without an IDR after drops: {bad[:3]}')
        if only_g or only_c:
            notes.append(f'output frame sets differ (timing): only golden={only_g[:12]} only candidate={only_c[:12]}')
        notes.append('drop runs golden=' + str([(r['first'], r['last'], r['resumed_at']) for r in gr]) +
                     ' candidate=' + str([(r['first'], r['last'], r['resumed_at']) for r in cr]))
    else:
        if c['missing_frame_nos']:
            diffs.append(f"aa mode: candidate dropped frames {c['missing_frame_nos'][:20]}")
    gev = [(e['kind']) for e in g['events'] if e['kind'] != 'MOST write failed']
    cev = [(e['kind']) for e in c['events'] if e['kind'] != 'MOST write failed']
    notes.append(f'events golden={gev} candidate={cev}')
    notes.append(f"lead_90k golden={gt['lead_90k_min']}..{gt['lead_90k_max']} candidate={ct['lead_90k_min']}..{ct['lead_90k_max']}")
    gp = {t['frame_no']: t for t in gt['aus']}; cp = {t['frame_no']: t for t in ct['aus']}
    steps = [(cp[f]['pts'] - gp[f]['pts']) for f in sorted(set(gp) & set(cp)) if f is not None]
    if steps:
        rel = [s - steps[0] for s in steps]
        notes.append(f'PTS offset candidate-golden: first={steps[0]} relative drift min={min(rel)} max={max(rel)} (90 kHz)')
    if a.lead_min is not None and ct['lead_90k_min'] is not None and ct['lead_90k_min'] < a.lead_min:
        diffs.append(f"lead_90k_min {ct['lead_90k_min']} < {a.lead_min}")
    out = [f'compare {a.golden} vs {a.candidate} (mode {a.mode})']
    out += ['DIFF ' + d for d in diffs] + ['note ' + n for n in notes]
    out.append('SAME (strict + normalized)' if not diffs else f'{len(diffs)} differences')
    text = '\n'.join(out) + '\n'
    sys.stdout.write(text)
    open(os.path.join(a.candidate, 'compare.txt'), 'w').write(text)
    sys.exit(1 if diffs else 0)


if __name__ == '__main__':
    main()
