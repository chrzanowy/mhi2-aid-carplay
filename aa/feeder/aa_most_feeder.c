/*
 * aa-most-feeder: Android Auto cluster video -> omonob's altscreen-most-bridge ring -> MOST -> AID.
 *
 * Started by MacsInSpace's libgal_hook.so in place of its stream-player (GAL_PLAYER_PATH), with the
 * stream URL as argv[1] ("tcp://127.0.0.1:12346" or a Unix socket path). The hook sends raw H.264
 * Annex B with no framing and expects one byte on /tmp/gal_ack.sock per frame the player has taken;
 * it ACKs the phone only then, so delaying that byte slows the phone down.
 *
 * Ring and bridge facts used here (docs/11-ring-altscreen.md, docs/06-audyt.md A63/A64):
 *   file 0x1000710 B: header {magic 'GRPC', version 1, generation, last seq}, 64 slots x 0x4001c;
 *   slot {seq, type (1 avcC, 2 frame), len, 0, frame no, u64 NTP 32.32 time, data <= 0x40000};
 *   writer: slot.seq = 0, fields + data, slot.seq = N, header.seq = N. The bridge reads from seq 1
 *   after it (re)initialises the file, adds start code + AUD itself and puts SPS/PPS from the avcC
 *   in front of every IDR, so frames go in as AVCC without AUD/SPS/PPS.
 *   MOST takeover as carplay-cluster-supervisor: dmdt dc 72 + dmdt sc 4 72, 500 ms, start bridge;
 *   back: SIGTERM bridge, flush(0) on /dev/mlb/debug/isoTX2, SIGKILL, 250 ms, dmdt dc 70 33 + sc 4 70.
 *
 * Fresh IDR (v2): the phone sends an IDR only every 64 s to 5 min, and after a latency reset the bridge drops every
 * frame until the next one; it asks for one by creating PMCP_AA_KF_REQ (default /ramdisk/carplay-alt-force-idr.request,
 * request_fresh_idr). In "most" mode with the ring ours the feeder removes that file and sends the byte 'K' on the ACK
 * pipe; the pmcp-patched hook (aa/hook/patch_keyframe.py) then cycles the cluster focus 2 -> 1 and the phone restarts its
 * stream with an IDR. Optionally also once PMCP_AA_KF_TAKE_MS after the takeover (default 0 = off since v3: on the car
 * a focus cycle in a session dropped the phone to ~3 fps and reset the connection ~130 s later, audit A-AA11).
 * At most one request per PMCP_AA_KF_MIN_MS.
 *
 * v3: in "most" mode the MOST takeover runs BEFORE the feeder connects to the hook's stream, so the phone is granted
 * the cluster only after the bridge is up and no frame waits for its ACK during the takeover (v2 took it at the first
 * IDR: ACKs stood still ~1.5 s, the hook presumed 6 frames dropped and discarded 5 late ACKs, A-AA11).
 *
 * v4: the takeover waits (PMCP_AA_WAIT_MS, default 6 s) while the guardian of the previous AA session is still stopping its
 * bridge or giving MOST back (gal restarts within 1 s, A-AA13; the guardian marks itself in <rundir>/pmcp-aa-guard.pid
 * until its dmdt restore is done), then waits PMCP_AA_SETTLE_MS (default 1 s) before the stream connects. The bridge's
 * output goes through a pipe to the guardian, which counts latency resets / IDR requests / MOST write errors and keeps
 * the last lines in <rundir>/pmcp-aa-bridge.txt; each session appends one line to <rundir>/pmcp-aa-sessions.txt (last 10
 * kept). Both are shown in the status. <rundir> = PMCP_AA_RUNDIR, default /ramdisk.
 *
 * v5: PMCP_AA_KF_METHOD=focus (byte 'K', focus cycle, default) or config (byte 'C': the patched hook resends the channel
 * setup response 0x8003, no focus change; aa/hook/patch_config_kf.py, experiment A-AA15).
 *
 * v6: start sync (PMCP_AA_SYNC_HOLD_MS, default 0 = off; the sync modes set 2500). The AID loses the session's first IDR
 * now and then (it is not ready yet; bridge keys = IDRs, drops = 0) and shows "starting map view" until the phone's next
 * IDR, 60 s to 5 min later (A-AA18). With sync on, the first IDR of a MOST session is written, its ACK is held, and the
 * same IDR is written again every PMCP_AA_SYNC_REPEAT_MS (default 500) until the hold ends. The phone stops after its
 * 8-frame window (the hook releases credit only when an ACK arrives, its hang rule is 20 s), the few frames it sent
 * meanwhile wait here and go out in order after the hold, then all ACKs. Every copy is the same picture, so the P frames
 * after it decode on the right reference whichever copy the AID took. The status lists the session's first IDRs
 * (time after the takeover, size) to check this on the car.
 *
 * v7 (car, A-AA20): the phone's first IDR of a stream is ~1 KB, an empty picture; the map comes in the P frames after it.
 * So repeating that IDR does not help: the AID must already decode when the first P frames come, or it shows the dark
 * picture with only the changes drawn on it until the phone's next IDR (60+ s). The hook waits for the player's
 * connections with no time limit before it grants the phone, so the feeder can wait as long as it likes after the
 * takeover: PMCP_AA_SETTLE_MS up to 15 s (the AA 3 settings use 5 s).
 * CarPlay: its cluster supervisor is a permanent daemon (started once per boot, idle without a phone), so its pid file
 * only says "running", and v3-v6 refused MOST for the rest of the boot once CarPlay had been used (car, A-AA20). It owns
 * MOST only while its bridge runs: /ramdisk/carplay-bridge.ready AND a live altscreen-most-bridge process that is not
 * ours (the marker can outlive a bridge that exited by itself). The takeover waits up to PMCP_AA_CP_WAIT_MS (default
 * 20 s) for that to end. Without /proc (host tests) the marker alone counts.
 *
 * v8 (car, A-AA27): after CarPlay the bridge failed with "open ring ... No space left on device". CarPlay's producer
 * (core.so in dio_manager, a permanent process) keeps the ring file mapped, so unlinking it (v2-v7) only hid the name: the
 * 16 MB stay used, the 20 MB /ramdisk has no room for a second ring, and AA had no picture until a restart (the same
 * cause as AA 2's "no MOST after CarPlay"). Now a ring of the right size and magic is reused in place: the header's
 * last sequence and every slot's sequence are set to 0 (so the bridge, starting at 1, replays nothing) and the file
 * stays; only a ring of another size or without magic is unlinked as before. The status line "plik ringu" says which.
 *
 * v9 (car, A-AA30): the AID also lost the picture in the middle of a drive (loading screen, 199 s session, one IDR, the
 * largest P frame 96 KB, 4.7 Mbit/s in one second, nothing dropped on our side). Two changes:
 *   pacing (PMCP_AA_PACE_KBPS, default 0 = off; PMCP_AA_PACE_BURST_KB, default 64): frames go into the ring no faster than
 *   this byte budget. A frame that overdraws it still goes whole, but the frames after it wait here (in order, their ACKs
 *   too, so the phone slows down) until the budget is back, so the AID's decoder never gets several large frames at once.
 *   The queue holds at most PACE_MAX frames / PACE_POOL bytes; when full everything queued goes out at once (counted).
 *   Diagnostics: frames per 10 s for the last 5 min, the longest gap between frames (and when), the last large frames,
 *   and how long ago the last frame came, so the status tells "the phone stopped sending" from "frames still came".
 *
 * v10 (car, A-AA33): one session of v9 ended like A-AA11. Around 128 s the pacing queue was full (48) and went out at
 * once; the bridge (omonob source: more than 1024 TS packets = ~188 KB = ~125 ms of MOST queued when a frame comes) did
 * a latency-reset, lost the frames until an IDR and asked for one; the feeder
 * turned that into a focus cycle; the phone sent the IDR, dropped to ~3 fps and the connection reset ~130 s later. The
 * start hold also put its 15 held frames into the ring at once. The rule now: the ring never gets a burst.
 *   - PMCP_AA_PACE_GAP_MS (default 0 = off): at least this long between two frames into the ring, also for the frames
 *     after the start hold and the ones queued by the byte budget;
 *   - the queue is larger (PACE_MAX / PACE_POOL); from 3/4 full it drains on a second byte budget,
 *     PMCP_AA_PACE_DRAIN_KBPS (default 8000, burst 128 KB: below the bridge's 188 KB and the 12.288 Mbit/s of MOST),
 *     still with the gap; when it is full only the oldest frames needed for room go out (counted), never the whole queue;
 *   - PMCP_AA_KF_BRIDGE (default 0): the bridge's IDR request file is removed and counted, but no focus cycle / config
 *     resend follows unless this is 1 (both break the phone's session, A-AA11/A-AA15).
 *
 * v11: our own MOST output, PMCP_AA_OUTPUT=direct (default "ring" = everything above, unchanged). The feeder starts no
 * altscreen-most-bridge and makes no ring: it muxes the frames itself (aa/most/ts_mux.c, the bridge's TS byte for byte)
 * and writes whole 12032-byte blocks to /dev/mlb/isoTX2 from a writer thread (aa/most/most_writer.c, the bridge's open
 * and devctl sequence). The queue holds whole access units in process memory and never drops, skips or truncates one,
 * and never waits for or asks for an IDR (the phone sends one about every 60 s; a request breaks its session).
 * Backpressure goes to the phone only: ACKs are held while more than PMCP_AA_ACK_HIGH_PKTS TS packets (default 1024,
 * ~125 ms of MOST) are queued and released once fewer than PMCP_AA_ACK_LOW_PKTS (default 512) are. The PTS is set when
 * the AU's first packet is built (lead over PCR ~100 ms, never negative), the first AU carries the discontinuity flag.
 * The guardian is the same: it runs no bridge in this mode, waits for the pipe and gives MOST back with dmdt; the feeder
 * closes isoTX2 before it closes the pipe. A write error, a short write or a stuck write gives MOST back mid-session
 * and the session goes on as analysis, as when the bridge dies. Diagnostics for both outputs: the guardian keeps the
 * first 30 bridge lines (the devctl read-backs) besides the last ones, and PMCP_AA_CAPTURE_S=N records the phone's
 * access units for N s (Annex B with an AUD per AU, at most 6 MB, plus an .idx with their times) to
 * PMCP_AA_CAPTURE_PATH (default /mnt/persist/pmcp/aa-stream.h264).
 *
 * v12 (car test A147: direct ran 890 s with no error): direct mode drops the v10 pacing (it only kept the mathsls bridge
 * under its latency-reset and held frames up to 405 ms here); the MOST writer's first sleep after an accepted block is
 * sized to the block time (PMCP_AA_MOST_SLEEP_US); the capture keeps 8 MB free, is cut to what fits and reports errno.
 *
 * v13 (car test A152): the full status of the last 3 sessions is kept (<status>-prev1..3, prev1 newest) for the log; the
 * MOST events also note phone gaps (>= 1.5 s, and a stall >= 3 s with the ACK/queue state at that moment) and every ACK
 * hold on/off; direct: PTS lead rebased down above 130 ms (PMCP_AA_LEAD_MAX_MS, was 200) and the start sync hold is
 * PMCP_AA_DIRECT_SYNC_HOLD_MS (default 1500, was the shared 3000); the capture keeps 4 MB free.
 *
 * v14 = AA 1.0 (user decision A153): PMCP_AA_OUTPUT is taken only when it is exactly "direct" or "ring" (trailing
 * blanks/CR ignored); any other value in aa-extra.conf or feeder.conf is ignored and counted in the status, so a bad switch
 * (the on-unit UI page writes it without a trial) always gives the default from feeder.conf (AA 1.0: direct).
 *
 * v15 (A165, after tomasz-twardzicki MU1367 v1.5.1-e): while the radio boots the factory video encoder takes isoTX2 by
 * itself about 15 s after it was released and the next write fails (ENOMEM on MU1367). Direct used to give MOST back
 * for the rest of the session (no cluster map until a reconnect). Now a write error with errno set, or a block refused
 * (EAGAIN) for PMCP_AA_MOST_STALL_MS, in the first PMCP_AA_RECLAIM_S of uptime (default 180, 0 = off) takes MOST back
 * instead, at most PMCP_AA_RECLAIM_MAX times (default 3): device closed, dmdt dc 72 + sc 4 72 again, 500 ms, the same
 * open and devctl sequence, the next AU with the discontinuity flag, then SPS/PPS and the last IDR again (the phone
 * sends one about every 60 s and asking breaks its session), so the picture comes back with brief artifacts at most.
 * A short write, a write stuck in the driver, a failed reclaim or anything later goes the old way.
 *
 * Modes (PMCP_AA_MODE): "analyze" (default) only reads, ACKs and writes a summary; the cluster keeps
 * the VW map. "most" also takes the MOST channel over. The summary is rewritten once a second to
 * PMCP_AA_STATUS (default /ramdisk/pmcp-aa-feeder.txt); nothing grows without bound.
 *
 * The hook starts the player with a fixed environment (IPL_CONFIG_DIR, LD_LIBRARY_PATH, PATH), so on the
 * unit the settings come from PMCP_AA_CONF (default /mnt/app/carplaymaps/aa/feeder.conf, written and
 * hash-checked by pmcp.sh): KEY=VALUE lines, only the keys in CONF_KEYS, the environment wins (host tests).
 */
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <dirent.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <pthread.h>

#include "../most/ts_mux.h"
#include "../most/most_writer.h"

#define FEEDER_VERSION "15"

#define RING_MAGIC      0x43505247u
#define RING_VERSION    1u
#define RING_SLOTS      64u
#define RING_SLOT_SIZE  0x4001cu
#define RING_HDR_SIZE   0x10u
#define RING_FILE_SIZE  (RING_HDR_SIZE + RING_SLOTS * RING_SLOT_SIZE)   /* 0x1000710 */
#define RING_DATA_MAX   0x40000u
#define RING_TYPE_AVCC  1u
#define RING_TYPE_FRAME 2u

#define IN_BUF_MAX      (1024u * 1024u)   /* raw Annex B waiting for an access unit boundary */
#define AU_MAX          RING_DATA_MAX     /* the ring cannot carry a larger frame */
#define AU_BUF_MAX      (IN_BUF_MAX + 1024u)   /* v11 direct output: no 256 KB limit (AVCC adds 1 byte per 3-byte start code) */
#define PS_MAX          256u              /* one SPS or PPS */
#define ACK_QUEUE       64u
#define SYNC_POOL       (768u * 1024u)    /* frames the phone sent during the start hold (window: 8) */
#define SYNC_HELD_MAX   32u
#define IDR_LOG_MAX     6u
#define PACE_POOL       (4096u * 1024u)   /* frames waiting for the pacing budget (v9; v10: 4 MB) */
#define PACE_MAX        256u              /* v10: ~8 s at 30 fps */
#define WIN_N           30u               /* 10 s windows kept: 5 min */
#define WIN_US          10000000u
#define BIG_LOG_MAX     6u
#define BIG_BYTES       32768u            /* a "large" frame for the status */
#define MUX_ENTRIES     1024u             /* v11: AUs + parameter sets the direct queue can hold */
#define EV_FIRST        30u               /* v11: first and last MOST events kept for the status */
#define EV_LAST         24u
#define BO_FIRST        30u               /* v11: first bridge lines kept by the guardian (devctl read-backs) */
#define CAP_MAX         (6u * 1024u * 1024u)   /* v11: capture limit, H.264 + index */
#define CAP_CFG_MAX     1024u
#define CAP_RESERVE     (4ull * 1024u * 1024u)  /* v13: free space the capture leaves on the partition (v12: 8 MB, v11: 16 MB;
                                                   * the car has ~7 MB free on /mnt/persist, A152) */
#define CAP_MIN         (256u * 1024u)          /* v12: a cut capture smaller than this is not written */

