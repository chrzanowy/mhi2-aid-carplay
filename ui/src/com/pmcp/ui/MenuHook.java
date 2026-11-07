/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.ui;

import de.vw.mib.view.internal.AbstractViewHandler;
import de.vw.mib.widgets.models.ViewModel;
import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.Hashtable;

/**
 * Entry points called from the factory AbstractViewHandler (ui/patcher/PatchMenuHook.java). Every view of the HMI
 * passes through them, so the work for a view that is not ours is one name compare (attach) or one empty-table test.
 * Each call site in the factory class is also wrapped in catch (Throwable) by the patcher: nothing from here, not even
 * a missing class, reaches the HMI.
 *
 *   init(boolean) start-> attach   (widget tree built, before the factory View.init; also after deinit -> init
 *                                    without a new setup, which the factory does on some screen-area paths)
 *   activate()    end  -> refresh
 *   deinit()      end  -> detach
 *   destroy()     end  -> detach
 *   fatalError()  start-> failure
 *
 * Switches: /tmp/pmcp-ui-off (RAM) keeps every view factory until the next start; a lifecycle error in our view sets it
 * and puts the factory widget tree back at once (also a factory lifecycle-order message counts: safe side).
 * GEM "Off ui" removes the package.
 */
public final class MenuHook {
    static final String VIEW_NAME = "SMI_SETUP_MAIN";
    static String offSwitch = "/tmp/pmcp-ui-off";
    static String root = "";
    private static final Hashtable PAGES = new Hashtable();
    private static boolean disabled;

    private MenuHook() {
    }

    static Setting[] settings() {
        return new Setting[] {new SpeedLimitSetting(root)};
    }

    public static void attach(AbstractViewHandler handler) {
        try {
            if (disabled) {
                return;
            }
            ViewModel view = handler.getView();
            if (view == null || !VIEW_NAME.equals(view.get_name()) || PAGES.containsKey(handler)) {
                return;
            }
            if (new File(offSwitch).exists()) {
                UiLog.log("OFF_SWITCH present, view stays factory");
                return;
            }
            SettingsPage page = new SettingsPage(view, settings());
            page.attach();
            PAGES.put(handler, page);
        } catch (Throwable error) {
            UiLog.log("ATTACH_FAILED view stays factory:", error);
        }
    }

    public static void refresh(AbstractViewHandler handler) {
        if (PAGES.isEmpty()) {
            return;
        }
        try {
            SettingsPage page = (SettingsPage) PAGES.get(handler);
            if (page != null) {
                page.activated();
            }
        } catch (Throwable error) {
            UiLog.log("REFRESH_FAILED", error);
        }
    }

    public static void detach(AbstractViewHandler handler) {
        if (PAGES.isEmpty()) {
            return;
        }
        try {
            SettingsPage page = (SettingsPage) PAGES.remove(handler);
            if (page != null) {
                page.detach();
            }
        } catch (Throwable error) {
            UiLog.log("DETACH_FAILED", error);
        }
    }

    /**
     * A lifecycle error in a view that has our page: the factory tree back now (the factory code rethrows or goes on
     * with its own widgets only), no page again until the next start, and the stack in the log.
     */
    public static void failure(AbstractViewHandler handler, RuntimeException error) {
        try {
            if (PAGES.isEmpty() || !PAGES.containsKey(handler)) {
                return;
            }
            disabled = true;
            SettingsPage page = (SettingsPage) PAGES.remove(handler);
            if (page != null) {
                page.detach();
            }
            FileOutputStream marker = new FileOutputStream(offSwitch);
            marker.close();
            StringWriter text = new StringWriter();
            error.printStackTrace(new PrintWriter(text));
            UiLog.log("VIEW_LIFECYCLE_FAILURE page off until restart:", text.toString());
        } catch (Throwable ignored) {
            // diagnostics only
        }
    }

    // ---- host tests ----

    static int attachedCount() {
        return PAGES.size();
    }

    static SettingsPage pageOf(AbstractViewHandler handler) {
        return (SettingsPage) PAGES.get(handler);
    }

    static void resetForTest() {
        PAGES.clear();
        disabled = false;
    }
}
