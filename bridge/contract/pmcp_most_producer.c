/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Producer-side library of the MOST bridge contract. See pmcp_most_producer.h. */
#define _POSIX_C_SOURCE 200112L

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include "pmcp_most_producer.h"

#if defined(__GNUC__)
#define PMCP_BARRIER() __sync_synchronize()
#else
#define PMCP_BARRIER() ((void)0)
#endif

/* ---- time ---- */
uint64_t pmcp_now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

uint64_t pmcp_ntp_now(void)
{
    struct timespec ts;
    uint64_t sec, frac;
    clock_gettime(CLOCK_REALTIME, &ts);
    sec = (uint64_t)ts.tv_sec + 2208988800u;
    frac = ((uint64_t)ts.tv_nsec << 32) / 1000000000u;
    return (sec << 32) | (frac & 0xffffffffu);
}

void pmcp_sleep_ms(unsigned ms)
{
    struct timespec ts;
    ts.tv_sec = (time_t)(ms / 1000u);
    ts.tv_nsec = (long)(ms % 1000u) * 1000000L;
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {
    }
}

/* ---- line files ---- */
static int ensure_dir(const char *dir)
{
    if (mkdir(dir, PMCP_MOST_DIR_MODE) != 0 && errno != EEXIST)
        return PMCP_E_IO;
    return PMCP_OK;
}

static int write_tmp(const char *dir, const char *name, const char *line,
                     char *tmp, size_t tmpsz)
{
    char buf[PMCP_MOST_LINE_MAX + 2];
    size_t n = strlen(line);
    int fd;
    if (n + 1 > PMCP_MOST_LINE_MAX)
        return PMCP_E_TOOBIG;
    memcpy(buf, line, n);
    buf[n++] = '\n';
    if (snprintf(tmp, tmpsz, "%s/%s.tmp.%lu", dir, name, (unsigned long)getpid())
        >= (int)tmpsz)
        return PMCP_E_INVAL;
    fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0)
        return PMCP_E_IO;
    if (write(fd, buf, n) != (ssize_t)n) {
        close(fd);
        unlink(tmp);
        return PMCP_E_IO;
    }
    if (close(fd) != 0) {
        unlink(tmp);
        return PMCP_E_IO;
    }
    return PMCP_OK;
}

int pmcp_atomic_write(const char *dir, const char *name, const char *line)
{
    char tmp[512], dst[512];
    int r = ensure_dir(dir);
    if (r != PMCP_OK)
        return r;
    r = write_tmp(dir, name, line, tmp, sizeof tmp);
    if (r != PMCP_OK)
        return r;
    if (snprintf(dst, sizeof dst, "%s/%s", dir, name) >= (int)sizeof dst) {
        unlink(tmp);
        return PMCP_E_INVAL;
    }
    if (rename(tmp, dst) != 0) {
        unlink(tmp);
        return PMCP_E_IO;
    }
    return PMCP_OK;
}

int pmcp_read_line(const char *path, char *buf, size_t bufsz)
{
    char tmp[PMCP_MOST_LINE_MAX + 2];
    ssize_t n;
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return errno == ENOENT ? PMCP_E_NOENT : PMCP_E_IO;
    n = read(fd, tmp, sizeof tmp);
    close(fd);
    if (n <= 0)
        return PMCP_E_PARSE;
    if (n > PMCP_MOST_LINE_MAX || tmp[n - 1] != '\n')
        return PMCP_E_PARSE;
    n--;
    if ((size_t)n + 1 > bufsz)
        return PMCP_E_TOOBIG;
    memcpy(buf, tmp, (size_t)n);
    buf[n] = '\0';
    return PMCP_OK;
}

int pmcp_kv_get(const char *line, const char *key, char *val, size_t valsz)
{
    size_t kl = strlen(key);
    const char *p = line;
    while (*p) {
        const char *end;
        while (*p == ' ')
            p++;
        if (!*p)
            break;
        end = p;
        while (*end && *end != ' ')
            end++;
        if ((size_t)(end - p) > kl && p[kl] == '=' && strncmp(p, key, kl) == 0) {
            size_t vl = (size_t)(end - p) - kl - 1;
            if (vl + 1 > valsz)
                return PMCP_E_TOOBIG;
            memcpy(val, p + kl + 1, vl);
            val[vl] = '\0';
            return PMCP_OK;
        }
        p = end;
    }
    return PMCP_E_NOENT;
}

