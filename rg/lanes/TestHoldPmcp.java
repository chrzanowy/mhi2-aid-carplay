/* SPDX-License-Identifier: GPL-3.0-or-later
 * pmcp checks for the quiet-route hold (rg/lanes/hold.py) beyond Tomasz's TestQuietHold: what must still end a held
 * route at once, with only our reader's STALE heartbeats arriving. */
package com.cpmap.rgi;
import java.io.*;

public final class TestHoldPmcp {
 static int checks;
 static void check(boolean b,String why){checks++;if(!b)throw new AssertionError(why);}
 static void poll(LiveBridge b,FeedRecovery feed,long now)throws Exception{TestLive.clock=now;b.pollProduction(feed,now,false);b.tick(now);}
 // A bridge that owns a route, then a minute of reader STALE heartbeats only (Apple Maps silent).
 static long held(LiveBridge b,FeedRecovery feed,TestRecovery.Wire w)throws Exception{
  w.route(0);w.publish();poll(b,feed,1000);
  w.add(0x5201,TestQuietHold.routeTo(1,5,300));w.add(0x5202,TestQuietHold.maneuver(5,2));w.publish();poll(b,feed,1250);
  check(b.owned,"route owned");
  long now=1250;for(int i=0;i<60;i++){now+=1000;w.envelope(3,5000,new byte[0]);poll(b,feed,now);}
  check(b.owned,"held through a minute of STALE heartbeats");return now;
 }
 static void disconnect(File root)throws Exception{
  TestLive.installMocks();LiveBridge b=TestLive.bridge();FeedRecovery feed=new FeedRecovery(root.toString());TestRecovery.Wire w=new TestRecovery.Wire(root);
  long now=held(b,feed,w);
  TestLive.connection=0;now+=250;w.envelope(3,5000,new byte[0]);poll(b,feed,now);check(!b.owned,"CarPlay disconnect ends a held route at once");
  TestLive.connection=2;
  for(int i=0;i<5;i++){now+=1000;w.envelope(3,5000,new byte[0]);poll(b,feed,now);check(!b.owned,"reconnect with only STALE heartbeats does not revive the held route");}
  w.add(0x5201,TestQuietHold.routeTo(1,5,200));w.publish();now+=250;poll(b,feed,now);check(b.owned,"a fresh phone message after reconnect takes over again");
 }
 static void session(File root)throws Exception{
  TestLive.installMocks();LiveBridge b=TestLive.bridge();FeedRecovery feed=new FeedRecovery(root.toString());TestRecovery.Wire w=new TestRecovery.Wire(root);
  long now=held(b,feed,w);
  TestRecovery.Wire next=new TestRecovery.Wire(root);next.nonce=2;next.route(0);next.publish();now+=250;poll(b,feed,now);
  check(!feed.live&&!b.owned,"a new reader session after a quiet stretch ends the held route");
 }
 static void invalidate(File root)throws Exception{
  TestLive.installMocks();LiveBridge b=TestLive.bridge();FeedRecovery feed=new FeedRecovery(root.toString());TestRecovery.Wire w=new TestRecovery.Wire(root);
  long now=held(b,feed,w);
  // our reader's sequence when its worker hangs: INVALIDATE, then heartbeats, then a late snapshot with one sparse delta
  w.envelope(2,5,new byte[0]);now+=250;poll(b,feed,now);check(!b.owned,"INVALIDATE ends a held route at once");
  for(int i=0;i<3;i++){now+=1000;w.envelope(3,5000,new byte[0]);poll(b,feed,now);check(!b.owned,"STALE after INVALIDATE does not revive");}
  w.publish();now+=250;poll(b,feed,now);check(!b.owned,"the old window after INVALIDATE does not revive");
 }
 static void rejectedManeuver(File root)throws Exception{
  TestLive.installMocks();LiveBridge b=TestLive.bridge();FeedRecovery feed=new FeedRecovery(root.toString());TestRecovery.Wire w=new TestRecovery.Wire(root);
  long now=held(b,feed,w);
  // a maneuver update that fails validation is dropped alone (as in Tomasz's v1.4.4): the held route and arrow stay
  w.add(0x5202,TestLanes.tlv(1,new byte[]{0}));w.publish();now+=250;poll(b,feed,now);
  check(b.owned&&feed.live&&feed.last.main==13&&feed.last.direction==192,"rejected maneuver message keeps the held route");
  w.add(0x5201,TestLanes.route(0,65535,false));w.publish();now+=250;poll(b,feed,now);check(!b.owned,"route end still clears at once");
 }
 public static void main(String[] a)throws Exception{
  File root=new File(a[0]);
  disconnect(new File(root,"disconnect"));session(new File(root,"session"));invalidate(new File(root,"invalidate"));rejectedManeuver(new File(root,"rejected"));
  System.out.println("HOLD_PMCP_PASS checks="+checks+" disconnect=1 session=1 invalidate=1 rejected_maneuver=1");
 }
}
