#!/bin/sh
#
# Drive the CR8-0 NSH console over its serial / FT232 USB-serial adapter for the
# transport-split IPC demo. CR8-0 runs the serial-console image; its NSH prompt is
# on a plain UART, so this is just a 115200 8N1 serial session — no probe.
#
# Two ways to use it:
#
#   Interactive (best for filming) -- opens picocom so you type live:
#     ./rzv2h-ipc-demo-type-cr8_0-serial.sh /dev/ttyUSB0
#
#   Scripted send -- push one NSH command and show the reply for a few seconds:
#     ./rzv2h-ipc-demo-type-cr8_0-serial.sh /dev/ttyUSB0 -- ipctest --recover -d /dev/ipcc1
#     ./rzv2h-ipc-demo-type-cr8_0-serial.sh /dev/ttyUSB0 -- ipctest --sink    -d /dev/ipcc1
#
# Scripted mode word-splits the command, so it cannot carry a quoted multi-word
# --say string ("hello core1" would arrive as two tokens). Send --say with text,
# and the blocking --sink / --heartbeat modes, from the interactive session
# instead (Ctrl-C to stop --sink; picocom exit is Ctrl-A Ctrl-X).

set -eu

PORT="${1:-/dev/ttyUSB0}"
BAUD="${BAUD:-115200}"
shift || true

[ -e "${PORT}" ] || { echo "serial port not found: ${PORT}" >&2; exit 2; }

# Everything after `--` is the NSH command line to send once (scripted mode).
CMD=""
if [ "${1:-}" = "--" ]; then
	shift
	CMD="$*"
fi

if [ -z "${CMD}" ]; then
	# Interactive: picocom is the clean path for live typing on camera.
	if command -v picocom >/dev/null 2>&1; then
		echo "opening ${PORT} @ ${BAUD} 8N1 (exit: Ctrl-A Ctrl-X)"
		exec picocom -b "${BAUD}" "${PORT}"
	fi
	echo "picocom not found; install it for interactive use, or pass:" >&2
	echo "  $0 ${PORT} -- <nsh command>" >&2
	exit 2
fi

# Scripted send: raw 8N1, background reader to show the reply, one CR-terminated
# command, then a short window for the IPC round-trip to print.
stty -F "${PORT}" "${BAUD}" cs8 -cstopb -parenb -icanon -echo raw

cat "${PORT}" &
reader_pid=$!
trap 'kill "${reader_pid}" 2>/dev/null || true' EXIT INT TERM

sleep 0.3
printf '%s\r' "${CMD}" > "${PORT}"
sleep "${SEND_WAIT:-3}"
