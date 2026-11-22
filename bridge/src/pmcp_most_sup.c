/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * pmcp-most-sup: MOST supervisor v1 (stage 5, passat-mhi2-carplay docs/23 "Etap 5").
 *
 * One process decides who writes the cluster map channel isoTX2 on the CarPlay side (cable and Wi-Fi) and keeps the
 * factory VW encoder (displaymanager) off the channel through its link /dev/pmcp-isoTX2 (made at every unit start by
 * the pmcp lsd.sh block; with "dm-path pmcp" the encoder opens the channel only through it).
 *
 * The takeover logic follows Tomasz's carplay_cluster_supervisor.c (MU1367 v1.5.0-e, GPL-3.0): stream ready for
 * 400 ms, OEM release (dmdt dc 72, sc 4 72), 500 ms, start the bridge (alive for 750 ms); on loss of the stream for
 * 500 ms or the bridge's exit: stop it (SIGTERM, flush(0), SIGKILL), OEM restore (dmdt dc 70 33, sc 4 70), retry
 * after 2 s. Ours on top:
 *   - Wi-Fi as a second source: MOST contract owner src=wireless + wireless.session state=start of the same gen;
 *   - the channel holder file most-src/isotx2 (holder=cp pid=<this supervisor>, O_EXCL), never over a live AA holder;
 *   - the encoder link: removed before the OEM release, made again BEFORE the OEM restore (the encoder checks its
 *     path when the HMI asks it to encode; build/displaymanager-20261120/REPORT.md);
 *   - at most 3 bridge exits in 60 s, then a 30 s pause;
 *   - one instance (pid file), a log of at most 2 x 32 KB in /ramdisk.
 * It never kills displaymanager or the AA guard and never touches an isotx2 file it does not hold.
 *
 * Host tests (bridge/test/sup_test.py) set every path and the time scale through the environment (PMCP_SUP_*).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "pmcp_most_producer.h"

/* ------------------------------------------------------------------ configuration (environment for tests) */
static const char *env_or(const char *k, const char *d) { const char *v = getenv(k); return v && *v ? v : d; }

static char P_RAM[256], P_APP[256], P_SRC[256], P_DMDT[256], P_LN[256], P_LINK[256], P_DEV[256], P_FLUSH[256];
static char P_BRIDGE[300], P_DISABLED[300], P_READY[300], P_DIOPID[300], P_AAGUARD[300];
static char P_LOGDIR[300], P_LOG[320], P_LOG1[330], P_SUPPID[320];
static unsigned g_div = 1;   /* time divisor (tests) */

static void config(void)
{
    const char *d;
    snprintf(P_RAM, sizeof(P_RAM), "%s", env_or("PMCP_SUP_RAMDISK", "/ramdisk"));
    snprintf(P_APP, sizeof(P_APP), "%s", env_or("PMCP_SUP_APP", "/mnt/app/carplaymaps"));
    snprintf(P_SRC, sizeof(P_SRC), "%s", pmcp_most_src_dir());
    snprintf(P_DMDT, sizeof(P_DMDT), "%s", env_or("PMCP_SUP_DMDT", "/eso/bin/apps/dmdt"));
    snprintf(P_LN, sizeof(P_LN), "%s", env_or("PMCP_SUP_LN", "/bin/ln"));
    snprintf(P_LINK, sizeof(P_LINK), "%s", env_or("PMCP_SUP_LINK", "/dev/pmcp-isoTX2"));
    snprintf(P_DEV, sizeof(P_DEV), "%s", env_or("PMCP_SUP_DEV", "/dev/mlb/isoTX2"));
    snprintf(P_FLUSH, sizeof(P_FLUSH), "%s", env_or("PMCP_SUP_FLUSH", "/dev/mlb/debug/isoTX2"));
    snprintf(P_BRIDGE, sizeof(P_BRIDGE), "%s/altscreen-most-bridge", P_APP);
    snprintf(P_DISABLED, sizeof(P_DISABLED), "%s/stock_first/DISABLED", P_APP);
    snprintf(P_READY, sizeof(P_READY), "%s/carplay-altstream.ready", P_RAM);
    snprintf(P_DIOPID, sizeof(P_DIOPID), "%s/carplay-dio-manager.pid", P_RAM);
    snprintf(P_AAGUARD, sizeof(P_AAGUARD), "%s/pmcp-aa-guard.pid", env_or("PMCP_AA_RUNDIR", P_RAM));
    snprintf(P_LOGDIR, sizeof(P_LOGDIR), "%s/pmcp-most", P_RAM);
    snprintf(P_LOG, sizeof(P_LOG), "%s/sup.log", P_LOGDIR);
    snprintf(P_LOG1, sizeof(P_LOG1), "%s/sup.log.1", P_LOGDIR);
    snprintf(P_SUPPID, sizeof(P_SUPPID), "%s/sup.pid", P_LOGDIR);
    d = getenv("PMCP_SUP_TIME_DIV");
    g_div = d && atoi(d) > 0 ? (unsigned)atoi(d) : 1U;
}

