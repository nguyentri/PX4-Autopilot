#!/bin/bash
#
# Load a CR8-0 + CR8-1 PX4 image pair into RZ/V2H RAM over J-Link and start
# both cores.
#
# Companion of ./flash.sh for dual-core profiles. Name the CR8-0 target and
# its CR8-1 partner is taken from DEFAULT_PAIRS below, or name both targets.
# The load itself is `./flash.sh <cr8_0-target> <cr8_1-target>`: it stops any
# RTT console holding the probe, then rzv2h-ipc-demo-load-both-auto.sh loads
# CR8-0 first and CR8-1 last and verifies that both cores run. Both images are
# volatile RAM loads (no SoC reset; a reset would wipe them).
#
# Loading a pair is mechanical only; it does not qualify an actuator pair.
#
# Exit: 0 both cores loaded and running, 1 load failed, 2 usage / target refused.

set -euo pipefail

cd "$(dirname "$0")"
ROOT=$(pwd)
FLASH="${ROOT}/flash.sh"
VERBOSE_ARG=()

# CR8-0 target and the CR8-1 image it is paired with when only the CR8-0
# target is named. demo and demosih run the heartbeat initiator and pair with
# the heartbeat responder; dualcr8 pairs with the PWM supervisor candidate.
DEFAULT_PAIRS=(
	"renesas_rdk-rzv2h_demo renesas_rdk-rzv2h-io-cr8_1_demo"
	"renesas_rdk-rzv2h_demosih renesas_rdk-rzv2h-io-cr8_1_demo"
	"renesas_rdk-rzv2h_dualcr8 renesas_rdk-rzv2h-io-cr8_1_default"
)

print_usage()
{
	cat <<'USAGE'
Usage: ./flash_dual.sh [options] <cr8_0-target> [<cr8_1-target>]

Load a CR8-0 + CR8-1 image pair into RZ/V2H RAM with J-Link and start both
cores. Build both targets first with ./build.sh <target>.

With only the CR8-0 target, its default CR8-1 partner is used (see --list).
Target names are those of ./build.sh and ./flash.sh, including its shortcuts;
a bare config name is also accepted for each core (demosih, demo).

Options:
  --list         Print the default pairs, the built CR8-1 targets and exit.
  -v, --verbose  Show J-Link / GDB output.
  -h, --help     Show this help.

Env:
  JLINK_SERIAL   Probe serial; auto-detected when exactly one J-Link is attached.

Examples:
  ./flash_dual.sh demosih                                 # + io-cr8_1_demo
  ./flash_dual.sh renesas_rdk-rzv2h_dualcr8               # + io-cr8_1_default
  ./flash_dual.sh rdk-rzv2h_dualcr8 rdk-rzv2h-io-cr8_1_demo
USAGE
}

has_elf() { [ -f "build/$1/$1.elf" ]; }

# Default CR8-1 partner of a resolved CR8-0 target; fails when there is none.
default_partner()
{
	local pair
	for pair in "${DEFAULT_PAIRS[@]}"; do
		if [ "${pair%% *}" = "$1" ]; then
			printf '%s\n' "${pair##* }"
			return 0
		fi
	done
	return 1
}

print_built_cr8_1()
{
	local found=0 d name
	for d in build/renesas_rdk-rzv2h-io-cr8_1_*/; do
		name=$(basename "$d")
		has_elf "$name" || continue
		printf '  %s\n' "$name"
		found=1
	done
	[ "$found" -eq 1 ] || echo "  (none; run ./build.sh renesas_rdk-rzv2h-io-cr8_1_<cfg>)"
}

print_pairs()
{
	local pair t state
	echo "Default pairs (CR8-0 target + CR8-1 partner):"
	for pair in "${DEFAULT_PAIRS[@]}"; do
		state="built"
		for t in $pair; do
			has_elf "$t" || state="not built: ${t}"
		done
		printf '  %-28s + %-34s [%s]\n' "${pair%% *}" "${pair##* }" "$state"
	done
	echo "Built CR8-1 targets:"
	print_built_cr8_1
}

TARGET_ARGS=()
LIST_ONLY=0
while [ "$#" -gt 0 ]; do
	case "$1" in
		--list) LIST_ONLY=1 ;;
		-v|--verbose) VERBOSE_ARG=(--verbose) ;;
		-h|--help) print_usage; exit 0 ;;
		-*) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
		*) TARGET_ARGS+=("$1") ;;
	esac
	shift
done

if [ "$LIST_ONLY" -eq 1 ]; then
	print_pairs
	exit 0
fi

if [ "${#TARGET_ARGS[@]}" -eq 0 ] || [ "${#TARGET_ARGS[@]}" -gt 2 ]; then
	print_usage >&2
	echo >&2
	print_pairs >&2
	exit 2
fi

# flash.sh owns target-name resolution, so both scripts accept the same
# shortcuts. Each argument position names one core here, so a bare config
# name (demo, default) is tried on that core's board first; without that, "demo"
# would be ambiguous between the CR8-0 and CR8-1 demo targets.
resolve_on_board()
{
	"$FLASH" --resolve "$1_$2" 2>/dev/null || "$FLASH" --resolve "$2"
}

cr8_0=$(resolve_on_board rdk-rzv2h "${TARGET_ARGS[0]}") || exit 2
case "$cr8_0" in
	renesas_rdk-rzv2h_*) ;;
	*)
		echo "'${cr8_0}' is not a CR8-0 target; the first target must be renesas_rdk-rzv2h_<cfg>." >&2
		exit 2
		;;
esac

if [ "${#TARGET_ARGS[@]}" -eq 2 ]; then
	cr8_1=$(resolve_on_board rdk-rzv2h-io-cr8_1 "${TARGET_ARGS[1]}") || exit 2
else
	if ! cr8_1=$(default_partner "$cr8_0"); then
		echo "${cr8_0} has no default CR8-1 partner; name the CR8-1 target too." >&2
		echo "Built CR8-1 targets:" >&2
		print_built_cr8_1 >&2
		exit 2
	fi
	if ! has_elf "$cr8_1"; then
		echo "CR8-1 partner ${cr8_1} is not built. Run ./build.sh ${cr8_1} first." >&2
		exit 2
	fi
fi

# flash.sh checks that the pair is CR8-0 + CR8-1, releases the probe from any
# RTT console and runs the guarded pair loader, which prints the console
# commands for both cores.
exec "$FLASH" "${VERBOSE_ARG[@]}" "$cr8_0" "$cr8_1"
