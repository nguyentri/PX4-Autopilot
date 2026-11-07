#!/bin/bash
#
# Program an RA8 (EVK-RA8P1 / FPB-RA8E1) on-chip flash from an ELF with
# JLinkExe, then reset and run. Load addresses come from the ELF; the
# generated flash_bin.jlink files carry a stale address and are not used.
# RA8 loading is still pending qualification: report what the board does.
#
# Usage: JLINK_SERIAL=<probe-sn> jlink-flash-ra8.sh [--verbose] <device> <elf>
#   device: R7KA8P1KF_CPU0 (EVK-RA8P1) or R7FA8E1AF (FPB-RA8E1)
# Exit:  0 programmed and running, 1 J-Link reported a failure, 2 usage.

set -euo pipefail

verbose=0
if [ "${1:-}" = "--verbose" ]; then
	verbose=1
	shift
fi
usage="usage: JLINK_SERIAL=<probe-sn> $0 [--verbose] <device> <elf>"
device="${1:-}"
elf="${2:-}"
if [ -z "${device}" ] || [ -z "${elf}" ]; then
	echo "${usage}" >&2
	exit 2
fi
[ -f "${elf}" ] || { echo "ELF not found: ${elf}" >&2; exit 2; }
[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL is not set" >&2; exit 2; }

jlink=$(command -v JLinkExe || echo /opt/SEGGER/JLink/JLinkExe)
[ -x "${jlink}" ] || { echo "JLinkExe not found" >&2; exit 2; }

cmd=$(mktemp)
log=$(mktemp)
trap 'rm -f "${cmd}" "${log}"' EXIT
cat >"${cmd}" <<EOF
r
h
loadfile ${elf}
r
g
qc
EOF

echo "Programming ${device} from ${elf}..."
rc=0
"${jlink}" -NoGui 1 -ExitOnError 1 -USB "${JLINK_SERIAL}" -Device "${device}" \
	-If SWD -Speed 4000 -AutoConnect 1 -CommandFile "${cmd}" >"${log}" 2>&1 || rc=$?
[ "${verbose}" -eq 0 ] || cat "${log}"

# JLinkExe can return 0 after a failed command, so check its log too.
markers="error|failed|cannot connect|could not"
if [ "${rc}" -ne 0 ] || grep -qiE "${markers}" "${log}"; then
	grep -iE "${markers}" "${log}" >&2 || true
	echo "FAIL: ${device} flash/run (exit ${rc}); rerun with --verbose for the full log." >&2
	exit 1
fi
echo "OK: ${device} programmed, reset and running."
