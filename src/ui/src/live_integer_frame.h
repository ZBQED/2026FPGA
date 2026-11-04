#ifndef LIVE_INTEGER_FRAME_V18_H
#define LIVE_INTEGER_FRAME_V18_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct li_topology {uint32_t crtc_id,connector_id,width,height,mode_clock_khz,htotal,vtotal,timestamp_monotonic;};
struct li_scan_receipt {uint64_t copy_fence_ns,event1_ns,event2_ns,observed1_ns,observed2_ns,irq_before,irq_after;uint32_t sequence1,sequence2,crtc_id,events_seen,verified;int32_t error;uint32_t same_fb_atomic_commits,atomic_test_only;};
int li_resize_800_640_bgr(const uint8_t*,uint32_t,uint8_t*,uint32_t);
int64_t li_logical_x_q20_to_capture(int64_t);
int li_draw_line_q20(uint8_t*,uint32_t,uint32_t,uint32_t,int64_t,int64_t,int64_t,int64_t,uint32_t,uint32_t);
int li_draw_point_q20(uint8_t*,uint32_t,uint32_t,uint32_t,int64_t,int64_t,uint32_t,uint32_t);
int li_scan_validate_fd(int,struct li_topology*);
int li_scan_after_copy(int,uint32_t,uint32_t,struct li_scan_receipt*);
struct li_scan_profile {uint64_t entered_ns,topology_done_ns,plane_request_done_ns,irq_before_done_ns,event1_done_ns,event2_done_ns,irq_after_done_ns,release_done_ns;};
int li_scan_after_copy_profile(int,uint32_t,uint32_t,struct li_scan_receipt*,struct li_scan_profile*);
uint64_t li_monotonic_ns(void);
#ifdef __cplusplus
}
#endif
#endif
