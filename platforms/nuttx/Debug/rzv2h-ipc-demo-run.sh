#!/bin/sh
#
# One command to get the RZ/V2H single-probe IPC demo ready to type on.
#
# Pipeline: (optional build) -> silent load+verify BOTH cores -> open the CR8-1
# RTT bridge -> open BOTH NSH consoles side by side in one tmux window:
#   left  pane: CR8-0 NSH on the SCI4 UART (picocom on /dev/ttyUSB0)
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
#   SCI_PORT       CR8-0 SCI4 serial device (default /dev/ttyUSB0).
#   SCI_BAUD       CR8-0 SCI4 baud (default 115200).
#   TMUX_SESSION   tmux session name (default rzv2h-ipc-demo).
#   plus JLINK_GDB / GDB / GDB_PORT / LOG_DIR (see the auto loader).

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
. "${HERE}/rzv2h-ipc-demo-jlink-lib.sh"

NUTTX=$(cd "${HERE}/../NuttX/nuttx" && pwd)
AUTO="${HERE}/rzv2h-ipc-demo-load-both-auto.sh"
BUILD="${HERE}/rzv2h-ipc-demo-build-and-load.sh"
RTT_JLINK="${HERE}/rzv2h-ipc-demo-cr8_1-rtt.jlink"

GDB_PORT="${GDB_PORT:-50000}"
RTT_PORT="${RTT_PORT:-19021}"
DEV_CR8_1="R9A09G057H44_R8_1"
SCI_PORT="${SCI_PORT:-/dev/ttyUSB0}"
SCI_BAUD="${SCI_BAUD:-115200}"
TMUX_SESSION="${TMUX_SESSION:-rzv2h-ipc-demo}"

DO_BUILD=0
DO_CONNECT=1
USE_TMUX=1               # auto-open both consoles in one tmux window
POS=""

for arg in "$@"; do
	case "${arg}" in
		--build)      DO_BUILD=1 ;;
		--no-connect) DO_CONNECT=0 ;;
		--no-tmux)    USE_TMUX=0 ;;
		-*)           echo "unknown option: ${arg}" >&2; exit 2 ;;
		*)            POS="${POS} ${arg}" ;;
	esac
done
# shellcheck disable=SC2086
set -- ${POS}

CR8_0_ELF="${1:-${NUTTX}/nuttx-ipcc-raw-cr8_0-sci4.elf}"
CR8_1_ELF="${2:-${NUTTX}/nuttx-ipcc-raw-cr8_1.elf}"

