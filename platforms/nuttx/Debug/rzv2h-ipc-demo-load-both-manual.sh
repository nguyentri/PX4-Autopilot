#!/bin/sh
#
# Manual, step-at-a-time driver for the RZ/V2H single-probe IPC demo. Where the
# -auto loader does everything silently and self-verifies, this one hands you
# each step so you can open the RTT and SCI consoles yourself and watch them
# come up (useful for filming, or when something in the auto flow needs eyes).
#
# It does NOT invent new mechanics: load/verify reuse the same gdb scripts as
# the auto loader, `rtt` drives the existing rzv2h-ipc-demo-cr8_1-rtt.jlink, and
# `sci` hands off to rzv2h-ipc-demo-type-cr8_0-sci4.sh.
#
# Subcommands:
#   guide                         (default) print the full runbook + reset notes
#   load   <cr8_0-elf> <cr8_1-elf>   verbose RAM load of both cores
#   verify <cr8_0-elf> <cr8_1-elf>   halt/PC/resume check of both (non-destructive)
#   reset  <0|1> <elf>            soft-restart ONE core (re-run its image; no SoC reset)
#   rtt                          open the CR8-1 RTT bridge on 127.0.0.1:19021 (stays up)
#   sci    [port]                open the CR8-0 NSH on SCI4 (default /dev/ttyUSB0)
#
# Env: JLINK_SERIAL (required for load/verify/reset/rtt), plus the same
# JLINK_GDB / GDB / GDB_PORT / LOG_DIR overrides as the auto loader.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
. "${HERE}/rzv2h-ipc-demo-jlink-lib.sh"

LOADSTART="${HERE}/rzv2h-ipc-hil-loadstart.gdb"
VERIFY="${HERE}/rzv2h-ipc-hil-verify-resume.gdb"
GDB_PORT="${GDB_PORT:-50000}"
LOG_DIR="${LOG_DIR:-${HERE}/logs}"
VERBOSE=1                       # manual mode: show the gdb/server chatter

DEV_CR8_0="R9A09G057H44_R8_0"
DEV_CR8_1="R9A09G057H44_R8_1"
RTT_JLINK="${HERE}/rzv2h-ipc-demo-cr8_1-rtt.jlink"
SCI_SCRIPT="${HERE}/rzv2h-ipc-demo-type-cr8_0-sci4.sh"

