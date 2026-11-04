#include "keypoint_conv.h"

static float activate(float v, int mode) {
#pragma HLS INLINE
    if (mode != KP_NONE && v < 0.0f) v = 0.0f;
    if (mode == KP_RELU6 && v > 6.0f) v = 6.0f;
    return v;
}

extern "C" int keypoint_conv_f32_reference(const float *input, const float *weights,
                                 const float *bias, float *output, const int *config) {
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=gmem depth=2097152 max_read_burst_length=64 num_read_outstanding=8
#pragma HLS INTERFACE m_axi port=weights offset=slave bundle=gmem depth=1048576
#pragma HLS INTERFACE m_axi port=bias offset=slave bundle=gmem depth=1152
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=gmem depth=2097152 max_write_burst_length=64 num_write_outstanding=4
#pragma HLS INTERFACE m_axi port=config offset=slave bundle=gmem depth=17
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=bias bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=config bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
    int cfg[KP_CONFIG_WORDS];
#pragma HLS ARRAY_PARTITION variable=cfg complete
    for (int i=0; i<KP_CONFIG_WORDS; ++i) cfg[i]=config[i];
    const int mode=cfg[KP_MODE], ih=cfg[KP_IH], iw=cfg[KP_IW], ic=cfg[KP_IC];
    const int oh=cfg[KP_OH], ow=cfg[KP_OW], oc=cfg[KP_OC];
    const int kh=cfg[KP_KH], kw=cfg[KP_KW], sh=cfg[KP_SH], sw=cfg[KP_SW];
    const int pt=cfg[KP_PAD_TOP], pl=cfg[KP_PAD_LEFT], act=cfg[KP_ACTIVATION];
    const int start=cfg[KP_START], count=cfg[KP_COUNT];
    if (cfg[KP_ABI]!=KP_ABI_VERSION || mode<0 || mode>1 ||
        ih<1 || ih>512 || iw<1 || iw>512 || oh<1 || oh>512 || ow<1 || ow>512 ||
        ic<1 || ic>KP_MAX_CHANNELS || oc<1 || oc>KP_MAX_CHANNELS ||
        kh<1 || kh>5 || kw<1 || kw>5 || sh<1 || sh>2 || sw<1 || sw>2 ||
        pt<0 || pt>=kh || pl<0 || pl>=kw ||
        (act!=KP_NONE && act!=KP_RELU && act!=KP_RELU6) ||
        start<0 || count<0 || start>oh*ow || count>oh*ow-start ||
        ih*iw*ic>KP_MAX_TENSOR_FLOATS || oh*ow*oc>KP_MAX_TENSOR_FLOATS ||
        (mode==KP_DEPTHWISE && ic!=oc) ||
        (mode==KP_CONV && (kh*kw*ic>KP_MAX_REDUCTION || kh*kw*ic*oc>KP_MAX_WEIGHT_FLOATS)))
        return -1;
    if (!count) return 0;
    float xbuf[KP_PIXELS][KP_MAX_REDUCTION];
    float wbuf[KP_LANES][KP_MAX_REDUCTION];
    float acc[KP_PIXELS][KP_LANES];
    float bbuf[KP_LANES];
#pragma HLS ARRAY_PARTITION variable=xbuf cyclic factor=8 dim=2
#pragma HLS ARRAY_PARTITION variable=wbuf complete dim=1
#pragma HLS ARRAY_PARTITION variable=acc complete dim=0
#pragma HLS ARRAY_PARTITION variable=bbuf complete
#pragma HLS BIND_STORAGE variable=xbuf type=ram_2p impl=bram
#pragma HLS BIND_STORAGE variable=wbuf type=ram_2p impl=bram
    const int reduction=mode==KP_CONV ? kh*kw*ic : kh*kw;
    CHANNEL_TILE: for (int ob=0; ob<oc; ob+=KP_LANES) {
        LOAD_BIAS: for (int lane=0; lane<KP_LANES; ++lane) {
#pragma HLS PIPELINE II=1
            bbuf[lane]=ob+lane<oc ? bias[ob+lane] : 0.0f;
        }
        LOAD_WEIGHTS: for (int lane=0; lane<KP_LANES; ++lane) {
            for (int r=0; r<reduction; ++r) {
#pragma HLS PIPELINE II=1
                int addr=mode==KP_CONV ? (ob+lane)*reduction+r : r*oc+ob+lane;
                wbuf[lane][r]=ob+lane<oc ? weights[addr] : 0.0f;
            }
        }
        PIXEL_TILE: for (int pb=0; pb<count; pb+=KP_PIXELS) {
            LOAD_INPUT: for (int p=0; p<KP_PIXELS; ++p) {
                const int pos=start+pb+p, oy=pos/ow, ox=pos%ow;
                for (int ky=0; ky<kh; ++ky) for (int kx=0; kx<kw; ++kx) {
                    const int iy=oy*sh+ky-pt, ix=ox*sw+kx-pl;
                    const bool valid=pb+p<count && iy>=0 && iy<ih && ix>=0 && ix<iw;
                    const int load_channels=mode==KP_CONV ? ic : KP_LANES;
                    for (int c=0; c<load_channels; ++c) {
#pragma HLS PIPELINE II=1
                        const int ch=mode==KP_CONV ? c : ob+c;
                        const int r=(ky*kw+kx)*load_channels+c;
                        xbuf[p][r]=(valid && ch<ic) ? input[(iy*iw+ix)*ic+ch] : 0.0f;
                    }
                }
                for (int lane=0; lane<KP_LANES; ++lane) {
#pragma HLS UNROLL
                    acc[p][lane]=0.0f;
                }
            }
            MAC_REDUCTION: for (int r=0; r<reduction; ++r) {
                MAC_PIXELS: for (int p=0; p<KP_PIXELS; ++p) {
#pragma HLS PIPELINE II=1
                    MAC_LANES: for (int lane=0; lane<KP_LANES; ++lane) {
#pragma HLS UNROLL
                        float x=mode==KP_CONV ? xbuf[p][r] : xbuf[p][r*KP_LANES+lane];
                        float product=x*wbuf[lane][r];
                        acc[p][lane]=acc[p][lane]+product;
                    }
                }
            }
            STORE_OUTPUT: for (int p=0; p<KP_PIXELS; ++p) {
                for (int lane=0; lane<KP_LANES; ++lane) {
#pragma HLS PIPELINE II=1
                    if (pb+p<count && ob+lane<oc)
                        output[(start+pb+p)*oc+ob+lane]=activate(acc[p][lane]+bbuf[lane],act);
                }
            }
        }
    }
    return 0;
}

