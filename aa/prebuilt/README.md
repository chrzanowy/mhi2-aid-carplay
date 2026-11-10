# Prebuilt Android Auto binaries (QNX 6.5, armv7)

`installer/build_sd.py` takes these three files only with the SHA-256 below, so `install.sh` needs no QNX toolchain.
Rebuild them with Docker (image `qnx65-armv7-toolchain:8.5`); two builds must give the same bytes.

Provenance:
- gal hook and `dmdt_flush` sources: [MacsInSpace/mib-cluster-map](https://github.com/MacsInSpace/mib-cluster-map) commit
  `07361db860b1d09e3901e9002b4222889a8a8c18` (`COMMIT=` in `aa/hook/build.sh`), plus the pmcp patches in `aa/hook/`;
- toolchain: Docker image `qnx65-armv7-toolchain:8.5`, image ID
  `sha256:1d63142818e84ae3d10c0774ac455ee0e527e7b4e600410b58d581536aade028`
  (`docker image inspect --format '{{.Id}}' qnx65-armv7-toolchain:8.5` on the build machine).

| File | Built by | SHA-256 | Size |
|---|---|---|---|
| `libgal_hook.so` | `aa/hook/build.sh <out> gamma` (MacsInSpace mib-cluster-map gal hook at the pinned commit + pmcp patches, GPL-3.0) | `bdd76a85f22319c9750f7c55849b4053d4ce365446559025195673677bc73b05` | 132823 |
| `libdmdt_flush.so` | `aa/hook/build.sh` (MacsInSpace `dmdt_flush`) | `4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f` | 5328 |
| `aa-most-feeder` | `aa/feeder/build.sh <out>` (feeder v10) | `c5f8b0ef3821b3a533cd762fab14ff984fffa0afe4fd66185e16ea57413149a7` | 34856 |
| `aa-most-feeder-exp` | `aa/feeder/build.sh <out>` (feeder v13, experimental cards only: AAX_FEEDER; the source in aa/feeder is v13) | `17a366da1d364bf9559df54b9d598516b3b21a026ec0786bba3e578c6c63a5f1` | 56336 |

The settings files `aa/unit/gal-hook-gamma.conf`, `aa/unit/feeder-gamma.conf` and `aa/unit/gal.wrapper.sh` still say
"experimental" in their comments. That wording is historical: the files are pinned by hash, and the AA set id on the
unit (AA_BOOT) is built from them, so changing a comment would turn every installed set into an "old" one.
