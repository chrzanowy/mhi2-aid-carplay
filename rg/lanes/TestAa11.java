/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host-only test of the AA 1.1 gate (aa11.py, audit A171) on the guarded factory classes, with TestLive's factory mocks:
 * with Android Auto, road name, lanes and destination distance / time only while the AID does not show the AA map
 * (com.pmcp.kv.KombiView.mapShown() == 0); unknown view hides; a view change re-sends the functions; CarPlay unchanged. */
package com.cpmap.rgi;

import com.pmcp.kv.KombiView;
import de.vw.mib.bap.mqbab2.common.api.APIFactory;
import de.vw.mib.bap.mqbab2.common.api.navigation.NavigationService;
import de.vw.mib.bap.mqbab2.generated.navsd.serializer.*;

public final class TestAa11 {
    static int checks;
    static void check(boolean ok, String m) { checks++; System.out.println((ok ? "ok     " : "FAILED ") + m); if (!ok) throw new AssertionError(m); }
    static boolean sent(Class c) { for (int i = 0; i < TestLive.sent.size(); i++) if (c.isInstance(TestLive.sent.get(i))) return true; return false; }
    static int count(java.util.Iterator it) { int n = 0; while (it.hasNext()) { it.next(); n++; } return n; }
    static void tick(LiveBridge b) { TestLive.sent.clear(); TestLive.clock += 250; b.journalAt = TestLive.clock; b.tick(TestLive.clock); }

    static void shown(LiveBridge b, NavigationService nav, String what) {
        TurnToInfo_Status tt = new TurnToInfo_Status();
        DistanceToDestination_Status dd = new DistanceToDestination_Status();
        TimeToDestination_Status td = new TimeToDestination_Status();
        check(LiveBridge.turnTo(tt) && tt.turnToInfo.toString().equals("Wojciecha Cybulskiego"), what + ": road name");
        check(LiveBridge.destinationDistance(dd) && dd.validityInformation.distanceToDestinationValid, what + ": destination distance valid");
        check(LiveBridge.destinationTime(td) && td.validityInformation.timeInfo_MinuteIsValid && td.timeInfo.hour == 0 && td.timeInfo.minute == 15,
            what + ": time to destination 0:15");
        check(count(LiveBridge.laneIterator(nav)) == 2 && LiveBridge.lanesVisible(nav), what + ": two lanes");
    }
    static void hidden(LiveBridge b, NavigationService nav, String what) {
        TurnToInfo_Status tt = new TurnToInfo_Status();
        DistanceToDestination_Status dd = new DistanceToDestination_Status();
        TimeToDestination_Status td = new TimeToDestination_Status();
        DistanceToNextManeuver_Status n = new DistanceToNextManeuver_Status();
        ManeuverDescriptor_Status d = new ManeuverDescriptor_Status();
        check(LiveBridge.turnTo(tt) && tt.turnToInfo.toString().equals(""), what + ": road name empty");
        check(LiveBridge.destinationDistance(dd) && !dd.validityInformation.distanceToDestinationValid, what + ": destination distance invalid");
        check(LiveBridge.destinationTime(td) && !td.validityInformation.timeInfo_MinuteIsValid && !td.validityInformation.timeInfo_HourIsValid,
            what + ": time to destination invalid");
        check(count(LiveBridge.laneIterator(nav)) == 0 && !LiveBridge.lanesVisible(nav), what + ": no lanes");
        check(LiveBridge.descriptor(d) && d.maneuver_1.mainElement == 13 && d.maneuver_1.direction == 192
            && LiveBridge.distance(n) && n.validityInformation.distanceToNextManeuverValid, what + ": arrow and manoeuvre distance stay");
    }

    public static void main(String[] a) throws Exception {
        TestLive.installMocks();
        LiveBridge b = TestLive.bridge();
        NavigationService nav = APIFactory.getAPIFactory().getNavigationService();
        TestLive.connection = 3; TestLive.setupLane = true;
        check(LiveBridge.factoryContext() == 0 && LiveBridge.phone == 3, "AA connection");
        b.root = LiveBridge.AA_ROOT;
        long t = TestLive.clock;
        LaneData[] lanes = { new LaneData(0, 0, 0, ""), new LaneData(1, 192, 2, "") };
        b.incoming = new LiveModel.Frame(true, 13, 192, 150, 12000, 900, 2, t, 1, lanes, t, "Wojciecha Cybulskiego", t, 2);
        b.journalAt = t; b.tick(t);
        check(b.owned, "AA frame with road, lanes and destination published");
        check(KombiView.mapShown() == -1 && LiveBridge.aaMapHides(), "view not reported yet: hidden");
        hidden(b, nav, "unknown view");

        KombiView.onMapVisibility(0);
        tick(b);
        check(!LiveBridge.aaMapHides(), "1110045 invisible: shown");
        check(sent(TurnToInfo_Status.class) && sent(DistanceToDestination_Status.class) && sent(TimeToDestination_Status.class),
            "view change: road name and destination re-sent at the next tick");
        shown(b, nav, "AID without the map");

        tick(b);
        check(!sent(TurnToInfo_Status.class) && !sent(DistanceToDestination_Status.class) && !sent(TimeToDestination_Status.class),
            "same view, same frame: nothing re-sent");

        KombiView.onMapVisibility(1);
        tick(b);
        check(LiveBridge.aaMapHides() && sent(TurnToInfo_Status.class) && sent(DistanceToDestination_Status.class)
            && sent(TimeToDestination_Status.class), "map on the AID: hidden and re-sent");
        hidden(b, nav, "AID with the map");

        KombiView.onMapVisibility(0);
        tick(b);
        shown(b, nav, "map off again");

        // CarPlay: the gate never applies
        KombiView.onMapVisibility(1);
        TestLive.connection = 2; LiveBridge.factoryContext();
        check(!LiveBridge.aaMapHides(), "CarPlay with the map flag set: not hidden");
        TestLive.connection = 3; LiveBridge.factoryContext();
        check(LiveBridge.aaMapHides(), "back to AA: hidden");
        System.out.println("AA11_PASS checks=" + checks);
    }
}
