"""Host test for aa-most-feeder v11 direct output (PMCP_AA_OUTPUT=direct) against the simulated isoTX2.

usage: python3 -I run_direct_test.py FEEDER_SIM_BINARY [GOLDEN_ROOT] [OUT_DIR]
  FEEDER_SIM_BINARY  the feeder built with -DMOST_HOST_SIM and aa/most/test/host_mlb.c (bridge-stage0's simulated
                     /dev/mlb/isoTX2: rate, EAGAIN / blocking, short writes, stalls, EIO, devctl statuses)
  GOLDEN_ROOT        bridge-stage0/golden (optional): its steady and burst inputs are replayed and compared
  OUT_DIR            where the runs are kept (default: a temporary directory)

A fake hook serves the stream and reads the ACK pipe. Its phone model keeps at most WINDOW frames unacknowledged
(the hook releases credit only per ACK; the phone's window is 8), so held ACKs slow it down; WINDOW 0 sends on
schedule whatever the ACKs say (a true 48-frame burst). The TS is decoded by bridge-stage0's analyser
(aa/most/test/ts_analyse.py, a verbatim copy).
"""
import hashlib, json, os, random, re, select, shutil, signal, socket, struct, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import h264synth as hs

FEEDER = os.path.abspath(sys.argv[1])
GOLDEN = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != '-' else None
OUT = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else tempfile.mkdtemp(prefix='pmcp-direct-')
MOST_TEST = os.path.join(HERE, '..', '..', 'most', 'test')
PY = [sys.executable, '-I']
fails = []


def check(cond, msg):
    print(('ok    ' if cond else 'FAILED ') + msg, flush=True)
    if not cond:
        fails.append(msg)


def wait_for(fn, timeout=5.0):
    t = time.time()
    while time.time() - t < timeout:
        if fn(): return True
        time.sleep(0.02)
    return False


def split_nals(b):
    out, i, n, starts = [], 0, len(b), []
    while i + 3 <= n:
        if b[i] == 0 and b[i + 1] == 0 and b[i + 2] == 1:
            starts.append(i + 3); i += 3
        else:
            i += 1
    for k, s in enumerate(starts):
        e = starts[k + 1] - 3 if k + 1 < len(starts) else n
        while k + 1 < len(starts) and e > s and b[e - 1] == 0: e -= 1
        out.append(b[s:e])
    return out


def avcc_hash(au):
    body = b''.join(struct.pack('>I', len(x)) + x for x in split_nals(au) if (x[0] & 0x1f) not in (7, 8, 9))
    return hashlib.sha256(body).hexdigest()


def plan_synth(steps, seed=11):
    """steps: (count, idr_every, size_lo, size_hi, burst). Returns [(annexb, idr, burst)]."""
    rng = random.Random(seed); out = []
    for count, idr_every, lo, hi, burst in steps:
        for k in range(count):
            idr = idr_every and (len(out) % idr_every == 0)
            size = 20000 if idr and hi < 20000 else rng.randrange(lo, hi + 1)
            au, _ = hs.access_unit(bool(idr), size, rng)
            out.append((au, bool(idr), burst))
    return out


def plan_golden(name):
    g = os.path.join(GOLDEN, name)
    data = open(os.path.join(g, 'input', 'input.h264'), 'rb').read()
    aus, cur = [], b''
    for nal in split_nals(data):
        if (nal[0] & 0x1f) == 9 and cur:
            aus.append(cur); cur = b''
        cur += b'\x00\x00\x00\x01' + nal
    if cur: aus.append(cur)
    fr = [json.loads(l) for l in open(os.path.join(g, 'input', 'frames.jsonl'))]
    fr = [x for x in fr if 'frame_no' in x and 'ring_seq' in x]
    assert len(fr) == len(aus), (len(fr), len(aus))
    return [(au, x['idr'], x['t_us']) for au, x in zip(aus, fr)], os.path.join(g, 'input', 'frames.jsonl')


class Run:
    pass


