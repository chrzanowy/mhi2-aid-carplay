#!/usr/bin/env python3
"""Feeder-side driver for the host bridge (run with python3 -I).

Writes the altscreen ring exactly as aa_most_feeder.c (v10) does:
  - waits until the bridge has created/initialised the ring (magic CPRG, version 1, size 0x1000710),
    then starts at the header's write_sequence (feeder most_take(): g_seq = rd32(ring + 0x0c));
  - ring_put(): slot.committed = 0; type, size, flags = 0, frame_no, ts_lo, ts_hi; data;
    slot.committed = N; header.write_sequence = N. A memory barrier (OSMemoryBarrier, a real dmb on
    arm64) separates the steps like the feeder's __sync_synchronize();
  - ts = NTP 32.32 from CLOCK_MONOTONIC at put time (feeder now_ntp());
  - frames go in as AVCC (4-byte lengths), AUD/SPS/PPS removed; SPS/PPS go in an avcC record
    (type 1, frame_no 0) built like send_avcc(), written before the first frame;
  - frame_no counts ring frames from 1 (a scenario can skip numbers to make a gap).

With --m1au HOST:PORT it instead serves the same access units (Annex B, unchanged) as M1AU v1 records
to harman-f's direct_ts_parity, which connects as a TCP client to 127.0.0.1.

Force-IDR handling (--idr-on-request N): when the bridge's request file exists, it is removed and the
N-th frame after it is sent as an IDR (what CarPlay's core.so / the AA hook with KF_BRIDGE=1 do).
N = -1 ignores requests (the AA feeder v10 default, PMCP_AA_KF_BRIDGE=0: the file is only removed).

Frame payloads are a function of (seed, frame index, idr, size) only, so the same scenario always
produces the same bytes; which frame becomes an IDR after a request depends on timing and is logged.
"""
import argparse, ctypes, hashlib, importlib.util, json, mmap, os, socket, struct, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location('h264synth', os.path.join(HERE, 'h264synth.py'))
h264synth = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(h264synth)

RING_MAGIC, RING_VERSION, RING_SLOTS, RING_SLOT_SIZE, RING_HDR = 0x43505247, 1, 64, 0x4001C, 0x10
RING_FILE_SIZE = RING_HDR + RING_SLOTS * RING_SLOT_SIZE
RING_DATA_MAX = 0x40000
FPS = 30

try:
    _barrier = ctypes.CDLL(None).OSMemoryBarrier
except (OSError, AttributeError):
    _barrier = None


def barrier():
    if _barrier is not None:
        _barrier()


