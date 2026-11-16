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
 *  4. Stage 1b: consumer gate of contract v1.1 (shared code in
 *     ../contract/pmcp_most_producer.c: pmcp_gate_owner/slot/poll). The owner
 *     file is polled every PMCP_MOST_OWNER_POLL_MS; an owner gen change (not
 *     the first owner seen) bumps the ring generation and closes the gate
 *     until a type-1 avcC written after the cut, and while the previous
 *     owner's pid lives (at most 100 ms for kind=in, 3000 ms for proxy).
 *     cut_seq is the ring write_sequence of the PREVIOUS owner poll (contract
 *     decision OQ3 (a)): an avcC written in the detection window opens it.
 *     No owner file at all = no gate (upstream behaviour).
 *  5. Event file /ramdisk/pmcp-most/events.log (next to the log; env
 *     PMCP_MOST_EVENTS, "-" = none): one line per rare event, never rotated,
 *     appended by every bridge run of this start, so the first runs survive
 *     a log that rotates in minutes. Each line starts with boot_ms (CLOCK_
 *     MONOTONIC, from unit start), up_ms (from this bridge's start) and pid.
 *     Events: start, MOST open / error / reclaim, latency reset (queue size),
 *     IDR request and resume, chain gap, ring overrun, ring generation, owner
 *     cut, gate open, session stop, first video frame of an epoch, frame
 *     gaps >= PMCP_MOST_GAP_MS (at most PMCP_MOST_GAP_EVENTS per run), exit.
 *     Capped at PMCP_MOST_EVENTS_LIMIT: the last line written is
 *     "events-full"; later events are only in bridge.log.
 *
 * Nothing here blocks: small files on /ramdisk, read or written by the
 * reader thread at most every PMCP_MOST_OWNER_POLL_MS / 1000 ms; the writer
 * thread never touches any of it. */
#ifndef PMCP_MOST_H
#define PMCP_MOST_H

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "pmcp_most_producer.h" /* contract kit: consumer gate, owner kinds */

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
#ifndef PMCP_STATUS_PID
#define PMCP_STATUS_PID getpid() /* host tests may set a large constant */
#endif
#define PMCP_MOST_SESSION_POLL_MS 100U
#define PMCP_MOST_OWNER_POLL_MS 20U /* PMCP_MOST_LINE_MAX: contract kit */
#ifndef PMCP_MOST_EVENTS_LIMIT
#define PMCP_MOST_EVENTS_LIMIT (64U * 1024U)
#endif
#define PMCP_MOST_GAP_MS 250U      /* a video frame this late after the previous one is an event */
#define PMCP_MOST_GAP_EVENTS 40U   /* gap events per bridge run; the rest only counted */

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
    uint64_t next_owner_us;
    int have_owner;        /* the last owner poll found a valid owner */
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
    /* consumer gate: ring write_sequence at the previous owner poll */
    uint32_t poll_seq;
    int poll_seq_have;
    uint32_t cut_write_seq;   /* write_sequence when the cut was noticed */
    unsigned long gate_drops; /* slots dropped by the closed gate */
    /* event file and frame gaps */
    char event_path[256];
    int event_fd;
    int event_full;
    uint64_t last_frame_us;   /* local time of the previous consumed video frame */
    uint64_t last_frame_ntp;
    int last_frame_have;
    unsigned long gaps;
    unsigned long gap_max_ms;
    unsigned long avcc_repeats; /* identical avcC parsed again (not logged) */
    int avcc_log_next;          /* log the next avcC even when unchanged */
} PmcpMostState;

static PmcpMostState g_pmcp = { .event_fd = -1, .avcc_log_next = 1 };
static pmcp_consumer_gate g_pmcp_gate;
static pthread_mutex_t g_pmcp_event_mutex = PTHREAD_MUTEX_INITIALIZER;

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

/* Opens the event file: PMCP_MOST_EVENTS, else events.log next to the active
 * log; none when the log is stderr and no path is given. Appends (never
 * truncates): all bridge runs of this start share it. */
static void pmcp_event_init(void)
{
    const char *path = getenv("PMCP_MOST_EVENTS");
    size_t n;
    if (path == NULL || path[0] == '\0') {
        if (!g_pmcp.log_active) return;
        n = strlen(g_pmcp.log_path);
        while (n > 0 && g_pmcp.log_path[n - 1U] != '/') --n;
        if (n + sizeof("events.log") > sizeof(g_pmcp.event_path)) return;
        memcpy(g_pmcp.event_path, g_pmcp.log_path, n);
        memcpy(g_pmcp.event_path + n, "events.log", sizeof("events.log"));
    } else {
        if (strcmp(path, "-") == 0 || strlen(path) >= sizeof(g_pmcp.event_path)) return;
        memcpy(g_pmcp.event_path, path, strlen(path) + 1U);
    }
    pmcp_mkdirs(g_pmcp.event_path, 0);
    g_pmcp.event_fd = open(g_pmcp.event_path, O_WRONLY | O_CREAT | O_APPEND, 0644);
}

