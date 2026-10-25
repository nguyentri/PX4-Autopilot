#!/bin/bash
#
# NuttX configure-and-build helper for the Renesas RZ/V2H board.
#
# Configures NuttX for a single rdk-rzv2h defconfig and builds it.
#
# Typical use (from anywhere; the script cds to its own directory):
#   platforms/nuttx/NuttX/build.sh --list            # list configs
#   platforms/nuttx/NuttX/build.sh nsh-rtt           # clean configure + build
#   platforms/nuttx/NuttX/build.sh --no-clean nsh-rtt  # incremental rebuild
#
# Outputs land in platforms/nuttx/NuttX/nuttx/: nuttx (ELF), nuttx.bin,
# nuttx.hex, System.map. Exit status: 0 ok, 1 build failed, 2 bad usage.
set -e

BUILD_JOBS="${NUTTX_BUILD_JOBS:-$(nproc)}"
case "$BUILD_JOBS" in
''|*[!0-9]*|0) echo "NUTTX_BUILD_JOBS must be a positive integer" >&2; exit 2 ;;
esac

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
Usage: $0 [--list] [--no-clean] <config>

Configure and build NuttX for the ${BOARD} board.

Options:
  -l, --list      List available configs and exit (builds nothing).
  -n, --no-clean  Skip distclean/configure; rebuild incrementally. Only valid
                  if <config> is the config already configured by this script.
  -h, --help      Show this help.

Outputs: ${SCRIPT_DIR}/nuttx/{nuttx,nuttx.bin,nuttx.hex,System.map}

<config> is one of the defconfig names under ${CONFIG_DIR}/.
Run '$0 --list' to see them, e.g.:

  $0 nsh
  $0 nsh-scif
  $0 adc

Available configs:
EOF
	list_configs | sed 's/^/  /'
}

no_clean=0
while [ $# -gt 0 ]; do
	case "$1" in
		-l|-list|--list)
			list_configs
			exit 0
			;;
		-h|-help|--help)
			print_usage
			exit 0
			;;
		-n|--no-clean)
			no_clean=1
			shift
			;;
		-*)
			echo "Error: unknown option '$1'." >&2
			echo >&2
			print_usage >&2
			exit 2
			;;
		*)
			break
			;;
	esac
done

if [ $# -ne 1 ]; then
	echo "Error: expected exactly one config, got $#." >&2
	echo >&2
	print_usage >&2
	exit 2
fi

config="$1"

if [ ! -d "${CONFIG_DIR}/${config}" ]; then
	echo "Error: unknown config '${config}' for board '${BOARD}'." >&2
	echo "Available configs:" >&2
	list_configs | sed 's/^/  /' >&2
	exit 2
fi

# Serialize the entire build with a verified inherited kernel lock.
LOCK_HELPER="${SCRIPT_DIR}/../../../Tools/firmware_workspace/build_lock.sh"
[ -x "$LOCK_HELPER" ] || { echo "Missing shared build lock helper: $LOCK_HELPER" >&2; exit 2; }
if ! "$LOCK_HELPER" --check; then
  exec "$LOCK_HELPER" "$0" "$@"
fi

# Records which config the tree was last configured with, so --no-clean can
# refuse to rebuild a tree configured for something else.
STAMP=".config-build-sh"  # matched by nuttx .gitignore (/.config-*)

if [ "$no_clean" -eq 1 ]; then
	current="$(cat "$STAMP" 2>/dev/null || true)"
	if [ ! -f .config ] || [ "$current" != "${BOARD}:${config}" ]; then
		echo "Error: --no-clean needs a tree configured for '${BOARD}:${config}'" >&2
		echo "       (currently: '${current:-none}'). Run without --no-clean first." >&2
		exit 2
	fi
else
	# Clean up problematic symlinks/directories before distclean
	rm -rf ../apps/platform/board 2>/dev/null || true

	# Use a more forgiving clean approach
	make distclean -j"${BUILD_JOBS}" || true

	# Remove any leftover arch symlinks that might cause issues
	rm -f arch/arm/src/chip 2>/dev/null || true
	rm -f arch/arm/src/board 2>/dev/null || true
	rm -f "$STAMP"

	./tools/configure.sh "${BOARD}:${config}"
	echo "${BOARD}:${config}" > "$STAMP"
fi

if ! make -j"${BUILD_JOBS}"; then
	echo "Error: build of '${BOARD}:${config}' failed." >&2
	exit 1
fi

echo
echo "Built ${BOARD}:${config}. Outputs:"
for f in nuttx nuttx.bin nuttx.hex System.map; do
	if [ -f "$f" ]; then echo "  $(pwd)/$f"; fi
done
