#!/bin/sh
#
# Hardware check of the PX4 demo heartbeat pair: CR8-0 renesas_rdk-rzv2h_demo
# (raw IPC initiator) and CR8-1 renesas_rdk-rzv2h-io-cr8_1_demo (responder)
# exchanging rzv2h_heartbeat frames over /dev/ipcc1.
#
# Consoles: CR8-0 is queried ONLY through the MAVLink shell on SCI5
# (rzv2h-mavlink-shell-exec.py, no probe needed); CR8-1 through one RTT bridge.
# That leaves the probe free to hold CR8-1 halted while CR8-0 is queried.
#
# Evidence chain (all must hold for exit 0):
#   1. CR8-0  `ver all` reports Build variant: demo; `mavlink status` on /dev/ttyS5
#   2. CR8-0  rzv2h_heartbeat: role initiator, peer alive, age_ms < 500,
#             tx sent and rx valid rising across two samples
#   3. CR8-1  rzv2h_heartbeat: role responder, peer alive, counters rising; `free` answers
#   4. CR8-1 held halted (no reset) for HOLD_S: CR8-0 reports peer lost,
#      age_ms >= 500, and its MAVLink shell still answers, all inside the
#      hold window; after the hold ends: CR8-0 reports peer alive again
#   5. no data abort / stack overflow / assert / PANIC in any transcript
#
# MUTATING: step 4 holds CR8-1 halted for HOLD_S seconds in one JLinkExe
# session, which resumes it at the end (run control only). With --load,
# both cores are first RAM-loaded via rzv2h-ipc-demo-load-both-auto.sh.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> rzv2h-px4-demo-heartbeat-check.sh [--load] [cr8_0-elf] [cr8_1-elf]
#
# Env: JLINK_SERIAL (required), MAV_PORT (/dev/ttyUSB0), MAV_BAUD (57600),
#      RTT_PORT (19021), HOLD_S (15), LOG_DIR (logs/px4-demo-heartbeat-<ts>;
#      new or empty).
#
# Exit: 0 all checks pass | 1 heartbeat evidence failed | 2 usage/preflight |
#       3 load or probe connect failed (diagnose, never blind-retry) |
#       4 a console transport is not answering (not a heartbeat verdict)

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "${HERE}/../../../.." && pwd)
LOADER="${HERE}/rzv2h-ipc-demo-load-both-auto.sh"
HALT="${HERE}/rzv2h-core-halt-resume.sh"
BRIDGE="${HERE}/../nuttx-rtt-bridge.sh"
RTT_EXEC="${HERE}/../nsh_console_exec.py"
MAV_EXEC="${HERE}/../rzv2h-mavlink-shell-exec.py"

MAV_PORT="${MAV_PORT:-/dev/ttyUSB0}"
MAV_BAUD="${MAV_BAUD:-57600}"
RTT_PORT="${RTT_PORT:-19021}"
RUN_DIR="${LOG_DIR:-${HERE}/logs/px4-demo-heartbeat-$(date +%Y%m%d-%H%M%S)}"

LOAD=0
if [ "${1:-}" = "--load" ]; then LOAD=1; shift; fi
case "${1:-}" in -*) echo "usage: $0 [--load] [cr8_0-elf] [cr8_1-elf]" >&2; exit 2 ;; esac
CR8_0_ELF="${1:-${ROOT}/build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf}"
CR8_1_ELF="${2:-${ROOT}/build/renesas_rdk-rzv2h-io-cr8_1_demo/renesas_rdk-rzv2h-io-cr8_1_demo.elf}"

RESULTS=""
FAILED=0
BRIDGE_OWNED=0
HOLD_PID=
HOLD_S=${HOLD_S:-15}

die() { code=$1; shift; echo "!! $*" >&2; exit "${code}"; }

record() {
	if [ "$2" -eq 0 ]; then RESULTS="${RESULTS}  PASS  $1
"; else RESULTS="${RESULTS}  FAIL  $1
"; FAILED=1; fi
}

