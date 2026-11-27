/* SPDX-License-Identifier: GPL-3.0-only
 *
 * pmcp-most stage 2: the CarPlay MOST bridge on the shared MOST output library
 * of Android Auto (aa/most: ts_mux + most_writer). One output code for CP and
 * AA (user decision 2026-11-16, shape (B): one library, two processes; the API
 * is kept ready for one process later).
 *
 * Input and contract are those of stage 1c (pmcp_most.h): the AltScreen ring
 * written by core.so, the IDR request marker, the consumer gate, producer
 * sessions, the consumer status and the event file. The binary keeps the name
 * altscreen-most-bridge and the command line (argv[1] = MOST device), so the
 * mathsls supervisor runs it unchanged.
 *
 * CarPlay policy on top of the library (public API only; aa/most is not
 * changed, so the AA feeder binary stays as pinned):
 *   - lateness: when more than PMCP_CP_LIMIT_PACKETS TS packets are queued, or
 *     the phone's frame chain has a gap, no AU is put until a keyframe. The
 *     queued whole AUs drain (at most about 250 ms at 12.288 Mbit/s; nothing is
 *     truncated). The IDR is requested once the writer has completed
 *     PMCP_CP_RECOVERY_BLOCKS blocks since the reset and its last write was
 *     fast (<= 30 ms), as stage 1c. The resuming keyframe carries the
 *     discontinuity flag (ts_mux_discontinuity).
 *   - PTS: the library stamps each AU when its first TS packet is built from
 *     the put time (never behind PCR), instead of the bridge's enqueue time.
 *   - reclaim: a write that fails with ENOMEM in the first 180 s of uptime
 *     (the factory encoder took isoTX2 while the unit booted) stops the
 *     writer, runs dmdt dc 72 and sc 4 72, waits 500 ms and reopens the device
 *     (most_stop, most_reopen, ts_mux_discontinuity, most_start), at most 3
 *     times; then the IDR is requested as after a latency reset. Any other
 *     writer failure ends the bridge (the supervisor restarts it).
 *   - isoTX2 held by Android Auto (arbitration step (a), docs/23, reviewed by AA): before opening the
 *     device the bridge reads AA's guardian pid file (<PMCP_AA_RUNDIR or /ramdisk>/pmcp-aa-guard.pid, present
 *     from AA's MOST takeover until its dmdt restore is done) and the future owner file
 *     /ramdisk/most-src/isotx2 (holder=aa pid=<guardian>). A live holder (kill(pid,0) == 0 or EPERM) that is
 *     not our parent (AA's ring mode starts this binary from its guardian) means: no open, event
 *     most-busy, exit 0, the same as a refused START. The bridge never writes the owner file: the mathsls
 *     supervisor, not the bridge, gives MOST back to the VW map (owner file for CP only with our own
 *     supervisor, stage 5).
 *   - stuck write: a write running longer than stall_ms + 1 s gets
 *     "flush(0)" on the debug node (as the supervisor does) and ends the bridge.
 *
 * Provenance: the ring reading, the dmdt runner and the reclaim sequence follow
 * altscreen_most_bridge.c of Tomasz Twardzicki (fork of omonob's bridge,
 * GPL-3.0-only); the output library is GPL-3.0-or-later (AA session). */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define PMCP_MOST_STAGE "2"
#define PMCP_MOST_LOG_STAGE "2"

#include "altscreen_frame_protocol.h"
#include "cpmap_resources.h"
#include "pmcp_most.h"
#include "most_writer.h"
#include "ts_mux.h"
#ifdef __QNX__
#include <sched.h>
#endif

#ifndef ALTSCREEN_BRIDGE_DMDT_PATH
#define ALTSCREEN_BRIDGE_DMDT_PATH "/eso/bin/apps/dmdt"
#endif
#ifndef ALTSCREEN_BRIDGE_RECLAIM_WINDOW_US
#define ALTSCREEN_BRIDGE_RECLAIM_WINDOW_US 180000000ULL /* CLOCK_MONOTONIC = time since boot */
#endif
#define PMCP_CP_RECLAIM_MAX 3U
/* Thread priority (after tomasz-twardzicki MU1367 v1.5.3, measured there in a car): with the reverse
 * camera on, the CPU reaches 98-100 % for seconds and the navigation renderer threads run at 10, the
 * priority the bridge inherited, so the bridge got no CPU long enough to overrun the ring. A resource
 * manager serves a write at its client's priority, so devp-iso-mmx (16) handled our writes at 10 too.
 * 14: above the navigation threads seen there (MapPositioning 13), below the MOST driver (16) and the
 * CarPlay receive threads (17-19). Only ever raised, never lowered; 0 = leave as inherited. */
#ifndef PMCP_MOST_PRIORITY
#define PMCP_MOST_PRIORITY 14
#endif
static void raise_priority(pthread_t th, const char *name);
#define PMCP_CP_RECLAIM_SETTLE_US 500000U
#define PMCP_CP_DMDT_TIMEOUT_POLLS 300U         /* 10 ms each */
#define PMCP_CP_LIMIT_PACKETS 2048U             /* as stage 1c (TS_LOW_LATENCY_LIMIT_PACKETS) */
#define PMCP_CP_RECOVERY_BLOCKS 8U              /* blocks written since the reset before the IDR request */
#define PMCP_CP_FAST_WRITE_US 30000ULL
#define PMCP_CP_POOL_BYTES (4U * 1024U * 1024U) /* AU bytes; a ring slot holds at most 256 KB */
#define PMCP_CP_POOL_ENTRIES 1024U
#define PMCP_CP_METRICS_US 5000000ULL           /* one metrics line every 5 s */
#define PMCP_CP_WRITER_CHECK_US 5000ULL
#define PMCP_CP_DEBUG_DEV "/dev/mlb/debug/isoTX2"

