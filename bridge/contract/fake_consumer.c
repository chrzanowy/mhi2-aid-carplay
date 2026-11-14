/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * fake_consumer -- stand-in for the MOST bridge, for host tests of a producer.
 *
 * Maps the ring, reads frames by the docs/11 reader rules (1 ms poll, overrun
 * skip, generation), validates the AVCC payload, writes the consumer status
 * file every 1000 ms with every contract key (queue numbers are synthetic),
 * follows session stop of the current owner, and prints one line per frame or
 * event on stdout.
 *
 * Usage: fake_consumer [--dir D] [--ring R] [--idr P] [--idr-every SEC]
 *                      [--overrun-after N [--stall-ms MS]] [--duration SEC]
 *                      [--max-frames N]
 * Defaults follow the contract (env PMCP_MOST_SRC_DIR / _RING / _IDR).
 * Stops on SIGINT/SIGTERM, --duration or --max-frames; writes ready=0 on exit.
 */
#define _POSIX_C_SOURCE 200112L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "pmcp_most_producer.h"

static volatile sig_atomic_t g_stop;
static void on_sig(int s) { (void)s; g_stop = 1; }

static uint8_t g_buf[PMCP_RING_SLOT_DATA_MAX];

typedef struct { int seen, start; uint32_t gen; uint64_t ts; } sess_seen;

static uint32_t ntp_age_ms(uint64_t ts)
{
    uint64_t now = pmcp_ntp_now();
    int64_t d = (int64_t)(now - ts);
    int64_t ms;
    if (d < 0)
        return 0;
    ms = (d >> 32) * 1000 + (int64_t)((((uint64_t)d & 0xffffffffu) * 1000u) >> 32);
    return ms > 999999999 ? 999999999u : (uint32_t)ms;
}

/* returns nonzero if the avcC is sane; sets nal_len and sps count */
static int check_avcc_config(const uint8_t *d, uint32_t n, int *nal_len, int *sps)
{
    if (n < 7 || d[0] != 1)
        return 0;
    *nal_len = (d[4] & 3) + 1;
    *sps = d[5] & 0x1f;
    return 1;
}

/* AVCC access unit: NAL units must tile the buffer exactly */
static int check_avcc_frame(const uint8_t *d, uint32_t n, int nal_len)
{
    uint32_t off = 0;
    while (off < n) {
        uint32_t len = 0;
        int i;
        if (off + (uint32_t)nal_len > n)
            return 0;
        for (i = 0; i < nal_len; i++)
            len = (len << 8) | d[off + (uint32_t)i];
        off += (uint32_t)nal_len;
        if (len == 0 || len > n - off)
            return 0;
        off += len;
    }
    return n != 0;
}

