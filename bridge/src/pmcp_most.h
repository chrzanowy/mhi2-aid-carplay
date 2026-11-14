/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * pmcp-most stage 1: additions to the MOST bridge of Tomasz Twardzicki
 * (tomasz-twardzicki/MHI2-Carplay-Maps, based on omonob's altscreen bridge).
 * Header-only, included once by altscreen_most_bridge.c after
 * cpmap_resources.h, so it shares the bridge's log mutex and helpers.
 *
 *  1. Log: stderr goes to /ramdisk/pmcp-most/bridge.log (env PMCP_MOST_LOG;
 *     "-" keeps the inherited stderr). The file never exceeds
 *     PMCP_MOST_LOG_LIMIT bytes; when the next line would not fit, it is
 *     renamed to bridge.log.1 (one rotation) and a new file is started.
 *     Reason: the mathsls supervisor sends the bridge's stderr to /dev/null.
 *  2. Consumer status /ramdisk/most-src/consumer (contract v0.2 section 3),
 *     every 1000 ms from the reader loop, tmp + rename, ready=0 on exit.
 *     Directory: env PMCP_MOST_SRC_DIR (host tests).
 *  3. Producer session files <dir>/<src>.session (contract v0.2 section 2):
 *     state=stop of the current owner ends the stream at once, the same way
 *     as the supervisor's SIGTERM. Absent files = upstream behaviour.
 *
 * Nothing here blocks: small files on /ramdisk, read or written by the
 * reader thread at most every PMCP_MOST_SESSION_POLL_MS / 1000 ms. */
#ifndef PMCP_MOST_H
#define PMCP_MOST_H

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef PMCP_MOST_LOG_PATH
#define PMCP_MOST_LOG_PATH "/ramdisk/pmcp-most/bridge.log"
#endif
#ifndef PMCP_MOST_LOG_LIMIT
#define PMCP_MOST_LOG_LIMIT (64U * 1024U)
#endif
#ifndef PMCP_MOST_SRC_DIR
#define PMCP_MOST_SRC_DIR "/ramdisk/most-src"
#endif
#define PMCP_MOST_STATUS_PERIOD_MS 1000U
#define PMCP_MOST_SESSION_POLL_MS 100U
#define PMCP_MOST_LINE_MAX 255U

/* Reader-visible state, set by the writer thread / signal handler. */
static volatile sig_atomic_t g_pmcp_most_ready;
static volatile int g_pmcp_most_errno;
static unsigned long g_pmcp_overruns;

typedef struct PmcpConsumerStats {
    uint32_t ring_gen;
    uint32_t seq;
    unsigned long frames;
    unsigned long drops;
    unsigned long latency_resets;
    unsigned long reclaims;
    unsigned long queue_pkts;
    unsigned long queue_hi;
} PmcpConsumerStats;

typedef struct PmcpMostState {
    char log_path[256];
    int log_active;
    char dir[200];
    uint64_t start_us;
    uint64_t next_status_us;
    uint64_t next_poll_us;
    uint32_t owner_gen;
    char src[16];          /* current (or last seen) owner source */
    int session_started;   /* state=start seen for src during this run */
    long session_pid;
    int stop_reported;
    int stale_reported;
    /* age_ms: lateness of the last consumed frame against the earliest
     * frame of this ring generation (local monotonic - media NTP). */
    int64_t age_min_offset_us;
    int age_have_min;
    unsigned long age_ms;
} PmcpMostState;

static PmcpMostState g_pmcp;

static uint64_t pmcp_now_us(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return 0;
    return (uint64_t)value.tv_sec * 1000000ULL +
           (uint64_t)value.tv_nsec / 1000ULL;
}

/* mkdir -p for the parents of path (dir_only = 0) or path itself. */
static void pmcp_mkdirs(const char *path, int dir_only)
{
    char buffer[256];
    size_t i;
    size_t n = strlen(path);
    if (n == 0 || n >= sizeof(buffer)) return;
    memcpy(buffer, path, n + 1U);
    if (!dir_only) {
        while (n > 0 && buffer[n - 1U] != '/') --n;
        if (n <= 1U) return;
        buffer[n - 1U] = '\0';
    }
    for (i = 1; buffer[i] != '\0'; ++i) {
        if (buffer[i] != '/') continue;
        buffer[i] = '\0';
        (void)mkdir(buffer, 0755);
        buffer[i] = '/';
    }
    (void)mkdir(buffer, 0755);
}

static void pmcp_log_init(void)
{
    const char *path = getenv("PMCP_MOST_LOG");
    int fd;
    if (path == NULL || path[0] == '\0') path = PMCP_MOST_LOG_PATH;
    if (strcmp(path, "-") == 0) return;
    if (strlen(path) + 3U > sizeof(g_pmcp.log_path)) return;
    memcpy(g_pmcp.log_path, path, strlen(path) + 1U);
    pmcp_mkdirs(path, 0);
    fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0644);
    if (fd < 0) return;
    fflush(stderr);
    if (fd != STDERR_FILENO) {
        if (dup2(fd, STDERR_FILENO) < 0) {
            close(fd);
            return;
        }
        close(fd);
    }
    g_pmcp.log_active = 1;
}

