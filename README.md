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
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 DShot** — Bounded on-target motor-stop TX (opt-in DShot600 via GPT+DMAC); electrical waveform, ESC, and nonzero-throttle proof pending ([latest evidence](./docs/renesas/evidence/px4-hardware-tests-cr8-0-261021.md))
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 Simple** — Build-Clean bench profile: RTT, four-channel PWMOut and SPI0 ICM20948 raw accel/gyro; fresh four-profile software checks passed; hardware untested
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 DualCR8** — Build-Clean exact-BOM sensor profile with a supervised remote-output producer; hardware identity unconfigured, no admitted actuator pair
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0 SIH** — On-Target Bounded Demo; simulated sensors (accel/gyro/baro/mag/GPS), HIL sensors, `pwm_out_sim`; GTM7 HRT callback pass; cold-cycle, pin-safety, and soak gates pending
- ⏸ **Renesas RDK-RZV2H IO CR8_1** — Build Only (raw IPC / IPCC build-clean with distinct RTT console and ABI-v2 sequence recovery; NuttX-only raw IPC demo passes 100/100 on target; this PX4 image is not target-proven)
- ⏸ **Renesas RDK-RZV2H IO CR8_1 PWM** — Build-Clean ABI-v3 supervisor candidate; physical resources remain unclaimed until a selected hardware contract is admitted
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
renesas_rdk-rzv2h-io-cr8_1_demo
renesas_rdk-rzv2h-io-cr8_1_pwm
renesas_rdk-rzv2h_default
renesas_rdk-rzv2h_demo
renesas_rdk-rzv2h_demosih
renesas_rdk-rzv2h_drone
renesas_rdk-rzv2h_dshot
renesas_rdk-rzv2h_dualcr8
renesas_rdk-rzv2h_sih
renesas_rdk-rzv2h_simple
```

## RZ/V2H Porting Status Summary

Cortex-R8 core 0 runs the PX4 flight stack; CR8-1 and CM33 are IO cores over IPC.

- **NuttX drivers:** a handful have bounded on-target evidence (CR8 startup/IRQ, SCI4 shell, GTM/HRT, DMAC memcpy, CAN-FD and SPI loopback, raw IPC CR8-0 ↔ CR8-1 100/100); most are build-clean or source-audited; none are production.
- **PX4 HAL (CR8-0):** SPI, I2C, GPIO, PWM, HRT, IPC build-clean; params on volatile TMPFS; xSPI persistence and per-unit identity remain qualification work.
- **Integrated PX4:** bounded SIH and DShot motor-stop evidence; the dual-CR8 sensor/output application is host-tested and build-clean. The sensor/actuator flight path remains unqualified.

Authoritative, per-driver tables: [port-status-nuttx.md](./docs/renesas/port-status-nuttx.md) and [port-status-px4-hal.md](./docs/renesas/port-status-px4-hal.md). Do not copy them here.

## Documentation

See [docs/](./docs/) and [docs/renesas/](./docs/renesas/) for comprehensive guides:

### General & Architecture

| Document | Purpose |
|----------|---------|
| [system-architecture.md](./docs/system-architecture.md) | Port scope, architecture, boundaries and plan links |
| [codebase-summary.md](./docs/codebase-summary.md) | Codebase structure and module overview |
| [code-standards.md](./docs/code-standards.md) | Coding standards and conventions |
| [porting-playbook.md](./docs/renesas/porting-playbook.md) | Driver design, implementation and review workflow |
| [deployment-guide.md](./docs/deployment-guide.md) | Build and deployment procedures |

### Renesas RZ/V2H Port Documentation

Start at [docs/renesas/README.md](./docs/renesas/README.md) (hardware, pinmap, status, playbook, IPC, validation).
For the compact PWM + ICM20948 bench target, use the
[simple validation guide](./docs/renesas/validation/simple-pwm-icm20948-validation.md).
The opt-in sensor-extension profile is tracked through
the [reference-port plan](./plans/261011-2017-rzv2h-drone-reference-port/plan.md).
Its profile wiring preserves existing native samples; source/host/build
work proceeds independently of later physical qualification.
The retired core-only target is historical; its NuttX/ROMFS resources and evidence remain archived.

The `demo` target is a CR8-0 bench image: four 400 Hz PWM outputs, one polled
ICM-45686 on SPI0/P93, BMP280 on SCI7, TFmini on SCI4 and QGroundControl on
SCI5. See the [demo bench validation guide](./docs/renesas/validation/demo-bench-validation.md).

The `dualcr8` target is build-clean for the exact-BOM sensor bring-up in the
[dual-CR8 demo plan](./plans/261021-0230-rzv2h-dualcr8-sensor-demo/plan.md).
It leaves CR8-0 motor outputs unclaimed and requires I/O status before arming.
The v3 producer and `renesas_rdk-rzv2h-io-cr8_1_pwm` supervisor candidate have
host/build checks and a [validation procedure](./docs/renesas/validation/dualcr8-sensor-actuator-demo.md).
The [software validation record](./docs/renesas/evidence/dualcr8-software-validation-261021.md)
records the current checks and remaining application gaps.
Their hardware identity remains unconfigured and
physical outputs stay unclaimed. Selected ESC/power/storage contracts and
physical qualification are still pending; this is not an accepted actuator pair.
The CR8-1 `default` image retains its legacy relay role and is not its peer.

### AI Agents

The repository includes the [gdb-jlink-debug skill](.claude/skills/gdb-jlink-debug/SKILL.md)
and its RZ/V2H references as regular files. Claude Code can discover it in
`.claude/skills/`; other agents can read `SKILL.md` directly. Install SEGGER
J-Link tools and an ARM GDB, then follow the skill's host preflight with your
board and matching ELF. No home-directory skill installation is required.

[AGENTS.md](./AGENTS.md) is the agent entry point: code map, the two build scripts, RTT/J-Link debug, `refs/` layout, and evidence rules. [CLAUDE.md](./CLAUDE.md) adds Claude Code workflow rules on top.

## Quick Start

```bash
git clone -b px4_ra_rzv https://github.com/nguyentri/PX4-Autopilot.git
cd PX4-Autopilot

