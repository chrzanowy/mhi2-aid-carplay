/* SPDX-License-Identifier: GPL-3.0-or-later. Host test of com.pmcp.kv.KombiView (A166). */
package com.pmcp.kv;

public final class TestKombiView {
    static int fails;
    static void check(boolean ok, String what) { System.out.println((ok ? "ok    " : "FAILED ") + what); if (!ok) fails++; }

    static String read(String p) throws Exception {
        java.io.File f = new java.io.File(p);
        if (!f.exists()) return "";
        byte[] b = new byte[(int) f.length()];
        java.io.FileInputStream in = new java.io.FileInputStream(f);
        try { int n = 0; while (n < b.length) { int k = in.read(b, n, b.length - n); if (k < 0) break; n += k; } } finally { in.close(); }
        return new String(b);
    }

    public static void main(String[] a) throws Exception {
        String p = a[0];
        KombiView.logPath = p;
        check(KombiView.mapShown() == -1, "no data rate yet: unknown");
        KombiView.onDataRate(2, 1);
        check(KombiView.mapShown() == 1, "rate 2: map shown");
        KombiView.onMapVisibility(1);
        KombiView.onDataRate(0, 1);
        check(KombiView.mapShown() == 0, "rate 0: no map");
        KombiView.onDataRate(1, 1);
        check(KombiView.mapShown() == 0, "rate 1 (reduced): no map");
        KombiView.onRgTypeSetGet(new de.vw.mib.bap.mqbab2.generated.navsd.serializer.ActiveRgType_SetGet());
        KombiView.onRgTypeSetGet("not an entity");
        String s = read(p);
        check(s.indexOf("data_rate=2 valid=1 | rate=2 visible=-1") >= 0, "data rate line with the state");
        check(s.indexOf("map_visible_1110045=1 | rate=2 visible=1") >= 0, "1110045 line");
        check(s.indexOf("activergtype_request=0") >= 0 && s.indexOf("activergtype_request_unreadable") >= 0, "ActiveRgType lines");
        for (int i = 0; i < KombiView.MAX_LINES + 10; i++) KombiView.onDataRate(i % 3, 1);
        String cur = read(p), old = read(p + ".1");
        int nCur = cur.split("\n").length, nOld = old.split("\n").length;
        check(old.length() > 0 && nOld == KombiView.MAX_LINES && nCur <= 20, "rotation at " + KombiView.MAX_LINES + " lines (" + nOld + "/" + nCur + ")");
        KombiView.logPath = "/nonexistent-dir/x.log";
        KombiView.onDataRate(2, 1);
        check(KombiView.mapShown() == 1, "unwritable log: state still kept, nothing thrown");
        System.out.println(fails == 0 ? "KOMBI_VIEW_PASS" : "KOMBI_VIEW_FAIL " + fails);
        if (fails != 0) System.exit(1);
    }
}
