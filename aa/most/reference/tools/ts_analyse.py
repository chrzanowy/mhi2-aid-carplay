#!/usr/bin/env python3
"""Decode a MOST TS capture (host shim output) into a normalized description (python3 -I).

usage: ts_analyse.py RUN_DIR [--ts mlb.ts] [--log mlb.ts.log] [--frames input/frames.jsonl]
                     [--stderr bridge.stderr]
writes RUN_DIR/norm.json (deterministic fields), RUN_DIR/timing.json (timing-dependent fields),
RUN_DIR/summary.txt; exit 0 = format checks passed (missing frames are reported, not errors).

Format rules (CONTRACT.md 3), all checked byte for byte:
  PAT/PMT/PCR at output packet n % 327 == 0/1/2, exact sections + CRC, CC per PID (PCR CC 0),
  PCR base = 45000 + n*705//64, null packets 47 1f ff 1x + 0xff, video PID 0x11 packetized as the
  bridge does (first packet: PUSI + >=2-byte adaptation, flags 0x40 RA / 0x80 discontinuity; middle
  packets 184-byte payload; last packet padded with an adaptation field), 14-byte PES header with PTS.
Each AU is rebuilt from its own PES bytes, flags and first CC and compared byte for byte
(packetization_exact). Its Annex-B content is converted back to the AVCC bytes the feeder put in the
ring and hashed, so every output AU is matched to an input frame (frames.jsonl).
"""
import argparse, collections, hashlib, json, os, re, struct, sys

TS, BLK = 188, 12032
PAT_PID, PMT_PID, PCR_PID, VID_PID, NUL_PID = 0x0000, 0x0010, 0x1000, 0x0011, 0x1FFF
PAT_SEC = bytes.fromhex('00b00d0001c100000001e010')
PMT_SEC = bytes.fromhex('02b0120001c10000f000f0001be011f000')
PES_HDR = bytes.fromhex('000001e00000808005')
CADENCE = 327


def crc32_mpeg(b):
    c = 0xffffffff
    for x in b:
        c ^= x << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04c11db7) & 0xffffffff if c & 0x80000000 else (c << 1) & 0xffffffff
    return c


def psi_packet(pid, cc, sec):
    sec = sec + struct.pack('>I', crc32_mpeg(sec))
    p = bytearray(b'\xff' * TS); p[0] = 0x47; p[1] = 0x40 | (pid >> 8); p[2] = pid & 0xff
    p[3] = 0x10 | (cc & 15); p[4] = 0; p[5:5 + len(sec)] = sec
    return bytes(p)


def pcr_base(n):
    return 45000 + (n * 705) // 64


def pcr_packet(base):
    b = base & 0x1ffffffff
    return bytes([0x47, 0x10, 0x00, 0x20, 183, 0x10, (b >> 25) & 255, (b >> 17) & 255, (b >> 9) & 255,
                  (b >> 1) & 255, ((b & 1) << 7) | 0x7e, 0]) + b'\xff' * 176


def null_packet(cc):
    return bytes([0x47, 0x1f, 0xff, 0x10 | (cc & 15)]) + b'\xff' * 184


def packetize(pes, flags, cc0):
    """The bridge's enqueue_pes(); flags = adaptation flags byte of the first packet."""
    out, off, first, cc = [], 0, True, cc0
    while off < len(pes):
        pay = min(len(pes) - off, 184 - (2 if first else 0)); ad = 184 - pay
        p = bytearray(b'\xff' * TS); p[0] = 0x47; p[1] = 0x40 if first else 0; p[2] = 0x11
        p[3] = ((3 if ad else 1) << 4) | (cc & 15); cc += 1; po = 4
        if ad:
            p[4] = ad - 1; po += ad
            if ad > 1: p[5] = flags if first else 0
        p[po:po + pay] = pes[off:off + pay]; off += pay; first = False
        out.append(bytes(p))
    return out


def pts_of(b):
    return (((b[0] >> 1) & 7) << 30) | (b[1] << 22) | ((b[2] >> 1) << 15) | (b[3] << 7) | (b[4] >> 1)


def split_annexb(b):
    """NAL units of an Annex-B buffer -> list of (start_code_len, nal)."""
    starts, i, n = [], 0, len(b)
    while i + 3 <= n:
        if b[i] == 0 and b[i + 1] == 0 and b[i + 2] == 1:
            sc = 4 if i > 0 and b[i - 1] == 0 else 3
            starts.append((i + 3, sc)); i += 3
        else:
            i += 1
    out = []
    for k, (s, sc) in enumerate(starts):
        e = starts[k + 1][0] - starts[k + 1][1] if k + 1 < len(starts) else n
        out.append((sc, b[s:e]))
    return out


