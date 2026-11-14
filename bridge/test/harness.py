#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""pmcp-most stage 1 host tests (run with python3 -I, called by run_tests.sh).

usage: harness.py BUILD_DIR TS_TOOLS_DIR [H264_CAPTURE|-] [only-test-name ...]

Every test runs the host bridge (ALTSCREEN_BRIDGE_FILE_OUTPUT, regular file instead of isoTX2) in its
own directory BUILD_DIR/runs/<test>/ with the ring, force-IDR marker, contract directory, log and fake
dmdt redirected there by environment variables (see shim/host_shim.h and src/pmcp_most.h).
"""
import hashlib, json, os, re, signal, subprocess, sys, time

BUILD, TOOLS = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
H264 = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != '-' else None
ONLY = set(sys.argv[4:])
HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCER = os.path.join(BUILD, 'producer')
BRIDGE = os.path.join(BUILD, 'bridge-host')
BRIDGE_UP = os.path.join(BUILD, 'bridge-host-upstream')
BRIDGE_ENOMEM = os.path.join(BUILD, 'bridge-host-enomem')
FAKE_DMDT = os.path.join(HERE, 'fake_dmdt.sh')
LOG_LIMIT = 64 * 1024
STATUS_KEYS = ['v', 'ready', 'pid', 'owner_gen', 'ring_gen', 'seq', 'frames', 'drops', 'overruns',
               'latency_resets', 'age_ms', 'queue_pkts', 'queue_hi', 'reclaims', 'most_errno', 'up_ms']

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('ok     ' if cond else 'FAILED ') + name + (f'  [{detail}]' if detail and not cond else ''),
          flush=True)
    return bool(cond)


class Run:
    def __init__(self, name, bridge=BRIDGE, env=None, log='pmcp'):
        self.name = name
        self.dir = os.path.join(BUILD, 'runs', name)
        subprocess.run(['rm', '-rf', self.dir], check=True)
        os.makedirs(os.path.join(self.dir, 'input'))
        self.src_dir = os.path.join(self.dir, 'most-src')
        os.makedirs(self.src_dir)
        self.ring = os.path.join(self.dir, 'ring.bin')
        self.idr = os.path.join(self.dir, 'force-idr.request')
        self.log = os.path.join(self.dir, 'pmcp-most', 'bridge.log')
        self.stderr_path = os.path.join(self.dir, 'bridge.stderr')
        self.dmdt_log = os.path.join(self.dir, 'dmdt.log')
        self.env = dict(os.environ, HOST_RING_PATH=self.ring, HOST_IDR_PATH=self.idr,
                        HOST_CACHE_LOCK=os.path.join(self.dir, 'cache.lock'),
                        HOST_INTRO_ONCE_PATH=os.path.join(self.dir, 'intro-played'),
                        HOST_DMDT_PATH=FAKE_DMDT, FAKE_DMDT_LOG=self.dmdt_log,
                        PMCP_MOST_LOG=self.log, PMCP_MOST_SRC_DIR=self.src_dir)
        self.env.pop('CARPLAY_CLUSTER_INTRO', None)
        if env: self.env.update(env)
        self.bridge_bin = bridge
        self.log_kind = log   # 'pmcp': our log file; 'stderr': upstream build

    def start(self):
        self.err = open(self.stderr_path, 'w')
        self.t_start = time.monotonic()
        self.p = subprocess.Popen([self.bridge_bin, os.path.join(self.dir, 'mlb.ts')], env=self.env,
                                  stdout=self.err, stderr=subprocess.STDOUT)
        return self

    def produce(self, *args, wait=True):
        cmd = [PRODUCER, '--ring', self.ring, '--idr', self.idr, '--out', os.path.join(self.dir, 'input')]
        cmd += [str(a) for a in args]
        self.prod = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        if wait:
            self.prod.wait(timeout=120)
        return self.prod

    def stop(self, timeout=10):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
        try:
            self.p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.p.kill(); self.p.wait()
        self.err.close()
        return self.p.returncode

    def logtext(self):
        path = self.log if self.log_kind == 'pmcp' else self.stderr_path
        text = ''
        for p in (path + '.1', path):
            if os.path.exists(p):
                text += open(p, errors='replace').read()
        return text

    def frames_manifest(self):
        """frames.raw.jsonl + input.avcc -> input/frames.jsonl as ts_analyse.py expects."""
        inp = os.path.join(self.dir, 'input')
        data = open(os.path.join(inp, 'input.avcc'), 'rb').read()
        out = []
        for line in open(os.path.join(inp, 'frames.raw.jsonl')):
            r = json.loads(line)
            if 'avcc_off' in r:
                r['avcc_sha256'] = hashlib.sha256(data[r['avcc_off']:r['avcc_off'] + r['avcc_bytes']]).hexdigest()
            out.append(r)
        with open(os.path.join(inp, 'frames.jsonl'), 'w') as f:
            for r in out: f.write(json.dumps(r) + '\n')
        return out

    def analyse(self):
        self.frames_manifest()
        stderr = self.log if self.log_kind == 'pmcp' else self.stderr_path
        # ts_analyse reads one stderr file: give it the whole log (rotated part first)
        merged = os.path.join(self.dir, 'bridge.events')
        with open(merged, 'w') as f: f.write(self.logtext())
        r = subprocess.run([sys.executable, '-I', os.path.join(TOOLS, 'ts_analyse.py'), self.dir,
                            '--stderr', merged], capture_output=True, text=True)
        norm = json.load(open(os.path.join(self.dir, 'norm.json'))) if os.path.exists(
            os.path.join(self.dir, 'norm.json')) else None
        return r.returncode, r.stdout + r.stderr, norm

    def status(self):
        try:
            return open(os.path.join(self.src_dir, 'consumer')).read()
        except FileNotFoundError:
            return None

    def cleanup(self):
        if os.path.exists(self.ring): os.unlink(self.ring)


def parse_status(line):
    pairs = [tok.split('=', 1) for tok in line.strip().split(' ')]
    return [k for k, _ in pairs], {k: v for k, v in pairs}


def wait_ring(run, timeout=5.0):
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        if os.path.exists(run.ring) and os.path.getsize(run.ring) == 0x1000710: return True
        time.sleep(0.02)
    return False


def log_sizes_ok(run):
    for p in (run.log, run.log + '.1'):
        if os.path.exists(p) and os.path.getsize(p) > LOG_LIMIT: return False
    return not os.path.exists(run.log + '.2')


# ------------------------------------------------------------------ tests
def test_steady(name='steady', h264=None, frames=150):
    r = Run(name).start()
    samples = []
    args = ['--frames', frames] + (['--h264', h264] if h264 else [])
    prod = r.produce(*args, wait=False)
    while prod.poll() is None:
        s = r.status()
        if s: samples.append((time.monotonic(), s))
        time.sleep(0.1)
    time.sleep(0.6)   # let the writer drain the queue
    alive = r.p.poll() is None
    rc = r.stop()
    code, out, norm = r.analyse()
    check(f'{name}: bridge keeps running without contract files (upstream behaviour)', alive)
    check(f'{name}: exit status 0 after SIGTERM', rc == 0, rc)
    check(f'{name}: ts_analyse format checks pass', code == 0, out[-600:])
    nin = norm['input_frames'] if norm else -1
    check(f'{name}: every input frame out, no drops', norm and not norm['missing_frame_nos'] and
          norm['output_aus'] == nin and nin > 0, f"in={nin} out={norm and norm['output_aus']} "
          f"missing={norm and norm['missing_frame_nos'][:10]}")
    check(f'{name}: log within 64 KB, no second rotation', log_sizes_ok(r))
    r.cleanup()
    return r, samples, norm


def test_status(r, samples):
    name = 'status'
    lines = [s for _, s in samples]
    ok_keys = all(parse_status(s)[0] == STATUS_KEYS for s in lines) and lines
    check(f'{name}: consumer file has exactly the contract v0.2 keys in order', ok_keys,
          lines[:1])
    check(f'{name}: one line, <= 255 bytes, ends with newline',
          lines and all(len(s.encode()) <= 255 and s.endswith('\n') and s.count('\n') == 1 for s in lines))
    vals = [parse_status(s)[1] for s in lines]
    check(f'{name}: pid is the bridge pid', vals and all(v['pid'] == str(r.p.pid) for v in vals))
    check(f'{name}: ready=1 while streaming', any(v['ready'] == '1' for v in vals))
    ups = sorted({int(v['up_ms']) for v in vals})
    steps = [b - a for a, b in zip(ups, ups[1:])]
    check(f'{name}: refreshed every 1000 +- 100 ms', len(steps) >= 3 and all(900 <= s <= 1100 for s in steps),
          steps)
    fr = [int(v['frames']) for v in vals]
    check(f'{name}: frames counter grows', fr and fr[-1] > fr[0], fr[:3] + fr[-3:])
    final = r.status()
    check(f'{name}: ready=0 written on exit', final and parse_status(final)[1].get('ready') == '0', final)
    leftovers = [f for f in os.listdir(r.src_dir) if '.tmp.' in f]
    check(f'{name}: no temporary files left', not leftovers, leftovers)


def test_upstream_parity():
    """Same deterministic input through the unmodified upstream bridge and ours: identical TS."""
    up = Run('parity-upstream', bridge=BRIDGE_UP, log='stderr').start()
    up.produce('--frames', 120); time.sleep(0.6); up.stop()
    c1, out1, _ = up.analyse(); up.cleanup()
    ours = Run('parity-pmcp').start()
    ours.produce('--frames', 120); time.sleep(0.6); ours.stop()
    c2, out2, _ = ours.analyse(); ours.cleanup()
    check('parity: upstream run passes ts_analyse', c1 == 0, out1[-400:])
    r = subprocess.run([sys.executable, '-I', os.path.join(TOOLS, 'ts_compare.py'), up.dir, ours.dir,
                        '--mode', 'cp'], capture_output=True, text=True)
    check('parity: ts_compare --mode cp upstream vs pmcp = SAME', r.returncode == 0 and 'SAME' in r.stdout,
          r.stdout[-600:])
    with open(os.path.join(BUILD, 'runs', 'parity-compare.txt'), 'w') as f: f.write(r.stdout)


def test_force_idr():
    r = Run('force-idr').start()
    r.produce('--frames', 150, '--burst-at', 40, '--burst-count', 12, '--burst-size', 100000,
              '--idr-on-request', 1)
    time.sleep(0.8)
    rc = r.stop()
    code, out, norm = r.analyse()
    log = r.logtext()
    frames = [json.loads(l) for l in open(os.path.join(r.dir, 'input', 'frames.raw.jsonl'))]
    reqs = [f for f in frames if f.get('event') == 'idr-request']
    forced = [f for f in frames if f.get('forced_idr')]
    check('force-idr: backlog overflow -> latency-reset', 'bridge: latency-reset' in log)
    check('force-idr: marker created (latency-request-idr status=0)',
          re.search(r'latency-request-idr .*status=0', log) is not None)
    check('force-idr: producer saw the marker and sent an IDR', reqs and forced, f'{len(reqs)} {len(forced)}')
    check('force-idr: bridge resumed on the keyframe (latency-resume-idr)', 'latency-resume-idr' in log)
    check('force-idr: ts_analyse format checks pass', code == 0, out[-600:])
    runs = norm['drop_runs'] if norm else []
    check('force-idr: every drop run ends on an IDR, frames flow after it',
          runs and all(x['resumed_with_idr'] for x in runs) and norm['output_aus'] > 60,
          runs)
    st = parse_status(r.status() or '')[1]
    check('force-idr: consumer latency_resets >= 1', int(st.get('latency_resets', 0)) >= 1, st)
    check('force-idr: exit 0', rc == 0, rc)
    r.cleanup()


def test_enomem():
    r = Run('enomem', bridge=BRIDGE_ENOMEM, env=dict(HOST_RECLAIM_WINDOW_US='600000000')).start()
    prod = r.produce('--frames', 400, '--idr-on-request', 1, wait=False)
    try:
        r.p.wait(timeout=20)
    except subprocess.TimeoutExpired:
        pass
    exited = r.p.poll() is not None
    prod.kill(); prod.wait()
    rc = r.stop()
    log = r.logtext()
    calls = open(r.dmdt_log).read().splitlines() if os.path.exists(r.dmdt_log) else []
    check('enomem: dmdt called as dc 72, sc 4 72, three times', calls == ['dc 72', 'sc 4 72'] * 3, calls)
    check('enomem: three reclaim attempts with dmdt=0/0 and reopen=ok',
          len(re.findall(r'most-reclaim attempt=\d+ uptime_ms=\d+ dmdt=0/0', log)) == 3 and
          len(re.findall(r'most-reclaim attempt=\d+ reopen=ok', log)) == 3)
    check('enomem: picture resynced after a reclaim (most-reclaim-resync, then latency-resume-idr)',
          'most-reclaim-resync' in log and log.find('latency-resume-idr') > log.find('most-reclaim-resync'))
    check('enomem: fourth ENOMEM not attempted (max 3), bridge exits by itself',
          'most-reclaim not-attempted reclaims=3 max=3' in log and exited and rc == 0, f'exited={exited} rc={rc}')
    st = parse_status(r.status() or '')[1]
    check('enomem: consumer reclaims=3, most_errno=ENOMEM, ready=0',
          st.get('reclaims') == '3' and st.get('most_errno') == '12' and st.get('ready') == '0', st)
    r.cleanup()

    w = Run('enomem-window', bridge=BRIDGE_ENOMEM, env=dict(HOST_RECLAIM_WINDOW_US='0')).start()
    prod = w.produce('--frames', 200, wait=False)
    try:
        w.p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    exited = w.p.poll() is not None
    prod.kill(); prod.wait(); w.stop()
    log = w.logtext()
    check('enomem-window: outside the window no dmdt call, not attempted, exit',
          not os.path.exists(w.dmdt_log) and 'most-reclaim not-attempted reclaims=0' in log and exited)
    w.cleanup()


def write_contract(dirname, name, line):
    tmp = os.path.join(dirname, f'{name}.tmp.{os.getpid()}')
    with open(tmp, 'w') as f: f.write(line)
    os.rename(tmp, os.path.join(dirname, name))


def test_session_stop():
    r = Run('session-stop').start()
    prod = r.produce('--frames', 600, '--session-dir', r.src_dir, '--src', 'wired', '--gen', 7,
                     '--stop-after', 60, '--stop-hold-ms', 4000, wait=False)
    line = prod.stdout.readline()
    t_stop = time.monotonic()
    try:
        r.p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    t_exit = time.monotonic()
    exited = r.p.poll() is not None
    prod.kill(); prod.wait()
    rc = r.stop()
    log = r.logtext()
    dt = t_exit - t_stop
    print(f'info   session-stop: bridge exit {dt * 1000:.0f} ms after state=stop', flush=True)
    check('session-stop: producer wrote state=stop', line.strip() == 'STOP', line)
    check('session-stop: bridge ended the stream within 1.5 s', exited and dt <= 1.5, f'{dt:.3f} s')
    check('session-stop: logged session-stop src=wired gen=7 reason=test',
          'session-stop src=wired gen=7' in log and 'reason=test' in log)
    st = parse_status(r.status() or '')[1]
    check('session-stop: exit 0, consumer ready=0 owner_gen=7', rc == 0 and st.get('ready') == '0' and
          st.get('owner_gen') == '7', f'rc={rc} {st}')
    r.cleanup()

    # a stop older than the bridge (previous session) must not stop a new bridge
    s = Run('session-stale')
    write_contract(s.src_dir, 'owner', 'v=1 src=wired pid=1 gen=3 since_ms=1\n')
    write_contract(s.src_dir, 'wired.session', 'v=1 state=stop gen=3 pid=1 ts_ms=1 reason=old\n')
    s.start()
    s.produce('--frames', 60)
    alive = s.p.poll() is None
    s.stop()
    check('session-stale: old state=stop is ignored, bridge keeps running',
          alive and 'session-stop-ignored' in s.logtext())
    s.cleanup()

    # the session file of a producer seen alive vanishes and its pid is dead
    v = Run('session-vanished')
    dead = subprocess.Popen(['/usr/bin/true']); dead.wait()
    write_contract(v.src_dir, 'owner', f'v=1 src=wireless pid={dead.pid} gen=2 since_ms=1\n')
    write_contract(v.src_dir, 'wireless.session', f'v=1 state=start gen=2 pid={dead.pid} ts_ms=1 reason=connect\n')
    v.start()
    wait_ring(v)
    time.sleep(0.5)
    alive_before = v.p.poll() is None
    os.unlink(os.path.join(v.src_dir, 'wireless.session'))
    t0 = time.monotonic()
    try:
        v.p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    dt = time.monotonic() - t0
    print(f'info   session-vanished: bridge exit {dt * 1000:.0f} ms after the file vanished', flush=True)
    exited = v.p.poll() is not None
    v.stop()
    check('session-vanished: file gone + dead pid ends the stream within 1.5 s',
          alive_before and exited and dt <= 1.5 and 'reason=vanished-dead-pid' in v.logtext(),
          f'alive_before={alive_before} exited={exited} dt={dt:.3f}')
    v.cleanup()


def test_log_rotation():
    r = Run('log-rotation')
    os.makedirs(os.path.dirname(r.log))
    filler = ('x' * 99 + '\n') * 650   # 65000 bytes
    open(r.log, 'w').write(filler)
    open(r.log + '.1', 'w').write('OLD1\n')
    r.start()
    r.produce('--frames', 30)
    r.stop()
    a = open(r.log).read() if os.path.exists(r.log) else ''
    b = open(r.log + '.1').read() if os.path.exists(r.log + '.1') else ''
    check('log-rotation: full log moved to bridge.log.1 (old .1 replaced)', b.startswith('xxxx') and 'OLD1' not in b)
    check('log-rotation: both files <= 64 KB, no bridge.log.2', log_sizes_ok(r),
          f'{len(a.encode())} {len(b.encode())}')
    check('log-rotation: new bridge.log starts with the bridge lines', a.startswith('bridge: ') and
          'bridge: complete' in a, a[:120])
    check('log-rotation: nothing went to inherited stderr', os.path.getsize(r.stderr_path) == 0)
    r.cleanup()


def test_provenance():
    """upstream/ is verbatim (PROVENANCE.json sha256); src/ differs only in pmcp-marked hunks."""
    import difflib
    root = os.path.dirname(HERE)
    prov = json.load(open(os.path.join(root, 'upstream', 'PROVENANCE.json')))
    bad = [f['path'] for f in prov['files']
           if hashlib.sha256(open(os.path.join(root, 'upstream', f['path']), 'rb').read()).hexdigest() != f['sha256']]
    check('provenance: upstream/ files match PROVENANCE.json sha256', not bad and prov['files'], bad)
    unmarked = []
    for f in prov['files']:
        name = f['path']
        if not name.endswith(('.c', '.h')): continue
        a = open(os.path.join(root, 'upstream', name)).read().splitlines()
        b = open(os.path.join(root, 'src', name)).read().splitlines()
        hunk = []
        for line in list(difflib.unified_diff(a, b, lineterm='', n=0))[2:] + ['@@ end']:
            if line.startswith('@@'):
                if hunk and not any('pmcp' in h for h in hunk): unmarked.append((name, hunk[:3]))
                hunk = []
            elif line.startswith('-'):
                hunk.append('')   # removed lines need a pmcp marker in the hunk too
            else:
                hunk.append(line)
    check('provenance: every src/ change against upstream is marked pmcp', not unmarked, unmarked[:3])


def main():
    os.makedirs(os.path.join(BUILD, 'runs'), exist_ok=True)
    br = os.path.join(BUILD, 'build-results.txt')
    if os.path.exists(br):
        for line in open(br):
            st, _, name = line.strip().partition(' ')
            check(name, st == 'ok')
    tests = [('provenance', test_provenance), ('steady', None), ('real-h264', None), ('parity', test_upstream_parity), ('force-idr', test_force_idr),
             ('enomem', test_enomem), ('session', test_session_stop), ('log', test_log_rotation)]
    for name, fn in tests:
        if ONLY and name not in ONLY: continue
        if name == 'steady':
            r, samples, _ = test_steady('steady', frames=150)
            test_status(r, samples)
        elif name == 'real-h264':
            if H264 and os.path.exists(H264):
                test_steady('real-h264', h264=H264, frames=150)
            else:
                print('skip   real-h264: no capture given')
        else:
            fn()
    ok = sum(1 for _, c in results if c)
    bad = [n for n, c in results if not c]
    print(f'BRIDGE TESTS: {ok} ok, {len(bad)} failed')
    for n in bad: print('  failed: ' + n)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
