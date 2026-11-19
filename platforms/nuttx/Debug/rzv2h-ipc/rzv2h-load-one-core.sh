#!/bin/sh
#
# Volatile RAM load of ONE RZ/V2H Cortex-R8 core, then a non-destructive
# verify (halt, PC check, resume). The single-core counterpart of
# rzv2h-ipc-demo-load-both-auto.sh, for CR8-0-only bring-up (PX4 default, demo,
# demosih) or for replacing one image of a running pair.
#
# MUTATING: halts the core, overwrites its image in RAM and starts it at
# __start with the reset CPSR. Needs the user's approval. No monitor reset is
# issued, so the other core keeps running; reload CR8-1 after CR8-0 when the
# pair has an IPC session (CR8-1 adopts the initiator's recovery epoch).
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-load-one-core.sh [--verbose] <cr8_0|cr8_1> <elf>
#
# Env: JLINK_SERIAL (required), JLINK_GDB, GDB, GDB_PORT (50000), LOG_DIR.
# One no-reset attempt; reset/DBGEN/connect failures stop target access.
# LOAD_ATTEMPTS, if supplied, must be 1. Another attempt needs approval.
# Exit: 0 loaded and verified, 1 load or verify failed, 2 usage.

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

if [ "${1:-}" = "--verbose" ] || [ "${1:-}" = "-v" ]; then
	VERBOSE=1; shift
fi
usage="usage: JLINK_SERIAL=<probe-sn> $0 [--verbose] <cr8_0|cr8_1> <elf>"
case "${1:-}" in
cr8_0) dev=R9A09G057H44_R8_0; label=CR8-0 ;;
cr8_1) dev=R9A09G057H44_R8_1; label=CR8-1 ;;
*) echo "${usage}" >&2; exit 2 ;;
esac
elf="${2:-}"
[ -n "${elf}" ] || { echo "${usage}" >&2; exit 2; }
[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL must identify the authorized probe" >&2; exit 2; }
for f in "${elf}" "${LOADSTART}" "${VERIFY}"; do
	[ -f "${f}" ] || { echo "not found: ${f}" >&2; exit 2; }
done

resolve_tools || exit 2
mkdir -p "${LOG_DIR}"

load_core "${dev}" "${elf}" "${label}" || exit 1
verify_core "${dev}" "${elf}" "${label}" || exit 1
echo "${label} running ${elf}; probe released."