static int parse_u64(const char *s, unsigned long long *out)
{
    char *e;
    if (*s == '\0' || *s == '-' || *s == '+')
        return PMCP_E_PARSE;
    errno = 0;
    *out = strtoull(s, &e, 10);
    if (errno != 0 || *e != '\0')
        return PMCP_E_PARSE;
    return PMCP_OK;
}

static int get_u(const char *line, const char *key, unsigned long long max,
                 unsigned long long *out)
{
    char v[32];
    int r = pmcp_kv_get(line, key, v, sizeof v);
    if (r != PMCP_OK)
        return r == PMCP_E_NOENT ? PMCP_E_NOENT : PMCP_E_PARSE;
    if (parse_u64(v, out) != PMCP_OK || *out > max)
        return PMCP_E_PARSE;
    return PMCP_OK;
}

static int check_version(const char *line)
{
    char v[16];
    if (pmcp_kv_get(line, "v", v, sizeof v) != PMCP_OK)
        return PMCP_E_PARSE;
    return strcmp(v, "1") == 0 ? PMCP_OK : PMCP_E_VERSION;
}

/* ---- ring ---- */
int pmcp_ring_open(pmcp_ring_map *m, const char *path, int create)
{
    struct stat st;
    void *p;
    int fd = open(path, create ? (O_RDWR | O_CREAT) : O_RDWR, 0644);
    m->fd = -1;
    m->ring = NULL;
    if (fd < 0)
        return errno == ENOENT ? PMCP_E_NOENT : PMCP_E_IO;
    if (fstat(fd, &st) != 0) {
        close(fd);
        return PMCP_E_IO;
    }
    if ((uint64_t)st.st_size < PMCP_RING_FILE_SIZE) {
        if (!create || ftruncate(fd, (off_t)PMCP_RING_FILE_SIZE) != 0) {
            close(fd);
            return create ? PMCP_E_IO : PMCP_E_PARSE;
        }
    }
    p = mmap(NULL, PMCP_RING_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) {
        close(fd);
        return PMCP_E_IO;
    }
    m->fd = fd;
    m->ring = (pmcp_ring *)p;
    if (create == 2)
        return PMCP_OK; /* consumer: file only, pmcp_ring_consumer_attach() inits */
    if (m->ring->magic != PMCP_RING_MAGIC) {
        if (!create) {
            pmcp_ring_close(m);
            return PMCP_E_PARSE;
        }
        memset(m->ring, 0, PMCP_RING_FILE_SIZE);
        m->ring->version = PMCP_RING_VERSION;
        m->ring->generation = 1;
        PMCP_BARRIER();
        m->ring->magic = PMCP_RING_MAGIC;
    }
    return PMCP_OK;
}

void pmcp_ring_close(pmcp_ring_map *m)
{
    if (m->ring != NULL)
        munmap((void *)m->ring, PMCP_RING_FILE_SIZE);
    if (m->fd >= 0)
        close(m->fd);
    m->ring = NULL;
    m->fd = -1;
}

uint32_t pmcp_ring_consumer_attach(pmcp_ring_map *m)
{
    pmcp_ring *r = m->ring;
    if (r->magic != PMCP_RING_MAGIC) {
        memset(r, 0, PMCP_RING_FILE_SIZE);
        r->version = PMCP_RING_VERSION;
        r->generation = 1;
        PMCP_BARRIER();
        r->magic = PMCP_RING_MAGIC;
    } else {
        uint32_t g = r->generation + 1u;
        r->generation = g == 0 ? 1u : g;
    }
    PMCP_BARRIER();
    return r->generation;
}

uint32_t pmcp_ring_publish(pmcp_ring *r, uint32_t type, const void *data,
                           uint32_t size, uint32_t flags, uint32_t frame_no,
                           uint64_t ntp_ts)
{
    uint32_t n = r->write_sequence + 1u;
    pmcp_ring_slot *s;
    if (n == 0)
        n = 1;
    s = &r->slots[(n - 1u) & (PMCP_RING_SLOT_COUNT - 1u)];
    s->seq = 0;
    PMCP_BARRIER();
    s->type = type;
    s->size = size;
    s->flags = flags;
    s->frame_no = frame_no;
    s->ts_lo = (uint32_t)(ntp_ts & 0xffffffffu);
    s->ts_hi = (uint32_t)(ntp_ts >> 32);
    memcpy(s->data, data, size);
    PMCP_BARRIER();
    s->seq = n;
    PMCP_BARRIER();
    r->write_sequence = n;
    PMCP_BARRIER();
    return n;
}

