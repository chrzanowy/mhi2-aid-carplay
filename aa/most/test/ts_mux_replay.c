/*
 * Host unit test driver for ts_mux: replays an Annex-B file through the mux on a virtual 12.288 Mbit/s clock
 * and writes the TS, so the result is deterministic (no threads, no device).
 *
 * usage: ts_mux_replay INPUT.h264 TIMES.txt OUT.ts [--lead-ms 100] [--stall-at BLOCK --stall-ms MS]
 *   INPUT.h264  access units, one per AUD (bridge-stage0 input/input.h264);
 *   TIMES.txt   one line per AU: the time in us it is put (relative), e.g. from frames.jsonl t_us;
 *   --stall-at  the virtual device accepts nothing for MS after block BLOCK (PCR stops, input goes on).
 * Each AU is converted the way the feeder converts the hook's stream: SPS/PPS go to ts_mux_put_params when they
 * change, AUD is dropped, every other NAL is put as AVCC with 4-byte lengths.
 * Prints one line per AU: "au <i> t_us <t> put_block <b>", and a summary.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../ts_mux.h"

static uint8_t *read_file(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb");
    uint8_t *b;
    long sz;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); sz = ftell(f); fseek(f, 0, SEEK_SET);
    b = (uint8_t *)malloc((size_t)sz + 1u);
    if (b && fread(b, 1, (size_t)sz, f) != (size_t)sz) { free(b); b = NULL; }
    fclose(f);
    *n = (size_t)sz;
    return b;
}

static size_t sc_at(const uint8_t *p, size_t i, size_t n)
{
    if (i + 4 <= n && !p[i] && !p[i + 1] && !p[i + 2] && p[i + 3] == 1) return 4;
    if (i + 3 <= n && !p[i] && !p[i + 1] && p[i + 2] == 1) return 3;
    return 0;
}

typedef struct { size_t off, len; } span_t;

int main(int argc, char **argv)
{
    size_t n, i, nn = 0, au_n = 0;
    uint8_t *in;
    span_t *nal;
    size_t *au_first;
    FILE *tf, *out;
    uint64_t *times;
    size_t ti = 0;
    ts_mux_t m;
    ts_mux_cfg_t cfg;
    uint8_t sps[TS_PS_MAX], pps[TS_PS_MAX], cur_sps[TS_PS_MAX], cur_pps[TS_PS_MAX];
    size_t sps_len = 0, pps_len = 0, cur_sps_len = 0, cur_pps_len = 0;
    static uint8_t avcc[4u << 20];
    static uint8_t block[TS_BLOCK_BYTES];
    uint64_t blk = 0, stall_at = (uint64_t)-1, stall_us = 0, put = 0, a;
    int k;
    if (argc < 4) { fprintf(stderr, "usage: %s INPUT.h264 TIMES.txt OUT.ts [--lead-ms N] [--stall-at B --stall-ms MS]\n", argv[0]); return 2; }
    ts_mux_default_cfg(&cfg);
    for (k = 4; k + 1 < argc; k += 2) {
        if (!strcmp(argv[k], "--lead-ms")) cfg.lead_90k = (uint32_t)atoi(argv[k + 1]) * 90u;
        else if (!strcmp(argv[k], "--stall-at")) stall_at = (uint64_t)atoll(argv[k + 1]);
        else if (!strcmp(argv[k], "--stall-ms")) stall_us = (uint64_t)atoll(argv[k + 1]) * 1000u;
    }
    in = read_file(argv[1], &n);
    if (!in) { perror(argv[1]); return 2; }
    nal = (span_t *)calloc(n / 3 + 2, sizeof *nal);
    au_first = (size_t *)calloc(n / 3 + 2, sizeof *au_first);
    times = (uint64_t *)calloc(n / 3 + 2, sizeof *times);
    /* NALs */
    for (i = 0; i < n;) {
        size_t sc = sc_at(in, i, n), s, e;
        if (!sc) { ++i; continue; }
        s = i + sc; e = s;
        while (e < n && !sc_at(in, e, n)) ++e;
        { size_t j = e; while (j > s && in[j - 1] == 0 && e < n) --j; nal[nn].off = s; nal[nn].len = j - s; }
        if ((in[s] & 0x1f) == 9) au_first[au_n++] = nn;
        nn++;
        i = e;
    }
    au_first[au_n] = nn;
    tf = fopen(argv[2], "r");
    if (!tf) { perror(argv[2]); return 2; }
    while (ti < au_n && fscanf(tf, "%llu", (unsigned long long *)&times[ti]) == 1) ti++;
    fclose(tf);
    if (ti != au_n) { fprintf(stderr, "times: %zu, AUs: %zu\n", ti, au_n); return 2; }
    if (ts_mux_init(&m, 16u << 20, 1024u, &cfg) != 0) return 2;
    out = fopen(argv[3], "wb");
    if (!out) { perror(argv[3]); return 2; }
    /* the writer runs from t = 0, the first AU comes 200 ms later (as with the bridge: started before the feeder) */
    for (a = 0;;) {
        /* virtual time at the start of block blk: packets / 8170.2 per s, plus any stall */
        uint64_t now_us = (blk * TS_BLOCK_BYTES * 8u * 1000000u) / 12288000u;
        uint32_t pk = 0;
        if (blk > stall_at) now_us += stall_us;
        while (a < au_n && times[a] + 200000u <= now_us) {
            size_t len = 0, j;
            int key = 0;
            for (j = au_first[a]; j < au_first[a + 1]; ++j) {
                const uint8_t *p = in + nal[j].off;
                size_t l = nal[j].len;
                unsigned t = p[0] & 0x1fu;
                if (t == 9) continue;
                if (t == 7 && l <= TS_PS_MAX) { memcpy(sps, p, l); sps_len = l; continue; }
                if (t == 8 && l <= TS_PS_MAX) { memcpy(pps, p, l); pps_len = l; continue; }
                if (t == 5) key = 1;
                avcc[len++] = (uint8_t)(l >> 24); avcc[len++] = (uint8_t)(l >> 16);
                avcc[len++] = (uint8_t)(l >> 8); avcc[len++] = (uint8_t)l;
                memcpy(avcc + len, p, l); len += l;
            }
            if (sps_len && pps_len && (sps_len != cur_sps_len || pps_len != cur_pps_len ||
                                       memcmp(sps, cur_sps, sps_len) || memcmp(pps, cur_pps, pps_len))) {
                if (ts_mux_put_params(&m, sps, (uint32_t)sps_len, pps, (uint32_t)pps_len) != 0) { fprintf(stderr, "params\n"); return 1; }
                memcpy(cur_sps, sps, sps_len); cur_sps_len = sps_len;
                memcpy(cur_pps, pps, pps_len); cur_pps_len = pps_len;
            }
            if (ts_mux_put_avcc(&m, avcc, (uint32_t)len, key, times[a] + 200000u, (uint32_t)(a + 1)) != 0) {
                fprintf(stderr, "put failed at AU %llu\n", (unsigned long long)a); return 1;
            }
            printf("au %llu t_us %llu put_block %llu\n", (unsigned long long)a, (unsigned long long)times[a], (unsigned long long)blk);
            a++; put++;
        }
        ts_mux_depth(&m, &pk, NULL);
        if (a == au_n && pk == 0 && blk % 41u == 40u) break;   /* drained; stop at a block boundary like the bridge */
        ts_mux_fill_block(&m, block);
        if (fwrite(block, 1, sizeof block, out) != sizeof block) return 1;
        blk++;
    }
    fclose(out);
    {
        ts_mux_stats_t s;
        ts_mux_snapshot(&m, &s);
        printf("summary aus_in=%llu aus_out=%llu blocks=%llu lead_first=%lld..%lld lead_last_min=%lld rebase_up=%llu rebase_down=%llu "
               "forced=%llu q_hi=%u mismatch=%llu without_ps=%llu\n",
               (unsigned long long)s.aus_in, (unsigned long long)s.aus_out, (unsigned long long)blk,
               (long long)s.lead_first_min, (long long)s.lead_first_max, (long long)s.lead_last_min,
               (unsigned long long)s.pts_rebase_up, (unsigned long long)s.pts_rebase_down,
               (unsigned long long)s.pts_forced_step, s.queue_packets_hi, (unsigned long long)s.packet_count_mismatch,
               (unsigned long long)s.aus_without_ps);
        ts_mux_free(&m);
        return s.aus_out == put && s.packet_count_mismatch == 0 ? 0 : 1;
    }
}
