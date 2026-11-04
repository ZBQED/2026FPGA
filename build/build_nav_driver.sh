#!/bin/sh
set -eu
: "${KERNEL_BUILD:?Set the matching configured target kernel build directory}"
CROSS_COMPILE=${CROSS_COMPILE-}
test "$#" -eq 1 || { echo 'usage: sh build/build_nav_driver.sh /absolute/new/output' >&2; exit 2; }
case "$1" in /*) ;; *) echo 'output must be an absolute new directory' >&2; exit 2;; esac
test ! -e "$1" || { echo 'output already exists; preserve it' >&2; exit 2; }
package=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p -- "$1"
cp "$package"/src/drivers/nav/*.c "$package"/src/drivers/nav/*.h "$1/"
cp "$package/src/drivers/nav/makefile" "$1/Makefile"
exec make -C "$KERNEL_BUILD" M="$1" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" ${CC:+CC="$CC"} modules
