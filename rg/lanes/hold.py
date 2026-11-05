# SPDX-License-Identifier: GPL-3.0-or-later
"""Quiet-route hold for Apple Maps (after asf.py and slhook.py; build modes *-asf*).

    hold.py STAGED_LANE_DIR LANES_DIR

Port of tomasz-twardzicki MU1367 v1.4.4 (tag MU1367-v1.4.4, commit d20527f; same Java as v1.4.4-e 319e6c8) onto our
MU1427-based sources. Only the Java side: our reader (pmcp-r1, rg/reader) is unchanged. It writes STALE after 5 s
without a new phone message and INVALIDATE only when its worker hangs, so no reader change is needed.

Why: Apple Maps sends sparse deltas and does not resend maneuvers it already sent. The old code reset the route on the
reader's 5 s STALE record and dropped output 5 s after the last message, so after a quiet stretch the arrow came back
as a placeholder and lanes were missing until the next maneuver. Google Maps resends about once a second and never hit
this.

What changes:
- STALE no longer clears the model; an active route is held for up to LiveModel.HOLD_MS (180 s) of total phone
  silence. The 1.5 s reader heartbeat, session, explicit route end, INVALIDATE and OEM navigation still clear at once.
- A message that fails field validation is rejected on its own instead of failing the whole 16-message window; an
  unreadable route update (0x5201) clears route state. Envelope, ordering and overlap faults still fail the snapshot.
- guidance-evidence.txt (GuidanceEvidence.java, Tomasz's file unchanged, <= 4 KiB) next to adapter-status.txt: message
  counts, route states, maneuver types, gaps, rejected message shapes (keys and sizes only) and the phone app name.
Tests: Tomasz's v1.4.4 test changes on our copies of TestLive/TestArrow/TestRoad/TestRecovery, plus his
TestQuietHold.java (one assertion on a status field our LiveBridge does not have is dropped).
"""
import pathlib
import shutil
import sys

lane_dir, src = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])


def patch(name, pairs):
    p = lane_dir / name
    s = p.read_text()
    for old, new, what, count in pairs:
        if s.count(old) != count:
            sys.exit("hold.py: %s: %s: expected text found %d times, want %d" % (name, what, s.count(old), count))
        s = s.replace(old, new)
    p.write_text(s)


for name in ("GuidanceEvidence", "TestQuietHold", "TestHoldPmcp"):
    shutil.copy2(src / (name + ".java"), lane_dir / (name + ".java"))

H = "LiveModel.HOLD_MS"
patch("LiveModel.java", [
    ("    static final int SNAP = 33088;\n",
     "    static final int SNAP = 33088;\n"
     "    /* Phone apps send deltas: Apple Maps can stay silent while stopped or\n"
     "     * between distance steps. An active route is held while the producer\n"
     "     * heartbeat, session and route state remain valid, bounded by HOLD_MS of\n"
     "     * total message silence. Explicit state/session changes still clear it. */\n"
     "    static final long HOLD_MS = 180000;\n", "HOLD_MS", 1),
    ("    static Message decode(int id, byte[] b, int p, int length) throws IOException {\n        int faultField=-1;\n",
     "    // Bounded structural shape of a rejected message: keys and sizes only,\n"
     "    // plus component/state values. Never text content.\n"
     "    static String shape(byte[] b, int p, int length) {\n"
     "        StringBuffer s=new StringBuffer(); int end=p+length, count=0;\n"
     "        while (p<end && count<24) {\n"
     "            if (end-p<4) { s.append(count>0?\",\":\"\").append(\"tail:\").append(end-p); break; }\n"
     "            int n=be16(b,p), key=be16(b,p+2);\n"
     "            if (count++>0) s.append(',');\n"
     "            s.append(key).append(':').append(n-4);\n"
     "            if (n<4 || p+n>end) { s.append(\"!\"); break; }\n"
     "            if ((key==0 || key==1) && n-4<=8) { s.append('='); for (int i=p+4;i<p+n;i++) { int v=b[i]&255; s.append(Character.forDigit(v>>4,16)).append(Character.forDigit(v&15,16)); } }\n"
     "            p+=n;\n"
     "        }\n"
     "        if (length==0) s.append(\"empty\");\n"
     "        return s.toString();\n"
     "    }\n"
     "    static Message decode(int id, byte[] b, int p, int length) throws IOException {\n        int faultField=-1, start=p;\n",
     "shape()", 1),
    ("        }catch(java.io.IOException e){throw new FeedRecovery.Fault(id,faultField);}\n",
     "        }catch(java.io.IOException e){FeedRecovery.Fault f=new FeedRecovery.Fault(id,faultField);f.shape=shape(b,start,length);throw f;}\n",
     "fault shape", 1),
    ("        Message[] messages=new Message[(int)count]; byte[][] bytes=new byte[(int)count][];\n",
     "        Message[] messages=new Message[(int)count]; byte[][] bytes=new byte[(int)count][];\n"
     "        FeedRecovery.Fault[] faults=new FeedRecovery.Fault[(int)count];\n", "faults array", 1),
    ("            try {messages[i]=decode(id,b,pos+16,length);}catch(FeedRecovery.Fault e){e.sequence=seq;throw e;} bytes[i]=copy(b,pos,16+length);\n",
     "            // A semantically invalid message is rejected alone; the envelope,\n"
     "            // ordering and overlap checks above/below still fail the snapshot.\n"
     "            try {messages[i]=decode(id,b,pos+16,length);}catch(FeedRecovery.Fault e){e.sequence=seq;faults[i]=e;} bytes[i]=copy(b,pos,16+length);\n",
     "message-scoped rejection", 1),
    ("            if (seq>seen) {\n                String passed=passedRoad(messages[i]);\n                boolean accepted=apply(messages[i]);\n",
     "            if (seq>seen) {\n"
     "                GuidanceEvidence.message(s*1000003L^ns*31L^session,seq,messages[i],faults[i],now);\n"
     "                if (messages[i]==null) {\n"
     "                    // An unreadable route update may have carried an end or\n"
     "                    // state change: drop route state rather than guess.\n"
     "                    if (faults[i].message==0x5201) invalidate();\n"
     "                    continue;\n"
     "                }\n"
     "                String passed=passedRoad(messages[i]);\n"
     "                boolean accepted=apply(messages[i]);\n"
     "                if (!accepted) GuidanceEvidence.notApplied();\n", "apply loop", 1),
])
patch("FeedRecovery.java", [
    ("        final int message,field; long sequence=-1;\n",
     "        final int message,field; long sequence=-1;\n        String shape=\"\";\n", "Fault.shape", 1),
    ("now-last.changed<5000\n", "now-last.changed<%s\n" % H, "feed hold", 1),
])
patch("MailboxReader.java", [
    ("            model.invalidate(); frame=model.frame();\n",
     "            // STALE only reports 5 s without a new phone message. Silence is\n"
     "            // bounded by HOLD_MS in the model and bridge, not a reset.\n"
     "            if (kind==3) GuidanceEvidence.quiet(now); else model.invalidate();\n"
     "            frame=model.frame();\n", "STALE keeps the model", 1),
])
patch("JournalReader.java", [("            if (kind!=4) model.invalidate();\n",
                              "            if (kind!=4 && kind!=3) model.invalidate();\n", "journal STALE", 1)])