extern char **environ;

static volatile sig_atomic_t g_stop;
static ts_mux_t g_mux;
static most_writer_t g_w;
static most_cfg_t g_wcfg;

/* CarPlay policy state (reader thread only). */
static int g_waiting_key = 1;         /* no AU is put until a keyframe */
static int g_idr_requested;
static uint64_t g_wait_start_us;
static uint64_t g_wait_blocks;        /* writer blocks at the reset */
static uint32_t g_last_source_seq;
static unsigned long g_frames, g_keyframes, g_drops, g_latency_resets, g_waited_frames, g_put_full;
static unsigned int g_reclaims;
static uint8_t g_length_size = 4;     /* AVCC length bytes of the current avcC */
static int g_have_params;
static uint8_t g_sps[TS_PS_MAX], g_pps[TS_PS_MAX];
static uint32_t g_sps_len, g_pps_len;
static uint8_t *g_au;                 /* 4-byte-length copy of a frame (length_size != 4) */

static uint64_t monotonic_us(void)
{
    return pmcp_now_us();
}

static void on_signal(int signal_number)
{
    (void)signal_number;
    g_stop = 1;
    g_pmcp_most_ready = 0;
}

static int request_fresh_idr(void)
{
    int fd = open(ALT_FRAME_FORCE_IDR_PATH, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return -1;
    close(fd);
    return 0;
}

/* dmdt with the factory environment, stdio on /dev/null, at most 3 s (Tomasz's run_dmdt). */
static int run_dmdt(const char *a, const char *b, const char *c)
{
    static char ipl[] = "IPL_CONFIG_DIR=/etc/eso/production";
    static char lib[] = "LD_LIBRARY_PATH=/mnt/app/root/lib-target:/eso/lib:/mnt/app/usr/lib:"
                        "/mnt/app/armle/lib:/mnt/app/armle/lib/dll:/mnt/app/armle/usr/lib";
    char *argv[5];
    char **envp;
    size_t count = 0, used = 0, i;
    unsigned int poll;
    int null_fd, status;
    pid_t child;
    argv[0] = (char *)ALTSCREEN_BRIDGE_DMDT_PATH;
    argv[1] = (char *)a;
    argv[2] = (char *)b;
    argv[3] = (char *)c;
    argv[4] = NULL;
    while (environ != NULL && environ[count] != NULL) ++count;
    envp = (char **)calloc(count + 3U, sizeof(*envp));
    if (envp == NULL) return -1;
    for (i = 0; i < count; ++i) {
        if (strncmp(environ[i], "LD_PRELOAD=", 11) == 0 ||
            strncmp(environ[i], "IPL_CONFIG_DIR=", 15) == 0 ||
            strncmp(environ[i], "LD_LIBRARY_PATH=", 16) == 0) continue;
        envp[used++] = environ[i];
    }
    envp[used++] = ipl;
    envp[used++] = lib;
    envp[used] = NULL;
    null_fd = open("/dev/null", O_RDWR);
    child = fork();
    if (child < 0) {
        if (null_fd >= 0) close(null_fd);
        free(envp);
        return -1;
    }
    if (child == 0) {
        if (null_fd >= 0) {
            dup2(null_fd, 0);
            dup2(null_fd, 1);
            dup2(null_fd, 2);
        }
        execve(argv[0], argv, envp);
        _exit(127);
    }
    if (null_fd >= 0) close(null_fd);
    free(envp);
    for (poll = 0; poll < PMCP_CP_DMDT_TIMEOUT_POLLS; ++poll) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) return WIFEXITED(status) ? WEXITSTATUS(status) : -2;
        if (result < 0 && errno != EINTR) return -1;
        usleep(10000);
    }
    kill(child, SIGKILL);
    (void)waitpid(child, &status, 0);
    return -3;
}

static void log_devinfo(const char *what)
{
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: %s %s open_errno=%d interface status=%d value=%u packet-size status=%d value=%u "
            "block-count status=%d value=%u queue-flush status=%d start status=%d packets=%u\n",
            what, g_wcfg.dev, g_w.dev.open_errno, g_w.dev.iface_rc, g_w.dev.iface, g_w.dev.packet_rc,
            g_w.dev.packet_size, g_w.dev.block_rc, g_w.dev.block_count, g_w.dev.flush_rc, g_w.dev.start_rc,
            TS_BLOCK_PACKETS);
}

/* ---------------------------------------------------------------- isoTX2 arbitration, step (a) */

static int pid_live(long pid)
{
    return pid > 0 && (kill((pid_t)pid, 0) == 0 || errno == EPERM);
}

/* pid of a live Android Auto holder of isoTX2 other than our parent, else 0; *how names the source. */
static long aa_holder(const char **how)
{
    char path[256], buf[PMCP_MOST_LINE_MAX + 2U], src[16];
    const char *dir = getenv("PMCP_AA_RUNDIR");
    unsigned long pid = 0;
    int fd, n;
    if (dir == NULL || dir[0] == '\0') dir = "/ramdisk";
    snprintf(path, sizeof(path), "%s/pmcp-aa-guard.pid", dir);
    fd = open(path, O_RDONLY);
    if (fd >= 0) {
        n = (int)read(fd, buf, sizeof(buf) - 1U);
        close(fd);
        if (n > 0) {
            buf[n] = '\0';
            pid = strtoul(buf, NULL, 10);
            if (pid_live((long)pid) && (pid_t)pid != getppid()) {
                *how = "aa-guard-pid";
                return (long)pid;
            }
        }
    }
    if (pmcp_read_name("isotx2", buf, sizeof(buf)) > 0 && pmcp_field(buf, "holder", src, sizeof(src)) == 0 &&
        strcmp(src, "aa") == 0 && pmcp_field_ul(buf, "pid", &pid) == 0 && pid_live((long)pid) &&
        (pid_t)pid != getppid()) {
        *how = "isotx2-file";
        return (long)pid;
    }
    return 0;
}

