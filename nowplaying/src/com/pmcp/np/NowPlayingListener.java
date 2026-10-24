/* SPDX-License-Identifier: GPL-3.0-or-later */
package com.pmcp.np;

import org.dsi.ifc.carplay.AppState;
import org.dsi.ifc.carplay.CallState;
import org.dsi.ifc.carplay.DSICarplayListener;
import org.dsi.ifc.carplay.DeviceInfo;
import org.dsi.ifc.carplay.PlaybackInfo;
import org.dsi.ifc.carplay.Resource;
import org.dsi.ifc.carplay.TelephonyState;
import org.dsi.ifc.carplay.TrackData;
import org.dsi.ifc.global.ResourceLocator;

/**
 * Our own DSICarplay listener, registered for ATTR_NOWPLAYINGDATA only. The DSI proxy keeps a notification
 * mask per listener (DSIProxyTarget.listenerNotificationMasks), so this does not change what the stock
 * CarPlay target receives. Only updateNowPlayingData does anything.
 */
final class NowPlayingListener implements DSICarplayListener {
    public void updateNowPlayingData(TrackData trackdata, int valid) {
        try {
            NowPlaying.onTrack(trackdata, valid);
        } catch (Throwable t) {
            // never disturb the DSI dispatcher
        }
    }

    public void updateMode(Resource[] r, AppState[] a, int v) { }
    public void responseModeChange(Resource[] r, AppState[] a, int v) { }
    public void requestBTDeactivation(String s, int v) { }
    public void updateDeviceInfo(DeviceInfo d, int v) { }
    public void updateCallState(CallState[] c, int v) { }
    public void updateTelephonyState(TelephonyState t, int v) { }
    public void updatePlaybackState(PlaybackInfo p, int v) { }
    public void updatePlayposition(int p, int v) { }
    public void updateCoverArtUrl(ResourceLocator r, int v) { }
    public void updateTextInputState(int s, int v) { }
    public void duckAudio(int i, double d) { }
    public void unduckAudio(int i) { }
    public void oemAppSelected() { }
    public void updateMainAudioType(int t, int v) { }
    public void asyncException(int i, String s, int j) { }
}
