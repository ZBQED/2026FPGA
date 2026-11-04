#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out=${1:?Specify an output directory}
: "${TFLITE_INCLUDE:?TensorFlow Lite compatible headers required}"
: "${TFLITE_LIB:?Directory containing libgesture_tflite_pl_pointwise.so required}"
cc=${CC:-arm-linux-gnueabihf-gcc}
cxx=${CXX:-arm-linux-gnueabihf-g++}
mkdir -p "$out/objects"
out=$(CDPATH= cd -- "$out" && pwd)
cd "$root/src/native/tcn"
flags="-O2 -fPIC -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -marm -ffp-contract=off -fno-fast-math"
for src in i8_math.cc i8_client.cc sha256.cc i8_delegate.cc i8_bridge.cc shared_owner.cc raw_delegate.cc prelu_device.cc prelu_delegate.cc direct_device.cc host_unused_person_stub.cc tcn_bridge.cc; do
 "$cxx" -std=c++17 $flags -I"$TFLITE_INCLUDE" -I. -include limits -c "$src" -o "$out/objects/${src%.cc}.o"
done
"$cc" -std=c11 $flags -c boundary_integer.c -o "$out/objects/boundary_integer.o"
"$cxx" -shared "$out"/objects/*.o -L"$TFLITE_LIB" -lgesture_tflite_pl_pointwise -Wl,-rpath,'$ORIGIN' -Wl,-z,defs -Wl,--version-script,exports.map -lpthread -ldl -lm -o "$out/libgesture_lite_i8_v12.so"