/* ---------------------------------------------------------------- CarPlay policy */

static uint64_t writer_blocks(void)
{
    most_stats_t st;
    most_snapshot(&g_w, &st);
    return st.blocks;
}

static void enter_recovery(const char *why, uint32_t sequence, uint32_t queued)
{
    g_waiting_key = 1;
    g_idr_requested = 0;
    g_wait_start_us = monotonic_us();
    g_wait_blocks = writer_blocks();
    ++g_latency_resets;
    unlink(ALT_FRAME_FORCE_IDR_PATH);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: latency-reset sequence=%u queued=%lu discarded=0 limit=%u idr_request_deferred=1 "
            "resets=%lu reason=%s\n", sequence, (unsigned long)queued, PMCP_CP_LIMIT_PACKETS,
            g_latency_resets, why);
    pmcp_event("latency-reset seq=%u queued=%lu discarded=0 limit=%u resets=%lu reason=%s", sequence,
               (unsigned long)queued, PMCP_CP_LIMIT_PACKETS, g_latency_resets, why);
}

/* A new stream (start, ring generation, owner cut): wait for a keyframe, ask for it at once. */
static void new_stream(const char *why)
{
    g_waiting_key = 1;
    g_idr_requested = 1;
    g_wait_start_us = monotonic_us();
    g_last_source_seq = 0;
    if (request_fresh_idr() != 0)
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: reconnect IDR request failed: %s\n",
                strerror(errno));
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: %s; waiting for fresh IDR\n", why);
}

static int writer_recovered(void)
{
    most_stats_t st;
    most_snapshot(&g_w, &st);
    return st.blocks - g_wait_blocks >= PMCP_CP_RECOVERY_BLOCKS && st.write_us_last <= PMCP_CP_FAST_WRITE_US;
}

/* avcC (type 1 slot): the first SPS and PPS; the parameter sets go to the mux in queue order. */
static int on_config(const uint8_t *d, uint32_t n)
{
    uint32_t off = 6, sps_len, pps_len;
    uint8_t length_size;
    const uint8_t *sps, *pps;
    int same;
    if (n < 7 || d[0] != 1U || (d[5] & 0x1fU) == 0) return -1;
    length_size = (uint8_t)((d[4] & 3U) + 1U);
    if (off + 2 > n) return -1;
    sps_len = ((uint32_t)d[off] << 8) | d[off + 1];
    off += 2;
    if (sps_len == 0 || sps_len > TS_PS_MAX || off + sps_len > n) return -1;
    sps = d + off;
    off += sps_len;
    {   /* only the first SPS is used: skip the others */
        unsigned k;
        for (k = 1; k < (d[5] & 0x1fU); ++k) {
            uint32_t l;
            if (off + 2 > n) return -1;
            l = ((uint32_t)d[off] << 8) | d[off + 1];
            off += 2 + l;
        }
    }
    if (off + 3 > n || d[off] == 0) return -1;
    off += 1;
    pps_len = ((uint32_t)d[off] << 8) | d[off + 1];
    off += 2;
    if (pps_len == 0 || pps_len > TS_PS_MAX || off + pps_len > n) return -1;
    pps = d + off;
    same = g_have_params && length_size == g_length_size && sps_len == g_sps_len && pps_len == g_pps_len &&
           memcmp(sps, g_sps, sps_len) == 0 && memcmp(pps, g_pps, pps_len) == 0;
    if (!same || g_pmcp.avcc_log_next) {
        if (ts_mux_put_params(&g_mux, sps, sps_len, pps, pps_len) != 0) return -1;
        memcpy(g_sps, sps, sps_len);
        memcpy(g_pps, pps, pps_len);
        g_sps_len = sps_len;
        g_pps_len = pps_len;
        g_length_size = length_size;
        g_have_params = 1;
        g_pmcp.avcc_log_next = 0;
        if (!same) pmcp_event("avcC length=%u sps=%u pps=%u", length_size, sps_len, pps_len);
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: avcC ready length=%u sps=%u pps=%u\n",
                length_size, sps_len, pps_len);
    } else {
        ++g_pmcp.avcc_repeats;
    }
    return 0;
}

/* Video slot: AVCC with g_length_size-byte lengths. Returns the 4-byte-length AU (in place or in g_au) and
 * whether it holds an IDR slice; NULL when malformed. */
