# Phase 1: baseline, references, build matrix

Date 2026-11-24. Static audit only. The user asked for no builds.

## Baseline
- PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- The RA8 files have not changed since planning; only R-Car commits landed. The NuttX submodule is clean.

## References
- The archive was extracted into `refs/ra8p1/` with `--strip-components=1` and made read-only (`chmod -R a-w`).
- Device headers: `refs/ra8p1/R7KA8P1KF_core0.h` (CM85) and `R7KA8P1KF_core1.h` (CM33).
- `refs/ra8p1/ek_ra8p1/` holds 88 samples. `refs/ra8p1/evk_ra8p1_dual_core/RA8P1_DSP_example{,_cpu0,_cpu1}` is the only `r_ipc` carrier.
- There is no `r_iic_slave` module in the archive. `ek_ra8p1/iic_slave` is the only behavioral reference.
- Correction from phase 3: `bsp_elc.h` (583 lines) and `bsp_feature.h` (622 lines) under `ra/fsp/src/bsp/mcu/ra8p1/` are populated, so the skill note that calls them empty is stale.

## Core map (from defconfigs)
- All 30 `evk-ra8p1` configs default to CM85, except `ipc-cm33` and `wdt-cm33`. Those two set `RA_CPU_CORE_CM33=y`, `ARCH_CORTEXM33=y` and `RA_CPU_CORE=1`.
- Items handed to phase 2:
  - PX4 `evk-ra8p1-io-cm33` nsh sets `CONFIG_RA_CPU_CORE_CM85=n`.
  - `ipc-cm85` sets only `RA_CPU_CORE=0`.
  - `canfd`, PX4 nsh and bootloader set `ARCH_CORTEXM85=y` explicitly.

## Build matrix
| Config | Result | Core | text+data+bss |
|---|---|---|---|
| evk-ra8p1:adc-b | rc 0 | CM85 | 69148+184+3016 |
| evk-ra8p1:adc-b-hwtrigger | rc 0 | CM85 | 70828+184+3024 |
| the other 28 NuttX configs, PX4 `evk-ra8p1_*`, `fpb-ra8e1` | not run: the user cancelled builds | n/a | n/a |

Artifacts are in `artifacts/nuttx/{adc-b,adc-b-hwtrigger}.{config,nm}`. Every other phase's ELF symbol layer reads "not built (user declined builds)".

## Prior review C1-C3 (`plans/reports/code-reviewer-261123-2330-ra8-sample-fixes-review.md`)
All three are statically closed. Phases 5 and 6 confirm them.
- C1: `ra_poeg_register` is defined at `ra_poeg_chardev.c:118` and declared at `ra_poeg.h:207`.
- C2: `ra_agt.c:465` uses `RA_PCLKB_FREQUENCY`, which is defined at `hardware/ra8p1/ra_clock.h:848`.
- C3: `ra_adc.c:199,226` uses `R_ADC12_CH_BASE(n)`.

## Verdict
PASS_WITH_LIMITATIONS. The baseline and references are pinned. The build layer covers 2 of 30 configs.
