#!/bin/sh
#
# Shut down every RTT console that holds the J-Link probe, so a loader can
# own it. Never starts RTT: open the console again manually afterwards with
#   platforms/nuttx/Debug/nuttx-rtt-bridge.sh start <core> <elf>
#
# Stops, in order:
#   1. the nuttx-rtt-bridge.sh bridge (its own pidfile-checked stop);
#   2. any other JLinkExe of this user listening on the RTT port (a bridge
#      started from another STATE_DIR, e.g. by the VS Code extension);
#   3. this user's SEGGER RTT tools (JLinkRTTClient/Logger/Viewer).
# GDB servers and debuggers are left alone: they are debug sessions, not RTT
# consoles, and the loaders refuse an occupied GDB port on their own.
#
# Processes get SIGTERM, then SIGKILL after STOP_TIMEOUT seconds.
#
# Usage: rtt-console-stop.sh
# Env:   RTT_PORT (19021), STOP_TIMEOUT (5)
# Exit:  0 nothing left running, 1 a process survived SIGKILL.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
RTT_PORT="${RTT_PORT:-19021}"
STOP_TIMEOUT="${STOP_TIMEOUT:-5}"
ME=$(id -u)
stopped=0

# 1. The managed bridge.
if ! "${HERE}/nuttx-rtt-bridge.sh" status 2>/dev/null | grep -q "not running"; then
	"${HERE}/nuttx-rtt-bridge.sh" stop
	stopped=1
fi

# Process name (comm) of a pid, empty if gone.
comm_of() { cat "/proc/$1/comm" 2>/dev/null || true; }

# True when the pid exists and belongs to this user.
mine() { [ -d "/proc/$1" ] && [ "$(stat -c %u "/proc/$1" 2>/dev/null)" = "${ME}" ]; }

# 2. JLinkExe processes serving the RTT port.
port_pids() {
	ss -ltnpH "sport = :${RTT_PORT}" 2>/dev/null \
		| grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u
}

# 3. SEGGER RTT tools (comm is truncated to 15 characters).
rtt_tool_pids() {
	for d in /proc/[0-9]*; do
		pid=${d#/proc/}
		case "$(comm_of "${pid}")" in
			JLinkRTTClient*|JLinkRTTLogger*|JLinkRTTViewer*) echo "${pid}" ;;
		esac
	done
}

targets=""
for pid in $(port_pids); do
	case "$(comm_of "${pid}")" in
		JLinkExe*) mine "${pid}" && targets="${targets} ${pid}" ;;
		*) echo "RTT port ${RTT_PORT} is held by '$(comm_of "${pid}")' (pid ${pid}); not a JLinkExe bridge, left running" >&2 ;;
	esac
done
for pid in $(rtt_tool_pids); do
	mine "${pid}" && targets="${targets} ${pid}"
done

for pid in ${targets}; do
	echo "Stopping RTT console $(comm_of "${pid}") (pid ${pid})"
	kill -TERM "${pid}" 2>/dev/null || true
	stopped=1
done

waited=0
while [ -n "${targets}" ] && [ "${waited}" -lt "${STOP_TIMEOUT}" ]; do
	alive=""
	for pid in ${targets}; do [ -d "/proc/${pid}" ] && alive="${alive} ${pid}"; done
	targets="${alive}"
	[ -z "${targets}" ] || { sleep 1; waited=$((waited + 1)); }
done

rc=0
for pid in ${targets}; do
	[ -d "/proc/${pid}" ] || continue
	echo "pid ${pid} ignored SIGTERM; sending SIGKILL" >&2
	kill -KILL "${pid}" 2>/dev/null || true
	sleep 1
	[ ! -d "/proc/${pid}" ] || { echo "pid ${pid} is still running" >&2; rc=1; }
done

if [ "${stopped}" -eq 1 ]; then
	echo "RTT console stopped; probe released. Start it again manually when needed."
else
	echo "No RTT console running."
fi
exit "${rc}"