/* ---- owner ---- */
int pmcp_src_valid(const char *src)
{
    return strcmp(src, PMCP_SRC_WIRED) == 0 || strcmp(src, PMCP_SRC_WIRELESS) == 0
        || strcmp(src, PMCP_SRC_AA) == 0;
}

int pmcp_pid_alive(unsigned long pid)
{
    if (pid == 0 || pid > 0x7fffffffUL)
        return 0;
    if (kill((pid_t)pid, 0) == 0)
        return 1;
    return errno != ESRCH; /* EPERM = alive, owned by someone else */
}

int pmcp_owner_parse(const char *line, pmcp_owner *o)
{
    char v[32];
    unsigned long long x;
    int r = check_version(line);
    if (r != PMCP_OK)
        return r;
    if (pmcp_kv_get(line, "src", v, sizeof v) != PMCP_OK || !pmcp_src_valid(v))
        return PMCP_E_PARSE;
    strcpy(o->src, v);
    if (get_u(line, "pid", 0x7fffffffULL, &x) != PMCP_OK)
        return PMCP_E_PARSE;
    o->pid = (unsigned long)x;
    if (get_u(line, "gen", 0xffffffffULL, &x) != PMCP_OK)
        return PMCP_E_PARSE;
    o->gen = (uint32_t)x;
    o->since_ms = 0;
    if (get_u(line, "since_ms", ~0ULL, &x) == PMCP_OK)
        o->since_ms = x;
    /* v1.1: kind missing (a v1 line) or unknown = in */
    o->kind = (pmcp_kv_get(line, "kind", v, sizeof v) == PMCP_OK && strcmp(v, "proxy") == 0)
        ? PMCP_KIND_PROXY : PMCP_KIND_IN;
    return PMCP_OK;
}

unsigned pmcp_owner_preempt_ms(int kind)
{
    return kind == PMCP_KIND_PROXY ? PMCP_MOST_PREEMPT_PROXY_MS : PMCP_MOST_PREEMPT_MS;
}

int pmcp_owner_is_stale(const char *dir, const pmcp_owner *o)
{
    uint64_t now;
    pmcp_session se;
    if (!pmcp_pid_alive(o->pid))
        return 1;
    if (o->since_ms == 0)
        return 0; /* since_ms missing: tolerated, rule not applicable */
    now = pmcp_now_ms();
    if (now <= o->since_ms || now - o->since_ms <= PMCP_MOST_SESSION_WAIT_MS)
        return 0;
    if (pmcp_session_read(dir, o->src, &se) == PMCP_OK && se.gen == o->gen)
        return 0; /* a session with this gen has appeared (start, maybe stop since) */
    return 1;
}

static int owner_path(const char *dir, char *out, size_t sz)
{
    return snprintf(out, sz, "%s/%s", dir, PMCP_MOST_FILE_OWNER) >= (int)sz
        ? PMCP_E_INVAL : PMCP_OK;
}

int pmcp_owner_read(const char *dir, pmcp_owner *o)
{
    char path[512], line[PMCP_MOST_LINE_MAX + 1];
    int r = owner_path(dir, path, sizeof path);
    if (r != PMCP_OK)
        return r;
    r = pmcp_read_line(path, line, sizeof line);
    if (r != PMCP_OK)
        return r;
    return pmcp_owner_parse(line, o);
}

int pmcp_owner_acquire(const char *dir, const char *src, pmcp_owner *out)
{
    return pmcp_owner_acquire_kind(dir, src, PMCP_KIND_IN, out);
}