/* Called by cpmap_log_fprintf (under its mutex) before a line of `bytes`
 * bytes is written to `file`: rotate if the line would not fit. */
static void pmcp_log_reserve(FILE *file, size_t bytes)
{
    struct stat st;
    char old_path[sizeof(g_pmcp.log_path) + 2U];
    int fd;
    if (!g_pmcp.log_active || file != stderr) return;
    fflush(stderr);
    if (fstat(STDERR_FILENO, &st) != 0 || !S_ISREG(st.st_mode)) return;
    if (st.st_size <= 0 ||
        (uint64_t)st.st_size + bytes <= (uint64_t)PMCP_MOST_LOG_LIMIT) return;
    snprintf(old_path, sizeof(old_path), "%s.1", g_pmcp.log_path);
    (void)rename(g_pmcp.log_path, old_path);
    fd = open(g_pmcp.log_path, O_WRONLY | O_CREAT | O_APPEND | O_TRUNC, 0644);
    if (fd < 0) return;
    if (fd != STDERR_FILENO) {
        (void)dup2(fd, STDERR_FILENO);
        close(fd);
    }
}

static void pmcp_most_init(void)
{
    const char *dir = getenv("PMCP_MOST_SRC_DIR");
    if (dir == NULL || dir[0] == '\0') dir = PMCP_MOST_SRC_DIR;
    if (strlen(dir) >= sizeof(g_pmcp.dir)) dir = PMCP_MOST_SRC_DIR;
    memcpy(g_pmcp.dir, dir, strlen(dir) + 1U);
    g_pmcp.start_us = pmcp_now_us();
    g_pmcp.next_status_us = g_pmcp.start_us;
    g_pmcp.next_poll_us = g_pmcp.start_us;
    pmcp_mkdirs(g_pmcp.dir, 1);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: pmcp-most stage1 pid=%ld log=%s limit=%u src_dir=%s\n",
            (long)getpid(), g_pmcp.log_active ? g_pmcp.log_path : "stderr",
            (unsigned)PMCP_MOST_LOG_LIMIT, g_pmcp.dir);
}

/* Reads one contract line; returns its length or -1. */
static int pmcp_read_line(const char *name, char *line, size_t size)
{
    char path[sizeof(g_pmcp.dir) + 32U];
    int fd;
    ssize_t n;
    if (snprintf(path, sizeof(path), "%s/%s", g_pmcp.dir, name) >= (int)sizeof(path))
        return -1;
    fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    n = read(fd, line, size - 1U);
    close(fd);
    if (n <= 0) return -1;
    line[n] = '\0';
    return (int)n;
}

/* Value of " key=" in a contract line (space separated), copied to out. */
static int pmcp_field(const char *line, const char *key, char *out, size_t size)
{
    size_t key_len = strlen(key);
    const char *p = line;
    while (*p) {
        while (*p == ' ') ++p;
        if (strncmp(p, key, key_len) == 0 && p[key_len] == '=') {
            size_t n = 0;
            p += key_len + 1U;
            while (p[n] && p[n] != ' ' && p[n] != '\n' && p[n] != '\r') ++n;
            if (n >= size) return -1;
            memcpy(out, p, n);
            out[n] = '\0';
            return 0;
        }
        while (*p && *p != ' ') ++p;
    }
    return -1;
}

