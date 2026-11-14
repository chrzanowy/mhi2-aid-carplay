# SPEC.md trace (for the lead only: never give this to the implementer)

## How to read this file

- It shows where each requirement of `SPEC.md` was observed, so the spec can be audited.
- **Abbreviations:**

  | Short | File |
  |---|---|
  | `B:` | `bridge/src/altscreen_most_bridge.c` (patched copy; line numbers of 2026-11-14) |
  | `U:` | `bridge/upstream/altscreen_most_bridge.c` |
  | `P:` | `bridge/src/pmcp_most.h` |
  | `CR:` | `bridge/src/cpmap_resources.h` |
  | `IP:` | `bridge/src/cpmap_intro_policy.h` |
  | `K:` | `bridge/contract/pmcp_most_contract.h` |
  | `KP:` | `bridge/contract/pmcp_most_producer.c` |
  | `FC:` | `bridge/contract/fake_consumer.c` |
  | `H:` | `bridge/test/harness.py` |
  | `S:` | `bridge/test/shim/host_shim.h` |
  | `D11` | `passat-mhi2-carplay/docs/11-ring-altscreen.md` |
  | `DC` | `passat-mhi2-carplay/docs/bridge-spike-CONTRACT.md` |
  | `D23` | `passat-mhi2-carplay/docs/23-wlasny-most.md` |
  | `S0` | `passat-mhi2-carplay/build/bridge-project/stage0-compat.md` |
  | `REF` | `wt/bridge/aa/most/reference/README.md` |
  | `TSA` | `aa/most/test/ts_analyse.py` |
  | `TSC` | `aa/most/test/ts_compare.py` |
  | `MW` | `aa/most/most_writer.h` |
  | `SUP` | strings of the mathsls `carplay-cluster-supervisor` (MU1161/791) |

- Each row gives the requirement, its source, and a note.
- **DEV** marks a deliberate deviation from the reference: a bug fix, or a new feature.

