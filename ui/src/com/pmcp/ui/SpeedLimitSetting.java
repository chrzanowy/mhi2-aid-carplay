/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

/**
 * The native speed-limit mode of package sl, the same file and bytes as "pmcp.sh speedlimit-mode MODE":
 * /mnt/persist/pmcp/native-speedlimit-mode holds exactly "off\n", "turnto\n" or "street\n"; no file means off.
 * The sl reader in the HMI polls that file, so a change shows within about a second, without a restart.
 *
 * The rules of pmcp.sh (installer/template/pmcp.sh.in, do_speedlimit_mode) that can be read from Java, not all of
 * them: pmcp.sh also checks the card, the firmware and the whole unit state (STATE=JAVA); the page relies on the set
 * running in this boot instead:
 *  - off is always allowed (no file: nothing to do);
 *  - turnto and street need package sl in the Java set, turnto also rg; the set must be confirmed (ok.SET), running
 *    this boot (last-boot "set=SET use=yes|trial") and not disabled by the rescue card;
 *  - writes are serialized with pmcp.sh through its lock directory /ramdisk/pmcp-speedlimit.lock (mkdir): when GEM holds
 *    it, nothing is written here;
 *  - the new value is staged in native-speedlimit-mode.pmcp-new, then renamed over the file, then read back.
 */
final class SpeedLimitSetting extends Setting {
    static final String[] MODES = {"off", "turnto", "street"};
    static final String[] LABELS = {"Off", "Before street name", "Street name (trial)"};

    private final String modePath;
    private final String persistPath;
    private final String lockPath;
    private final String bootPath;

    SpeedLimitSetting(String root) {
        persistPath = new StringBuffer(root).append("/mnt/persist/pmcp").toString();
        modePath = new StringBuffer(persistPath).append("/native-speedlimit-mode").toString();
        lockPath = new StringBuffer(root).append("/ramdisk/pmcp-speedlimit.lock").toString();
        bootPath = new StringBuffer(root).append("/mnt/app/carplaymaps/HMI_BOOT").toString();
    }

    String label() {
        return "Speed limit";
    }

    int count() {
        return MODES.length;
    }

    String choice(int i) {
        return LABELS[i];
    }

    String invalidText() {
        return "Invalid file (off)";
    }

    String hint() {
        if (current() < 0) {
            return "The saved mode is not valid: the limit is off. Pick a mode to replace it.";
        }
        // street needs less than turnto (no rg): its reason covers both; otherwise only turnto is blocked
        String street = blocked(2);
        if (street != null) {
            return street;
        }
        String turnto = blocked(1);
        if (turnto != null) {
            return turnto;
        }
        return "Applies within a second and stays after a restart.";
    }

    int current() {
        File file = new File(modePath);
        if (!file.exists()) {
            return 0;
        }
        byte[] data = readSmall(file, 16);
        if (data == null) {
            return -1;
        }
        for (int i = 0; i < MODES.length; i++) {
            if (equalsBytes(data, line(MODES[i]))) {
                return i;
            }
        }
        return -1;
    }

    String blocked(int i) {
        if (i == 0) {
            return null;
        }
        try {
            String boot = firstLine(bootPath);
            if (boot == null || boot.length() == 0) {
                return "Needs the Java packages (package sl), none are on.";
            }
            int space = boot.indexOf(' ');
            String set = space < 0 ? boot : boot.substring(0, space);
            if (set.length() == 0) {
                return "Needs the Java packages (package sl), none are on.";
            }
            if (!hasPackage(set, "sl")) {
                return "Needs package sl: GEM features_advanced, On sl.";
            }
            if (i == 1 && !hasPackage(set, "rg")) {
                return "Before street name needs package rg as well.";
            }
            if (new File(persistPath, "DISABLED").exists()) {
                return "Java packages are disabled by the rescue card.";
            }
            if (!new File(persistPath, new StringBuffer("ok.").append(set).toString()).exists()) {
                return "Save the trial start first: Changes, Save.";
            }
            String last = firstLine(new StringBuffer(persistPath).append("/last-boot").toString());
            String yes = new StringBuffer("set=").append(set).append(" use=yes").toString();
            String trial = new StringBuffer("set=").append(set).append(" use=trial").toString();
            if (!yes.equals(last) && !trial.equals(last)) {
                return "The Java set changed: restart the unit first.";
            }
            return null;
        } catch (Throwable error) {
            UiLog.log("SPEEDLIMIT_CHECK_FAILED", error);
            return "Cannot read the package state.";
        }
    }

