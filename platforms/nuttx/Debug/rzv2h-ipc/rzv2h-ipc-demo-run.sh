#!/bin/sh
#
# One command to get the RZ/V2H single-probe IPC demo ready to type on.
#
# Pipeline: (optional build) -> silent load+verify BOTH cores -> open the CR8-1
# RTT bridge -> open BOTH NSH consoles side by side in one tmux window:
#   left  pane: CR8-0 NSH on the serial UART (picocom on /dev/ttyUSB0)
#   right pane: CR8-1 NSH on RTT (nc/telnet to 127.0.0.1:19021)
# So one command gives you both prompts to type on -- no separate terminal, no
# manual serial monitor. Type ipctest across /dev/ipcc1 on either side.
#
# The one J-Link probe loads both cores, then is handed to the RTT bridge which
# this script keeps alive for the whole session; on exit (quit both tmux panes)
# the bridge is stopped and the probe released.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh                 # use built ELFs
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh --build         # (re)build first
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh --no-tmux       # single pane: RTT here, open SCI yourself
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh --no-connect    # bridge only, no console
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh <cr8_0-elf> <cr8_1-elf>
#
# Quit: in tmux, exit picocom (Ctrl-A Ctrl-X) and nc (Ctrl-C) in both panes, or
# kill the window (Ctrl-b &). tmux prefix is Ctrl-b; switch panes with Ctrl-b o.
#
# Env:
#   JLINK_SERIAL   Authorized probe serial (required).
#   RTT_PORT       RTT server / client port (default 19021).
#   SCI_PORT       CR8-0 serial console device (default /dev/ttyUSB0).
#   SCI_BAUD       CR8-0 serial baud (default 115200).
#   TMUX_SESSION   tmux session name (default rzv2h-ipc-demo).
#   plus JLINK_GDB / GDB / GDB_PORT / LOG_DIR (see the auto loader).

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
. "${HERE}/rzv2h-ipc-demo-jlink-lib.sh"

NUTTX=$(cd "${HERE}/../../NuttX/nuttx" && pwd)
AUTO="${HERE}/rzv2h-ipc-demo-load-both-auto.sh"
BUILD="${HERE}/rzv2h-ipc-demo-build-and-load.sh"
# The managed bridge derives RTT from the exact loaded image.
RTT_DEVICE="${RTT_DEVICE:-R9A09G057H44_R8_1}"
case "${RTT_DEVICE}" in
 R9A09G057H44_R8_0|cr8_0) RTT_CORE=cr8_0; RTT_LABEL=CR8-0 ;;
 R9A09G057H44_R8_1|cr8_1) RTT_CORE=cr8_1; RTT_LABEL=CR8-1 ;;
 *) echo "RTT_DEVICE must select CR8-0 or CR8-1" >&2; exit 2 ;;
esac
BRIDGE="${HERE}/../nuttx-rtt-bridge.sh"

GDB_PORT="${GDB_PORT:-50000}"
RTT_PORT="${RTT_PORT:-19021}"
SCI_PORT="${SCI_PORT:-/dev/ttyUSB0}"
SCI_BAUD="${SCI_BAUD:-115200}"
TMUX_SESSION="${TMUX_SESSION:-rzv2h-ipc-demo}"

DO_BUILD=0
DO_CONNECT=1
USE_TMUX=1               # auto-open both consoles in one tmux window
ARG_ELF0=
ARG_ELF1=

for arg in "$@"; do
	case "${arg}" in
		--build)      DO_BUILD=1 ;;
		--no-connect) DO_CONNECT=0 ;;
		--no-tmux)    USE_TMUX=0 ;;
		-*)           echo "unknown option: ${arg}" >&2; exit 2 ;;
		*)
            if [ -z "${ARG_ELF0}" ]; then ARG_ELF0="${arg}"
            elif [ -z "${ARG_ELF1}" ]; then ARG_ELF1="${arg}"
            else echo "expected two ELF paths" >&2; exit 2; fi ;;
	esac
done

CR8_0_ELF="${ARG_ELF0:-${NUTTX}/nuttx-ipcc-raw-cr8_0-serial.elf}"
CR8_1_ELF="${ARG_ELF1:-${NUTTX}/nuttx-ipcc-raw-cr8_1.elf}"

