/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.np;

import de.vw.mib.bap.mqbab2.audiosd.functions.CurrentStationInfo;
import de.vw.mib.bap.mqbab2.common.api.APIFactory;
import de.vw.mib.bap.mqbab2.generated.audiosd.serializer.CurrentStationInfo_Status;
import de.vw.mib.genericevents.ThreadSwitchingTarget;
import org.dsi.ifc.carplay.DSICarplay;
import org.dsi.ifc.carplay.TrackData;

/**
 * CarPlay track title / artist / album on the cluster (BAP AudioSD CurrentStationInfo).
 *
 * Stock MU1161: the CarPlay ASL target never subscribes to DSICarplay ATTR_NOWPLAYINGDATA (3) and
 * CurrentStationInfo sends only "Apple CarPlay". Three hooks (patcher/PatchNp.java) call this class:
 *   attach(dsi)      after HsmTarget's own setNotification: our own listener for attribute 3;
 *   register(csi)    from CurrentStationInfo.init (unregister from uninitialize);
 *   fill(type, st)   at the start of CurrentStationInfo.setStationInfoForMirrorLink.
 * A track change is handed to the BAP thread with the stock ThreadSwitchingService (as ASLDataPoolAdapter
 * does), which then runs CurrentStationInfo.process(-1). Every hook swallows its own errors: a failure here
 * must never break CarPlay or the cluster, it only leaves the stock "Apple CarPlay".
 *
 * Java 1.2 clean (no StringBuilder, no string concatenation, no autoboxing, no class literals): the
 * classes are downgraded to class file version 46 for the J9 foun11 VM.
 */
public final class NowPlaying {
    /** BAP AudioSD info types, as stock setStationInfoForMediaExternalDevice / setArtistAndAlbum use them. */
    static final int TYPE_TITLE = 72;
    static final int TYPE_ARTIST = 73;
    static final int TYPE_ALBUM = 74;
    /** SmartphoneIntegrationService active connection type of CarPlay (stock switch in setStationInfoForMirrorLink). */
    static final int CONNECTION_CARPLAY = 2;
    static final int ATTR_NOWPLAYINGDATA = 3;
    static final int VALID = 1;

    private static final Object LOCK = new Object();
    private static String title = "";
    private static String artist = "";
    private static String album = "";
    private static CurrentStationInfo station;
    private static DSICarplay attached;
    private static final NowPlayingListener LISTENER = new NowPlayingListener();
    private static final Runnable REFRESH = new Runnable() {
        public void run() {
            CurrentStationInfo s;
            synchronized (LOCK) {
                s = station;
            }
            if (s != null) {
                try {
                    s.process(-1);
                } catch (Throwable t) {
                    // keep the stock behaviour
                }
            }
        }
    };

    private NowPlaying() {
    }

    /** Hook in HsmTarget.initializeDSI, right after its own setNotification. Idempotent per DSI instance. */
    public static void attach(DSICarplay dsi) {
        try {
            if (dsi == null) {
                return;
            }
            synchronized (LOCK) {
                if (attached == dsi) {
                    return;
                }
                attached = dsi;
            }
            dsi.setNotification(new int[] {ATTR_NOWPLAYINGDATA}, LISTENER);
        } catch (Throwable t) {
            // no track info, stock "Apple CarPlay"
        }
    }

    public static void register(CurrentStationInfo s) {
        synchronized (LOCK) {
            station = s;
        }
    }

    public static void unregister(CurrentStationInfo s) {
        synchronized (LOCK) {
            if (station == s) {
                station = null;
            }
        }
    }

    /** From the DSI listener. Stores the strings and asks the BAP thread for a new status if anything changed. */
    static void onTrack(TrackData td, int valid) {
        String t = "";
        String ar = "";
        String al = "";
        if (td != null && valid == VALID) {
            t = clean(td.title);
            ar = clean(td.artist);
            al = clean(td.album);
        }
        boolean changed;
        synchronized (LOCK) {
            changed = !t.equals(title) || !ar.equals(artist) || !al.equals(album);
            title = t;
            artist = ar;
            album = al;
        }
        if (changed) {
            refresh();
        }
    }

    static void refresh() {
        try {
            ThreadSwitchingTarget ts = APIFactory.getAPIFactory().getThreadSwitchingService();
            if (ts != null) {
                ts.enqueue(REFRESH);
            }
        } catch (Throwable t) {
            // BAP not up yet: the next stock update shows the track
        }
    }

    /**
     * Hook at the start of CurrentStationInfo.setStationInfoForMirrorLink. Returns true if it filled the
     * status (CarPlay active and a title known), false to let the stock code run unchanged.
     */
    public static boolean fill(int connectionType, CurrentStationInfo_Status st) {
        try {
            String t;
            String ar;
            String al;
            synchronized (LOCK) {
                t = title;
                ar = artist;
                al = album;
            }
            if (connectionType != CONNECTION_CARPLAY || t.length() == 0 || st == null) {
                return false;
            }
            st.primaryInformation.setContent(t);
            st.pi_Type = TYPE_TITLE;
            st.pi_Id = 0;
            st.secondaryInformation.setContent(ar);
            st.si_Type = ar.length() != 0 ? TYPE_ARTIST : 0;
            st.tertiaryInformation.setContent(al);
            st.ti_Type = al.length() != 0 ? TYPE_ALBUM : 0;
            st.quaternaryInformation.setContent("");
            st.qi_Type = 0;
            return true;
        } catch (Throwable x) {
            return false;
        }
    }

    /** Trim and cap the length; BAP strings are bounded and the cluster line is short. */
    static String clean(String s) {
        if (s == null) {
            return "";
        }
        String r = s.trim();
        if (r.length() > 80) {
            r = r.substring(0, 80);
        }
        return r;
    }

    /** For host tests only. */
    static String[] snapshot() {
        synchronized (LOCK) {
            return new String[] {title, artist, album};
        }
    }
}
