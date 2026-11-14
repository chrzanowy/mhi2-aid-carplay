/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * test_unit -- host test helper for the contract kit.
 * Modes (each prints "ok: ..." / "FAIL: ..." lines, exit 1 if any FAIL):
 *   unit DIR                 parser / owner / session / limits unit tests
 *   stress-writer DIR N      rewrite the consumer file N times (varying length)
 *   stress-reader DIR N      read it N times, every read must be a full line
 *   status-watch DIR SECS    consumer file must refresh ~1 Hz with all keys
 *   race DIR N               N rounds of two takers on a dead owner, one must win
 *   rawwriter RING DELAY_MS CFG STOPFILE|- MAXMS PAYLOAD   core.so-like ring writer
 *   zombie DIR SRC RING MAXMS PAYLOAD   proxy owner + writer that ignores preemption
 *   supervisor DIR SRC in|proxy HOLD_MS   owner holder without a ring
 *   deaddir DIR GEN SRC      write an owner file held by a dead pid
 *   owner-show DIR           print "src pid gen" of the owner file
 *   ring-gen RING [N]        print ring generation; with N, set it first
 */
#define _POSIX_C_SOURCE 200112L

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
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
    snprintf(line, sizeof line, "v=1 src=%s pid=%lu gen=%lu since_ms=%llu", src, pid, gen,
             (unsigned long long)pmcp_now_ms());
    pmcp_atomic_write(dir, "owner", line);
}

/* owner line with explicit since_ms (<0 = key omitted) and kind (NULL = key omitted) */
static void put_owner_x(const char *dir, const char *src, unsigned long pid, unsigned long gen,
                        long long since_ms, const char *kind)
{
    char line[200];
    int n = snprintf(line, sizeof line, "v=1 src=%s pid=%lu gen=%lu", src, pid, gen);
    if (since_ms >= 0)
        n += snprintf(line + n, sizeof line - (size_t)n, " since_ms=%lld", since_ms);
    if (kind != NULL)
        snprintf(line + n, sizeof line - (size_t)n, " kind=%s", kind);
    pmcp_atomic_write(dir, "owner", line);
}

static void rm_in(const char *dir, const char *name)
{
    char p[600];
    snprintf(p, sizeof p, "%s/%s", dir, name);
    unlink(p);
}

static pmcp_ring g_ring; /* 16 MB in BSS, for the gate tests */
static const uint8_t g_avcc[] = {1, 0x64, 0, 0x28, 0xff, 0xe1, 0, 4, 0x67, 0x64, 0, 0x28, 1, 0, 2, 0x68, 0xee};

static pid_t fork_sleeper(void)
{
    pid_t c = fork();
    if (c == 0) {
        sleep(30);
        _exit(0);
    }
    return c;
} /* 16 MB in BSS, for the gate tests */

