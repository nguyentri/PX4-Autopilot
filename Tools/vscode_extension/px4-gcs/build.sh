#!/usr/bin/env bash
#
# Build, verify and package the Px4-GCS extension.
#
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$script_dir"

deps_dir="node_modules"
if [[ ! -d "$deps_dir" || package-lock.json -nt "$deps_dir/.package-lock.json" ]]; then
  npm ci
fi

npm run typecheck
npm run build

version="$(node -p 'require("./package.json").version')"
npm run package -- --out "$script_dir/px4-gcs-$version.vsix" "$@"
exec npm test
