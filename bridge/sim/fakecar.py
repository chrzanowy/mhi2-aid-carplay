#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""fake-car: one process that plays the car around our MOST programs (docs/28-symulator-auta.md, stages 1-2).

usage: python3 -I fakecar.py BUILD_DIR [scenario ...]      (run by sim/run_sim.sh)

The real supervisor (pmcp-most-sup) and the real pmcp-most stage 2 bridge (host build with sim_mlb.c) run unchanged;
the car owns the isoTX2 channel (unix socket, sim_mlb.c), dmdt (sim/dmdt -> dmdt.req), the factory VW encoder (an
adversary thread), the phones (ring producer + marker files) and the AID screen. Verdicts come only from what the car
sees: channel calls, dmdt calls, accepted bytes, files and processes. Every run leaves runs/<scenario>/blackbox.txt.

Model parameters: M = measured in the car (visit), A = assumption (docs/28 "Model auta").
"""
import hashlib, json, os, random, re, select, shutil, signal, socket, struct, subprocess, sys, threading, time

BUILD = os.path.abspath(sys.argv[1])
_ARGS = sys.argv[2:]
JOBS = int(_ARGS[_ARGS.index('--jobs') + 1]) if '--jobs' in _ARGS else int(os.environ.get('FAKECAR_JOBS', '1'))
ONLY = [a for i, a in enumerate(_ARGS) if a not in ('--jobs', '--params', '--none') and
        not (i > 0 and _ARGS[i - 1] == '--jobs')]
HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.dirname(HERE)

ENOMEM, EBUSY, EAGAIN, EBADF, ENOTTY = 12, 16, 35 if sys.platform == 'darwin' else 11, 9, 25
DC_START, DC_FLUSH = 0x80040509, 0x40040506
DC_READ = {0x4004050c: 0, 0x4004050d: 0, 0x40040510: 0}   # iface / packet size / block count (A: unknown on MU1161)

PARAMS = {
    'bps': 12288000,          # M: 127 blocks/s = 12.15-12.25 Mbit/s, write_us ~8 ms (bridge metrics 20.11, calib. 24.11)
    'depth': 2 * 12032,       # A: driver FIFO
    'dmdt_call_ms': 400,      # M (derived): one dmdt call blocks ~0.4 s (mathsls: 2 calls + 500 ms = 1.31 s, 14.11)
    'dmdt_ms': 120,           # A: dmdt effect delay (not logged; our open 0-1 s after NvVideoStreamEncoderClose, calib. 24.11)
    'vw_start_s': 0,          # A per run: the encoder's first activity after boot (cold start 22.11: 8 s, it then took isoTX2 from us)
    'vw_knock_ms': 50,        # M: 20 open tries/s (sloginfo 16.11, A208)
    'vw_release_ms': 80,      # A: encoder closes after dc 72 (M: it does close, A222)
    'vw_knock_in_cp': True,   # M: 20 probes/s also in the CP view (sloginfo 22.11); A: a probe never takes isoTX2 - takes are HMI view requests (steals)
    'vw_return_ms': 400,      # A: encoder back after dc 70 33 / sc 4 70
    'aa_fps': 30,             # M (AA): phone frame rate, aa/feeder/test/run_direct_test.py phone model
    'aa_window': 8,           # M (AA): the phone keeps at most 8 frames unACKed
    'aa_idr_every_s': 60,     # M (AA): an IDR about every 60 s, never on request
    'wl_phone_gone_ms': 3000, # A (WL): airplayd sees the phone leave the hotspot (by MAC) after about 3 s
    'wl_idle_ms': 5000,       # M: WL cluster_owner_idle_ms default 5000 (airplayd ap_conf.c, WL 2026-11-24)
    'chan_loss': 0.0,         # A (experiments only): silent loss per accepted block on MOST/AID - the bridge never sees it
    'screen_hold_ms': 1500,   # A: stricter than the car (AA: the AID drops the picture after ~15 s without data)
}
# Source of every parameter: M = measured in the car (where), A = assumption. `fakecar.py BUILD --params` prints it.
PARAM_SRC = {k: ('M' if c.split('#')[1].strip().startswith('M') else 'A', c.split('#', 1)[1].strip())
             for k, c in re.findall(r"^    '(\w+)': [^#\n]*(#.*)$", open(__file__).read(), re.M) if k in PARAMS}
if os.environ.get('FAKECAR_PARAMS'):          # model experiments: FAKECAR_PARAMS='{"dmdt_ms": 300}'
    PARAMS.update(json.loads(os.environ['FAKECAR_PARAMS']))
AA_FEEDER_TEST = os.path.join(BRIDGE_DIR, '..', 'aa', 'feeder', 'test')
AA_MOST_TEST = os.path.join(BRIDGE_DIR, '..', 'aa', 'most', 'test')

T0 = time.monotonic()
LOSS_RNG = random.Random(1161)


def now():
    return time.monotonic() - T0


class BlackBox:
    """Ordered record of everything the car saw; written to blackbox.txt."""
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = []

    def rec(self, kind, text=''):
        with self.lock:
            self.rows.append((now(), kind, text))

    def find(self, kind, pattern='', after=0.0):
        rx = re.compile(pattern)
        return [r for r in self.rows if r[1] == kind and r[0] >= after and rx.search(r[2])]

    def dump(self, path):
        with open(path, 'w') as f:
            for t, k, x in self.rows:
                f.write('%9.3f %-8s %s\n' % (t, k, x))


class Handle:
    def __init__(self, hid, tag, pid):
        self.hid, self.tag, self.pid = hid, tag, pid
        self.t_open = now()
        self.started = False
        self.stolen = False
        self.idr_at = None       # first keyframe accepted on this handle (picture visible)
        self.last_write = None
        self.last_picture = None  # last video PES start (PUSI on PID 0x11): a new picture on the AID
        self.pictures = 0
        self.key_times = []       # every keyframe accepted on this handle
        self.pic_times = []       # every new video PES (picture) accepted
        self.broken_since = None  # silent channel loss: picture broken until the next keyframe
        self.broken = []          # (from, to) intervals of a broken picture
        self.bytes = 0
        self.bad_blocks = 0
        self.cap = None          # every accepted byte of this handle (chan-<id>-<tag>.ts)


class Channel:
    """isoTX2: one holder, FIFO with a drain rate, START before data, ENOMEM after the encoder took it."""
    def __init__(self, bb):
        self.bb = bb
        self.lock = threading.Lock()
        self.holder = None        # Handle, 'vw' or None
        self.next_id = 1
        self.level = 0.0
        self.level_t = now()
        self.handles = {}
        self.rate = 1.0           # drain multiplier: < 1 while the unit is starved (reverse gear, A203/A208)
        self.capdir = None

    def open(self, tag, pid, path):
        with self.lock:
            if self.holder is not None:
                who = self.holder if self.holder == 'vw' else self.holder.tag
                self.bb.rec('chan', 'open tag=%s pid=%d busy holder=%s' % (tag, pid, who))
                return None
            h = Handle(self.next_id, tag, pid)
            self.next_id += 1
            self.holder = h
            self.handles[h.hid] = h
            if self.capdir:
                h.cap = open(os.path.join(self.capdir, 'chan-%d-%s.ts' % (h.hid, tag)), 'wb')
            self.bb.rec('chan', 'open tag=%s pid=%d id=%d path=%s' % (tag, pid, h.hid, path))
            return h

    def close(self, h, why='close'):
        with self.lock:
            if self.holder is h:
                self.holder = None
            if h.cap:
                h.cap.close()
                h.cap = None
            self.bb.rec('chan', '%s tag=%s id=%d bytes=%d stolen=%d' % (why, h.tag, h.hid, h.bytes, h.stolen))

    def devctl(self, h, code, value):
        if code == DC_START:
            with self.lock:
                h.started = True
                self.level, self.level_t = 0.0, now()
            self.bb.rec('chan', 'start tag=%s id=%d' % (h.tag, h.hid))
            return 0, 0
        if code == DC_FLUSH:
            return 0, 0
        if code in DC_READ:
            return 0, DC_READ[code]
        return ENOTTY, 0

    def write(self, h, data):
        with self.lock:
            if h.stolen:
                return -1, ENOMEM
            if self.holder is not h:
                return -1, EBADF
            t = now()
            self.level = max(0.0, self.level - (t - self.level_t) * PARAMS['bps'] * self.rate / 8.0)
            self.level_t = t
            if not h.started or len(data) > PARAMS['depth'] - self.level:
                return -1, EAGAIN
            self.level += len(data)
            h.bytes += len(data)
            h.last_write = t
            if h.cap:
                h.cap.write(data)
            for i in range(0, len(data) - 187, 188):
                if data[i + 1] & 0x40 and ((data[i + 1] & 0x1f) << 8 | data[i + 2]) == 0x11:
                    h.last_picture = t
                    h.pictures += 1
                    h.pic_times.append(t)
            if len(data) % 188 or any(data[i] != 0x47 for i in range(0, len(data), 188)):
                h.bad_blocks += 1
            if re.search(rb'\x00\x00\x01[\x25\x45\x65]', data):
                h.key_times.append(t)
                if h.broken_since is not None:
                    h.broken.append((h.broken_since, t))
                    h.broken_since = None
                if h.idr_at is None:
                    h.idr_at = t
                    self.bb.rec('screen', 'keyframe tag=%s id=%d' % (h.tag, h.hid))
            elif PARAMS['chan_loss'] and h.broken_since is None and LOSS_RNG.random() < PARAMS['chan_loss']:
                h.broken_since = t   # a block lost on the bus: the AID decoder shows artifacts until a keyframe
            return len(data), 0

    # the factory encoder (not a client: lives in the car)
    def vw_try(self):
        with self.lock:
            if self.holder is None:
                self.holder = 'vw'
                return True
            return False

    def vw_steal(self):
        with self.lock:
            old = self.holder
            if isinstance(old, Handle):
                old.stolen = True
            self.holder = 'vw'
            return old

    def vw_drop(self):
        with self.lock:
            if self.holder == 'vw':
                self.holder = None
                return True
            return False


def put(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.rename(tmp, path)


def x264_aus():
    """60 s of libx264 baseline 800x480 at 30 fps, one IDR (the phone's IDR about every 60 s), split at the AUDs.
    Made once per build directory (ffmpeg with libx264 needed; else None and the synthetic stream is used)."""
    path = os.path.join(BUILD, 'aa-x264.h264')
    if not os.path.exists(path):
        if not shutil.which('ffmpeg'):
            return None
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=800x480:rate=30',
                            '-frames:v', '1800', '-c:v', 'libx264', '-profile:v', 'baseline', '-x264-params',
                            'keyint=1800:ref=1:bframes=0:aud=1', '-f', 'h264', path + '.tmp'])
        if r.returncode != 0:
            return None
        os.rename(path + '.tmp', path)
    data = open(path, 'rb').read()
    starts = [m.start() for m in re.finditer(rb'\x00\x00\x00\x01\x09', data)]
    return [data[a:b] for a, b in zip(starts, starts[1:] + [len(data)])]


class AAPhone:
    """gal's hook + the phone for the real aa-most-feeder: Annex-B stream over TCP, one ACK byte per frame back
    (8-frame window), IDR first and about every 60 s, never on request (AA 2026-11-24)."""
    n = 0

    def __init__(self, car, idr_every_s, env_add=None):
        sys.path.insert(0, AA_FEEDER_TEST)
        import h264synth
        self.hs = h264synth
        self.car = car
        self.plug_t = now()
        AAPhone.n += 1
        self.dir = os.path.join(car.dir, 'aa-%d' % AAPhone.n)
        os.makedirs(os.path.join(self.dir, 'input'))
        open(os.path.join(self.dir, 'feeder.conf'), 'w').close()
        self.ack_path = '/tmp/fc-ack-%d-%d.sock' % (os.getpid(), AAPhone.n)
        try:
            os.unlink(self.ack_path)
        except OSError:
            pass
        self.ack_srv = socket.socket(socket.AF_UNIX)
        self.ack_srv.bind(self.ack_path)
        self.ack_srv.listen(1)
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(1)
        self.idr_every = max(1, int(idr_every_s * PARAMS['aa_fps']))
        self.x264 = x264_aus()
        self.acks = self.other = 0
        self.frames = []
        self.conn = None
        self.stopping = threading.Event()
        self.silence_until = 0.0
        self.connected_at = None
        env = dict(car.env, FAKECAR_TAG='aa', FAKECAR_WHO='aa', PMCP_AA_MODE='most', PMCP_AA_OUTPUT='direct',
                   PMCP_AA_DMDT=os.path.join(HERE, 'dmdt'), PMCP_AA_ACK=self.ack_path, PMCP_AA_MOST_DEV=car.dev,
                   PMCP_AA_OWNER=os.path.join(car.src, 'isotx2'),
                   PMCP_AA_CP_READY=os.path.join(car.ram, 'carplay-bridge.ready'), PMCP_AA_RUNDIR=car.ram,
                   PMCP_AA_STATUS=os.path.join(car.ram, 'pmcp-aa-feeder.txt'),
                   PMCP_AA_RING=os.path.join(self.dir, 'aa-ring.bin'), PMCP_AA_BRIDGE='/nonexistent/bridge',
                   PMCP_AA_CONF=os.path.join(self.dir, 'feeder.conf'),
                   PMCP_AA_CONF_EXTRA=os.path.join(self.dir, 'extra.conf'),
                   PMCP_AA_FLUSH_DEV=os.path.join(self.dir, 'flush.dev'),
                   PMCP_AA_KF_REQ=os.path.join(self.dir, 'kf.request'), PMCP_AA_PRIO='0',
                   PMCP_AA_RECLAIM_S=os.environ.get('FAKECAR_AA_RECLAIM_S', str(int(time.clock_gettime(time.CLOCK_MONOTONIC)) + 180)))
        env.update(env_add or {})
        self.lag = []            # (t, frames sent - ACKs) per frame: > 0 for long = the feeder holds ACKs
        self.status_before = ''
        self.log = open(os.path.join(self.dir, 'feeder.stderr'), 'w')
        self.feeder = car.spawn([os.path.join(BUILD, 'feeder-sim'), 'tcp://127.0.0.1:%d' % self.srv.getsockname()[1]],
                                env=env, stdout=self.log)
        self.th = threading.Thread(target=self.run, daemon=True)
        self.th.start()

    def take(self, ack, timeout):
        rd, _, _ = select.select([ack], [], [], timeout)
        if not rd:
            return False
        try:
            b = ack.recv(4096)
        except (BlockingIOError, OSError):
            return False
        if not b:
            return False
        k = b.count(b'K') + b.count(b'C')
        self.other += k
        self.acks += len(b) - k
        return True

    def run(self):
        hs = self.hs
        self.srv.settimeout(0.2)
        while not self.stopping.is_set():
            try:
                self.conn, _ = self.srv.accept()
                break
            except socket.timeout:
                continue
        if self.conn is None:
            return
        self.connected_at = now()
        self.car.bb.rec('phone', 'aa hook connected')
        self.ack_srv.settimeout(10)
        try:
            ack, _ = self.ack_srv.accept()
        except socket.timeout:
            self.car.bb.rec('phone', 'aa no ACK connection')
            return
        ack.setblocking(False)
        rng = random.Random(1161)
        try:
            if not self.x264:
                self.conn.sendall(b''.join(hs.SC + x for x in (hs.sps(), hs.pps())))
            t0 = time.time()
            t_next = t0
            i = 0
            while not self.stopping.is_set():
                if time.time() < self.silence_until:      # the phone sends nothing (A215)
                    self.take(ack, 0.05)
                    t_next = time.time()
                    continue
                while time.time() < t_next:
                    self.take(ack, max(0.0, min(0.005, t_next - time.time())))
                w0 = time.time()
                while i - self.acks >= PARAMS['aa_window'] and not self.stopping.is_set():
                    self.take(ack, 0.05)
                    if time.time() - w0 > 20:              # the hook's hang rule
                        self.car.bb.rec('phone', 'aa hook hang: 20 s without an ACK')
                        self.stopping.set()
                if self.stopping.is_set():
                    break
                if self.x264:
                    au = self.x264[i % len(self.x264)]
                    idr = i % len(self.x264) == 0
                else:
                    idr = i % self.idr_every == 0
                    au, _ = hs.access_unit(idr, 20000 if idr else rng.randrange(1500, 4000), rng)
                t_sent = time.time()
                self.conn.sendall(au)
                self.frames.append(dict(idx=i, frame_no=i + 1, ring_seq=i + 2, idr=idr,
                                        avcc_sha256=self.avcc_hash(au), t_us=int((t_sent - t0) * 1e6)))
                i += 1
                self.lag.append((now(), i - self.acks))
                t_next = max(t_next + 1.0 / PARAMS['aa_fps'], t_sent - 0.5 / PARAMS['aa_fps'])
                self.take(ack, 0)
            end = time.time() + 1.0                            # collect the last ACKs
            while time.time() < end and self.take(ack, 0.05):
                pass
        except OSError:
            pass
        with open(os.path.join(self.dir, 'input', 'frames.jsonl'), 'w') as f:
            sps, pps = hs.sps(), hs.pps()
            if self.x264:
                nals = [n for n in re.split(rb'\x00\x00\x00\x01|\x00\x00\x01', self.x264[0]) if n]
                sps = next(n for n in nals if n[0] & 0x1f == 7)
                pps = next(n for n in nals if n[0] & 0x1f == 8)
            f.write(json.dumps(dict(event='avcC', ring_seq=1, sps=sps.hex(), pps=pps.hex())) + '\n')
            for x in self.frames:
                f.write(json.dumps(x) + '\n')

    def avcc_hash(self, au):
        body, b = b'', au
        for nal in re.split(rb'\x00\x00\x00\x01|\x00\x00\x01', b):
            if nal and (nal[0] & 0x1f) not in (7, 8, 9):
                body += struct.pack('>I', len(nal)) + nal
        return hashlib.sha256(body).hexdigest()

    def silence(self, seconds):
        self.silence_until = time.time() + seconds

    def status(self):
        try:
            return open(os.path.join(self.car.ram, 'pmcp-aa-feeder.txt')).read()
        except OSError:
            return ''

    def stop(self, mode):
        if self.stopping.is_set() and mode == 'unplug' and self.feeder.poll() is not None:
            return
        self.status_before = self.status() or self.status_before
        self.stopping.set()
        if mode == 'kill' and self.feeder.poll() is None:
            self.feeder.send_signal(signal.SIGKILL)
        self.th.join(5)
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        try:
            self.feeder.wait(10)
        except subprocess.TimeoutExpired:
            self.car.bb.rec('phone', 'aa feeder did not exit after unplug')
            self.feeder.kill()
        for s in (self.srv, self.ack_srv):
            s.close()
        try:
            os.unlink(self.ack_path)
        except OSError:
            pass

    def handle_aus(self, hid):
        """Video AUs of one channel handle: (leading non-PUSI packets, [(discontinuity, [frame_no...] or None)])."""
        by_hash = {}
        for f in self.frames:
            by_hash.setdefault(f['avcc_sha256'], []).append(f['frame_no'])
        data = open(os.path.join(self.car.dir, 'chan-%d-aa.ts' % hid), 'rb').read()
        aus, cur, lead = [], None, 0
        for i in range(0, len(data) - 187, 188):
            p = data[i:i + 188]
            if ((p[1] & 0x1f) << 8 | p[2]) != 0x11:
                continue
            afc, off, disc = (p[3] >> 4) & 3, 4, False
            if afc & 2:
                disc, off = p[4] > 0 and bool(p[5] & 0x80), 5 + p[4]
            pay = p[off:] if afc & 1 else b''
            if p[1] & 0x40:
                if cur is not None:
                    aus.append(cur)
                cur = [disc, bytearray(pay[9 + pay[8]:])]
            elif cur is None:
                lead += 1
            else:
                cur[1] += pay
        if cur is not None:
            aus.append(cur)
        return lead, [(d, by_hash.get(self.avcc_hash(bytes(b)))) for d, b in aus]

    def decode(self):
        """AA I6: ffmpeg decodes the AA TS with zero errors; returns (rc, errors, pictures)."""
        self.analyse()   # writes mlb.ts (all AA handles of this phone)
        ts = os.path.join(self.dir, 'mlb.ts')
        r = subprocess.run(['ffmpeg', '-v', 'error', '-err_detect', 'crccheck+bitstream+buffer+explode', '-f', 'mpegts',
                            '-i', ts, '-map', '0:v', '-f', 'null', '-'], capture_output=True, text=True)
        # count with ffprobe: the framemd5/null muxers drop pictures whose timestamps crowd (after a slow drain)
        c = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v', '-show_entries',
                            'stream=nb_read_frames', '-of', 'csv=p=0', ts], capture_output=True, text=True)
        try:
            pics = int(c.stdout.split()[0])
        except (IndexError, ValueError):
            pics = -1
        # the null muxer maps PTS 0.3 ms apart (a phone burst) to one 1/30 s tick and says so: not a decoder error
        err = '\n'.join(l for l in r.stderr.splitlines() if 'non monotonically increasing dts to muxer' not in l
                        and 'Last message repeated' not in l)
        return r.returncode, err.strip(), pics

    def analyse(self):
        """aa/most/test/ts_analyse.py on every AA byte the channel accepted (all AA handles, in order)."""
        d = self.dir
        with open(os.path.join(d, 'mlb.ts'), 'wb') as out:
            for h in sorted(self.car.chan.handles.values(), key=lambda h: h.hid):
                p = os.path.join(self.car.dir, 'chan-%d-aa.ts' % h.hid)
                if h.tag == 'aa' and h.t_open >= self.plug_t and os.path.exists(p):
                    out.write(open(p, 'rb').read())
        r = subprocess.run([sys.executable, '-I', os.path.join(AA_MOST_TEST, 'ts_analyse.py'), d, '--log',
                            os.path.join(d, 'none.log')], capture_output=True, text=True)
        try:
            norm = json.load(open(os.path.join(d, 'norm.json')))
        except (OSError, ValueError):
            norm = None
        return r.returncode, (r.stdout + r.stderr)[-800:], norm


class Car:
    def __init__(self, name):
        self.name = name
        self.dir = os.path.join(BUILD, 'runs', name)
        shutil.rmtree(self.dir, ignore_errors=True)
        self.ram = os.path.join(self.dir, 'ramdisk')
        self.app = os.path.join(self.dir, 'app')
        self.src = os.path.join(self.ram, 'most-src')
        for d in (self.src, os.path.join(self.app, 'stock_first'), os.path.join(self.dir, 'dev', 'mlb')):
            os.makedirs(d)
        self.dev = os.path.join(self.dir, 'dev', 'mlb', 'isoTX2')
        open(self.dev, 'w').close()
        shutil.copy(os.path.join(BUILD, 'bridge-sim'), os.path.join(self.app, 'altscreen-most-bridge'))
        self.sock_path = '/tmp/fakecar-%d-%s.sock' % (os.getpid(), name[:20])   # sun_path is short
        self.bb = BlackBox()
        self.chan = Channel(self.bb)
        self.view = 'vw'              # what the cluster shows: VW map or the CP/AA stream (dmdt)
        self.view_t = 0.0
        self.vw_mode = 'polite'       # polite | steal_at
        self.vw_steal_at = None
        self.stop_ev = threading.Event()
        self.procs = []
        self.sup = None
        self.prod = None
        self.dio = None
        self.aa_guard = None
        self.aa_handle = None
        self.screen = []              # (t, who) every 50 ms
        self.marks = {}
        self.chan.capdir = self.dir
        self.aa = None
        self.wl = None
        self.wl_gen = 0
        self.env = dict(os.environ, FAKECAR_SOCK=self.sock_path, FAKECAR_DIR=self.dir, FAKECAR_WHO='cp',
                        FAKECAR_DMDT_CALL_S='%.3f' % (PARAMS['dmdt_call_ms'] / 1000.0),
                        PMCP_SUP_RAMDISK=self.ram, PMCP_SUP_APP=self.app, PMCP_MOST_SRC_DIR=self.src,
                        PMCP_SUP_DMDT=os.path.join(HERE, 'dmdt'), PMCP_SUP_LN=os.path.join(HERE, 'ln'),
                        PMCP_SUP_LINK=os.path.join(self.dir, 'dev', 'pmcp-isoTX2'), PMCP_SUP_DEV=self.dev,
                        PMCP_SUP_FLUSH=os.path.join(self.dir, 'dev', 'flush'),
                        PMCP_MOST_LOG=os.path.join(self.ram, 'pmcp-most', 'bridge.log'),
                        PMCP_AA_RUNDIR=self.ram,
                        HOST_RING_PATH=os.path.join(self.ram, 'carplay-alt-ring.bin'),
                        HOST_IDR_PATH=os.path.join(self.ram, 'carplay-alt-force-idr.request'),
                        HOST_CACHE_LOCK=os.path.join(self.dir, 'cache.lock'),
                        HOST_INTRO_ONCE_PATH=os.path.join(self.dir, 'intro-played'),
                        HOST_DMDT_PATH=os.path.join(HERE, 'dmdt'),
                        HOST_RECLAIM_WINDOW_US=os.environ.get('FAKECAR_RECLAIM_US', str(180 * 1000000)))
        for k in ('PMCP_SUP_TIME_DIV', 'CARPLAY_CLUSTER_INTRO', 'FAKECAR_TAG') + tuple(
                k for k in os.environ if k.startswith(('PMCP_AA_', 'HOST_MLB_'))):
            self.env.pop(k, None)

    # ------------------------------------------------------------------ car threads
    def serve(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            os.unlink(self.sock_path)
        except OSError:
            pass
        srv.bind(self.sock_path)
        srv.listen(16)
        srv.settimeout(0.1)
        while not self.stop_ev.is_set():
            try:
                c, _ = srv.accept()
            except socket.timeout:
                continue
            threading.Thread(target=self.client, args=(c,), daemon=True).start()
        srv.close()
        os.unlink(self.sock_path)

    @staticmethod
    def recv_all(c, n):
        b = b''
        while len(b) < n:
            x = c.recv(n - len(b))
            if not x:
                raise EOFError
            b += x
        return b

    def client(self, c):
        h = None
        try:
            while True:
                op, a, b, n = struct.unpack('<B3xiiI', self.recv_all(c, 16))
                payload = self.recv_all(c, n) if n else b''
                if op == ord('O'):
                    tag, _, path = payload.partition(b'\0')
                    h = self.chan.open(tag.decode(), b, path.decode(errors='replace'))
                    reply = (-1, EBUSY, 0) if h is None else (h.hid, 0, 0)
                elif op == ord('D'):
                    st, val = self.chan.devctl(h, a & 0xffffffff, payload)
                    reply = (st, 0, val)
                elif op == ord('W'):
                    r, e = self.chan.write(h, payload)
                    reply = (r, e, 0)
                else:
                    reply = (-1, EBADF, 0)
                c.sendall(struct.pack('<iiI', *reply))
                if h is None and op == ord('O'):
                    break
        except (EOFError, OSError):
            pass
        if h is not None:
            self.chan.close(h, 'close')
        c.close()

    def dmdt_watch(self):
        path = os.path.join(self.dir, 'dmdt.req')
        pos = 0
        while not self.stop_ev.is_set():
            time.sleep(0.01)
            if not os.path.exists(path):
                continue
            with open(path) as f:
                f.seek(pos)
                data = f.read()
                pos = f.tell()
            for line in data.splitlines():
                parts = line.split()
                args = ' '.join(parts[2:])
                self.bb.rec('dmdt', '%s by=%s' % (args, parts[1] if len(parts) > 1 else '?'))
                threading.Timer(PARAMS['dmdt_ms'] / 1000.0, self.dmdt_apply, (args,)).start()

    def dmdt_apply(self, args):
        if args in ('dc 72', 'sc 4 72'):
            if self.view != 'cp':
                self.view, self.view_t = 'cp', now()
                self.bb.rec('view', 'cp (%s)' % args)
        elif args.startswith('dc 70') or args == 'sc 4 70':
            if self.view != 'vw':
                self.view, self.view_t = 'vw', now()
                self.bb.rec('view', 'vw (%s)' % args)

    def vw_encoder(self):
        """The factory encoder: knocks 20/s in the VW view, takes a free channel, drops it after dc 72."""
        holding = False
        tries = 0
        probes = 0
        started = False
        while not self.stop_ev.is_set():
            time.sleep(PARAMS['vw_knock_ms'] / 1000.0)
            t = now()
            if not started:
                if t - self.boot_t < PARAMS['vw_start_s']:
                    continue
                started = True
                if isinstance(self.chan.holder, Handle):   # cold start: the encoder comes up while we hold isoTX2
                    self.vw_steal_at = t
            if self.vw_steal_at is not None and t >= self.vw_steal_at:
                self.vw_steal_at = None
                old = self.chan.vw_steal()
                holding = True
                # the HMI asked for the VW view (that is why the encoder came back): it holds isoTX2 until dc 72
                self.view, self.view_t = 'vw', t
                self.bb.rec('view', 'vw (encoder steal)')
                self.bb.rec('vw', 'steal from %s' % (old.tag if isinstance(old, Handle) else old))
                continue
            if holding:
                if self.view == 'cp' and t >= self.view_t + PARAMS['vw_release_ms'] / 1000.0:
                    if self.chan.vw_drop():
                        self.bb.rec('vw', 'release (tries=%d)' % tries)
                    holding = False
                elif self.chan.holder != 'vw':
                    holding = False
                continue
            if PARAMS['vw_knock_in_cp'] and self.view == 'cp':
                probes += 1   # io_open 0x8880/0x0 + io_close handle=-1: a probe, never a take (we got isoTX2 anyway)
                continue
            if self.view == 'vw' and t - self.view_t >= PARAMS['vw_return_ms'] / 1000.0:
                tries += 1
                if self.chan.vw_try():
                    holding = True
                    self.bb.rec('vw', 'open ok (tries=%d)' % tries)

    def screen_watch(self):
        last = None
        while not self.stop_ev.is_set():
            time.sleep(0.05)
            t = now()
            hd = self.chan.holder
            if hd == 'vw':
                who = 'vw'
            elif isinstance(hd, Handle) and hd.idr_at is not None and hd.last_picture and \
                    t - hd.last_picture < PARAMS['screen_hold_ms'] / 1000.0:
                who = hd.tag
            else:
                who = 'blank'
            self.screen.append((t, who))
            if who != last:
                self.bb.rec('screen', who)
                last = who

    # ------------------------------------------------------------------ actors
    def spawn(self, argv, **kw):
        p = subprocess.Popen(argv, env=kw.pop('env', self.env), stdout=kw.pop('stdout', subprocess.DEVNULL),
                             stderr=subprocess.STDOUT, **kw)
        self.procs.append(p)
        return p

    def boot(self):
        self.boot_t = now()
        for fn in (self.serve, self.dmdt_watch, self.vw_encoder, self.screen_watch, self.proc_watch):
            threading.Thread(target=fn, daemon=True).start()
        time.sleep(0.1)
        self.sup_log = open(os.path.join(self.dir, 'sup.stderr'), 'w')
        self.sup = self.spawn([os.path.join(BUILD, 'pmcp-most-sup')], stdout=self.sup_log)
        self.bb.rec('car', 'boot supervisor pid=%d' % self.sup.pid)

    def bridge_pids(self):
        """Bridges of this car: argv[0] is exactly our app path (pgrep -f would also match a concurrent pgrep)."""
        exe = os.path.join(self.app, 'altscreen-most-bridge')
        out = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True).stdout
        return [int(l.split(None, 1)[0]) for l in out.splitlines()
                if len(l.split(None, 1)) == 2 and l.split(None, 1)[1].split(' ')[0] == exe]

    def proc_watch(self):
        """Bridge processes as the car's pidin would show them (start/exit)."""
        seen = set()
        while not self.stop_ev.is_set():
            time.sleep(0.05)
            pids = set(self.bridge_pids())
            for p in pids - seen:
                ps = subprocess.run(['ps', '-o', 'ppid=,command=', '-p', str(p)], capture_output=True, text=True)
                self.bb.rec('proc', 'bridge start pid=%d %s' % (p, ps.stdout.strip()[:160]))
            for p in seen - pids:
                self.bb.rec('proc', 'bridge exit pid=%d' % p)
            seen = pids

    def cable_plug(self):
        self.dio = self.spawn(['sleep', '3600'])
        out = os.path.join(self.dir, 'producer-%d' % len(self.marks.get('plug', [])))
        os.makedirs(out)
        with open(os.path.join(self.ram, 'carplay-dio-manager.pid'), 'w') as f:
            f.write('%d\n' % self.dio.pid)
        self.prod = self.spawn([os.path.join(BUILD, 'producer'), '--ring', self.env['HOST_RING_PATH'],
                                '--idr', self.env['HOST_IDR_PATH'], '--out', out,
                                '--frames', '100000', '--fps', '30', '--gop', '60', '--repeat-avcc', '1',
                                '--attach-ms', '0'])   # A: core.so waits for the bridge's ring as long as the session lives
        open(os.path.join(self.ram, 'carplay-altstream.ready'), 'w').close()
        self.marks.setdefault('plug', []).append(now())
        self.bb.rec('phone', 'cp cable plug dio=%d producer=%d' % (self.dio.pid, self.prod.pid))

    def cable_unplug(self):
        try:
            os.unlink(os.path.join(self.ram, 'carplay-altstream.ready'))
        except OSError:
            pass
        for p in (self.prod, self.dio):
            if p and p.poll() is None:
                p.kill()
                p.wait()
        self.marks.setdefault('unplug', []).append(now())
        self.bb.rec('phone', 'cp cable unplug')

    # ---- Android Auto: the real aa-most-feeder (host build with sim_mlb.c), the car plays gal's hook + the phone
    def aa_plug(self, idr_every_s=None, env_add=None):
        self.aa = AAPhone(self, idr_every_s or PARAMS['aa_idr_every_s'], env_add)
        self.marks.setdefault('aa_plug', []).append(now())
        self.bb.rec('phone', 'aa plug feeder=%d' % self.aa.feeder.pid)

    def aa_unplug(self):
        self.aa.stop('unplug')
        self.marks.setdefault('aa_unplug', []).append(now())
        self.bb.rec('phone', 'aa unplug')

    def aa_kill(self):
        self.aa.stop('kill')
        self.marks.setdefault('aa_kill', []).append(now())
        self.bb.rec('phone', 'aa feeder SIGKILL')

    # ---- CarPlay over Wi-Fi: the car plays the WL receiver's contract files (WL 2026-11-24), producer = core.so
    def wl_start(self, fps=30, gop=5, idr_on_request=1, gen=1):
        out = os.path.join(self.dir, 'producer-wl-%d' % gen)
        os.makedirs(out)
        self.wl = self.spawn([os.path.join(BUILD, 'producer'), '--ring', self.env['HOST_RING_PATH'],
                              '--idr', self.env['HOST_IDR_PATH'], '--out', out, '--frames', '100000',
                              '--fps', str(fps), '--gop', str(gop), '--repeat-avcc', '1',
                              '--idr-on-request', str(idr_on_request), '--attach-ms', '0'])
        self.wl_gen = gen
        ms = int(time.monotonic() * 1000)
        put(os.path.join(self.src, 'owner'), 'v=1 src=wireless pid=%d gen=%d since_ms=%d kind=in\n' % (self.wl.pid, gen, ms))
        put(os.path.join(self.src, 'wireless.session'),
            'v=1 state=start gen=%d pid=%d ts_ms=%d reason=connect\n' % (gen, self.wl.pid, ms))
        self.marks.setdefault('wl_start', []).append(now())
        self.bb.rec('phone', 'wl start gen=%d fps=%d gop=%d producer=%d' % (gen, fps, gop, self.wl.pid))

    def wl_stop(self, reason):
        """The WL receiver ends the session (reasons as airplayd writes them, WL 2026-11-24):
        'idle'  Wi-Fi gone: airplayd (the producer) stays alive, only the frames stop; stop after wl_idle_ms;
        'done'  TEARDOWN of stream 111; any other session reason the same way (phone-gone, SIGTERM, guard).
        The producer is frozen (SIGSTOP), never killed: in the car its pid stays alive."""
        pid = self.wl.pid
        if self.wl.poll() is None:
            self.wl.send_signal(signal.SIGSTOP)
        self.bb.rec('phone', 'wl frames stop reason=%s (producer alive)' % reason)
        if reason == 'idle':
            time.sleep(PARAMS['wl_idle_ms'] / 1000.0)
        elif reason == 'phone-gone':
            time.sleep(PARAMS['wl_phone_gone_ms'] / 1000.0)
        ms = int(time.monotonic() * 1000)
        put(os.path.join(self.src, 'wireless.session'),
            'v=1 state=stop gen=%d pid=%d ts_ms=%d reason=%s\n' % (self.wl_gen, pid, ms, reason))
        try:
            if ('pid=%d ' % pid) in open(os.path.join(self.src, 'owner')).read():
                os.unlink(os.path.join(self.src, 'owner'))
        except OSError:
            pass
        self.marks.setdefault('wl_stop', []).append(now())
        self.bb.rec('phone', 'wl session stop reason=%s' % reason)

    def wl_replaced(self, gap=1.5):
        """A new SETUP of stream 111 (WL: 'replaced'): detach only, owner stays, the frames come back with the same gen;
        the first frame of the new connection is config + IDR (the WL side asks for it when a P frame comes first)."""
        self.wl.send_signal(signal.SIGSTOP)
        self.bb.rec('phone', 'wl stream 111 replaced: detach, owner kept (gen=%d)' % self.wl_gen)
        time.sleep(gap)
        open(self.env['HOST_IDR_PATH'], 'w').close()
        self.wl.send_signal(signal.SIGCONT)
        self.marks.setdefault('wl_resume', []).append(now())
        self.bb.rec('phone', 'wl stream 111 back (config + IDR)')

    def wl_gen_change(self):
        """Ring generation / picture size change on the WL side: a new owner gen of the same producer, no stop."""
        self.wl_gen += 1
        ms = int(time.monotonic() * 1000)
        put(os.path.join(self.src, 'owner'), 'v=1 src=wireless pid=%d gen=%d since_ms=%d kind=in\n' % (
            self.wl.pid, self.wl_gen, ms))
        put(os.path.join(self.src, 'wireless.session'),
            'v=1 state=start gen=%d pid=%d ts_ms=%d reason=connect\n' % (self.wl_gen, self.wl.pid, ms))
        self.marks.setdefault('wl_gen', []).append(now())
        self.bb.rec('phone', 'wl owner gen -> %d (same producer)' % self.wl_gen)

    def wl_preempt_by_cable(self):
        """The cable comes while Wi-Fi runs: the dio_manager wrapper writes owner src=wired with gen+1 (the cable
        wins), the WL library writes stop reason=preempted and stops writing; core.so of the cable session takes over."""
        old_pid = self.wl.pid
        self.wl.send_signal(signal.SIGSTOP)
        self.cable_plug()
        ms = int(time.monotonic() * 1000)
        put(os.path.join(self.src, 'owner'), 'v=1 src=wired pid=%d gen=%d since_ms=%d kind=in\n' % (
            self.dio.pid, self.wl_gen + 1, ms))
        put(os.path.join(self.src, 'wireless.session'),
            'v=1 state=stop gen=%d pid=%d ts_ms=%d reason=preempted\n' % (self.wl_gen, old_pid, ms))
        self.bb.rec('phone', 'wl preempted by the cable (owner src=wired gen=%d)' % (self.wl_gen + 1))

    def wl_crash(self):
        """airplayd dies: dead owner pid, no stop line (WL: the guard restarts it with a new pid and gen+1)."""
        self.wl.kill()
        self.wl.wait()
        self.marks.setdefault('wl_crash', []).append(now())
        self.bb.rec('phone', 'wl airplayd killed (no session stop)')

    # ---- the unit under load: reverse camera, CPU 98-100 %, devp-iso-mmx drains slowly (A203/A208)
    def reverse(self, seconds, rate=0.03):
        self.chan.rate = rate
        self.bb.rec('car', 'reverse on drain=%.2f' % rate)
        self.marks.setdefault('reverse', []).append((now(), now() + seconds))
        time.sleep(seconds)
        self.chan.rate = 1.0
        self.bb.rec('car', 'reverse off')

    def vw_steal_in(self, seconds):
        self.vw_steal_at = now() + seconds
        self.marks.setdefault('steal', []).append(self.vw_steal_at)

    def shutdown(self):
        self.bb.rec('car', 'shutdown')
        if self.aa:
            self.aa.stop('unplug')
        if self.sup and self.sup.poll() is None:
            self.sup.send_signal(signal.SIGTERM)
            try:
                self.sup.wait(10)
            except subprocess.TimeoutExpired:
                self.sup.kill()
                self.bb.rec('car', 'supervisor did not stop on SIGTERM')
        time.sleep(1.0)
        self.stop_ev.set()
        for p in self.procs:
            if p.poll() is None:
                p.kill()
        left = [str(p) for p in self.bridge_pids()]
        if left:
            ps = subprocess.run(['ps', '-o', 'pid=,ppid=,command=', '-p', ','.join(left)], capture_output=True,
                                text=True).stdout
            for l in ps.splitlines():
                self.bb.rec('car', 'leftover %s' % l.strip())
        for p in left:
            try:
                os.kill(int(p), signal.SIGKILL)
            except ProcessLookupError:   # exited between pgrep and kill: not a leftover
                left = [x for x in left if x != p]
        self.leftover = left
        time.sleep(0.2)
        self.bb.dump(os.path.join(self.dir, 'blackbox.txt'))

    # ------------------------------------------------------------------ verdict helpers
    def who_at(self, t):
        for ts, who in self.screen:
            if ts >= t:
                return who
        return None

    def first_after(self, t, who, within):
        for ts, w in self.screen:
            if t <= ts <= t + within and w == who:
                return ts - t
        return None


# ---------------------------------------------------------------------- checks shared by every scenario
results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('ok     ' if cond else 'FAILED ') + name + (f'  [{detail}]' if detail and not cond else ''), flush=True)


