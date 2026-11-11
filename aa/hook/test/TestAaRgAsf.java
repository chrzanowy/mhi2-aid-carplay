/* SPDX-License-Identifier: GPL-3.0-or-later
 * rg_test's step-N.bin through the staged rgluasf(a) classes (lanes-uturn-asf[-aa] guidance-src): the same frames as
 * TestAaRg, plus the bargraph (ArrowProgress) and road name (RoadName) on hook output. */
package com.cpmap.rgi;

import java.nio.file.*;

public final class TestAaRgAsf {
    static int fails;
    static void check(boolean c, String m) { System.out.println((c ? "ok     " : "FAILED ") + m); if (!c) fails++; }
    static String lanes(LiveModel.Frame f) {
        StringBuffer b = new StringBuffer();
        for (int i = 0; i < f.lanes.length; i++) b.append(i == 0 ? "" : " ").append(f.lanes[i].position).append(':').append(f.lanes[i].direction).append('/').append(f.lanes[i].recommendation);
        return b.toString();
    }
    public static void main(String[] a) throws Exception {
        String dir = a[0];
        Path cur = Paths.get(dir, "cur-asf.bin");
        MailboxReader r = new MailboxReader(cur.toString());
        LiveModel.Frame[] f = new LiveModel.Frame[22];
        for (int i = 0; i < 22; i++) {
            Files.copy(Paths.get(dir, "step-" + i + ".bin"), cur, StandardCopyOption.REPLACE_EXISTING);
            long now = 1000L * (i + 1);
            f[i] = r.next(now);
            if (f[i] == null) f[i] = r.model.frame();
            System.out.println("asf step " + i + ": main=" + f[i].main + " m=" + f[i].meters + " bar=" + ArrowProgress.remaining(f[i], now)
                + " road='" + RoadName.current(f[i], now) + "' lanes=" + lanes(f[i]));
        }
        check(f[4].main == 21 && ArrowProgress.remaining(f[4], 5000L) == 40, "4 roundabout 80 m: bar 40% (window 200 m)");
        check(ArrowProgress.remaining(f[5], 6000L) == -1, "5 unknown step: no bar");
        check(f[7].main == 13 && ArrowProgress.remaining(f[7], 8000L) == 55, "7 right 110 m: bar 55%");
        check(f[2].meters == 250 && ArrowProgress.remaining(f[2], 3000L) == -1, "2 250 m: outside the window, no bar");
        boolean noRoad = true;
        for (int i = 0; i < 15; i++) if (RoadName.current(f[i], 1000L * (i + 1)).length() != 0) noRoad = false;
        check(noRoad, "0-14 (no road in 0x8006): no road name");
        // AA 1.1 (A171): road name and lanes from 0x8006
        check(RoadName.current(f[15], 16000L).equals("Wojciecha Cybulskiego"), "15 road name");
        check(lanes(f[15]).equals("0:0/0 1:0/0 2:192/2"), "15 three lanes, the right one preferred (" + lanes(f[15]) + ")");
        check(RoadName.current(f[16], 17000L).equals("Wojciecha Cybulskiego") && f[16].lanes.length == 0, "16 lanes gone, road kept");
        check(RoadName.current(f[17], 18000L).equals("Jedno\u015bci Narodowej"), "17 new road (UTF-8)");
        check(lanes(f[17]).startsWith("0:0/2") && lanes(f[17]).endsWith("1:0/2"), "17 two lanes straight preferred (" + lanes(f[17]) + ")");
        check(RoadName.current(f[18], 19000L).length() == 0, "18 bad UTF-8 road sent empty");
        check(lanes(f[18]).startsWith("0:") && f[18].lanes.length == 2 && f[18].lanes[0].recommendation == 2, "18 u-turn lane preferred (" + lanes(f[18]) + ")");
        check(RoadName.current(f[20], 21000L).equals("Pomorska") && f[20].lanes.length == 0, "20 lanes with no direction: none");
        check(f[21].lanes.length == 0 && RoadName.current(f[21], 22000L).length() == 0, "21 ended: no road, no lanes");
        System.out.println("FAILED CHECKS Java asf: " + fails);
        System.exit(fails == 0 ? 0 : 1);
    }
}
