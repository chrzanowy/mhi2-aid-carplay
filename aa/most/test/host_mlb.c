/* HOST shim: simulated QNX /dev/mlb/isoTX2 for altscreen_most_bridge.c.
 *
 * The "device" is a regular file that receives every accepted byte (the TS
 * golden), plus a text log (<device>.log or HOST_MLB_LOG) with one line per
 * open, devctl, accepted write and close.
 *
 * Back-pressure model: a driver FIFO of HOST_MLB_DEPTH bytes (default two
 * 12032-byte blocks) drained at HOST_MLB_BPS bit/s (default 12288000) from the
 * START devctl on. A write that does not fit:
 *   HOST_MLB_MODE=eagain (default; the bridge opens O_NONBLOCK): -1/EAGAIN
 *   HOST_MLB_MODE=block: sleeps until it fits (models a driver that blocks
 *                        the caller even on a non-blocking fd)
 * HOST_MLB_PARTIAL=1 accepts the whole TS packets that fit (short writes).
 * HOST_MLB_STALL_AT_BLOCK=N + HOST_MLB_STALL_MS=M: after N accepted writes
 * the FIFO stops draining for M ms (a slow MOST episode).
 * HOST_MLB_FAIL_AT_BLOCK=N: write N+1 returns -1/EIO.
 * devctl readback values: HOST_MLB_IFACE, HOST_MLB_PKTSIZE, HOST_MLB_BLKCOUNT
 * (default 0: the real values on MU1161 are not known, CONTRACT.md U2);
 * statuses HOST_MLB_FLUSH_STATUS (e.g. 25 = ENOTTY as on MU1440) and
 * HOST_MLB_START_STATUS (default 0).
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define TS_PACKET 188U

static int g_mlb_fd = -1;
static int g_log_fd = -1;
static uint64_t g_t0_us;
static double g_rate_bytes_per_us = 12288000.0 / 8.0 / 1e6;
static double g_depth = 2.0 * 12032.0;
static int g_block_mode;
static int g_partial;
static long g_stall_at = -1;
static uint64_t g_stall_us;
static long g_fail_at = -1;
static int g_started;
static double g_level;
static uint64_t g_level_t;
static uint64_t g_stall_until;
static unsigned long g_writes;
static unsigned long g_eagain_pending;
static unsigned long long g_offset;
static uint64_t g_block_wait_us;
static unsigned long g_underruns;
static pthread_mutex_t g_lock = PTHREAD_MUTEX_INITIALIZER;

static uint64_t now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}

static const char *env_or(const char *name, const char *fallback)
{
    const char *v = getenv(name);
    return v && v[0] ? v : fallback;
}

static long env_long(const char *name, long fallback)
{
    const char *v = getenv(name);
    return v && v[0] ? strtol(v, NULL, 0) : fallback;
}

const char *host_ring_path(void) { return env_or("HOST_RING_PATH", "ring.bin"); }
const char *host_idr_path(void) { return env_or("HOST_IDR_PATH", "force-idr.request"); }
const char *host_intro_once_path(void) { return env_or("HOST_INTRO_ONCE_PATH", "intro-played"); }

static void log_line(const char *format, ...)
{
    char line[512];
    int n;
    va_list ap;
    if (g_log_fd < 0) return;
    n = snprintf(line, sizeof(line), "t_us=%llu ",
                 (unsigned long long)(now_us() - g_t0_us));
    va_start(ap, format);
    n += vsnprintf(line + n, sizeof(line) - (size_t)n, format, ap);
    va_end(ap);
    if (n > (int)sizeof(line) - 2) n = (int)sizeof(line) - 2;
    line[n++] = '\n';
    (void)write(g_log_fd, line, (size_t)n);
}

int host_open64(const char *path, int flags, ...)
{
    char log_path[1024];
    const char *mode = env_or("HOST_MLB_MODE", "eagain");
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    int saved = errno;
    if (fd < 0) return -1;
    snprintf(log_path, sizeof(log_path), "%s.log", path);
    g_log_fd = open(env_or("HOST_MLB_LOG", log_path),
                    O_WRONLY | O_CREAT | O_TRUNC | O_APPEND, 0644);
    g_t0_us = now_us();
    g_rate_bytes_per_us = (double)env_long("HOST_MLB_BPS", 12288000L) / 8.0 / 1e6;
    g_depth = (double)env_long("HOST_MLB_DEPTH", 2L * 12032L);
    g_block_mode = strcmp(mode, "block") == 0;
    g_partial = env_long("HOST_MLB_PARTIAL", 0) != 0;
    g_stall_at = env_long("HOST_MLB_STALL_AT_BLOCK", -1);
    g_stall_us = (uint64_t)env_long("HOST_MLB_STALL_MS", 0) * 1000ULL;
    g_fail_at = env_long("HOST_MLB_FAIL_AT_BLOCK", -1);
    g_mlb_fd = fd;
    log_line("open path=%s flags=0x%x nonblock=%d model bps=%ld depth=%.0f mode=%s partial=%d stall_at=%ld stall_ms=%llu",
             path, flags, (flags & O_NONBLOCK) != 0, env_long("HOST_MLB_BPS", 12288000L),
             g_depth, g_block_mode ? "block" : "eagain", g_partial, g_stall_at,
             (unsigned long long)(g_stall_us / 1000ULL));
    errno = saved;
    return fd;
}

int devctl(int fd, int dcmd, void *data, size_t n_bytes, int *info)
{
    uint32_t code = (uint32_t)dcmd;
    uint32_t value = 0;
    int status = 0;
    const char *dir = (code & 0x80000000U) ? ((code & 0x40000000U) ? "inout" : "to") :
                      (code & 0x40000000U) ? "from" : "none";
    (void)info;
    if (fd != g_mlb_fd) return EBADF;
    switch (code) {
    case 0x4004050cU: value = (uint32_t)env_long("HOST_MLB_IFACE", 0); break;
    case 0x4004050dU: value = (uint32_t)env_long("HOST_MLB_PKTSIZE", 0); break;
    case 0x40040510U: value = (uint32_t)env_long("HOST_MLB_BLKCOUNT", 0); break;
    case 0x40040506U: status = (int)env_long("HOST_MLB_FLUSH_STATUS", 0); break;
    case 0x80040509U:
        status = (int)env_long("HOST_MLB_START_STATUS", 0);
        if (data && n_bytes >= 4) memcpy(&value, data, 4);
        if (status == 0) {
            pthread_mutex_lock(&g_lock);
            g_started = 1;
            g_level = 0;
            g_level_t = now_us();
            pthread_mutex_unlock(&g_lock);
        }
        break;
    default: status = ENOTTY; break;
    }
    if ((code & 0x40000000U) && !(code & 0x80000000U) && data && n_bytes >= 4)
        memcpy(data, &value, 4);
    log_line("devctl code=0x%08x dir=%s size=%zu value=%u status=%d",
             code, dir, n_bytes, value, status);
    return status;
}

/* Drains the model FIFO up to time t. Called with g_lock held. */
static void drain(uint64_t t)
{
    uint64_t from = g_level_t;
    if (g_stall_until > from) from = g_stall_until;
    if (t > from) {
        double next = g_level - (double)(t - from) * g_rate_bytes_per_us;
        if (next < 0) {
            if (g_level > 0) ++g_underruns; /* FIFO ran dry: MOST idle */
            next = 0;
        }
        g_level = next;
    }
    if (t > g_level_t) g_level_t = t;
}