int pmcp_owner_acquire_kind(const char *dir, const char *src, int kind, pmcp_owner *out)
{
    unsigned long pid = (unsigned long)getpid();
    char path[512], tmp[512], line[PMCP_MOST_LINE_MAX + 1];
    int attempt, r;

    if (!pmcp_src_valid(src) || (kind != PMCP_KIND_IN && kind != PMCP_KIND_PROXY))
        return PMCP_E_INVAL;
    if ((r = ensure_dir(dir)) != PMCP_OK || (r = owner_path(dir, path, sizeof path)) != PMCP_OK)
        return r;

    for (attempt = 0; attempt < 4; attempt++) {
        pmcp_owner cur, now;
        uint32_t prev = 0, gen;
        int missing = 0;

        r = pmcp_owner_read(dir, &cur);
        if (r == PMCP_E_NOENT) {
            missing = 1;
        } else if (r == PMCP_E_PARSE || r == PMCP_E_VERSION) {
            /* unparsable owner = stale (rule documented in the header) */
        } else if (r != PMCP_OK) {
            return r;
        } else {
            prev = cur.gen;
            if (cur.pid == pid && strcmp(cur.src, src) == 0) {
                *out = cur;
                return PMCP_OK;
            }
            if (!pmcp_owner_is_stale(dir, &cur)
                && !(strcmp(src, PMCP_SRC_WIRED) == 0
                     && strcmp(cur.src, PMCP_SRC_WIRELESS) == 0))
                return PMCP_E_BUSY;
        }
        gen = prev + 1u;
        if (gen == 0)
            gen = 1;
        snprintf(line, sizeof line, "v=%d src=%s pid=%lu gen=%lu since_ms=%llu kind=%s",
                 PMCP_MOST_CONTRACT_VERSION, src, pid, (unsigned long)gen,
                 (unsigned long long)pmcp_now_ms(),
                 kind == PMCP_KIND_PROXY ? "proxy" : "in");
        r = write_tmp(dir, PMCP_MOST_FILE_OWNER, line, tmp, sizeof tmp);
        if (r != PMCP_OK)
            return r;
        if (missing) {
            if (link(tmp, path) == 0) {
                unlink(tmp);
            } else if (errno == EEXIST) {
                unlink(tmp);
                continue; /* lost the race, re-evaluate */
            } else if (rename(tmp, path) != 0) { /* no hard links on this fs */
                unlink(tmp);
                return PMCP_E_IO;
            }
        } else if (rename(tmp, path) != 0) {
            unlink(tmp);
            return PMCP_E_IO;
        }
        if (!missing)
            pmcp_sleep_ms(PMCP_MOST_TAKE_VERIFY_MS); /* race window: re-verify */
        if (pmcp_owner_read(dir, &now) == PMCP_OK && now.pid == pid && now.gen == gen) {
            *out = now;
            return PMCP_OK;
        }
        return PMCP_E_BUSY; /* lost the race: back off, nothing written */
    }
    return PMCP_E_BUSY;
}

int pmcp_owner_check(const char *dir, const pmcp_owner *mine)
{
    pmcp_owner cur;
    int r = pmcp_owner_read(dir, &cur);
    if (r == PMCP_E_IO)
        return PMCP_E_IO;
    if (r != PMCP_OK)
        return PMCP_E_PREEMPTED;
    return (cur.pid == mine->pid && cur.gen == mine->gen) ? PMCP_OK : PMCP_E_PREEMPTED;
}

int pmcp_owner_release(const char *dir, const pmcp_owner *mine)
{
    char path[512];
    int r = pmcp_owner_check(dir, mine);
    if (r != PMCP_OK)
        return r;
    if (owner_path(dir, path, sizeof path) != PMCP_OK)
        return PMCP_E_INVAL;
    return unlink(path) == 0 ? PMCP_OK : PMCP_E_IO;
}

/* ---- session ---- */
static int session_name(char *out, size_t sz, const char *src)
{
    if (!pmcp_src_valid(src))
        return PMCP_E_INVAL;
    snprintf(out, sz, "%s%s", src, PMCP_MOST_SESSION_SUFFIX);
    return PMCP_OK;
}

static int reason_ok(const char *s)
{
    size_t i, n = strlen(s);
    if (n == 0 || n > 31)
        return 0;
    for (i = 0; i < n; i++)
        if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= '0' && s[i] <= '9')
              || s[i] == '_' || s[i] == '-'))
            return 0;
    return 1;
}

