# SPDX-License-Identifier: GPL-3.0-or-later
"""Route guidance for Android Auto too (package rg since v1.5.0, rg/build.sh lanes-uturn-asf-m-aa; v1.4.x experimental
cards shipped it as the separate package rg-aa; audit A-AA22). Runs after apply_lanes.py, uturn.py, asf.py and
maneuvers.py, on the staged copies only.

Tomasz's LiveBridge publishes only while the phone connection is CarPlay (getSmarphoneIntegrationActiveConnectionType()
== 2) and reads /ramdisk/carplay-route-guidance. The pmcp AA gamma hook (aa/hook/pmcp_rg.c) writes the same RGM1/RGI1
mailbox from Google Maps' manoeuvres to its own directory /ramdisk/pmcp-aa-rg, with no remaining distance / time.

    aa.py STAGED_LANE_DIR   -> patches STAGED_LANE_DIR/LiveBridge.java, writes TestAa.java there

Changes:
  - factoryContext(): connection 3 (Android Auto) is accepted like 2 (CarPlay); the last value is kept in `phone`;
  - the reader thread reads root(phone): /ramdisk/pmcp-aa-rg for AA, the CarPlay directory otherwise; when it changes,
    a new MailboxReader, the frame dropped, a previous read error cleared (one source's bad file does not block the other);
    adapter-status.txt goes to the directory being read;
  - with AA, destination distance / time the mailbox does not carry are left to the factory path (the helper returns
    false), instead of being published as invalid: the AA picture shows them.
  - with AA the quiet-route hold (hold.py's LiveModel.HOLD_MS, 180 s) is AA_HOLD_MS, 10 s: the hook repeats the route
    every 2.5 s while Google Maps navigates, so a VW arrow / bar / road name ends 10 s after Maps goes quiet instead of
    staying up to the hook's 60 s end (LiveBridge tick/current/lanes, ArrowProgress, RoadName, FeedRecovery on the AA
    directory). CarPlay keeps 180 s;
  - tick() and current() publish an active frame only while the reader reads the directory of the current connection
    (rootFor(phone) equals root): no frame of the previous source in the window between factoryContext() and switchRoot().
CarPlay (connection 2) behaves exactly as before: with connection 2 or no phone the reader stays on the CarPlay directory,
nothing under /ramdisk/pmcp-aa-rg is read, and no thread is added (the existing reader thread switches directories).
Each replacement must match exactly once.

After asf.py (package rgluasfa) the reader loop is Tomasz's v1.4.3 FeedRecovery loop: the source switch is switchRoot(),
which starts a fresh FeedRecovery on the other directory (frame dropped, error / fatal latch / retry wait cleared), and
TestAa gets the switch checks and an AA bargraph check (same manoeuvre, falling metres for more than 5 s).
"""
import pathlib
import sys

lane_dir = pathlib.Path(sys.argv[1])


def patch(text, old, new, what):
    if text.count(old) != 1:
        sys.exit("aa.py: %s: expected text found %d times" % (what, text.count(old)))
    return text.replace(old, new)


lb = lane_dir / "LiveBridge.java"
s = lb.read_text()
s = patch(s, '''    static final LiveBridge INSTANCE=new LiveBridge();''',
          '''    static final LiveBridge INSTANCE=new LiveBridge();
    // pmcp rglua: Android Auto (connection 3) reads the AA gamma hook's mailbox
    static final String AA_ROOT="/ramdisk/pmcp-aa-rg";
    static volatile int phone=-1;
    volatile String root=ROOT;
    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }
    // Java 1.2 / CDC: no StringBuilder (PatchLive rejects it), so paths from a variable directory are built here
    static String at(String dir, String name) { return new StringBuffer(dir).append(name).toString(); }''', "fields")
s = patch(s, '''        if (connection!=2) return 1;''',
          '''        phone=connection;
        if (connection!=2 && connection!=3) return 1;''', "factoryContext")
