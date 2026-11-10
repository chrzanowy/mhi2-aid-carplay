/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

import java.io.File;
import java.io.FileOutputStream;

/**
 * "Save changes" on the unit: the same as GEM main menu "5. Confirm" (pmcp.sh do_confirm), without the SD card.
 *
 * After a change from the card (new Java set, new Android Auto set) the first start is a trial. If the user does not
 * save during that start, the next restart loads none of our JARs (lsd.sh), not the previously saved set. The
 * markers and rules are those of pmcp.sh java_confirm_try / aa_confirm_try:
 *  - Java set SET (first word of carplaymaps/HMI_BOOT): not disabled by the rescue card, ok.SET missing, trial.SET
 *    present and last-boot exactly "set=SET use=trial" (lsd.sh wrote it in this start) -> touch ok.SET;
 *  - Android Auto set AA (carplaymaps/aa/AA_BOOT): aa-ok.AA missing, aa-trial.AA present and the RAM marker
 *    /ramdisk/pmcp-aa-trial.AA of this start present -> remove other aa-ok.*, touch aa-ok.AA.
 * pmcp.sh also checks the card, the firmware and the installed files (detect_state); the page cannot, and relies on the
 * trial that lsd.sh and the AA wrapper started in this boot. Each marker file is synced (FileDescriptor.sync) and
 * checked; the directory entry is not (pmcp.sh runs a file-system sync): a power cut right after Save can lose the
 * marker, and then the next start is factory, the safe side.
 */
final class TrialSetting extends Setting {
    private final String persist;
    private final String hmiBoot;
    private final String aaBoot;
    private final String ramdisk;

    TrialSetting(String root) {
        persist = new StringBuffer(root).append("/mnt/persist/pmcp").toString();
        hmiBoot = new StringBuffer(root).append("/mnt/app/carplaymaps/HMI_BOOT").toString();
        aaBoot = new StringBuffer(root).append("/mnt/app/carplaymaps/aa/AA_BOOT").toString();
        ramdisk = new StringBuffer(root).append("/ramdisk").toString();
    }

    String label() {
        return "Changes";
    }

    int count() {
        return 1;
    }

    String choice(int i) {
        return "Save: everything works";
    }

    int current() {
        return -1;
    }

    String invalidText() {
        return valueText();
    }

    String valueText() {
        try {
            if (javaPending() != null || aaPending() != null) {
                return "Not saved (trial start)";
            }
            if (new File(persist, "DISABLED").exists()) {
                return "Off (rescue card)";
            }
            String set = firstWord(SpeedLimitSetting.firstLine(hmiBoot));
            if (set != null && !new File(persist, new StringBuffer("ok.").append(set).toString()).exists()) {
                return "Not saved (restart first)";
            }
            String aa = firstWord(SpeedLimitSetting.firstLine(aaBoot));
            if (aa != null && !new File(persist, new StringBuffer("aa-ok.").append(aa).toString()).exists()) {
                return new File(persist, new StringBuffer("aa-trial.").append(aa).toString()).exists()
                        ? "Android Auto not saved" : "Android Auto: connect the phone";
            }
            return "Saved";
        } catch (Throwable error) {
            return "Unknown";
        }
    }

    String blocked(int i) {
        try {
            if (javaPending() != null || aaPending() != null) {
                return null;
            }
            if (new File(persist, "DISABLED").exists()) {
                return "Switched off by the rescue card: GEM 6. Try again, then restart.";
            }
            String aa = firstWord(SpeedLimitSetting.firstLine(aaBoot));
            if (aa != null && !new File(persist, new StringBuffer("aa-ok.").append(aa).toString()).exists()) {
                return new File(persist, new StringBuffer("aa-trial.").append(aa).toString()).exists()
                        ? "Android Auto trial was not saved: GEM 6. Try again, then restart."
                        : "Android Auto: connect the phone; that start is its trial, then save here.";
            }
            return "Nothing to save: no trial start now.";
        } catch (Throwable error) {
            UiLog.log("TRIAL_CHECK_FAILED", error);
            return "Cannot read the trial state.";
        }
    }