def dm(car, pattern, after=0.0, before=1e9):
    return [r for r in car.bb.find('dmdt', pattern, after) if r[0] <= before]


def common_invariants(car):
    n = car.name
    rows = car.bb.rows
    bad = [h for h in car.chan.handles.values() if h.bad_blocks]
    check(f'{n}: every block written is whole TS packets (188 B, sync 0x47)', not bad,
          ', '.join('id=%d bad=%d' % (h.hid, h.bad_blocks) for h in bad))
    # isoTX2 closed before any restore; nobody fights a live holder of the other kind (AA I2, both directions)
    opened = {}
    restore_open, fights = [], []
    for t, k, x in rows:
        if k == 'chan':
            m = re.match(r'open tag=(\w+) pid=\d+ (id=(\d+)|busy holder=(\w+))', x)
            if m:
                tag = m.group(1)
                if any(v != tag for v in opened.values()):
                    fights.append('%.2f %s open while %s holds' % (t, tag, set(opened.values())))
                if m.group(3):
                    opened[m.group(3)] = tag
            m = re.match(r'close tag=\w+ id=(\d+)', x)
            if m:
                opened.pop(m.group(1), None)
        if k == 'dmdt':
            who = x.split(' by=')[-1]
            if x.startswith('dc 70') and opened:
                restore_open.append('%.2f %s' % (t, x))
            if x.startswith('dc 72') and any(v != who for v in opened.values()):
                fights.append('%.2f dmdt %s while %s holds' % (t, x, set(opened.values())))
    check(f'{n}: dmdt restore only after isoTX2 was closed', not restore_open, ' '.join(restore_open))
    check(f'{n}: nobody fights a live holder (no open, no dc 72 against the other)', not fights, '; '.join(fights[:4]))
    big = []
    logdir = os.path.join(car.ram, 'pmcp-most')
    if os.path.isdir(logdir):
        for f in os.listdir(logdir):
            s = os.path.getsize(os.path.join(logdir, f))
            if s > 64 * 1024:
                big.append('%s=%d' % (f, s))
    check(f'{n}: logs in /ramdisk within 64 KB each', not big, ' '.join(big))
    check(f'{n}: no bridge left after the supervisor stopped', not car.leftover, ' '.join(car.leftover))
    check(f'{n}: supervisor stopped on SIGTERM', not car.bb.find('car', 'did not stop'))
    check(f'{n}: after shutdown the cluster is back on the VW map', car.view == 'vw' and car.screen and
          car.screen[-1][1] == 'vw', 'view=%s screen=%s' % (car.view, car.screen[-1][1] if car.screen else None))