s = patch(s, '''        boolean valid=f.active && f.remainingMeters>=0;
        int[] converted=convertDistance(valid?f.remainingMeters:0,true);''',
          '''        if (phone==3 && f.remainingMeters<0) return false;   // AA: not in the mailbox, factory path
        boolean valid=f.active && f.remainingMeters>=0;
        int[] converted=convertDistance(valid?f.remainingMeters:0,true);''', "destinationDistance")
s = patch(s, '''        if (INSTANCE.current()==null) return false;
        return true;''',
          '''        LiveModel.Frame f=INSTANCE.current();
        if (f==null || phone==3 && f.remainingMeters<0) return false;
        return true;''', "destinationValidity")
s = patch(s, '''        boolean valid=f.active && f.remainingSeconds>=0;
        int minutes=valid?(f.remainingSeconds+59)/60:0;''',
          '''        if (phone==3 && f.remainingSeconds<0) return false;  // AA: not in the mailbox, factory path
        boolean valid=f.active && f.remainingSeconds>=0;
        int minutes=valid?(f.remainingSeconds+59)/60:0;''', "destinationTime")
s = patch(s, '''            File target=new File(ROOT+"/adapter-status.txt"), temp=new File(ROOT+"/adapter-status.tmp");''',
          '''            File target=new File(at(root,"/adapter-status.txt")), temp=new File(at(root,"/adapter-status.tmp"));''', "status")
ASF = "FeedRecovery feed=new FeedRecovery(ROOT);productionFeed=feed;" in s
if ASF:
    # rgluasfa (after asf.py): the reader loop is FeedRecovery's (Tomasz v1.4.3); a source switch starts a fresh one
    s = patch(s, '''                long time=now();
                pollProduction(feed,time,new File(ROOT+"/disabled").exists());''',
              '''                long time=now();
                feed=switchRoot(feed);
                pollProduction(feed,time,new File(at(root,"/disabled")).exists());''', "runProduction (FeedRecovery)")
    s = patch(s, '''                    if(new File(ROOT).isDirectory())status(feed.reader.records,feed.error);''',
              '''                    if(new File(root).isDirectory())status(feed.reader.records,feed.error);''', "runProduction status (FeedRecovery)")
    s = patch(s, '''    long feedGeneration=-1;
''', '''    // pmcp rgluasfa: a source switch (CarPlay <-> AA) reads the other directory with a fresh FeedRecovery: frame
    // dropped; a read error, fatal latch or retry wait of the other source cleared
    FeedRecovery switchRoot(FeedRecovery feed) {
        String want=rootFor(phone);
        if (want.equals(root)) return feed;
        root=want; incoming=null; mode=0; journalAt=-1;
        return new FeedRecovery(want);
    }
    long feedGeneration=-1;
''', "switchRoot")
s = s if ASF else patch(s, '''        MailboxReader reader=new MailboxReader(ROOT+"/latest.bin");
        long written=-1, recordAt=-1; int error=0;
        runId="1"; runSerial++;
        for (;;) {
            try {
                long time=now();
                if (new File(ROOT+"/disabled").exists() || error!=0) { incoming=null; mode=0; }''',
          '''        MailboxReader reader=new MailboxReader(ROOT+"/latest.bin");
        long written=-1, recordAt=-1; int error=0;
        runId="1"; runSerial++;
        for (;;) {
            try {
                long time=now();
                String want=rootFor(phone);
                if (!want.equals(root)) {
                    root=want; reader=new MailboxReader(at(want,"/latest.bin"));
                    incoming=null; mode=0; recordAt=-1; error=0;
                }
                if (new File(at(root,"/disabled")).exists() || error!=0) { incoming=null; mode=0; }''', "runProduction")
s = s if ASF else patch(s, '''                    if (new File(ROOT).isDirectory()) status(reader.records,error);
                    written=time;''',
          '''                    if (new File(root).isDirectory()) status(reader.records,error);
                    written=time;''', "runProduction status")
lb.write_text(s)

