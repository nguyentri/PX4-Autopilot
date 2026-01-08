#!/bin/bash
#
# Flash both CM85 and CM33 firmware to RA8P1 board using J-Link
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JLINK_CMD="/opt/SEGGER/JLink/JLinkExe"
JLINK_SCRIPT="${SCRIPT_DIR}/f.jlink"

CM85_ELF="${SCRIPT_DIR}/build/renesas_evk-ra8p1_default/renesas_evk-ra8p1_default.elf"
CM33_ELF="${SCRIPT_DIR}/build/renesas_evk-ra8p1-io-cm33_default/renesas_evk-ra8p1-io-cm33_default.elf"

# Check if ELF files exist
if [ ! -f "$CM85_ELF" ]; then
    echo "Error: CM85 firmware not found: $CM85_ELF"
    echo "Run: make renesas_evk-ra8p1_default"
    exit 1
fi

if [ ! -f "$CM33_ELF" ]; then
    echo "Error: CM33 firmware not found: $CM33_ELF"
    echo "Run: make renesas_evk-ra8p1-io-cm33_default"
    exit 1
fi

# Check if J-Link is available
if [ ! -x "$JLINK_CMD" ]; then
    echo "Error: J-Link not found at $JLINK_CMD"
    exit 1
fi

echo "==========================================="
echo "Flashing RA8P1 Dual-Core Firmware"
echo "==========================================="
echo "CM85 (Core0): $CM85_ELF"
echo "CM33 (Core1): $CM33_ELF"
echo "==========================================="

# Execute J-Link script
"$JLINK_CMD" -CommandFile "$JLINK_SCRIPT"

echo "==========================================="
echo "Flash completed successfully!"
echo "==========================================="
