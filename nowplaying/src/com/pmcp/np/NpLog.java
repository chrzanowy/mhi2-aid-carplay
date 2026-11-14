/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.np;

/**
 * Android Auto track events, one line each, in /ramdisk/pmcp-aa-np.log (300 lines, then .1), so that "AA save log"
 * shows whether the stock DSI tells us when an Android Auto session ends (review A176: the AA title is not cleared
 * between sessions). Only lengths and flags, never the title / artist / album text. /ramdisk is gone at the next
 * start, so no persistent file is added. Nothing here throws. Java 1.2 clean: StringBuffer, no string concatenation.
 */
final class NpLog {
    static final String LOG = "/ramdisk/pmcp-aa-np.log";
    static final int MAX_LINES = 300;
    static String logPath = LOG;   // tests
    private static long t0;
    private static int lines;

    private NpLog() {
    }

    /** event name and up to three numbers (-1 = left out). */
    static synchronized void log(String what, int a, int b, int c) {
        java.io.FileOutputStream f = null;
        try {
            long now = System.currentTimeMillis();
            if (t0 == 0L) {
                t0 = now;
            }
            if (lines >= MAX_LINES) {
                java.io.File cur = new java.io.File(logPath);
                java.io.File old = new java.io.File(logPath.concat(".1"));
                old.delete();
                cur.renameTo(old);
                lines = 0;
            }
            StringBuffer s = new StringBuffer(80);
            s.append("t_ms=").append(now - t0).append(' ').append(what);
            if (a != -1) {
                s.append(' ').append(a);
            }
            if (b != -1) {
                s.append(' ').append(b);
            }
            if (c != -1) {
                s.append(' ').append(c);
            }
            s.append('\n');
            f = new java.io.FileOutputStream(logPath, true);
            f.write(s.toString().getBytes());
            lines++;
        } catch (Throwable x) {
            // diagnostics only
        } finally {
            if (f != null) {
                try {
                    f.close();
                } catch (Throwable x) {
                    // ignore
                }
            }
        }
    }
}
