# NuttX Driver Port Status Matrix

**Date:** 2026-10-24
**Scope:** Renesas RZ/V2H (R9A09G057H) NuttX drivers under `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`

---

## Status Legend

- **stub**: Driver file exists; no implementation beyond config hook(s).
- **source-audited**: Source contracts, pin mappings, or board glue line up; no build or target transcript asserted.
- **build-clean**: Compiles without errors; architecture-level glue in place; validation pending.
- **bounded on-target**: A named evidence record contains a board transcript or an explicitly attributed hardware-retest confirmation. State the demonstrated scope and missing capture/provenance; this does not promote the subsystem to full target-ready status.
- **blocked**: Audit found correctness or integration defects that must be resolved before hardware validation.
- **production**: Source/build plus stress tested (≥10k cycles or 1h uptime); used in flight-qualified code.

For current planning, target readiness uses the stricter evidence tiers in the
[RDK-RZV2H PX4 NuttX Port Goal Plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md):
configured, build-clean, hardware-ready, bounded on-target, PX4-integrated,
and stress-validated. A row without a linked target evidence record remains
**needs on-target validation**. A user-confirmed retest without a passing
transcript leaves capture and exact-image provenance gates open.

Current board evidence is narrow but important: CR8-0 `nsh-rtt` reaches a
working serial shell (then on SCI4; the console moved to SCI5 and passed a standalone `nsh` check on 2026-11-08, see row 20) with RX/TX interrupt delivery and RTT diagnostics. The SIH
transcript adds interactive shell use, one GTM7-backed HRT callback test,
work-queue execution, and simulated PX4 topics. It does not validate every
driver or the integrated PX4 image.
Because SIH excludes physical payload/sensor buses and GPT/PWM, that evidence
does not promote any physical lower-half. Capture transport, cold-cycle
provenance, pin-safety measurement, and soak testing remain open.
The historical 2026-08-02 default, DShot, SIH, and core-only builds all include the
NuttX reset API. Their ELFs link `board_on_reset`, `board_reset`, and
`up_systemreset`; runtime reset and motor-pin safety are not yet target-proven.

The 2026-08-09 three-core raw-IPC preparation adds clean
`ipcc-raw-cr8_0`, `ipcc-raw-cr8_1`, and `ipcc-raw-cm33` builds with distinct
RTT consoles, numeric raw devices, ABI-v2 epoch/sequence recovery, and a
fail-closed ELF load checker. The tracked host evidence now lives in
[RZ/V2H Three-Core IPC Artifact Evidence](./evidence/rzv2h-three-core-ipc-artifacts.md).
The legacy `ipcc` profile still builds. CR8-0/CR8-1 load spans are
host-authorized only when the canonical bundled manifest and exact ELF SHA-256
are supplied.
The Renesas CM33 linker/post-build reference now source-ratifies secure SRAM
`0x08002800`, secure DDR alias `0x83820000`, and MHU NS `0x50480000`; the
rebuilt CM33 raw ELF passes the address checker. This is build evidence only:
at that date no CR8-1/CM33 boot or IPC traffic claim existed.
Since then the CR8-0 ↔ CR8-1 raw link (`/dev/ipcc1`) passes `ipctest`
recover + ping/echo 100/100 on target
([HIL guide](./validation/rzv2h-ipc-hil-test-guide.md)), and the CR8-1 PX4IO image
autostarts and streams heartbeat/fault frames over it
([IPC architecture](ipc-architecture.md)); CM33 boot/traffic is still unproven.
The focused ADC, Ether, Ether PHY, SCIF, RIIC, POEG, and serial fixes below
separate source/build closure from the still-open hardware or HIL gates.

The [expanded remediation record](../../plans/261013-0624-rzv2h-expanded-remediation/reports/remediation.md)
tracks core-specific register/header repairs, acquisition cleanup, buffered
RPMsg TX retries and debug-process ownership. Optional CM33 generic timers,
GPT/PWM/POEG, RIIC, SCI-I2C, SCIF, ADC, CAN, WDT and GPIO IRQ providers are
excluded until their core routing is implemented. CM33 HRT retains its
separate GTM5/NVIC provider. Existing bounded rows remain historical target
evidence; the repair overlay has no new board qualification.

The [2026-10-14 IRQ routing repair](../../plans/261014-1117-rzv2h-irq-event-routing/plan.md)
separates ELC, CPU IRQSEL and DMAC source numbers. SCI UART on both cores and
SCI-SPI use fixed inputs; RIIC uses selectable data plus fixed completion/error
inputs; SCIF0 uses selectors 113/114, and Ethernet uses 422/437. Pulse sensitivity
is configured before enable, and reused selectable slots return to level mode.
Watchdog interrupt mode uses fixed hardware WDT2/3 inputs; WDT0/1 interrupt-mode
registration is rejected on CR8. Host route, rollback and capture checks pass.
These repairs provide no new target qualification or ADC conversion result;
the named evidence and hardware gates in the matrix remain applicable.

The latest [integrated CR8-0 PX4 hardware campaign](evidence/px4-hardware-tests-cr8-0-261021.md)
adds focused consumer observations without changing lower-half scope: the PX4
SPI/I2C argument-parser entry passed but MPU9250 and accel/gyro topics were absent; SCI7 I2C
had no BMP280 instance or barometer topic; serial TX progressed while RX stayed
zero on the inspected ports; and DShot600 zero-throttle transfers completed on
all four channels through a restart. The same record contains detached HRT
timing and its RTT-attached failure. It does not qualify sensors, electrical
waveforms, persistent storage, cold-cycle/soak behavior, other profiles, or IO
cores.

The current PX4 software receipt records the canonical `dualcr8` CR8-0 sensor
profile and the compiled CR8-1 `pwm` supervisor candidate:
[dual-CR8 software validation](evidence/dualcr8-software-validation-261021.md).
Those checks are host/build evidence only and add no lower-half hardware tier;
the receipt preserves the existing named NuttX board evidence and its physical
qualification limits.

The [all-sample machine snapshot](../../plans/261022-1849-rzv2h-jlink-retry/all-sample-results.json)
and [remaining-sample actions](../../plans/261022-1849-rzv2h-jlink-retry/remaining-samples.md)
own shipped-configuration coverage and unresolved gates. The [retry report](../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md)
records bounded warm-load evidence for the repaired TMPFS and raw RTT pair; it
does not promote unrelated drivers or establish cold-state or physical
qualification.

