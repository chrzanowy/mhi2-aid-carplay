# MOST video bridge: behavioural specification

Spec version 1 (2026-11-14). Status: draft for a clean-room implementation.

## 0. Scope, words and conventions

The bridge is one process on the VW MHI2 head unit (QNX 6.5, armv7, MU1161, AID 791). It reads H.264 frames that a
producer publishes in a shared-memory ring file. It turns them into an MPEG transport stream (TS) and writes that stream
to the MOST video channel device `/dev/mlb/isoTX2`, which feeds the instrument cluster (AID). It runs under an existing
supervisor that it cannot change. It is the *consumer* of the producer/consumer contract in
`bridge/contract/pmcp_most_contract.h` (line format v=1, contract revision 1 = "v1.1"). Below that file is called **the
contract header**. Where this spec says "as the contract header defines", the header is normative and exact.

This spec covers CarPlay mode only: wired CarPlay, and Wi-Fi CarPlay through the same ring. An Android Auto variant is out
of scope (section 10).

Words:

- MUST, MUST NOT, SHOULD, MAY: as in RFC 2119.
- **Ring:** the shared file defined in section 1 of the contract header. **Slot**, **seq**, **write_sequence**,
  **generation**, **frame_no**, **ts_hi/ts_lo**, **type 1 (avcC)** and **type 2 (AVCC access unit)** have the meaning given
  there.
- **AU:** one access unit, i.e. one video frame. A type-2 slot holds one AU.
- **Keyframe:** an AU that contains at least one NAL unit of type 5 (IDR slice). Section 2.6 says how this is decided.
- **Packet:** a 188-byte TS packet. **Block:** 64 consecutive packets (12032 bytes), the unit of every device write.
- **n:** the output packet index. It counts every packet the bridge has put into blocks since the process started,
  starting at 0. It includes the packets of a block whose write later failed.
- **Transport clock T:** `T = 45000 + floor(n_next * 705 / 64)` in 90 kHz ticks. `n_next` is the index of the first packet
  of the next block not yet built. T is 45000 before the first block is built. The bridge updates T once per block, when
  that block has been built and before it is written.
- **Backlog:** the number of video packets (PID 0x0011) that have been packetised but not yet put into a block. PAT, PMT,
  PCR and null packets never count.
- **Whole-AU discard:** see R60.
- **Epoch:** a PTS time base, see section 2.7.
- **Wait-for-keyframe state:** the input side drops every AU until a keyframe arrives (R64).
- **Monotonic time:** `CLOCK_MONOTONIC`. On the unit this is the time since boot.
- Log lines are shown without the trailing newline. `%u`/`%lu`/`%llu` mean an unsigned decimal, `%d` a signed decimal and
  `%s` a string. Every log line ends with `\n`.

## 1. Process contract with the supervisor

The supervisor is the closed mathsls `carplay-cluster-supervisor`. It cannot be changed in this stage.

- **R1** The executable MUST be named `altscreen-most-bridge` and MUST run when started as
  `/mnt/app/carplaymaps/altscreen-most-bridge`, with `argv[0]` = that path and no other arguments. The supervisor uses
  `execl(path, path, NULL)`, and other tools find the process by this name.
- **R2** `argv[1]`, if present, is the output device path. Without it the device is `/dev/mlb/isoTX2`. Further arguments
  MUST be ignored.
- **R3** The bridge MUST work with stdin, stdout and stderr connected to `/dev/null`. The supervisor does exactly that.
  The bridge MUST NOT depend on any environment variable in normal operation. In particular it MUST NOT need, and MUST
  ignore, `CARPLAY_CLUSTER_INTRO` and `CARPLAY_CLUSTER_INTRO_FPS`. The environment variables of section 9 are optional
  overrides.
- **R4** SIGTERM and SIGINT MUST request a stop. After the request the bridge MUST:
  - (a) set the readiness to 0 (R100);
  - (b) close the MOST device descriptor right away, so a write blocked inside the driver returns (the supervisor relies
    on this);
  - (c) stop reading the ring;
  - (d) write the final status (R101) and the `complete` line (R108);
  - (e) exit with status 0.

  The process MUST exit within 1000 ms of the signal. The one exception is R80: a dmdt child that is already running at
  that moment may delay the exit by its own timeout.
- **R5** SIGPIPE MUST be ignored.
- **R6** Exit status:
  - 1 when start-up fails before streaming can begin: out of memory for the output buffer, cannot create, size or map
    the ring, cannot start the output stage;
  - 0 in every other case. This includes a stop request, a session stop (R88), a MOST device open or START failure
    (R37), a MOST write failure (R42) and a reclaim that is not attempted or fails (section 5).

  The supervisor logs the status but does not interpret it.
- **R7** A run without a stop request ends only through R6. The bridge MUST NOT exit while the ring is idle: no input
  for any length of time is normal, and null/PSI/PCR blocks keep flowing (R46).
- **R8** The bridge MUST NOT create, modify or delete these supervisor files:
  - `/ramdisk/carplay-bridge.ready`
  - `/ramdisk/carplay-altstream.ready`
  - `/ramdisk/carplay-dio-manager.pid`
  - `/ramdisk/carplay-cluster-supervisor.pid`
  - `/ramdisk/carplay-cluster-supervisor.log`
  - anything under `/ramdisk/carplaymaps-diagnostics/`
  - anything under `/mnt/app/carplaymaps/`

  The bridge MUST NOT write the contract's `owner` file or any `<src>.session` file. It MUST NOT delete the ring file.
- **R9** The bridge creates or changes only these files:
  - the ring file (R13, R14);
  - the IDR marker (R26);
  - the log directory `/ramdisk/pmcp-most/` and the files `bridge.log` and `bridge.log.1` in it (section 7);
  - the contract directory `/ramdisk/most-src/` (mode 0755 when it creates it), and in it `consumer` and
    `consumer.tmp.<pid>` (R97);
  - the intro once-per-boot marker (R114);
  - in file-output mode only, the output file (section 9).

  It MAY also create and lock `/ramdisk/cpmap-video-cache.lock` (section 10). It MUST NOT leave a `consumer.tmp.<pid>`
  file behind after a normal exit.
- **R10** After the process exits, no descriptor of the MOST device may remain open. The bridge MUST close it on every
  exit path.
- **R11** The ring MUST be initialised (R13) within 500 ms of process start. Before that, nothing may be written to the
  device. The first device open (R35) happens after the ring has been initialised.
- **R12** The supervisor treats a process that dies within about 750 ms of `exec` as a failed start. So the bridge MUST
  NOT exit by itself during start-up except for the reasons in R6 (status 1) and R37.

## 2. Input: the ring

### 2.1 Creation and generation

- **R13** At start the bridge MUST open the ring at `/ramdisk/carplay-alt-ring.bin` (override: section 9) with read-write
  access, creating it with mode 0666 if missing. It MUST set the file size to exactly 0x1000710 bytes and map it shared
  and read-write. Then it MUST initialise the header in this order:
  1. read the old header. If magic = 0x43505247 and version = 1, the new generation is the old generation + 1, with 0
     skipped (0 becomes 1). Otherwise the new generation is 1;
  2. store magic = 0;
  3. store version = 1, the new generation, write_sequence = 0, and seq = 0 in all 64 slots;
  4. issue a memory barrier, then store magic = 0x43505247.

  Slot payloads need not be cleared. After this the bridge MUST read from sequence W = 1.
