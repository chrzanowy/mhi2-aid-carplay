/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.np;

import org.dsi.ifc.androidauto2.CallState;
import org.dsi.ifc.androidauto2.DSIAndroidAuto2Listener;
import org.dsi.ifc.androidauto2.PlaybackInfo;
import org.dsi.ifc.androidauto2.TelephonyState;
import org.dsi.ifc.androidauto2.TrackData;
import org.dsi.ifc.global.ResourceLocator;

/**
 * Our own DSIAndroidAuto2 listener (AA 1.1, A171), registered for ATTR_NOWPLAYINGDATA only, as NowPlayingListener is
 * for CarPlay: the DSI proxy keeps a notification mask per listener, so the stock Android Auto target receives what it
 * did before. Only updateNowPlayingData does anything.
 */
final class AaNowPlayingListener implements DSIAndroidAuto2Listener {
    public void updateNowPlayingData(TrackData trackdata, int valid) {
        try {
            NowPlaying.onAaTrack(trackdata, valid);
        } catch (Throwable t) {
            // never disturb the DSI dispatcher
        }
    }

    public void videoFocusRequestNotification(int a, int b) { }
    public void videoAvailable(boolean a, int b) { }
    public void audioFocusRequestNotification(int a, int b) { }
    public void audioAvailable(int a, boolean b, int c) { }
    public void voiceSessionNotification(int a, int b) { }
    public void microphoneRequestNotification(int a, int b) { }
    public void navFocusRequestNotification(int a, int b) { }
    public void updateCallState(CallState[] c, int v) { }
    public void updateTelephonyState(TelephonyState t, int v) { }
    public void updatePlaybackState(PlaybackInfo p, int v) { }
    public void updatePlayposition(int p, int v) { }
    public void updateCoverArtUrl(ResourceLocator r, int v) { }
    public void updateNavigationNextTurnEvent(String road, int side, int event, int angle, int number, int v) { }
    public void updateNavigationNextTurnDistance(int meters, int seconds, int v) { }
    public void setExternalDestination(double lat, double lon, String a, String b, int v) { }
    public void bluetoothPairingRequest(String s, int v) { }
    public void asyncException(int i, String s, int j) { }
}