    String select(int i) throws Exception {
        if (i < 0 || i >= MODES.length) {
            throw new IllegalArgumentException("Unknown choice.");
        }
        // The lock is held across the fsync below, on the HMI thread (milliseconds). If the HMI dies inside that window
        // the directory stays until the next unit start (/ramdisk is RAM) and GEM speed-limit and package actions, also
        // main 4, answer SPEEDLIMIT_LOCK_BUSY until then (ui/README.md).
        File lock = new File(lockPath);
        if (!lock.mkdir()) {
            throw new IllegalStateException("Busy: a GEM action is running. Try again.");
        }
        try {
            String reason = blocked(i);
            if (reason != null) {
                throw new IllegalStateException(reason);
            }
            File file = new File(modePath);
            if (i == 0 && !file.exists()) {
                UiLog.log("SPEEDLIMIT_MODE_OK off (no configuration file)");
                return "Off.";
            }
            File persist = new File(persistPath);
            if (!persist.isDirectory()) {
                throw new IllegalStateException("Persist directory missing.");
            }
            if (file.isDirectory()) {
                throw new IllegalStateException("Mode path is a directory.");
            }
            byte[] data = line(MODES[i]);
            File staged = new File(new StringBuffer(modePath).append(".pmcp-new").toString());
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
                if (!equalsBytes(readSmall(staged, 16), data)) {
                    throw new IllegalStateException("Staged file did not read back.");
                }
                if (!staged.renameTo(file)) {
                    throw new IllegalStateException("Could not save the mode.");
                }
                renamed = true;
            } finally {
                if (!renamed) {
                    // as the trap in pmcp.sh: no staged file stays behind, the saved mode is unchanged
                    staged.delete();
                }
            }
            if (!equalsBytes(readSmall(file, 16), data)) {
                throw new IllegalStateException("Saved file did not read back.");
            }
            UiLog.log("SPEEDLIMIT_MODE_OK", MODES[i]);
            return "Saved. Applies within a second and stays after a restart.";
        } finally {
            lock.delete();
        }
    }

    /** True when the set id ("name-sha8" parts joined by "+") holds package name, exactly as pmcp.sh current_set. */
    static boolean hasPackage(String set, String name) {
        int start = 0;
        while (start <= set.length()) {
            int plus = set.indexOf('+', start);
            String part = plus < 0 ? set.substring(start) : set.substring(start, plus);
            int dash = part.lastIndexOf('-');
            String id = dash < 0 ? part : part.substring(0, dash);
            if (id.equals(name)) {
                return true;
            }
            if (plus < 0) {
                return false;
            }
            start = plus + 1;
        }
        return false;
    }

    static byte[] line(String mode) {
        byte[] text = mode.getBytes();
        byte[] data = new byte[text.length + 1];
        System.arraycopy(text, 0, data, 0, text.length);
        data[text.length] = '\n';
        return data;
    }

    static boolean equalsBytes(byte[] a, byte[] b) {
        if (a == null || b == null || a.length != b.length) {
            return false;
        }
        for (int i = 0; i < a.length; i++) {
            if (a[i] != b[i]) {
                return false;
            }
        }
        return true;
    }

    /** The whole file when it is a regular file of at most max bytes, else null. */
    static byte[] readSmall(File file, int max) {
        if (!file.isFile() || file.length() > max) {
            return null;
        }
        FileInputStream in = null;
        try {
            in = new FileInputStream(file);
            byte[] buffer = new byte[max + 1];
            int total = 0;
            while (total < buffer.length) {
                int n = in.read(buffer, total, buffer.length - total);
                if (n < 0) {
                    break;
                }
                total += n;
            }
            if (total > max) {
                return null;
            }
            byte[] data = new byte[total];
            System.arraycopy(buffer, 0, data, 0, total);
            return data;
        } catch (Throwable error) {
            return null;
        } finally {
            if (in != null) {
                try {
                    in.close();
                } catch (Throwable ignored) {
                    // read only
                }
            }
        }
    }

    /** First line of a small text file (at most 512 bytes), without the newline; null when missing or larger. */
    static String firstLine(String path) {
        byte[] data = readSmall(new File(path), 512);
        if (data == null) {
            return null;
        }
        int end = 0;
        while (end < data.length && data[end] != '\n') {
            end++;
        }
        try {
            return new String(data, 0, end, "ISO-8859-1");
        } catch (Throwable error) {
            return null;
        }
    }
}
