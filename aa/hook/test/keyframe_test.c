/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host test of patch_keyframe.py: the hook's real focus_ctl.c and vc_stream_out.c (pinned MacsInSpace commit after
 * patch_no_sd.py + patch_keyframe.py) with gal, the phone and the player faked here. Built and run by run_keyframe_test.sh.
 *
 * The fake player connects to the hook's video and ACK sockets like aa-most-feeder. The test plays the phone: it answers
 * the hook's focus writes with MediaStop / MediaStart (fc_playback_stop / fc_playback_start) and checks that a 'K' on the
 * ACK pipe gives mode 2 then mode 1 with the player kept, that 'K' is never counted as an ACK, and the rate limit. */
#include "focus_ctl.h"
#include "gal_hook.h"
#include "vc_player_mgr.h"
#include "vc_stream_out.h"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

/* ------------------------------------------------------------------ fakes for the rest of the hook */

static pthread_mutex_t g_m = PTHREAD_MUTEX_INITIALIZER;
static char g_log[65536];
static size_t g_log_len;
static int g_modes[64], g_n_modes;
static unsigned g_rendered;
static int g_configs, g_config_arg = -1;
static int g_player_alive, g_player_starts, g_player_stops;
static int g_vfd = -1, g_afd = -1;

void gal_hook_log(const char *msg)
{
    pthread_mutex_lock(&g_m);
    printf("  hook: %s\n", msg);
    if (g_log_len + strlen(msg) + 2 < sizeof g_log) {
        memcpy(g_log + g_log_len, msg, strlen(msg)); g_log_len += strlen(msg); g_log[g_log_len++] = '\n';
        g_log[g_log_len] = '\0';
    }
    pthread_mutex_unlock(&g_m);
}

void gal_hook_logf(const char *fmt, ...)
{
    char b[512];
    va_list ap;
    va_start(ap, fmt); vsnprintf(b, sizeof b, fmt, ap); va_end(ap);
    gal_hook_log(b);
}

int hook_fix_enabled(hook_fix fix)
{
    return fix == HOOK_FIX_FOCUS_CONTROL || fix == HOOK_FIX_ACK_RENDERED_ONLY || fix == HOOK_FIX_NO_IDR_REPLAY;
}
int gal_hook_focus_start_native(void) { return 1; }
int gal_hook_focus_wait_kombi(void) { return 0; }
void vc_kombi_watch_start(void) {}
int vc_kombi_ready(void) { return 1; }

static int connect_tcp(unsigned short port)
{
    struct sockaddr_in a;
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    memset(&a, 0, sizeof a);
    a.sin_family = AF_INET; a.sin_port = htons(port); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) != 0) { close(fd); return -1; }
    return fd;
}

static int connect_unix(const char *path)
{
    struct sockaddr_un a;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX; strncpy(a.sun_path, path, sizeof a.sun_path - 1);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) != 0) { close(fd); return -1; }
    return fd;
}

/* The "player": connects to both sockets at once, as the feeder does. */
void vc_player_start(void)
{
    pthread_mutex_lock(&g_m);
    g_player_starts++;
    g_player_alive = 1;
    pthread_mutex_unlock(&g_m);
    g_vfd = connect_tcp((unsigned short)atoi(getenv("GAL_STREAM_PORT")));
    g_afd = connect_unix("/tmp/gal_ack.sock");
    printf("  player: start video=%d ack=%d\n", g_vfd >= 0, g_afd >= 0);
}
void vc_player_stop(void) { vc_player_stop_wait(300); }
void vc_player_stop_wait(int grace_ms)
{
    (void)grace_ms;
    pthread_mutex_lock(&g_m); g_player_stops++; g_player_alive = 0; pthread_mutex_unlock(&g_m);
}
int vc_player_poll(void) { int a; pthread_mutex_lock(&g_m); a = g_player_alive; pthread_mutex_unlock(&g_m); return a; }

/* gal: the stock setVideoFocus and ackFrames */
static void fake_set_focus(void *sink, int mode, int unconstrained)
{
    (void)sink; (void)unconstrained;
    pthread_mutex_lock(&g_m);
    if (g_n_modes < 64) g_modes[g_n_modes++] = mode;
    pthread_mutex_unlock(&g_m);
    printf("  gal: setVideoFocus(secondary, %d)\n", mode);
}
static int fake_send_config(void *sink, int arg)
{
    (void)sink;
    pthread_mutex_lock(&g_m); g_configs++; g_config_arg = arg; pthread_mutex_unlock(&g_m);
    printf("  gal: sendConfig(secondary, %d)\n", arg);
    return 0;
}
static void fake_frames_rendered(unsigned n)
{
    pthread_mutex_lock(&g_m); g_rendered += n; pthread_mutex_unlock(&g_m);
}

/* ------------------------------------------------------------------ test helpers */

static int fails;
static void check(int ok, const char *msg)
{
    printf("%s %s\n", ok ? "ok    " : "FAILED", msg);
    if (!ok) fails++;
}
static void sleep_ms(int ms) { struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L }; nanosleep(&ts, 0); }
static int n_modes(void) { int n; pthread_mutex_lock(&g_m); n = g_n_modes; pthread_mutex_unlock(&g_m); return n; }
static int last_mode(void) { int m; pthread_mutex_lock(&g_m); m = g_n_modes ? g_modes[g_n_modes - 1] : -1; pthread_mutex_unlock(&g_m); return m; }
static int wait_mode_count(int n, int ms) { while (ms > 0 && n_modes() < n) { sleep_ms(10); ms -= 10; } return n_modes() >= n; }
static int log_count(const char *s)
{
    int n = 0; const char *p;
    pthread_mutex_lock(&g_m);
    for (p = g_log; (p = strstr(p, s)) != NULL; p += strlen(s)) n++;
    pthread_mutex_unlock(&g_m);
    return n;
}
static int wait_log(const char *s, int n, int ms) { while (ms > 0 && log_count(s) < n) { sleep_ms(10); ms -= 10; } return log_count(s) >= n; }
static void send_ack_bytes(const char *b, size_t n) { if (write(g_afd, b, n) != (ssize_t)n) printf("ack write failed\n"); }