static int pmcp_field_ul(const char *line, const char *key, unsigned long *value)
{
    char text[24];
    char *end;
    if (pmcp_field(line, key, text, sizeof(text)) != 0 || text[0] == '\0') return -1;
    errno = 0;
    *value = strtoul(text, &end, 10);
    if (errno != 0 || *end != '\0') return -1;
    return 0;
}

static int pmcp_valid_src(const char *src)
{
    size_t i;
    if (src[0] == '\0') return 0;
    for (i = 0; src[i]; ++i)
        if (src[i] < 'a' || src[i] > 'z') return 0;
    return 1;
}

/* Returns 1 when the owner's producer session has ended (state=stop newer
 * than this bridge, or its file vanished with a dead pid). */
static int pmcp_session_check(uint64_t now_us)
{
    char line[PMCP_MOST_LINE_MAX + 2U];
    char src[16];
    char state[16];
    char reason[32];
    char session_name[32];
    unsigned long owner_gen = 0;
    unsigned long gen = 0;
    unsigned long pid = 0;
    unsigned long ts_ms = 0;
    int have_owner = 0;
    (void)now_us;
    if (pmcp_read_line("owner", line, sizeof(line)) > 0 &&
        pmcp_field(line, "src", src, sizeof(src)) == 0 && pmcp_valid_src(src) &&
        pmcp_field_ul(line, "gen", &owner_gen) == 0) {
        have_owner = 1;
        if (strcmp(src, g_pmcp.src) != 0) {
            memcpy(g_pmcp.src, src, strlen(src) + 1U);
            g_pmcp.session_started = 0;
            g_pmcp.session_pid = 0;
        }
    }
    /* TODO(stage 1b, contract v1.1): owner kind=in|proxy; on an owner gen
     * change bump the ring generation and drop frames until a new type-1 avcC,
     * through the shared consumer gate in ../contract/pmcp_most_producer.{c,h}.
     * Not implemented in stage 1. */
    g_pmcp.owner_gen = have_owner ? (uint32_t)owner_gen : 0U;
    if (g_pmcp.src[0] == '\0') return 0;
    snprintf(session_name, sizeof(session_name), "%s.session", g_pmcp.src);
    if (pmcp_read_line(session_name, line, sizeof(line)) <= 0) {
        /* Vanished file: only a producer seen alive in this run and now dead. */
        if (g_pmcp.session_started && g_pmcp.session_pid > 0 &&
            kill((pid_t)g_pmcp.session_pid, 0) != 0 && errno == ESRCH) {
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: session-stop src=%s pid=%ld reason=vanished-dead-pid\n",
                    g_pmcp.src, g_pmcp.session_pid);
            return 1;
        }
        return 0;
    }
    if (pmcp_field(line, "state", state, sizeof(state)) != 0) return 0;
    (void)pmcp_field_ul(line, "gen", &gen);
    (void)pmcp_field_ul(line, "pid", &pid);
    (void)pmcp_field_ul(line, "ts_ms", &ts_ms);
    if (pmcp_field(line, "reason", reason, sizeof(reason)) != 0)
        memcpy(reason, "-", 2U);
    if (have_owner && gen != owner_gen) return 0; /* another owner generation */
    if (strcmp(state, "start") == 0) {
        g_pmcp.session_started = 1;
        g_pmcp.session_pid = (long)pid;
        return 0;
    }
    if (strcmp(state, "stop") != 0) return 0;
    /* A stop written before this bridge started belongs to an earlier
     * session; honouring it would make the supervisor restart loop. */
    if ((uint64_t)ts_ms * 1000ULL < g_pmcp.start_us) {
        if (!g_pmcp.stale_reported)
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: session-stop-ignored src=%s gen=%lu ts_ms=%lu (older than bridge)\n",
                    g_pmcp.src, gen, ts_ms);
        g_pmcp.stale_reported = 1;
        return 0;
    }
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: session-stop src=%s gen=%lu pid=%lu reason=%s\n",
            g_pmcp.src, gen, pid, reason);
    return 1;
}