#define MS(x) ((uint64_t)(x) / g_div)
#define POLL_MS          100
#define READY_STABLE_MS  400
#define RELEASE_WAIT_MS  500
#define START_ALIVE_MS   750
#define GRACE_MS         500
#define RESTORE_WAIT_MS  250
#define RETRY_MS         2000
#define EXITS_WINDOW_MS  60000
#define EXITS_MAX        3
#define BACKOFF_MS       30000
#define LOG_LIMIT        32768

/* ------------------------------------------------------------------ log (2 x 32 KB) */
static void sup_log(const char *fmt, ...)
{
    char line[400];
    struct stat st;
    va_list ap;
    int n, fd;
    n = snprintf(line, sizeof(line), "up_ms=%llu ", (unsigned long long)pmcp_now_ms());
    va_start(ap, fmt);
    if (n > 0 && n < (int)sizeof(line)) vsnprintf(line + n, sizeof(line) - (size_t)n, fmt, ap);
    va_end(ap);
    n = (int)strlen(line);
    if (n < (int)sizeof(line) - 1) { line[n++] = '\n'; line[n] = 0; }
    if (stat(P_LOG, &st) == 0 && st.st_size + n > LOG_LIMIT) rename(P_LOG, P_LOG1);
    fd = open(P_LOG, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd >= 0) { (void)!write(fd, line, (size_t)n); close(fd); }
}

/* ------------------------------------------------------------------ small helpers */
static volatile sig_atomic_t g_stop = 0;
static void on_signal(int s) { (void)s; g_stop = 1; }

static long read_pid(const char *path)
{
    char buf[64];
    long v;
    char *end;
    if (pmcp_read_line(path, buf, sizeof(buf)) < 0) return 0;
    errno = 0;
    v = strtol(buf, &end, 10);
    return errno || end == buf || v <= 1 ? 0 : v;
}

static int alive(long pid) { return pid > 1 && pmcp_pid_alive((unsigned long)pid); }

/* run a program and wait; returns its exit status or -1 */
static int run_wait(char *const argv[])
{
    pid_t c = fork();
    int st;
    if (c < 0) return -1;
    if (c == 0) {
        int fd = open("/dev/null", O_RDWR);
        if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
        execv(argv[0], argv);
        _exit(127);
    }
    while (waitpid(c, &st, 0) < 0) if (errno != EINTR) return -1;
    return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

/* ------------------------------------------------------------------ inputs */
/* wired: core.so's ready marker and a live dio_manager (as mathsls's supervisor) */
static int wired_ready(void)
{
    long dio = read_pid(P_DIOPID);
    int marker = access(P_READY, F_OK) == 0;
    if (marker && !alive(dio)) {
        if (unlink(P_READY) == 0) sup_log("stale-ready-cleared dio_pid=%ld", dio);
        return 0;
    }
    return marker;
}

/* Wi-Fi: owner src=wireless, live, with wireless.session state=start of the same gen */
static int wireless_ready(void)
{
    pmcp_owner o;
    pmcp_session s;
    if (pmcp_owner_read(P_SRC, &o) != 0 || strcmp(o.src, "wireless") != 0 || !alive((long)o.pid)) return 0;
    if (pmcp_session_read(P_SRC, "wireless", &s) != 0) return 0;
    return s.start && s.gen == o.gen;
}

/* a live Android Auto holder of the channel (the bridge's own mirror of AA's busy check) */
static long aa_holder(void)
{
    char path[320], buf[256], v[32];
    long g = read_pid(P_AAGUARD);
    if (alive(g)) return g;
    snprintf(path, sizeof(path), "%s/isotx2", P_SRC);
    if (pmcp_read_line(path, buf, sizeof(buf)) >= 0 && pmcp_kv_get(buf, "holder", v, sizeof(v)) == 0 && !strcmp(v, "aa")
        && pmcp_kv_get(buf, "pid", v, sizeof(v)) == 0 && alive(atol(v)))
        return atol(v);
    return 0;
}

/* ------------------------------------------------------------------ channel holder file most-src/isotx2 */
static int holder_take(void)
{
    char path[320], tmp[340], line[160], buf[256], v[32];
    int fd, tries;
    snprintf(path, sizeof(path), "%s/isotx2", P_SRC);
    snprintf(tmp, sizeof(tmp), "%s/isotx2.tmp.%ld", P_SRC, (long)getpid());
    snprintf(line, sizeof(line), "v=1 holder=cp pid=%ld since_ms=%llu\n", (long)getpid(),
             (unsigned long long)pmcp_now_ms());
    mkdir(P_SRC, 0755);
    for (tries = 0; tries < 2; tries++) {
        unlink(tmp);
        fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL, 0644);
        if (fd < 0) return -1;
        if (write(fd, line, strlen(line)) != (ssize_t)strlen(line)) { close(fd); unlink(tmp); return -1; }
        close(fd);
        if (link(tmp, path) == 0) { unlink(tmp); return 0; }
        unlink(tmp);
        if (errno != EEXIST) return -1;
        /* a dead holder may be cleared, only after reading the same pid again */
        if (pmcp_read_line(path, buf, sizeof(buf)) < 0 || pmcp_kv_get(buf, "pid", v, sizeof(v)) != 0) return -1;
        if (alive(atol(v))) { errno = EBUSY; return -1; }
        {
            char again[256], v2[32];
            if (pmcp_read_line(path, again, sizeof(again)) < 0 || pmcp_kv_get(again, "pid", v2, sizeof(v2)) != 0
                || strcmp(v, v2) != 0)
                return -1;
        }
        unlink(path);
        sup_log("isotx2-dead-holder-cleared pid=%s", v);
    }
    return -1;
}

