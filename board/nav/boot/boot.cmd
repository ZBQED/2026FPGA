# One-time boot. Existing SD boot files and saved environment are unchanged.
setenv mgd_ok 0
mw.l 0x01f00000 0x01020304 1
crc32 0x01f00000 4 0x01f00004
if itest.l *0x01f00004 == 0xe951a406; then
  setenv mgd_fit_crc 0xbc8fc15c
  setenv mgd_bit_crc 0x9a6ab523
  setenv mgd_ok 1
else
  if itest.l *0x01f00004 == 0x06a451e9; then
    setenv mgd_fit_crc 0x5cc18fbc
    setenv mgd_bit_crc 0x23b56a9a
    setenv mgd_ok 1
  fi
fi
if test "${mgd_ok}" = "1"; then
  setenv mgd_ok 0
  if fatload mmc 0:1 0x10000000 medical_gesture/image.ub; then
    if itest.l ${filesize} == 0x4a302c; then
      crc32 0x10000000 ${filesize} 0x01f00008
      if itest.l *0x01f00008 == ${mgd_fit_crc}; then
        if iminfo 0x10000000; then
          setenv mgd_ok 1
        fi
      fi
    fi
  fi
fi
if test "${mgd_ok}" = "1"; then
  setenv mgd_ok 0
  if fatload mmc 0:1 0x02000000 medical_gesture/system.bit; then
    if itest.l ${filesize} == 0x3dbb6a; then
      crc32 0x02000000 ${filesize} 0x01f0000c
      if itest.l *0x01f0000c == ${mgd_bit_crc}; then
        if fpga loadb 0 0x02000000 ${filesize}; then
          setenv mgd_ok 1
        fi
      fi
    fi
  fi
fi
if test "${mgd_ok}" = "1"; then
  setenv bootargs 'console=ttyPS0,115200 cma=128M earlycon root=/dev/mmcblk0p2 rw rootwait'
  bootm 0x10000000
fi
echo MEDICAL_GESTURE_BOOT_STOPPED