int pmcp_session_write(const char *dir, const char *src, int start,
                       uint32_t gen, const char *reason)
{
    char name[64], line[PMCP_MOST_LINE_MAX + 1];
    int r = session_name(name, sizeof name, src);
    if (r != PMCP_OK)
        return r;
    if (reason == NULL)
        reason = start ? "start" : "done";
    if (!reason_ok(reason))
        return PMCP_E_INVAL;
    snprintf(line, sizeof line, "v=%d state=%s gen=%lu pid=%lu ts_ms=%llu reason=%s",
             PMCP_MOST_CONTRACT_VERSION, start ? "start" : "stop",
             (unsigned long)gen, (unsigned long)getpid(),
             (unsigned long long)pmcp_now_ms(), reason);
    return pmcp_atomic_write(dir, name, line);
}

int pmcp_session_read(const char *dir, const char *src, pmcp_session *s)
{
    char name[64], path[512], line[PMCP_MOST_LINE_MAX + 1], v[40];
    unsigned long long x;
    int r = session_name(name, sizeof name, src);
    if (r != PMCP_OK)
        return r;
    if (snprintf(path, sizeof path, "%s/%s", dir, name) >= (int)sizeof path)
        return PMCP_E_INVAL;
    r = pmcp_read_line(path, line, sizeof line);
    if (r != PMCP_OK)
        return r;
    if ((r = check_version(line)) != PMCP_OK)
        return r;
    if (pmcp_kv_get(line, "state", v, sizeof v) != PMCP_OK)
        return PMCP_E_PARSE;
    if (strcmp(v, "start") == 0)
        s->start = 1;
    else if (strcmp(v, "stop") == 0)
        s->start = 0;
    else
        return PMCP_E_PARSE;
    if (get_u(line, "gen", 0xffffffffULL, &x) != PMCP_OK)
        return PMCP_E_PARSE;
    s->gen = (uint32_t)x;
    s->pid = get_u(line, "pid", 0x7fffffffULL, &x) == PMCP_OK ? (unsigned long)x : 0;
    s->ts_ms = get_u(line, "ts_ms", ~0ULL, &x) == PMCP_OK ? x : 0;
    s->reason[0] = '\0';
    if (pmcp_kv_get(line, "reason", v, sizeof v) == PMCP_OK) {
        strncpy(s->reason, v, sizeof s->reason - 1);
        s->reason[sizeof s->reason - 1] = '\0';
    }
    return PMCP_OK;
}

/* ---- IDR ---- */
int pmcp_idr_poll_consume(const char *path)
{
    return unlink(path) == 0 ? 1 : 0;
}

int pmcp_idr_request(const char *path)
{
    int fd = open(path, O_WRONLY | O_CREAT, 0644);
    if (fd < 0)
        return PMCP_E_IO;
    close(fd);
    return PMCP_OK;
}

/* ---- consumer status ---- */
static const struct {
    const char *key;
    unsigned bit;
} cs_keys[] = {
    {"ready", PMCP_CS_READY}, {"pid", PMCP_CS_PID}, {"owner_gen", PMCP_CS_OWNER_GEN},
    {"ring_gen", PMCP_CS_RING_GEN}, {"seq", PMCP_CS_SEQ}, {"frames", PMCP_CS_FRAMES},
    {"drops", PMCP_CS_DROPS}, {"overruns", PMCP_CS_OVERRUNS},
    {"latency_resets", PMCP_CS_LATENCY_RESETS}, {"age_ms", PMCP_CS_AGE_MS},
    {"queue_pkts", PMCP_CS_QUEUE_PKTS}, {"queue_hi", PMCP_CS_QUEUE_HI},
    {"reclaims", PMCP_CS_RECLAIMS}, {"most_errno", PMCP_CS_MOST_ERRNO},
    {"up_ms", PMCP_CS_UP_MS}
};

