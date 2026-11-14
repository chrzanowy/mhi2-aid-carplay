/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Synthetic ring producer for the pmcp-most host tests. Writes the AltScreen
 * ring exactly as docs/11-ring-altscreen.md describes core.so doing it:
 *   - waits for the bridge's ring (magic CPRG, version 1, 0x1000710 bytes),
 *     continues from the header's last published sequence;
 *   - slot: sequence = 0, type/size/0/frame_no/NTP lo/hi, data, sequence = N,
 *     then header sequence = N (barriers between the steps);
 *   - type 1 = avcC before the first frame, type 2 = AVCC frame with 4-byte
 *     lengths (AUD/SPS/PPS removed), timestamps NTP 32.32 from CLOCK_MONOTONIC.
 * Input: a real Annex-B capture (--h264, one AU per AUD) or a synthetic
 * Baseline stream (parse-valid SPS/PPS/slice headers, payload bytes 1..255 in
 * a seeded pattern, so no start-code emulation).
 * Force-IDR: when the request file exists it is removed and the N-th next
 * frame is sent as an IDR (what core.so does), or only removed (N = -1).
 * Optional contract v0.2 owner + <src>.session files (start, later stop).
 * Owner switch (stage 1b, consumer gate): --switch-after K writes an "old"
 * stream under owner gen G (pid of a forked idle child, so the test controls
 * when the previous owner dies), then after old frame K installs owner gen
 * G+1 (this pid, --new-kind) and writes a "new" stream (its own avcC with a
 * different SPS, frame_no from 100001) while the old stream keeps writing
 * for --old-tail-ms (every 4th tail frame an IDR). The child is killed --kill-old-ms after the switch
 * (-1: only at the end). Synthetic frames only.
 *
 * Writes OUT/frames.raw.jsonl (one record per frame/event, frame bytes at
 * avcc_off/avcc_bytes in OUT/input.avcc); the harness adds the SHA-256. */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define RING_MAGIC 0x43505247U
#define RING_VERSION 1U
#define RING_SLOTS 64U
#define RING_SLOT_SIZE 0x4001cU
#define RING_HDR 0x10U
#define RING_FILE_SIZE (RING_HDR + RING_SLOTS * RING_SLOT_SIZE)
#define RING_DATA_MAX 0x40000U

typedef struct Buf {
    uint8_t *p;
    size_t n, cap;
} Buf;

static void buf_put(Buf *b, const void *data, size_t n)
{
    if (b->n + n > b->cap) {
        size_t cap = b->cap ? b->cap : 4096;
        while (cap < b->n + n) cap *= 2;
        b->p = (uint8_t *)realloc(b->p, cap);
        if (!b->p) { perror("realloc"); exit(2); }
        b->cap = cap;
    }
    memcpy(b->p + b->n, data, n);
    b->n += n;
}

static void buf_be32(Buf *b, uint32_t v)
{
    uint8_t x[4] = {(uint8_t)(v >> 24), (uint8_t)(v >> 16), (uint8_t)(v >> 8), (uint8_t)v};
    buf_put(b, x, 4);
}

/* ---------------------------------------------------------------- bits */
typedef struct Bits { uint8_t v[64]; size_t bits; } Bits;
static void bits_u(Bits *b, unsigned n, uint32_t x)
{
    while (n--) {
        if ((x >> n) & 1U) b->v[b->bits / 8] |= (uint8_t)(0x80U >> (b->bits % 8));
        ++b->bits;
    }
}
static void bits_ue(Bits *b, uint32_t x)
{
    unsigned n = 0;
    uint32_t y = x + 1U;
    while ((y >> n) > 1U) ++n;
    bits_u(b, n, 0);
    bits_u(b, n + 1U, y);
}
static size_t bits_rbsp(Bits *b)
{
    bits_u(b, 1, 1);
    while (b->bits % 8) ++b->bits;
    return b->bits / 8;
}

