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
ONLY = sys.argv[2:]
HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE_DIR = os.path.dirname(HERE)

ENOMEM, EBUSY, EAGAIN, EBADF, ENOTTY = 12, 16, 35 if sys.platform == 'darwin' else 11, 9, 25
DC_START, DC_FLUSH = 0x80040509, 0x40040506
DC_READ = {0x4004050c: 0, 0x4004050d: 0, 0x40040510: 0}   # iface / packet size / block count (A: unknown on MU1161)

PARAMS = {
    'bps': 12288000,          # A: channel drain rate (host_mlb.c default)
    'depth': 2 * 12032,       # A: driver FIFO
    'dmdt_ms': 120,           # A: dmdt effect delay
    'vw_knock_ms': 50,        # M: 20 open tries/s (sloginfo 16.11, A208)
    'vw_release_ms': 80,      # A: encoder closes after dc 72 (M: it does close, A222)
    'vw_knock_in_cp': False,  # M: A222 with supervisor pmcp: 0 "error open" after dc 72
    'vw_return_ms': 400,      # A: encoder back after dc 70 33 / sc 4 70
    'aa_fps': 30,             # AA phone model (aa/feeder/test/run_direct_test.py): 8-frame window, IDR ~60 s
    'aa_window': 8,
    'aa_idr_every_s': 60,
    'wl_idle_ms': 3000,
    'screen_hold_ms': 1500,   # A: the AID keeps the last picture this long without data       # A: WL cluster_owner_idle_ms (WL: no frames -> session stop reason=idle)
}
AA_FEEDER_TEST = os.path.join(BRIDGE_DIR, '..', 'aa', 'feeder', 'test')
AA_MOST_TEST = os.path.join(BRIDGE_DIR, '..', 'aa', 'most', 'test')

T0 = time.monotonic()


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
            if len(data) % 188 or any(data[i] != 0x47 for i in range(0, len(data), 188)):
                h.bad_blocks += 1
            if h.idr_at is None and re.search(rb'\x00\x00\x01[\x25\x45\x65]', data):
                h.idr_at = t
                self.bb.rec('screen', 'keyframe tag=%s id=%d' % (h.tag, h.hid))
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


class AAPhone:
    """gal's hook + the phone for the real aa-most-feeder: Annex-B stream over TCP, one ACK byte per frame back
    (8-frame window), IDR first and about every 60 s, never on request (AA 2026-11-24)."""
    n = 0

    def __init__(self, car, idr_every_s):
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
                idr = i % self.idr_every == 0
                au, _ = hs.access_unit(idr, 20000 if idr else rng.randrange(1500, 4000), rng)
                t_sent = time.time()
                self.conn.sendall(au)
                self.frames.append(dict(idx=i, frame_no=i + 1, ring_seq=i + 2, idr=idr,
                                        avcc_sha256=self.avcc_hash(au), t_us=int((t_sent - t0) * 1e6)))
                i += 1
                t_next = max(t_next + 1.0 / PARAMS['aa_fps'], t_sent - 0.5 / PARAMS['aa_fps'])
                self.take(ack, 0)
            end = time.time() + 1.0                            # collect the last ACKs
            while time.time() < end and self.take(ack, 0.05):
                pass
        except OSError:
            pass
        with open(os.path.join(self.dir, 'input', 'frames.jsonl'), 'w') as f:
            f.write(json.dumps(dict(event='avcC', ring_seq=1, sps=hs.sps().hex(), pps=hs.pps().hex())) + '\n')
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

    def stop(self, mode):
        if self.stopping.is_set() and mode == 'unplug' and self.feeder.poll() is not None:
            return
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
        self.env = dict(os.environ, FAKECAR_SOCK=self.sock_path, FAKECAR_DIR=self.dir, FAKECAR_WHO='cp',
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
        while not self.stop_ev.is_set():
            time.sleep(PARAMS['vw_knock_ms'] / 1000.0)
            t = now()
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
                if self.view == 'cp' and t - self.view_t >= PARAMS['vw_release_ms'] / 1000.0:
                    if self.chan.vw_drop():
                        self.bb.rec('vw', 'release (tries=%d)' % tries)
                    holding = False
                elif self.chan.holder != 'vw':
                    holding = False
                continue
            knock = (self.view == 'vw' and t - self.view_t >= PARAMS['vw_return_ms'] / 1000.0) or \
                PARAMS['vw_knock_in_cp']
            if knock:
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
            elif isinstance(hd, Handle) and hd.idr_at is not None and hd.last_write and t - hd.last_write < PARAMS['screen_hold_ms'] / 1000.0:
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
                                '--frames', '100000', '--fps', '30', '--gop', '60', '--repeat-avcc', '1'])
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
    def aa_plug(self, idr_every_s=None):
        self.aa = AAPhone(self, idr_every_s or PARAMS['aa_idr_every_s'])
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
                              '--idr-on-request', str(idr_on_request)])
        self.wl_gen = gen
        ms = int(time.monotonic() * 1000)
        put(os.path.join(self.src, 'owner'), 'v=1 src=wireless pid=%d gen=%d since_ms=%d\n' % (self.wl.pid, gen, ms))
        put(os.path.join(self.src, 'wireless.session'),
            'v=1 state=start gen=%d pid=%d ts_ms=%d reason=connect\n' % (gen, self.wl.pid, ms))
        self.marks.setdefault('wl_start', []).append(now())
        self.bb.rec('phone', 'wl start gen=%d fps=%d gop=%d producer=%d' % (gen, fps, gop, self.wl.pid))

    def wl_stop(self, reason):
        """'idle': Wi-Fi gone, no frames for wl_idle_ms, then stop; otherwise the stream ended (TEARDOWN...)."""
        pid = self.wl.pid
        if self.wl.poll() is None:
            self.wl.kill()
            self.wl.wait()
        self.bb.rec('phone', 'wl stream gone reason=%s' % reason)
        if reason == 'idle':
            time.sleep(PARAMS['wl_idle_ms'] / 1000.0)
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

    # ---- the unit under load: reverse camera, CPU 98-100 %, devp-iso-mmx drains slowly (A203/A208)
    def reverse(self, seconds, rate=0.1):
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


