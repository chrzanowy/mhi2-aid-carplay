# SPDX-License-Identifier: GPL-3.0-or-later
"""Host tests of the MOST supervisor v1 (src/pmcp_most_sup.c), docs/23 "Etap 5".

Fake dmdt, ln and bridge (shell scripts) write one ordered event log; the supervisor runs with every path in a temp
directory and its times divided by 10 (PMCP_SUP_TIME_DIV). Usage: python3 -I sup_test.py SUPERVISOR_BINARY
Prints "SUPERVISOR TESTS: N ok, M failed"; exit status 1 on any failure.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

SUP = os.path.abspath(sys.argv[1])
OK = 0
BAD = 0


def ok(cond, what):
    global OK, BAD
    if cond:
        OK += 1
        print("ok     " + what)
    else:
        BAD += 1
        print("FAILED " + what)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def script(path, body):
    write(path, "#!/bin/sh\n" + body)
    os.chmod(path, 0o755)


class Rig:
    def __init__(self, bridge_mode="run"):
        self.d = tempfile.mkdtemp(prefix="pmcp-sup-")
        self.ram = os.path.join(self.d, "ramdisk")
        self.app = os.path.join(self.d, "app")
        self.src = os.path.join(self.ram, "most-src")
        self.ev = os.path.join(self.d, "events.log")
        self.link = os.path.join(self.d, "dev", "pmcp-isoTX2")
        self.dev = os.path.join(self.d, "dev", "mlb", "isoTX2")
        os.makedirs(os.path.join(self.app, "stock_first"))
        os.makedirs(self.src)
        os.makedirs(os.path.dirname(self.dev))
        write(self.ev, "")
        script(os.path.join(self.d, "dmdt"), 'echo "dmdt $*" >> "%s"\nexit 0\n' % self.ev)
        script(os.path.join(self.d, "ln"), 'echo "ln $*" >> "%s"\nln -s "$2" "$3"\n' % self.ev)
        # fake bridge: run = until SIGTERM; exit = 0.2 s then exit 3; stubborn = ignores SIGTERM
        body = {
            "run": 'trap \'echo "bridge term $$" >> "%s"; exit 0\' TERM\necho "bridge start $$" >> "%s"\n'
                   'while :; do sleep 0.05; done\n',
            "exit": 'echo "bridge start $$" >> "%s"\nsleep 0.2\necho "bridge exit $$" >> "%s"\nexit 3\n',
            "stubborn": 'trap \'echo "bridge ignore-term $$" >> "%s"\' TERM\necho "bridge start $$" >> "%s"\n'
                        'while :; do sleep 0.05; done\n',
        }[bridge_mode]
        script(os.path.join(self.app, "altscreen-most-bridge"), body.replace("%s", self.ev))
        os.symlink(self.dev, self.link)   # the lsd.sh block made it at start
        self.env = dict(os.environ, PMCP_SUP_RAMDISK=self.ram, PMCP_SUP_APP=self.app, PMCP_MOST_SRC_DIR=self.src,
                        PMCP_SUP_DMDT=os.path.join(self.d, "dmdt"), PMCP_SUP_LN=os.path.join(self.d, "ln"),
                        PMCP_SUP_LINK=self.link, PMCP_SUP_DEV=self.dev,
                        PMCP_SUP_FLUSH=os.path.join(self.d, "flush"), PMCP_SUP_TIME_DIV="10",
                        PMCP_MOST_RING=os.path.join(self.ram, "carplay-alt-ring.bin"))
        self.env.pop("PMCP_AA_RUNDIR", None)
        self.sleeper = subprocess.Popen(["sleep", "300"])
        self.p = None

    def start(self):
        self.p = subprocess.Popen([SUP], env=self.env)
        time.sleep(0.05)
        return self.p

    def events(self):
        with open(self.ev) as f:
            return [l.strip() for l in f if l.strip()]

    def log(self):
        try:
            with open(os.path.join(self.ram, "pmcp-most", "sup.log")) as f:
                return f.read()
        except OSError:
            return ""

    def wired_on(self, pid=None):
        write(os.path.join(self.ram, "carplay-dio-manager.pid"), "%d\n" % (pid or self.sleeper.pid))
        write(os.path.join(self.ram, "carplay-altstream.ready"), "")

    def wired_off(self):
        try:
            os.unlink(os.path.join(self.ram, "carplay-altstream.ready"))
        except OSError:
            pass

    def holder(self):
        try:
            with open(os.path.join(self.src, "isotx2")) as f:
                return f.read().strip()
        except OSError:
            return None

    def wait(self, cond, t=2.0):
        end = time.time() + t
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return cond()

    def stop(self):
        if self.p and self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
            try:
                self.p.wait(5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.sleeper.kill()
        subprocess.run(["pkill", "-f", os.path.join(self.app, "altscreen-most-bridge")], check=False)


def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def idx(evs, prefix):
    for i, e in enumerate(evs):
        if e.startswith(prefix):
            return i
    return -1


def has_bridge(r):
    return any(e.startswith("bridge start") for e in r.events())


print("== wired: takeover, giveback, order")
r = Rig()
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "wired ready: bridge started")
h = r.holder() or ""
ok(h.startswith("v=1 holder=cp pid=%d " % r.p.pid), "isotx2 holder=cp pid=supervisor (%s)" % h)
ok(not os.path.lexists(r.link), "encoder link removed while CP holds the channel")
evs = r.events()
ok(idx(evs, "dmdt dc 72") < idx(evs, "dmdt sc 4 72") < idx(evs, "bridge start") and idx(evs, "dmdt dc 72") >= 0,
   "OEM release dc 72, sc 4 72, then the bridge")
lg = r.log()
ok(lg.find("dm-link-dropped") < lg.find("oem-most-release") and lg.find("dm-link-dropped") >= 0, "link dropped before the OEM release")
r.wired_off()
ok(r.wait(lambda: any(e.startswith("dmdt sc 4 70") for e in r.events())), "stream gone: OEM restore")
evs = r.events()
ok(idx(evs, "bridge term") < idx(evs, "ln -Ps") < idx(evs, "dmdt dc 70 33") < idx(evs, "dmdt sc 4 70")
   and idx(evs, "bridge term") >= 0, "bridge stopped, link made BEFORE dc 70 33 / sc 4 70")
ok(os.path.islink(r.link) and os.readlink(r.link) == r.dev, "link points to the MOST device again")
ok(r.holder() is None, "isotx2 file removed after the giveback")
ok("state-oem-active" in r.log(), "log: state-oem-active")
r.stop()
ok(not os.path.exists(os.path.join(r.ram, "pmcp-most", "sup.pid")), "SIGTERM: pid file removed")

print("== AA holds the channel: no takeover until it lets go")
r = Rig()
write(os.path.join(r.ram, "pmcp-aa-guard.pid"), "%d\n" % r.sleeper.pid)
r.start()
r.wired_on(pid=os.getpid())
time.sleep(0.6)
ok(not has_bridge(r) and not any(e.startswith("dmdt") for e in r.events()), "live AA guard: no dmdt, no bridge")
ok("wait-aa-holder pid=%d" % r.sleeper.pid in r.log() and r.log().count("wait-aa-holder") == 1, "logged once: wait-aa-holder")
ok(os.path.islink(r.link), "link untouched while AA holds")
os.unlink(os.path.join(r.ram, "pmcp-aa-guard.pid"))
ok(r.wait(lambda: has_bridge(r)), "AA gone: takeover")
r.stop()

r = Rig()
other = subprocess.Popen(["sleep", "300"])
write(os.path.join(r.src, "isotx2"), "v=1 holder=aa pid=%d since_ms=1\n" % other.pid)
r.start()
r.wired_on()
time.sleep(0.5)
ok(not has_bridge(r) and r.holder().startswith("v=1 holder=aa"), "isotx2 holder=aa (live): no takeover, file untouched")
other.kill()
other.wait()
ok(r.wait(lambda: has_bridge(r)), "AA holder dead: takeover")
ok((r.holder() or "").startswith("v=1 holder=cp"), "dead AA holder file replaced by holder=cp")
r.stop()

print("== a live CP holder that is not us: busy")
r = Rig()
other = subprocess.Popen(["sleep", "300"])
write(os.path.join(r.src, "isotx2"), "v=1 holder=cp pid=%d since_ms=1\n" % other.pid)
r.start()
r.wired_on()
time.sleep(0.5)
ok(not has_bridge(r) and not any(e.startswith("dmdt") for e in r.events()), "other live holder: no dmdt, no bridge")
ok("takeover-busy" in r.log(), "log: takeover-busy")
other.kill()
r.stop()

print("== Wi-Fi: owner src=wireless + session of the same gen")
r = Rig()
r.start()
write(os.path.join(r.src, "owner"), "v=1 src=wireless pid=%d gen=5 since_ms=1 kind=in\n" % r.sleeper.pid)
write(os.path.join(r.src, "wireless.session"), "v=1 state=start gen=4 pid=%d ts_ms=1 reason=start\n" % r.sleeper.pid)
time.sleep(0.5)
ok(not has_bridge(r), "session of another gen: no takeover")
write(os.path.join(r.src, "wireless.session"), "v=1 state=start gen=5 pid=%d ts_ms=2 reason=start\n" % r.sleeper.pid)
ok(r.wait(lambda: has_bridge(r)), "wireless session start: takeover")
ok("source=wireless" in r.log(), "log: source=wireless")
write(os.path.join(r.src, "wireless.session"), "v=1 state=stop gen=5 pid=%d ts_ms=3 reason=done\n" % r.sleeper.pid)
ok(r.wait(lambda: any(e.startswith("dmdt sc 4 70") for e in r.events())), "wireless session stop: giveback")
r.stop()

print("== wired to Wi-Fi in one session: the bridge keeps running")
r = Rig()
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "wired: bridge")
write(os.path.join(r.src, "owner"), "v=1 src=wireless pid=%d gen=6 since_ms=1 kind=in\n" % r.sleeper.pid)
write(os.path.join(r.src, "wireless.session"), "v=1 state=start gen=6 pid=%d ts_ms=1 reason=start\n" % r.sleeper.pid)
r.wired_off()
time.sleep(0.4)
evs = r.events()
ok(sum(1 for e in evs if e.startswith("bridge start")) == 1 and idx(evs, "dmdt dc 70") < 0, "no giveback, one bridge run")
r.stop()

print("== stale ready marker (dead dio_manager)")
r = Rig()
r.start()
r.wired_on(pid=dead_pid())
time.sleep(0.4)
ok(not has_bridge(r) and not os.path.exists(os.path.join(r.ram, "carplay-altstream.ready")), "stale marker removed, no takeover")
ok("stale-ready-cleared" in r.log(), "log: stale-ready-cleared")
r.stop()

print("== the bridge exits: giveback, retry, back-off after 3 exits")
r = Rig("exit")
r.start()
r.wired_on()
ok(r.wait(lambda: r.log().count("bridge-exited") >= 1), "bridge exit seen")
ok(r.wait(lambda: "bridge-backoff" in r.log(), 4.0), "3 exits in the window: bridge-backoff")
n = r.log().count("bridge-started")
time.sleep(1.0)
ok(r.log().count("bridge-started") == n, "no new start during the back-off")
time.sleep(0.3)
evs = r.events()
ok(evs.count("dmdt sc 4 70") == r.log().count("bridge-exited pid=") and evs[-1] == "dmdt sc 4 70",
   "every exit followed by an OEM restore (%d restores, %d exits)" % (evs.count("dmdt sc 4 70"), r.log().count("bridge-exited pid=")))
r.stop()

print("== a bridge that ignores SIGTERM: flush, then SIGKILL")
r = Rig("stubborn")
write(os.path.join(r.d, "flush"), "")   # the debug device exists on the unit; open() never creates it
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "bridge started")
r.wired_off()
ok(r.wait(lambda: "bridge-killed" in r.log(), 3.0), "SIGKILL after the wait")
ok(open(os.path.join(r.d, "flush")).read() == "flush(0)\n", "flush(0) written to the debug device")
r.stop()

print("== rescue card DISABLED and SIGTERM while active")
r = Rig()
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "bridge started")
write(os.path.join(r.app, "stock_first", "DISABLED"), "")
ok(r.wait(lambda: r.p.poll() is not None), "DISABLED: supervisor exits")
ok("giveback reason=disabled" in r.log() and r.events()[-1] == "dmdt sc 4 70", "DISABLED: giveback first")
r.stop()
r = Rig()
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "bridge started")
r.p.send_signal(signal.SIGTERM)
r.p.wait(5)
ok("giveback reason=signal" in r.log() and os.path.islink(r.link) and r.holder() is None, "SIGTERM: giveback, link back, no holder")
r.stop()

print("== no ln on the unit (car 2026-11-22: /proc/boot/ln missing, status=127)")
r = Rig()
r.env["PMCP_SUP_LN"] = os.path.join(r.d, "no-such-ln")
r.start()
r.wired_on()
ok(r.wait(lambda: has_bridge(r)), "wired ready: bridge started")
r.wired_off()
ok(r.wait(lambda: any(e.startswith("dmdt sc 4 70") for e in r.events())), "missing ln: OEM restore still done")
ok("dm-link-make-failed no-ln path=%s" % r.env["PMCP_SUP_LN"] in r.log(), "log: dm-link-make-failed no-ln")
ok("status=127" not in r.log(), "no status=127 line")
r.stop()
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "pmcp_most_sup.c")).read()
ok('env_or("PMCP_SUP_LN", "/bin/ln")' in src and "/proc/boot/ln\")" not in src, "default ln is /bin/ln (MU1161)")

print("== one instance")
r = Rig()
r.start()
second = subprocess.run([SUP], env=r.env, timeout=5)
ok(second.returncode == 0 and "already-running" in r.log(), "second instance exits: already-running")
r.stop()

print("== ring made at start when missing (A247: Wi-Fi without the cable)")
import shutil
import struct
RING_SIZE, RING_MAGIC = 0x1000710, 0x43505247
r = Rig()
ring = r.env["PMCP_MOST_RING"]
r.start()
ok(r.wait(lambda: "ring-created" in r.log()), "log: ring-created")
st = os.stat(ring)
magic, version, gen = struct.unpack("<III", open(ring, "rb").read(12))
ok(st.st_size == RING_SIZE and magic == RING_MAGIC and gen == 1, "ring: full size, magic, generation 1")
ok(st.st_mode & 0o777 == 0o666, "ring: mode 0666 as the bridge makes it")
# the WL producer now finds the ring and takes the owner; the supervisor starts the bridge (no cable at all)
write(os.path.join(r.src, "owner"), "v=1 src=wireless pid=%d gen=1 since_ms=1 kind=in\n" % r.sleeper.pid)
write(os.path.join(r.src, "wireless.session"), "v=1 state=start gen=1 pid=%d ts_ms=1 reason=start\n" % r.sleeper.pid)
ok(r.wait(lambda: has_bridge(r)), "Wi-Fi only after a cold start: bridge started")
r.stop()
r = Rig()
ring = r.env["PMCP_MOST_RING"]
write(ring, "not a ring, someone else's file")
r.start()
ok(r.wait(lambda: "supervisor-started" in r.log()), "started")
time.sleep(0.1)
ok(open(ring).read() == "not a ring, someone else's file" and "ring-created" not in r.log(), "existing ring file untouched")
r.stop()

print("== --boot from the lsd.sh block (A247)")
def boot_rig(active):
    r = Rig()
    os.makedirs(os.path.join(r.app, "bridge"))
    copy = os.path.join(r.app, "bridge", "pmcp-most-sup")
    shutil.copy2(SUP, copy)
    act = os.path.join(r.app, "carplay-cluster-supervisor")
    if active == "pmcp":
        shutil.copy2(SUP, act)
    elif active == "other":
        script(act, 'echo "other supervisor $*" >> "%s"\nexit 0\n' % r.ev)
    return r, copy
r, copy = boot_rig("pmcp")
b = subprocess.Popen([copy, "--boot"], env=r.env)
ok(r.wait(lambda: "supervisor-started" in r.log()), "--boot, active is pmcp: supervisor running")
pid = open(os.path.join(r.ram, "pmcp-most", "sup.pid")).read().strip()
ok(pid == str(b.pid) and b.poll() is None, "--boot execs in place (same pid, keeps running)")
ps = subprocess.run(["ps", "-o", "command=", "-p", pid], capture_output=True, text=True).stdout.strip()
ok(ps == os.path.join(r.app, "carplay-cluster-supervisor"), "runs under the active path (pmcp.sh slay -f finds it)")
ok(os.path.exists(r.env["PMCP_MOST_RING"]), "--boot: ring made")
second = subprocess.run([os.path.join(r.app, "carplay-cluster-supervisor")], env=r.env, timeout=5)
ok(second.returncode == 0 and "already-running" in r.log(), "the wrapper's later start: already-running")
r.p = b
r.stop()
for kind in ("other", "missing"):
    r, copy = boot_rig(kind)
    res = subprocess.run([copy, "--boot"], env=r.env, timeout=5)
    ok(res.returncode == 0 and "boot-skip active-supervisor-not-pmcp" in r.log(), "--boot, active %s: skip" % kind)
    ok(not os.path.exists(os.path.join(r.ram, "pmcp-most", "sup.pid")) and not os.path.exists(r.env["PMCP_MOST_RING"])
       and not any(e.startswith("other supervisor") for e in r.events()), "--boot, active %s: nothing started" % kind)
    r.stop()
r, copy = boot_rig("pmcp")
write(os.path.join(r.app, "stock_first", "DISABLED"), "")
res = subprocess.run([copy, "--boot"], env=r.env, timeout=5)
ok(res.returncode == 0 and "boot-skip disabled" in r.log() and "supervisor-started" not in r.log(), "--boot with DISABLED: skip")
r.stop()

print("SUPERVISOR TESTS: %d ok, %d failed" % (OK, BAD))
sys.exit(1 if BAD else 0)
