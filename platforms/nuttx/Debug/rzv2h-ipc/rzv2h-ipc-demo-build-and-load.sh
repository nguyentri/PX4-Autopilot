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
#   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-build-and-load.sh --load-only
#     (load previously built images without opening consoles)
#
# Env / options:
#   --build-only   Build both images and print their ELF paths; skip loading.
#   --load-only    Load and verify saved images; skip builds and consoles.
#   -jN | JOBS=N   Parallel make jobs (default: nproc).
#   OUT_DIR        Where to copy the built ELFs (default: the nuttx dir).
#   CR8_0_CONFIG   Override CR8-0 config (default rdk-rzv2h:ipcc-raw-cr8_0-sci4).
#   CR8_1_CONFIG   Override CR8-1 config (default rdk-rzv2h:ipcc-raw-cr8_1).
#   JLINK_SERIAL   Authorized probe serial (required unless --build-only);
#                  passed through to rzv2h-ipc-demo-load-both.sh.

set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
LOAD_BOTH="${HERE}/rzv2h-ipc-demo-load-both.sh"

usage() {
	cat <<'EOF'
Usage: rzv2h-ipc-demo-build-and-load.sh [--build-only | --load-only] [-jN]

Default: build both images, then RAM-load and verify CR8-0 followed by CR8-1.
  --build-only  Build and preserve both ELFs without touching hardware.
  --load-only   RAM-load and verify preserved ELFs without building.
  -h, --help    Show this help without building or connecting.

No mode starts an RTT bridge or interactive console.
JLINK_SERIAL is required for loading. OUT_DIR overrides the saved ELF directory;
CR8_0_CONFIG and CR8_1_CONFIG select their nuttx-<config>.elf filenames.
Defaults: rdk-rzv2h:ipcc-raw-cr8_0-sci4 and rdk-rzv2h:ipcc-raw-cr8_1.

After a successful load, open these separately from the repository root:
  platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-type-cr8_0-sci4.sh /dev/ttyUSB0
  platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_1 <exact-loaded-cr8_1-elf>
  nc 127.0.0.1 19021
Use the actual UART path, keep JLINK_SERIAL exported, and stop your debugger
before starting RTT. Stop the bridge when finished with nuttx-rtt-bridge.sh stop.
EOF
}

CR8_0_CONFIG="${CR8_0_CONFIG:-rdk-rzv2h:ipcc-raw-cr8_0-sci4}"
CR8_1_CONFIG="${CR8_1_CONFIG:-rdk-rzv2h:ipcc-raw-cr8_1}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 4)}"
BUILD_ONLY=0
LOAD_ONLY=0

for arg in "$@"; do
	case "${arg}" in
		--build-only) BUILD_ONLY=1 ;;
		--load-only) LOAD_ONLY=1 ;;
		-h|--help) usage; exit 0 ;;
		-j) echo "use -jN or JOBS=N" >&2; exit 2 ;;
		-j*) JOBS="${arg#-j}" ;;
		*) echo "unknown option: ${arg}" >&2; exit 2 ;;
	esac
done

[ "${BUILD_ONLY}${LOAD_ONLY}" != 11 ] || {
	echo "--build-only and --load-only are mutually exclusive" >&2; exit 2;
}

NUTTX=$(cd "${HERE}/../../NuttX/nuttx" && pwd)
OUT_DIR="${OUT_DIR:-${NUTTX}}"

if [ "${LOAD_ONLY}" -eq 1 ]; then
	[ -n "${JLINK_SERIAL:-}" ] || { echo "JLINK_SERIAL is required for --load-only" >&2; exit 2; }
else
	[ -x "${HERE}/../../NuttX/build.sh" ] || { echo "project build helper not found" >&2; exit 2; }
fi
[ -f "${LOAD_BOTH}" ] || { echo "loader not found: ${LOAD_BOTH}" >&2; exit 2; }

# Keep saved image files stable against this helper's concurrent rebuilds,
# including while loading without a build. The guarded loader owns the probe.
LOCK_HELPER="${HERE}/../../../../Tools/firmware_workspace/build_lock.sh"
[ -x "$LOCK_HELPER" ] || { echo "Missing shared build lock helper: $LOCK_HELPER" >&2; exit 2; }
if ! "$LOCK_HELPER" --check; then
  exec "$LOCK_HELPER" "$0" "$@"
fi

if [ "${LOAD_ONLY}" -eq 1 ]; then
	for config in "${CR8_0_CONFIG}" "${CR8_1_CONFIG}"; do
		case "${config}" in
			rdk-rzv2h:*) ;;
			*) echo "expected rdk-rzv2h:<config>: ${config}" >&2; exit 2 ;;
		esac
		elf="${OUT_DIR}/nuttx-${config#*:}.elf"
		[ -f "${elf}" ] || { echo "saved ELF not found: ${elf}; run --build-only first" >&2; exit 2; }
	done
	"${LOAD_BOTH}" "${OUT_DIR}/nuttx-${CR8_0_CONFIG#*:}.elf" "${OUT_DIR}/nuttx-${CR8_1_CONFIG#*:}.elf"
	echo "Both images loaded and verified; consoles were not started. See --help for SCI4 and RTT commands."
	exit 0
fi

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
