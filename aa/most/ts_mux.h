/*
 * ts_mux: H.264 access units -> the MPEG-TS stream the VW AID expects on MOST (isoTX2).
 *
 * Output format (byte for byte the one of altscreen-most-bridge, docs: bridge-spike CONTRACT.md section 3):
 *   188-byte packets in 64-packet / 12032-byte blocks; PAT on PID 0, PMT on 0x10, PCR-only packets on 0x1000
 *   (CC always 0), H.264 on 0x11, null packets on 0x1fff; PAT/PMT/PCR at output packet n % 327 == 0/1/2;
 *   PCR base = 45000 + n * 705 / 64 (12.288 Mbit/s, packet count, not wall clock); PES header
 *   00 00 01 e0 00 00 80 80 05 + PTS; the first TS packet of an AU always has an adaptation field of at
 *   least 2 bytes (flags 0x40 random access on a keyframe, 0x80 discontinuity); the AU is
 *   AUD (09 f0), SPS + PPS before a keyframe, then every NAL, all with 4-byte start codes.
 *
 * Decisions that intentionally differ from the bridge (they follow harman-f's corrected version):
 *   - the queue holds whole AUs; nothing is ever discarded, truncated or skipped (AA mode never drops);
 *   - the first AU of a mux session carries the discontinuity flag (the v1.x bridge never sets it at start);
 *   - the PTS is assigned when the AU's first TS packet is built, from the transport clock of that packet,
 *     so the lead over PCR cannot go negative however long the AU waited in the queue (the bridge stamps at
 *     enqueue time and sends late PTS after a backlog).
 *
 * Threads: one producer (ts_mux_put_*) and one consumer (ts_mux_fill_block). The pool is allocated once in
 * ts_mux_init; nothing is allocated afterwards.
 *
 * The packet and section layout follows omonob/MHI2-Carplay-Maps altscreen_most_bridge.c (GPL-3.0) and
 * harman-f/mhi2_altscreen_carplay direct_ts_parity.c (GPL-3.0-or-later).
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef PMCP_TS_MUX_H
#define PMCP_TS_MUX_H

#include <pthread.h>
#include <stddef.h>
#include <stdint.h>

#define TS_PACKET          188u
#define TS_BLOCK_PACKETS   64u
#define TS_BLOCK_BYTES     (TS_PACKET * TS_BLOCK_PACKETS)   /* 12032 */
#define TS_PSI_INTERVAL    327u
#define TS_PCR_ORIGIN_90K  45000u
#define TS_TICKS_NUM       705u                             /* 90 kHz ticks per 64 packets at 12.288 Mbit/s */
#define TS_TICKS_DEN       64u
#define TS_PID_PAT         0x0000u
#define TS_PID_PMT         0x0010u
#define TS_PID_PCR         0x1000u
#define TS_PID_VIDEO       0x0011u
#define TS_PID_NULL        0x1fffu
#define TS_PS_MAX          256u                             /* one SPS or PPS */
#define TS_PES_HEADER      14u
#define TS_AUD_BYTES       6u                               /* 00 00 00 01 09 f0 */

/* PCR base (90 kHz) of output packet n. */
static inline uint64_t ts_pcr_of_packet(uint64_t n)
{
    return TS_PCR_ORIGIN_90K + (n * TS_TICKS_NUM) / TS_TICKS_DEN;
}

/* Packet builders, also used by the tests. cc is the per-PID continuity counter, advanced. */
void ts_make_pat(uint8_t p[TS_PACKET], uint8_t *cc);
void ts_make_pmt(uint8_t p[TS_PACKET], uint8_t *cc);
void ts_make_pcr(uint8_t p[TS_PACKET], uint64_t pcr90k);
void ts_make_null(uint8_t p[TS_PACKET], uint8_t *cc);
void ts_encode_pts(uint8_t out[5], uint64_t pts90k);
uint32_t ts_crc32_mpeg(const uint8_t *p, size_t n);

/* TS packets of a PES of pes_bytes (first packet: 182 payload bytes at most, then 184). */
static inline unsigned ts_packets_for_pes(size_t pes_bytes)
{
    return pes_bytes <= 182u ? 1u : 1u + (unsigned)((pes_bytes - 182u + 183u) / 184u);
}

