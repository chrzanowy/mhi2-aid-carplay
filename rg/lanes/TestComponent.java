/* pmcp (rg/lanes/component.py): route-guidance display component 1 (wireless CarPlay, omonob's notes) is handled like
 * 16 (wired CarPlay, our AA hook); a message with 16 behaves exactly as before; other components are still dropped.
 * SPDX-License-Identifier: GPL-3.0-or-later */
package com.cpmap.rgi;

public final class TestComponent {
    static int checks;
    static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    /** The same payload with its leading component TLV (00 06 00 00 00 10) replaced by the given component list. */
    static byte[] comp(byte[] payload,int... ids){
        check(payload.length>=6&&payload[0]==0&&payload[1]==6&&payload[2]==0&&payload[3]==0&&payload[4]==0&&payload[5]==0x10,"payload starts with component 16");
        byte[] list=new byte[0];for(int id:ids)list=TestLanes.join(list,TestLanes.u16(id));
        return TestLanes.join(TestLanes.tlv(0,list),LiveModel.copy(payload,6,payload.length-6));
    }
    static String arrow(int... ids)throws Exception{
        TestLanes.Feed f=new TestLanes.Feed();
        f.add(0x5201,comp(TestQuietQnx.route(1,0,150),ids));f.add(0x5202,comp(TestQuietQnx.maneuver(0,11),ids));
        f.add(0x5201,comp(TestQuietQnx.route(1,0,150),ids));LiveModel.Frame r=f.read();
        return r.active+" "+r.main+" "+r.direction+" "+r.meters+" "+r.validDistance+" "+r.maneuverType;
    }
    static int lanes(int[] route,int[] lane)throws Exception{
        TestLanes.Feed f=new TestLanes.Feed();
        f.add(0x5201,comp(TestLanes.route(1,7,true),route));f.add(0x5204,comp(TestLanes.instruction(7,TestLanes.sample()),lane));
        return f.read().lanes.length;
    }
    public static void main(String[] args)throws Exception{
        int[] wired={16},wireless={1},other={2};
        String w=arrow(16);
        check(w.equals("true 13 0 150 true 11"),"wired: start-of-route arrow with distance ("+w+")");
        check(arrow(1).equals(w),"wireless component 1: same frame as wired ("+arrow(1)+")");
        check(arrow(2,1).equals(w)&&arrow(1,16).equals(w)&&arrow(16,2).equals(w),"lists that include 1 or 16");
        check(!arrow(2).startsWith("true"),"component 2 still dropped");
        check(!arrow(0).startsWith("true")&&!arrow(0x11).startsWith("true")&&!arrow(0x100).startsWith("true"),"components 0, 0x11, 0x100 dropped");
        check(lanes(wired,wired)==3,"wired lanes");
        check(lanes(wireless,wireless)==3,"wireless lanes");
        check(lanes(wired,wireless)==3&&lanes(wireless,wired)==3,"mixed 1/16 lanes");
        check(lanes(wired,other)==0,"lanes of component 2 dropped");
        // 0x5204 without a component list: Tomasz's default 16 (all displays) still applies
        TestLanes.Feed f=new TestLanes.Feed();f.add(0x5201,comp(TestLanes.route(1,7,true),wireless));
        byte[] omitted=TestLanes.instruction(7,TestLanes.sample());f.add(0x5204,LiveModel.copy(omitted,6,omitted.length-6));
        check(f.read().lanes.length==3,"lanes without component, wireless route");
        System.out.println("COMPONENT_PASS checks="+checks+" wired_16=1 wireless_1=1 other_dropped=1");
    }
}