static void run_v11(const char *dir)
{
    pmcp_owner o, mine;
    pmcp_producer pp;
    pmcp_session se;
    pmcp_consumer_gate g;
    char line[300], path[600];
    unsigned long live = (unsigned long)getppid();
    long long now = (long long)pmcp_now_ms();
    int r;

    CHECK(PMCP_MOST_CONTRACT_VERSION == 1 && PMCP_MOST_CONTRACT_REVISION == 1, "line version 1, revision 1");
    CHECK(PMCP_MOST_PREEMPT_MS == 100 && PMCP_MOST_PREEMPT_PROXY_MS == 3000
          && pmcp_owner_preempt_ms(PMCP_KIND_IN) == 100 && pmcp_owner_preempt_ms(PMCP_KIND_PROXY) == 3000,
          "preempt deadlines in=100 proxy=3000");

    /* parser: v1 line without kind = in; proxy; unknown keys */
    r = pmcp_owner_parse("v=1 src=aa pid=12 gen=3 since_ms=5", &o);
    CHECK(r == PMCP_OK && o.kind == PMCP_KIND_IN && o.since_ms == 5, "v1 owner line without kind parses as in");
    r = pmcp_owner_parse("v=1 src=wired pid=12 gen=3 since_ms=5 kind=proxy zzz=1", &o);
    CHECK(r == PMCP_OK && o.kind == PMCP_KIND_PROXY, "owner kind=proxy parses");
    r = pmcp_owner_parse("v=1 src=wired pid=12 gen=3 kind=in", &o);
    CHECK(r == PMCP_OK && o.kind == PMCP_KIND_IN && o.since_ms == 0, "owner kind=in, no since_ms tolerated");

    /* writer */
    rm_in(dir, "owner");
    r = pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine);
    snprintf(path, sizeof path, "%s/owner", dir);
    pmcp_read_line(path, line, sizeof line);
    CHECK(r == PMCP_OK && mine.kind == PMCP_KIND_IN && strstr(line, " kind=in") != NULL, "writer: default kind=in");
    pmcp_owner_release(dir, &mine);
    r = pmcp_owner_acquire_kind(dir, PMCP_SRC_WIRED, PMCP_KIND_PROXY, &mine);
    pmcp_read_line(path, line, sizeof line);
    CHECK(r == PMCP_OK && mine.kind == PMCP_KIND_PROXY && strstr(line, " kind=proxy") != NULL
          && pmcp_owner_read(dir, &o) == PMCP_OK && o.kind == PMCP_KIND_PROXY, "writer: kind=proxy round trip");
    CHECK(strlen(line) + 1 <= PMCP_MOST_LINE_MAX, "owner line <= 255 B");
    pmcp_owner_release(dir, &mine);
    CHECK(pmcp_owner_acquire_kind(dir, PMCP_SRC_AA, 7, &mine) == PMCP_E_INVAL, "bad kind refused");

    /* supervisor (proxy) mode: owns, writes the session, no frames */
    rm_in(dir, "owner");
    rm_in(dir, "wireless.session");
    r = pmcp_producer_init_proxy(&pp, PMCP_SRC_WIRELESS, dir);
    CHECK(r == PMCP_OK && pp.map.ring == NULL, "proxy init without ring");
    r = pmcp_producer_acquire(&pp);
    CHECK(r == PMCP_OK && pp.owner.kind == PMCP_KIND_PROXY, "proxy acquire takes kind=proxy");
    CHECK(pmcp_producer_session_start(&pp) == PMCP_OK
          && pmcp_session_read(dir, PMCP_SRC_WIRELESS, &se) == PMCP_OK && se.start && se.gen == pp.owner.gen,
          "proxy session start");
    CHECK(pmcp_producer_write_frame(&pp, "x", 1, 0, 1) == PMCP_E_INVAL
          && pmcp_producer_write_config(&pp, "xxxxxxxx", 8) == PMCP_E_INVAL, "proxy writes no frames");
    CHECK(pmcp_producer_check_owner(&pp) == PMCP_OK, "proxy check_owner ok");
    pmcp_producer_close(&pp, "done");
    CHECK(pmcp_owner_read(dir, &o) == PMCP_E_NOENT
          && pmcp_session_read(dir, PMCP_SRC_WIRELESS, &se) == PMCP_OK && !se.start, "proxy close: stop + owner released");

    /* stale-by-no-session (PID reuse guard) */
    rm_in(dir, "aa.session");
    rm_in(dir, "wireless.session");
    put_owner_x(dir, "wireless", live, 20, now - 5000, "proxy");
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine) == PMCP_E_BUSY, "live owner 5 s old without session: still busy");
    put_owner_x(dir, "wireless", live, 20, -1, NULL);
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine) == PMCP_E_BUSY, "live owner without since_ms: rule not applied");
    put_owner_x(dir, "wireless", live, 20, now - 11000, "proxy");
    CHECK(pmcp_owner_read(dir, &o) == PMCP_OK && pmcp_owner_is_stale(dir, &o), "owner 11 s old without session is stale");
    r = pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine);
    CHECK(r == PMCP_OK && mine.gen == 21, "stale (no session in 10 s) live owner taken over, gen+1");
    pmcp_owner_release(dir, &mine);
    put_owner_x(dir, "wireless", live, 20, now - 11000, "proxy");
    pmcp_session_write(dir, PMCP_SRC_WIRELESS, 1, 20, "start");
    CHECK(pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine) == PMCP_E_BUSY, "11 s old owner WITH session start of that gen: busy");
    pmcp_session_write(dir, PMCP_SRC_WIRELESS, 1, 19, "start");
    r = pmcp_owner_acquire(dir, PMCP_SRC_AA, &mine);
    CHECK(r == PMCP_OK && mine.gen == 21, "session with another gen does not count");
    pmcp_owner_release(dir, &mine);
    rm_in(dir, "wireless.session");

    /* consumer gate */
    {
        pmcp_owner a, b;
        uint8_t big[PMCP_CFG_CACHE_MAX + 1];
        memset(&a, 0, sizeof a);
        b = a;
        strcpy(a.src, "wired"); strcpy(b.src, "wired");
        memset(big, 1, sizeof big);
        memset(&g_ring, 0, sizeof g_ring);
        g_ring.generation = 4294967295u;
        g_ring.write_sequence = 100;
        pmcp_gate_init(&g);
        a.pid = live; a.gen = 5; a.kind = PMCP_KIND_PROXY;
        b.pid = 4242; b.gen = 6; b.kind = PMCP_KIND_IN;
        CHECK(pmcp_gate_owner(&g, &g_ring, NULL, 0) == 0, "gate: no owner file, no cut");
        CHECK(pmcp_gate_owner(&g, &g_ring, &a, 0) == 0 && g_ring.generation == 4294967295u, "gate: first observation does not cut");
        CHECK(pmcp_gate_slot(&g, 101, PMCP_RING_TYPE_FRAME, "x", 1, 0) == PMCP_GATE_PASS, "gate open passes");
        CHECK(pmcp_gate_owner(&g, &g_ring, &a, 0) == 0, "gate: same gen, no cut");
        CHECK(pmcp_gate_owner(&g, &g_ring, NULL, 0) == 0, "gate: missing owner file keeps the previous owner");
        CHECK(pmcp_gate_owner(&g, &g_ring, &b, 1000) == 1 && g_ring.generation == 1
              && g.prev_pid == live && g.prev_kind == PMCP_KIND_PROXY, "gate: gen change bumps ring generation (wrap skips 0), remembers previous owner");
        CHECK(pmcp_gate_slot(&g, 101, PMCP_RING_TYPE_FRAME, "x", 1, 1000) == PMCP_GATE_DROP
              && pmcp_gate_slot(&g, 100, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 1000) == PMCP_GATE_DROP
              && pmcp_gate_slot(&g, 102, PMCP_RING_TYPE_FRAME, "x", 1, 1000) == PMCP_GATE_DROP, "gate: frames and avcC written before/at the cut dropped");
        /* previous pid alive: avcC is held, frames dropped */
        CHECK(pmcp_gate_slot(&g, 103, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 1010) == PMCP_GATE_HELD
              && pmcp_gate_slot(&g, 104, PMCP_RING_TYPE_FRAME, "x", 1, 1020) == PMCP_GATE_DROP
              && pmcp_gate_poll(&g, 2000) == 0, "gate: new avcC held while the previous pid is alive (proxy, < 3000 ms)");
        CHECK(pmcp_gate_poll(&g, 3999) == 0 && g.forced == 0, "gate: still closed at cut+2999 ms");
        CHECK(pmcp_gate_poll(&g, 4000) == 1 && g.forced == 1 && g.open_reason == PMCP_GATE_OPEN_FORCED
              && g.cfg_len == sizeof g_avcc && g.cfg_seq == 103 && !memcmp(g.cfg, g_avcc, sizeof g_avcc)
              && pmcp_gate_slot(&g, 105, PMCP_RING_TYPE_FRAME, "x", 1, 4000) == PMCP_GATE_PASS,
              "gate: forced open at the 3000 ms deadline, forced=1, held avcC returned");
        /* in-kind previous owner: 100 ms */
        a = b; a.pid = live; a.gen = 6; a.kind = PMCP_KIND_IN;
        pmcp_gate_init(&g);
        g_ring.write_sequence = 0xFFFFFFFFu;
        pmcp_gate_owner(&g, &g_ring, &a, 0);
        b.gen = 7; b.pid = 4242;
        CHECK(pmcp_gate_owner(&g, &g_ring, &b, 50) == 1
              && pmcp_gate_slot(&g, 1, PMCP_RING_TYPE_FRAME, "x", 1, 50) == PMCP_GATE_DROP
              && pmcp_gate_slot(&g, 1, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 60) == PMCP_GATE_HELD
              && pmcp_gate_poll(&g, 149) == 0 && pmcp_gate_poll(&g, 150) == 1 && g.forced == 1,
              "gate: in-kind previous owner alive: forced at 100 ms, sequence wrap");
        /* previous pid dead: opens on the avcC itself, nothing to emit later */
        a.pid = dead_pid(); a.gen = 8;
        pmcp_gate_init(&g);
        pmcp_gate_owner(&g, &g_ring, &a, 0);
        b.gen = 9;
        CHECK(pmcp_gate_owner(&g, &g_ring, &b, 10) == 1
              && pmcp_gate_slot(&g, 2, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 10) == PMCP_GATE_PASS
              && g.forced == 0 && g.open_reason == PMCP_GATE_OPEN_EXIT, "gate: previous pid dead: opens at the new avcC, no force");
        /* previous pid dies while the avcC is held: poll opens at once */
        a.pid = (unsigned long)fork_sleeper();
        a.gen = 10;
        pmcp_gate_init(&g);
        pmcp_gate_owner(&g, &g_ring, &a, 0);
        b.gen = 11;
        pmcp_gate_owner(&g, &g_ring, &b, 0);
        CHECK(pmcp_gate_slot(&g, 3, PMCP_RING_TYPE_CONFIG, big, sizeof big, 1) == PMCP_GATE_HELD
              && g.cfg_len == 0, "gate: oversized avcC is not stored");
        pmcp_gate_slot(&g, 4, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 2);
        CHECK(pmcp_gate_poll(&g, 3) == 0, "gate: sleeper alive: held");
        kill((pid_t)a.pid, SIGKILL);
        waitpid((pid_t)a.pid, NULL, 0);
        CHECK(pmcp_gate_poll(&g, 4) == 1 && g.forced == 0 && g.cfg_seq == 4, "gate: opens right after the previous pid exits, held avcC emitted");
    }
}

