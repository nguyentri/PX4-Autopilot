---
title: "RA8 NuttX driver audit (RA8P1, EK-RA8P1)"
description: "Bounded, per-subsystem audit of every NuttX ra8 lower-half against RA8P1 FSP samples, device headers and PX4 consumers"
status: completed
priority: P1
effort: "8-10d"
tags: [ra8p1, ra8, nuttx, audit, fsp]
created: 2026-11-24
---

# RA8 NuttX driver audit (RA8P1, EK-RA8P1)

## Overview

Audit all 58 NuttX lower-halves in `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/`
(about 47 kLOC), the 30 `evk-ra8p1` sample configs, and the PX4 `renesas/ra8`
HAL plus the `evk-ra8p1` / `evk-ra8p1-io-cm33` boards. The method is the
`audit-ra8p1-px4-nuttx-port` skill applied one subsystem at a time.

References come from `refs/ra8p1/ra8p1-references.tar.gz` (27,108 entries). It
holds 88 EK-RA8P1 FSP samples, the dual-core DSP sample (cpu0/cpu1, which carries
`r_ipc`) and both device headers. The archive is **not extracted yet**. Its top
directory is `refs/`, so it must be unpacked with `--strip-components=1` into
`refs/ra8p1/` to match the layout the skill expects.

The deliverable is audit reports only. Fixes, flashing and hardware runs are out
of scope unless the user authorizes them per phase.

## Baseline

- PX4 `main` @ `12f73bead1e`, NuttX submodule @ `c4ef71b3aa`, apps @ `ee45eec37`.
- The NuttX submodule carries uncommitted R-Car changes from another session.
  RA8 files are clean. Phase 1 re-pins the baseline before auditing.
- Most recent RA8 history: NuttX commits `7aafbc26d8`, `31865dfc0f` and
  `4418e680fd` (sample repairs), and
  `plans/reports/code-reviewer-261123-2330-ra8-sample-fixes-review.md`, whose
  C1-C3 build breaks must be re-verified against these commits.

## Phases

| # | Phase | Core | Status |
|---|-------|------|--------|
| 1 | [Baseline, references, build matrix](./phase-01-start.md) | both | Done (static; 2/30 built) |
| 2 | [Arch foundation: Kconfig, build, startup, clocks, GPIO](./phase-02-arch-foundation.md) | CM85 + CM33 start | Done (static) |
| 3 | [ICU, ELC, DTC, DMAC](./phase-03-interrupts-events-dma.md) | CM85 | Done (static) |
| 4 | [SCI UART, SPI_B, SCI-SPI, IIC, SCI-I2C, I3C](./phase-04-serial-spi-i2c-i3c.md) | CM85 | Done (static) |
| 5 | [GPT, AGT, ULPT, POEG, CAC, RTC, WDT/IWDT, LPM](./phase-05-timers-watchdog-power.md) | CM85 (WDT also CM33) | Done (static) |
| 6 | [ADC_B (+ RA8E1 ADC blast radius)](./phase-06-analog-adc.md) | CM85 | Done (static) |
| 7 | [MRAM, OSPI_B, SDRAM, SDHI](./phase-07-memory-storage.md) | CM85 | Done (static) |
| 8 | [CANFD, Ethernet RMAC + PHYs, USB device](./phase-08-connectivity.md) | CM85 | Done (static) |
| 9 | [MIPI CSI + OV5640, mbed crypto](./phase-09-camera-crypto.md) | CM85 | Done (static) |
| 10 | [Dual-core IPC and CM33 image](./phase-10-dual-core-ipc.md) | CM85 + CM33 | Done (static) |
| 11 | [PX4 HAL and PX4 board integration](./phase-11-px4-hal-boards.md) | CM85 + CM33 | Done (static) |
| 12 | [Consolidation and status docs](./phase-12-consolidation.md) | both | Done |

Dependencies: phase 1 blocks everything else. Phase 2 blocks phases 3-11
because it settles the core choice, include paths and clock getters. Phase 3
blocks phases 4-9 because it settles ICU/ELC/DMA routing. Phases 4-9 are
independent of each other and can run in parallel, since each writes only its
own report. Phase 10 needs phase 2. Phase 11 needs phases 3, 4 and 5. Phase 12
needs all the others.

## Per-phase contract

Each phase follows SKILL.md "Start → Trace → Audit → Validate → Report":

- Name **exactly one core** per trace. Phases that touch both cores write a
  separate trace matrix per core.
- Run `collect-audit-context.sh <topic>` for each module in the phase.
- Follow the full trace chain: FSP `configuration.xml`/`ra_gen`, device header,
  `r_<module>`, Kconfig/Make.defs/CMake, the lower-half, the upper-half, board
  glue and defconfig, apps, PX4, ELF symbols, and on-target evidence. Mark a
  layer N/A only with a reason.
- State the RA8E1 (`fpb-ra8e1`) blast radius for every shared-code finding.
- Write one report per phase:
  `plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-<subsystem>.md`.
- Treat "Seed leads" in the phase files as unverified hypotheses from scouting,
  not findings.

## Authorization gates (ask before the phase needs them)

| Action | Default | Needed by |
|---|---|---|
| Extract the tarball into `refs/ra8p1/` (writes into gitignored `refs/`) | ask | phase 1 |
| Run `build_ra8p1.sh <config>` / `./build.sh renesas_evk-ra8p1_*` | ask | phases 1, 2-11 (symbol layer) |
| Any source fix | not in scope | separate `/ak-cook` plan |
| Flash or run on the EK-RA8P1 (the RZ/V2H standing authorization does not apply) | not in scope | evidence layer stays "missing" |

The NuttX builds share one tree with RZ/V2H and R-Car work, and `build_ra8p1.sh`
distcleans that tree. Run them serially and only when no other session is
building. Phase 1 also checks the build lock.

## Success Criteria

- [ ] Every `ra_*.c` in `arch/arm/src/ra8/` and every `evk-ra8p1/configs/*` is
      covered by exactly one phase report, or listed as N/A with a reason.
- [ ] Each report has a per-core trace matrix that cites FSP sample paths, plus
      findings with `path:line` evidence, severity, confidence and verdict per
      `references/evidence-and-verdicts.md`.
- [ ] Build, static and runtime evidence are kept separate. Nothing is promoted
      above source-audited or build-clean without a board transcript.
- [ ] The prior review's C1-C3 items are re-verified and closed or carried forward.
- [ ] The consolidated report ranks all findings and gives the RA8E1 blast radius.
      The port-status docs are updated only to the evidence tier reached.

## Non-goals

- RZ/V2H, R-Car and RA8E1-only drivers. RA8E1 is assessed only as blast radius
  from shared code.
- SCI10/SCI11 ELC events.
- FSP modules that have no NuttX driver (GLCDC, DRW, DAC_B, ACMPHS, SSI, ...).
  The consolidated report lists them as coverage gaps only.

<!-- slug: ra8-nuttx-driver-audit -->