def parse_log(path):
    dev, writes, other = [], [], []
    if not path or not os.path.exists(path):
        return dev, writes, other
    for line in open(path):
        kv = dict(re.findall(r'(\w+)=(\S+)', line))
        if ' devctl ' in line:
            dev.append([kv['code'], kv['dir'], int(kv['size']), int(kv['value']), int(kv['status'])])
        elif ' write ' in line and 'ret' in kv:
            writes.append(kv)
        else:
            other.append(line.strip())
    return dev, writes, other


EVENT_RE = re.compile(r'bridge: (latency-reset|predictive-chain-gap|latency-wait-writer|latency-request-idr|'
                      r'latency-resume-idr|pts-rebase|ring overrun|avcC ready|ring generation|MOST write failed)(.*)')


def parse_stderr(path):
    ev = []
    if not path or not os.path.exists(path):
        return ev
    for line in open(path, errors='replace'):
        m = EVENT_RE.search(line)
        if m:
            d = dict(re.findall(r'(\w+)=(\S+)', m.group(2))); d['kind'] = m.group(1)
            ev.append(d)
        elif line.startswith('PARITY_') and ('RECOVERY' in line or 'DROP' in line or 'PTS_REBASE' in line):
            ev.append(dict(kind=line.split()[0], line=line.strip()))
    return ev