def run(case, plan, env_add=None, window=8, fps=30.0, golden_times=False, conf='', ack_idle=1.0, sync_reps=False, extra=None, pause=None, status=None):
    d = os.path.join(OUT, case)
    shutil.rmtree(d, ignore_errors=True); os.makedirs(os.path.join(d, 'input'))
    P = lambda n: os.path.join(d, n)
    ack_srv = socket.socket(socket.AF_UNIX); ack_path = os.path.join(tempfile.mkdtemp(prefix='ack'), 'a.sock')
    ack_srv.bind(ack_path); ack_srv.listen(1)
    srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)
    with open(P('feeder.conf'), 'w') as f: f.write(conf)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PMCP_', 'HOST_MLB_'))}
    env.update(PMCP_AA_CONF=P('feeder.conf'), PMCP_AA_STATUS=status or P('status.txt'), PMCP_AA_RING=P('ring.bin'),
               PMCP_AA_BRIDGE=os.path.join(HERE, 'fake_bridge.sh'), PMCP_AA_DMDT=os.path.join(HERE, 'fake_dmdt.sh'),
               PMCP_AA_ACK=ack_path, PMCP_AA_FLUSH_DEV=P('flush.dev'), FAKE_DMDT_LOG=P('dmdt.log'),
               FAKE_BRIDGE_OUT=P('bridge.jsonl'), PMCP_AA_KF_REQ=P('kf.request'), PMCP_AA_RUNDIR=d,
               PMCP_AA_MODE='most', PMCP_AA_OUTPUT='direct', PMCP_AA_MOST_DEV=P('mlb.ts'), PMCP_AA_SETTLE_MS='200',
               PMCP_AA_CP_READY=P('cp.ready'), PMCP_AA_CONF_EXTRA=P('extra.conf'))
    if extra is not None:
        with open(P('extra.conf'), 'w') as f: f.write(extra)
    for k, v in (env_add or {}).items():
        if v is None: env.pop(k, None)
        else: env[k] = v
    feeder = subprocess.Popen([FEEDER, 'tcp://127.0.0.1:%d' % srv.getsockname()[1]], env=env)
    srv.settimeout(10)
    conn, _ = srv.accept()
    SP = status or P('status.txt')
    r = Run(); r.d = d; r.P = P; r.dmdt_at_connect = dmdt_lines(P)
    ack_srv.settimeout(5); ack, _ = ack_srv.accept(); ack.setblocking(False)
    acks = 0; other = 0
    def take(timeout=0.0):
        nonlocal acks, other
        rd, _, _ = select.select([ack], [], [], timeout)
        if not rd: return False
        try: b = ack.recv(4096)
        except BlockingIOError: return False
        if not b: return False
        k = b.count(b'K') + b.count(b'C'); other += k; acks += len(b) - k
        return True
    sps, pps = hs.sps(), hs.pps()
    conn.sendall(b''.join(hs.SC + n for n in (sps, pps)))      # codec config replay, as the hook does
    time.sleep(0.02)
    frames, t0 = [], time.time()
    wait_window, t_next = 0.0, t0
    mid = {}
    for i, item in enumerate(plan):
        au, idr = item[0], item[1]
        if pause and i in pause:                  # v13: the phone sends nothing for a while
            p_end = time.time() + pause[i]
            while time.time() < p_end: take(0.05)
            t_next = time.time()
        if golden_times:
            due = t0 + item[2] / 1e6
        else:
            due = t_next if not item[2] else time.time()
        while time.time() < due:
            take(max(0.0, min(0.005, due - time.time())))
        if window:
            w0 = time.time()
            while i - acks >= window:
                if not take(0.05) and time.time() - w0 > 30: break
            wait_window += time.time() - w0
        t_sent = time.time()
        if not golden_times and not item[2]:
            t_next = max(t_next + 1.0 / fps, t_sent - 0.5 / fps)
        conn.sendall(au)
        frames.append(dict(idx=i, frame_no=i + 1, ring_seq=i + 2, idr=idr, avcc_sha256=avcc_hash(au),
                           t_us=int((t_sent - t0) * 1e6)))
        take(0)
        if i == len(plan) // 2:
            mid['status'] = open(SP).read() if os.path.exists(SP) else ''
            mid['dmdt'] = dmdt_lines(P)
    r.t_send = time.time() - t0
    last = time.time()
    while time.time() - last < ack_idle:
        if take(0.05): last = time.time()
    r.status_before_close = open(SP).read() if os.path.exists(SP) else ''
    r.dmdt_before_close = dmdt_lines(P)
    conn.close()
    try: feeder.wait(timeout=10)
    except subprocess.TimeoutExpired: feeder.kill(); feeder.wait()
    # v15: a reclaim logs a second release, so 4 lines can come before the restore; the guardian's marker goes last
    wait_for(lambda: len(dmdt_lines(P)) >= 4 and not os.path.exists(P('pmcp-aa-guard.pid')), 5)
    with open(P('input/frames.jsonl'), 'w') as f:
        f.write(json.dumps(dict(event='avcC', ring_seq=1, sps=sps.hex(), pps=pps.hex())) + '\n')
        for x in frames: f.write(json.dumps(x) + '\n')
    r.rc = feeder.returncode; r.acks = acks; r.other = other; r.frames = frames; r.wait_window = wait_window
    r.mid = mid
    r.status = open(SP).read() if os.path.exists(SP) else ''
    r.dmdt = dmdt_lines(P)
    return r


def dmdt_lines(P):
    try: return open(P('dmdt.log')).read().split('\n')[:-1]
    except FileNotFoundError: return []


def analyse(r, frames_file=None):
    if frames_file: shutil.copy(frames_file, r.P('input/frames.jsonl'))
    a = subprocess.run([*PY, os.path.join(MOST_TEST, 'ts_analyse.py'), r.d], capture_output=True, text=True)
    r.analyser_rc, r.analyser_out = a.returncode, a.stdout
    try:
        r.norm = json.load(open(r.P('norm.json'))); r.timing = json.load(open(r.P('timing.json')))
    except FileNotFoundError:
        r.norm = r.timing = None
    return r


def line(st, prefix):
    l = [x for x in st.split('\n') if x.startswith(prefix)]
    return l[0] if l else ''


def num(l, key):
    try: return int(re.match(r'-?\d+', l.split(key + '=')[1]).group(0))
    except (IndexError, ValueError, AttributeError): return -1


