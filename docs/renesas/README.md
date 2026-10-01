# RZ/V2H Documentation Index

Index for RDK-RZ/V2H (R9A09G057H) PX4 + NuttX porting docs. Agents: read
[../../AGENTS.md](../../AGENTS.md) first for build, debug, and `refs/` layout.
Each doc carries its own `**Date:**` header; trust that over this index.

---

## Hardware & Pinout

| Doc | Use it for |
|-----|-----------|
| [hardware.md](./hardware.md) | Clocks, memory map, GIC/ICU, DMAC, MHU, boot flow, DSW1 switches |
| [pinmap.md](./pinmap.md) | Software pin ownership matrix; cross-check with `pin_data.c` and board electrical authority |
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
| [port-status-px4-hal.md](./port-status-px4-hal.md) | PX4 HAL integration status per peripheral (authoritative) |
| [px4-nuttx-rzv2h-sih-transcript.txt](./px4-nuttx-rzv2h-sih-transcript.txt) | Archived 2026-07-30 on-target SIH transcript (evidence) |

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
| [prompt-recipes.md](./prompt-recipes.md) | Reusable agent prompts: driver audit, HAL port, migration |
| [../deployment-guide.md](../deployment-guide.md) | Build, RAM load, RTT console, J-Link debug |

## Product (non-engineering)

[marketing/](./marketing/) — solution positioning and system specification. Claims there are gated by the status docs above; do not use them as engineering evidence.

---

## AI-Assisted Porting Workflow

Project-local skills, in order, for a bounded RZ/V2H change:

1. **`firmware-audit`** + [reference-source-map.md](./reference-source-map.md) — bug hunt with core-matched reference inputs.
2. **[audit-rzv2h-px4-nuttx-port](../../.claude/skills/audit-rzv2h-px4-nuttx-port/SKILL.md)** — FSP/CMSIS-to-PX4 cross-layer audit.
3. **[ck-debug](../../.claude/skills/ck-debug/SKILL.md)** — root-cause proof for a build or runtime failure.
4. **[gdb-jlink-debug](../../.claude/skills/gdb-jlink-debug/SKILL.md)** — J-Link/GDB/RTT/SVD hardware evidence.
5. **[ck-code-review](../../.claude/skills/ck-code-review/SKILL.md)** — review the diff and its verification evidence.

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

- **Active plan:** [../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
- **Roadmap:** [../project-roadmap.md](../project-roadmap.md)
- **Board pinout / wiring:** [../../boards/renesas/rdk-rzv2h/src/pinout.md](../../boards/renesas/rdk-rzv2h/src/pinout.md)
- **Pin data source (local `refs/`):** `refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c`
- **NuttX arch drivers:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/)
- **PX4 board:** [../../boards/renesas/rdk-rzv2h/](../../boards/renesas/rdk-rzv2h/)
- **Register map:** `../../rzv2h.svd` (CMSIS-SVD; use with `platforms/nuttx/Debug/svd_register_tool.py`)

## Maintenance

- **Per PR:** update `port-status-nuttx.md` / `port-status-px4-hal.md` (and `pinmap.md` if pins change) when a driver's status changes; bump the doc's `**Date:**`.
- New files: kebab-case. Add them to this index.
