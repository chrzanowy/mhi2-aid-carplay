/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

import java.io.File;
import java.io.FileOutputStream;

/**
 * Android Auto output (AA 1.0): which writer takes the phone's map to the AID, the same line as "pmcp.sh aa-output
 * direct|ring" (installer/template/pmcp.sh.in aa_extra_set):
 *  - /mnt/persist/pmcp/aa-extra.conf: the first PMCP_AA_OUTPUT= line is replaced by PMCP_AA_OUTPUT=direct|ring, the first
 *    PMCP_AA_CAPTURE_S= line is kept, nothing else (the feeder reads only these two keys); the new file is written as
 *    aa-extra.conf.pmcp-new, synced, then renamed over the file;
 *  - no trial and no marker change (user decision "1 przelaczasz odrazu"): the feeder reads the file at each AA
 *    connection, so the choice applies from the next one (unplug and plug the phone);
 *  - the saved value counts only when it is exactly "direct" or "ring" (trailing blanks/CR ignored), as feeder v14;
 *    anything else, or no line, is the default: direct.
 * Only for the Google Maps on the AID mode (AA_BOOT "gamma-..."), not after the rescue card or with AA switched off.
 */
final class AaOutputSetting extends Setting {
    static final String[] VALUES = {"direct", "ring"};
    static final String[] LABELS = {"pmcp MOST writer (default)", "CarPlay bridge (fallback)"};

    private final String persist;
    private final String conf;
    private final String aaBoot;
    private final String aaLast;

    AaOutputSetting(String root) {
        persist = new StringBuffer(root).append("/mnt/persist/pmcp").toString();
        conf = new StringBuffer(persist).append("/aa-extra.conf").toString();
        aaBoot = new StringBuffer(root).append("/mnt/app/carplaymaps/aa/AA_BOOT").toString();
        aaLast = new StringBuffer(root).append("/ramdisk/pmcp-aa-last").toString();
    }

    String label() {
        return "Android Auto output";
    }

    int count() {
        return VALUES.length;
    }

    String choice(int i) {
        return LABELS[i];
    }

    String invalidText() {
        return "Android Auto off";
    }

    int current() {
        if (reason() != null) {
            return -1;
        }
        String saved = savedOutput();
        return "ring".equals(saved) ? 1 : 0;
    }

    String blocked(int i) {
        return reason();
    }

    String hint() {
        return null;
    }

    String select(int i) throws Exception {
        if (i < 0 || i >= VALUES.length) {
            throw new IllegalArgumentException("Unknown choice.");
        }
        String why = reason();
        if (why != null) {
            throw new IllegalStateException(why);
        }
        File persistDir = new File(persist);
        if (!persistDir.isDirectory()) {
            throw new IllegalStateException("Persist directory missing.");
        }
        String output = null;
        String capture = null;
        byte[] old = SpeedLimitSetting.readSmall(new File(conf), 4096);
        if (old != null) {
            String[] lines = split(new String(old, "ISO-8859-1"));
            for (int k = 0; k < lines.length; k++) {
                if (output == null && lines[k].startsWith("PMCP_AA_OUTPUT=")) {
                    output = lines[k];
                }
                if (capture == null && lines[k].startsWith("PMCP_AA_CAPTURE_S=")) {
                    capture = lines[k];
                }
            }
        }
        StringBuffer text = new StringBuffer("# pmcp: AA switches (settings page)\n");
        text.append("PMCP_AA_OUTPUT=").append(VALUES[i]).append('\n');
        if (capture != null) {
            text.append(capture).append('\n');
        }
        byte[] data = text.toString().getBytes("ISO-8859-1");
        File staged = new File(new StringBuffer(conf).append(".pmcp-new").toString());
        File target = new File(conf);
        if (staged.exists() && !staged.delete()) {
            throw new IllegalStateException("Cannot remove the old staged file.");
        }
        boolean renamed = false;
        try {
            FileOutputStream out = new FileOutputStream(staged);
            try {
                out.write(data);
                out.getFD().sync();
            } finally {
                out.close();
            }
            if (!SpeedLimitSetting.equalsBytes(SpeedLimitSetting.readSmall(staged, 4096), data)) {
                throw new IllegalStateException("Staged file did not read back.");
            }
            if (!staged.renameTo(target)) {
                throw new IllegalStateException("Could not save.");
            }
            renamed = true;
        } finally {
            if (!renamed) {
                staged.delete();
            }
        }
        if (!VALUES[i].equals(savedOutput())) {
            throw new IllegalStateException("Saved file did not read back.");
        }
        UiLog.log("AA_OUTPUT_OK", VALUES[i]);
        return "Saved. Applies at the next phone connection (unplug and plug the phone).";
    }

    /** null when the row can be used now, otherwise why not (also the reason the value shows "Android Auto off"). */
    String reason() {
        try {
            String set = SpeedLimitSetting.firstLine(aaBoot);
            if (set == null || !set.startsWith("gamma-")) {
                return "Android Auto from pmcp is not installed (GEM 3. Install Android Auto).";
            }
            if (new File(persist, "DISABLED").exists() || new File(persist, "AA_DISABLED").exists()) {
                return "Android Auto from pmcp is switched off.";
            }
            return null;
        } catch (Throwable error) {
            UiLog.log("AA_OUTPUT_CHECK_FAILED", error);
            return "Cannot read the Android Auto state.";
        }
    }

    String valueText() {
        String why = reason();
        if (why != null) {
            return invalidText();
        }
        String text = choice(current());
        String last = SpeedLimitSetting.firstLine(aaLast);
        if (last != null && last.indexOf(" use=no") >= 0) {
            return new StringBuffer(text).append(" (AA not active this start)").toString();
        }
        return text;
    }

    /** The output the feeder takes from aa-extra.conf: the first exact direct|ring value, else null. */
    String savedOutput() {
        byte[] data = SpeedLimitSetting.readSmall(new File(conf), 4096);
        if (data == null) {
            return null;
        }
        try {
            String[] lines = split(new String(data, "ISO-8859-1"));
            for (int k = 0; k < lines.length; k++) {
                if (!lines[k].startsWith("PMCP_AA_OUTPUT=")) {
                    continue;
                }
                String value = trimEnd(lines[k].substring("PMCP_AA_OUTPUT=".length()));
                if ("direct".equals(value) || "ring".equals(value)) {
                    return value;
                }
            }
        } catch (Throwable error) {
            UiLog.log("AA_OUTPUT_READ_FAILED", error);
        }
        return null;
    }

    private static String trimEnd(String value) {
        int end = value.length();
        while (end > 0) {
            char c = value.charAt(end - 1);
            if (c != ' ' && c != '\t' && c != '\r') {
                break;
            }
            end--;
        }
        return value.substring(0, end);
    }

    /** Lines without their "\n". */
    private static String[] split(String text) {
        java.util.Vector parts = new java.util.Vector();
        int start = 0;
        while (start < text.length()) {
            int nl = text.indexOf('\n', start);
            if (nl < 0) {
                parts.addElement(text.substring(start));
                break;
            }
            parts.addElement(text.substring(start, nl));
            start = nl + 1;
        }
        String[] out = new String[parts.size()];
        parts.copyInto(out);
        return out;
    }
}
