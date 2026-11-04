/* SPDX-License-Identifier: GPL-3.0-or-later
 * rg_test's step-N.bin through the staged rgluasf(a) classes (lanes-uturn-asf[-aa] guidance-src): the same frames as
 * TestAaRg, plus the bargraph (ArrowProgress) and road name (RoadName) on hook output. */
package com.cpmap.rgi;

import java.nio.file.*;

public final class TestAaRgAsf {
    static int fails;
    static void check(boolean c, String m) { System.out.println((c ? "ok     " : "FAILED ") + m); if (!c) fails++; }
    public static void main(String[] a) throws Exception {
        String dir = a[0];
        Path cur = Paths.get(dir, "cur-asf.bin");
        MailboxReader r = new MailboxReader(cur.toString());
        LiveModel.Frame[] f = new LiveModel.Frame[15];
        for (int i = 0; i < 15; i++) {
            Files.copy(Paths.get(dir, "step-" + i + ".bin"), cur, StandardCopyOption.REPLACE_EXISTING);
            long now = 1000L * (i + 1);
            f[i] = r.next(now);
            if (f[i] == null) f[i] = r.model.frame();
            System.out.println("asf step " + i + ": main=" + f[i].main + " m=" + f[i].meters + " bar=" + ArrowProgress.remaining(f[i], now)
                + " road='" + RoadName.current(f[i], now) + "'");
        }
        check(f[4].main == 21 && ArrowProgress.remaining(f[4], 5000L) == 40, "4 roundabout 80 m: bar 40% (window 200 m)");
        check(ArrowProgress.remaining(f[5], 6000L) == -1, "5 unknown step: no bar");
        check(f[7].main == 13 && ArrowProgress.remaining(f[7], 8000L) == 55, "7 right 110 m: bar 55%");
        check(f[2].meters == 250 && ArrowProgress.remaining(f[2], 3000L) == -1, "2 250 m: outside the window, no bar");
        boolean noRoad = true;
        for (int i = 0; i < 15; i++) if (RoadName.current(f[i], 1000L * (i + 1)).length() != 0) noRoad = false;
        check(noRoad, "no road name from AA");
        System.out.println("FAILED CHECKS Java asf: " + fails);
        System.exit(fails == 0 ? 0 : 1);
    }
}