static const uint8_t *to_avcc4(const uint8_t *d, uint32_t n, uint32_t *out_len, int *idr)
{
    uint32_t off = 0, w = 0, ls = g_length_size;
    *idr = 0;
    while (off < n) {
        uint32_t len = 0, k;
        if (off + ls > n) return NULL;
        for (k = 0; k < ls; ++k) len = (len << 8) | d[off + k];
        off += ls;
        if (len == 0 || len > n - off) return NULL;
        if ((d[off] & 0x1fU) == 5U) *idr = 1;
        if (ls != 4U) {
            if (w + 4U + len > ALT_FRAME_RING_SLOT_DATA_MAX + ALT_FRAME_RING_SLOT_DATA_MAX / 2U) return NULL;
            g_au[w] = (uint8_t)(len >> 24); g_au[w + 1] = (uint8_t)(len >> 16);
            g_au[w + 2] = (uint8_t)(len >> 8); g_au[w + 3] = (uint8_t)len;
            memcpy(g_au + w + 4, d + off, len);
            w += 4U + len;
        }
        off += len;
    }
    *out_len = ls == 4U ? n : w;
    return ls == 4U ? d : g_au;
}

/* Returns 0 = put (or knowingly dropped by the policy), -1 = malformed. */
static uint64_t g_frame_ntp;   /* ring NTP of the frame on_video handles (A249) */
static uint64_t au_time_us(uint64_t now_us, uint64_t ntp);

static int on_video(const uint8_t *d, uint32_t n, uint32_t flags, uint32_t sequence, uint32_t source_seq)
{
    uint32_t len, queued;
    int idr, key, rc;
    const uint8_t *au = to_avcc4(d, n, &len, &idr);
    int restart, gap;
    if (au == NULL) return -1;
    key = idr || (flags & ALT_FRAME_FLAG_KEYFRAME) != 0;
    restart = source_seq <= 2U && g_last_source_seq > 100U;
    gap = g_last_source_seq != 0U && !restart && source_seq != g_last_source_seq + 1U;
    g_last_source_seq = source_seq;
    ts_mux_depth(&g_mux, &queued, NULL);
    if (!g_waiting_key && (restart || gap)) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                "bridge: predictive-chain-gap current=%u restart=%d\n", source_seq, restart);
        pmcp_event("chain-gap current=%u restart=%d", source_seq, restart);
        enter_recovery("chain-gap", sequence, queued);
    } else if (!g_waiting_key && queued > PMCP_CP_LIMIT_PACKETS) {
        enter_recovery("backlog", sequence, queued);
    }
    if (g_waiting_key) {
        if (!g_idr_requested) {
            if (!writer_recovered()) {
                ++g_waited_frames;
                if ((g_waited_frames % 30U) == 1U)
                    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                            "bridge: latency-wait-writer sequence=%u dropped_frames=%lu wait_us=%llu queued=%u\n",
                            sequence, g_waited_frames,
                            (unsigned long long)(monotonic_us() - g_wait_start_us), queued);
                return 0;
            }
            if (!key) {
                int status = request_fresh_idr();
                uint64_t waited = monotonic_us() - g_wait_start_us;
                if (status == 0) g_idr_requested = 1;
                cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                        "bridge: latency-request-idr sequence=%u status=%d wait_us=%llu queued=%u\n",
                        sequence, status, (unsigned long long)waited, queued);
                pmcp_event("idr-request seq=%u status=%d wait_ms=%llu", sequence, status,
                           (unsigned long long)(waited / 1000ULL));
            }
        }
        if (!key) {
            ++g_waited_frames;
            return 0;
        }
        {
            uint64_t waited = monotonic_us() - g_wait_start_us;
            g_waiting_key = 0;
            g_idr_requested = 0;
            ts_mux_discontinuity(&g_mux);
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: latency-resume-idr sequence=%u wait_us=%llu extra_discarded=0 queued=%u\n",
                    sequence, (unsigned long long)waited, queued);
            pmcp_event("idr-resume seq=%u wait_ms=%llu extra_discarded=0", sequence,
                       (unsigned long long)(waited / 1000ULL));
        }
    }
    rc = ts_mux_put_avcc(&g_mux, au, len, key, au_time_us(monotonic_us(), g_frame_ntp), sequence);
    if (rc == -1) {
        /* pool or entry table full: the writer is far behind; a latency reset drops until a keyframe */
        ++g_put_full;
        enter_recovery("pool-full", sequence, queued);
        return 0;
    }
    if (rc != 0) return -1;
    ++g_frames;
    if (key) ++g_keyframes;
    return 0;
}

/* ---------------------------------------------------------------- writer supervision */

static void writer_failed_status(const most_stats_t *st)
{
    g_pmcp_most_ready = 0;
    g_pmcp_most_errno = st->fail_errno;
}

