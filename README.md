# PX4 Autopilot for Renesas RA8E1/RA8P1/RZV2H

[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

## Overview

This fork of PX4 Autopilot provides support for Renesas microcontroller and microprocessor families, bringing the powerful PX4 flight stack to Renesas-based drone platforms.

## Supported Hardware

### Currently Supported

- ⏸ **Renesas FPB-RA8E1 PX4 CM85** — Basic Test (BSP, Shell, and SPI)
- ⏸ **Renesas EVK-RA8P1 PX4 CM85** — Basic Test (BSP, Shell, SPI, and PWM)
- ⏸ **Renesas EVK-RA8P1 IO CM33** — Build Only
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 (Default)** — Build-Clean; RTT0 console, volatile `/fs/params`, WDT-backed reset chain linked, SPI0/SCI7/PWM/serial adapters wired; on-target hardware validation pending
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 DShot** — Build-Clean (opt-in TX-only DShot600 via GPT+DMAC; hardware scope proof pending)
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 Core-Only** — Build-Clean (diagnostics-only rollback profile with RTT/HRT/params/uORB and bounded PWM bench test)
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 SIH** — On-Target Bounded Demo; simulated sensors (accel/gyro/baro/mag/GPS), HIL sensors, `pwm_out_sim`; GTM7 HRT callback pass; cold-cycle, pin-safety, and soak gates pending
- ⏸ **Renesas RDK-RZV2H IO CR8_1** — Build Only (raw IPC / IPCC build-clean with distinct RTT console and ABI-v2 sequence recovery; target proof pending)
- ⏸ **Renesas RDK-RZV2H IO CM33** — Build Only (raw IPC / IPCC build-clean with secure SRAM `0x08002800` vectors, non-secure MHU `0x50480000`; target boot/IPC proof pending)

### Build Targets

`./build.sh --list` reports these Renesas targets:

```text
renesas_evk-ra8p1-io-cm33_default
renesas_evk-ra8p1_default
renesas_evk-ra8p1_dshot
renesas_evk-ra8p1_test
renesas_fpb-ra8e1_default
renesas_fpb-ra8e1_dshot
renesas_fpb-ra8e1_test
renesas_rdk-rzv2h-io-cm33_default
renesas_rdk-rzv2h-io-cr8_1_default
renesas_rdk-rzv2h_core_only
renesas_rdk-rzv2h_default
renesas_rdk-rzv2h_dshot
renesas_rdk-rzv2h_sih
```

## RZ/V2H Porting Status Summary

The RDK-RZ/V2H porting effort focuses on Cortex-R8 Core 0 as the primary flight stack, with Cortex-R8 Core 1 and Cortex-M33 in multi-core IPC roles.

### NuttX Driver Matrix (42 Drivers)

| Status Tier | Count | Drivers |
|-------------|-------|---------|
| **Bounded On-Target** | 9 | CAN-FD (internal loopback), DMAC (memcpy), GTM (timer0/2), HRT (GTM7 shim / SIH test), IRQ (CR8 GIC), Serial (SCI-B on SCI4 shell), SPI (RSPI loopback), Startup (CR8-0), Timer ISR (CR8) |
| **Build-Clean** | 17 | IPC Dispatch, IPC IPCC, IPC Raw (CR8-0/CR8-1/CM33), Memory Management, MHU Core, OpenAMP, RPMsg, Remote Proc, SCI/I2C Master, SCI/I2C Clock, SCI/I2C ISR, SCI/SPI Master, SCI/SPI Clock, SCI/SPI ISR, SDHI, Watchdog, System Reset (CR8) |
| **Source-Audited** | 11 | Clock/CPG, GPIO (P0–PB), GPT (32-bit), I2C (RIIC), ICU (CR8), ICU (CM33), IRQ (CM33), Low-Level UART, MPU Regions, POEG, Startup (CM33) |
| **Blocked (HW/HIL Gates)** | 4 | ADC (SAR 12-bit), Ether (GbEther), Ether PHY, SCIF UART (source defects resolved; target HW/HIL proof open) |
| **Stub** | 1 | Idle Task (WFI) |
| **Production** | 0 | Pending stress & soak testing (≥10k cycles / 1h uptime) |

### PX4 HAL Integration Matrix (CR8-0)

| Peripheral / Subsystem | Status | Implementation & Policy Notes |
|------------------------|--------|-------------------------------|
| **SPI** | `build-clean` | RSPI0 mapped to P90–P92, P93 GPIO CS; sensor bus registration shared; DRDY on P50. |
| **I2C** | `build-clean` | BMP280 barometer on SCI7 simple-I2C (P76/P77); `CONFIG_RZV_SCI7_I2C=y`. |
| **UART / Serial** | `in-progress` | RTT0 `/dev/console` for PX4; SCI4 LiDAR, SCI5 MAVLink/QGC, SCI6 RC, SCI9 GPS. |
| **GPIO** | `build-clean` | Port I/O and IRQ/edge via `rzv_gpio*` across 86 bonded pins. |
| **PWM / ESC** | `build-clean` | 4-channel GPT output (PA4, PA7, P96, P53); restart-safe channel allocation; safe reset pin unwinding. |
| **DShot** | `build-clean` (opt-in) | TX-only DShot600 via GPT + DMAC in `renesas_rdk-rzv2h_dshot`; BDShot telemetry disabled (`-ENOTSUP`). |
| **Timer / HRT** | `build-clean` | Dedicated GTM7 64-bit epoch free-run comparison; tested in SIH demo (`22,044 µs` sleep, `4 µs` latency). |
| **xSPI / Parameter Storage** | `blocked` (volatile fallback) | TMPFS `/fs/params` active default (resets on reboot); xSPI LittleFS disabled pending flash safety proof. |
| **Board Identity** | `blocked` | Fixed UUID/GUID (`RZV2H0000000000`); single-prototype workflow only until persistent UID source approved. |
| **Multi-Core IPC** | `build-clean` | Unified memory map, ABI-v2 rings, fail-closed ELF load checker, and MHU doorbells for CR8-0/CR8-1/CM33. |

## Documentation

See [docs/](./docs/) and [docs/renesas/](./docs/renesas/) for comprehensive guides:

### General & Architecture

| Document | Purpose |
|----------|---------|
| [project-overview-pdr.md](./docs/project-overview-pdr.md) | Project scope, objectives, and requirements |
| [system-architecture.md](./docs/system-architecture.md) | System design and component architecture |
| [codebase-summary.md](./docs/codebase-summary.md) | Codebase structure and module overview |
| [code-standards.md](./docs/code-standards.md) | Coding standards and conventions |
| [design-guidelines.md](./docs/design-guidelines.md) | Design patterns and architectural decisions |
| [deployment-guide.md](./docs/deployment-guide.md) | Build and deployment procedures |
| [project-roadmap.md](./docs/project-roadmap.md) | Planned features and milestones |

### Renesas RZ/V2H Port Documentation

| Document | Purpose |
|----------|---------|
| [docs/renesas/README.md](./docs/renesas/README.md) | RZ/V2H documentation mini-index and navigation guide |
| [hardware.md](./docs/renesas/hardware.md) | Clocks, memory map, GIC/ICU, DMAC, MHU, boot flow, and DSW1 switches |
| [pinmap.md](./docs/renesas/pinmap.md) | Software pin ownership matrix, alternate functions, and electrical mapping |
| [port-status-nuttx.md](./docs/renesas/port-status-nuttx.md) | 42-driver NuttX HAL coverage, evidence levels, and audit reports |
| [port-status-px4-hal.md](./docs/renesas/port-status-px4-hal.md) | PX4 HAL integration status per peripheral and CR8-0 goal reconciliation |
| [porting-playbook.md](./docs/renesas/porting-playbook.md) | Step-by-step recipe for FSP to NuttX driver porting |
| [freertos-to-nuttx-mapping.md](./docs/renesas/freertos-to-nuttx-mapping.md) | FreeRTOS/POSIX to NuttX API translation cheat sheet |
| [prompt-recipes.md](./docs/renesas/prompt-recipes.md) | Parametric AI prompts for driver audits, HAL porting, and debugging |
| [reference-source-map.md](./docs/renesas/reference-source-map.md) | Canonical EVK/core selection map and evidence hierarchy |
| [multicore-memory-map.md](./docs/renesas/multicore-memory-map.md) | Ratified unified memory map for CR8-0, CR8-1, and CM33 address spaces |
| [ipc-architecture.md](./docs/renesas/ipc-architecture.md) | Multi-core IPC architecture, MHU channels, and shared DDR ring buffers |
| [rzv2h-three-core-ipc-artifacts.md](./docs/renesas/rzv2h-three-core-ipc-artifacts.md) | Tracked host ELF hashes, load-span checks, and address contracts |
| [rzv2h-three-core-jlink-contract.md](./docs/renesas/rzv2h-three-core-jlink-contract.md) | J-Link GDB server devices, core selectors, and debugger lifecycle gates |
| [validation-checklist.md](./docs/renesas/validation-checklist.md) | Per-driver static and dynamic bring-up checklist |
| [px4_nuttx_rzv2h_sil.txt](./docs/renesas/px4_nuttx_rzv2h_sil.txt) | Archived on-target SIH simulation demonstration transcript |

## Quick Start

```bash
git clone -b px4_ra_rzv https://github.com/nguyentri/PX4-Autopilot.git
cd PX4-Autopilot

# One-time setup: scrubs hostile env vars, checks deps, inits submodules.
# Use `source` so the env scrub propagates into your shell.
source ./build_setup.sh

# Build one target...
./build.sh renesas_rdk-rzv2h_default
# ...or build every Renesas target
./build.sh
```

`./build.sh --list` enumerates every supported target. `make <target>` works too
and is equivalent to `./build.sh <target>`.

## Quick Start for Contributors

Extending the RZ/V2H port? Start here:

- **[docs/renesas/porting-playbook.md](./docs/renesas/porting-playbook.md)** — Step-by-step guide for adding drivers and features
- **[docs/renesas/prompt-recipes.md](./docs/renesas/prompt-recipes.md)** — Effective prompts to use for port development
- **[docs/renesas/port-status-nuttx.md](./docs/renesas/port-status-nuttx.md)** — Current NuttX HAL coverage and next steps
- **[docs/renesas/validation-checklist.md](./docs/renesas/validation-checklist.md)** — Per-driver validation checklist template

## Prerequisites

`build_setup.sh` validates every requirement; install whatever it flags missing.
For background, see the [PX4 Development Environment Setup](https://docs.px4.io/main/en/dev_setup/dev_env.html).

Required: Linux/macOS host, ARM GCC 9+ (`arm-none-eabi-gcc` on `PATH`), CMake
3.20+, Ninja, Python 3.6+ with `kconfiglib`.

> **Heads-up:** if you sourced the e2studio FSP env script, it exports
> `CMAKE_C_COMPILER` / `CMAKE_CXX_COMPILER` etc. which break the CMake compiler
> test. `build_setup.sh` (sourced) and `build.sh` both unset these defensively.

## Repository Layout

Renesas builds validate that the custom NuttX submodules track:

- `platforms/nuttx/NuttX/nuttx` → `https://gitlab.com/OneKiwiTech/onekiwi_wiki/drone_solutions/nuttx_px4.git`, branch `main`
- `platforms/nuttx/NuttX/apps` → `https://gitlab.com/OneKiwiTech/onekiwi_wiki/drone_solutions/nuttx-apps.git`, branch `main`

The `renesas_rdk-rzv2h_default` target is CR8-only — no CA55/Linux, SD, or
RPMsg dependency. Production console is SEGGER RTT. During bring-up,
`/fs/params` lives on volatile TMPFS and resets at reboot. The experimental
xSPI LittleFS backend stays disabled until controller setup, partition
ownership, erase/program/readback, reboot persistence, and power-loss recovery
are proven on the RDK.

### Switching Targets

`./build.sh` runs `make distclean` in NuttX between targets automatically.
Pass `--no-clean` to skip when iterating on a single target.

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

PX4 is open source under BSD 3-Clause license.