- **R14** Apart from R13, the bridge writes the ring header only for the consumer gate's generation bump (R92). It MUST
  NOT write slots after R13.
- **R15** Log after a successful map:
  `bridge: shared ring %s bytes=%u slots=%u -> %s`. The fields are the ring path, 16779024, 64 and the device path.

### 2.2 Polling

- **R16** The bridge MUST poll the ring in passes. When a pass finds nothing to consume, the next pass MUST start within
  about 1 ms. The nominal interval is a 1 ms sleep between passes, and the latency SHOULD stay under 5 ms. A pass consumes
  every slot that is ready, in sequence order.
- **R17** At the start of a pass, if magic is not 0x43505247 or version is not 1, the bridge MUST consume nothing in that
  pass and try again at the next one. It MUST NOT re-initialise the ring.
- **R18** If the header generation differs from the generation the bridge last stored or saw, and the bridge did not
  change it itself (R92), this is a **foreign generation change**. The bridge MUST:
  - remember the new value and continue from W = 1;
  - make a whole-AU discard (R60);
  - create the IDR marker (R26);
  - enter the wait-for-keyframe state (R64);
  - set the discontinuity flag for the next AU (R53);
  - start a new epoch at the next AU (R31);
  - forget the last frame_no (R57);
  - reset the age reference (R99).

  It MUST keep the current avcC configuration. Log:
  `bridge: ring generation=%u; waiting for fresh IDR`
  If creating the marker fails, it also logs `bridge: reconnect IDR request failed: %s` with the error text.

### 2.3 Slot consumption

- **R19** For the wanted sequence W, while `W <= write_sequence` (read with acquire semantics), look at slot index
  `(W - 1) mod 64`:
  - (a) Slot seq = W: read type, size, flags, frame_no, ts_lo and ts_hi.
    - If size is 0 or greater than 0x40000: count one drop (R97 `drops`), set W = W + 1, and continue.
    - Otherwise copy size bytes of data, then read the slot seq again.
      - If it is still W: handle the slot (R20), then set W = W + 1.
      - If it changed: discard the copy and look at the same W again. The usual result is case (b).
  - (b) Slot seq > W: this is a **ring overrun**. Add `slot seq - W` to drops, add 1 to overruns, set W = slot seq, and
    continue. Log: `bridge: ring overrun wanted=%u found=%u drops=%lu`. The fields are the old W, the new W and the drops
    total.
  - (c) Slot seq < W, including 0: the slot is being written. End the pass.
- **R20** Handling by type:
  - type 1: parse it as avcC (R22);
  - type 2: process it as an AU (sections 2.5 to 2.7 and section 4);
  - any other type: count one drop.
- **R21** The bridge MUST NEVER block, lock or otherwise slow down the producer. A slow bridge loses slots through
  overruns and never stalls the ring.

### 2.4 Configuration (type 1)

- **R22** A type-1 payload is valid when all of these hold:
  - its size is at least 7 bytes and byte 0 = 1;
  - NAL length size = `(byte4 & 3) + 1`;
  - SPS count = `byte5 & 0x1f`;
  - from offset 6 there are that many SPS units, each with a 2-byte big-endian length of at least 1 that lies inside the
    payload;
  - one byte holds the PPS count, followed by that many PPS units in the same form;
  - there is at least one SPS and at least one PPS.

  Bytes after the last PPS are ignored. The bridge keeps only the first SPS and the first PPS. A valid avcC replaces the
  current configuration and is logged as
  `bridge: avcC ready length=%u sps=%u pps=%u`
  with the length size and the SPS and PPS byte counts. An invalid one counts one drop and leaves the current
  configuration unchanged.
- **R23** A new configuration by itself MUST NOT reset the stream, discard anything or change the wait state.

### 2.5 AVCC to Annex B (type 2)

- **R24** A type-2 AU is valid only when both of these hold:
  - a valid configuration exists;
  - the payload splits exactly into units of a big-endian length field of the configured size followed by that many
    bytes. Every length must be at least 1 and must not run past the end, and no bytes may be left over.

  An invalid AU counts one drop. Nothing about it is queued, and the latency logic (section 4) does not see it.
- **R25** The Annex-B form of a valid AU MUST be, in this order:
  1. `00 00 00 01 09 F0` (an access unit delimiter);
  2. only for keyframes: `00 00 00 01`, SPS, `00 00 00 01`, PPS;
  3. for every NAL unit of the AU, in order and copied verbatim (including any AUD, SPS or PPS units the producer put in
     the AU): `00 00 00 01` and the unit.

  No emulation-prevention change is made. The bridge does not parse slice data.

### 2.6 Keyframe decision and the IDR marker

- **R26** **IDR marker:** the file `/ramdisk/carplay-alt-force-idr.request` (override: section 9).
  - To request an IDR, the bridge creates it (or truncates it) empty with mode 0666, then closes it. This is idempotent.
  - To cancel a pending request, the bridge removes it with `unlink`. ENOENT is ignored.
  - The producer consumes the marker (unlink) and answers with a genuine IDR. The bridge MUST NOT wait for the marker to
    disappear.
- **R27** An AU is a keyframe if and only if its payload contains a NAL unit of type 5. Bit 0 of the slot flags is only
  advisory (contract header) and MUST NOT make an AU without a type-5 NAL a keyframe. The flag MAY be logged.
- **R28** The bridge creates the IDR marker only in these cases:
  - R18 (foreign generation change);
  - R65 (latency recovery, once per reset);
  - R94 (gate opening);
  - R116 (after the intro).

  It removes the marker in R61 (at every latency reset). No other path touches it.

### 2.7 Timestamps and PTS

- **R29** A slot timestamp is `ts = ts_hi * 2^32 + ts_lo`: NTP 32.32 seconds, not microseconds. A difference Δ (an
  unsigned 64-bit value) converts to 90 kHz ticks as:
  `ticks(Δ) = (Δ >> 32) * 90000 + (((Δ & 0xFFFFFFFF) * 90000 + 2^31) >> 32)`
  The result is rounded to the nearest tick, with halves rounded up.
- **R30** **Lead target:** `L = max(T + 9000, last_pts + 1)`. Here last_pts is the PTS of the last AU queued in this
  process, live or intro, and 0 before the first one.
- **R31** **Epoch start.** The bridge starts a new epoch at the AU being processed when any of these holds:
  - it is the first AU of the process;
  - it is the first AU after R18 or R92;
  - it is the resume keyframe of R66;
  - it is the first live AU after the intro (R116);
  - its frame_no is ≤ 2 while the last frame_no is > 100 (a producer restart);
  - its ts is non-zero, an epoch origin ts exists, and ts is below that origin (time went backwards).

  At an epoch start:
  - with a non-zero ts: origin_ts = ts and origin_pts = L;
  - with ts = 0: origin_local = the current monotonic time in µs and origin_pts = L.

  Within an epoch:
  - an AU whose ts is non-zero gets `pts = origin_pts + ticks(ts - origin_ts)`. If that epoch has no origin_ts yet,
    because it was started by ts = 0 AUs, the AU first sets origin_ts = ts and origin_pts = L;
  - an AU with ts = 0 gets `pts = origin_pts + floor((now_us - origin_local) * 90 / 1000)`. If origin_local is unset or
    in the future, it first sets origin_local = now and origin_pts = L.