DEVCTL = [['0x4004050c', 'from', 4, 0, 0], ['0x4004050d', 'from', 4, 0, 0], ['0x40040510', 'from', 4, 0, 0],
          ['0x40040506', 'from', 0, 0, 0], ['0x80040509', 'to', 4, 64, 0]]
RESTORE = ['dc 72', 'sc 4 72', 'dc 70 33', 'sc 4 70']


def common(r, name, n_frames, lead_min=0):
    t = r.norm['transport'] if r.norm else {}
    check(r.analyser_rc == 0, '%s: analyser passes %s' % (name, (r.norm or {}).get('errors', ['no norm'])[:3]))
    check(r.norm and r.norm['output_aus'] == n_frames and not r.norm['missing_frame_nos'],
          '%s: every input AU once, in order (%s/%d, missing %s)' % (name, r.norm and r.norm['output_aus'], n_frames,
                                                                    r.norm and r.norm['missing_frame_nos'][:10]))
    check(t.get('write_sizes') == [12032] and t.get('partial_writes') == 0 and t.get('capture_whole_blocks'),
          '%s: whole 12032-byte writes only' % name)
    check(t.get('devctl') == DEVCTL, '%s: devctl sequence + start 64 %s' % (name, t.get('devctl')))
    lm = r.timing and r.timing['lead_90k_min']
    check(lm is not None and lm >= lead_min, '%s: PTS lead never below %d: min=%s max=%s' % (name, lead_min, lm,
                                                                                       r.timing and r.timing['lead_90k_max']))
    check(r.acks == n_frames, '%s: one ACK per frame (%d/%d)' % (name, r.acks, n_frames))
    check(r.other == 0, "%s: no IDR request ('K'/'C') ever (%d)" % (name, r.other))
    check(r.dmdt == RESTORE, '%s: dmdt release + restore %r' % (name, r.dmdt))
    check(r.dmdt_at_connect == ['dc 72', 'sc 4 72'], '%s: MOST taken before the stream connected' % name)
    check(not os.path.exists(r.P('ring.bin')) and not os.path.exists(r.P('bridge.jsonl')), '%s: no ring, no bridge' % name)
    check(not os.path.exists(r.P('pmcp-aa-guard.pid')), '%s: guardian marker removed after the restore' % name)
    flags = [(a['discontinuity'], a['random_access'] == a['idr']) for a in (r.norm or {}).get('aus', [])]
    check(flags and flags[0][0] and not any(f[0] for f in flags[1:]) and all(f[1] for f in flags),
          '%s: discontinuity on the first AU only, random access = IDR' % name)
    check(r.rc == 0, '%s: feeder exit 0 (%s)' % (name, r.rc))


def build_compare(r, golden_name):
    c = subprocess.run([*PY, os.path.join(MOST_TEST, 'ts_compare.py'), os.path.join(GOLDEN, golden_name), r.d,
                        '--mode', 'aa', '--lead-min', '0'], capture_output=True, text=True)
    diffs = [l[5:] for l in c.stdout.split('\n') if l.startswith('DIFF ')]
    return [d for d in diffs if not d.startswith('au.discontinuity differs')], c.stdout


# ------------------------------------------------------------------ cases
STEADY = [(1, 1, 20000, 20000, False), (149, 0, 1500, 6000, False)]

# 1. steady, default settings
r = analyse(run('steady', plan_synth(STEADY)))
common(r, 'steady', 150, lead_min=4500)
st = r.status
check(st.startswith('PMCP AA FEEDER v15 mode=most wyjscie=direct'), 'steady: status header %r' % st.split('\n')[0])
for p in ('kolejka direct:', 'ACK wstrzymane:', 'zapis MOST:', 'czas zapisu bloku:', 'PTS-PCR (90kHz):', 'devctl: interfejs=0 (status 0)',
          'MOST poczatek 01: ', 'AU direct:'):
    check(any(l.startswith(p) for l in st.split('\n')), 'steady: status line %r' % p)
check('MOST przejety (direct)' in r.mid.get('status', ''), 'steady: status mid-session says MOST taken (direct)')
check('devctl start status=0 pakiety=64' in st and 'pierwszy blok zapisany' in st, 'steady: MOST events (devctl, first block)')
check(num(line(st, 'AU direct:'), 'niezgodne') == 0 and num(line(st, 'AU direct:'), 'wyslane') == 150, 'steady: AU counts %s' % line(st, 'AU direct:'))
check('bridge:' not in st, 'steady: no bridge lines in direct mode')
sess = open(r.P('pmcp-aa-sessions.txt')).read() if os.path.exists(r.P('pmcp-aa-sessions.txt')) else ''
check('klatki=150' in sess, 'steady: session line %r' % sess.strip())

# 2. golden replay through the whole feeder: steady and the 48-frame burst (no window: the burst really arrives at once)
if GOLDEN:
    for gname in ('steady', 'burst'):
        plan, ff = plan_golden(gname)
        r = analyse(run('golden-' + gname, plan, window=0, golden_times=True), frames_file=ff)
        common(r, 'golden-' + gname, len(plan), lead_min=4500)
        other, txt = build_compare(r, gname)
        check(not other, 'golden-%s: only documented differences from the golden bridge %s' % (gname, other))
        print('   ', [l for l in txt.split('\n') if l.startswith('note lead') or 'discontinuity' in l])
        if gname == 'burst':
            ql = line(r.status, 'kolejka direct:')
            check(num(ql, 'max') > 1024, 'golden-burst: the queue took the whole burst (%s)' % ql)

