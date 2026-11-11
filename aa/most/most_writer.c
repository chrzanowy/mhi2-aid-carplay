/*
 * most_writer: whole 12032-byte TS blocks to /dev/mlb/isoTX2. See most_writer.h.
 *
 * The devctl sequence and the open flags are those of omonob/MHI2-Carplay-Maps altscreen_most_bridge.c
 * (GPL-3.0); the poll fallback rule follows harman-f/mhi2_altscreen_carplay direct_ts_parity.c
 * (GPL-3.0-or-later).
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "most_writer.h"

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#if defined(MOST_HOST_SIM)
/* Host tests: the simulated isoTX2 of bridge-stage0 (aa/most/test/host_mlb.c). */
#include <sys/types.h>
int host_open64(const char *path, int flags, ...);
ssize_t host_write(int fd, const void *data, size_t size);
int host_close(int fd);
int devctl(int fd, int dcmd, void *data, size_t n_bytes, int *info);
#define DEV_OPEN(p, f)     host_open64((p), (f))
#define DEV_WRITE(d, b, n) host_write((d), (b), (n))
#define DEV_CLOSE(d)       host_close(d)
#elif defined(__QNXNTO__)
#include <devctl.h>
#define DEV_OPEN(p, f)     open((p), (f))
#define DEV_WRITE(d, b, n) write((d), (b), (n))
#define DEV_CLOSE(d)       close(d)
#else
/* Any other host: no MOST device; the start devctl fails and the caller keeps the factory picture. */
static int devctl(int fd, int dcmd, void *data, size_t n_bytes, int *info)
{
    (void)fd; (void)dcmd; (void)data; (void)n_bytes; (void)info;
    return ENOSYS;
}
#define DEV_OPEN(p, f)     open((p), (f))
#define DEV_WRITE(d, b, n) write((d), (b), (n))
#define DEV_CLOSE(d)       close(d)
#endif

static const uint64_t HIST_LIMIT_US[MOST_HIST_N - 1u] = { 5000u, 10000u, 30000u, 50000u, 100000u };

uint64_t most_now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

const char *most_wait_name(most_wait_t w)
{
    switch (w) {
    case MOST_WAIT_POLL: return "poll";
    case MOST_WAIT_SLEEP: return "sleep";
    case MOST_WAIT_BLOCK: return "block";
    default: return "auto";
    }
}

static void sleep_us(unsigned us)
{
    struct timespec ts = { 0, (long)us * 1000L };
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {}
}

static int read_u32(int fd, uint32_t dcmd, uint32_t *v)
{
    *v = 0;
    return devctl(fd, (int)dcmd, v, sizeof *v, NULL);
}

static int open_dev(most_writer_t *w, int flags);

int most_open(most_writer_t *w, const most_cfg_t *cfg)
{
    int flags = O_WRONLY | (cfg->wait == MOST_WAIT_BLOCK ? 0 : O_NONBLOCK);
    memset(w, 0, sizeof *w);
    w->cfg = *cfg;
    w->fd = -1;
    w->dev.iface_rc = w->dev.packet_rc = w->dev.block_rc = w->dev.flush_rc = w->dev.start_rc = -1;
    if (pthread_mutex_init(&w->lock, NULL) != 0) { w->dev.open_errno = ENOMEM; return -1; }
    return open_dev(w, flags);
}

int most_reopen(most_writer_t *w)
{
    int flags = O_WRONLY | (w->cfg.wait == MOST_WAIT_BLOCK ? 0 : O_NONBLOCK);
    if (w->thread_on || w->fd >= 0) return -1;      /* most_stop first */
    pthread_mutex_lock(&w->lock);
    w->st.failed = 0; w->st.fail_errno = 0; w->st.fail_what[0] = 0; w->st.done = 0; w->st.in_write_since = 0;
    w->st.reopens++;
    pthread_mutex_unlock(&w->lock);
    memset(&w->dev, 0, sizeof w->dev);
    w->dev.iface_rc = w->dev.packet_rc = w->dev.block_rc = w->dev.flush_rc = w->dev.start_rc = -1;
    return open_dev(w, flags);
}

