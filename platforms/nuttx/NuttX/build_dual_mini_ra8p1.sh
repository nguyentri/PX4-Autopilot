#!/bin/bash
set -e

cd ./nuttx

echo "========================================="
echo "Building CM33 (Core 1) configuration with mini CM85 startup"
echo "========================================="

# Clean up
echo "Cleaning workspace..."
rm -rf ../apps/platform/board 2>/dev/null || true
make distclean -j$(nproc) || true
rm -f arch/arm/src/chip arch/arm/src/board 2>/dev/null || true

# Build CM85 configuration
echo ""
echo "========================================="
echo "Building CM85 (Core 0) configuration..."
echo "========================================="
./tools/configure.sh evk-ra8p1:mini-cm85
make -j$(nproc)

# Save CM85 binaries
echo "Saving CM85 binaries..."
cp nuttx nuttx_ra8p1_cm85.elf
cp nuttx.hex nuttx_ra8p1_cm85.hex
cp nuttx.bin nuttx_ra8p1_cm85.bin
echo "  ✓ nuttx_ra8p1_cm85.elf"
echo "  ✓ nuttx_ra8p1_cm85.hex"
echo "  ✓ nuttx_ra8p1_cm85.bin"

# Clean for next build
echo "Cleaning for CM33 build..."
make distclean -j$(nproc) || true
rm -f arch/arm/src/chip arch/arm/src/board 2>/dev/null || true

# Build CM33 configuration
echo ""
echo "========================================="
echo "Building CM33 (Core 1) configuration..."
echo "========================================="
./tools/configure.sh evk-ra8p1:nsh-cm33
make -j$(nproc)

# Save CM33 binaries
echo "Saving CM33 binaries..."
cp nuttx nuttx_ra8p1_cm33.elf
cp nuttx.hex nuttx_ra8p1_cm33.hex
cp nuttx.bin nuttx_ra8p1_cm33.bin
echo "  ✓ nuttx_ra8p1_cm33.elf"
echo "  ✓ nuttx_ra8p1_cm33.hex"
echo "  ✓ nuttx_ra8p1_cm33.bin"

echo ""
echo "========================================="
echo "Build complete! Binaries created:"
echo "========================================="
echo "CM85 (Core 0 - Primary):"
echo "  - nuttx_ra8p1_cm85.elf"
echo "  - nuttx_ra8p1_cm85.hex"
echo "  - nuttx_ra8p1_cm85.bin"
echo ""
echo "CM33 (Core 1 - Secondary):"
echo "  - nuttx_ra8p1_cm33.elf"
echo "  - nuttx_ra8p1_cm33.hex"
echo "  - nuttx_ra8p1_cm33.bin"
echo ""
echo "Flash CM85 binary to address 0x02000000"
echo "Flash CM33 binary to address 0x020E8000"
echo "========================================="