/* Called every few ms by the reader. Returns 0 = writing, -1 = end the bridge. */
static int check_writer(void)
{
    most_stats_t st;
    uint64_t now = monotonic_us();
    int err;
    if (most_write_age_us(&g_w, now) > ((uint64_t)g_wcfg.stall_ms + 1000U) * 1000U) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: MOST write stuck > %u ms: debug flush\n",
                g_wcfg.stall_ms + 1000U);
        pmcp_event("most-error stuck_write_ms=%u", g_wcfg.stall_ms + 1000U);
        most_debug_flush(PMCP_CP_DEBUG_DEV);
        g_pmcp_most_ready = 0;
        return -1;
    }
    most_snapshot(&g_w, &st);
    if (!st.failed) return 0;
    err = st.fail_errno;
    writer_failed_status(&st);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: MOST write failed: %s (%s) blocks=%llu\n",
            strerror(err), st.fail_what, (unsigned long long)st.blocks);
    {
        uint32_t queued;
        ts_mux_depth(&g_mux, &queued, NULL);
        pmcp_event("most-error errno=%d blocks=%llu queue=%u reclaims=%u", err, (unsigned long long)st.blocks,
                   queued, g_reclaims);
    }
    if (g_stop) return -1;
    if (err == ENOMEM && g_reclaims < PMCP_CP_RECLAIM_MAX && now < ALTSCREEN_BRIDGE_RECLAIM_WINDOW_US) {
        int dc, sc = -1, rc;
        uint32_t queued;
        ++g_reclaims;
        most_stop(&g_w, 0); /* the writer thread has ended; no write is left in flight */
        dc = run_dmdt("dc", "72", NULL);
        if (dc == 0) sc = run_dmdt("sc", "4", "72");
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: most-reclaim attempt=%u uptime_ms=%llu dmdt=%d/%d\n",
                g_reclaims, (unsigned long long)(monotonic_us() / 1000ULL), dc, sc);
        if (g_stop) return -1;
        usleep(PMCP_CP_RECLAIM_SETTLE_US);
        if (g_stop) return -1;
        rc = most_reopen(&g_w);
        if (rc == 0) {
            ts_mux_discontinuity(&g_mux);
            rc = most_start(&g_w, &g_mux);
            if (rc == 0) raise_priority(g_w.th, "writer");
        }
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: most-reclaim attempt=%u reopen=%s\n", g_reclaims,
                rc == 0 ? "ok" : "failed");
        pmcp_event("reclaim attempt=%u dmdt=%d/%d reopen=%s", g_reclaims, dc, sc, rc == 0 ? "ok" : "failed");
        if (rc != 0) {
            log_devinfo("reopen failed");
            g_pmcp_most_errno = g_w.dev.open_errno ? g_w.dev.open_errno : EIO;
            return -1;
        }
        g_pmcp_most_ready = 1;
        g_pmcp_most_errno = err;
        ts_mux_depth(&g_mux, &queued, NULL);
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: most-reclaim-resync queued=%u reclaims=%u\n",
                queued, g_reclaims);
        pmcp_event("reclaim-resync queued=%u reclaims=%u", queued, g_reclaims);
        enter_recovery("reclaim", 0, queued);
        return 0;
    }
    if (err == ENOMEM) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                "bridge: most-reclaim not-attempted reclaims=%u max=%u uptime_ms=%llu\n",
                g_reclaims, PMCP_CP_RECLAIM_MAX, (unsigned long long)(now / 1000ULL));
        pmcp_event("reclaim-not-attempted reclaims=%u max=%u", g_reclaims, PMCP_CP_RECLAIM_MAX);
    }
    return -1;
}

/* A249: the time an AU is put into the mux (its PTS follows it). The read time, except when the bridge reads
   frames that the producer made apart in one go (a backlog after a slow loop): then the producer's spacing (ring
   NTP timestamps) on from the previous AU, so two frames never get PTS 0.01 ms apart (the AID decoder dropped such
   frames: zoom artifacts until the next IDR, car 27.11; sim scenario zoom). Never earlier than the previous one. */
static uint64_t g_t_last_eff, g_ntp_last;
static int g_t_have;

static uint64_t ntp_to_us(uint64_t ntp)
{
    return (ntp >> 32) * 1000000ULL + (((ntp & 0xffffffffULL) * 1000000ULL) >> 32);
}

static void au_time_reset(void)
{
    g_t_have = 0;
}

static uint64_t au_time_us(uint64_t now_us, uint64_t ntp)
{
    uint64_t t = now_us;
    if (g_t_have && ntp > g_ntp_last) {
        uint64_t d = ntp_to_us(ntp - g_ntp_last);
        if (d <= 200000ULL && now_us < g_t_last_eff + d / 2U) t = g_t_last_eff + d;
    }
    if (g_t_have && t < g_t_last_eff) t = g_t_last_eff;
    g_t_last_eff = t;
    g_ntp_last = ntp;
    g_t_have = 1;
    return t;
}

static void log_metrics(void)
{
    most_stats_t w;
    ts_mux_stats_t m;
    uint32_t queued;
    most_snapshot(&g_w, &w);
    ts_mux_snapshot(&g_mux, &m);
    ts_mux_depth(&g_mux, &queued, NULL);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: metrics blocks=%llu queue=%u queue_hi=%u frames=%lu keys=%lu drops=%lu aus_out=%llu "
            "write_us=%llu write_us_max=%llu slow_writes=%llu hist_write_us=%llu,%llu,%llu,%llu,%llu,%llu "
            "eagain=%llu lead_first_min=%lld lead_last_min=%lld pts_rebase=%llu/%llu pts_slew=%llu pts_forced=%llu\n",
            (unsigned long long)w.blocks, queued, m.queue_packets_hi, g_frames, g_keyframes, g_drops,
            (unsigned long long)m.aus_out, (unsigned long long)w.write_us_last,
            (unsigned long long)w.write_us_max, (unsigned long long)w.slow_writes,
            (unsigned long long)w.hist[0], (unsigned long long)w.hist[1], (unsigned long long)w.hist[2],
            (unsigned long long)w.hist[3], (unsigned long long)w.hist[4], (unsigned long long)w.hist[5],
            (unsigned long long)w.eagain, (long long)m.lead_first_min, (long long)m.lead_last_min,
            (unsigned long long)m.pts_rebase_up, (unsigned long long)m.pts_rebase_down,
            (unsigned long long)m.pts_slew_down, (unsigned long long)m.pts_forced_step);
}

