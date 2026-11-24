#!/bin/bash
#
# Load a NuttX sample built by build.sh / build_ra8p1.sh onto the board over
# J-Link and start it. Companion of those scripts, like ../../../flash.sh is
# for ./build.sh.
#
# The image defaults to the last build, nuttx/nuttx. Its core comes from
# nuttx/.config (board + RZV2H_BUILD_* / RA_CPU_CORE_CM33). An explicit ELF
# (e.g. nuttx/nuttx-ipcc-demo-cr8_1.elf) is mapped by its entry address
# (CR8-0 DDR 0x408xxxxx, CR8-1 DDR 0x420xxxxx) or by cr8_0/cr8_1/ra8p1/ra8e1
# in its file name; --core overrides both.
#
#   cr8_0, cr8_1  RZ/V2H volatile RAM load + start through
#                 ../Debug/rzv2h-ipc/rzv2h-load-one-core.sh (no SoC reset).
#   two CR8 ELFs  CR8-0 + CR8-1 through rzv2h-ipc-demo-load-both-auto.sh.
#   rzv_cm33      refused: a J-Link connect to the RZ/V2H CM33 resets the SoC.
#   ra8p1, ra8e1  program on-chip flash, reset and run (../Debug/jlink-flash-ra8.sh).
#
# A running RTT console owns the probe, so ../Debug/rtt-console-stop.sh shuts
# it down first. RTT is not restarted: open the console manually afterwards.
#
# Exit: 0 loaded and running, 1 load failed, 2 usage / image refused.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NUTTX_DIR="${SCRIPT_DIR}/nuttx"
DEBUG_DIR="$(cd "${SCRIPT_DIR}/../Debug" && pwd)"
IPC_DIR="${DEBUG_DIR}/rzv2h-ipc"
VERBOSE_ARG=()
CORE_OVERRIDE=""

print_usage()
{
	cat <<EOF
Usage: $0 [options] [<elf> [<cr8_1-elf>]]

Load a NuttX sample onto the board with J-Link and start it. Build it first
with build.sh <config> (RZ/V2H) or build_ra8p1.sh <config> (EVK-RA8P1).

  (no ELF)              load the last build, nuttx/nuttx, on the core its
                        nuttx/.config was built for
  <elf>                 load that ELF (core from entry address or file name)
  <cr8_0-elf> <cr8_1-elf>
                        load both RZ/V2H CR8 cores (e.g. the ipcc-demo pair)

Options:
  -c, --core <core>  Force the core: cr8_0, cr8_1, ra8p1, ra8e1.
  -v, --verbose      Show J-Link / GDB output.
  -h, --help         Show this help.

Env:
  JLINK_SERIAL   Probe serial; auto-detected when exactly one J-Link is attached.

Examples:
  $0
  $0 nuttx/nuttx-ipcc-demo-cr8_0-serial.elf nuttx/nuttx-ipcc-demo-cr8_1.elf
  $0 --core ra8p1 nuttx/nuttx_ra8p1_cm85.elf
EOF
}

# Core of the last build, from nuttx/.config.
core_from_config()
{
	local cfg="${NUTTX_DIR}/.config"
	[ -f "${cfg}" ] || return 1
	if grep -q '^CONFIG_ARCH_BOARD_RDK_RZV2H=y' "${cfg}"; then
		if grep -q '^CONFIG_RZV2H_BUILD_CM33=y' "${cfg}"; then echo rzv_cm33
		elif grep -q '^CONFIG_RZV2H_BUILD_CR8_1=y' "${cfg}"; then echo cr8_1
		else echo cr8_0
		fi
	elif grep -q '^CONFIG_ARCH_BOARD_EVK_RA8P1=y' "${cfg}"; then echo ra8p1
	elif grep -q '^CONFIG_ARCH_BOARD_FPB_RA8E1=y' "${cfg}"; then echo ra8e1
	else return 1
	fi
}

# Core of an explicit ELF: CR8 DDR entry window first, then the file name.
core_from_elf()
{
	local elf="$1" entry name
	entry=$(readelf -h "${elf}" 2>/dev/null | awk '/Entry point/ {print $NF}')
	case "${entry}" in
		0x408?????|0x40[9a-f]?????) echo cr8_0; return 0 ;;
		# CR8-1 private DDR cache window 0x42000000-0x427FFFFF. 0x418xxxxx was the
		# CR8-1 entry before the private DDR moved; that range is CR8-0's now.
		0x42[0-7]?????) echo cr8_1; return 0 ;;
	esac
	name=$(basename "${elf}")
	case "${name}" in
		*cr8_1*) echo cr8_1 ;;
		*cr8_0*) echo cr8_0 ;;
		*cm33*rzv*|*rzv*cm33*) echo rzv_cm33 ;;
		*ra8p1*) echo ra8p1 ;;
		*ra8e1*) echo ra8e1 ;;
		*) return 1 ;;
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

# Free the probe from any RTT console; never restarts it.
stop_rtt_console()
{
	"${DEBUG_DIR}/rtt-console-stop.sh" || {
		echo "Could not release the probe from the RTT console." >&2
		exit 1
	}
}

