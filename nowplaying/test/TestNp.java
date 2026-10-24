/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed.
 * Run with -Xverify:all, the built jar first and the converted stock jar after it. */
package com.pmcp.np;

import de.vw.mib.bap.mqbab2.generated.audiosd.serializer.CurrentStationInfo_Status;
import org.dsi.ifc.carplay.TrackData;

public class TestNp {
    static int failures = 0;

    static void check(boolean ok, String what) {
        System.out.println((ok ? "ok   " : "FAIL ") + what);
        if (!ok) failures++;
    }

    public static void main(String[] a) throws Exception {
        String[] patched = {
            "de.vw.mib.asl.internal.carplay.target.HsmTarget",
            "de.vw.mib.bap.mqbab2.audiosd.functions.CurrentStationInfo",
        };
        for (int i = 0; i < patched.length; i++) {
            Class c = Class.forName(patched[i], false, TestNp.class.getClassLoader());
            String src = c.getProtectionDomain().getCodeSource().getLocation().toString();
            check(src.endsWith("pmcp-np.jar"), patched[i] + " loads from the built jar");
            c.getDeclaredMethods();
        }

        // before any track: stock behaviour
        CurrentStationInfo_Status st = new CurrentStationInfo_Status();
        check(!NowPlaying.fill(2, st), "no track yet -> stock");

        // invalid flag is ignored (treated as empty)
        NowPlaying.onTrack(new TrackData("Song", 100, "Album", "Artist", "", ""), 0);
        check(!NowPlaying.fill(2, st), "invalid data -> stock");

        NowPlaying.onTrack(new TrackData("  Song  ", 100, "Album", "Artist", "", ""), 1);
        String[] s = NowPlaying.snapshot();
        check(s[0].equals("Song") && s[1].equals("Artist") && s[2].equals("Album"), "stored and trimmed");
        check(!NowPlaying.fill(3, st), "Android Auto (3) -> stock");
        check(!NowPlaying.fill(1, st), "MirrorLink (1) -> stock");
        check(NowPlaying.fill(2, st), "CarPlay (2) with a title -> filled");
        check(st.pi_Type == 72 && st.si_Type == 73 && st.ti_Type == 74 && st.qi_Type == 0 && st.pi_Id == 0, "types 72/73/74");

        CurrentStationInfo_Status st2 = new CurrentStationInfo_Status();
        NowPlaying.onTrack(new TrackData("Only title", 0, null, null, null, null), 1);
        check(NowPlaying.fill(2, st2) && st2.si_Type == 0 && st2.ti_Type == 0, "missing artist/album -> type 0");

        StringBuffer longTitle = new StringBuffer();
        for (int i = 0; i < 200; i++) longTitle.append('x');
        NowPlaying.onTrack(new TrackData(longTitle.toString(), 0, "", "", "", ""), 1);
        check(NowPlaying.snapshot()[0].length() == 80, "long title capped at 80");

        NowPlaying.onTrack(null, 1);
        check(!NowPlaying.fill(2, new CurrentStationInfo_Status()), "null track -> stock");

        // refresh without a BAP APIFactory must not throw
        NowPlaying.refresh();
        check(true, "refresh without BAP runtime is silent");
        NowPlaying.attach(null);
        check(true, "attach(null) is silent");

        System.out.println(failures == 0 ? "ALL OK" : failures + " FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }
}