# 3. burst of 48 frames 6-12 KB with the phone's window of 8: ACKs held, the phone waits, nothing lost
BURST = [(1, 1, 20000, 20000, False), (29, 0, 1500, 6000, False), (48, 0, 6000, 12000, True), (60, 0, 1500, 6000, False)]
r = analyse(run('burst-window', plan_synth(BURST, seed=5), env_add={'HOST_MLB_BPS': '6000000'}))
common(r, 'burst-window', 138, lead_min=4500)
al = line(r.status, 'ACK wstrzymane:')
check(num(al, 'razy') >= 1 and num(al, 'ACK') >= 1, 'burst-window: ACKs held and released: %s' % al)
check(r.wait_window > 0.1, 'burst-window: the phone waited %.2f s for ACKs' % r.wait_window)

# 4. slow device (2 Mbit/s against ~2.9 Mbit/s of frames): the phone slows down to it, nothing lost
SLOW = [(1, 1, 20000, 20000, False), (119, 0, 11000, 13000, False)]
r = analyse(run('slow-device', plan_synth(SLOW, seed=6), env_add={'HOST_MLB_BPS': '2000000'}, ack_idle=3.0))
common(r, 'slow-device', 120, lead_min=0)
al = line(r.status, 'ACK wstrzymane:')
fps = 120 / r.t_send if r.t_send else 0
check(num(al, 'razy') >= 3 and num(al, 'ACK') > 10, 'slow-device: ACKs held and released repeatedly: %s' % al)
check(fps < 25 and r.wait_window > 1.0, 'slow-device: the phone slowed down to %.1f fps, waited %.1f s for ACKs' % (fps, r.wait_window))
ql = line(r.status, 'kolejka direct:')
check(0 < num(ql, 'max') < 1024 + 8 * 80, 'slow-device: queue bounded by the hold + window (%s)' % ql)

# 5. MOST stalls for 2 s mid-stream (EAGAIN): nothing lost, lead stays positive, no failure
r = analyse(run('stall-2s', plan_synth(STEADY, seed=7), env_add={'HOST_MLB_STALL_AT_BLOCK': '300', 'HOST_MLB_STALL_MS': '2000'},
                ack_idle=3.0))
common(r, 'stall-2s', 150, lead_min=4500)
zl = line(r.status, 'zapis MOST:'); cl = line(r.status, 'czas zapisu bloku:')
check(num(zl, 'EAGAIN') > 100 and num(cl, 'max') >= 1900000, 'stall-2s: EAGAIN while stalled, longest write ~2 s: %s | %s' % (zl, cl))
check(num(line(r.status, 'ACK wstrzymane:'), 'razy') >= 1, 'stall-2s: ACKs held during the stall')
check('najdluzszy zapis' in r.status, 'stall-2s: slow write logged in the MOST events')

# 6. a driver that blocks in write() (stage 0 block mode) with poll, and our blocking open: same result
r = analyse(run('block-driver', plan_synth(STEADY, seed=8), env_add={'HOST_MLB_MODE': 'block'}))
common(r, 'block-driver', 150, lead_min=4500)
r = analyse(run('block-open', plan_synth(STEADY, seed=9), env_add={'PMCP_AA_MOST_WAIT': 'block', 'HOST_MLB_MODE': 'block'}))
common(r, 'block-open', 150, lead_min=4500)
log = open(r.P('mlb.ts.log')).read()
check('nonblock=0' in log and 'oczekiwanie=block' in r.status, 'block-open: device opened without O_NONBLOCK')
r = analyse(run('sleep-wait', plan_synth(STEADY, seed=10), env_add={'PMCP_AA_MOST_WAIT': 'sleep'}))
common(r, 'sleep-wait', 150, lead_min=4500)
zl = line(r.status, 'zapis MOST:')
check(num(zl, 'poll') == 0 and num(zl, 'sny') > 0, 'sleep-wait: sleeps, no poll: %s' % zl)

# 7. EIO mid-session: MOST given back at once (device closed, guardian restores), the session goes on with ACKs
r = analyse(run('eio', plan_synth([(1, 1, 20000, 20000, False), (119, 0, 1500, 6000, False)], seed=12),
                env_add={'HOST_MLB_FAIL_AT_BLOCK': '150'}))
check(r.dmdt_before_close == RESTORE, 'eio: MOST given back while the stream still ran %r' % r.dmdt_before_close)
check('blad: MOST: blad zapisu errno=5' in r.status_before_close and 'MOST oddane (blad zapisu errno=5)' in r.status_before_close,
      'eio: error and state in the status')
check(r.acks == 120, 'eio: every frame still ACKed (%d)' % r.acks)
check('close fd' in open(r.P('mlb.ts.log')).read(), 'eio: isoTX2 closed')
check(r.rc == 0 and r.dmdt == RESTORE, 'eio: exit 0, dmdt %r' % r.dmdt)
check('MOST oddane: blad zapisu errno=5' in r.status, 'eio: event logged')