int main(int argc, char **argv)
{
    const char *dir = NULL, *ringp = NULL, *idrp = NULL;
    unsigned idr_every = 0, stall_ms = 1500, duration = 0;
    unsigned long overrun_after = 0, max_frames = 0;
    pmcp_ring_map map;
    pmcp_ring *ring;
    pmcp_consumer_status st;
    sess_seen ss[3];
    static const char *const srcs[3] = {PMCP_SRC_WIRED, PMCP_SRC_WIRELESS, PMCP_SRC_AA};
    uint32_t W = 1, my_gen;
    int cfg_seen = 0, nal_len = 4, stalled = 0, i;
    uint64_t t0, last_status, last_sess = 0, next_idr = 0;
    unsigned long total = 0;
    struct sigaction sa;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *v = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(a, "--dir") && v) dir = argv[++i];
        else if (!strcmp(a, "--ring") && v) ringp = argv[++i];
        else if (!strcmp(a, "--idr") && v) idrp = argv[++i];
        else if (!strcmp(a, "--idr-every") && v) idr_every = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--overrun-after") && v) overrun_after = strtoul(argv[++i], NULL, 10);
        else if (!strcmp(a, "--stall-ms") && v) stall_ms = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--duration") && v) duration = (unsigned)atoi(argv[++i]);
        else if (!strcmp(a, "--max-frames") && v) max_frames = strtoul(argv[++i], NULL, 10);
        else {
            fprintf(stderr, "usage: fake_consumer [--dir D] [--ring R] [--idr P] [--idr-every SEC] "
                            "[--overrun-after N] [--stall-ms MS] [--duration SEC] [--max-frames N]\n");
            return 2;
        }
    }
    if (dir == NULL) dir = pmcp_most_src_dir();
    if (ringp == NULL) ringp = pmcp_most_ring_path();
    if (idrp == NULL) idrp = pmcp_most_idr_path();

    memset(&sa, 0, sizeof sa);
    sa.sa_handler = on_sig;
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
    setvbuf(stdout, NULL, _IOLBF, 0);

    if (pmcp_ring_open(&map, ringp, 2) != PMCP_OK) {
        fprintf(stderr, "fake_consumer: cannot open ring %s\n", ringp);
        return 1;
    }
    ring = map.ring;
    my_gen = pmcp_ring_consumer_attach(&map);
    memset(&st, 0, sizeof st);
    memset(ss, 0, sizeof ss);
    st.ready = 1;
    st.pid = (unsigned long)getpid();
    st.ring_gen = my_gen;
    t0 = pmcp_now_ms();
    last_status = t0;
    next_idr = t0 + (uint64_t)idr_every * 1000u;
    printf("event=start dir=%s ring=%s ring_gen=%lu\n", dir, ringp, (unsigned long)my_gen);
    pmcp_consumer_write(dir, &st);

    while (!g_stop) {
        uint64_t now = pmcp_now_ms();
        int worked = 0;

        /* ---- ring ---- */
        if (ring->magic != PMCP_RING_MAGIC || ring->version != PMCP_RING_VERSION) {
            /* producer/other consumer has not initialised it: wait */
        } else if (ring->generation != my_gen) {
            my_gen = ring->generation;
            W = 1;
            cfg_seen = 0;
            st.ring_gen = my_gen;
            printf("event=ring-generation gen=%lu\n", (unsigned long)my_gen);
        } else if (W <= ring->write_sequence) {
            pmcp_ring_slot *s = &ring->slots[(W - 1u) & (PMCP_RING_SLOT_COUNT - 1u)];
            uint32_t sq = s->seq;
            if (sq == W) {
                uint32_t type = s->type, size = s->size, flags = s->flags, fno = s->frame_no;
                uint64_t ts = ((uint64_t)s->ts_hi << 32) | s->ts_lo;
                int ok = size >= 1 && size <= PMCP_RING_SLOT_DATA_MAX;
                if (ok)
                    memcpy(g_buf, s->data, size);
                if (s->seq != W) {
                    /* overwritten while copying: discard, overrun logic next round */
                    st.drops++;
                    worked = 1;
                } else {
                    uint32_t seqn = W;
                    W++;
                    worked = 1;
                    st.seq = seqn;
                    if (!ok || (type != PMCP_RING_TYPE_CONFIG && type != PMCP_RING_TYPE_FRAME)) {
                        st.drops++;
                        printf("event=drop reason=bad-type-or-size seq=%lu type=%lu size=%lu\n",
                               (unsigned long)seqn, (unsigned long)type, (unsigned long)size);
                    } else if (type == PMCP_RING_TYPE_CONFIG) {
                        int sps = 0;
                        if (check_avcc_config(g_buf, size, &nal_len, &sps)) {
                            cfg_seen = 1;
                            printf("config seq=%lu size=%lu nal_len=%d sps=%d\n",
                                   (unsigned long)seqn, (unsigned long)size, nal_len, sps);
                        } else {
                            st.drops++;
                            printf("event=bad-config seq=%lu\n", (unsigned long)seqn);
                        }
                    } else if (!cfg_seen) {
                        st.drops++;
                        printf("event=drop reason=no-config seq=%lu\n", (unsigned long)seqn);
                    } else if (!check_avcc_frame(g_buf, size, nal_len)) {
                        st.drops++;
                        printf("event=bad-frame seq=%lu size=%lu\n", (unsigned long)seqn,
                               (unsigned long)size);
                    } else {
                        st.frames++;
                        total++;
                        st.age_ms = ntp_age_ms(ts);
                        st.queue_pkts = st.frames % 17u;
                        if (st.queue_pkts > st.queue_hi)
                            st.queue_hi = st.queue_pkts;
                        printf("frame seq=%lu size=%lu key=%d fno=%lu ts=%lu.%lu age_ms=%lu\n",
                               (unsigned long)seqn, (unsigned long)size,
                               (flags & PMCP_RING_FLAG_KEY) ? 1 : 0, (unsigned long)fno,
                               (unsigned long)(ts >> 32), (unsigned long)(ts & 0xffffffffu),
                               (unsigned long)st.age_ms);
                        if (overrun_after != 0 && !stalled && total >= overrun_after) {
                            stalled = 1;
                            printf("event=stall ms=%u\n", stall_ms);
                            pmcp_sleep_ms(stall_ms);
                        }
                        if (max_frames != 0 && total >= max_frames)
                            g_stop = 1;
                    }
                }
            } else if (sq > W) {
                printf("event=overrun from=%lu to=%lu dropped=%lu\n", (unsigned long)W,
                       (unsigned long)sq, (unsigned long)(sq - W));
                st.overruns++;
                st.latency_resets++;
                st.drops += sq - W;
                W = sq;
                worked = 1;
            }
        }

        /* ---- sessions + owner, every 20 ms ---- */
        if (now - last_sess >= 20) {
            pmcp_owner ow;
            int have_owner = pmcp_owner_read(dir, &ow) == PMCP_OK;
            last_sess = now;
            st.owner_gen = have_owner ? ow.gen : 0;
            for (i = 0; i < 3; i++) {
                pmcp_session se;
                if (pmcp_session_read(dir, srcs[i], &se) != PMCP_OK)
                    continue;
                if (ss[i].seen && ss[i].start == se.start && ss[i].gen == se.gen && ss[i].ts == se.ts_ms)
                    continue;
                ss[i].seen = 1; ss[i].start = se.start; ss[i].gen = se.gen; ss[i].ts = se.ts_ms;
                printf("event=session src=%s state=%s gen=%lu reason=%s\n", srcs[i],
                       se.start ? "start" : "stop", (unsigned long)se.gen, se.reason);
                if (!se.start && (!have_owner || strcmp(ow.src, srcs[i]) == 0)) {
                    cfg_seen = 0; /* end of stream: wait for a new config */
                    printf("event=stream-end src=%s\n", srcs[i]);
                }
            }
        }

        /* ---- IDR requests ---- */
        if (idr_every != 0 && now >= next_idr) {
            next_idr += (uint64_t)idr_every * 1000u;
            if (access(idrp, F_OK) != 0 && pmcp_idr_request(idrp) == PMCP_OK)
                printf("event=idr-request\n");
        }

        /* ---- status at 1 Hz ---- */
        if (now - last_status >= PMCP_MOST_REFRESH_MS) {
            last_status += PMCP_MOST_REFRESH_MS;
            if (now - last_status >= PMCP_MOST_REFRESH_MS)
                last_status = now;
            st.up_ms = (uint32_t)(now - t0);
            if (pmcp_consumer_write(dir, &st) != PMCP_OK)
                printf("event=status-write-failed\n");
        }

        if (duration != 0 && now - t0 >= (uint64_t)duration * 1000u)
            break;
        if (!worked)
            pmcp_sleep_ms(1);
    }

    st.ready = 0;
    st.up_ms = (uint32_t)(pmcp_now_ms() - t0);
    pmcp_consumer_write(dir, &st);
    printf("event=exit frames=%lu drops=%lu overruns=%lu\n", (unsigned long)st.frames,
           (unsigned long)st.drops, (unsigned long)st.overruns);
    pmcp_ring_close(&map);
    return 0;
}
