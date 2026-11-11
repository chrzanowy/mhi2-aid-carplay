/* SPDX-License-Identifier: GPL-3.0-or-later
 * Host test of pmcp_rg.c: feeds Android Auto 1.7 navigation messages, snapshots latest.bin after each step
 * (step-N.bin) for TestAaRg.java, which reads them with tomasz-twardzicki's real MailboxReader + LiveModel. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "pmcp_rg.h"

static unsigned char m[1024];
static unsigned n;
static void var(unsigned long v) { while (v >= 0x80) { m[n++] = (unsigned char)(v | 0x80); v >>= 7; } m[n++] = (unsigned char)v; }
static void sleep_ms(int ms) { struct timespec ts = { ms / 1000, (long)(ms % 1000) * 1000000L }; nanosleep(&ts, 0); }
static void status(unsigned s) { n = 0; m[n++] = 0x80; m[n++] = 0x03; var(0x08); var(s); pmcp_rg_message(m, n); }
static void state(unsigned nt, unsigned ex, unsigned an)
{
    unsigned char man[16]; unsigned mn = 0, i, save;
    n = 0; var(0x08); var(nt); if (ex) { var(0x10); var(ex); } if (an) { var(0x18); var(an); }
    memcpy(man, m, n); mn = n;
    n = 0; m[n++] = 0x80; m[n++] = 0x06;
    var(0x0a); var(mn + 2u + 4u);            /* step: maneuver LEN + an instruction LEN with 2 bytes */
    var(0x0a); var(mn); for (i = 0; i < mn; ++i) m[n++] = man[i];
    var(0x12); var(2); m[n++] = 0x0a; m[n++] = 0x00;
    save = n; (void)save;
    pmcp_rg_message(m, n);
}
static void position(unsigned long meters)
{
    unsigned char d[16]; unsigned dn, i;
    n = 0; var(0x08); var(meters); dn = n; memcpy(d, m, dn);
    n = 0; m[n++] = 0x80; m[n++] = 0x07;
    var(0x0a); var(dn + 2u);
    var(0x0a); var(dn); for (i = 0; i < dn; ++i) m[n++] = d[i];
    pmcp_rg_message(m, n);
}