typedef struct {
    uint32_t lead_90k;        /* PTS target lead over PCR when (re)anchoring; default 9000 (100 ms) */
    uint32_t lead_min_90k;    /* lead at the AU's LAST packet below this: rebase up; default 4500 (50 ms) */
    uint32_t lead_max_90k;    /* lead at the AU's first packet above this: rebase down; default 18000 (200 ms); 0 = never */
    int discontinuity_first;  /* 0x80 on the first AU (harman-f); default 1 */
} ts_mux_cfg_t;

/* Queue entry: one AU (AVCC with 4-byte lengths, as in the ring) or one parameter set update. */
typedef struct {
    uint32_t off, len;        /* bytes in the pool */
    uint32_t sps_len;         /* config entry: SPS bytes, then PPS bytes */
    uint32_t packets;         /* AU: TS packets it will take */
    uint64_t t_us;            /* AU: time it was put (monotonic) */
    uint32_t seq;             /* AU: producer's frame number (diagnostics) */
    uint8_t type;             /* 1 config, 2 AU */
    uint8_t keyframe;
} ts_entry_t;

typedef struct {
    /* written by the consumer under the lock; read by the producer for its status */
    uint64_t packets_out, video_packets, null_packets, aus_out, aus_started, keyframes_out;
    uint64_t pts_rebase_up, pts_rebase_down, pts_forced_step;
    int64_t lead_first_min, lead_first_max, lead_last_min, lead_first_last;   /* 90 kHz */
    int have_lead;
    uint64_t aus_without_ps;  /* keyframes sent before any SPS/PPS was known */
    uint64_t packet_count_mismatch;   /* must stay 0 */
    /* producer side */
    uint64_t aus_in, bytes_in, put_full;
    uint32_t queue_packets_hi, queue_aus_hi;
} ts_mux_stats_t;

typedef struct {
    pthread_mutex_t lock;
    ts_mux_cfg_t cfg;
    uint8_t *pool;
    uint32_t pool_size;
    ts_entry_t *q;
    uint32_t q_cap, q_head, q_count;
    uint32_t wr;              /* next free pool byte (producer) */
    uint32_t queued_packets;  /* packets of every queued AU not yet built (head AU: its remaining packets) */
    uint32_t reserved_len, reserved_off;   /* producer: space reserved, not yet committed */
    /* producer view of the parameter sets, for the packet count of a keyframe */
    uint32_t put_sps_len, put_pps_len;
    /* consumer state */
    uint8_t cc_pat, cc_pmt, cc_null, cc_video;
    uint64_t n;               /* output packets built so far */
    uint8_t sps[TS_PS_MAX], pps[TS_PS_MAX];
    uint32_t sps_len, pps_len;
    int active;               /* an AU is being sent */
    ts_entry_t cur;
    uint8_t prefix[TS_PES_HEADER + TS_AUD_BYTES + 8u + 2u * TS_PS_MAX];
    uint32_t prefix_len;
    uint64_t cur_total, cur_pos;
    uint32_t cur_packet;      /* packets of the current AU built so far */
    int sent_first;           /* the first AU of the session went out */
    int have_origin;
    uint64_t origin_pts, origin_t_us, last_pts;
    ts_mux_stats_t st;
} ts_mux_t;

/* pool_bytes: AU and parameter-set bytes; max_entries: queue entries. 0 = ok, -1 = no memory. */
int ts_mux_init(ts_mux_t *m, uint32_t pool_bytes, uint32_t max_entries, const ts_mux_cfg_t *cfg);
void ts_mux_free(ts_mux_t *m);
void ts_mux_default_cfg(ts_mux_cfg_t *cfg);

/* Producer. Both return 0, or -1 when the pool or the entry table has no room now (the caller retries later;
 * nothing is dropped), or -2 when the data can never fit / is invalid. */
int ts_mux_put_params(ts_mux_t *m, const uint8_t *sps, uint32_t sps_len, const uint8_t *pps, uint32_t pps_len);
int ts_mux_put_avcc(ts_mux_t *m, const uint8_t *avcc, uint32_t len, int keyframe, uint64_t t_us, uint32_t seq);

/* Queue depth now: TS packets still to send and AUs (the head AU counts until its last packet is built). */
void ts_mux_depth(ts_mux_t *m, uint32_t *packets, uint32_t *aus);
void ts_mux_snapshot(ts_mux_t *m, ts_mux_stats_t *out);

/* Consumer: the next 64 packets. Never blocks on input: PSI/PCR at their slots, queued video, else null. */
void ts_mux_fill_block(ts_mux_t *m, uint8_t block[TS_BLOCK_BYTES]);

#endif