[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL must identify the authorized probe" >&2; exit 2; }
[ -f "${RTT_JLINK}" ] || { echo "not found: ${RTT_JLINK}" >&2; exit 2; }

# --- (optional) build both images -------------------------------------------
if [ "${DO_BUILD}" -eq 1 ]; then
	[ -x "${BUILD}" ] || { echo "not found/executable: ${BUILD}" >&2; exit 2; }
	echo "== building both images (--build-only) =="
	"${BUILD}" --build-only
fi

for f in "${CR8_0_ELF}" "${CR8_1_ELF}"; do
	[ -f "${f}" ] || { echo "ELF not found: ${f} (pass paths or run with --build)" >&2; exit 2; }
done

# --- load + verify both cores (silent; auto loader frees the probe after) ----
echo "== load + verify both cores =="
"${AUTO}" "${CR8_0_ELF}" "${CR8_1_ELF}"

# --- resolve JLinkExe for the RTT bridge ------------------------------------
if command -v JLinkExe >/dev/null 2>&1; then JLINKEXE=$(command -v JLinkExe)
elif [ -x /opt/SEGGER/JLink/JLinkExe ]; then JLINKEXE=/opt/SEGGER/JLink/JLinkExe
else echo "JLinkExe not found (needed for the RTT bridge)" >&2; exit 2; fi

# RTT client: telnet if present, else nc.
if command -v telnet >/dev/null 2>&1; then RTT_CLIENT="telnet 127.0.0.1 ${RTT_PORT}"
elif command -v nc >/dev/null 2>&1; then RTT_CLIENT="nc 127.0.0.1 ${RTT_PORT}"
else RTT_CLIENT=""; fi

# --- start the RTT bridge in the background, kept alive for the session ------
# JLinkExe drops to an interactive prompt after the command file; feeding it a
# never-closing stdin (a fifo we hold open on fd 9) keeps port ${RTT_PORT}
# served without sending it any further commands.
LOG_DIR="${LOG_DIR:-${HERE}/logs}"; mkdir -p "${LOG_DIR}"
RTT_LOG="${LOG_DIR}/rtt-bridge.log"
FIFO=$(mktemp -u "${TMPDIR:-/tmp}/rzv2h-rtt.XXXXXX")
mkfifo "${FIFO}"

echo "== opening CR8-1 RTT bridge on 127.0.0.1:${RTT_PORT} (log: ${RTT_LOG}) =="
preflight_probe_free || { rm -f "${FIFO}"; exit 1; }

"${JLINKEXE}" -select "usb=${JLINK_SERIAL}" -device "${DEV_CR8_1}" \
	-if SWD -speed auto -AutoConnect 1 -CommandFile "${RTT_JLINK}" \
	<"${FIFO}" >"${RTT_LOG}" 2>&1 &
BRIDGE_PID=$!
exec 9>"${FIFO}"          # hold stdin open so JLinkExe stays alive

cleanup() {
	exec 9>&- 2>/dev/null || true
	kill "${BRIDGE_PID}" 2>/dev/null || true
	rm -f "${FIFO}" 2>/dev/null || true
	echo "-- RTT bridge stopped, probe released --"
}
trap cleanup EXIT INT TERM

# Wait for the RTT server to come up (or the bridge to die).
tries=0
while ! port_listening "${RTT_PORT}"; do
	kill -0 "${BRIDGE_PID}" 2>/dev/null || { echo "RTT bridge exited early (see ${RTT_LOG})" >&2; exit 1; }
	tries=$((tries + 1))
	[ "${tries}" -gt 150 ] && { echo "RTT server not up on ${RTT_PORT} (see ${RTT_LOG})" >&2; exit 1; }
	sleep 0.1
done

cat <<EOF

Ready to demo. Type e.g.:  ipctest --sink -d /dev/ipcc1   (one side)
                           ipctest --say hi -d /dev/ipcc1 (the other)
EOF

# Decide how to present the two consoles.
#   tmux path (default): both NSH prompts side by side in one window.
#   --no-tmux / no tmux: RTT here, CR8-0 SCI4 opened by you in another terminal.
if [ "${DO_CONNECT}" -eq 0 ]; then
	[ -n "${RTT_CLIENT}" ] || echo "(no telnet/nc found; connect a client to 127.0.0.1:${RTT_PORT})"
	echo "Bridge is up. Connect CR8-1 with: ${RTT_CLIENT:-nc 127.0.0.1 ${RTT_PORT}}"
	echo "CR8-0 SCI4: ${HERE}/rzv2h-ipc-demo-type-cr8_0-sci4.sh ${SCI_PORT}"
	echo "Press Ctrl-C here to stop the bridge and release the probe."
	while kill -0 "${BRIDGE_PID}" 2>/dev/null; do sleep 1; done

elif [ "${USE_TMUX}" -eq 1 ] && command -v tmux >/dev/null 2>&1 && [ -e "${SCI_PORT}" ] && [ -n "${RTT_CLIENT}" ]; then
	echo "== opening both NSH consoles in tmux ('${TMUX_SESSION}'):"
	echo "   left = CR8-0 SCI4 (${SCI_PORT}), right = CR8-1 RTT (:${RTT_PORT}) =="
	tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null || true
	# Left pane: CR8-0 NSH on the SCI4 UART.
	tmux new-session -d -s "${TMUX_SESSION}" -n ipc-demo \
		"picocom -b ${SCI_BAUD} ${SCI_PORT}"
	# Right pane: CR8-1 NSH over the RTT bridge.
	# shellcheck disable=SC2086
	tmux split-window -h -t "${TMUX_SESSION}" ${RTT_CLIENT}
	tmux set-option -t "${TMUX_SESSION}" pane-border-status top 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.0" -T "CR8-0 SCI4 ${SCI_PORT}" 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.1" -T "CR8-1 RTT :${RTT_PORT}" 2>/dev/null || true
	tmux set-option -t "${TMUX_SESSION}" mouse on 2>/dev/null || true
	tmux select-pane -t "${TMUX_SESSION}.0"
	tmux attach-session -t "${TMUX_SESSION}" || true
	tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null || true

elif [ -n "${RTT_CLIENT}" ]; then
	# Fallback: no tmux (or SCI port absent). RTT here; open SCI4 separately.
	[ -e "${SCI_PORT}" ] || echo "(note: ${SCI_PORT} not present -- attach the FT232 for the CR8-0 console)"
	echo "== CR8-1 NSH (RTT). Open CR8-0 in another terminal: =="
	echo "   ${HERE}/rzv2h-ipc-demo-type-cr8_0-sci4.sh ${SCI_PORT}"
	echo "== Quit this client to end the session. =="
	# shellcheck disable=SC2086
	${RTT_CLIENT} || true

else
	echo "(no telnet/nc found; connect a client to 127.0.0.1:${RTT_PORT})" >&2
	while kill -0 "${BRIDGE_PID}" 2>/dev/null; do sleep 1; done
fi
