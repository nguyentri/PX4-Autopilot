#!/usr/bin/env bash
#
# PX4 Build Script for Renesas RA8 and RZV Targets
#
# Builds all Renesas PX4 board configurations found under boards/renesas.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Belt-and-braces: scrub leaked toolchain env vars (e2studio FSP env, etc.)
# that would override platforms/nuttx/cmake/Toolchain-arm-none-eabi.cmake and
# fail the CMake compiler test. Same set as build_setup.sh.
_hostile_vars=(
	CMAKE_C_COMPILER CMAKE_CXX_COMPILER CMAKE_ASM_COMPILER
	CC CXX LD AR AS NM OBJCOPY OBJDUMP STRIP RANLIB
	CFLAGS CXXFLAGS LDFLAGS ASFLAGS CPPFLAGS
)
_scrubbed=()
for _v in "${_hostile_vars[@]}"; do
	if [ -n "${!_v-}" ]; then
		_scrubbed+=("$_v")
		unset "$_v"
	fi
done
if [ "${#_scrubbed[@]}" -gt 0 ]; then
	echo "[build.sh] Unset leaked toolchain env vars: ${_scrubbed[*]}" >&2
	echo "[build.sh] Tip: source ./build_setup.sh to scrub them in your shell too." >&2
fi
unset _hostile_vars _scrubbed _v

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

Build one or more Renesas PX4 board configurations. With no target given,
every Renesas .px4board config (except backups ending in _bk) is built.

Options:
  --list      Print available Renesas targets and exit.
  --no-clean  Skip NuttX distclean before building.
  -h, --help  Show this help.

Target selection:
  A target may be given as a full PX4 make target, a board name, or any
  unambiguous shortcut. These are all resolved to a canonical make target:

    ./build.sh renesas_rdk-rzv2h_default   # full make target
    ./build.sh rdk-rzv2h                    # board name -> _default config
    ./build.sh rdk-rzv2h_dshot              # board + config
    ./build.sh dshot                        # unambiguous shortcut (if unique)

  Run './build.sh --list' to see the exact target names. If a shortcut
  matches more than one target, the script lists the candidates and exits.

Examples:
  ./build.sh --list                         # list targets, build nothing
  ./build.sh rdk-rzv2h                       # build a single board
  ./build.sh --no-clean rdk-rzv2h            # rebuild without distclean
  ./build.sh rdk-rzv2h fpb-ra8e1             # build several targets
EOF
}

# Resolve a user-supplied target (full name, board name, or shortcut) to a
# canonical PX4 make target from AVAILABLE. Prints the resolved target on
# success. On ambiguity prints "ambiguous:<t1> <t2> ..." and returns 2; on no
# match returns 1.
resolve_target()
{
	local input="$1" t matches=()

	# 1. Exact canonical make target (e.g. renesas_rdk-rzv2h_default).
	for t in "${AVAILABLE[@]}"; do
		[ "$t" = "$input" ] && { printf '%s\n' "$t"; return 0; }
	done

	# 2. Missing the renesas_ vendor prefix (e.g. rdk-rzv2h_dshot).
	for t in "${AVAILABLE[@]}"; do
		[ "$t" = "renesas_$input" ] && { printf '%s\n' "$t"; return 0; }
	done

	# 3. Board name shorthand -> its _default config (e.g. rdk-rzv2h).
	for t in "${AVAILABLE[@]}"; do
		[ "$t" = "renesas_${input}_default" ] && { printf '%s\n' "$t"; return 0; }
	done

	# 4. Fuzzy: any target containing the input; accept only if unique.
	for t in "${AVAILABLE[@]}"; do
		case "$t" in
			*"$input"*) matches+=("$t") ;;
		esac
	done
	if [ "${#matches[@]}" -eq 1 ]; then
		printf '%s\n' "${matches[0]}"
		return 0
	fi
	if [ "${#matches[@]}" -gt 1 ]; then
		printf 'ambiguous:%s\n' "${matches[*]}"
		return 2
	fi

	return 1
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

mapfile -t AVAILABLE < <(collect_renesas_targets)

if [ "${#AVAILABLE[@]}" -eq 0 ]; then
	echo "No Renesas targets found." >&2
	exit 1
fi

if [ "$LIST_ONLY" -eq 1 ]; then
	printf '%s\n' "${AVAILABLE[@]}"
	exit 0
fi

if [ "${#TARGETS[@]}" -eq 0 ]; then
	# No explicit target: build everything.
	TARGETS=("${AVAILABLE[@]}")
else
	# Resolve each requested target (full name, board name, or shortcut) to a
	# canonical make target before building, so nothing is cleaned or built
	# until every target is known-good.
	RESOLVED=()
	for want in "${TARGETS[@]}"; do
		if match="$(resolve_target "$want")"; then
			RESOLVED+=("$match")
		elif [ "${match#ambiguous:}" != "$match" ]; then
			echo "Target '$want' is ambiguous. Candidates:" >&2
			printf '  %s\n' ${match#ambiguous:} >&2
			echo "Re-run with a more specific name (see './build.sh --list')." >&2
			exit 2
		else
			echo "Unknown target: '$want'" >&2
			echo "Available targets:" >&2
			printf '  %s\n' "${AVAILABLE[@]}" >&2
			exit 2
		fi
	done
	TARGETS=("${RESOLVED[@]}")
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