int pmcp_consumer_parse(const char *line, pmcp_consumer_status *st)
{
    size_t i;
    int r = check_version(line);
    if (r != PMCP_OK)
        return r;
    memset(st, 0, sizeof *st);
    for (i = 0; i < sizeof cs_keys / sizeof cs_keys[0]; i++) {
        char v[32];
        unsigned long long x = 0;
        long long sx = 0;
        const char *k = cs_keys[i].key;
        r = pmcp_kv_get(line, k, v, sizeof v);
        if (r == PMCP_E_NOENT)
            continue;
        if (r != PMCP_OK)
            return PMCP_E_PARSE;
        if (cs_keys[i].bit == PMCP_CS_MOST_ERRNO) {
            char *e;
            errno = 0;
            sx = strtoll(v, &e, 10);
            if (errno != 0 || *e != '\0' || v[0] == '\0' || sx < -2147483647LL - 1
                || sx > 2147483647LL)
                return PMCP_E_PARSE;
            st->most_errno = (int)sx;
        } else {
            if (parse_u64(v, &x) != PMCP_OK || x > 0xffffffffULL)
                return PMCP_E_PARSE;
            switch (cs_keys[i].bit) {
            case PMCP_CS_READY: if (x > 1) return PMCP_E_PARSE; st->ready = (int)x; break;
            case PMCP_CS_PID: st->pid = (unsigned long)x; break;
            case PMCP_CS_OWNER_GEN: st->owner_gen = (uint32_t)x; break;
            case PMCP_CS_RING_GEN: st->ring_gen = (uint32_t)x; break;
            case PMCP_CS_SEQ: st->seq = (uint32_t)x; break;
            case PMCP_CS_FRAMES: st->frames = (uint32_t)x; break;
            case PMCP_CS_DROPS: st->drops = (uint32_t)x; break;
            case PMCP_CS_OVERRUNS: st->overruns = (uint32_t)x; break;
            case PMCP_CS_LATENCY_RESETS: st->latency_resets = (uint32_t)x; break;
            case PMCP_CS_AGE_MS: st->age_ms = (uint32_t)x; break;
            case PMCP_CS_QUEUE_PKTS: st->queue_pkts = (uint32_t)x; break;
            case PMCP_CS_QUEUE_HI: st->queue_hi = (uint32_t)x; break;
            case PMCP_CS_RECLAIMS: st->reclaims = (uint32_t)x; break;
            case PMCP_CS_UP_MS: st->up_ms = (uint32_t)x; break;
            default: break;
            }
        }
        st->present |= cs_keys[i].bit;
    }
    return PMCP_OK;
}

static unsigned long sat(uint32_t v, unsigned long max)
{
    return v > max ? max : v;
}

int pmcp_consumer_format(char *buf, size_t bufsz, const pmcp_consumer_status *s)
{
    int e = s->most_errno;
    int n;
    if (e > 99999)
        e = 99999;
    if (e < -99999)
        e = -99999;
    n = snprintf(buf, bufsz,
        "v=%d ready=%d pid=%lu owner_gen=%lu ring_gen=%lu seq=%lu frames=%lu "
        "drops=%lu overruns=%lu latency_resets=%lu age_ms=%lu queue_pkts=%lu "
        "queue_hi=%lu reclaims=%lu most_errno=%d up_ms=%lu",
        PMCP_MOST_CONTRACT_VERSION, s->ready ? 1 : 0,
        s->pid > 9999999UL ? 9999999UL : s->pid,
        (unsigned long)s->owner_gen, (unsigned long)s->ring_gen,
        (unsigned long)s->seq, sat(s->frames, 99999999UL), sat(s->drops, 99999999UL),
        sat(s->overruns, 99999999UL), sat(s->latency_resets, 99999999UL),
        sat(s->age_ms, 999999UL), sat(s->queue_pkts, 999999UL),
        sat(s->queue_hi, 999999UL), sat(s->reclaims, 99999999UL), e,
        sat(s->up_ms, 999999999UL));
    if (n < 0 || (size_t)n >= bufsz || n + 1 > PMCP_MOST_LINE_MAX)
        return PMCP_E_TOOBIG;
    return n;
}

int pmcp_consumer_write(const char *dir, const pmcp_consumer_status *st)
{
    char line[PMCP_MOST_LINE_MAX + 64];
    int n = pmcp_consumer_format(line, sizeof line, st);
    if (n < 0)
        return n;
    return pmcp_atomic_write(dir, PMCP_MOST_FILE_CONSUMER, line);
}

int pmcp_consumer_read(const char *dir, pmcp_consumer_status *st)
{
    char path[512], line[PMCP_MOST_LINE_MAX + 1];
    int r;
    if (snprintf(path, sizeof path, "%s/%s", dir, PMCP_MOST_FILE_CONSUMER) >= (int)sizeof path)
        return PMCP_E_INVAL;
    r = pmcp_read_line(path, line, sizeof line);
    if (r != PMCP_OK)
        return r;
    return pmcp_consumer_parse(line, st);
}