def analyse(ts, frames, dev, writes, events):
    err = []
    n = len(ts) // TS
    if len(ts) % BLK: err.append(f'capture length {len(ts)} is not a multiple of 12032')
    cc = collections.defaultdict(lambda: None)
    counts = collections.Counter()
    au_starts, cur = [], None
    cadence_bad, pcr_bad, null_bad, psi_bad, cc_breaks = [], [], [], [], []
    pat_cc = pmt_cc = None
    for i in range(n):
        p = ts[i * TS:(i + 1) * TS]
        if p[0] != 0x47: err.append(f'pkt {i}: no sync'); continue
        pid = ((p[1] & 0x1f) << 8) | p[2]; c = p[3] & 15
        counts[pid] += 1
        phase = i % CADENCE
        want = {0: PAT_PID, 1: PMT_PID, 2: PCR_PID}.get(phase)
        if want is not None and pid != want: cadence_bad.append((i, f'{pid:#x}'))
        if want is None and pid in (PAT_PID, PMT_PID, PCR_PID): cadence_bad.append((i, f'{pid:#x}'))
        if pid == PAT_PID:
            if p != psi_packet(PAT_PID, c, PAT_SEC): psi_bad.append(i)
            if pat_cc is not None and c != (pat_cc + 1) & 15: cc_breaks.append((i, 'pat'))
            pat_cc = c
        elif pid == PMT_PID:
            if p != psi_packet(PMT_PID, c, PMT_SEC): psi_bad.append(i)
            if pmt_cc is not None and c != (pmt_cc + 1) & 15: cc_breaks.append((i, 'pmt'))
            pmt_cc = c
        elif pid == PCR_PID:
            if p != pcr_packet(pcr_base(i)): pcr_bad.append(i)
        elif pid == NUL_PID:
            if p != null_packet(c): null_bad.append(i)
            if cc['nul'] is not None and c != (cc['nul'] + 1) & 15: cc_breaks.append((i, 'null'))
            cc['nul'] = c
        elif pid == VID_PID:
            if cc['vid'] is not None and c != (cc['vid'] + 1) & 15: cc_breaks.append((i, 'video'))
            cc['vid'] = c
            if p[1] & 0x40:
                cur = dict(first=i, pkts=[p]); au_starts.append(cur)
            elif cur is None:
                err.append(f'pkt {i}: video continuation without PUSI')
            else:
                cur['pkts'].append(p)
        else:
            err.append(f'pkt {i}: unexpected PID {pid:#x}')
    for name, lst in (('psi cadence', cadence_bad), ('PAT/PMT bytes', psi_bad), ('PCR packet', pcr_bad),
                      ('null packet', null_bad)):
        if lst: err.append(f'{name}: {len(lst)} bad, first {lst[:5]}')

    # avcC (SPS/PPS) the feeder sent, for the SPS/PPS check
    by_hash = collections.defaultdict(list)
    inputs = [f for f in frames if 'frame_no' in f and 'ring_seq' in f]
    param_sets = {f[k] for f in frames if f.get('event') == 'avcC' for k in ('sps', 'pps')}
    for f in inputs: by_hash[f['avcc_sha256']].append(f)

    aus, timing = [], []
    last_pts = None
    for k, a in enumerate(au_starts):
        pk = a['pkts']; p0 = pk[0]
        afc = (p0[3] >> 4) & 3
        flags = p0[5] if afc & 2 and p0[4] >= 1 else None
        payload = b''
        for p in pk:
            f = (p[3] >> 4) & 3
            off = 4 + (1 + p[4] if f & 2 else 0)
            payload += p[off:]
        pes_ok = payload[:9] == PES_HDR
        pts = pts_of(payload[9:14])
        annexb = payload[14:]
        exact = packetize(payload, flags if flags is not None else 0, p0[3] & 15) == pk
        nals = split_annexb(annexb)
        types = [nal[0] & 0x1f for _, nal in nals]
        aud_first = bool(nals) and nals[0][1] == b'\x09\xf0' and nals[0][0] == 4
        has_ps = 7 in types and 8 in types
        ps_ok = all(nal.hex() in param_sets for _, nal in nals if (nal[0] & 0x1f) in (7, 8))
        if not ps_ok: err.append(f'AU {k}: SPS/PPS bytes differ from every avcC the feeder sent')
        body = b''.join(struct.pack('>I', len(nal)) + nal for _, nal in nals if (nal[0] & 0x1f) not in (7, 8, 9))
        h = hashlib.sha256(body).hexdigest()
        src = by_hash[h].pop(0) if by_hash.get(h) else None
        ra = bool(flags is not None and flags & 0x40)
        rec = dict(au=k, frame_no=src['frame_no'] if src else None, input_idx=src['idx'] if src else None,
                   idr=5 in types, random_access=ra, discontinuity=bool(flags is not None and flags & 0x80),
                   adaptation_flags=flags, aud_first=aud_first, sps_pps=has_ps,
                   sps_pps_iff_idr=(has_ps == (5 in types)), sps_pps_match_avcc=ps_ok, nal_types=types,
                   start_codes=sorted(set(sc for sc, _ in nals)),
                   pes_header_ok=pes_ok, annexb_bytes=len(annexb), packets=len(pk),
                   packetization_exact=exact, avcc_sha256=h[:16])
        if not pes_ok: err.append(f'AU {k}: PES header {payload[:9].hex()}')
        if not exact: err.append(f'AU {k}: packetization differs from the bridge rule')
        if src is None: err.append(f'AU {k}: payload matches no input frame')
        aus.append(rec)
        lead = pts - pcr_base(a['first'])
        timing.append(dict(au=k, frame_no=rec['frame_no'], first_packet=a['first'],
                           last_packet=a['first'] + len(pk) - 1 if True else None, pts=pts,
                           pts_step=None if last_pts is None else pts - last_pts,
                           pcr_at_first_packet=pcr_base(a['first']), lead_90k=lead,
                           ntp=src.get('ntp') if src else None, t_put_us=src.get('t_us') if src else None))
        last_pts = pts
    # PTS rules
    pts_list = [t['pts'] for t in timing]
    if any(b <= a for a, b in zip(pts_list, pts_list[1:])): err.append('PTS not strictly increasing')
    # SPS/PPS bytes against the avcC records are implied by the hash match of the IDR AUs' VCL;
    # check them directly too
    matched = {r['frame_no'] for r in aus if r['frame_no'] is not None}
    missing = [f['frame_no'] for f in inputs if f['frame_no'] not in matched]
    # drop runs: a run of missing input frames; the bridge rule is "drop until an IDR", so the first
    # output AU after a run must be an IDR (resumed_with_idr) unless the input ended
    out_by_fn = {r['frame_no']: r for r in aus if r['frame_no'] is not None}
    in_fns = [f['frame_no'] for f in inputs]
    drop_runs, run = [], None
    for fn in in_fns + [None]:
        if fn is not None and fn not in out_by_fn:
            run = run or dict(first=fn, last=fn, frames=0)
            run['last'] = fn; run['frames'] += 1
        elif run:
            run['resumed_at'] = fn
            run['resumed_with_idr'] = None if fn is None else bool(out_by_fn[fn]['idr'])
            drop_runs.append(run); run = None
    order = [r['frame_no'] for r in aus if r['frame_no'] is not None]
    if order != sorted(order): err.append('output AU order differs from input order')

    wsizes = collections.Counter(int(w['size']) for w in writes)
    wret = collections.Counter(int(w['ret']) for w in writes)
    total_ret = sum(int(w['ret']) for w in writes)
    if writes and total_ret != len(ts): err.append(f'log says {total_ret} bytes accepted, capture has {len(ts)}')
    partial = sum(1 for w in writes if int(w['ret']) != int(w['size']))

    ev_norm = []
    for e in events:
        if e['kind'] in ('latency-wait-writer', 'pts-rebase', 'avcC ready'):
            continue
        d = dict(kind=e['kind'])
        for key in ('sequence', 'previous', 'current', 'restart', 'queued', 'discarded', 'extra_discarded'):
            if key in e: d[key] = e[key]
        ev_norm.append(d)
    ev_counts = collections.Counter(e['kind'] for e in events)

    norm = dict(
        format='bridge-stage0-norm/1',
        transport=dict(
            block_bytes=BLK, blocks=len(ts) // BLK, capture_whole_blocks=len(ts) % BLK == 0,
            write_sizes=sorted(wsizes), partial_writes=partial,
            devctl=dev,
            psi_cadence_ok=not cadence_bad, pat_pmt_bytes_ok=not psi_bad, pcr_formula_ok=not pcr_bad,
            null_packets_ok=not null_bad,
            cc_breaks={k: sum(1 for _, x in cc_breaks if x == k) for k in ('pat', 'pmt', 'null', 'video')},
            pids=sorted(f'{p:#06x}' for p in counts)),
        aus=[{k: r[k] for k in ('frame_no', 'idr', 'random_access', 'discontinuity', 'aud_first', 'sps_pps',
                                'sps_pps_match_avcc', 'nal_types', 'start_codes', 'pes_header_ok', 'annexb_bytes', 'packets',
                                'packetization_exact', 'avcc_sha256')} for r in aus],
        input_frames=len(inputs),
        output_aus=len(aus),
        missing_frame_nos=missing,
        drop_runs=drop_runs,
        input_avcc_sha256={str(f['frame_no']): f['avcc_sha256'][:16] for f in inputs},
        events=ev_norm,
        errors=err)
    tim = dict(format='bridge-stage0-timing/1',
               packet_counts={f'{p:#06x}': c for p, c in sorted(counts.items())},
               video_cc_breaks_at=[i for i, x in cc_breaks if x == 'video'],
               event_counts=dict(ev_counts), aus=timing,
               lead_90k_min=min((t['lead_90k'] for t in timing), default=None),
               lead_90k_max=max((t['lead_90k'] for t in timing), default=None),
               writes=dict(count=len(writes), eagain_total=sum(int(w.get('eagain_before', 0)) for w in writes),
                           blocked_us_total=sum(int(w.get('blocked_us', 0)) for w in writes)))
    return norm, tim


