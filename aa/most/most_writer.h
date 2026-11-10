/*
 * most_writer: opens the AID video channel /dev/mlb/isoTX2 as altscreen-most-bridge does and writes the TS of a
 * ts_mux in whole 12032-byte blocks from its own thread.
 *
 * Device contract (bridge-spike CONTRACT.md section 2, checked in the bridge binary):
 *   open(dev, O_WRONLY | O_NONBLOCK);
 *   devctl 0x4004050c, 0x4004050d, 0x40040510: 4-byte read-backs (interface, packet size, block count), logged only;
 *   devctl 0x40040506: queue flush, status logged only (ENOTTY on MU1440);
 *   devctl 0x80040509 with u32 64: start, 64 packets per block; any status other than 0 = no MOST;
 *   then back-to-back write() of 12032-byte blocks, paced only by the driver (EAGAIN or a blocking write).
 *   There is no stop devctl: close(fd).
 *
 * Wait strategies when the driver is full (PMCP_AA_MOST_WAIT):
 *   auto  (default) O_NONBLOCK; on EAGAIN poll(POLLOUT) for up to 2 ms, falling back to a 1 ms sleep for the
 *         rest of the session once poll proves useless (3 "ready" answers in a row that were still EAGAIN, or an
 *         error), the way harman-f's opt-in poll path does;
 *   poll  O_NONBLOCK, poll only;  sleep  O_NONBLOCK, 1 ms sleep (what the bridge does);
 *   block open without O_NONBLOCK: write() blocks in the driver.
 * Errors: a positive short write and any errno other than EAGAIN/EINTR stop the writer (the caller gives MOST
 * back); so does a block that stays unwritten (EAGAIN) for stall_ms.
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef PMCP_MOST_WRITER_H
#define PMCP_MOST_WRITER_H

#include <pthread.h>
#include <stdint.h>

#include "ts_mux.h"

#define MOST_DCMD_FLUSH      0x40040506u
#define MOST_DCMD_START      0x80040509u
#define MOST_DCMD_INTERFACE  0x4004050cu
#define MOST_DCMD_PACKETSIZE 0x4004050du
#define MOST_DCMD_BLOCKCOUNT 0x40040510u
#define MOST_HIST_N          6u

typedef enum { MOST_WAIT_AUTO = 0, MOST_WAIT_POLL, MOST_WAIT_SLEEP, MOST_WAIT_BLOCK } most_wait_t;

typedef struct {
    const char *dev;
    most_wait_t wait;
    unsigned stall_ms;        /* a block not accepted for this long (EAGAIN) = error */
    unsigned first_sleep_us;  /* v12 (sleep path): the first EAGAIN after an accepted block sleeps until this long after
                                 that accept (the driver takes one block per ~7.9 ms at 12.2 Mbit/s), then 1 ms steps;
                                 0 = 1 ms steps only (v11) */
} most_cfg_t;

typedef struct {
    int open_errno;
    int iface_rc, packet_rc, block_rc, flush_rc, start_rc;
    uint32_t iface, packet_size, block_count;
} most_devinfo_t;

typedef struct {
    uint64_t blocks, bytes, eagain, polls, poll_ready_false, sleeps, short_writes, slow_writes;
    uint64_t long_sleeps;                    /* v12: first sleeps sized to the block time */
    uint64_t hist[MOST_HIST_N];              /* write time: <5, <10, <30, <50, <100, >=100 ms (the bridge's buckets) */
    uint64_t write_us_max, write_us_sum, write_us_last;
    uint64_t first_block_us;                 /* first accepted block, us after the start devctl */
    uint64_t in_write_since;                 /* monotonic us when the current write began, 0 = not writing */
    int poll_off;                            /* auto: poll found useless, sleeping instead */
    int failed, fail_errno, done;
    char fail_what[64];
} most_stats_t;

typedef struct {
    most_cfg_t cfg;
    int fd;
    int thread_on;
    volatile int stop;
    pthread_t th;
    pthread_mutex_t lock;
    ts_mux_t *mux;
    most_devinfo_t dev;
    most_stats_t st;
    uint64_t t_start_us;
} most_writer_t;

uint64_t most_now_us(void);
/* Opens the device and runs the devctl sequence. 0 = started; -1 = no MOST (fd closed, dev says why). */
int most_open(most_writer_t *w, const most_cfg_t *cfg);
/* Starts the writer thread on mux. 0 = ok. */
int most_start(most_writer_t *w, ts_mux_t *mux);
/* Lets the queue drain for up to drain_ms, stops the thread (waits up to 1 s) and closes the device. */
void most_stop(most_writer_t *w, unsigned drain_ms);
void most_snapshot(most_writer_t *w, most_stats_t *out);
/* How long the current write has been running (0 = none), for the caller's watchdog. */
uint64_t most_write_age_us(most_writer_t *w, uint64_t now);
/* Last resort for a write stuck in the driver: "flush(0)\n" to the debug node, as the supervisor does. */
void most_debug_flush(const char *debug_dev);
const char *most_wait_name(most_wait_t w);

#endif
