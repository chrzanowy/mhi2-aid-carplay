# SPDX-License-Identifier: GPL-3.0-or-later
"""Route guidance of CarPlay over Wi-Fi (A248; rg/build.sh mode lanes-uturn-asf-m-aa-r-wl, after component.py), on the
staged copies only.

The WL receiver (wlcpd, publish/mhi2-wireless-carplay) gets the phone's 0x5201/0x5202/0x5204 inside the AirPlay session
and writes the same RGM1/RGI1 mailbox as the wired reader to its own directory /ramdisk/pmcp-wl-rg (contract agreed with
WL 2026-11-28, A248: kind 1 snapshot, tmp + rename, heartbeat every 0.5 s, route state 0 at the end of the session).

    wl.py STAGED_LANE_DIR RG_LANES_DIR   -> patches STAGED_LANE_DIR/LiveBridge.java, copies WlSource.java, TestWl.java

Change: rootFor(connection) gives the WL directory for a non-AA connection while WlSource.active(), i.e. while a Wi-Fi
session owns the MOST map contract (/ramdisk/most-src/owner src=wireless with a live pid and wireless.session
state=start of the same gen; read at most every 0.5 s, fail-closed). Everything else follows from aa.py's source switch:
switchRoot() starts a fresh FeedRecovery on the other directory, tick()/current() publish only while the reader reads
the directory of the current source, adapter-status.txt goes to the directory being read. The cable takes the owner
(src=wired), so the cable wins. Android Auto (connection 3) is unchanged; without a Wi-Fi owner rootFor() returns
exactly what it returned before. The quiet-route hold of the WL directory is CarPlay's (holdFor: not the AA directory).
factoryContext() is unchanged: the HMI must report connection 2 (CarPlay) during a WL session (to be confirmed in the
car). Each replacement must match exactly once.
"""
import pathlib
import shutil
import sys

lane_dir = pathlib.Path(sys.argv[1])
src_dir = pathlib.Path(sys.argv[2])


def patch(text, old, new, what):
    if text.count(old) != 1:
        sys.exit("wl.py: %s: expected text found %d times" % (what, text.count(old)))
    return text.replace(old, new)


lb = lane_dir / "LiveBridge.java"
s = lb.read_text()
s = patch(s, '''    static String rootFor(int connection) { return connection==3?AA_ROOT:ROOT; }''',
          '''    // pmcp A248: CarPlay over Wi-Fi reads the WL receiver's mailbox while a Wi-Fi session owns the MOST map contract
    static String rootFor(int connection) { return connection==3?AA_ROOT:WlSource.active()?WlSource.ROOT:ROOT; }''',
          "rootFor")
lb.write_text(s)
shutil.copy(src_dir / "WlSource.java", lane_dir / "WlSource.java")
shutil.copy(src_dir / "TestWl.java", lane_dir / "TestWl.java")
print("wl.py: Wi-Fi CarPlay mailbox source added in %s" % lane_dir)