# 7b. v15 (A165): ENOMEM early after boot (the factory encoder took isoTX2): MOST taken back once, the session goes on
#     with our picture: dmdt release again, the device reopened with the same devctl sequence, SPS/PPS + last IDR again.
#     The host's uptime is far over 180 s, so the window is set huge here; the eio case above is the "too late" one.
RECLAIM_ENV = {'HOST_MLB_FAIL_AT_BLOCK': '150', 'HOST_MLB_FAIL_ERRNO': '12', 'PMCP_AA_RECLAIM_S': '4000000000'}
r = run('reclaim', plan_synth([(1, 1, 20000, 20000, False), (119, 0, 1500, 6000, False)], seed=15), env_add=RECLAIM_ENV)
rl = line(r.status, 'ponowne przejecie MOST:')
mlog = open(r.P('mlb.ts.log')).read()
check(r.dmdt_before_close == ['dc 72', 'sc 4 72', 'dc 72', 'sc 4 72'], 'reclaim: dmdt release again, no restore while running %r'
      % r.dmdt_before_close)
check(r.dmdt == ['dc 72', 'sc 4 72', 'dc 72', 'sc 4 72', 'dc 70 33', 'sc 4 70'], 'reclaim: one restore at the end %r' % r.dmdt)
check(num(rl, 'proby') == 1 and num(rl, 'nieudane') == 0 and num(rl, 'IDR_ponownie') == 1, 'reclaim: counted %r' % rl)
check('MOST zabrane (blad zapisu errno=12)' in r.status and 'MOST znowu nasze' in r.status and 'IDR ponownie: tak' in r.status,
      'reclaim: events logged')
check('przejety ponownie (direct)' in r.status_before_close and 'MOST oddane' not in r.status_before_close,
      'reclaim: MOST still ours after it')
check(mlog.count('open path=') == 2 and mlog.count('code=0x80040509') == 2 and mlog.count('close fd') == 2,
      'reclaim: device reopened with the start devctl, closed twice')
check(mlog.split('errno=12', 1)[-1].count('ret=12032') > 50, 'reclaim: blocks written after the reopen')
check(r.acks == 120 and r.other == 0 and r.rc == 0, 'reclaim: every frame ACKed, no IDR request, exit 0 (%d %d %s)'
      % (r.acks, r.other, r.rc))

# 7c. the third failure with PMCP_AA_RECLAIM_MAX=2: two reclaims, then MOST given back as before
r = run('reclaim-max', plan_synth([(1, 1, 20000, 20000, False), (149, 0, 1500, 6000, False)], seed=16),
        env_add=dict(RECLAIM_ENV, HOST_MLB_FAIL_AT_BLOCK='100', HOST_MLB_FAIL_REPEAT='100', PMCP_AA_RECLAIM_MAX='2'))
rl = line(r.status, 'ponowne przejecie MOST:')
check(num(rl, 'proby') == 2 and num(rl, 'IDR_ponownie') == 2, 'reclaim-max: two reclaims %r' % rl)
check(r.dmdt == ['dc 72', 'sc 4 72'] * 3 + ['dc 70 33', 'sc 4 70'], 'reclaim-max: then given back %r' % r.dmdt)
check('bez ponownego przejecia' in r.status and 'MOST oddane (blad zapisu errno=12)' in r.status,
      'reclaim-max: the third one goes the old way')
check(r.acks == 150 and r.rc == 0, 'reclaim-max: every frame ACKed, exit 0 (%d %s)' % (r.acks, r.rc))

# 7d. PMCP_AA_RECLAIM_S=0 turns it off; a short write is never reclaimed
r = run('reclaim-off', plan_synth([(1, 1, 20000, 20000, False), (59, 0, 1500, 6000, False)], seed=17),
        env_add=dict(RECLAIM_ENV, PMCP_AA_RECLAIM_S='0'))
check(r.dmdt_before_close == RESTORE and num(line(r.status, 'ponowne przejecie MOST:'), 'proby') == 0,
      'reclaim-off: MOST given back at once %r' % r.dmdt_before_close)
r = run('reclaim-short', plan_synth([(1, 1, 20000, 20000, False), (59, 0, 1500, 6000, False)], seed=18),
        env_add={'HOST_MLB_PARTIAL': '1', 'PMCP_AA_RECLAIM_S': '4000000000'})
check(r.dmdt_before_close == RESTORE and num(line(r.status, 'ponowne przejecie MOST:'), 'proby') == 0,
      'reclaim-short: a short write is not reclaimed %r' % r.dmdt_before_close)

# 8. short write (the driver takes part of a block): reported, MOST given back
r = analyse(run('short-write', plan_synth(STEADY, seed=13), env_add={'HOST_MLB_PARTIAL': '1'}))
check('krotki zapis' in r.status_before_close and r.dmdt_before_close == RESTORE, 'short-write: reported, MOST given back %r'
      % line(r.status_before_close, 'blad:'))
check(num(line(r.status, 'zapis MOST:'), 'krotkie') == 1 and r.acks == 150, 'short-write: counted, ACKs go on (%d)' % r.acks)

# 9. start devctl fails: no MOST, guardian restores, session = analysis
r = run('start-fail', plan_synth([(1, 1, 20000, 20000, False), (29, 0, 1500, 6000, False)], seed=14),
        env_add={'HOST_MLB_START_STATUS': '5'})
