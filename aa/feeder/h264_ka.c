/* SPDX-License-Identifier: GPL-3.0-or-later */
/* H.264 keep-alive pictures for the AID while the phone is silent (feeder v17, A215-AA). See h264_ka.h. */
#include "h264_ka.h"

#include <string.h>

#define KA_HEAD_MAX 64u        /* RBSP bytes of a slice header we look at (frame_num / POC end well before) */

typedef struct { const uint8_t *b; unsigned n, pos; int err; } rd_t;

static unsigned rd1(rd_t *r)
{
    unsigned v;
    if (r->pos >= r->n * 8u) { r->err = 1; return 0; }
    v = (r->b[r->pos >> 3] >> (7u - (r->pos & 7u))) & 1u;
    r->pos++;
    return v;
}

static unsigned rdn(rd_t *r, unsigned n)
{
    unsigned v = 0;
    while (n--) v = (v << 1) | rd1(r);
    return v;
}

static unsigned rdue(rd_t *r)
{
    unsigned z = 0;
    while (!r->err && rd1(r) == 0) if (++z > 31) { r->err = 1; return 0; }
    return z ? ((1u << z) - 1u + rdn(r, z)) : 0u;
}

static int rdse(rd_t *r)
{
    unsigned k = rdue(r);
    return (k & 1u) ? (int)((k + 1u) / 2u) : -(int)(k / 2u);
}

/* RBSP of a NAL (header byte skipped, emulation prevention removed), at most cap bytes. */
static unsigned unescape(const uint8_t *nal, unsigned len, uint8_t *out, unsigned cap)
{
    unsigned i, n = 0, zeros = 0;
    for (i = 1; i < len && n < cap; ++i) {
        if (zeros >= 2 && nal[i] == 3) { zeros = 0; continue; }
        zeros = nal[i] == 0 ? zeros + 1 : 0;
        out[n++] = nal[i];
    }
    return n;
}

static void skip_scaling(rd_t *r, unsigned size)
{
    int last = 8, next = 8;
    unsigned j;
    for (j = 0; j < size && !r->err; ++j) {
        if (next != 0) next = (last + rdse(r) + 256) % 256;
        last = next == 0 ? last : next;
    }
}

void h264ka_reset(h264ka_t *k)
{
    memset(k, 0, sizeof *k);
    k->why = "brak SPS/PPS";
}

void h264ka_sps(h264ka_t *k, const uint8_t *nal, unsigned len)
{
    uint8_t b[KA_HEAD_MAX * 2u];
    rd_t r;
    unsigned profile, i, chroma = 1, w, h;
    r.b = b; r.n = unescape(nal, len, b, sizeof b); r.pos = 0; r.err = 0;
    profile = rdn(&r, 8); (void)rdn(&r, 16); (void)rdue(&r);
    if (profile == 100 || profile == 110 || profile == 122 || profile == 244 || profile == 44 || profile == 83 ||
        profile == 86 || profile == 118 || profile == 128) {
        chroma = rdue(&r);
        if (chroma == 3) (void)rd1(&r);
        (void)rdue(&r); (void)rdue(&r); (void)rd1(&r);
        if (rd1(&r))
            for (i = 0; i < (chroma != 3 ? 8u : 12u); ++i)
                if (rd1(&r)) skip_scaling(&r, i < 6 ? 16u : 64u);
    }
    k->log2_fn = rdue(&r) + 4u;
    k->poc_type = rdue(&r);
    k->log2_poc = 0;
    if (k->poc_type == 0) k->log2_poc = rdue(&r) + 4u;
    else if (k->poc_type == 1) {
        unsigned n;
        (void)rd1(&r); (void)rdse(&r); (void)rdse(&r);
        n = rdue(&r);
        for (i = 0; i < n && !r.err; ++i) (void)rdse(&r);
    }
    k->max_refs = rdue(&r);
    (void)rd1(&r);
    w = rdue(&r) + 1u; h = rdue(&r) + 1u;
    k->frame_mbs_only = rd1(&r);
    k->mbs = w * h * (k->frame_mbs_only ? 1u : 2u);
    k->sps_ok = !r.err && k->log2_fn <= 16u && k->log2_poc <= 16u;
    k->have_ref = 0;          /* a new SPS: wait for its IDR */
}

