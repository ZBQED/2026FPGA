#ifndef GESTURE_PL_CLIENT_H
#define GESTURE_PL_CLIENT_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
void *gp_open_device(const char *path);
/* The owner must join all gp_run/gp_get_stats calls before closing. Close must
 * not race with any access to this handle. Runs on a live handle serialize. */
void gp_close_device(void *handle);
int gp_run(void *handle, const float *input, const float *weights,
           const float *bias, float *output, const int *config);
const char *gp_last_error(void);
const char *gp_backend_name(void);
/* Actual hardware jobs, hardware ns, bytes copied to PL, bytes from PL.
 * An emulation build always reports ZERO hardware jobs and hardware ns. */
void gp_get_stats(void *handle, uint64_t result[4]);
#ifdef __cplusplus
}
#endif
#endif
