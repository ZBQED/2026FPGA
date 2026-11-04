#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cc=${CC:-arm-linux-gnueabihf-gcc}
out=${1:?Specify an output directory}
mkdir -p "$out"
out=$(CDPATH= cd -- "$out" && pwd)
flags="-O3 -fPIC -shared -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -marm -ffp-contract=off -fno-fast-math"
for variant in hand_p hand_q; do
  cd "$root/src/native/$variant"
  source=full_hand.c
  if [ "$variant" = hand_q ]; then source=workspace_source.c; fi
  "$cc" -std=c11 $flags "$source" -lm -o "$out/lib${variant}.so"
done
cd "$root/src/native/person"
"$cc" -std=c11 -D_POSIX_C_SOURCE=200809L $flags -DYF2_PREPROC_IN_W=192 -DYF2_PREPROC_IN_H=192 -I. delivery_yolo_pc.c yf2_core.c yf2_decode.c yf2_preproc.c -lm -o "$out/libyf2_raw_pl.so"
cd "$root/src/native/nav"
"$cc" -std=c11 $flags hand_crop.c -lm -o "$out/libhand_crop.so"
"$cc" -std=c11 $flags gaussian3.c -lm -o "$out/libgaussian3.so"
cd "$root/src/native/capture"
"$cc" -std=c11 $flags camera_seqlock.c capture_timestamp.c -o "$out/libcamera_timed_arm.so"
"$cc" -std=c99 $flags -nostdlib "$root/src/native/tcn_frontend/resample_i64.c" -o "$out/libtcn_resample.so"