def ranges(xs):
    out = []
    for x in xs:
        if out and x == out[-1][1] + 1: out[-1][1] = x
        else: out.append([x, x])
    return ', '.join(f'{a}' if a == b else f'{a}-{b}' for a, b in out)


def summary(norm, tim):
    t = norm['transport']
    L = [f"blocks={t['blocks']} write_sizes={t['write_sizes']} partial={t['partial_writes']} "
         f"pids={','.join(t['pids'])}",
         f"devctl={[(d[0], d[3], d[4]) for d in t['devctl']]}",
         f"psi_cadence_ok={t['psi_cadence_ok']} pat_pmt_ok={t['pat_pmt_bytes_ok']} pcr_ok={t['pcr_formula_ok']} "
         f"null_ok={t['null_packets_ok']} cc_breaks={t['cc_breaks']}",
         f"input_frames={norm['input_frames']} output_aus={norm['output_aus']} "
         f"idr_out={sum(a['idr'] for a in norm['aus'])} "
         f"packetization_exact={sum(a['packetization_exact'] for a in norm['aus'])}/{len(norm['aus'])}",
         f"missing_frame_nos={ranges(norm['missing_frame_nos']) or 'none'}",
         f"drop_runs={[(r['first'], r['last'], r['resumed_at'], r['resumed_with_idr']) for r in norm['drop_runs']]}"
         " (first, last, resumed_at, resumed_with_idr)",
         f"events={tim['event_counts']}",
         f"pts_lead_90k min={tim['lead_90k_min']} max={tim['lead_90k_max']}"]
    for e in norm['events']:
        L.append('  event ' + ' '.join(f'{k}={v}' for k, v in e.items()))
    L.append('OK' if not norm['errors'] else 'ERRORS:\n  ' + '\n  '.join(norm['errors'][:30]))
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('run_dir')
    ap.add_argument('--ts', default='mlb.ts'); ap.add_argument('--log', default='mlb.ts.log')
    ap.add_argument('--frames', default='input/frames.jsonl'); ap.add_argument('--stderr', default='bridge.stderr')
    ap.add_argument('--prefix', default='')
    a = ap.parse_args()
    j = lambda x: os.path.join(a.run_dir, x)
    ts = open(j(a.ts), 'rb').read()
    frames = [json.loads(l) for l in open(j(a.frames))]
    dev, writes, _ = parse_log(j(a.log))
    events = parse_stderr(j(a.stderr))
    norm, tim = analyse(ts, frames, dev, writes, events)
    json.dump(norm, open(j(a.prefix + 'norm.json'), 'w'), indent=1)
    json.dump(tim, open(j(a.prefix + 'timing.json'), 'w'), indent=1)
    s = summary(norm, tim)
    open(j(a.prefix + 'summary.txt'), 'w').write(s)
    sys.stdout.write(s)
    sys.exit(1 if norm['errors'] else 0)


if __name__ == '__main__':
    main()
