<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# MOST bridge producer contract kit (contract version 1)

Everything a video producer needs to feed the MOST bridge: the contract header,
a small producer library, a stand-in for the bridge (fake consumer) and a demo
producer. Producers are: CarPlay wired (core.so), CarPlay Wi-Fi (WL manager),
Android Auto (feeder). The bridge is the consumer.

## What to copy into your repo

| File | Why |
|---|---|
| `pmcp_most_contract.h` | the contract: ring layout, paths, file formats, limits, all rules in comments |
| `pmcp_most_producer.h`, `pmcp_most_producer.c` | optional library: ring write protocol, owner, session, IDR marker, status parser |
| `fake_consumer.c` | the bridge stand-in for host tests of your producer |
| `example_producer.c`, `test/` | reference usage and the test suite (optional) |

C99 + POSIX only, no threads, no malloc. Builds on macOS and QNX 6.5 gcc.
You may use the header alone and implement the protocol yourself.

## Build and test

```sh
cc -std=c99 -Wall -Wextra -Werror -pedantic -I. fake_consumer.c pmcp_most_producer.c -o fake_consumer
cc -std=c99 -Wall -Wextra -Werror -pedantic -I. example_producer.c pmcp_most_producer.c -o example_producer
test/run_tests.sh        # prints "CONTRACT TESTS: N ok, M failed"; takes about 40 s
```

Try by hand (everything in a scratch directory):

```sh
export PMCP_MOST_SRC_DIR=$PWD/scratch/most-src PMCP_MOST_RING=$PWD/scratch/ring.bin \
       PMCP_MOST_IDR=$PWD/scratch/idr.request
mkdir -p scratch
./fake_consumer --idr-every 2 &                       # one line per frame / event
./example_producer --src wireless --fps 30 --duration 10
```

`fake_consumer` options: `--dir --ring --idr --idr-every SEC --overrun-after N
--stall-ms MS --duration SEC --max-frames N`. `example_producer` options:
`--src wired|wireless|aa --fps --dir --ring --idr --create-ring --duration
--frames --gop --size`.

## The rules in short (details in the header comments)

1. **Ring** `/ramdisk/carplay-alt-ring.bin`: 16 B header + 64 slots of 0x4001c B,
   total 0x1000710. Magic 0x43505247. Type 1 = avcC (must come first), type 2 =
   one AVCC access unit (length-prefixed NALs, not Annex B). Timestamp = NTP
   32.32 (not microseconds). Write order: `slot.seq = 0`, fields + data,
   `slot.seq = N`, `header.write_sequence = N`. Never wait for the consumer.
2. **Generation** belongs to the consumer. When it changes, send your avcC again
   (the library does this on the next frame). The ring is normally created by
   the consumer; the library can create one for tests (`create_ring`).
3. **Owner** `/ramdisk/most-src/owner`:
   `v=1 src=wired|wireless|aa pid= gen= since_ms=`. Take it with tmp + rename only
   if there is no owner, the owner pid is dead, or you are `wired` and the owner is
   `wireless`. `gen` = previous + 1, 0 skipped. Release only if the file still
   holds your pid and gen.
4. **Preemption**: if `owner` shows another pid/gen, stop writing to the ring
   within 100 ms and write `state=stop`. Call `pmcp_producer_check_owner()` from
   your idle loop too (it is throttled to one file read per 10 ms).
5. **Session** `/ramdisk/most-src/<src>.session`:
   `v=1 state=start|stop gen= pid= ts_ms= reason=<word>`. Write start before the
   first frame and stop when the stream ends (stop makes the bridge end the
   stream at once, no timeout).
6. **IDR marker** `/ramdisk/carplay-alt-force-idr.request`: the bridge creates it,
   you `unlink()` it (`pmcp_idr_poll_consume()`), ask the phone for an IDR and mark
   that frame keyframe.
7. **Consumer status** `/ramdisk/most-src/consumer`, refreshed every 1000 ms (+-100):
   `ready pid owner_gen ring_gen seq frames drops overruns latency_resets age_ms
   queue_pkts queue_hi reclaims most_errno up_ms`. Read-only for producers
   (`pmcp_consumer_parse()`); unknown keys are ignored.
8. **Line files**: one ASCII line, `key=value` separated by single spaces, first
   key `v=1`, at most 255 bytes including the newline, always written as
   `<name>.tmp.<pid>` + `rename()`. Readers ignore unknown keys.

Paths are under `PMCP_MOST_BASE_DIR` (default `/ramdisk`, build-time macro) and can be
overridden at run time for tests with `PMCP_MOST_SRC_DIR`, `PMCP_MOST_RING`,
`PMCP_MOST_IDR`.

Note on `slot.flags` (offset 0x0c): core.so writes 0 there; the library sets bit 0 for
keyframes as an advisory hint (build with `-DPMCP_RING_NO_KEYFLAG` to write 0). The
bridge must not depend on it.

## Versioning policy

* Within `v=1` only additive changes: new keys may appear at the end of a line;
  readers ignore keys they do not know; existing keys keep their meaning and format.
* A breaking change (renamed or removed key, changed meaning, new ring layout)
  bumps `v=` (and `PMCP_MOST_CONTRACT_VERSION`). Readers reject a `v` they do not know.
* The ring layout is frozen by the car's core.so; it only changes with its own version
  field.
