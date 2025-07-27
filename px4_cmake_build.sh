#!/usr/bin/env bash

TARGET="$1"

if [ -z "$TARGET" ]; then
  echo "Usage: $0 <target_name>"
  exit 1
fi

rm -rf build/$TARGET
cmake -Bbuild/$TARGET -DCONFIG=$TARGET . -GNinja
cmake --build build/$TARGET
