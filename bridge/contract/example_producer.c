/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * example_producer -- host demo of the producer library.
 *
 * Acquires ring ownership as --src, writes session start, a synthetic avcC
 * and synthetic AVCC frames at --fps; reacts to the IDR marker by marking the
 * next frame keyframe; on SIGINT/SIGTERM, --duration/--frames or preemption
 * it ends the session and releases ownership (when still owner).
 *
 * Usage: example_producer --src wired|wireless|aa [--fps N] [--dir D]
 *        [--ring R] [--idr P] [--create-ring] [--duration SEC] [--frames N]
 *        [--gop N] [--size BYTES]
 * Exit: 0 normal/preempted, 2 usage, 3 busy (owned by someone else), 1 error.
 * Every event line carries t=<monotonic ms> so tests can measure latencies.
 */
#define _POSIX_C_SOURCE 200112L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pmcp_most_producer.h"

static volatile sig_atomic_t g_stop;
static void on_sig(int s) { (void)s; g_stop = 1; }

#define T() ((unsigned long long)pmcp_now_ms())

static uint8_t g_frame[PMCP_RING_SLOT_DATA_MAX];

/* synthetic avcC: 1 SPS (8 B), 1 PPS (4 B), 4-byte NAL lengths */
static uint32_t make_config(uint8_t *o)
{
    static const uint8_t sps[8] = {0x67, 0x64, 0x00, 0x1f, 0xac, 0xd9, 0x40, 0x50};
    static const uint8_t pps[4] = {0x68, 0xee, 0x3c, 0x80};
    uint32_t n = 0;
    o[n++] = 1; o[n++] = sps[1]; o[n++] = sps[2]; o[n++] = sps[3];
    o[n++] = 0xff; o[n++] = 0xe1;
    o[n++] = 0; o[n++] = (uint8_t)sizeof sps;
    memcpy(o + n, sps, sizeof sps); n += sizeof sps;
    o[n++] = 1; o[n++] = 0; o[n++] = (uint8_t)sizeof pps;
    memcpy(o + n, pps, sizeof pps); n += sizeof pps;
    return n;
}

/* synthetic AVCC frame: one NAL, 4-byte length prefix */
static uint32_t make_frame(uint32_t no, int key, uint32_t total)
{
    uint32_t nal = total - 4, i;
    g_frame[0] = (uint8_t)(nal >> 24); g_frame[1] = (uint8_t)(nal >> 16);
    g_frame[2] = (uint8_t)(nal >> 8);  g_frame[3] = (uint8_t)nal;
    g_frame[4] = key ? 0x65 : 0x41;
    for (i = 5; i < total; i++)
        g_frame[i] = (uint8_t)(no + i);
    return total;
}

int main(int argc, char **argv)
{
    const char *src = NULL, *dir = NULL, *ringp = NULL, *idrp = NULL;
    const char *why = "done";
    unsigned fps = 30, duration = 0, gop = 300, size = 2000;
    unsigned long max_frames = 0, n = 0;
    int create = 0, want_key = 1, i, r;
    pmcp_producer p;
    uint8_t cfg[64];
    uint64_t t0, next;
    unsigned long long last_frame_t = 0;
    struct sigaction sa;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(a, "--src") && v) src = argv[++i];
        else if (!strcmp(a, "--fps") && v) fps = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--dir") && v) dir = argv[++i];
        else if (!strcmp(a, "--ring") && v) ringp = argv[++i];
        else if (!strcmp(a, "--idr") && v) idrp = argv[++i];
        else if (!strcmp(a, "--create-ring")) create = 1;
        else if (!strcmp(a, "--duration") && v) duration = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--frames") && v) max_frames = strtoul(argv[++i], NULL, 10);
        else if (!strcmp(a, "--gop") && v) gop = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--size") && v) size = (unsigned)atoi(argv[++i]);
        else src = NULL, i = argc;
    }
    if (src == NULL || !pmcp_src_valid(src) || fps == 0 || fps > 1000 || size < 16 || size > PMCP_RING_SLOT_DATA_MAX) {
        fprintf(stderr, "usage: example_producer --src wired|wireless|aa [--fps N] [--dir D] "
                        "[--ring R] [--idr P] [--create-ring] [--duration SEC] [--frames N] "
                        "[--gop N] [--size BYTES]\n");
        return 2;
    }
    if (idrp == NULL) idrp = pmcp_most_idr_path();

    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_sig;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    setvbuf(stdout, NULL, _IOLBF, 0);

    r = pmcp_producer_init(&p, src, dir, ringp, create);
    if (r != PMCP_OK) {
        printf("event=error what=init rc=%d t=%llu\n", r, T());
        return 1;
    }
    r = pmcp_producer_acquire(&p);
    if (r == PMCP_E_BUSY) {
        printf("event=busy src=%s t=%llu\n", src, T());
        pmcp_producer_close(&p, "busy");
        return 3;
    }
    if (r != PMCP_OK) {
        printf("event=error what=acquire rc=%d t=%llu\n", r, T());
        return 1;
    }
    printf("event=acquired src=%s gen=%lu pid=%lu t=%llu\n", src, (unsigned long)p.owner.gen,
           p.owner.pid, T());
    if (pmcp_producer_session_start(&p) != PMCP_OK
        || pmcp_producer_write_config(&p, cfg, make_config(cfg)) != PMCP_OK) {
        printf("event=error what=session-or-config t=%llu\n", T());
        pmcp_producer_close(&p, "error");
        return 1;
    }
    printf("event=session-start src=%s t=%llu\n", src, T());

    t0 = next = pmcp_now_ms();
    while (!g_stop) {
        uint64_t now = pmcp_now_ms();
        if (duration != 0 && now - t0 >= (uint64_t)duration * 1000u)
            break;
        if (max_frames != 0 && n >= max_frames)
            break;
        if (pmcp_idr_poll_consume(idrp)) {
            want_key = 1;
            printf("event=idr-consumed t=%llu\n", T());
        }
        if (now >= next) {
            int key = want_key || (gop != 0 && n % gop == 0);
            uint32_t len = make_frame((uint32_t)n, key, key ? (size * 4 < PMCP_RING_SLOT_DATA_MAX ? size * 4 : size) : size);
            r = pmcp_producer_write_frame(&p, g_frame, len, pmcp_ntp_now(), key);
            if (r == PMCP_E_PREEMPTED)
                break;
            if (r != PMCP_OK) {
                printf("event=error what=write_frame rc=%d t=%llu\n", r, T());
                why = "error";
                break;
            }
            last_frame_t = T();
            printf("frame n=%lu key=%d size=%lu t=%llu\n", n, key, (unsigned long)len, last_frame_t);
            want_key = 0;
            n++;
            next += 1000u / fps;
            if (next + 1000u < now)
                next = now;
        }
        /* idle in short slices: preemption must be noticed within 100 ms */
        if (pmcp_producer_check_owner(&p) == PMCP_E_PREEMPTED)
            break;
        pmcp_sleep_ms(2);
    }
    if (p.preempted) {
        why = "preempted";
        printf("event=preempted t=%llu\n", T());
    } else if (g_stop) {
        why = "sigint";
    }
    printf("event=stopped why=%s frames=%lu last_frame_t=%llu t=%llu\n", why, n, last_frame_t, T());
    pmcp_producer_close(&p, why);
    return 0;
}
