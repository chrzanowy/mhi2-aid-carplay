/* SPDX-License-Identifier: GPL-3.0-or-later */
/* pmcp-most stage 1b: the consumer gate of contract v1.1, copied verbatim from
 * ../contract/pmcp_most_producer.c (functions pmcp_pid_alive,
 * pmcp_owner_preempt_ms and the "consumer gate" section). Only these functions
 * are linked into the bridge: the whole kit would add libc imports that are not
 * proven on the MU1161 libc (link, nanosleep, strcpy, strncpy, strtoll,
 * strtoull; ld 2.19 keeps them even with --gc-sections). The host test
 * "provenance" checks that every function here is byte-identical to the kit. */
#define _POSIX_C_SOURCE 200112L

#include <errno.h>
#include <signal.h>
#include <string.h>
#include <sys/types.h>

#include "pmcp_most_producer.h"

#if defined(__GNUC__)
#define PMCP_BARRIER() __sync_synchronize()
#else
#define PMCP_BARRIER() ((void)0)
#endif

int pmcp_pid_alive(unsigned long pid)
{
    if (pid == 0 || pid > 0x7fffffffUL)
        return 0;
    if (kill((pid_t)pid, 0) == 0)
        return 1;
    return errno != ESRCH; /* EPERM = alive, owned by someone else */
}

unsigned pmcp_owner_preempt_ms(int kind)
{
    return kind == PMCP_KIND_PROXY ? PMCP_MOST_PREEMPT_PROXY_MS : PMCP_MOST_PREEMPT_MS;
}

/* ---- consumer gate ---- */
void pmcp_gate_init(pmcp_consumer_gate *g)
{
    memset(g, 0, sizeof *g);
}

int pmcp_gate_owner(pmcp_consumer_gate *g, pmcp_ring *ring, const pmcp_owner *cur, uint64_t now_ms)
{
    uint32_t ng;
    if (cur == NULL)
        return 0;
    if (!g->have || g->owner_gen == cur->gen) {
        g->have = 1;
        g->owner_gen = cur->gen;
        g->last_pid = cur->pid;
        g->last_kind = cur->kind;
        return 0;
    }
    g->prev_pid = g->last_pid;
    g->prev_kind = g->last_kind;
    g->owner_gen = cur->gen;
    g->last_pid = cur->pid;
    g->last_kind = cur->kind;
    g->cut_seq = ring->write_sequence;
    g->cut_ms = now_ms;
    g->cut = 1;
    g->cfg_have = 0;
    g->cfg_len = 0;
    g->cuts++;
    ng = ring->generation + 1u;
    ring->generation = ng == 0 ? 1u : ng;
    PMCP_BARRIER();
    return 1;
}

/* 1 = may open now (sets open_reason, counts forced) */
static int gate_release(pmcp_consumer_gate *g, uint64_t now_ms)
{
    if (g->prev_pid == 0 || !pmcp_pid_alive(g->prev_pid)) {
        g->open_reason = PMCP_GATE_OPEN_EXIT;
        return 1;
    }
    if (now_ms - g->cut_ms >= pmcp_owner_preempt_ms(g->prev_kind)) {
        g->open_reason = PMCP_GATE_OPEN_FORCED;
        g->forced++;
        return 1;
    }
    return 0;
}

int pmcp_gate_slot(pmcp_consumer_gate *g, uint32_t seq, uint32_t type, const void *data,
                   uint32_t size, uint64_t now_ms)
{
    if (!g->cut)
        return PMCP_GATE_PASS;
    if (type != PMCP_RING_TYPE_CONFIG || (int32_t)(seq - g->cut_seq) <= 0)
        return PMCP_GATE_DROP;
    g->cfg_have = 1;
    g->cfg_seq = seq;
    if (data != NULL && size <= PMCP_CFG_CACHE_MAX) {
        memcpy(g->cfg, data, size);
        g->cfg_len = size;
    } else {
        g->cfg_len = 0;
    }
    if (gate_release(g, now_ms)) {
        g->cut = 0;
        g->cfg_have = 0;
        return PMCP_GATE_PASS; /* this very slot is the avcC */
    }
    return PMCP_GATE_HELD;
}

int pmcp_gate_poll(pmcp_consumer_gate *g, uint64_t now_ms)
{
    if (!g->cut || !g->cfg_have)
        return 0;
    if (!gate_release(g, now_ms))
        return 0;
    g->cut = 0;
    g->cfg_have = 0;
    return g->cfg_len > 0;
}