def aa_invariants(car, phone, sessions_with_most=1, ts=True, decode=True, killed=False):
    n = car.name
    gb = dm(car, r'^dc 70 33 by=aa', after=phone.plug_t)
    check(f'{n}: AA gives MOST back exactly once per session ({sessions_with_most})', len(gb) == sessions_with_most,
          len(gb))
    check(f'{n}: AA never asks the phone for an IDR (no K/C on the ACK socket)', phone.other == 0, phone.other)
    if killed:   # frames in flight when the feeder died are never ACKed: at most the phone's window
        check(f'{n}: every frame ACKed except those in flight at the SIGKILL (<= {PARAMS["aa_window"]})',
              0 <= len(phone.frames) - phone.acks <= PARAMS['aa_window'], '%d/%d' % (phone.acks, len(phone.frames)))
    else:
        check(f'{n}: one ACK per frame sent ({len(phone.frames)})', phone.acks == len(phone.frames),
              '%d/%d' % (phone.acks, len(phone.frames)))
    check(f'{n}: AA guardian marker and owner file removed after the restore',
          not os.path.exists(os.path.join(car.ram, 'pmcp-aa-guard.pid')) and
          not os.path.exists(os.path.join(car.src, 'isotx2')))
    if decode and sessions_with_most and phone.x264 and shutil.which('ffmpeg'):
        rc, err, pics = phone.decode()
        ka = max(0, snum(phone.status_before or phone.status(), 'keepalive:', 'wyslane'))
        check(f'{n}: AA TS decodes with ffmpeg, zero errors (AA I6)', rc == 0 and not err, err[:200])
        check(f'{n}: pictures decoded = phone frames + keep-alive ({len(phone.frames)} + {ka})',
              pics == len(phone.frames) + ka, pics)
    if ts and sessions_with_most:
        rc, out, norm = phone.analyse()
        miss = norm and norm['missing_frame_nos']
        check(f'{n}: AA TS passes ts_analyse', rc == 0, out[-300:])
        check(f'{n}: every AA frame in the TS once, in order', norm and not miss and
              norm['output_aus'] >= len(phone.frames), 'out=%s sent=%d missing=%s' % (
                  norm and norm['output_aus'], len(phone.frames), miss and miss[:8]))


