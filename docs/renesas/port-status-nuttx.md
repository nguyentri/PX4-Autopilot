# NuttX Driver Port Status Matrix

**Date:** 2026-08-02
**Branch:** gitlab-migration
**Scope:** Renesas RZ/V2H (R9A09G057H) NuttX drivers under `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`

---

## Status Legend

- **stub**: Driver file exists; no implementation beyond config hook(s).
- **source-audited**: Source contracts, pin mappings, or board glue line up; no build or target transcript asserted.
- **build-clean**: Compiles without errors; architecture-level glue in place; validation pending.
- **bounded on-target**: A named board transcript exists, but it is intentionally narrow and does not promote the subsystem to full target-ready status.
- **blocked**: Audit found correctness or integration defects that must be resolved before hardware validation.
- **production**: Source/build plus stress tested (≥10k cycles or 1h uptime); used in flight-qualified code.

For current planning, target readiness uses the stricter evidence tiers in the
[RDK-RZV2H PX4 NuttX Port Goal Plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md):
configured, build-clean, hardware-ready, bounded on-target, PX4-integrated,
and stress-validated. A row without a linked target transcript remains
**needs on-target validation**.

Current board evidence is narrow but important: CR8-0 `nsh-rtt` reaches a
working SCI4 shell with RX/TX interrupt delivery and RTT diagnostics. The SIH
transcript adds interactive shell use, one GTM7-backed HRT callback test,
work-queue execution, and simulated PX4 topics. It does not validate every
driver or the integrated PX4 image.
Because SIH excludes physical payload/sensor buses and GPT/PWM, that evidence
does not promote any physical lower-half. Capture transport, cold-cycle
provenance, pin-safety measurement, and soak testing remain open.
The 2026-08-02 default, DShot, SIH, and core-only builds all include the
NuttX reset API. Their ELFs link `board_on_reset`, `board_reset`, and
`up_systemreset`; runtime reset and motor-pin safety are not yet target-proven.

---

## Driver Inventory