/* two takers race for one dead owner, N times: exactly one must win */
static int race(const char *dir, unsigned long n)
{
    unsigned long i, bad = 0, both = 0, none = 0;
    for (i = 0; i < n; i++) {
        int gate[2], res[2], k;
        pid_t kid[2];
        unsigned long win_pid = 0;
        int wins = 0;
        pmcp_owner o;
        put_owner_x(dir, "wired", dead_pid(), i + 1, (long long)pmcp_now_ms(), NULL);
        if (pipe(gate) != 0)
            return 2;
        for (k = 0; k < 2; k++) {
            kid[k] = fork();
            if (kid[k] == 0) {
                char b;
                pmcp_owner m;
                close(gate[1]);
                if (read(gate[0], &b, 1) < 0) { /* EOF = go */ }
                _exit(pmcp_owner_acquire(dir, PMCP_SRC_AA, &m) == PMCP_OK ? 10 : 11);
            }
        }
        close(gate[0]);
        close(gate[1]);
        for (k = 0; k < 2; k++) {
            int st = 0;
            waitpid(kid[k], &st, 0);
            res[k] = WIFEXITED(st) ? WEXITSTATUS(st) : -1;
            if (res[k] == 10) {
                wins++;
                win_pid = (unsigned long)kid[k];
            }
        }
        if (wins == 2)
            both++;
        else if (wins == 0)
            none++;
        if (wins != 1 || pmcp_owner_read(dir, &o) != PMCP_OK || o.pid != win_pid)
            bad++;
    }
    CHECK(bad == 0, "race: two takers on a dead owner, exactly one winner, owner file = winner (200x)");
    if (bad)
        printf("# both=%lu none=%lu bad=%lu\n", both, none, bad);
    return g_fail ? 1 : 0;
}