def aa_reclaim_ts(car, phone, steal_t):
    """AA I3 as corrected by AA (2026-11-24), per channel handle, nothing glued: handle 1 = frames 1..k (the last may
    be cut); handle 2 starts (after < 1 AU of continuation packets) with a discontinuity-flagged AU, holds every frame
    from k+1 in order plus exactly one replayed IDR equal to the last IDR before the steal. Order logged."""
    n = car.name
    hs = sorted(h.hid for h in car.chan.handles.values() if h.tag == 'aa' and h.t_open >= phone.plug_t)
    if len(hs) != 2:
        check(f'{n}: two AA channel handles (before and after the reclaim)', False, hs)
        return
    lead1, a1 = phone.handle_aus(hs[0])
    lead2, a2 = phone.handle_aus(hs[1])
    f1 = [x[0] for _, x in a1 if x]
    cut = 1 if a1 and a1[-1][1] is None else 0
    ok1 = f1 == list(range(1, len(f1) + 1)) and all(x for _, x in a1[:len(a1) - cut])
    check(f'{n}: handle 1 = frames 1..{len(f1)} whole and in order (cut at the steal: {cut})', ok1,
          [x for _, x in a1][:6])
    k = len(f1)
    idrs = [f['frame_no'] for f in phone.frames if f['idr'] and f['frame_no'] <= k + cut]
    last_idr = idrs[-1] if idrs else None
    seq = [(d, x) for d, x in a2]
    check(f'{n}: handle 2 starts on a PES start with the discontinuity flag ({lead2} continuation packets first)',
          seq and seq[0][0] and lead2 * 184 < 60000, (lead2, seq[:1]))
    replay = [i for i, (_, x) in enumerate(seq) if x and last_idr in x and x[0] <= k + cut]
    rest = [x[0] for _, x in seq if x and x[0] > k]
    first = k + 1 + cut
    expect = list(range(rest[0], rest[0] + len(rest))) if rest else []
    check(f'{n}: handle 2 = every frame from {first} on, in order, plus exactly one replayed IDR (frame {last_idr})',
          len(replay) == 1 and rest == expect and rest and rest[0] in (k + 1, k + 2) and
          all(x for _, x in seq), 'replay at %s, rest %s..%s, unmatched %d' % (
              replay, rest[:2], rest[-1:], sum(1 for _, x in seq if not x)))
    order = ' '.join(('D:' if d else '') + ('?' if not x else ('IDR%d' % x[0] if x[0] == last_idr else str(x[0])))
                     for d, x in seq[:6])
    car.bb.rec('aa', 'after reclaim: %s ...' % order)
    print('       aa-steal order after the reopen: %s ...' % order, flush=True)


