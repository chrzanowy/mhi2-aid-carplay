/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.dn;

import de.vw.mib.asl.framework.internal.framework.ServiceManager;
import de.vw.mib.asl.internal.carplay.common.CarPlayGlobalProperies;
import de.vw.mib.asl.internal.carplay.target.HsmTarget;
import de.vw.mib.genericevents.EventGeneric;

/**
 * Package G: the CarPlay cluster map stays in night mode after a daytime start until the lights change
 * (omonob #51; chefranov v1.1.4 "altscreen_night_resend" for the same bug).
 *
 * Stock: the night mode goes to the phone once, in startService(ServiceConfiguration), and afterwards only on a
 * change (ASLHandler.handleDayNightMode -> requestNightMode). The cluster display appears seconds later.
 * Hook right after the stock startService (patcher/PatchExtras.java): a daemon thread re-sends the current
 * value 5, 15 and 30 s later as the stock DAYNIGHT event 4300038, addressed to the CarPlay target only
 * (AbstractTarget.triggerMe -> event dispatcher -> the target's own thread -> stock handleDayNightMode, which
 * calls requestNightMode only while connected). Java 1.2 clean, every error swallowed.
 *
 * The value is not read on our thread: a real day/night event already queued (e.g. a tunnel within 30 s of
 * connecting) would otherwise be followed by our older value and undone (review 2, finding 6). Our event carries
 * only a marker object in parameter 1; a second hook at the entry of the stock handleDayNightMode (target thread)
 * calls beforeHandle, which fills parameter 0 with properties.isNightMode() at that moment, i.e. the result of every
 * event handled before. Pooled events are cleared on backToPool, and the marker is removed when consumed.
 */
public final class DayNight {
    static final int EV_DAYNIGHT_MODE = 4300038;
    static final long[] DELAYS = {5000L, 10000L, 15000L};   // cumulative: 5 s, 15 s, 30 s after startService
    static final int P_VALUE = 0;      // stock parameter: night mode
    static final int P_MARKER = 1;     // ours: MARKER, never used by the stock event
    static final Object MARKER = new Object();

    /** What one re-send needs; the production one sends the stock event, tests use their own. */
    interface Resender {
        boolean connected();
        void resend();
    }

    private DayNight() {
    }

    public static void sessionStarted(final HsmTarget target, final CarPlayGlobalProperies properties) {
        try {
            if (target == null || properties == null) {
                return;
            }
            start(new Resender() {
                public boolean connected() {
                    return properties.isConnected();
                }

                public void resend() {
                    EventGeneric ev = ServiceManager.mGenericEventFactory.newEvent();
                    ev.setBoolean(P_VALUE, properties.isNightMode());   // replaced on the target thread
                    ev.setObject(P_MARKER, MARKER);
                    target.triggerMe(ev, EV_DAYNIGHT_MODE);
                }
            });
        } catch (Throwable t) {
            // stock behaviour
        }
    }

    /** Entry of the stock ASLHandler.handleDayNightMode (target thread). Real events pass unchanged. */
    public static void beforeHandle(EventGeneric ev, CarPlayGlobalProperies properties) {
        try {
            if (ev == null || properties == null || !ev.contains(P_MARKER) || ev.getObject(P_MARKER) != MARKER) {
                return;
            }
            ev.removeParameter(P_MARKER);
            ev.setBoolean(P_VALUE, properties.isNightMode());
        } catch (Throwable t) {
            // stock behaviour
        }
    }

    static Thread start(final Resender r) {
        Thread t = new Thread(new Runnable() {
            public void run() {
                runSchedule(r, DELAYS);
            }
        }, "pmcp-daynight");
        t.setDaemon(true);
        t.start();
        return t;
    }

    /** Returns how many times it re-sent (for tests). */
    static int runSchedule(Resender r, long[] delays) {
        int sent = 0;
        for (int i = 0; i < delays.length; i++) {
            try {
                Thread.sleep(delays[i]);
                if (!r.connected()) {
                    return sent;
                }
                r.resend();
                sent++;
            } catch (Throwable t) {
                return sent;
            }
        }
        return sent;
    }
}
