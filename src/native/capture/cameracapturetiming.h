#ifndef CAMERA_CAPTURE_TIMING_H
#define CAMERA_CAPTURE_TIMING_H
#include <stdint.h>
#define CameraTimingMagic 0x3954434du
#define CameraTimingTIM8 0x384d4954u
#define CameraTimingTIM9 0x394d4954u
// Metadata only. Slot seqlocks and previewSequence join this to camera.frame.
typedef struct CameraTimingSlot {
    uint32_t guard, previewSequence, driverSequence, flags;
    uint32_t timestampKind, selectionReason, reserved[2];
    uint64_t dequeueObservedNs, driverTimestampNs, captureSelectedNs, reserved64;
} CameraTimingSlot;
typedef struct CameraTimingMap {
    uint32_t magic, version, bytes, latestSequence, reserved[12];
    CameraTimingSlot entries[3];
} CameraTimingMap;
#ifdef __cplusplus
static_assert(sizeof(CameraTimingSlot) == 64 && sizeof(CameraTimingMap) == 256, "camera timing ABI");
#else
_Static_assert(sizeof(CameraTimingSlot) == 64 && sizeof(CameraTimingMap) == 256, "camera timing ABI");
#endif
#endif
