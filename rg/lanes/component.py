# SPDX-License-Identifier: GPL-3.0-or-later
"""Route-guidance display component 1 as well as 16 (rg/build.sh mode lanes-uturn-asf-m-aa-r, after aa11.py), on the
staged copies only.

Tomasz's LiveModel.apply() drops every 0x5201/0x5202/0x5204 whose component list (key 0) does not contain 0x10, the id
his B2 driver hook declares in the identification (RouteGuidanceDisplayComponent, param 0x1e) and asks for in its
0x5200 StartRouteGuidanceUpdates frame (MU1427/route-guidance/driver-hooks.S). Wired CarPlay and our AA hook
(aa/hook/pmcp_rg.c) send 0x10. omonob's wireless CarPlay notes (not verified by us): over wireless the phone sends the
same messages with component 1, and an adapter that accepted only 16 showed the map but no arrows. This accepts 1 as
well. Messages that carry 16 are handled exactly as before; a message carrying both is applied once (the check is
"any of"); any other component is still dropped.

    component.py STAGED_LANE_DIR RG_LANES_DIR   -> patches STAGED_LANE_DIR/LiveModel.java, copies TestComponent.java

The driver (identification and 0x5200 request: component 16 only) and iap2.cfg are unchanged. Each replacement must
match exactly once.
"""
import pathlib
import shutil
import sys

lane_dir = pathlib.Path(sys.argv[1])
src_dir = pathlib.Path(sys.argv[2])


def patch(text, old, new, what, count=1):
    if text.count(old) != count:
        sys.exit("component.py: %s: expected text found %d times" % (what, text.count(old)))
    return text.replace(old, new)


lm = lane_dir / "LiveModel.java"
s = lm.read_text()
s = patch(s, '''        for (int i=0;i<m.components.length;i++) if (m.components[i]==0x10) component=true;''',
          '''        // pmcp: 16 = wired CarPlay and our AA hook, 1 = wireless CarPlay (omonob's notes)
        for (int i=0;i<m.components.length;i++) if (m.components[i]==0x10 || m.components[i]==0x01) component=true;''',
          "apply component check")
lm.write_text(s)
shutil.copy(src_dir / "TestComponent.java", lane_dir / "TestComponent.java")
print("component.py: route-guidance display component 1 accepted as well as 16 in %s" % lane_dir)
