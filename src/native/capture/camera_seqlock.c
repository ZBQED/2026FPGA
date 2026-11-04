/* Read-only copy of qt_dual_display/src/CameraFrame.h triple-buffer frames.
 * GCC atomics are necessary on ARMv7; the Python GIL is not a memory barrier
 * against a different process. This helper never writes shared memory.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define MC_MAGIC UINT32_C(0x4d43414d)
#define MC_WIDTH 800u
#define MC_HEIGHT 480u
#define MC_BYTES (MC_WIDTH * MC_HEIGHT * 3u)
struct mc_header {
    uint32_t magic, sequence, width, height, stride;
    uint32_t slot_sequence[3];
    uint32_t reserved[8];
};
_Static_assert(sizeof(struct mc_header) == 64, "CameraFrameHeader ABI mismatch");

/* Returns 1=copied, 0=no new frame, 2=slot changed/busy, -1=size error,
 * -2=header format error. current_sequence is populated for all valid headers.
 * Both successful sequence values refer to the shared preview publication,
 * not the V4L2 driver's sequence (the original bridge does not export that).
 */
int mc_camera_copy(const void *mapping, size_t mapping_bytes,
                   void *destination, size_t destination_bytes,
                   uint32_t previous_sequence, uint32_t *copied_sequence,
                   uint32_t *current_sequence) {
    const struct mc_header *h = (const struct mc_header *)mapping;
    if (!mapping || !destination || !copied_sequence || !current_sequence ||
        mapping_bytes != sizeof(*h) + 3u * MC_BYTES || destination_bytes < MC_BYTES)
        return -1;
    const uint32_t sequence = __atomic_load_n(&h->sequence, __ATOMIC_ACQUIRE);
    *current_sequence = sequence;
    if (__atomic_load_n(&h->magic, __ATOMIC_RELAXED) != MC_MAGIC ||
        __atomic_load_n(&h->width, __ATOMIC_RELAXED) != MC_WIDTH ||
        __atomic_load_n(&h->height, __ATOMIC_RELAXED) != MC_HEIGHT ||
        __atomic_load_n(&h->stride, __ATOMIC_RELAXED) != MC_WIDTH * 3u)
        return -2;
    if (sequence == 0 || sequence == previous_sequence) return 0;
    const unsigned slot = sequence % 3u;
    const uint32_t before = __atomic_load_n(&h->slot_sequence[slot], __ATOMIC_ACQUIRE);
    if (before != sequence * UINT32_C(2)) return 2;
    const unsigned char *pixels = (const unsigned char *)(h + 1) + slot * MC_BYTES;
    memcpy(destination, pixels, MC_BYTES);
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    const uint32_t after = __atomic_load_n(&h->slot_sequence[slot], __ATOMIC_ACQUIRE);
    if (after != before) return 2;
    *copied_sequence = sequence;
    return 1;
}