| # | Driver | Source File | HW Header | Status | FSP Reference | Sample Config | Validation Report | Notes |
|---|--------|-------------|-----------|--------|---------------|----------------|-------------------|-------|
| 1 | ADC | rzv_adc.c | rzv_adc.h | blocked | `.../adc_e_iodefine.h` (regs only; no FSP HAL driver) | adc | [2026-07-19 audit](../../plans/reports/audit-260719-1439-rzv2h-adc-fsp-vs-nuttx-report.md) | 12-bit SAR; ELC scan-end via ICU. F1 clock gate fixed (both CPG bits [1:0] via rzv_clock_enable). Open blockers: CLKON domain index unverified (F4), scan-end ADELCCR routing unverified (F5); no on-target evidence. |
| 2 | CAN-FD | rzv_canfd.c | rzv_canfd.h | source-audited | `refs/.../r_canfd.c` | canfd, canfd-dual | (pending) | Dual CAN0/CAN1; DMAC integration |
| 3 | Clock/CPG | rzv_clock.c | rzv_cpg.h | source-audited | (internal) | nsh | (pending) | Clock divider init, PLL setup |
| 4 | DMAC | rzv_dmac.c | rzv_dmac.h | build-clean | `refs/.../r_dmac_b.c` | dmac-memcpy | [DMAC API contract](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.h) | CR8-0 polling one-shot memory copy plus hardware-triggered, one-shot memory-to-peripheral routing used by serial and opt-in DShot. Checked-in CMSIS/FSP verifies DMkSEL offsets/unit mapping and activation IDs. Builds clean; on-target request routing, transfer ordering, and peripheral behavior remain unvalidated. |
| 5 | Ether | rzv_ether.c | rzv_ether.h | blocked | `refs/.../r_ether.c` | ether | [2026-07-19 audit](../../plans/reports/audit-260719-1358-rzv2h-gbeth-fsp-vs-nuttx-report.md) | Group A audit fixes applied (RXQ0EN routing, cacheline-aligned descriptors, atomic ISR, RX tail fix, MAC baseline, PBLx8, PHY poll). Remaining blockers: RGMII pinmux stub (F2), GBETH1 clock IDs (F3), IRQ topology unverified (F6). |
| 6 | Ether PHY | rzv_ether_phy.c | (via rzv_ether.h) | blocked | (FSP integrated) | ether | [2026-07-19 audit](../../plans/reports/audit-260719-1358-rzv2h-gbeth-fsp-vs-nuttx-report.md) | 1000BASE-T advertisement now written before autoneg (F14). Cannot reach MDIO until board pinmux (F2) is populated. |
| 7 | GPIO | rzv_gpio.c | rzv_gpio.h | source-audited | `refs/.../r_ioport.c` | nsh-leds | (pending) | NuttX ports 0-11 map to P20-P2B; 86 bonded pins; IRQ/edge config |
| 8 | GPT (32-bit) | rzv_gpt.c | rzv_gpt.h | source-audited | `refs/.../r_gpt.c` | pwm | [GPT/PWM source contract](../../test/rzv2h_gpt_pwm_contract_test.py) | Pulse generation and PWM mode; target waveform proof pending |
| 9 | GTM (32-bit) | rzv_gtm.c | rzv_gtm.h | build-clean | `refs/.../r_gtm.c` | gtm | [GTM source contract](../../test/rzv2h_gtm_contract_test.py) | Reset pulse/release now follows the FSP lifecycle; failure and explicit uninitialize paths stop, detach, reset, clock-gate, and free the lower-half. Board registration handles `timer_register()` as a pointer and reports/cleans every configured channel. Source contracts and a fresh `gtm` config build pass; `/dev/timer0` and `/dev/timer2` target timing/stop evidence remains required. |
| 10 | HRT | rzv_hrt.c (arch shim) + platforms/.../renesas/rzv/hrt/hrt.c (queue mgr) | rzv_hrt.h | bounded on-target | (GTM7 free-run, arch shim) | PX4 board config (`CONFIG_RZV_HRT=y`) | [2026-07-30 SIH transcript](./px4_nuttx_rzv2h_sil.txt) | PX4 HRT delegates counter/arm to the arch GTM7 shim at runtime P1CLK. SIH `system_time hrt-test` passed with 22,044 us sleep and 4 us callback latency. Exact load provenance, clock measurement, long-run monotonicity, jitter, drift, and load bounds remain required. |
| 11 | I2C (RIIC) | rzv_i2c.c | rzv_i2c.h | source-audited | `refs/.../r_riic.c` | (nsh default) | (pending) | Native I2C master; DMA optional |
| 12 | ICU (CR8-0/1) | rzv_icu.c | rzv_icu.h | source-audited | (internal) | (framework) | (pending) | Interrupt control unit; priority routing |
| 13 | ICU (CM33) | rzv_icu_cm33.c | rzv_icu.h | source-audited | (CM33 variant) | nsh-cm33 | (pending) | CM33-specific ICU routing |
| 14 | Idle Task | rzv_idle.c | (none) | stub | (none) | nsh | (pending) | CPU idle loop; WFI instruction |
| 15 | IPC Dispatch | rzv_ipc.c | (none) | build-clean | (none) | (framework) | (pending) | IPC message dispatcher; no target traffic proof |
| 16 | IPC/IPCC | rzv_ipc_ipcc.c | (none) | build-clean | `nuttx/include/nuttx/ipcc.h` | ipcc, ipcc-multi | (pending) | NuttX IPCC character device; default/SIH images disable it |
| 17 | IPC Raw | rzv_ipc_raw.c | (none) | build-clean | (internal) | ipcc-multi | (pending) | MHU doorbell + DDR rings; peer and cache-coherency proof pending |
| 18 | IRQ (CR8) | rzv_irq.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` evidence | Interrupt vector setup; CR8-0/1 GIC. The `nsh-rtt` pass validates the SCI4 TX/RX interrupt path only. |
| 19 | IRQ (CM33) | rzv_irq_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33 | (pending) | CM33 Cortex-M33 NVIC setup; target and final link proof remain G11 work. |
| 20 | Low-Level UART | rzv_lowputc.c | (none) | source-audited | (SCI-B based) | (bootloader) | (pending) | Early putc for debugging; no buffering. Current policy: standalone CR8-0 `nsh-rtt` uses SCI4 shell + RTT diagnostics; integrated PX4 CR8-0 uses RTT0 console/debug and bypasses SCI low-setup so SCI3 remains untouched. |
| 21 | Memory Management | rzv_memmng.c | (none) | build-clean | (internal) | (framework) | (pending) | Heap and page-alignment setup; explicit target heap evidence remains pending. |
| 22 | MHU Core | rzv_mhu_core.c | rzv_mhu.h | build-clean | (internal) | (framework) | (pending) | Register read/write and DSB ordering; target channel proof pending |
| 23 | MPU Regions | rzv_mpu_regions.c | (none) | source-audited | (internal) | (framework) | (pending) | ARM MPU setup for memory protection; exact-image region snapshot remains pending. |
| 24 | OpenAMP | rzv_openamp.c | (none) | build-clean | `refs/.../openamp/` | ipcc, ipcc-multi | (pending) | CA55 ↔ CR8 sample path only; disabled in default/SIH |
| 25 | POEG | rzv_poeg.c | rzv_poeg.h | source-audited | (internal) | (framework) | (pending) | PWM output enable group; target fault and safe-state proof pending. |
| 26 | RPMsg Layer | rzv_rpmsg.c | (none) | build-clean | (OpenAMP dep) | ipcc | (pending) | OpenAMP endpoint wrapper with bounded RX packet queue; no application CRC framing |
| 27 | Remote Proc | rzv_rproc.c | (none) | build-clean | `nuttx/include/remoteproc.h` | ipcc | (pending) | CA55/CR8 resource and kickoff path; target boot/recovery proof pending |
| 28 | SCI/I2C Master | rzv_sci_i2c.c | rzv_sci.h | build-clean | `refs/.../r_sci_b_i2c/` | hil-full (SCI7) | [SCI7 re-audit](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/audit-260728-rzv2h-sci7-i2c-reaudit.md) | `CONFIG_RZV_SCI7_I2C` uses FSP-compatible SCISPICLK timing, fixed GIC TXI/TEI lines, and P76/P77 FSP-parity pins; board registration retains logical bus 7. Both the nested NuttX `hil-full` build and the PX4 `renesas_rdk-rzv2h_default` build now pass. BMP280 transactions, analyzer capture, NACK/timeout, and recovery remain on-target gates. |
| 29 | SCI/I2C Clock | rzv_sci_i2c_clock.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [goal-plan reconciliation](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/phase-03-rzv2h-blocked-driver-closure-plan.md) | Runtime P5CLK calculation; 100 MHz/400 kHz reproduces FSP CKS0, BRR3, MDDR131, 399780 Hz, and 30-cycle SDA delay. Frequency measurement and on-target timing capture remain pending. |
| 30 | SCI/I2C ISR | rzv_sci_i2c_isr.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | (pending) | Interrupt handlers build with the SCI7 path; target event/error proof remains pending. |
| 31 | SCI/SPI Master | rzv_sci_spi.c | rzv_sci_spi.h | build-clean | `refs/.../r_sci_b.c` | sci-spi-loopback | [SCI/SPI source contract](../../test/rzv2h_sci_spi_contract_test.py) | SCI0 only on RDK; P6_0 SCK. The isolated sample now registers `/dev/spi0`, includes `spitool`, and uses a no-op CMD/DATA hook because SCI-B has no separate CMD/DATA signal. Fresh build and source contract pass. Run the documented P5_0 MOSI↔P5_1 MISO `spi exch` loopback plus removed-jumper error check on target. |
| 32 | SCI/SPI Clock | rzv_sci_spi_clock.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | BRR/CKS/MDDR calculation build-validated; frequency measurement pending |
| 33 | SCI/SPI ISR | rzv_sci_spi_isr.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | FRSR-based FIFO drain build-validated; on-target transfer/error paths pending |
| 34 | SCIF UART | rzv_scif.c | rzv_scifa.h | blocked | `refs/.../scifa_iodefine.h` (R9A09G057H) | nsh-scif (build) | [2026-07-20 audit](../../plans/reports/audit-260720-1112-rzv2h-scif-serial-port-report.md) | SCIFA0 16-byte FIFO UART. Register model + ELC events verified vs FSP. BLOCKED for functional: (F1) driver enables RSCI/SCI0 clock id, not SCIFA0's CPG_CLKON_8[15] + MCPU2_MSTOP → peripheral stays gated; (F2) SCIFA0 TXD/RXD pins never muxed. Safe fixes applied: up_putc readiness guard, dead TEI path removed, baud-failure bits cleared. Sample-only path (all shipping targets use SCI-B/RTT console) |
| 35 | SDHI | rzv_sdhi.c | rzv_sdhi.h | build-clean | (none — no FSP `r_sdhi.c` in refs/) | sdhi | [2026-07-20 audit](../../plans/reports/audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md) | PIO 1/4-bit, IRQ-driven (combined ISR, INTID 767); compiles + wired to `/dev/mmcsd0`. Pending on-target register/command/PIO evidence. No FSP parity reference; sample/post-G9 only and does not gate the first drone-equivalent PX4 run. |
| 36 | Serial Framework | rzv_serial.c | (none) | bounded on-target | (NuttX core) | (framework) | `nsh-rtt` evidence | UART dispatcher; flow control. FIFO RX is validated on SCI4 under `nsh-rtt`; payload channels and error injection remain unproved. `TIOCGICOUNT` and the non-opening `rzv_serial_get_icount()` snapshot path back PX4 `serial_status`; counters are boot-lifetime modulo-2^32 register-transfer or sampled-error counts. |
| 37 | SPI (RSPI) | rzv_spi.c | rzv_spi.h | build-clean | `refs/.../r_rspi.c` | spi-loopback, hil-spi-loopback | [2026-07-27 HIL registration fix](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/tester-260727-0838-rzv2h-hil-spi-registration.md) | Native polled SPI master with board GPIO CS. `hil-spi-loopback` now runs late board bring-up before direct `hwtest_main`, so `/dev/spi0` registration is linked into the boot path; internal loopback requires no jumper. Clean HIL/standalone builds pass; loopback, MPU9250 WHOAMI/data/DRDY, and error recovery remain on-target gates. |
| 38 | Startup (CR8) | rzv_start.c | (none) | bounded on-target | (internal) | (bootloader) | `nsh-rtt` + SIH transcripts | CR8-0 startup reaches shells in bounded captures. Exact-image cold/debugger provenance and integrated default startup remain pending. |
| 39 | Startup (CM33) | rzv_start_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33 | (pending) | CM33 boot path; final link, co-processor wake, and runtime proof remain G11 work. |
| 40 | Timer ISR | rzv_timerisr.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` + SIH transcripts | System tick supports bounded shell/runtime captures; explicit clock/load/jitter evidence remains pending. |
| 41 | Watchdog | rzv_wdt.c | rzv_wdt.h | build-clean | separate WDT sample/CMSIS evidence; not active in drone ref | wdt | [2026-07-20 audit](../../plans/reports/audit-260720-1152-rzv2h-wdt-fsp-vs-nuttx-report.md) | Independent watchdog; refresh sequence. Reset-mode/WDT0 is source-audited, but no on-target evidence exists. Automatic sample only, no NSH command-registration requirement, and non-gating for G3-G9. |
| 42 | System reset (CR8) | rzv_systemreset.c | CMSIS/FSP WDT/CPG definitions | build-clean | FSP WDT reset routing | PX4 default/DShot/SIH/core-only | [reset source contract](../../test/rzv2h_gpt_pwm_contract_test.py) | `up_systemreset()` uses the CR8-0 WDT2 or CR8-1 WDT3 route, enables the required clock source, releases reset, selects the shortest supported timeout, routes underflow to system reset, and starts the watchdog with interrupts masked. All four board ELFs link the reset chain. Actual reset latency, post-reset boot state, repeated resets, and inactive motor-pin levels remain target gates. |