static void holder_release(void)
{
    char path[320], buf[256], v[32];
    snprintf(path, sizeof(path), "%s/isotx2", P_SRC);
    if (pmcp_read_line(path, buf, sizeof(buf)) >= 0 && pmcp_kv_get(buf, "holder", v, sizeof(v)) == 0 && !strcmp(v, "cp")
        && pmcp_kv_get(buf, "pid", v, sizeof(v)) == 0 && atol(v) == (long)getpid())
        unlink(path);
}

/* ------------------------------------------------------------------ encoder link and OEM MOST */
static void link_drop(void)
{
    if (unlink(P_LINK) == 0) sup_log("dm-link-dropped");
    else if (errno != ENOENT) sup_log("dm-link-drop-failed errno=%d", errno);
}

static void link_make(void)
{
    struct stat st;
    char *argv[] = { P_LN, "-Ps", P_DEV, P_LINK, NULL };
    int r;
    if (lstat(P_LINK, &st) == 0) return;
    /* MU1161 has no /proc/boot/ln (car 2026-11-22: status=127); without ln the giveback goes on, logged once per try */
    if (access(P_LN, X_OK) != 0) { sup_log("dm-link-make-failed no-ln path=%s errno=%d", P_LN, errno); return; }
    r = run_wait(argv);
    sup_log("dm-link-made status=%d", r);
}

static int oem_release(void)
{
    char *dc[] = { P_DMDT, "dc", "72", NULL };
    char *sc[] = { P_DMDT, "sc", "4", "72", NULL };
    int a = run_wait(dc), b = run_wait(sc);
    sup_log("oem-most-release dc=%d sc=%d", a, b);
    return a == 0 && b == 0 ? 0 : -1;
}

static int oem_restore(void)
{
    char *dc[] = { P_DMDT, "dc", "70", "33", NULL };
    char *sc[] = { P_DMDT, "sc", "4", "70", NULL };
    int a = run_wait(dc), b = run_wait(sc);
    sup_log("oem-most-restore dc=%d sc=%d", a, b);
    return a == 0 && b == 0 ? 0 : -1;
}

/* ------------------------------------------------------------------ the bridge */
static pid_t g_bridge = -1;

static int bridge_start(void)
{
    pid_t c;
    int i, st;
    c = fork();
    if (c < 0) return -1;
    if (c == 0) {
        int fd = open("/dev/null", O_RDWR);
        if (fd >= 0) { dup2(fd, 0); dup2(fd, 1); dup2(fd, 2); if (fd > 2) close(fd); }
        unsetenv("LD_PRELOAD");
        execl(P_BRIDGE, P_BRIDGE, (char *)NULL);
        _exit(127);
    }
    for (i = 0; i < 15; i++) {
        pmcp_sleep_ms((unsigned)MS(START_ALIVE_MS / 15));
        if (waitpid(c, &st, WNOHANG) == c) { sup_log("bridge-start-failed pid=%ld status=%d", (long)c, st); return -1; }
    }
    g_bridge = c;
    sup_log("bridge-started pid=%ld", (long)c);
    return 0;
}

static int bridge_wait(unsigned tenths)
{
    int st;
    unsigned i;
    for (i = 0; i < tenths; i++) {
        if (waitpid(g_bridge, &st, WNOHANG) == g_bridge) return 1;
        pmcp_sleep_ms((unsigned)MS(100));
    }
    return 0;
}

