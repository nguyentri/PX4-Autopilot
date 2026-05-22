# PX4 Autopilot for Renesas RA8E1/RA8P1/RZV2H

[![License](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

## Overview

This fork of PX4 Autopilot provides support for Renesas microcontroller and microprocessor families, bringing the powerful PX4 flight stack to Renesas-based drone platforms.

## Supported Hardware

### Currently Supported

- ⏸ **Renesas EVK-RA8P1 PX4 CM85**  - Basic Support
- ⏸ **Renesas EVK-RA8P1 PX4 CM33**  - Build Only
- ⏸ **Renesas FPB-RA8E1 PX4 CR8_0** - Basic Support
- ⏸ **Renesas RDK-RZV2H PX4 CR8_0** - Build Only
- ⏸ **Renesas RDK-RZV2H IO  CR8_1** - Build Only
- ⏸ **Renesas RDK-RZV2H IO  CM33**  - Build Only

## Quick Start

```bash
git clone -b px4_ra_rzv https://github.com/nguyentri/PX4-Autopilot.git
cd PX4-Autopilot

# One-time setup: scrubs hostile env vars, checks deps, inits submodules.
# Use `source` so the env scrub propagates into your shell.
source ./build_setup.sh

# Build one target...
./build.sh renesas_evk-ra8p1_default
# ...or build every Renesas target
./build.sh
```

`./build.sh --list` enumerates every supported target. `make <target>` works too
and is equivalent to `./build.sh <target>`.

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

- `platforms/nuttx/NuttX/nuttx` → `https://github.com/nguyentri/NuttX_Px4.git`, branch `nuttx_ra_rzv`
- `platforms/nuttx/NuttX/apps` → `https://github.com/nguyentri/nuttx-apps.git`, branch `main`

The `renesas_rdk-rzv2h_default` target is CR8-only — no CA55/Linux, SD, or
RPMsg dependency. Production console is SEGGER RTT and parameters live at
`/fs/params` on the board-mounted XSPI LittleFS volume.

### Switching Targets

`./build.sh` runs `make distclean` in NuttX between targets automatically.
Pass `--no-clean` to skip when iterating on a single target.

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

PX4 is open source under BSD 3-Clause license.