/* Same bit layout as aa/most/reference/tools/h264synth.py. */
static size_t make_sps(uint8_t *out, unsigned w, unsigned h)
{
    Bits b; size_t n;
    memset(&b, 0, sizeof(b));
    bits_u(&b, 8, 66); bits_u(&b, 8, 0xC0); bits_u(&b, 8, 31);
    bits_ue(&b, 0); bits_ue(&b, 0); bits_ue(&b, 2); bits_ue(&b, 1); bits_u(&b, 1, 0);
    bits_ue(&b, w / 16 - 1); bits_ue(&b, h / 16 - 1);
    bits_u(&b, 1, 1); bits_u(&b, 1, 1); bits_u(&b, 1, 0); bits_u(&b, 1, 0);
    n = bits_rbsp(&b);
    out[0] = 0x67; memcpy(out + 1, b.v, n);
    return n + 1;
}
static size_t make_pps(uint8_t *out)
{
    Bits b; size_t n;
    memset(&b, 0, sizeof(b));
    bits_ue(&b, 0); bits_ue(&b, 0); bits_u(&b, 1, 0); bits_u(&b, 1, 0);
    bits_ue(&b, 0); bits_ue(&b, 0); bits_ue(&b, 0); bits_u(&b, 1, 0); bits_u(&b, 2, 0);
    n = bits_rbsp(&b);
    out[0] = 0x68; memcpy(out + 1, b.v, n);
    return n + 1;
}

/* One slice NAL of `size` bytes as an AVCC frame. */
static void make_frame(Buf *out, unsigned seed, unsigned idx, int idr, size_t size)
{
    Bits b; size_t head, i;
    uint8_t *nal;
    uint32_t x = (seed * 2654435761U) ^ (idx * 40503U) ^ (idr ? 0x9e3779b9U : 0U);
    memset(&b, 0, sizeof(b));
    bits_ue(&b, 0); bits_ue(&b, idr ? 7 : 5);
    head = bits_rbsp(&b) + 1;
    if (size < head + 4) size = head + 4;
    nal = (uint8_t *)malloc(size);
    if (!nal) exit(2);
    nal[0] = idr ? 0x65 : 0x41;
    memcpy(nal + 1, b.v, head - 1);
    for (i = head; i < size; ++i) {
        x = x * 1103515245U + 12345U;
        nal[i] = (uint8_t)(1U + ((x >> 16) % 255U));  /* never 0: no emulation */
    }
    buf_be32(out, (uint32_t)size);
    buf_put(out, nal, size);
    free(nal);
}

/* ---------------------------------------------------------------- real capture */
typedef struct Au { size_t off, len; int idr; } Au;
static uint8_t *g_cap; static size_t g_cap_n;
static Au *g_aus; static size_t g_au_count;
static uint8_t g_sps[256], g_pps[256]; static size_t g_sps_n, g_pps_n;

static size_t sc_len(const uint8_t *d, size_t n, size_t i)
{
    if (i + 4 <= n && !d[i] && !d[i + 1] && !d[i + 2] && d[i + 3] == 1) return 4;
    if (i + 3 <= n && !d[i] && !d[i + 1] && d[i + 2] == 1) return 3;
    return 0;
}

/* Calls fn for each NAL (start, length) of an Annex-B range. */
static void each_nal(const uint8_t *d, size_t n, void (*fn)(const uint8_t *, size_t, void *), void *ctx)
{
    size_t i = 0, start = (size_t)-1;
    while (i < n) {
        size_t s = sc_len(d, n, i);
        if (s) {
            if (start != (size_t)-1) {
                size_t e = i;
                while (e > start && d[e - 1] == 0) --e;
                fn(d + start, e - start, ctx);
            }
            i += s; start = i;
        } else ++i;
    }
    if (start != (size_t)-1 && start < n) {
        size_t e = n;
        while (e > start && d[e - 1] == 0) --e;
        fn(d + start, e - start, ctx);
    }
}

static void to_avcc_nal(const uint8_t *nal, size_t n, void *ctx)
{
    unsigned t = nal[0] & 0x1fU;
    if (t == 7) { if (n <= sizeof(g_sps)) { memcpy(g_sps, nal, n); g_sps_n = n; } return; }
    if (t == 8) { if (n <= sizeof(g_pps)) { memcpy(g_pps, nal, n); g_pps_n = n; } return; }
    if (t == 9) return;
    buf_be32((Buf *)ctx, (uint32_t)n);
    buf_put((Buf *)ctx, nal, n);
}

