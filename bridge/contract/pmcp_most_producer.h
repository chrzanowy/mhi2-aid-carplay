/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * pmcp_most_producer.h -- small producer-side library for the MOST bridge
 * contract (see pmcp_most_contract.h). C99 + POSIX only, no threads, no
 * malloc anywhere; the frame path touches only caller memory, the mapped ring
 * and a few stat()/read() calls (owner check throttled to every 10 ms).
 */
#ifndef PMCP_MOST_PRODUCER_H
#define PMCP_MOST_PRODUCER_H

#include <stddef.h>
#include <stdint.h>
#include "pmcp_most_contract.h"

#ifdef __cplusplus
extern "C" {
#endif

#define PMCP_OK            0
#define PMCP_E_IO         -1
#define PMCP_E_BUSY       -2  /* somebody else owns the ring */
#define PMCP_E_PREEMPTED  -3  /* we lost ownership: stop writing */
#define PMCP_E_INVAL      -4
#define PMCP_E_TOOBIG     -5
#define PMCP_E_PARSE      -6
#define PMCP_E_VERSION    -7  /* v= is not PMCP_MOST_CONTRACT_VERSION */
#define PMCP_E_NOENT      -8

#define PMCP_OWNER_CHECK_MS 10   /* min interval between owner file reads */
#define PMCP_CFG_CACHE_MAX  4096

/* ---- time ------------------------------------------------------------- */
uint64_t pmcp_now_ms(void);      /* CLOCK_MONOTONIC, system wide */
uint64_t pmcp_ntp_now(void);     /* wall clock as NTP 32.32 (hi<<32 | lo) */
void     pmcp_sleep_ms(unsigned ms);

/* ---- line files ------------------------------------------------------- */
/* Write `line` (no newline, <= 254 chars) as <dir>/<name> atomically via
 * <name>.tmp.<pid> + rename. Creates dir (0755) if missing. */
int pmcp_atomic_write(const char *dir, const char *name, const char *line);
/* Read a whole line file (<=255 B, must end in '\n'); strips the '\n'. */
int pmcp_read_line(const char *path, char *buf, size_t bufsz);
/* Find key in "k=v k=v ..." line; copy value into val. 0 = found. */
int pmcp_kv_get(const char *line, const char *key, char *val, size_t valsz);

/* ---- ring ------------------------------------------------------------- */
typedef struct pmcp_ring_map {
    int fd;
    pmcp_ring *ring;
} pmcp_ring_map;

/* create=0: open existing ring (E_NOENT when missing, E_PARSE if the size or
 * magic is wrong: the consumer has not initialised it yet). Producers ALWAYS
 * use create=0.
 * create=2: CONSUMER ONLY: create/extend the file, leave the header alone
 *           (pmcp_ring_consumer_attach() initialises it).
 * create=1: create/extend; if magic is missing initialise it like the
 * consumer does (zero, version 1, generation 1, magic last). */
int  pmcp_ring_open(pmcp_ring_map *m, const char *path, int create);
void pmcp_ring_close(pmcp_ring_map *m);
/* Consumer-side attach: zero + generation 1 if no magic, else generation+1
 * skipping 0. Returns the new generation. Mapping must be created=1. */
uint32_t pmcp_ring_consumer_attach(pmcp_ring_map *m);
/* Publish one slot following the seq protocol. Returns the sequence. */
uint32_t pmcp_ring_publish(pmcp_ring *r, uint32_t type, const void *data,
                           uint32_t size, uint32_t flags, uint32_t frame_no,
                           uint64_t ntp_ts);

/* ---- owner ------------------------------------------------------------ */
#define PMCP_KIND_IN    0   /* owner writes the ring itself (default) */
#define PMCP_KIND_PROXY 1   /* supervisor owns, another process writes */

typedef struct pmcp_owner {
    char src[PMCP_SRC_NAME_MAX];
    unsigned long pid;
    uint32_t gen;
    uint64_t since_ms;
    int kind;                /* PMCP_KIND_*; missing key in the file = IN */
} pmcp_owner;

/* Preemption deadline for an owner of this kind (100 or 3000 ms). */
unsigned pmcp_owner_preempt_ms(int kind);

int pmcp_src_valid(const char *src);
int pmcp_pid_alive(unsigned long pid);
int pmcp_owner_parse(const char *line, pmcp_owner *o);
int pmcp_owner_read(const char *dir, pmcp_owner *o);   /* E_NOENT if none */
/* Stale = unparsable, dead pid, or (since_ms present, older than
 * PMCP_MOST_SESSION_WAIT_MS and no <src>.session with this gen). */
int pmcp_owner_is_stale(const char *dir, const pmcp_owner *o);
/* PMCP_OK + *out filled, or PMCP_E_BUSY (also when we lost the race: after a
 * takeover we wait PMCP_MOST_TAKE_VERIFY_MS and re-verify). kind = in. */
int pmcp_owner_acquire(const char *dir, const char *src, pmcp_owner *out);
int pmcp_owner_acquire_kind(const char *dir, const char *src, int kind, pmcp_owner *out);
/* OK if removed; E_PREEMPTED if the file is not ours (left untouched). */
int pmcp_owner_release(const char *dir, const pmcp_owner *mine);
/* OK = still ours, E_PREEMPTED = someone else (or nobody) is in `owner`. */
int pmcp_owner_check(const char *dir, const pmcp_owner *mine);

/* ---- session ---------------------------------------------------------- */
typedef struct pmcp_session {
    int start;               /* 1 = state=start, 0 = state=stop */
    uint32_t gen;
    unsigned long pid;
    uint64_t ts_ms;
    char reason[32];
} pmcp_session;

int pmcp_session_write(const char *dir, const char *src, int start,
                       uint32_t gen, const char *reason);
int pmcp_session_read(const char *dir, const char *src, pmcp_session *s);

/* ---- consumer gate (v1.1) --------------------------------------------- */
/* Cuts off a stale writer after an owner gen change. Reusable by the bridge:
 *   per loop:  if (pmcp_gate_owner(&g, ring, have ? &ow : NULL, now)) {
 *                  W = ring->write_sequence + 1; forget avcC; }   (ring gen bumped)
 *              if (pmcp_gate_poll(&g, now)) emit the held avcC g.cfg/g.cfg_len
 *                  (as a type-1 slot, seq g.cfg_seq) and request an IDR;
 *   per slot:  r = pmcp_gate_slot(&g, seq, type, data, size, now);
 *              PASS = process normally, DROP/HELD = discard (count as drop).
 * Rules: after an owner gen change every slot is dropped until a new type-1
 * (avcC) written after the change. Additionally the gate remembers the PREVIOUS
 * owner (pid, kind): if that pid is still alive the gate stays closed even
 * after the new avcC, until (a) the pid is gone (kill(pid,0) == ESRCH) or (b)
 * pmcp_owner_preempt_ms(prev kind) (100 / 3000 ms) have passed since the cut;
 * on (b) it opens anyway and counts `forced`. The last avcC seen after the cut
 * is kept in the gate (<= PMCP_CFG_CACHE_MAX) and emitted by pmcp_gate_poll()
 * when the gate opens late, so the new source need not resend it. Note: for
 * kind=proxy the owner pid is the supervisor; it must live exactly as long as
 * the writer it supervises (parent of the writing process). */
#define PMCP_GATE_PASS 0
#define PMCP_GATE_DROP 1
#define PMCP_GATE_HELD 2  /* a new avcC arrived but the old writer is alive: stored, dropped */
#define PMCP_GATE_OPEN_NONE   0
#define PMCP_GATE_OPEN_EXIT   1 /* previous owner pid gone (or none known) */
#define PMCP_GATE_OPEN_FORCED 2 /* deadline passed, previous pid still alive */
typedef struct pmcp_consumer_gate {
    int have;                /* an owner has been observed */
    uint32_t owner_gen;
    unsigned long last_pid;  /* current owner as last observed */
    int last_kind;
    int cut;                 /* closed */
    uint32_t cut_seq;        /* ring write_sequence at the cut */
    uint64_t cut_ms;
    unsigned long prev_pid;  /* owner before the cut */
    int prev_kind;
    int cfg_have;            /* an avcC after the cut is stored */
    uint32_t cfg_seq;
    uint32_t cfg_len;
    int open_reason;         /* PMCP_GATE_OPEN_* of the last opening */
    uint32_t cuts;
    uint32_t forced;         /* gate_forced counter */
    uint8_t cfg[PMCP_CFG_CACHE_MAX];
} pmcp_consumer_gate;
void pmcp_gate_init(pmcp_consumer_gate *g);
/* cur=NULL: owner file missing (state kept, no cut). Returns 1 when the gen
 * changed against the last observed one: ring generation bumped (0 skipped),
 * gate closed. The first observation never cuts. */
int pmcp_gate_owner(pmcp_consumer_gate *g, pmcp_ring *ring, const pmcp_owner *cur, uint64_t now_ms);
int pmcp_gate_slot(pmcp_consumer_gate *g, uint32_t seq, uint32_t type, const void *data,
                   uint32_t size, uint64_t now_ms);
/* 1 = the gate just opened and a stored avcC (g->cfg, g->cfg_len, g->cfg_seq)
 * must be emitted now. */
int pmcp_gate_poll(pmcp_consumer_gate *g, uint64_t now_ms);

/* ---- IDR marker ------------------------------------------------------- */
/* Producer: 1 = marker existed and was consumed (next frame = keyframe). */
int pmcp_idr_poll_consume(const char *path);
/* Consumer: create the marker (idempotent). */
int pmcp_idr_request(const char *path);

/* ---- consumer status -------------------------------------------------- */
enum {
    PMCP_CS_READY = 1u << 0, PMCP_CS_PID = 1u << 1, PMCP_CS_OWNER_GEN = 1u << 2,
    PMCP_CS_RING_GEN = 1u << 3, PMCP_CS_SEQ = 1u << 4, PMCP_CS_FRAMES = 1u << 5,
    PMCP_CS_DROPS = 1u << 6, PMCP_CS_OVERRUNS = 1u << 7,
    PMCP_CS_LATENCY_RESETS = 1u << 8, PMCP_CS_AGE_MS = 1u << 9,
    PMCP_CS_QUEUE_PKTS = 1u << 10, PMCP_CS_QUEUE_HI = 1u << 11,
    PMCP_CS_RECLAIMS = 1u << 12, PMCP_CS_MOST_ERRNO = 1u << 13,
    PMCP_CS_UP_MS = 1u << 14, PMCP_CS_ALL = (1u << 15) - 1u
};

typedef struct pmcp_consumer_status {
    unsigned present;        /* PMCP_CS_* bits of keys that were in the line */
    int ready;
    unsigned long pid;
    uint32_t owner_gen, ring_gen, seq;
    uint32_t frames, drops, overruns, latency_resets, age_ms;
    uint32_t queue_pkts, queue_hi, reclaims;
    int most_errno;
    uint32_t up_ms;
} pmcp_consumer_status;

/* Unknown keys ignored; missing keys stay 0 and are absent from `present`;
 * E_VERSION when v != 1; E_PARSE on a malformed known value. */
int pmcp_consumer_parse(const char *line, pmcp_consumer_status *st);
/* Fields are clamped as listed in pmcp_most_contract.h (2.3). */
int pmcp_consumer_format(char *buf, size_t bufsz, const pmcp_consumer_status *st);
int pmcp_consumer_write(const char *dir, const pmcp_consumer_status *st);
int pmcp_consumer_read(const char *dir, pmcp_consumer_status *st);

/* ---- producer (ring + owner + session glued together) ------------------ */
typedef struct pmcp_producer {
    char dir[256];
    char src[PMCP_SRC_NAME_MAX];
    pmcp_ring_map map;
    pmcp_owner owner;
    int owned;               /* acquired and not (yet) lost/released */
    int preempted;           /* lost ownership; further writes refused */
    int kind;                /* PMCP_KIND_*, owner kind taken by acquire */
    int session_open;        /* session start written, stop not yet */
    uint32_t frame_no;
    uint32_t seen_ring_gen;
    int cfg_pending;         /* re-send cached config before next frame */
    uint32_t cfg_len;
    uint64_t last_check_ms;
    uint8_t cfg[PMCP_CFG_CACHE_MAX];
} pmcp_producer;

/* dir/ring NULL = env or default. create_ring: see pmcp_ring_open. */
int pmcp_producer_init(pmcp_producer *p, const char *src, const char *dir,
                       const char *ring_path, int create_ring);
int pmcp_producer_acquire(pmcp_producer *p);              /* E_BUSY if taken */
int pmcp_producer_session_start(pmcp_producer *p);
/* OK or E_PREEMPTED (session stop already written, reason=preempted).
 * Throttled to PMCP_OWNER_CHECK_MS; call it from idle loops too, so a
 * preemption is noticed within the 100 ms budget even when no frames flow. */
int pmcp_producer_check_owner(pmcp_producer *p);
int pmcp_producer_write_config(pmcp_producer *p, const void *avcc, uint32_t size);
int pmcp_producer_write_frame(pmcp_producer *p, const void *avcc_au,
                              uint32_t size, uint64_t ntp_ts, int keyframe);
/* Proxy / supervisor mode: no ring, no frames. Owns on behalf of another
 * process that writes the ring (core.so). Use pmcp_producer_acquire() (takes
 * the owner with kind=proxy), pmcp_producer_session_start(),
 * pmcp_producer_check_owner() (on E_PREEMPTED you have
 * pmcp_owner_preempt_ms(PMCP_KIND_PROXY) to kill the writer) and
 * pmcp_producer_close(). write_config/write_frame return E_INVAL. */
int pmcp_producer_init_proxy(pmcp_producer *p, const char *src, const char *dir);
/* Session stop (if open and not yet stopped), owner release, unmap. */
void pmcp_producer_close(pmcp_producer *p, const char *reason);

#ifdef __cplusplus
}
#endif
#endif
