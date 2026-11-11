# SPDX-License-Identifier: GPL-3.0-or-later
"""CarPlay guidance fixes of tomasz-twardzicki MU1367 v1.4.5 and v1.4.6 (rg/build.sh mode lanes-uturn-asf-m-aa-r, after
aa.py, on the staged copies only).

    v146.py STAGED_LANE_DIR LANES_DIR

Source: upstream/tomasz, tags MU1367-v1.4.5 (59cee2e, the Java of v1.4.5-e 6610cbb) and MU1367-v1.4.6 (9ff2f1b, the
Java of v1.4.6-e d680311), MU1367/integration/src/guidance. Our sources are his v1.4.4 LiveModel (hold.py) plus our edits,
so his v1.4.5/v1.4.6 hunks apply as counted text replacements. GuidanceEvidence.java and the tests TestReroute,
TestSourceName, TestUturnSide, TestPlaceholder and TestQuietQnx are his files, copied unchanged into rg/lanes/v146/ and
pinned in build.sh; the few test lines our edits change on purpose are patched here, on the staged copies.

1. Reroute (v1.4.5): a reroute arrives as route states 1,5,0,3,1 within about 0.5 s, then the new list starts at a
   start-route maneuver reporting 0 m. That was taken as a new trip (counters, bar, road and arrival lost). Now it is one
   episode: the factory CALC_ROUTE symbol (main 9) is shown and distance, bar, road and arrival keep their values until
   the phone reports a real distance again; at most 20 s (RECOVER_MS) or 5 s of phone silence (the reader's STALE
   record, model.quiet()). A stop inside a reroute ends guidance 1.5 s later (STOP_GRACE_MS) or at that silence. A route
   end, new destination, another app, disconnect and OEM navigation still clear at once.
2. Placeholder arrow (v1.4.5): an active route without any maneuver yet shows the straight DIRECTION_TO_DESTINATION
   symbol (main 2) without a distance. pmcp: only when no maneuver is known at all (frame maneuverType < 0) and not for
   Android Auto. A known maneuver that the strict map and our fallbacks (maneuvers.py) leave empty stays empty
   (highway change 51, roundabout exits without angle: no guessing), and the start of route keeps our straight turn
   arrow (maneuvers.py), which also carries the distance.
3. U-turn side (v1.4.6): a lane at exactly +-180 degrees carries no side; it stays the left U-turn lane (114, uturn.py)
   unless the phone's driving side says left-hand traffic, then 146. The main arrow at exactly +-180 follows the driving
   side when it is known (right-hand traffic: left U-turn). pmcp: not for Android Auto (LiveModel.signedUturns, set in
   factoryContext for connection 3): the AA hook (aa/hook/pmcp_rg.c) encodes the U-turn direction in the sign of 180
   and always sends side 0, so its +180 stays the right U-turn.
4. Apple Maps names (v1.4.6): names containing the word "Apple" are the same app ("Apple Maps" / "Mapy Apple"), so a
   name flip no longer clears the maneuvers and lanes Apple Maps does not resend. guidance-evidence.txt gains
   route_clears source=/destination= and a bounded source_flips log (his GuidanceEvidence.java, no text).
Each replacement must match exactly the given number of times.
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
            sys.exit("v146.py: %s: %s: expected text found %d times, want %d" % (name, what, s.count(old), count))
        s = s.replace(old, new)
    p.write_text(s)


for name in ("GuidanceEvidence", "TestReroute", "TestSourceName", "TestUturnSide", "TestPlaceholder", "TestQuietQnx"):
    shutil.copy2(src / "v146" / (name + ".java"), lane_dir / (name + ".java"))

# ---- LiveModel: reroute episode, driving side, Apple names (his v1.4.4 -> v1.4.6 hunks) ----
patch("LiveModel.java", [
    ("    static final long HOLD_MS = 180000;\n",
     "    static final long HOLD_MS = 180000;\n"
     "    /* A captured reroute is 1,5,0,3,1 within about 0.5 s. The list then restarts\n"
     "     * at a start-route maneuver reporting 0 m for up to 15 s. The whole episode\n"
     "     * is one route: it shows CALC_ROUTE and keeps the last counters until the\n"
     "     * phone reports a real distance again. (tomasz-twardzicki MU1367 v1.4.5) */\n"
     "    static final int MAIN_RECALCULATING = 9;\n"
     "    static final long STOP_GRACE_MS = 1500, RECOVER_MS = 20000;\n"
     "    // pmcp: Android Auto (connection 3, set in LiveBridge.factoryContext): the AA hook signs its U-turn angle\n"
     "    // (-180 left, +180 right) and always sends side 0, so +-180 keeps its sign there.\n"
     "    static volatile boolean signedUturns;\n", "constants", 1),
    ("    private byte[][] retained=new byte[16][];\n",
     "    private byte[][] retained=new byte[16][];\n"
     "    private boolean rerouting;\n"
     "    // Driving side of the last maneuver that carried one: 0 right-hand, 1 left-hand traffic.\n"
     "    private int drivingSide=-1;\n"
     "    private int reroutingType=-1;\n"
     "    private long clock, stopAt=-1, recoverAt=-1;\n", "fields", 1),
    ("    static boolean equal(byte[] a, byte[] b) {\n",
     "    /* A source name is display text, not an identity. Apple Maps alternates\n"
     "     * \"Apple Maps\" and a localized form (\"Mapy Apple\") within one session. Taken\n"
     "     * as an app switch, that drops maneuver records the phone may not resend,\n"
     "     * so guidance stays lost until it reaches a record it has not sent yet. */\n"
     "    static boolean sameSource(byte[] a, byte[] b) { return equal(a,b) || apple(a) && apple(b); }\n"
     "    private static boolean letter(int c) { c|=32; return c>='a' && c<='z'; }\n"
     "    // \"Apple\" as a whole word, any case. UTF-8 neighbours are not ASCII letters.\n"
     "    private static boolean apple(byte[] b) {\n"
     "        if (b==null) return false;\n"
     "        String word=\"apple\";\n"
     "        for (int p=0;p+5<=b.length;p++) {\n"
     "            int i=0;\n"
     "            while (i<5 && (b[p+i]|32)==word.charAt(i)) i++;\n"
     "            if (i==5 && (p==0 || !letter(b[p-1])) && (p+5==b.length || !letter(b[p+5]))) return true;\n"
     "        }\n"
     "        return false;\n"
     "    }\n"
     "    static boolean equal(byte[] a, byte[] b) {\n", "sameSource", 1),
    ("        remainingMeters=remainingSeconds=-1;\n    }\n"
     "    public void invalidate() { clearCache(); state=-1; source=destination=null; seen=0; changed=-1; epoch++; }\n",
     "        remainingMeters=remainingSeconds=-1;\n"
     "        rerouting=false;reroutingType=-1;stopAt=recoverAt=-1;\n"
     "    }\n"
     "    // Indexes are reused by the new route, so its maneuvers and lanes must go.\n"
     "    private void dropManeuvers() {\n"
     "        laneCache.clear();cache=new Message[32];ages=new long[32];order=new int[0];\n"
     "    }\n"
     "    private boolean guiding(int phase) { return phase==1 || phase==6; }\n"
     "    private void endStop() { clearCache();destination=null;state=0; }\n"
     "    /** The phone has been silent for 5 s: stop waiting for what it has not sent. */\n"
     "    public void quiet() {\n"
     "        if(stopAt>=0)endStop();\n"
     "        else if(rerouting && guiding(state))rerouting=false;\n"
     "    }\n"
     "    private void expire(long now) {\n"
     "        if(stopAt>=0 && (now<stopAt || now-stopAt>=STOP_GRACE_MS))endStop();\n"
     "        else if(rerouting && recoverAt>=0 && (now<recoverAt || now-recoverAt>=RECOVER_MS))rerouting=false;\n"
     "    }\n"
     "    public void invalidate() { clearCache(); drivingSide=-1; state=-1; source=destination=null; seen=0; changed=-1; epoch++; }\n",
     "clearCache/quiet/expire/invalidate", 1),
    ("            || m.has[19] && source!=null && !equal(source,m.raw[19])\n",
     "            || m.has[19] && source!=null && !sameSource(source,m.raw[19])\n", "passed road source", 1),
    ("            cache[slot]=m; ages[slot]=++age; return true;\n",
     "            cache[slot]=m; ages[slot]=++age;\n"
     "            if (m.has[8] && (m.v[8]==0 || m.v[8]==1)) drivingSide=(int)m.v[8];\n"
     "            return true;\n", "driving side", 1),
    ("        boolean sourceChange=m.has[19] && source!=null && !equal(source,m.raw[19]);\n"
     "        boolean destChange=m.has[4] && destination!=null && destination.length>0 && m.raw[4].length>0 && !equal(destination,m.raw[4]);\n"
     "        if (next==0 && state!=0 || next>0 && state<=0 || (next==3 || next==5) && state>0 && state!=next || sourceChange || destChange || next>6) {\n"
     "            clearCache(); destination=null; if (sourceChange) source=null;\n"
     "        }\n"
     "        state=next;\n",
     "        boolean sourceChange=m.has[19] && source!=null && !sameSource(source,m.raw[19]);\n"
     "        if(m.has[19] && source!=null && !equal(source,m.raw[19]))GuidanceEvidence.flip(clock,state,next,m.has[13],m.has[4],m.has[10],current()!=null,sourceChange);\n"
     "        boolean destChange=m.has[4] && destination!=null && destination.length>0 && m.raw[4].length>0 && !equal(destination,m.raw[4]);\n"
     "        boolean sameRoute=!sourceChange && !destChange;\n"
     "        // A stop inside a reroute is provisional; a real one ends it after the grace period.\n"
     "        if (next==0 && rerouting && !guiding(state) && sameRoute) { if(stopAt<0)stopAt=clock; return true; }\n"
     "        stopAt=-1;\n"
     "        if(next!=3 && next!=5 && !guiding(next) && next!=0)rerouting=false;\n"
     "        if (sameRoute && (next==3 || next==5) && guiding(state)) {\n"
     "            reroutingType=maneuverType();rerouting=true;recoverAt=-1;dropManeuvers();\n"
     "        } else if (sameRoute && (next==3 || next==5) && rerouting) {\n"
     "            if(state!=next)dropManeuvers();\n"
     "        } else if (next==0 && state!=0 || next>0 && state<=0 || (next==3 || next==5) && state>0 && state!=next || sourceChange || destChange || next>6) {\n"
     "            if(sourceChange)GuidanceEvidence.sourceClears++;else if(destChange)GuidanceEvidence.destinationClears++;\n"
     "            clearCache(); destination=null; if (sourceChange) source=null;\n"
     "        }\n"
     "        if(rerouting && guiding(next) && !guiding(state))recoverAt=clock;\n"
     "        state=next;\n", "route state machine", 1),
    ("        if (next!=1 && next!=6) {remainingMeters=remainingSeconds=-1;currentRoad=\"\";roadAt=-1;directRoad=false;}\n",
     "        if (!guiding(next) && !rerouting) {remainingMeters=remainingSeconds=-1;currentRoad=\"\";roadAt=-1;directRoad=false;}\n",
     "counters kept while rerouting", 1),
    ("        if(next!=1 && next!=6){laneCache.showing=false;routeStatusAt=-1;}\n",
     "        if(!guiding(next)){laneCache.showing=false;if(!rerouting)routeStatusAt=-1;}\n", "lanes/route status", 1),
    ("        for (int i=48;i<64;i+=4) require(u32(b,i)==0);\n",
     "        for (int i=48;i<64;i+=4) require(u32(b,i)==0);\n        clock=now;\n", "clock", 1),
    ("                if (head()!=distanceHead || generation!=distanceGeneration || current()==null) distance=-1;\n",
     "                if (!rerouting && (head()!=distanceHead || generation!=distanceGeneration || current()==null)) distance=-1;\n",
     "distance kept while rerouting", 1),
    ("                    if (m.id==0x5201 && (state==1 || state==6)) {\n",
     "                    if (m.id==0x5201 && (guiding(state) || rerouting)) {\n", "route status while rerouting", 1),
    ("                    if (m.id==0x5201 && m.has[10] && current()!=null) distance=m.v[10]<=Integer.MAX_VALUE?(int)m.v[10]:-1;\n",
     "                    if (m.id==0x5201 && m.has[10] && current()!=null && !(rerouting && m.v[10]==0)) {\n"
     "                        distance=m.v[10]<=Integer.MAX_VALUE?(int)m.v[10]:-1;\n"
     "                        rerouting=false;\n"
     "                    }\n", "real distance ends the reroute", 1),
    ("        high=sequence; seen=sequence;\n        return frame();\n",
     "        high=sequence; seen=sequence;\n        expire(now);\n        return frame();\n", "expire", 1),
    ("    private int maneuverType(){",
     "    /** The current maneuver's side, else the last one seen; -1 when the phone never sent one. */\n"
     "    private int side(){Message m=current();return m!=null && m.has[8] && (m.v[8]==0 || m.v[8]==1)?(int)m.v[8]:drivingSide;}\n"
     "    private int maneuverType(){", "side()", 1),
    ("        int[] symbol=map(current());\n"
     "        return new Frame((state==1 || state==6) && changed>=0,symbol[0],symbol[1],distance,remainingMeters,remainingSeconds,progress,changed,epoch,laneCache.current(),routeStatusAt,currentRoad,roadAt,maneuverType());\n",
     "        int[] symbol=rerouting?symbol(MAIN_RECALCULATING,0):map(current());\n"
     "        return new Frame((guiding(state) || rerouting) && changed>=0,symbol[0],symbol[1],distance,remainingMeters,remainingSeconds,progress,changed,epoch,LaneData.forSide(laneCache.current(),side()),routeStatusAt,currentRoad,roadAt,rerouting?reroutingType:maneuverType());\n",
     "frame()", 1),
    ("            if (angle && a!=0) return symbol(25,a<0?64:192);\n",
     "            // +-180 carries no side; the driving side decides when it is known (not for Android Auto, see signedUturns).\n"
     "            if (angle && a!=0 && !(sideKnown && !signedUturns && (a==180 || a==-180))) return symbol(25,a<0?64:192);\n",
     "U-turn arrow side", 1),
])

# ---- LaneData: sideless 180 degree lanes follow the driving side (his v1.4.6 forSide on our v1.4.0 decoder) ----
patch("LaneData.java", [
    ("    LaneData(int p,int d,int r,String s){position=p;direction=d;recommendation=r;sides=s;}\n",
     "    /* Exactly +-180 has no side. The byte stays the left U-turn until the\n"
     "     * driving side is known: bit 16 is the main direction, bits 0-15 the\n"
     "     * matching characters of sides. (tomasz-twardzicki MU1367 v1.4.6) */\n"
     "    final int unsided;\n"
     "    LaneData(int p,int d,int r,String s){this(p,d,r,s,0);}\n"
     "    LaneData(int p,int d,int r,String s,int unsidedMask){position=p;direction=d;recommendation=r;sides=s;unsided=unsidedMask;}\n",
     "constructor", 1),
    ("        int[] plain=new int[16];int count=0,angles=0;\n",
     "        int[] plain=new int[16];boolean[] open=new boolean[16];int count=0,angles=0;boolean openHighlight=false;\n",
     "open flags", 1),
    ("                int d=direction((short)LiveModel.be16(data,p+4));boolean seen=false;\n"
     "                for(int i=0;i<count;i++)if(plain[i]==d)seen=true;\n"
     "                if(d!=255 && !seen)plain[count++]=d;\n",
     "                int degrees=(short)LiveModel.be16(data,p+4);\n"
     "                int d=direction(degrees);boolean seen=false,sideless=degrees==180 || degrees==-180;\n"
     "                // A signed angle on the same byte settles its side.\n"
     "                for(int i=0;i<count;i++)if(plain[i]==d){seen=true;if(!sideless)open[i]=false;}\n"
     "                if(d!=255 && !seen){open[count]=sideless;plain[count++]=d;}\n", "angles", 1),
    ("hasHighlight=true;highlight=direction((short)LiveModel.be16(data,p+4));\n",
     "hasHighlight=true;int degrees=(short)LiveModel.be16(data,p+4);highlight=direction(degrees);openHighlight=degrees==180 || degrees==-180;\n",
     "highlight", 1),
    ("        if(main==255)recommendation=0;\n"
     "        char[] other=new char[count];int used=0;\n"
     "        for(int i=0;i<count;i++)if(plain[i]!=main)other[used++]=(char)plain[i];\n"
     "        return new LaneData(pos,main,recommendation,new String(other,0,used));\n    }\n",
     "        if(main==255)recommendation=0;\n"
     "        int unsided=(highlight!=255?openHighlight:count==1 && open[0])?1<<16:0;\n"
     "        for(int i=0;i<count;i++)if(plain[i]==main && !open[i])unsided=0;\n"
     "        char[] other=new char[count];int used=0;\n"
     "        for(int i=0;i<count;i++)if(plain[i]!=main){if(open[i])unsided|=1<<used;other[used++]=(char)plain[i];}\n"
     "        return new LaneData(pos,main,recommendation,new String(other,0,used),unsided);\n    }\n"
     "    static final int LEFT_HAND_TRAFFIC=1, UTURN_LEFT=114, UTURN_RIGHT=146;\n"
     "    /** In left-hand traffic a U-turn goes clockwise: a sideless 180 degree lane becomes the right U-turn. */\n"
     "    LaneData forSide(int drivingSide){\n"
     "        if(drivingSide!=LEFT_HAND_TRAFFIC || unsided==0)return this;\n"
     "        int main=(unsided&1<<16)!=0 && direction==UTURN_LEFT?UTURN_RIGHT:direction;\n"
     "        char[] other=new char[sides.length()];int used=0;\n"
     "        for(int i=0;i<sides.length();i++){\n"
     "            int d=sides.charAt(i);if((unsided&1<<i)!=0 && d==UTURN_LEFT)d=UTURN_RIGHT;\n"
     "            boolean seen=d==main;for(int j=0;j<used;j++)if(other[j]==d)seen=true;\n"
     "            if(!seen)other[used++]=(char)d;\n"
     "        }\n"
     "        return new LaneData(position,main,recommendation,new String(other,0,used),0);\n"
     "    }\n"
     "    static LaneData[] forSide(LaneData[] lanes,int drivingSide){\n"
     "        if(drivingSide!=LEFT_HAND_TRAFFIC)return lanes;\n"
     "        LaneData[] result=lanes;\n"
     "        for(int i=0;i<lanes.length;i++){\n"
     "            LaneData next=lanes[i].forSide(drivingSide);\n"
     "            if(next!=lanes[i]){if(result==lanes){result=new LaneData[lanes.length];System.arraycopy(lanes,0,result,0,lanes.length);}result[i]=next;}\n"
     "        }\n"
     "        return result;\n"
     "    }\n", "forSide", 1),
])

# ---- readers: the 5 s STALE record ends a provisional stop / a reroute wait ----
patch("MailboxReader.java", [
    ("            if (kind==3) GuidanceEvidence.quiet(now); else model.invalidate();\n",
     "            if (kind==3) { GuidanceEvidence.quiet(now); model.quiet(); } else model.invalidate();\n", "STALE", 1)])
patch("JournalReader.java", [
    ("            if (kind!=4 && kind!=3) model.invalidate();\n",
     "            if (kind==3) model.quiet(); else if (kind!=4) model.invalidate();\n", "STALE", 1)])

# ---- ArrowProgress: a reroute keeps the bar it had ----
patch("ArrowProgress.java", [
    ("    static int window(LiveModel.Frame f){\n",
     "    // A reroute keeps the bar it had, so the countdown does not restart afterwards. (MU1367 v1.4.5)\n"
     "    static boolean shown(int main){return supported(main) || main==LiveModel.MAIN_RECALCULATING;}\n"
     "    static int window(LiveModel.Frame f){\n", "shown()", 1),
    ("!f.validDistance || !supported(f.main)", "!f.validDistance || !shown(f.main)", "remaining()", 1)])

# ---- LiveBridge: AA flag for the U-turn sign; placeholder arrow ----
patch("LiveBridge.java", [
    ("        phone=connection;\n", "        phone=connection;\n        LiveModel.signedUturns=connection==3;\n", "signedUturns", 1),
    ("        out.maneuver_1.mainElement=f.main; out.maneuver_1.direction=f.direction;\n",
     "        // tomasz-twardzicki MU1367 v1.4.5: an owned, fresh active route without a maneuver shows the straight\n"
     "        // DIRECTION_TO_DESTINATION arrow (2). No bearing is known, so it never turns. pmcp: only when no maneuver is\n"
     "        // known at all (maneuverType<0), CarPlay only; known maneuvers keep the strict map and our fallbacks.\n"
     "        boolean placeholder=placeholder(f);\n"
     "        out.maneuver_1.mainElement=placeholder?2:f.main; out.maneuver_1.direction=placeholder?0:f.direction;\n",
     "descriptor placeholder", 1),
    ("    public static boolean distance(DistanceToNextManeuver_Status out) {\n",
     "    static boolean placeholder(LiveModel.Frame f) { return f.active && f.main==0 && f.maneuverType<0 && phone!=3; }\n"
     "    public static boolean distance(DistanceToNextManeuver_Status out) {\n", "placeholder()", 1),
    ("        int[] converted=convertDistance(f.validDistance?f.meters:0,false);\n"
     "        out.distanceToNextManeuver.distance=converted[0];\n"
     "        out.distanceToNextManeuver.unit=converted[1]; out.validityInformation.distanceToNextManeuverValid=f.validDistance;\n",
     "        boolean realDistance=f.validDistance && !placeholder(f);   // the placeholder has no distance of its own\n"
     "        int[] converted=convertDistance(realDistance?f.meters:0,false);\n"
     "        out.distanceToNextManeuver.distance=converted[0];\n"
     "        out.distanceToNextManeuver.unit=converted[1]; out.validityInformation.distanceToNextManeuverValid=realDistance;\n",
     "distance placeholder", 1),
])

# ---- his tests on our sources: only the lines our deliberate differences change ----
# TestReroute: after the 20 s bound / the quiet end the new route's start maneuver (type 11 without angle) shows; his
# strict map leaves it empty (main 0, his placeholder), our start-of-route fallback (maneuvers.py) shows straight (13, 0).
patch("TestReroute.java", [
    ('check(f.main==0&&f.meters==300,"after the bound the phone\'s own maneuver shows (no angle: placeholder)");',
     'check(f.main==13&&f.direction==0&&f.meters==300,"after the bound the phone\'s own maneuver shows (pmcp: start-of-route fallback, straight)");',
     "bound", 1),
    ('check(f.active&&f.main==0,"quiet ends the wait");',
     'check(f.active&&f.main==13&&f.direction==0,"quiet ends the wait (pmcp: start-of-route fallback)");', "quiet", 1),
])
# TestUturnSide / TestPlaceholder / TestSourceName / TestQuietQnx run unchanged.

# TestArrow / TestRoad (his v1.4.3 tests with hold.py's edits): his v1.4.5 changes for the reroute
patch("TestArrow.java", [
    ("            boolean allowed=main>=3&&main<=5 || main>=13&&main<=27 || main>=32&&main<=35;\n",
     "            // Main 9 is only ever a held reroute; the factory whitelist itself is unchanged.\n"
     "            boolean allowed=main>=3&&main<=5 || main>=13&&main<=27 || main>=32&&main<=35 || main==LiveModel.MAIN_RECALCULATING;\n"
     "            check(ArrowProgress.supported(main)==(allowed&&main!=LiveModel.MAIN_RECALCULATING),\"factory whitelist\");\n",
     "whitelist", 1),
    ('        for(int phase:new int[]{5,0,2}){feed.state(phase,65535,false);f=feed.model.frame();check(!f.validDistance||!f.active,"stop/reroute cannot animate old turn");}\n',
     '        feed.state(5,65535,false);f=feed.model.frame();check(f.active&&f.main==9&&ArrowProgress.remaining(f,f.changed)==50,"reroute holds the bar on the calculating symbol, never on the old turn");\n'
     '        feed.state(2,65535,false);f=feed.model.frame();check(!f.active&&!f.validDistance,"arrival ends the reroute and cannot animate an old turn");\n',
     "reroute bar", 1),
])
patch("TestRoad.java", [
    ('        update(feed,1,"Before Reroute");f=update(feed,5,null);check(f.currentRoad.equals("")&&f.roadAt<0,"reroute clears");\n'
     '        f=update(feed,1,null);check(f.currentRoad.equals(""),"reroute cannot resurrect");\n'
     '        for(int phase=0;phase<=6;phase++)if(phase!=1&&phase!=6){update(feed,1,"Before phase");f=update(feed,phase,null);check(f.currentRoad.equals("")&&f.roadAt<0,"non-guiding phase clears");}\n',
     '        update(feed,1,"Before Reroute");f=update(feed,5,null);check(f.active&&f.main==9&&f.currentRoad.equals("Before Reroute")&&f.roadAt>=0,"reroute keeps the road");\n'
     '        f=update(feed,1,null);check(f.currentRoad.equals("Before Reroute"),"road survives until the phone replaces it");\n'
     '        for(int phase=0;phase<=6;phase++)if(phase!=1&&phase!=6){update(feed,1,"Before phase");f=update(feed,phase,null);check(phase==3||phase==5?f.currentRoad.equals("Before phase"):f.currentRoad.equals("")&&f.roadAt<0,"only a reroute keeps the road");}\n',
     "reroute road", 1),
    ('        f=update(feed,5,null);check(f.currentRoad.equals(""),"reroute clears passed-road fallback");\n',
     '        f=update(feed,5,null);check(f.currentRoad.equals("Passed Road"),"the car is still on that road during a reroute");\n',
     "passed road", 1),
])
print("v146.py: reroute, placeholder, U-turn side and Apple Maps names (MU1367 v1.4.5/v1.4.6) staged in %s" % lane_dir)
