/*
 * ts_mux: H.264 access units -> MPEG-TS for the VW AID on MOST. See ts_mux.h for the format and the decisions.
 *
 * The packet and section layout follows omonob/MHI2-Carplay-Maps altscreen_most_bridge.c (GPL-3.0) and
 * harman-f/mhi2_altscreen_carplay direct_ts_parity.c (GPL-3.0-or-later); the CRC, PCR and PTS encoders are
 * the ones of direct_ts_parity.c.
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "ts_mux.h"

#include <stdlib.h>
#include <string.h>

#define ENTRY_CONFIG 1u
#define ENTRY_AU     2u

uint32_t ts_crc32_mpeg(const uint8_t *p, size_t n)
{
    uint32_t crc = 0xffffffffu;
    size_t i;
    unsigned b;
    for (i = 0; i < n; ++i) {
        crc ^= (uint32_t)p[i] << 24;
        for (b = 0; b < 8u; ++b) crc = (crc & 0x80000000u) ? (crc << 1) ^ 0x04c11db7u : (crc << 1);
    }
    return crc;
}

static void psi_packet(uint8_t p[TS_PACKET], uint16_t pid, uint8_t *cc, const uint8_t *sec, size_t sec_len)
{
    uint32_t crc = ts_crc32_mpeg(sec, sec_len);
    memset(p, 0xff, TS_PACKET);
    p[0] = 0x47;
    p[1] = (uint8_t)(0x40u | ((pid >> 8) & 0x1fu));
    p[2] = (uint8_t)pid;
    p[3] = (uint8_t)(0x10u | (*cc & 0x0fu));
    *cc = (uint8_t)((*cc + 1u) & 0x0fu);
    p[4] = 0;                                   /* pointer field */
    memcpy(p + 5, sec, sec_len);
    p[5 + sec_len] = (uint8_t)(crc >> 24);
    p[6 + sec_len] = (uint8_t)(crc >> 16);
    p[7 + sec_len] = (uint8_t)(crc >> 8);
    p[8 + sec_len] = (uint8_t)crc;
}

void ts_make_pat(uint8_t p[TS_PACKET], uint8_t *cc)
{
    /* program 1 -> PMT PID 0x0010 */
    static const uint8_t sec[] = { 0x00, 0xb0, 0x0d, 0x00, 0x01, 0xc1, 0x00, 0x00, 0x00, 0x01, 0xe0, 0x10 };
    psi_packet(p, TS_PID_PAT, cc, sec, sizeof sec);
}

void ts_make_pmt(uint8_t p[TS_PACKET], uint8_t *cc)
{
    /* PCR PID 0x1000, stream type 0x1b (H.264) on PID 0x0011, no descriptors */
    static const uint8_t sec[] = { 0x02, 0xb0, 0x12, 0x00, 0x01, 0xc1, 0x00, 0x00, 0xf0, 0x00, 0xf0, 0x00,
                                   0x1b, 0xe0, 0x11, 0xf0, 0x00 };
    psi_packet(p, TS_PID_PMT, cc, sec, sizeof sec);
}

void ts_make_pcr(uint8_t p[TS_PACKET], uint64_t pcr90k)
{
    uint64_t b = pcr90k & ((1ull << 33) - 1ull);
    memset(p, 0xff, TS_PACKET);
    p[0] = 0x47;
    p[1] = (uint8_t)((TS_PID_PCR >> 8) & 0x1fu);
    p[2] = (uint8_t)TS_PID_PCR;
    p[3] = 0x20;                                /* adaptation only, CC always 0 (as the bridge) */
    p[4] = 183;
    p[5] = 0x10;                                /* PCR flag */
    p[6] = (uint8_t)(b >> 25);
    p[7] = (uint8_t)(b >> 17);
    p[8] = (uint8_t)(b >> 9);
    p[9] = (uint8_t)(b >> 1);
    p[10] = (uint8_t)(((b & 1u) << 7) | 0x7eu);
    p[11] = 0;
}

void ts_make_null(uint8_t p[TS_PACKET], uint8_t *cc)
{
    memset(p, 0xff, TS_PACKET);
    p[0] = 0x47; p[1] = 0x1f; p[2] = 0xff;
    p[3] = (uint8_t)(0x10u | (*cc & 0x0fu));
    *cc = (uint8_t)((*cc + 1u) & 0x0fu);
}

