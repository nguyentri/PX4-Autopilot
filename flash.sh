#!/bin/bash
#
# Load a built Renesas PX4 image onto the board over J-Link and start it.
#
# Companion of ./build.sh: takes the same target names and uses the ELF in
# build/<target>/<target>.elf. What "flash" means depends on the target:
#
#   rdk-rzv2h_*            CR8-0, volatile RAM load + start at __start through
#                          rzv2h-load-one-core.sh (no SoC reset; a reset would
#                          wipe the RAM image).
#   rdk-rzv2h-io-cr8_1_*   CR8-1, same RAM loader.
#   CR8-0 + CR8-1 pair     both cores through rzv2h-ipc-demo-load-both-auto.sh
#                          (CR8-0 first, CR8-1 last, then both verified).
#   rdk-rzv2h-io-cm33_*    refused: a J-Link connect to the CM33 resets the SoC.
#
# Every RZ/V2H CR8 image first passes the PT_LOAD address allowlist
# (platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py, the same check the managed
# loader runs); an image it rejects, such as a CR8-1 image linked into the boot
# firmware window, is refused before the probe is touched. The loader gets a
# private copy of the checked ELF, so a rebuild during the load cannot swap it.
#   evk-ra8p1*, fpb-ra8e1* program on-chip flash from the ELF with JLinkExe,
#                          then reset and run.
#
# Any running RTT console owns the probe, so platforms/nuttx/Debug/
# rtt-console-stop.sh shuts it down before loading. RTT is not restarted:
# open the console manually afterwards.
#
# Exit: 0 loaded and running, 1 load failed, 2 usage / target refused.

set -euo pipefail

cd "$(dirname "$0")"
ROOT=$(pwd)
DEBUG_DIR="${ROOT}/platforms/nuttx/Debug"
IPC_DIR="${DEBUG_DIR}/rzv2h-ipc"
ALLOWLIST="${DEBUG_DIR}/rzv2h-ipc-elf-allowlist.py"
VERBOSE_ARG=()

print_usage()
{
	cat <<'EOF'
Usage: ./flash.sh [options] <target> [<cr8_1-target>]

Load the built image of a Renesas PX4 target onto the board with J-Link and
start it. Build it first with ./build.sh <target>.

Options:
  --list         Print targets that have a built ELF and exit.
  --resolve      Print the built target each name resolves to and exit
                 (no probe access; used by ./flash_dual.sh).
  -v, --verbose  Show J-Link / GDB output.
  -h, --help     Show this help.

Targets (same names as ./build.sh; a build/ prefix is also accepted):
  renesas_rdk-rzv2h_<cfg>            CR8-0 RAM load + start
  renesas_rdk-rzv2h-io-cr8_1_<cfg>   CR8-1 RAM load + start
  <CR8-0 target> <CR8-1 target>      load both cores (e.g. dualcr8 + io-cr8_1_default)
  renesas_evk-ra8p1*, fpb-ra8e1*     flash program, reset, run
  renesas_rdk-rzv2h-io-cm33_*        refused (connecting the CM33 resets the SoC)

Env:
  JLINK_SERIAL   Probe serial; auto-detected when exactly one J-Link is attached.

Examples:
  ./flash.sh renesas_rdk-rzv2h_default
  ./flash.sh rdk-rzv2h_dualcr8 rdk-rzv2h-io-cr8_1_default
  ./flash.sh build/renesas_evk-ra8p1_default
EOF
}

# Targets that have a built ELF, one per line.
collect_built_targets()
{
	local d name
	for d in build/renesas_*/; do
		name=$(basename "$d")
		[ -f "build/${name}/${name}.elf" ] && printf '%s\n' "$name"
	done
	return 0
}

print_targets()
{
	if [ "${#AVAILABLE[@]}" -eq 0 ]; then
		echo "No built Renesas targets under build/. Run ./build.sh <target> first."
	else
		printf '  %s\n' "${AVAILABLE[@]}"
	fi
}

