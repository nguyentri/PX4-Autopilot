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

### Automated Build Script

Use the provided `make` script for batch building:

```bash
./make
```

This script builds all currently supported targets.

## Flashing

After building, flash the firmware to your target board using the appropriate flashing tool for your Renesas development board.

## Running and Testing

### Simulation

PX4 supports various simulation environments. For hardware-in-the-loop testing:

```bash
# SITL simulation
make px4_sitl_default

# Gazebo simulation
make px4_sitl_default sitl_gazebo-classic
```

### Hardware Testing

1. Flash the firmware to your Renesas board
2. Connect via MAVLink (USB or serial)
3. Use QGroundControl for configuration and flight control
4. Perform pre-flight checks and calibration

## Development

### Code Structure

- `src/` - PX4 source code
- `platforms/nuttx/` - NuttX platform-specific code
- `boards/renesas/` - Renesas board configurations
- `msg/` - MAVLink message definitions

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

Please follow the [PX4 Contributing Guidelines](https://docs.px4.io/main/en/contribute/) and ensure all tests pass.

### Testing

```bash
# Run unit tests
make tests

# Run integration tests
make integration_tests
```

## Documentation

- [PX4 User Guide](https://docs.px4.io/main/en/)
- [PX4 Developer Guide](https://docs.px4.io/main/en/development/development.html)
- [Renesas RA Family Documentation](https://www.renesas.com/us/en/products/microcontrollers-microprocessors/ra-cortex-m-mcus)

## Troubleshooting

### Common Issues

1. **Build fails with NuttX errors**: Clean NuttX artifacts and rebuild
2. **Missing dependencies**: Follow the development environment setup
3. **Flash failures**: Check board connections and power supply

### Getting Help

- [PX4 Discuss Forum](https://discuss.px4.io/)
- [PX4 Slack](https://slack.px4.io/)
- [GitHub Issues](https://github.com/nguyentri/PX4-Autopilot/issues)

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.

PX4 is open source under BSD 3-Clause license.
