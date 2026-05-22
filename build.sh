#!/usr/bin/env bash
#
# PX4 Build Script for Renesas RA8 and RZV Targets
#
# Builds all Renesas PX4 board configurations found under boards/renesas.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export GIT_SUBMODULES_ARE_EVIL=1

clean_nuttx_artifacts()
{
	echo "Cleaning NuttX build artifacts..."
	make -C platforms/nuttx/NuttX/nuttx distclean
	echo "NuttX artifacts cleaned."
	echo
}

collect_renesas_targets()
{
	find boards/renesas -maxdepth 2 -name '*.px4board' ! -name '*_bk.px4board' -print \
		| sed -e 's|^boards/||' -e 's|\.px4board$||' -e 's|/|_|g' \
		| sort
}

print_usage()
{
	cat <<'EOF'
Usage: ./build.sh [options] [target ...]

Options:
  --list      Print Renesas targets and exit.
  --no-clean  Skip NuttX distclean before building.
  -h, --help  Show this help.

With no targets, the script builds every Renesas .px4board target except
backup configs ending in _bk.
EOF
}

DO_CLEAN=1
LIST_ONLY=0
TARGETS=()

while [ "$#" -gt 0 ]; do
	case "$1" in
		--list)
			LIST_ONLY=1
			;;
		--no-clean)
			DO_CLEAN=0
			;;
		-h|--help)
			print_usage
			exit 0
			;;
		-*)
			echo "Unknown option: $1" >&2
			print_usage >&2
			exit 2
			;;
		*)
			TARGETS+=("$1")
			;;
	esac

	shift
done

if [ "${#TARGETS[@]}" -eq 0 ]; then
	mapfile -t TARGETS < <(collect_renesas_targets)
fi

if [ "${#TARGETS[@]}" -eq 0 ]; then
	echo "No Renesas targets found." >&2
	exit 1
fi

if [ "$LIST_ONLY" -eq 1 ]; then
	printf '%s\n' "${TARGETS[@]}"
	exit 0
fi

echo "=========================================="
echo "PX4 Build Script for Renesas RA8/RZV Targets"
echo "=========================================="
echo

echo "Building PX4 for Renesas targets..."
printf '  %s\n' "${TARGETS[@]}"
echo

for target in "${TARGETS[@]}"; do
	if [ "$DO_CLEAN" -eq 1 ]; then
		clean_nuttx_artifacts
	fi

	echo "Building ${target}..."
	make "$target"
	echo "OK: ${target} build completed"
	echo
done

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
