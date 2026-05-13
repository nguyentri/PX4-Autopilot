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

### Clone the Repository

```bash
git clone -b px4_ra8_rz https://github.com/nguyentri/PX4-Autopilot.git
cd PX4-Autopilot
```

### Initialize Submodules

```bash
git submodule update --init --recursive
```

### Build and Flash

```bash
# Set required environment variable
export GIT_SUBMODULES_ARE_EVIL=1

# Build for RA8P1 EVK
make renesas_evk-ra8p1_default

# Or use the convenience script
./make
```

## Prerequisites

### System Requirements

- Ubuntu 18.04 or later (recommended) or macOS
- Minimum 8GB RAM, 50GB free disk space
- ARM GCC toolchain
- Python 3.6+

### Dependencies

Install the required dependencies following the [PX4 Development Environment Setup](https://docs.px4.io/main/en/dev_setup/dev_env.html).

Key dependencies include:
- CMake 3.20+
- Ninja build system
- ARM GCC 9+
- Python packages (pip install -r requirements.txt)

## Building PX4

### Environment Setup

```bash
# Set required environment variable for custom NuttX reports
export GIT_SUBMODULES_ARE_EVIL=1
```

### Clean Build (if needed)

If a previous build failed for a different target, clean the NuttX artifacts:

```bash
cd platforms/nuttx/NuttX/nuttx
make distclean
cd ../../../..
```

### Build Commands

Build for specific Renesas targets:

```bash
# RA8P1 EVK
make renesas_evk-ra8p1_default

# RA8P1 IO CM33
make renesas_evk-ra8p1-io-cm33_default

# Other targets (when enabled)
# make renesas_fpb-ra8e1_default
# make renesas_rdk-rzv2h_default
```

The `renesas_rdk-rzv2h_default` target is CR8-only and does not depend on
CA55/Linux, SD, or RPMsg services. Production console is SEGGER RTT, and
parameters are stored at `/fs/params` on the board-mounted XSPI LittleFS
volume.

### Automated Build Script

Use the provided `build` script for batch building:

```bash
./build
```

This script builds all currently supported targets.

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

PX4 is open source under BSD 3-Clause license.
