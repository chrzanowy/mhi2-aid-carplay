# Prebuilt Android Auto binaries (QNX 6.5, armv7)

`installer/build_sd.py` takes these three files only with the SHA-256 below, so `install.sh` needs no QNX toolchain.
Rebuild them with Docker (image `qnx65-armv7-toolchain:8.5`); two builds must give the same bytes.

| File | Built by | SHA-256 | Size |
|---|---|---|---|
| `libgal_hook.so` | `aa/hook/build.sh <out> gamma` (MacsInSpace mib-cluster-map gal hook at the pinned commit + pmcp patches, GPL-3.0) | `bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05` | 132823 |
| `libdmdt_flush.so` | `aa/hook/build.sh` (MacsInSpace `dmdt_flush`) | `4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f` | 5328 |
| `aa-most-feeder` | `aa/feeder/build.sh <out>` (feeder v10) | `c5f8b0ef3821b3a533cd762fab14ff984fffa0afe4fd66185e16ea57413149a7` | 34856 |

The settings files `aa/unit/gal-hook-gamma.conf`, `aa/unit/feeder-gamma.conf` and `aa/unit/gal.wrapper.sh` still say
"experimental" in their comments. That wording is historical: the files are pinned by hash, and the AA set id on the
unit (AA_BOOT) is built from them, so changing a comment would turn every installed set into an "old" one.