static void load_capture(const char *path)
{
    FILE *f = fopen(path, "rb");
    size_t i, cap = 0;
    if (!f) { perror(path); exit(2); }
    fseek(f, 0, SEEK_END); g_cap_n = (size_t)ftell(f); fseek(f, 0, SEEK_SET);
    g_cap = (uint8_t *)malloc(g_cap_n);
    if (!g_cap || fread(g_cap, 1, g_cap_n, f) != g_cap_n) { perror("read"); exit(2); }
    fclose(f);
    for (i = 0; i < g_cap_n;) {
        size_t s = sc_len(g_cap, g_cap_n, i);
        if (s && i + s < g_cap_n) {
            unsigned t = g_cap[i + s] & 0x1fU;
            if (t == 9) {
                if (g_au_count == cap) {
                    cap = cap ? cap * 2 : 1024;
                    g_aus = (Au *)realloc(g_aus, cap * sizeof(*g_aus));
                }
                if (g_au_count) g_aus[g_au_count - 1].len = i - g_aus[g_au_count - 1].off;
                g_aus[g_au_count].off = i; g_aus[g_au_count].len = 0; g_aus[g_au_count].idr = 0;
                ++g_au_count;
            } else if (t == 5 && g_au_count) g_aus[g_au_count - 1].idr = 1;
            i += s;
        } else ++i;
    }
    if (g_au_count) g_aus[g_au_count - 1].len = g_cap_n - g_aus[g_au_count - 1].off;
    if (!g_au_count) { fprintf(stderr, "producer: no AUD in %s\n", path); exit(2); }
}

/* ---------------------------------------------------------------- ring */
static uint8_t *g_ring;
static uint32_t g_seq;

static uint64_t now_ns(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ULL + (uint64_t)t.tv_nsec;
}
static uint64_t now_ntp(void)
{
    uint64_t ns = now_ns();
    uint64_t sec = ns / 1000000000ULL, frac = ns % 1000000000ULL;
    return ((sec & 0xffffffffULL) << 32) | ((frac << 32) / 1000000000ULL);
}
static void wr32(uint32_t off, uint32_t v)
{
    memcpy(g_ring + off, &v, 4); /* little-endian host, as the unit */
}
static uint32_t rd32(uint32_t off)
{
    uint32_t v;
    memcpy(&v, g_ring + off, 4);
    return v;
}