- **R32** **Rebase.** After R31, if `pts < T + 4500` (T read at this moment), the bridge shifts origin_pts and pts forward
  by `L - pts` (L computed at this moment), so that pts = L. It counts one rebase and logs:
  `bridge: pts-rebase sequence=%u shift=%llu pcr=%u pts=%llu count=%lu`
  The fields are frame_no, the shift, T, the new pts and the total number of rebases.
- **R33** **Monotonic PTS.** After R32, if `pts <= last_pts`, then pts = last_pts + 1. The PTS of the AUs a process
  queues are strictly increasing. The PTS field carries pts modulo 2^33.
- **R34** Every 60th queued live AU, counting from the first (the 1st, 61st, 121st and so on), the bridge logs:
  `bridge: clock frame=%lu ntp=%llu pts=%llu step=%llu`
  The fields are the AU count including this one, ts, pts, and pts minus last_pts (0 if last_pts = 0).

## 3. Output: device, blocks and the transport stream

### 3.1 Device

- **R35** **Open sequence on the unit.** These steps run in this order, each logged with its status (the value of the
  QNX `devctl` return) and, for reads, the 32-bit value:
  1. `open(dev, O_WRONLY | O_NONBLOCK)` (64-bit offsets). On failure: `bridge: open %s failed: %s`.
  2. `devctl(fd, 0x4004050c, &u32, 4, NULL)` → `bridge: interface status=%d value=%u`
  3. `devctl(fd, 0x4004050d, &u32, 4, NULL)` → `bridge: packet-size status=%d value=%u`
  4. `devctl(fd, 0x40040510, &u32, 4, NULL)` → `bridge: block-count status=%d value=%u`
  5. `devctl(fd, 0x40040506, NULL, 0, NULL)` → `bridge: queue-flush status=%d` (any status is accepted; ENOTTY is
     normal on some units)
  6. `devctl(fd, 0x80040509, &u32 = 64, 4, NULL)` → `bridge: start status=%d packets=%u` (the value logged is 64)

  The statuses and values of steps 2 to 5 MUST NOT change behaviour. There is no stop devctl: stopping is `close(fd)`.
- **R36** MOST is **ready** only when the open succeeded and step 6 returned 0. The readiness drops to 0 as soon as the
  descriptor is closed for any reason, or a stop is requested.
- **R37** If the open fails, or step 6 returns non-zero (the bridge then closes the descriptor):
  - most_errno takes the open errno, or for a START failure SHOULD take the START status;
  - the bridge requests a stop and exits with status 0. This is also the behaviour on a reopen failure in section 5.
- **R38** The device is opened exactly once at start, plus once per reclaim (section 5). It is never opened while
  another descriptor of it is open in the process.

### 3.2 Blocks and writes

- **R39** Every write to the device carries exactly one whole block of 12032 bytes. The bridge MUST NOT write partial
  blocks on purpose and MUST NOT merge blocks into one call.
- **R40** A block write that returns a positive count less than 12032 MUST be continued with the rest of the block. EINTR
  MUST be retried at once. EAGAIN/EWOULDBLOCK MUST be retried after a sleep of about 1 ms. There is no other pacing on
  the unit: the bridge writes blocks back to back, and only the driver's back-pressure limits the rate. Nominally that is
  12.288 Mbit/s, about 8170 packets/s.
- **R41** If a stop is requested while a block write is pending (EAGAIN loop or an interrupted call), the bridge MUST
  abandon the block silently. That is not a write failure: no `MOST write failed` line, and no change to most_errno.
- **R42** Any other write error is a **write failure**. The bridge sets most_errno = errno and logs
  `bridge: MOST write failed: %s`
  with the error text. Then section 5 decides: reclaim, or stop with exit status 0. A failed block is never resent.
- **R43** Per block the bridge measures the time of the whole write, from the first call until the block is fully
  accepted, in µs. It keeps these statistics:
  - the maximum write time;
  - **slow writes**: writes of 50000 µs or more. At each one it also records the backlog at that moment;
  - a **fast streak**: the number of consecutive writes of 30000 µs or less. A slower write sets it to 0;
  - a histogram with the buckets <5000, <10000, <30000, <50000, <100000 and ≥100000 µs;
  - the total number of blocks completed.
- **R44** After every 100th completed block (counting all blocks the process completed), the bridge logs these two lines,
  then resets the histogram, the burst maxima and the slow-write backlog:
  `bridge: blocks=%lu output_bps=%llu queue=%u frames=%lu keys=%lu drops=%lu write_us=%llu write_us_max=%llu slow_writes=%lu`
  `bridge: hist_write_us=%lu,%lu,%lu,%lu,%lu,%lu burst_100ms_max_bytes=%llu burst_100ms_max_frames=%lu slow_write_queue=%lu`
  The fields:
  - output_bps: 12032 × 8 × 10^6 × (blocks since the last report) / (µs since the last report, or since the output
    stage started);
  - queue: the current backlog;
  - frames, keys, drops: the live counters;
  - write_us: the last block's write time;
  - write_us_max: the all-time maximum;
  - slow_writes: the all-time count;
  - the burst maxima: the largest number of AVCC input bytes, and of AUs, queued within one 100 ms input window since
    the last report;
  - slow_write_queue: the backlog recorded at the last slow write since the last report, or 0.
- **R45** When the output stage ends, it logs `bridge: writer stopped blocks=%lu reclaims=%u`: the completed blocks and
  the reclaim attempts.

### 3.3 Transport stream layout

- **R46** **Packet choice.** Each position n of a block holds exactly one packet, chosen by the first rule that applies:
  1. if the previous position held a PAT: the PMT;
  2. else if n ≥ next_psi: a PAT, and next_psi += 327;
  3. else if n ≥ next_pcr: a PCR packet carrying `base = 45000 + floor(n * 705 / 64)` (n of this very packet), and
     next_pcr += 327;
  4. else if the backlog is non-zero: the oldest pending video packet;
  5. else: a null packet.

  At process start next_psi = 0 and next_pcr = 2. So without a reclaim, PAT is at n ≡ 0, PMT at n ≡ 1 and PCR at n ≡ 2
  (mod 327). After a reclaim, R79 changes next_psi.
- **R47** **PAT packet** (PID 0x0000):
  - header `47 40 00 1c`, where c is the PAT continuity counter. It starts at 0 and adds 1 per PAT, mod 16;
  - pointer field `00`;
  - the section `00 b0 0d 00 01 c1 00 00 00 01 e0 10` and its CRC-32/MPEG-2 (big-endian; poly 0x04C11DB7, init
    0xFFFFFFFF, no reflection, no final XOR);
  - 0xFF up to 188 bytes.

  The section means: transport_stream_id 1, version 0, current, program 1 → PMT PID 0x0010.