static void status_now(uint32_t generation, uint32_t next_sequence, uint64_t now_us)
{
    PmcpConsumerStats s;
    ts_mux_stats_t m;
    uint32_t queued;
    memset(&s, 0, sizeof(s));
    ts_mux_snapshot(&g_mux, &m);
    ts_mux_depth(&g_mux, &queued, NULL);
    s.ring_gen = generation;
    s.seq = next_sequence ? next_sequence - 1U : 0U;
    s.frames = g_frames;
    s.drops = g_drops;
    s.latency_resets = g_latency_resets;
    s.reclaims = g_reclaims;
    s.queue_pkts = queued;
    s.queue_hi = m.queue_packets_hi;
    pmcp_status_write(&s, (int)g_pmcp_most_ready, now_us);
}

/* The consumer gate opened (contract v1.1, R94): ask the producer for an IDR. */
static void gate_opened(void)
{
    if (request_fresh_idr() != 0)
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: reconnect IDR request failed: %s\n",
                strerror(errno));
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: gate-open reason=%s gate_forced=%lu\n",
            pmcp_gate_reason(), (unsigned long)g_pmcp_gate.forced);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: gate-stats cuts=%lu forced=%lu gate_drops=%lu wait_ms=%llu\n",
            (unsigned long)g_pmcp_gate.cuts, (unsigned long)g_pmcp_gate.forced, g_pmcp.gate_drops,
            (unsigned long long)(monotonic_us() / 1000ULL - g_pmcp_gate.cut_ms));
    pmcp_event("gate-open reason=%s gate_drops=%lu", pmcp_gate_reason(), g_pmcp.gate_drops);
}

/* Raises one thread of this process to PMCP_MOST_PRIORITY (same policy), never lowers it; logs the result
 * in bridge.log and events.log. The writer thread of most_writer.c is created with default attributes, so
 * it inherits the main thread's priority: main is raised before most_start and the writer is checked after. */
static void raise_priority(pthread_t th, const char *name)
{
#ifdef __QNX__
    struct sched_param param;
    int policy = 0;
    int before;
    int status = 0;
    if (PMCP_MOST_PRIORITY <= 0) return;
    if (pthread_getschedparam(th, &policy, &param) != 0) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: priority read failed thread=%s\n", name);
        pmcp_event("priority thread=%s read-failed", name);
        return;
    }
    before = param.sched_priority;
    if (before < PMCP_MOST_PRIORITY) {
        param.sched_priority = PMCP_MOST_PRIORITY;
        status = pthread_setschedparam(th, policy, &param);
    }
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: priority thread=%s before=%d target=%d policy=%d status=%d\n",
            name, before, PMCP_MOST_PRIORITY, policy, status);
    pmcp_event("priority thread=%s before=%d target=%d policy=%d status=%d", name, before, PMCP_MOST_PRIORITY, policy,
            status);
#else
    (void)th;
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: priority thread=%s unchanged (host build) target=%d\n",
            name, PMCP_MOST_PRIORITY);
#endif
}

