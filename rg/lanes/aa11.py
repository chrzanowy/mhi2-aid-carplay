# SPDX-License-Identifier: GPL-3.0-or-later
"""AA 1.1 (experimental, audit A171): Android Auto road name, lanes and destination distance / time on the cockpit only
while the AID does not show the AA map. Runs after v146.py (rg/build.sh mode lanes-uturn-asf-m-aa-r), on the staged
copies only.

Since A171 the AA gamma hook (aa/hook/pmcp_rg.c) puts Google Maps' road name (0x5201 key 3), lanes (0x5204, keys 16/18)
and the destination's metres / seconds (keys 7 / 6) into /ramdisk/pmcp-aa-rg. LiveBridge already publishes them for
CarPlay. With the AA map on the AID, Google Maps draws the same things in its own picture and the AID would draw ours
over the map, so with Android Auto (phone == 3) they are hidden whenever com.pmcp.kv.KombiView.mapShown() is not 0:
datapool 1110045, which followed every view switch on the 2026-11-11 drive (A167). An unknown view (-1, nothing
reported yet) hides as well: the same as AA 1.0, which showed none of them.

    aa11.py STAGED_LANE_DIR RG_LANES_DIR   -> patches STAGED_LANE_DIR/LiveBridge.java, copies TestAa11.java there

Hidden means: TurnToInfo empty (a speed-limit prefix from package sl stays), no lanes (lane list empty, lane guidance
not visible), DistanceToDestination / TimeToDestination published as invalid. The arrow and the distance to the
manoeuvre stay. When the view changes, the next timer tick (250 ms) re-sends the four functions (refreshPending).
CarPlay (phone 2) is unchanged. Each replacement must match exactly the given number of times.
"""
import pathlib
import shutil
import sys

lane_dir = pathlib.Path(sys.argv[1])
src_dir = pathlib.Path(sys.argv[2])


def patch(text, old, new, what, count=1):
    if text.count(old) != count:
        sys.exit("aa11.py: %s: expected text found %d times" % (what, text.count(old)))
    return text.replace(old, new)


lb = lane_dir / "LiveBridge.java"
s = lb.read_text()
s = patch(s, '''    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }''',
          '''    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }
    // pmcp AA 1.1 (A171): with Android Auto, road name, lanes and destination distance/time only while the AID does
    // not show the AA map (Google Maps draws them there itself); an unknown view hides them too
    static boolean aaMapHides() { return phone==3 && com.pmcp.kv.KombiView.mapShown()!=0; }
    int publishedHide=-1;''', "fields")
s = patch(s, '''            String road=SpeedLimitText.preview(RoadName.current(frame,time));''',
          '''            int hide=aaMapHides()?1:0;
            // the view changed: lanes (24), destination distance (21) and time (22), road name (20) again
            if(hide!=publishedHide){publishedHide=hide;refreshPending|=8|16|32|64;}
            String road=SpeedLimitText.preview(hide==1?"":RoadName.current(frame,time));''', "tick")
s = patch(s, '''out.turnToInfo.setContent(SpeedLimitText.apply(RoadName.current(f,now())));''',
          '''out.turnToInfo.setContent(SpeedLimitText.apply(aaMapHides()?"":RoadName.current(f,now())));''', "turnTo")
s = patch(s, '''        boolean valid=f.active && f.remainingMeters>=0;''',
          '''        boolean valid=f.active && f.remainingMeters>=0 && !aaMapHides();''', "destinationDistance")
s = patch(s, '''        boolean valid=f.active && f.remainingSeconds>=0;''',
          '''        boolean valid=f.active && f.remainingSeconds>=0 && !aaMapHides();''', "destinationTime")
s = patch(s, '''LiveModel.Frame f=laneFrame();''', '''LiveModel.Frame f=aaMapHides()?null:laneFrame();''', "lanes", 2)
lb.write_text(s)
shutil.copy(src_dir / "TestAa11.java", lane_dir / "TestAa11.java")
print("aa11.py: AA 1.1 gate (road, lanes, destination hidden while the AID shows the AA map) staged in %s" % lane_dir)
