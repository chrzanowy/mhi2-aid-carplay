/* pmcp (rg/lanes/v146.py): where our port of tomasz-twardzicki's MU1367 v1.4.5/v1.4.6 guidance fixes deliberately
 * differs from his: Android Auto keeps its signed U-turn arrow and gets no placeholder, a known maneuver that maps to
 * nothing stays empty, the start of route keeps our straight arrow with its distance, and a reroute never shows an old
 * lane. SPDX-License-Identifier: GPL-3.0-or-later */
package com.cpmap.rgi;
import de.vw.mib.bap.mqbab2.generated.navsd.serializer.*;

public final class TestPmcp146 {
    static int checks;
    static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    static int[] uturn(int side,int angle){
        byte[] m=TestUturnSide.maneuver(1,4,side,Integer.valueOf(angle));
        try{return LiveModel.map(LiveModel.decode(0x5202,m,0,m.length));}catch(Exception e){throw new AssertionError(e.toString());}
    }
    static LiveBridge bridge(LiveModel.Frame f)throws Exception{
        TestLive.clock=f.changed;LiveBridge b=TestLive.bridge();
        b.incoming=f;b.journalAt=TestLive.clock;b.lastTick=TestLive.clock;b.tick(TestLive.clock);return b;
    }
    public static void main(String[] args)throws Exception{
        TestLive.installMocks();TestLive.route=0;TestLive.status=0;TestLive.clock=1000;
        // U-turn main arrow: CarPlay follows the driving side at exactly +-180, Android Auto keeps the hook's sign.
        TestLive.connection=2;LiveBridge.factoryContext();
        check(!LiveModel.signedUturns,"CarPlay: side rule");
        check(uturn(0,180)[1]==64&&uturn(0,-180)[1]==64,"CarPlay, right-hand traffic: left U-turn");
        check(uturn(1,180)[1]==192,"CarPlay, left-hand traffic: right U-turn");
        check(uturn(0,175)[1]==192&&uturn(0,-175)[1]==64,"CarPlay: a signed angle keeps its side");
        TestLive.connection=3;LiveBridge.factoryContext();
        check(LiveModel.signedUturns,"Android Auto: signed U-turns");
        check(uturn(0,180)[0]==25&&uturn(0,180)[1]==192&&uturn(0,-180)[1]==64,"Android Auto: hook's +180 right, -180 left (side 0)");
        TestLive.connection=2;LiveBridge.factoryContext();check(!LiveModel.signedUturns,"back to CarPlay");

        // Placeholder only without any maneuver.
        ManeuverDescriptor_Status out=new ManeuverDescriptor_Status();DistanceToNextManeuver_Status d=new DistanceToNextManeuver_Status();
        TestLanes.Feed feed=new TestLanes.Feed();LiveModel.Frame f=feed.state(1,65535,false);
        LiveBridge b=bridge(f);
        check(b.owned&&f.maneuverType<0&&LiveBridge.descriptor(out)&&out.maneuver_1.mainElement==2&&out.maneuver_1.direction==0,"no maneuver: DIRECTION_TO_DESTINATION");
        check(LiveBridge.distance(d)&&!d.validityInformation.distanceToNextManeuverValid,"placeholder: no distance");
        // A known maneuver without a mapping (highway change 51, no angle) stays empty, distance shown as before.
        b.selected=new LiveModel.Frame(true,0,0,700,-1,-1,5,TestLive.clock,1,LaneData.EMPTY,TestLive.clock,"",-1,51);
        check(LiveBridge.descriptor(out)&&out.maneuver_1.mainElement==0,"known maneuver without arrow: no placeholder");
        check(LiveBridge.distance(d)&&d.validityInformation.distanceToNextManeuverValid,"its distance is kept");
        // Start of route (type 11, no angle): our straight fallback with its distance, not the placeholder.
        feed=new TestLanes.Feed();feed.add(0x5201,TestQuietQnx.route(1,0,150));feed.add(0x5202,TestQuietQnx.maneuver(0,11));
        feed.add(0x5201,TestQuietQnx.route(1,0,150));f=feed.read();
        check(f.active&&f.main==13&&f.direction==0&&f.meters==150&&f.maneuverType==11,"start of route: straight turn arrow");
        b=bridge(f);check(LiveBridge.descriptor(out)&&out.maneuver_1.mainElement==13&&LiveBridge.distance(d)&&d.validityInformation.distanceToNextManeuverValid,"start of route output");
        // Android Auto: no placeholder (the AA picture shows the route; the hook sends state before its maneuver).
        TestLive.connection=3;LiveBridge.factoryContext();
        b.selected=new LiveModel.Frame(true,0,0,-1,-1,-1,5,TestLive.clock,1);
        b.root=LiveBridge.AA_ROOT;
        check(LiveBridge.placeholder(b.selected)==false,"Android Auto: no placeholder");
        TestLive.connection=2;LiveBridge.factoryContext();b.root=LiveBridge.ROOT;
        check(LiveBridge.placeholder(b.selected),"CarPlay: placeholder");

        // Reroute: lanes of the old route are dropped, U-turn lanes of the new one follow the side.
        feed=new TestLanes.Feed();feed.state(1,7,true);feed.add(0x5202,TestUturnSide.maneuver(7,3,1,null));
        feed.add(0x5204,TestLanes.instruction(7,TestLanes.lane(0,2,180,180)));f=feed.read();
        check(f.lanes.length==1&&f.lanes[0].direction==146,"left-hand traffic: right U-turn lane");
        f=feed.state(5,7,true);check(f.active&&f.main==9&&f.lanes.length==0,"reroute: CALC_ROUTE, no old lanes");
        System.out.println("PMCP146_PASS checks="+checks+" aa_signed_uturn=1 placeholder_only_without_maneuver=1 aa_no_placeholder=1");
    }
}