void h264ka_pps(h264ka_t *k, const uint8_t *nal, unsigned len)
{
    uint8_t b[KA_HEAD_MAX];
    rd_t r;
    unsigned groups;
    r.b = b; r.n = unescape(nal, len, b, sizeof b); r.pos = 0; r.err = 0;
    k->pps_id = rdue(&r);
    (void)rdue(&r);
    k->cabac = rd1(&r);
    k->bottom_poc = rd1(&r);
    groups = rdue(&r);
    (void)rdue(&r); (void)rdue(&r);
    k->weighted_p = rd1(&r);
    (void)rdn(&r, 2);
    (void)rdse(&r); (void)rdse(&r); (void)rdse(&r);
    k->deblock_ctrl = rd1(&r);
    (void)rd1(&r);
    k->redundant = rd1(&r);
    k->pps_ok = !r.err && groups == 0;
    k->have_ref = 0;
}

static const char *unsupported(const h264ka_t *k)
{
    if (!k->sps_ok || !k->pps_ok) return "brak SPS/PPS";
    if (!k->frame_mbs_only) return "pola (interlace)";
    if (k->cabac) return "CABAC";
    if (k->poc_type == 1) return "POC typ 1";
    if (k->max_refs != 1u) return "wiecej niz 1 ramka odniesienia";
    if (k->weighted_p) return "predykcja wazona";
    if (k->mbs == 0u || k->mbs > 8160u) return "rozmiar";
    return NULL;
}

/* Copy rbsp (head patched: the first hn bytes come from head) as an escaped NAL after hdr. */
static int escape_out(uint8_t hdr, const uint8_t *nal, unsigned len, const uint8_t *head, unsigned hn,
                      uint8_t *out, unsigned cap, unsigned *out_len)
{
    unsigned i, n = 0, zeros_in = 0, zeros_out = 0, ri = 0;
    if (cap < 1u) return -1;
    out[n++] = hdr;
    for (i = 1; i < len; ++i) {
        uint8_t c = nal[i];
        if (zeros_in >= 2 && c == 3) { zeros_in = 0; continue; }   /* emulation byte of the input */
        zeros_in = c == 0 ? zeros_in + 1 : 0;
        if (ri < hn) c = head[ri];
        ri++;
        if (zeros_out >= 2 && c <= 3) {
            if (n >= cap) return -1;
            out[n++] = 3; zeros_out = 0;
        }
        if (n >= cap) return -1;
        out[n++] = c;
        zeros_out = c == 0 ? zeros_out + 1 : 0;
    }
    *out_len = n;
    return 0;
}

static void put_bits(uint8_t *b, unsigned pos, unsigned n, unsigned v)
{
    while (n--) {
        unsigned bit = (v >> n) & 1u, byte = pos >> 3, sh = 7u - (pos & 7u);
        b[byte] = (uint8_t)((b[byte] & ~(1u << sh)) | (bit << sh));
        pos++;
    }
}

int h264ka_slice(h264ka_t *k, const uint8_t *nal, unsigned len, uint8_t *out, unsigned cap, unsigned *out_len)
{
    uint8_t head[KA_HEAD_MAX];
    rd_t r;
    unsigned type, ref_idc, first_mb, st, pps_id, fn, poc = 0, fn_pos, poc_pos = 0, hn, nfn, npoc;
    const char *bad;
    *out_len = 0;
    if (len < 2u) goto copy_err;
    type = nal[0] & 0x1fu; ref_idc = (nal[0] >> 5) & 3u;
    bad = unsupported(k);
    if (bad != NULL) {                            /* nothing to shift from: never made a keep-alive with these sets */
        k->why = bad;
        k->have_ref = 0;
        if (k->shift == 0u || type == 5u) {
            if (type == 5u) k->shift = 0;
            if (len > cap) return -1;
            memcpy(out, nal, len); *out_len = len;
            return 0;
        }
        goto copy_err;
    }
    hn = unescape(nal, len, head, sizeof head);
    r.b = head; r.n = hn; r.pos = 0; r.err = 0;
    first_mb = rdue(&r);
    st = rdue(&r) % 5u;
    pps_id = rdue(&r);
    fn_pos = r.pos;
    fn = rdn(&r, k->log2_fn);
    if (type == 5u) (void)rdue(&r);
    if (k->poc_type == 0) { poc_pos = r.pos; poc = rdn(&r, k->log2_poc); }
    if (r.err || pps_id != k->pps_id) { k->why = "naglowek wycinka"; goto copy_err; }

    if (type == 5u) {                             /* IDR: the decoder starts over, no shift */
        if (first_mb == 0u) { k->shift = 0; k->idr_resets++; k->have_ref = 1; k->last_fn = fn; k->last_poc = poc; }
        if (len > cap) return -1;
        memcpy(out, nal, len); *out_len = len;
        k->why = "";
        return 0;
    }
    nfn = (fn + k->shift) & ((1u << k->log2_fn) - 1u);
    npoc = k->poc_type == 0 ? (poc + 2u * k->shift) & ((1u << k->log2_poc) - 1u) : 0u;
    if (first_mb == 0u) {
        k->last_fn = nfn; k->last_poc = npoc;
        if (ref_idc == 0u) { k->have_ref = 0; k->why = "obraz bez odniesienia"; }
        else if (st != 0u && st != 2u) { k->have_ref = 0; k->why = "wycinek B/SP/SI"; }
    }
    if (k->shift == 0u) {
        if (len > cap) return -1;
        memcpy(out, nal, len); *out_len = len;
        return 0;
    }
    put_bits(head, fn_pos, k->log2_fn, nfn);
    if (k->poc_type == 0) put_bits(head, poc_pos, k->log2_poc, npoc);
    if (escape_out(nal[0], nal, len, head, hn, out, cap, out_len) != 0) goto copy_err;
    k->rewritten++;
    return 0;

copy_err:
    k->rewrite_err++;
    k->have_ref = 0;
    if (k->why == NULL || k->why[0] == '\0') k->why = "blad przesuniecia";
    if (len <= cap) { memcpy(out, nal, len); *out_len = len; }
    return -1;
}