static const char *g_mode, *g_status_path, *g_ring_path, *g_bridge_path, *g_dmdt_path, *g_ack_path;
static const char *g_flush_dev, *g_kf_req_path, *g_run_dir;
static unsigned long g_wait_ms, g_settle_ms, g_cp_wait_ms;
static const char *g_cp_ready_path;
static unsigned long g_sync_hold_ms, g_sync_repeat_ms;
static double g_pace_bps, g_pace_burst;  /* v9 pacing: bytes per second into the ring, 0 = off; burst in bytes */
static uint64_t g_pace_gap_us;           /* v10: least time between two frames into the ring, 0 = off */
static double g_drain_bps, g_drain_burst, g_dtok;   /* v10: byte budget for draining a 3/4 full queue */
static uint64_t g_dtok_t;
static uint64_t g_pace_last_us;          /* v10: when the last frame went into the ring */
static int g_kf_bridge_on;               /* v10: 1 = the bridge's IDR request sends K/C to the hook */
static uint8_t g_kf_byte = 'K';   /* K = focus cycle, C = resend setup response (v5) */
static unsigned long g_kf_take_ms, g_kf_min_ms;
static uint64_t g_kf_take_due;   /* one request this long after the takeover; 0 = none pending */
static uint64_t g_kf_last_us;    /* last 'K' sent */
static int g_kf_waiting;         /* a 'K' went out and no IDR has come since */
static unsigned g_idle_ms;       /* the hook writes a frame at once: a pause this long ends it */
static volatile sig_atomic_t g_stop;
/* v11 direct output */
static int g_direct;             /* PMCP_AA_OUTPUT=direct */
static int g_direct_on;          /* MOST taken in direct mode and the writer thread running */
static ts_mux_t g_mux;
static ts_mux_cfg_t g_mux_cfg;
static most_writer_t g_mw;
static most_cfg_t g_mw_cfg;
static unsigned long g_queue_kb, g_ack_high, g_ack_low;
static int g_ack_hold;           /* ACKs held: the direct queue went over the high-water mark */
static uint64_t g_hold_t0;
static unsigned g_au_limit = RING_DATA_MAX;   /* largest frame taken (the ring's slot; direct: AU_BUF_MAX) */
static unsigned long g_cap_s;    /* v11 capture seconds, 0 = off */
static const char *g_cap_path;

/* ---------------------------------------------------------------- time */

static uint64_t now_us(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000u + (uint64_t)ts.tv_nsec / 1000u;
}

/* NTP 32.32 from the monotonic clock: the bridge only uses differences (PTS = delta x 90 kHz). */
static uint64_t now_ntp(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((uint64_t)ts.tv_sec << 32) | (uint64_t)(((uint64_t)ts.tv_nsec << 32) / 1000000000u);
}

static void sleep_ms(unsigned ms)
{
    struct timespec ts = { (time_t)(ms / 1000u), (long)(ms % 1000u) * 1000000L };
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR && !g_stop) {}
}

static const char *env_or(const char *name, const char *def)
{
    const char *v = getenv(name);
    return (v != NULL && *v != '\0') ? v : def;
}

static unsigned long env_ul(const char *name, unsigned long def, unsigned long lo, unsigned long hi)
{
    const char *v = getenv(name);
    char *end;
    unsigned long x;
    if (v == NULL || *v == '\0') return def;
    x = strtoul(v, &end, 10);
    return (*end != '\0' || x < lo || x > hi) ? def : x;
}

/* Settings file: only mode and pacing, never a path, so the file cannot point the feeder at another program. */
static const char *const CONF_KEYS[] = { "PMCP_AA_MODE", "PMCP_AA_RATE_KBPS", "PMCP_AA_BURST_KB", "PMCP_AA_IDLE_MS",
                                         "PMCP_AA_KF_TAKE_MS", "PMCP_AA_KF_MIN_MS", "PMCP_AA_WAIT_MS",
                                         "PMCP_AA_SETTLE_MS", "PMCP_AA_KF_METHOD", "PMCP_AA_SYNC_HOLD_MS",
                                         "PMCP_AA_SYNC_REPEAT_MS", "PMCP_AA_CP_WAIT_MS", "PMCP_AA_PACE_KBPS",
                                         "PMCP_AA_PACE_BURST_KB", "PMCP_AA_PACE_GAP_MS", "PMCP_AA_KF_BRIDGE",
                                         "PMCP_AA_PACE_DRAIN_KBPS",
                                         /* v11 */
                                         "PMCP_AA_OUTPUT", "PMCP_AA_ACK_HIGH_PKTS", "PMCP_AA_ACK_LOW_PKTS",
                                         "PMCP_AA_QUEUE_KB", "PMCP_AA_MOST_WAIT", "PMCP_AA_MOST_STALL_MS", "PMCP_AA_MOST_SLEEP_US",
                                         "PMCP_AA_LEAD_MS", "PMCP_AA_LEAD_MIN_MS", "PMCP_AA_LEAD_MAX_MS",
                                         "PMCP_AA_DISC_FIRST", "PMCP_AA_CAPTURE_S",
                                         "PMCP_AA_DIRECT_SYNC_HOLD_MS",
                                         /* v15 */
                                         "PMCP_AA_RECLAIM_S", "PMCP_AA_RECLAIM_MAX", NULL };

/* v11: GEM switches (pmcp.sh aa-output / aa-capture) write a second, unpinned file on /mnt/persist: only these keys,
 * never a path, read before the pinned settings so the switch wins over them (the environment still wins). */
static const char *const EXTRA_KEYS[] = { "PMCP_AA_OUTPUT", "PMCP_AA_CAPTURE_S", NULL };

static unsigned long g_reclaim_s, g_reclaim_max;   /* v15: PMCP_AA_RECLAIM_S / _MAX (direct only) */
static unsigned long g_output_ignored;    /* v14: PMCP_AA_OUTPUT lines with a value other than direct/ring */
static char g_output_from[16] = "domyslne";

static void load_keys(const char *path, const char *const *keys, const char *from)
{
    char line[128];
    FILE *f = fopen(path, "r");
    if (f == NULL) return;
    while (fgets(line, (int)sizeof line, f) != NULL) {
        char *eq = strchr(line, '='), *end;
        int i;
        if (line[0] == '#' || eq == NULL) continue;
        *eq = '\0';
        end = eq + 1 + strcspn(eq + 1, "\r\n");
        while (end > eq + 1 && (end[-1] == ' ' || end[-1] == '\t')) --end;
        *end = '\0';
        if (strcmp(line, "PMCP_AA_OUTPUT") == 0) {   /* v14: only the two known outputs */
            if (strcmp(eq + 1, "direct") != 0 && strcmp(eq + 1, "ring") != 0) { g_output_ignored++; continue; }
            if (getenv("PMCP_AA_OUTPUT") == NULL) snprintf(g_output_from, sizeof g_output_from, "%s", from);
        }
        for (i = 0; keys[i] != NULL; ++i)
            if (strcmp(line, keys[i]) == 0) (void)setenv(line, eq + 1, 0);
    }
    fclose(f);
}

static void load_conf(const char *path) { load_keys(path, CONF_KEYS, "feeder.conf"); }

/* ---------------------------------------------------------------- statistics */

typedef struct {
    uint64_t t_start_us, t_first_frame_us;
    unsigned long frames, idrs, b_slices, dropped_big, dropped_unparsed, ring_writes, avcc_writes;
    unsigned long bytes_in, max_idr, max_p, sum_p, p_count;
    uint64_t last_idr_us, idr_gap_min, idr_gap_max, idr_gap_sum;
    unsigned long idr_gaps;
    unsigned long sec_bytes, sec_max_bytes; uint64_t sec_start_us;
    unsigned long acks_sent, ack_delayed, ack_delay_max_ms;
    int sps_ok, profile, constraints, level, width, height, refs, poc_type, frame_mbs_only, vui;
    int cabac, pps_ok;
    char most_state[64], last_error[96];
    int dmdt_release_rc, dmdt_restore_rc;
    long bridge_pid;
    unsigned long kf_bridge, kf_take, kf_sent, kf_skipped, kf_failed, kf_idr_ms_last, kf_idr_ms_max, kf_no_idr;
    unsigned long kf_ignored;                  /* v10: bridge requests not passed on */
    unsigned long take_wait_ms;
    char take_wait_reason[40];
    char ring_file[48];                        /* v8: what happened to an existing ring file */
    uint64_t t_taken_us;                       /* MOST taken (ring ready) */
    unsigned long idr_log_ms[IDR_LOG_MAX], idr_log_bytes[IDR_LOG_MAX], idr_logged;
    unsigned long sync_state;                  /* 0 off/not yet, 1 holding, 2 done */
    unsigned long sync_repeats, sync_held, sync_hold_ms, sync_overflow;
    /* v9 */
    unsigned long pace_delayed, pace_wait_max_ms, pace_q_hi, pace_overflow;
    unsigned long pace_drain;                 /* v10: frames out over the byte budget to drain the queue */
    uint64_t last_frame_us, gap_max_us, gap_max_at_us;
    int stall_logged;                    /* v13: this gap already noted at 3 s */
    unsigned long gaps_1s, gaps_3s;
    unsigned long win[WIN_N], win_kb[WIN_N];  /* frames / KB per 10 s window, circular */
    uint64_t win_no;                          /* absolute number of the current window, from the first frame */
    unsigned long big_n, big_log_s[BIG_LOG_MAX], big_log_kb[BIG_LOG_MAX];
    /* v11 direct output */
    unsigned long hold_n, hold_ms_max, hold_ms_sum, acks_held, ack_forced, put_waits, put_wait_ms_max, put_err;
    unsigned long reclaims, reclaim_fail, reclaim_idr, reclaim_last_s;   /* v15 */
    uint64_t wr_max_logged;
    int poll_off_logged, first_block_logged;
    /* v11 capture: 0 off, 1 recording (from the first frame), 2 being written, 3 written (cap_rc 0 or errno) */
    int cap_state, cap_rc;
    unsigned long cap_aus, cap_bytes, cap_s;
    unsigned long cap_free_kb, cap_written_kb;  /* v12: free space found before the write, what was written */
    int cap_cut;                                /* v12: cut to the free space */
} stats_t;

static stats_t S;

static void set_error(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(S.last_error, sizeof S.last_error, fmt, ap);
    va_end(ap);
}

/* <rundir>/name */
static const char *run_path(char *buf, size_t n, const char *name)
{
    snprintf(buf, n, "%s/%s", g_run_dir, name);
    return buf;
}

/* Copies a small text file into the status, each line prefixed. */
static void copy_lines(FILE *f, const char *path, const char *prefix)
{
    char line[256];
    FILE *in = fopen(path, "r");
    if (in == NULL) return;
    while (fgets(line, (int)sizeof line, in) != NULL) {
        line[strcspn(line, "\r\n")] = '\0';
        fprintf(f, "%s%s\n", prefix, line);
    }
    fclose(in);
}

/* v9: moves the 10 s windows on to the one holding t (empty windows count 0). */
static void win_advance(uint64_t t)
{
    uint64_t w;
    if (S.t_first_frame_us == 0u || t < S.t_first_frame_us) return;
    w = (t - S.t_first_frame_us) / WIN_US;
    if (w <= S.win_no) return;
    if (w - S.win_no >= WIN_N) { memset(S.win, 0, sizeof S.win); memset(S.win_kb, 0, sizeof S.win_kb); }
    else while (S.win_no < w) { S.win_no++; S.win[S.win_no % WIN_N] = 0; S.win_kb[S.win_no % WIN_N] = 0; }
    S.win_no = w;
}

/* Seconds since the MOST takeover (or the start, in analysis). */
static unsigned long since_take_s(uint64_t t)
{
    uint64_t base = S.t_taken_us ? S.t_taken_us : S.t_start_us;
    return t > base ? (unsigned long)((t - base) / 1000000u) : 0ul;
}

static void write_status_v9(FILE *f, uint64_t t)
{
    unsigned long k, first;
    if (g_pace_bps > 0.0 || g_pace_gap_us != 0u)
        fprintf(f, "dawkowanie: %.0f kbit/s zapas %.0f KB odstep %lums opoznione=%lu czekanie max=%lums kolejka max=%lu/%u "
                "oproznianie=%lu przepelnienie=%lu\n",
                g_pace_bps * 8.0 / 1000.0, g_pace_burst / 1000.0, (unsigned long)(g_pace_gap_us / 1000u), S.pace_delayed,
                S.pace_wait_max_ms, S.pace_q_hi, PACE_MAX, S.pace_drain, S.pace_overflow);
    else
        fprintf(f, "dawkowanie: wylaczone%s\n", g_direct ? " (direct: kolejka + wstrzymane ACK)" : "");
    if (S.last_frame_us)
        fprintf(f, "przerwy: ostatnia klatka %lums temu, najdluzsza %lums (%lus po przejeciu) >1s=%lu >3s=%lu\n",
                (unsigned long)((t - S.last_frame_us) / 1000u), (unsigned long)(S.gap_max_us / 1000u),
                since_take_s(S.gap_max_at_us), S.gaps_1s, S.gaps_3s);
    if (S.t_first_frame_us) {
        win_advance(t);
        first = S.win_no + 1u > WIN_N ? (unsigned long)(S.win_no + 1u - WIN_N) : 0ul;
        fprintf(f, "klatki co 10s (od %lus, najstarsze->teraz):", (unsigned long)(first * 10u));
        for (k = first; k <= S.win_no; ++k) fprintf(f, " %lu", S.win[k % WIN_N]);
        fprintf(f, "\nKB co 10s:");
        for (k = first; k <= S.win_no; ++k) fprintf(f, " %lu", S.win_kb[k % WIN_N]);
        fprintf(f, "\n");
    }
    fprintf(f, "duze klatki >=%uKB: %lu", BIG_BYTES / 1024u, S.big_n);
    if (S.big_n) {
        unsigned long n = S.big_n < BIG_LOG_MAX ? S.big_n : BIG_LOG_MAX;
        fprintf(f, " ostatnie (s po przejeciu/KB):");
        for (k = S.big_n - n; k < S.big_n; ++k) fprintf(f, " %lu/%lu", S.big_log_s[k % BIG_LOG_MAX], S.big_log_kb[k % BIG_LOG_MAX]);
    }
    fprintf(f, "\n");
}

static void write_status_direct(FILE *f);