# Resolve a user-supplied name to a built target: exact name, build/ prefix,
# missing renesas_ prefix, board name -> _default, a unique _<config> suffix,
# or a unique substring.
resolve_target()
{
	local input="${1#build/}" t matches=()
	input="${input%/}"

	for t in "${AVAILABLE[@]}"; do
		case "$t" in
			"$input"|"renesas_$input"|"renesas_${input}_default") printf '%s\n' "$t"; return 0 ;;
		esac
	done
	# Config shortcut (e.g. dualcr8): prefer targets ending in _<input>.
	for t in "${AVAILABLE[@]}"; do
		case "$t" in *"_$input") matches+=("$t") ;; esac
	done
	if [ "${#matches[@]}" -eq 0 ]; then
		for t in "${AVAILABLE[@]}"; do
			case "$t" in *"$input"*) matches+=("$t") ;; esac
		done
	fi
	if [ "${#matches[@]}" -eq 1 ]; then
		printf '%s\n' "${matches[0]}"
		return 0
	fi
	if [ "${#matches[@]}" -gt 1 ]; then
		echo "Target '$1' is ambiguous. Candidates:" >&2
		printf '  %s\n' "${matches[@]}" >&2
	else
		echo "No built target matches '$1'. Built targets:" >&2
		print_targets >&2
	fi
	return 1
}

# Map a target to the core it runs on.
target_kind()
{
	case "$1" in
		renesas_rdk-rzv2h-io-cm33_*) echo rzv_cm33 ;;
		renesas_rdk-rzv2h-io-cr8_1_*) echo cr8_1 ;;
		renesas_rdk-rzv2h_*) echo cr8_0 ;;
		renesas_evk-ra8p1*) echo ra8p1 ;;
		renesas_fpb-ra8e1*) echo ra8e1 ;;
		*) echo unknown ;;
	esac
}

ensure_serial()
{
	if [ -z "${JLINK_SERIAL:-}" ]; then
		if ! JLINK_SERIAL=$(python3 "${DEBUG_DIR}/jlink-debug-preflight.py" --print-serial); then
			echo "Set JLINK_SERIAL: auto-detect needs exactly one attached J-Link." >&2
			exit 2
		fi
	fi
	export JLINK_SERIAL
}

# An RTT console holds the probe; loading needs it free. RTT is never
# restarted here: the user opens the console manually after the load.
stop_rtt_bridge()
{
	"${DEBUG_DIR}/rtt-console-stop.sh" || {
		echo "Could not release the probe from the RTT console." >&2
		exit 1
	}
}

# Copy a CR8 ELF to a private snapshot, run the address allowlist on that copy
# and print its path. Exits 2 when the checker is missing or rejects the image.
SNAPSHOT_DIR=""
admit_rzv_elf()
{
	local core="$1" target="$2" device copy digest report
	case "$core" in
		cr8_0) device=R9A09G057H44_R8_0 ;;
		cr8_1) device=R9A09G057H44_R8_1 ;;
		*) echo "No address allowlist for core ${core}." >&2; exit 2 ;;
	esac
	if [ ! -f "${ALLOWLIST}" ]; then
		echo "Refusing ${target}: the ELF address allowlist ${ALLOWLIST} is missing." >&2
		exit 2
	fi
	copy="${SNAPSHOT_DIR}/${target}/${target}.elf"
	mkdir -p "${copy%/*}"
	cp "$(elf_of "$target")" "$copy"
	digest=$(sha256sum "$copy" | cut -d' ' -f1)
	if ! report=$(python3 "${ALLOWLIST}" --elf "$copy" --device "$device" \
			--expect-sha256 "$digest" 2>&1) ||
		! grep -qx 'RESULT=ADDRESS_CONTRACT_VERIFIED' <<<"$report"; then
		printf '%s\n' "$report" >&2
		echo "Refusing ${target}: its load addresses are not allowed on ${core}. Rebuild it with ./build.sh ${target}." >&2
		exit 2
	fi
	printf '%s\n' "$copy"
}

# RA8: program flash from the ELF, then reset and run (shared helper).
flash_ra8()
{
	"${DEBUG_DIR}/jlink-flash-ra8.sh" "${VERBOSE_ARG[@]}" "$1" "$2" || exit $?
}

