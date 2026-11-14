/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * test_unit -- host test helper for the contract kit.
 * Modes (each prints "ok: ..." / "FAIL: ..." lines, exit 1 if any FAIL):
 *   unit DIR                 parser / owner / session / limits unit tests
 *   stress-writer DIR N      rewrite the consumer file N times (varying length)
 *   stress-reader DIR N      read it N times, every read must be a full line
 *   status-watch DIR SECS    consumer file must refresh ~1 Hz with all keys
 *   deaddir DIR GEN SRC      write an owner file held by a dead pid
 *   owner-show DIR           print "src pid gen" of the owner file
 *   ring-gen RING [N]        print ring generation; with N, set it first
 */
#define _POSIX_C_SOURCE 200112L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "pmcp_most_producer.h"

static int g_fail;

#define CHECK(cond, name) do { \
    if (cond) printf("ok: %s\n", name); \
    else { printf("FAIL: %s (line %d)\n", name, __LINE__); g_fail++; } \
} while (0)

static unsigned long dead_pid(void)
{
    pid_t c = fork();
    if (c == 0)
        _exit(0);
    waitpid(c, NULL, 0);
    return (unsigned long)c;
}

static void put_owner(const char *dir, const char *src, unsigned long pid, unsigned long gen)
{
    char line[200];
    snprintf(line, sizeof line, "v=1 src=%s pid=%lu gen=%lu since_ms=5", src, pid, gen);
    pmcp_atomic_write(dir, "owner", line);
}