check(r.dmdt_before_close == RESTORE and 'MOST oddawane' in r.status_before_close,
      'start-fail: MOST given back at once, session went on %r' % r.dmdt_before_close)
check('isoTX2 open errno=0 start=5' in r.status_before_close and 'start=5' in line(r.status, 'devctl:'),
      'start-fail: reason and devctl values in the status')
check(r.acks == 30, 'start-fail: every frame ACKed (%d)' % r.acks)

# 10. frames over the ring's 256 KB limit go out whole in direct mode
BIG = [(1, 1, 20000, 20000, False), (5, 0, 1500, 3000, False), (2, 0, 300000, 320000, False), (12, 0, 1500, 3000, False)]
r = analyse(run('big-frames', plan_synth(BIG, seed=15), env_add={'PMCP_AA_ACK_HIGH_PKTS': '1024'}, ack_idle=2.0))
common(r, 'big-frames', 20, lead_min=4500)
check('odrzucone duze=0' in r.status, 'big-frames: no frame refused (300 KB > ring slot)')

# 11. start sync (v6) in direct mode: the first IDR repeated while its ACK is held, then every frame in order
r = run('sync', plan_synth([(1, 1, 20000, 20000, False), (59, 0, 1500, 6000, False)], seed=16),
        env_add={'PMCP_AA_SYNC_HOLD_MS': '600', 'PMCP_AA_DIRECT_SYNC_HOLD_MS': '600', 'PMCP_AA_SYNC_REPEAT_MS': '200'})
sl = line(r.status, 'sync startu')
check('plan 600ms co 200ms' in sl, 'sync: v13 direct hold from PMCP_AA_DIRECT_SYNC_HOLD_MS: %s' % sl)
rep = num(sl, 'powtorki IDR')
fr = [json.loads(l) for l in open(r.P('input/frames.jsonl'))]
first = [x for x in fr if x.get('frame_no') == 1][0]
with open(r.P('input/frames.jsonl'), 'w') as f:   # the repeats are inputs of their own for the analyser
    for x in fr:
        f.write(json.dumps(x) + '\n')
    for k in range(rep):
        f.write(json.dumps(dict(first, frame_no=1 + (k + 1) / 10.0, idx=1000 + k, ring_seq=1000 + k)) + '\n')
analyse(r)
check('zrobiony' in sl and rep >= 2, 'sync: done in direct mode %s' % sl)
check(r.analyser_rc == 0 and r.norm['output_aus'] == 60 + rep, 'sync: IDR x %d then 59 frames in the TS (%s AUs)' % (1 + rep, r.norm and r.norm['output_aus']))
check(r.acks == 60, 'sync: one ACK per frame (%d)' % r.acks)

# 12. gamma settings (start sync + pacing) with direct output: shorter, nothing lost
s3 = open(os.path.join(HERE, '..', '..', 'unit', 'feeder-gamma.conf')).read()
conf = (s3.replace('SETTLE_MS=5000', 'SETTLE_MS=200').replace('HOLD_MS=3000', 'HOLD_MS=600').replace('REPEAT_MS=500', 'REPEAT_MS=200')
        + '\nPMCP_AA_OUTPUT=direct\n')
r = run('gamma-direct', plan_synth([(1, 1, 20000, 20000, False), (59, 0, 1500, 6000, False)], seed=17), conf=conf,
        env_add={'PMCP_AA_OUTPUT': None})
check('wyjscie=direct' in r.status.split('\n')[0] and 'dawkowanie: wylaczone (direct' in r.status and 'zrobiony' in r.status,
      'gamma-direct: output from feeder.conf, v12: pacing off in direct (PACE_KBPS ignored), sync on')
check(r.acks == 60 and num(line(r.status, 'AU direct:'), 'wyslane') >= 60, 'gamma-direct: every frame (%s)' % line(r.status, 'AU direct:'))
check('plan 1500ms' in line(r.status, 'sync startu'), 'gamma-direct: v13 direct hold 1500 ms, not feeder.conf\'s: %s' % line(r.status, 'sync startu'))
check('max 18000' not in line(r.status, 'PTS-PCR') and '(cel 9000 min 4500 max 11700)' in line(r.status, 'PTS-PCR'),
      'gamma-direct: v13 lead max 130 ms: %s' % line(r.status, 'PTS-PCR'))

# 12b. v13 (A152): a 3.5 s phone gap and a 4 s silence before the end are in the MOST events; the full status of the
# earlier sessions is kept as <status>-prev1..3 and the session line has the gap and ACK counts
SPATH = os.path.join(OUT, 'prev-status', 'status.txt')
shutil.rmtree(os.path.dirname(SPATH), ignore_errors=True); os.makedirs(os.path.dirname(SPATH))
for k in range(4):
    r = run('prev%d' % k, plan_synth([(1, 1, 20000, 20000, False), (29, 0, 1500, 6000, False)], seed=40 + k), status=SPATH,
            pause={15: 3.5} if k == 3 else None, ack_idle=4.0 if k == 3 else 1.0)