def snum(text, prefix, key):
    """Number after key= on the status line starting with prefix (aa feeder status), -1 if absent."""
    for l in text.split('\n'):
        if l.startswith(prefix):
            m = re.search(r'(?:^|\s)' + re.escape(key) + r'[= ](-?\d+)', l)
            return int(m.group(1)) if m else -1
    return -1


def picture_after(car, t, tag, within):
    return car.first_after(t, tag, within)


# ---------------------------------------------------------------------- scenarios: CarPlay over the cable
def sc_session():
    """Plain cable session: plug, CP map on the AID, unplug, VW map back."""
    car = Car('session')
    car.boot()
    time.sleep(1.5)
    check('session: VW map on the AID before any phone', car.who_at(1.4) == 'vw')
    car.cable_plug()
    time.sleep(8)
    t = car.marks['plug'][0]
    d = car.first_after(t, 'cp', 6)
    check('session: CP map within 4 s of the plug', d is not None and d < 4, d)
    rel = dm(car, '', after=t)
    op = car.bb.find('chan', 'open tag=cp pid=\\d+ id=', after=t)
    check('session: takeover dmdt dc 72 + sc 4 72 (by cp) before the bridge opened isoTX2',
          [x for _, _, x in rel[:2]] == ['dc 72 by=cp', 'sc 4 72 by=cp'] and op and rel[1][0] < op[0][0],
          [x for _, _, x in rel[:4]])
    car.cable_unplug()
    time.sleep(5)
    d = car.first_after(car.marks['unplug'][0], 'vw', 5)
    check('session: VW map back within 4 s of the unplug', d is not None and d < 4, d)
    car.shutdown()
    common_invariants(car)


def sc_boot_steal():
    """Cold start: the encoder takes isoTX2 back from the bridge (A184/A201/A208): ENOMEM -> reclaim -> keyframe."""
    car = Car('boot-steal')
    car.boot()
    time.sleep(1)
    car.cable_plug()
    time.sleep(3)
    car.vw_steal_in(2)   # scaled down from ~15 s
    time.sleep(10)
    st = car.marks['steal'][0]
    check('boot-steal: the encoder took the channel', car.bb.find('vw', 'steal from cp'))
    rec = car.bb.find('screen', '^keyframe tag=cp', after=st)
    d = rec[0][0] - st if rec else None
    check('boot-steal: CP picture back with a keyframe within 3 s of the steal', d is not None and d < 3, d)
    check('boot-steal: reclaim dmdt (dc 72 by cp) after the steal', dm(car, '^dc 72 by=cp', after=st))
    blank = sum(1 for t, w in car.screen if st <= t <= st + 6 and w != 'cp') * 0.05
    check('boot-steal: picture gap after the steal under 2 s', blank < 2.0, '%.2f s' % blank)
    car.cable_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_replug():
    """Three quick unplug/plug cycles: one bridge per session, VW and CP alternate."""
    car = Car('replug')
    car.boot()
    time.sleep(1)
    for _ in range(3):
        car.cable_plug()
        time.sleep(4)
        car.cable_unplug()
        time.sleep(3)
    check('replug: CP map after every plug', all(car.first_after(t, 'cp', 4) is not None for t in car.marks['plug']))
    check('replug: VW map after every unplug',
          all(car.first_after(t, 'vw', 3) is not None for t in car.marks['unplug']))
    starts = car.bb.find('proc', 'bridge start')
    check('replug: one bridge per session (3)', len(starts) == 3, len(starts))
    car.shutdown()
    common_invariants(car)


