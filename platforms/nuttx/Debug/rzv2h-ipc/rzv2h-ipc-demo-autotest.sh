#!/bin/sh
#
# One-shot hardware autotest of the RZ/V2H CR8-0 <-> CR8-1 IPC demo over
# /dev/ipcc1, using ONLY the two RTT NSH consoles and ONE J-Link probe (no
# UART). The probe serves one RTT bridge at a time, so the cores are visited in
# turn:
#   CR8-0 (initiator, RTT 0x081A0000): ipctest --recover, --ping 100
#   CR8-1 (responder, RTT 0x081E0000): drain the result its boot auto-echo task
#          printed meanwhile -- it stays in CR8-1's RTT up-buffer because no
#          host reads that buffer until the bridge switches over
#
# Evidence chain (all must hold for exit 0):
#   1. CR8-0  IPCTEST_RESULT mode=recover status=pass, ready=1
#   2. CR8-0  IPCTEST_RESULT mode=ping status=pass pass=100 expected=100
#             timeouts=0, IPCTEST_STATS rx=100 (pass only on byte-exact echo)
#   3. CR8-1  IPCTEST_RESULT mode=auto-echo status=pass echoed=100 -- printed
#             by CR8-1 itself on its own RTT console
#   4. CR8-1 ipc-auto-echo task gone from `ps`; `free` answers on both cores;
#      no data abort / stack overflow / assert in any transcript
#
# MUTATING: RAM-loads both cores (CR8-0 first, no monitor reset with the peer
# resident) via rzv2h-ipc-demo-load-both-auto.sh. One-shot per load: CR8-1's
# auto-echo is bounded to CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_COUNT=100 and
# exits, so PING_COUNT must stay 100 and every run reloads.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> rzv2h-ipc-demo-autotest.sh [cr8_0-rtt-elf] [cr8_1-elf]
#
# Env: JLINK_SERIAL (required), RTT_PORT (19021),
#      LOG_DIR (logs/autotest-<ts> next to this script; must be new or empty).
#
# Exit: 0 all checks pass | 1 IPC/liveness check failed | 2 usage/preflight |
#       3 load failed | 4 RTT console transport not answering (not an IPC verdict)

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
NUTTX="${HERE}/../../NuttX/nuttx"
LOADER="${HERE}/rzv2h-ipc-demo-load-both-auto.sh"
BRIDGE="${HERE}/../nuttx-rtt-bridge.sh"
EXEC="${HERE}/../nsh_console_exec.py"

RTT_PORT="${RTT_PORT:-19021}"
RUN_DIR="${LOG_DIR:-${HERE}/logs/autotest-$(date +%Y%m%d-%H%M%S)}"
IPC_DEV=/dev/ipcc1
PING_COUNT=100          # must equal CR8-1 DEFAULT_COUNT (bounded auto-echo)
PING_SIZE=64

CR8_0_ELF="${1:-${NUTTX}/nuttx-ipcc-raw-cr8_0.elf}"
CR8_1_ELF="${2:-${NUTTX}/nuttx-ipcc-raw-cr8_1.elf}"

RESULTS=""
FAILED=0
BRIDGE_OWNED=0

die() { code=$1; shift; echo "!! $*" >&2; exit "${code}"; }

# record <check-name> <0|1>
record() {
	if [ "$2" -eq 0 ]; then RESULTS="${RESULTS}  PASS  $1
"; else RESULTS="${RESULTS}  FAIL  $1
"; FAILED=1; fi
}

# rtt <step> <timeout-s> <nsh command...>; output -> ${RUN_DIR}/<step>.out/.raw
rtt() { step=$1 to=$2; shift 2
	python3 "${EXEC}" --rtt "${RTT_PORT}" --timeout "${to}" \
		--log "${RUN_DIR}/${step}.raw" "$@" >"${RUN_DIR}/${step}.out" 2>&1; }

has() { grep -Eq "$1" "$2" 2>/dev/null; }

