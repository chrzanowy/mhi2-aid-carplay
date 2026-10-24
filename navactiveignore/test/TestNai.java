/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed.
 * Run with -Xverify:all, the built jar first and the converted stock jar after it. */
import de.vw.mib.navactiveignore.NavActiveIgnore;
import org.dsi.ifc.carplay.AppStateRequest;
import org.dsi.ifc.carplay.ResourceRequest;

public class TestNai {
    static int failures = 0;

    static void check(boolean ok, String what) {
        System.out.println((ok ? "ok   " : "FAIL ") + what);
        if (!ok) failures++;
    }

    public static void main(String[] a) throws Exception {
        String[] patched = {
            "de.esolutions.fw.comm.dsi.carplay.impl.DSICarplayProxy",
            "de.vw.mib.asl.internal.carplay.common.CarPlayModeHandling",
            "de.vw.mib.asl.internal.navigation.api.impl.ASLNavigationServices",
            "de.vw.mib.asl.internal.androidauto.target.NavigationListener",
            "de.vw.mib.asl.internal.androidauto.target.RequestHandler",
        };
        ClassLoader cl = TestNai.class.getClassLoader();
        for (String n : patched) {
            Class c = Class.forName(n, false, cl);
            java.net.URL src = c.getProtectionDomain().getCodeSource().getLocation();
            check(src.toString().endsWith("NavActiveIgnore.jar"), n + " loads from the built jar (" + src + ")");
            c.getDeclaredMethods(); // links and verifies under -Xverify:all
        }

        AppStateRequest claim = new AppStateRequest(2, true, 0);
        AppStateRequest release = new AppStateRequest(2, false, 0);
        AppStateRequest speech = new AppStateRequest(1, true, 0);
        AppStateRequest navSpeech = new AppStateRequest(2, true, 1);

        check(NavActiveIgnore.stripNativeNavClaims(null) == null, "null stays null");
        AppStateRequest[] clean = {release, speech, navSpeech};
        check(NavActiveIgnore.stripNativeNavClaims(clean) == clean, "no claim -> same array");
        AppStateRequest[] mixed = {speech, claim, release};
        AppStateRequest[] s = NavActiveIgnore.stripNativeNavClaims(mixed);
        check(s.length == 2 && s[0] == speech && s[1] == release, "claim removed, order kept");
        AppStateRequest[] only = {claim};
        AppStateRequest[] e = NavActiveIgnore.stripNativeNavClaims(only);
        check(e.length == 0, "only claim -> empty");

        check(!NavActiveIgnore.dropRequest(new ResourceRequest[0], clean, clean), "unchanged request is sent");
        check(NavActiveIgnore.dropRequest(new ResourceRequest[0], only, e), "nothing left -> dropped");
        check(NavActiveIgnore.dropRequest(null, only, e), "null resources, nothing left -> dropped");
        check(!NavActiveIgnore.dropRequest(new ResourceRequest[1], only, e), "resources left -> sent");
        check(!NavActiveIgnore.dropRequest(new ResourceRequest[0], mixed, s), "states left -> sent");

        System.out.println(failures == 0 ? "ALL OK" : failures + " FAILED");
        System.exit(failures == 0 ? 0 : 1);
    }
}