check('przerwa od telefonu 3' in r.status or 'przerwa od telefonu 4' in r.status, 'gap: phone gap logged %s' % [l for l in r.status.split('\n') if 'przerwa od' in l])
bl = [l for l in r.status.split('\n') if 'brak klatek 3 s' in l]
check(len(bl) == 2 and 'ACK czeka 0 (wstrzymane nie)' in bl[-1] and 'kolejka 0 pakietow/0 AU' in bl[-1], 'gap: stall noted with ACK/queue state %s' % bl)
pv = [open(SPATH + '-prev%d' % k).read() if os.path.exists(SPATH + '-prev%d' % k) else '' for k in (1, 2, 3)]
check(all(x.startswith('PMCP AA FEEDER v15') for x in pv) and not os.path.exists(SPATH + '-prev4'), 'prev: 3 earlier full statuses kept')
check([num(line(x, 'klatki='), 'klatki') for x in pv] == [30, 30, 30] and pv[0] != pv[1] != pv[2], 'prev: prev1..3 are separate sessions')
sess = [l for l in open(os.path.join(OUT, 'prev3', 'pmcp-aa-sessions.txt')).read().split('\n') if l]
check(len(sess) == 1 and '>3s=1' in sess[0] and 'ACK=30' in sess[0]
      and ('ostatnia klatka 4s przed koncem' in sess[0] or 'ostatnia klatka 5s przed koncem' in sess[0]), 'session line: gaps, last frame, ACKs %s' % sess)

# 13. capture: 2 s of a 5 s stream, Annex B with an AUD per AU, replayable; plus the 6 MB limit
r = run('capture', plan_synth(STEADY, seed=18),
        env_add={'PMCP_AA_CAPTURE_S': '2', 'PMCP_AA_CAPTURE_PATH': os.path.join(OUT, 'capture-files', 'cap', 'aa.h264')})
cp = os.path.join(OUT, 'capture-files', 'cap', 'aa.h264')
data = open(cp, 'rb').read() if os.path.exists(cp) else b''
aus, cur = [], []
for nal in split_nals(data):
    if (nal[0] & 0x1f) == 9:
        if cur: aus.append(cur)
        cur = []
    else:
        cur.append(nal)
if cur: aus.append(cur)
idx = open(cp + '.idx').read().split('\n')[:-1] if os.path.exists(cp + '.idx') else []
sent = [split_nals(a) for a, _, _ in plan_synth(STEADY, seed=18)]
ok = all([n for n in got if (n[0] & 0x1f) not in (7, 8)] == [n for n in want if (n[0] & 0x1f) not in (7, 8, 9)]
         for got, want in zip(aus, sent))
check(50 <= len(aus) <= 66 and len(idx) == len(aus) and ok, 'capture: %d AUs (~2 s at 30 fps), same NALs as sent, idx lines %d'
      % (len(aus), len(idx)))
check(len(aus) and (aus[0][0][0] & 0x1f) == 7 and (aus[0][1][0] & 0x1f) == 8, 'capture: SPS/PPS sent before the first frame kept in front of it')
check('nagranie: zapisane' in r.status, 'capture: status %s' % line(r.status, 'nagranie:'))
r = run('capture-limit', plan_synth([(1, 1, 20000, 20000, False), (79, 0, 95000, 105000, False)], seed=19),
        env_add={'PMCP_AA_CAPTURE_S': '600', 'PMCP_AA_CAPTURE_PATH': os.path.join(OUT, 'capture-files', 'big.h264')}, ack_idle=2.0)
sz = os.path.getsize(os.path.join(OUT, 'capture-files', 'big.h264')) if os.path.exists(os.path.join(OUT, 'capture-files', 'big.h264')) else 0
check(5 * 2 ** 20 < sz <= 6 * 2 ** 20 and 'nagranie: zapisane' in r.status, 'capture-limit: stopped at the 6 MB limit (%d bytes)' % sz)

# 14. PMCP_AA_OUTPUT=ring explicitly: today's path (fake bridge, ring), no device touched
r = run('ring-explicit', plan_synth([(1, 1, 20000, 20000, False), (39, 0, 1500, 6000, False)], seed=20),
        env_add={'PMCP_AA_OUTPUT': 'ring', 'FAKE_BRIDGE_PRINT': '1', 'PMCP_AA_CAPTURE_S': '1',
                 'PMCP_AA_CAPTURE_PATH': os.path.join(OUT, 'capture-files', 'ring.h264')})
check(not os.path.exists(r.P('mlb.ts')) and os.path.exists(r.P('bridge.jsonl')) and r.acks == 40, 'ring-explicit: ring + bridge, no isoTX2')
check(r.status.startswith('PMCP AA FEEDER v15 mode=most czas='), 'ring-explicit: header without wyjscie=direct')
bt = open(r.P('pmcp-aa-bridge.txt')).read() if os.path.exists(r.P('pmcp-aa-bridge.txt')) else ''
check('bridge poczatek 01: bridge: start status=0 packets=64' in bt and 'bridge poczatek 02: bridge: latency-reset' in bt,
      'ring-explicit: guardian keeps the first bridge lines')
check('bridge poczatek 01: ' in r.status, 'ring-explicit: first bridge lines in the status')
rc_ = os.path.join(OUT, 'capture-files', 'ring.h264')
naud = sum(1 for n in split_nals(open(rc_, 'rb').read()) if (n[0] & 0x1f) == 9) if os.path.exists(rc_) else 0
check(25 <= naud <= 36 and 'nagranie: zapisane' in r.status, 'ring-explicit: capture works with the ring output too (%d AUs in 1 s)' % naud)