- **R48** **PMT packet** (PID 0x0010):
  - header `47 40 10 1c`, with its own counter, starting at 0;
  - pointer `00`;
  - the section `02 b0 12 00 01 c1 00 00 f0 00 f0 00 1b e0 11 f0 00` and its CRC;
  - 0xFF fill.

  The section means: program 1, PCR_PID 0x1000, no program descriptors, one stream of stream_type 0x1B (H.264) on
  PID 0x0011, no ES descriptors.
- **R49** **PCR packet** (PID 0x1000): `47 10 00 20 b7 10`, then the 6 PCR bytes, then 176 × 0xFF. The PCR bytes are
  `b>>25, b>>17, b>>9, b>>1, ((b&1)<<7)|0x7E, 0x00` (each taken mod 256), with b = base mod 2^33. So the extension is 0
  and the continuity counter is always 0 (adaptation only, no payload).
- **R50** **Null packet:** `47 1f ff 1c` and 184 × 0xFF, with its own counter that adds 1 per null packet, mod 16, from 0.
- **R51** **PES** for one AU: `00 00 01 e0 00 00 80 80 05`, then the 5-byte PTS, then the Annex-B AU (R25). The PES length
  is 0 (unbounded). There is no DTS. The PTS bytes for p = pts mod 2^33 are:
  `0x21 | ((p>>30)&7)<<1`, `(p>>22)&0xFF`, `(((p>>15)&0x7F)<<1)|1`, `(p>>7)&0xFF`, `((p&0x7F)<<1)|1`.
- **R52** **Video packetisation** (PID 0x0011). The PES is cut into packets in order. Let R be the bytes still to place.
  - **First packet:** the payload is min(R, 182) bytes and the adaptation field takes A = 184 − payload bytes (so A ≥ 2).
    The header is `47 40 11 3c` (PUSI set, PID 0x0011, adaptation + payload). Then come the adaptation length A − 1, a flags byte,
    A − 2 bytes of 0xFF, and the payload. The flags byte is 0x40 (random_access) when the AU is a keyframe, OR 0x80
    (discontinuity) when R53 applies; otherwise 0x00.
  - **Every later packet:** the payload is min(R, 184) bytes.
    - With 184 bytes: header `47 00 11 1c` (payload only).
    - With fewer: header `47 00 11 3c` and A = 184 − payload. If A = 1, the adaptation field is the single byte `00`.
      If A ≥ 2, it is the length A − 1, a flags byte `00` and A − 2 bytes of 0xFF.
  - c is the video continuity counter. It adds 1 per video packet created, mod 16, starting at 0.

  An AU therefore takes `1 + ceil(max(0, P − 182) / 184)` packets, where P = 14 + the Annex-B size.
- **R53** **Discontinuity flag.** It is set on the first AU queued after each of these events, and on no other AU:
  - a latency reset (R59, including chain-gap and reclaim resets);
  - a foreign generation change (R18);
  - a gate cut (R92);
  - the start of the intro (its first AU);
  - the end of the intro (the first live AU, R116).

  It is set once per event: several events before one AU give one flag. In particular the first AU of a process started
  without an intro has no discontinuity flag. The current tools compare this byte for byte.
- **R54** **Continuity counters.**
  - PAT, PMT and null counters MUST NOT skip, ever, including across reclaims.
  - The video counter MUST NOT skip except right before an AU that carries the discontinuity flag.
  - When packets are discarded (R60), the counter values they held MAY either be skipped or be reused. Both are
    acceptable.
- **R55** **AU contiguity.** The packets of one AU go out in order. Between the first and last packet of one AU there
  may be PAT, PMT or PCR packets, but never a null packet and never a packet of another AU. Every AU starts with a PUSI
  packet. After an AU has started, the bridge MUST emit all of its packets (R60), except after a reclaim (R79).
- **R56** **Order.** AUs go out in the order they were queued. The bridge never reorders frames.

## 4. Latency policy (CarPlay)

- **R57** **frame_no tracking.** The bridge remembers the frame_no (slot offset 0x10) of the last type-2 AU that reached
  the latency stage, whether that AU was queued or dropped by this policy. 0 means "none". It is reset to 0 by R18,
  R92 and R116.
- **R58** **Order of checks.** For each valid AU (R24), after the intro and gate checks (R116, R95), the bridge first
  measures the backlog B (before this AU is queued). Then:
  - (a) Always: if a successful reclaim happened since the last AU (R81), it logs
    `bridge: most-reclaim-resync sequence=%u queued=%lu reclaims=%lu` (frame_no, B, reclaims so far). If it is not in
    the latency wait (R64), it then makes a latency reset (R59).
  - Checks (b) and (c) run only when not in the latency wait.
  - (b) If last frame_no ≠ 0, and either (frame_no ≤ 2 and last > 100) or frame_no ≠ last + 1, it logs
    `bridge: predictive-chain-gap previous=%u current=%u restart=%d` (restart = 1 for the first form, else 0) and makes
    a latency reset.
  - (c) If B > 2048, it makes a latency reset.

  For each check, B is the backlog after the previous reset (0 if a reset already happened for this AU).
- **R59** **Latency reset** does all of the following:
  - a whole-AU discard (R60);
  - remove the IDR marker (R61);
  - enter the wait-for-keyframe state with "writer not yet recovered" and "IDR not yet requested";
  - set the discontinuity flag pending;
  - remember the reset time and the completed-block count;
  - add 1 to latency_resets;
  - add the discarded packets to latency_packets_discarded.

  Log:
  `bridge: latency-reset sequence=%u queued=%lu discarded=%lu limit=%u idr_request_deferred=1 resets=%lu`
  The fields are frame_no, B, the packets actually removed, 2048 and the reset total.
- **R60** **Whole-AU discard.** The bridge removes from the backlog every packet that belongs to an AU none of whose
  packets has been put into a block yet. It keeps the remaining packets of an AU that has already partly been put into a
  block, and those still go out (R55). A truncated AU never reaches the device because of a discard. The reported
  `discarded` counts only removed packets. Every discard also resets the "window" high-water mark used by R105.
- **R61** At every latency reset the bridge MUST remove the IDR marker. An IDR answered while the output is still
  congested would only be buried behind the next backlog, so the request is deferred (R65).
- **R62** **The triggering AU is dropped**, even if it is a keyframe, because the writer has not recovered yet (R63).
- **R63** **Writer recovery.** The output counts as recovered after a reset when both hold:
  - at least 8 blocks have completed since the reset;
  - the current fast streak (R43) is at least 8.

  While it has not recovered, every AU is dropped: it adds 1 to latency_frames_discarded and updates last frame_no.
  For the 1st, 31st, 61st and so on dropped AU (the total since process start ≡ 1 mod 30, counting R63 and R65 drops),
  the bridge logs:
  `bridge: latency-wait-writer sequence=%u dropped_frames=%lu wait_us=%llu blocks=%lu streak=%lu`
- **R64** **Wait-for-keyframe state.** It has two forms.
  - The **latency wait** is entered by R59. It goes through R63, R65 and R66.
  - The **plain wait** is entered by R18, R92 and R116. In it, every AU that is not a keyframe is dropped before the
    checks of R58. It updates no frame_no, and counts neither as `drops` nor in the latency counters. The first keyframe
    ends the plain wait at once (there is no output-recovery condition). It starts a new epoch (R31), carries the
    discontinuity flag, and then goes through R58 with last frame_no = 0. Log:
    `bridge: intro-live-resume-idr sequence=%u pts_origin=%llu`
    The name is historical; it is logged for every way into the plain wait.