static int ring_attach(const char *path, unsigned timeout_ms)
{
    uint64_t end = now_ns() + (uint64_t)timeout_ms * 1000000ULL;
    while (now_ns() < end) {
        struct stat st;
        if (stat(path, &st) == 0 && st.st_size == (off_t)RING_FILE_SIZE) {
            int fd = open(path, O_RDWR);
            if (fd >= 0) {
                void *m = mmap(NULL, RING_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
                close(fd);
                if (m != MAP_FAILED) {
                    g_ring = (uint8_t *)m;
                    __sync_synchronize();
                    if (rd32(0) == RING_MAGIC && rd32(4) == RING_VERSION) {
                        g_seq = rd32(0x0c);
                        return 0;
                    }
                    munmap(m, RING_FILE_SIZE);
                    g_ring = NULL;
                }
            }
        }
        usleep(10000);
    }
    return -1;
}

static uint32_t ring_put(uint32_t type, const uint8_t *data, size_t n, uint32_t frame_no, uint64_t *ts_out)
{
    uint64_t ts = now_ntp();
    uint32_t off;
    g_seq = g_seq + 1U == 0 ? 1U : g_seq + 1U;
    off = RING_HDR + ((g_seq - 1U) & (RING_SLOTS - 1U)) * RING_SLOT_SIZE;
    wr32(off, 0);
    __sync_synchronize();
    wr32(off + 0x04, type);
    wr32(off + 0x08, (uint32_t)n);
    wr32(off + 0x0c, 0);
    wr32(off + 0x10, frame_no);
    wr32(off + 0x14, (uint32_t)ts);
    wr32(off + 0x18, (uint32_t)(ts >> 32));
    memcpy(g_ring + off + 0x1c, data, n);
    __sync_synchronize();
    wr32(off, g_seq);
    __sync_synchronize();
    wr32(0x0c, g_seq);
    if (ts_out) *ts_out = ts;
    return g_seq;
}

/* ---------------------------------------------------------------- contract files */
static void put_file(const char *dir, const char *name, const char *line)
{
    char tmp[512], path[512];
    FILE *f;
    snprintf(path, sizeof(path), "%s/%s", dir, name);
    snprintf(tmp, sizeof(tmp), "%s/%s.tmp.%ld", dir, name, (long)getpid());
    f = fopen(tmp, "w");
    if (!f) { perror(tmp); return; }
    fputs(line, f);
    fclose(f);
    if (rename(tmp, path) != 0) perror(path);
}

static void hex(FILE *f, const uint8_t *d, size_t n)
{
    size_t i;
    for (i = 0; i < n; ++i) fprintf(f, "%02x", d[i]);
}

/* ---------------------------------------------------------------- owner switch */
typedef struct SwitchOpts {
    const char *dir, *src, *new_src, *kind, *new_kind;
    unsigned gen, new_gen, frames_old_max, new_frames, fps, seed;
    int switch_after, old_tail_ms, new_delay_ms, kill_old_ms;
} SwitchOpts;

static void put_owner(const char *dir, const char *src, long pid, unsigned gen, const char *kind)
{
    char line[256];
    int n = snprintf(line, sizeof(line), "v=1 src=%s pid=%ld gen=%u since_ms=%llu", src, pid, gen,
                     (unsigned long long)(now_ns() / 1000000ULL));
    if (kind && kind[0]) n += snprintf(line + n, sizeof(line) - (size_t)n, " kind=%s", kind);
    snprintf(line + n, sizeof(line) - (size_t)n, "\n");
    put_file(dir, "owner", line);
}

static uint32_t put_avcc(FILE *man, const char *stream, unsigned w, unsigned h)
{
    uint8_t sps[64], pps[64], rec[160];
    size_t sn = make_sps(sps, w, h), pn = make_pps(pps), n = 0;
    uint32_t seq;
    rec[n++] = 1; rec[n++] = sps[1]; rec[n++] = sps[2]; rec[n++] = sps[3]; rec[n++] = 0xff; rec[n++] = 0xe1;
    rec[n++] = (uint8_t)(sn >> 8); rec[n++] = (uint8_t)sn; memcpy(rec + n, sps, sn); n += sn;
    rec[n++] = 1; rec[n++] = (uint8_t)(pn >> 8); rec[n++] = (uint8_t)pn; memcpy(rec + n, pps, pn); n += pn;
    seq = ring_put(1, rec, n, 0, NULL);
    fprintf(man, "{\"event\":\"avcC\",\"stream\":\"%s\",\"ring_seq\":%u,\"bytes\":%zu,\"sps\":\"",
            stream, seq, n);
    hex(man, sps, sn); fprintf(man, "\",\"pps\":\""); hex(man, pps, pn); fprintf(man, "\"}\n");
    return seq;
}

static int run_switch(const SwitchOpts *o, const char *idr_path, FILE *man, FILE *avcc_file)
{
    Buf frame = {0, 0, 0};
    pid_t child = fork();
    uint64_t t0, next_ns, period_ns = 1000000000ULL / o->fps, t_switch = 0;
    unsigned old_no = 0, new_no = 0, idx = 0;
    int switched = 0, new_started = 0, old_idr_pending = 1, new_idr_pending = 1, child_alive = 1;
    size_t avcc_off = 0;
    if (child < 0) { perror("fork"); return 2; }
    if (child == 0) {
        for (;;) pause();
    }
    put_owner(o->dir, o->src, (long)child, o->gen, o->kind);
    put_avcc(man, "old", 800, 480);
    t0 = now_ns();
    next_ns = t0;
    while (new_no < o->new_frames && old_no < o->frames_old_max) {
        uint64_t now = now_ns();
        int k;
        if (next_ns > now) {
            uint64_t d = next_ns - now;
            struct timespec ts_sleep;
            ts_sleep.tv_sec = (time_t)(d / 1000000000ULL);
            ts_sleep.tv_nsec = (long)(d % 1000000000ULL);
            nanosleep(&ts_sleep, NULL);
        }
        next_ns += period_ns;
        now = now_ns();
        if (access(idr_path, F_OK) == 0) {
            unlink(idr_path);
            fprintf(man, "{\"event\":\"idr-request\",\"before_idx\":%u,\"t_us\":%llu,\"action\":\"idr\","
                    "\"stream\":\"%s\"}\n", idx, (unsigned long long)((now - t0) / 1000ULL),
                    switched ? "new" : "old");
            if (switched) new_idr_pending = 1; else old_idr_pending = 1;
        }
        if (switched && child_alive && o->kill_old_ms >= 0 &&
            now >= t_switch + (uint64_t)o->kill_old_ms * 1000000ULL) {
            kill(child, SIGKILL);
            waitpid(child, NULL, 0);
            child_alive = 0;
            fprintf(man, "{\"event\":\"old-killed\",\"t_us\":%llu}\n",
                    (unsigned long long)((now_ns() - t0) / 1000ULL));
        }
        for (k = 0; k < 2; ++k) {
            int is_new = k == 1, idr, forced = 0;
            uint32_t seq, fno;
            uint64_t ts;
            size_t size;
            if (!is_new && switched && now >= t_switch + (uint64_t)o->old_tail_ms * 1000000ULL) continue;
            if (is_new && !switched) continue;
            if (is_new && !new_started) {
                if (now < t_switch + (uint64_t)o->new_delay_ms * 1000000ULL) continue;
                put_avcc(man, "new", 1024, 480);
                new_started = 1;
            }
            idr = is_new ? new_idr_pending : old_idr_pending;
            /* the stale writer keeps sending keyframes too (every 4th tail frame): only
             * the gate, not the wait for a keyframe, may keep them off the output */
            if (!is_new && switched && (old_no - (unsigned)o->switch_after) % 4U == 0U) idr = 1;
            forced = idr && (is_new ? new_no : old_no) > 0;
            if (is_new) new_idr_pending = 0; else old_idr_pending = 0;
            size = idr ? 20000 : 1500 + (size_t)((idx * 2654435761U) % 4501U);
            frame.n = 0;
            make_frame(&frame, o->seed + (is_new ? 7777U : 0U), idx, idr, size);
            fno = is_new ? 100000U + ++new_no : ++old_no;
            seq = ring_put(2, frame.p, frame.n, fno, &ts);
            fwrite(frame.p, 1, frame.n, avcc_file);
            fprintf(man, "{\"idx\":%u,\"frame_no\":%u,\"stream\":\"%s\",\"idr\":%s,\"forced_idr\":%s,"
                    "\"burst\":false,\"avcc_off\":%zu,\"avcc_bytes\":%zu,\"ring_seq\":%u,\"ntp\":%llu,"
                    "\"t_us\":%llu}\n", idx, fno, is_new ? "new" : "old", idr ? "true" : "false",
                    forced ? "true" : "false", avcc_off, frame.n, seq, (unsigned long long)ts,
                    (unsigned long long)((now_ns() - t0) / 1000ULL));
            avcc_off += frame.n;
            ++idx;
            if (!is_new && !switched && (int)old_no == o->switch_after) {
                switched = 1;
                t_switch = now_ns();
                if (o->kill_old_ms == 0) { /* previous owner gone right at the switch */
                    kill(child, SIGKILL);
                    waitpid(child, NULL, 0);
                    child_alive = 0;
                    fprintf(man, "{\"event\":\"old-killed\",\"t_us\":%llu}\n",
                            (unsigned long long)((now_ns() - t0) / 1000ULL));
                }
                put_owner(o->dir, o->new_src, (long)getpid(), o->new_gen, o->new_kind);
                fprintf(man, "{\"event\":\"switch\",\"t_us\":%llu,\"after_ring_seq\":%u}\n",
                        (unsigned long long)((t_switch - t0) / 1000ULL), seq);
                printf("SWITCH\n");
                fflush(stdout);
                now = t_switch;
            }
        }
        fflush(man);
    }
    if (child_alive) {
        kill(child, SIGKILL);
        waitpid(child, NULL, 0);
    }
    fprintf(man, "{\"event\":\"end\",\"old\":%u,\"new\":%u}\n", old_no, new_no);
    free(frame.p);
    return 0;
}

static void usage(void)
{
    fprintf(stderr,
        "usage: producer --ring PATH --idr PATH --out DIR [--h264 FILE] [--frames N] [--fps F]\n"
        "  [--seed S] [--idr-size B] [--p-min B] [--p-max B] [--burst-at K --burst-count M --burst-size B]\n"
        "  [--idr-on-request N] [--session-dir D --src NAME --gen G --stop-after K --stop-hold-ms MS]\n"
        "  [--session-dir D --switch-after K [--kind K] [--new-src S] [--new-kind K] [--old-tail-ms T]\n"
        "   [--new-delay-ms D] [--kill-old-ms X] [--new-frames N]]\n");
    exit(2);
}

int main(int argc, char **argv)
{
    const char *ring_path = NULL, *idr_path = NULL, *out = NULL, *h264 = NULL;
    const char *session_dir = NULL, *src = "wired";
    unsigned frames = 150, fps = 30, seed = 1161, gen = 1;
    size_t idr_size = 20000, p_min = 1500, p_max = 6000, burst_size = 100000;
    int burst_at = -1, burst_count = 0, idr_on_request = 1, stop_after = -1;
    unsigned stop_hold_ms = 2000;
    SwitchOpts sw;
    char path[512], line[256];
    FILE *man, *avcc_file;
    Buf frame = {0, 0, 0};
    uint8_t sps[64], pps[64];
    size_t sps_n, pps_n;
    uint64_t t0, next_ns, period_ns;
    uint32_t frame_no = 0;
    int pending = -1, avcc_sent = 0, stopped = 0;
    unsigned requests = 0;
    size_t avcc_off = 0;
    unsigned idx;
    int i;
    memset(&sw, 0, sizeof(sw));
    sw.switch_after = -1; sw.kind = ""; sw.new_kind = "in"; sw.new_frames = 90; sw.kill_old_ms = -1;
    for (i = 1; i < argc; i += 2) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!v) usage();
        if (!strcmp(a, "--ring")) ring_path = v;
        else if (!strcmp(a, "--idr")) idr_path = v;
        else if (!strcmp(a, "--out")) out = v;
        else if (!strcmp(a, "--h264")) h264 = v;
        else if (!strcmp(a, "--frames")) frames = (unsigned)atoi(v);
        else if (!strcmp(a, "--fps")) fps = (unsigned)atoi(v);
        else if (!strcmp(a, "--seed")) seed = (unsigned)atoi(v);
        else if (!strcmp(a, "--idr-size")) idr_size = (size_t)atol(v);
        else if (!strcmp(a, "--p-min")) p_min = (size_t)atol(v);
        else if (!strcmp(a, "--p-max")) p_max = (size_t)atol(v);
        else if (!strcmp(a, "--burst-at")) burst_at = atoi(v);
        else if (!strcmp(a, "--burst-count")) burst_count = atoi(v);
        else if (!strcmp(a, "--burst-size")) burst_size = (size_t)atol(v);
        else if (!strcmp(a, "--idr-on-request")) idr_on_request = atoi(v);
        else if (!strcmp(a, "--session-dir")) session_dir = v;
        else if (!strcmp(a, "--src")) src = v;
        else if (!strcmp(a, "--gen")) gen = (unsigned)atoi(v);
        else if (!strcmp(a, "--stop-after")) stop_after = atoi(v);
        else if (!strcmp(a, "--stop-hold-ms")) stop_hold_ms = (unsigned)atoi(v);
        else if (!strcmp(a, "--switch-after")) sw.switch_after = atoi(v);
        else if (!strcmp(a, "--kind")) sw.kind = v;
        else if (!strcmp(a, "--new-src")) sw.new_src = v;
        else if (!strcmp(a, "--new-kind")) sw.new_kind = v;
        else if (!strcmp(a, "--old-tail-ms")) sw.old_tail_ms = atoi(v);
        else if (!strcmp(a, "--new-delay-ms")) sw.new_delay_ms = atoi(v);
        else if (!strcmp(a, "--kill-old-ms")) sw.kill_old_ms = atoi(v);
        else if (!strcmp(a, "--new-frames")) sw.new_frames = (unsigned)atoi(v);
        else usage();
    }
    if (!ring_path || !idr_path || !out || fps == 0) usage();
    if (h264) {
        load_capture(h264);
        if (frames > g_au_count) frames = (unsigned)g_au_count;
    }
    snprintf(path, sizeof(path), "%s/frames.raw.jsonl", out);
    man = fopen(path, "w");
    snprintf(path, sizeof(path), "%s/input.avcc", out);
    avcc_file = fopen(path, "wb");
    if (!man || !avcc_file) { perror(out); return 2; }
    if (ring_attach(ring_path, 10000) != 0) {
        fprintf(stderr, "producer: ring not ready\n");
        return 3;
    }
    usleep(200000); /* let the writer thread open its output */
    if (sw.switch_after >= 0) {
        int rc;
        if (!session_dir) usage();
        sw.dir = session_dir; sw.src = src; sw.new_src = sw.new_src ? sw.new_src : src;
        sw.gen = gen; sw.new_gen = gen + 1U == 0 ? 1U : gen + 1U;
        sw.frames_old_max = 100000U; sw.fps = fps; sw.seed = seed;
        rc = run_switch(&sw, idr_path, man, avcc_file);
        fclose(man);
        fclose(avcc_file);
        return rc;
    }
    if (session_dir) {
        uint64_t ms = now_ns() / 1000000ULL;
        snprintf(line, sizeof(line), "v=1 src=%s pid=%ld gen=%u since_ms=%llu\n",
                 src, (long)getpid(), gen, (unsigned long long)ms);
        put_file(session_dir, "owner", line);
        snprintf(line, sizeof(line), "v=1 state=start gen=%u pid=%ld ts_ms=%llu reason=connect\n",
                 gen, (long)getpid(), (unsigned long long)ms);
        snprintf(path, sizeof(path), "%s.session", src);
        put_file(session_dir, path, line);
    }
    sps_n = make_sps(sps, 800, 480);
    pps_n = make_pps(pps);
    t0 = now_ns();
    period_ns = 1000000000ULL / fps;
    next_ns = t0;
    for (idx = 0; idx < frames; ++idx) {
        int burst = burst_at >= 0 && (int)idx >= burst_at && (int)idx < burst_at + burst_count;
        int idr, forced = 0;
        size_t size;
        uint32_t seq;
        uint64_t ts;
        uint64_t now = now_ns();
        if (!burst) {
            if (next_ns > now) {
                uint64_t d = next_ns - now;
                struct timespec ts_sleep;
                ts_sleep.tv_sec = (time_t)(d / 1000000000ULL);
                ts_sleep.tv_nsec = (long)(d % 1000000000ULL);
                nanosleep(&ts_sleep, NULL);
            }
            next_ns += period_ns;
            if (next_ns + period_ns / 2 < now_ns()) next_ns = now_ns();
        } else {
            next_ns = now_ns() + period_ns;
        }
        if (access(idr_path, F_OK) == 0) {
            unlink(idr_path);
            ++requests;
            fprintf(man, "{\"event\":\"idr-request\",\"before_idx\":%u,\"t_us\":%llu,\"action\":\"%s\"}\n",
                    idx, (unsigned long long)((now_ns() - t0) / 1000ULL),
                    idr_on_request >= 0 && pending < 0 ? "idr" : "ignored");
            if (idr_on_request >= 0 && pending < 0) pending = idr_on_request;
        }
        frame.n = 0;
        if (h264) {
            Au *au = &g_aus[idx];
            idr = au->idr;
            if (pending == 0 && !idr) {
                size_t k;
                for (k = 0; k < g_au_count && !g_aus[k].idr; ++k) {}
                if (k < g_au_count) { au = &g_aus[k]; idr = 1; forced = 1; }
            }
            each_nal(g_cap + au->off, au->len, to_avcc_nal, &frame);
            if (!avcc_sent && (!g_sps_n || !g_pps_n)) continue; /* nothing decodable yet */
        } else {
            idr = idx == 0;
            size = burst ? burst_size : p_min + (size_t)((idx * 2654435761U) % (unsigned)(p_max - p_min + 1));
            if (pending == 0 && !idr) { idr = 1; forced = 1; }
            if (idr) size = idr_size;
            make_frame(&frame, seed, idx, idr, size);
        }
        if (pending == 0) pending = -1;
        else if (pending > 0) --pending;
        if (!avcc_sent) {
            const uint8_t *s = h264 ? g_sps : sps, *p = h264 ? g_pps : pps;
            size_t sn = h264 ? g_sps_n : sps_n, pn = h264 ? g_pps_n : pps_n;
            Buf rec = {0, 0, 0};
            uint8_t head[6] = {1, s[1], s[2], s[3], 0xff, 0xe1};
            uint8_t len2[2];
            buf_put(&rec, head, 6);
            len2[0] = (uint8_t)(sn >> 8); len2[1] = (uint8_t)sn; buf_put(&rec, len2, 2); buf_put(&rec, s, sn);
            buf_put(&rec, "\x01", 1);
            len2[0] = (uint8_t)(pn >> 8); len2[1] = (uint8_t)pn; buf_put(&rec, len2, 2); buf_put(&rec, p, pn);
            seq = ring_put(1, rec.p, rec.n, 0, NULL);
            fprintf(man, "{\"event\":\"avcC\",\"ring_seq\":%u,\"bytes\":%zu,\"sps\":\"", seq, rec.n);
            hex(man, s, sn); fprintf(man, "\",\"pps\":\""); hex(man, p, pn); fprintf(man, "\"}\n");
            free(rec.p);
            avcc_sent = 1;
        }
        if (frame.n > RING_DATA_MAX) {
            fprintf(man, "{\"idx\":%u,\"dropped_by_producer\":\"larger than 256 KiB\"}\n", idx);
            continue;
        }
        ++frame_no;
        seq = ring_put(2, frame.p, frame.n, frame_no, &ts);
        fwrite(frame.p, 1, frame.n, avcc_file);
        fprintf(man, "{\"idx\":%u,\"frame_no\":%u,\"idr\":%s,\"forced_idr\":%s,\"burst\":%s,"
                "\"avcc_off\":%zu,\"avcc_bytes\":%zu,\"ring_seq\":%u,\"ntp\":%llu,\"t_us\":%llu}\n",
                idx, frame_no, idr ? "true" : "false", forced ? "true" : "false",
                burst ? "true" : "false", avcc_off, frame.n, seq, (unsigned long long)ts,
                (unsigned long long)((now_ns() - t0) / 1000ULL));
        avcc_off += frame.n;
        if (session_dir && stop_after >= 0 && (int)frame_no == stop_after && !stopped) {
            uint64_t ms = now_ns() / 1000000ULL;
            snprintf(line, sizeof(line), "v=1 state=stop gen=%u pid=%ld ts_ms=%llu reason=test\n",
                     gen, (long)getpid(), (unsigned long long)ms);
            snprintf(path, sizeof(path), "%s.session", src);
            put_file(session_dir, path, line);
            fprintf(man, "{\"event\":\"session-stop\",\"t_us\":%llu}\n",
                    (unsigned long long)((now_ns() - t0) / 1000ULL));
            fflush(man);
            printf("STOP\n");
            fflush(stdout);
            stopped = 1;
            frames = idx + 1 + stop_hold_ms * fps / 1000U; /* keep producing a while */
            if (h264 && frames > g_au_count) frames = (unsigned)g_au_count;
        }
    }
    fprintf(man, "{\"event\":\"end\",\"frames\":%u,\"requests\":%u}\n", frames, requests);
    fclose(man);
    fclose(avcc_file);
    free(frame.p);
    return 0;
}