static void write_status(void)
{
    char pb[256];
    char tmp[256];
    FILE *f;
    uint64_t t = now_us();
    double secs = (double)(t - S.t_start_us) / 1e6;
    double fsecs = S.t_first_frame_us ? (double)(t - S.t_first_frame_us) / 1e6 : 0.0;
    snprintf(tmp, sizeof tmp, "%s.tmp", g_status_path);
    f = fopen(tmp, "w");
    if (f == NULL) return;
    fprintf(f, "PMCP AA FEEDER v%s mode=%s%s czas=%.0fs\n", FEEDER_VERSION, g_mode, g_direct ? " wyjscie=direct" : "", secs);
    if (strcmp(g_mode, "most") == 0)              /* v14: where the output came from, bad switch values ignored */
        fprintf(f, "wyjscie: %s (z: %s) zignorowane wartosci=%lu\n", g_direct ? "direct" : "bridge (ring)", g_output_from,
                g_output_ignored);
    fprintf(f, "klatki=%lu IDR=%lu fps=%.1f B-slice=%lu\n", S.frames, S.idrs,
            fsecs > 0.5 ? (double)S.frames / fsecs : 0.0, S.b_slices);
    if (S.sps_ok)
        fprintf(f, "SPS profil=%d constr=0x%02x poziom=%d %dx%d refs=%d poc=%d progr=%d vui=%d\n",
                S.profile, S.constraints, S.level, S.width, S.height, S.refs, S.poc_type,
                S.frame_mbs_only, S.vui);
    else
        fprintf(f, "SPS brak\n");
    fprintf(f, "PPS %s\n", S.pps_ok ? (S.cabac ? "CABAC" : "CAVLC") : "brak");
    if (S.idr_gaps)
        fprintf(f, "IDR co ms: min=%llu sr=%llu max=%llu\n", (unsigned long long)(S.idr_gap_min / 1000u),
                (unsigned long long)(S.idr_gap_sum / S.idr_gaps / 1000u),
                (unsigned long long)(S.idr_gap_max / 1000u));
    else
        fprintf(f, "IDR co ms: -\n");
    fprintf(f, "B max IDR=%lu P sr=%lu P max=%lu\n", S.max_idr, S.p_count ? S.sum_p / S.p_count : 0ul, S.max_p);
    fprintf(f, "kbit/s sr=%.0f max1s=%lu\n", fsecs > 0.5 ? (double)S.bytes_in * 8.0 / fsecs / 1000.0 : 0.0,
            S.sec_max_bytes * 8ul / 1000ul);
    fprintf(f, "ack=%lu opoznione=%lu max=%lums\n", S.acks_sent, S.ack_delayed, S.ack_delay_max_ms);
    fprintf(f, "odrzucone duze=%lu nieparsowalne=%lu\n", S.dropped_big, S.dropped_unparsed);
    fprintf(f, "MOST %s ring=%lu avcC=%lu straznik=%ld dmdt=%d/%d\n", S.most_state[0] ? S.most_state : "-",
            S.ring_writes, S.avcc_writes, S.bridge_pid, S.dmdt_release_rc, S.dmdt_restore_rc);
    fprintf(f, "IDR prosby (%s): bridge=%lu start=%lu wyslane=%lu pominiete=%lu bledy=%lu IDR po %lums (max %lums) bez IDR=%lu"
            " zignorowane=%lu%s\n",
            g_kf_byte == 'C' ? "config" : "focus", S.kf_bridge, S.kf_take, S.kf_sent, S.kf_skipped, S.kf_failed, S.kf_idr_ms_last,
            S.kf_idr_ms_max, S.kf_no_idr, S.kf_ignored, g_kf_bridge_on ? "" : " (prosby bridge nie ida do telefonu)");
    fprintf(f, "blad: %s\n", S.last_error[0] ? S.last_error : "-");
    if (S.ring_file[0]) fprintf(f, "plik ringu: %s\n", S.ring_file);
    if (S.take_wait_ms) fprintf(f, "czekanie przed przejeciem MOST: %lums (%s)\n", S.take_wait_ms,
                                S.take_wait_reason[0] ? S.take_wait_reason : "-");
    if (g_sync_hold_ms)
        fprintf(f, "sync startu: %s powtorki IDR=%lu wstrzymane klatki=%lu wstrzymanie=%lums przepelnienie=%lu (plan %lums co %lums)\n",
                S.sync_state == 0 ? "czeka na IDR" : (S.sync_state == 1 ? "TRWA" : "zrobiony"), S.sync_repeats, S.sync_held,
                S.sync_hold_ms, S.sync_overflow, g_sync_hold_ms, g_sync_repeat_ms);
    if (S.idr_logged) {
        unsigned long k;
        fprintf(f, "pierwsze IDR (ms po przejeciu/KB):");
        for (k = 0; k < S.idr_logged && k < IDR_LOG_MAX; ++k)
            fprintf(f, " %lu/%lu", S.idr_log_ms[k], (S.idr_log_bytes[k] + 512ul) / 1024ul);
        fprintf(f, "\n");
    }
    write_status_v9(f, t);
    if (g_direct) write_status_direct(f);         /* v11: no bridge in this mode, its old file is not shown */
    else copy_lines(f, run_path(pb, sizeof pb, "pmcp-aa-bridge.txt"), "");
    if (g_cap_s != 0u)
        fprintf(f, "nagranie: %s AU=%lu %luKB %lus (limit %lus, 6 MB) plik=%s%s errno=%d wolne=%luKB zapisane=%luKB%s\n",
                S.cap_state == 1 ? (S.cap_aus ? "TRWA" : "czeka na klatke") : S.cap_state == 2 ? "zapis" :
                (S.cap_rc == 0 ? "zapisane" : "BLAD"), S.cap_aus, S.cap_bytes / 1024ul, S.cap_s, g_cap_s, g_cap_path,
                S.cap_state == 3 && S.cap_rc != 0 ? (S.cap_rc == ENOMEM ? " (brak pamieci)" : S.cap_rc == ENOSPC ?
                " (brak miejsca)" : " (zapis nieudany)") : "", S.cap_rc, S.cap_free_kb, S.cap_written_kb,
                S.cap_cut ? " (przyciete do wolnego miejsca)" : "");
    copy_lines(f, run_path(pb, sizeof pb, "pmcp-aa-sessions.txt"), "poprzednia ");
    if (fclose(f) == 0) rename(tmp, g_status_path);
}

/* ---------------------------------------------------------------- H.264 bit reader */

typedef struct { uint8_t b[PS_MAX]; unsigned n, pos; int err; } bits_t;

/* Copy a NAL payload without its header byte and without emulation prevention bytes. */
static void bits_init(bits_t *r, const uint8_t *nal, unsigned len)
{
    unsigned i, zeros = 0;
    r->n = r->pos = 0; r->err = 0;
    for (i = 1; i < len && r->n < sizeof r->b; ++i) {
        if (zeros >= 2 && nal[i] == 3) { zeros = 0; continue; }
        zeros = nal[i] == 0 ? zeros + 1 : 0;
        r->b[r->n++] = nal[i];
    }
}

static unsigned bit1(bits_t *r)
{
    unsigned v;
    if (r->pos >= r->n * 8u) { r->err = 1; return 0; }
    v = (r->b[r->pos >> 3] >> (7u - (r->pos & 7u))) & 1u;
    r->pos++;
    return v;
}

static unsigned bitsn(bits_t *r, unsigned n)
{
    unsigned v = 0;
    while (n--) v = (v << 1) | bit1(r);
    return v;
}

static unsigned ue(bits_t *r)
{
    unsigned zeros = 0;
    while (!r->err && bit1(r) == 0) if (++zeros > 31) { r->err = 1; return 0; }
    return zeros ? ((1u << zeros) - 1u + bitsn(r, zeros)) : 0u;
}

static int se(bits_t *r)
{
    unsigned k = ue(r);
    return (k & 1u) ? (int)((k + 1u) / 2u) : -(int)(k / 2u);
}

static void skip_scaling_list(bits_t *r, unsigned size)
{
    int last = 8, next = 8;
    unsigned j;
    for (j = 0; j < size && !r->err; ++j) {
        if (next != 0) next = (last + se(r) + 256) % 256;
        last = next == 0 ? last : next;
    }
}

static void parse_sps(const uint8_t *nal, unsigned len)
{
    bits_t r;
    unsigned chroma = 1, i, w_mbs, h_map, cl = 0, cr = 0, ct = 0, cb = 0;
    bits_init(&r, nal, len);
    S.profile = (int)bitsn(&r, 8); S.constraints = (int)bitsn(&r, 8); S.level = (int)bitsn(&r, 8);
    (void)ue(&r);
    if (S.profile == 100 || S.profile == 110 || S.profile == 122 || S.profile == 244 || S.profile == 44 ||
        S.profile == 83 || S.profile == 86 || S.profile == 118 || S.profile == 128) {
        chroma = ue(&r);
        if (chroma == 3) (void)bit1(&r);
        (void)ue(&r); (void)ue(&r); (void)bit1(&r);
        if (bit1(&r))
            for (i = 0; i < (chroma != 3 ? 8u : 12u); ++i)
                if (bit1(&r)) skip_scaling_list(&r, i < 6 ? 16u : 64u);
    }
    (void)ue(&r);
    S.poc_type = (int)ue(&r);
    if (S.poc_type == 0) (void)ue(&r);
    else if (S.poc_type == 1) {
        unsigned n;
        (void)bit1(&r); (void)se(&r); (void)se(&r);
        n = ue(&r);
        for (i = 0; i < n && !r.err; ++i) (void)se(&r);
    }
    S.refs = (int)ue(&r);
    (void)bit1(&r);
    w_mbs = ue(&r) + 1u; h_map = ue(&r) + 1u;
    S.frame_mbs_only = (int)bit1(&r);
    if (!S.frame_mbs_only) (void)bit1(&r);
    (void)bit1(&r);
    if (bit1(&r)) { cl = ue(&r); cr = ue(&r); ct = ue(&r); cb = ue(&r); }
    S.vui = (int)bit1(&r);
    S.width = (int)(w_mbs * 16u - 2u * (cl + cr));
    S.height = (int)((2u - (unsigned)S.frame_mbs_only) * h_map * 16u - 2u * (2u - (unsigned)S.frame_mbs_only) * (ct + cb));
    S.sps_ok = !r.err;
    (void)chroma;
}

static void parse_pps(const uint8_t *nal, unsigned len)
{
    bits_t r;
    bits_init(&r, nal, len);
    (void)ue(&r); (void)ue(&r);
    S.cabac = (int)bit1(&r);
    S.pps_ok = !r.err;
}

/* slice_type of a VCL NAL: 0/5 P, 1/6 B, 2/7 I. -1 if unreadable. */
static int slice_type(const uint8_t *nal, unsigned len, unsigned *first_mb)
{
    bits_t r;
    unsigned t;
    bits_init(&r, nal, len < 16u ? len : 16u);
    *first_mb = ue(&r);
    t = ue(&r);
    return r.err ? -1 : (int)(t % 5u);
}

/* ---------------------------------------------------------------- ring */

static void direct_put_params(void);
static void direct_put(const uint8_t *au, unsigned len, uint32_t frame_no);

static volatile uint8_t *g_ring;
static uint32_t g_seq;
static unsigned long g_frame_no;

static inline void wr32(volatile uint8_t *p, uint32_t v) { *(volatile uint32_t *)(void *)p = v; }
static inline uint32_t rd32(const volatile uint8_t *p) { return *(const volatile uint32_t *)(const void *)p; }

static void ring_put(uint32_t type, const uint8_t *data, unsigned len, uint32_t frame_no)
{
    volatile uint8_t *slot;
    uint64_t ts = now_ntp();
    if (g_ring == NULL || len == 0u || len > RING_DATA_MAX) return;
    g_seq = g_seq + 1u == 0u ? 1u : g_seq + 1u;
    slot = g_ring + RING_HDR_SIZE + ((g_seq - 1u) & (RING_SLOTS - 1u)) * RING_SLOT_SIZE;
    wr32(slot + 0x00, 0u);
    __sync_synchronize();
    wr32(slot + 0x04, type);
    wr32(slot + 0x08, len);
    wr32(slot + 0x0c, 0u);
    wr32(slot + 0x10, frame_no);
    wr32(slot + 0x14, (uint32_t)ts);
    wr32(slot + 0x18, (uint32_t)(ts >> 32));
    memcpy((void *)(slot + 0x1c), data, len);
    __sync_synchronize();
    wr32(slot + 0x00, g_seq);
    __sync_synchronize();
    wr32(g_ring + 0x0c, g_seq);
    if (type == RING_TYPE_AVCC) S.avcc_writes++; else S.ring_writes++;
}

/* ---------------------------------------------------------------- SPS/PPS -> avcC */

static uint8_t g_sps[PS_MAX], g_pps[PS_MAX];
static unsigned g_sps_len, g_pps_len;
static int g_avcc_dirty;

static void keep_param_set(uint8_t *dst, unsigned *dst_len, const uint8_t *nal, unsigned len)
{
    if (len > PS_MAX) { set_error("SPS/PPS za dlugi %u", len); return; }
    if (len == *dst_len && memcmp(dst, nal, len) == 0) return;
    memcpy(dst, nal, len); *dst_len = len; g_avcc_dirty = 1;
}

static void send_avcc(void)
{
    uint8_t a[11u + 2u * PS_MAX];
    unsigned n = 0;
    if (!g_avcc_dirty || g_sps_len < 4u || g_pps_len == 0u) return;
    if (g_direct_on) { direct_put_params(); g_avcc_dirty = 0; return; }   /* v11: SPS/PPS go to the mux in order */
    a[n++] = 1; a[n++] = g_sps[1]; a[n++] = g_sps[2]; a[n++] = g_sps[3];
    a[n++] = 0xff;                       /* 4-byte NAL lengths */
    a[n++] = 0xe1;                       /* one SPS */
    a[n++] = (uint8_t)(g_sps_len >> 8); a[n++] = (uint8_t)g_sps_len;
    memcpy(a + n, g_sps, g_sps_len); n += g_sps_len;
    a[n++] = 1;                          /* one PPS */
    a[n++] = (uint8_t)(g_pps_len >> 8); a[n++] = (uint8_t)g_pps_len;
    memcpy(a + n, g_pps, g_pps_len); n += g_pps_len;
    ring_put(RING_TYPE_AVCC, a, n, 0u);
    g_avcc_dirty = 0;
}

/* ---------------------------------------------------------------- ACK pacing */

static int g_ack_fd = -1;
static uint64_t g_ack_due[ACK_QUEUE], g_ack_queued_at[ACK_QUEUE];
static unsigned g_ack_head, g_ack_count;
static double g_tokens;          /* bytes the bridge may still take without queueing */
static uint64_t g_tokens_t;
static double g_rate_bps, g_burst;

static void ack_connect(void)
{
    struct sockaddr_un a;
    int fd;
    if (g_ack_fd >= 0) return;
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return;
    memset(&a, 0, sizeof a);
    a.sun_family = AF_UNIX;
    strncpy(a.sun_path, g_ack_path, sizeof a.sun_path - 1u);
    if (connect(fd, (struct sockaddr *)&a, sizeof a) != 0) { close(fd); return; }
    (void)fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
    g_ack_fd = fd;
}

/* Sends every ACK due by t (UINT64_MAX: all of them, when the queue is full); delays are measured to now.
 * v11: while the direct queue is over its high-water mark (g_ack_hold) nothing goes, except for UINT64_MAX. */
static void ack_send_due(uint64_t t)
{
    uint64_t now = now_us();
    while (g_ack_count > 0u && g_ack_due[g_ack_head] <= t && (!g_ack_hold || t == UINT64_MAX)) {
        unsigned long d_ms = (unsigned long)((now - g_ack_queued_at[g_ack_head]) / 1000u);
        ack_connect();
        if (g_ack_fd >= 0) {
            uint8_t one = 1;
            ssize_t w = send(g_ack_fd, &one, 1, 0);
            if (w != 1 && errno != EAGAIN && errno != EWOULDBLOCK) { close(g_ack_fd); g_ack_fd = -1; }
            if (w == 1) S.acks_sent++;
        }
        if (d_ms > 1ul) S.ack_delayed++;
        if (d_ms > S.ack_delay_max_ms) S.ack_delay_max_ms = d_ms;
        g_ack_head = (g_ack_head + 1u) % ACK_QUEUE;
        g_ack_count--;
    }
}

/* One ACK per frame; when the frame overdraws the byte budget, the ACK waits until the budget has
 * refilled, so the phone (which only sends a few frames ahead of its ACKs) slows down. */
static void ack_schedule(unsigned bytes)
{
    uint64_t t = now_us(), due = t, last;
    unsigned idx;
    if (g_rate_bps > 0.0) {
        g_tokens += (double)(t - g_tokens_t) * g_rate_bps / 1e6;
        if (g_tokens > g_burst) g_tokens = g_burst;
        g_tokens_t = t;
        g_tokens -= (double)bytes;
        if (g_tokens < 0.0) due = t + (uint64_t)(-g_tokens * 1e6 / g_rate_bps);
    }
    if (g_ack_count == ACK_QUEUE) { if (g_ack_hold) S.ack_forced++; ack_send_due(UINT64_MAX); }
    if (g_ack_hold) S.acks_held++;              /* v11: this ACK waits for the direct queue to drain */
    last = g_ack_count ? g_ack_due[(g_ack_head + g_ack_count - 1u) % ACK_QUEUE] : 0u;
    if (due < last) due = last;
    idx = (g_ack_head + g_ack_count) % ACK_QUEUE;
    g_ack_due[idx] = due; g_ack_queued_at[idx] = t;
    g_ack_count++;
    ack_send_due(t);
}

/* ---------------------------------------------------------------- MOST takeover */

static pid_t g_guard_pid = -1;
static int g_guard_fd = -1;      /* write end; its EOF tells the guardian to give MOST back */

static int run_wait_argv(char *const argv[])
{
    pid_t pid = fork();
    int st, i;
    if (pid < 0) return -1;
    if (pid == 0) {
        int nul = open("/dev/null", O_RDWR);
        if (nul >= 0) { dup2(nul, 0); dup2(nul, 1); dup2(nul, 2); }
        unsetenv("LD_PRELOAD");
        setenv("IPL_CONFIG_DIR", "/etc/eso/production", 1);
        setenv("LD_LIBRARY_PATH", "/mnt/app/root/lib-target:/eso/lib:/mnt/app/usr/lib:/mnt/app/armle/lib:"
               "/mnt/app/armle/lib/dll:/mnt/app/armle/usr/lib", 1);
        execv(argv[0], argv);
        _exit(127);
    }
    for (i = 0; i < 300; ++i) {               /* dmdt has taken up to ~1 s on the car; give it 3 s */
        pid_t r = waitpid(pid, &st, WNOHANG);
        if (r == pid) return WIFEXITED(st) ? WEXITSTATUS(st) : -2;
        if (r < 0 && errno != EINTR) return -1;
        sleep_ms(10);
    }
    kill(pid, SIGKILL);
    (void)waitpid(pid, &st, 0);
    return -3;
}

