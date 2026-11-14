# SPEC.md: open questions

Ordered by risk, highest first. "R" numbers refer to SPEC.md.

1. **The supervisor's stop timing (R4).**
   - The exact grace period of the mathsls supervisor is not known from its code: we only have its strings.
   - What is known: Tomasz's supervisor waits 10×100 ms, then writes `flush(0)`, waits 40×100 ms, then sends SIGKILL.
     DC §2 says "up to 1 s".
   - The spec assumes 1000 ms.
   - Exception: R80 lets a running dmdt delay the exit by up to 3 s. Under the supervisor that ends in `flush(0)` and
     SIGKILL.
   - Check in the car: `bridge-stopped` against `bridge-killed`.
2. **Does core.so answer the IDR marker outside the latency path?**
   - The cases are a ring generation change (R18), gate opening (R94) and the end of the intro (R116).
   - If core.so does not answer, the cluster stays black until the phone's periodic IDR, about 64 s (stage0 risk 2).
   - The same question applies to the Wi-Fi core.so instance.
3. **A gate that never opens (R93, R94).**
   - The gate opens only on a type-1 slot written after the cut (seq > cut_seq).
   - A proxy producer (core.so in a fresh dio_manager) may write its avcC *before* the bridge notices the owner change.
     The detection latency is up to 20 ms, the poll interval of R83.
   - Then nothing opens the gate: core.so is not known to resend avcC when the ring generation changes.
   - Options:
     - (a) take cut_seq from the last owner poll *before* the change;
     - (b) after N seconds closed, open on the next keyframe if an avcC with seq > cut_seq exists anywhere in the ring;
     - (c) require the wrapper to take the owner before it execs dio_manager. D23 says it does, which makes the race
       unlikely for wired.
   - Needs a decision from the lead or the WL session.
4. **PTS lead after a backlog (R31-R33, R126).**
   - The reference stamps PTS at queue time. With up to 2048 packets queued (about 250 ms) and a 100 ms target lead, an
     AU can leave with PTS behind PCR (golden: −2009 ticks).
   - The AA conditions in D23 say "PTS never behind PCR" (for AA).
   - The spec keeps the queue-time rule and allows a later stamp (R126).
   - Should CP require lead ≥ 0 at emission? `ts_compare` does not compare PTS, so either choice passes the current tests.
5. **ENOMEM on MU1161 is unconfirmed (section 5).**
   - It is only a hypothesis from cp-log-2 (`bridge-exited` 7.8 s after start).
   - The 180 s window and 3 attempts are Tomasz's numbers for MU1367.
   - Also unknown: whether the supervisor's own `dc 70 33` fallback can race the reclaim (R80 narrows it, but cannot stop
     a dmdt that is already running).
6. **R79 (drop the reclaim tail) and R80 (no dmdt after stop)** are our corrections. Neither has been tried in the car.
   R79 changes the bytes after a reclaim compared with the reference: no headless AU tail.
7. **Start without an intro (R118):**
   - no IDR wait;
   - no discontinuity flag on the first AU;
   - frames are accepted from the first AU after the first avcC.

   If the supervisor restarts the bridge mid-session, core.so continues with P-frames and the cluster shows garbage until
   the next IDR. harman-f sets the discontinuity flag at start; the reference does too, but only on its intro-skipped
   path. Keeping parity with the upstream TS (`ts_compare` SAME) forced the plain behaviour. Should start instead wait
   for a keyframe and request one?
8. **Owner poll interval (R83).** The spec chose 20 ms; the reference reads every 100 ms and fake_consumer every 2 ms.
   Is a small file read every 20 ms on the unit's /ramdisk acceptable? Very likely, but unmeasured.
9. **Intro design (section 8) is new and needs the user's decisions:**
   - the paths `/mnt/app/pmcp-most/intro.h264` and `intro.off`;
   - once per boot only, versus the reference's `every-connect` option;
   - a fixed 30 fps;
   - no replay on a reconnect without a bridge restart;
   - no early cut when live video is ready (the intro always plays to the end, about 2-3 s);
   - the GEM switch (the `intro.off` file) and how the installer creates it;
   - whether a clip and a licence for it exist.
10. **Ring initialisation: kit versus reference (R13).**
    - The kit's consumer attach only bumps the generation on valid magic.
    - The reference (and the deployed mathsls binary, per DC §1) also resets write_sequence and every slot seq.
    - The spec follows the reference. The kit's `fake_consumer` should be aligned, or the difference documented in the
      contract header.
11. **Status semantics.**
    - `drops` excludes latency, intro and plain-wait drops (R68, R97).
    - `reclaims` counts successful reopens (R77).
    - `most_errno` after a START failure is only a SHOULD (R37).
    - Producers (WL) should confirm that these meanings are useful to them.
12. **Exit status 0 on a device open or START failure (R6, R37).** This is kept from the reference. The supervisor
    ignores the status anyway. A non-zero status would help diagnostics, but it would change the logged supervisor
    `value2`.
13. **The reclaim restarts the PAT/PMT phase (R79).**
    - After a reclaim, `ts_analyse`'s fixed n mod 327 phase check fails by design.
    - The tests must not run the cadence check across a reclaim, or `ts_analyse` must learn the phase reset.
    - Alternatively the spec could keep the original phase. That would differ from the reference, and the AID decoder
      behaviour is unknown.
14. **Writer recovery (R63).**
    - The rule is ≥ 8 blocks and a streak of ≥ 8 writes of 30 ms or less.
    - The deployed mathsls binary (diasdio patch) used a streak of ≥ 1.
    - The real isoTX2 write times on MU1161 are unknown (DC U1). With slow writes the recovery could take long. The car
      logs (`hist_write_us`) will tell.
15. **Pacing in file mode (R119):**
    - 10 ms per block is a test artefact (about 9.6 Mbit/s, lower than MOST);
    - the force-idr scenario depends on it.
    - The real driver behaviour (EAGAIN versus blocking, FIFO depth) is modelled only in `aa/most/reference` (`host_mlb.c`),
      not in the bridge tests.
16. **The cache lease file (R128).** The spec drops it: nobody on our install takes the write lock. Confirm that no
    other installed component (for example a cache cleaner from Tomasz's package) expects the bridge to hold it.
17. **Sequence wrap (R130).** The reference stops consuming at the 2^32 wrap. This is not tested and is not reachable in
    practice.
18. **Log name collision.**
    - Tomasz's supervisor logs to `/ramdisk/altscreen-most-bridge.log`. Ours goes to `/ramdisk/pmcp-most/bridge.log`.
    - The log-clear button (main 9) and `cp-log-save` still need these paths (README "Not done yet").