    String hint() {
        try {
            if (javaPending() != null || aaPending() != null) {
                return "Trial start: if all works, save under Changes. Otherwise the next restart goes back.";
            }
        } catch (Throwable error) {
            UiLog.log("TRIAL_CHECK_FAILED", error);
        }
        return null;
    }

    String select(int i) throws Exception {
        String reason = blocked(i);
        if (reason != null) {
            throw new IllegalStateException(reason);
        }
        int saved = 0;
        String set = javaPending();
        if (set != null) {
            File ok = new File(persist, new StringBuffer("ok.").append(set).toString());
            touch(ok);
            appendBootLog(new StringBuffer("page-ok set=").append(set).toString());
            UiLog.log("JAVA_CONFIRM_OK", set);
            saved++;
        }
        String aa = aaPending();
        if (aa != null) {
            try {
                saveAa(aa);
            } catch (Throwable error) {
                UiLog.log("AA_CONFIRM_FAILED", error);
                if (saved > 0) {
                    return "CarPlay saved. Android Auto NOT saved: try again or GEM 5. Confirm.";
                }
                throw new IllegalStateException("Could not save.");
            }
            saved++;
        }
        if (saved == 0) {
            throw new IllegalStateException("Nothing to save: no trial start now.");
        }
        return "Saved. These settings now load on every start.";
    }

    /** As aa_confirm_try: only this set's aa-ok marker stays. */
    private void saveAa(String aa) throws Exception {
        String keep = new StringBuffer("aa-ok.").append(aa).toString();
        String[] names = new File(persist).list();
        for (int k = 0; names != null && k < names.length; k++) {
            if (names[k].startsWith("aa-ok.") && !names[k].equals(keep)) {
                new File(persist, names[k]).delete();
            }
        }
        touch(new File(persist, keep));
        UiLog.log("AA_CONFIRM_OK", aa);
    }

    /** The Java set in its trial start now, else null. */
    String javaPending() {
        String set = firstWord(SpeedLimitSetting.firstLine(hmiBoot));
        if (set == null || new File(persist, "DISABLED").exists()) {
            return null;
        }
        if (new File(persist, new StringBuffer("ok.").append(set).toString()).exists()
                || !new File(persist, new StringBuffer("trial.").append(set).toString()).exists()) {
            return null;
        }
        String last = SpeedLimitSetting.firstLine(new StringBuffer(persist).append("/last-boot").toString());
        return new StringBuffer("set=").append(set).append(" use=trial").toString().equals(last) ? set : null;
    }

    /** The Android Auto set in its trial start now, else null. */
    String aaPending() {
        String aa = firstWord(SpeedLimitSetting.firstLine(aaBoot));
        if (aa == null || new File(persist, "DISABLED").exists()) {
            return null;
        }
        if (new File(persist, new StringBuffer("aa-ok.").append(aa).toString()).exists()
                || !new File(persist, new StringBuffer("aa-trial.").append(aa).toString()).exists()
                || !new File(ramdisk, new StringBuffer("pmcp-aa-trial.").append(aa).toString()).exists()) {
            return null;
        }
        return aa;
    }

    private static String firstWord(String line) {
        if (line == null) {
            return null;
        }
        int space = line.indexOf(' ');
        String word = space < 0 ? line : line.substring(0, space);
        // a set id is a file-name part: never a path
        if (word.length() == 0 || word.indexOf('/') >= 0 || word.startsWith(".")) {
            return null;
        }
        return word;
    }

    private static void touch(File file) throws Exception {
        FileOutputStream out = new FileOutputStream(file, true);
        try {
            out.getFD().sync();
        } finally {
            out.close();
        }
        if (!file.isFile()) {
            throw new IllegalStateException("Could not save.");
        }
    }

    private void appendBootLog(String line) {
        FileOutputStream out = null;
        try {
            out = new FileOutputStream(new StringBuffer(persist).append("/boot.log").toString(), true);
            out.write(new StringBuffer(line).append('\n').toString().getBytes("ISO-8859-1"));
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
}