/* raw ring writer like core.so: no owner file, no avcC resend on generation change.
 * rawwriter RING DELAY_MS CFG(0|1) STOPFILE|- MAXMS PAYLOAD */
static int rawwriter(const char *ring, unsigned delay, int cfg, const char *stopfile,
                     unsigned maxms, unsigned payload)
{
    pmcp_ring_map m;
    static uint8_t fr[PMCP_RING_SLOT_DATA_MAX];
    uint64_t t0;
    uint32_t fno = 0;
    struct stat sb;
    if (payload + 4u > sizeof fr || pmcp_ring_open(&m, ring, 0) != PMCP_OK)
        return 1;
    pmcp_sleep_ms(delay);
    if (cfg)
        pmcp_ring_publish(m.ring, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 0, 0, 0);
    memset(fr, 0xab, sizeof fr);
    fr[0] = (uint8_t)(payload >> 24); fr[1] = (uint8_t)(payload >> 16);
    fr[2] = (uint8_t)(payload >> 8); fr[3] = (uint8_t)payload;
    fr[4] = 0x65;
    t0 = pmcp_now_ms();
    while (pmcp_now_ms() - t0 < maxms && !(stopfile[0] != '-' && stat(stopfile, &sb) == 0)) {
        pmcp_ring_publish(m.ring, PMCP_RING_TYPE_FRAME, fr, payload + 4u, 0, ++fno, pmcp_ntp_now());
        pmcp_sleep_ms(5);
    }
    printf("event=writer-done frames=%lu\n", (unsigned long)fno);
    pmcp_ring_close(&m);
    return 0;
}

/* zombie DIR SRC RING MAXMS PAYLOAD: an old proxy writer that owns the ring as proxy and
 * never notices a preemption: keeps writing until MAXMS, then exits (its pid dies). */