- **R65** **IDR request.** When the output has recovered and the AU is not a keyframe:
  - the first time after a reset, the bridge creates the IDR marker and logs
    `bridge: latency-request-idr sequence=%u status=%d wait_us=%llu blocks=%lu streak=%lu`
    with status 0 on success and −1 on failure (then it tries again at the next AU);
  - the AU is dropped (latency_frames_discarded + 1, last frame_no updated).
- **R66** **Resume.** When the output has recovered and the AU is a keyframe:
  - another whole-AU discard; its count adds to latency_packets_discarded;
  - a new epoch starts at this AU (R31);
  - the bridge leaves the wait-for-keyframe state, and the AU is queued with the random-access and discontinuity flags.

  Log:
  `bridge: latency-resume-idr sequence=%u wait_us=%llu extra_discarded=%lu blocks=%lu streak=%lu`
- **R67** The 2048 limit is fixed. It MUST NOT be configurable at run time on the unit.
- **R68** AUs dropped by this policy, or by the waits of R95 and R116, MUST NOT count in `drops` (R97). Only the
  counters above count them.
- **R69** After each queued live AU, the bridge updates:
  - frames + 1, and keys + 1 when it is a keyframe;
  - input_bytes += the AVCC size;
  - ts_packets += the packets of the AU;
  - frame_max and idr_max: the largest AVCC sizes, all-time and per metrics window;
  - pts_step_max for the window.
- **R70** **Metrics line.** The first queued AU of the process opens a window. At each later queued AU, once at least
  1 s has passed since the window opened, the bridge logs this line and opens a new window:
  `bridge: metrics input_bps=%llu ts_bps=%llu fps_milli=%llu frame_max=%lu idr_max=%lu queue=%lu queue_hi=%lu queue_hi_total=%lu pts_step_max=%llu`
  The fields:
  - input_bps: AVCC bits per second in the window;
  - ts_bps: video TS bits per second queued in the window;
  - fps_milli: AUs per 1000 s;
  - frame_max and idr_max: per window;
  - queue: the backlog now;
  - queue_hi: the backlog high-water mark since the last metrics line or discard;
  - queue_hi_total: the all-time high-water mark;
  - pts_step_max: the largest pts step in the window.

## 5. Boot-time MOST reclaim

During boot the factory video encoder may take isoTX2 for itself. The bridge's next write then fails with ENOMEM. The
fix is to re-assert the release of the display context to the cluster map, reopen, and resync the picture.

- **R71** **Trigger.** A write failure (R42) with errno = ENOMEM starts a reclaim only when both hold:
  - fewer than 3 reclaims have been attempted in this process;
  - monotonic time (time since boot) is below 180 s at the failure.

  Otherwise:
  - for ENOMEM the bridge logs `bridge: most-reclaim not-attempted reclaims=%u max=%u uptime_ms=%llu`, with the attempts
    so far, 3, and monotonic ms;
  - for any errno it then stops and exits with status 0, without calling dmdt.
- **R72** **Attempt k** (k = 1, 2, 3, numbered in order):
  1. close the device (readiness 0);
  2. run `dmdt dc 72`;
  3. only if that returned exit status 0, run `dmdt sc 4 72`;
  4. log `bridge: most-reclaim attempt=%u uptime_ms=%llu dmdt=%d/%d`, with k, monotonic ms, the status of `dc` and the
     status of `sc` (−1 if not run);
  5. wait 500 ms;
  6. reopen the device with the full sequence of R35;
  7. log `bridge: most-reclaim attempt=%u reopen=%s` with `ok` or `failed`.

  A failed reopen stops the bridge with exit status 0.
- **R73** **dmdt call.** The executable is `/eso/bin/apps/dmdt` with argv `[path, arg1, arg2(, arg3)]`. It runs as a
  child process with:
  - stdin, stdout and stderr on `/dev/null`;
  - the bridge's environment, minus every `LD_PRELOAD=`, `IPL_CONFIG_DIR=` and `LD_LIBRARY_PATH=` entry, plus
    `IPL_CONFIG_DIR=/etc/eso/production` and
    `LD_LIBRARY_PATH=/mnt/app/root/lib-target:/eso/lib:/mnt/app/usr/lib:/mnt/app/armle/lib:/mnt/app/armle/lib/dll:/mnt/app/armle/usr/lib`.

  All other variables pass through unchanged.
- **R74** **dmdt status.** The status of one call is:
  - the child's exit status;
  - −1 if it could not be started;
  - −2 if it ended by a signal;
  - −3 if it did not end within 3000 ms. The bridge polls about every 10 ms. On timeout it kills the child with SIGKILL
    and reaps it.

  No dmdt child may outlive the bridge's handling of it: always reap.
- **R75** The bridge MUST NOT call dmdt with any other arguments, and MUST NOT call it outside R72. In particular it
  never restores the OEM context (`dc 70 33` / `sc 4 70`): that is the supervisor's job.
- **R76** At most 3 attempts per process. A 4th ENOMEM gives the `not-attempted` line of R71 with `reclaims=3 max=3`.
- **R77** The `reclaims` counter in the consumer status counts the attempts whose reopen succeeded.
- **R78** The failed block is lost. The output packet index n is not rewound. The PCR therefore jumps by
  64 × 705/64 = 705 ticks across the lost block, and the PCR schedule (next_pcr) continues unchanged.
- **R79** **Transport restart after a reopen.**
  - next_psi is set to the first position of the next block, and a pending PMT is cancelled. So the next block starts
    with a PAT and a PMT, and later PAT/PMT pairs follow every 327 packets from there.
  - All continuity counters continue (R54).
  - The fast streak (R43) is reset to 0.
  - Video packets of an AU that had already partly gone into a block before the failure MUST be dropped as well, from
    the next block on. The device lost the start of that AU, so its tail would be a truncated frame.
- **R80** **Stop during reclaim.** If a stop is requested before a dmdt call starts, the bridge MUST NOT start it: no
  `sc 4 72` after a stop that arrived during `dc 72`. It MUST NOT reopen the device after a stop. A dmdt child already
  running may be waited for, up to its R74 timeout, and then the bridge exits.
- **R81** **Picture resync.** After a successful reopen, the next processed AU runs R58 (a): a latency reset, the
  deferred IDR request and resume on a keyframe. So the decoder restarts on a fresh IDR. If the bridge is already
  waiting for a keyframe, only the resync line is logged.

## 6. Contract consumer duties

The contract header (sections 2.1 to 2.4) is normative for file formats, paths, limits and the gate rules. This section
says what the bridge does with them. "Contract directory" means `/ramdisk/most-src/` (override: section 9).

### 6.1 Line files the bridge reads

- **R82** The bridge reads `owner` and `<src>.session` as the contract header defines:
  - one line of `key=value` pairs separated by single spaces;
  - unknown keys ignored;
  - a line whose `v` is not `1` ignored;
  - a missing file, an unreadable file or an unparsable file means "no file".

  It reads only; writers use tmp + rename, so the bridge never sees a partial line.