void ts_encode_pts(uint8_t out[5], uint64_t pts90k)
{
    uint64_t v = pts90k & ((1ull << 33) - 1ull);
    out[0] = (uint8_t)(0x20u | (((v >> 30) & 0x07u) << 1) | 1u);
    out[1] = (uint8_t)(v >> 22);
    out[2] = (uint8_t)((((v >> 15) & 0x7fu) << 1) | 1u);
    out[3] = (uint8_t)(v >> 7);
    out[4] = (uint8_t)(((v & 0x7fu) << 1) | 1u);
}

void ts_mux_default_cfg(ts_mux_cfg_t *cfg)
{
    cfg->lead_90k = 9000u;
    cfg->lead_min_90k = 4500u;
    cfg->lead_max_90k = 18000u;
    cfg->discontinuity_first = 1;
}

int ts_mux_init(ts_mux_t *m, uint32_t pool_bytes, uint32_t max_entries, const ts_mux_cfg_t *cfg)
{
    memset(m, 0, sizeof *m);
    if (cfg != NULL) m->cfg = *cfg; else ts_mux_default_cfg(&m->cfg);
    if (m->cfg.lead_min_90k > m->cfg.lead_90k) m->cfg.lead_min_90k = m->cfg.lead_90k;
    if (m->cfg.lead_max_90k != 0u && m->cfg.lead_max_90k < m->cfg.lead_90k) m->cfg.lead_max_90k = m->cfg.lead_90k;
    m->pool = (uint8_t *)malloc(pool_bytes);
    m->q = (ts_entry_t *)calloc(max_entries, sizeof *m->q);
    if (m->pool == NULL || m->q == NULL || max_entries < 2u) { free(m->pool); free(m->q); m->pool = NULL; m->q = NULL; return -1; }
    m->pool_size = pool_bytes;
    m->q_cap = max_entries;
    if (pthread_mutex_init(&m->lock, NULL) != 0) { free(m->pool); free(m->q); m->pool = NULL; m->q = NULL; return -1; }
    return 0;
}

void ts_mux_free(ts_mux_t *m)
{
    if (m->pool == NULL) return;
    pthread_mutex_destroy(&m->lock);
    free(m->pool);
    free(m->q);
    m->pool = NULL;
    m->q = NULL;
}

/* ---------------------------------------------------------------- producer */

/* Reserves len contiguous pool bytes at the producer's write position (wrapping to 0 when the tail is too
 * short). Called with the lock held. The pool is a byte ring: the head entry's data starts the used part. */
static int pool_reserve(ts_mux_t *m, uint32_t len, uint32_t *off)
{
    uint32_t rd;
    if (m->q_count + 1u > m->q_cap) return -1;
    if (m->q_count == 0u && !m->active) { m->wr = 0; *off = 0; return len <= m->pool_size ? 0 : -1; }
    /* the oldest bytes still in use: the AU being sent, else the head entry */
    rd = m->active ? m->cur.off : m->q[m->q_head].off;
    if (m->wr > rd) {                           /* used: [rd, wr); free: [wr, end) and [0, rd) */
        if (m->pool_size - m->wr >= len) { *off = m->wr; return 0; }
        if (rd > len) { *off = 0; return 0; }   /* strictly: wr never catches up with rd */
        return -1;
    }
    if (rd - m->wr > len) { *off = m->wr; return 0; }   /* wrapped: free is [wr, rd) */
    return -1;
}

static int put_entry(ts_mux_t *m, ts_entry_t *e, const uint8_t *a, uint32_t alen, const uint8_t *b, uint32_t blen)
{
    uint32_t off, len = alen + blen, idx;
    if (len > m->pool_size / 2u) return -2;
    pthread_mutex_lock(&m->lock);
    if (pool_reserve(m, len, &off) != 0) { m->st.put_full++; pthread_mutex_unlock(&m->lock); return -1; }
    pthread_mutex_unlock(&m->lock);
    /* the reserved bytes are invisible to the consumer until the entry is committed below */
    if (alen) memcpy(m->pool + off, a, alen);
    if (blen) memcpy(m->pool + off + alen, b, blen);
    e->off = off;
    e->len = len;
    pthread_mutex_lock(&m->lock);
    idx = (m->q_head + m->q_count) % m->q_cap;
    m->q[idx] = *e;
    m->q_count++;
    m->wr = off + len;
    if (e->type == ENTRY_AU) {
        uint32_t aus = m->q_count + (m->active ? 1u : 0u);
        m->queued_packets += e->packets;
        m->st.aus_in++;
        m->st.bytes_in += len;
        if (m->queued_packets > m->st.queue_packets_hi) m->st.queue_packets_hi = m->queued_packets;
        if (aus > m->st.queue_aus_hi) m->st.queue_aus_hi = aus;
    }
    pthread_mutex_unlock(&m->lock);
    return 0;
}

