# Prebuilt MOST bridge binaries (QNX 6.5, armv7)

`installer/build_sd.py` takes these files only with the SHA-256 below, so `install.sh` needs no QNX toolchain.
Rebuild them with Docker (`bridge/build.sh OUTDIR`, image `qnx65-armv7-toolchain:8.5`); each build is made twice and
must give the same bytes (the script checks it).

| File | Built by | SHA-256 | Size |
|---|---|---|---|
| `altscreen-most-bridge` | `PMCP_MOST_LIB=1 bridge/build.sh OUTDIR` (pmcp-most stage 2: `src/pmcp_most_lib.c` on the Android Auto MOST output library `aa/most`, reader and writer threads at priority 14, rotated event file) | `93bad193f7351eecdb6808e8ffd96ae5e8b31caf8e2ab08802e6d57e46dab79c` | 38172 |
| `pmcp-most-sup` | `PMCP_MOST_SUP=1 bridge/build.sh OUTDIR` (MOST supervisor v1, `src/pmcp_most_sup.c` + contract library; `ln` is `/bin/ln`, A247: ring made at start, `--boot` from lsd.sh; was `a545d5b1…`) | `fbc73f076a88b5322e2c7464be915ee0717c7818f4b22ea8e5ad6dc685f8b4e6` | 23396 |

Rebuilt from this tree on 2026-11-22: both reproduce the hashes above. In the car (2026-11-22, A222) pmcp-most with
the supervisor ran CarPlay over the cable and over wireless (WL) with no dropped frames, and gave the MOST channel back
to the VW map after the phone left.
