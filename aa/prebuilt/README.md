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
| `libgal_hook.so` | `aa/hook/build.sh <out> gamma` (MacsInSpace mib-cluster-map gal hook at the pinned commit + pmcp patches, GPL-3.0; A166: + raw navigation dump; A171 (AA 1.1): + road name, lanes and destination into the rg mailbox; AA 1.0 of v1.6.0 was `bdd76a85…`, 132823 B; A166 card b542b2d4 `0340ccca…`, 136636 B) | `cbf2e388ab053c0468daab6a6d3e3e2bb27875cfb16c2e260147b37282baa3af` | 141023 |
| `libdmdt_flush.so` | `aa/hook/build.sh` (MacsInSpace `dmdt_flush`) | `4e3202f0f41b5ad5a96d86ff49adbe574ce550f7b168c9a5f385069ca0e5222f` | 5328 |
| `aa-most-feeder` | `aa/feeder/build.sh <out>` (A166, v1.7.0: feeder v15 = v14 + MOST reclaim after boot; v14 `0003c60c…` 56900 B = Android Auto 1.0 of v1.6.0; v10 c5f8b0ef was the 0.1 alpha of v1.5.x) | `395d99b756789e39b119eded68f90d4eceee269138d7f950447aa928ea464592` | 58656 |

The settings files `aa/unit/gal-hook-gamma.conf`, `aa/unit/feeder-gamma.conf` and `aa/unit/gal.wrapper.sh` still say
"experimental" in their comments. That wording is historical: the files are pinned by hash, and the AA set id on the
unit (AA_BOOT) is built from them, so changing a comment would turn every installed set into an "old" one.