def aa_invariants(car, phone, sessions_with_most=1, ts=True):
    n = car.name
    gb = dm(car, r'^dc 70 33 by=aa', after=phone.plug_t)
    check(f'{n}: AA gives MOST back exactly once per session ({sessions_with_most})', len(gb) == sessions_with_most,
          len(gb))
    check(f'{n}: AA never asks the phone for an IDR (no K/C on the ACK socket)', phone.other == 0, phone.other)
    check(f'{n}: one ACK per frame sent ({len(phone.frames)})', phone.acks == len(phone.frames),
          '%d/%d' % (phone.acks, len(phone.frames)))
    check(f'{n}: AA guardian marker and owner file removed after the restore',
          not os.path.exists(os.path.join(car.ram, 'pmcp-aa-guard.pid')) and
          not os.path.exists(os.path.join(car.src, 'isotx2')))
    if ts and sessions_with_most:
        rc, out, norm = phone.analyse()
        miss = norm and norm['missing_frame_nos']
        check(f'{n}: AA TS passes ts_analyse', rc == 0, out[-300:])
        check(f'{n}: every AA frame in the TS once, in order', norm and not miss and
              norm['output_aus'] >= len(phone.frames) - 0, 'out=%s sent=%d missing=%s' % (
                  norm and norm['output_aus'], len(phone.frames), miss and miss[:8]))


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
    car.wl_stop('idle')
    time.sleep(5)
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
    car.wl_stop('teardown')
    time.sleep(4)
    d = car.first_after(car.marks['wl_stop'][0], 'vw', 4)
    check('wl-steal: VW map back within 3 s of the teardown', d is not None and d < 3, d)
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
    aa_invariants(car, car.aa, ts=False)


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
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    # ts_analyse assumes one continuous capture (PSI cadence by packet number); AA's own reclaim test does not run it
    # either. The AU in flight at the steal is cut (the ENOMEM block is not accepted) - question to AA (docs/28).
    aa_invariants(car, car.aa, ts=False)


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
    car.aa_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)
    aa_invariants(car, car.aa)


SCENARIOS = {'session': sc_session, 'boot-steal': sc_boot_steal, 'replug': sc_replug, 'cp-reverse': sc_cp_reverse,
             'wl-session': sc_wl_session, 'wl-steal': sc_wl_steal,
             'aa-session': sc_aa_session, 'aa-kill': sc_aa_kill, 'aa-holds': sc_aa_holds, 'cp-then-aa': sc_cp_then_aa,
             'aa-steal': sc_aa_steal, 'aa-reverse': sc_aa_reverse, 'aa-silence': sc_aa_silence}


def main():
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