def sc_cp_reverse():
    """Reverse gear during a CP session: the channel drains at 10 % for 5 s; the bridge must ride it out."""
    car = Car('cp-reverse')
    car.boot()
    time.sleep(1)
    car.cable_plug()
    time.sleep(4)
    t_on = now()
    car.reverse(5)
    t_off = now()
    time.sleep(4)
    check('cp-reverse: the bridge stays up through reverse', not car.bb.find('proc', 'bridge exit', after=t_on))
    check('cp-reverse: no reclaim and no giveback during reverse', not dm(car, '', after=t_on, before=t_off + 0.5),
          [x for _, _, x in dm(car, '', after=t_on, before=t_off + 0.5)])
    d = car.first_after(t_off, 'cp', 4)
    check('cp-reverse: CP picture on the AID within 2 s after reverse', d is not None and d < 2, d)
    car.cable_unplug()
    time.sleep(3)
    car.shutdown()
    common_invariants(car)


# ---------------------------------------------------------------------- scenarios: CarPlay over Wi-Fi (WL contract)
def sc_wl_session():
    """Wireless session, 30 fps, keyframe every 5 frames: CP map; Wi-Fi drops, idle stop, VW back."""
    car = Car('wl-session')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=5)
    time.sleep(7)
    d = car.first_after(car.marks['wl_start'][0], 'cp', 6)
    check('wl-session: CP map within 4 s of the session start', d is not None and d < 4, d)
    t_drop = now()
    car.wl_stop('idle')
    time.sleep(5)
    vw = car.first_after(t_drop, 'vw', 12)
    print('       wl-session: frozen CP map %.2f s after the Wi-Fi drop (idle)' % (vw or -1), flush=True)
    d = car.first_after(car.marks['wl_stop'][0], 'vw', 5)
    check('wl-session: VW map back within 4 s of the idle stop', d is not None and d < 4, d)
    car.shutdown()
    common_invariants(car)


def sc_wl_steal():
    """Wireless at 40 fps, IDR requests never answered (lost on 2.4 GHz), keyframe every 5 frames; the encoder
    steals the channel: the picture must come back from the periodic keyframes alone."""
    car = Car('wl-steal')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=40, gop=5, idr_on_request=-1)
    time.sleep(4)
    car.vw_steal_in(1)
    time.sleep(6)
    st = car.marks['steal'][0]
    rec = car.bb.find('screen', '^keyframe tag=cp', after=st)
    d = rec[0][0] - st if rec else None
    check('wl-steal: CP picture back within 3 s without any answered IDR request', d is not None and d < 3, d)
    car.wl_stop('done')
    time.sleep(4)
    d = car.first_after(car.marks['wl_stop'][0], 'vw', 4)
    check('wl-steal: VW map back within 3 s of the TEARDOWN (reason=done)', d is not None and d < 3, d)
    car.shutdown()
    common_invariants(car)


# ---------------------------------------------------------------------- scenarios: Android Auto (real feeder)
def sc_aa_session():
    car = Car('aa-session')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(8)
    d = car.first_after(car.marks['aa_plug'][0], 'aa', 6)
    check('aa-session: AA map within 4 s of the plug', d is not None and d < 4, d)
    car.aa_unplug()
    time.sleep(4)
    d = car.first_after(car.marks['aa_unplug'][0], 'vw', 4)
    check('aa-session: VW map back within 3 s of the unplug', d is not None and d < 3, d)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa)


def sc_aa_kill():
    """SIGKILL of the feeder mid-session: the guardian still gives MOST back, exactly once (AA I1)."""
    car = Car('aa-kill')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(6)
    car.aa_kill()
    time.sleep(4)
    d = car.first_after(car.marks['aa_kill'][0], 'vw', 4)
    check('aa-kill: VW map back within 3 s of the SIGKILL', d is not None and d < 3, d)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa, ts=False, decode=False, killed=True)


def sc_aa_holds():
    """AA holds isoTX2; CP cable plugs: CP waits (no dmdt, no open); after AA ends CP takes over."""
    car = Car('aa-holds')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(4)
    t = now()
    car.cable_plug()
    time.sleep(5)
    check('aa-holds: no dmdt from CP while AA holds the channel', not dm(car, 'by=cp', after=t),
          [x for _, _, x in dm(car, 'by=cp', after=t)])
    check('aa-holds: CP never got isoTX2', not car.bb.find('chan', 'open tag=cp pid=\\d+ id=', after=t))
    check('aa-holds: AA keeps the AID', all(w == 'aa' for ts, w in car.screen if t + 0.2 <= ts <= t + 5))
    phone = car.aa
    car.aa_unplug()
    time.sleep(6)
    d = car.first_after(car.marks['aa_unplug'][0], 'cp', 6)
    check('aa-holds: CP takes over within 5 s after AA ended (cable still plugged)', d is not None and d < 5, d)
    car.cable_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, phone)


def sc_cp_then_aa():
    """CP holds isoTX2; AA plugs: the feeder waits (up to 20 s) without touching MOST; when CP ends, AA takes it."""
    car = Car('cp-then-aa')
    car.boot()
    time.sleep(1)
    car.cable_plug()
    time.sleep(4)
    t = now()
    car.aa_plug()
    time.sleep(5)
    check('cp-then-aa: AA does not touch MOST while CP holds it', not dm(car, 'by=aa', after=t) and
          not car.bb.find('chan', 'open tag=aa', after=t), [x for _, _, x in car.bb.rows if _ == 'chan'][-3:])
    check('cp-then-aa: CP keeps the AID', all(w == 'cp' for ts, w in car.screen if t + 0.2 <= ts <= t + 5))
    car.cable_unplug()
    time.sleep(7)
    d = car.first_after(car.marks['unplug'][0], 'aa', 7)
    check('cp-then-aa: AA takes the AID within 6 s after CP ended', d is not None and d < 6, d)
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa)


def sc_aa_steal():
    """Cold start with AA: the encoder takes isoTX2 back; the feeder reclaims and keeps every frame (AA 3, I3, I8)."""
    car = Car('aa-steal')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(4)
    car.vw_steal_in(1)
    time.sleep(7)
    st = car.marks['steal'][0]
    rec = car.bb.find('screen', '^keyframe tag=aa', after=st)
    d = rec[0][0] - st if rec else None
    check('aa-steal: AA picture back with a keyframe within 3 s of the steal', d is not None and d < 3, d)
    check('aa-steal: reclaim dmdt (dc 72 by aa) after the steal', dm(car, '^dc 72 by=aa', after=st))
    aa_reclaim_ts(car, car.aa, st)
    st_text = car.aa.status()
    check('aa-steal: feeder status: one reclaim attempt, IDR replayed once',
          snum(st_text, 'ponowne przejecie MOST:', 'proby') == 1 and
          snum(st_text, 'ponowne przejecie MOST:', 'IDR_ponownie') == 1,
          [l for l in st_text.split('\n') if l.startswith('ponowne')])
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    # ts_analyse assumes one continuous capture (PSI cadence by packet number); AA's own reclaim test does not run it
    # either. The AU in flight at the steal is cut (the ENOMEM block is not accepted) - question to AA (docs/28).
    aa_invariants(car, car.aa, ts=False, decode=False)


def sc_aa_reverse():
    """Reverse gear during AA: drain at 10 % for 5 s; frames queue, ACKs held, nothing dropped, no giveback."""
    car = Car('aa-reverse')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(4)
    t_on = now()
    car.reverse(5)
    t_off = now()
    time.sleep(5)
    check('aa-reverse: no giveback and no reclaim during reverse', not dm(car, 'by=aa', after=t_on,
                                                                           before=t_off + 1),
          [x for _, _, x in dm(car, 'by=aa', after=t_on, before=t_off + 1)])
    d = car.first_after(t_off, 'aa', 4)
    check('aa-reverse: AA picture on the AID within 2 s after reverse', d is not None and d < 2, d)
    lag = max([x for t, x in car.aa.lag if t_on <= t <= t_off] or [0])
    held = snum(car.aa.status(), 'ACK wstrzymane:', 'razy')
    check('aa-reverse: the feeder really held ACKs (phone at its 8-frame window, status razy >= 1)',
          lag >= PARAMS['aa_window'] and held >= 1, 'max lag=%d razy=%d' % (lag, held))
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa)


def sc_aa_silence():
    """The phone goes silent for 8 s (A215): the map must stay, keep-alive only, no giveback."""
    car = Car('aa-silence')
    car.boot()
    time.sleep(1)
    car.aa_plug()
    time.sleep(4)
    t = now()
    car.aa.silence(8)
    time.sleep(10)
    check('aa-silence: AA map stays through 8 s of phone silence',
          all(w == 'aa' for ts, w in car.screen if t <= ts <= t + 9), sorted(set(w for ts, w in car.screen
                                                                                  if t <= ts <= t + 9)))
    check('aa-silence: no giveback during the silence', not dm(car, 'by=aa', after=t, before=t + 9))
    st_text = car.aa.status()
    ka = snum(st_text, 'keepalive:', 'wyslane')
    check('aa-silence: about 8 keep-alive pictures sent, no errors', 6 <= ka <= 10 and
          snum(st_text, 'keepalive:', 'bledy') == 0, [l for l in st_text.split('\n') if l.startswith('keepalive')])
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    # after keep-alive the phone frames carry shifted frame_num/POC (v17), so ts_analyse's byte match cannot hold:
    # the decode check (zero errors, phone + keep-alive pictures) is AA's own criterion (run_direct_test 17)
    aa_invariants(car, car.aa, ts=False)