static ssize_t append_all(int fd, const uint8_t *data, size_t size)
{
    size_t done = 0;
    while (done < size) {
        ssize_t n = write(fd, data + done, size - done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        done += (size_t)n;
    }
    return (ssize_t)done;
}

ssize_t host_write(int fd, const void *data, size_t size)
{
    size_t accept;
    uint64_t t;
    uint64_t wait_start = 0;
    double level_before;
    if (fd != g_mlb_fd || fd < 0) return write(fd, data, size);
    pthread_mutex_lock(&g_lock);
    if (g_fail_at >= 0 && (long)g_writes == g_fail_at) {
        pthread_mutex_unlock(&g_lock);
        log_line("write n=%lu size=%zu ret=-1 errno=EIO (injected)", g_writes, size);
        errno = EIO;
        return -1;
    }
    for (;;) {
        double space;
        t = now_us();
        drain(t);
        space = g_depth - g_level;
        if (!g_started) space = 0;
        if ((double)size <= space) { accept = size; break; }
        if (g_partial && space >= TS_PACKET) {
            accept = (size_t)(space / TS_PACKET) * TS_PACKET;
            break;
        }
        if (!g_block_mode) {
            ++g_eagain_pending;
            pthread_mutex_unlock(&g_lock);
            errno = EAGAIN;
            return -1;
        }
        if (!wait_start) wait_start = t;
        pthread_mutex_unlock(&g_lock);
        usleep(200);
        pthread_mutex_lock(&g_lock);
    }
    level_before = g_level;
    g_level += (double)accept;
    if (append_all(fd, (const uint8_t *)data, accept) < 0) {
        int saved = errno;
        pthread_mutex_unlock(&g_lock);
        errno = saved;
        return -1;
    }
    if (wait_start) g_block_wait_us += t - wait_start;
    log_line("write n=%lu size=%zu ret=%zu offset=%llu eagain_before=%lu blocked_us=%llu fifo_before=%.0f underruns=%lu",
             g_writes, size, accept, g_offset, g_eagain_pending,
             (unsigned long long)(wait_start ? t - wait_start : 0),
             level_before, g_underruns);
    g_offset += accept;
    g_eagain_pending = 0;
    ++g_writes;
    if (g_stall_at >= 0 && (long)g_writes == g_stall_at && g_stall_us) {
        g_stall_until = t + g_stall_us;
        log_line("stall start until_t_us=%llu",
                 (unsigned long long)(g_stall_until - g_t0_us));
    }
    pthread_mutex_unlock(&g_lock);
    return (ssize_t)accept;
}

int host_close(int fd)
{
    if (fd >= 0 && fd == g_mlb_fd) {
        /* May run in the bridge's signal handler: no locks here. */
        log_line("close fd writes=%lu bytes=%llu", g_writes, g_offset);
        g_mlb_fd = -1;
    }
    return close(fd);
}
