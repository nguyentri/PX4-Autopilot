#!/bin/bash
# Wrapper to execute a command while holding the shared NuttX build lock.
set -eu

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${HERE}/../.." && pwd)"

export PYTHONPATH="${REPO_ROOT}/Tools:${PYTHONPATH:-}"
PYTHON="${PYTHON:-python3}"

if [ "${1:-}" = "--check" ]; then
  exec "${PYTHON}" -m firmware_workspace.locks check
fi
exec "${PYTHON}" -m firmware_workspace.locks exec "$@"