- **R83** **Owner polling.** The bridge reads `owner` at least every 20 ms while running. A valid owner has:
  - `src`: a non-empty lowercase word; the contract defines `wired`, `wireless` and `aa`;
  - `gen`: a u32;
  - `pid`;
  - `kind`: `in` or `proxy`, missing = `in`.

  The current owner's `gen` is reported as owner_gen in the status (0 when there is no valid owner).
- **R84** **Source tracking.** The tracked source is the `src` of the current valid owner. When there is no owner file,
  it is the last source seen in this run. When it changes, the bridge forgets what it knew about the old source's
  session (R87). Before any owner has been seen there is no tracked source, and session files are not read.

### 6.2 Session stop

- **R85** **Session polling.** The bridge reads `<tracked src>.session` at least every 100 ms.
- **R86** A session line counts only if both hold:
  - it has a `state` key;
  - when a valid owner exists, its `gen` equals the owner's gen.

  Missing `gen`, `pid` and `ts_ms` read as 0, and a missing `reason` reads as `-`.
- **R87** `state=start`: the bridge remembers that a start was seen for the tracked source in this run, together with
  its `pid`.
- **R88** `state=stop` with `ts_ms` (monotonic ms) at or after the bridge's own start time ends the stream. The bridge
  logs `bridge: session-stop src=%s gen=%lu pid=%lu reason=%s` and then behaves exactly as for SIGTERM (R4): final
  status with ready=0, `complete` line, exit status 0. The process MUST exit within 500 ms after the stop file appears.
- **R89** `state=stop` with `ts_ms` earlier than the bridge's start time is stale, left over from an earlier session.
  It MUST be ignored, and logged once per run:
  `bridge: session-stop-ignored src=%s gen=%lu ts_ms=%lu (older than bridge)`
  This guards against a restart loop: the supervisor restarts the bridge after every exit.
- **R90** **Vanished session.** When the session file cannot be read (missing or empty), and R87 recorded a start with
  pid > 0 in this run, and `kill(pid, 0)` fails with ESRCH, the stream ends as in R88. Log:
  `bridge: session-stop src=%s pid=%ld reason=vanished-dead-pid`
  A vanished file whose pid is still alive, or for which no start was seen, does nothing.
- **R91** With no `owner` and no session files at all, the bridge behaves as if section 6.1 and 6.2 did not exist:
  status writing (6.4) still runs, but nothing stops the stream.

### 6.3 Consumer gate (contract v1.1)

- **R92** **Cut.** The first valid owner seen in a run is only recorded: its gen, pid and kind. Each later valid owner
  whose gen differs from the last recorded gen is a **cut**. A missing owner file is not a cut and keeps the recorded
  values. At a cut the bridge MUST:
  - (a) remember the previous owner's pid and kind (from the last recorded owner) and record the new owner;
  - (b) increase the ring header generation by 1, skipping 0, and treat that value as its own (no R18 follows);
  - (c) set cut_seq = the header write_sequence read at the cut, and continue reading at W = cut_seq + 1;
  - (d) make a whole-AU discard, set the discontinuity flag pending, forget the last frame_no, reset the age reference,
    and mark the next AU as an epoch start;
  - (e) close the gate.

  Log:
  `bridge: owner-cut owner_gen=%u ring_gen=%u kind=%s prev_pid=%lu`
  kind is the new owner's kind (`in` or `proxy`).
- **R93** **While the gate is closed**, every slot counts one drop, except a type-1 slot with seq > cut_seq. That slot
  is stored (the last such one wins; up to 4096 bytes) and then:
  - if the previous pid is 0, or `kill(pid, 0)` fails with ESRCH, the gate opens at once with reason `pid-exit`, and this
    slot is handled as a normal type-1 slot (R22);
  - otherwise the slot is **held**. It counts one drop and stays stored.
- **R94** **Opening.** While the gate is closed with a held avcC, at every poll pass the bridge checks:
  - if the previous pid is now gone (ESRCH), the gate opens with reason `pid-exit`;
  - else, once 100 ms (previous kind `in`) or 3000 ms (previous kind `proxy`) have passed since the cut, it opens with
    reason `forced` and gate_forced + 1.

  On every opening, at once or later:
  - the stored avcC is applied as the configuration (R22);
  - the IDR marker is created (R26);
  - the bridge logs `bridge: gate-open reason=%s gate_forced=%lu`.

  A gate without any type-1 slot after the cut stays closed (see OPEN-QUESTIONS).
- **R95** After a cut, also once the gate is open, the bridge is in the wait-for-keyframe state: it drops type-2 AUs
  until the first keyframe, and that keyframe starts the new epoch with the discontinuity flag. These drops count
  neither as `drops` nor in latency_frames_discarded. They are a separate count, which the implementation MAY log.
- **R96** The gate MUST NOT block the producer, and MUST NOT write anything to the ring except the generation bump of
  R92 (b).

### 6.4 Consumer status

- **R97** **Status file** `consumer` in the contract directory, one line, exactly these keys in this order:
  `v=1 ready=%d pid=%ld owner_gen=%lu ring_gen=%lu seq=%lu frames=%lu drops=%lu overruns=%lu latency_resets=%lu age_ms=%lu queue_pkts=%lu queue_hi=%lu reclaims=%lu most_errno=%d up_ms=%llu`
  The values:
  - ready: R36;
  - pid: the bridge's pid;
  - owner_gen: R83;
  - ring_gen: the ring generation the bridge currently follows;
  - seq: W − 1, the last consumed or skipped sequence, 0 at start;
  - frames: queued live AUs;
  - drops: the drops defined in R19, R20, R22, R24, R93 and enqueue failures, and nothing else;
  - overruns: overrun events;
  - latency_resets: R59;
  - age_ms: R99;
  - queue_pkts: the backlog now;
  - queue_hi: the all-time backlog high-water mark;
  - reclaims: R77;
  - most_errno: the errno of the last failed device open or write, 0 if none (R37, R41, R42);
  - up_ms: ms since process start.

  The values are clamped as the contract header (section 2.3) specifies, which keeps the line at most 253 bytes
  including `\n`.
- **R98** **Writing.** The file is written as `consumer.tmp.<pid>` (mode 0644), then renamed over `consumer`. The
  contract directory is created (mode 0755, with parents) if it is missing. If a write fails, the tmp file is removed.
  - The first status MUST be written within 1000 ms of start.
  - After that it is written every 1000 ms ± 100 ms, as consecutive up_ms values show. The schedule does not drift: when
    the bridge falls behind by more than one period it re-anchors.
  - It keeps being written during the intro, during reclaim waits and while the ring is invalid. A reclaim attempt may
    delay one refresh by its duration.
- **R99** **age_ms** is the lateness of the last consumed type-2 slot. For each type-2 slot that reaches processing, with
  ts ≠ 0, let `offset = now_us − media_us`, where media_us = ts as microseconds (seconds × 10^6 + the fraction × 10^6 /
  2^32, truncated). age_ms = (offset − the smallest offset seen since the age reference was reset) / 1000. With ts = 0,
  age_ms = 0. The reference is reset at start, by R18 and by R92.
- **R100** A stop request sets ready to 0 at once.
- **R101** On every exit after start-up, including session stop, write failure and stop signal, the bridge writes one
  final status with `ready=0` and the final counters (best effort).

