# RZ/V2H Documentation Index

Start here for the RDK-RZ/V2H PX4/NuttX port. Contributors and agents use the
same owners below; [AGENTS.md](../../AGENTS.md) adds workspace and hardware
operation rules. Select a board/profile before using a pin assignment or
validation result.

## Start here

| Need | Owner |
|---|---|
| Port scope, software boundaries and intended direction | [System architecture](../system-architecture.md) |
| Locate implementation and build inputs | [Codebase map](../codebase-summary.md) |
| Build, load and connect a console | [Deployment guide](../deployment-guide.md) |
| VS Code extension and workspace tooling | [VS Code workspace guide](../vscode-extension.md) |
| Extend a driver or prepare an audit | [Porting playbook](porting-playbook.md) |
| Formatting, comments and commits | [Code standards](../code-standards.md) |

## Hardware and source authority

| Need | Owner |
|---|---|
| Boot switches, clocks and hardware integration constraints | [Hardware guide](hardware.md) |
| Profile wiring, pin conflicts and physical connector drawing | [Pin ownership](pinmap.md) |
| Per-core address views and shared-memory carveouts | [Multicore memory map](multicore-memory-map.md) |
| RDK versus EVK evidence, source selection and missing references | [Reference source map](reference-source-map.md) |
| FreeRTOS/POSIX migration semantics | [NuttX API mapping](freertos-to-nuttx-mapping.md) |
| Optional peripheral bring-up | [CAN-FD](peripherals/canfd.md), [ADC](peripherals/adc.md), [SDHI](peripherals/sdhi.md) |

