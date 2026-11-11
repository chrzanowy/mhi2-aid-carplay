/* SPDX-License-Identifier: GPL-3.0-or-later
 * pmcp (AA gamma): Android Auto 1.7 navigation -> the RAM mailbox the rg route guidance Java package reads.
 *
 * Google Maps at protocol 1.6+ sends 0x8006 NavigationState (the next step: NavigationType, roundabout exit number,
 * angle), 0x8007 NavigationCurrentPosition (metres to that step) and 0x8003 NavigationStatus. Here they become the
 * synthetic iAP2 route guidance events tomasz-twardzicki's rg bridge decodes (LiveModel.java, MailboxReader.java,
 * upstream/tomasz 024dd159 MU1427/route-guidance): 0x5202 manoeuvre {components [0x10], index, type, side, junction,
 * angle} and 0x5201 route {components [0x10], state, order [index], manoeuvre distance}.
 * AA 1.1 (experimental, A171): also the road name (0x8006 step.road_info.road_names[0] -> 0x5201 key 3), the lanes
 * (step.lanes -> 0x5204 {components, index, lane {position, status, angle..., highlight}} with 0x5201 keys 16/18),
 * and the destination's distance and time (0x8007 dest.distance.meters / dest.time_to_arrival_seconds -> 0x5201
 * keys 7 / 6). Field numbers: kkrvch mib-std2-kombibridge navproto.h (open-android-auto schema), confirmed by the
 * raw dump of 2026-11-11 (A167). Whether the cockpit shows them is decided by rg (hidden while the AID shows the AA
 * map: Google Maps draws them there itself). A road name that is not strict UTF-8 is sent empty, as LiveModel would
 * reject the whole snapshot.
 *
 * Files (own directory, never the CarPlay reader's /ramdisk/carplay-route-guidance):
 *   GAL_PMCP_RG_DIR (default /ramdisk/pmcp-aa-rg)/latest.bin  RGM1 mailbox, kind 1 snapshot of an RGI1 image, written
 *                                                             tmp + rename; heartbeat (serial + 1, same bytes) every
 *                                                             0.5 s, the route event again every 2.5 s while guiding
 *                                                             and the phone still sends navigation
 * Liveness (review 2026-11-03, M1): the route event is repeated only while 0x8006/0x8007 arrived within
 * GAL_PMCP_RG_STALE_MS (default 10 s). Without them the repeats stop, so the bridge releases the arrow within 5 s
 * (a crashed Maps, navigation moved to another app); the next 0x8006/0x8007 brings it back. After
 * GAL_PMCP_RG_END_MS (default 60 s) of silence the route is ended (state 0), as on 0x8003 inactive.
 * Unknown NavigationType (M2): a new step index with no manoeuvre, so a following distance never lands on the
 * previous arrow.
 *   GAL_PMCP_RG_STATUS (default /ramdisk/pmcp-aa-rg.txt)      counters and the last manoeuvres, for pmcp aa-status
 *   GAL_PMCP_RG_RAW (default /ramdisk/pmcp-aa-rg-raw.txt, "0" = off)  experimental (A165): the navigation messages as a
 *                                                             protobuf tree, one line each (0x8006 when it changes,
 *                                                             0x8003 always, 0x8007 at most every 5 s), to see which
 *                                                             fields (road, lanes, destination/ETA) Google Maps sends;
 *                                                             at 64 KB the file becomes <file>.1 (2 x 64 KB at most)
 * Only when GAL_PMCP_RG=1. pmcp_rg_message() runs on gal's reader thread and only copies values under a mutex; all
 * file work is on this module's own thread.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "pmcp_rg.h"

#define RG_SNAP     33088u
#define RG_SLOTS    16u
#define RG_EV_MAX   1024u
#define RG_LAST     5u
#define RG_UNK      8u
#define RG_ROAD_MAX 200u              /* bytes; LiveModel takes 256, RoadName shows 75 */
#define RG_LANES    16u               /* LiveModel's limit */
#define RG_LANE_DIRS 6u               /* directions kept per lane (16 lanes stay inside RG_EV_MAX) */

typedef struct { uint32_t seq; uint16_t id, len; uint8_t d[RG_EV_MAX]; } rg_ev;

static pthread_mutex_t g_m = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cv = PTHREAD_COND_INITIALIZER;
static int g_on = -1, g_started;
static char g_dir[128], g_status[128];
static rg_ev g_ring[RG_SLOTS];
static uint32_t g_seq, g_session, g_life_s, g_life_ns, g_serial;
static uint64_t g_nonce;
static int g_dirty;                   /* a new event since the last write */
static int g_guiding;                 /* 0x8003 active */
static int g_state_sent;              /* the bridge has seen route state 1 (it caches manoeuvres only then) */
static unsigned g_index;              /* current manoeuvre index, 0 = none */
static int g_cur_t = -1, g_cur_j, g_cur_side, g_cur_a, g_cur_has_a;
static long g_meters = -1;
static uint64_t g_route_ms;           /* last 0x5201 */
static unsigned long g_n3, g_n6, g_n7, g_known, g_unknown, g_events, g_writes, g_werr;
static unsigned g_unk[RG_UNK], g_unk_n;
static char g_last[RG_LAST][96];
static unsigned g_last_n;
static uint64_t g_t0;
static uint64_t g_nav_ms;             /* last 0x8006 / 0x8007 */
static unsigned g_stale_ms = 10000u, g_end_ms = 60000u;
static int g_paused;                  /* route repeats stopped: no navigation from the phone */
static unsigned long g_pauses, g_silent_ends;
static unsigned g_unk_last;           /* NavigationType of the current unknown step (g_cur_t == -1) */