static void pmcp_status_write(const PmcpConsumerStats *s, int ready, uint64_t now_us)
{
    char line[PMCP_MOST_LINE_MAX + 64U];
    char tmp[sizeof(g_pmcp.dir) + 40U];
    char path[sizeof(g_pmcp.dir) + 16U];
    int n;
    int fd;
    int errno_value = (int)g_pmcp_most_errno;
    /* Field limits of contract v0.2 (worst case 253 bytes with the newline). */
#define PMCP_CLAMP(value, max) ((value) > (max) ? (max) : (value))
    n = snprintf(line, sizeof(line),
            "v=1 ready=%d pid=%ld owner_gen=%lu ring_gen=%lu seq=%lu frames=%lu "
            "drops=%lu overruns=%lu latency_resets=%lu age_ms=%lu queue_pkts=%lu "
            "queue_hi=%lu reclaims=%lu most_errno=%d up_ms=%llu\n",
            ready ? 1 : 0, PMCP_CLAMP((long)getpid(), 9999999L),
            (unsigned long)g_pmcp.owner_gen, (unsigned long)s->ring_gen,
            (unsigned long)s->seq, PMCP_CLAMP(s->frames, 99999999UL),
            PMCP_CLAMP(s->drops, 99999999UL), PMCP_CLAMP(g_pmcp_overruns, 99999999UL),
            PMCP_CLAMP(s->latency_resets, 99999999UL), PMCP_CLAMP(g_pmcp.age_ms, 999999UL),
            PMCP_CLAMP(s->queue_pkts, 999999UL), PMCP_CLAMP(s->queue_hi, 999999UL),
            PMCP_CLAMP(s->reclaims, 99999999UL),
            errno_value < -99999 ? -99999 : errno_value > 99999 ? 99999 : errno_value,
            PMCP_CLAMP((unsigned long long)((now_us - g_pmcp.start_us) / 1000ULL), 999999999ULL));
    if (n <= 0 || n > (int)PMCP_MOST_LINE_MAX) return;
    snprintf(path, sizeof(path), "%s/consumer", g_pmcp.dir);
    snprintf(tmp, sizeof(tmp), "%s/consumer.tmp.%ld", g_pmcp.dir, (long)getpid());
    fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) {
        pmcp_mkdirs(g_pmcp.dir, 1);
        fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd < 0) return;
    }
    if (write(fd, line, (size_t)n) != (ssize_t)n) {
        close(fd);
        unlink(tmp);
        return;
    }
    close(fd);
    if (rename(tmp, path) != 0) unlink(tmp);
}

/* Reader loop hook. Fills the stats only when a status line is due.
 * Returns 1 if the owner's session asked the stream to end. */
#define PMCP_TICK_STATUS 1
#define PMCP_TICK_STOP 2
static int pmcp_most_tick(uint64_t now_us)
{
    int result = 0;
    if (now_us >= g_pmcp.next_poll_us) {
        g_pmcp.next_poll_us = now_us + PMCP_MOST_SESSION_POLL_MS * 1000ULL;
        if (!g_pmcp.stop_reported && pmcp_session_check(now_us)) {
            g_pmcp.stop_reported = 1;
            result |= PMCP_TICK_STOP;
        }
    }
    if (now_us >= g_pmcp.next_status_us) {
        g_pmcp.next_status_us += PMCP_MOST_STATUS_PERIOD_MS * 1000ULL;
        if (g_pmcp.next_status_us <= now_us)
            g_pmcp.next_status_us = now_us + PMCP_MOST_STATUS_PERIOD_MS * 1000ULL;
        result |= PMCP_TICK_STATUS;
    }
    return result;
}

/* Called for each consumed video slot with its media timestamp. */
static void pmcp_most_note_frame(uint64_t media_ntp, uint64_t now_us, int new_epoch)
{
    int64_t media_us;
    int64_t offset;
    if (new_epoch) g_pmcp.age_have_min = 0;
    if (media_ntp == 0) {
        g_pmcp.age_ms = 0;
        return;
    }
    media_us = (int64_t)((media_ntp >> 32) * 1000000ULL +
                         (((media_ntp & 0xffffffffULL) * 1000000ULL) >> 32));
    offset = (int64_t)now_us - media_us;
    if (!g_pmcp.age_have_min || offset < g_pmcp.age_min_offset_us) {
        g_pmcp.age_min_offset_us = offset;
        g_pmcp.age_have_min = 1;
    }
    g_pmcp.age_ms = (unsigned long)((offset - g_pmcp.age_min_offset_us) / 1000);
}

#endif
