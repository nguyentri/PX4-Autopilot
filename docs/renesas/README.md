# RZ/V2H Documentation Index

Index for RDK-RZ/V2H (R9A09G057H) PX4 + NuttX porting docs. Agents: read
[../../AGENTS.md](../../AGENTS.md) first for build, debug, and `refs/` layout.
Use the status documents for evidence levels and the selected board profile
for wiring; a newer reference does not replace a working sample's pin policy.

The current FreeRTOS reference is `refs/rzv2h_drone_px4-dev/`. Its sensor
extension replaces the single MPU9250/BMP280 with three ICM-45686 IMUs,
BMM150, BMP390L and INA228. Native integration is available in the opt-in
`renesas_rdk-rzv2h_drone` profile;
existing GY912/default/simple/SIH/DShot profiles retain their current contracts.
Start with [sensor wiring profiles](./pinmap.md#sensor-wiring-profiles) and
[reference availability](./reference-source-map.md#current-rdk-reference-availability).
Source/host/build work proceeds from the selected RDK XML and reference board
sources. Missing schematic/generated output is later physical-validation work. The
profile builds with host/artifact checks; it has no target qualification and
still uses volatile parameters and prototype identity. See the
[execution checkpoint](../../plans/261011-2017-rzv2h-drone-reference-port/reports/goal-progress.md).

---

## Hardware & Pinout

| Doc | Use it for |
|-----|-----------|
| [hardware.md](./hardware.md) | Clocks, memory map, GIC/ICU, DMAC, MHU, boot flow, DSW1 switches |
| [pinmap.md](./pinmap.md) | Native bench versus sensor-extension wiring, selected RDK XML, and physical header drawing |
| [multicore-memory-map.md](./multicore-memory-map.md) | CR8-0/CR8-1/CM33 unified memory map and per-core aliases (single source of truth) |

## Driver Development

| Doc | Use it for |
|-----|-----------|
| [porting-playbook.md](./porting-playbook.md) | Step-by-step: add a driver, FSP → NuttX recipe, build/validate loop |
| [freertos-to-nuttx-mapping.md](./freertos-to-nuttx-mapping.md) | FreeRTOS/POSIX → NuttX API cheat sheet |
| [reference-source-map.md](./reference-source-map.md) | Which `refs/` sample to trust per core/driver; evidence precedence |
| [../design-guidelines.md](../design-guidelines.md) | Lower/upper-half split, ISR, DMAC, reset rules |
| [../code-standards.md](../code-standards.md) | PX4 vs NuttX style, Kconfig, commits |
| [peripherals/canfd.md](./peripherals/canfd.md), [sdhi.md](./peripherals/sdhi.md), [adc.md](./peripherals/adc.md) | Per-peripheral notes, source-verified (CAN-FD on-target loopback, SDHI build-clean, ADC blocked) |

## Status

| Doc | Use it for |
|-----|-----------|
| [port-status-nuttx.md](./port-status-nuttx.md) | Per-driver NuttX status and evidence tier (authoritative) |
| [gpio-button-interrupt-validation.md](./gpio-button-interrupt-validation.md) | 2026-10-01 CR8-0 `nsh-leds` P94 external-interrupt confirmation, fixes, and open evidence gates |
| [port-status-px4-hal.md](./port-status-px4-hal.md) | PX4 HAL integration status per peripheral (authoritative) |
| [px4-nuttx-rzv2h-sih-transcript.txt](./px4-nuttx-rzv2h-sih-transcript.txt) | Unmodified historical SIH evidence with simulated sensors; no extension-bus or physical PWM proof |
| [gy912-icm20948-rtt-261011.txt](./gy912-icm20948-rtt-261011.txt) | Unmodified legacy single-ICM20948 RTT excerpt; scope and limits in the GY912 guide |

## Multi-Core IPC

| Doc | Use it for |
|-----|-----------|
| [ipc-architecture.md](./ipc-architecture.md) | IPCC/MHU, uORB bridge framing, CRC, sequence checks |
| [rzv2h-ipc-hil-test-guide.md](./rzv2h-ipc-hil-test-guide.md) | RAM load order, RTT driving, `ipctest` 100/100 acceptance, autotest scripts |
| [rzv2h-three-core-jlink-contract.md](./rzv2h-three-core-jlink-contract.md) | J-Link core selectors, CM33 aliases, reset/detach gates |
| [rzv2h-three-core-ipc-artifacts.md](./rzv2h-three-core-ipc-artifacts.md) | Tracked ELF hashes, PT_LOAD span checks, CM33 vector contract |

## Validation & Prompts

| Doc | Use it for |
|-----|-----------|
| [validation-checklist.md](./validation-checklist.md) | Per-driver static + on-target bring-up checklist |
| [pwm-pin-validation.md](./pwm-pin-validation.md) | Standalone GPT PWM duty/period pin measurements, endpoint limits and live-update capture |
| [simple-pwm-icm20948-validation.md](./simple-pwm-icm20948-validation.md) | PX4 simple bench: SPI0 raw/FIFO/IRQ evidence and four-channel PWM measurement gates |
| [gy912-icm20948-validation.md](./gy912-icm20948-validation.md) | Standalone CR8-0 SPI0/P94 ICM20948 diagnostic wiring, RTT commands and acceptance gates |
| [bmm150-i2c-validation.md](./bmm150-i2c-validation.md) | Standalone CR8-0 SCI7 I2C BMM150 diagnostic wiring, RTT commands and acceptance gates |
| [prompt-recipes.md](./prompt-recipes.md) | Reusable agent prompts: driver audit, HAL port, migration |
| [../deployment-guide.md](../deployment-guide.md) | Build, RAM load, RTT console, J-Link debug |

## Autonomous Drone Solution and Design

| Doc | Use it for |
|-----|------------|
| [marketing/README.md](./marketing/README.md) | Entry point, document map, customer and engineering reading paths, and direct design/development links |
| [marketing/rzv2h-autonomous-drone-solution.md](./marketing/rzv2h-autonomous-drone-solution.md) | Customer-facing single-central-SoC solution, external-device story, and approved claim boundaries |
| [marketing/rzv2h-system-specification.md](./marketing/rzv2h-system-specification.md) | Target aircraft boundary, external-device interfaces, system requirements, and verification gates |
| [marketing/rzv2h-software-specification.md](./marketing/rzv2h-software-specification.md) | Target A55/DRP-AI3/CR8-0/CR8-1 allocation, IPC, lifecycle, fault handling, and software requirements |
| [marketing/rzv2h-development-ecosystem.md](./marketing/rzv2h-development-ecosystem.md) | Customer starting profiles, RDK pre-development boundary, official repositories, Yocto/Ubuntu/ROS 2 versions, and AI/YOLO compatibility guidance |

Claims in `marketing/` are gated by the status documents above. Target
architecture is not engineering evidence that a capability is implemented.

---

## AI-Assisted Porting Workflow

Project-local skills, in order, for a bounded RZ/V2H change:

1. **`firmware-audit`** + [reference-source-map.md](./reference-source-map.md) — bug hunt with core-matched reference inputs.
2. **[audit-rzv2h-px4-nuttx-port](../../.claude/skills/audit-rzv2h-px4-nuttx-port/SKILL.md)** — FSP/CMSIS-to-PX4 cross-layer audit.
3. **`ak-debug`** (installed skill) — root-cause proof for a build or runtime failure.
4. **[gdb-jlink-debug](../../.claude/skills/gdb-jlink-debug/SKILL.md)** — J-Link/GDB/RTT/SVD hardware evidence.
5. **`ak-code-review`** (installed skill) — review the diff and its verification evidence.

Build success, RTT output, or a static register comparison is not on-target
evidence. GDB/J-Link reset, ELF load, and target writes require explicit
authorization.

## Reading Order for Newcomers

1. [../../AGENTS.md](../../AGENTS.md) — repo map, build, debug
2. [../project-overview-pdr.md](../project-overview-pdr.md) — scope
3. [../system-architecture.md](../system-architecture.md) — layers, core roles
4. [../codebase-summary.md](../codebase-summary.md) — where code lives
5. [hardware.md](./hardware.md), [pinmap.md](./pinmap.md) — the chip and board
6. [porting-playbook.md](./porting-playbook.md) — then the driver at hand

## Key Links

- **Active reference-port plan:** [reference port](../../plans/261011-2017-rzv2h-drone-reference-port/plan.md)
- **Broader driver/multicore roadmap:** [master plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
- **Roadmap:** [../project-roadmap.md](../project-roadmap.md)
- **Board pinout / wiring:** [../../boards/renesas/rdk-rzv2h/src/pinout.md](../../boards/renesas/rdk-rzv2h/src/pinout.md)
- **Software wiring source (local `refs/`):** selected `RDK` pin set in
  `refs/rzv2h_drone_px4-dev/configuration.xml`; generated `rzv_gen/pin_data.c`
  and extension schematic are later corroboration inputs.
- **Physical header drawing:** [RDK 40-pin connector](./rzv2h-rdk-40_pin_header_pin.png)
  (SoC-to-header connections, not extension sensor assignments).
- **NuttX arch drivers:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/)
- **PX4 board:** [../../boards/renesas/rdk-rzv2h/](../../boards/renesas/rdk-rzv2h/)
- **Register map:** `../../rzv2h.svd` (CMSIS-SVD; use with `platforms/nuttx/Debug/svd_register_tool.py`)

## Maintenance

- **Per PR:** update `port-status-nuttx.md` / `port-status-px4-hal.md` (and `pinmap.md` if pins change) when a driver's status changes; bump the doc's `**Date:**`.
- New files: kebab-case. Add them to this index.
