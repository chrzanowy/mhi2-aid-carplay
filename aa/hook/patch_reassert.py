#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Experiment (A203-AA, reverse gear): re-grant the cluster display once after the main display changes focus. Host
tool, run after patch_config_kf.py.

  python3 -I patch_reassert.py SRC_DIR

Why: the car logs of 9-14.11 show that when the main screen leaves Android Auto (the reverse camera, or the user going
to a VW screen) gal tells the phone "primary display: native" (aap.video_focus role=primary mode=2), and the phone then
often slows the cluster stream to ~4 fps of ~1 KB frames or stops it for up to ~9 s; a few times it never came back
until the phone was plugged in again. Our feeder was idle each time (queue 0, no ACK hold): the phone stops sending.
The hook only logged it (role=secondary_synced action=skipped). The secondary's own focus stays 1 the whole time.

What this adds (default off, nothing changes without the switch):
  - GAL_PMCP_SEC_REASSERT: bit 1 = after the primary goes native, bit 2 = after it is projected again (3 = both).
    Without it in the environment the hook reads the GEM switch itself: 3 only for the exact line
    "PMCP_AA_SEC_REASSERT=3" in GAL_PMCP_EXTRA_CONF (default /mnt/persist/pmcp/aa-extra.conf, written by pmcp.sh
    aa-regrant); anything else is 0. The gal wrapper stays as it is: pmcp.sh recognises an earlier AA set by it.
  - GAL_PMCP_SEC_REASSERT_MS (default 800, 0..10000): delay after the primary's change.
  - focus_ctl.c fc_primary_focus(mode): on a real change of the primary's mode (not the first one of a session),
    queues ONE mode 1 write for the secondary in the controller's existing mailbox (written on gal's thread under
    the endpoint write lock, as every focus write), only while the secondary is GRANTED/ACTIVE with mode 1 sent, the
    phone has not asked for native and no other write is pending. It never writes mode 2: a 2 -> 1 cycle made the
    phone stream ~3 fps and reset ~130 s later (audit A-AA11). Logged event=focus.reassert ... fix=pmcp, then the
    usual event=focus.write mode=1 reason=primary_native|primary_projected.
  - video_sink_hook.c: setVideoFocus on the primary calls fc_primary_focus(mode) when the controller runs.