def sc_wl_phone_gone():
    """The phone leaves the hotspot: frames stop, airplayd (alive) writes stop reason=phone-gone after ~3 s, before
    the 5 s idle (WL 2026-11-24). Measures how long the frozen CP map stays on the AID."""
    car = Car('wl-phone-gone')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=5)
    time.sleep(5)
    t_drop = now()
    car.wl_stop('phone-gone')
    time.sleep(4)
    d = car.first_after(car.marks['wl_stop'][0], 'vw', 4)
    check('wl-phone-gone: VW map back within 3 s of the phone-gone stop', d is not None and d < 3, d)
    vw = car.first_after(t_drop, 'vw', 10)
    check('wl-phone-gone: frozen CP map shorter than with idle (< 5 s from the drop)', vw is not None and vw < 5, vw)
    car.bb.rec('car', 'frozen CP map after the drop: %.2f s' % (vw or -1))
    print('       wl-phone-gone: frozen CP map %.2f s after the drop' % (vw or -1), flush=True)
    car.wl.kill()
    car.shutdown()
    common_invariants(car)


def sc_wl_replaced():
    """WL 'replaced': stream 111 reconnects with the same gen after 1.5 s: no giveback, no bridge restart, the
    picture comes back on the config + IDR within 1 s."""
    car = Car('wl-replaced')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=30)
    time.sleep(5)
    t = now()
    car.wl_replaced(1.5)
    time.sleep(4)
    check('wl-replaced: no giveback during the reconnect', not dm(car, '^dc 70', after=t))
    check('wl-replaced: one bridge for the whole session', len(car.bb.find('proc', 'bridge start')) == 1,
          len(car.bb.find('proc', 'bridge start')))
    r = car.marks['wl_resume'][0]
    k = [x for h in car.chan.handles.values() if h.tag == 'cp' for x in h.key_times if x >= r]
    check('wl-replaced: keyframe on the AID within 1 s after the stream came back', k and min(k) - r < 1.0,
          k and min(k) - r)
    car.wl_stop('done')
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_wl_gen():
    """Ring generation change under a live WL producer (WL: 'wait + IDR request, no stop'): the bridge dies (SIGKILL),
    the supervisor gives back and starts a new bridge, which re-inits the ring with a new generation. The producer
    stays attached (sequence from the header, docs/11); the CP picture must come back."""
    car = Car('wl-gen')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=30)
    time.sleep(4)
    pids = car.bridge_pids()
    for p in pids:
        os.kill(p, signal.SIGKILL)
    t = now()
    car.bb.rec('car', 'bridge SIGKILL %s' % pids)
    time.sleep(7)
    check('wl-gen: the supervisor started a new bridge', len(car.bb.find('proc', 'bridge start')) == 2,
          len(car.bb.find('proc', 'bridge start')))
    k = [x for h in car.chan.handles.values() if h.tag == 'cp' and h.t_open > t for x in h.key_times]
    check('wl-gen: CP picture (keyframe) from the new bridge within 5 s', k and min(k) - t < 5.0, k and min(k) - t)
    print('       wl-gen: picture back %.2f s after the bridge was killed' % ((min(k) - t) if k else -1), flush=True)
    car.wl_stop('done')
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_wl_preempted():
    """The cable comes during a Wi-Fi session (cable wins): no giveback, the same bridge goes on, the cable picture
    within 2 s; unplug -> VW."""
    car = Car('wl-preempted')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=5)
    time.sleep(4)
    t = now()
    car.wl_preempt_by_cable()
    time.sleep(5)
    check('wl-preempted: no giveback on the switch to the cable', not dm(car, '^dc 70', after=t))
    check('wl-preempted: one bridge across the switch', len(car.bb.find('proc', 'bridge start')) == 1,
          len(car.bb.find('proc', 'bridge start')))
    k = [x for h in car.chan.handles.values() if h.tag == 'cp' for x in h.key_times if x >= t]
    check('wl-preempted: cable picture (keyframe) on the AID within 2 s', k and min(k) - t < 2.0, k and min(k) - t)
    car.cable_unplug()
    time.sleep(5)
    d = car.first_after(car.marks['unplug'][0], 'vw', 5)
    check('wl-preempted: VW map back after the unplug', d is not None and d < 4, d)
    car.wl.kill()
    car.shutdown()
    common_invariants(car)


def sc_wl_crash():
    """airplayd dies mid-session (dead owner pid, no stop line), the guard restarts it with gen+1."""
    car = Car('wl-crash')
    car.boot()
    time.sleep(1)
    car.wl_start(fps=30, gop=5, gen=1)
    time.sleep(4)
    car.wl_crash()
    time.sleep(5)
    d = car.first_after(car.marks['wl_crash'][0], 'vw', 5)
    check('wl-crash: VW map back within 4 s after airplayd died', d is not None and d < 4, d)
    car.wl_start(fps=30, gop=5, gen=2)
    time.sleep(6)
    d = car.first_after(car.marks['wl_start'][1], 'cp', 6)
    check('wl-crash: CP map again within 4 s of the restarted session (gen 2)', d is not None and d < 4, d)
    car.wl_stop('done')
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_aa_silence_noka():
    """Control for aa-silence (AA request): keep-alive off (PMCP_AA_KEEPALIVE_MS=0) - the car must see the gap."""
    car = Car('aa-silence-noka')
    car.boot()
    time.sleep(1)
    car.aa_plug(env_add={'PMCP_AA_KEEPALIVE_MS': '0'})
    time.sleep(4)
    t = now()
    car.aa.silence(8)
    time.sleep(10)
    check('aa-silence-noka: without keep-alive the AID loses the AA picture during the silence (control)',
          any(w != 'aa' for ts, w in car.screen if t <= ts <= t + 9))
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa)


def sc_aa_steal_late():
    """The encoder steals after the reclaim window (PMCP_AA_RECLAIM_S=0): AA gives MOST back, no reclaim, the session
    goes on as analysis only (AA I8); exactly one giveback in the whole session."""
    car = Car('aa-steal-late')
    car.boot()
    time.sleep(1)
    car.aa_plug(env_add={'PMCP_AA_RECLAIM_S': '0'})
    time.sleep(4)
    car.vw_steal_in(1)
    time.sleep(6)
    st = car.marks['steal'][0]
    check('aa-steal-late: no reclaim (no dc 72 by aa) after the steal', not dm(car, '^dc 72 by=aa', after=st))
    check('aa-steal-late: MOST given back (dc 70 33 by aa) after the steal', dm(car, '^dc 70 33 by=aa', after=st))
    check('aa-steal-late: the AA session goes on (feeder alive, analysis only)', car.aa.feeder.poll() is None)
    d = car.first_after(st, 'vw', 3)
    check('aa-steal-late: VW map on the AID', d is not None)
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa, ts=False, decode=False)


SCENARIOS = {'session': sc_session, 'boot-steal': sc_boot_steal, 'replug': sc_replug, 'cp-reverse': sc_cp_reverse,
             'wl-session': sc_wl_session, 'wl-steal': sc_wl_steal, 'wl-crash': sc_wl_crash,
             'wl-phone-gone': sc_wl_phone_gone, 'wl-replaced': sc_wl_replaced, 'wl-gen': sc_wl_gen,
             'wl-preempted': sc_wl_preempted,
             'aa-session': sc_aa_session, 'aa-kill': sc_aa_kill, 'aa-holds': sc_aa_holds, 'cp-then-aa': sc_cp_then_aa,
             'aa-steal': sc_aa_steal, 'aa-steal-late': sc_aa_steal_late, 'aa-reverse': sc_aa_reverse,
             'aa-silence': sc_aa_silence, 'aa-silence-noka': sc_aa_silence_noka}


# ---------------------------------------------------------------------- chaos (stage 4)
CHAOS_DISTURB = ('vw_steal', 'reverse', 'starve', 'bridge_kill')


def chaos_gen(seed, steps):
    """A random but car-sensible sequence: [{'do', 'arg', 'wait', 'check'}]. The generator tracks the phones so every
    action is possible (unplug only what is plugged; the cable during Wi-Fi = the cable preempts it)."""
    rng = random.Random(seed)
    cable = wl = aa = False
    t = last_kill = last_steal = -1e9
    seq = []
    for _ in range(steps):
        opts = []
        opts += ['cable_unplug'] if cable else ['cable_plug']
        if wl:
            opts += ['wl_stop', 'wl_crash', 'wl_replaced']
        elif not cable:
            opts += ['wl_start']
        opts += ['aa_unplug', 'aa_kill'] if aa else ['aa_plug']
        opts += ['reverse', 'starve']
        if t - last_steal > 15:
            opts.append('vw_steal')
        if t - last_kill > 60:
            opts.append('bridge_kill')
        do = rng.choice(opts)
        arg = None
        if do == 'cable_plug':
            cable, wl = True, False
        elif do == 'cable_unplug':
            cable = False
        elif do == 'wl_start':
            wl, arg = True, rng.choice([5, 30])
        elif do == 'wl_stop':
            wl, arg = False, rng.choice(['done', 'idle', 'phone-gone'])
        elif do == 'wl_crash':
            wl = False
        elif do == 'aa_plug':
            aa = True
        elif do in ('aa_unplug', 'aa_kill'):
            aa = False
        elif do == 'reverse':
            arg = round(rng.uniform(2, 5), 1)
        elif do == 'starve':
            arg = round(rng.uniform(0.5, 2.5), 1)
        elif do == 'vw_steal':
            last_steal = t
        elif do == 'bridge_kill':
            last_kill = t
        check = rng.random() < 0.4
        wait = 9.0 if check else round(rng.uniform(0.3, 4.0), 1)
        seq.append(dict(do=do, arg=arg, wait=wait, check=check))
        t += wait + (arg if do in ('reverse', 'starve') else 0)
    seq.append(dict(do='end', arg=None, wait=0, check=False))
    return seq


