/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed on the unit. */
package com.pmcp.ui;

import de.vw.mib.widgets.View;

/**
 * Run with the patched AbstractViewHandler but WITHOUT the com.pmcp.ui helper classes on the class path (as if the
 * JAR were damaged or half loaded): every hooked lifecycle method must still finish normally, the VM's
 * NoClassDefFoundError at each call site caught by the guard.
 */
public final class TestNoHelper {
    public static void main(String[] args) throws Exception {
        boolean helperPresent;
        try {
            Class.forName("com.pmcp.ui.MenuHook");
            helperPresent = true;
        } catch (ClassNotFoundException expected) {
            helperPresent = false;
        }
        if (helperPresent) {
            throw new IllegalStateException("FAIL MenuHook must not be on the class path for this test");
        }
        HostRuntime.installServices();
        View view = new View();
        view.set_name("SMI_SETUP_MAIN");
        Object handler = HostRuntime.createdHandler(view);
        HostRuntime.call(handler, "setup");
        HostRuntime.init(handler);
        HostRuntime.call(handler, "activate");
        HostRuntime.fatal(handler, new IllegalStateException("factory error path"));
        HostRuntime.setLifeCycle(handler, 3);
        HostRuntime.call(handler, "deinit");
        HostRuntime.setLifeCycle(handler, 1);
        HostRuntime.call(handler, "destroy");
        System.out.println("UI_NO_HELPER_PASS 6");
    }
}
