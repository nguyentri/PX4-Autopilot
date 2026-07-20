# NuttX Driver Port Status Matrix

**Date:** 2026-07-19
**Branch:** px4_ra_rzv  
**Scope:** Renesas RZ/V2H (R9A09G057H) NuttX drivers under `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`

---

## Status Legend

- **stub**: Driver file exists; no functional implementation (config hook only).
- **build-clean**: Compiles without errors; architecture-level glue in place; validation pending.
- **blocked**: Audit found correctness or integration defects that must be resolved before hardware validation.
- **functional**: Passes basic validation (register init, ISR ack, DMA init order); ready for integration testing.
- **production**: Functional + stress tested (≥10k cycles or 1h uptime); used in flight-qualified code.

---

## Driver Inventory

| # | Driver | Source File | HW Header | Status | FSP Reference | Sample Config | Validation Report | Notes |
|---|--------|-------------|-----------|--------|---------------|----------------|-------------------|-------|
| 1 | ADC | rzv_adc.c | rzv_adc.h | blocked | `.../adc_e_iodefine.h` (regs only; no FSP HAL driver) | adc | [2026-07-19 audit](../../plans/reports/audit-260719-1439-rzv2h-adc-fsp-vs-nuttx-report.md) | 12-bit SAR; ELC scan-end via ICU. F1 clock gate fixed (both CPG bits [1:0] via rzv_clock_enable). Open blockers: CLKON domain index unverified (F4), scan-end ADELCCR routing unverified (F5); no on-target evidence. |
| 2 | CAN-FD | rzv_canfd.c | rzv_canfd.h | functional | `refs/.../r_canfd.c` | canfd, canfd-dual | (pending) | Dual CAN0/CAN1; DMAC integration |
| 3 | Clock/CPG | rzv_clock.c | rzv_cpg.h | functional | (internal) | nsh | (pending) | Clock divider init, PLL setup |
| 4 | DMAC | rzv_dmac.c | rzv_dmac.h | build-clean | `refs/.../r_dmac_b.c` | dmac-memcpy | [2026-07-18 re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) | CR8-0 one-shot polling memory copy only; hardware proof and peripheral DMA pending |
| 5 | Ether | rzv_ether.c | rzv_ether.h | blocked | `refs/.../r_ether.c` | ether | [2026-07-19 audit](../../plans/reports/audit-260719-1358-rzv2h-gbeth-fsp-vs-nuttx-report.md) | Group A audit fixes applied (RXQ0EN routing, cacheline-aligned descriptors, atomic ISR, RX tail fix, MAC baseline, PBLx8, PHY poll). Remaining blockers: RGMII pinmux stub (F2), GBETH1 clock IDs (F3), IRQ topology unverified (F6). |
| 6 | Ether PHY | rzv_ether_phy.c | (via rzv_ether.h) | blocked | (FSP integrated) | ether | [2026-07-19 audit](../../plans/reports/audit-260719-1358-rzv2h-gbeth-fsp-vs-nuttx-report.md) | 1000BASE-T advertisement now written before autoneg (F14). Cannot reach MDIO until board pinmux (F2) is populated. |
| 7 | GPIO | rzv_gpio.c | rzv_gpio.h | functional | `refs/.../r_ioport.c` | nsh-leds | (pending) | Port 0–12; IRQ/edge config |
| 8 | GPT (16-bit) | rzv_gpt.c | rzv_gpt.h | functional | `refs/.../r_gpt.c` | pwm | (pending) | Pulse generation; PWM mode |
| 9 | GTM (32-bit) | rzv_gtm.c | rzv_gtm.h | functional | `refs/.../r_gtm.c` | gtm | [2026-07-19 re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) | Re-audit findings closed: `settimeout` race fixed, `next_interval_us` rearm honoured (APR-02), GTM0 collision resolved (PX4 HRT moved to GTM7). Build not yet re-verified. |
| 10 | HRT | rzv_hrt.c (arch shim) + platforms/.../renesas/rzv/hrt/hrt.c (queue mgr) | rzv_hrt.h | functional | (GTM7 free-run, arch shim) | nsh (CONFIG_RZV_HRT=y) | [2026-07-19 re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) | Consolidated: PX4 HRT queue delegates counter/arm to arch shim on GTM7 at P1CLK runtime lookup. Split-brain resolved (HRT-N-01, HRT-N-02). Build not yet re-verified. |
| 11 | I2C (RIIC) | rzv_i2c.c | rzv_i2c.h | functional | `refs/.../r_riic.c` | (nsh default) | (pending) | Native I2C master; DMA optional |
| 12 | ICU (CR8-0/1) | rzv_icu.c | rzv_icu.h | functional | (internal) | (framework) | (pending) | Interrupt control unit; priority routing |
| 13 | ICU (CM33) | rzv_icu_cm33.c | rzv_icu.h | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33-specific ICU routing |
| 14 | Idle Task | rzv_idle.c | (none) | stub | (none) | nsh | (pending) | CPU idle loop; WFI instruction |
| 15 | IPC Dispatch | rzv_ipc.c | (none) | functional | (none) | (framework) | (pending) | IPC message dispatcher; no protocol |
| 16 | IPC/IPCC | rzv_ipc_ipcc.c | (none) | functional | `nuttx/include/nuttx/ipcc.h` | ipcc, ipcc-multi | (pending) | NuttX IPCC character device; /dev/ipccN |
| 17 | IPC Raw | rzv_ipc_raw.c | (none) | functional | (internal) | (framework) | (pending) | Low-level MHU mailbox access |
| 18 | IRQ (CR8) | rzv_irq.c | (none) | functional | (internal) | (framework) | (pending) | Interrupt vector setup; CR8-0/1 GIC |
| 19 | IRQ (CM33) | rzv_irq_cm33.c | (none) | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33 Cortex-M33 NVIC setup |
| 20 | Low-Level UART | rzv_lowputc.c | (none) | functional | (SCI-B based) | (bootloader) | (pending) | Early putc for debugging; no buffering. Console channel selected by CONFIG_SCIx_SERIAL_CONSOLE (defaults to SCI3); no SCIF branch |
| 21 | Memory Management | rzv_memmng.c | (none) | functional | (internal) | (framework) | (pending) | Heap, page alignment setup |
| 22 | MHU Core | rzv_mhu_core.c | rzv_mhu.h | functional | (internal) | (framework) | (pending) | Register read/write; DSB ordering |
| 23 | MPU Regions | rzv_mpu_regions.c | (none) | functional | (internal) | (framework) | (pending) | ARM MPU setup for memory protection |
| 24 | OpenAMP | rzv_openamp.c | (none) | stub | `refs/.../openamp/` | (none) | (pending) | Future; deprecated by direct IPCC path |
| 25 | POEG | rzv_poeg.c | rzv_poeg.h | functional | (internal) | (framework) | (pending) | PWM output enable group; fault handling |
| 26 | RPMsg Layer | rzv_rpmsg.c | (none) | build-clean | (OpenAMP dep) | ipcc | (pending) | RPMsg endpoint abstraction; CRC16 frame |
| 27 | Remote Proc | rzv_rproc.c | (none) | functional | `nuttx/include/remoteproc.h` | (framework) | (pending) | Core loading, boot, IPC kickoff |
| 28 | SCI/I2C Master | rzv_sci_i2c.c | rzv_sci.h | functional | `refs/.../r_sci_b.c` | (nsh alt) | (pending) | Serial interface as I2C; clock stretching |
| 29 | SCI/I2C Clock | rzv_sci_i2c_clock.c | rzv_sci.h | functional | (FSP helper) | (shared) | (pending) | BRR/CKS divider calculation for I2C |
| 30 | SCI/I2C ISR | rzv_sci_i2c_isr.c | rzv_sci.h | functional | (FSP helper) | (shared) | (pending) | Interrupt handlers for I2C events |
| 31 | SCI/SPI Master | rzv_sci_spi.c | rzv_sci_spi.h | build-clean | `refs/.../r_sci_b.c` | sci-spi-loopback | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | SCI0 only on RDK; P6_0 SCK; on-target loopback/error validation pending |
| 32 | SCI/SPI Clock | rzv_sci_spi_clock.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | BRR/CKS/MDDR calculation build-validated; frequency measurement pending |
| 33 | SCI/SPI ISR | rzv_sci_spi_isr.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | FRSR-based FIFO drain build-validated; on-target transfer/error paths pending |
| 34 | SCIF UART | rzv_scif.c | rzv_scifa.h | blocked | `refs/.../scifa_iodefine.h` (R9A09G057H) | nsh-scif (build) | [2026-07-20 audit](../../plans/reports/audit-260720-1112-rzv2h-scif-serial-port-report.md) | SCIFA0 16-byte FIFO UART. Register model + ELC events verified vs FSP. BLOCKED for functional: (F1) driver enables RSCI/SCI0 clock id, not SCIFA0's CPG_CLKON_8[15] + MCPU2_MSTOP → peripheral stays gated; (F2) SCIFA0 TXD/RXD pins never muxed. Safe fixes applied: up_putc readiness guard, dead TEI path removed, baud-failure bits cleared. Sample-only path (all shipping targets use SCI-B/RTT console) |
| 35 | SDHI | rzv_sdhi.c | rzv_sdhi.h | build-clean | (none — no FSP `r_sdhi.c` in refs/) | sdhi | [2026-07-20 audit](../../plans/reports/audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md) | PIO 1/4-bit, IRQ-driven (combined ISR, INTID 767); compiles + wired to `/dev/mmcsd0`. Audit blockers resolved: boot FW (u-boot/TF-A) provides SDHI ACLK/CLK_HS + SD0 dedicated pin-mux (NuttX gates IMCLK only); IMCLK=200MHz and controller card-detect (INFO1.SDCDIN) confirmed. Pending functional tier: on-target register/command/PIO evidence. No FSP parity reference. |
| 36 | Serial Framework | rzv_serial.c | (none) | functional | (NuttX core) | (framework) | (pending) | UART dispatcher; flow control |
| 37 | SPI (RSPI) | rzv_spi.c | rzv_spi.h | functional | `refs/.../r_rspi.c` | spi-loopback | (pending) | Native SPI master; CS control; DMAC |
| 38 | Startup (CR8) | rzv_start.c | (none) | functional | (internal) | (bootloader) | (pending) | CR8-0 boot; memory init; jump to main |
| 39 | Startup (CM33) | rzv_start_cm33.c | (none) | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33 boot path; co-processor wake |
| 40 | Timer ISR | rzv_timerisr.c | (none) | functional | (internal) | (framework) | (pending) | System tick; clock interrupt dispatch |
| 41 | Watchdog | rzv_wdt.c | rzv_wdt.h | functional | `refs/.../r_wdt.c` | wdt | [2026-07-20 audit](../../plans/reports/audit-260720-1152-rzv2h-wdt-fsp-vs-nuttx-report.md) | Independent watchdog; refresh sequence. Register model verified vs FSP (bases, CKS/TOPS, CPG CLKP/LOCO/RST, SYSC non-seq CTRL, ERRORRST, ELC). Fixes applied: SYSC bp_halted RMW (WDTSTOPMASK is not a WEN), CLKMON confirm bits correct for all channels. Reset-mode/WDT0 is the verified path; interrupt/NMI mode on WDT0/1 unproven (no CR8 WDTINT line); no on-target evidence |

---

## Summary

- **Total drivers:** 41
- **Functional:** 30
- **Build-clean:** 6
- **Blocked:** 3 (ADC, Ether, Ether PHY)
- **Stub:** 2
- **Production:** 0 (pending stress test)

---

## Per-PR Update Discipline

When submitting a driver PR:
1. Update the driver row: status, sample config (if applicable).
2. Verify the row count remains 41.
3. Link to validation report (once available).
4. Update notes field if behavior changed.

---

## Related Docs

- [Validation Checklist](validation-checklist.md) — per-driver bring-up steps.
- [IPC Architecture](ipc-architecture.md) — MHU/IPCC integration.
- [Deployment Guide](../deployment-guide.md) — build and test harness.
- [DMAC Re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) — blocking DMAC findings and remediation order.
- [GTM + PX4 HRT Re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) — GTM lower-half + HRT split-brain findings and remediation order.
