#!/bin/sh
# Compatibility entry point: use the guarded CR8-0 then CR8-1 loader.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
exec "${HERE}/rzv2h-ipc-demo-load-both-auto.sh" "$@"