/* ---- producer ---- */
int pmcp_producer_init(pmcp_producer *p, const char *src, const char *dir,
                       const char *ring_path, int create_ring)
{
    int r;
    memset(p, 0, sizeof *p);
    p->map.fd = -1;
    if (!pmcp_src_valid(src))
        return PMCP_E_INVAL;
    if (dir == NULL)
        dir = pmcp_most_src_dir();
    if (ring_path == NULL)
        ring_path = pmcp_most_ring_path();
    if (strlen(dir) >= sizeof p->dir)
        return PMCP_E_INVAL;
    strcpy(p->dir, dir);
    strcpy(p->src, src);
    r = pmcp_ring_open(&p->map, ring_path, create_ring);
    if (r != PMCP_OK)
        return r;
    p->seen_ring_gen = p->map.ring->generation;
    return PMCP_OK;
}

int pmcp_producer_init_proxy(pmcp_producer *p, const char *src, const char *dir)
{
    memset(p, 0, sizeof *p);
    p->map.fd = -1;
    p->kind = PMCP_KIND_PROXY;
    if (!pmcp_src_valid(src))
        return PMCP_E_INVAL;
    if (dir == NULL)
        dir = pmcp_most_src_dir();
    if (strlen(dir) >= sizeof p->dir)
        return PMCP_E_INVAL;
    strcpy(p->dir, dir);
    strcpy(p->src, src);
    return PMCP_OK;
}

int pmcp_producer_acquire(pmcp_producer *p)
{
    int r = pmcp_owner_acquire_kind(p->dir, p->src, p->kind, &p->owner);
    if (r == PMCP_OK) {
        p->owned = 1;
        p->preempted = 0;
    }
    return r;
}

int pmcp_producer_session_start(pmcp_producer *p)
{
    int r;
    if (!p->owned)
        return p->preempted ? PMCP_E_PREEMPTED : PMCP_E_INVAL;
    r = pmcp_session_write(p->dir, p->src, 1, p->owner.gen, "start");
    if (r == PMCP_OK)
        p->session_open = 1;
    return r;
}

int pmcp_producer_check_owner(pmcp_producer *p)
{
    uint64_t now;
    int r;
    if (p->preempted)
        return PMCP_E_PREEMPTED;
    if (!p->owned)
        return PMCP_E_INVAL;
    now = pmcp_now_ms();
    if (p->last_check_ms != 0 && now - p->last_check_ms < PMCP_OWNER_CHECK_MS)
        return PMCP_OK;
    p->last_check_ms = now;
    r = pmcp_owner_check(p->dir, &p->owner);
    if (r == PMCP_E_PREEMPTED) {
        p->owned = 0;
        p->preempted = 1;
        if (p->session_open) {
            pmcp_session_write(p->dir, p->src, 0, p->owner.gen, "preempted");
            p->session_open = 0;
        }
        return PMCP_E_PREEMPTED;
    }
    return PMCP_OK; /* transient I/O error: keep going, re-check next time */
}

int pmcp_producer_write_config(pmcp_producer *p, const void *avcc, uint32_t size)
{
    const uint8_t *b = (const uint8_t *)avcc;
    int r;
    if (p->map.ring == NULL)
        return PMCP_E_INVAL;
    r = pmcp_producer_check_owner(p);
    if (r != PMCP_OK)
        return r;
    if (size < 7 || size > PMCP_RING_SLOT_DATA_MAX || b[0] != 1)
        return size > PMCP_RING_SLOT_DATA_MAX ? PMCP_E_TOOBIG : PMCP_E_INVAL;
    if (size <= PMCP_CFG_CACHE_MAX) {
        memcpy(p->cfg, b, size);
        p->cfg_len = size;
    } else {
        p->cfg_len = 0;
    }
    p->seen_ring_gen = p->map.ring->generation;
    p->cfg_pending = 0;
    pmcp_ring_publish(p->map.ring, PMCP_RING_TYPE_CONFIG, b, size, 0, 0, 0);
    return PMCP_OK;
}

