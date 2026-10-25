#!/usr/bin/env bash
# Cortex-Debug serverpath: keep the real server under the probe supervisor.
set -euo pipefail
WORKSPACE_TOOLS=$(cd -- "$(dirname -- "$0")/.." && pwd)
WORKSPACE_PYTHON=python3
SERVER_ARGS=()
for argument in "$@"; do
  case "$argument" in
    --firmware-python=*) WORKSPACE_PYTHON=${argument#--firmware-python=} ;;
    *) SERVER_ARGS+=("$argument") ;;
  esac
done
exec "$WORKSPACE_PYTHON" "${WORKSPACE_TOOLS}/firmware-workspace.py" jlink-server "${SERVER_ARGS[@]}"
