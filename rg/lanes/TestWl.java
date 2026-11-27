/* pmcp (rg/lanes/wl.py, A248): CarPlay over Wi-Fi reads the WL receiver's mailbox only while a Wi-Fi session owns the
 * MOST map contract; cable (src=wired) and Android Auto (connection 3) win; anything else = the wired directory.
 * Host-only, on the guarded factory classes with TestLive's mocks; temporary directories stand in for /ramdisk and /proc.
 * SPDX-License-Identifier: GPL-3.0-or-later */
package com.cpmap.rgi;

import java.io.*;
import de.vw.mib.bap.mqbab2.generated.navsd.serializer.*;

public final class TestWl {
    static int checks;
    static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    static File src, proc;
    static void put(String name,String text)throws Exception{FileOutputStream o=new FileOutputStream(new File(src,name));o.write(text.getBytes("US-ASCII"));o.close();}
    static void owner(String text)throws Exception{put("owner",text);}
    static void session(String text)throws Exception{put("wireless.session",text);}
    static boolean fresh(){WlSource.reset();return WlSource.active();}
    static void rm(File f){File[] l=f.listFiles();if(l!=null)for(int i=0;i<l.length;i++)rm(l[i]);f.delete();}

    public static void main(String[] a)throws Exception{
        File base=new File(System.getProperty("java.io.tmpdir"),"pmcp-testwl-"+System.nanoTime());
        src=new File(base,"most-src");proc=new File(base,"proc");File wl=new File(base,"pmcp-wl-rg");
        src.mkdirs();proc.mkdirs();
        WlSource.SRC_DIR=src.getPath();WlSource.PROC=proc.getPath();WlSource.ROOT=wl.getPath();
        File pid=new File(proc,"4242");

        // ---- contract check (fail-closed)
        check(!fresh(),"no owner, no session: not Wi-Fi");
        owner("v=1 src=wireless pid=4242 gen=7 since_ms=100 kind=in\n");
        check(!fresh(),"owner without a session: not Wi-Fi");
        session("v=1 state=start gen=7 pid=4242 ts_ms=120 reason=start\n");
        check(!fresh(),"owner pid not alive: not Wi-Fi");
        pid.mkdirs();
        check(fresh(),"owner src=wireless, live pid, session start of the same gen: Wi-Fi");
        long r0=WlSource.reads;
        for(int i=0;i<50;i++)WlSource.active();
        check(WlSource.reads==r0,"cached: no file read within the period");
        pid.delete();
        check(WlSource.active(),"within the period the cached answer stays");
        check(!fresh(),"owner pid gone: not Wi-Fi");
        pid.mkdirs();
        session("v=1 state=start gen=8 pid=4242 ts_ms=120 reason=start\n");check(!fresh(),"gen mismatch: not Wi-Fi");
        session("v=1 state=stop gen=7 pid=4242 ts_ms=130 reason=idle\n");check(!fresh(),"session stop: not Wi-Fi");
        session("v=1 state=start gen=7 pid=4242 ts_ms=120 reason=start\n");check(fresh(),"session start again");
        owner("v=1 src=wired pid=4242 gen=8 since_ms=0 kind=proxy\n");check(!fresh(),"cable owns the contract: not Wi-Fi");
        owner("v=2 src=wireless pid=4242 gen=7 since_ms=100 kind=in\n");check(!fresh(),"unknown line version: not Wi-Fi");
        owner("v=1 src=wireless pid=abc gen=7\n");check(!fresh(),"pid not a number: not Wi-Fi");
        owner("v=1 src=wireless pid=1 gen=7\n");check(!fresh(),"pid 1: not Wi-Fi");
        owner("v=1 src=wireless pid=4242 gen=\n");check(!fresh(),"empty gen: not Wi-Fi");
        owner("v=1 src=wirelessX pid=4242 gen=7\n");check(!fresh(),"src must match exactly");
        owner("v=1 xsrc=wireless pid=4242 gen=7\n");check(!fresh(),"key must match exactly");
        StringBuffer longLine=new StringBuffer("v=1 src=wireless pid=4242 gen=7");while(longLine.length()<300)longLine.append(" x=y");
        owner(longLine.toString());check(!fresh(),"line over 255 bytes: not Wi-Fi");
        {FileOutputStream o=new FileOutputStream(new File(src,"owner"));o.write("v=1 src=wireless pid=4242 gen=7 name=".getBytes("US-ASCII"));o.write(new byte[]{(byte)0xc3,(byte)0xa9,'\n'});o.close();}
        check(!fresh(),"non-ASCII byte in the line: not Wi-Fi");
        owner("v=1 gen=7 kind=in src=wireless since_ms=5 pid=4242\n");check(fresh(),"key order free, no trailing newline needed");
        new File(src,"wireless.session").delete();check(!fresh(),"session file gone: not Wi-Fi");
        session("v=1 state=start gen=7 pid=4242 ts_ms=120 reason=start");check(fresh(),"Wi-Fi again");

        // ---- source selection
        TestLive.installMocks();
        TestLive.connection=2;LiveBridge.factoryContext();
        check(LiveBridge.rootFor(2).equals(WlSource.ROOT),"Wi-Fi owner: CarPlay reads the WL directory");
        check(LiveBridge.rootFor(3).equals(LiveBridge.AA_ROOT),"Android Auto unchanged while a Wi-Fi owner exists");
        check(LiveBridge.holdFor(WlSource.ROOT)==LiveModel.HOLD_MS,"WL quiet-route hold = CarPlay's");
        owner("v=1 src=wired pid=4242 gen=8 since_ms=0 kind=proxy\n");WlSource.reset();
        check(LiveBridge.rootFor(2).equals(LiveBridge.ROOT)&&LiveBridge.rootFor(0).equals(LiveBridge.ROOT),"cable: the wired directory, as before");

        // ---- WL mailbox through the actual bridge (FeedRecovery + tick)
        owner("v=1 src=wireless pid=4242 gen=9 since_ms=100 kind=in\n");session("v=1 state=start gen=9 pid=4242 ts_ms=120 reason=start\n");WlSource.reset();
        LiveBridge b=TestLive.bridge();b.root=LiveBridge.ROOT;
        FeedRecovery feed=b.switchRoot(new FeedRecovery(LiveBridge.ROOT));
        check(feed.root.equals(WlSource.ROOT)&&b.root.equals(WlSource.ROOT),"switch to the WL directory with a fresh feed");
        TestRecovery.Wire w=new TestRecovery.Wire(wl);
        w.route(0);w.publish();TestLive.clock=1000;b.pollProduction(feed,1000,false);b.tick(1000);
        w.add(0x5202,TestArrow.maneuver(7,1));w.route(1);w.publish();TestLive.clock=1250;b.pollProduction(feed,1250,false);b.tick(1250);
        check(b.owned&&b.current()!=null,"WL guidance published on the AID");
        ManeuverDescriptor_Status d=new ManeuverDescriptor_Status();
        check(LiveBridge.descriptor(d),"WL arrow descriptor");

        // cable plugged: owner src=wired -> the WL frame is no longer published, the reader goes back to the wired directory
        owner("v=1 src=wired pid=4242 gen=10 since_ms=0 kind=proxy\n");WlSource.reset();
        check(b.current()==null,"cable owner: the WL frame is not published (reader still on the WL directory)");
        TestLive.clock=1500;b.tick(1500);
        check(!b.owned||b.current()==null,"cable owner: nothing of WL goes out");
        FeedRecovery back=b.switchRoot(feed);
        check(back!=feed&&back.root.equals(LiveBridge.ROOT)&&b.root.equals(LiveBridge.ROOT)&&b.incoming==null,"back to the wired directory, frame dropped");

        // Wi-Fi again, then the WL receiver dies (owner pid gone): back to the wired directory
        owner("v=1 src=wireless pid=4242 gen=11 since_ms=100 kind=in\n");session("v=1 state=start gen=11 pid=4242 ts_ms=120 reason=start\n");WlSource.reset();
        FeedRecovery again=b.switchRoot(back);
        check(again!=back&&again.root.equals(WlSource.ROOT),"Wi-Fi again: WL directory");
        pid.delete();WlSource.reset();
        LiveModel.Frame c=b.current();
        check(c==null||!c.active,"owner pid gone: no active WL frame published");
        check(b.switchRoot(again).root.equals(LiveBridge.ROOT),"owner pid gone: wired directory");
        // gen mismatch (a new session not started yet): wired directory
        pid.mkdirs();session("v=1 state=start gen=10 pid=4242 ts_ms=120 reason=start\n");WlSource.reset();
        check(LiveBridge.rootFor(2).equals(LiveBridge.ROOT),"session of another gen: wired directory");

        // Android Auto with a stale Wi-Fi owner: the AA directory, as before
        session("v=1 state=start gen=11 pid=4242 ts_ms=120 reason=start\n");WlSource.reset();
        TestLive.connection=3;LiveBridge.factoryContext();
        check(b.switchRoot(new FeedRecovery(LiveBridge.ROOT)).root.equals(LiveBridge.AA_ROOT),"AA: AA directory");
        TestLive.connection=2;LiveBridge.factoryContext();
        rm(base);
        System.out.println("WL_PASS checks="+checks+" fail_closed=1 cached=1 cable_wins=1 aa_unchanged=1 actual_bridge=1");
    }
}