/* One event line: "boot_ms= up_ms= pid= <text>\n", one write() (O_APPEND, so
 * lines of overlapping bridge runs never interleave). Any thread; never
 * blocks on more than a small ramdisk write. Errors are ignored. */
static void pmcp_event(const char *format, ...)
{
    char line[320];
    struct stat st;
    uint64_t now_us = pmcp_now_us();
    int head;
    int body;
    int saved = errno;
    va_list ap;
    pthread_mutex_lock(&g_pmcp_event_mutex);
    if (g_pmcp.event_fd < 0 || g_pmcp.event_full) goto out;
    head = snprintf(line, sizeof(line), "boot_ms=%llu up_ms=%llu pid=%ld ",
            (unsigned long long)(now_us / 1000ULL),
            (unsigned long long)((now_us - g_pmcp.start_us) / 1000ULL), (long)getpid());
    if (head <= 0 || head >= (int)sizeof(line)) goto out;
    va_start(ap, format);
    body = vsnprintf(line + head, sizeof(line) - (size_t)head - 1U, format, ap);
    va_end(ap);
    if (body < 0) goto out;
    if (body > (int)(sizeof(line) - (size_t)head - 2U)) body = (int)(sizeof(line) - (size_t)head - 2U);
    head += body;
    line[head++] = '\n';
    if (fstat(g_pmcp.event_fd, &st) != 0) goto out;
    /* keep room for the closing events-full line */
    if ((uint64_t)st.st_size + (uint64_t)head + 128U > (uint64_t)PMCP_MOST_EVENTS_LIMIT) {
        g_pmcp.event_full = 1;
        if ((uint64_t)st.st_size + 128U > (uint64_t)PMCP_MOST_EVENTS_LIMIT) goto out;
        head = snprintf(line, sizeof(line),
                "boot_ms=%llu up_ms=%llu pid=%ld events-full limit=%u (later events only in bridge.log)\n",
                (unsigned long long)(now_us / 1000ULL),
                (unsigned long long)((now_us - g_pmcp.start_us) / 1000ULL), (long)getpid(),
                (unsigned)PMCP_MOST_EVENTS_LIMIT);
        if (head <= 0 || head >= (int)sizeof(line)) goto out;
    }
    (void)write(g_pmcp.event_fd, line, (size_t)head);
out:
    pthread_mutex_unlock(&g_pmcp_event_mutex);
    errno = saved;
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
    g_pmcp.next_owner_us = g_pmcp.start_us;
    pmcp_gate_init(&g_pmcp_gate);
    pmcp_mkdirs(g_pmcp.dir, 1);
    cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
            "bridge: pmcp-most stage1b pid=%ld log=%s limit=%u src_dir=%s\n",
            (long)getpid(), g_pmcp.log_active ? g_pmcp.log_path : "stderr",
            (unsigned)PMCP_MOST_LOG_LIMIT, g_pmcp.dir);
    pmcp_event_init();
    pmcp_event("start stage=1c log=%s events=%s limit=%u",
            g_pmcp.log_active ? g_pmcp.log_path : "stderr", g_pmcp.event_path,
            (unsigned)PMCP_MOST_EVENTS_LIMIT);
}

/* Reads one contract line; returns its length or -1. */
static int pmcp_read_name(const char *name, char *line, size_t size)
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

/* Owner poll (every PMCP_MOST_OWNER_POLL_MS, reader thread). Tracks the
 * source for the session files and feeds the consumer gate. Returns 1 on a
 * gate cut: the ring generation was bumped (by us) and *cut_seq is the
 * write_sequence of the previous poll (OQ3 (a)); the caller restarts reading
 * at *cut_seq + 1. A missing or invalid owner is not a cut (R92). */