int main(void)
{
    static unsigned char sink[64];
    fc_ops ops = { fake_set_focus, fake_frames_rendered, fake_send_config };
    int cfg, discards;
    int m = 1, held, starts, stops;
    char port[16];

    snprintf(port, sizeof port, "%d", 20000 + (int)(getpid() % 20000));
    setenv("GAL_STREAM_PORT", port, 1);
    sink[4] = 1;                                   /* channel open */

    fc_start(sink, &ops);
    check(fc_enabled(), "controller started");
    fc_setup_begin(sink);
    held = fc_filter_focus(sink, &m);              /* gal's setup-time mode 1 is held native */
    fc_setup_end(sink);
    check(held == 1 && m == 2, "setup: mode 1 held as 2");

    /* the controller spawns the player, sees both sockets and grants mode 1 */
    check(wait_mode_count(1, 5000) && last_mode() == 1, "grant: mode 1 after the player connected");
    fc_playback_start(sink);                       /* phone: MediaStart */
    check(wait_log("to=ACTIVE", 1, 2000), "ACTIVE after MediaStart");

    /* 1: one ACK byte and a 'K': the ACK is not the phone's (nothing delivered), 'K' is a request, not an ACK */
    send_ack_bytes("\001K", 2);
    check(wait_mode_count(2, 2000) && last_mode() == 2, "K: mode 2 written (refocus)");
    check(log_count("action=refocus count=1") == 1, "K: refocus logged");
    check(log_count("reason=keyframe_request player=kept") == 1, "K: loss path with the player kept");
    pthread_mutex_lock(&g_m); check(g_rendered == 0u, "K: no ACK reached the phone for 'K'"); pthread_mutex_unlock(&g_m);
    check(fc_playback_stop(sink) == 1, "phone: MediaStop after our mode 2 is ours");
    check(wait_mode_count(3, 3000) && last_mode() == 1, "re-grant: mode 1 after the phone's stop");
    fc_playback_start(sink);
    check(wait_log("to=ACTIVE", 2, 2000), "ACTIVE again");
    pthread_mutex_lock(&g_m); starts = g_player_starts; stops = g_player_stops; pthread_mutex_unlock(&g_m);
    check(starts == 1 && stops == 0, "player kept: one start, no stop");

    /* 2: another 'K' at once: too soon (3 s), nothing written */
    send_ack_bytes("K", 1);
    check(wait_log("reason=too_soon", 1, 2000), "K too soon: ignored");
    sleep_ms(500);
    check(n_modes() == 3, "K too soon: no focus write");

    /* 3: after 3 s it works again; a 'K' while HOLD (refocus running) is ignored */
    sleep_ms(3100);
    send_ack_bytes("K", 1);
    check(wait_mode_count(4, 2000) && last_mode() == 2, "K after 3 s: mode 2 again");
    send_ack_bytes("K", 1);
    check(wait_log("reason=state_HOLD", 1, 2000), "K in HOLD: ignored");
    fc_playback_stop(sink);
    check(wait_mode_count(5, 3000) && last_mode() == 1, "second re-grant: mode 1");
    fc_playback_start(sink);
    check(wait_log("to=ACTIVE", 3, 2000), "ACTIVE third time");
    check(log_count("action=refocus") == 2 && log_count("action=ignored") == 2, "2 refocus, 2 ignored");
    pthread_mutex_lock(&g_m); starts = g_player_starts; stops = g_player_stops; pthread_mutex_unlock(&g_m);
    check(starts == 1 && stops == 0, "player still the first one");

    /* 4: plain ACK bytes still count (no 'K'): they are discarded only because nothing was delivered */
    send_ack_bytes("\001\001\001", 3);
    check(wait_log("event=ack.discard", 2, 2000), "plain ACK bytes still reach the ACK path (2nd discard line)");
    check(n_modes() == 5, "plain ACKs: no focus write");

    /* 5: 'C' (config method): sendConfig(sink, 2), no focus write, player kept; too soon ignored; not ACK */
    discards = log_count("event=ack.discard");
    send_ack_bytes("C", 1);
    check(wait_log("event=focus.config_request action=sent count=1", 1, 2000), "C: setup response resent");
    pthread_mutex_lock(&g_m); cfg = g_configs; pthread_mutex_unlock(&g_m);
    check(cfg == 1 && g_config_arg == 2, "C: sendConfig(sink, 2) once");
    check(n_modes() == 5, "C: no focus write");
    send_ack_bytes("C", 1);
    check(wait_log("event=focus.config_request action=ignored reason=too_soon", 1, 2000), "C too soon: ignored");
    pthread_mutex_lock(&g_m); cfg = g_configs; pthread_mutex_unlock(&g_m);
    check(cfg == 1, "C too soon: no second sendConfig");
    check(log_count("event=ack.discard") == discards, "C bytes are not ACKs (no new discard)");
    pthread_mutex_lock(&g_m); starts = g_player_starts; stops = g_player_stops; pthread_mutex_unlock(&g_m);
    check(starts == 1 && stops == 0, "C: player still the first one");

    sink[4] = 0;                                   /* channel closed */
    fc_notify();
    check(wait_log("reason=channel_closed", 1, 3000), "session end");
    fc_shutdown();
    printf("FAILED CHECKS: %d\n", fails);
    return fails ? 1 : 0;
}