has() { grep -Eq "$1" "$2" 2>/dev/null; }

# num <file> <sed-regex with one \(group\)>: number captured from the last
# rzv2h_heartbeat status line that matches the WHOLE pattern to end of line,
# or -1. Full-line matching rejects lines spliced by dropped MAVLink chunks.
HB='.*\[rzv2h_heartbeat\] '
num() { v=$(sed -n "s/^${HB}$2\r*\$/\1/p" "$1" 2>/dev/null | tail -1); echo "${v:--1}"; }
PEER_AGE='peer: \(alive\|lost\) age_ms \(-*[0-9]*\) seq [0-9]* uptime_ms [0-9]* loops [0-9]* state [0-9]*'
TX_SENT='tx: sent \([0-9]*\) failed [0-9]* seq [0-9]*'
RX_VALID='rx: valid \([0-9]*\) ignored [0-9]* stale [0-9]* restarts [0-9]*'

# peer_age <file>: "<alive|lost> <age_ms>" from the last whole peer line, or "none -1".
peer_age() { v=$(sed -n "s/^${HB}${PEER_AGE}\r*\$/\1 \2/p" "$1" 2>/dev/null | tail -1); echo "${v:-none -1}"; }

# mav <step> <command...>: CR8-0 MAVLink shell over SCI5 -> ${RUN_DIR}/<step>.out
mav() { step=$1; shift
	python3 "${MAV_EXEC}" --port "${MAV_PORT}" --baud "${MAV_BAUD}" "$@" >"${RUN_DIR}/${step}.out" 2>&1; }

# rtt <step> <command...>: CR8-1 NSH over the RTT bridge
rtt() { step=$1; shift
	python3 "${RTT_EXEC}" --rtt "${RTT_PORT}" --marker --timeout 5 \
		--log "${RUN_DIR}/${step}.raw" "$@" >"${RUN_DIR}/${step}.out" 2>&1; }

