#!/bin/bash
#
# NuttX configure-and-build helper for the Renesas RZ/V2H board.
#
# Configures NuttX for a single rdk-rzv2h defconfig and builds it.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/nuttx"

BOARD="rdk-rzv2h"
CONFIG_DIR="boards/arm/rzv/${BOARD}/configs"

list_configs()
{
	# Each subdirectory of the board's configs/ folder is a selectable config.
	find "$CONFIG_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort
}

print_usage()
{
	cat <<EOF
Usage: $0 [--list] <config>

Configure and build NuttX for the ${BOARD} board.

Options:
  --list      List available configs and exit (builds nothing).
  -h, --help  Show this help.

<config> is one of the defconfig names under ${CONFIG_DIR}/.
Run '$0 --list' to see them, e.g.:

  $0 nsh
  $0 nsh-scif
  $0 adc

Available configs:
EOF
	list_configs | sed 's/^/  /'
}

case "${1-}" in
	--list)
		list_configs
		exit 0
		;;
	-h|--help)
		print_usage
		exit 0
		;;
	"")
		echo "Error: no config given." >&2
		echo >&2
		print_usage >&2
		exit 2
		;;
	-*)
		echo "Error: unknown option '$1'." >&2
		echo >&2
		print_usage >&2
		exit 2
		;;
esac

config="$1"

if [ ! -d "${CONFIG_DIR}/${config}" ]; then
	echo "Error: unknown config '${config}' for board '${BOARD}'." >&2
	echo "Available configs:" >&2
	list_configs | sed 's/^/  /' >&2
	exit 2
fi

# Clean up problematic symlinks/directories before distclean
rm -rf ../apps/platform/board 2>/dev/null || true

# Use a more forgiving clean approach
make distclean -j"$(nproc)" || true

# Remove any leftover arch symlinks that might cause issues
rm -f arch/arm/src/chip 2>/dev/null || true
rm -f arch/arm/src/board 2>/dev/null || true

./tools/configure.sh "${BOARD}:${config}"

make -j"$(nproc)"