def now_ntp():
    ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    sec, frac_ns = divmod(ns, 1_000_000_000)
    return ((sec & 0xffffffff) << 32) | ((frac_ns << 32) // 1_000_000_000)


# ------------------------------------------------------------------ scenarios
# Each step: (count, kind, size_lo, size_hi, idr_every) with kind 'steady' (1/30 s apart) or
# 'burst' (no wait); 'gap' adds to the next frame_no; 'pause' sleeps. Sizes are slice-NAL bytes.
def scenario(name):
    if name == 'steady':
        return dict(idr_size=20000, steps=[('idr',), ('steady', 149, 1500, 6000)])
    if name == 'burst':
        return dict(idr_size=20000, steps=[('idr',), ('steady', 29, 1500, 6000),
                                           ('burst', 48, 6000, 12000), ('steady', 60, 1500, 6000)])
    if name == 'gap':
        return dict(idr_size=20000, steps=[('idr',), ('steady', 39, 1500, 6000), ('gap', 1),
                                           ('steady', 60, 1500, 6000)])
    if name == 'large-idr':
        return dict(idr_size=110000, steps=[('idr',), ('steady', 14, 1500, 6000), ('large', 60000, 110000),
                                            ('steady', 14, 1500, 6000), ('large', 60000, 110000),
                                            ('steady', 14, 1500, 6000), ('idr',),
                                            ('steady', 14, 1500, 6000), ('large', 60000, 110000),
                                            ('steady', 30, 1500, 6000)])
    if name == 'large-run':
        return dict(idr_size=20000, steps=[('idr',), ('steady', 29, 1500, 6000),
                                           ('steady-large', 4, 95000, 105000), ('steady', 60, 1500, 6000)])
    raise SystemExit(f'unknown scenario {name}')


def frame_plan(name, seed):
    """Static plan: list of dicts {idx, idr, size, burst, skip}. IDRs on request are decided live."""
    sc = scenario(name)
    plan, skip = [], 0
    import random
    rng = random.Random(seed)

    def add(idr, size, burst=False):
        nonlocal skip
        plan.append(dict(idx=len(plan), idr=idr, size=size, burst=burst, skip=skip)); skip = 0

    for st in sc['steps']:
        k = st[0]
        if k == 'idr':
            add(True, sc['idr_size'])
        elif k in ('steady', 'burst', 'steady-large'):
            for _ in range(st[1]):
                add(False, rng.randrange(st[2], st[3] + 1), burst=(k == 'burst'))
        elif k == 'large':
            add(False, rng.randrange(st[1], st[2] + 1))
        elif k == 'gap':
            skip += st[1]
    return sc, plan


def make_au(seed, idx, idr, size):
    import random
    rng = random.Random((seed << 24) ^ (idx << 1) ^ (1 if idr else 0))
    annexb, _ = h264synth.access_unit(idr, size, rng)
    return annexb


def split_annexb(b):
    out, i, n = [], 0, len(b)
    starts = []
    while i + 3 <= n:
        if b[i] == 0 and b[i + 1] == 0 and b[i + 2] == 1:
            starts.append(i + 3); i += 3
        else:
            i += 1
    for k, s in enumerate(starts):
        e = starts[k + 1] - 3 if k + 1 < len(starts) else n
        while k + 1 < len(starts) and e > s and b[e - 1] == 0:
            e -= 1
        out.append(b[s:e])
    return out


def to_avcc(annexb):
    """Feeder: SPS/PPS kept for avcC, AUD dropped, the rest with 4-byte lengths."""
    sps = pps = None; body = b''
    for nal in split_annexb(annexb):
        t = nal[0] & 0x1f
        if t == 7: sps = nal; continue
        if t == 8: pps = nal; continue
        if t == 9: continue
        body += struct.pack('>I', len(nal)) + nal
    return sps, pps, body


def make_avcc(sps, pps):
    return (bytes([1, sps[1], sps[2], sps[3], 0xff, 0xe1]) + struct.pack('>H', len(sps)) + sps +
            bytes([1]) + struct.pack('>H', len(pps)) + pps)


class Ring:
    def __init__(self, path, timeout=10.0):
        t0 = time.monotonic()
        while True:
            try:
                if os.path.getsize(path) == RING_FILE_SIZE:
                    fd = os.open(path, os.O_RDWR)
                    self.m = mmap.mmap(fd, RING_FILE_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
                    os.close(fd)
                    magic, ver, gen, wseq = struct.unpack_from('<4I', self.m, 0)
                    if magic == RING_MAGIC and ver == RING_VERSION:
                        self.seq, self.gen = wseq, gen
                        return
                    self.m.close()
            except FileNotFoundError:
                pass
            if time.monotonic() - t0 > timeout:
                raise SystemExit('ring not ready')
            time.sleep(0.01)

    def put(self, typ, data, frame_no):
        ts = now_ntp()
        assert 0 < len(data) <= RING_DATA_MAX
        self.seq = 1 if self.seq + 1 > 0xffffffff else self.seq + 1
        off = RING_HDR + ((self.seq - 1) & (RING_SLOTS - 1)) * RING_SLOT_SIZE
        struct.pack_into('<I', self.m, off, 0)
        barrier()
        struct.pack_into('<6I', self.m, off + 4, typ, len(data), 0, frame_no, ts & 0xffffffff, ts >> 32)
        self.m[off + 0x1c:off + 0x1c + len(data)] = data
        barrier()
        struct.pack_into('<I', self.m, off, self.seq)
        barrier()
        struct.pack_into('<I', self.m, 0x0c, self.seq)
        return self.seq, ts


class M1AU:
    """harman-f direct_ts_parity input: 56-byte big-endian header + one Annex-B AU."""
    def __init__(self, port, timeout=40.0):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(('127.0.0.1', port)); srv.listen(1); srv.settimeout(timeout)
        self.c, _ = srv.accept(); srv.close()
        self.c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def put(self, annexb, idr, seq):
        ts = now_ntp()
        flags = (1 if idr else 0) | 4 | 8
        hdr = (b'M1AU' + struct.pack('>HHII', 1, 56, flags, len(annexb)) +
               struct.pack('>QQQQ', 1, 1, 1, seq) + struct.pack('<II', ts & 0xffffffff, ts >> 32))
        self.c.sendall(hdr + annexb)
        return seq, ts

    def close(self):
        try:
            self.c.shutdown(socket.SHUT_WR)
            self.c.settimeout(15.0)
            while self.c.recv(4096):
                pass
        except OSError:
            pass
        self.c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario', required=True)
    ap.add_argument('--out', required=True, help='directory for frames.jsonl / input.h264')
    ap.add_argument('--ring', help='ring file (bridge mode)')
    ap.add_argument('--m1au', type=int, help='serve M1AU on 127.0.0.1:PORT (harman-f mode)')
    ap.add_argument('--idr-path', action='append', default=[], help='request file(s) to watch')
    ap.add_argument('--idr-on-request', type=int, default=1)
    ap.add_argument('--ignore-requests-first', type=int, default=0,
                    help='ignore requests seen before this many frames (harman asks once at start)')
    ap.add_argument('--seed', type=int, default=1161)
    ap.add_argument('--h264', help='real Annex-B capture instead of the synthetic plan (one AU per AUD)')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    sc, plan = frame_plan(a.scenario, a.seed)
    if a.h264:
        data = open(a.h264, 'rb').read()
        aus, cur = [], b''
        for nal in split_annexb(data):
            if (nal[0] & 0x1f) == 9 and cur:
                aus.append(cur); cur = b''
            cur += b'\x00\x00\x00\x01' + nal
        if cur: aus.append(cur)
        real = aus
        plan = [dict(idx=i, idr=any((n[0] & 0x1f) == 5 for n in split_annexb(au)), size=len(au),
                     burst=False, skip=0) for i, au in enumerate(real)]
    else:
        real = None

    sink = Ring(a.ring) if a.ring else M1AU(a.m1au)
    man = open(os.path.join(a.out, 'frames.jsonl'), 'w')
    h264 = open(os.path.join(a.out, 'input.h264'), 'wb')
    frame_no, avcc_sent, pending = 0, None, None
    t_next = time.monotonic()
    t_start = t_next
    requests = 0
    for p in plan:
        if not p['burst']:
            d = t_next - time.monotonic()
            if d > 0:
                time.sleep(d)
            t_next = max(t_next + 1.0 / FPS, time.monotonic() - 0.5 / FPS)
        else:
            t_next = time.monotonic() + 1.0 / FPS
        for path in a.idr_path:
            if os.path.exists(path):
                try: os.unlink(path)
                except FileNotFoundError: pass
                requests += 1
                ev = dict(event='idr-request', before_idx=p['idx'], path=os.path.basename(path),
                          t_us=int((time.monotonic() - t_start) * 1e6))
                if p['idx'] >= a.ignore_requests_first and a.idr_on_request >= 0 and pending is None:
                    pending = a.idr_on_request
                    ev['action'] = f'idr in {pending} frames'
                else:
                    ev['action'] = 'ignored'
                man.write(json.dumps(ev) + '\n')
        idr = p['idr']; size = p['size']; forced = False
        if pending is not None:
            if pending <= 0 and not idr:
                idr, size, forced = True, sc['idr_size'] if not real else size, True
            if pending <= 0:
                pending = None
            else:
                pending -= 1
        au = real[p['idx']] if real else make_au(a.seed, p['idx'], idr, size)
        sps, pps, body = to_avcc(au)
        frame_no += 1 + p['skip']
        rec = dict(idx=p['idx'], frame_no=frame_no, idr=idr, forced_idr=forced, burst=p['burst'],
                   annexb_bytes=len(au), avcc_bytes=len(body),
                   avcc_sha256=hashlib.sha256(body).hexdigest())
        if sps and pps and make_avcc(sps, pps) != avcc_sent:
            avcc_sent = make_avcc(sps, pps)
            seq = sink.put(1, avcc_sent, 0)[0] if a.ring else None   # M1AU: SPS/PPS stay in the AU
            man.write(json.dumps(dict(event='avcC', ring_seq=seq, bytes=len(avcc_sent), sps=sps.hex(),
                                      pps=pps.hex(), sha256=hashlib.sha256(avcc_sent).hexdigest())) + '\n')
        if a.ring:
            if len(body) > RING_DATA_MAX:
                rec['dropped_by_feeder'] = 'larger than 256 KiB'   # feeder: no ring_put, no frame_no
                frame_no -= 1 + p['skip']
                man.write(json.dumps(rec) + '\n'); continue
            seq, ts = sink.put(2, body, frame_no)
        else:
            seq, ts = sink.put(au, idr, frame_no)
        rec.update(ring_seq=seq, ntp=ts, t_us=int((time.monotonic() - t_start) * 1e6))
        man.write(json.dumps(rec) + '\n')
        h264.write(au)
    man.write(json.dumps(dict(event='end', frames=len(plan), requests=requests)) + '\n')
    man.close(); h264.close()
    if not a.ring:
        sink.close()


if __name__ == '__main__':
    main()