static int pmcp_owner_poll(pmcp_ring *ring, uint64_t now_us, uint32_t *cut_seq)
{
    char line[PMCP_MOST_LINE_MAX + 2U];
    char src[16];
    char text[16];
    unsigned long gen = 0;
    unsigned long pid = 0;
    uint32_t seq_now;
    pmcp_owner cur;
    int cut = 0;
    __sync_synchronize();
    seq_now = ring->write_sequence;
    if (pmcp_read_name("owner", line, sizeof(line)) > 0 &&
        pmcp_field(line, "v", text, sizeof(text)) == 0 && strcmp(text, "1") == 0 &&
        pmcp_field(line, "src", src, sizeof(src)) == 0 && pmcp_valid_src(src) &&
        pmcp_field_ul(line, "gen", &gen) == 0 && (unsigned long)(uint32_t)gen == gen) {
        if (pmcp_field_ul(line, "pid", &pid) != 0) pid = 0;
        if (strcmp(src, g_pmcp.src) != 0) {
            memcpy(g_pmcp.src, src, strlen(src) + 1U);
            g_pmcp.session_started = 0;
            g_pmcp.session_pid = 0;
        }
        memset(&cur, 0, sizeof(cur));
        memcpy(cur.src, src, strlen(src) + 1U);
        cur.pid = pid;
        cur.gen = (uint32_t)gen;
        cur.kind = (pmcp_field(line, "kind", text, sizeof(text)) == 0 &&
                    strcmp(text, "proxy") == 0) ? PMCP_KIND_PROXY : PMCP_KIND_IN;
        if (pmcp_gate_owner(&g_pmcp_gate, ring, &cur, now_us / 1000ULL)) {
            if (g_pmcp.poll_seq_have) g_pmcp_gate.cut_seq = g_pmcp.poll_seq;
            *cut_seq = g_pmcp_gate.cut_seq;
            g_pmcp.cut_write_seq = seq_now;
            cut = 1;
        }
        g_pmcp.have_owner = 1;
        g_pmcp.owner_gen = (uint32_t)gen;
    } else {
        g_pmcp.have_owner = 0;
        g_pmcp.owner_gen = 0;
    }
    g_pmcp.poll_seq = seq_now;
    g_pmcp.poll_seq_have = 1;
    return cut;
}

/* Gate check of one ring slot. Returns -1 = drop it (gate closed: counts as a
 * drop, R93), 0 = process normally, 1 = process normally and the gate has
 * just opened on this avcC slot (the caller requests an IDR and logs). */
static int pmcp_gate_filter(uint32_t seq, uint32_t type, const void *data, uint32_t size,
                            uint64_t now_us)
{
    if (!g_pmcp_gate.cut) return 0;
    if (pmcp_gate_slot(&g_pmcp_gate, seq, type, data, size, now_us / 1000ULL) != PMCP_GATE_PASS) {
        ++g_pmcp.gate_drops;
        return -1;
    }
    return 1;
}

/* Gate poll of every reader pass while a held avcC waits for the previous
 * writer (R94). Returns 0 = nothing, 1 = opened, apply the stored avcC
 * (g_pmcp_gate.cfg, cfg_len), 2 = opened, stored avcC too large to keep. */
static int pmcp_gate_tick(uint64_t now_us)
{
    int apply;
    if (!g_pmcp_gate.cut || !g_pmcp_gate.cfg_have) return 0;
    apply = pmcp_gate_poll(&g_pmcp_gate, now_us / 1000ULL);
    if (g_pmcp_gate.cut) return 0;
    return apply ? 1 : 2;
}

static const char *pmcp_gate_reason(void)
{
    return g_pmcp_gate.open_reason == PMCP_GATE_OPEN_FORCED ? "forced" : "pid-exit";
}

/* Returns 1 when the owner's producer session has ended (state=stop newer
 * than this bridge, or its file vanished with a dead pid). The owner itself
 * comes from the last owner poll (at most PMCP_MOST_OWNER_POLL_MS old). */