static int dmdt(const char *a, const char *b, const char *c)
{
    char *argv[5];
    argv[0] = (char *)g_dmdt_path; argv[1] = (char *)a; argv[2] = (char *)b; argv[3] = (char *)c; argv[4] = NULL;
    return run_wait_argv(argv);
}

/* Is pid running the program named name? 1 yes, 0 no (another program: stale pid file), -1 unknown (no /proc). */
static int pid_is(long pid, const char *name)
{
    char path[64], exe[256];
    int fd, n;
    snprintf(path, sizeof path, "/proc/%ld/exefile", pid);
    if ((fd = open(path, O_RDONLY)) < 0) return -1;
    n = (int)read(fd, exe, sizeof exe - 1u);
    close(fd);
    if (n <= 0) return -1;
    exe[n] = '\0';
    return strstr(exe, name) != NULL;
}

/* A live altscreen-most-bridge other than pid `ours`? 1 yes, 0 no, -1 unknown (no /proc). */
static int other_bridge_alive(long ours)
{
    DIR *d = opendir("/proc");
    struct dirent *e;
    int seen = 0, found = 0;
    if (d == NULL) return -1;
    while (!found && (e = readdir(d)) != NULL) {
        char *end;
        long pid = strtol(e->d_name, &end, 10);
        int r;
        if (*end != '\0' || pid <= 0) continue;
        r = pid_is(pid, "altscreen-most-bridge");
        if (r >= 0) seen = 1;
        if (r == 1 && pid != ours) found = 1;
    }
    closedir(d);
    return found ? 1 : (seen ? 0 : -1);
}

static int pid_alive(const char *pidfile)
{
    char buf[32];
    long pid;
    int fd = open(pidfile, O_RDONLY), n;
    if (fd < 0) return 0;
    n = (int)read(fd, buf, sizeof buf - 1u);
    close(fd);
    if (n <= 0) return 0;
    buf[n] = '\0';
    pid = strtol(buf, NULL, 10);
    return pid > 0 && kill((pid_t)pid, 0) == 0;
}

/* Puts the stock VW map back on the cluster video output (supervisor's "oem-most-restore"). */
static void dmdt_restore(void)
{
    S.dmdt_restore_rc = dmdt("dc", "70", "33");
    if (dmdt("sc", "4", "70") != 0 && S.dmdt_restore_rc == 0) S.dmdt_restore_rc = -4;
}

/*
 * Guardian: a child that owns the bridge. It runs the bridge and waits on a pipe from the feeder;
 * when the pipe closes (feeder exits, crashes or is SIGKILLed by the hook after its 300 ms grace)
 * or the bridge exits, it stops the bridge as the supervisor does and gives MOST back to the VW
 * encoder. So the bridge can never outlive the feeder and keep writing to isoTX2.
 */
/* Bridge output, read by the guardian: counters and the last lines, rewritten to <rundir>/pmcp-aa-bridge.txt. */
typedef struct {
    unsigned long resets, idr_req, idr_resume, wait_writer, most_fail, lines;
    char last[2][160], metrics[160];
    char first[BO_FIRST][160];   /* v11: the first lines (open, devctl read-backs, start), kept for good */
    unsigned nfirst;
    char buf[512];
    unsigned len;
    int dirty;
} bridge_out_t;

static void bo_line(bridge_out_t *o, const char *l)
{
    o->lines++;
    if (o->nfirst < BO_FIRST) snprintf(o->first[o->nfirst++], sizeof o->first[0], "%s", l);
    if (strstr(l, "latency-reset")) o->resets++;
    if (strstr(l, "latency-request-idr") || strstr(l, "IDR request")) o->idr_req++;
    if (strstr(l, "resume-idr")) o->idr_resume++;
    if (strstr(l, "latency-wait-writer")) o->wait_writer++;
    if (strstr(l, "MOST write failed")) o->most_fail++;
    if (strstr(l, "bridge: metrics")) snprintf(o->metrics, sizeof o->metrics, "%s", l);
    else { memcpy(o->last[0], o->last[1], sizeof o->last[0]); snprintf(o->last[1], sizeof o->last[1], "%s", l); }
    o->dirty = 1;
}

static void bo_read(bridge_out_t *o, int fd)
{
    ssize_t n;
    unsigned i, s;
    if (fd < 0) return;
    while ((n = read(fd, o->buf + o->len, sizeof o->buf - 1u - o->len)) > 0) {
        o->len += (unsigned)n;
        for (i = 0, s = 0; i < o->len; ++i)
            if (o->buf[i] == '\n') { o->buf[i] = '\0'; bo_line(o, o->buf + s); s = i + 1u; }
        if (s > 0u) { memmove(o->buf, o->buf + s, o->len - s); o->len -= s; }
        if (o->len == sizeof o->buf - 1u) { o->buf[o->len] = '\0'; bo_line(o, o->buf); o->len = 0; }   /* overlong line */
    }
}

static void bo_write(bridge_out_t *o)
{
    char path[256], tmp[260];
    FILE *f;
    if (!o->dirty) return;
    run_path(path, sizeof path, "pmcp-aa-bridge.txt");
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    f = fopen(tmp, "w");
    if (f == NULL) return;
    fprintf(f, "bridge: reset_opoznienia=%lu prosba_idr=%lu wznow_po_idr=%lu czeka_na_zapis=%lu blad_MOST=%lu linie=%lu\n",
            o->resets, o->idr_req, o->idr_resume, o->wait_writer, o->most_fail, o->lines);
    if (o->metrics[0]) fprintf(f, "bridge metryki: %s\n", o->metrics);
    if (o->last[0][0]) fprintf(f, "bridge: %s\n", o->last[0]);
    if (o->last[1][0]) fprintf(f, "bridge: %s\n", o->last[1]);
    {
        unsigned k;
        for (k = 0; k < o->nfirst; ++k) fprintf(f, "bridge poczatek %02u: %s\n", k + 1u, o->first[k]);
    }
    if (fclose(f) == 0) rename(tmp, path);
    o->dirty = 0;
}

/*
 * Guardian: a child that owns the bridge. It runs the bridge and waits on a pipe from the feeder;
 * when the pipe closes (feeder exits, crashes or is SIGKILLed by the hook after its 300 ms grace)
 * or the bridge exits, it stops the bridge as the supervisor does and gives MOST back to the VW
 * encoder. So the bridge can never outlive the feeder and keep writing to isoTX2.
 * v4: <rundir>/pmcp-aa-guard.pid exists from the start until the dmdt restore is done, so the next session waits for
 * it; the bridge's stdout/stderr come through a pipe (bridge_out_t).
 */
