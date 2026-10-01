#!/bin/sh
#
# Load both RZ/V2H CR8 IPC images to DDR with a single J-Link probe, in order:
# CR8-0 (initiator) first, CR8-1 (responder) last. Each core is loaded through
# its own short-lived JLinkGDBServer (-singlerun) so the probe is fully released
# between cores; the volatile RAM load itself is rzv2h-ipc-hil-loadstart.gdb
# (no monitor reset while a peer image may be resident).
#
# This is the transport-split demo loader: CR8-0 is the SCI4-console image
# (build rdk-rzv2h:ipcc-raw-cr8_0-sci4) so its NSH lands on the FT232 USB-serial
# adapter, and CR8-1 is the RTT-console image (build rdk-rzv2h:ipcc-raw-cr8_1)
# so the one probe is free to bridge its RTT block afterwards.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both.sh <cr8_0-sci4-elf> <cr8_1-elf>
#
# Env:
#   JLINK_SERIAL   Serial number of the authorized probe (required).
#   JLINK_GDB      Path to JLinkGDBServerCLExe (default: search PATH then
#                  /opt/SEGGER/JLink/JLinkGDBServerCLExe).
#   GDB            gdb-multiarch (default: search PATH).
#   GDB_PORT       GDB server port (default 50000; matches loadstart.gdb).
#
# After both loads report ENTRY/SET_PC, CR8-0 NSH is live on SCI4 and CR8-1 NSH
# is live on RTT. Bridge CR8-1 with rzv2h-ipc-demo-cr8_1-rtt.jlink and type into
# CR8-0 with rzv2h-ipc-demo-type-cr8_0-sci4.sh.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
# port_listening (ss/proc based: POSIX sh has no /dev/tcp, and a probe
# connect could consume the -singlerun GDB session). Its load_core is
# superseded by the local one below.
. "${HERE}/rzv2h-ipc-demo-jlink-lib.sh"
LOADSTART="${HERE}/rzv2h-ipc-hil-loadstart.gdb"

CR8_0_ELF="${1:-}"
CR8_1_ELF="${2:-}"
GDB_PORT="${GDB_PORT:-50000}"

DEV_CR8_0="R9A09G057H44_R8_0"
DEV_CR8_1="R9A09G057H44_R8_1"

if [ -z "${CR8_0_ELF}" ] || [ -z "${CR8_1_ELF}" ]; then
	echo "usage: JLINK_SERIAL=<probe-sn> $0 <cr8_0-sci4-elf> <cr8_1-elf>" >&2
	exit 2
fi
if [ -z "${JLINK_SERIAL:-}" ]; then
	echo "JLINK_SERIAL must identify the authorized probe" >&2
	exit 2
fi
for f in "${CR8_0_ELF}" "${CR8_1_ELF}" "${LOADSTART}"; do
	[ -f "${f}" ] || { echo "not found: ${f}" >&2; exit 2; }
done

if [ -n "${JLINK_GDB:-}" ]; then
	JLINK_GDB_BIN="${JLINK_GDB}"
elif command -v JLinkGDBServerCLExe >/dev/null 2>&1; then
	JLINK_GDB_BIN=$(command -v JLinkGDBServerCLExe)
elif [ -x /opt/SEGGER/JLink/JLinkGDBServerCLExe ]; then
	JLINK_GDB_BIN=/opt/SEGGER/JLink/JLinkGDBServerCLExe
else
	echo "JLinkGDBServerCLExe not found (set JLINK_GDB)" >&2
	exit 2
fi

if [ -n "${GDB:-}" ]; then
	GDB_BIN="${GDB}"
elif command -v gdb-multiarch >/dev/null 2>&1; then
	GDB_BIN=$(command -v gdb-multiarch)
else
	echo "gdb-multiarch not found (set GDB)" >&2
	exit 2
fi

# Load one core: start a single-run GDB server for its device, run loadstart,
# then wait for the server to exit so the probe is free for the next core.
load_core() {
	dev="$1"
	elf="$2"
	label="$3"

	echo "== ${label}: loading ${elf} via ${dev} =="
	"${JLINK_GDB_BIN}" -device "${dev}" -select "usb=${JLINK_SERIAL}" \
		-if SWD -speed auto -LocalhostOnly 1 -strict -singlerun \
		-timeout 3000 -powertarget 0 -port "${GDB_PORT}" -nogui &
	srv_pid=$!

	# Wait until the server is listening (or died).
	tries=0
	while ! port_listening "${GDB_PORT}"; do
		kill -0 "${srv_pid}" 2>/dev/null || { echo "GDB server for ${label} failed to start" >&2; exit 1; }
		tries=$((tries + 1))
		[ "${tries}" -gt 100 ] && { echo "GDB server for ${label} not listening" >&2; kill "${srv_pid}" 2>/dev/null || true; exit 1; }
		sleep 0.1
	done

	"${GDB_BIN}" -q -batch "${elf}" -x "${LOADSTART}"

	# -singlerun exits after the GDB session detaches; wait so the probe frees.
	wait "${srv_pid}" 2>/dev/null || true
	echo "== ${label}: loaded, probe released =="
}

# Order matters: initiator first so the responder adopts its recovery epoch.
load_core "${DEV_CR8_0}" "${CR8_0_ELF}" "CR8-0 (SCI4 console)"
load_core "${DEV_CR8_1}" "${CR8_1_ELF}" "CR8-1 (RTT console)"

cat <<EOF

Both images resident and running.
  CR8-0 NSH  -> SCI4 / FT232 USB-serial (e.g. /dev/ttyUSB0, 115200 8N1)
  CR8-1 NSH  -> RTT block 0x081E0000 (bridge on 127.0.0.1:19021)

Next:
  1. Bridge CR8-1 RTT:   JLinkExe -select usb=\${JLINK_SERIAL} -device ${DEV_CR8_1} \\
                             -if SWD -speed auto -AutoConnect 1 \\
                             -CommandFile ${HERE}/rzv2h-ipc-demo-cr8_1-rtt.jlink
     then connect a client to 127.0.0.1:19021 for the CR8-1 NSH prompt.
  2. Drive CR8-0:         ${HERE}/rzv2h-ipc-demo-type-cr8_0-sci4.sh /dev/ttyUSB0
EOF