int pmcp_producer_write_frame(pmcp_producer *p, const void *avcc_au,
                              uint32_t size, uint64_t ntp_ts, int keyframe)
{
    uint32_t g;
    int r;
    if (p->map.ring == NULL)
        return PMCP_E_INVAL;
    r = pmcp_producer_check_owner(p);
    if (r != PMCP_OK)
        return r;
    if (size == 0 || size > PMCP_RING_SLOT_DATA_MAX)
        return size == 0 ? PMCP_E_INVAL : PMCP_E_TOOBIG;
    g = p->map.ring->generation;
    if (g != p->seen_ring_gen) {
        p->seen_ring_gen = g;
        if (p->cfg_len != 0)
            p->cfg_pending = 1;
    }
    if (p->cfg_pending) {
        pmcp_ring_publish(p->map.ring, PMCP_RING_TYPE_CONFIG, p->cfg, p->cfg_len, 0, 0, 0);
        p->cfg_pending = 0;
    }
    p->frame_no++;
    pmcp_ring_publish(p->map.ring, PMCP_RING_TYPE_FRAME, avcc_au, size,
#ifndef PMCP_RING_NO_KEYFLAG
                      keyframe ? PMCP_RING_FLAG_KEY : 0u,
#else
                      0u,
#endif
                      p->frame_no, ntp_ts);
    return PMCP_OK;
}

void pmcp_producer_close(pmcp_producer *p, const char *reason)
{
    if (p->session_open) {
        pmcp_session_write(p->dir, p->src, 0, p->owner.gen,
                           reason != NULL ? reason : "done");
        p->session_open = 0;
    }
    if (p->owned) {
        pmcp_owner_release(p->dir, &p->owner);
        p->owned = 0;
    }
    pmcp_ring_close(&p->map);
}

/* ---- consumer gate ---- */
void pmcp_gate_init(pmcp_consumer_gate *g)
{
    memset(g, 0, sizeof *g);
}

int pmcp_gate_owner(pmcp_consumer_gate *g, pmcp_ring *ring, const pmcp_owner *cur, uint64_t now_ms)
{
    uint32_t ng;
    if (cur == NULL)
        return 0;
    if (!g->have || g->owner_gen == cur->gen) {
        g->have = 1;
        g->owner_gen = cur->gen;
        g->last_pid = cur->pid;
        g->last_kind = cur->kind;
        return 0;
    }
    g->prev_pid = g->last_pid;
    g->prev_kind = g->last_kind;
    g->owner_gen = cur->gen;
    g->last_pid = cur->pid;
    g->last_kind = cur->kind;
    g->cut_seq = ring->write_sequence;
    g->cut_ms = now_ms;
    g->cut = 1;
    g->cfg_have = 0;
    g->cfg_len = 0;
    g->cuts++;
    ng = ring->generation + 1u;
    ring->generation = ng == 0 ? 1u : ng;
    PMCP_BARRIER();
    return 1;
}

/* 1 = may open now (sets open_reason, counts forced) */
static int gate_release(pmcp_consumer_gate *g, uint64_t now_ms)
{
    if (g->prev_pid == 0 || !pmcp_pid_alive(g->prev_pid)) {
        g->open_reason = PMCP_GATE_OPEN_EXIT;
        return 1;
    }
    if (now_ms - g->cut_ms >= pmcp_owner_preempt_ms(g->prev_kind)) {
        g->open_reason = PMCP_GATE_OPEN_FORCED;
        g->forced++;
        return 1;
    }
    return 0;
}

int pmcp_gate_slot(pmcp_consumer_gate *g, uint32_t seq, uint32_t type, const void *data,
                   uint32_t size, uint64_t now_ms)
{
    if (!g->cut)
        return PMCP_GATE_PASS;
    if (type != PMCP_RING_TYPE_CONFIG || (int32_t)(seq - g->cut_seq) <= 0)
        return PMCP_GATE_DROP;
    g->cfg_have = 1;
    g->cfg_seq = seq;
    if (data != NULL && size <= PMCP_CFG_CACHE_MAX) {
        memcpy(g->cfg, data, size);
        g->cfg_len = size;
    } else {
        g->cfg_len = 0;
    }
    if (gate_release(g, now_ms)) {
        g->cut = 0;
        g->cfg_have = 0;
        return PMCP_GATE_PASS; /* this very slot is the avcC */
    }
    return PMCP_GATE_HELD;
}

int pmcp_gate_poll(pmcp_consumer_gate *g, uint64_t now_ms)
{
    if (!g->cut || !g->cfg_have)
        return 0;
    if (!gate_release(g, now_ms))
        return 0;
    g->cut = 0;
    g->cfg_have = 0;
    return g->cfg_len > 0;
}
