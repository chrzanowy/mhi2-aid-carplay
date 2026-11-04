# SPDX-License-Identifier: GPL-3.0-or-later
"""Route guidance for Android Auto too (experimental branch, package rg-aa, audit A-AA22; after apply_lanes.py, uturn.py, asf.py and maneuvers.py, on
the staged copies only).

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
CarPlay (connection 2) behaves exactly as before. Each replacement must match exactly once.

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
        check(LiveBridge.destinationDistance(total) && !total.validityInformation.distanceToDestinationValid
            && LiveBridge.destinationTime(time) && !time.validityInformation.timeInfo_MinuteIsValid,
            "CarPlay unchanged: missing metrics still published as invalid");
        TestLive.connection = 0;
        check(LiveBridge.factoryContext() == 1, "no phone: blocked as before");
%ASF%        TestLive.connection = 2;
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
        check(ArrowProgress.remaining(f, f.laneAt + 4999) == 50 && ArrowProgress.remaining(f, f.laneAt + 5000) == -1,
            "bar ends 5 s after the last route update, not after the manoeuvre change");
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
(lane_dir / "TestAa.java").write_text(TEST.replace("%ASF%", ASF_TEST if ASF else ""))
print("aa.py: LiveBridge patched, TestAa written in %s" % lane_dir)