TARGET_ARGS=()
LIST_ONLY=0
RESOLVE_ONLY=0
while [ "$#" -gt 0 ]; do
	case "$1" in
		--list) LIST_ONLY=1 ;;
		--resolve) RESOLVE_ONLY=1 ;;
		-v|--verbose) VERBOSE_ARG=(--verbose) ;;
		-h|--help) print_usage; exit 0 ;;
		-*) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
		*) TARGET_ARGS+=("$1") ;;
	esac
	shift
done

mapfile -t AVAILABLE < <(collect_built_targets)

if [ "$LIST_ONLY" -eq 1 ]; then
	print_targets
	exit 0
fi

if [ "${#TARGET_ARGS[@]}" -eq 0 ] || [ "${#TARGET_ARGS[@]}" -gt 2 ]; then
	print_usage >&2
	echo >&2
	echo "Built targets:" >&2
	print_targets >&2
	exit 2
fi

TARGETS=()
for want in "${TARGET_ARGS[@]}"; do
	t=$(resolve_target "$want") || exit 2
	TARGETS+=("$t")
done

if [ "$RESOLVE_ONLY" -eq 1 ]; then
	printf '%s\n' "${TARGETS[@]}"
	exit 0
fi

KINDS=()
for t in "${TARGETS[@]}"; do
	KINDS+=("$(target_kind "$t")")
done

elf_of() { printf '%s/build/%s/%s.elf\n' "$ROOT" "$1" "$1"; }

case "${KINDS[*]}" in
	*cr8_0*|*cr8_1*)
		SNAPSHOT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/flash-rzv2h.XXXXXX")
		trap 'rm -rf "$SNAPSHOT_DIR"' EXIT
		;;
esac

if [ "${#TARGETS[@]}" -eq 2 ]; then
	if [ "${KINDS[0]}" != cr8_0 ] || [ "${KINDS[1]}" != cr8_1 ]; then
		echo "Two targets are only accepted as a <CR8-0 target> <CR8-1 target> pair." >&2
		exit 2
	fi
	cr8_0_elf=$(admit_rzv_elf cr8_0 "${TARGETS[0]}") || exit 2
	cr8_1_elf=$(admit_rzv_elf cr8_1 "${TARGETS[1]}") || exit 2
	ensure_serial
	stop_rtt_bridge
	echo "Loading CR8-0 ${TARGETS[0]} and CR8-1 ${TARGETS[1]}..."
	"${IPC_DIR}/rzv2h-ipc-demo-load-both-auto.sh" "${VERBOSE_ARG[@]}" \
		"$cr8_0_elf" "$cr8_1_elf" || exit 1
	echo "Console: platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 $(elf_of "${TARGETS[0]}")"
	exit 0
fi

target="${TARGETS[0]}"
elf=$(elf_of "$target")
case "${KINDS[0]}" in
	cr8_0|cr8_1)
		admitted=$(admit_rzv_elf "${KINDS[0]}" "$target") || exit 2
		ensure_serial
		stop_rtt_bridge
		echo "Loading ${target} into ${KINDS[0]} RAM and starting it..."
		"${IPC_DIR}/rzv2h-load-one-core.sh" "${VERBOSE_ARG[@]}" "${KINDS[0]}" "$admitted" || exit 1
		if [ "${KINDS[0]}" = cr8_0 ]; then
			echo "Note: a dual-core profile (e.g. dualcr8) also needs its CR8-1 image; ./flash_dual.sh loads the pair."
		fi
		echo "Console: platforms/nuttx/Debug/nuttx-rtt-bridge.sh start ${KINDS[0]} ${elf}"
		;;
	ra8p1)
		ensure_serial
		stop_rtt_bridge
		flash_ra8 R7KA8P1KF_CPU0 "$elf"
		;;
	ra8e1)
		ensure_serial
		stop_rtt_bridge
		flash_ra8 R7FA8E1AF "$elf"
		;;
	rzv_cm33)
		echo "Refusing ${target}: a J-Link connect to the RZ/V2H CM33 resets the SoC," >&2
		echo "and its load lifecycle is not admitted. Load a CR8 target instead." >&2
		exit 2
		;;
	*)
		echo "Don't know how to load ${target}." >&2
		exit 2
		;;
esac