static void guardian(int rfd)
{
    static bridge_out_t bo;
    pid_t b;
    int st, i, bp[2] = { -1, -1 };
    char c, gpath[256], bpath[256];
    uint64_t last_write = 0;
    signal(SIGTERM, SIG_IGN); signal(SIGINT, SIG_IGN); signal(SIGHUP, SIG_IGN); signal(SIGPIPE, SIG_IGN);
    for (i = 3; i < 256; ++i) if (i != rfd) close(i);   /* no copy of the hook's sockets may outlive the feeder */
    run_path(gpath, sizeof gpath, "pmcp-aa-guard.pid");
    run_path(bpath, sizeof bpath, "pmcp-aa-bridge.pid");
    {
        char pf[32];
        int fd = open(gpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        snprintf(pf, sizeof pf, "%ld\n", (long)getpid());
        if (fd >= 0) { (void)write(fd, pf, strlen(pf)); close(fd); }
    }
    if (g_direct) {
        /* v11 direct output: no bridge. The feeder itself writes isoTX2 and closes it before this pipe (or the kernel
         * closes both when it dies); then MOST goes back exactly as below. */
        for (;;) {                                /* blocking read: EOF when the feeder closed its end or died */
            ssize_t n = read(rfd, &c, 1);
            if (n == 0 || (n < 0 && errno != EINTR)) break;
        }
        sleep_ms(250);
        dmdt_restore();
        (void)unlink(gpath);
        _exit(0);
    }
    if (pipe(bp) != 0) { bp[0] = bp[1] = -1; }
    b = fork();
    if (b == 0) {
        int nul = open("/dev/null", O_RDWR);
        close(rfd);
        if (bp[1] >= 0) { dup2(bp[1], 1); dup2(bp[1], 2); close(bp[0]); close(bp[1]); }
        else if (nul >= 0) { dup2(nul, 1); dup2(nul, 2); }
        if (nul >= 0) { dup2(nul, 0); if (nul > 2) close(nul); }
        signal(SIGTERM, SIG_DFL); signal(SIGINT, SIG_DFL); signal(SIGHUP, SIG_DFL); signal(SIGPIPE, SIG_DFL);
        unsetenv("LD_PRELOAD");
        execl(g_bridge_path, g_bridge_path, (char *)NULL);
        _exit(127);
    }
    if (bp[1] >= 0) close(bp[1]);
    if (bp[0] >= 0) (void)fcntl(bp[0], F_SETFL, fcntl(bp[0], F_GETFL, 0) | O_NONBLOCK);
    if (b > 0) {
        char pf[64];
        int fd;
        snprintf(pf, sizeof pf, "%ld\n", (long)b);
        fd = open(bpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) { (void)write(fd, pf, strlen(pf)); close(fd); }
        (void)fcntl(rfd, F_SETFL, fcntl(rfd, F_GETFL, 0) | O_NONBLOCK);
        for (;;) {                                /* pipe EOF or bridge exit, checked every 20 ms */
            ssize_t n = read(rfd, &c, 1);
            uint64_t now = now_us();
            bo_read(&bo, bp[0]);
            if (now - last_write >= 1000000u) { bo_write(&bo); last_write = now; }
            if (n == 0 || (n < 0 && errno != EAGAIN && errno != EINTR)) break;
            if (waitpid(b, &st, WNOHANG) == b) { b = -1; break; }
            sleep_ms(20);
        }
        if (b > 0) {
            kill(b, SIGTERM);
            for (i = 0; i < 50 && waitpid(b, &st, WNOHANG) == 0; ++i) { bo_read(&bo, bp[0]); sleep_ms(20); }
            if (i == 50) {
                int fd2 = open(g_flush_dev, O_WRONLY);
                if (fd2 >= 0) { (void)write(fd2, "flush(0)\n", 9); close(fd2); }
                for (i = 0; i < 50 && waitpid(b, &st, WNOHANG) == 0; ++i) { bo_read(&bo, bp[0]); sleep_ms(20); }
                if (i == 50) { kill(b, SIGKILL); (void)waitpid(b, &st, 0); }
            }
        }
        bo_read(&bo, bp[0]);
        bo.dirty = 1;
        bo_write(&bo);
        (void)unlink(bpath);
    }
    sleep_ms(250);
    dmdt_restore();
    (void)unlink(gpath);                          /* only now may the next session take MOST */
    _exit(0);
}

static int direct_start(void);

static void most_restore(void)
{
    int st, i;
    if (g_ring != NULL) { munmap((void *)g_ring, RING_FILE_SIZE); g_ring = NULL; }
    if (g_guard_fd >= 0) { close(g_guard_fd); g_guard_fd = -1; }
    if (g_guard_pid > 0) {                       /* short wait only: the guardian finishes on its own */
        for (i = 0; i < 10 && waitpid(g_guard_pid, &st, WNOHANG) == 0; ++i) sleep_ms(10);
        g_guard_pid = -1;
        snprintf(S.most_state, sizeof S.most_state, "oddawane (straznik)");
    }
}

/* Why MOST cannot be taken now, or NULL. */
static const char *busy_reason(void)
{
    char pb[256];
    if (access(g_cp_ready_path, F_OK) == 0 && other_bridge_alive(-1) != 0) return "bridge CarPlay";
    if (pid_alive(run_path(pb, sizeof pb, "pmcp-aa-guard.pid")) || pid_alive(run_path(pb, sizeof pb, "pmcp-aa-bridge.pid")))
        return "poprzednia sesja AA";
    return NULL;
}

/* v8: an existing ring of the right size and magic (CarPlay's, still mapped by dio_manager, or our earlier one) is
 * reused in place: last sequence and every slot sequence to 0, so the bridge (wants sequence 1) replays nothing. Unlinking
 * it would leave its 16 MB used while mapped and the new ring would not fit on /ramdisk. Anything else: unlinked. */
static int ring_prepare(void)
{
    struct stat sb;
    int fd = open(g_ring_path, O_RDWR);
    if (fd < 0) {
        if (errno == ENOENT) { snprintf(S.ring_file, sizeof S.ring_file, "nowy"); return 0; }
        set_error("open ring errno=%d", errno); return -1;
    }
    if (fstat(fd, &sb) == 0 && (unsigned long)sb.st_size == RING_FILE_SIZE) {
        void *m = mmap(NULL, RING_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if (m != MAP_FAILED) {
            volatile uint8_t *r = (volatile uint8_t *)m;
            if (rd32(r) == RING_MAGIC && rd32(r + 4) == RING_VERSION) {
                unsigned i;
                for (i = 0; i < RING_SLOTS; ++i) wr32(r + RING_HDR_SIZE + (size_t)i * RING_SLOT_SIZE, 0u);
                wr32(r + 0x0c, 0u);
                (void)msync(m, RING_FILE_SIZE, MS_SYNC);
                munmap(m, RING_FILE_SIZE);
                close(fd);
                snprintf(S.ring_file, sizeof S.ring_file, "uzyty ponownie (wyzerowany, bez usuwania)");
                return 0;
            }
            munmap(m, RING_FILE_SIZE);
        }
    }
    close(fd);
    if (unlink(g_ring_path) != 0 && errno != ENOENT) { set_error("unlink ring errno=%d", errno); return -1; }
    snprintf(S.ring_file, sizeof S.ring_file, "inny rozmiar/magic: usuniety");
    return 0;
}

/* Called once at start in "most" mode, before the stream connects (v3). Leaves everything as it was on any failure. */
static int most_take(void)
{
    int fd, i, rc, p[2];
    const char *busy;
    uint64_t t0 = now_us();
    /* Our previous session's guardian may still be stopping its bridge / restoring MOST: wait for it (v4). CarPlay's
     * supervisor or bridge: never fight it, but wait a while for it to go (v7). The hook does not grant the phone
     * before we connect, so nothing streams meanwhile. */
    uint64_t last_st = 0;
    while ((busy = busy_reason()) != NULL && !g_stop) {
        unsigned long lim = strcmp(busy, "poprzednia sesja AA") == 0 ? g_wait_ms : g_cp_wait_ms;
        uint64_t t = now_us();
        if (t - t0 >= (uint64_t)lim * 1000u) break;
        snprintf(S.take_wait_reason, sizeof S.take_wait_reason, "%s", busy);
        if (t - last_st >= 1000000u) {
            S.take_wait_ms = (unsigned long)((t - t0) / 1000u);
            snprintf(S.most_state, sizeof S.most_state, "czeka (%s)", busy);
            write_status(); last_st = t;
        }
        sleep_ms(100);
    }
    S.take_wait_ms = (unsigned long)((now_us() - t0) / 1000u);
    if (busy != NULL) {
        snprintf(S.most_state, sizeof S.most_state, "zajety (%s)", busy);
        return -1;
    }
    if (!g_direct) {                            /* v11: direct output needs no bridge and no ring */
        if (access(g_bridge_path, X_OK) != 0) { set_error("brak bridge %s", g_bridge_path); return -1; }
        /* A ring left by an earlier session (ours or CarPlay's) is reset in place, never unlinked while it may be mapped (v8). */
        if (ring_prepare() != 0) return -1;
        (void)unlink(g_kf_req_path);            /* a request left by an earlier bridge is not ours */
    }
    if (pipe(p) != 0) { set_error("pipe errno=%d", errno); return -1; }
    rc = dmdt("dc", "72", NULL);
    S.dmdt_release_rc = rc != 0 ? rc : dmdt("sc", "4", "72");
    if (rc != 0 || S.dmdt_release_rc != 0) {
        set_error("dmdt release rc=%d", S.dmdt_release_rc);
        close(p[0]); close(p[1]);
        dmdt_restore();                           /* the first call may have gone through */
        return -1;
    }
    sleep_ms(500);
    g_guard_pid = fork();
    if (g_guard_pid == 0) { close(p[1]); guardian(p[0]); }
    close(p[0]);
    if (g_guard_pid < 0) { set_error("fork straznik errno=%d", errno); close(p[1]); dmdt_restore(); return -1; }
    g_guard_fd = p[1];
    (void)fcntl(g_guard_fd, F_SETFD, FD_CLOEXEC);
    S.bridge_pid = (long)g_guard_pid;
    if (g_direct) return direct_start();        /* v11: open isoTX2 here, the guardian holds no device */
    for (i = 0; i < 300 && !g_stop; ++i) {     /* the bridge creates and initialises the ring */
        int st;
        if (waitpid(g_guard_pid, &st, WNOHANG) == g_guard_pid) {
            g_guard_pid = -1; set_error("bridge wyszedl przy starcie"); most_restore(); return -1;
        }
        fd = open(g_ring_path, O_RDWR);
        if (fd >= 0) {
            struct stat sb;
            if (fstat(fd, &sb) == 0 && (unsigned long)sb.st_size == RING_FILE_SIZE) {
                void *m = mmap(NULL, RING_FILE_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
                if (m != MAP_FAILED) {
                    if (rd32((volatile uint8_t *)m) == RING_MAGIC && rd32((volatile uint8_t *)m + 4) == RING_VERSION) {
                        close(fd);
                        g_ring = (volatile uint8_t *)m;
                        g_seq = rd32(g_ring + 0x0c);
                        g_avcc_dirty = 1;
                        snprintf(S.most_state, sizeof S.most_state, "przejety gen=%u", (unsigned)rd32(g_ring + 8));
                        S.t_taken_us = now_us();
                        if (g_kf_take_ms != 0u) g_kf_take_due = now_us() + (uint64_t)g_kf_take_ms * 1000u;
                        return 0;
                    }
                    munmap(m, RING_FILE_SIZE);
                }
            }
            close(fd);
        }
        sleep_ms(10);
    }
    set_error("ring bridge nie gotowy");
    most_restore();
    return -1;
}

/* ---------------------------------------------------------------- fresh IDR (v2) */

/* Sends 'K' on the ACK pipe: the patched hook cycles the focus and the phone restarts with an IDR. */
static void kf_send(uint64_t t)
{
    uint8_t k = g_kf_byte;
    if (g_kf_last_us != 0u && t - g_kf_last_us < (uint64_t)g_kf_min_ms * 1000u) { S.kf_skipped++; return; }
    ack_connect();
    if (g_ack_fd >= 0 && send(g_ack_fd, &k, 1, 0) == 1) {
        S.kf_sent++;
        g_kf_last_us = t;
        if (g_kf_waiting) S.kf_no_idr++;      /* the previous request brought no IDR before this one */
        g_kf_waiting = 1;
    } else {
        S.kf_failed++;
    }
}

/* Main loop, every pass (at most 200 ms apart): the bridge's request file and the one after the takeover. */
static void kf_poll(uint64_t t)
{
    static uint64_t last_check;
    if (g_ring == NULL) return;
    if (t - last_check >= 100000u && (last_check = t, access(g_kf_req_path, F_OK) == 0)) {
        (void)unlink(g_kf_req_path);
        S.kf_bridge++;
        if (g_kf_bridge_on) kf_send(t); else S.kf_ignored++;   /* v10: no focus cycle for the bridge by default */
    }
    if (g_kf_take_due != 0u && t >= g_kf_take_due) {
        g_kf_take_due = 0u;
        S.kf_take++;
        kf_send(t);
    }
}

/* ---------------------------------------------------------------- access units */

static uint8_t g_in[IN_BUF_MAX];
static unsigned g_in_len;
static uint8_t g_au_ring[AU_MAX];
static uint8_t *g_au = g_au_ring;           /* v11 direct: AU_BUF_MAX bytes from malloc */
static int g_most_failed;

typedef struct { unsigned off, len; } nal_t;

/* Start code at p[i]? Returns its length (3 or 4) or 0. */
static unsigned start_code_at(const uint8_t *p, unsigned i, unsigned n)
{
    if (i + 3u <= n && p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 1) return 3u;
    if (i + 4u <= n && p[i] == 0 && p[i + 1] == 0 && p[i + 2] == 0 && p[i + 3] == 1) return 4u;
    return 0u;
}

/* ---------------------------------------------------------------- v11 direct output */

/* MOST events (open, devctl read-backs, first block, slow writes, errors): the first EV_FIRST kept for good, then the
 * last EV_LAST, all shown in the status. */
static char g_ev_first[EV_FIRST][120], g_ev_last[EV_LAST][120];
static unsigned g_ev_nfirst;
static unsigned long g_ev_nlast;

static void ev_log(const char *fmt, ...)
{
    char line[120];
    va_list ap;
    unsigned long ms = (unsigned long)((now_us() - S.t_start_us) / 1000u);
    int k = snprintf(line, sizeof line, "%lu.%03lus ", ms / 1000ul, ms % 1000ul);
    if (k < 0 || k >= (int)sizeof line) k = 0;
    va_start(ap, fmt);
    vsnprintf(line + k, sizeof line - (size_t)k, fmt, ap);
    va_end(ap);
    if (g_ev_nfirst < EV_FIRST) memcpy(g_ev_first[g_ev_nfirst++], line, sizeof line);
    else memcpy(g_ev_last[g_ev_nlast++ % EV_LAST], line, sizeof line);
}

/* ACK hold with hysteresis: on over g_ack_high queued TS packets, off under g_ack_low (or when the output is gone). */
static void direct_hold_update(uint64_t t)
{
    uint32_t pk = 0;
    if (g_direct_on) ts_mux_depth(&g_mux, &pk, NULL);
    if (!g_ack_hold && g_direct_on && pk > g_ack_high) {
        g_ack_hold = 1;
        g_hold_t0 = t;
        S.hold_n++;
        S.acks_held += g_ack_count;               /* the ACKs already waiting now wait for the drain too */
        ev_log("ACK wstrzymane: kolejka %u pakietow > %lu, ACK czeka %u", (unsigned)pk, g_ack_high, (unsigned)g_ack_count);
    } else if (g_ack_hold && (!g_direct_on || pk < g_ack_low)) {
        unsigned long ms = (unsigned long)((t - g_hold_t0) / 1000u);
        g_ack_hold = 0;
        S.hold_ms_sum += ms;
        if (ms > S.hold_ms_max) S.hold_ms_max = ms;
        ev_log("ACK puszczone po %lums (kolejka %u pakietow)", ms, (unsigned)pk);
    }
}

/* The queue has no room for the next AU (never expected: 8 MB by default): wait for the writer. 0 = give up. */
static int direct_wait_room(void)
{
    most_stats_t ms;
    if (g_stop) return 0;
    most_snapshot(&g_mw, &ms);
    if (ms.failed || ms.done) return 0;
    sleep_ms(2);
    return 1;
}

static void direct_put_params(void)
{
    int r;
    while ((r = ts_mux_put_params(&g_mux, g_sps, g_sps_len, g_pps, g_pps_len)) == -1 && direct_wait_room()) {}
    if (r == 0) S.avcc_writes++;
    else { S.put_err++; set_error("SPS/PPS do kolejki r=%d", r); }
}

/* One frame (AVCC, as for the ring) into the TS queue, whole; the hold is updated before its ACK is scheduled. */
static void direct_put(const uint8_t *au, unsigned len, uint32_t frame_no)
{
    uint64_t t0 = now_us();
    int r, waited = 0;
    while ((r = ts_mux_put_avcc(&g_mux, au, len, 0, now_us(), frame_no)) == -1) {
        if (!waited) { waited = 1; S.put_waits++; }
        if (!direct_wait_room()) break;
    }
    if (waited) {
        unsigned long ms = (unsigned long)((now_us() - t0) / 1000u);
        if (ms > S.put_wait_ms_max) S.put_wait_ms_max = ms;
    }
    if (r == 0) S.ring_writes++;
    else { S.put_err++; set_error("klatka do kolejki r=%d len=%u", r, len); }
    direct_hold_update(now_us());
}

/* Is a MOST output (ring or direct) taking frames? */
static int out_on(void)
{
    return g_ring != NULL || g_direct_on;
}

static void out_frame(const uint8_t *au, unsigned len, uint32_t frame_no)
{
    if (g_direct_on) direct_put(au, len, frame_no);
    else ring_put(RING_TYPE_FRAME, au, len, frame_no);
}

/* Called by most_take after dmdt released MOST and the guardian runs: queue, isoTX2, writer thread. */
static int direct_start(void)
{
    if (g_au == g_au_ring) { set_error("brak pamieci na klatki"); most_restore(); return -1; }
    if (ts_mux_init(&g_mux, (uint32_t)(g_queue_kb * 1024u), MUX_ENTRIES, &g_mux_cfg) != 0) {
        set_error("brak pamieci na kolejke %luKB", g_queue_kb); most_restore(); return -1;
    }
    if (most_open(&g_mw, &g_mw_cfg) != 0) {
        if (g_mw.dev.open_errno) ev_log("open %s blad errno=%d", g_mw_cfg.dev, g_mw.dev.open_errno);
        else ev_log("start status=%d: MOST nie ruszyl", g_mw.dev.start_rc);
        set_error("isoTX2 open errno=%d start=%d", g_mw.dev.open_errno, g_mw.dev.start_rc);
        most_restore();
        return -1;
    }
    ev_log("open %s ok (oczekiwanie %s)", g_mw_cfg.dev, most_wait_name(g_mw_cfg.wait));
    ev_log("devctl interfejs status=%d wartosc=%u", g_mw.dev.iface_rc, (unsigned)g_mw.dev.iface);
    ev_log("devctl rozmiar-pakietu status=%d wartosc=%u", g_mw.dev.packet_rc, (unsigned)g_mw.dev.packet_size);
    ev_log("devctl liczba-blokow status=%d wartosc=%u", g_mw.dev.block_rc, (unsigned)g_mw.dev.block_count);
    ev_log("devctl flush status=%d", g_mw.dev.flush_rc);
    ev_log("devctl start status=%d pakiety=64", g_mw.dev.start_rc);
    if (most_start(&g_mw, &g_mux) != 0) {
        most_stop(&g_mw, 0u);
        set_error("watek zapisu errno=%d", errno);
        most_restore();
        return -1;
    }
    g_direct_on = 1;
    g_au_limit = AU_BUF_MAX;
    g_avcc_dirty = 1;
    snprintf(S.most_state, sizeof S.most_state, "przejety (direct)");
    S.t_taken_us = now_us();
    return 0;
}

/* The writer failed or stalled: MOST goes back now (device closed first, then the guardian's pipe), the session
 * goes on as analysis (every ACK at once from now on). */
static void direct_lost(const char *why)
{
    ev_log("MOST oddane: %s", why);
    most_stop(&g_mw, 0u);
    g_direct_on = 0;
    direct_hold_update(now_us());
    most_restore();
    set_error("MOST: %s", why);
    snprintf(S.most_state, sizeof S.most_state, "oddane (%s)", why);
    g_most_failed = 1;
}

static int direct_reclaim(uint64_t t, const most_stats_t *ms, const char *why);

/* Main loop: the writer's health, and the events worth keeping. */
static void direct_check(uint64_t t)
{
    most_stats_t ms;
    if (!g_direct_on) return;
    most_snapshot(&g_mw, &ms);
    if (ms.blocks && !S.first_block_logged) {
        S.first_block_logged = 1;
        ev_log("pierwszy blok zapisany %llums po starcie", (unsigned long long)(ms.first_block_us / 1000u));
    }
    if (ms.poll_off && !S.poll_off_logged) { S.poll_off_logged = 1; ev_log("poll() nic nie daje: czekanie 1 ms"); }
    if (S.last_frame_us != 0u && !S.stall_logged && t > S.last_frame_us && t - S.last_frame_us >= 3000000u) {
        uint32_t pk = 0, aus = 0;                 /* v13 (A152): what was waiting while the phone sent nothing */
        S.stall_logged = 1;
        ts_mux_depth(&g_mux, &pk, &aus);
        ev_log("brak klatek 3 s: ACK czeka %u (wstrzymane %s) kolejka %u pakietow/%u AU bloki=%llu",
               (unsigned)g_ack_count, g_ack_hold ? "TAK" : "nie", (unsigned)pk, (unsigned)aus,
               (unsigned long long)ms.blocks);
    }
    if (ms.write_us_max >= 10000u && ms.write_us_max >= 2u * S.wr_max_logged) {
        S.wr_max_logged = ms.write_us_max;
        ev_log("najdluzszy zapis %llums (blok %llu)", (unsigned long long)(ms.write_us_max / 1000u),
               (unsigned long long)ms.blocks);
    }
    if (ms.failed || ms.done) {
        char why[80];
        snprintf(why, sizeof why, "%s", ms.failed ? ms.fail_what : "zapis zakonczony");
        if (ms.failed && direct_reclaim(t, &ms, why)) return;     /* v15 */
        direct_lost(why);
        return;
    }
    if (most_write_age_us(&g_mw, t) > ((uint64_t)g_mw_cfg.stall_ms + 1000u) * 1000u) {
        most_debug_flush(g_flush_dev);            /* what the guardian does for a bridge that does not stop */
        direct_lost("zapis zawieszony");
    }
}

/* Session end: the queue drains for up to 200 ms (the hook kills the feeder 300 ms after its SIGTERM), then the
 * writer stops and isoTX2 is closed; most_restore() then lets the guardian give MOST back. */
static void direct_finish(void)
{
    uint32_t pk = 0;
    most_stats_t ms;
    if (!g_direct_on) return;
    most_stop(&g_mw, 200u);
    ts_mux_depth(&g_mux, &pk, NULL);
    most_snapshot(&g_mw, &ms);
    ev_log("koniec: blokow=%llu, w kolejce zostalo %u pakietow", (unsigned long long)ms.blocks, (unsigned)pk);
    g_direct_on = 0;
    direct_hold_update(now_us());
}

static void write_status_direct(FILE *f)
{
    ts_mux_stats_t m;
    most_stats_t w;
    uint32_t pk = 0, aus = 0;
    unsigned k;
    if (g_mux.pool == NULL) {
        fprintf(f, "wyjscie direct: nie uruchomione\n");
    } else {
        ts_mux_snapshot(&g_mux, &m);
        ts_mux_depth(&g_mux, &pk, &aus);
        most_snapshot(&g_mw, &w);
        fprintf(f, "kolejka direct: teraz=%u pakietow/%u AU max=%u pakietow/%u AU pelna=%lu czekanie max=%lums bledy=%lu\n",
                (unsigned)pk, (unsigned)aus, (unsigned)m.queue_packets_hi, (unsigned)m.queue_aus_hi, S.put_waits,
                S.put_wait_ms_max, S.put_err);
        fprintf(f, "ACK wstrzymane: teraz=%u (%s) razy=%lu ACK=%lu najdluzej=%lums razem=%lums wymuszone=%lu progi=%lu/%lu pakietow\n",
                g_ack_hold ? g_ack_count : 0u, g_ack_hold ? "TRWA" : "nie", S.hold_n, S.acks_held, S.hold_ms_max,
                S.hold_ms_sum, S.ack_forced, g_ack_high, g_ack_low);
        fprintf(f, "zapis MOST: bloki=%llu EAGAIN=%llu poll=%llu poll_falszywe=%llu sny=%llu (pierwszy %uus: %llu) krotkie=%llu"
                " wolne>=50ms=%llu oczekiwanie=%s%s\n",
                (unsigned long long)w.blocks, (unsigned long long)w.eagain, (unsigned long long)w.polls,
                (unsigned long long)w.poll_ready_false, (unsigned long long)w.sleeps, g_mw_cfg.first_sleep_us,
                (unsigned long long)w.long_sleeps, (unsigned long long)w.short_writes,
                (unsigned long long)w.slow_writes, most_wait_name(g_mw_cfg.wait), w.poll_off ? " (poll wylaczony)" : "");
        fprintf(f, "ponowne przejecie MOST: proby=%lu nieudane=%lu IDR_ponownie=%lu ostatnie=%lus (okno %lus od startu radia, maks %lu)\n",
                S.reclaims, S.reclaim_fail, S.reclaim_idr, S.reclaim_last_s, g_reclaim_s, g_reclaim_max);
        fprintf(f, "czas zapisu bloku: <5ms=%llu <10ms=%llu <30ms=%llu <50ms=%llu <100ms=%llu >=100ms=%llu max=%lluus sr=%lluus\n",
                (unsigned long long)w.hist[0], (unsigned long long)w.hist[1], (unsigned long long)w.hist[2],
                (unsigned long long)w.hist[3], (unsigned long long)w.hist[4], (unsigned long long)w.hist[5],
                (unsigned long long)w.write_us_max, (unsigned long long)(w.blocks ? w.write_us_sum / w.blocks : 0u));
        if (m.have_lead)
            fprintf(f, "PTS-PCR (90kHz): pierwszy pakiet min=%lld max=%lld ostatnio=%lld, ostatni pakiet min=%lld;"
                    " przesuniecia w gore=%llu w dol=%llu krok+1=%llu (cel %u min %u max %u)\n",
                    (long long)m.lead_first_min, (long long)m.lead_first_max, (long long)m.lead_first_last,
                    (long long)m.lead_last_min, (unsigned long long)m.pts_rebase_up, (unsigned long long)m.pts_rebase_down,
                    (unsigned long long)m.pts_forced_step, (unsigned)g_mux_cfg.lead_90k, (unsigned)g_mux_cfg.lead_min_90k,
                    (unsigned)g_mux_cfg.lead_max_90k);
        else
            fprintf(f, "PTS-PCR (90kHz): -\n");
        fprintf(f, "AU direct: przyjete=%llu wyslane=%llu kluczowe=%llu bez SPS/PPS=%llu pakiety video=%llu null=%llu niezgodne=%llu\n",
                (unsigned long long)m.aus_in, (unsigned long long)m.aus_out, (unsigned long long)m.keyframes_out,
                (unsigned long long)m.aus_without_ps, (unsigned long long)m.video_packets,
                (unsigned long long)m.null_packets, (unsigned long long)m.packet_count_mismatch);
    }
    fprintf(f, "devctl: interfejs=%u (status %d) rozmiar-pakietu=%u (status %d) liczba-blokow=%u (status %d) flush=%d start=%d"
            " urzadzenie=%s\n",
            (unsigned)g_mw.dev.iface, g_mw.dev.iface_rc, (unsigned)g_mw.dev.packet_size, g_mw.dev.packet_rc,
            (unsigned)g_mw.dev.block_count, g_mw.dev.block_rc, g_mw.dev.flush_rc, g_mw.dev.start_rc, g_mw_cfg.dev);
    for (k = 0; k < g_ev_nfirst; ++k) fprintf(f, "MOST poczatek %02u: %s\n", k + 1u, g_ev_first[k]);
    {
        unsigned long n = g_ev_nlast < EV_LAST ? g_ev_nlast : EV_LAST, j;
        for (j = g_ev_nlast - n; j < g_ev_nlast; ++j) fprintf(f, "MOST: %s\n", g_ev_last[j % EV_LAST]);
    }
}

/* ---------------------------------------------------------------- v11 capture */

/* The phone's access units for g_cap_s seconds from its first frame, in memory, then written once (from a thread,
 * so flash never stalls the stream): Annex B with an AUD first in every AU (bridge-stage0's driver splits at AUDs),
 * the codec config the hook sent before a frame in front of it, 4-byte start codes; <path>.idx has one line per AU:
 * "us_since_first bytes idr". At most CAP_MAX bytes in all. */
static uint8_t *g_cap;
static size_t g_cap_len;
static char *g_cap_idx;
static size_t g_cap_idx_len;
static uint8_t g_cap_cfg[CAP_CFG_MAX];
static unsigned g_cap_cfg_len;
static uint64_t g_cap_t0;
static pthread_t g_cap_th;
static int g_cap_th_on;

static int write_all(const char *path, const void *data, size_t n)
{
    const uint8_t *p = (const uint8_t *)data;
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return errno ? errno : -1;
    while (n > 0u) {
        ssize_t w = write(fd, p, n);
        if (w < 0 && errno == EINTR) continue;
        if (w <= 0) { int e = errno; close(fd); return e ? e : -1; }
        p += w; n -= (size_t)w;
    }
    return close(fd) == 0 ? 0 : errno;
}

static void *cap_write(void *arg)
{
    char dir[256], idx[300];
    char *slash;
    (void)arg;
    snprintf(dir, sizeof dir, "%s", g_cap_path);
    for (slash = dir + 1; (slash = strchr(slash, '/')) != NULL; ++slash) {   /* mkdir -p of the parent */
        *slash = '\0';
        (void)mkdir(dir, 0755);
        *slash = '/';
    }
    snprintf(idx, sizeof idx, "%s.idx", g_cap_path);
    {   /* never fill the persistent partition: CAP_RESERVE must stay free. v12: in the car (A147) the whole 6 MB did
         * not fit with v11's 16 MB reserve, so the capture is cut at an AU boundary to what fits (at least 256 KB) */
        struct statvfs v;
        *strrchr(dir, '/') = '\0';
        if (statvfs(dir, &v) == 0) {
            uint64_t fr = (uint64_t)v.f_bavail * v.f_frsize;
            uint64_t room = fr > CAP_RESERVE ? fr - CAP_RESERVE : 0u;
            S.cap_free_kb = (unsigned long)(fr / 1024u);
            if (room < (uint64_t)g_cap_len + g_cap_idx_len) {
                size_t len = 0u, il = 0u;
                while (il < g_cap_idx_len) {          /* "us bytes idr\n" per AU */
                    unsigned long long us; unsigned b; int idr;
                    char *nl = memchr(g_cap_idx + il, '\n', g_cap_idx_len - il);
                    if (nl == NULL || sscanf(g_cap_idx + il, "%llu %u %d", &us, &b, &idr) != 3) break;
                    if ((uint64_t)len + b + (size_t)(nl + 1 - g_cap_idx) > room) break;
                    len += b; il = (size_t)(nl + 1 - g_cap_idx);
                }
                if (len < CAP_MIN) { S.cap_rc = ENOSPC; S.cap_state = 3; return NULL; }
                g_cap_len = len; g_cap_idx_len = il;
                S.cap_cut = 1;
            }
        }
    }
    S.cap_rc = write_all(g_cap_path, g_cap, g_cap_len);
    if (S.cap_rc == 0) S.cap_rc = write_all(idx, g_cap_idx, g_cap_idx_len);
    if (S.cap_rc == 0) S.cap_written_kb = (unsigned long)(g_cap_len / 1024u);
    S.cap_state = 3;                              /* written (cap_rc: 0 or errno) */
    return NULL;
}

static void cap_finish(int wait)
{
    if (S.cap_state != 1) return;
    S.cap_state = 2;
    if (!wait && pthread_create(&g_cap_th, NULL, cap_write, NULL) == 0) { g_cap_th_on = 1; return; }
    cap_write(NULL);
}

static void cap_put(const void *d, size_t n)
{
    memcpy(g_cap + g_cap_len, d, n);
    g_cap_len += n;
}

/* Every AU as it came from the hook (nals: its NAL units). */
static void cap_au(const uint8_t *p, const nal_t *nals, unsigned cnt, uint64_t t)
{
    static const uint8_t sc[4] = { 0, 0, 0, 1 }, aud[2] = { 0x09, 0xf0 };
    unsigned j, need = 6u + g_cap_cfg_len;
    int vcl = 0, idr = 0;
    char line[64];
    int ln;
    if (S.cap_state != 1) return;
    for (j = 0; j < cnt; ++j) {
        unsigned type = p[nals[j].off] & 0x1fu;
        if (type == 1u || type == 5u) vcl = 1;
        if (type == 5u) idr = 1;
        if (type != 9u) need += 4u + nals[j].len;
    }
    if (!vcl) {                                   /* codec config alone: goes in front of the next frame */
        for (j = 0; j < cnt; ++j) {
            if ((p[nals[j].off] & 0x1fu) == 9u || g_cap_cfg_len + 4u + nals[j].len > CAP_CFG_MAX) continue;
            memcpy(g_cap_cfg + g_cap_cfg_len, sc, 4); memcpy(g_cap_cfg + g_cap_cfg_len + 4u, p + nals[j].off, nals[j].len);
            g_cap_cfg_len += 4u + nals[j].len;
        }
        return;
    }
    if (g_cap_t0 == 0u) g_cap_t0 = t;
    if (t - g_cap_t0 > (uint64_t)g_cap_s * 1000000u) { cap_finish(0); return; }
    ln = snprintf(line, sizeof line, "%llu %u %d\n", (unsigned long long)(t - g_cap_t0), need, idr);
    if (ln < 0 || g_cap_len + need + g_cap_idx_len + (size_t)ln > CAP_MAX) { cap_finish(0); return; }
    cap_put(sc, 4); cap_put(aud, 2);
    if (g_cap_cfg_len) { cap_put(g_cap_cfg, g_cap_cfg_len); g_cap_cfg_len = 0; }
    for (j = 0; j < cnt; ++j) {
        if ((p[nals[j].off] & 0x1fu) == 9u) continue;
        cap_put(sc, 4); cap_put(p + nals[j].off, nals[j].len);
    }
    memcpy(g_cap_idx + g_cap_idx_len, line, (size_t)ln);
    g_cap_idx_len += (size_t)ln;
    S.cap_aus++;
    S.cap_bytes = (unsigned long)g_cap_len;
    S.cap_s = (unsigned long)((t - g_cap_t0) / 1000000u);
}

/* ---------------------------------------------------------------- start sync (v6) */

static uint8_t g_sync_idr_ring[AU_MAX];
static uint8_t *g_sync_idr = g_sync_idr_ring;   /* the session's first IDR as ring data (v11 direct: AU_BUF_MAX) */
static unsigned g_sync_idr_cap = AU_MAX;       /* v15: its size; direct keeps the latest IDR there after the hold */
static unsigned g_sync_idr_len;
static unsigned g_sync_idr_ack;                /* its input size, for the held ACK */
static uint64_t g_sync_until, g_sync_next, g_sync_t0;
static uint8_t g_sync_pool[SYNC_POOL];
static unsigned g_sync_pool_len;
static struct { unsigned off, len, ack; } g_sync_held[SYNC_HELD_MAX];
static unsigned g_sync_held_n;

static void ack_schedule(unsigned bytes);

/* ---------------------------------------------------------------- pacing (v9) */

static uint8_t g_pace_pool[PACE_POOL];
static unsigned g_pace_pool_len;
static struct { unsigned len, ack; uint64_t t_in; } g_pace_q[PACE_MAX];   /* in order, data packed in the pool */
static unsigned g_pace_n;
static double g_ptok;                          /* bytes of budget; may go negative after a large frame */
static uint64_t g_ptok_t;

static void drain_refill(uint64_t t)
{
    if (g_dtok_t == 0u) { g_dtok_t = t; g_dtok = g_drain_burst; return; }
    if (t > g_dtok_t) {
        g_dtok += (double)(t - g_dtok_t) * g_drain_bps / 1e6;
        if (g_dtok > g_drain_burst) g_dtok = g_drain_burst;
        g_dtok_t = t;
    }
}

static void pace_refill(uint64_t t)
{
    if (g_ptok_t == 0u) { g_ptok_t = t; g_ptok = g_pace_burst; return; }
    if (t > g_ptok_t) {
        g_ptok += (double)(t - g_ptok_t) * g_pace_bps / 1e6;
        if (g_ptok > g_pace_burst) g_ptok = g_pace_burst;
        g_ptok_t = t;
    }
}

/* One frame into the ring now, charged to the budget, then its ACK. */
static void pace_emit(const uint8_t *au, unsigned len, unsigned ack)
{
    g_pace_last_us = now_us();
    if (out_on()) out_frame(au, len, (uint32_t)++g_frame_no);   /* v11: the ring or the direct queue */
    if (g_pace_bps > 0.0) g_ptok -= (double)len;
    drain_refill(g_pace_last_us); g_dtok -= (double)len;
    ack_schedule(ack);
}

/* The oldest queued frame out. */
static void pace_pop(uint64_t t)
{
    unsigned len = g_pace_q[0].len, k;
    unsigned long w = (unsigned long)((t - g_pace_q[0].t_in) / 1000u);
    if (w > S.pace_wait_max_ms) S.pace_wait_max_ms = w;
    pace_emit(g_pace_pool, len, g_pace_q[0].ack);
    memmove(g_pace_pool, g_pace_pool + len, g_pace_pool_len - len);
    g_pace_pool_len -= len;
    for (k = 1; k < g_pace_n; ++k) g_pace_q[k - 1u] = g_pace_q[k];
    g_pace_n--;
}

/* Everything queued out at once (stream config change, end; v10: no longer for a full queue or the start hold). The budget then starts from 0, not
 * from the debt of the whole flush, or the frames after it would wait for seconds. */
static void pace_flush(void)
{
    uint64_t t = now_us();
    if (g_pace_n == 0u) return;
    while (g_pace_n > 0u) pace_pop(t);
    if (g_ptok < 0.0) g_ptok = 0.0;
}

/* v10: the gap since the last frame into the ring has passed. */
static int pace_gap_ok(uint64_t t)
{
    return g_pace_gap_us == 0u || g_pace_last_us == 0u || t >= g_pace_last_us + g_pace_gap_us;
}

/* v10: the queue is 3/4 full: drain it at the gap rate, whatever the byte budget says. */
static int pace_draining(void)
{
    return g_pace_n * 4u >= PACE_MAX * 3u || g_pace_pool_len * 4u >= PACE_POOL * 3u;
}

/* One queued frame may go now. */
static int pace_may_pop(uint64_t t)
{
    if (g_pace_n == 0u) return 0;
    if (!pace_gap_ok(t)) return 0;
    if (g_pace_bps <= 0.0 || g_ptok >= 0.0) return 1;
    if (!pace_draining()) return 0;
    drain_refill(t);
    return g_dtok >= 0.0;
}

/* Main loop: queued frames out while the budget and the gap allow (with a gap: one per pass). */
static void pace_poll(uint64_t t)
{
    if (g_pace_n == 0u) return;
    if (g_pace_bps > 0.0) pace_refill(t);
    while (pace_may_pop(t)) {
        if (g_pace_bps > 0.0 && g_ptok < 0.0) {     /* draining: the debt is capped so the queue does not stall after */
            S.pace_drain++;
            if (g_ptok < -g_pace_burst) g_ptok = -g_pace_burst;   /* the drain budget limits these */
        }
        pace_pop(t);
        if (g_pace_gap_us != 0u) break;
    }
}

/* Milliseconds until the next queued frame may go, or -1. */
static int pace_timeout_ms(uint64_t t)
{
    int ms = 0;
    if (g_pace_n == 0u) return -1;
    if (g_pace_bps > 0.0) {
        pace_refill(t);
        if (g_ptok < 0.0) {
            if (!pace_draining()) ms = (int)(-g_ptok * 1000.0 / g_pace_bps) + 1;
            else { drain_refill(t); if (g_dtok < 0.0) ms = (int)(-g_dtok * 1000.0 / g_drain_bps) + 1; }
        }
    }
    if (!pace_gap_ok(t)) {
        int g = (int)((g_pace_last_us + g_pace_gap_us - t + 999u) / 1000u);
        if (g > ms) ms = g;
    }
    return ms;
}

/* A frame (ring data + its input size for the ACK): straight out when nothing waits and the budget allows, else queued. */
static void pace_out(const uint8_t *au, unsigned len, unsigned ack)
{
    uint64_t t;
    if (g_pace_bps <= 0.0 && g_pace_gap_us == 0u) { pace_emit(au, len, ack); return; }
    t = now_us();
    if (g_pace_bps > 0.0) pace_refill(t);
    if (g_pace_n == 0u && (g_pace_bps <= 0.0 || g_ptok >= 0.0) && pace_gap_ok(t)) { pace_emit(au, len, ack); return; }
    if (g_pace_n == PACE_MAX || g_pace_pool_len + len > PACE_POOL) {
        /* v10: full: only the oldest frames needed for room go out (the gap is not kept for them), never the whole queue */
        S.pace_overflow++;
        while (g_pace_n > 0u && (g_pace_n == PACE_MAX || g_pace_pool_len + len > PACE_POOL)) pace_pop(t);
        if (g_ptok < -g_pace_burst) g_ptok = -g_pace_burst;
    }
    memcpy(g_pace_pool + g_pace_pool_len, au, len);
    g_pace_pool_len += len;
    g_pace_q[g_pace_n].len = len; g_pace_q[g_pace_n].ack = ack; g_pace_q[g_pace_n].t_in = t;
    g_pace_n++;
    S.pace_delayed++;
    if (g_pace_n > S.pace_q_hi) S.pace_q_hi = g_pace_n;
}

/* End of the hold: the held frames in order, then every held ACK (the IDR's first). */
static void sync_end(uint64_t t)
{
    unsigned k;
    if (S.sync_state != 1u) return;
    S.sync_state = 2u;
    S.sync_hold_ms = (unsigned long)((t - g_sync_t0) / 1000u);
    ack_schedule(g_sync_idr_ack);
    /* v9: the held frames in order through the pacing, each ACK when its frame goes (v6-v8: all at once) */
    for (k = 0; k < g_sync_held_n; ++k) pace_out(g_sync_pool + g_sync_held[k].off, g_sync_held[k].len, g_sync_held[k].ack);
    g_sync_held_n = 0; g_sync_pool_len = 0;
}

/* Main loop: the next copy of the IDR, or the end of the hold. */
static void sync_poll(uint64_t t)
{
    if (S.sync_state != 1u) return;
    if (!out_on() || t >= g_sync_until || g_stop) { sync_end(t); return; }
    if (t >= g_sync_next) {
        out_frame(g_sync_idr, g_sync_idr_len, (uint32_t)++g_frame_no);
        S.sync_repeats++;
        g_sync_next = t + (uint64_t)g_sync_repeat_ms * 1000u;
    }
}

/* ---------------------------------------------------------------- MOST reclaim (v15) */

/* The writer failed with errno set early after boot: take isoTX2 back as the guardian's takeover did. 1 = writing
 * again; 0 = give MOST back (direct_lost). Runs on the main loop: input waits ~1-2 s, the ACK hold covers the queue. */
static int direct_reclaim(uint64_t t, const most_stats_t *ms, const char *why)
{
    unsigned long up_s = (unsigned long)(t / 1000000u);   /* CLOCK_MONOTONIC: time since boot on QNX */
    int rc;
    if (g_reclaim_s == 0u || ms->fail_errno == 0) return 0;     /* a write error or a 5 s EAGAIN stall */
    if (up_s >= g_reclaim_s || S.reclaims >= g_reclaim_max) {
        ev_log("MOST: bez ponownego przejecia (%lus od startu radia, proby %lu/%lu)", up_s, S.reclaims, g_reclaim_max);
        return 0;
    }
    S.reclaims++;
    S.reclaim_last_s = up_s;
    ev_log("MOST zabrane (%s) %lus od startu radia: przejmuje ponownie, proba %lu/%lu", why, up_s, S.reclaims,
           g_reclaim_max);
    most_stop(&g_mw, 0u);
    rc = dmdt("dc", "72", NULL);
    if (rc == 0) rc = dmdt("sc", "4", "72");
    sleep_ms(500);
    if (rc != 0 || most_reopen(&g_mw) != 0) {
        ev_log("ponowne przejecie nieudane: dmdt=%d open errno=%d start=%d", rc, g_mw.dev.open_errno, g_mw.dev.start_rc);
        S.reclaim_fail++;
        return 0;
    }
    ts_mux_discontinuity(&g_mux);
    if (most_start(&g_mw, &g_mux) != 0) {
        most_stop(&g_mw, 0u);
        ev_log("ponowne przejecie nieudane: watek zapisu errno=%d", errno);
        S.reclaim_fail++;
        return 0;
    }
    g_avcc_dirty = 1;
    send_avcc();                                  /* SPS/PPS first, then the picture to decode from */
    if (g_sync_idr_len != 0u && S.sync_state != 1u) {
        out_frame(g_sync_idr, g_sync_idr_len, (uint32_t)++g_frame_no);
        S.reclaim_idr++;
    }
    snprintf(S.most_state, sizeof S.most_state, "przejety ponownie (direct)");
    ev_log("MOST znowu nasze po %lums (IDR ponownie: %s)", (unsigned long)((now_us() - t) / 1000u),
           g_sync_idr_len != 0u && S.sync_state != 1u ? "tak" : "nie");
    return 1;
}

/* Milliseconds until the next sync event, or -1. */
static int sync_timeout_ms(uint64_t t)
{
    uint64_t d;
    if (S.sync_state != 1u) return -1;
    d = g_sync_next < g_sync_until ? g_sync_next : g_sync_until;
    return d > t ? (int)((d - t + 999u) / 1000u) : 0;
}

/* A frame during the hold waits here; returns 0 when the pool is full (then the hold ends first). */
static int sync_hold_frame(const uint8_t *au, unsigned len, unsigned ack)
{
    if (g_sync_held_n == SYNC_HELD_MAX || g_sync_pool_len + len > SYNC_POOL) return 0;
    memcpy(g_sync_pool + g_sync_pool_len, au, len);
    g_sync_held[g_sync_held_n].off = g_sync_pool_len;
    g_sync_held[g_sync_held_n].len = len;
    g_sync_held[g_sync_held_n].ack = ack;
    g_sync_held_n++; g_sync_pool_len += len;
    S.sync_held++;
    return 1;
}

/* Turns one access unit (Annex B, possibly with AUD/SPS/PPS) into ring data. */
static void handle_au(const uint8_t *p, unsigned n)
{
    nal_t nals[64];
    unsigned cnt = 0, i = 0, j, out = 0, sc;
    int is_idr = 0, has_vcl = 0;
    uint64_t t = now_us();
    while (i < n && (sc = start_code_at(p, i, n)) == 0u) ++i;
    while (i < n && cnt < 64u) {
        unsigned start = i + sc, end = start;
        while (end < n && start_code_at(p, end, n) == 0u) ++end;
        sc = end < n ? start_code_at(p, end, n) : 0u;
        j = end;
        while (j > start && p[j - 1] == 0) --j;   /* trailing_zero_8bits belong to no NAL */
        if (j > start) { nals[cnt].off = start; nals[cnt].len = j - start; cnt++; }
        i = end;
    }
    if (S.cap_state == 1) cap_au(p, nals, cnt, t);   /* v11: the phone's AU as it came, before any limit */
    for (j = 0; j < cnt; ++j) {
        const uint8_t *nal = p + nals[j].off;
        unsigned len = nals[j].len, type = nal[0] & 0x1fu, first_mb;
        int st;
        if (type == 7u) { keep_param_set(g_sps, &g_sps_len, nal, len); parse_sps(nal, len); continue; }
        if (type == 8u) { keep_param_set(g_pps, &g_pps_len, nal, len); parse_pps(nal, len); continue; }
        if (type == 9u) continue;
        if (type == 5u) is_idr = 1;
        if (type == 1u || type == 5u) {
            has_vcl = 1;
            st = slice_type(nal, len, &first_mb);
            if (st == 1) S.b_slices++;
        }
        if (out + 4u + len > g_au_limit) {
            S.dropped_big++;
            if (g_au_limit == RING_DATA_MAX) set_error("klatka > 256 KB"); else set_error("klatka > %u KB", g_au_limit / 1024u);
            return;
        }
        g_au[out++] = (uint8_t)(len >> 24); g_au[out++] = (uint8_t)(len >> 16);
        g_au[out++] = (uint8_t)(len >> 8); g_au[out++] = (uint8_t)len;
        memcpy(g_au + out, nal, len); out += len;
    }
    if (!has_vcl) return;                        /* codec config only */
    S.frames++; S.bytes_in += n;
    if (S.t_first_frame_us == 0u) S.t_first_frame_us = t;
    if (t - S.sec_start_us >= 1000000u) {
        if (S.sec_bytes > S.sec_max_bytes) S.sec_max_bytes = S.sec_bytes;
        S.sec_bytes = 0; S.sec_start_us = t;
    }
    S.sec_bytes += n;
    if (S.last_frame_us != 0u) {                 /* v9 gaps */
        uint64_t g = t - S.last_frame_us;
        if (g > S.gap_max_us) { S.gap_max_us = g; S.gap_max_at_us = S.last_frame_us; }
        if (g >= 1000000u) S.gaps_1s++;
        if (g >= 3000000u) S.gaps_3s++;
        if (g >= 1500000u && g_direct) ev_log("przerwa od telefonu %lums (koniec)", (unsigned long)(g / 1000u));
    }
    S.stall_logged = 0;
    S.last_frame_us = t;
    win_advance(t);
    S.win[S.win_no % WIN_N]++;
    S.win_kb[S.win_no % WIN_N] += (n + 512u) / 1024u;
    if (n >= BIG_BYTES) {
        S.big_log_s[S.big_n % BIG_LOG_MAX] = since_take_s(t);
        S.big_log_kb[S.big_n % BIG_LOG_MAX] = (n + 512u) / 1024u;
        S.big_n++;
    }
    if (is_idr) {
        S.idrs++;
        if (g_kf_waiting) {
            S.kf_idr_ms_last = (unsigned long)((t - g_kf_last_us) / 1000u);
            if (S.kf_idr_ms_last > S.kf_idr_ms_max) S.kf_idr_ms_max = S.kf_idr_ms_last;
            g_kf_waiting = 0;
        }
        if (n > S.max_idr) S.max_idr = n;
        if (S.idr_logged < IDR_LOG_MAX && S.t_taken_us != 0u) {
            S.idr_log_ms[S.idr_logged] = (unsigned long)((t - S.t_taken_us) / 1000u);
            S.idr_log_bytes[S.idr_logged] = n;
            S.idr_logged++;
        }
        if (S.last_idr_us) {
            uint64_t g = t - S.last_idr_us;
            if (S.idr_gaps == 0u || g < S.idr_gap_min) S.idr_gap_min = g;
            if (g > S.idr_gap_max) S.idr_gap_max = g;
            S.idr_gap_sum += g; S.idr_gaps++;
        }
        S.last_idr_us = t;
    } else {
        if (n > S.max_p) S.max_p = n;
        S.sum_p += n; S.p_count++;
    }
    if (is_idr && g_direct_on && S.sync_state != 1u && out <= g_sync_idr_cap) {   /* v15: for a MOST reclaim */
        memcpy(g_sync_idr, g_au, out); g_sync_idr_len = out;
    }
    if (S.sync_state == 1u) {                     /* start hold: the frame and its ACK wait */
        if (sync_hold_frame(g_au, out, n)) return;
        S.sync_overflow++;
        sync_end(t);
    }
    if (out_on()) {
        if (g_avcc_dirty) pace_flush();           /* frames before a new avcC go out first, in order */
        send_avcc();
        if (is_idr && g_sync_hold_ms != 0u && S.sync_state == 0u) {
            pace_flush();
            out_frame(g_au, out, (uint32_t)++g_frame_no);
            if (g_pace_bps > 0.0) { pace_refill(t); g_ptok -= (double)out; }
            memcpy(g_sync_idr, g_au, out); g_sync_idr_len = out; g_sync_idr_ack = n;
            g_sync_t0 = t;
            g_sync_until = t + (uint64_t)g_sync_hold_ms * 1000u;
            g_sync_next = t + (uint64_t)g_sync_repeat_ms * 1000u;
            S.sync_state = 1u;
            return;                               /* its ACK waits for the end of the hold */
        }
        pace_out(g_au, out, n);                   /* v9: maybe after the frames already waiting */
        return;
    }
    ack_schedule(n);
}

/* Is the NAL at p (after its start code) the first of a new access unit, given the current one
 * already holds a picture? AUD, SPS, PPS, SEI, or a slice with first_mb_in_slice == 0. */
static int starts_au(const uint8_t *nal, unsigned avail)
{
    unsigned type;
    if (avail < 2u) return 0;
    type = nal[0] & 0x1fu;
    if (type == 9u || type == 7u || type == 8u || type == 6u) return 1;
    if (type == 1u || type == 5u) return (nal[1] & 0x80u) != 0u;   /* ue(v) == 0 is a single '1' bit */
    return 0;
}

/* Splits g_in into access units; with flush, the tail is one too (the hook paused after it). */
static void process_input(int flush)
{
    unsigned i = 0, au_start = 0, sc;
    int au_has_vcl = 0;
    while (i < g_in_len) {
        sc = start_code_at(g_in, i, g_in_len);
        if (sc == 0u) { ++i; continue; }
        if (i + sc + 2u > g_in_len) break;                      /* header not here yet */
        {
            const uint8_t *nal = g_in + i + sc;
            unsigned type = nal[0] & 0x1fu;
            if (au_has_vcl && starts_au(nal, g_in_len - i - sc)) {
                handle_au(g_in + au_start, i - au_start);
                au_start = i; au_has_vcl = 0;
            }
            if (type == 1u || type == 5u) au_has_vcl = 1;
        }
        i += sc;
    }
    if (flush && au_has_vcl) { handle_au(g_in + au_start, g_in_len - au_start); au_start = g_in_len; }
    if (au_start > 0u) { memmove(g_in, g_in + au_start, g_in_len - au_start); g_in_len -= au_start; }
    if (g_in_len == IN_BUF_MAX) { g_in_len = 0; S.dropped_unparsed++; set_error("bufor wejscia pelny"); }
}

/* ---------------------------------------------------------------- connection */

static int connect_stream(const char *url)
{
    int fd;
    if (strncmp(url, "tcp://", 6) == 0) {
        struct sockaddr_in a;
        char host[64];
        const char *colon = strrchr(url + 6, ':');
        unsigned hl;
        int rcv = 2 * 1024 * 1024;
        if (colon == NULL || (hl = (unsigned)(colon - (url + 6))) >= sizeof host) return -1;
        memcpy(host, url + 6, hl); host[hl] = '\0';
        memset(&a, 0, sizeof a);
        a.sin_family = AF_INET;
        a.sin_port = htons((unsigned short)strtoul(colon + 1, NULL, 10));
        if (inet_pton(AF_INET, host, &a.sin_addr) != 1) return -1;
        fd = socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) return -1;
        (void)setsockopt(fd, SOL_SOCKET, SO_RCVBUF, &rcv, sizeof rcv);
        if (connect(fd, (struct sockaddr *)&a, sizeof a) != 0) { close(fd); return -1; }
    } else {
        struct sockaddr_un a;
        fd = socket(AF_UNIX, SOCK_STREAM, 0);
        if (fd < 0) return -1;
        memset(&a, 0, sizeof a);
        a.sun_family = AF_UNIX;
        strncpy(a.sun_path, url, sizeof a.sun_path - 1u);
        if (connect(fd, (struct sockaddr *)&a, sizeof a) != 0) { close(fd); return -1; }
    }
    return fd;
}

/* One line per session in <rundir>/pmcp-aa-sessions.txt, the last 10 kept (small /ramdisk). */
static void append_session(void)
{
    char path[256], tmp[260], line[1400];
    static char keep[10][1400];                  /* v13: room for the longest possible line (gcc 8 -Wformat-truncation) */
    unsigned n = 0, i;
    FILE *f;
    uint64_t t = now_us();
    double secs = (double)(t - S.t_start_us) / 1e6, fsecs = S.t_first_frame_us ? (double)(t - S.t_first_frame_us) / 1e6 : 0.0;
    run_path(path, sizeof path, "pmcp-aa-sessions.txt");
    if ((f = fopen(path, "r")) != NULL) {
        while (fgets(line, (int)sizeof line, f) != NULL) {
            line[strcspn(line, "\r\n")] = '\0';
            if (n == 10u) { for (i = 1; i < 10u; ++i) memcpy(keep[i - 1u], keep[i], sizeof keep[0]); n = 9u; }
            snprintf(keep[n++], sizeof keep[0], "%s", line);
        }
        fclose(f);
    }
    if (n == 10u) { for (i = 1; i < 10u; ++i) memcpy(keep[i - 1u], keep[i], sizeof keep[0]); n = 9u; }
    snprintf(keep[n++], sizeof keep[0], "sesja start=%.0fs czas=%.0fs klatki=%lu fps=%.1f IDR=%lu przerwa_max=%lums (>3s=%lu,"
             " ostatnia klatka %lus przed koncem) ACK=%lu wstrzymane=%lu MOST=%s blad=%s",
             (double)S.t_start_us / 1e6, secs, S.frames, fsecs > 0.5 ? (double)S.frames / fsecs : 0.0, S.idrs,
             (unsigned long)(S.gap_max_us / 1000u), S.gaps_3s,
             S.last_frame_us && t > S.last_frame_us ? (unsigned long)((t - S.last_frame_us) / 1000000u) : 0ul,
             S.acks_sent, S.hold_n, S.most_state[0] ? S.most_state : "-", S.last_error[0] ? S.last_error : "-");
    snprintf(tmp, sizeof tmp, "%s.tmp", path);
    if ((f = fopen(tmp, "w")) == NULL) return;
    for (i = 0; i < n; ++i) fprintf(f, "%s\n", keep[i]);
    if (fclose(f) == 0) rename(tmp, path);
}

static void on_signal(int sig) { (void)sig; g_stop = 1; }

int main(int argc, char **argv)
{
    const char *url = argc > 1 ? argv[1] : "tcp://127.0.0.1:12346";
    int fd = -1, i;
    uint64_t last_status = 0, last_rx = 0;
    char pidbuf[32];

    {   /* v14: an output from the environment (host tests) is checked like the files' */
        const char *o = getenv("PMCP_AA_OUTPUT");
        if (o != NULL && strcmp(o, "direct") != 0 && strcmp(o, "ring") != 0) { unsetenv("PMCP_AA_OUTPUT"); g_output_ignored++; }
        else if (o != NULL) snprintf(g_output_from, sizeof g_output_from, "srodowisko");
    }
    load_keys(env_or("PMCP_AA_CONF_EXTRA", "/mnt/persist/pmcp/aa-extra.conf"), EXTRA_KEYS, "aa-extra.conf");   /* v11: GEM switches */
    load_conf(env_or("PMCP_AA_CONF", "/mnt/app/carplaymaps/aa/feeder.conf"));
    g_mode = env_or("PMCP_AA_MODE", "analyze");
    if (strcmp(g_mode, "most") != 0) g_mode = "analyze";
    g_status_path = env_or("PMCP_AA_STATUS", "/ramdisk/pmcp-aa-feeder.txt");
    g_ring_path = env_or("PMCP_AA_RING", "/ramdisk/carplay-alt-ring.bin");
    g_bridge_path = env_or("PMCP_AA_BRIDGE", "/mnt/app/carplaymaps/altscreen-most-bridge");
    g_dmdt_path = env_or("PMCP_AA_DMDT", "/eso/bin/apps/dmdt");
    g_ack_path = env_or("PMCP_AA_ACK", "/tmp/gal_ack.sock");
    g_flush_dev = env_or("PMCP_AA_FLUSH_DEV", "/dev/mlb/debug/isoTX2");
    g_kf_req_path = env_or("PMCP_AA_KF_REQ", "/ramdisk/carplay-alt-force-idr.request");
    g_run_dir = env_or("PMCP_AA_RUNDIR", "/ramdisk");
    g_wait_ms = env_ul("PMCP_AA_WAIT_MS", 6000ul, 0ul, 20000ul);
    g_settle_ms = env_ul("PMCP_AA_SETTLE_MS", 1000ul, 0ul, 15000ul);
    g_cp_wait_ms = env_ul("PMCP_AA_CP_WAIT_MS", 20000ul, 0ul, 60000ul);
    g_cp_ready_path = env_or("PMCP_AA_CP_READY", "/ramdisk/carplay-bridge.ready");
    g_sync_hold_ms = env_ul("PMCP_AA_SYNC_HOLD_MS", 0ul, 0ul, 8000ul);           /* 0 = no start sync */
    if (strcmp(env_or("PMCP_AA_MODE", "analyze"), "most") == 0 && strcmp(env_or("PMCP_AA_OUTPUT", "ring"), "direct") == 0
        && g_sync_hold_ms != 0u)                 /* v13: direct has its own (shorter) hold; feeder.conf's is the bridge's */
        g_sync_hold_ms = env_ul("PMCP_AA_DIRECT_SYNC_HOLD_MS", 1500ul, 0ul, 8000ul);
    g_sync_repeat_ms = env_ul("PMCP_AA_SYNC_REPEAT_MS", 500ul, 100ul, 2000ul);
    g_pace_bps = (double)env_ul("PMCP_AA_PACE_KBPS", 0ul, 0ul, 20000ul) * 1000.0 / 8.0;   /* 0 = no pacing (v9) */
    g_pace_burst = (double)env_ul("PMCP_AA_PACE_BURST_KB", 64ul, 8ul, 256ul) * 1000.0;
    g_pace_gap_us = (uint64_t)env_ul("PMCP_AA_PACE_GAP_MS", 0ul, 0ul, 200ul) * 1000u;      /* 0 = no gap (v10) */
    g_drain_bps = (double)env_ul("PMCP_AA_PACE_DRAIN_KBPS", 8000ul, 500ul, 12000ul) * 1000.0 / 8.0;
    g_drain_burst = 128.0 * 1000.0;
    g_kf_bridge_on = env_ul("PMCP_AA_KF_BRIDGE", 0ul, 0ul, 1ul) == 1ul;              /* 0 = bridge request only counted */
    if (strcmp(env_or("PMCP_AA_KF_METHOD", "focus"), "config") == 0) g_kf_byte = 'C';
    g_kf_take_ms = env_ul("PMCP_AA_KF_TAKE_MS", 0ul, 0ul, 10000ul);      /* 0 = no request after the takeover */
    g_kf_min_ms = env_ul("PMCP_AA_KF_MIN_MS", 3000ul, 1000ul, 60000ul);
    /* Default budget 700 KB/s (5.6 Mbit/s) with 150 KB of burst: below the bridge's ~12 Mbit/s MOST
     * output and inside its 1024-packet (188 KB) queue. 0 = ACK on arrival. */
    g_rate_bps = (double)env_ul("PMCP_AA_RATE_KBPS", 700ul, 0ul, 4000ul) * 1000.0;
    g_burst = (double)env_ul("PMCP_AA_BURST_KB", 150ul, 16ul, 180ul) * 1000.0;
    if (strcmp(g_mode, "analyze") == 0 && getenv("PMCP_AA_RATE_KBPS") == NULL) g_rate_bps = 0.0;
    /* v11: PMCP_AA_OUTPUT=direct (only with PMCP_AA_MODE=most). The queue-based ACK hold replaces the byte budget
     * there, so the budget is off unless set explicitly. */
    g_direct = strcmp(g_mode, "most") == 0 && strcmp(env_or("PMCP_AA_OUTPUT", "ring"), "direct") == 0;
    if (g_direct) {
        const char *wait = env_or("PMCP_AA_MOST_WAIT", "auto");
        if (getenv("PMCP_AA_RATE_KBPS") == NULL) g_rate_bps = 0.0;
        g_queue_kb = env_ul("PMCP_AA_QUEUE_KB", 8192ul, 1024ul, 65536ul);
        g_ack_high = env_ul("PMCP_AA_ACK_HIGH_PKTS", 1024ul, 16ul, 65536ul);
        g_ack_low = env_ul("PMCP_AA_ACK_LOW_PKTS", 512ul, 0ul, 65536ul);
        if (g_ack_low > g_ack_high) g_ack_low = g_ack_high / 2u;
        ts_mux_default_cfg(&g_mux_cfg);
        g_mux_cfg.lead_90k = (uint32_t)env_ul("PMCP_AA_LEAD_MS", 100ul, 20ul, 1000ul) * 90u;
        g_mux_cfg.lead_min_90k = (uint32_t)env_ul("PMCP_AA_LEAD_MIN_MS", 50ul, 0ul, 1000ul) * 90u;
        g_mux_cfg.lead_max_90k = (uint32_t)env_ul("PMCP_AA_LEAD_MAX_MS", 130ul, 0ul, 10000ul) * 90u;   /* 0 = never down; v13: 130 (A152: 200 let the lead sit at ~150 ms) */
        g_mux_cfg.discontinuity_first = env_ul("PMCP_AA_DISC_FIRST", 1ul, 0ul, 1ul) == 1ul;
        g_mw_cfg.dev = env_or("PMCP_AA_MOST_DEV", "/dev/mlb/isoTX2");   /* environment only (host tests), never the file */
        g_mw_cfg.wait = strcmp(wait, "poll") == 0 ? MOST_WAIT_POLL : strcmp(wait, "sleep") == 0 ? MOST_WAIT_SLEEP :
                        strcmp(wait, "block") == 0 ? MOST_WAIT_BLOCK : MOST_WAIT_AUTO;
        g_mw_cfg.stall_ms = (unsigned)env_ul("PMCP_AA_MOST_STALL_MS", 5000ul, 500ul, 60000ul);
        /* v15: reclaim window in seconds of uptime (0 = off; the host tests set a huge one) and attempts */
        g_reclaim_s = env_ul("PMCP_AA_RECLAIM_S", 180ul, 0ul, 4000000000ul);
        g_reclaim_max = env_ul("PMCP_AA_RECLAIM_MAX", 3ul, 0ul, 10ul);
        /* v12: first sleep after an accepted block; one 12032-byte block is ~7.9 ms of MOST (A147: write sr 7884 us) */
        g_mw_cfg.first_sleep_us = (unsigned)env_ul("PMCP_AA_MOST_SLEEP_US", 6500ul, 0ul, 7500ul);
        /* v12: no v10 pacing here. It only existed to keep the mathsls bridge under its 1024-packet latency-reset;
         * our queue never drops and backpressure is the ACK hold. In the car (A147) it held 286 frames up to 405 ms. */
        g_pace_bps = 0.0;
        g_pace_gap_us = 0u;
        /* frames up to the input buffer instead of the ring's 256 KB slot; allocated only in this mode */
        {
            uint8_t *a = (uint8_t *)malloc(AU_BUF_MAX), *b = (uint8_t *)malloc(AU_BUF_MAX);
            if (a != NULL && b != NULL) { g_au = a; g_sync_idr = b; g_sync_idr_cap = AU_BUF_MAX; } else { free(a); free(b); }
        }
    }
    g_cap_s = env_ul("PMCP_AA_CAPTURE_S", 0ul, 0ul, 600ul);                       /* v11: 0 = no capture */
    g_cap_path = env_or("PMCP_AA_CAPTURE_PATH", "/mnt/persist/pmcp/aa-stream.h264");   /* environment only */
    g_tokens = g_burst;
    g_idle_ms = (unsigned)env_ul("PMCP_AA_IDLE_MS", 8ul, 2ul, 30ul);

    signal(SIGTERM, on_signal); signal(SIGINT, on_signal); signal(SIGHUP, on_signal);
    signal(SIGPIPE, SIG_IGN);
    memset(&S, 0, sizeof S);
    S.t_start_us = now_us(); g_tokens_t = S.t_start_us; S.sec_start_us = S.t_start_us;
    S.bridge_pid = -1;
    if (g_cap_s != 0u) {                          /* v11: one allocation for the whole capture */
        g_cap = (uint8_t *)malloc(CAP_MAX);
        g_cap_idx = (char *)malloc(CAP_MAX / 16u);
        if (g_cap != NULL && g_cap_idx != NULL) S.cap_state = 1;
        else { free(g_cap); free(g_cap_idx); g_cap = NULL; g_cap_idx = NULL; S.cap_rc = ENOMEM; S.cap_state = 3; }
    }
    {   /* v13 (A152): keep the full status of the last 3 sessions, prev1 newest (a lost picture is in the one before) */
        char a[280], b[280];
        int k;
        for (k = 3; k > 1; --k) {
            snprintf(a, sizeof a, "%s-prev%d", g_status_path, k - 1);
            snprintf(b, sizeof b, "%s-prev%d", g_status_path, k);
            (void)rename(a, b);
        }
        snprintf(b, sizeof b, "%s-prev1", g_status_path);
        (void)rename(g_status_path, b);
    }
    snprintf(pidbuf, sizeof pidbuf, "%ld\n", (long)getpid());
    {
        char pf[256];
        int pfd;
        snprintf(pf, sizeof pf, "%s.pid", g_status_path);
        pfd = open(pf, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (pfd >= 0) { (void)write(pfd, pidbuf, strlen(pidbuf)); close(pfd); }
    }

    /* v3: take MOST first; the hook grants the phone only once we are connected, so nothing waits for an ACK meanwhile.
     * One attempt per start; on failure the session runs as analysis (the cluster keeps the VW map). */
    if (strcmp(g_mode, "most") == 0) {
        if (most_take() != 0) g_most_failed = 1;
        else if (g_settle_ms) { write_status(); sleep_ms((unsigned)g_settle_ms); }   /* let the AID lock on first */
    }
    write_status();
    for (i = 0; i < 100 && !g_stop && (fd = connect_stream(url)) < 0; ++i) sleep_ms(50);
    if (fd < 0) { set_error("brak polaczenia %s", url); most_restore(); write_status(); return 2; }
    ack_connect();

    while (!g_stop) {
        struct pollfd pfd;
        int timeout = 200, r;
        uint64_t t = now_us();
        if (g_ack_count > 0u && !g_ack_hold) {
            uint64_t due = g_ack_due[g_ack_head];
            int ms = due > t ? (int)((due - t + 999u) / 1000u) : 0;
            if (ms < timeout) timeout = ms;
        }
        if (g_in_len > 0u && last_rx != 0u && timeout > (int)g_idle_ms) timeout = (int)g_idle_ms;
        { int st = sync_timeout_ms(t); if (st >= 0 && st < timeout) timeout = st; }
        { int pt = pace_timeout_ms(t); if (pt >= 0 && pt < timeout) timeout = pt; }
        if (g_direct_on && timeout > 20) timeout = 20;            /* v11: writer health, every 20 ms */
        if (g_ack_hold && g_ack_count > 0u && timeout > 2) timeout = 2;   /* v11: release held ACKs within 2 ms */
        pfd.fd = fd; pfd.events = POLLIN; pfd.revents = 0;
        r = poll(&pfd, 1, timeout);
        t = now_us();
        if (r > 0 && (pfd.revents & (POLLIN | POLLHUP | POLLERR))) {
            ssize_t n = recv(fd, g_in + g_in_len, IN_BUF_MAX - g_in_len, 0);
            if (n == 0 || (n < 0 && errno != EINTR && errno != EAGAIN)) { set_error("strumien zamkniety"); break; }
            if (n > 0) { g_in_len += (unsigned)n; last_rx = t; process_input(0); }
        } else if (r == 0 && g_in_len > 0u && last_rx != 0u && t - last_rx >= (uint64_t)g_idle_ms * 1000u) {
            process_input(1);
            last_rx = 0;
        }
        sync_poll(now_us());
        pace_poll(now_us());
        if (g_direct) { direct_check(now_us()); direct_hold_update(now_us()); }   /* v11 */
        ack_send_due(now_us());
        kf_poll(now_us());
        if (S.cap_state == 1 && g_cap_t0 != 0u && now_us() - g_cap_t0 > (uint64_t)g_cap_s * 1000000u) cap_finish(0);
        if (g_guard_pid > 0) {                   /* bridge gone mid-session: the guardian gave MOST back */
            int st;
            if (waitpid(g_guard_pid, &st, WNOHANG) == g_guard_pid) {
                g_guard_pid = -1;
                if (g_direct_on) {
                    /* v11: the guardian is gone, so nobody would give MOST back: stop writing and do it here */
                    direct_lost("straznik zakonczyl sie");
                    dmdt_restore();
                } else {
                    if (g_ring != NULL) { munmap((void *)g_ring, RING_FILE_SIZE); g_ring = NULL; }
                    if (g_guard_fd >= 0) { close(g_guard_fd); g_guard_fd = -1; }
                    set_error("bridge zakonczyl sie w trakcie");
                    snprintf(S.most_state, sizeof S.most_state, "oddane (bridge)");
                    g_most_failed = 1;
                }
            }
        }
        if (t - last_status >= 1000000u) { write_status(); last_status = t; }
    }
    sync_end(now_us());
    pace_flush();
    direct_finish();                              /* v11: queue drained (<= 200 ms), writer stopped, isoTX2 closed */
    ack_send_due(UINT64_MAX);
    close(fd);
    most_restore();
    cap_finish(1);                                /* v11: a capture still recording is written now */
    if (g_cap_th_on) pthread_join(g_cap_th, NULL);
    write_status();
    append_session();
    if (g_ack_fd >= 0) close(g_ack_fd);
    return 0;
}