[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL must identify the authorized probe" >&2; exit 2; }
# Never replace an interactive session owned by someone else.
if command -v tmux >/dev/null 2>&1 && tmux has-session -t "=${TMUX_SESSION}" 2>/dev/null; then
 echo "tmux session ${TMUX_SESSION} already exists; release its owner first" >&2; exit 2
fi

# --- (optional) build both images -------------------------------------------
if [ "${DO_BUILD}" -eq 1 ]; then
	[ -x "${BUILD}" ] || { echo "not found/executable: ${BUILD}" >&2; exit 2; }
	echo "== building both images (--build-only) =="
	"${BUILD}" --build-only
fi

for f in "${CR8_0_ELF}" "${CR8_1_ELF}"; do
	[ -f "${f}" ] || { echo "ELF not found: ${f} (pass paths or run with --build)" >&2; exit 2; }
done

# Pre-existing owners are refused before taking cleanup responsibility.
if "${BRIDGE}" status 2>/dev/null | grep -q '^running'; then
 echo "RTT bridge already owned; release it first" >&2; exit 1
fi

# --- load + verify both cores (silent; auto loader frees the probe after) ----
echo "== load + verify both cores =="
"${AUTO}" "${CR8_0_ELF}" "${CR8_1_ELF}"

# RTT client: telnet if present, else nc.
if command -v telnet >/dev/null 2>&1; then RTT_CLIENT="telnet 127.0.0.1 ${RTT_PORT}"
elif command -v nc >/dev/null 2>&1; then RTT_CLIENT="nc 127.0.0.1 ${RTT_PORT}"
else RTT_CLIENT=""; fi

# --- managed bridge; cleanup only the bridge this invocation starts --------
BRIDGE_OWNED=0
TMUX_OWNED=0
cleanup() {
 if [ "${BRIDGE_OWNED}" -eq 1 ]; then "${BRIDGE}" stop; fi
 if [ "${TMUX_OWNED}" -eq 1 ]; then tmux kill-session -t "=${TMUX_SESSION}" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' HUP TERM
if [ "${RTT_CORE}" = cr8_0 ]; then RTT_ELF="${CR8_0_ELF}"; else RTT_ELF="${CR8_1_ELF}"; fi
BRIDGE_OWNED=1
export RTT_PORT
"${BRIDGE}" start "${RTT_CORE}" "${RTT_ELF}"

cat <<EOF

Ready to demo. Type e.g.:  ipctest --sink -d /dev/ipcc1   (one side)
                           ipctest --say hi -d /dev/ipcc1 (the other)
EOF

# Decide how to present the two consoles.
#   tmux path (default): both NSH prompts side by side in one window.
#   --no-tmux / no tmux: RTT here, CR8-0 serial opened by you in another terminal.
if [ "${DO_CONNECT}" -eq 0 ]; then
	[ -n "${RTT_CLIENT}" ] || echo "(no telnet/nc found; connect a client to 127.0.0.1:${RTT_PORT})"
	echo "Bridge is up. Connect ${RTT_LABEL} with: ${RTT_CLIENT:-nc 127.0.0.1 ${RTT_PORT}}"
	echo "CR8-0 serial: ${HERE}/rzv2h-ipc-demo-type-cr8_0-serial.sh ${SCI_PORT}"
	echo "Press Ctrl-C here to stop the bridge and release the probe."
	while "${BRIDGE}" status 2>/dev/null | grep -q '^running'; do sleep 1; done

elif [ "${USE_TMUX}" -eq 1 ] && command -v tmux >/dev/null 2>&1 && [ -e "${SCI_PORT}" ] && [ -n "${RTT_CLIENT}" ]; then
	echo "== opening both NSH consoles in tmux ('${TMUX_SESSION}'):"
	echo "   left = CR8-0 serial (${SCI_PORT}), right = CR8-1 RTT (:${RTT_PORT}) =="
	# Left pane: CR8-0 NSH on the serial UART.
	tmux new-session -d -s "${TMUX_SESSION}" -n ipc-demo \
		"picocom -b ${SCI_BAUD} ${SCI_PORT}"
	TMUX_OWNED=1
	# Right pane: CR8-1 NSH over the RTT bridge.
	# shellcheck disable=SC2086
	tmux split-window -h -t "${TMUX_SESSION}" ${RTT_CLIENT}
	tmux set-option -t "${TMUX_SESSION}" pane-border-status top 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.0" -T "CR8-0 serial ${SCI_PORT}" 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.1" -T "CR8-1 RTT :${RTT_PORT}" 2>/dev/null || true
	tmux set-option -t "${TMUX_SESSION}" mouse on 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.0"
	tmux attach-session -t "${TMUX_SESSION}" || true

elif [ -n "${RTT_CLIENT}" ]; then
	# Fallback: no tmux (or SCI port absent). Single RTT console here.
	echo "== ${RTT_LABEL} NSH (RTT) on 127.0.0.1:${RTT_PORT}. =="
	if [ "${RTT_LABEL}" = "CR8-1" ]; then
		# Dual-console split: the other core (CR8-0) is on the serial UART.
		[ -e "${SCI_PORT}" ] || echo "(note: ${SCI_PORT} not present -- attach the FT232 for the CR8-0 console)"
		echo "   Open CR8-0 in another terminal: ${HERE}/rzv2h-ipc-demo-type-cr8_0-serial.sh ${SCI_PORT}"
	fi
	echo "== Quit this client to end the session. =="
	# shellcheck disable=SC2086
	${RTT_CLIENT} || true

else
	echo "(no telnet/nc found; connect a client to 127.0.0.1:${RTT_PORT})" >&2
	while "${BRIDGE}" status 2>/dev/null | grep -q '^running'; do sleep 1; done
fi