int ts_mux_put_params(ts_mux_t *m, const uint8_t *sps, uint32_t sps_len, const uint8_t *pps, uint32_t pps_len)
{
    ts_entry_t e;
    int r;
    if (sps_len == 0u || pps_len == 0u || sps_len > TS_PS_MAX || pps_len > TS_PS_MAX) return -2;
    memset(&e, 0, sizeof e);
    e.type = ENTRY_CONFIG;
    e.sps_len = sps_len;
    r = put_entry(m, &e, sps, sps_len, pps, pps_len);
    if (r == 0) { m->put_sps_len = sps_len; m->put_pps_len = pps_len; }   /* producer-only fields */
    return r;
}

/* An AVCC buffer with 4-byte lengths that covers len exactly; *idr = it holds NAL type 5. */
static int avcc_scan(const uint8_t *a, uint32_t len, int *idr)
{
    uint32_t off = 0;
    *idr = 0;
    while (off + 4u <= len) {
        uint32_t n = ((uint32_t)a[off] << 24) | ((uint32_t)a[off + 1] << 16) | ((uint32_t)a[off + 2] << 8) | a[off + 3];
        off += 4u;
        if (n == 0u || n > len - off) return -1;
        if ((a[off] & 0x1fu) == 5u) *idr = 1;
        off += n;
    }
    return off == len ? 0 : -1;
}

int ts_mux_put_avcc(ts_mux_t *m, const uint8_t *avcc, uint32_t len, int keyframe, uint64_t t_us, uint32_t seq)
{
    ts_entry_t e;
    int idr;
    uint64_t pes;
    if (len == 0u || avcc_scan(avcc, len, &idr) != 0) return -2;
    memset(&e, 0, sizeof e);
    e.type = ENTRY_AU;
    e.keyframe = (uint8_t)(keyframe || idr);   /* as the bridge: flag or an IDR NAL */
    e.t_us = t_us;
    e.seq = seq;
    pes = TS_PES_HEADER + TS_AUD_BYTES + (uint64_t)len;
    if (e.keyframe && m->put_sps_len && m->put_pps_len) pes += 8u + m->put_sps_len + m->put_pps_len;
    e.packets = ts_packets_for_pes((size_t)pes);
    return put_entry(m, &e, avcc, len, NULL, 0);
}

void ts_mux_depth(ts_mux_t *m, uint32_t *packets, uint32_t *aus)
{
    pthread_mutex_lock(&m->lock);
    if (packets) *packets = m->queued_packets;
    if (aus) {
        uint32_t i, n = m->active ? 1u : 0u;
        for (i = 0; i < m->q_count; ++i) if (m->q[(m->q_head + i) % m->q_cap].type == ENTRY_AU) n++;
        *aus = n;
    }
    pthread_mutex_unlock(&m->lock);
}

void ts_mux_snapshot(ts_mux_t *m, ts_mux_stats_t *out)
{
    pthread_mutex_lock(&m->lock);
    *out = m->st;
    pthread_mutex_unlock(&m->lock);
}

/* ---------------------------------------------------------------- consumer (lock held) */

/* PTS of the AU whose first packet is output packet n and which takes `packets` packets.
 * Anchored on the put time: pts = origin + (t - t0) * 90 kHz, so the AUs keep the producer's cadence.
 * Rebased up when the lead at the AU's last packet would be under lead_min, and down when the lead at its
 * first packet is over lead_max (a stall of the device, or a slower/faster MOST than nominal); both re-anchor
 * at PCR(first) + lead (or later, if the AU is so long that it would not complete lead_min before its PTS).
 * Always strictly increasing. */
