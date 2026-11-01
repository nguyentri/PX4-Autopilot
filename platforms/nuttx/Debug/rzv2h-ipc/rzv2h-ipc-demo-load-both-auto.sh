#!/bin/sh
#
# Silent, self-verifying single-probe loader for the RZ/V2H IPC demo.
#
# Same volatile RAM load as rzv2h-ipc-demo-load-both.sh (CR8-0 image first,
# CR8-1 image last), but hardened for unattended use. Works for any CR8 pair:
# the NuttX IPC demo (serial or RTT CR8-0 console) or PX4 dualcr8 + io-cr8_1:
#   * preflight refuses an occupied GDB port; release its existing owner
#     before loading and keep one probe owner at a time;
#   * one guarded connect per operation; failure ends the batch;
#   * server + gdb chatter is captured to per-core logs, so the console shows
#     only step and PASS/FAIL lines (pass --verbose to tee the logs);
#   * after both loads, each core is re-attached, halted, PC-checked and
#     resumed (non-destructive) to prove the image is actually running.
#
# Exit status is 0 only if BOTH cores load and verify; non-zero otherwise, so
# it is safe to chain in a build+load pipeline.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-auto.sh <cr8_0-elf> <cr8_1-elf>
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-auto.sh --verbose <elf0> <elf1>
#
# Env:
#   JLINK_SERIAL   Authorized probe serial (required).
#   JLINK_GDB      JLinkGDBServerCLExe path (default: PATH then /opt/SEGGER).
#   GDB            gdb-multiarch path (default: PATH).
#   GDB_PORT       GDB server port (default 50000).
#   LOG_DIR        Where per-core logs go (default: <script dir>/logs).

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=rzv2h-ipc-demo-jlink-lib.sh
. "${HERE}/rzv2h-ipc-demo-jlink-lib.sh"
trap '_stop_server' EXIT
trap '_stop_server; exit 130' INT
trap '_stop_server; exit 143' HUP TERM

LOADSTART="${HERE}/rzv2h-ipc-hil-loadstart.gdb"
VERIFY="${HERE}/rzv2h-ipc-hil-verify-resume.gdb"
GDB_PORT="${GDB_PORT:-50000}"
LOG_DIR="${LOG_DIR:-${HERE}/logs}"
VERBOSE=0
export VERBOSE

DEV_CR8_0="R9A09G057H44_R8_0"
DEV_CR8_1="R9A09G057H44_R8_1"

# --- args -------------------------------------------------------------------
if [ "${1:-}" = "--verbose" ] || [ "${1:-}" = "-v" ]; then
	VERBOSE=1; shift
fi
CR8_0_ELF="${1:-}"
CR8_1_ELF="${2:-}"

if [ -z "${CR8_0_ELF}" ] || [ -z "${CR8_1_ELF}" ]; then
	echo "usage: JLINK_SERIAL=<probe-sn> $0 [--verbose] <cr8_0-elf> <cr8_1-elf>" >&2
	exit 2
fi
if [ -z "${JLINK_SERIAL:-}" ]; then
	echo "JLINK_SERIAL must identify the authorized probe" >&2
	exit 2
fi
for f in "${CR8_0_ELF}" "${CR8_1_ELF}" "${LOADSTART}" "${VERIFY}"; do
	[ -f "${f}" ] || { echo "not found: ${f}" >&2; exit 2; }
done

resolve_tools || exit 2
mkdir -p "${LOG_DIR}"

# --- load: initiator first so the responder adopts its recovery epoch -------
run_step() {
	step_core="$1"; step_phase="$2"; shift 2
	if [ "${FIRMWARE_WORKSPACE_STEPS:-0}" = 1 ]; then
		echo "PX4_WORKSPACE_STEP ${step_core} ${step_phase} begin" >&2
	fi
	if "$@"; then
		if [ "${FIRMWARE_WORKSPACE_STEPS:-0}" = 1 ]; then
			echo "PX4_WORKSPACE_STEP ${step_core} ${step_phase} ok" >&2
		fi
	else
		if [ "${FIRMWARE_WORKSPACE_STEPS:-0}" = 1 ]; then
			echo "PX4_WORKSPACE_STEP ${step_core} ${step_phase} fail" >&2
		fi
		return 1
	fi
}
run_step cr8_0 load load_core "${DEV_CR8_0}" "${CR8_0_ELF}" "CR8-0" || exit 1
run_step cr8_1 load load_core "${DEV_CR8_1}" "${CR8_1_ELF}" "CR8-1" || exit 1

# --- verify both are actually running ---------------------------------------
run_step cr8_0 verify verify_core "${DEV_CR8_0}" "${CR8_0_ELF}" "CR8-0" || exit 1
run_step cr8_1 verify verify_core "${DEV_CR8_1}" "${CR8_1_ELF}" "CR8-1" || exit 1

# Suggest an RTT bridge only for an image that has an RTT control block.
has_rtt() {
	nm_bin=$(command -v "${NM:-arm-none-eabi-nm}") || return 0
	"${nm_bin}" "$1" 2>/dev/null | grep -q ' _SEGGER_RTT$'
}

echo
echo "Both images resident, running, and verified; the probe is free."
echo "Open a console (one RTT bridge at a time; it takes the probe):"
has_rtt "${CR8_0_ELF}" && echo "  ${HERE}/../nuttx-rtt-bridge.sh start cr8_0 ${CR8_0_ELF}"
has_rtt "${CR8_1_ELF}" && echo "  ${HERE}/../nuttx-rtt-bridge.sh start cr8_1 ${CR8_1_ELF}"
echo "  ${HERE}/../nsh_console_exec.py --marker 'ps'"
has_rtt "${CR8_0_ELF}" || echo "  ${HERE}/rzv2h-ipc-demo-type-cr8_0-serial.sh /dev/ttyUSB0   # CR8-0 NSH on serial"
exit 0