# bridge_to <cr8_0|cr8_1> <elf>: (re)point the single RTT bridge at a core.
# BRIDGE_OWNED is set first: a timed-out start leaves its JLinkExe running.
bridge_to() {
	if [ "${BRIDGE_OWNED}" -eq 1 ]; then "${BRIDGE}" stop >>"${RUN_DIR}/bridge.log" 2>&1 || true; fi
	BRIDGE_OWNED=1
	RTT_PORT="${RTT_PORT}" "${BRIDGE}" start "$1" "$2" >>"${RUN_DIR}/bridge.log" 2>&1
}

# shellcheck disable=SC2317  # invoked via trap
cleanup() {
	if [ "${BRIDGE_OWNED}" -eq 1 ]; then
		BRIDGE_OWNED=0
		"${BRIDGE}" stop >/dev/null 2>&1 || true
	fi
	# Keep the probe serial out of the transcripts (J-Link banners print it).
	if [ -n "${JLINK_SERIAL:-}" ] && [ -d "${RUN_DIR}" ]; then
		for f in "${RUN_DIR}"/*; do
			[ -f "${f}" ] || continue
			grep -q "${JLINK_SERIAL}" "${f}" 2>/dev/null || continue
			sed "s/${JLINK_SERIAL}/<probe-sn>/g" "${f}" >"${f}.tmp" && mv "${f}.tmp" "${f}"
		done
	fi
}

# --- 0. preflight (exit 2) -----------------------------------------------------
[ -n "${JLINK_SERIAL:-}" ] || die 2 "set JLINK_SERIAL to the authorized probe serial"
for f in "${CR8_0_ELF}" "${CR8_1_ELF}" "${LOADER}" "${BRIDGE}" "${EXEC}"; do
	[ -f "${f}" ] || die 2 "not found: ${f}"
done
"${BRIDGE}" status 2>/dev/null | grep -q '^running' \
	&& die 2 "an RTT bridge already owns the probe; run: ${BRIDGE} stop"
# A reused log dir could hold a previous run's PASS lines.
if [ -d "${RUN_DIR}" ] && [ -n "$(ls -A "${RUN_DIR}")" ]; then
	die 2 "LOG_DIR ${RUN_DIR} is not empty; use a new directory"
fi
mkdir -p "${RUN_DIR}"

cat <<EOF
== RZ/V2H IPC autotest (RTT only, one probe) ==
  MUTATING: RAM load + run both cores (no monitor reset with peer resident)
  CR8-0  R9A09G057H44_R8_0  ${CR8_0_ELF}  NSH over RTT
  CR8-1  R9A09G057H44_R8_1  ${CR8_1_ELF}  NSH over RTT
  probe  <probe-sn> over SWD   RTT 127.0.0.1:${RTT_PORT}   link ${IPC_DEV}
  logs   ${RUN_DIR}
EOF

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# --- 1. load both cores (exit 3) -----------------------------------------------
echo "-- [1] load + verify both cores"
LOG_DIR="${RUN_DIR}" "${LOADER}" "${CR8_0_ELF}" "${CR8_1_ELF}" >"${RUN_DIR}/load.log" 2>&1 \
	|| die 3 "load failed (see ${RUN_DIR}/load.log)"

# --- 2. CR8-0: bridge + liveness (exit 4) --------------------------------------
echo "-- [2] RTT bridge -> CR8-0"
bridge_to cr8_0 "${CR8_0_ELF}" || die 4 "RTT bridge to CR8-0 did not come up (see ${RUN_DIR}/bridge.log)"
rtt cr8_0-live 5 'uname -a' || { sleep 2; rtt cr8_0-live 5 'uname -a'; } \
	|| die 4 "CR8-0 RTT NSH not answering (see ${RUN_DIR}/cr8_0-live.out)"

# --- 3. recover ----------------------------------------------------------------
echo "-- [3] CR8-0 ipctest --recover"
# ipctest runs as a background builtin here (no CONFIG_SCHED_WAITPID): NSH
# returns the prompt at once, so wait for the RESULT line before going on.
rtt cr8_0-recover 20 --until 'IPCTEST_RESULT .*mode=recover' \
	"ipctest --recover -d ${IPC_DEV}" || true
R=1; has 'mode=recover.*status=pass' "${RUN_DIR}/cr8_0-recover.out" \
	&& has 'IPCTEST_STATS .* ready=1 ' "${RUN_DIR}/cr8_0-recover.out" && R=0
record "CR8-0 recover status=pass ready=1" "${R}"

# --- 4. ping 100 ---------------------------------------------------------------
echo "-- [4] CR8-0 ipctest --ping -n ${PING_COUNT} -s ${PING_SIZE}"
rtt cr8_0-ping 60 --until 'IPCTEST_RESULT .*mode=ping' \
	"ipctest --ping -d ${IPC_DEV} -n ${PING_COUNT} -s ${PING_SIZE}" || true
R=1; has "mode=ping.*status=pass.*pass=${PING_COUNT} expected=${PING_COUNT} timeouts=0" \
	"${RUN_DIR}/cr8_0-ping.out" \
	&& has "IPCTEST_STATS .* rx=${PING_COUNT} timeouts=" "${RUN_DIR}/cr8_0-ping.out" && R=0
record "CR8-0 ping ${PING_COUNT}/${PING_COUNT} timeouts=0 rx=${PING_COUNT}" "${R}"

R=0; rtt cr8_0-post 5 free || R=1
record "CR8-0 RTT NSH alive after test" "${R}"

# --- 5. CR8-1: switch bridge, drain its buffered self-report (exit 4) ----------
echo "-- [5] RTT bridge -> CR8-1, drain auto-echo result"
bridge_to cr8_1 "${CR8_1_ELF}" || die 4 "RTT bridge to CR8-1 did not come up (see ${RUN_DIR}/bridge.log)"
# Listen-only first: whatever CR8-1 printed since boot is read before any input.
python3 "${EXEC}" --rtt "${RTT_PORT}" --monitor --timeout 3 \
	>"${RUN_DIR}/cr8_1-drain.out" 2>&1 || true
rtt cr8_1-live 5 'uname -a' || { sleep 2; rtt cr8_1-live 5 'uname -a'; } \
	|| die 4 "CR8-1 RTT NSH not answering (see ${RUN_DIR}/cr8_1-live.out)"

R=1
for f in "${RUN_DIR}/cr8_1-drain.out" "${RUN_DIR}/cr8_1-live.raw"; do
	has "mode=auto-echo.*status=pass echoed=${PING_COUNT} expected=" "${f}" && R=0
done
record "CR8-1 auto-echo status=pass echoed=${PING_COUNT} (own RTT console)" "${R}"

R=1
if rtt cr8_1-ps 5 ps; then has 'ipc-auto-echo' "${RUN_DIR}/cr8_1-ps.out" || R=0; fi
record "CR8-1 ipc-auto-echo task finished (ps)" "${R}"

R=0; rtt cr8_1-post 5 free || R=1
record "CR8-1 RTT NSH alive after test" "${R}"

# --- 6. crash scan -------------------------------------------------------------
R=0
grep -Eil 'data abort|user stack pointer is not within|assertion failed|PANIC' \
	"${RUN_DIR}"/cr8_*.out "${RUN_DIR}"/cr8_*.raw >/dev/null 2>&1 && R=1
record "no data abort / stack overflow / assert on either console" "${R}"

# --- 7. verdict ----------------------------------------------------------------
echo
echo "== verdict (logs: ${RUN_DIR}) =="
printf '%s' "${RESULTS}"
if [ "${FAILED}" -eq 0 ]; then
	echo "== PASS: CR8-0 <-> CR8-1 IPC over ${IPC_DEV} proven on both cores =="
	exit 0
fi
echo "== FAIL =="
exit 1
