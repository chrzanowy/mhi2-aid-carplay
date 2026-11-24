# fake-car: the simulated car for the MOST bridge

Plan and model: `passat-mhi2-carplay/docs/28-symulator-auta.md`.

One process (`fakecar.py`) plays the car. The real supervisor `pmcp-most-sup` and the real pmcp-most stage 2 bridge run
unchanged in it, built for the host. The car provides:

- the isoTX2 channel (`sim_mlb.c`: a unix-socket client that replaces `aa/most/test/host_mlb.c`; `aa/` is not changed);
- dmdt (`dmdt` -> `dmdt.req`);
- the factory VW encoder as an adversary;
- the phones;
- the AID screen.

Verdicts come only from what the car saw. Every run leaves `build/runs/<scenario>/blackbox.txt` (ordered channel, dmdt,
encoder, process and screen events) next to the programs' own logs in `ramdisk/`.

```
./run_sim.sh                 # all 13 scenarios (about 4 minutes)
./run_sim.sh boot-steal      # one scenario
FAKECAR_RECLAIM_US=0 ./run_sim.sh boot-steal      # bridge without reclaim: the gap check must fail
FAKECAR_AA_RECLAIM_S=0 ./run_sim.sh aa-steal       # feeder without reclaim: the picture check must fail
```

Scenarios:

| Area | Scenarios |
|---|---|
| CarPlay over the cable | session, boot-steal, replug, cp-reverse |
| CarPlay over Wi-Fi (WL contract files) | wl-session, wl-steal |
| Android Auto (the real aa-most-feeder, `aa/` compiled, never edited) | aa-session, aa-kill, aa-holds, cp-then-aa, aa-steal, aa-reverse, aa-silence |

`bridge/test/run_tests.sh` (no arguments) runs it as its last stage.