TEST = '''/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host-only test of the rglua changes (aa.py) on the guarded factory classes, with TestLive's factory mocks. */
package com.cpmap.rgi;
import de.vw.mib.bap.mqbab2.generated.navsd.serializer.*;

public final class TestAa {
    static int checks;
    static void check(boolean ok, String m) { checks++; if (!ok) throw new AssertionError(m); }
    public static void main(String[] a) throws Exception {
        TestLive.installMocks();
        LiveBridge b = TestLive.bridge();
        TestLive.connection = 3;
        check(LiveBridge.factoryContext() == 0 && LiveBridge.phone == 3, "AA connection accepted");
        check(LiveBridge.rootFor(3).equals("/ramdisk/pmcp-aa-rg") && LiveBridge.rootFor(2).equals(LiveBridge.ROOT)
            && LiveBridge.rootFor(0).equals(LiveBridge.ROOT), "AA reads its own directory, CarPlay and the rest the CarPlay one");
        b.incoming = new LiveModel.Frame(true, 13, 64, 250, -1, -1, 1, TestLive.clock, 1); b.journalAt = TestLive.clock;
        TestLive.sent.clear(); b.tick(TestLive.clock);
        check(!b.owned && b.current() == null, "AA connection, reader still on the CarPlay directory: nothing published");
        b.root = LiveBridge.AA_ROOT; TestLive.clock += 250; b.journalAt = TestLive.clock; b.tick(TestLive.clock);
        check(b.owned, "AA frame published");
        ManeuverDescriptor_Status d = new ManeuverDescriptor_Status();
        check(LiveBridge.descriptor(d) && d.maneuver_1.mainElement == 13 && d.maneuver_1.direction == 64, "AA arrow");
        DistanceToNextManeuver_Status n = new DistanceToNextManeuver_Status();
        check(LiveBridge.distance(n) && n.validityInformation.distanceToNextManeuverValid, "AA distance to the manoeuvre");
        DistanceToDestination_Status total = new DistanceToDestination_Status();
        TimeToDestination_Status time = new TimeToDestination_Status();
        check(!LiveBridge.destinationDistance(total) && !LiveBridge.destinationValidity(total) && !LiveBridge.destinationTime(time),
            "AA without remaining distance / time: factory path for destination");
        TestLive.connection = 2; LiveBridge.factoryContext();
        check(b.current() == null, "CarPlay connection, reader still on the AA directory: the AA frame is not published");
        b.root = LiveBridge.ROOT; TestLive.clock += 250; b.journalAt = TestLive.clock; b.tick(TestLive.clock);
        check(LiveBridge.destinationDistance(total) && !total.validityInformation.distanceToDestinationValid
            && LiveBridge.destinationTime(time) && !time.validityInformation.timeInfo_MinuteIsValid,
            "CarPlay unchanged: missing metrics still published as invalid");
        TestLive.connection = 0;
        check(LiveBridge.factoryContext() == 1, "no phone: blocked as before");
%ASF%%HOLD%        TestLive.connection = 2;
        System.out.println("{\\"aa_assertions\\":" + checks + "}");
    }
}
'''
ASF_TEST = '''        // rgluasfa: (a) a source switch drops the frame and clears the other source's error in the FeedRecovery path
        FeedRecovery cp = new FeedRecovery(LiveBridge.ROOT); cp.error = 1; cp.fatal = true; cp.retryAt = 99999;
        b.root = LiveBridge.ROOT; LiveBridge.phone = 3; b.mode = 2; b.journalAt = TestLive.clock;
        b.incoming = new LiveModel.Frame(true, 13, 64, 250, -1, -1, 1, TestLive.clock, 1);
        FeedRecovery aa = b.switchRoot(cp);
        check(aa != cp && aa.root.equals("/ramdisk/pmcp-aa-rg") && aa.error == 0 && !aa.fatal && aa.retryAt < 0
            && b.incoming == null && b.mode == 0 && b.journalAt == -1, "CP -> AA: new feed, frame dropped, error cleared");
        check(b.switchRoot(aa) == aa, "same source keeps its feed");
        aa.error = 1; LiveBridge.phone = 2;
        FeedRecovery back = b.switchRoot(aa);
        check(back != aa && back.root.equals(LiveBridge.ROOT) && back.error == 0, "AA -> CP: new feed, error cleared");
        // (b) AA bar: same manoeuvre, falling metres for more than 5 s, 0x5201 every 2.5 s -> the bar stays on
        TestLanes.Feed feed = new TestLanes.Feed();
        feed.add(0x5201, TestArrow.route(10)); feed.read();
        feed.add(0x5202, TestArrow.maneuver(10, 1)); feed.read();
        long start = feed.now; LiveModel.Frame f = null;
        for (int k = 0; k <= 4; k++) {
            feed.now = start + k * 2500L;
            feed.add(0x5201, TestLanes.join(TestArrow.route(10), TestLanes.tlv(10, new byte[]{0, 0, 0, (byte)(180 - k * 20)})));
            f = feed.read();
            check(ArrowProgress.remaining(f, feed.now + 2400) == (180 - k * 20) / 2, "AA bar on while metres fall");
        }
        check(feed.now - start > 5000, "same manoeuvre for longer than 5 s");
        check(ArrowProgress.remaining(f, f.laneAt + ArrowProgress.ROUTE_AGE - 1) == 50
            && ArrowProgress.remaining(f, f.laneAt + ArrowProgress.ROUTE_AGE) == -1,
            "bar ends ROUTE_AGE after the last route update (5 s; 180 s with the quiet-route hold), not after the manoeuvre change");
        // (c) CarPlay (connection 2) and no phone (0): the reader stays on the CarPlay directory across ticks; no AA feed
        // (reader of /ramdisk/pmcp-aa-rg) is created
        int[] others = {2, 0};
        for (int i = 0; i < others.length; i++) {
            TestLive.connection = others[i]; LiveBridge.factoryContext();
            check(LiveBridge.phone == others[i], "connection recorded");
            FeedRecovery own = new FeedRecovery(LiveBridge.ROOT);
            b.root = LiveBridge.ROOT;
            for (int k = 0; k < 5; k++) {
                TestLive.clock += 1000; b.tick(TestLive.clock);
                FeedRecovery next = b.switchRoot(own);
                check(next == own && b.root == LiveBridge.ROOT && own.root.equals(LiveBridge.ROOT),
                    "connection " + others[i] + ": root stays ROOT, no AA reader");
            }
        }
'''
# rgluasfma only (letter m staged before aa.py): the status line names the connection type and the directory read, so the
# "connection 3 = Android Auto" assumption can be checked from the logs (AA review 2026-11-03, m3). rglua/rgluasfa unchanged.
MAN = "static int[] mapStrict(" in (lane_dir / "LiveModel.java").read_text()
if MAN:
    p = lane_dir / "LiveBridge.java"
    s = p.read_text()
    s = patch(s, """.append(" error=").append(error).append('\\n');""",
              """.append(" error=").append(error).append(" phone=").append(phone).append(" root=").append(root).append('\\n');""",
              "status phone/root")
    p.write_text(s)
