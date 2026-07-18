# NuttX Driver Port Status Matrix

**Date:** 2026-07-18
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
| 1 | ADC | rzv_adc.c | rzv_adc.h | functional | `refs/.../r_adc.c` | adc | (pending) | 12-bit SAR; ELC trigger support |
| 2 | CAN-FD | rzv_canfd.c | rzv_canfd.h | functional | `refs/.../r_canfd.c` | canfd, canfd-dual | (pending) | Dual CAN0/CAN1; DMAC integration |
| 3 | Clock/CPG | rzv_clock.c | rzv_cpg.h | functional | (internal) | nsh | (pending) | Clock divider init, PLL setup |
| 4 | DMAC | rzv_dmac.c | rzv_dmac.h | build-clean | `refs/.../r_dmac_b.c` | dmac-memcpy | [2026-07-18 re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) | CR8-0 one-shot polling memory copy only; hardware proof and peripheral DMA pending |
| 5 | Ether | rzv_ether.c | rzv_ether.h | functional | `refs/.../r_ether.c` | ether | (pending) | MAC controller; link-up polling |
| 6 | Ether PHY | rzv_ether_phy.c | (via rzv_ether.h) | functional | (FSP integrated) | ether | (pending) | MDIO/MDC phy register access |
| 7 | GPIO | rzv_gpio.c | rzv_gpio.h | functional | `refs/.../r_ioport.c` | nsh-leds | (pending) | Port 0–12; IRQ/edge config |
| 8 | GPT (16-bit) | rzv_gpt.c | rzv_gpt.h | functional | `refs/.../r_gpt.c` | pwm | (pending) | Pulse generation; PWM mode |
| 9 | GTM (32-bit) | rzv_gtm.c | rzv_gtm.h | functional | `refs/.../r_gtm.c` | gtm | (pending) | General timer; cascade mode |
| 10 | HRT | rzv_hrt.c | (via rzv_gpt.h) | functional | (derived from GPT) | pwm | (pending) | High-resolution timer backing; up-counter |
| 11 | I2C (RIIC) | rzv_i2c.c | rzv_i2c.h | functional | `refs/.../r_riic.c` | (nsh default) | (pending) | Native I2C master; DMA optional |
| 12 | ICU (CR8-0/1) | rzv_icu.c | rzv_icu.h | functional | (internal) | (framework) | (pending) | Interrupt control unit; priority routing |
| 13 | ICU (CM33) | rzv_icu_cm33.c | rzv_icu.h | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33-specific ICU routing |
| 14 | Idle Task | rzv_idle.c | (none) | stub | (none) | nsh | (pending) | CPU idle loop; WFI instruction |
| 15 | IPC Dispatch | rzv_ipc.c | (none) | functional | (none) | (framework) | (pending) | IPC message dispatcher; no protocol |
| 16 | IPC/IPCC | rzv_ipc_ipcc.c | (none) | functional | `nuttx/include/nuttx/ipcc.h` | ipcc, ipcc-multi | (pending) | NuttX IPCC character device; /dev/ipccN |
| 17 | IPC Raw | rzv_ipc_raw.c | (none) | functional | (internal) | (framework) | (pending) | Low-level MHU mailbox access |
| 18 | IRQ (CR8) | rzv_irq.c | (none) | functional | (internal) | (framework) | (pending) | Interrupt vector setup; CR8-0/1 GIC |
| 19 | IRQ (CM33) | rzv_irq_cm33.c | (none) | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33 Cortex-M33 NVIC setup |
| 20 | Low-Level UART | rzv_lowputc.c | (none) | functional | (SCIF-based) | (bootloader) | (pending) | Early putc for debugging; no buffering |
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
| 31 | SCI/SPI Master | rzv_sci_spi.c | rzv_sci_spi.h | functional | `refs/.../r_sci_b.c` | sci-spi-loopback | (pending) | Serial interface as SPI; clock/phase config |
| 32 | SCI/SPI Clock | rzv_sci_spi_clock.c | rzv_sci.h | functional | (FSP helper) | (shared) | (pending) | BRR/CKS divider calculation for SPI |
| 33 | SCI/SPI ISR | rzv_sci_spi_isr.c | rzv_sci.h | functional | (FSP helper) | (shared) | (pending) | Interrupt handlers for SPI events |
| 34 | SCIF UART | rzv_scif.c | rzv_sci.h | functional | `refs/.../r_sci_b.c` | nsh-scif | (pending) | 16-byte FIFO UART; multi-baud capable |
| 35 | SDHI | rzv_sdhi.c | rzv_sdhi.h | functional | `refs/.../r_sdhi.c` | sdhi | (pending) | SD/MMC host; DMA-backed; card-detect |
| 36 | Serial Framework | rzv_serial.c | (none) | functional | (NuttX core) | (framework) | (pending) | UART dispatcher; flow control |
| 37 | SPI (RSPI) | rzv_spi.c | rzv_spi.h | functional | `refs/.../r_rspi.c` | spi-loopback | (pending) | Native SPI master; CS control; DMAC |
| 38 | Startup (CR8) | rzv_start.c | (none) | functional | (internal) | (bootloader) | (pending) | CR8-0 boot; memory init; jump to main |
| 39 | Startup (CM33) | rzv_start_cm33.c | (none) | functional | (CM33 variant) | nsh-cm33 | (pending) | CM33 boot path; co-processor wake |
| 40 | Timer ISR | rzv_timerisr.c | (none) | functional | (internal) | (framework) | (pending) | System tick; clock interrupt dispatch |
| 41 | Watchdog | rzv_wdt.c | rzv_wdt.h | functional | `refs/.../r_wdt.c` | wdt | (pending) | Independent watchdog; refresh sequence |

---

## Summary

- **Total drivers:** 41
- **Functional:** 38
- **Build-clean:** 2
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