int main(int argc, char **argv)
{
    AltFrameRing *ring = MAP_FAILED;
    uint8_t *message = NULL;
    ts_mux_cfg_t mcfg;
    int fd = -1, cache_leased = 0, mux_on = 0, writer_on = 0, result = 1, replay = 0, new_epoch = 1;
    uint32_t generation = 0, next_sequence = 1, replay_end = 0;
    uint64_t next_writer_check = 0, next_metrics;
    unsigned int i;
    memset(&g_wcfg, 0, sizeof(g_wcfg));
    g_wcfg.dev = argc > 1 ? argv[1] : "/dev/mlb/isoTX2";
    g_wcfg.wait = MOST_WAIT_AUTO;        /* AA direct in the car (v12/v13) */
    g_wcfg.stall_ms = 5000;
    g_wcfg.first_sleep_us = 6500;
    pmcp_log_init();
    pmcp_most_init();
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    signal(SIGPIPE, SIG_IGN);
    ts_mux_default_cfg(&mcfg);           /* lead 100 ms as stage 1c (PTS_TARGET_LEAD_90K) */
    /* A249: over lead_max the PTS slews down 2 ms per AU instead of jumping 100 ms (a jump gave the next AUs PTS
       1 tick apart: the AID dropped them, zoom artifacts until the next IDR, car 27.11). PMCP_MOST_PTS_SLEW_90K=0 =
       the old jump (A/B only). */
    {
        const char *v = getenv("PMCP_MOST_PTS_SLEW_90K");
        mcfg.slew_down_90k = (v && *v) ? (uint32_t)strtoul(v, NULL, 10) : 180u;
    }
    g_au = (uint8_t *)malloc(ALT_FRAME_RING_SLOT_DATA_MAX + ALT_FRAME_RING_SLOT_DATA_MAX / 2U);
    message = (uint8_t *)malloc(ALT_FRAME_RING_SLOT_DATA_MAX);
    if (!g_au || !message || ts_mux_init(&g_mux, PMCP_CP_POOL_BYTES, PMCP_CP_POOL_ENTRIES, &mcfg) != 0) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: queue allocation failed\n");
        goto done;
    }
    mux_on = 1;
    if (cpmap_cache_acquire() != 0) goto done;
    cache_leased = 1;
    fd = open(ALT_FRAME_RING_PATH, O_RDWR | O_CREAT, 0666);
    if (fd < 0 || ftruncate(fd, (off_t)sizeof(*ring)) != 0) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: open ring %s failed: %s\n",
                ALT_FRAME_RING_PATH, strerror(errno));
        goto done;
    }
    ring = (AltFrameRing *)mmap(NULL, sizeof(*ring), PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    fd = -1;
    if (ring == MAP_FAILED) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: mmap ring failed: %s\n", strerror(errno));
        goto done;
    }
    /* Init by the bridge (docs/11): bump the generation, reset the sequences, publish the magic last. */
    generation = (ring->magic == ALT_FRAME_RING_MAGIC && ring->version == ALT_FRAME_RING_VERSION) ?
                 ring->generation + 1U : 1U;
    ring->magic = 0;
    __sync_synchronize();
    ring->version = ALT_FRAME_RING_VERSION;
    ring->generation = generation ? generation : 1U;
    ring->write_sequence = 0;
    for (i = 0; i < ALT_FRAME_RING_SLOT_COUNT; ++i) ring->slots[i].committed_sequence = 0;
    __sync_synchronize();
    ring->magic = ALT_FRAME_RING_MAGIC;
    generation = ring->generation;
    {
        const char *how = "";
        long holder = aa_holder(&how);
        if (holder) {
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: most-busy holder=aa pid=%ld via=%s: isoTX2 not opened, exit\n", holder, how);
            pmcp_event("most-busy holder=aa pid=%ld via=%s", holder, how);
            g_pmcp_most_errno = EBUSY;
            result = 0; /* as a refused START */
            goto done;
        }
    }
    raise_priority(pthread_self(), "main");
    if (most_open(&g_w, &g_wcfg) != 0) {
        log_devinfo("open failed");
        g_pmcp_most_errno = g_w.dev.open_errno ? g_w.dev.open_errno : EIO;
        pmcp_event("most-open-failed errno=%d start_status=%d", g_w.dev.open_errno, g_w.dev.start_rc);
        result = 0; /* as stage 1: the writer thread stops the bridge, main returns 0 (the supervisor's view) */
        goto done;
    }
    log_devinfo("most-open");
    if (most_start(&g_w, &g_mux) != 0) {
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: writer thread failed\n");
        goto done;
    }
    writer_on = 1;
    raise_priority(g_w.th, "writer");
    g_pmcp_most_ready = 1;
    pmcp_event("most-open ok reopen=0 output=aa-most-lib wait=%s", most_wait_name(g_wcfg.wait));
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: shared ring %s bytes=%u slots=%u -> %s output=aa-most-lib limit=%u reclaim-window-s=%u\n",
            ALT_FRAME_RING_PATH, (unsigned)sizeof(*ring), ALT_FRAME_RING_SLOT_COUNT, g_wcfg.dev,
            PMCP_CP_LIMIT_PACKETS, (unsigned)(ALTSCREEN_BRIDGE_RECLAIM_WINDOW_US / 1000000ULL));
    new_stream("bridge start");
    next_metrics = monotonic_us() + PMCP_CP_METRICS_US;
    while (!g_stop) {
        uint32_t available;
        uint64_t now = monotonic_us();
        uint32_t cut_seq = 0;
        int tick = pmcp_most_tick(now, (pmcp_ring *)(void *)ring, &cut_seq);
        int open_now;
        if (now >= next_writer_check) {
            next_writer_check = now + PMCP_CP_WRITER_CHECK_US;
            if (check_writer() != 0) break;
        }
        if (now >= next_metrics) {
            next_metrics = now + PMCP_CP_METRICS_US;
            log_metrics();
        }
        if (tick & PMCP_TICK_CUT) {
            /* contract v1.1 consumer gate (R92): restart at cut_seq + 1; video consumed before is not resent */
            generation = ring->generation;
            replay_end = next_sequence;
            next_sequence = cut_seq + 1U;
            if (next_sequence == 0) next_sequence = 1U;
            replay = (int32_t)(replay_end - next_sequence) > 0;
            new_epoch = 1;
            g_pmcp.avcc_log_next = 1;
            g_waiting_key = 1;
            g_idr_requested = 1; /* the IDR is requested when the gate opens */
            g_wait_start_us = now;
            g_last_source_seq = 0;
            pmcp_event("owner-cut owner_gen=%u ring_gen=%u prev_pid=%lu", (unsigned)g_pmcp_gate.owner_gen,
                       (unsigned)generation, g_pmcp_gate.prev_pid);
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: owner-cut owner_gen=%u ring_gen=%u kind=%s prev_pid=%lu\n",
                    (unsigned)g_pmcp_gate.owner_gen, (unsigned)generation,
                    g_pmcp_gate.last_kind == PMCP_KIND_PROXY ? "proxy" : "in", g_pmcp_gate.prev_pid);
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: gate-closed cut_seq=%u write_seq=%u resume_seq=%u replay_to=%u prev_kind=%s cuts=%lu\n",
                    (unsigned)cut_seq, (unsigned)g_pmcp.cut_write_seq, (unsigned)next_sequence,
                    replay ? (unsigned)replay_end : 0U,
                    g_pmcp_gate.prev_kind == PMCP_KIND_PROXY ? "proxy" : "in", (unsigned long)g_pmcp_gate.cuts);
        }
        open_now = pmcp_gate_tick(now);
        if (open_now == 1 && on_config(g_pmcp_gate.cfg, g_pmcp_gate.cfg_len) != 0) ++g_drops;
        if (open_now) gate_opened();
        if (tick & PMCP_TICK_STATUS) status_now(generation, next_sequence, now);
        if (tick & PMCP_TICK_STOP) {
            on_signal(SIGTERM);
            break;
        }
        if (ring->magic != ALT_FRAME_RING_MAGIC || ring->version != ALT_FRAME_RING_VERSION) {
            usleep(1000);
            continue;
        }
        if (ring->generation != generation) {
            /* a new AltScreen listener (phone reconnect): start a new stream at sequence 1 */
            generation = ring->generation;
            next_sequence = 1;
            new_epoch = 1;
            replay = 0;
            g_pmcp.avcc_log_next = 1;
            pmcp_event("ring-generation gen=%u", generation);
            {
                char why[48];
                snprintf(why, sizeof(why), "ring generation=%u", generation);
                new_stream(why);
            }
        }
        __sync_synchronize();
        available = ring->write_sequence;
        while (!g_stop && next_sequence != 0 && next_sequence <= available) {
            AltFrameRingSlot *slot = &ring->slots[(next_sequence - 1U) % ALT_FRAME_RING_SLOT_COUNT];
            uint32_t committed = slot->committed_sequence;
            uint32_t size, type, flags, source_sequence;
            uint64_t media_ntp;
            int status;
            if (committed != next_sequence) {
                if (committed > next_sequence) {
                    g_drops += committed - next_sequence;
                    ++g_pmcp_overruns;
                    if (g_pmcp_overruns <= PMCP_MOST_GAP_EVENTS)
                        pmcp_event("ring-overrun wanted=%u found=%u overruns=%lu", next_sequence, committed,
                                   g_pmcp_overruns);
                    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                            "bridge: ring overrun wanted=%u found=%u drops=%lu\n", next_sequence, committed,
                            g_drops);
                    next_sequence = committed;
                    continue;
                }
                break;
            }
            __sync_synchronize();
            size = slot->size;
            type = slot->type;
            flags = slot->flags;
            source_sequence = slot->source_sequence;
            media_ntp = ((uint64_t)slot->media_timestamp_hi << 32) | slot->media_timestamp_lo;
            if (size == 0 || size > ALT_FRAME_RING_SLOT_DATA_MAX) {
                ++g_drops;
                ++next_sequence;
                continue;
            }
            memcpy(message, slot->data, size);
            __sync_synchronize();
            if (slot->committed_sequence != next_sequence) continue; /* overwritten while copied */
            status = g_pmcp_gate.cut ? pmcp_gate_filter(next_sequence, type, message, size, monotonic_us()) : 0;
            if (status < 0) {
                ++g_drops;
                ++next_sequence;
                continue;
            }
            if (status > 0) gate_opened();
            if (replay && (int32_t)(replay_end - next_sequence) <= 0) replay = 0;
            if (replay && type == ALT_FRAME_TYPE_VIDEO) {
                ++next_sequence; /* already consumed before the cut */
                continue;
            }
            if (type == ALT_FRAME_TYPE_CONFIG) {
                status = on_config(message, size);
            } else if (type == ALT_FRAME_TYPE_VIDEO) {
                pmcp_most_note_frame(media_ntp, monotonic_us(), new_epoch, next_sequence);
                if (new_epoch) au_time_reset();
                new_epoch = 0;
                g_frame_ntp = media_ntp;
                status = on_video(message, size, flags, next_sequence, source_sequence);
            } else {
                status = -1;
            }
            if (status != 0) ++g_drops;
            ++next_sequence;
        }
        usleep(1000);
    }
    result = 0;
