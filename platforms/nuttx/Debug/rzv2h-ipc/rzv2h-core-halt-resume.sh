#!/bin/sh
#
# Hold one running RZ/V2H CR8 core halted for a bounded time through J-Link,
# then resume it, without reset or load. Used by IPC loss tests: holding CR8-1
# silences its heartbeat while CR8-0 keeps running and is queried over SCI5.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-core-halt-resume.sh <cr8_0|cr8_1> hold <seconds>
#
# One JLinkExe run: InhibitConnectRetries, connect, halt, sleep, go, exit.
# The halt must stay inside one JLinkExe session: on this board a CR8 core
# halted by JLinkExe runs again as soon as JLinkExe disconnects, so a separate
# `halt` call does not keep the core stopped. Run the hold in the background
# and do the observation while it lasts; the core resumes by itself at the end.
# The CM33 is refused (its connect resets the SoC). The call refuses to run
# while another J-Link process owns the probe (one probe owner at a time).
#
# Exit: 0 halt confirmed and resumed, 2 usage, 3 connect failed or the J-Link
# log shows a reset (diagnose before any reload; never blind-retry), 1 other
# failure (probe not reached, JLinkExe error or timeout, halt not confirmed).

set -eu

usage() { echo "usage: JLINK_SERIAL=<sn> $0 <cr8_0|cr8_1> hold <seconds 1-120>" >&2; exit 2; }
if [ $# -ne 3 ] || [ "$2" != hold ]; then usage; fi
case "$1" in
cr8_0) dev=R9A09G057H44_R8_0 ;;
cr8_1) dev=R9A09G057H44_R8_1 ;;
cm33*) echo "refused: connecting to the CM33 resets the SoC" >&2; exit 2 ;;
*) usage ;;
esac
case "$3" in '' | *[!0-9]*) usage ;; esac
if [ "$3" -lt 1 ] || [ "$3" -gt 120 ]; then usage; fi
hold_s=$3
[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL is required" >&2; exit 2; }

JLINKEXE=${JLINKEXE:-$(command -v JLinkExe || echo /opt/SEGGER/JLink/JLinkExe)}
RESET_MARKERS='Resetting via Reset pin|cold reset sequence'
PROBE_MARKERS='Connecting to J-Link via USB\.*FAILED|Cannot connect to J-Link'
CONNECT_MARKERS="${RESET_MARKERS}|Cannot connect to target|Could not connect|Failed to attach|DBGEN is not asserted"

if pgrep -x JLinkExe >/dev/null || pgrep -f '^[^ ]*JLinkGDBServer(CLExe)?( |$)' >/dev/null; then
	echo "probe busy: another JLinkExe/JLinkGDBServer is running; stop its owner first" >&2
	exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "${tmp}"' EXIT
printf '%s\n' "exec InhibitConnectRetries = 1" connect halt "sleep $((hold_s * 1000))" go exit >"${tmp}/cmd.jlink"
rc=0
timeout "$((hold_s + 30))" "${JLINKEXE}" -USB "${JLINK_SERIAL}" -device "${dev}" -if "${JLINK_IF:-SWD}" \
	-speed "${JLINK_SPEED:-auto}" -NoGui 1 -CommandFile "${tmp}/cmd.jlink" >"${tmp}/jlink.log" 2>&1 || rc=$?

if grep -Eq "${CONNECT_MARKERS}" "${tmp}/jlink.log"; then
	grep -E "${CONNECT_MARKERS}" "${tmp}/jlink.log" >&2
	if grep -Eq "${RESET_MARKERS}" "${tmp}/jlink.log"; then
		echo "!! J-Link RESET $1: the running image is gone; reload before trusting any output" >&2
	fi
	exit 3
fi

if grep -Eq "${PROBE_MARKERS}" "${tmp}/jlink.log" || [ "${rc}" -ne 0 ]; then
	tail -20 "${tmp}/jlink.log" >&2
	echo "JLinkExe failed on $1 hold (exit ${rc}; 124 = timeout); core state unknown" >&2
	exit 1
fi

# `halt` prints the register file; without it the core may never have stopped.
if ! grep -Eq '^PC = |PC: ' "${tmp}/jlink.log"; then
	tail -20 "${tmp}/jlink.log" >&2
	echo "halt not confirmed on $1" >&2
	exit 1
fi
grep -E '^PC = |PC: ' "${tmp}/jlink.log" | head -1
echo "$1 held ${hold_s} s and resumed: ok"
