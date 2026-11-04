#ifndef GESTURE_I8_BRIDGE_H
#define GESTURE_I8_BRIDGE_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Exact original model SHA required. Policies: fp32, pose39_i8, pose53_balanced16.
 * No global environment policy. No concurrent close/use, no handle use after
 * fork. Input/output byte counts must match tensor_info exactly. Return0 means
 * success; negative/error handle means stop and inspect gpi8p_error(). */
void* gpi8p_open(const char* model,int threads,const char* policy);
void gpi8p_close(void* handle);
const char* gpi8p_error(void);
int gpi8p_count(void* handle,int output);
int gpi8p_tensor_info(void*,int output,int ordinal,int* type,int* rank,int dims[8],uint64_t* bytes);
int gpi8p_input(void*,int ordinal,const void*,uint64_t bytes);
int gpi8p_invoke(void*);
int gpi8p_output(void*,int ordinal,void*,uint64_t bytes);
int gpi8p_policy_info(void*,int* bits,int* nodes,int* passes);
/* Cumulative successful hardware RUNs across the process-shared Device:
 * jobs, hardware_ns, input_bytes(including128B config/job), output_bytes. */
int gpi8p_hardware_stats(void*,uint64_t out[4]);
/* Cumulative per-original-layer: completed_evals, successful_jobs, hardware_ns,
 * total_ns, weight_quant_ns, input_quant_ns, run_wall_ns, dequant_ns.
 * For16bit, run_wall_ns includes all4transfers and exact int64 reconstruction.
 * Node ordinal follows generated_policy order filtered by explicit policy. */
int gpi8p_layer_stats(void*,int ordinal,int* original_node,uint64_t out[8]);
#ifdef __cplusplus
}
#endif
#endif

extern "C" int gpi8p_tensor_id(void*,int,int);

extern "C" int gpi8p_tensor_quantization(void*,int,int,float*,int*);
extern "C" int gpi8p_input_i8(void*,int,const int8_t*,uint64_t);
extern "C" int gpi8p_output_i8(void*,int,int8_t*,uint64_t);