done:
    g_stop = 1;
    if (writer_on) {
        most_stats_t w;
        most_stop(&g_w, 0);
        most_snapshot(&g_w, &w);
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT, "bridge: writer stopped blocks=%llu reclaims=%u\n",
                (unsigned long long)w.blocks, g_reclaims);
        pmcp_event("writer-stopped blocks=%llu reclaims=%u", (unsigned long long)w.blocks, g_reclaims);
        log_metrics();
    }
    g_pmcp_most_ready = 0;
    {
        ts_mux_stats_t m;
        memset(&m, 0, sizeof(m));
        if (mux_on) ts_mux_snapshot(&g_mux, &m);
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                "bridge: complete frames=%lu keys=%lu drops=%lu aus_out=%llu queue_hi=%u latency_resets=%lu "
                "latency_frames_discarded=%lu put_full=%lu packet_count_mismatch=%llu\n",
                g_frames, g_keyframes, g_drops, (unsigned long long)m.aus_out, m.queue_packets_hi,
                g_latency_resets, g_waited_frames, g_put_full, (unsigned long long)m.packet_count_mismatch);
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                "bridge: pmcp avcc_repeats=%lu frame_gaps=%lu gap_max_ms=%lu overruns=%lu\n",
                g_pmcp.avcc_repeats, g_pmcp.gaps, g_pmcp.gap_max_ms, g_pmcp_overruns);
        pmcp_event("exit result=%d frames=%lu drops=%lu overruns=%lu latency_resets=%lu reclaims=%u queue_hi=%u "
                   "most_errno=%d frame_gaps=%lu gap_max_ms=%lu", result, g_frames, g_drops, g_pmcp_overruns,
                   g_latency_resets, g_reclaims, m.queue_packets_hi, (int)g_pmcp_most_errno, g_pmcp.gaps,
                   g_pmcp.gap_max_ms);
    }
    if (g_pmcp_gate.cuts)
        cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                "bridge: gate-stats cuts=%lu forced=%lu gate_drops=%lu closed=%d\n",
                (unsigned long)g_pmcp_gate.cuts, (unsigned long)g_pmcp_gate.forced, g_pmcp.gate_drops,
                g_pmcp_gate.cut);
    if (mux_on) status_now(ring != MAP_FAILED ? ring->generation : 0, next_sequence, monotonic_us());
    if (fd >= 0) close(fd);
    if (ring != MAP_FAILED) munmap(ring, sizeof(*ring));
    if (cache_leased) cpmap_cache_release();
    if (mux_on) ts_mux_free(&g_mux);
    free(message);
    free(g_au);
    return result;
}