# 15. GEM switches (pmcp.sh aa-output / aa-capture) in /mnt/persist/pmcp/aa-extra.conf: output and capture win over the
# pinned feeder.conf, any other key there is ignored (here PMCP_AA_MODE=analyze would turn MOST off)
r = run('extra-switch', plan_synth([(1, 1, 20000, 20000, False), (39, 0, 1500, 6000, False)], seed=21),
        conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=ring\n', env_add={'PMCP_AA_OUTPUT': None, 'PMCP_AA_MODE': None,
        'PMCP_AA_CAPTURE_PATH': os.path.join(OUT, 'capture-files', 'extra.h264')},
        extra='PMCP_AA_OUTPUT=direct\nPMCP_AA_CAPTURE_S=1\nPMCP_AA_MODE=analyze\nPMCP_AA_CAPTURE_PATH=/tmp/x\n')
check(r.status.startswith('PMCP AA FEEDER v15 mode=most wyjscie=direct'), 'extra-switch: output from aa-extra.conf, MODE there ignored')
check(os.path.exists(os.path.join(OUT, 'capture-files', 'extra.h264')) and 'nagranie: zapisane' in r.status,
      'extra-switch: capture switched on there, path key there ignored')
check(r.acks == 40, 'extra-switch: every frame (%d)' % r.acks)
r = run('extra-ring', plan_synth([(1, 1, 20000, 20000, False), (19, 0, 1500, 6000, False)], seed=22),
        conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=direct\n', env_add={'PMCP_AA_OUTPUT': None}, extra='PMCP_AA_OUTPUT=ring\n')
check(os.path.exists(r.P('bridge.jsonl')) and not os.path.exists(r.P('mlb.ts')), 'extra-ring: switch back to the bridge wins over feeder.conf')
check('wyjscie: bridge (ring) (z: aa-extra.conf) zignorowane wartosci=0' in r.status, 'extra-ring: status shows the source')

# 15b. v14 (AA 1.0, A153): the on-unit UI writes the switch without a trial, so a bad value must give the default
# (feeder.conf: direct), start without an error, and change no file
BAD = ['PMCP_AA_OUTPUT=\n', 'PMCP_AA_OUTPUT=bridge\n', 'PMCP_AA_OUTPUT=Direct\n', 'PMCP_AA_OUTPUT=direct;rm\n',
       'PMCP_AA_OUTPUT=\xc3\xa9\n', 'PMCP_AA_OUTPUT=rin\n', 'PMCP_AA_OUTPUT= direct\n']
for k, ex in enumerate(BAD):
    r = run('extra-bad%d' % k, plan_synth([(1, 1, 20000, 20000, False), (9, 0, 1500, 6000, False)], seed=60 + k),
            conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=direct\n', env_add={'PMCP_AA_OUTPUT': None}, extra=ex)
    before = open(r.P('extra.conf')).read()
    check(r.rc == 0 and os.path.exists(r.P('mlb.ts')) and not os.path.exists(r.P('bridge.jsonl')) and r.acks == 10
          and 'wyjscie: direct (z: feeder.conf) zignorowane wartosci=1' in r.status and 'blad: strumien zamkniety' in r.status
          and before == ex, 'extra-bad %r: default direct, no error, file unchanged' % ex)
r = run('extra-crlf', plan_synth([(1, 1, 20000, 20000, False), (9, 0, 1500, 6000, False)], seed=70),
        conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=direct\n', env_add={'PMCP_AA_OUTPUT': None}, extra='PMCP_AA_OUTPUT=ring \r\n')
check(os.path.exists(r.P('bridge.jsonl')) and 'zignorowane wartosci=0' in r.status, 'extra-crlf: "ring" with a blank and CRLF is ring')
r = run('extra-dup', plan_synth([(1, 1, 20000, 20000, False), (9, 0, 1500, 6000, False)], seed=71),
        conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=direct\n', env_add={'PMCP_AA_OUTPUT': None},
        extra='PMCP_AA_OUTPUT=junk\nPMCP_AA_OUTPUT=ring\nPMCP_AA_OUTPUT=direct\n')
check(os.path.exists(r.P('bridge.jsonl')) and 'wyjscie: bridge (ring) (z: aa-extra.conf) zignorowane wartosci=1' in r.status,
      'extra-dup: the first valid line wins, the junk one is counted')
r = run('conf-bad', plan_synth([(1, 1, 20000, 20000, False), (9, 0, 1500, 6000, False)], seed=72),
        conf='PMCP_AA_MODE=most\nPMCP_AA_OUTPUT=xyz\n', env_add={'PMCP_AA_OUTPUT': None})
check(os.path.exists(r.P('bridge.jsonl')) and 'wyjscie: bridge (ring) (z: domyslne)' in r.status,
      'conf-bad: nothing valid anywhere = the built-in ring (feeder.conf is pinned by hash, so only a test case)')

print('runs kept in', OUT)
print('FAILED CHECKS: %d' % len(fails))
sys.exit(1 if fails else 0)