static int run_unit(const char *dir)
{
    pmcp_consumer_status st;
    pmcp_owner o, mine;
    pmcp_session se;
    char line[400];
    unsigned long live = (unsigned long)getppid();
    int r;

    /* layout */
    CHECK(sizeof(pmcp_ring_slot) == 0x4001c && sizeof(pmcp_ring) == 0x1000710, "layout sizes");

    /* parser: unknown keys ignored, known read */
    r = pmcp_consumer_parse("v=1 ready=1 zzz=5 pid=7 owner_gen=2 ring_gen=3 seq=4 frames=5 drops=6 "
                            "overruns=7 latency_resets=8 age_ms=9 queue_pkts=10 queue_hi=11 "
                            "reclaims=12 most_errno=-2 up_ms=13 future_key=abc", &st);
    CHECK(r == PMCP_OK && st.present == PMCP_CS_ALL && st.ready == 1 && st.most_errno == -2
          && st.frames == 5 && st.up_ms == 13 && st.queue_hi == 11, "consumer parse all keys, unknown ignored");
    r = pmcp_consumer_parse("v=1 ready=0 seq=9 extra=1", &st);
    CHECK(r == PMCP_OK && st.present == (PMCP_CS_READY | PMCP_CS_SEQ) && st.seq == 9,
          "consumer parse partial line");
    CHECK(pmcp_consumer_parse("v=2 ready=1", &st) == PMCP_E_VERSION, "consumer v=2 rejected");
    CHECK(pmcp_consumer_parse("ready=1", &st) == PMCP_E_PARSE, "consumer without v rejected");
    CHECK(pmcp_consumer_parse("v=1 frames=abc", &st) == PMCP_E_PARSE, "consumer bad value rejected");
    r = pmcp_owner_parse("v=1 src=aa pid=12 gen=3 since_ms=9 newkey=x another=1", &o);
    CHECK(r == PMCP_OK && !strcmp(o.src, "aa") && o.pid == 12 && o.gen == 3, "owner parse unknown keys ignored");
    CHECK(pmcp_owner_parse("v=1 src=bogus pid=1 gen=1", &o) == PMCP_E_PARSE, "owner bad src rejected");

    /* worst-case status line stays within 255 B */
    memset(&st, 0xff, sizeof st);
    st.ready = 1; st.most_errno = -2147483647 - 1; st.pid = 2147483647UL;
    r = pmcp_consumer_format(line, sizeof line, &st);
    CHECK(r > 0 && r + 1 <= PMCP_MOST_LINE_MAX, "worst-case consumer line <= 255 B");
    CHECK(pmcp_atomic_write(dir, "toolong",
        "v=1 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") == PMCP_E_TOOBIG,
        "line > 255 B refused by writer");

    /* owner: missing -> gen 1 */
    {
        char p[600];
        snprintf(p, sizeof p, "%s/owner", dir);
        unlink(p);
    }
    r = pmcp_owner_acquire(dir, PMCP_SRC_WIRELESS, &mine);
    CHECK(r == PMCP_OK && mine.gen == 1 && mine.pid == (unsigned long)getpid(), "acquire with no owner => gen 1");
    CHECK(pmcp_owner_check(dir, &mine) == PMCP_OK, "check own owner ok");
    {
        pmcp_owner again;
        CHECK(pmcp_owner_acquire(dir, PMCP_SRC_WIRELESS, &again) == PMCP_OK && again.gen == 1,
              "re-acquire by same pid/src is idempotent");
    }
    CHECK(pmcp_owner_release(dir, &mine) == PMCP_OK && pmcp_owner_read(dir, &o) == PMCP_E_NOENT,
          "release removes owner");

    /* live other owner: busy, except wired over wireless */
    put_owner(dir, "wireless", live, 7);
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine) == PMCP_E_BUSY, "live owner blocks aa");
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_WIRELESS, &mine) == PMCP_E_BUSY, "live wireless blocks wireless");
    r = pmcp_owner_acquire(dir, PMCP_SRC_WIRED, &mine);
    CHECK(r == PMCP_OK && mine.gen == 8, "wired preempts live wireless, gen+1");
    put_owner(dir, "wired", live, 3);
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_WIRELESS, &mine) == PMCP_E_BUSY, "wireless cannot take live wired");
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_WIRED, &mine) == PMCP_E_BUSY, "wired cannot take live wired");

    /* dead pid takeover, gen wrap skips 0 */
    put_owner(dir, "wired", dead_pid(), 4294967295UL);
    r = pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine);
    CHECK(r == PMCP_OK && mine.gen == 1, "dead owner taken over, gen wraps 0xFFFFFFFF -> 1 (0 skipped)");
    put_owner(dir, "aa", dead_pid(), 41);
    r = pmcp_owner_acquire(dir, PMCP_SRC_WIRELESS, &mine);
    CHECK(r == PMCP_OK && mine.gen == 42, "dead owner taken over, gen+1");

    /* preemption seen by old owner; release only if mine */
    {
        pmcp_owner old = mine, thief;
        put_owner(dir, "wired", live, old.gen + 1);
        CHECK(pmcp_owner_check(dir, &old) == PMCP_E_PREEMPTED, "check detects other pid/gen");
        CHECK(pmcp_owner_release(dir, &old) == PMCP_E_PREEMPTED && pmcp_owner_read(dir, &thief) == PMCP_OK
              && thief.gen == old.gen + 1, "release leaves a foreign owner untouched");
    }
    {
        char p[600];
        snprintf(p, sizeof p, "%s/owner", dir);
        pmcp_atomic_write(dir, "owner", "garbage not a contract line");
        r = pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine);
        CHECK(r == PMCP_OK && mine.gen == 1, "unparsable owner counts as stale");
        unlink(p);
    }

    /* session roundtrip */
    CHECK(pmcp_session_write(dir, PMCP_SRC_WIRELESS, 0, 5, "preempted") == PMCP_OK, "session write");
    r = pmcp_session_read(dir, PMCP_SRC_WIRELESS, &se);
    CHECK(r == PMCP_OK && se.start == 0 && se.gen == 5 && !strcmp(se.reason, "preempted")
          && se.pid == (unsigned long)getpid(), "session read back");
    CHECK(pmcp_session_write(dir, PMCP_SRC_WIRELESS, 1, 5, "Bad Reason") == PMCP_E_INVAL, "session reason must be a word");

    /* IDR marker */
    {
        char p[600];
        snprintf(p, sizeof p, "%s/idr.marker", dir);
        CHECK(pmcp_idr_poll_consume(p) == 0, "idr: no marker => 0");
        pmcp_idr_request(p);
        CHECK(pmcp_idr_poll_consume(p) == 1 && pmcp_idr_poll_consume(p) == 0, "idr: consumed exactly once");
    }
    return g_fail ? 1 : 0;
}

static int fill_status(pmcp_consumer_status *st, unsigned long i)
{
    memset(st, 0, sizeof *st);
    st->ready = 1;
    st->pid = 4242;
    st->owner_gen = (uint32_t)i;
    st->ring_gen = (uint32_t)i;
    st->seq = (uint32_t)i;
    st->frames = st->drops = st->overruns = (uint32_t)i;
    st->latency_resets = st->age_ms = st->queue_pkts = st->queue_hi = (uint32_t)i;
    st->reclaims = (uint32_t)i;
    st->up_ms = (uint32_t)i;
    st->most_errno = -(int)(i % 100);
    return 0;
}