The [sensor profile table](pinmap.md#px4-configuration-profiles) distinguishes the
opt-in drone extension from default, simple and standalone bench wiring. P94
DRDY/button ownership cannot coexist with extension CS1. Missing generated pin
output or schematics are physical-qualification gaps; the
[reference map](reference-source-map.md#current-rdk-reference-availability)
defines what can support source and build work.

## Status and evidence

[NuttX driver status](port-status-nuttx.md) and
[PX4 HAL status](port-status-px4-hal.md) own qualification claims. A source
comparison, build or host test does not establish physical behavior. Retain
scope and provenance when citing these records:

| Record | Evidence boundary |
|---|---|
| [P94 button confirmation](evidence/gpio-button-interrupt-validation.md) | Named user retest; passing transcript and exact-image provenance remain open |
| [GY-912 RTT excerpt](evidence/gy912-icm20948-rtt-261011.txt) | Partial standalone sensor capture; limits in its validation guide |
| [SIH transcript](evidence/px4-nuttx-rzv2h-sih-transcript.txt) | Simulation/HRT evidence, no physical sensor or PWM proof |
| [Three-core IPC artifacts](evidence/rzv2h-three-core-ipc-artifacts.md) | Historical hashes/address checks, not runtime qualification |
| [PX4 software checkpoints](evidence/px4-hal-software-checkpoints.md) | Historical builds, reset-symbol checks and SIH/DShot provenance |
| [PX4 CR8-0 hardware tests](evidence/px4-hardware-tests-cr8-0-261021.md) | 21/32 native entries passed; 11 blocked, with bounded DShot/HRT observations and physical qualification limits |
| [Dual-CR8 software validation](evidence/dualcr8-software-validation-261021.md) | Current host/build receipt: 61 suites/583 cases, three firmware builds and five candidate artifact cases; no hardware tier or actuator-pair admission |
| [All-sample machine coverage](../../plans/261022-1849-rzv2h-jlink-retry/all-sample-results.json) | Current shipped-profile snapshot; [retry report](../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md) records bounded warm-load evidence and [remaining actions](../../plans/261022-1849-rzv2h-jlink-retry/remaining-samples.md) |
| [SCI5 NSH console run](evidence/sci5-nsh-console-cr8-0-261108.txt) | Standalone `nsh` on CR8-0, FT232 at 115200: boot progress, CRLF, 70-byte RX paste, 18 KB TX bursts; no MAVLink, error injection or PX4 image |
| [SCI5 Ctrl-C and CRLF run](evidence/sci5-nsh-ctrl-c-crlf-cr8-0-261108.txt) | Standalone `nsh` on CR8-0: syslog CRLF and three `cpuhog` Ctrl-C interrupts; no PX4 image |
| [SCI5 cold-start RX run](evidence/sci5-nsh-cold-start-rx-cr8-0-261109.txt) | Standalone `nsh` on CR8-0 after SCI5 register reset and simulated cold CPG state; RX alive with FIFO mode set before RE; no real power cycle |
| [ICM-45686 bit-rate run](evidence/icm45686-spi-rtt-261108-bitrate.txt) | Standalone sample at 7.69 and 20 MHz achieved SCK (divider readback); no waveform |
| [RTT, HIL and PX4 demo run](evidence/rtt-hil-demo-hardware-run-261109.md) | 2026-11-09 CR8-0: 87/90 runner profiles, IPC autotest pass, PX4 demo on the free-running HRT, `reboot` SoC reset; ether0 TX stall open, no analog or waveform qualification |
| [ether0 RGMII configuration gap](evidence/ether0-rgmii-interface-config-gap-261109.md) | Source comparison of the ether0 TX stall against FSP and the GbEther reference, plus a read-only board readback: `PHY_INTF_TYPE` and SSEL0 already hold the RGMII values; clearing `PFC_OEN.OEN0` on the board left the loopback at `-116`, and Ethernet is deferred |
| [Sensor-free RTT validation](evidence/sensor-free-rtt-validation-261024.md) and [machine matrix](evidence/sensor-free-rtt-matrix-261024.json) | 128 native entries: 92 PASS, 2 NOT-PASS, 6 BLOCKED and 28 OUT-OF-SCOPE; register/ISR/internal-function scope only, with no sensors or PWM waveforms |

The all-sample snapshot is incomplete: load verification, warm-load results and
confirmed fixture or engineering blockers remain separate evidence classes. The
retry report records the approved validation route and its limits; it does not
promote cold-state, electrical or production qualification.

The sensor-free RTT campaign is a separate native NuttX evidence record. Its
register, ISR-delivery and internal-function checks do not promote PX4 physical
or production qualification. Both GBETH units remain supported, and matching-core
I/O headers take precedence where present.

## Validation procedures

Use [the checklist](validation/validation-checklist.md) to record only the
checks applicable to the selected contract. Reset, ELF load and target writes
require explicit approval. Guides define acceptance; evidence records establish
what was actually observed.

| Profile or path | Procedure |
|---|---|
| Standalone SCI7 BMM150 | [I2C validation](validation/bmm150-i2c-validation.md) |
| Standalone SCI7 BMP280 | [BMP280 I2C validation](validation/bmp280-i2c-validation.md) |
| Standalone SPI0/P94 ICM20948 | [GY-912 validation](validation/gy912-icm20948-validation.md) |
| Standalone SPI0/SSLA0 DMA ICM-45686 | [ICM-45686 SPI validation](validation/icm45686-spi-validation.md) |
| Standalone GPT PWM | [PWM pin validation](validation/pwm-pin-validation.md) |
| Integrated `demo` PWM/ICM-45686/BMP280/TFmini/QGC bench | [Demo bench validation](validation/demo-bench-validation.md) |
| Integrated simple PWM/ICM20948 bench | [Simple profile validation](validation/simple-pwm-icm20948-validation.md) |
| Canonical dual-CR8 v3 candidates | [Sensor/actuator candidate validation](validation/dualcr8-sensor-actuator-demo.md) and [software receipt](evidence/dualcr8-software-validation-261021.md) |
| Regression/build/offline checks | [Regression tooling](validation/rzv2h-regression-ci.md) |
| Isolated CR8-0 driver samples over RTT | [Board sample procedure](validation/rzv2h-rtt-board-samples.md) |
| CR8-0 ↔ CR8-1 raw IPC | [IPC HIL guide](validation/rzv2h-ipc-hil-test-guide.md) |

## Multicore and customer design

[IPC architecture](ipc-architecture.md) distinguishes native raw links,
OpenAMP and the PX4 bridge. The
[J-Link contract](rzv2h-three-core-jlink-contract.md) owns core selectors and
unresolved reset/detach semantics. Qualifying one link does not qualify another
peer or an application bridge.

The [customer solution and design index](marketing/README.md) routes product
value, ecosystem research, system requirements and software requirements.
Those documents describe target designs; current port readiness remains owned
by the status tables above.

## Plans and maintenance

- [Reference-port plan](../../plans/261011-2017-rzv2h-drone-reference-port/plan.md)
  owns sensor-extension integration and its execution evidence.
- [Broader port plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
  owns driver, flight-path and optional multicore dependencies.
- [Journals](../journals) retain past incidents and lessons.

Update the owning status row when evidence changes, the pin matrix when
ownership changes, and this index when a document moves. Keep procedures in
`validation/`, named observations in `evidence/`, and execution progress under
its plan. Link to those owners instead of copying status or command inventories.
The PX4 User Guide site and its build/translation files remain a separate
upstream documentation surface.
