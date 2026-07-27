#!/bin/bash
set -e

cd ./nuttx

config="${1:?Usage: $0 <rdk-rzv2h-config>}"

# Clean up problematic symlinks/directories before distclean
rm -rf ../apps/platform/board 2>/dev/null || true

# Use a more forgiving clean approach
make distclean -j$(nproc) || true

# Remove any leftover arch symlinks that might cause issues
rm -f arch/arm/src/chip 2>/dev/null || true
rm -f arch/arm/src/board 2>/dev/null || true

./tools/configure.sh "rdk-rzv2h:${config}"
# If Make.defs is missing, manually remove .config and reconfigure (can't use -E since make needs Make.defs)
#if [ ! -r Make.defs ]; then
#  echo "Make.defs missing: removing .config and reconfiguring"
#  rm -f .config defconfig
#  ./tools/configure.sh rdk-rzv2h:nsh
#else
#  ./tools/configure.sh rdk-rzv2h:nsh
#fi

make -j$(nproc)