/* AA 1.1: road, lanes and destination of the current step */
typedef struct { unsigned n; uint8_t shape[RG_LANE_DIRS], hl[RG_LANE_DIRS]; } rg_lane;
static char g_road[RG_ROAD_MAX + 1u];
static unsigned g_road_len;
static rg_lane g_lanes[RG_LANES];
static unsigned g_lane_n;
static long g_dest_m = -1, g_dest_s = -1;
static unsigned long g_lane_events, g_road_bad;
/* raw navigation dump (A165): copies queued on gal's reader thread, formatted and written on the writer thread */
#define RAW_SLOTS   16u
#define RAW_MSG_MAX 1024u
#define RAW_FILE_MAX 65536L
typedef struct { uint64_t t; unsigned id, len, full; uint8_t d[RAW_MSG_MAX]; } raw_msg;
static raw_msg g_raw[RAW_SLOTS];
static unsigned g_raw_head, g_raw_n;
static unsigned long g_raw_lines, g_raw_dropped, g_raw_same;
static char g_raw_path[128];
static uint8_t g_raw_last6[RAW_MSG_MAX];
static unsigned g_raw_last6_len;
static uint64_t g_raw_last7_ms;

static uint64_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}
static void le32(uint8_t *p, uint32_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24); }
static void le16(uint8_t *p, unsigned v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

/* ---- protobuf reader (bounded) ---- */
typedef struct { const uint8_t *p, *e; } pb;
static uint64_t pb_var(pb *s)
{
    uint64_t v = 0; int sh = 0;
    while (s->p < s->e) {
        uint8_t b = *s->p++;
        if (sh < 64) v |= (uint64_t)(b & 0x7fu) << sh;
        if (!(b & 0x80u)) break;
        sh += 7;
    }
    return v;
}
static int pb_tag(pb *s, unsigned *f, unsigned *w)
{
    uint64_t t;
    if (s->p >= s->e) return 0;
    t = pb_var(s);
    if (t == 0) return 0;
    *f = (unsigned)(t >> 3); *w = (unsigned)(t & 7u);
    return 1;
}
static int pb_sub(pb *s, pb *d)
{
    uint64_t n = pb_var(s);
    if (n > (uint64_t)(s->e - s->p)) { s->p = s->e; return 0; }
    d->p = s->p; d->e = s->p + n; s->p += n;
    return 1;
}
static void pb_skip(pb *s, unsigned w)
{
    pb d;
    if (w == 0u) (void)pb_var(s);
    else if (w == 2u) (void)pb_sub(s, &d);
    else if (w == 1u) s->p = (s->e - s->p >= 8) ? s->p + 8 : s->e;
    else if (w == 5u) s->p = (s->e - s->p >= 4) ? s->p + 4 : s->e;
    else s->p = s->e;
}

/* ---- TLV writer (iAP2, big-endian) ---- */
typedef struct { uint8_t *b; unsigned n, cap; int full; } tw;
static void tlv(tw *o, unsigned key, const uint8_t *v, unsigned len)
{
    if (o->n + 4u + len > o->cap) { o->full = 1; return; }
    o->b[o->n] = (uint8_t)((len + 4u) >> 8); o->b[o->n + 1] = (uint8_t)(len + 4u);
    o->b[o->n + 2] = (uint8_t)(key >> 8); o->b[o->n + 3] = (uint8_t)key;
    memcpy(o->b + o->n + 4, v, len);
    o->n += 4u + len;
}
static void tlv_u(tw *o, unsigned key, uint32_t v, unsigned width)
{
    uint8_t b[4]; unsigned i;
    for (i = 0; i < width; ++i) b[i] = (uint8_t)(v >> (8u * (width - 1u - i)));
    tlv(o, key, b, width);
}

static void push_event(unsigned id, const tw *o)
{
    rg_ev *e;
    if (o->full) return;
    g_seq++;
    e = &g_ring[(g_seq - 1u) & (RG_SLOTS - 1u)];
    e->seq = g_seq; e->id = (uint16_t)id; e->len = (uint16_t)o->n;
    memcpy(e->d, o->b, o->n);
    g_events++;
    g_dirty = 1;
}

static void route_event(int state)
{
    static uint8_t b[RG_EV_MAX];                 /* static: callers hold g_m; keeps gal's thread stack small */
    tw o = { b, 0, sizeof b, 0 };
    tlv_u(&o, 0, 0x10, 2);
    tlv_u(&o, 1, (uint32_t)state, 1);
    g_state_sent = state == 1;
    if (state == 1 && g_index) {
        tlv(&o, 3, (const uint8_t *)g_road, g_road_len);          /* always: an empty road clears the old one */
        if (g_dest_s >= 0) {
            uint8_t s8[8] = { 0, 0, 0, 0, 0, 0, 0, 0 };
            uint32_t v = (uint32_t)g_dest_s;
            s8[4] = (uint8_t)(v >> 24); s8[5] = (uint8_t)(v >> 16); s8[6] = (uint8_t)(v >> 8); s8[7] = (uint8_t)v;
            tlv(&o, 6, s8, 8);
        }
        if (g_dest_m >= 0) tlv_u(&o, 7, (uint32_t)g_dest_m, 4);
        tlv_u(&o, 13, g_index, 2);
        if (g_meters >= 0) tlv_u(&o, 10, (uint32_t)g_meters, 4);
        tlv_u(&o, 16, g_index, 2);
        tlv_u(&o, 18, g_lane_n ? 1u : 0u, 1);
    }
    push_event(0x5201, &o);
    g_route_ms = now_ms();
}

/* AA LaneDirection.shape -> iAP2 lane angle (degrees, negative = left); 0x7fff = unknown, not sent */
static int lane_angle(unsigned shape)
{
    static const short a[10] = { 0x7fff, 0, -45, 45, -90, 90, -135, 135, -180, 179 };   /* 179: rg (uturn.py) reads exactly 180 as a left U-turn */
    return shape < 10u ? a[shape] : 0x7fff;
}

/* 0x5204 lane guidance for the current index: one nested lane per AA lane, left to right */
static void lane_event(void)
{
    static uint8_t b[RG_EV_MAX];                 /* static: callers hold g_m; keeps gal's thread stack small */
    tw o = { b, 0, sizeof b, 0 };
    unsigned i, k;
    tlv_u(&o, 0, 0x10, 2);
    tlv_u(&o, 1, g_index, 2);
    for (i = 0; i < g_lane_n; ++i) {
        static uint8_t lb[128];
        tw l = { lb, 0, sizeof lb, 0 };
        int hi = 0x7fff;
        for (k = 0; k < g_lanes[i].n; ++k) if (g_lanes[i].hl[k] && lane_angle(g_lanes[i].shape[k]) != 0x7fff) { hi = lane_angle(g_lanes[i].shape[k]); break; }
        tlv_u(&l, 0, i, 2);
        tlv_u(&l, 1, hi != 0x7fff ? 2u : 0u, 1);                 /* 2 preferred (highlighted), 0 not */
        for (k = 0; k < g_lanes[i].n; ++k) {
            int an = lane_angle(g_lanes[i].shape[k]);
            if (an != 0x7fff) tlv_u(&l, 2, (uint32_t)(uint16_t)(int16_t)an, 2);
        }
        if (hi != 0x7fff) tlv_u(&l, 3, (uint32_t)(uint16_t)(int16_t)hi, 2);
        if (l.full) { o.full = 1; break; }
        tlv(&o, 2, lb, l.n);
    }
    if (o.full) return;
    push_event(0x5204, &o);
    g_lane_events++;
}

/* LiveModel.text: strict UTF-8, no controls (tab/LF/CR allowed), no C1, no surrogates, nothing above U+10FFFF */
static int utf8_ok(const uint8_t *p, unsigned n)
{
    const uint8_t *e = p + n;
    while (p < e) {
        unsigned c = *p++, cnt = 0, v = c, min = 0, i;
        if (c >= 0xc2u && c <= 0xdfu) { cnt = 1; v = c & 31u; min = 128; }
        else if (c >= 0xe0u && c <= 0xefu) { cnt = 2; v = c & 15u; min = 2048; }
        else if (c >= 0xf0u && c <= 0xf4u) { cnt = 3; v = c & 7u; min = 65536; }
        else if (c >= 128u) return 0;
        if ((unsigned)(e - p) < cnt) return 0;
        for (i = 0; i < cnt; ++i) { c = *p++; if ((c & 192u) != 128u) return 0; v = (v << 6) | (c & 63u); }
        if (v < min || v > 0x10ffffu || (v >= 0xd800u && v <= 0xdfffu)) return 0;
        if ((v < 32u && v != 9u && v != 10u && v != 13u) || (v >= 127u && v < 160u)) return 0;
    }
    return 1;
}

static void clear_step_data(void)
{
    g_road_len = 0; g_road[0] = 0; g_lane_n = 0; g_dest_m = -1; g_dest_s = -1;
}

static void maneuver_event(void)
{
    static uint8_t b[RG_EV_MAX];                 /* static: callers hold g_m; keeps gal's thread stack small */
    tw o = { b, 0, sizeof b, 0 };
    tlv_u(&o, 0, 0x10, 2);
    tlv_u(&o, 1, g_index, 2);
    tlv_u(&o, 3, (uint32_t)g_cur_t, 1);
    tlv_u(&o, 8, (uint32_t)g_cur_side, 1);
    tlv_u(&o, 9, (uint32_t)g_cur_j, 1);
    if (g_cur_has_a) tlv_u(&o, 11, (uint32_t)(uint16_t)(int16_t)g_cur_a, 2);
    push_event(0x5202, &o);
}

/* 1.7 NavigationType (kombibridge numbering, as nav_translate.c) -> iAP2 RouteGuidanceManeuver type, junction, side
 * (0 right-hand traffic, 1 left-hand: from the roundabout direction), signed angle (negative = left). 0 = unknown. */
int pmcp_rg_map(unsigned nt, unsigned exit_no, unsigned angle, int *t, int *j, int *side, int *a, int *has_a)
{
    static const signed char k[51] = {
        -1, 5, 5, 13, 14, 49, 50, 1, 2, 47, 48, 4, 4,   /*  0..12 */
        49, 50, 1, 2, 47, 48, 4, 4,                     /* 13..20 on-ramp slight, normal, sharp, u-turn */
        22, 23, 22, 23, 13, 14, 52, 53, 5,              /* 21..29 off-ramp, fork, merge L/R/- */
        -1, -1, -2, -2, -3, -3,                         /* 30, 31 unassigned; 32..35 enter-and-exit CW, CCW */
        3, 15, 15, 12, 12, 24, 25,                      /* 36 straight, ferries, destinations */
        6, 7, 6, 7,                                     /* 43..46 roundabout enter/exit CW, CCW */
        15, 15, 15, 15 };                               /* 47..50 ferries L/R */
    int v = nt < 51u ? k[nt] : -1;
    *j = 0; *side = 0; *a = 0; *has_a = 0;
    if (v == -1) return 0;
    if (v == -2 || v == -3) {                           /* enter and exit: exit number + angle */
        int cw = v == -2;
        *side = cw ? 1 : 0; *j = 1;
        if (exit_no >= 1u && exit_no <= 19u && angle >= 1u && angle <= 360u) {
            *t = 27 + (int)exit_no;
            *a = cw ? (int)angle - 180 : 180 - (int)angle;
            *has_a = 1;
        } else {
            *t = 6;
        }
        return 1;
    }
    *t = v;
    if (nt >= 43u && nt <= 46u) { *j = 1; *side = nt <= 44u ? 1 : 0; }
    if (v == 4) { *a = (nt == 11u || nt == 19u) ? -180 : 180; *has_a = 1; }
    return 1;
}

static const char *type_name(int t)
{
    switch (t) {
    case 1: return "w lewo"; case 2: return "w prawo"; case 3: return "prosto"; case 4: return "zawroc";
    case 5: return "dalej"; case 6: return "rondo"; case 7: return "zjazd z ronda"; case 12: return "cel";
    case 13: return "trzymaj lewo"; case 14: return "trzymaj prawo"; case 15: return "prom";
    case 22: return "zjazd lewo"; case 23: return "zjazd prawo"; case 24: return "cel lewo"; case 25: return "cel prawo";
    case 47: return "ostro lewo"; case 48: return "ostro prawo"; case 49: return "lekko lewo"; case 50: return "lekko prawo";
    case 52: return "pas lewo"; case 53: return "pas prawo";
    default: return t >= 28 && t <= 46 ? "rondo zjazd" : "?";
    }
}

/* NavigationLane { repeated LaneDirection dir = 1 }, LaneDirection { shape = 1; is_highlighted = 2 } */
static void parse_lane(pb l, rg_lane *out)
{
    unsigned f, w, df, dw;
    pb d;
    out->n = 0;
    while (pb_tag(&l, &f, &w)) {
        unsigned shape = 0, hl = 0;
        if (!(f == 1u && w == 2u)) { pb_skip(&l, w); continue; }
        if (!pb_sub(&l, &d)) break;
        while (pb_tag(&d, &df, &dw)) {
            if (dw != 0u) { pb_skip(&d, dw); continue; }
            if (df == 1u) shape = (unsigned)pb_var(&d);
            else if (df == 2u) hl = pb_var(&d) != 0u;
            else (void)pb_var(&d);
        }
        if (out->n < RG_LANE_DIRS && shape <= 255u) { out->shape[out->n] = (uint8_t)shape; out->hl[out->n] = (uint8_t)hl; out->n++; }
    }
}

/* Road / lanes of the step just parsed differ from what was sent: store them, report what changed (1 road, 2 lanes) */
static unsigned take_step_data(const char *road, unsigned road_len, const rg_lane *lanes, unsigned lane_n)
{
    unsigned what = 0;
    if (road_len != g_road_len || memcmp(road, g_road, road_len) != 0) {
        memcpy(g_road, road, road_len); g_road[road_len] = 0; g_road_len = road_len; what |= 1u;
    }
    if (lane_n != g_lane_n || memcmp(lanes, g_lanes, sizeof g_lanes[0] * lane_n) != 0) {
        memcpy(g_lanes, lanes, sizeof g_lanes[0] * lane_n); g_lane_n = lane_n; what |= 2u;
    }
    return what;
}

static void on_state(pb s)
{
    unsigned f, w, sf, sw, mf, mw, nt = 0, ex = 0, an = 0, lane_n = 0, road_len = 0, what;
    int have = 0, t, j, side, a, has_a;
    pb step, man, ri;
    static rg_lane lanes[RG_LANES];
    char road[RG_ROAD_MAX + 1u];
    memset(lanes, 0, sizeof lanes);
    while (!have && pb_tag(&s, &f, &w)) {
        if (!(f == 1u && w == 2u)) { pb_skip(&s, w); continue; }
        if (!pb_sub(&s, &step)) break;
        have = 1;
        while (pb_tag(&step, &sf, &sw)) {
            if (sf == 3u && sw == 2u) {                      /* NavigationLane, repeated */
                pb l;
                if (!pb_sub(&step, &l)) break;
                if (lane_n < RG_LANES) parse_lane(l, &lanes[lane_n++]);
                continue;
            }
            if (sf == 4u && sw == 2u) {                      /* NavigationRoadInfo { repeated string road_names = 1 } */
                unsigned rf, rw;
                pb nm;
                if (!pb_sub(&step, &ri)) break;
                while (road_len == 0u && pb_tag(&ri, &rf, &rw)) {
                    if (!(rf == 1u && rw == 2u)) { pb_skip(&ri, rw); continue; }
                    if (!pb_sub(&ri, &nm)) break;
                    {
                        unsigned n = (unsigned)(nm.e - nm.p);
                        if (n > RG_ROAD_MAX) { n = RG_ROAD_MAX; while (n > 0u && (nm.p[n] & 0xc0u) == 0x80u) n--; }
                        if (utf8_ok(nm.p, n)) { memcpy(road, nm.p, n); road_len = n; }
                        else g_road_bad++;
                    }
                }
                continue;
            }
            if (!(sf == 1u && sw == 2u)) { pb_skip(&step, sw); continue; }
            if (!pb_sub(&step, &man)) break;
            while (pb_tag(&man, &mf, &mw)) {
                if (mw != 0u) { pb_skip(&man, mw); continue; }
                if (mf == 1u) nt = (unsigned)pb_var(&man);
                else if (mf == 2u) ex = (unsigned)pb_var(&man);
                else if (mf == 3u) an = (unsigned)pb_var(&man);
                else (void)pb_var(&man);
            }
        }
    }
    if (!have) return;
    road[road_len] = 0;
    {
        /* lanes with no known direction at all show nothing: drop the list */
        unsigned i, any = 0;
        unsigned k;
        for (i = 0; i < lane_n; ++i) for (k = 0; k < lanes[i].n; ++k) if (lane_angle(lanes[i].shape[k]) != 0x7fff) any = 1;
        if (!any) lane_n = 0;
    }
    if (!pmcp_rg_map(nt, ex, an, &t, &j, &side, &a, &has_a)) {
        unsigned i;
        g_unknown++;
        for (i = 0; i < g_unk_n && g_unk[i] != nt; ++i) {}
        if (i == g_unk_n && g_unk_n < RG_UNK) g_unk[g_unk_n++] = nt;
        if (g_cur_t == -1 && g_index && g_unk_last == nt) {           /* the same unknown step again */
            what = take_step_data(road, road_len, lanes, lane_n);
            if (what & 2u) { if (g_lane_n) lane_event(); }
            if (what) route_event(1);
            return;
        }
        /* a new step without a manoeuvre: the route points at an index with no 0x5202, so the bridge shows no
         * arrow and the distance that follows is not attached to the previous one */
        g_cur_t = -1; g_unk_last = nt;
        g_index = g_index >= 65535u ? 1u : g_index + 1u;
        g_meters = -1;
        {
            unsigned k = g_last_n < RG_LAST ? g_last_n++ : (memmove(g_last, g_last[1], sizeof g_last[0] * (RG_LAST - 1u)), RG_LAST - 1u);
            snprintf(g_last[k], sizeof g_last[k], "t=%lus AA typ=%u zjazd=%u kat=%u -> nierozpoznany (bez strzalki)",
                     (unsigned long)((now_ms() - g_t0) / 1000u), nt, ex, an);
        }
        g_guiding = 1;
        (void)take_step_data(road, road_len, lanes, lane_n);
        if (!g_state_sent) { unsigned keep = g_index; g_index = 0; route_event(1); g_index = keep; }
        if (g_lane_n) lane_event();
        route_event(1);
        return;
    }
    g_known++;
    if (t == g_cur_t && j == g_cur_j && side == g_cur_side && a == g_cur_a && has_a == g_cur_has_a && g_index) {
        /* the same manoeuvre: only a new road name or new lanes go out (AA 1.1) */
        what = take_step_data(road, road_len, lanes, lane_n);
        if (what & 2u) { if (g_lane_n) lane_event(); }
        if (what) route_event(1);
        return;
    }
    g_cur_t = t; g_cur_j = j; g_cur_side = side; g_cur_a = a; g_cur_has_a = has_a;
    g_index = g_index >= 65535u ? 1u : g_index + 1u;
    g_meters = -1;                                    /* a new step: its distance comes with 0x8007 */
    {
        unsigned k = g_last_n < RG_LAST ? g_last_n++ : (memmove(g_last, g_last[1], sizeof g_last[0] * (RG_LAST - 1u)), RG_LAST - 1u);
        snprintf(g_last[k], sizeof g_last[k], "t=%lus AA typ=%u zjazd=%u kat=%u -> iAP2 %d %s%s",
                 (unsigned long)((now_ms() - g_t0) / 1000u), nt, ex, an, t, type_name(t), has_a ? " (kat)" : "");
    }
    g_guiding = 1;
    /* LiveModel.apply caches a 0x5202 only while the route state is active, and a state change from inactive clears
     * the cache: the state first, then the manoeuvre, then the route event that points at it */
    (void)take_step_data(road, road_len, lanes, lane_n);
    if (!g_state_sent) { unsigned keep = g_index; g_index = 0; route_event(1); g_index = keep; }
    maneuver_event();
    if (g_lane_n) lane_event();
    route_event(1);
}

/* NavigationDistance { meters = 1; display = 2; units = 3 } -> metres, -1 when absent */
static long distance_m(pb n)
{
    unsigned nf, nw;
    long m = -1;
    while (pb_tag(&n, &nf, &nw)) {
        if (nf == 1u && nw == 0u) { uint64_t v = pb_var(&n); if (v <= 20000000u) m = (long)v; }
        else pb_skip(&n, nw);
    }
    return m;
}

/* NavigationCurrentPosition { step = 1 { distance = 1 }; dest = 2 { distance = 1; eta = 2; time_to_arrival_seconds = 3 } } */
static void on_position(pb s)
{
    unsigned f, w, df, dw;
    pb d, n;
    long m = -1, dm = -1, ds = -1;
    int have_dest = 0, dest_changed;
    while (pb_tag(&s, &f, &w)) {
        if (!((f == 1u || f == 2u) && w == 2u)) { pb_skip(&s, w); continue; }
        if (!pb_sub(&s, &d)) break;
        if (f == 2u) have_dest = 1;
        while (pb_tag(&d, &df, &dw)) {
            if (df == 1u && dw == 2u) {
                if (!pb_sub(&d, &n)) break;
                if (f == 1u) m = distance_m(n); else dm = distance_m(n);
            } else if (f == 2u && df == 3u && dw == 0u) {
                uint64_t v = pb_var(&d);
                if (v <= 359940u) ds = (long)v;              /* LiveModel's bound: 99 h 59 min */
            } else pb_skip(&d, dw);
        }
    }
    dest_changed = 0;
    if (have_dest && (dm != g_dest_m || ds != g_dest_s)) { g_dest_m = dm; g_dest_s = ds; dest_changed = 1; }
    if (!g_guiding || !g_index) return;
    if (m < 0) {
        /* no step distance (Google Maps sends none on some steps): the destination still goes out, at most every 1 s */
        if (dest_changed && now_ms() - g_route_ms >= 1000u) route_event(1);
        return;
    }
    if (m == g_meters && !(dest_changed && now_ms() - g_route_ms >= 1000u) && now_ms() - g_route_ms < 2500u) return;
    g_meters = m;
    route_event(1);
}

static void on_status(pb s)
{
    unsigned f, w;
    while (pb_tag(&s, &f, &w)) {
        if (f == 1u && w == 0u) {
            unsigned v = (unsigned)pb_var(&s);
            if (v == 1u || v == 3u) { g_guiding = 1; }
            else if (g_guiding || g_index) {
                g_guiding = 0; g_index = 0; g_cur_t = -1; g_meters = -1; g_paused = 0;
                clear_step_data();
                route_event(0);
            }
            return;
        }
        pb_skip(&s, w);
    }
}

/* ---- writer thread ---- */
static int write_file(const char *dir, const char *name, const uint8_t *a, size_t an, const uint8_t *b, size_t bn)
{
    char tmp[200], dst[200];
    int fd, bad = 0;
    snprintf(tmp, sizeof tmp, "%s/%s.tmp", dir, name);
    snprintf(dst, sizeof dst, "%s/%s", dir, name);
    fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return -1;
    if (an && write(fd, a, an) != (ssize_t)an) bad = 1;
    if (bn && write(fd, b, bn) != (ssize_t)bn) bad = 1;
    if (close(fd) != 0) bad = 1;
    if (bad) { unlink(tmp); return -1; }
    return rename(tmp, dst);
}

static uint8_t g_img[RG_SNAP + 32u];

/* Builds RGM1 + compacted RGI1 from the ring; caller holds g_m. Returns the size. */
static size_t build(void)
{
    uint8_t *h = g_img, *b = g_img + 32;
    uint32_t count = g_seq < RG_SLOTS ? g_seq : RG_SLOTS, i;
    size_t used = 64;
    memset(b, 0, 64);
    memcpy(b, "RGI1", 4); le32(b + 4, 1); le32(b + 8, RG_SNAP); le32(b + 12, 0);
    le32(b + 16, g_session); le32(b + 20, g_seq); le32(b + 24, count); le32(b + 28, 0); le32(b + 32, 0);
    le32(b + 36, 1); le32(b + 40, g_life_s); le32(b + 44, g_life_ns);
    for (i = 0; i < count; ++i) {
        uint32_t s = g_seq - count + 1u + i;
        const rg_ev *e = &g_ring[(s - 1u) & (RG_SLOTS - 1u)];
        uint8_t *p = b + used;
        le32(p, e->seq); le16(p + 4, e->id); le16(p + 6, e->len); le32(p + 8, g_session); le32(p + 12, 0);
        memcpy(p + 16, e->d, e->len);
        used += 16u + e->len;
    }
    memcpy(h, "RGM1", 4); le32(h + 4, 1); le32(h + 8, (uint32_t)(32u + used));
    le32(h + 12, ++g_serial); le32(h + 16, 1); le32(h + 20, 0);
    le32(h + 24, (uint32_t)g_nonce); le32(h + 28, (uint32_t)(g_nonce >> 32));
    return 32u + used;
}

/* ---- raw navigation dump (A165) ---- */
static void raw_queue(unsigned id, const uint8_t *d, unsigned len)
{
    raw_msg *m;
    uint64_t t = now_ms();
    unsigned n = len < RAW_MSG_MAX ? len : RAW_MSG_MAX;
    if (id != 0x8003u && id != 0x8006u && id != 0x8007u) return;
    if (id == 0x8006u) {
        if (n == g_raw_last6_len && memcmp(d, g_raw_last6, n) == 0) { g_raw_same++; return; }
        memcpy(g_raw_last6, d, n); g_raw_last6_len = n;
    }
    if (id == 0x8007u) {
        if (g_raw_last7_ms && t - g_raw_last7_ms < 5000u) return;
        g_raw_last7_ms = t;
    }
    if (g_raw_n >= RAW_SLOTS) { g_raw_dropped++; return; }
    m = &g_raw[(g_raw_head + g_raw_n) % RAW_SLOTS];
    m->t = t; m->id = id; m->len = n; m->full = len;
    memcpy(m->d, d, n);
    g_raw_n++;
    g_dirty = 1;
}

typedef struct { char *b; size_t n, cap; } sbuf;
static void sb_put(sbuf *o, const char *fmt, ...)
{
    va_list ap;
    int k;
    if (o->n + 1u >= o->cap) return;
    va_start(ap, fmt);
    k = vsnprintf(o->b + o->n, o->cap - o->n, fmt, ap);
    va_end(ap);
    if (k < 0) return;
    o->n = (size_t)k < o->cap - o->n ? o->n + (size_t)k : o->cap - 1u;
}

/* Is the whole buffer a well-formed message (every tag valid, every length inside)? */
static int pb_valid(const uint8_t *p, const uint8_t *e, int depth)
{
    pb s, d;
    unsigned f, w;
    if (p == e) return 0;
    s.p = p; s.e = e;
    while (s.p < s.e) {
        if (!pb_tag(&s, &f, &w) || f == 0u || f > 64u) return 0;
        if (w == 0u) { const uint8_t *q = s.p; (void)pb_var(&s); if (s.p == q || (s.p[-1] & 0x80u)) return 0; }
        else if (w == 2u) { if (!pb_sub(&s, &d)) return 0; (void)depth; }
        else if (w == 1u) { if (s.e - s.p < 8) return 0; s.p += 8; }
        else if (w == 5u) { if (s.e - s.p < 4) return 0; s.p += 4; }
        else return 0;
    }
    return 1;
}

static int printable(const uint8_t *p, const uint8_t *e)
{
    if (p == e) return 0;
    for (; p < e; ++p) if (*p < 0x20u || *p == 0x7fu || *p == '"' || *p == '\\') return 0;
    return 1;
}

/* field:value pairs; length-delimited = "text" when printable, {nested} when it parses, else hex */
static void pb_dump(sbuf *o, const uint8_t *p, const uint8_t *e, int depth)
{
    pb s, d;
    unsigned f, w;
    int first = 1;
    s.p = p; s.e = e;
    while (pb_tag(&s, &f, &w)) {
        sb_put(o, first ? "%u:" : " %u:", f);
        first = 0;
        if (w == 0u) sb_put(o, "%llu", (unsigned long long)pb_var(&s));
        else if (w == 2u) {
            const uint8_t *q;
            if (!pb_sub(&s, &d)) { sb_put(o, "?"); break; }
            if (printable(d.p, d.e)) sb_put(o, "\"%.*s\"", (int)(d.e - d.p), (const char *)d.p);
            else if (depth < 8 && pb_valid(d.p, d.e, depth)) { sb_put(o, "{"); pb_dump(o, d.p, d.e, depth + 1); sb_put(o, "}"); }
            else { sb_put(o, "x"); for (q = d.p; q < d.e && q < d.p + 48; ++q) sb_put(o, "%02x", *q); if (q < d.e) sb_put(o, ".."); }
        } else if (w == 1u) { sb_put(o, "f64"); pb_skip(&s, w); }
        else if (w == 5u) { sb_put(o, "f32"); pb_skip(&s, w); }
        else { sb_put(o, "?w%u", w); break; }
    }
}

/* Writer thread, g_m held: everything queued goes to the file (the lock is held only for a few lines a second). */
static void raw_flush(void)
{
    static char line[RAW_MSG_MAX * 3u + 256u];
    FILE *f;
    struct stat st;
    if (!g_raw_n) return;
    if (stat(g_raw_path, &st) == 0 && st.st_size >= RAW_FILE_MAX) {
        char old[160];
        snprintf(old, sizeof old, "%s.1", g_raw_path);
        (void)rename(g_raw_path, old);
    }
    f = fopen(g_raw_path, "a");
    while (g_raw_n) {
        raw_msg *m = &g_raw[g_raw_head];
        sbuf o;
        o.b = line; o.n = 0; o.cap = sizeof line;
        sb_put(&o, "t=%lu.%lus %04x len=%u%s | ", (unsigned long)((m->t - g_t0) / 1000u),
               (unsigned long)((m->t - g_t0) % 1000u / 100u), m->id, m->full, m->full > m->len ? " (uciete)" : "");
        pb_dump(&o, m->d, m->d + m->len, 0);
        if (f != NULL) { fputs(line, f); fputc('\n', f); g_raw_lines++; }
        g_raw_head = (g_raw_head + 1u) % RAW_SLOTS;
        g_raw_n--;
    }
    if (f != NULL) fclose(f);
}

static void write_status(void)
{
    char s[1536];
    int n;
    unsigned i;
    n = snprintf(s, sizeof s, "RG AA: komunikaty 0x8003=%lu 0x8006=%lu 0x8007=%lu prowadzenie=%s\n"
                 "manewry rozpoznane=%lu nierozpoznane=%lu", g_n3, g_n6, g_n7, g_guiding ? "tak" : "nie", g_known, g_unknown);
    if (g_unk_n) {
        n += snprintf(s + n, sizeof s - (size_t)n, " (typy AA:");
        for (i = 0; i < g_unk_n; ++i) n += snprintf(s + n, sizeof s - (size_t)n, " %u", g_unk[i]);
        n += snprintf(s + n, sizeof s - (size_t)n, ")");
    }
    n += snprintf(s + n, sizeof s - (size_t)n, "\nzapis: zdarzenia=%lu pliki=%lu bledy=%lu dystans=%ldm\n",
                  g_events, g_writes, g_werr, g_meters);
    n += snprintf(s + n, sizeof s - (size_t)n, "cisza telefonu: ostatnia nawigacja %lds temu, pauzy=%lu koniec_po_ciszy=%lu%s\n",
                  g_nav_ms ? (long)((now_ms() - g_nav_ms) / 1000u) : -1L, g_pauses, g_silent_ends, g_paused ? " (pauza)" : "");
    if (g_raw_path[0])
        n += snprintf(s + n, sizeof s - (size_t)n, "surowe: linie=%lu pominiete_bez_zmian=%lu zgubione=%lu plik=%s\n",
                      g_raw_lines, g_raw_same, g_raw_dropped, g_raw_path);
    n += snprintf(s + n, sizeof s - (size_t)n, "AA 1.1: droga='%.60s' pasy=%u zdarzenia_pasow=%lu zle_nazwy=%lu cel=%ldm/%lds\n",
                  g_road, g_lane_n, g_lane_events, g_road_bad, g_dest_m, g_dest_s);
    for (i = 0; i < g_last_n && n < (int)sizeof s - 100; ++i) n += snprintf(s + n, sizeof s - (size_t)n, "manewr %s\n", g_last[i]);
    {
        char tmp[200];
        FILE *f;
        snprintf(tmp, sizeof tmp, "%s.tmp", g_status);
        if ((f = fopen(tmp, "w")) == NULL) return;
        fputs(s, f);
        if (fclose(f) == 0) rename(tmp, g_status);
    }
}

static void *writer(void *arg)
{
    uint64_t last_write = 0, last_status = 0;
    (void)arg;
    pthread_mutex_lock(&g_m);
    for (;;) {
        struct timespec ts;
        uint64_t t;
        int need;
        clock_gettime(CLOCK_REALTIME, &ts);
        ts.tv_nsec += 250000000L;
        if (ts.tv_nsec >= 1000000000L) { ts.tv_sec++; ts.tv_nsec -= 1000000000L; }
        if (!g_dirty) pthread_cond_timedwait(&g_cv, &g_m, &ts);
        t = now_ms();
        /* the bridge needs a new accepted event within 5 s while guiding; only while the phone still navigates */
        if (g_guiding && g_index) {
            uint64_t quiet = t - g_nav_ms;
            if (quiet >= g_end_ms) {
                g_guiding = 0; g_index = 0; g_cur_t = -1; g_meters = -1; g_paused = 0;
                clear_step_data();
                g_silent_ends++;
                route_event(0);
            } else if (quiet >= g_stale_ms) {
                if (!g_paused) { g_paused = 1; g_pauses++; }
            } else if (t - g_route_ms >= 2500u) route_event(1);
        }
        /* heartbeat 0.5 s: the bridge wants a new serial within 1.5 s (review m1: 1 s left ~150 ms margin) */
        need = g_dirty || t - last_write >= 500u;
        if (need) {
            size_t n = build();
            g_dirty = 0;
            if (write_file(g_dir, "latest.bin", g_img, n, NULL, 0) == 0) g_writes++; else g_werr++;
            last_write = t;
        }
        if (g_raw_n) raw_flush();
        if (t - last_status >= 1000u) { write_status(); last_status = t; }
    }
    return NULL;
}

static int start(void)
{
    pthread_t th;
    pthread_attr_t at;
    struct timespec ts;
    const char *v = getenv("GAL_PMCP_RG");
    g_on = v != NULL && strcmp(v, "1") == 0;
    if (!g_on) return 0;
    v = getenv("GAL_PMCP_RG_DIR");
    snprintf(g_dir, sizeof g_dir, "%s", v && *v == '/' ? v : "/ramdisk/pmcp-aa-rg");
    v = getenv("GAL_PMCP_RG_STALE_MS");
    if (v) { unsigned long x = strtoul(v, NULL, 10); if (x >= 1000u && x <= 120000u) g_stale_ms = (unsigned)x; }
    v = getenv("GAL_PMCP_RG_END_MS");
    if (v) { unsigned long x = strtoul(v, NULL, 10); if (x >= 2000u && x <= 600000u) g_end_ms = (unsigned)x; }
    if (g_end_ms <= g_stale_ms) g_end_ms = g_stale_ms + 1000u;
    v = getenv("GAL_PMCP_RG_RAW");
    snprintf(g_raw_path, sizeof g_raw_path, "%s", v == NULL ? "/ramdisk/pmcp-aa-rg-raw.txt" : (*v == '/' ? v : ""));
    v = getenv("GAL_PMCP_RG_STATUS");
    snprintf(g_status, sizeof g_status, "%s", v && *v == '/' ? v : "/ramdisk/pmcp-aa-rg.txt");
    if (mkdir(g_dir, 0755) != 0 && errno != EEXIST) { g_on = 0; return 0; }
    clock_gettime(CLOCK_REALTIME, &ts);
    g_t0 = now_ms();
    g_life_s = (uint32_t)ts.tv_sec; g_life_ns = (uint32_t)ts.tv_nsec;
    g_nonce = ((uint64_t)(uint32_t)getpid() << 32) | (uint32_t)ts.tv_sec;   /* new per gal process: the bridge resets */
    g_session = ((uint32_t)getpid() & 0xffffu) | 0x10000u;
    g_dirty = 1;                                                             /* baseline: no events */
    pthread_attr_init(&at);
    pthread_attr_setdetachstate(&at, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&th, &at, writer, NULL) != 0) g_on = 0;
    pthread_attr_destroy(&at);
    return g_on;
}

void pmcp_rg_message(const unsigned char *msg, unsigned len)
{
    unsigned id;
    pb s;
    if (msg == NULL || len < 2u) return;
    pthread_mutex_lock(&g_m);
    if (!g_started) { g_started = 1; start(); }
    if (!g_on) { pthread_mutex_unlock(&g_m); return; }
    id = ((unsigned)msg[0] << 8) | msg[1];
    s.p = msg + 2; s.e = msg + len;
    if (id == 0x8006u || id == 0x8007u) {
        g_nav_ms = now_ms();
        if (g_paused) {
            /* the phone navigates again: the current manoeuvre and the route event once more */
            g_paused = 0;
            if (g_guiding && g_index) { if (g_cur_t >= 0) maneuver_event(); if (g_lane_n) lane_event(); route_event(1); }
        }
    }
    if (g_raw_path[0]) raw_queue(id, msg + 2, len - 2u);
    if (id == 0x8006u) { g_n6++; on_state(s); }
    else if (id == 0x8007u) { g_n7++; on_position(s); }
    else if (id == 0x8003u) { g_n3++; on_status(s); }
    if (g_dirty) pthread_cond_signal(&g_cv);
    pthread_mutex_unlock(&g_m);
}
