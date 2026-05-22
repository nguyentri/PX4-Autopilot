#!/usr/bin/env bash
#
# PX4 Renesas RA8/RZV — one-shot setup
#
# Usage:
#   ./build_setup.sh        # run as subprocess (env scrub takes effect only for cmake invocations done from here)
#   source ./build_setup.sh # propagate the env scrub into the current shell (recommended)
#
# Responsibilities:
#   1. Scrub leaked toolchain env vars (e2studio FSP env, vendor scripts) that
#      would override platforms/nuttx/cmake/Toolchain-arm-none-eabi.cmake and
#      break the CMake compiler test with "_exit / _write / _sbrk undefined".
#   2. Verify host dependencies (arm-none-eabi-gcc >= 9, cmake >= 3.20, ninja,
#      python3 >= 3.6, kconfiglib).
#   3. Initialize submodules (mainline + custom NuttX forks).
#   4. Print next-step commands.
#
# Idempotent: safe to re-run any time the shell looks suspicious.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

log()  { printf '\033[0;94m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[0;33m[setup]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[0;31m[setup]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. Scrub hostile env vars
# ---------------------------------------------------------------------------
HOSTILE_VARS=(
	CMAKE_C_COMPILER CMAKE_CXX_COMPILER CMAKE_ASM_COMPILER
	CC CXX LD AR AS NM OBJCOPY OBJDUMP STRIP RANLIB
	CFLAGS CXXFLAGS LDFLAGS ASFLAGS CPPFLAGS
)
scrubbed=()
for v in "${HOSTILE_VARS[@]}"; do
	if [ -n "${!v-}" ]; then
		scrubbed+=("$v")
		unset "$v"
	fi
done
if [ "${#scrubbed[@]}" -gt 0 ]; then
	warn "Unset leaked env vars (would override PX4 toolchain file): ${scrubbed[*]}"
	warn "If you sourced an e2studio FSP env script, run this with: source ./build_setup.sh"
else
	log "Env clean — no toolchain overrides present."
fi

# ---------------------------------------------------------------------------
# 2. Dependency checks
# ---------------------------------------------------------------------------
require_cmd() {
	command -v "$1" >/dev/null 2>&1 || { err "Missing required tool: $1"; return 1; }
}

check_arm_gcc() {
	require_cmd arm-none-eabi-gcc || {
		err "Install ARM GCC: https://docs.px4.io/main/en/dev_setup/dev_env.html"
		return 1
	}
	local ver
	ver=$(arm-none-eabi-gcc -dumpversion | cut -d. -f1)
	if [ "$ver" -lt 9 ]; then
		err "arm-none-eabi-gcc version $ver is too old (need >= 9)."
		return 1
	fi
	log "arm-none-eabi-gcc $(arm-none-eabi-gcc -dumpversion) at $(command -v arm-none-eabi-gcc)"
}

check_cmake() {
	require_cmd cmake || return 1
	local v major minor
	v=$(cmake --version | head -1 | awk '{print $3}')
	major=${v%%.*}; minor=${v#*.}; minor=${minor%%.*}
	if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 20 ]; }; then
		err "cmake $v is too old (need >= 3.20)."
		return 1
	fi
	log "cmake $v"
}

check_python() {
	require_cmd python3 || return 1
	local v
	v=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
	log "python3 $v"
	python3 -c 'import menuconfig' 2>/dev/null || {
		err "Python 'kconfiglib' missing — install: pip3 install --user kconfiglib"
		return 1
	}
}

check_ninja() {
	require_cmd ninja || require_cmd ninja-build || {
		err "ninja not found — install: sudo apt install ninja-build"
		return 1
	}
	log "ninja $(ninja --version 2>/dev/null || ninja-build --version)"
}

failures=0
check_arm_gcc || failures=$((failures+1))
check_cmake   || failures=$((failures+1))
check_python  || failures=$((failures+1))
check_ninja   || failures=$((failures+1))

if [ "$failures" -gt 0 ]; then
	err "$failures dependency check(s) failed. Fix the above and re-run."
	# Return rather than exit when sourced so the parent shell survives.
	if [ "${BASH_SOURCE[0]}" != "${0}" ]; then return 1; else exit 1; fi
fi

# ---------------------------------------------------------------------------
# 3. Submodules
# ---------------------------------------------------------------------------
log "Initializing PX4 submodules..."
git submodule update --init --recursive

log "Syncing custom Renesas NuttX submodule remotes..."
make sync_nuttx_submodules

# ---------------------------------------------------------------------------
# 4. Next steps
# ---------------------------------------------------------------------------
cat <<EOF

[setup] Done.

Next steps:
  ./build.sh                                 # build all Renesas targets
  ./build.sh --list                          # list available targets
  ./build.sh renesas_evk-ra8p1_default       # build one target
  make renesas_evk-ra8p1_default             # equivalent via Makefile

EOF