static int stress_writer(const char *dir, unsigned long n)
{
    unsigned long i;
    pmcp_consumer_status st;
    for (i = 1; i <= n; i++) {
        /* vary the line length: digits count grows/shrinks with i */
        fill_status(&st, (i * 7919u) % 1000000u);
        if (pmcp_consumer_write(dir, &st) != PMCP_OK) {
            printf("FAIL: writer error at %lu\n", i);
            return 1;
        }
    }
    return 0;
}

static int stress_reader(const char *dir, unsigned long n)
{
    unsigned long i, ok = 0, bad = 0, missing = 0;
    pmcp_consumer_status st;
    for (i = 0; i < n; i++) {
        int r = pmcp_consumer_read(dir, &st);
        if (r == PMCP_E_NOENT) {
            missing++; /* only before the first write */
            continue;
        }
        if (r != PMCP_OK || st.present != PMCP_CS_ALL || st.frames != st.drops
            || st.frames != st.overruns || st.seq != st.up_ms || st.seq != st.ring_gen)
            bad++;
        else
            ok++;
    }
    printf("%s: stress reader reads=%lu good=%lu bad=%lu not-yet-existing=%lu\n",
           (bad == 0 && ok > 0) ? "ok" : "FAIL", n, ok, bad, missing);
    return (bad == 0 && ok > 0) ? 0 : 1;
}

static int status_watch(const char *dir, unsigned secs)
{
    uint64_t t0 = pmcp_now_ms(), last_change = 0;
    uint32_t last_up = 0;
    int have = 0, changes = 0, allkeys = 1, spacing_ok = 1, ready_seen = 0;
    while (pmcp_now_ms() - t0 < (uint64_t)secs * 1000u) {
        pmcp_consumer_status st;
        if (pmcp_consumer_read(dir, &st) == PMCP_OK) {
            if (st.present != PMCP_CS_ALL)
                allkeys = 0;
            if (st.ready)
                ready_seen = 1;
            if (!have || st.up_ms != last_up) {
                uint64_t now = pmcp_now_ms();
                if (have) {
                    unsigned d = st.up_ms - last_up;
                    changes++;
                    if (d < PMCP_MOST_REFRESH_MS - PMCP_MOST_REFRESH_TOL_MS
                        || d > PMCP_MOST_REFRESH_MS + PMCP_MOST_REFRESH_TOL_MS)
                        spacing_ok = 0;
                    (void)last_change;
                }
                have = 1;
                last_up = st.up_ms;
                last_change = now;
            }
        }
        pmcp_sleep_ms(5);
    }
    CHECK(have && ready_seen, "status file present and ready=1");
    CHECK(allkeys, "status has every contract key");
    CHECK(changes >= 2, "status refreshed at least twice");
    CHECK(spacing_ok, "status refresh interval 1000 ms +-100 (up_ms deltas)");
    return g_fail ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc >= 3 && !strcmp(argv[1], "unit"))
        return run_unit(argv[2]);
    if (argc >= 4 && !strcmp(argv[1], "stress-writer"))
        return stress_writer(argv[2], strtoul(argv[3], NULL, 10));
    if (argc >= 4 && !strcmp(argv[1], "stress-reader"))
        return stress_reader(argv[2], strtoul(argv[3], NULL, 10));
    if (argc >= 4 && !strcmp(argv[1], "status-watch"))
        return status_watch(argv[2], (unsigned)atoi(argv[3]));
    if (argc >= 5 && !strcmp(argv[1], "deaddir")) {
        put_owner(argv[2], argv[4], dead_pid(), strtoul(argv[3], NULL, 10));
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "owner-show")) {
        pmcp_owner o;
        if (pmcp_owner_read(argv[2], &o) != PMCP_OK)
            return 1;
        printf("%s %lu %lu\n", o.src, o.pid, (unsigned long)o.gen);
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "ring-gen")) {
        pmcp_ring_map m;
        if (pmcp_ring_open(&m, argv[2], 0) != PMCP_OK)
            return 1;
        if (argc >= 4)
            m.ring->generation = (uint32_t)strtoul(argv[3], NULL, 10);
        printf("%lu\n", (unsigned long)m.ring->generation);
        pmcp_ring_close(&m);
        return 0;
    }
    fprintf(stderr, "usage: see header comment\n");
    return 2;
}
