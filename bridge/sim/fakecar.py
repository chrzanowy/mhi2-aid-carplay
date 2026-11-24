#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""fake-car: one process that plays the car around our MOST programs (docs/28-symulator-auta.md, stage 1).

usage: python3 -I fakecar.py BUILD_DIR [scenario ...]      (run by sim/run_sim.sh)

The real supervisor (pmcp-most-sup) and the real pmcp-most stage 2 bridge (host build with sim_mlb.c) run unchanged;
the car owns the isoTX2 channel (unix socket, sim_mlb.c), dmdt (sim/dmdt -> dmdt.req), the factory VW encoder (an
adversary thread), the phones (ring producer + marker files) and the AID screen. Verdicts come only from what the car
sees: channel calls, dmdt calls, accepted bytes, files and processes. Every run leaves runs/<scenario>/blackbox.txt.

Model parameters: M = measured in the car (visit), A = assumption (docs/28 "Model auta").
"""
import os, re, shutil, signal, socket, struct, subprocess, sys, threading, time

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
}

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
        self.started = False
        self.stolen = False
        self.idr_at = None       # first keyframe accepted on this handle (picture visible)
        self.last_write = None
        self.bytes = 0
        self.bad_blocks = 0


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
            self.bb.rec('chan', 'open tag=%s pid=%d id=%d path=%s' % (tag, pid, h.hid, path))
            return h

    def close(self, h, why='close'):
        with self.lock:
            if self.holder is h:
                self.holder = None
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
            self.level = max(0.0, self.level - (t - self.level_t) * PARAMS['bps'] / 8.0)
            self.level_t = t
            if not h.started or len(data) > PARAMS['depth'] - self.level:
                return -1, EAGAIN
            self.level += len(data)
            h.bytes += len(data)
            h.last_write = t
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
        self.env = dict(os.environ, FAKECAR_SOCK=self.sock_path, FAKECAR_DIR=self.dir,
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
        for k in ('PMCP_SUP_TIME_DIV', 'CARPLAY_CLUSTER_INTRO', 'FAKECAR_TAG'):
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
                self.bb.rec('dmdt', args)
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
            elif isinstance(hd, Handle) and hd.idr_at is not None and hd.last_write and t - hd.last_write < 0.3:
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

    def proc_watch(self):
        """Bridge processes as the car's pidin would show them (start/exit)."""
        seen = set()
        while not self.stop_ev.is_set():
            time.sleep(0.05)
            r = subprocess.run(['pgrep', '-f', os.path.join(self.app, 'altscreen-most-bridge')],
                               capture_output=True, text=True)
            pids = set(int(x) for x in r.stdout.split())
            for p in pids - seen:
                self.bb.rec('proc', 'bridge start pid=%d' % p)
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

    def aa_start(self):
        """AA direct holds the channel (stage 1: played by the car; stage 2: the real feeder)."""
        self.aa_guard = self.spawn(['sleep', '3600'])
        with open(os.path.join(self.ram, 'pmcp-aa-guard.pid'), 'w') as f:
            f.write('%d\n' % self.aa_guard.pid)
        with open(os.path.join(self.src, 'isotx2'), 'w') as f:
            f.write('v=1 holder=aa pid=%d since_ms=0\n' % self.aa_guard.pid)
        self.dmdt_apply('dc 72')
        self.bb.rec('phone', 'aa start guard=%d' % self.aa_guard.pid)
        for _ in range(100):
            time.sleep(0.05)
            self.aa_handle = self.chan.open('aa', self.aa_guard.pid, '/dev/mlb/isoTX2')
            if self.aa_handle:
                self.aa_handle.started = True
                self.aa_handle.idr_at = now()
                break
        self.marks['aa_start'] = now()
        threading.Thread(target=self.aa_writer, daemon=True).start()

    def aa_writer(self):
        block = bytes([0x47] + [0] * 187) * 64
        while self.aa_handle and not self.stop_ev.is_set():
            self.chan.write(self.aa_handle, block)
            time.sleep(0.02)

    def aa_stop(self):
        h, self.aa_handle = self.aa_handle, None
        if h:
            self.chan.close(h, 'close')
        self.dmdt_apply('dc 70 33')
        for p in (os.path.join(self.src, 'isotx2'), os.path.join(self.ram, 'pmcp-aa-guard.pid')):
            try:
                os.unlink(p)
            except OSError:
                pass
        self.aa_guard.kill()
        self.marks['aa_stop'] = now()
        self.bb.rec('phone', 'aa stop')

    def vw_steal_in(self, seconds):
        self.vw_steal_at = now() + seconds
        self.marks.setdefault('steal', []).append(self.vw_steal_at)

    def shutdown(self):
        self.bb.rec('car', 'shutdown')
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
        left = subprocess.run(['pgrep', '-f', os.path.join(self.app, 'altscreen-most-bridge')],
                              capture_output=True, text=True).stdout.split()
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