ELFS=()
while [ "$#" -gt 0 ]; do
	case "$1" in
		-c|--core)
			[ "$#" -ge 2 ] || { echo "--core needs a value" >&2; exit 2; }
			CORE_OVERRIDE="$2"
			shift
			;;
		-v|--verbose) VERBOSE_ARG=(--verbose) ;;
		-h|--help) print_usage; exit 0 ;;
		-*) echo "Unknown option: $1" >&2; print_usage >&2; exit 2 ;;
		*) ELFS+=("$1") ;;
	esac
	shift
done

case "${CORE_OVERRIDE}" in
	""|cr8_0|cr8_1|ra8p1|ra8e1) ;;
	*) echo "Unknown core '${CORE_OVERRIDE}' (cr8_0, cr8_1, ra8p1, ra8e1)." >&2; exit 2 ;;
esac

if [ "${#ELFS[@]}" -gt 2 ]; then
	print_usage >&2
	exit 2
fi

# Default image: the last build, which must postdate its configure.
if [ "${#ELFS[@]}" -eq 0 ]; then
	elf="${NUTTX_DIR}/nuttx"
	if [ ! -f "${elf}" ]; then
		echo "No NuttX build at ${elf}. Run build.sh <config> first, or pass an ELF." >&2
		echo >&2
		print_usage >&2
		exit 2
	fi
	if [ "${NUTTX_DIR}/.config" -nt "${elf}" ]; then
		echo "nuttx/.config is newer than nuttx/nuttx: the tree was reconfigured after" >&2
		echo "that build. Rebuild, or pass the ELF and --core explicitly." >&2
		exit 2
	fi
	ELFS=("${elf}")
	stamp=$(cat "${NUTTX_DIR}/.config-build-sh" 2>/dev/null || echo unknown)
	echo "Image: ${elf} (config ${stamp})"
fi

# ELF paths may be relative to the caller or to this script's directory.
for i in "${!ELFS[@]}"; do
	e="${ELFS[$i]}"
	if [ ! -f "${e}" ] && [ -f "${SCRIPT_DIR}/${e}" ]; then
		ELFS[i]="${SCRIPT_DIR}/${e}"
	elif [ ! -f "${e}" ]; then
		echo "ELF not found: ${e}" >&2
		exit 2
	fi
done

if [ "${#ELFS[@]}" -eq 2 ]; then
	[ -z "${CORE_OVERRIDE}" ] || { echo "--core applies to one ELF only." >&2; exit 2; }
	k0=$(core_from_elf "${ELFS[0]}" || echo unknown)
	k1=$(core_from_elf "${ELFS[1]}" || echo unknown)
	if [ "${k0}" != cr8_0 ] || [ "${k1}" != cr8_1 ]; then
		echo "Two ELFs are only accepted as a <CR8-0 ELF> <CR8-1 ELF> pair" >&2
		echo "(detected: ${k0}, ${k1})." >&2
		exit 2
	fi
	ensure_serial
	stop_rtt_console
	echo "Loading CR8-0 ${ELFS[0]} and CR8-1 ${ELFS[1]}..."
	"${IPC_DIR}/rzv2h-ipc-demo-load-both-auto.sh" "${VERBOSE_ARG[@]}" \
		"$(realpath "${ELFS[0]}")" "$(realpath "${ELFS[1]}")" || exit 1
	echo "Console: platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 $(realpath "${ELFS[0]}")"
	exit 0
fi

elf=$(realpath "${ELFS[0]}")
if [ -n "${CORE_OVERRIDE}" ]; then
	core="${CORE_OVERRIDE}"
elif [ "${elf}" = "${NUTTX_DIR}/nuttx" ]; then
	core=$(core_from_config) || { echo "Cannot tell the board from nuttx/.config; pass --core." >&2; exit 2; }
else
	core=$(core_from_elf "${elf}") || { echo "Cannot tell the core of ${elf}; pass --core." >&2; exit 2; }
fi

case "${core}" in
	cr8_0|cr8_1)
		ensure_serial
		stop_rtt_console
		echo "Loading ${elf} into ${core} RAM and starting it..."
		"${IPC_DIR}/rzv2h-load-one-core.sh" "${VERBOSE_ARG[@]}" "${core}" "${elf}" || exit 1
		echo "Console: platforms/nuttx/Debug/nuttx-rtt-bridge.sh start ${core} ${elf}"
		;;
	ra8p1|ra8e1)
		device=R7KA8P1KF_CPU0
		[ "${core}" = ra8p1 ] || device=R7FA8E1AF
		ensure_serial
		stop_rtt_console
		"${DEBUG_DIR}/jlink-flash-ra8.sh" "${VERBOSE_ARG[@]}" "${device}" "${elf}" || exit $?
		;;
	rzv_cm33)
		echo "Refusing ${elf}: a J-Link connect to the RZ/V2H CM33 resets the SoC," >&2
		echo "and its load lifecycle is not admitted. Load a CR8 image instead." >&2
		exit 2
		;;
esac