need_serial() {
	[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL must identify the authorized probe" >&2; exit 2; }
}

find_jlinkexe() {
	if command -v JLinkExe >/dev/null 2>&1; then command -v JLinkExe
	elif [ -x /opt/SEGGER/JLink/JLinkExe ]; then echo /opt/SEGGER/JLink/JLinkExe
	else echo ""; fi
}

print_guide() {
	cat <<EOF
RZ/V2H single-probe IPC demo -- manual runbook
==============================================

Images (build first, e.g. via rzv2h-ipc-demo-build-and-load.sh --build-only):
  CR8-0  rdk-rzv2h:ipcc-raw-cr8_0-sci4   NSH on SCI4 -> FT232 /dev/ttyUSB0
  CR8-1  rdk-rzv2h:ipcc-raw-cr8_1        NSH on RTT block 0x081E0000

One physical J-Link = one active owner at a time, so the order is:
  1. $0 load  <cr8_0-elf> <cr8_1-elf>     # loads both to DDR (probe freed after)
  2. $0 verify <cr8_0-elf> <cr8_1-elf>    # optional: confirm both are running
  3. $0 rtt                               # CR8-1 NSH on 127.0.0.1:19021 (leave open)
  4. $0 sci  /dev/ttyUSB0                 # CR8-0 NSH on the UART (separate terminal)
Then run ipctest across /dev/ipcc1 from either prompt.

Resetting the board -- do you need FLASH?
------------------------------------------
These images are VOLATILE RAM loads over SWD (rzv2h-ipc-hil-loadstart.gdb): the
J-Link writes them straight to DDR and starts them. Nothing is written to flash.

  * A hardware reset (power cycle or the NRST button) WIPES DDR. Both images are
    gone and the board comes up with no NuttX. To use it again you must RELOAD
    (step 1). So: do NOT reset the board to "refresh" the demo -- just reload.
  * Making the firmware survive a hardware reset means programming the boot
    flash (xSPI) plus a boot chain that the boot ROM loads. That is a separate,
    much heavier effort and is NOT what this demo does (see flash_disabled_rzv
    in this directory -- flashing is intentionally off the RZ/V2H dev path here).
  * To restart just ONE core cleanly WITHOUT a SoC-wide reset, re-run its image:
        $0 reset 0 <cr8_0-elf>      # soft-restart CR8-0
        $0 reset 1 <cr8_1-elf>      # soft-restart CR8-1
    This re-runs loadstart (PC=__start, go); it does not 'monitor reset', whose
    SoC-wide scope is unmeasured while the peer image is still resident.

Probe hand-off: 'rtt' holds the J-Link for the RTT bridge, so run load/verify
first and keep only one probe owner alive at a time. 'sci' needs no probe.
EOF
}

cmd="${1:-guide}"
[ "$#" -gt 0 ] && shift || true

case "${cmd}" in
	guide|help|-h|--help)
		print_guide
		;;

	load)
		[ "$#" -ge 2 ] || { echo "usage: $0 load <cr8_0-elf> <cr8_1-elf>" >&2; exit 2; }
		need_serial; resolve_tools || exit 2; mkdir -p "${LOG_DIR}"
		for f in "$1" "$2" "${LOADSTART}"; do [ -f "${f}" ] || { echo "not found: ${f}" >&2; exit 2; }; done
		load_core "${DEV_CR8_0}" "$1" "CR8-0 (SCI4 console)" || exit 1
		load_core "${DEV_CR8_1}" "$2" "CR8-1 (RTT console)"  || exit 1
		echo "Both loaded. Next: '$0 rtt' and '$0 sci /dev/ttyUSB0'."
		;;

	verify)
		[ "$#" -ge 2 ] || { echo "usage: $0 verify <cr8_0-elf> <cr8_1-elf>" >&2; exit 2; }
		need_serial; resolve_tools || exit 2; mkdir -p "${LOG_DIR}"
		for f in "$1" "$2" "${VERIFY}"; do [ -f "${f}" ] || { echo "not found: ${f}" >&2; exit 2; }; done
		rc=0
		verify_core "${DEV_CR8_0}" "$1" "CR8-0 (SCI4 console)" || rc=1
		verify_core "${DEV_CR8_1}" "$2" "CR8-1 (RTT console)"  || rc=1
		exit "${rc}"
		;;

	reset)
		[ "$#" -ge 2 ] || { echo "usage: $0 reset <0|1> <elf>" >&2; exit 2; }
		need_serial; resolve_tools || exit 2; mkdir -p "${LOG_DIR}"
		[ -f "$2" ] || { echo "not found: $2" >&2; exit 2; }
		case "$1" in
			0) load_core "${DEV_CR8_0}" "$2" "CR8-0 (SCI4 console)" ;;
			1) load_core "${DEV_CR8_1}" "$2" "CR8-1 (RTT console)"  ;;
			*) echo "core must be 0 or 1" >&2; exit 2 ;;
		esac
		;;

	rtt)
		need_serial
		[ -f "${RTT_JLINK}" ] || { echo "not found: ${RTT_JLINK}" >&2; exit 2; }
		JLINKEXE=$(find_jlinkexe)
		[ -n "${JLINKEXE}" ] || { echo "JLinkExe not found (needed for the RTT bridge)" >&2; exit 2; }
		echo "Freeing probe, then opening CR8-1 RTT bridge on 127.0.0.1:19021 ..."
		echo "Leave this running; connect a client with: telnet 127.0.0.1 19021"
		preflight_probe_free || exit 1
		exec "${JLINKEXE}" -select "usb=${JLINK_SERIAL}" -device "${DEV_CR8_1}" \
			-if SWD -speed auto -AutoConnect 1 -CommandFile "${RTT_JLINK}"
		;;

	sci)
		[ -x "${SCI_SCRIPT}" ] || { echo "not found/executable: ${SCI_SCRIPT}" >&2; exit 2; }
		exec "${SCI_SCRIPT}" "${1:-/dev/ttyUSB0}"
		;;

	*)
		echo "unknown subcommand: ${cmd}" >&2
		echo "try: $0 guide" >&2
		exit 2
		;;
esac