patch("LiveBridge.java", [
    ("time-selected.changed>=5000\n", "time-selected.changed>=%s\n" % H, "current() hold", 1),
    ("time-frame.changed<5000\n", "time-frame.changed<%s\n" % H, "tick() hold", 1),
    ("time-f.laneAt<5000?f:null;", "time-f.laneAt<%s?f:null;" % H, "lane hold", 1),
    ("            if (!temp.renameTo(target)) failures++;\n        } catch (IOException e) { failures++; }\n    }\n    public void run() {\n",
     "            if (!temp.renameTo(target)) failures++;\n            GuidanceEvidence.write(ROOT);\n"
     "        } catch (IOException e) { failures++; }\n    }\n    public void run() {\n", "evidence file", 1),
])
patch("ArrowProgress.java", [("    static final long ROUTE_AGE=5000;\n", "    static final long ROUTE_AGE=%s;\n" % H, "bar hold", 1)])
patch("RoadName.java", [("    static final long MAX_AGE=5000;\n", "    static final long MAX_AGE=%s;\n" % H, "road hold", 1)])

# ---- tests: Tomasz's v1.4.4 changes (MU1367/integration/tests/java, 24f84f4..319e6c8) ---------------------------
patch("TestLive.java", [
    ("        b=bridge(); b.tick(clock); b.incoming=new LiveModel.Frame(true,13,64,20,2,clock-5000,1); clock+=250; b.tick(clock); check(!b.owned,\"semantic stale deadline\");\n",
     "        b=bridge(); b.tick(clock); b.incoming=new LiveModel.Frame(true,13,64,20,2,clock-5000,1); clock+=250; b.tick(clock); check(b.owned,\"quiet active route held past 5 s\");\n"
     "        b=bridge(); b.tick(clock); b.incoming=new LiveModel.Frame(true,13,64,20,2,clock-LiveModel.HOLD_MS,1); clock+=250; b.tick(clock); check(!b.owned,\"semantic hold deadline\");\n",
     "bridge hold", 1),
    ("at-f.changed<5000;", "at-f.changed<LiveModel.HOLD_MS;", "replay hold", 1),
])
patch("TestArrow.java", [
    ("        check(ArrowProgress.remaining(frame(1,13,20,1000),6000)==-1,\"stale route hides\");\n",
     "        check(ArrowProgress.remaining(frame(1,13,20,1000),6000)==10,\"quiet route keeps its bar\");\n"
     "        check(ArrowProgress.remaining(frame(1,13,20,1000),1000+LiveModel.HOLD_MS)==-1,\"stale route hides\");\n", "bar", 1),
    ("        TestLive.clock=5999;b=TestLive.bridge();", "        TestLive.clock=1000+LiveModel.HOLD_MS-1;b=TestLive.bridge();", "bar deadline-1", 1),
    ("int sent=TestLive.sent.size();TestLive.clock=6000;", "int sent=TestLive.sent.size();TestLive.clock=1000+LiveModel.HOLD_MS;", "bar deadline", 1),
])
patch("TestRoad.java", [
    ("        check(RoadName.current(f,at+4999).equals(\"Current Road\"),\"road valid before deadline\");\n"
     "        check(RoadName.current(f,at+5000).equals(\"\"),\"road expires at deadline\");\n",
     "        check(RoadName.current(f,at+5000).equals(\"Current Road\"),\"road held through a quiet period\");\n"
     "        check(RoadName.current(f,at+LiveModel.HOLD_MS-1).equals(\"Current Road\"),\"road valid before deadline\");\n"
     "        check(RoadName.current(f,at+LiveModel.HOLD_MS).equals(\"\"),\"road expires at deadline\");\n", "road", 1),
    ("long oldRoute=f.laneAt;TestLive.clock=oldRoute+5000;", "long oldRoute=f.laneAt;TestLive.clock=oldRoute+LiveModel.HOLD_MS;", "road bridge", 1),
])
patch("TestRecovery.java", [
    ("f.poll(4400);check(f.error==1&&!f.live,\"semantic field width rejected\");",
     "f.poll(4400);check(f.error==0&&!f.live&&f.errors==1,\"invalid route message rejected alone and clears route\");", "reject", 1),
    ("  check(f.errors<13,\"bad input retry bounded to one per second\");check(LiveModel.equal(saved,read(first)),\"first failure never overwritten\");\n"
     "  Wire next=new Wire(root);next.nonce=2;next.route(0);next.publish();long time=f.retryAt;f.poll(time);check(!f.live,\"new producer baseline\");next.route(1);next.publish();f.poll(time+100);check(f.live&&f.recoveries==2,\"new source recovers\");\n",
     "  check(f.errors==1,\"rejected message is not a feed error\");check(LiveModel.equal(saved,read(first)),\"first failure never overwritten\");\n"
     "  w.route(1);w.publish();f.poll(14600);check(f.live&&f.error==0,\"valid message after rejected one resumes in the same window\");\n"
     "  Wire next=new Wire(root);next.nonce=2;next.route(0);next.publish();long time=15000;f.poll(time);check(!f.live,\"new producer baseline\");next.route(1);next.publish();f.poll(time+100);check(f.live&&f.recoveries==1,\"new source starts without an error latch\");\n",
     "recovery", 1),
    ("  Wire w=new Wire(root);w.add(0x5201,TestLanes.join(TestLanes.tlv(0,TestLanes.u16(16)),TestLanes.tlv(1,new byte[]{1,0})));w.publish();FeedRecovery f=new FeedRecovery(root.toString());f.poll(1000);\n"
     "  String s=new String(read(new File(root,\"failure-first.txt\")),\"US-ASCII\");check(s.indexOf(\"message=20993 field=1\")>=0&&s.indexOf(\"sequence=1\")>=0,\"numeric offending message/field/sequence retained\");\n"
     "  check(s.indexOf(\"serial=1 kind=1 nonce=1\")>=0,\"offending envelope retained\");\n",
     "  GuidanceEvidence.session=-1;\n"
     "  Wire w=new Wire(root);w.add(0x5201,TestLanes.join(TestLanes.tlv(0,TestLanes.u16(16)),TestLanes.tlv(1,new byte[]{1,0})));w.publish();FeedRecovery f=new FeedRecovery(root.toString());f.poll(1000);\n"
     "  check(!new File(root,\"failure-first.txt\").exists()&&f.error==0&&!f.live,\"semantic rejection is message-scoped, not a feed failure\");\n"
     "  String s=GuidanceEvidence.lastRejected;check(s.indexOf(\"seq=1 id=5201 field=1\")>=0&&s.indexOf(\"shape=0:2=0010,1:2=0100\")>=0,\"numeric offending message/field/sequence and shape retained\");\n"
     "  write(new File(root,\"latest.bin\"),new byte[]{1,2,3});f.poll(1100);\n"
     "  s=new String(read(new File(root,\"failure-first.txt\")),\"US-ASCII\");check(s.indexOf(\"serial=-1 kind=-1\")>=0,\"envelope faults still recorded\");\n",
     "first fault", 1),
])
patch("TestLanes.java", [("  TestLive.clock+=5001;b.lastTick=TestLive.clock;b.journalAt=TestLive.clock;\n",
                           "  TestLive.clock+=LiveModel.HOLD_MS+1;b.lastTick=TestLive.clock;b.journalAt=TestLive.clock;\n", "lane deadline", 1)])
# our LiveBridge has no ownership history fields (Tomasz's MU1367 diagnostics); the release itself is still checked
patch("TestQuietHold.java", [("check(!b.owned&&b.lastReleaseReason!=3,\"bridge releases at the silence bound\");",
                              "check(!b.owned,\"bridge releases at the silence bound\");", "release reason", 1)])
print("hold.py: quiet-route hold (HOLD_MS 180 s, message-scoped rejection, guidance evidence) staged in %s" % lane_dir)
