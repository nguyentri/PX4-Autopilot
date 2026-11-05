#!/usr/bin/env bash
#
# Build, verify and package the 1KW-Px4-Nuttx extension.
#
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$script_dir"

if [[ ! -d node_modules ]]; then
  npm ci
fi

npm run typecheck
npm run build

version="$(node -p 'require("./package.json").version')"
npm run package -- --out "$script_dir/1kw-px4-nuttx-$version.vsix" "$@"
cp -f "$script_dir/1kw-px4-nuttx-$version.vsix" "$script_dir/px4-nuttx-dashboard-$version.vsix"
exec npm test