static int zombie(const char *dir, const char *src, const char *ring, unsigned maxms, unsigned payload)
{
    pmcp_producer p;
    static uint8_t fr[PMCP_RING_SLOT_DATA_MAX];
    pmcp_ring_map m;
    uint64_t t0;
    uint32_t fno = 0;
    if (payload + 4u > sizeof fr || pmcp_producer_init_proxy(&p, src, dir) != PMCP_OK
        || pmcp_ring_open(&m, ring, 0) != PMCP_OK || pmcp_producer_acquire(&p) != PMCP_OK)
        return 1;
    pmcp_producer_session_start(&p);
    pmcp_ring_publish(m.ring, PMCP_RING_TYPE_CONFIG, g_avcc, sizeof g_avcc, 0, 0, 0);
    memset(fr, 0xab, sizeof fr);
    fr[0] = (uint8_t)(payload >> 24); fr[1] = (uint8_t)(payload >> 16);
    fr[2] = (uint8_t)(payload >> 8); fr[3] = (uint8_t)payload;
    fr[4] = 0x65;
    printf("event=acquired src=%s gen=%lu t=%llu\n", src, (unsigned long)p.owner.gen,
           (unsigned long long)pmcp_now_ms());
    t0 = pmcp_now_ms();
    while (pmcp_now_ms() - t0 < maxms) {
        pmcp_ring_publish(m.ring, PMCP_RING_TYPE_FRAME, fr, payload + 4u, 0, ++fno, pmcp_ntp_now());
        pmcp_sleep_ms(5);
    }
    printf("event=writer-done t=%llu\n", (unsigned long long)pmcp_now_ms());
    return 0; /* no close: the owner file stays, like a crashed writer */
}

/* supervisor DIR SRC KIND HOLD_MS : owns on behalf of a writer, never writes frames */
static int supervisor(const char *dir, const char *src, const char *kind, unsigned hold)
{
    pmcp_producer p;
    uint64_t t0;
    if (pmcp_producer_init_proxy(&p, src, dir) != PMCP_OK)
        return 1;
    p.kind = strcmp(kind, "proxy") == 0 ? PMCP_KIND_PROXY : PMCP_KIND_IN;
    if (pmcp_producer_acquire(&p) != PMCP_OK) {
        printf("event=busy\n");
        return 3;
    }
    pmcp_producer_session_start(&p);
    printf("event=acquired src=%s gen=%lu kind=%s t=%llu\n", src, (unsigned long)p.owner.gen, kind,
           (unsigned long long)pmcp_now_ms());
    t0 = pmcp_now_ms();
    while (pmcp_now_ms() - t0 < hold) {
        if (pmcp_producer_check_owner(&p) == PMCP_E_PREEMPTED) {
            printf("event=preempted t=%llu\n", (unsigned long long)pmcp_now_ms());
            pmcp_producer_close(&p, "preempted");
            return 0;
        }
        pmcp_sleep_ms(5);
    }
    pmcp_producer_close(&p, "done");
    printf("event=released\n");
    return 0;
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

    run_v11(dir);

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
    setvbuf(stdout, NULL, _IOLBF, 0);
    if (argc >= 3 && !strcmp(argv[1], "unit"))
        return run_unit(argv[2]);
    if (argc >= 4 && !strcmp(argv[1], "stress-writer"))
        return stress_writer(argv[2], strtoul(argv[3], NULL, 10));
    if (argc >= 4 && !strcmp(argv[1], "stress-reader"))
        return stress_reader(argv[2], strtoul(argv[3], NULL, 10));
    if (argc >= 4 && !strcmp(argv[1], "status-watch"))
        return status_watch(argv[2], (unsigned)atoi(argv[3]));
    if (argc >= 6 && !strcmp(argv[1], "putowner")) { /* DIR SRC PID GEN: since_ms = now, no kind */
        put_owner(argv[2], argv[3], strtoul(argv[4], NULL, 10), strtoul(argv[5], NULL, 10));
        return 0;
    }
    if (argc >= 4 && !strcmp(argv[1], "race"))
        return race(argv[2], strtoul(argv[3], NULL, 10));
    if (argc >= 8 && !strcmp(argv[1], "rawwriter"))
        return rawwriter(argv[2], (unsigned)atoi(argv[3]), atoi(argv[4]), argv[5],
                         (unsigned)atoi(argv[6]), (unsigned)atoi(argv[7]));
    if (argc >= 7 && !strcmp(argv[1], "zombie"))
        return zombie(argv[2], argv[3], argv[4], (unsigned)atoi(argv[5]), (unsigned)atoi(argv[6]));
    if (argc >= 6 && !strcmp(argv[1], "supervisor"))
        return supervisor(argv[2], argv[3], argv[4], (unsigned)atoi(argv[5]));
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