## 7. Logging

- **R102** **Log file.** `/ramdisk/pmcp-most/bridge.log` (override: section 9). The directory is created with parents
  (mode 0755) if missing, and the file is opened for append (mode 0644).
  - On success, everything the bridge writes to stderr goes to this file, and nothing goes to the inherited stdout or
    stderr.
  - If the file cannot be opened, the bridge logs to the inherited stderr and carries on.
  - The override value `-` means "use the inherited stderr".
- **R103** **Cap.** Before writing a line of L bytes, if the file is non-empty and size + L > 65536, the bridge renames
  `bridge.log` to `bridge.log.1` (replacing any older `.1`) and continues in a new empty `bridge.log`. Neither file ever
  exceeds 65536 bytes. No `.2` or higher exists. Existing content at start is kept, and the rule applies to it from the
  first line.
- **R104** Each line is written whole, with no interleaving between concurrent writers, and flushed at once, so the file
  is current when the process is killed. Every line starts with `bridge: `. The first line of a run MUST contain
  `pid=<pid>`. It SHOULD also name the log path, the cap and the contract directory.
- **R105** **Lines that tools and people parse.** For these lines the text up to the first `=`, and every `key=value`
  token shown, MUST be exactly as given. Values are decimal.

  | Line | Defined in |
  |---|---|
  | `ring overrun`, `avcC ready`, `ring generation=` | R19, R22, R18 |
  | `predictive-chain-gap`, `latency-reset`, `latency-wait-writer`, `latency-request-idr`, `latency-resume-idr` | R58 to R66 |
  | `pts-rebase`, `clock` | R32, R34 |
  | `MOST write failed: <text>` | R42 |
  | `most-reclaim attempt=… uptime_ms=… dmdt=…/…`, `most-reclaim attempt=… reopen=ok\|failed`, `most-reclaim not-attempted …`, `most-reclaim-resync …` | section 5 |
  | `session-stop …`, `session-stop-ignored …` | R88 to R90 |
  | `owner-cut …`, `gate-open …` | R92, R94 |
  | `blocks=…`, `hist_write_us=…`, `metrics …`, `writer stopped …` | R44, R70, R45 |
  | device lines `open … failed`, `interface`, `packet-size`, `block-count`, `queue-flush`, `start` | R35 |
  | `complete …` | R108 |
  | intro lines | R117 |

  The consumers are `aa/most/test/ts_analyse.py` (event extraction by the regular expression on these names and the
  keys `sequence previous current restart queued discarded extra_discarded`), the bridge test harness and the people who
  read car logs (frame_max, latency resets, reclaims).
- **R106** Start-up lines (the format is free apart from these keys): the latency limit and the reclaim window
  (`latency-limit packets=2048 reclaim-window-s=180`) and the intro decision (R117).
- **R107** Other diagnostic lines MAY be added, but MUST NOT start with any name listed in R105.
- **R108** **Summary line.** Exactly once per run, at exit:
  `bridge: complete frames=%lu keys=%lu drops=%lu input_bytes=%llu ts_packets=%llu frame_max=%lu idr_max=%lu queue_hi=%lu write_us_max=%llu slow_writes=%lu latency_resets=%lu latency_packets_discarded=%llu latency_frames_discarded=%lu pts_rebases=%lu intro_frames=%lu`
  The values:
  - frame_max and idr_max: all-time maximum AVCC sizes, of any AU and of a keyframe;
  - queue_hi: the all-time backlog high-water mark;
  - ts_packets: all video packets queued, intro included;
  - intro_frames: the intro AUs queued.

  It is written on start-up failures too (with zeros) and after a session stop.

## 8. Optional intro clip (new)

The bridge MAY show a short pre-encoded clip (for example a logo animation) on the cluster before the live map. This
function is new; nothing of the reference behaviour applies.

- **R109** **Files** (the directory can be overridden: section 9):
  - clip: `/mnt/app/pmcp-most/intro.h264`;
  - disable switch: `/mnt/app/pmcp-most/intro.off`. If it exists, whatever its content, the intro is off;
  - once-per-boot marker: `/ramdisk/pmcp-most/intro-played`.
- **R110** **Clip format.** A raw H.264 Annex-B elementary stream with these properties:
  - 800×480, progressive, Baseline or Main profile, 4:2:0, at most 16 MiB;
  - every AU begins with an AUD NAL (type 9) after a 3- or 4-byte start code;
  - the first AU is an IDR preceded by SPS and PPS inside the AU, and SPS/PPS precede every IDR;
  - the last AU SHOULD show the final still picture: there is no fade-out, and the hand-over is a hard cut;
  - the nominal rate is 30 fps.

  The bridge does not decode, scale or check the picture content.
- **R111** **When it plays.** At process start, after the ring has been initialised, the intro plays when all of these
  hold:
  - the clip exists;
  - `intro.off` does not exist;
  - the once-per-boot marker does not exist.

  It plays at most once per process. It does not replay on R18 or R92.
- **R112** **Validation.** The clip is rejected, and the bridge continues as without an intro (logging the reason), when
  any of these is true:
  - it cannot be read;
  - its size is 0 or over 16 MiB;
  - it contains no AUD.

  Bytes before the first AUD are ignored.
- **R113** **Playback.**
  - Split the clip into AUs: each runs from one AUD start code up to the next one, or to the end of the file.
  - Queue each AU unchanged, as one PES (R51, R52). The bridge adds nothing: no extra AUD, no SPS/PPS.
  - The keyframe flag is set when the AU contains a type-5 NAL.
  - PTS: the first intro AU gets L (R30), and each later one adds 3000.
  - The first intro AU carries the discontinuity flag.
  - AUs are queued at 1/30 s intervals.
  - The latency policy of section 4 does not apply to intro AUs.
- **R114** The once-per-boot marker is created (mode 0600, exclusive create) when the first intro AU has been queued. If
  that fails, the failure is logged and the intro still plays.
- **R115** **During playback** the bridge keeps all its other duties:
  - it reads the ring and applies type-1 configurations;
  - it drops type-2 AUs, counting them in neither `drops` nor the latency counters;
  - it follows R18 and R92;
  - it writes the status;
  - it honours SIGTERM and session stop within the times of R4 and R88.

  A stop ends the intro at once.
- **R116** **Hand-over.** After the last intro AU has been queued:
  - create the IDR marker;
  - enter the plain wait (R64);
  - forget the last frame_no.

  The first live keyframe ends it as R64 says. If no valid configuration exists when that keyframe arrives, it is dropped (R24) and the wait goes on.
- **R117** **Intro log lines.**
  - At start, exactly one of:
    - `bridge: intro=off reason=%s`, where reason is `no-clip`, `switch`, `played-this-boot` or `invalid`;
    - `bridge: intro-start path=%s bytes=%lu fps=30 pts=%llu`.
  - At the end, one of:
    - `bridge: intro-complete frames=%lu next_pts=%llu`;
    - `bridge: intro-interrupted frames=%lu` (stopped).
- **R118** With the intro off, start-up is the plain path: there is no IDR request at start, no wait for a keyframe at
  start, and no discontinuity flag on the first AU (R53).

## 9. Host-test interface

