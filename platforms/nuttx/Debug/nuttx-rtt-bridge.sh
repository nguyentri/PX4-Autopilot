#!/bin/sh
#
# Start/stop a detached SEGGER RTT bridge to a running NuttX/PX4 target.
#
# JLinkExe attaches to the ALREADY RUNNING core (no reset, no halt, no load),
# points RTT at the image's _SEGGER_RTT control block and serves channel 0
# (typically the NSH console) as raw TCP on 127.0.0.1:${RTT_PORT}. Use it when
# the GDB server cannot bridge RTT (e.g. RZ/V2H CR8) or to talk to NSH without
# a debugger. The bridge owns the probe while up: stop it before starting
# JLinkGDBServer / a VS Code debug session.
#
# Usage:
#   JLINK_SERIAL=<sn> nuttx-rtt-bridge.sh start <target> [elf|0xADDR]
#   nuttx-rtt-bridge.sh status
#   nuttx-rtt-bridge.sh stop
# <target>: a J-Link device name (e.g. STM32H743VI), or an alias:
#   cr8_0 -> R9A09G057H44_R8_0 (default RTT 0x081A0000)
#   cr8_1 -> R9A09G057H44_R8_1 (default RTT 0x081E0000)
# RTT address: RTT_ADDR env, else `nm <elf>` _SEGGER_RTT, else 0xADDR arg,
# else the alias default, else J-Link's own control-block search.
# Then:  nsh_console_exec.py --rtt 'ps'      or      nc 127.0.0.1 19021
#
# Env: JLINK_SERIAL (required for start), RTT_PORT (19021), RTT_ADDR,
#      JLINK_IF (SWD), JLINK_SPEED (auto), STATE_DIR (${TMPDIR:-/tmp}/nuttx-rtt-bridge).

set -eu

RTT_PORT="${RTT_PORT:-19021}"
STATE_DIR="${STATE_DIR:-${TMPDIR:-/tmp}/nuttx-rtt-bridge}"
PIDFILE="${STATE_DIR}/bridge.pid"
LOG="${STATE_DIR}/jlinkexe.log"
JLINKEXE=$(command -v JLinkExe || echo /opt/SEGGER/JLink/JLinkExe)

port_up() { nc -z 127.0.0.1 "${RTT_PORT}" 2>/dev/null; }

# A numeric PID alone cannot identify a detached bridge after PID reuse.
running() {
	[ -r "${PIDFILE}" ] && [ -r "${PIDFILE}.identity" ] || return 1
	bridge_pid=$(cat "${PIDFILE}")
	case "${bridge_pid}" in ''|*[!0-9]*) return 1 ;; esac
	{
		read -r bridge_start && read -r bridge_cmd &&
		read -r bridge_probe && read -r bridge_core
	} <"${PIDFILE}.identity" || return 1
	[ -r "/proc/${bridge_pid}/stat" ] || return 1
	bridge_identity=$(awk '{sub(/^.*\) /, ""); print $3, $4, $20}' "/proc/${bridge_pid}/stat") || return 1
	[ "${bridge_identity}" = "${bridge_pid} ${bridge_pid} ${bridge_start}" ] || return 1
	tr '\000' '\n' <"/proc/${bridge_pid}/cmdline" | grep -Fxq 'nuttx-rtt-bridge' || return 1
	for bridge_arg in "${bridge_cmd}" "${bridge_probe}" "${bridge_core}"; do
		tr '\000' '\n' <"/proc/${bridge_pid}/cmdline" | grep -Fxq -- "${bridge_arg}" || return 1
	done
}

stop_owned() {
	if running; then
		kill -- "-${bridge_pid}" 2>/dev/null || return 1
		stop_tries=0
		while running || port_up; do
			stop_tries=$((stop_tries + 1))
			[ "${stop_tries}" -lt 50 ] || { echo "RTT bridge has not released its port" >&2; return 1; }
			sleep 0.1
		done
	fi
}

