---
phase: 2
title: "Phase 2: Arch foundation"
status: pending
priority: P1
effort: "1d"
dependencies: [1]
---

# Phase 2: Arch foundation: Kconfig, build, startup, clocks, GPIO

## Goal
Prove that the shared ra8 core layer selects the right core, headers, sources and clocks for RA8P1 (CM85 first, then CM33 startup), because every driver phase depends on it.

## Scope
- Modules: `ra_start.c`, `ra_clock.c` + `hardware/ra8p1/ra_clock.c`, `ra_mstp.c`, `ra_irq.c`, `ra_gpio.c`, `ra_lowputc.c`, `ra_timerisr.c`, `ra_memmng.c`, `ra_idle.c`, `chip.h`, `hardware/ra_{memorymap,hardware,clock,pinmap}.h`, `arch/arm/include/ra8/{chip.h,irq.h,ra8p1_irq.h}`
- Build files: `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/{Kconfig,Make.defs,CMakeLists.txt}`
- Board glue: `ra8p1_bringup.c`, `ra8p1_boot.c`, `ra8p1_app_examples.c`, `ra8p1_gpio.c`, `ra8p1_buttons.c`, `ra8p1_{auto,user}_leds.c`, `evk-ra8p1.h`, `include/{board.h,board.csv}`
- Configs: `nsh`, `nsh-leds` (CM85); CM33 startup through `ipc-cm33`
- FSP: `bsp/mcu/{all,ra8p1}`, `r_cgc` (`ek_ra8p1/cac`), `r_ioport` and `ra_gen/{bsp_clock_cfg.h,pin_data.c,vector_data.c}` from `ek_ra8p1/_quickstart`, plus `evk_ra8p1_dual_core/RA8P1_DSP_example_cpu1` for CM33 startup

## Tasks & Steps
1. Kconfig: the core choice, `RA8P1_GROUP`, the family selects, CM33 cache selects (any path to `ARMV8M_HAVE_*CACHE` on CM33 is a finding), dead options, and `depends on` symbols that do not exist.
2. Make.defs vs CMakeLists.txt parity, source by source and selector by selector. Check include order: `hardware/ra8e1` is on the path unconditionally, so look for bare includes that resolve to RA8E1 headers.
3. Clocks: every `RA_PCLK_*` ID used by any driver must have a case in the RA8P1 getter. Compare the frequencies with `bsp_clock_cfg.h`. Check MSTP bit tables against `R_MSTP` in core0.h.
4. Startup: vectors, the TCM/cache enable order (CM85 only), FPU/MVE enable, and the CM33 reset path with its separate vector table and memory view.
5. Check the IRQ table `ra8p1_irq.h` against the core0/core1 headers, per `hardware-fact-parity.md`. Skip SCI10/11.
6. GPIO/PFS: PWPR unlock order and the pin function codes. Check `board.h`/`board.csv` pins against the EK `pin_data.c`.
7. Check that the system tick (`ra_timerisr.c`) source and rate are not also claimed by PX4 HRT or PWM. The ownership question goes on to phase 11.

## Seed leads (unverified)
- `Make.defs` adds `ra_sci_spi.c` twice (inside the `RA_SCI_SPI` and `RA_SCI_I2C` blocks), so it may be compiled twice and cause duplicate symbols.
- `Make.defs` references `ra_flash.c` under `CONFIG_RA_FLASH`, but the file does not exist. Check whether that symbol is reachable.
- `ra_clock.c` is only 36 lines. Confirm the RA8P1 getter really lives in `hardware/ra8p1/ra_clock.c` and that both build systems compile it.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-arch-foundation.md`, with one trace matrix for CM85 and one for CM33 startup.

## Verification
- Read the generated `.config` from phase 1 artifacts (`nsh`, `ipc-cm33`) to confirm the effective core.
- `arm-none-eabi-nm` on the nsh ELF shows each foundation source linked exactly once.