HOLD_TEST = '''        // (d) quiet route: Android Auto (connection 3) ends 10 s after the last route change (arrow and bar); CarPlay (2)
        // keeps 180 s
        int[] conns = {3, 2}; long[] holds = {10000, 180000};
        for (int i = 0; i < conns.length; i++) {
            TestLive.connection = conns[i]; LiveBridge.factoryContext(); TestLive.clock += 5000;
            check(LiveBridge.hold() == holds[i] && LiveBridge.holdFor(LiveBridge.rootFor(conns[i])) == holds[i], "hold length");
            long t0 = TestLive.clock;
            LiveBridge q = TestLive.bridge(); q.root = LiveBridge.rootFor(conns[i]);
            LiveModel.Frame g = new LiveModel.Frame(true, 13, 64, 100, -1, -1, 5, t0, 1, LaneData.EMPTY, t0, "Road", t0, 1);
            q.incoming = g; q.journalAt = t0; q.tick(t0);
            check(q.owned && TestArrow.output().bargraphInfo.bargraphOnOff == 1, "connection " + conns[i] + ": arrow and bar on");
            for (long t = t0 + 1000; t < t0 + holds[i] - 1; t += 1000) { TestLive.clock = t; q.journalAt = t; q.tick(t); }
            long last = t0 + holds[i] - 1; TestLive.clock = last; q.journalAt = last; q.tick(last);
            check(q.owned && ArrowProgress.remaining(g, last) == 50 && RoadName.current(g, last).equals("Road")
                && TestArrow.output().bargraphInfo.bargraphOnOff == 1, "connection " + conns[i] + ": quiet route held until the hold ends");
            TestLive.clock = t0 + holds[i]; q.journalAt = TestLive.clock; q.tick(TestLive.clock);
            check(!q.owned && q.current() != null && !q.current().active && ArrowProgress.remaining(g, TestLive.clock) == -1
                && RoadName.current(g, TestLive.clock).equals(""), "connection " + conns[i] + ": arrow and bar end at the hold");
        }
'''
# Android Auto: short quiet-route hold (review 2026-11-07). hold.py holds a quiet route for LiveModel.HOLD_MS (180 s, for
# Apple Maps' sparse deltas). The AA hook repeats the route every 2.5 s while Google Maps navigates and keeps its 0.5 s
# heartbeat while paused, so with 180 s a stopped Maps (crash, no 0x8003 end) left the VW arrow and bar up until the
# hook's own 60 s end. With connection 3 (the AA directory for the feed) the hold is AA_HOLD_MS, 10 s; CarPlay keeps 180 s.
HOLD = "static final long HOLD_MS" in (lane_dir / "LiveModel.java").read_text()
if HOLD:
    s = lb.read_text()
    s = patch(s, '''    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }''',
              '''    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }
    // pmcp: quiet-route hold, 10 s for Android Auto, 180 s (hold.py) for CarPlay
    static final long AA_HOLD_MS=10000;
    static long hold() { return phone==3?AA_HOLD_MS:LiveModel.HOLD_MS; }
    static long holdFor(String dir) { return AA_ROOT.equals(dir)?AA_HOLD_MS:LiveModel.HOLD_MS; }''', "hold()")
    for old, new in (("time-selected.changed>=LiveModel.HOLD_MS", "time-selected.changed>=hold()"),
                     ("time-frame.changed<LiveModel.HOLD_MS", "time-frame.changed<hold()"),
                     ("time-f.laneAt<LiveModel.HOLD_MS?f:null;", "time-f.laneAt<hold()?f:null;")):
        s = patch(s, old, new, "LiveBridge hold " + old)
    if s.count("LiveModel.HOLD_MS") != 2:   # hold() and holdFor() only
        sys.exit("aa.py: LiveBridge: LiveModel.HOLD_MS left %d times, want 2" % s.count("LiveModel.HOLD_MS"))
    lb.write_text(s)
    for name, old, new in (
            ("ArrowProgress.java", "now-f.laneAt>=ROUTE_AGE)return -1;", "now-f.laneAt>=LiveBridge.hold())return -1;"),
            ("RoadName.java", "time-f.laneAt<MAX_AGE", "time-f.laneAt<LiveBridge.hold()"),
            ("FeedRecovery.java", "now-last.changed<LiveModel.HOLD_MS", "now-last.changed<LiveBridge.holdFor(root)")):
        q = lane_dir / name
        q.write_text(patch(q.read_text(), old, new, name + " hold"))

# A source switch: factoryContext() (HMI thread) records the new connection before switchRoot() (reader thread) has
# changed directories (up to ~100 ms). In that window the previous source's active frame must not go out.
s = lb.read_text()
s = patch(s, '''        boolean take=mode==2 && c==0 && lease && fresh && core;''',
          '''        boolean take=mode==2 && c==0 && lease && fresh && core && rootFor(phone).equals(root);''', "tick() root")
s = patch(s, '''selected.active && (mode!=2 ||''', '''selected.active && (!rootFor(phone).equals(root) || mode!=2 ||''',
          "current() root")
lb.write_text(s)
(lane_dir / "TestAa.java").write_text(TEST.replace("%ASF%", ASF_TEST if ASF else "").replace("%HOLD%", HOLD_TEST if HOLD else ""))
print("aa.py: LiveBridge patched, TestAa written in %s" % lane_dir)