Each replacement must match exactly once.
"""
import pathlib
import sys

FUNC = r'''/*
 * pmcp (A203-AA): the primary display changed focus (reverse camera, or a VW screen on the main display). The phone
 * often slows or stops the cluster stream then; GAL_PMCP_SEC_REASSERT (bit 1: primary -> native, bit 2: primary ->
 * projected, 0 = off) queues ONE mode 1 write for the secondary GAL_PMCP_SEC_REASSERT_MS later (default 800). Never a
 * mode 2 (a 2 -> 1 cycle made the phone stream ~3 fps and reset, A-AA11).
 */
static int g_reassert = -1;

/* 3 only for the exact line PMCP_AA_SEC_REASSERT=3 (no blanks, LF or CRLF) in the GEM switch file. */
static int reassert_from_file(void)
{
    const char *path = getenv("GAL_PMCP_EXTRA_CONF");
    char line[128];
    int found = 0;
    FILE *f = fopen(path != NULL && path[0] ? path : "/mnt/persist/pmcp/aa-extra.conf", "r");
    if (f == NULL) return 0;
    while (fgets(line, sizeof line, f) != NULL) {
        size_t n = strlen(line);
        while (n > 0 && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = '\0';
        if (strcmp(line, "PMCP_AA_SEC_REASSERT=3") == 0) found = 1;
        else if (strncmp(line, "PMCP_AA_SEC_REASSERT=", 21) == 0) found = 0;   /* the last line wins */
    }
    fclose(f);
    return found ? 3 : 0;
}
static long long g_reassert_ms = 800;
static int g_primary_mode_seen = -1;
static unsigned long g_reassert_n, g_reassert_skipped;

void fc_primary_focus(int mode)
{
    int bit, prev, posted = 0, wanted;
    const char *why = "";

    if (g_reassert < 0) {
        const char *v = getenv("GAL_PMCP_SEC_REASSERT"), *d = getenv("GAL_PMCP_SEC_REASSERT_MS");
        g_reassert = v != NULL ? atoi(v) : reassert_from_file();
        if (g_reassert < 0 || g_reassert > 3) g_reassert = 0;
        if (d != NULL && atoi(d) >= 0 && atoi(d) <= 10000) g_reassert_ms = atoi(d);
        gal_hook_logf("event=focus.reassert_config value=%d delay_ms=%lld fix=pmcp", g_reassert, g_reassert_ms);
    }
    bit = mode == 2 ? 1 : (mode == 1 ? 2 : 0);
    pthread_mutex_lock(&g_lock);
    prev = g_primary_mode_seen;
    g_primary_mode_seen = mode;
    wanted = g_reassert > 0 && (g_reassert & bit) && prev >= 0 && prev != mode;
    if (!wanted) why = "off";
    else if (!g_started) why = "controller_off";
    else if (!(g_state == FC_ACTIVE || g_state == FC_GRANTED)) why = "secondary_not_granted";
    else if (g_mode_sent != 1) why = "secondary_not_mode1";
    else if (g_phone_wants_native) why = "phone_wants_native";
    else if (g_mb_pending) why = "write_pending";
    else {
        post_focus_locked(1, mode == 2 ? "primary_native" : "primary_projected");
        g_mb_posted_ms += g_reassert_ms;   /* run_mailbox waits until now - posted >= 0 */
        posted = 1;
    }
    if (posted) g_reassert_n++;
    else if (wanted) g_reassert_skipped++;
    pthread_mutex_unlock(&g_lock);
    if (wanted)
        gal_hook_logf("event=focus.reassert primary_mode=%d prev=%d action=%s reason=%s delay_ms=%lld queued=%lu skipped=%lu fix=pmcp",
                      mode, prev, posted ? "queued" : "none", posted ? "-" : why, g_reassert_ms,
                      g_reassert_n, g_reassert_skipped);
    if (posted) fc_notify();
}

void fc_run_mailbox(void)
'''

EDITS = {
    "src/focus_ctl.h": [
        ('void fc_run_mailbox(void);\n',
         'void fc_run_mailbox(void);\n'
         '/* pmcp (A203-AA): the primary display changed focus; GAL_PMCP_SEC_REASSERT re-grants the secondary once. */\n'
         'void fc_primary_focus(int mode);\n'),
    ],
    "src/focus_ctl.c": [
        ('#include <signal.h>\n',
         '#include <signal.h>\n'
         '#include <stdio.h>\n'
         '#include <stdlib.h>\n'),
        ('void fc_run_mailbox(void)\n', FUNC),
    ],
    "src/video_sink_hook.c": [
        ('        gal_hook_logf("event=aap.video_focus role=secondary_synced action=skipped "\n'
         '                      "primary_mode=%d reason=%s secondary_keeps=%d",\n'
         '                      mode, fc_enabled() ? "focus_control" : "mirror_disabled",\n'
         '                      g_secondary_focus_mode);\n',
         '        gal_hook_logf("event=aap.video_focus role=secondary_synced action=skipped "\n'
         '                      "primary_mode=%d reason=%s secondary_keeps=%d",\n'
         '                      mode, fc_enabled() ? "focus_control" : "mirror_disabled",\n'
         '                      g_secondary_focus_mode);\n'
         '        if (fc_enabled()) fc_primary_focus(mode);   /* pmcp A203-AA, GAL_PMCP_SEC_REASSERT */\n'),
    ],
}


def main():
    src = pathlib.Path(sys.argv[1])
    for rel, edits in EDITS.items():
        p = src / rel
        text = p.read_text()
        for old, new in edits:
            n = text.count(old)
            if n != 1:
                sys.exit("patch_reassert: %s: expected 1 match, found %d: %r" % (rel, n, old[:70]))
            text = text.replace(old, new)
        p.write_text(text)
    print("patch_reassert: OK")


if __name__ == "__main__":
    main()