| R | Source | Note |
|---|---|---|
| R1 | S0 §1 (execl disassembly 0x1024e4); SUP `/mnt/app/carplaymaps/altscreen-most-bridge`; S0 §1 `slay -f altscreen-most-bridge` | |
| R2 | B:1550 | |
| R3 | S0 §1 (dup2 to /dev/null at 0x1024a0); `dio_manager.wrapper.sh:31-32` (unset of the intro variables) | DEV: the reference reads `CARPLAY_CLUSTER_INTRO` (B:1551, B:730); the spec ignores it |
| R4 | B:257-267, B:1568-1569, B:1757-1778; S0 §1 (T:sup 10×100 ms, then flush and SIGKILL); DC §2 ("wait up to 1 s") | the 1000 ms bound is the supervisor's grace period (OQ1) |
| R5 | B:1570 | |
| R6 | B:1560, 1571-1610 (`goto done` with result 1); B:1757 (result 0); B:1143-1147 (device failure gives 0); S0 §2 | |
| R7 | B:1148-1178 (nulls when the queue is empty) | |
| R8 | S0 §1 "Pliki nadzoru"; K §2.1/2.2 (the consumer only reads them) | |
| R9 | B:1577, B:404, P:118-138, P:162-171, P:332-346, B:789; CR:87-106 (cache lock) | the intro marker path is DEV (section 8) |
| R10 | B:1015-1023, B:1264, B:257-267 | |
| R11 | B:1577-1610 (ring before the writer thread); H:146 (`wait_ring` 5 s) | the 500 ms bound is ours |
| R12 | S0 §1 "Okno startu" (15×50 ms), S0 §2 (750 ms) | |
| R13 | B:1577-1603; D11 "Plik", "generacja"; DC §1 "Init by the bridge [D]" | the kit's `pmcp_ring_consumer_attach` (KP:239-253) does NOT reset write_sequence or the slot seqs on valid magic; the spec follows the reference and the deployed binary (OQ15) |
| R14 | B (no other ring stores); KP:825-852 (gate bump) | |
| R15 | B:1611-1613 | |
| R16 | B:1644, 1755 (`usleep(1000)`); D11 "Protokół" | |
| R17 | B:1661-1665 | |
| R18 | B:1666-1700 (without the intro replay); P:1680 (age epoch, the `pmcp_new_epoch` marker at B:1680); K §1 "restarts at W = 1" | DEV: no intro replay on a generation change |
| R19 | B:1701-1741; B:1717 (`overruns`); D11 "Odczyt" | |
| R20 | B:1742-1752 | |
| R21 | D11 last paragraph of "Protokół"; K header comment | |
| R22 | B:847-893 | |
| R23 | B:847-893 (no other state is touched) | |
| R24 | B:903-926 (B:914 without a config), B:1293, B:1751 | |
| R25 | B:903-949; DC §3 "AU content" | |
| R26 | B:402-409, B:433; `altscreen_frame_protocol.h:23-29`; K §2.4 | |
| R27 | B:1284, B:1294 (the reference uses flags bit 0); K top comment ("MUST NOT depend on it"); D11 (core.so writes 0) | DEV |
| R28 | B:433, 815, 1372, 1627, 1681 | DEV: no request at start after an intro played earlier in the boot (B:1619-1632 is dropped), and a request at gate opening is added |
| R29 | B:249-255; D11 "Wniosek" formula | |
| R30 | B:1270-1275 | |
| R31 | B:1296-1310, 1386-1403, 1404-1425, 810-814, 1676-1679 | |
| R32 | B:1429-1441 | |
| R33 | B:1442; TSA "PTS not strictly increasing" | |
| R34 | B:1444-1450 | |
| R35 | B:969-1013; DC §2 table (code-to-label pairing as logged); MW header comment | the macro names in B:43-47 are shifted against the labels; the labels are the facts |
| R36 | B:1011, B:1018, B:263; K §2.3 | |
| R37 | B:981-984, 998-1004, 1143-1147 | DEV (minor): most_errno for a START failure is a SHOULD; the reference leaves it unchanged |
| R38 | B:1143, B:1196 | |
| R39 | B:49-51, 1183, 951-965; TSA (whole 12032-byte blocks) | |
| R40 | B:951-965; DC §4 "Threads" | |
| R41 | REF §4 "Shutdown" (spurious `MOST write failed`); B:954, B:1188-1192 | DEV |
| R42 | B:1188-1214 | |
| R43 | B:1215-1226, B:193-197, B:65-66 | |
| R44 | B:1232-1262 | |
| R45 | B:1264-1266 | the `reclaims=` field is new in Tomasz's version |
| R46 | B:1138-1140, B:1159-1178 | |
| R47 | B:269-281, B:541-568; TSA `PAT_SEC` | |
| R48 | B:570-583; TSA `PMT_SEC` | |
| R49 | B:595-617; TSA `pcr_packet` | |
| R50 | B:532-539; TSA `null_packet` | |
| R51 | B:585-593, B:637-641; TSA `PES_HDR` | |
| R52 | B:619-673; TSA `packetize()` | |
| R53 | B:424, 666, 677, 767, 814, 1306, 1626, 1679; REF §6 item 1 (no flag at start in v1.x); TSC (`discontinuity` compared strictly) | the reference sets the flag at start only on the intro-skipped path (B:1619-1632); the spec drops that path |
| R54 | B:537, 550, 659; TSC (cc_breaks compared only for pat/pmt/null) | |
| R55 | B:674 (whole AU pushed atomically), B:379-400 (the pmcp fix); README item 5 | |
| R56 | B:356-368 (FIFO) | |
| R57 | B:1312-1314, 1358, 1382, 1458, 810, 1676, 1305 | |
| R58 | B:1311-1355 | |
| R59 | B:418-441 | |
| R60 | B:379-400 (pmcp fix); U:367-375 (the reference bug); README item 5; NOTES-stage1 (4/30 truncated in upstream) | DEV relative to upstream; equal to our patched copy |
| R61 | B:430-433 | |
| R62 | B:443-450, B:1356-1368 | |
| R63 | B:65-66, 443-450, 1356-1368 | |
| R64 | B:1296-1310 (the intro_waiting flag is used for intro end, generation change and the intro-skipped start); B:1625, 1675, 809 | the log name `intro-live-resume-idr` is kept from B:1307 |
| R65 | B:1369-1385 | |
| R66 | B:1386-1403 | |
| R67 | B:55-64; S0 header (1024 changed to 2048 in 59d6a4e) | |
| R68 | B:1751-1752 (status 1 is not counted) | |
| R69 | B:1451-1458, B:475-484 | |
| R70 | B:463-530 | |
| R71 | B:87-101, B:1188-1213 | |
| R72 | B:102-104, B:1092-1111 | |
| R73 | B:1030-1077; S0 §4 (the env strings equal those of SUP) | |
| R74 | B:108, B:1079-1087 | |
| R75 | S0 §4 (SUP rodata `dc 70 33`, `sc 4 70`) | |
| R76 | B:99-101, B:1193; H test_enomem | |
| R77 | B:1203 (set only on a successful reopen) | |
| R78 | B:1161-1163, B:1179 (n includes the failed block; no rewind) | |
| R79 | B:1198-1204 | DEV: the tail of a partly sent AU is dropped after a reclaim (the reference keeps it through B:379-400 and sends it) |
| R80 | B:1097-1105 (g_stop is checked only after both dmdt calls); S0 §4 risk (a) | DEV |
| R81 | B:1315-1330 | |
| R82 | P:179-225; K §2 (reject an unknown `v`) | DEV (minor): the reference does not check `v` |
| R83 | P:47, P:251-265 (owner read every 100 ms); FC:141 (2 ms) | DEV: 20 ms (needed for the gate, OQ8) |
| R84 | P:251-260, P:266 | |
| R85 | P:47, P:356-358 | |
| R86 | P:279-285 | |
| R87 | P:286-290 | |
| R88 | P:291-305; B:1655-1658; H test_session_stop (1.5 s; 40 ms measured) | the 500 ms bound is ours |
| R89 | P:292-301 | |
| R90 | P:268-277; H session-vanished | |
| R91 | README "Differences" item 3 | |
| R92 | K §2.1 "Consumer gate"; KP:825-852; FC:141-155 | NEW (the reference has a TODO at B:1653, P:261) |
| R93 | KP:869-890; FC:196-205 | NEW |
| R94 | KP:855-867, KP:892-901; FC:157-169 | NEW |
| R95 | K §2.1 ("the consumer should request an IDR on opening") | NEW; uses the plain wait |
| R96 | K header | |
| R97 | P:308-347; K §2.3; H `STATUS_KEYS` | the drops semantics follow B:1716, 1735, 1751 |
| R98 | P:331-346, P:353-370; H test_status (900..1100 ms) | DEV: the reference writes no status while the intro plays (the intro blocks the reader) |
| R99 | P:372-390; B:1745 | the reset on a gate cut is ours |
| R100 | B:263 | |
| R101 | B:1778 | |
| R102 | P:118-138; D23 v0.2 §5 | |
| R103 | P:140-160, CR:73-82 (the hook); H test_log_rotation | |
| R104 | CR:66-93 (mutex, flush); P:172-175 (first line with pid) | |
| R105 | TSA `EVENT_RE`; H regexes (enomem, force-idr, session); DC §6 U1/U5 (people read blocks, hist and frame_max) | |
| R106 | B:1616-1618 | |
| R107 | ours | |
| R108 | B:1763-1777 | |
| R109-R118 | NEW. Built from the reference intro: B:719-821 (AUD split, 16 MiB, fps 30, PTS step, discontinuity, marker after the first AU, IDR request and live resume), IP:1-53 (policy, once-per-boot marker) | DEV: file switch instead of env; the ring is read during the intro (the reference skipped the ring and relied on core.so resending avcC with the IDR, B:805-808) |
| R119 | B:975-1010, B:1227-1229 (10 ms pause); S | |
| R120 | S (`HOST_DMDT_PATH`), `test/fake_dmdt.sh` | |
| R121 | `test/shim/host_shim.c` (window from process start, µs) | |
| R122 | B:1113-1128 (compile-time) | |
| R123 | B:1101, B:1209 | |
| R124 | `build.sh`; NOTES-stage1 "Sprawdzenie importów" | |
| R125 | B:52-54 (65536) | |
| R126 | DC §5 "Timing rules"; REF §4 (negative lead) | |
| R127 | TSC (video CC not compared) | |
| R128 | CR:87-131; IP; S0 §5 | |
| R129 | REF §5 "Which fields depend on timing" | |
| R130 | K top comment (wrap from 0xFFFFFFFF to 1); B:1703 (the reference breaks at wrap) | |
| R131 | B:1701, 1726, 1740 | |

## Deviations from the reference

These are the deliberate deviations, so tests against the reference can be marked:

- R3: the intro variables are ignored.
- R27: the keyframe flag is not used.
- R28 and R95: an IDR is requested at gate opening.
- R41: no spurious write failure at stop.
- R64 and R18: no intro replay.
- R79: the reclaim tail is dropped.
- R80: no dmdt call after a stop.
- R82: `v` is checked.
- R83: owner read every 20 ms.
- R92-R96: the gate.
- R98: status keeps being written during the intro.
- R109-R118: the intro.
- R53 and R118: the intro-skipped start path is gone.