# shellcheck disable=SC2317  # invoked via trap
cleanup() {
	if [ "${BRIDGE_OWNED}" -eq 1 ]; then BRIDGE_OWNED=0; "${BRIDGE}" stop >/dev/null 2>&1 || true; fi
	# A running hold resumes CR8-1 by itself; wait for it, never reconnect.
	if [ -n "${HOLD_PID}" ]; then wait "${HOLD_PID}" 2>/dev/null || true; HOLD_PID=; fi
	if [ -n "${JLINK_SERIAL:-}" ] && [ -d "${RUN_DIR}" ]; then
		for f in "${RUN_DIR}"/*; do
			[ -f "${f}" ] || continue
			grep -q "${JLINK_SERIAL}" "${f}" 2>/dev/null || continue
			sed "s/${JLINK_SERIAL}/<probe-sn>/g" "${f}" >"${f}.tmp" && mv "${f}.tmp" "${f}"
		done
	fi
}

# heartbeat_ok <file> <role>: role matches, peer alive, age below the 500 ms timeout.
heartbeat_ok() {
	has "role: $2" "$1" || return 1
	# shellcheck disable=SC2046  # split "<state> <age>" into $1 $2
	set -- $(peer_age "$1")
	[ "$1" = alive ] && [ "$2" -ge 0 ] && [ "$2" -lt 500 ]
}

# rising <file-a> <file-b>: tx sent and rx valid both increased.
rising() {
	[ "$(num "$2" "${TX_SENT}")" -gt "$(num "$1" "${TX_SENT}")" ] \
		&& [ "$(num "$2" "${RX_VALID}")" -gt "$(num "$1" "${RX_VALID}")" ]
}

# --- 0. preflight (exit 2) -----------------------------------------------------
[ -n "${JLINK_SERIAL:-}" ] || die 2 "set JLINK_SERIAL to the authorized probe serial"
for f in "${CR8_0_ELF}" "${CR8_1_ELF}" "${LOADER}" "${HALT}" "${BRIDGE}" "${RTT_EXEC}" "${MAV_EXEC}"; do
	[ -f "${f}" ] || die 2 "not found: ${f}"
done
[ -c "${MAV_PORT}" ] || die 2 "no MAVLink serial device ${MAV_PORT} (set MAV_PORT)"
if command -v fuser >/dev/null && fuser "${MAV_PORT}" >/dev/null 2>&1; then
	die 2 "${MAV_PORT} is open in another process; close that terminal first"
fi
if pgrep -x JLinkExe >/dev/null || pgrep -f '^[^ ]*JLinkGDBServer(CLExe)?( |$)' >/dev/null; then
	die 2 "another J-Link process owns the probe; stop its owner first (one probe owner)"
fi
if [ -d "${RUN_DIR}" ] && [ -n "$(ls -A "${RUN_DIR}")" ]; then
	die 2 "LOG_DIR ${RUN_DIR} is not empty; use a new directory"
fi
mkdir -p "${RUN_DIR}"

cat <<EOF
== RZ/V2H PX4 demo heartbeat check ==
  CR8-0  ${CR8_0_ELF}  MAVLink shell ${MAV_PORT} @${MAV_BAUD}
  CR8-1  ${CR8_1_ELF}  NSH over RTT 127.0.0.1:${RTT_PORT}
  MUTATING: hold CR8-1 halted ${HOLD_S} s$( [ "${LOAD}" -eq 1 ] && echo "; RAM load both cores first" )
  logs   ${RUN_DIR}
EOF

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# --- 1. optional load (exit 3) -------------------------------------------------
if [ "${LOAD}" -eq 1 ]; then
	echo "-- [1] load + verify both cores"
	LOG_DIR="${RUN_DIR}" "${LOADER}" "${CR8_0_ELF}" "${CR8_1_ELF}" >"${RUN_DIR}/load.log" 2>&1 \
		|| die 3 "load failed (see ${RUN_DIR}/load.log)"
	sleep 8   # PX4 boot: rcS starts mavlink and rzv2h_heartbeat
fi

# --- 2. CR8-0 over SCI5 (exit 4 when the shell does not answer) ---------------
echo "-- [2] CR8-0 MAVLink shell: identity + heartbeat"
mav cr8_0-ident 'ver all' 'mavlink status' || die 4 "CR8-0 MAVLink shell not answering (see ${RUN_DIR}/cr8_0-ident.out)"
R=1; has 'Build variant: demo' "${RUN_DIR}/cr8_0-ident.out" && has '/dev/ttyS5' "${RUN_DIR}/cr8_0-ident.out" && R=0
record "CR8-0 demo image, MAVLink on /dev/ttyS5" "${R}"

mav cr8_0-hb-a 'rzv2h_heartbeat status' || die 4 "CR8-0 MAVLink shell not answering"
sleep 2
mav cr8_0-hb-b 'rzv2h_heartbeat status' || die 4 "CR8-0 MAVLink shell not answering"
R=1; heartbeat_ok "${RUN_DIR}/cr8_0-hb-b.out" initiator && rising "${RUN_DIR}/cr8_0-hb-a.out" "${RUN_DIR}/cr8_0-hb-b.out" && R=0
record "CR8-0 initiator sees CR8-1 alive (age < 500 ms), tx/rx rising" "${R}"

# --- 3. CR8-1 over RTT ---------------------------------------------------------
echo "-- [3] RTT bridge -> CR8-1: heartbeat"
BRIDGE_OWNED=1
rc=0; RTT_PORT="${RTT_PORT}" "${BRIDGE}" start cr8_1 "${CR8_1_ELF}" >"${RUN_DIR}/bridge.log" 2>&1 || rc=$?
if [ "${rc}" -ne 0 ]; then
	[ "${rc}" -eq 3 ] && die 3 "J-Link connect to CR8-1 failed (see ${RUN_DIR}/bridge.log)"
	die 4 "RTT bridge to CR8-1 did not come up (see ${RUN_DIR}/bridge.log)"
fi
rtt cr8_1-hb-a 'rzv2h_heartbeat status' || { sleep 2; rtt cr8_1-hb-a 'rzv2h_heartbeat status'; } \
	|| die 4 "CR8-1 RTT NSH not answering (see ${RUN_DIR}/cr8_1-hb-a.out)"
sleep 2
rtt cr8_1-hb-b 'rzv2h_heartbeat status' 'free' || die 4 "CR8-1 RTT NSH not answering"
R=1; heartbeat_ok "${RUN_DIR}/cr8_1-hb-b.out" responder && rising "${RUN_DIR}/cr8_1-hb-a.out" "${RUN_DIR}/cr8_1-hb-b.out" \
	&& has 'Mem:|total' "${RUN_DIR}/cr8_1-hb-b.out" && R=0
record "CR8-1 responder sees CR8-0 alive (age < 500 ms), tx/rx rising, free answers" "${R}"
"${BRIDGE}" stop >>"${RUN_DIR}/bridge.log" 2>&1 || true
BRIDGE_OWNED=0

# --- 4. loss and recovery: hold CR8-1 halted, query CR8-0 over SCI5 ----------
echo "-- [4] hold CR8-1 halted ${HOLD_S} s -> CR8-0 must report lost; then alive"
t0=$(date +%s)
"${HALT}" cr8_1 hold "${HOLD_S}" >"${RUN_DIR}/halt.log" 2>&1 &
HOLD_PID=$!
# Connect takes ~1-2 s; then the 500 ms peer timeout must elapse.
sleep 5
mrc=0; mav cr8_0-lost 'rzv2h_heartbeat status' 'mavlink status' || mrc=$?
t1=$(date +%s)
rc=0; wait "${HOLD_PID}" || rc=$?
HOLD_PID=
[ "${rc}" -eq 3 ] && die 3 "J-Link connect to CR8-1 failed (see ${RUN_DIR}/halt.log)"
[ "${rc}" -eq 0 ] || die 1 "CR8-1 hold not confirmed (exit ${rc}, see ${RUN_DIR}/halt.log)"
[ "${mrc}" -eq 0 ] || die 4 "CR8-0 MAVLink shell not answering with CR8-1 halted"
# shellcheck disable=SC2046  # split "<state> <age>" into $1 $2
set -- $(peer_age "${RUN_DIR}/cr8_0-lost.out"); peer=$1; age=$2
R=1; [ "${peer}" = lost ] && { [ "${age}" -ge 500 ] || [ "${age}" -eq -1 ]; } \
	&& has '/dev/ttyS5' "${RUN_DIR}/cr8_0-lost.out" && [ $((t1 - t0)) -lt "${HOLD_S}" ] && R=0
record "CR8-1 held: CR8-0 reports peer ${peer} (age ${age} ms) at +$((t1 - t0)) s of ${HOLD_S} s, MAVLink answers" "${R}"

# The initiator may first need its 1 s rate-limited raw recovery; allow 3 polls.
R=1
for i in 1 2 3; do
	sleep 2
	mav "cr8_0-back-${i}" 'rzv2h_heartbeat status' || continue
	if heartbeat_ok "${RUN_DIR}/cr8_0-back-${i}.out" initiator; then R=0; break; fi
done
record "CR8-1 resumed: CR8-0 reports peer alive again" "${R}"

# --- 5. crash scan -------------------------------------------------------------
R=0
grep -Eil 'data abort|user stack pointer is not within|stack overflow|assertion failed|PANIC' \
	"${RUN_DIR}"/cr8_*.out >/dev/null 2>&1 && R=1
record "no data abort / stack overflow / assert / PANIC on either console" "${R}"

echo
echo "== verdict (logs: ${RUN_DIR}) =="
printf '%s' "${RESULTS}"
if [ "${FAILED}" -eq 0 ]; then
	echo "== PASS: PX4 demo CR8-0 <-> CR8-1 heartbeat proven, including loss and recovery =="
	exit 0
fi
echo "== FAIL =="
exit 1
