#!/bin/sh
#
# Build both RZ/V2H IPC-demo images, then load them with one J-Link probe.
#
# Convenience wrapper around the project NuttX build helper and the
# existing rzv2h-ipc-demo-load-both.sh loader, for the single-probe transport
# split demo:
#   CR8-0 -> rdk-rzv2h:ipcc-raw-cr8_0-sci4  (NSH on SCI4 / FT232 USB-serial)
#   CR8-1 -> rdk-rzv2h:ipcc-raw-cr8_1       (NSH on RTT block 0x081E0000)
#
# Each config uses the project clean build helper so switching
# between the two is clean; the resulting `nuttx` ELF is copied out under a
# per-config name before the next build overwrites it.
#
# Usage:
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-build-and-load.sh
#   ./rzv2h-ipc-demo-build-and-load.sh --build-only        # build, don't load
#
# Env / options:
#   --build-only   Build both images and print their ELF paths; skip loading.
#   -j N | JOBS=N  Parallel make jobs (default: nproc).
#   OUT_DIR        Where to copy the built ELFs (default: the nuttx dir).
#   CR8_0_CONFIG   Override CR8-0 config (default rdk-rzv2h:ipcc-raw-cr8_0-sci4).
#   CR8_1_CONFIG   Override CR8-1 config (default rdk-rzv2h:ipcc-raw-cr8_1).
#   JLINK_SERIAL   Authorized probe serial (required unless --build-only);
#                  passed through to rzv2h-ipc-demo-load-both.sh.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
NUTTX=$(cd "${HERE}/../../NuttX/nuttx" && pwd)
LOAD_BOTH="${HERE}/rzv2h-ipc-demo-load-both.sh"

CR8_0_CONFIG="${CR8_0_CONFIG:-rdk-rzv2h:ipcc-raw-cr8_0-sci4}"
CR8_1_CONFIG="${CR8_1_CONFIG:-rdk-rzv2h:ipcc-raw-cr8_1}"
OUT_DIR="${OUT_DIR:-${NUTTX}}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
BUILD_ONLY=0

for arg in "$@"; do
	case "${arg}" in
		--build-only) BUILD_ONLY=1 ;;
		-j) echo "use -jN or JOBS=N" >&2; exit 2 ;;
		-j*) JOBS="${arg#-j}" ;;
		*) echo "unknown option: ${arg}" >&2; exit 2 ;;
	esac
done

[ -x "${HERE}/../../NuttX/build.sh" ] || { echo "project build helper not found" >&2; exit 2; }
[ -f "${LOAD_BOTH}" ] || { echo "loader not found: ${LOAD_BOTH}" >&2; exit 2; }
mkdir -p "${OUT_DIR}"

# Build one board:config and copy its nuttx ELF to OUT_DIR/nuttx-<config>.elf.
# Echoes only the ELF path on stdout so callers can capture it; build chatter
# goes to stderr.
build_one() {
	config="$1"
	name=${config#*:}            # strip "board:" -> config-name
	elf="${OUT_DIR}/nuttx-${name}.elf"

	echo "== building ${config} (-j${JOBS}) ==" >&2
	case "${config}" in
		rdk-rzv2h:*) name=${config#*:} ;;
		*) echo "expected rdk-rzv2h:<config>: ${config}" >&2; return 2 ;;
	esac
	NUTTX_BUILD_JOBS="${JOBS}" "${HERE}/../../NuttX/build.sh" "${name}" >&2
	[ -f "${NUTTX}/nuttx" ] || { echo "build produced no nuttx ELF for ${config}" >&2; exit 1; }
	cp -f "${NUTTX}/nuttx" "${elf}"
	echo "== ${config} -> ${elf} ==" >&2
	echo "${elf}"
}

CR8_0_ELF=$(build_one "${CR8_0_CONFIG}")
CR8_1_ELF=$(build_one "${CR8_1_CONFIG}")

echo
echo "Built:"
echo "  CR8-0 (SCI4): ${CR8_0_ELF}"
echo "  CR8-1 (RTT):  ${CR8_1_ELF}"

if [ "${BUILD_ONLY}" -eq 1 ]; then
	echo
	echo "Load later with:"
	echo "  JLINK_SERIAL=<probe-sn> ${LOAD_BOTH} ${CR8_0_ELF} ${CR8_1_ELF}"
	exit 0
fi

echo
echo "== loading both cores (CR8-0 first) =="
exec "${LOAD_BOTH}" "${CR8_0_ELF}" "${CR8_1_ELF}"
