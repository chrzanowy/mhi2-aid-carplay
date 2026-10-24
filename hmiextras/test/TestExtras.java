/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed.
 * Run with -Xverify:all; classpath: tests, pmcp-zoom.jar, pmcp-dn.jar, converted stock jar. */
package com.pmcp.dn;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;

public class TestExtras {
    static int failures = 0;

    static void check(boolean ok, String what) {
        System.out.println((ok ? "ok   " : "FAIL ") + what);
        if (!ok) failures++;
    }

    static Object allocate(Class c) throws Exception {
        java.lang.reflect.Field f = Class.forName("sun.misc.Unsafe").getDeclaredField("theUnsafe");
        f.setAccessible(true);
        Object u = f.get(null);
        return u.getClass().getMethod("allocateInstance", new Class[] {Class.class}).invoke(u, new Object[] {c});
    }

    public static void main(String[] a) throws Exception {
        String[][] patched = {
            {"de.esolutions.fw.dsi.keypanel.DSIKeyPanelDispatcher", "pmcp-zoom.jar"},
            {"de.vw.mib.asl.internal.carplay.target.ASLHandler", "pmcp-dn.jar"},
        };
        for (int i = 0; i < patched.length; i++) {
            Class c = Class.forName(patched[i][0], false, TestExtras.class.getClassLoader());
            check(c.getProtectionDomain().getCodeSource().getLocation().toString().endsWith(patched[i][1]),
                  patched[i][0] + " loads from " + patched[i][1]);
            c.getDeclaredMethods();
        }

        // F: MFW up press -> "zoom-in" over UDP 127.0.0.1:7032; other keyboards and keys -> nothing
        DatagramSocket s = new DatagramSocket(7032, InetAddress.getByName("127.0.0.1"));
        s.setSoTimeout(2000);
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 1, 0, 1);
        byte[] buf = new byte[64];
        DatagramPacket p = new DatagramPacket(buf, buf.length);
        s.receive(p);
        check(new String(buf, 0, p.getLength(), "US-ASCII").equals("zoom-in"), "MFW up -> zoom-in on 7032");
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 0, 0, 1);
        com.pmcp.zoom.ZoomHook.onKey2(4, 39, 1, 0, 1);
        s.receive(p);
        check(new String(buf, 0, p.getLength(), "US-ASCII").equals("zoom-out"), "MFW down -> zoom-out");
        com.pmcp.zoom.ZoomHook.onKey2(4, 39, 0, 0, 1);
        // held key: repeats and long-press states send nothing, also after the old 2.5 s long-press time
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 1, 0, 1);
        s.receive(p);
        check(new String(buf, 0, p.getLength(), "US-ASCII").equals("zoom-in"), "MFW up again -> zoom-in");
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 1, 0, 1);
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 3, 0, 1);
        Thread.sleep(3000);
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 4, 0, 1);
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 5, 0, 1);
        s.setSoTimeout(700);
        boolean quiet = false;
        try { s.receive(p); } catch (java.net.SocketTimeoutException e) { quiet = true; }
        check(quiet, "held key: no repeat, no long-press command (no map-previous/map-next)");
        com.pmcp.zoom.ZoomHook.onKey2(4, 38, 0, 0, 1);
        com.pmcp.zoom.ZoomHook.onKey2(1, 38, 1, 0, 1);   // another keyboard
        com.pmcp.zoom.ZoomHook.onKey2(4, 12, 1, 0, 1);   // another key
        s.setSoTimeout(700);
        boolean nothing = false;
        try { s.receive(p); } catch (java.net.SocketTimeoutException e) { nothing = true; }
        check(nothing, "other keyboards/keys send nothing");
        s.close();

        // G: schedule resends while connected, stops when disconnected
        final int[] count = {0};
        final boolean[] connected = {true};
        DayNight.Resender r = new DayNight.Resender() {
            public boolean connected() { return connected[0]; }
            public void resend() { count[0]++; if (count[0] == 2) connected[0] = false; }
        };
        int sent = DayNight.runSchedule(r, new long[] {10, 10, 10});
        check(sent == 2 && count[0] == 2, "resends twice, stops after disconnect (sent=" + sent + ")");
        count[0] = 0; connected[0] = true;
        check(DayNight.runSchedule(r, new long[] {1, 1}) == 2, "two delays -> two resends");
        check(DayNight.DELAYS.length == 3 && DayNight.DELAYS[0] == 5000L, "production schedule 5/15/30 s");
        DayNight.sessionStarted(null, null);
        check(true, "sessionStarted(null) is silent");

        // G: our event gets the value at handling time; a real event passes unchanged
        de.vw.mib.asl.internal.carplay.common.CarPlayGlobalProperies props =
                (de.vw.mib.asl.internal.carplay.common.CarPlayGlobalProperies) allocate(de.vw.mib.asl.internal.carplay.common.CarPlayGlobalProperies.class);
        de.vw.mib.genericevents.internal.SimpleEventFactory f = new de.vw.mib.genericevents.internal.SimpleEventFactory();
        props.setNightMode(true);
        de.vw.mib.genericevents.EventGeneric ours = f.newEvent();
        ours.setBoolean(DayNight.P_VALUE, false);           // value read on our thread, before a real change
        ours.setObject(DayNight.P_MARKER, DayNight.MARKER);
        DayNight.beforeHandle(ours, props);
        check(ours.getBoolean(DayNight.P_VALUE) && !ours.contains(DayNight.P_MARKER), "resend carries the handled value, marker removed");
        de.vw.mib.genericevents.EventGeneric real = f.newEvent();
        real.setBoolean(DayNight.P_VALUE, false);
        DayNight.beforeHandle(real, props);
        check(!real.getBoolean(DayNight.P_VALUE), "real day/night event unchanged");
        DayNight.beforeHandle(null, null);
        check(true, "beforeHandle(null) is silent");

        System.out.println(failures == 0 ? "ALL OK" : failures + " FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }
}