static int open_dev(most_writer_t *w, int flags)
{
    uint32_t packets = TS_BLOCK_PACKETS;
    w->fd = DEV_OPEN(w->cfg.dev, flags);
    if (w->fd < 0) { w->dev.open_errno = errno; return -1; }
    w->dev.iface_rc = read_u32(w->fd, MOST_DCMD_INTERFACE, &w->dev.iface);
    w->dev.packet_rc = read_u32(w->fd, MOST_DCMD_PACKETSIZE, &w->dev.packet_size);
    w->dev.block_rc = read_u32(w->fd, MOST_DCMD_BLOCKCOUNT, &w->dev.block_count);
    w->dev.flush_rc = devctl(w->fd, (int)MOST_DCMD_FLUSH, NULL, 0, NULL);
    w->dev.start_rc = devctl(w->fd, (int)MOST_DCMD_START, &packets, sizeof packets, NULL);
    if (w->dev.start_rc != 0) {
        DEV_CLOSE(w->fd);
        w->fd = -1;
        return -1;
    }
    w->t_start_us = most_now_us();
    return 0;
}

static void fail(most_writer_t *w, int err, const char *what)
{
    pthread_mutex_lock(&w->lock);
    if (!w->st.failed) {
        w->st.failed = 1;
        w->st.fail_errno = err;
        snprintf(w->st.fail_what, sizeof w->st.fail_what, "%s", what);
    }
    pthread_mutex_unlock(&w->lock);
}

/* Poll bookkeeping of one writer thread. */
typedef struct { int ready_pending, false_ready; uint64_t last_ok_us; int slept; } wait_state_t;

/* One whole block. 0 = written, 1 = stopped meanwhile, -1 = error (recorded). */
static int write_block(most_writer_t *w, const uint8_t *b, wait_state_t *ws)
{
    uint64_t t0 = most_now_us();
    for (;;) {
        ssize_t n = DEV_WRITE(w->fd, b, TS_BLOCK_BYTES);
        int e = errno;
        if (n == (ssize_t)TS_BLOCK_BYTES) {
            ws->ready_pending = 0; ws->false_ready = 0; ws->last_ok_us = most_now_us(); ws->slept = 0;
            return 0;
        }
        if (n > 0) {
            char what[64];
            pthread_mutex_lock(&w->lock); w->st.short_writes++; pthread_mutex_unlock(&w->lock);
            snprintf(what, sizeof what, "krotki zapis %ld/%u", (long)n, TS_BLOCK_BYTES);
            fail(w, 0, what);
            return -1;
        }
        if (n < 0 && e == EINTR) continue;
        if (n < 0 && (e == EAGAIN || e == EWOULDBLOCK)) {
            int use_poll;
            if (w->stop) return 1;
            if (most_now_us() - t0 >= (uint64_t)w->cfg.stall_ms * 1000u) { fail(w, EAGAIN, "zapis stoi (EAGAIN)"); return -1; }
            pthread_mutex_lock(&w->lock);
            w->st.eagain++;
            if (ws->ready_pending) {              /* poll said ready, the write still did not fit */
                ws->ready_pending = 0;
                w->st.poll_ready_false++;
                if (++ws->false_ready >= 3 && w->cfg.wait == MOST_WAIT_AUTO) w->st.poll_off = 1;
            }
            use_poll = w->cfg.wait == MOST_WAIT_POLL || (w->cfg.wait == MOST_WAIT_AUTO && !w->st.poll_off);
            pthread_mutex_unlock(&w->lock);
            if (use_poll) {
                struct pollfd p;
                int r;
                p.fd = w->fd; p.events = POLLOUT; p.revents = 0;
                r = poll(&p, 1, 2);
                pthread_mutex_lock(&w->lock);
                w->st.polls++;
                if (r < 0 || (r > 0 && (p.revents & (POLLERR | POLLHUP | POLLNVAL)))) {
                    if (w->cfg.wait == MOST_WAIT_AUTO) w->st.poll_off = 1;
                    pthread_mutex_unlock(&w->lock);
                } else {
                    pthread_mutex_unlock(&w->lock);
                    if (r > 0) ws->ready_pending = 1;
                    continue;                     /* ready or a 2 ms timeout: try the write again */
                }
            }
            {
                /* v12: the driver frees one block about every 7.9 ms; the car log of v11 (A147) showed ~4 EAGAIN +
                 * 1 ms sleeps per block. The first sleep after an accepted block now waits out most of that time. */
                unsigned us = 1000u;
                uint64_t now = most_now_us();
                int lng = 0;
                if (!ws->slept && w->cfg.first_sleep_us > 1000u && ws->last_ok_us != 0u &&
                    now < ws->last_ok_us + w->cfg.first_sleep_us) {
                    uint64_t left = ws->last_ok_us + w->cfg.first_sleep_us - now;
                    if (left > 1000u) { us = (unsigned)left; lng = 1; }
                }
                ws->slept = 1;
                pthread_mutex_lock(&w->lock); w->st.sleeps++; if (lng) w->st.long_sleeps++; pthread_mutex_unlock(&w->lock);
                sleep_us(us);
            }
            continue;
        }
        {
            char what[64];
            snprintf(what, sizeof what, "blad zapisu errno=%d", n < 0 ? e : 0);
            fail(w, n < 0 ? e : 0, what);
        }
        return -1;
    }
}

