/* SPDX-License-Identifier: GPL-3.0-or-later. Host test, never installed.
 * Classpath: this test, a copy of pmcp-zoom.jar WITHOUT com/pmcp/zoom/*, the converted stock jar.
 * The patched DSIKeyPanelDispatcher.updateKey2 must not throw a LinkageError (NoClassDefFoundError) when the helper
 * cannot be loaded: the guard falls back to the stock path (review 2, finding 1). The instance is allocated without a
 * constructor, so the stock body itself may fail on its null fields; that is fine, only a LinkageError is a failure. */
public class TestZoomGuard {
    public static void main(String[] a) throws Exception {
        java.lang.reflect.Field f = Class.forName("sun.misc.Unsafe").getDeclaredField("theUnsafe");
        f.setAccessible(true);
        Object u = f.get(null);
        Class c = Class.forName("de.esolutions.fw.dsi.keypanel.DSIKeyPanelDispatcher");
        try {
            Class.forName("com.pmcp.zoom.ZoomHook");
            System.out.println("FAIL helper is present, test setup wrong");
            System.exit(1);
        } catch (ClassNotFoundException expected) {
        }
        Object d = u.getClass().getMethod("allocateInstance", new Class[] {Class.class}).invoke(u, new Object[] {c});
        java.lang.reflect.Method m = c.getMethod("updateKey2", new Class[] {int.class, int.class, int.class, int.class, int.class});
        int bad = 0;
        int[][] calls = {{4, 38, 1, 0, 1}, {4, 39, 0, 0, 1}, {1, 5, 1, 0, 1}};
        for (int i = 0; i < calls.length; i++) {
            Object[] args = new Object[5];
            for (int j = 0; j < 5; j++) args[j] = new Integer(calls[i][j]);
            String what = "updateKey2(" + calls[i][0] + "," + calls[i][1] + ",...) without helper";
            try {
                m.invoke(d, args);
                System.out.println("ok   " + what + ": no exception");
            } catch (java.lang.reflect.InvocationTargetException e) {
                Throwable t = e.getCause();
                boolean ok = !(t instanceof LinkageError);
                System.out.println((ok ? "ok   " : "FAIL ") + what + ": " + t + (ok ? " (stock body, not the hook)" : ""));
                if (!ok) bad++;
            }
        }
        System.out.println(bad == 0 ? "GUARD OK" : bad + " FAILED");
        System.exit(bad == 0 ? 0 : 1);
    }
}