def common_invariants(car):
    n = car.name
    rows = car.bb.rows
    # I1 two writers: an accepted CP byte never while AA holds (model) + bad TS blocks
    bad = [h for h in car.chan.handles.values() if h.bad_blocks]
    check(f'{n}: every block written is whole TS packets (188 B, sync 0x47)', not bad,
          ', '.join('id=%d bad=%d' % (h.hid, h.bad_blocks) for h in bad))
    # I3 dmdt order: no restore (dc 70) while a CP handle is open on the channel
    opened = set()
    viol = []
    for t, k, x in rows:
        m = re.match(r'open tag=cp pid=\d+ id=(\d+)', x) if k == 'chan' else None
        if m:
            opened.add(m.group(1))
        m = re.match(r'close tag=cp id=(\d+)', x) if k == 'chan' else None
        if m:
            opened.discard(m.group(1))
        if k == 'dmdt' and x.startswith('dc 70') and opened:
            viol.append('%.2f' % t)
    check(f'{n}: dmdt restore only after the bridge closed isoTX2', not viol, ' '.join(viol))
    # I6 logs bounded
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
    # VW never killed: the encoder is in the car, so the check is that the car view ends on VW
    check(f'{n}: after shutdown the cluster is back on the VW map', car.view == 'vw' and car.screen and
          car.screen[-1][1] == 'vw', 'view=%s screen=%s' % (car.view, car.screen[-1][1] if car.screen else None))


# ---------------------------------------------------------------------- scenarios
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
    rel = car.bb.find('dmdt', '', after=t)
    check('session: takeover dmdt dc 72 + sc 4 72 before the bridge opened isoTX2',
          [x for _, _, x in rel[:2]] == ['dc 72', 'sc 4 72'] and
          rel and car.bb.find('chan', 'open tag=cp', after=t) and
          rel[1][0] < car.bb.find('chan', 'open tag=cp', after=t)[0][0], [x for _, _, x in rel[:4]])
    car.cable_unplug()
    time.sleep(5)
    u = car.marks['unplug'][0]
    d = car.first_after(u, 'vw', 5)
    check('session: VW map back within 4 s of the unplug', d is not None and d < 4, d)
    car.shutdown()
    common_invariants(car)


def sc_boot_steal():
    """Cold start: 15 s after the bridge took isoTX2 the encoder takes it back (A184/A201/A208): the bridge must
    reclaim (ENOMEM -> dmdt -> reopen) and the CP picture must come back with a keyframe."""
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
    check('boot-steal: reclaim dmdt (dc 72) after the steal', car.bb.find('dmdt', '^dc 72$', after=st))
    blank = sum(1 for t, w in car.screen if st <= t <= st + 6 and w != 'cp') * 0.05
    check('boot-steal: picture gap after the steal under 2 s', blank < 2.0, '%.2f s' % blank)
    car.cable_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_aa_holds():
    """AA direct holds isoTX2; a CP cable session starts: CP must not take MOST (no dmdt, no open), AA keeps the map."""
    car = Car('aa-holds')
    car.boot()
    time.sleep(1)
    car.aa_start()
    time.sleep(1)
    t = now()
    car.cable_plug()
    time.sleep(5)
    check('aa-holds: no dmdt from CP while AA holds the channel', not car.bb.find('dmdt', '', after=t),
          [x for _, _, x in car.bb.find('dmdt', '', after=t)])
    check('aa-holds: CP never got isoTX2', not car.bb.find('chan', 'open tag=cp pid=\\d+ id=', after=t))
    check('aa-holds: AA keeps the AID', all(w == 'aa' for ts, w in car.screen if t + 0.2 <= ts <= t + 5))
    car.aa_stop()
    time.sleep(6)
    a = car.marks['aa_stop']
    d = car.first_after(a, 'cp', 6)
    check('aa-holds: CP takes over within 5 s after AA ended (phone still plugged)', d is not None and d < 5, d)
    car.cable_unplug()
    time.sleep(4)
    car.shutdown()
    common_invariants(car)


def sc_replug():
    """Three quick unplug/plug cycles: one supervisor, one bridge at a time, VW and CP alternate."""
    car = Car('replug')
    car.boot()
    time.sleep(1)
    for _ in range(3):
        car.cable_plug()
        time.sleep(4)
        car.cable_unplug()
        time.sleep(3)
    ok_cp = all(car.first_after(t, 'cp', 4) is not None for t in car.marks['plug'])
    ok_vw = all(car.first_after(t, 'vw', 3) is not None for t in car.marks['unplug'])
    check('replug: CP map after every plug', ok_cp)
    check('replug: VW map after every unplug', ok_vw)
    starts = car.bb.find('proc', 'bridge start')
    check('replug: one bridge per session (3)', len(starts) == 3, len(starts))
    car.shutdown()
    common_invariants(car)


SCENARIOS = {'session': sc_session, 'boot-steal': sc_boot_steal, 'aa-holds': sc_aa_holds, 'replug': sc_replug}


def main():
    for name, fn in SCENARIOS.items():
        if ONLY and name not in ONLY:
            continue
        print('== scenario %s' % name, flush=True)
        try:
            fn()
        except Exception as e:   # a crash in the car is a failed scenario, not a silent pass
            check(f'{name}: scenario ran to the end', False, repr(e))
    n_ok = sum(1 for _, c in results if c)
    n_bad = len(results) - n_ok
    print('FAKECAR TESTS: %d ok, %d failed' % (n_ok, n_bad))
    return 1 if n_bad else 0


if __name__ == '__main__':
    sys.exit(main())
