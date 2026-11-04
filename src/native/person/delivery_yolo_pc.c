/* PC bridge only. The copied delivery core, weights and arithmetic stay intact. */
#include "yf2_core.h"
#include "yf2_preproc.h"
#include <math.h>
#include <string.h>

#ifdef _WIN32
#define API __declspec(dllexport)
#else
#define API __attribute__((visibility("default")))
#endif

_Static_assert(YF2_PREPROC_IN_W == YF2_IN_W, "Preprocessing width must match model");
_Static_assert(YF2_PREPROC_IN_H == YF2_IN_H, "Preprocessing height must match model");

static int8_t workspace[YF2_BUF_TOTAL];
static int8_t input_q[YF2_IN_H * YF2_IN_W * 3];
static float feat16[22 * 22 * YF2_DEC_FEAT_CH];
static float feat32[11 * 11 * YF2_DEC_FEAT_CH];
static yf2_box_t raw[2048], keep[32];

API int yf2_pc_input_size(void) { return YF2_IN_W; }
API int yf2_pc_box_bytes(void) { return sizeof(yf2_box_t); }

API int yf2_pc_preprocess(const uint8_t *bgr, int width, int height,
                         int8_t *q, uint8_t *resized)
{
    return yf2_preproc_bgr888_to_q_dbg(bgr, width, height,
        YF2_LAYERS[0].s_in, YF2_LAYERS[0].zp_in, q, resized);
}

API int yf2_pc_decode(yf2_box_t *out,int capacity)
{
    if(!out||capacity<1)return -1;
    yf2_head_scale_in_t s16, s32;
    yf2_core_head_scale(workspace, feat16, feat32, &s16, &s32);
    int n = yf2_decode_scale_int8(&s16, yf2_dec_anchors, .4,
                                 feat16, raw, 2048);
    n += yf2_decode_scale_int8(&s32, yf2_dec_anchors, .4,
                              feat32, raw + n, 2048 - n);
    int count = yf2_nms(raw, n, .45, keep, 32);
    int valid = 0;
    /* Preserve main.c's post-NMS validation, including float clipping. */
    for (int i = 0; i < count && valid < capacity; ++i) {
        yf2_box_t b = keep[i];
        if (!isfinite(b.x1) || !isfinite(b.y1) || !isfinite(b.x2) ||
            !isfinite(b.y2) || !isfinite(b.score) || b.score < .4 ||
            b.score > 1.0f || b.x2 <= b.x1 || b.y2 <= b.y1) continue;
        b.x1 = fmaxf(0.0f, b.x1); b.y1 = fmaxf(0.0f, b.y1);
        b.x2 = fminf((float)(YF2_IN_W - 1), b.x2);
        b.y2 = fminf((float)(YF2_IN_H - 1), b.y2);
        if (b.x2 - b.x1 < 4.0f || b.y2 - b.y1 < 4.0f) continue;
        out[valid++] = b;
    }
    return valid;
}

API int yf2_pc_infer(const uint8_t *bgr, int width, int height,
                    yf2_box_t *out, int capacity)
{
    if (!bgr || !out || capacity < 1) return -1;
    if (yf2_pc_preprocess(bgr, width, height, input_q, NULL)) return -2;
    if (yf2_core_run(workspace, input_q)) return -3;
    return yf2_pc_decode(out,capacity);
}

API int yf2_pc_copy_heads(int8_t *out)
{
    const char *names[] = {"Conv_256", "Conv_257", "Conv_258",
                           "Conv_259", "Conv_260", "Conv_261"};
    int offset = 0;
    for (int i = 0; i < 6; ++i) {
        const yf2_layer_t *layer = yf2_core_layer(names[i]);
        int size = layer->h_out * layer->w_out * layer->c_out;
        memcpy(out + offset, workspace + layer->out_off, size);
        offset += size;
    }
    return offset;
}

API int yf2_pc_workspace_bytes(void) { return YF2_BUF_TOTAL; }
API int yf2_pc_infer_quantized(const int8_t *q) { return yf2_core_run(workspace, q); }
API int yf2_pc_copy_workspace(int8_t *out) { memcpy(out, workspace, YF2_BUF_TOTAL); return YF2_BUF_TOTAL; }

API int yf2_pc_clear_workspace(int value) { memset(workspace,value,sizeof(workspace));return 0; }
API int yf2_pc_decode_heads(const int8_t *heads,int bytes,yf2_box_t *out,int capacity) {
    const char *names[]={"Conv_256","Conv_257","Conv_258","Conv_259","Conv_260","Conv_261"};
    int total=0;
    for(int i=0;i<6;++i){const yf2_layer_t *l=yf2_core_layer(names[i]);total+=l->h_out*l->w_out*l->c_out;}
    if(!heads||bytes!=total)return -1;
    int off=0;
    for(int i=0;i<6;++i){const yf2_layer_t *l=yf2_core_layer(names[i]);int n=l->h_out*l->w_out*l->c_out;memcpy(workspace+l->out_off,heads+off,n);off+=n;}
    return yf2_pc_decode(out,capacity);
}
