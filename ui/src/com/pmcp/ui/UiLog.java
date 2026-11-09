/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

import java.io.File;
import java.io.FileOutputStream;

/** Append-only diagnostic log in /ramdisk (RAM, gone at the next start). It stops growing at LIMIT bytes. Never throws. */
final class UiLog {
    static final int LIMIT = 65536;
    static String path = "/ramdisk/pmcp-ui.log";

    private UiLog() {
    }

    static void log(String line) {
        FileOutputStream out = null;
        try {
            File file = new File(path);
            if (file.length() > LIMIT) {
                return;
            }
            out = new FileOutputStream(path, true);
            out.write(new StringBuffer(line).append('\n').toString().getBytes("UTF-8"));
        } catch (Throwable ignored) {
            // diagnostics only
        } finally {
            if (out != null) {
                try {
                    out.close();
                } catch (Throwable ignored) {
                    // diagnostics only
                }
            }
        }
    }

    static void log(String event, String detail) {
        log(new StringBuffer(event).append(' ').append(detail).toString());
    }

    static void log(String event, Throwable error) {
        log(new StringBuffer(event).append(' ').append(String.valueOf(error)).toString());
    }
}