/* AA 1.1: a step with road name and lanes, a position with the destination. Byte builder: b_* write into bb. */
typedef struct { unsigned char d[512]; unsigned n; } bb;
static void b_var(bb *b, unsigned long v) { while (v >= 0x80) { b->d[b->n++] = (unsigned char)(v | 0x80); v >>= 7; } b->d[b->n++] = (unsigned char)v; }
static void b_key(bb *b, unsigned f, unsigned w) { b_var(b, (unsigned long)(f << 3 | w)); }
static void b_u(bb *b, unsigned f, unsigned long v) { b_key(b, f, 0); b_var(b, v); }
static void b_bytes(bb *b, unsigned f, const unsigned char *p, unsigned len) { b_key(b, f, 2); b_var(b, len); memcpy(b->d + b->n, p, len); b->n += len; }
static void b_sub(bb *b, unsigned f, const bb *s) { b_bytes(b, f, s->d, s->n); }
/* lanes: "1.,5*" = lane 1 straight / lane 2 normal right highlighted; ',' separates lanes, '*' = highlighted, digit = shape */
static void state_full(unsigned nt, const char *road, unsigned road_len, const char *lanes)
{
    bb man = { {0}, 0 }, step = { {0}, 0 }, top = { {0}, 0 }, ri = { {0}, 0 }, txt = { {0}, 0 };
    const char *p = lanes;
    b_u(&man, 1, nt);
    b_sub(&step, 1, &man);
    b_bytes(&txt, 1, (const unsigned char *)"x", 1); b_sub(&step, 2, &txt);
    while (p && *p) {
        bb lane = { {0}, 0 };
        while (*p && *p != ',') {
            bb dir = { {0}, 0 };
            b_u(&dir, 1, (unsigned long)(*p - '0')); p++;
            if (*p == '*') { b_u(&dir, 2, 1); p++; }
            b_sub(&lane, 1, &dir);
        }
        if (*p == ',') p++;
        b_sub(&step, 3, &lane);
    }
    if (road) { b_bytes(&ri, 1, (const unsigned char *)road, road_len); b_sub(&step, 4, &ri); }
    b_sub(&top, 1, &step);
    n = 0; m[n++] = 0x80; m[n++] = 0x06; memcpy(m + n, top.d, top.n); n += top.n;
    pmcp_rg_message(m, n);
}
static void position_full(unsigned long meters, unsigned long dest_m, unsigned long dest_s)
{
    bb sd = { {0}, 0 }, sdist = { {0}, 0 }, dd = { {0}, 0 }, ddist = { {0}, 0 }, top = { {0}, 0 };
    b_u(&sdist, 1, meters); b_bytes(&sdist, 2, (const unsigned char *)"1", 1); b_u(&sdist, 3, 1);
    b_sub(&sd, 1, &sdist);
    b_u(&ddist, 1, dest_m); b_bytes(&ddist, 2, (const unsigned char *)"12", 2); b_u(&ddist, 3, 2);
    b_sub(&dd, 1, &ddist); b_bytes(&dd, 2, (const unsigned char *)"16:25", 5); b_u(&dd, 3, dest_s);
    b_sub(&top, 1, &sd); b_sub(&top, 2, &dd);
    n = 0; m[n++] = 0x80; m[n++] = 0x07; memcpy(m + n, top.d, top.n); n += top.n;
    pmcp_rg_message(m, n);
}
static int step;
static void snap(const char *dir)
{
    char a[256], b[256], cmd[600];
    sleep_ms(400);
    snprintf(a, sizeof a, "%s/latest.bin", dir);
    snprintf(b, sizeof b, "%s/step-%d.bin", dir, step++);
    snprintf(cmd, sizeof cmd, "cp '%s' '%s'", a, b);
    if (system(cmd) != 0) printf("copy failed\n");
}
int main(void)
{
    const char *dir = getenv("GAL_PMCP_RG_DIR");
    int t, j, side, a, ha, fails = 0;
    /* mapping spot checks */
#define MAP(nt, ex, an, et, ej, es, ea, eh) do { int r = pmcp_rg_map(nt, ex, an, &t, &j, &side, &a, &ha); \
    if (!r || t != et || j != ej || side != es || a != ea || ha != eh) { printf("FAILED map %d -> %d %d %d %d %d\n", nt, t, j, side, a, ha); fails++; } \
    else printf("ok     map %d -> iAP2 %d\n", nt, t); } while (0)
    MAP(7, 0, 0, 1, 0, 0, 0, 0);       /* normal left */
    MAP(8, 0, 0, 2, 0, 0, 0, 0);
    MAP(36, 0, 0, 3, 0, 0, 0, 0);
    MAP(11, 0, 0, 4, 0, 0, -180, 1);
    MAP(34, 2, 90, 29, 1, 0, 90, 1);   /* CCW enter-and-exit, 2nd exit, 90 deg -> right */
    MAP(32, 3, 270, 30, 1, 1, 90, 1);  /* CW */
    MAP(34, 0, 0, 6, 1, 0, 0, 0);      /* no exit number: enter roundabout */
    MAP(45, 0, 0, 6, 1, 0, 0, 0);
    MAP(46, 0, 0, 7, 1, 0, 0, 0);
    MAP(41, 0, 0, 24, 0, 0, 0, 0);
    if (pmcp_rg_map(30, 0, 0, &t, &j, &side, &a, &ha) || pmcp_rg_map(0, 0, 0, &t, &j, &side, &a, &ha) ||
        pmcp_rg_map(99, 0, 0, &t, &j, &side, &a, &ha)) { printf("FAILED unknown types mapped\n"); fails++; }
    /* run_rg_test.sh: GAL_PMCP_RG_STALE_MS=3000, GAL_PMCP_RG_END_MS=9000 */
    status(1); snap(dir);                       /* 0 baseline */
    state(7, 0, 0); snap(dir);                  /* 1 left, no distance yet */
    position(250); snap(dir);                   /* 2 250 m */
    state(7, 0, 0); position(250); snap(dir);   /* 3 same step again: no new manoeuvre */
    state(34, 2, 90); position(80); snap(dir);  /* 4 roundabout 2nd exit, right */
    state(30, 0, 0); position(900); snap(dir);  /* 5 unknown type + distance: no arrow, 900 m not on the roundabout (M2) */
    state(8, 0, 0); position(120); snap(dir);   /* 6 right 120 m */
    sleep_ms(1200); position(110); snap(dir);   /* 7 the phone still navigates */
    sleep_ms(1300); position(110); sleep_ms(1300); position(110); snap(dir);   /* 8 route event repeated (5 s rule) */
    sleep_ms(3500); snap(dir);                  /* 9 phone silent > 3 s: repeats stop (M1) */
    sleep_ms(2600); snap(dir);                  /* 10 still silent: no new route event */
    position(100); snap(dir);                   /* 11 the phone again: resumes, 100 m */
    sleep_ms(9500); snap(dir);                  /* 12 silent > 9 s: route ended */
    status(1); state(7, 0, 0); position(300); snap(dir);   /* 13 a new route after the silent end */
    status(2); snap(dir);                       /* 14 route ended */
    /* AA 1.1 (A171): road, lanes, destination */
    status(1); state_full(8, "Wojciecha Cybulskiego", 21, "1,1,5*"); position_full(150, 12000, 900); snap(dir);  /* 15 */
    state_full(8, "Wojciecha Cybulskiego", 21, ""); position_full(140, 11990, 890); snap(dir);     /* 16 lanes gone */
    state_full(8, "Jedno\xc5\x9b" "ci Narodowej", 19, "1*2,1*"); snap(dir);                        /* 17 same turn, new road + lanes */
    state_full(7, "Bad\xff", 4, "8*,1"); position_full(90, 11900, 880); snap(dir);                /* 18 new step, bad UTF-8 road */
    position_full(80, 11800, 870); snap(dir);                                                      /* 19 */
    state_full(36, "Pomorska", 8, "0,0"); position_full(500, 11000, 800); snap(dir);               /* 20 lanes with no direction */
    status(2); snap(dir);                                                                          /* 21 ended */
    sleep_ms(1100);
    printf("FAILED CHECKS C: %d\n", fails);
    return fails ? 1 : 0;
}