The default-off `CONFIG_RZV2H_SPI0_SINGLE_IMU` board selector registers exactly
one polled SPI0 device on P93 and excludes P94/P95 sensor or button ownership.
The three-CS extension and native GY912 paths remain separate. The `dualcr8` and `demo`
PX4 profiles use it. This selector has source/host/build evidence, not a new physical SPI qualification result.

The [driver catalogue](../../platforms/nuttx/Debug/rzv2h-driver-coverage.json)
tracks RIIC0–8, native SPI0–2, SCI mode dispatch0–9 and logical GPT0–15
(physical GPT0–7/10–17). Indexed state uses actual lower-half coordinates;
unknown suites and absent instances fail admission. The
[shipped inventory](../../platforms/nuttx/Debug/rzv2h-all-sample-configs.json)
and [host regression catalog](../../Tools/rzv2h-regression-catalog.json) own
profile and check lists. [SCI mode authority](reference-source-map.md#sci-b-mode-authority)
comes from the pinned hardware manual where mode-specific FSP is absent.
Expanded RDK pin routes, external transfers and PWM waveforms remain separate
qualification work. Current bounded results are in the committed campaign
record below; software coverage alone does not establish a new target tier.

The [two-GBETH regression](../../test/rzv2h-ether-two-port-runtime-test.py)
restores independent GBETH0/1 board registration, failure rollback and link
clock/MAC updates. The current catalogue has 73 fixed profiles plus 55 original
configurations; the two Ethernet profiles inspect each MAC separately.
CR8 bases are `0x15c30000/0x15c40000`; explicit CM33 non-secure aliases are
`0x55c30000/0x55c40000`, and secure aliases are `0x45c30000/0x45c40000`.
CM33 runtime is unqualified. The driver supports MII/RGMII selection and
10/100/1000 link modes; the SoC's TSN/PTP hardware capabilities do not establish
NuttX implementations of those features. This repair adds software evidence
only. See the [register-coordinate explanation](reference-source-map.md#ethernet-and-phy-gap)
when comparing CSDIV offsets with the supplied CMSIS header.

The [indexed-provider regression](../../test/rzv2h-indexed-sdhi-wdt-runtime-test.py)
adds SDHI0–2 and WDT0–3 fixed identity profiles. SDHI's current address/GIC
path is CR8-only; Kconfig excludes CM33. Indexed snapshots retain the legacy
slot0/watchdog0 wrappers. Watchdog checks require pre-existing counting
inhibition and never start/feed a counter; SDHI checks omit media binding.
RIIC exposes named port IDs 0–8. CSDIV offsets follow matching-core I/O headers
at `0x4f0/0x4f4`; the manual uses a different block origin but the same absolute
register addresses. These are software
changes and do not promote a peripheral's target evidence tier.

The committed [sensor-free RTT validation record](evidence/sensor-free-rtt-validation-261024.md)
and [machine matrix](evidence/sensor-free-rtt-matrix-261024.json) account for
128 entries: 92 PASS, 2 NOT-PASS (GBETH1 RX-clock admission and GBETH0 DMA
loopback), 6 BLOCKED (five watchdog profiles and CM33 RTT), and 28
OUT-OF-SCOPE. The admitted scope is register, ISR-delivery and internal-function
checking only: no sensors, external peripheral traffic, PWM waveforms or
production qualification. Native checks do not promote PX4 physical or flight
qualification. Both GBETH units remain supported, and matching-core I/O
headers take precedence where present.

The campaign passes the SCIF internal 128-byte loopback and close/reopen cases
with RXI=248 and TXI=235 after the first-frame drain fix. SDHI0/1/2 register
identity and idle cancellation also pass after the reserved-bit mask repair.
The five watchdog profiles remain blocked because counting-inhibition bits were
clear; no watchdog start, feed or inhibition write was made. GBETH1 remains
not-pass because RX clocks cannot be admitted, while GBETH0 remains not-pass
because internal MAC loopback did not complete RX ownership. These results do
not qualify external links, sensor transfers, waveforms or production use.

### SCI-I2C timing policy

Requests are rate ceilings. The driver selects the fastest admitted tuple at
or below the request and the safe hardware ceiling; its two-percent accuracy
window applies around that limited target. At nominal P5CLK=100MHz, a 100kHz
request produces 97,656Hz and a 400kHz request produces 260,416Hz. The latter
throughput reduction preserves the manual's minimum SCL widths and strict
SDA-delay bound; average modulation frequency alone is insufficient. Actual
clock accuracy, edge times, routing and connected transfers still need target
measurement. This policy does not claim FSP timing parity.

### Reference extension boundary

The opt-in `drone` profile has host/build evidence and no extension target
qualification. Keep its P94 chip-select role separate from the legacy
button/DRDY images. Wiring belongs in [sensor profiles](pinmap.md#sensor-wiring-profiles);
software checkpoint details belong in
[execution progress](../../plans/261011-2017-rzv2h-drone-reference-port/reports/goal-progress.md).

Reference cells follow the core-selection and evidence rules in the
[RZ/V2H Reference Source Map](reference-source-map.md). EVK examples are
recorded source/configuration evidence, not RDK runtime proof. Compact paths
in the table are relative to `refs/` unless they begin with another repository
root such as `nuttx/`.

Integrated-reference `rzv/fsp/src/` paths below are expected e2studio-populated
inputs and are absent from the supplied snapshot. For present source review,
use its selected XML and recovered PX4 board backends; record this availability
limit rather than claiming those FSP files were inspected.

---

## Driver Inventory

| # | Driver | Source File | HW Header | Status | FSP Reference | Sample Config | Validation Report | Notes |
|---|--------|-------------|-----------|--------|---------------|----------------|-------------------|-------|
| 1 | ADC | rzv_adc.c | rzv_adc.h | bounded on-target | `rzv2h_evk/adc_e/*_<core>_ep`: `r_adc_e` + generated config | adc / adc-rtt | [ADC completion repair](../../plans/reports/debug-261014-1122-rzv2h-adc-completion.md) | IRQ selector 575 plus edge sensitivity before enable. Named RDK CR8-0 uninstrumented transcript completes 105 software scan groups / 420 channel records across two warm loads, with error-free read/close and released IRQ/readers. Analog accuracy, routing/reference, cold boot and PX4 integration remain open. |
| 2 | CAN-FD | rzv_canfd.c | rzv_canfd.h | bounded on-target | `rzv2h_evk/can_fd/*_<core>_ep`: `r_canfd` + generated config | canfd, canfd-rtt, canfd-dual, canfd-ext | [disconnected target run](evidence/canfd-disconnected-target-validation-261022.md); J-Link/GDB + RTT, 2026-08-09; [connected-test receipt](evidence/canfd-connected-software-validation-261022.md); [six-channel receipt](evidence/canfd-six-channel-software-validation-261022.md); [audit-repair receipt](evidence/canfd-audit-fixes-software-validation-261022.md) | 2026-10-22 warm CR8-0 runs verify 28 Classic frames across HW0/HW3 internal loopback (HW3 uses an archived device-path variant), normal/loopback/reset registers, priority `0xc0`, standby output latches and repeated HW0 missing-ACK cancellation/close/reopen. HW0 error IRQs are observed; synchronous loopback does not prove successful normal TX/RX IRQ delivery. FDCFG is zero on both channels; TDC settings parity remains open. The six-channel repair has host coverage, five clean software builds, unique FIFO/node mappings, PA2/PA3 standby isolation, and bounded TX cancel/close/reopen. The subsequent semantic audit repair preserves RX DLC/payload, applies configured IRQ priorities before enable, and quarantines failed internal-loopback recovery while retiring queued failures; the dedicated RTT command remains scoped to onboard HW0/HW3. HW1/P82/P83 and HW2/P84/P85, HW4/P42/P43, and HW5/P46/P47 remain optional expansion selections with externally managed transceivers. External connected FD/BRS traffic, physical standby/termination, successful normal-mode TX/RX IRQs, and physical qualification for expansion channels remain target gates. |
| 3 | Clock/CPG | rzv_clock.c | rzv_cpg.h | build-clean | Core-matched BSP/CPG and hardware manual | all native profiles | [lifecycle regression catalog](../../Tools/rzv2h-regression-catalog.json) | Bounded RIIC0–8 lifecycle, split SPI2 reset, transactional SCI controls and shared GPT unit clocks pass production-C host checks and integration builds. PLL/clock frequency, inherited cold state and physical timing remain target gates. |
| 4 | DMAC | rzv_dmac.c | rzv_dmac.h | bounded on-target | `rzv2h_evk/spi_b/*_<core>_ep`: `r_dmac_b` consumer example | dmac-memcpy | J-Link/GDB + RTT, 2026-08-09 | Historical 2026-08-09 CR8-0 software-triggered block-mode copy passed a 1024-byte memory comparison (`status=0x00000040`); this does not prove retained rearm or peripheral pacing. The 2026-10-02 fixes prepare cached memory destinations on every software start, guard enabled/bus-active start and buffer replacement, and reassert DEM on repeated starts. [Executed host driver tests](../../test/rzv2h-dmac-runtime-test.py): six failures before fixes, 11/11 after; [verification](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/worker-261002-dmac-runtime-fix.md). At that checkpoint, opt-in DShot compare-event pacing was unvalidated on target; serial DMA remains deferred. 2026-10-11: peripheral-to-memory hardware triggers (`ack_mode`, `source_request`) added for SPI0 DMA; host tests 12/12, build-clean only (see SPI row). No standalone EVK DMAC project. 2026-10-14: a fresh 1024-byte software copy passes, and the reduced-log DMA48/49 + hardware-SSL SPI0 sensor fixture completes 1/20/repeated-20 samples. That consumer evidence does not qualify DShot or the uncalled board allocator; see [2026-10-14 sample results](../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md). The [2026-10-20/21 CR8-0 repair run](evidence/dshot-dmac-cr8-0-validation-261020.md) adds independent CHEXT protection attributes and corrected ICU bus-status offsets, and verifies 26/26 one-KiB comparisons across both groups of all five units, inactive warm-state reset, stale software-route clearing, verified hardware-route rearm and bounded DMAC-only logs; four-channel DShot600 motor-stop completion/restart passes on DMAC3. The initial diagnostic SYS reads caused an abort and were removed. Peripheral access beyond these named consumers remains unqualified. |
| 5 | Ether | rzv_ether.c | rzv_ether.h | blocked | `rzv2h_gb_ether/plat/ether/r_ether.c` (legacy CA55; no EVK EP) | ether | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md); [sensor-free RTT validation](evidence/sensor-free-rtt-validation-261024.md) | Legacy same-IP evidence only. Descriptor-stride, cache/order, lock, and PHY-fallback defects are fixed in source. GBETH clock/reset IDs now use separate physical domains and bank-aware clock spans, with host-tested board/ifup unwind. RGMII pin/parent-clock ownership, target IRQ delivery and link-state remain open. The [RTT board samples](validation/rzv2h-rtt-board-samples.md) provide separately gated registration and MAC-loopback profiles; the campaign passes GBETH0 registration, while GBETH1 fails RX-clock admission and GBETH0 MAC loopback fails RX completion. Both units remain supported; matching-core I/O headers take precedence where present, and external link/traffic is unqualified. |
| 6 | Ether PHY | rzv_ether_phy.c | (via rzv_ether.h) | blocked | `rzv2h_gb_ether/plat/ether/r_phy.c` (legacy CA55; no EVK EP) | ether | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md) | Legacy PHY/skew evidence only. PHY resolution and fallback are fixed in source. Exact fitted PHY, straps, RGMII timing ownership, per-core integration, and target MDIO/traffic remain open. |
| 7 | GPIO | rzv_gpio.c | rzv_gpio.h | bounded on-target | core-matched EVK `r_ioport` + generated `pin_data.c`; integrated RDK pin ownership | nsh-leds, gy912 | [2026-10-01 P94 confirmation](evidence/gpio-button-interrupt-validation.md), [GY-912 checkpoint](validation/gy912-icm20948-validation.md) | User confirmed external interrupt delivery after retesting CR8-0 `nsh-leds`. P94 uses GPIO/TINT source GPIOINT68 with ISEL enabled and falling-edge press handling; the callback is configured to toggle LED0/PB4. PM input-mode and IRQ lifecycle fixes are in source. The 2026-10-11 GY-912 run adds user-reported sensor INT activity (`IRQ=3863`) after restoring CS to P93; no fresh edge trace was supplied. Passing transcript, exact image provenance, measured LED/edge behavior, other channels, and stress remain open. 2026-10-14: complete reduced-log ICM20948 transcripts record positive P94 callbacks in both SPI profiles. Counts are cumulative and do not qualify distinct edge rate, latency or physical waveforms; see [2026-10-14 sample results](../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md). |
| 8 | GPT (32-bit) | rzv_gpt.c | rzv_gpt.h | bounded on-target | `rzv2h_evk/gpt` + `gpt_input_capture` core-matched EPs: `r_gpt` | pwm | [GPT/PWM source contract](../../test/rzv2h_gpt_pwm_contract_test.py), [CR8-0 register transcript](evidence/rzv2h-pwm-register-transcript-261012.txt), [oneshot startup and shell tests](evidence/rzv2h-pwm-oneshot-transcript-261012.txt) | 2026-10-12: four PWM devices, continuous frequency/duty register checks, stop/restart, ten-pulse software completion and finite endpoint rejection passed (16 cases). Software group gates, edge compare IRQs and IRQSEL routing corrected. Stock oneshot startup and 36 additional shell/register cases passed with these fixes. Electrical waveforms, physical pulse count, live transitions and cold-cycle proof pending. |
| 9 | GTM (32-bit) | rzv_gtm.c | rzv_gtm.h | bounded on-target | `rzv2h_evk/gtm/*_<core>_ep`: `r_gtm` + generated config | gtm | J-Link/GDB + RTT, 2026-08-09 | RTT NSH runs on `/dev/timer0` and `/dev/timer2` each completed 20 status samples, five signal deliveries, stop, and clean finish. Long-run timing accuracy, jitter, and fault injection remain target gates. 2026-10-14: interval countdown status, handler flags, stopped `settimeout` behavior and ticks-minus-one periods are repaired. The named `/dev/timer0` run has 20 observations, two signals, stop and clean finish; see [2026-10-14 sample results](../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md). |
| 10 | HRT | rzv_hrt.c (arch shim) + platforms/.../renesas/rzv/hrt/hrt.c (queue mgr) | rzv_hrt.h | bounded on-target | (GTM7 free-run, arch shim) | PX4 board config (`CONFIG_RZV_HRT=y`) | [2026-07-30 SIH transcript](./evidence/px4-nuttx-rzv2h-sih-transcript.txt), [2026-10-21 CR8-0 evidence](./evidence/px4-hardware-tests-cr8-0-261021.md) | PX4 HRT delegates counter/arm to the arch GTM7 shim at runtime P1CLK. SIH `system_time hrt-test` passed with 22,044 us sleep and 4 us callback latency. The latest detached CR8-0 check measured 11,041 us sleep and 4 us callback latency; RTT-attached timing reached 133,603 us, so probe interference remains a limit. Exact clock measurement, long-run monotonicity, jitter, drift, and load bounds remain required. |
| 11 | I2C (RIIC) | rzv_i2c.c | rzv_i2c.h | bounded on-target | `rzv2h_evk/riic_master/*_<core>_ep`: `r_riic_master` | (nsh default) | [sensor-free identity checks](evidence/sensor-free-rtt-validation-261024.md) | 2026-10-24: RIIC0–8 controller identity/lifecycle checks pass on CR8-0; this demonstrates register/initialization scope only, with external transfers and timing unqualified. Native I2C master; board API and implementation now match. Nine distinct RIIC0–8 lower halves and opt-in controlled RTT profiles now have source/host/build coverage, including RIIC8’s separate clock/reset bank and failed-acquisition cleanup. Normal unassigned routes remain denied. The [2026-10-13 remediation](../../plans/261013-0002-rzv2h-audit-remediation/plan.md) fixes ACKWP/ACKBT ordering for short/continued reads and repeated START, attaches the fixed channel STOP interrupt, and keeps NACK completion with STOP while resetting on timeout/arbitration loss. Host receive, error, and IRQ rollback regressions plus target compilation pass; RX/STOP analyzer and HIL proof remain open. Use SCI7 simple-I2C (rows 28–30) for sensors. |
| 12 | ICU (CR8-0/1) | rzv_icu.c | rzv_icu.h + rzv_intc.h | bounded on-target | `rzv2h_evk/intc_irq` + `intc_tint` CR8 EPs | nsh-leds | [2026-10-01 P94 confirmation](evidence/gpio-button-interrupt-validation.md), [GY-912 checkpoint](validation/gy912-icm20948-validation.md) | CR8-0 P94 GPIO/TINT delivery user-confirmed after correcting all 43 INTR8SEL offsets to CMSIS range `0x0140..0x01e8` (`INTR8SEL0=0x10400140`). The 2026-10-11 GY-912 run adds user-reported sensor INT activity (`IRQ=3863`) on the same route; no fresh edge trace was supplied. Evidence covers this route only; CR8-1, native IRQ, other selectable events, full passing capture, and stress remain open. 2026-10-14: complete reduced-log SPI sensor runs add exact-image, positive P94 callback and reentry evidence on CR8-0. Other routes/cores and measured edge behavior remain open; see [2026-10-14 sample results](../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md). |
| 13 | ICU (CM33) | rzv_icu_cm33.c | rzv_icu.h | source-audited | `rzv2h_evk/intc_irq` + `intc_tint` CM33 EPs | nsh-cm33, ipcc-raw-cm33 | (pending) | CM33 selectable-event routing builds with the raw profile; fixed MHU interrupts bypass INTM33SEL. Target dispatch proof pending. |
| 14 | Idle Task | rzv_idle.c | (none) | stub | (none) | nsh | (pending) | CPU idle loop; WFI instruction |
| 15 | IPC Dispatch | rzv_ipc.c | (none) | build-clean | (none) | (framework) | (pending) | IPC message dispatcher; no target traffic proof |
| 16 | IPC/IPCC | rzv_ipc_ipcc.c | (none) | build-clean | `nuttx/include/nuttx/ipcc.h` | ipcc, ipcc-multi | (pending) | Buffered TX retains queued bytes on failed RPMsg sends and consumes them only after acceptance; bounded host retry/order checks pass. Buffered RX admits only complete RPMsg packets, drains bounded backlogs, preserves overflow retry, and serializes callback/refill producers. Legacy OpenAMP/IPCC remains separate from raw IPC; saturation, ordering, and wakeup HIL remain open. |
| 17 | IPC Raw | rzv_ipc_raw.c | (none) | bounded on-target | (internal) | ipcc-raw-cr8_0, ipcc-raw-cr8_1, ipcc-raw-cm33 | [IPC HIL guide](./validation/rzv2h-ipc-hil-test-guide.md), [Three-core IPC artifacts](./evidence/rzv2h-three-core-ipc-artifacts.md), [repaired warm RTT pair](../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md) | Scoped character device, numeric minors, checked ABI-v2 rings, exact ACK correlation, stale-response-safe ACK arming, quarantine, and two-sided recovery build on all three cores. The repaired CR8-0 ↔ CR8-1 `/dev/ipcc1` RTT pair passes two consecutive warm loads, each with recovery and 100/100 byte-exact 64-byte echoes, zero timeouts, responsive consoles and no faults; CR8-1 independently reports completion. CR8-0 reports zero invalid headers; CR8-1 increments `invalid_headers` once per warm recovery/traffic run. The increment site was not instrumented; no zero-counter claim applies to both cores. `poll()` samples ring state under `rxlock`, and a writer arms its ACK wait before publishing the entry, so an ACK from a peer that consumes the entry at once cannot be lost (both host-tested; the ACK fix removed runtime link drops in a 5-minute dual-CR8 PX4 run). Writes move exactly one 64-byte entry (`EMSGSIZE` otherwise) and are stop-and-wait: a write waits up to `CONFIG_RZV_IPC_TX_TIMEOUT_MS` for the peer's ACK, and a timeout quarantines the link until the initiator recovers it. A quarantined responder adopts a fresh initiator epoch through plain read/poll (host-tested; board-proven 2026-10-13 when the CR8-1 PX4IO relay joined epochs 12/13 and streamed 20 consecutive CRC-valid heartbeat/fault frames to CR8-0). `GET_STATS` takes `rxlock`, not the write lock held across the ACK wait, so a reader's epoch query never blocks behind a stalled writer (host-tested). The `ipcdemo` showcase pair (`ipcc-demo-cr8_0-serial` + `ipcc-demo-cr8_1`, 400 ms TX-ACK timeout, TRIM RTT up-buffer) passed a 5-minute two-way heartbeat soak, 300/300 one-way and concurrent 100/100 pings in both directions, and a CR8-1-only reload relink with no command ([evidence 2026-10-31](./evidence/rzv-ipc-showcase-demo-261031.md)); with the 100 ms default, J-Link stop-mode RTT halts on CR8-1 lost 4/300 pings. CM33 traffic, cold boot, long-run soak, and error injection remain open. |
| 18 | IRQ (CR8) | rzv_irq.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` evidence | Interrupt vector setup; CR8-0/1 GIC. The `nsh-rtt` pass validates SCI4 TX/RX; [P94 confirmation](evidence/gpio-button-interrupt-validation.md) adds bounded CR8-0 GPIO/TINT delivery. CR8-0 and CR8-1 share one GIC distributor: CR8-0 owns it, CR8-1 resets only its own SGI/PPI state and the SPIs routed to it, `up_enable_irq()` routes each SPI to the enabling core, and boot ends stale active interrupts left by a reset image; on 2026-10-13 this removed the IRQ 154 crash during dual-CR8 IPC loads. Other routes remain unvalidated. |
| 19 | IRQ (CM33) | rzv_irq_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33, ipcc-raw-cm33 | (pending) | Standard ARMv8-M vectors and base-16 NuttX external IRQ numbering link clean; target NVIC dispatch remains unproved. |
| 20 | Low-Level UART | rzv_lowputc.c | (none) | bounded on-target | `rzv2h_evk/sci_b_uart/*_<core>_ep`: `r_sci_b_uart` + generated pins | (bootloader) | [SCI5 `nsh` run 2026-11-08](evidence/sci5-nsh-console-cr8-0-261108.txt) | SCI-B evidence only, not SCIFA. Early putc has no buffering. In FIFO mode it waits for a free stage (FTSR.T < 16), because TDRE stays set there. 2026-11-08: standalone `nsh` on CR8-0 printed the boot progress `NUTTX` intact over SCI5 after FIFO mode was on. Current policy: standalone CR8-0 `nsh-rtt` uses the SCI5 serial shell + RTT diagnostics (SCI5 early-console branch added; needs on-target validation); integrated PX4 CR8-0 uses RTT0 and bypasses SCI low-setup. |
| 21 | Memory Management | rzv_memmng.c | (none) | build-clean | (internal) | (framework) | (pending) | Heap and page-alignment setup; explicit target heap evidence remains pending. |
| 22 | MHU Core | rzv_mhu_core.c | rzv_mhu.h | build-clean | core-matched FSP `bsp_mhu_b.h`/IRQ IDs | ipcc-raw-cr8_0, ipcc-raw-cr8_1, ipcc-raw-cm33 | (pending) | Source route is CR8 ch21↔CM33 ch11 and CR8 ch22↔CM33 ch17; CM33 fixed IRQs map to NuttX 310/317 and use NVIC without CR8 GIC retargeting. The full CM33 IO image builds. Register, interrupt, and traffic proof pending. |
| 23 | MPU Regions | rzv_mpu_regions.c | (none) | source-audited | (internal) | (framework) | (pending) | ARM MPU setup for memory protection; exact-image region snapshot remains pending. |
| 24 | OpenAMP | rzv_openamp.c | (none) | build-clean | `rzv2h_drone_px4-dev/rzv/linaro/open-amp/` (integrated; no EVK EP) | ipcc, ipcc-multi | (pending) | CA55 ↔ CR8 sample path only; disabled in default/SIH |
| 25 | POEG | rzv_poeg.c | rzv_poeg.h | source-audited | `rzv2h_evk/poeg/*_<core>_ep`: `r_poeg` + `r_gpt` | (framework) | (pending) | PWM output enable group; event-mask ABI and module-start sequencing are fixed in source. Fault and safe-state HIL remain open. |
| 26 | RPMsg Layer | rzv_rpmsg.c | (none) | build-clean | (OpenAMP dep) | ipcc | (pending) | OpenAMP endpoint wrapper with bounded RX packet queue; no application CRC framing |
| 27 | Remote Proc | rzv_rproc.c | (none) | build-clean | `nuttx/include/remoteproc.h` | ipcc | (pending) | CA55/CR8 resource and kickoff path; target boot/recovery proof pending |
| 28 | SCI/I2C Master | rzv_sci_i2c.c | rzv_sci.h | bounded on-target | Hardware manual Rev.1.40 §7.3; SCI-B CMSIS/BSP coordinates; mode FSP absent | hil-full, bmm150; fixed SCI0–9 instance profiles | [mode and timing regressions](../../test/rzv2h-sci-i2c-mode-runtime-test.py); [sensor-free identity checks](evidence/sensor-free-rtt-validation-261024.md) | 2026-11-08: SCI7 completed external transfers on CR8-0 ([BMP280 run](validation/bmp280-i2c-validation.md#board-run-2026-11-08-pass-after-txi-fix): write, NOSTOP + repeated-START read, master NACK, address-NACK recovery at 97,656 Hz). 2026-10-24: SCI-I2C0–9 identity/lifecycle checks pass on CR8-0; other channels' external transfers and physical timing stay unqualified. All ten channels use distinct state; SCI7 retains logical bus7 and its existing P76/P77 route. Required CCR3 CPOL/CPHA bits stay high. Stop, mode transition, retry and stale IRQ paths have production-C host coverage. The BMM150 sample still requests 400 kHz; selected actual rates follow the conservative timing policy below. Historical [PX4 observations](evidence/px4-hardware-tests-cr8-0-261021.md) found no BMP280 instance or barometer topic; physical timing remains unqualified. |
| 29 | SCI/I2C Clock | rzv_sci_i2c_clock.c | rzv_sci.h | build-clean | Hardware manual Tables7.3-8/9/19/20/21 and §7.3.7.3 | (shared) | [minimum-width oracle](../../test/rzv2h-sci-i2c-mode-runtime-test.py) | Clock tuples must satisfy unmodulated SCL minima and a representable SDA delay strictly above 300 ns. Modulation can lengthen an admitted base. Exact rational selection never exceeds the request; deadlines use the programmed rate. See timing policy below. |
| 30 | SCI/I2C ISR | rzv_sci_i2c_isr.c | rzv_sci.h | bounded on-target | Hardware manual §§7.3.7/17/18 | (shared) | [mode and recovery tests](../../test/rzv2h-sci-i2c-mode-runtime-test.py) | CPU/TXI mode remains non-FIFO with no ERI. TXI acknowledges only the GIC pending bit; writing CFCLR.TDREC while TE=1 re-raises TXI mid-frame and caused false NACKs (fixed 2026-11-08, SCI7 BMP280 pass). STI clears before another condition request; half a selected bit period separates STOP from restart/completion. Late TXI cannot duplicate STOP, and completed-STOP overrun reports EIO. Electrical timing proof remains pending. |
| 31 | SCI/SPI Master | rzv_sci_spi.c | rzv_sci_spi.h | bounded on-target | R01UH1032EJ0140 Rev.1.40 §7.3; SCI-B CMSIS/BSP coordinates | sci-spi-loopback; fixed SCI0–9 instance profiles | [mode regressions](../../test/rzv2h-sci-spi-mode-runtime-test.py); [sensor-free identity checks](evidence/sensor-free-rtt-validation-261024.md) | 2026-10-24: SCI-SPI0–9 controller identity/lifecycle checks pass on CR8-0; this demonstrates register/initialization scope only, with external transfers and timing unqualified. SCI0 retains its RDK P6_0 SCK route; all ten controllers have distinct dispatch/state. TE/TIE start together, mode transitions are bounded, and final completion waits for TEND. Unassigned normal routes remain denied. Source/host and build evidence do not qualify connected loopback, removed-jumper errors or physical timing. |
| 32 | SCI/SPI Clock | rzv_sci_spi_clock.c | rzv_sci.h | build-clean | Hardware manual Tables7.3-8/19 and §7.3.10 | (shared) | [clock and mode oracle](../../test/rzv2h_sci_spi_contract_test.py) | BGDM=1 integer calculation matches the programmed divisor. SPI modulation is prohibited and disabled; requests outside the two-percent integer-rate window retain the prior actual rate. Frequency measurement remains pending. |
| 33 | SCI/SPI ISR | rzv_sci_spi_isr.c | rzv_sci.h | build-clean | Hardware manual §§7.3.17/18 | (shared) | [production ISR tests](../../test/rzv2h-sci-spi-mode-runtime-test.py) | TX writes are bounded by the 32-stage FIFO occupancy. RXI/TEI require both exhausted counts and TEND, post once in either IRQ order, and preserve bounded error cleanup. Target transfer/error and final-edge timing captures remain pending. |
| 34 | SCIF UART | rzv_scif.c | rzv_scifa.h | bounded on-target | core-matched R9A09G057H `scifa_iodefine.h`/BSP only; no SCIFA EP | scif-internal-loopback-rtt, nsh-scif (build) | [2026-08-09 audit](../../plans/reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md); [sensor-free RTT validation](evidence/sensor-free-rtt-validation-261024.md) | Do not map `sci_b_uart` to SCIFA. Clock, INTID-width, baud and ISR work are source-audited. The sensor-free campaign passes both internal 128-byte loopback and close/reopen cases with RXI=248, TXI=235 and no retained case IRQs after repairing first-frame drain and idle-status handling. External pinmux, baud accuracy, FIFO-error injection and peer transfers remain unqualified. |
| 35 | SDHI | rzv_sdhi.c | rzv_sdhi.h | bounded on-target | (none — no FSP `r_sdhi.c` in refs/) | sdhi | [2026-07-20 audit](../../plans/reports/audit-260720-1000-rzv2h-sdhi-fsp-vs-nuttx-report.md); [sensor-free RTT validation](evidence/sensor-free-rtt-validation-261024.md) | PIO 1/4-bit, IRQ-driven (combined ISR on ICU selectable event `RZV_IRQSEL_SDHI_OXMN(slot)` = 392 + 2·slot); compiles + wired to `/dev/mmcsd0`. The campaign passes SDHI0/1/2 controller identities and idle cancellation after correcting reserved-bit mask readback. 2026-11-08 rework (hardware-manual based): separate bounded command/data waits, explicit `SD_CMD` response types, one block per BRE/BWE, SECCNT/SEC multi-block, SCR `SD_SIZE`=8, R2 realignment, `SDCD` presence, CBSY/SCLKDIVEN clock gate, soft reset that keeps bus setup, and cancel releasing both waiters; [command/data register-model tests](../../test/rzv2h-sdhi-command-data-runtime-test.py) pass and `sdhi0-board-rtt`/`sdhi-lower-only-rtt` build clean. Command/PIO/media evidence on target remains open. No FSP parity reference; sample/post-G9 only and does not gate the first drone-equivalent PX4 run. |
| 36 | Serial Framework | rzv_serial.c | (none) | bounded on-target | `rzv2h_evk/sci_b_uart/{cm33,cr8_0,cr8_1}` EPs | (framework) | `nsh-rtt` evidence, [2026-10-21 CR8-0 evidence](./evidence/px4-hardware-tests-cr8-0-261021.md) | UART dispatcher over SCI-B; not SCIFA. SCI setup/shutdown waits are now bounded. SCI remains interrupt driven even when another serial device selects global DMA options; unsupported dormant SCI DMA code is removed, and serial DMA remains deferred. FIFO RX is validated on SCI4 under `nsh-rtt`; the latest PX4 image showed TX progress but zero RX on the inspected ports, so payload channels and error injection remain unproved. `TIOCGICOUNT` and the non-opening snapshot path back PX4 `serial_status`. 2026-11-08: CR8 boot now runs `arm_earlyserialinit`, which drains TX, sets up the console and marks it `isconsole` only on success (LF→CRLF, console open/close semantics). On the standalone `nsh` SCI5 console: zero bare LF, 30/30 70-byte pastes echoed intact, 3× 18 KB `xd` bursts byte-exact against the ELF ([transcript](evidence/sci5-nsh-console-cr8-0-261108.txt)). 2026-11-08: `up_putc` sends CR before LF, so syslog is CRLF too; Ctrl-C interrupts a foreground builtin 3/3 with `TTY_SIGINT` in `nsh`/`nsh-scif`/`nsh-cm33` ([transcript](evidence/sci5-nsh-ctrl-c-crlf-cr8-0-261108.txt)). 2026-11-09: setup sets CCR3.FM and resets the FIFOs before RE, as FSP does; with FM set after RE, a channel starting from reset values never received. RX now passes after an SCI5 register reset and a simulated cold CPG state ([transcript](evidence/sci5-nsh-cold-start-rx-cr8-0-261109.txt)); a real power cycle is not captured. |
| 37 | SPI (RSPI) | rzv_spi.c | rzv_spi.h | bounded on-target | core-matched EVK `spi_b/r_spi_b.c` + BSP; legacy `drivers/rspi.c` secondary | spi-loopback, hil-spi-loopback, gy912 | J-Link/GDB + RTT, 2026-08-09; [GY-912 checkpoint](validation/gy912-icm20948-validation.md), [archived RTT excerpt](evidence/gy912-icm20948-rtt-261011.txt), [status report](../../plans/reports/pm-261011-1859-gy912-icm20948-on-target.md) | Native RSPI master with legacy board CS/DRDY profiles. `hil-spi-loopback` passed 1/4 MHz byte, 64-byte burst, and mode-3 cases. The 2026-10-11 user-reported GY-912 run adds CS selection activity and one raw ICM20948 sample on CR8-0 after restoring CS to P93; the excerpt is partial and has no direct analyzer trace. The 2026-10-24 direct FSP/CMSIS comparison confirms the same native SPI-B register bank and RSPI module lifecycle; SPI0–2 now have distinct descriptors and bounded initialization/rollback host checks. This corrects the earlier different-IP attribution; it adds no physical qualification. Opt-in `RZV_SPI0_DMA` and `RZV2H_SPI0_HARDWARE_SSL` were tried in `gy912`; the first hardware-SSL run read WHO_AM_I 0x00, and GPIO-CS + DMA then reported RX DMA errors. Host/build results remain software evidence only. The opt-in three-CS, polled ICM45686 drone profile has passing host/build checks and no native target evidence. 2026-10-14: fresh internal SPI0/SPI1 and four-case HIL tests pass. Separately named reduced-log polled GPIO-CS and DMA48/49 + hardware-SSL ICM20948 fixtures complete 1/20/repeated-20 with positive IRQs. Original verbose sensor images faulted, with cause unresolved; no timing, electrical or production qualification follows. The latest PX4 campaign adds no sensor publication; see [2026-10-14 sample results](../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md) and [CR8-0 hardware evidence](./evidence/px4-hardware-tests-cr8-0-261021.md). 2026-11-01: the standalone `icm45686-dma-ssl-rtt` sample (DMA48/49 + hardware SSLA0 on P93) completes 1/20/repeated-20/1000-sample ICM-45686 FIFO runs on CR8-0 with `result=0` and exact image hash; see [ICM-45686 validation](validation/icm45686-spi-validation.md). Waveform/SCK, cold-state and the PX4 driver path remain unqualified. 2026-11-08: the bit rate follows FSP (fastest rate at or below the request). The sample passes at 7.69 MHz (8 MHz request) and 20 MHz (24 MHz request, the PX4 `SPI_SPEED`), confirmed by SPBR/BRDV readback ([ICM-45686 validation](validation/icm45686-spi-validation.md#board-run-after-the-spi-bit-rate-fix-2026-11-08)); no scope measurement. |
| 38 | Startup (CR8) | rzv_start.c | (none) | bounded on-target | (internal) | (bootloader) | `nsh-rtt` + SIH transcripts | CR8-0 startup reaches shells in bounded captures. Exact-image cold/debugger provenance and integrated default startup remain pending. |
| 39 | Startup (CM33) | rzv_start_cm33.c | (none) | source-audited | (CM33 variant) | nsh-cm33, ipcc-raw-cm33 | [Three-core IPC artifacts](./evidence/rzv2h-three-core-ipc-artifacts.md) | Standard vectors and Thumb reset entry link at FSP-matched secure SRAM `0x08002800`; current NuttX exports `_vectors` there and uses verified vector words for MSP/Thumb launch semantics. Heap ends at `0x080f8000`, with a non-cacheable RTT window above it. SEGGER reset-entry, co-processor wake, and runtime proof remain target gates. |
| 40 | Timer ISR | rzv_timerisr.c | (none) | bounded on-target | (internal) | (framework) | `nsh-rtt` + SIH transcripts | CR8 private-timer tick supports bounded CR8-0 shell/runtime captures. The private timer counts at I6CLK / 4 (`CONFIG_RZV_CR8_PERIPHCLK_DIV`, 200 MHz; load `0x30d3f` for 1 kHz), not CPU / 2: on 2026-10-13 the old divider ran the tick at half rate on both CR8 cores, measured against the GTM HRT, and the corrected tick matched it. CM33 now selects `rzv_timerisr_cm33.c`: SysTick exception 15 at the matched I7CLK rate. The CM33 PX4 IO image builds; host pending-reload checks pass. CM33 tick rate, scheduler and cold-boot target proof remain open. |
| 41 | Watchdog | rzv_wdt.c | rzv_wdt.h | build-clean | `rzv2h_evk/wdt/*_<core>_ep`: `r_wdt` + INTC/GTM config | wdt | [2026-07-20 audit](../../plans/reports/audit-260720-1152-rzv2h-wdt-fsp-vs-nuttx-report.md) | Independent watchdog; refresh sequence. Reset-mode/WDT0 is source-audited, but no on-target evidence exists. Automatic sample only, no NSH command-registration requirement, and non-gating for G3-G9. |
| 42 | System reset (CR8) | rzv_systemreset.c | CMSIS/FSP WDT/CPG definitions | build-clean | core-matched `rzv2h_evk/wdt` EP reset routing | PX4 default/DShot/SIH/core-only | [reset source contract](../../test/rzv2h_gpt_pwm_contract_test.py) | `up_systemreset()` uses the CR8-0 WDT2 or CR8-1 WDT3 route, enables the required clock source, releases reset, selects the shortest supported timeout, routes underflow to system reset, and starts the watchdog with interrupts masked. All four board ELFs link the reset chain. Actual reset latency, post-reset boot state, repeated resets, and inactive motor-pin levels remain target gates. |
| 43 | xSPI QSPI flash MTD | rzv_xspi.c | rzv_xspi.h (+ `hardware/rzv_xspi.h`) | build-clean | `rz-fsp-4.2.0/rzv/rz/fsp/src/r_xspi_qspi/r_xspi_qspi.c` (Open, direct transfer, Write, StatusGet, Erase) | xspi-authority-guard-rtt (`RZV_XSPI`, selected by `RDK_RZV2H_XSPI_PARAMFS`) | [production-C host contract](../../test/rzv2h-xspi-paramfs-contract-test.py) | Arch MTD lower-half moved out of the board paramfs file. Follows FSP: TRNUM/TRREQ manual-command sequence, 1-byte opcode in CDT bits 24-31 with CMDSIZE=1 and TRTYPE for writes, CMCFG0-2/BMCTL0/BMCFG write-combining Open, 64-byte memory-window programs each preceded by write enable, COMSTT+WIP ready polling, flash-relative erase, D-cache clean/invalidate, mutex-serialised callbacks. Refuses a controller in XIP. Caller owns clock/reset/pins, the fitted flash part and opcodes. The default MPU region maps the window read-only, so programming faults until the platform supplies a writable mapping. Board `rzv2h_xspi_paramfs.c` keeps only partition/manifest policy, the weak authority hook, `/dev/xspi_params` and the LittleFS mount. No target register, erase, program or readback evidence. |

---

## Per-PR Update Discipline

### Source limitations awaiting implementation or qualification

These limitations remain open after comment cleanup; no driver evidence tier
changes as a result of formatting or documentation:

- Clock gate encodings require hardware-manual confirmation. The PLLCM33
  standby-register offset is unverified, so startup avoids the speculative
  write. Dynamic frequency changes return `-ENOSYS`.
- Ethernet requires verified RDK RGMII pins and independent GBETH module,
  TX/RX reference, and pad clock ownership. Both ports now acquire their own
  six module clocks/reset and update their own speed divider; earlier boot
  stages still supply PLL/reference-clock and pad routing. The board path
  does not configure placeholder pins.
- SCI early output assumes bootloader SCI3 configuration and 100 MHz P5CLK;
  board measurements must confirm both and the baud divisor. SCIF pin
  routing remains unqualified.
- Serial baud-error tolerance is a driver constant rather than a Kconfig
  option. DMA transmit interrupt suppression remains a no-op and requires
  explicit residual-TXI qualification.
- SCI/SPI timeout recovery masks interrupts, disables transfer, and flushes
  FIFOs; chip-select release belongs to the upper SPI layer. Concurrent
  first initialization requires serialization.
- CAN-FD runtime bitrate changes remain unsupported. The watchdog sample
  changes software LED state without a qualified LED GPIO route.
- A TCSETS on an open SCI port re-runs `rzv_setup()`, which rewrites CCR0
  without RIE. The upper half probably re-enables RX interrupts on the next
  read; this is unconfirmed on target.
- Open decision (2026-10-13): RTT up-buffer trim mode
  (`CONFIG_SEGGER_RTT_UP_MODE_TRIM`) is set only in the PX4 rdk-rzv2h
  defconfigs and the RTT-console IPC samples (`ipcc-raw-cr8_0`,
  `ipcc-raw-cr8_1`, `ipcc-raw-cm33`, `ipcc-demo-cr8_1`; 2026-10-31). The
  other NuttX-only RZ/V configs (`nsh-rtt` and others) and the RA8
  `fpb-ra8e1` / `evk-ra8p1` nsh defconfigs still block on a full buffer.

When submitting a driver PR:
1. Update the driver row: status, sample config (if applicable).
2. Preserve each row's evidence scope and unresolved gates; add or remove rows
   only when driver ownership changes.
3. Link to validation report (once available).
4. Update notes field if behavior changed.

---

## Related Docs

- [Validation Checklist](validation/validation-checklist.md) — per-driver bring-up steps.
- [Reference Source Map](reference-source-map.md) — canonical EVK/core selection and gaps.
- [IPC Architecture](ipc-architecture.md) — MHU/IPCC integration.
- [Deployment Guide](../deployment-guide.md) — build and test harness.
- [DMAC Re-audit](../../plans/260718-2121-rzv2h-dmac-driver-reaudit/reports/review-rzv2h-dmac-260718-reaudit.md) — historical findings and remediation order.
- [DShot/DMAC Runtime Remediation](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/plan.md) — October 2 source fixes, executed host regressions, and remaining physical timing gates.
- [DMAC Runtime Verification](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/worker-261002-dmac-runtime-fix.md) — real-driver cache, enabled-channel, and DEM regressions; preserves the August 9 bounded memory-copy evidence.
- [DShot Runtime Fix Review](../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md) — historical July 20 DMAC routing review; superseded runtime findings are covered by the October 2 remediation.
- [GTM + PX4 HRT Re-audit](../../plans/260718-2242-rzv2h-gtm-hrt-driver-reaudit/reports/review-rzv2h-gtm-hrt-260718-reaudit.md) — GTM lower-half + HRT split-brain findings and remediation order.

### Source failure-path contracts

The current source rejects WDT requests above its representable timeout
(5592 ms at 24 MHz OSCCLK) without replacing the previous configuration.
The watchdog sample prepares its feeder before starting the watchdog and
preserves setup errors across cleanup. Failed timer or signal cleanup retains
its ownership state for retry and prevents replacement of live resources.
SCI-SPI deadlines include calculated
wire time and use relative NuttX semaphore waits; negative waits abort the
active transfer. SCI-I2C prepares continuation metadata in task context so
its IRQ path does not scan arbitrarily long message chains.

Board pin failures stop the affected peripheral setup. UART setup retains
its pinmux retry state on failure and configures only the opened channel;
bring-up preserves the first reported
error and skips LED registration after failed pin setup. IPCC registration
failure releases its watcher exactly once and permits retry. ICU teardown
holds its local critical section through validation and slot release, and
the CR8 private timer compensates one pending reload while sampling time.
Clock status uses the packed CPG monitor indices and reset polarity.
These contracts have extracted-source host coverage. They do not promote
hardware status or establish physical timing, pins, cache or CA55 behavior.
