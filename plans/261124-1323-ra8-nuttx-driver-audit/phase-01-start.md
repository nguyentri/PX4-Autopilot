---
phase: 1
title: "Phase 1: Baseline, references, build matrix"
status: pending
priority: P1
effort: "0.5d"
dependencies: []
---

# Phase 1: Baseline, references, build matrix

## Goal
Make the FSP references usable, pin the baseline, and record which RA8P1 configs build today, so later phases can cite symbols rather than config text.

## Files to Create / Modify
- Create (gitignored, needs user OK): `refs/ra8p1/{R7KA8P1KF_core0.h,R7KA8P1KF_core1.h,ek_ra8p1/,evk_ra8p1_dual_core/}`
- Create: `plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-baseline-and-build-matrix.md`
- No source edits.

## Tasks & Steps
1. Ask for authorization, then run `tar xzf refs/ra8p1/ra8p1-references.tar.gz -C refs/ra8p1 --strip-components=1`. The archive's top directory is `refs/`, so a plain extract would put the headers in `refs/` instead of `refs/ra8p1/`. Verify that `refs/ra8p1/R7KA8P1KF_core0.h`, `R7KA8P1KF_core1.h` and `ek_ra8p1/adc/` exist, then make the tree read-only (`chmod -R a-w`).
2. Check that `collect-audit-context.sh adc` now finds FSP carriers. If the script assumes other paths, record that and pass paths explicitly; do not edit the skill unless the user authorizes it.
3. Record the PX4, NuttX and apps SHAs and `git -C platforms/nuttx/NuttX/nuttx status --short -- arch/arm/src/ra8 boards/arm/ra8` (it must be clean).
4. Map each NuttX config to the core it selects: `build_ra8p1.sh --list`, plus Kconfig semantics for every defconfig. Flag any config that sets only `RA_CPU_CORE=<n>` or `ARCH_CORTEXM33=y`. Candidate CM33 configs: `ipc-cm33`, `wdt-cm33` and PX4 `evk-ra8p1-io-cm33/nuttx-config/nsh`.
5. If builds are authorized, run serially: all 30 `build_ra8p1.sh <config>`, then `./build.sh renesas_evk-ra8p1_{default,dshot,test}`, `renesas_evk-ra8p1-io-cm33_default` and `renesas_fpb-ra8e1_{default,dshot,test}`. Record the exit code, the first error and the ELF path. Keep each ELF, or its `nm` output, under `reports/artifacts/` for later symbol checks. Check the build lock first; never build at the same time as another session.
6. Re-check the prior review's C1-C3 items (`ra_poeg_register`, `ra_clock_pclkb_frequency`, `RA_ADC1_BASE`) against NuttX `7aafbc26d8..4418e680fd` and record each as closed or open.

## Verification
- `ls refs/ra8p1/ek_ra8p1 | wc -l` prints 88, and `ls refs/ra8p1/evk_ra8p1_dual_core` lists the cpu0 and cpu1 samples.
- The build-matrix table lists 30 NuttX configs and 7 PX4 targets, each with an exit code or "not run (unauthorized)".

## Risks
- `build_ra8p1.sh` distcleans the shared NuttX tree, which disturbs RZ/V2H and R-Car sessions. Run it serially and only after checking the lock.
- Distclean deletes `RTT.zip`. Set `NUTTX_DOWNLOAD_CACHE` when the host is offline.
