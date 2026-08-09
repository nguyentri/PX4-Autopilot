# NuttX Driver Port Status Matrix

**Date:** 2026-08-09
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

Reference cells follow the core-selection and evidence rules in the
[RZ/V2H Reference Source Map](reference-source-map.md). EVK examples are
recorded source/configuration evidence, not RDK runtime proof. Compact paths
in the table are relative to `refs/` unless they begin with another repository
root such as `nuttx/`.

---

## Driver Inventory

| # | Driver | Source File | HW Header | Status | FSP Reference | Sample Config | Validation Report | Notes |
|---|--------|-------------|-----------|--------|---------------|----------------|-------------------|-------|
| 1 | ADC | rzv_adc.c | rzv_adc.h | blocked | `rzv2h_evk/adc_e/*_<core>_ep`: `r_adc_e` + generated config | adc | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md) | Dedicated FSP driver exists for all three cores. Clock/ELC concerns from the older audit are superseded; byte-wide ADELCCR is still written by an odd-address halfword access. No target conversion evidence. |
| 2 | CAN-FD | rzv_canfd.c | rzv_canfd.h | bounded on-target | `rzv2h_evk/can_fd/*_<core>_ep`: `r_canfd` + generated config | canfd, canfd-dual | J-Link/GDB + RTT, 2026-08-09 | CAN0 internal loopback passed four frames with matching IDs, DLCs, and payloads through `/dev/can0`. The corrected TX access window is `BASE+0x10000`; loopback completion is serviced synchronously because late selectable-ICU route writes did not latch. External-bus and CAN1 interrupt-driven operation remain target gates. |
| 3 | Clock/CPG | rzv_clock.c | rzv_cpg.h | source-audited | (internal) | nsh | (pending) | Clock divider init, PLL setup |
| 4 | DMAC | rzv_dmac.c | rzv_dmac.h | bounded on-target | `rzv2h_evk/spi_b/*_<core>_ep`: `r_dmac_b` consumer example | dmac-memcpy | J-Link/GDB + RTT, 2026-08-09 | CR8-0 software-triggered block-mode copy passed a 1024-byte memory comparison (`status=0x00000040`). Hardware-triggered peripheral pacing used by serial and opt-in DShot remains unvalidated. No standalone EVK DMAC project. |
| 5 | Ether | rzv_ether.c | rzv_ether.h | blocked | `rzv2h_gb_ether/plat/ether/r_ether.c` (legacy CA55; no EVK EP) | ether | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md) | Legacy same-IP evidence only. Open critical descriptor-stride and ETH0 clock-ID defects plus RGMII pinmux, IRQ topology, locking, and link-state blockers. Per-core FSP/generated parity absent. |
| 6 | Ether PHY | rzv_ether_phy.c | (via rzv_ether.h) | blocked | `rzv2h_gb_ether/plat/ether/r_phy.c` (legacy CA55; no EVK EP) | ether | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md) | Legacy PHY/skew evidence only. Exact fitted PHY, straps, RGMII timing ownership, per-core integration, and target MDIO/traffic remain open. |
| 7 | GPIO | rzv_gpio.c | rzv_gpio.h | source-audited | core-matched EVK `r_ioport` + generated `pin_data.c`; integrated RDK pin ownership | nsh-leds | (pending) | NuttX ports 0-11 map to P20-P2B; 86 bonded pins; IRQ/edge config |
| 8 | GPT (32-bit) | rzv_gpt.c | rzv_gpt.h | source-audited | `rzv2h_evk/gpt` + `gpt_input_capture` core-matched EPs: `r_gpt` | pwm | [GPT/PWM source contract](../../test/rzv2h_gpt_pwm_contract_test.py) | Pulse generation and PWM mode; target waveform proof pending |
| 9 | GTM (32-bit) | rzv_gtm.c | rzv_gtm.h | bounded on-target | `rzv2h_evk/gtm/*_<core>_ep`: `r_gtm` + generated config | gtm | J-Link/GDB + RTT, 2026-08-09 | RTT NSH runs on `/dev/timer0` and `/dev/timer2` each completed 20 status samples, five signal deliveries, stop, and clean finish. Long-run timing accuracy, jitter, and fault injection remain target gates. |
| 10 | HRT | rzv_hrt.c (arch shim) + platforms/.../renesas/rzv/hrt/hrt.c (queue mgr) | rzv_hrt.h | bounded on-target | (GTM7 free-run, arch shim) | PX4 board config (`CONFIG_RZV_HRT=y`) | [2026-07-30 SIH transcript](./px4_nuttx_rzv2h_sil.txt) | PX4 HRT delegates counter/arm to the arch GTM7 shim at runtime P1CLK. SIH `system_time hrt-test` passed with 22,044 us sleep and 4 us callback latency. Exact load provenance, clock measurement, long-run monotonicity, jitter, drift, and load bounds remain required. |
| 11 | I2C (RIIC) | rzv_i2c.c | rzv_i2c.h | source-audited | `rzv2h_evk/riic_master/*_<core>_ep`: `r_riic_master` | (nsh default) | (pending) | Native I2C master; DMA optional |
| 12 | ICU (CR8-0/1) | rzv_icu.c | rzv_icu.h | source-audited | `rzv2h_evk/intc_irq` + `intc_tint` CR8 EPs | (framework) | (pending) | Interrupt control unit; priority routing |
| 13 | ICU (CM33) | rzv_icu_cm33.c | rzv_icu.h | source-audited | `rzv2h_evk/intc_irq` + `intc_tint` CM33 EPs | nsh-cm33 | (pending) | CM33-specific ICU routing |
| 14 | Idle Task | rzv_idle.c | (none) | stub | (none) | nsh | (pending) | CPU idle loop; WFI instruction |
| 15 | IPC Dispatch | rzv_ipc.c | (none) | build-clean | (none) | (framework) | (pending) | IPC message dispatcher; no target traffic proof |
| 16 | IPC/IPCC | rzv_ipc_ipcc.c | (none) | build-clean | `nuttx/include/nuttx/ipcc.h` | ipcc, ipcc-multi | (pending) | NuttX IPCC character device; default/SIH images disable it |
| 17 | IPC Raw | rzv_ipc_raw.c | (none) | build-clean | (internal) | ipcc-multi | (pending) | MHU doorbell + DDR rings; peer and cache-coherency proof pending |
| 18 | IRQ (CR8) | rzv_irq.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` evidence | Interrupt vector setup; CR8-0/1 GIC. The `nsh-rtt` pass validates the SCI4 TX/RX interrupt path only. |
| 19 | IRQ (CM33) | rzv_irq_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33 | (pending) | CM33 Cortex-M33 NVIC setup; target and final link proof remain G11 work. |
| 20 | Low-Level UART | rzv_lowputc.c | (none) | source-audited | `rzv2h_evk/sci_b_uart/*_<core>_ep`: `r_sci_b_uart` + generated pins | (bootloader) | (pending) | SCI-B evidence only, not SCIFA. Early putc has no buffering. Current policy: standalone CR8-0 `nsh-rtt` uses SCI4 shell + RTT diagnostics; integrated PX4 CR8-0 uses RTT0 and bypasses SCI low-setup. |
| 21 | Memory Management | rzv_memmng.c | (none) | build-clean | (internal) | (framework) | (pending) | Heap and page-alignment setup; explicit target heap evidence remains pending. |
| 22 | MHU Core | rzv_mhu_core.c | rzv_mhu.h | build-clean | (internal) | (framework) | (pending) | Register read/write and DSB ordering; target channel proof pending |
| 23 | MPU Regions | rzv_mpu_regions.c | (none) | source-audited | (internal) | (framework) | (pending) | ARM MPU setup for memory protection; exact-image region snapshot remains pending. |
| 24 | OpenAMP | rzv_openamp.c | (none) | build-clean | `px4-freertos-posix-renesas-fsp/rzv/linaro/open-amp/` (integrated; no EVK EP) | ipcc, ipcc-multi | (pending) | CA55 ↔ CR8 sample path only; disabled in default/SIH |
| 25 | POEG | rzv_poeg.c | rzv_poeg.h | source-audited | `rzv2h_evk/poeg/*_<core>_ep`: `r_poeg` + `r_gpt` | (framework) | (pending) | PWM output enable group; target fault and safe-state proof pending. |
| 26 | RPMsg Layer | rzv_rpmsg.c | (none) | build-clean | (OpenAMP dep) | ipcc | (pending) | OpenAMP endpoint wrapper with bounded RX packet queue; no application CRC framing |
| 27 | Remote Proc | rzv_rproc.c | (none) | build-clean | `nuttx/include/remoteproc.h` | ipcc | (pending) | CA55/CR8 resource and kickoff path; target boot/recovery proof pending |
| 28 | SCI/I2C Master | rzv_sci_i2c.c | rzv_sci.h | build-clean | `px4-freertos-posix-renesas-fsp/rzv/fsp/src/r_sci_b_i2c/` (integrated; no EVK mode EP) | hil-full (SCI7) | [SCI7 re-audit](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/audit-260728-rzv2h-sci7-i2c-reaudit.md) | `CONFIG_RZV_SCI7_I2C` uses FSP-compatible SCISPICLK timing, fixed GIC TXI/TEI lines, and P76/P77 FSP-parity pins; board registration retains logical bus 7. Both builds pass. BMP280 transactions, analyzer capture, NACK/timeout, and recovery remain target gates. |
| 29 | SCI/I2C Clock | rzv_sci_i2c_clock.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [goal-plan reconciliation](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/phase-03-rzv2h-blocked-driver-closure-plan.md) | Runtime P5CLK calculation; 100 MHz/400 kHz reproduces FSP CKS0, BRR3, MDDR131, 399780 Hz, and 30-cycle SDA delay. Frequency measurement and on-target timing capture remain pending. |
| 30 | SCI/I2C ISR | rzv_sci_i2c_isr.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | (pending) | Interrupt handlers build with the SCI7 path; target event/error proof remains pending. |
| 31 | SCI/SPI Master | rzv_sci_spi.c | rzv_sci_spi.h | build-clean | integrated SCI-B/CMSIS register evidence; no SCI-B SPI EVK EP | sci-spi-loopback | [SCI/SPI source contract](../../test/rzv2h_sci_spi_contract_test.py) | SCI0 only on RDK; P6_0 SCK. `sci_b_uart` proves UART mode only. Fresh build and source contract pass; run the documented loopback plus removed-jumper error check on target. |
| 32 | SCI/SPI Clock | rzv_sci_spi_clock.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | BRR/CKS/MDDR calculation build-validated; frequency measurement pending |
| 33 | SCI/SPI ISR | rzv_sci_spi_isr.c | rzv_sci.h | build-clean | (FSP helper) | (shared) | [2026-07-19 remediation](../../plans/reports/review-260719-rzv2h-sci-spi-remediation.md) | FRSR-based FIFO drain build-validated; on-target transfer/error paths pending |
| 34 | SCIF UART | rzv_scif.c | rzv_scifa.h | blocked | core-matched R9A09G057H `scifa_iodefine.h`/BSP only; no SCIFA EP | nsh-scif (build) | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md) | Do not map `sci_b_uart` to SCIFA. Register/clock/reset/event evidence exists, but no generated SCIFA pins or FSP lifecycle. Clock, pinmux, INTID-width, baud, FIFO-error, and ISR-work blockers remain. |
| 35 | SDHI | rzv_sdhi.c | rzv_sdhi.h | build-clean | (none — no FSP `r_sdhi.c` in refs/) | sdhi | [2026-07-20 audit](../../plans/reports/audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md) | PIO 1/4-bit, IRQ-driven (combined ISR, INTID 767); compiles + wired to `/dev/mmcsd0`. Pending on-target register/command/PIO evidence. No FSP parity reference; sample/post-G9 only and does not gate the first drone-equivalent PX4 run. |
| 36 | Serial Framework | rzv_serial.c | (none) | bounded on-target | `rzv2h_evk/sci_b_uart/{cm33,cr8_0,cr8_1}` EPs | (framework) | `nsh-rtt` evidence | UART dispatcher over SCI-B; not SCIFA. FIFO RX is validated on SCI4 under `nsh-rtt`; payload channels and error injection remain unproved. `TIOCGICOUNT` and the non-opening snapshot path back PX4 `serial_status`. |
| 37 | SPI (RSPI) | rzv_spi.c | rzv_spi.h | bounded on-target | `rzv2h_gb_ether/drivers/rspi.c` (secondary); EVK `spi_b` is different IP | spi-loopback, hil-spi-loopback | J-Link/GDB + RTT, 2026-08-09 | Native polled RSPI master with board GPIO CS. `hil-spi-loopback` passed 1/4 MHz byte, 64-byte burst, and mode-3 cases. SPI-B must not be used as same-IP parity evidence. |
| 38 | Startup (CR8) | rzv_start.c | (none) | bounded on-target | (internal) | (bootloader) | `nsh-rtt` + SIH transcripts | CR8-0 startup reaches shells in bounded captures. Exact-image cold/debugger provenance and integrated default startup remain pending. |
| 39 | Startup (CM33) | rzv_start_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33 | (pending) | CM33 boot path; final link, co-processor wake, and runtime proof remain G11 work. |
| 40 | Timer ISR | rzv_timerisr.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` + SIH transcripts | System tick supports bounded shell/runtime captures; explicit clock/load/jitter evidence remains pending. |
| 41 | Watchdog | rzv_wdt.c | rzv_wdt.h | build-clean | `rzv2h_evk/wdt/*_<core>_ep`: `r_wdt` + INTC/GTM config | wdt | [2026-07-20 audit](../../plans/reports/audit-260720-1152-rzv2h-wdt-fsp-vs-nuttx-report.md) | Independent watchdog; refresh sequence. Reset-mode/WDT0 is source-audited, but no on-target evidence exists. Automatic sample only, no NSH command-registration requirement, and non-gating for G3-G9. |
| 42 | System reset (CR8) | rzv_systemreset.c | CMSIS/FSP WDT/CPG definitions | build-clean | core-matched `rzv2h_evk/wdt` EP reset routing | PX4 default/DShot/SIH/core-only | [reset source contract](../../test/rzv2h_gpt_pwm_contract_test.py) | `up_systemreset()` uses the CR8-0 WDT2 or CR8-1 WDT3 route, enables the required clock source, releases reset, selects the shortest supported timeout, routes underflow to system reset, and starts the watchdog with interrupts masked. All four board ELFs link the reset chain. Actual reset latency, post-reset boot state, repeated resets, and inactive motor-pin levels remain target gates. |

---

## Summary

- **Total drivers:** 42
- **Source-audited:** 11
- **Build-clean:** 17
- **Bounded on-target:** 9
- **Blocked:** 4 (ADC, Ether, Ether PHY, SCIF UART)
- **Stub:** 1
- **Production:** 0 (pending stress test)

Plan-critical reconciliation:

- Standalone CR8-0 defconfigs are normalized to SCI4 or RTT-only diagnostics.
- `nsh-cr8_1` and `nsh-cm33` select SCI5 and SCI9. CM33 linking and both target
  proofs remain final-milestone work.
- Board Make/CMake source selection is reconciled for the audited configs.
- `hil-spi-loopback` explicitly selects late board initialization; its clean
  image links the SPI registration chain before direct `hwtest_main`. The
  non-inverted internal loopback suite passes all four on-target cases.
- `hil-full` is SCI7 build-clean and now passes both nested NuttX and PX4
  builds, but it still cannot be hardware-ready until the BMP280 transaction
  and recovery procedure passes on target.
- CR8-1/CM33/OpenAMP work is non-gating until the CR8-0 PX4 drone path passes.

---

## Per-PR Update Discipline

When submitting a driver PR:
1. Update the driver row: status, sample config (if applicable).
2. Verify the row count remains 42.
3. Link to validation report (once available).
4. Update notes field if behavior changed.

---

## Related Docs

- [Validation Checklist](validation-checklist.md) — per-driver bring-up steps.
- [Reference Source Map](reference-source-map.md) — canonical EVK/core selection and gaps.
- [IPC Architecture](ipc-architecture.md) — MHU/IPCC integration.
- [Deployment Guide](../deployment-guide.md) — build and test harness.
- [DMAC Re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) — historical findings and remediation order.
- [DShot Runtime Fix Review](../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md) — current DMAC routing review and remaining hardware-only validation gaps.
- [GTM + PX4 HRT Re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) — GTM lower-half + HRT split-brain findings and remediation order.
