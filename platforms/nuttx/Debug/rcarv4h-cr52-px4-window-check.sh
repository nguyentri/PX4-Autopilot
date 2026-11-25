#!/usr/bin/env bash
# Check that every PT_LOAD segment of an R-Car V4H CR52-0 PX4 ELF lies in
# the single-core 9 MiB window (manifest device R8A779G3_CR52_0_PX4).
# The rcar manifest is a custom one, so the checker only inspects (exit 2,
# RESULT=INSPECTION_ONLY); U-Boot does the load, nothing is authorized here.
# Usage: rcarv4h-cr52-px4-window-check.sh <elf>. Exit 0 ok, 1 failed.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
elf="${1:?usage: $0 <elf>}"
out="$(python3 "${SCRIPT_DIR}/rzv2h-ipc-elf-allowlist.py" --elf "$elf" \
	--device R8A779G3_CR52_0_PX4 \
	--manifest "${SCRIPT_DIR}/rcarv4h-cr52-elf-allowlists.json" \
	--allow-unverified 2>&1)"
rc=$?
echo "$out"
if [ "$rc" -ne 2 ] || ! echo "$out" | grep -q '^RESULT=INSPECTION_ONLY' ||
   echo "$out" | grep -q ' DENY$\|RESULT=DENY'; then
	echo "Error: PX4 window check of '${elf}' failed (rc=${rc})." >&2
	exit 1
fi
echo "Window check: all PT_LOAD segments inside the R8A779G3_CR52_0_PX4 window."