static uint64_t assign_pts(ts_mux_t *m, uint64_t n, uint32_t packets, uint64_t t_us)
{
    uint64_t pcr_first = ts_pcr_of_packet(n);
    uint64_t pcr_last = ts_pcr_of_packet(n + (packets ? packets - 1u : 0u));
    uint64_t target = pcr_first + m->cfg.lead_90k, pts;
    if (pcr_last + m->cfg.lead_min_90k > target) target = pcr_last + m->cfg.lead_min_90k;
    if (!m->have_origin) {
        m->origin_pts = target;
        m->origin_t_us = t_us;
        m->have_origin = 1;
    }
    if (t_us < m->origin_t_us) {                     /* never: put times are monotonic; re-anchor anyway */
        m->origin_pts = target;
        m->origin_t_us = t_us;
    }
    pts = m->origin_pts + ((t_us - m->origin_t_us) * 9u) / 100u;
    if (pts < pcr_last + m->cfg.lead_min_90k) {
        m->origin_pts += target - pts;
        pts = target;
        m->st.pts_rebase_up++;
    } else if (m->cfg.lead_max_90k != 0u && pts > pcr_first + m->cfg.lead_max_90k) {
        m->origin_pts -= pts - target;
        pts = target;
        m->st.pts_rebase_down++;
    }
    if (m->sent_first && pts <= m->last_pts) { pts = m->last_pts + 1u; m->st.pts_forced_step++; }
    m->last_pts = pts;
    {
        int64_t lf = (int64_t)pts - (int64_t)pcr_first, ll = (int64_t)pts - (int64_t)pcr_last;
        if (!m->st.have_lead || lf < m->st.lead_first_min) m->st.lead_first_min = lf;
        if (!m->st.have_lead || lf > m->st.lead_first_max) m->st.lead_first_max = lf;
        if (!m->st.have_lead || ll < m->st.lead_last_min) m->st.lead_last_min = ll;
        m->st.lead_first_last = lf;
        m->st.have_lead = 1;
    }
    return pts;
}

/* AVCC lengths -> 4-byte start codes, in place (the AU's bytes belong to the consumer now). */
static void avcc_to_annexb_inplace(uint8_t *a, uint32_t len)
{
    uint32_t off = 0;
    while (off + 4u <= len) {
        uint32_t n = ((uint32_t)a[off] << 24) | ((uint32_t)a[off + 1] << 16) | ((uint32_t)a[off + 2] << 8) | a[off + 3];
        a[off] = 0; a[off + 1] = 0; a[off + 2] = 0; a[off + 3] = 1;
        off += 4u + n;
    }
}

/* Takes queue entries until an AU is ready to send (config entries are applied on the way). */
static int start_next_au(ts_mux_t *m)
{
    while (m->q_count > 0u) {
        ts_entry_t *e = &m->q[m->q_head];
        if (e->type == ENTRY_CONFIG) {
            memcpy(m->sps, m->pool + e->off, e->sps_len);
            m->sps_len = e->sps_len;
            memcpy(m->pps, m->pool + e->off + e->sps_len, e->len - e->sps_len);
            m->pps_len = e->len - e->sps_len;
            m->q_head = (m->q_head + 1u) % m->q_cap;
            m->q_count--;
            continue;
        }
        m->cur = *e;
        m->q_head = (m->q_head + 1u) % m->q_cap;
        m->q_count--;
        m->active = 1;
        m->cur_pos = 0;
        m->cur_packet = 0;
        return 1;
    }
    return 0;
}

/* Builds the PES header + AUD (+ SPS/PPS) prefix of the current AU; its PTS comes from packet n. */
static void begin_au(ts_mux_t *m, uint64_t n)
{
    uint8_t *p = m->prefix;
    uint32_t k = 0;
    int ps = m->cur.keyframe && m->sps_len && m->pps_len;
    uint64_t pts = assign_pts(m, n, m->cur.packets, m->cur.t_us);
    p[k++] = 0x00; p[k++] = 0x00; p[k++] = 0x01; p[k++] = 0xe0;
    p[k++] = 0x00; p[k++] = 0x00;               /* unbounded video PES */
    p[k++] = 0x80; p[k++] = 0x80; p[k++] = 0x05;
    ts_encode_pts(p + k, pts); k += 5u;
    p[k++] = 0; p[k++] = 0; p[k++] = 0; p[k++] = 1; p[k++] = 0x09; p[k++] = 0xf0;
    if (ps) {
        p[k++] = 0; p[k++] = 0; p[k++] = 0; p[k++] = 1;
        memcpy(p + k, m->sps, m->sps_len); k += m->sps_len;
        p[k++] = 0; p[k++] = 0; p[k++] = 0; p[k++] = 1;
        memcpy(p + k, m->pps, m->pps_len); k += m->pps_len;
    } else if (m->cur.keyframe) {
        m->st.aus_without_ps++;
    }
    m->prefix_len = k;
    avcc_to_annexb_inplace(m->pool + m->cur.off, m->cur.len);
    m->cur_total = (uint64_t)k + m->cur.len;
    m->cur_pos = 0;
    m->st.aus_started++;
}

