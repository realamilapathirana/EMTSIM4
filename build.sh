#!/bin/sh
# Build EMTSim with CMake (GCC or Clang) and run the tests: Linux and macOS.
# Usage: ./build.sh
set -e
cd "$(dirname "$0")"
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