static void *writer_main(void *arg)
{
    most_writer_t *w = (most_writer_t *)arg;
    static uint8_t block[TS_BLOCK_BYTES];
    wait_state_t ws = { 0, 0, 0u, 0 };
    while (!w->stop) {
        uint64_t t0, dt;
        int r;
        unsigned k;
        ts_mux_fill_block(w->mux, block);
        t0 = most_now_us();
        pthread_mutex_lock(&w->lock); w->st.in_write_since = t0; pthread_mutex_unlock(&w->lock);
        r = write_block(w, block, &ws);
        dt = most_now_us() - t0;
        pthread_mutex_lock(&w->lock);
        w->st.in_write_since = 0;
        if (r == 0) {
            if (w->st.blocks == 0u) w->st.first_block_us = most_now_us() - w->t_start_us;
            w->st.blocks++;
            w->st.bytes += TS_BLOCK_BYTES;
            for (k = 0; k < MOST_HIST_N - 1u && dt >= HIST_LIMIT_US[k]; ++k) {}
            w->st.hist[k]++;
            if (dt > w->st.write_us_max) w->st.write_us_max = dt;
            if (dt >= 50000u) w->st.slow_writes++;
            w->st.write_us_sum += dt;
            w->st.write_us_last = dt;
        }
        pthread_mutex_unlock(&w->lock);
        if (r != 0) break;
    }
    pthread_mutex_lock(&w->lock); w->st.done = 1; pthread_mutex_unlock(&w->lock);
    return NULL;
}

int most_start(most_writer_t *w, ts_mux_t *mux)
{
    sigset_t all, old;
    int r;
    w->mux = mux;
    w->stop = 0;
    /* the thread starts with every signal blocked: SIGTERM/SIGHUP reach the main thread, never interrupt a write */
    sigfillset(&all);
    pthread_sigmask(SIG_SETMASK, &all, &old);
    r = pthread_create(&w->th, NULL, writer_main, w);
    pthread_sigmask(SIG_SETMASK, &old, NULL);
    if (r != 0) { errno = r; return -1; }
    w->thread_on = 1;
    return 0;
}

void most_snapshot(most_writer_t *w, most_stats_t *out)
{
    pthread_mutex_lock(&w->lock);
    *out = w->st;
    pthread_mutex_unlock(&w->lock);
}

uint64_t most_write_age_us(most_writer_t *w, uint64_t now)
{
    uint64_t s;
    pthread_mutex_lock(&w->lock);
    s = w->st.in_write_since;
    pthread_mutex_unlock(&w->lock);
    return s != 0u && now > s ? now - s : 0u;
}

void most_debug_flush(const char *debug_dev)
{
    int fd = open(debug_dev, O_WRONLY | O_NONBLOCK);
    if (fd >= 0) { (void)write(fd, "flush(0)\n", 9); close(fd); }
}

void most_stop(most_writer_t *w, unsigned drain_ms)
{
    uint64_t t0 = most_now_us();
    int done = 0, i;
    if (w->thread_on) {
        while ((most_now_us() - t0) < (uint64_t)drain_ms * 1000u) {
            uint32_t pk = 0;
            most_stats_t s;
            most_snapshot(w, &s);
            if (s.done) break;
            ts_mux_depth(w->mux, &pk, NULL);
            if (pk == 0u) break;
            sleep_us(2000u);
        }
        w->stop = 1;
        for (i = 0; i < 500; ++i) {               /* one block takes ~8 ms; give a slow driver 1 s */
            pthread_mutex_lock(&w->lock); done = w->st.done; pthread_mutex_unlock(&w->lock);
            if (done) break;
            sleep_us(2000u);
        }
        if (done) pthread_join(w->th, NULL);
        else pthread_detach(w->th);               /* stuck in the driver: closing the fd below unblocks it */
        w->thread_on = 0;
    }
    if (w->fd >= 0) { DEV_CLOSE(w->fd); w->fd = -1; }
}