int h264ka_ready(h264ka_t *k)
{
    const char *bad = unsupported(k);
    if (bad != NULL) { k->why = bad; return 0; }
    if (!k->have_ref) { if (k->why == NULL || k->why[0] == '\0') k->why = "czekam na IDR"; return 0; }
    k->why = "";
    return 1;
}

typedef struct { uint8_t b[48]; unsigned pos; } wr_t;

static void wr1(wr_t *w, unsigned v)
{
    if (w->pos >= sizeof w->b * 8u) return;
    if (v) w->b[w->pos >> 3] |= (uint8_t)(1u << (7u - (w->pos & 7u)));
    w->pos++;
}

static void wrn(wr_t *w, unsigned n, unsigned v) { while (n--) wr1(w, (v >> n) & 1u); }

static void wrue(wr_t *w, unsigned v)
{
    unsigned x = v + 1u, n = 0, t = x;
    while (t > 1u) { t >>= 1; n++; }
    wrn(w, n, 0);
    wrn(w, n + 1u, x);
}

unsigned h264ka_make(h264ka_t *k, uint8_t *out, unsigned cap)
{
    wr_t w;
    unsigned fn, poc, i, n = 0, zeros = 0, bytes;
    if (!h264ka_ready(k)) return 0;
    fn = (k->last_fn + 1u) & ((1u << k->log2_fn) - 1u);
    poc = k->poc_type == 0 ? (k->last_poc + 2u) & ((1u << k->log2_poc) - 1u) : 0u;
    memset(&w, 0, sizeof w);
    wrue(&w, 0);                                  /* first_mb_in_slice */
    wrue(&w, 5);                                  /* slice_type: P, every slice of the picture */
    wrue(&w, k->pps_id);
    wrn(&w, k->log2_fn, fn);                      /* frame_mbs_only: no field flags; not IDR: no idr_pic_id */
    if (k->poc_type == 0) {
        wrn(&w, k->log2_poc, poc);
        if (k->bottom_poc) wrue(&w, 0);           /* delta_pic_order_cnt_bottom se(0) */
    }
    if (k->redundant) wrue(&w, 0);                /* redundant_pic_cnt */
    wr1(&w, 1);                                   /* num_ref_idx_active_override_flag */
    wrue(&w, 0);                                  /* num_ref_idx_l0_active_minus1: one reference */
    wr1(&w, 0);                                   /* ref_pic_list_modification_flag_l0 */
    wr1(&w, 0);                                   /* dec_ref_pic_marking: adaptive_ref_pic_marking_mode_flag */
    wrue(&w, 0);                                  /* slice_qp_delta se(0) */
    if (k->deblock_ctrl) wrue(&w, 1);             /* disable_deblocking_filter_idc 1 */
    wrue(&w, k->mbs);                             /* slice_data: mb_skip_run = every macroblock */
    wr1(&w, 1);                                   /* rbsp_stop_one_bit, then zero alignment */
    bytes = (w.pos + 7u) / 8u;
    if (cap < 1u + bytes + bytes / 2u + 1u) return 0;
    out[n++] = 0x41;                              /* nal_ref_idc 2, non-IDR slice */
    for (i = 0; i < bytes; ++i) {
        if (zeros >= 2 && w.b[i] <= 3) { out[n++] = 3; zeros = 0; }
        out[n++] = w.b[i];
        zeros = w.b[i] == 0 ? zeros + 1 : 0;
    }
    k->last_fn = fn; k->last_poc = poc;
    k->shift++;
    k->made++;
    return n;
}
