---
phase: 7
title: "Phase 7: MRAM, OSPI_B, SDRAM, SDHI"
status: pending
priority: P2
effort: "1d"
dependencies: [3]
---

# Phase 7: Memory and storage (CM85)

## Scope
- Modules: `ra_mram.c`, `ra_ospi_b.c`, `ra_sdram.c`, `ra_sdhi.c`
- Board glue: `ra8p1_mram.c`, `ra8p1_ospi_b.c`, `ra8p1_ospi_test.c`, `ra8p1_sdram.c`, `ra8p1_sdhi.c`; linker scripts `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1/scripts/{evk-ra8p1.ld,evk-ra8p1_non_ospi.ld,cm85/,common/}`
- Configs: `mram`, `ospi-b`, `sdram`, `sdhi`
- FSP: `r_mram` (`mram`, the only carrier), `r_ospi_b` (`ospi_b`, `mbed_crypto`), `sdram` (BSP `bsp_sdram`; there is no `r_` module), `r_sdhi` (`sdhi`, the only carrier)

## Tasks & Steps
1. MRAM: the program/erase command sequence, the write unit and alignment, the FACI/FCACHE interaction, MTD geometry, and running code from MRAM while it is being programmed.
2. OSPI_B: the xSPI protocol switch (SPI to OPI), memory-mapped mode, the calibration/DS timing, and the board flash part (EK: check `configuration.xml`). Check whether the `ospi-b` auto-test is functional; the prior review said it was not.
3. SDRAM: the init sequence and timing parameters from FSP `bsp_sdram`, refresh, the 0x68000000 window, the MPU attributes and the linker placement. Run `placement.py`/`verify_placement.sh` statically.
4. SDHI: clock divider, card detect/WP pins, the DMA/DTC path, cache maintenance and the timeout paths against the `sdio_dev_s` contract.
5. Check that each linker script's memory regions agree with `memory.yaml`/`memory.xml` and the README addresses.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-memory-storage.md`