static int pmcp_session_check(uint64_t now_us)
{
    char line[PMCP_MOST_LINE_MAX + 2U];
    char state[16];
    char reason[32];
    char session_name[32];
    unsigned long owner_gen = g_pmcp.owner_gen;
    unsigned long gen = 0;
    unsigned long pid = 0;
    unsigned long ts_ms = 0;
    int have_owner = g_pmcp.have_owner;
    (void)now_us;
    if (g_pmcp.src[0] == '\0') return 0;
    snprintf(session_name, sizeof(session_name), "%s.session", g_pmcp.src);
    if (pmcp_read_name(session_name, line, sizeof(line)) <= 0) {
        /* Vanished file: only a producer seen alive in this run and now dead. */
        if (g_pmcp.session_started && g_pmcp.session_pid > 0 &&
            kill((pid_t)g_pmcp.session_pid, 0) != 0 && errno == ESRCH) {
            cpmap_log_fprintf(stderr, CPMAP_BRIDGE_LOG_LIMIT,
                    "bridge: session-stop src=%s pid=%ld reason=vanished-dead-pid\n",
                    g_pmcp.src, g_pmcp.session_pid);
            pmcp_event("session-stop src=%s session_pid=%ld reason=vanished-dead-pid",
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
    pmcp_event("session-stop src=%s gen=%lu session_pid=%lu reason=%s", g_pmcp.src, gen, pid, reason);
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
    /* Field limits of contract v1.2 (worst case 255 bytes with the newline):
     * the full QNX pid (a pid_t is 32 bits; 9999999 hid the real one). */
#define PMCP_CLAMP(value, max) ((value) > (max) ? (max) : (value))
    n = snprintf(line, sizeof(line),
            "v=1 ready=%d pid=%ld owner_gen=%lu ring_gen=%lu seq=%lu frames=%lu "
            "drops=%lu overruns=%lu latency_resets=%lu age_ms=%lu queue_pkts=%lu "
            "queue_hi=%lu reclaims=%lu most_errno=%d up_ms=%llu\n",
            ready ? 1 : 0, PMCP_CLAMP((long)PMCP_STATUS_PID, 2147483647L),
            (unsigned long)g_pmcp.owner_gen, (unsigned long)s->ring_gen,
            (unsigned long)s->seq, PMCP_CLAMP(s->frames, 99999999UL),
            PMCP_CLAMP(s->drops, 99999999UL), PMCP_CLAMP(g_pmcp_overruns, 99999999UL),
            PMCP_CLAMP(s->latency_resets, 99999999UL), PMCP_CLAMP(g_pmcp.age_ms, 999999UL),
            PMCP_CLAMP(s->queue_pkts, 999999UL), PMCP_CLAMP(s->queue_hi, 999999UL),
            PMCP_CLAMP(s->reclaims, 99999999UL),
            errno_value < -9999 ? -9999 : errno_value > 99999 ? 99999 : errno_value,
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

/* Reader loop hook. PMCP_TICK_STATUS: a status line is due; PMCP_TICK_STOP:
 * the owner's session asked the stream to end; PMCP_TICK_CUT: consumer gate
 * cut (owner gen change), restart reading at *cut_seq + 1. */
#define PMCP_TICK_STATUS 1
#define PMCP_TICK_STOP 2
#define PMCP_TICK_CUT 4
static int pmcp_most_tick(uint64_t now_us, pmcp_ring *ring, uint32_t *cut_seq)
{
    int result = 0;
    if (now_us >= g_pmcp.next_owner_us) {
        g_pmcp.next_owner_us = now_us + PMCP_MOST_OWNER_POLL_MS * 1000ULL;
        if (pmcp_owner_poll(ring, now_us, cut_seq)) result |= PMCP_TICK_CUT;
    }
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

/* Called for each consumed video slot with its media timestamp: age_ms, the
 * first frame of an epoch and frame gaps (local and media time) as events. */
static void pmcp_most_note_frame(uint64_t media_ntp, uint64_t now_us, int new_epoch,
                                 uint32_t seq)
{
    int64_t media_us;
    int64_t offset;
    if (new_epoch) {
        g_pmcp.age_have_min = 0;
        pmcp_event("video-start seq=%u", (unsigned)seq);
    } else if (g_pmcp.last_frame_have &&
               now_us - g_pmcp.last_frame_us >= PMCP_MOST_GAP_MS * 1000ULL) {
        unsigned long gap_ms = (unsigned long)((now_us - g_pmcp.last_frame_us) / 1000ULL);
        long media_ms = -1;
        if (media_ntp != 0 && g_pmcp.last_frame_ntp != 0 && media_ntp >= g_pmcp.last_frame_ntp)
            media_ms = (long)((((media_ntp - g_pmcp.last_frame_ntp) >> 16) * 1000ULL) >> 16);
        ++g_pmcp.gaps;
        if (gap_ms > g_pmcp.gap_max_ms) g_pmcp.gap_max_ms = gap_ms;
        if (g_pmcp.gaps <= PMCP_MOST_GAP_EVENTS)
            pmcp_event("frame-gap seq=%u gap_ms=%lu media_ms=%ld gaps=%lu%s", (unsigned)seq, gap_ms,
                    media_ms, g_pmcp.gaps,
                    g_pmcp.gaps == PMCP_MOST_GAP_EVENTS ? " (last gap event of this run)" : "");
    }
    g_pmcp.last_frame_us = now_us;
    g_pmcp.last_frame_ntp = media_ntp;
    g_pmcp.last_frame_have = 1;
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