# One-time setup: scrubs hostile env vars, checks deps, inits submodules.
# Use `source` so the env scrub propagates into your shell.
source ./build_setup.sh

# Build one or more targets (a target is required; bare ./build.sh prints help)
./build.sh renesas_rdk-rzv2h_default
```

`./build.sh --list` enumerates every supported target. `make <target>` works too
and is equivalent to `./build.sh <target>`.

Load a built target onto the board with `./flash.sh` (same target names;
bare `./flash.sh` prints help and the built targets):

```bash
./flash.sh renesas_rdk-rzv2h_default                      # CR8-0 RAM load + start
./flash.sh rdk-rzv2h_dualcr8 rdk-rzv2h-io-cr8_1_pwm       # CR8-0 + CR8-1 pair
./flash.sh renesas_evk-ra8p1_default                      # RA8: flash, reset, run
```

RZ/V2H CR8 images are volatile RAM loads started at `__start` (no SoC reset);
the RZ/V2H CM33 target is refused because connecting to it resets the SoC.

NuttX-only builds (driver bring-up, NSH test configs) use a separate script:

```bash
platforms/nuttx/NuttX/build.sh --list      # nsh-rtt, ipcc, adc, canfd, ...
platforms/nuttx/NuttX/build.sh nsh-rtt     # ELF: platforms/nuttx/NuttX/nuttx/nuttx
platforms/nuttx/NuttX/flash.sh             # load that last build on its core
```

## Quick Start for Contributors

Extending the RZ/V2H port? Start here:

- **[docs/renesas/porting-playbook.md](./docs/renesas/porting-playbook.md)** — Step-by-step guide for adding drivers and features
- **[docs/renesas/port-status-nuttx.md](./docs/renesas/port-status-nuttx.md)** — Current NuttX HAL coverage and next steps
- **[docs/renesas/validation/validation-checklist.md](./docs/renesas/validation/validation-checklist.md)** — Per-driver validation checklist template

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