/* Copies n bytes of the current PES (prefix, then the Annex-B body) from cur_pos on. */
static void pes_copy(ts_mux_t *m, uint8_t *dst, uint32_t n)
{
    while (n > 0u) {
        uint32_t c;
        if (m->cur_pos < m->prefix_len) {
            c = m->prefix_len - (uint32_t)m->cur_pos;
            if (c > n) c = n;
            memcpy(dst, m->prefix + m->cur_pos, c);
        } else {
            uint32_t bo = (uint32_t)(m->cur_pos - m->prefix_len);
            c = m->cur.len - bo;
            if (c > n) c = n;
            memcpy(dst, m->pool + m->cur.off + bo, c);
        }
        dst += c; n -= c; m->cur_pos += c;
    }
}

void ts_mux_discontinuity(ts_mux_t *m)
{
    m->disc_next = 1;
}

/* One video packet of the current AU, packetized as the bridge's enqueue_pes(). */
static void video_packet(ts_mux_t *m, uint8_t p[TS_PACKET])
{
    int first = m->cur_pos == 0u;
    uint64_t rem = m->cur_total - m->cur_pos;
    uint32_t max_payload = first ? 182u : 184u;
    uint32_t payload = rem < max_payload ? (uint32_t)rem : max_payload;
    uint32_t adaptation = 184u - payload, po = 4u;
    memset(p, 0xff, TS_PACKET);
    p[0] = 0x47;
    p[1] = (uint8_t)((first ? 0x40u : 0u) | ((TS_PID_VIDEO >> 8) & 0x1fu));
    p[2] = (uint8_t)TS_PID_VIDEO;
    p[3] = (uint8_t)(((adaptation ? 3u : 1u) << 4) | (m->cc_video & 0x0fu));
    m->cc_video = (uint8_t)((m->cc_video + 1u) & 0x0fu);
    if (adaptation) {
        p[4] = (uint8_t)(adaptation - 1u);
        po += adaptation;
        if (adaptation > 1u) {
            uint8_t flags = 0;
            if (first) {
                if (m->cur.keyframe) flags |= 0x40u;
                if ((!m->sent_first && m->cfg.discontinuity_first) || m->disc_next) flags |= 0x80u;
                m->disc_next = 0;
            }
            p[5] = flags;
        }
    }
    pes_copy(m, p + po, payload);
    if (first) m->sent_first = 1;
    m->cur_packet++;
    if (m->queued_packets) m->queued_packets--;
    m->st.video_packets++;
    if (m->cur_pos == m->cur_total) {
        /* the AU's last packet: its pool bytes are free from now on */
        m->active = 0;
        m->st.aus_out++;
        if (m->cur.keyframe) m->st.keyframes_out++;
        if (m->cur_packet != m->cur.packets) m->st.packet_count_mismatch++;   /* never: the count is exact */
    }
}

void ts_mux_fill_block(ts_mux_t *m, uint8_t block[TS_BLOCK_BYTES])
{
    unsigned i;
    pthread_mutex_lock(&m->lock);
    for (i = 0; i < TS_BLOCK_PACKETS; ++i) {
        uint8_t *p = block + i * TS_PACKET;
        uint64_t phase = m->n % TS_PSI_INTERVAL;
        if (phase == 0u) ts_make_pat(p, &m->cc_pat);
        else if (phase == 1u) ts_make_pmt(p, &m->cc_pmt);
        else if (phase == 2u) ts_make_pcr(p, ts_pcr_of_packet(m->n));
        else if (m->active || start_next_au(m)) {
            if (m->cur_pos == 0u) begin_au(m, m->n);
            video_packet(m, p);
        } else {
            ts_make_null(p, &m->cc_null);
            m->st.null_packets++;
        }
        m->n++;
    }
    m->st.packets_out = m->n;
    pthread_mutex_unlock(&m->lock);
}
