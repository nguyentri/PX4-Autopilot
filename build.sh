#!/bin/bash
#
# PX4 Build Script for Renesas RA8/RZ Targets
#
# This script builds PX4 firmware for supported Renesas microcontroller targets.
# It sets the required environment variables and builds multiple targets sequentially.
#
# Usage: ./make
#
# Requirements:
# - PX4 development environment set up
# - Git submodules initialized
# - Required dependencies installed
#

set -e  # Exit on any error

# Set environment variable required for custom NuttX reports
export GIT_SUBMODULES_ARE_EVIL=1

echo "=========================================="
echo "PX4 Build Script for Renesas RA8/RZ Targets"
echo "=========================================="
echo

# Optional: Clean NuttX build artifacts if previous build failed
# Uncomment the following lines if you encounter build issues due to
# previous failed builds for different targets
#
# echo "Cleaning NuttX build artifacts..."
# cd platforms/nuttx/NuttX/nuttx
# make distclean
# cd ../../../..
# echo "NuttX artifacts cleaned."
# echo

echo "Building PX4 for Renesas targets..."
echo

# Build currently supported targets
echo "Building renesas_evk-ra8p1_default..."
echo "y" | make renesas_evk-ra8p1_default
echo "✓ renesas_evk-ra8p1_default build completed"
echo

echo "Building renesas_evk-ra8p1-io-cm33_default..."
echo "y" | make renesas_evk-ra8p1-io-cm33_default
echo "✓ renesas_evk-ra8p1-io-cm33_default build completed"
echo

# Development/In-progress targets (currently disabled)
# Uncomment when these targets are ready for building
#
# echo "Building renesas_fpb-ra8e1_default..."
# echo "y" | make renesas_fpb-ra8e1_default
# echo "✓ renesas_fpb-ra8e1_default build completed"
# echo
#
# echo "Building renesas_rdk-rzv2h_default..."
# echo "y" | make renesas_rdk-rzv2h_default
# echo "✓ renesas_rdk-rzv2h_default build completed"
# echo
#
# echo "Building renesas_rdk-rzv2h-io-cr8_1_default..."
# echo "y" | make renesas_rdk-rzv2h-io-cr8_1_default
# echo "✓ renesas_rdk-rzv2h-io-cr8_1_default build completed"
# echo
#
# echo "Building renesas_rdk-rzv2h-io-cm33_default..."
# echo "y" | make renesas_rdk-rzv2h-io-cm33_default
# echo "✓ renesas_rdk-rzv2h-io-cm33_default build completed"
# echo

echo "=========================================="
echo "All builds completed successfully!"
echo "=========================================="
echo
echo "Next steps:"
echo "1. Flash the firmware to your target board"
echo "2. Connect via MAVLink using QGroundControl"
echo "3. Perform calibration and configuration"
echo
echo "For flashing instructions, refer to the board documentation."