case "${1:-}" in
start)
	target="${2:?target: J-Link device name or cr8_0|cr8_1}"
	: "${JLINK_SERIAL:?set JLINK_SERIAL to the exact probe serial}"
	case "${target}" in
	cr8_0) dev=R9A09G057H44_R8_0; def_addr=0x081A0000 ;;
	cr8_1) dev=R9A09G057H44_R8_1; def_addr=0x081E0000 ;;
	*) dev="${target}"; def_addr="" ;;
	esac
	addr="${RTT_ADDR:-}"
	case "${3:-}" in
	"") ;;
	0x*|0X*) addr="${addr:-$3}" ;;
	*)
		if [ -z "${addr}" ]; then
			nm=$(command -v arm-none-eabi-nm || echo /opt/arm-gnu-toolchain-13.2.Rel1/bin/arm-none-eabi-nm)
			addr=0x$("${nm}" "$3" | awk '$3=="_SEGGER_RTT"{print $1}')
			[ "${addr}" != "0x" ] || { echo "_SEGGER_RTT not in $3 (not an RTT-console build?)" >&2; exit 2; }
		fi ;;
	esac
	addr="${addr:-${def_addr}}"
	running && { echo "bridge already running (pid $(cat "${PIDFILE}"))" >&2; exit 1; }
	# A just-finished JLinkGDBServer (-singlerun) also serves RTT telnet on
	# 19021 while it shuts down; give it up to 5 s to release the port.
	i=0
	while port_up; do
		i=$((i + 1)); [ "${i}" -gt 50 ] && { echo "port ${RTT_PORT} already in use" >&2; exit 1; }
		sleep 0.1
	done
	mkdir -p "${STATE_DIR}"
	cmdfile=$(mktemp "${STATE_DIR}/bridge.XXXXXX.jlink")
	{
		# No address -> J-Link scans RAM for the "SEGGER RTT" control block.
		[ -z "${addr}" ] || echo "exec SetRTTAddr ${addr}"
		# 19021 is JLinkExe's default; only override when asked.
		[ "${RTT_PORT}" = 19021 ] || echo "exec SetRTTTelnetPort ${RTT_PORT}"
		echo "rtt start"
	} >"${cmdfile}"
	# A never-ending stdin keeps JLinkExe at its prompt so the port stays served.
	# JLinkExe selects the probe with -USB <sn> (it rejects GDB server's -select).
	setsid sh -c 'sleep 2147483647 | "$@"' nuttx-rtt-bridge \
		"${JLINKEXE}" -USB "${JLINK_SERIAL}" -device "${dev}" \
		-if "${JLINK_IF:-SWD}" -speed "${JLINK_SPEED:-auto}" -AutoConnect 1 \
		-CommandFile "${cmdfile}" >"${LOG}" 2>&1 &
	sid=$!
	echo "${sid}" >"${PIDFILE}"
	bridge_start=$(awk '{sub(/^.*\) /, ""); print $20}' "/proc/${sid}/stat")
	printf '%s\n' "${bridge_start}" "${cmdfile}" "${JLINK_SERIAL}" "${dev}" >"${PIDFILE}.identity"
	fail() { echo "$1" >&2; stop_owned; tail -20 "${LOG}" >&2; rm -f "${PIDFILE}" "${PIDFILE}.identity" "${cmdfile}"; exit 1; }
	i=0
	until port_up; do
		# The sleep keeps the session alive, so look for JLinkExe itself in it
		# (after a short grace for it to spawn).
		[ "${i}" -lt 5 ] || pgrep -s "${sid}" -x JLinkExe >/dev/null || fail "JLinkExe exited early:"
		i=$((i + 1)); [ "${i}" -gt 150 ] && fail "RTT port not up:"
		sleep 0.1
	done
	echo "RTT bridge up: ${target} (${dev}) _SEGGER_RTT=${addr:-auto-search} -> 127.0.0.1:${RTT_PORT}"
	echo "log: ${LOG}"
	;;
stop)
	if running; then
		stop_owned
		rm -f "${bridge_cmd}"
		echo "RTT bridge stopped, probe released"
	else
		echo "no bridge running"
	fi
	rm -f "${PIDFILE}" "${PIDFILE}.identity"
	;;
status)
	if running; then echo "running pid $(cat "${PIDFILE}"), port ${RTT_PORT} $(port_up && echo up || echo DOWN)"
	else echo "not running"; fi
	;;
*)
	sed -n '2,25p' "$0"; exit 2 ;;
esac