---

## Summary

- **Total drivers:** 42
- **Source-audited:** 12
- **Build-clean:** 20
- **Bounded on-target:** 5
- **Blocked:** 4 (ADC, Ether, Ether PHY, SCIF UART)
- **Stub:** 1
- **Production:** 0 (pending stress test)

Plan-critical reconciliation:

- Standalone CR8-0 defconfigs are normalized to SCI4 or RTT-only diagnostics.
- `nsh-cr8_1` and `nsh-cm33` select SCI5 and SCI9. CM33 linking and both target
  proofs remain final-milestone work.
- Board Make/CMake source selection is reconciled for the audited configs.
- `hil-spi-loopback` explicitly selects late board initialization; its clean
  image links the SPI registration chain before direct `hwtest_main`.
- `hil-full` is SCI7 build-clean and now passes both nested NuttX and PX4
  builds, but it still cannot be hardware-ready until the BMP280 transaction
  and recovery procedure passes on target.
- CR8-1/CM33/OpenAMP work is non-gating until the CR8-0 PX4 drone path passes.

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
- [DMAC Re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) — historical findings and remediation order.
- [DShot Runtime Fix Review](../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md) — current DMAC routing review and remaining hardware-only validation gaps.
- [GTM + PX4 HRT Re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) — GTM lower-half + HRT split-brain findings and remediation order.
