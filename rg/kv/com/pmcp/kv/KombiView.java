/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.kv;

/**
 * Which view the AID shows (A165/A166: AA 1.1 shows road, lanes, distance and ETA only while the AID does not show the
 * map, because Google Maps draws them in the map picture). Three stock entry points call in (rg/patcher/PatchKombiView,
 * every call guarded):
 *   ChangeDataRate.dsiKOMOGfxStreamSinkUpdateDataRate(rate, valid)  MOST stream-sink data rate from the cluster:
 *                                                                    0 off, 1 reduced, 2 full (= map view, inferred)
 *   MapViewerKombiNotifierModel.notifyKombiMapVisible/Invisible     datapool 1110045 as the VW map viewer reports it
 *   ActiveRgType.setGetProperty(entity)                              the cluster's own ActiveRgType request
 * Each call is one line in /ramdisk/pmcp-kombi-view.log (500 lines, then .1), so a drive shows which of them follows
 * the driver's view switches. Nothing here throws; J9 CDC 1.1 API only (StringBuffer, no StringBuilder).
 */
public final class KombiView {
    static final String LOG = "/ramdisk/pmcp-kombi-view.log";
    static final int MAX_LINES = 500;
    private static volatile int rate = -1, rateValid = -1, visible = -1, rgRequest = -1;
    private static long t0;
    private static int lines;
    static String logPath = LOG;   // tests

    private KombiView() {}

    public static void onDataRate(int r, int valid) {
        rate = r; rateValid = valid;
        log("data_rate", r, valid);
    }

    public static void onMapVisibility(int v) {
        visible = v;
        log("map_visible_1110045", v, -1);
    }

    public static void onRgTypeSetGet(Object entity) {
        try {
            int t = ((de.vw.mib.bap.mqbab2.generated.navsd.serializer.ActiveRgType_SetGet) entity).rgtype;
            rgRequest = t;
            log("activergtype_request", t, -1);
        } catch (Throwable x) {
            log("activergtype_request_unreadable", -1, -1);
        }
    }

    /** 1 = the AID shows the map (data rate full), 0 = it does not, -1 = no data rate seen yet. */
    public static int mapShown() {
        int r = rate;
        return r < 0 ? -1 : (r == 2 ? 1 : 0);
    }

    public static int dataRate() { return rate; }
    public static int mapVisibility() { return visible; }
    public static int rgTypeRequest() { return rgRequest; }

    static synchronized void log(String what, int a, int b) {
        java.io.FileOutputStream f = null;
        try {
            long now = System.currentTimeMillis();
            if (t0 == 0L) t0 = now;
            if (lines >= MAX_LINES) {
                java.io.File cur = new java.io.File(logPath), old = new java.io.File(logPath.concat(".1"));
                old.delete();
                cur.renameTo(old);
                lines = 0;
            }
            StringBuffer s = new StringBuffer(96);
            s.append("t_ms=").append(now - t0).append(" wall_ms=").append(now).append(' ').append(what).append('=').append(a);
            if (b != -1) s.append(" valid=").append(b);
            s.append(" | rate=").append(rate).append(" visible=").append(visible).append(" rg_request=").append(rgRequest);
            s.append('\n');
            f = new java.io.FileOutputStream(logPath, true);
            f.write(s.toString().getBytes());
            lines++;
        } catch (Throwable x) {
            // diagnostics only
        } finally {
            if (f != null) try { f.close(); } catch (Throwable x) { }
        }
    }
}
