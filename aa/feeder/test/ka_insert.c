/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Host tool for h264_ka (A215-AA): reads an Annex B stream, inserts keep-alive pictures, writes Annex B.
 *
 *   ka_insert IN.h264 OUT.h264 MAP.txt PLAN
 *
 * PLAN: comma list of AU:COUNT (after phone picture AU, insert COUNT keep-alives; AU counts pictures from 0).
 * MAP.txt: one line per output picture: "p" (phone) or "k" (keep-alive), then the h264ka counters at the end. */
#include "../h264_ka.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char *rd_all(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb");
    unsigned char *b;
    long s;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END); s = ftell(f); fseek(f, 0, SEEK_SET);
    b = malloc((size_t)s + 1);
    if (fread(b, 1, (size_t)s, f) != (size_t)s) { fclose(f); free(b); return NULL; }
    fclose(f);
    *n = (size_t)s;
    return b;
}

static size_t sc_at(const unsigned char *p, size_t i, size_t n)
{
    if (i + 3 <= n && p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1) return 3;
    if (i + 4 <= n && p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 0 && p[i + 3] == 1) return 4;
    return 0;
}

static const unsigned char SC[4] = {0, 0, 0, 1}, AUD[2] = {0x09, 0xf0};

int main(int argc, char **argv)
{
    size_t n, i = 0, sc;
    unsigned char *p, *out;
    FILE *fo, *fm;
    h264ka_t k;
    long plan_au[256], plan_n[256];
    int np = 0, j;
    long pic = -1;
    int pending = 0;          /* keep-alives due after the current picture ends */
    char *s;
    if (argc != 5) { fprintf(stderr, "usage\n"); return 2; }
    p = rd_all(argv[1], &n);
    if (!p) return 2;
    for (s = strtok(argv[4], ","); s && np < 256; s = strtok(NULL, ",")) {
        plan_au[np] = atol(s);
        plan_n[np] = strchr(s, ':') ? atol(strchr(s, ':') + 1) : 1;
        np++;
    }
    out = malloc(n + 65536);
    fo = fopen(argv[2], "wb"); fm = fopen(argv[3], "w");
    if (!out || !fo || !fm) return 2;
    h264ka_reset(&k);
    while (i < n && (sc = sc_at(p, i, n)) == 0) ++i;
    while (i < n) {
        size_t start = i + sc, end = start, len;
        unsigned type, ol = 0;
        while (end < n && sc_at(p, end, n) == 0) ++end;
        sc = end < n ? sc_at(p, end, n) : 0;
        len = end - start;
        while (len > 0 && p[start + len - 1] == 0 && end < n) --len;
        type = p[start] & 0x1fu;
        /* a new AU starts at AUD / SPS / PPS / first slice: emit the keep-alives due after the previous picture */
        if (pending > 0 && (type == 9 || type == 7 || type == 8 || ((type == 1 || type == 5) && (p[start + 1] & 0x80)))) {
            for (j = 0; j < pending; ++j) {
                unsigned kl = h264ka_make(&k, out, 64);
                if (kl == 0) { fprintf(fm, "skip %s\n", k.why); continue; }
                fwrite(SC, 1, 4, fo); fwrite(AUD, 1, 2, fo);
                fwrite(SC, 1, 4, fo); fwrite(out, 1, kl, fo);
                fprintf(fm, "k\n");
            }
            pending = 0;
        }
        if (type == 7) h264ka_sps(&k, p + start, (unsigned)len);
        if (type == 8) h264ka_pps(&k, p + start, (unsigned)len);
        if (type == 1 || type == 5) {
            if (p[start + 1] & 0x80) {           /* first_mb_in_slice == 0: a new picture */
                pic++;
                fprintf(fm, "p\n");
                for (j = 0; j < np; ++j) if (plan_au[j] == pic) pending += (int)plan_n[j];
            }
            if (h264ka_slice(&k, p + start, (unsigned)len, out, (unsigned)(n + 65536), &ol) != 0)
                fprintf(fm, "err %s\n", k.why);
            fwrite(SC, 1, 4, fo); fwrite(out, 1, ol, fo);
        } else {
            fwrite(SC, 1, 4, fo); fwrite(p + start, 1, len, fo);
        }
        i = end;
    }
    for (j = 0; j < pending; ++j) {
        unsigned kl = h264ka_make(&k, out, 64);
        if (kl == 0) continue;
        fwrite(SC, 1, 4, fo); fwrite(AUD, 1, 2, fo); fwrite(SC, 1, 4, fo); fwrite(out, 1, kl, fo);
        fprintf(fm, "k\n");
    }
    fprintf(fm, "made=%lu rewritten=%lu rewrite_err=%lu idr_resets=%lu shift=%u why=%s\n", k.made, k.rewritten,
            k.rewrite_err, k.idr_resets, k.shift, k.why);
    fclose(fo); fclose(fm);
    return 0;
}
