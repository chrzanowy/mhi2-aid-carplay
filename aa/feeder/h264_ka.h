/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * H.264 keep-alive for the AID (feeder v17, A215-AA). The phone sends the cluster stream only when the picture changes;
 * standing still it can stay silent for 18 s and more. After about 15 s without a frame the cluster drops the map and
 * from then on retries every 5 s (data_rate / map_visible 1110045 flipping, car 2026-11-20) until frames flow again.
 *
 * While the phone is silent the feeder inserts "nothing changed" pictures: a P slice whose macroblocks are all
 * P_Skip (motion 0, no residual, deblocking off), so the decoded picture is an exact copy of the previous one. They
 * are reference pictures with the next frame_num and POC, so every later phone picture is shifted by the same
 * count: its frame_num += k, its pic_order_cnt_lsb += 2k (both fixed width in the slice header; the NAL is re-escaped).
 * An IDR resets the shift. With max_num_ref_frames 1 (the phone's SPS) the skip picture replaces the phone's last
 * picture as the only reference and is identical to it, so the phone's next P picture decodes exactly as it would have.
 *
 * Supported: frame_mbs_only, CAVLC, pic_order_cnt_type 0 or 2, P without weighted prediction, phone pictures that are
 * all reference pictures. Anything else: no keep-alive (reason in h264ka_t.why), phone NALs untouched while shift 0.
 * No allocation, no globals: the caller owns the state and the buffers.
 */
#ifndef PMCP_H264_KA_H
#define PMCP_H264_KA_H

#include <stdint.h>

typedef struct {
    /* parameter sets (last SPS / PPS seen) */
    int sps_ok, pps_ok;
    unsigned log2_fn, log2_poc, poc_type, frame_mbs_only, mbs, max_refs;
    unsigned pps_id, cabac, bottom_poc, weighted_p, redundant, deblock_ctrl;
    /* stream: what the decoder has as its reference (values as sent, after the shift) */
    int have_ref;             /* an IDR went out since the last reset and every picture since was usable */
    unsigned last_fn, last_poc;
    unsigned shift;           /* keep-alive pictures since the last IDR */
    const char *why;          /* why no keep-alive is possible now ("" = possible) */
    /* counters */
    unsigned long made, rewritten, rewrite_err, idr_resets;
} h264ka_t;

void h264ka_reset(h264ka_t *k);
/* nal = one NAL without start code (header byte first). */
void h264ka_sps(h264ka_t *k, const uint8_t *nal, unsigned len);
void h264ka_pps(h264ka_t *k, const uint8_t *nal, unsigned len);

/* One VCL NAL (type 1 or 5) of a phone picture, in output order. Writes the NAL to send into out (cap bytes) and its
 * length to *out_len: unchanged while the shift is 0, else with frame_num / pic_order_cnt_lsb shifted.
 * 0 = ok, -1 = could not parse / does not fit (out holds the original NAL if it fits; the stream may break: counted
 * in rewrite_err, keep-alive off until the next IDR). */
int h264ka_slice(h264ka_t *k, const uint8_t *nal, unsigned len, uint8_t *out, unsigned cap, unsigned *out_len);

/* 1 if a keep-alive picture can be made now (h264ka_t.why says why not otherwise). */
int h264ka_ready(h264ka_t *k);
/* The next keep-alive picture: one NAL (no start code) into out. Returns its length, 0 if not ready / no room. */
unsigned h264ka_make(h264ka_t *k, uint8_t *out, unsigned cap);

#endif