static void bridge_stop(void)
{
    if (g_bridge <= 0) return;
    kill(g_bridge, SIGTERM);
    if (bridge_wait(10)) { sup_log("bridge-stopped"); g_bridge = -1; return; }
    {
        int fd = open(P_FLUSH, O_WRONLY | O_NONBLOCK);
        if (fd >= 0) { (void)!write(fd, "flush(0)\n", 9); close(fd); }
    }
    if (bridge_wait(40)) { sup_log("bridge-stopped-after-flush"); g_bridge = -1; return; }
    kill(g_bridge, SIGKILL);
    waitpid(g_bridge, NULL, 0);
    sup_log("bridge-killed");
    g_bridge = -1;
}

/* ------------------------------------------------------------------ takeover and giveback */
static int takeover(void)
{
    if (holder_take() != 0) { sup_log("takeover-busy errno=%d", errno); return -1; }
    link_drop();
    if (oem_release() != 0) { link_make(); oem_restore(); holder_release(); return -1; }
    pmcp_sleep_ms((unsigned)MS(RELEASE_WAIT_MS));
    if (bridge_start() != 0) { link_make(); oem_restore(); holder_release(); return -1; }
    return 0;
}

static void giveback(const char *why)
{
    sup_log("giveback reason=%s", why);
    bridge_stop();
    link_make();   /* before the restore: the encoder checks its path when the HMI asks it to encode */
    pmcp_sleep_ms((unsigned)MS(RESTORE_WAIT_MS));
    oem_restore();
    holder_release();
}

/* ------------------------------------------------------------------ one instance */
static int lock_take(void)
{
    char line[32];
    int fd, tries;
    mkdir(P_LOGDIR, 0755);
    snprintf(line, sizeof(line), "%ld\n", (long)getpid());
    for (tries = 0; tries < 2; tries++) {
        fd = open(P_SUPPID, O_WRONLY | O_CREAT | O_EXCL, 0644);
        if (fd >= 0) { (void)!write(fd, line, strlen(line)); close(fd); return 0; }
        if (errno != EEXIST) return -1;
        if (alive(read_pid(P_SUPPID))) return -1;
        unlink(P_SUPPID);
    }
    return -1;
}

int main(void)
{
    int active = 0;
    uint64_t ready_since = 0, missing_since = 0, next_try = 0;
    uint64_t exits[EXITS_MAX];
    unsigned nexit = 0;
    int aa_logged = 0;

    config();
    mkdir(P_LOGDIR, 0755);
    if (lock_take() != 0) { sup_log("already-running"); return 0; }
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGHUP, on_signal);
    signal(SIGPIPE, SIG_IGN);
    sup_log("supervisor-started pid=%ld", (long)getpid());
    memset(exits, 0, sizeof(exits));

    while (!g_stop) {
        uint64_t now = pmcp_now_ms();
        int wired = wired_ready(), wifi = wireless_ready(), want = wired || wifi;
        long aa = aa_holder();

        if (access(P_DISABLED, F_OK) == 0) { sup_log("disabled"); break; }
        if (!active) {
            if (want && !aa) {
                if (!ready_since) ready_since = now;
                if (now >= next_try && now - ready_since >= MS(READY_STABLE_MS)) {
                    if (takeover() == 0) {
                        active = 1; missing_since = 0;
                        sup_log("state-cp-active source=%s", wired ? "wired" : "wireless");
                    } else {
                        next_try = now + MS(RETRY_MS); ready_since = 0;
                        sup_log("takeover-failed");
                    }
                }
            } else {
                ready_since = 0;
                if (want && aa && !aa_logged) { sup_log("wait-aa-holder pid=%ld", aa); aa_logged = 1; }
                if (!aa) aa_logged = 0;
            }
        } else {
            int st;
            if (waitpid(g_bridge, &st, WNOHANG) == g_bridge) {
                sup_log("bridge-exited pid=%ld status=%d", (long)g_bridge, st);
                g_bridge = -1;
                giveback("bridge-exited");
                active = 0; ready_since = 0; next_try = now + MS(RETRY_MS);
                exits[nexit % EXITS_MAX] = now; nexit++;
                if (nexit >= EXITS_MAX && now - exits[nexit % EXITS_MAX] <= MS(EXITS_WINDOW_MS)) {
                    next_try = now + MS(BACKOFF_MS);
                    sup_log("bridge-backoff exits=%u", EXITS_MAX);
                }
                continue;
            }
            if (!want) {
                if (!missing_since) missing_since = now;
                if (now - missing_since >= MS(GRACE_MS)) {
                    giveback("stream-timeout");
                    active = 0; ready_since = 0; next_try = now + MS(RETRY_MS);
                    sup_log("state-oem-active");
                }
            } else {
                missing_since = 0;
            }
        }
        pmcp_sleep_ms((unsigned)MS(POLL_MS) ? (unsigned)MS(POLL_MS) : 1U);
    }
    if (active) giveback(g_stop ? "signal" : "disabled");
    unlink(P_SUPPID);
    sup_log("supervisor-stopped");
    return 0;
}
