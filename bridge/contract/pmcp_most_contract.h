/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * pmcp_most_contract.h -- producer/consumer contract of the MOST video bridge.
 *
 * Self-contained C99 header, no platform-specific includes: it compiles on
 * macOS (host tests) and on QNX 6.5 gcc (head unit). Contract version 1
 * (contract document: docs/23-wlasny-most.md, "Kontrakt v0.2").
 *
 * Roles
 *   producer  = whoever decodes/receives the phone video and writes H.264
 *               frames into the ring (CarPlay wired: core.so, CarPlay Wi-Fi:
 *               the WL manager, Android Auto: AA feeder).
 *   consumer  = the bridge: reads the ring, muxes MPEG-TS, drives MOST isoTX2.
 *
 * The producer never waits for the consumer (seqlock, no locks). A consumer
 * that is too slow loses frames (overrun); it never blocks the producer.
 *
 * ===========================================================================
 * 1. RING FILE  (PMCP_MOST_RING_PATH_DEFAULT, "ring v1")
 * ===========================================================================
 * Source of truth: docs/11-ring-altscreen.md (measured on the car's core.so).
 * Same memory layout as AltFrameRing in the upstream header
 * altscreen_frame_protocol.h (tomasz/omonob), only the field names differ.
 * Where the two differ in MEANING, docs/11 wins:
 *   - slot offset 0x0c: upstream names it "flags" (bit0 = keyframe); docs/11
 *     measured that core.so always writes 0 there. We name it `flags`,
 *     define bit0 = keyframe as an ADVISORY hint (see PMCP_RING_FLAG_KEY) and
 *     a consumer MUST NOT depend on it.
 *   - slot offset 0x10: upstream "source_sequence"; docs/11: frame counter in
 *     core.so (0 for type 1). Informational only.
 *   - timestamp (0x14..0x1b): NTP 32.32 (high word = seconds, low word =
 *     fraction) taken from the AirPlay message header bytes 8..15; NOT
 *     microseconds. PTS = delta_hi*90000 + ((delta_lo*90000 + 2^31) >> 32).
 *   - header generation (0x08): managed by the CONSUMER (see below); the
 *     upstream header does not say who owns it.
 *
 * All values little-endian, 32-bit. File size 0x1000710 = 16 B header +
 * 64 slots x 0x4001c. Mapped MAP_SHARED, PROT_READ|PROT_WRITE by both sides.
 *
 * Header   : magic 0x43505247 (bytes "GRPC"), version 1, generation,
 *            write_sequence (last published sequence).
 * Slot     : seq (0 while being written, else N; slot index = (N-1)&63,
 *            N starts at 1, wraps 0xFFFFFFFF -> 1), type, size, flags,
 *            frame_no, ts_lo (fraction), ts_hi (seconds), data[0x40000].
 * type 1   : AVCDecoderConfigurationRecord (avcC): byte0 = 1,
 *            (byte4 & 3)+1 = NAL length-field size, byte5 & 0x1f = SPS count,
 *            then SPS/PPS with 2-byte big-endian lengths. Must precede the
 *            first frame.
 * type 2   : one access unit in AVCC format (NAL units prefixed with their
 *            length, size taken from avcC). NOT Annex B. Annex B sources
 *            (Android Auto) must be rewritten to length prefixes and an avcC
 *            built from SPS/PPS. The consumer adds start codes and AUD.
 * other    : consumer skips and counts as drop.
 *
 * Producer write order (no barriers in core.so; the library adds them):
 *   N = write_sequence + 1 (0 skipped); slot.seq = 0; fields + data;
 *   slot.seq = N; write_sequence = N.
 *
 * Consumer read rules: poll every 1 ms; check magic, version, generation;
 *   want sequence W (starts at 1). If W <= write_sequence and
 *   slot[(W-1)&63].seq == W: copy data, re-check slot.seq (changed =>
 *   discard), handle, W++. If slot.seq > W: "ring overrun": jump to that
 *   sequence, drops += difference.
 *
 * Generation: when the ring file is missing or has no magic, the consumer
 * zeroes it and sets generation 1; with valid magic it increments the
 * generation (0 skipped) at start. A consumer that sees the generation change
 * restarts at W = 1. A producer that sees the generation change SHOULD
 * re-send its type 1 config before the next frame (the library does).
 *
 * Who creates the ring: the consumer owns creation and generation. A
 * producer normally opens an EXISTING ring (core.so does exactly that). The
 * producer library can create one, for tests and stand-alone use, in the
 * same way as the consumer does (zero, version 1, generation 1, magic last).
 *
 * ===========================================================================
 * 2. CONTRACT DIRECTORY  (src dir, PMCP_MOST_SRC_DIR_DEFAULT)
 * ===========================================================================
 * Created by whoever needs it first, mode 0755. Every file in it is ONE ASCII
 * line of `key=value` pairs separated by single spaces, ending in '\n', at
 * most PMCP_MOST_LINE_MAX (255) bytes including the '\n'. The first key is
 * always `v=1`. Writers ALWAYS write `<name>.tmp.<pid>` and rename() it over
 * `<name>`, so a reader never sees a partial line. Readers ignore unknown
 * keys (forward compatibility) and reject a `v` they do not know.
 *
 * 2.1 owner  --  `owner`
 *   v=1 src=wired|wireless|aa pid=<pid> gen=<u32> since_ms=<monotonic ms>
 *   Acquire: write owner.tmp.<pid>, then install it over `owner` only if
 *     (a) there is no owner file, or
 *     (b) the owner's pid is dead (kill(pid,0) fails with ESRCH), or
 *     (c) the taker is `wired` and the current owner is `wireless`
 *         (the cable wins).
 *     Otherwise the taker backs off (busy).
 *   gen = previous gen + 1, 0 skipped (no previous file => 1).
 *   Release: remove `owner` only if it still holds my pid AND gen.
 *   Preemption: a producer that finds another pid/gen (or no file) in
 *     `owner` MUST stop writing to the ring within PMCP_MOST_PREEMPT_MS
 *     (100 ms) and end its session (write session state=stop).
 *   Implementation notes (not wire format): the library installs with
 *     link() when no owner exists (atomic fail-if-exists, avoids a double
 *     take) and rename() otherwise; an unparsable owner file counts as stale.
 *
 * 2.2 session  --  `<src>.session`  (wired.session, wireless.session, aa.session)
 *   v=1 state=start|stop gen=<gen from owner> pid=<pid> ts_ms=<monotonic ms> reason=<word>
 *   The consumer treats state=stop (or the file vanishing with a dead pid)
 *   as end of stream immediately, without waiting for a timeout.
 *   reason is one lowercase word [a-z0-9_-] (e.g. start, done, preempted,
 *   sigint, phone-gone, error).
 *
 * 2.3 consumer status  --  `consumer`, refreshed every PMCP_MOST_REFRESH_MS
 *     (1000 ms, +-PMCP_MOST_REFRESH_TOL_MS 100)
 *   v=1 ready=0|1 pid= owner_gen= ring_gen= seq= frames= drops= overruns=
 *   latency_resets= age_ms= queue_pkts= queue_hi= reclaims= most_errno=
 *   up_ms=
 *   ready=1 means isoTX2 is open and the START devctl returned 0. On exit the
 *   consumer writes ready=0 (best effort). seq = last consumed sequence,
 *   age_ms = age of the last frame at consumption, most_errno is a signed
 *   int, up_ms = time since the bridge started. To keep the worst-case line
 *   within 255 bytes writers clamp the fields: pid <= 9999999;
 *   most_errno in [-99999, 99999]; age_ms, queue_pkts, queue_hi <= 999999;
 *   frames, drops, overruns, latency_resets, reclaims <= 99999999;
 *   up_ms <= 999999999; owner_gen, ring_gen, seq are plain u32. Readers
 *   accept any u32 for the unsigned keys (a future writer may clamp
 *   differently). Worst-case line length with these clamps: 253 bytes.
 *   255 bytes. Producers only read it; they never need it to stream.
 *
 * 2.4 IDR request  --  PMCP_MOST_IDR_PATH_DEFAULT (unchanged from core.so)
 *   The consumer creates the marker file (e.g. after dropping a stale
 *   backlog); the producer consumes it (unlink) and asks the phone for a
 *   genuine IDR, then marks that frame keyframe. unlink() is atomic, so
 *   exactly one producer sees success.
 *
 * Paths: everything below PMCP_MOST_BASE_DIR (default /ramdisk). Override at
 * build time with -DPMCP_MOST_BASE_DIR="\"/x\"" and at run time (tests) with
 * the environment variables PMCP_MOST_SRC_DIR, PMCP_MOST_RING,
 * PMCP_MOST_IDR (see the pmcp_most_*_path() helpers).
 *
 * Versioning: additive keys only within v=1. A breaking change bumps v=.
 */
#ifndef PMCP_MOST_CONTRACT_H
#define PMCP_MOST_CONTRACT_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

#define PMCP_MOST_CONTRACT_VERSION 1

/* ---- paths ------------------------------------------------------------ */
#ifndef PMCP_MOST_BASE_DIR
#define PMCP_MOST_BASE_DIR "/ramdisk"
#endif
#define PMCP_MOST_SRC_DIR_DEFAULT  PMCP_MOST_BASE_DIR "/most-src"
#define PMCP_MOST_RING_PATH_DEFAULT PMCP_MOST_BASE_DIR "/carplay-alt-ring.bin"
#define PMCP_MOST_IDR_PATH_DEFAULT PMCP_MOST_BASE_DIR "/carplay-alt-force-idr.request"

#define PMCP_MOST_ENV_SRC_DIR "PMCP_MOST_SRC_DIR"
#define PMCP_MOST_ENV_RING    "PMCP_MOST_RING"
#define PMCP_MOST_ENV_IDR     "PMCP_MOST_IDR"

#define PMCP_MOST_FILE_OWNER    "owner"
#define PMCP_MOST_FILE_CONSUMER "consumer"
#define PMCP_MOST_SESSION_SUFFIX ".session"

/* ---- sources ---------------------------------------------------------- */
#define PMCP_SRC_WIRED    "wired"
#define PMCP_SRC_WIRELESS "wireless"
#define PMCP_SRC_AA       "aa"
#define PMCP_SRC_NAME_MAX 16

/* ---- limits ----------------------------------------------------------- */
#define PMCP_MOST_LINE_MAX        255   /* bytes incl. trailing '\n' */
#define PMCP_MOST_REFRESH_MS      1000  /* consumer status refresh */
#define PMCP_MOST_REFRESH_TOL_MS  100
#define PMCP_MOST_PREEMPT_MS      100   /* preempted producer must stop within */
#define PMCP_MOST_DIR_MODE        0755

/* ---- ring ------------------------------------------------------------- */
#define PMCP_RING_MAGIC          0x43505247u /* bytes "GRPC" */
#define PMCP_RING_VERSION        1u
#define PMCP_RING_SLOT_COUNT     64u
#define PMCP_RING_SLOT_DATA_MAX  0x40000u
#define PMCP_RING_TYPE_CONFIG    1u /* avcC */
#define PMCP_RING_TYPE_FRAME     2u /* AVCC access unit */
#define PMCP_RING_FLAG_KEY       1u /* advisory, see top comment */

#define PMCP_RING_HEADER_SIZE    0x10u
#define PMCP_RING_SLOT_SIZE      0x4001cu
#define PMCP_RING_FILE_SIZE      0x1000710u

typedef struct pmcp_ring_slot {
    volatile uint32_t seq;        /* 0x00 0 while writing, then N */
    uint32_t type;                /* 0x04 1 = avcC, 2 = frame */
    uint32_t size;                /* 0x08 1..0x40000 */
    uint32_t flags;               /* 0x0c core.so: 0; bit0 = keyframe (advisory) */
    uint32_t frame_no;            /* 0x10 frame counter (type 1: 0) */
    uint32_t ts_lo;               /* 0x14 NTP fraction */
    uint32_t ts_hi;               /* 0x18 NTP seconds */
    uint8_t  data[PMCP_RING_SLOT_DATA_MAX]; /* 0x1c */
} pmcp_ring_slot;

typedef struct pmcp_ring {
    volatile uint32_t magic;          /* 0x00 */
    uint32_t version;                 /* 0x04 */
    volatile uint32_t generation;     /* 0x08 owned by the consumer */
    volatile uint32_t write_sequence; /* 0x0c last published sequence */
    pmcp_ring_slot slots[PMCP_RING_SLOT_COUNT]; /* 0x10 */
} pmcp_ring;

/* compile-time layout checks (C99 compatible) */
#define PMCP_STATIC_ASSERT(cond, name) typedef char pmcp_sa_##name[(cond) ? 1 : -1]
PMCP_STATIC_ASSERT(sizeof(uint32_t) == 4, u32_is_4);
PMCP_STATIC_ASSERT(sizeof(pmcp_ring_slot) == PMCP_RING_SLOT_SIZE, slot_size_0x4001c);
PMCP_STATIC_ASSERT(offsetof(pmcp_ring, slots) == PMCP_RING_HEADER_SIZE, header_size_0x10);
PMCP_STATIC_ASSERT(sizeof(pmcp_ring) == PMCP_RING_FILE_SIZE, ring_size_0x1000710);
PMCP_STATIC_ASSERT(offsetof(pmcp_ring_slot, data) == 0x1c, slot_data_off_0x1c);
PMCP_STATIC_ASSERT(offsetof(pmcp_ring_slot, ts_lo) == 0x14, slot_ts_off_0x14);

/* ---- run-time path resolution ----------------------------------------- */
static inline const char *pmcp_most_env_or(const char *env, const char *dflt)
{
    const char *v = getenv(env);
    return (v != NULL && v[0] != '\0') ? v : dflt;
}
static inline const char *pmcp_most_src_dir(void)
{
    return pmcp_most_env_or(PMCP_MOST_ENV_SRC_DIR, PMCP_MOST_SRC_DIR_DEFAULT);
}
static inline const char *pmcp_most_ring_path(void)
{
    return pmcp_most_env_or(PMCP_MOST_ENV_RING, PMCP_MOST_RING_PATH_DEFAULT);
}
static inline const char *pmcp_most_idr_path(void)
{
    return pmcp_most_env_or(PMCP_MOST_ENV_IDR, PMCP_MOST_IDR_PATH_DEFAULT);
}

#endif /* PMCP_MOST_CONTRACT_H */
