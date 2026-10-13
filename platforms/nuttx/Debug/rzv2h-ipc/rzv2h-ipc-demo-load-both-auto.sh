#!/bin/sh
#
# Silent, self-verifying single-probe loader for the RZ/V2H IPC demo.
#
# Same volatile RAM load as rzv2h-ipc-demo-load-both.sh (CR8-0 SCI4 image first,
# CR8-1 RTT image last), but hardened for unattended use:
#   * preflight refuses an occupied GDB port; release its existing owner
#     before loading and keep one probe owner at a time;
#   * each connect is retried (3x) with a longer timeout and without -strict;
#   * server + gdb chatter is captured to per-core logs, so the console shows
#     only step and PASS/FAIL lines (pass --verbose to tee the logs);
#   * after both loads, each core is re-attached, halted, PC-checked and
#     resumed (non-destructive) to prove the image is actually running.
#
# Exit status is 0 only if BOTH cores load and verify; non-zero otherwise, so
# it is safe to chain in a build+load pipeline.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-auto.sh <cr8_0-sci4-elf> <cr8_1-elf>
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-auto.sh --verbose <elf0> <elf1>
#
# Env:
#   JLINK_SERIAL   Authorized probe serial (required).
#   JLINK_GDB      JLinkGDBServerCLExe path (default: PATH then /opt/SEGGER).
#   GDB            gdb-multiarch path (default: PATH).
#   GDB_PORT       GDB server port (default 50000; matches loadstart.gdb).
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

DEV_CR8_0="R9A09G057H44_R8_0"
DEV_CR8_1="R9A09G057H44_R8_1"

# --- args -------------------------------------------------------------------
if [ "${1:-}" = "--verbose" ] || [ "${1:-}" = "-v" ]; then
	VERBOSE=1; shift
fi
CR8_0_ELF="${1:-}"
CR8_1_ELF="${2:-}"

if [ -z "${CR8_0_ELF}" ] || [ -z "${CR8_1_ELF}" ]; then
	echo "usage: JLINK_SERIAL=<probe-sn> $0 [--verbose] <cr8_0-sci4-elf> <cr8_1-elf>" >&2
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
load_core "${DEV_CR8_0}" "${CR8_0_ELF}" "CR8-0 (SCI4 console)" || exit 1
load_core "${DEV_CR8_1}" "${CR8_1_ELF}" "CR8-1 (RTT console)"  || exit 1

# --- verify both are actually running ---------------------------------------
rc=0
verify_core "${DEV_CR8_0}" "${CR8_0_ELF}" "CR8-0 (SCI4 console)" || rc=1
verify_core "${DEV_CR8_1}" "${CR8_1_ELF}" "CR8-1 (RTT console)"  || rc=1

if [ "${rc}" -ne 0 ]; then
	echo "!! one or more cores failed verification (logs in ${LOG_DIR})" >&2
	exit 1
fi

cat <<EOF

Both images resident, running, and verified.
  CR8-0 NSH  -> SCI4 / FT232 USB-serial (e.g. /dev/ttyUSB0, 115200 8N1)
  CR8-1 NSH  -> RTT block 0x081E0000 (bridge on 127.0.0.1:19021)

Open the consoles (manual step, needs the now-free probe for RTT):
  ${HERE}/rzv2h-ipc-demo-load-both-manual.sh rtt     # CR8-1 RTT bridge -> :19021
  ${HERE}/rzv2h-ipc-demo-type-cr8_0-sci4.sh /dev/ttyUSB0   # CR8-0 NSH on SCI4
EOF