def chaos_run(name, seq):
    """Plays seq on a fresh car; returns the failed check names. Liveness at every check point (after a calm
    wait): the AID shows AA if AA holds MOST, else CP if a CP phone is on (cable or Wi-Fi), else the VW map."""
    first = len(results)
    car = Car(name)
    car.boot()
    time.sleep(1.5)
    cable = wl = False
    aa = None                 # None | 'show' | 'waiting' | 'analysis'
    aa_until = 0.0
    phones = []
    log = []

    def cp_ended():
        nonlocal aa
        if aa == 'waiting' and now() < aa_until:
            aa = 'show'

    for i, st in enumerate(seq):
        do, arg = st['do'], st['arg']
        t = now()
        impossible = ((do == 'cable_plug' and cable) or (do == 'cable_unplug' and not cable) or
                      (do == 'wl_start' and (wl or cable)) or (do in ('wl_stop', 'wl_crash', 'wl_replaced') and not wl) or
                      (do == 'aa_plug' and aa is not None) or (do in ('aa_unplug', 'aa_kill') and aa is None))
        if impossible:   # a shrunk sequence may drop the step that made this one possible
            log.append('%7.2f %s skipped (not possible now)' % (t, do))
            continue
        log.append('%7.2f %s %s' % (t, do, '' if arg is None else arg))
        car.bb.rec('chaos', 'step %d %s %s' % (i, do, '' if arg is None else arg))
        if do == 'cable_plug':
            if wl:
                car.wl_preempt_by_cable()
                wl = False
            else:
                car.cable_plug()
            cable = True
        elif do == 'cable_unplug':
            car.cable_unplug()
            cable = False
            cp_ended()
        elif do == 'wl_start':
            if car.wl is not None and car.wl.poll() is None:
                car.wl.kill()
            car.wl_start(fps=30, gop=arg, gen=len(car.marks.get('wl_start', [])) + 1)
            wl = True
        elif do == 'wl_stop':
            car.wl_stop(arg)
            wl = False
            cp_ended()
        elif do == 'wl_crash':
            car.wl_crash()
            wl = False
            cp_ended()
        elif do == 'wl_replaced':
            car.wl_replaced(1.5)
        elif do == 'aa_plug':
            car.aa_plug()
            phones.append(car.aa)
            if cable or wl:
                aa, aa_until = 'waiting', now() + 20
            else:
                aa = 'show'
        elif do in ('aa_unplug', 'aa_kill'):
            car.aa_unplug() if do == 'aa_unplug' else car.aa_kill()
            aa = None
        elif do == 'reverse':
            car.reverse(arg)
        elif do == 'starve':
            pids = car.bridge_pids()
            for p in pids:
                os.kill(p, signal.SIGSTOP)
            time.sleep(arg)
            for p in pids:
                os.kill(p, signal.SIGCONT)
        elif do == 'vw_steal':
            car.vw_steal_in(0)
        elif do == 'bridge_kill':
            for p in car.bridge_pids():
                os.kill(p, signal.SIGKILL)
        elif do == 'end':
            if aa:
                car.aa_unplug()
            if cable:
                car.cable_unplug()
            if wl:
                car.wl_stop('done')
            aa, cable, wl = None, False, False
            time.sleep(6)
        time.sleep(st['wait'])
        if st['check']:
            if aa == 'waiting' and now() >= aa_until:
                aa = 'analysis'        # AA waited 20 s for CP and runs without the AID (AA rule)
            if aa == 'show':
                allowed = {'aa'}
            elif cable or wl:
                allowed = {'cp'}
            else:
                allowed = {'vw'}
            tail = [w for ts, w in car.screen if ts >= now() - 1.0]
            ok = tail and all(w in allowed for w in tail)
            check('%s: step %d (%s) AID shows %s' % (name, i, do, '/'.join(sorted(allowed))), ok,
                  'saw %s' % sorted(set(tail)))
    tail = [w for ts, w in car.screen if ts >= now() - 1.0]
    check('%s: VW map at the end' % name, tail and all(w == 'vw' for w in tail), sorted(set(tail)))
    if car.wl is not None and car.wl.poll() is None:
        car.wl.kill()
    car.shutdown()
    common_invariants(car)
    for ph in phones:
        check('%s: AA phone never asked for an IDR (K/C)' % name, ph.other == 0, ph.other)
    with open(os.path.join(car.dir, 'chaos.json'), 'w') as f:
        json.dump(dict(seq=seq, log=log), f, indent=1)
    return [n for n, c in results[first:] if not c]


def sc_chaos_quick():
    """Stage 4 in the suite: one seeded random drive (about 90 s); the long runs and the shrinking are chaos.py."""
    chaos_run('chaos-1161', chaos_gen(1161, 16))


SCENARIOS['chaos-quick'] = sc_chaos_quick


# ---------------------------------------------------------------------- replay of car timelines (stage 3)
ACTIONS = {
    'cable_plug': lambda car, a: car.cable_plug(),
    'cable_unplug': lambda car, a: car.cable_unplug(),
    'aa_plug': lambda car, a: car.aa_plug(),
    'aa_unplug': lambda car, a: car.aa_unplug(),
    'aa_kill': lambda car, a: car.aa_kill(),
    'vw_steal': lambda car, a: car.vw_steal_in(0),
    'reverse': lambda car, a: threading.Thread(target=car.reverse, args=(a.get('s', 5),), daemon=True).start(),
    'wl_start': lambda car, a: car.wl_start(fps=a.get('fps', 30), gop=a.get('gop', 5)),
    'wl_stop': lambda car, a: car.wl_stop(a.get('reason', 'done')),
}


def replay(path):
    """A car timeline (timelines/*.json): actions at car times, then what the car saw, each with a tolerance.
    {"source": "...", "params": {...}, "actions": [{"t": 2.0, "do": "cable_plug"}, ...],
     "expect": [{"t": 3.1, "kind": "dmdt", "match": "^dc 72", "tol": 1.0, "what": "..."}, ...], "end": 30}
    Sim time 0 = the car's t 0 (supervisor start). Every expected event is matched in order to the first sim event
    of that kind after the previous match; the report lists car t, sim t and the difference."""
    tl = json.load(open(path))
    name = 'replay-' + os.path.splitext(os.path.basename(path))[0]
    saved = dict(PARAMS)
    PARAMS.update(tl.get('params', {}))
    try:
        car = Car(name)
        car.boot()
        t0 = car.boot_t   # the car's t 0: before the encoder thread can act
        for a in sorted(tl['actions'], key=lambda x: x['t']):
            while now() < t0 + a['t']:
                time.sleep(0.01)
            ACTIONS[a['do']](car, a)
        while now() < t0 + tl.get('end', 30):
            time.sleep(0.05)
        car.shutdown()
    finally:
        PARAMS.clear()
        PARAMS.update(saved)
    lines = ['replay %s (source: %s)' % (name, tl.get('source', '?')),
             '%-44s %8s %8s %7s %5s' % ('expected', 'car t', 'sim t', 'diff', 'tol')]
    after = t0
    for e in tl['expect']:
        hit = car.bb.find(e['kind'], e['match'], after)
        st = hit[0][0] - t0 if hit else None
        if hit:
            hit = [(hit[0][0] + 1e-6,) + tuple(hit[0][1:])]   # the next expectation starts after this event
        diff = None if st is None else st - e['t']
        ok = diff is not None and abs(diff) <= e.get('tol', 1.0)
        if hit:
            after = hit[0][0]
        lines.append('%-44s %8.2f %8s %7s %5.1f %s' % (e.get('what', e['kind'] + ' ' + e['match'])[:44], e['t'],
                     '-' if st is None else '%.2f' % st, '-' if diff is None else '%+.2f' % diff, e.get('tol', 1.0),
                     'ok' if ok else 'DIFF'))
        if not tl.get('informational') or os.environ.get('FAKECAR_STRICT'):
            check('%s: %s at car t=%.2f (sim %s)' % (name, e.get('what', e['match']), e['t'],
                                                     '-' if st is None else '%.2f' % st), ok,
                  'diff=%s tol=%s' % (diff, e.get('tol', 1.0)))
    with open(os.path.join(car.dir, 'replay.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join('       ' + l for l in lines), flush=True)
    common_invariants(car)


for _p in sorted(os.listdir(os.path.join(HERE, 'timelines'))) if os.path.isdir(os.path.join(HERE, 'timelines')) else []:
    if _p.endswith('.json'):
        SCENARIOS['replay-' + _p[:-5]] = (lambda path: lambda: replay(path))(os.path.join(HERE, 'timelines', _p))


def print_params():
    print('| parametr | wartość | źródło | opis |')
    print('|---|---|---|---|')
    for k, v in PARAMS.items():
        src, text = PARAM_SRC.get(k, ('?', ''))
        print('| %s | %s | %s | %s |' % (k, v, 'zmierzone' if src == 'M' else 'założenie',
                                         re.sub(r'^[MA]( \(\w+\))?:\s*', '', text)))


def run_parallel(names):
    """Every scenario in its own process (own car dir, socket, processes), JOBS at a time; output kept per scenario."""
    import collections
    order = sorted(names, key=lambda n: (not n.startswith(('chaos', 'replay-car')), names.index(n)))   # long ones first
    queue = collections.deque(order)
    running = {}
    n_ok = n_bad = 0
    bad_names = []
    t0 = time.time()
    while queue or running:
        while queue and len(running) < JOBS:
            n = queue.popleft()
            f = open(os.path.join(BUILD, 'job-%s.log' % n), 'w+')
            running[n] = (subprocess.Popen([sys.executable, '-I', os.path.abspath(__file__), BUILD, n],
                                           stdout=f, stderr=subprocess.STDOUT,
                                           env=dict(os.environ, FAKECAR_JOBS='1')), f)
        time.sleep(0.2)
        for n, (p, f) in list(running.items()):
            if p.poll() is None:
                continue
            del running[n]
            f.seek(0)
            out = f.read()
            f.close()
            m = re.search(r'FAKECAR TESTS: (\d+) ok, (\d+) failed', out)
            a, b = (int(m.group(1)), int(m.group(2))) if m else (0, 1)
            n_ok, n_bad = n_ok + a, n_bad + b
            if b:
                bad_names.append(n)
            print('\n'.join(l for l in out.splitlines() if not l.startswith('FAKECAR TESTS')), flush=True)
            if not m:
                print('FAILED %s: scenario process died (rc %s)' % (n, p.returncode), flush=True)
    print('parallel: %d scenarios, %d at a time, %.1f min%s' % (len(names), JOBS, (time.time() - t0) / 60,
          ('; failed in ' + ', '.join(bad_names)) if bad_names else ''))
    print('FAKECAR TESTS: %d ok, %d failed' % (n_ok, n_bad))
    return 1 if n_bad else 0


def main():
    if '--params' in sys.argv:
        print_params()
        return 0
    names = [n for n in SCENARIOS if not ONLY or n in ONLY]
    if JOBS > 1 and len(names) > 1:
        return run_parallel(names)
    for name, fn in SCENARIOS.items():
        if ONLY and name not in ONLY:
            continue
        print('== scenario %s' % name, flush=True)
        try:
            fn()
        except Exception as e:   # a crash in the car is a failed scenario, not a silent pass
            import traceback
            traceback.print_exc()
            check(f'{name}: scenario ran to the end', False, repr(e))
    n_ok = sum(1 for _, c in results if c)
    n_bad = len(results) - n_ok
    print('FAKECAR TESTS: %d ok, %d failed' % (n_ok, n_bad))
    return 1 if n_bad else 0


if __name__ == '__main__':
    sys.exit(main())