Every implementation MUST provide a **host build**: an executable built on macOS (and Linux) with the system C compiler
and no QNX headers. It behaves like the unit build except as listed here. Black-box tests run only the host build. The
bridge test harness is the only client.

### 9.1 Overrides honoured in every build

These are path overrides only. Each takes effect when the variable is set and not empty.

| Variable | Replaces |
|---|---|
| `PMCP_MOST_RING` | ring path `/ramdisk/carplay-alt-ring.bin` |
| `PMCP_MOST_IDR` | IDR marker `/ramdisk/carplay-alt-force-idr.request` |
| `PMCP_MOST_SRC_DIR` | contract directory `/ramdisk/most-src` |
| `PMCP_MOST_LOG` | log file `/ramdisk/pmcp-most/bridge.log` (`-` = inherited stderr) |
| `PMCP_MOST_INTRO_DIR` | intro directory `/mnt/app/pmcp-most` (clip and `intro.off`) |
| `PMCP_MOST_INTRO_MARKER` | `/ramdisk/pmcp-most/intro-played` |

### 9.2 Host-build-only behaviour

The unit build MUST NOT honour any of the following.

- **R119** **File output.** `argv[1]` is a regular file path.
  - The first open creates or truncates it (mode 0644). A reopen after a reclaim appends.
  - No devctl is issued. Instead the bridge logs `bridge: portable file-output validation mode`, and readiness is 1 once
    the file is open.
  - After each completed block the bridge pauses `PMCP_MOST_FILE_BLOCK_US` µs (default 10000, which gives about 9.6
    Mbit/s), so that backlog scenarios are reproducible.
  - The file always holds a whole number of 12032-byte blocks (R39, R41).
- **R120** `PMCP_MOST_DMDT`: the dmdt executable path, used instead of `/eso/bin/apps/dmdt` with the same argv and
  environment rules (R73). The harness's fake dmdt appends `"$*"` to the file named by `FAKE_DMDT_LOG` (which reaches it
  through R73's pass-through) and exits 0, or with a status it is given.
- **R121** `PMCP_MOST_RECLAIM_WINDOW_MS`: the reclaim window in ms, measured from **process start** (on the host,
  uptime is meaningless). The default is 180000. The value 0 means "always outside".
- **R122** `PMCP_MOST_TEST_ENOMEM=<first>[,<repeat>]`: ENOMEM injection.
  - Let k be the number of blocks completed successfully before the current one (failed blocks do not count). When
    k ≥ next (next starts at first), the block that has just been written is reported as a write failure with errno ENOMEM, and next becomes
    k + repeat. repeat = 0 or absent means only once.
  - The reported failure goes through R42 and section 5 exactly like a real one.
- **R123** Uptime for `uptime_ms` in log lines is CLOCK_MONOTONIC on the host too. Only the window test uses R121.

### 9.3 Observable artefacts and harness expectations

- The output file (TS, checked by `ts_analyse.py`, and compared with `ts_compare.py --mode cp` against the reference run
  on the same input).
- The log file(s) of R102/R103.
- The `consumer` file.
- The IDR marker and the ring file (the harness's producer writes the ring as the contract header defines, and acts on
  the IDR marker).
- The fake dmdt log.
- The exit status and the time to exit.

The harness passes all paths through 9.1 and 9.2 and runs each test in its own directory. It never needs root, devices
or QNX.

### 9.4 Reference host build: differences and the adapter it needs

The current reference (`bridge/src`) can be driven by the same tests through an adapter.

- **Variable names.**
  - The reference takes the ring, IDR marker, dmdt path and intro-marker paths from `HOST_RING_PATH`, `HOST_IDR_PATH`,
    `HOST_DMDT_PATH` and `HOST_INTRO_ONCE_PATH`, through its compile-time shim. The adapter sets those as well as the
    `PMCP_MOST_*` names.
  - `PMCP_MOST_SRC_DIR` and `PMCP_MOST_LOG` are honoured as they are.
- **Intro.** The adapter MUST unset `CARPLAY_CLUSTER_INTRO`, so that the reference takes its plain start path.
- **Cache lock.** The reference also needs `HOST_CACHE_LOCK` set to a writable path. Without it, start-up fails with
  status 1.
- **Reclaim window.** The window is `HOST_RECLAIM_WINDOW_US`, in µs from process start. The adapter converts ms × 1000.
- **ENOMEM injection.** This is compile-time only. The adapter builds a second binary with
  `-DALTSCREEN_BRIDGE_TEST_ENOMEM_AT_BLOCKS=<first> -DALTSCREEN_BRIDGE_TEST_ENOMEM_REPEAT=<repeat>` and selects that
  binary when the test sets `PMCP_MOST_TEST_ENOMEM`.
- **File pacing.** The pause is fixed at 10 ms. `PMCP_MOST_FILE_BLOCK_US` is ignored, so tests must use the default.
- **Tests the reference is expected to fail:**
  - the consumer gate (R92 to R96): not implemented;
  - the intro (section 8): different files and policy;
  - R27: the reference also treats flags bit 0 as a keyframe;
  - R41: it logs a spurious `MOST write failed` at SIGTERM;
  - R79: it sends the tail of an AU cut by a reclaim;
  - R80: it runs `sc 4 72` after a stop;
  - R83: it reads the owner every 100 ms, not 20 ms.

  The adapter marks these as "reference: expected deviation".

## 10. Non-requirements and freedom

- **R124** **Inner structure is free:** the number of threads, the queue design, the memory layout and the language
  (C99 is recommended, since the toolchain is gcc for QNX 6.5 armv7, softfp). The unit build may link only `libc.so.3`
  and `libsocket.so.3`. Its imports SHOULD stay within the set that mathsls and the reference bridge already use on the
  unit.
- **R125** **Backlog capacity** is free, but it MUST hold at least 4096 packets (the limit plus the largest possible AU,
  about 1490 packets). If the capacity is ever full, the input side may wait, but it MUST keep polling for stop requests.
- **R126** **When PTS is stamped:** the stamp MAY be computed at queue time (R31 to R33 at that moment, as the formulas
  state) or later. A later stamp is allowed only if it is never earlier than the queue-time value, and R33 holds.
  See OPEN-QUESTIONS 4.
- **R127** The video counter MAY be assigned when a packet is emitted instead of when it is queued (R54). Discarded
  packets then leave no gap.
- **R128** **Not required:**
  - the video-cache lease file `/ramdisk/cpmap-video-cache.lock` of the original package (shared read lock);
  - the `CARPLAY_CLUSTER_INTRO*` variables;
  - the reference's Java-UI intro policy files;
  - the Android Auto single-IDR variant;
  - a UDP input;
  - draining the backlog at stop.
- **R129** **Diagnostic counters and lines** beyond those in sections 4, 6.4 and 7 are free. Exact µs values, bitrates
  and timing-dependent positions (which AU a reset hits, where an AU starts in the packet stream, the number of null
  packets) are not compared. `ts_compare` treats them as notes.
- **R130** **Sequence wrap** of write_sequence from 0xFFFFFFFF to 1 SHOULD be handled as the contract header describes.
  It is not tested: at 60 slots/s it takes about 2.3 years.
- **R131** **Memory barriers:** the implementation chooses them, but it MUST read slot fields and data only between two
  reads of the slot seq that both equal W (R19).
