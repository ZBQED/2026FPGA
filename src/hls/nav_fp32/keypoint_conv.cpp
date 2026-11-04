#include "keypoint_conv.h"

static float activate(float v, int mode) {
#pragma HLS INLINE
    if (mode != KP_NONE && v < 0.0f) v = 0.0f;
    if (mode == KP_RELU6 && v > 6.0f) v = 6.0f;
    return v;
}

extern "C" int keypoint_conv_f32(const float *input, const float *weights,
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
    const bool direct_pointwise=mode==KP_CONV && kh==1 && kw==1 &&
        sh==1 && sw==1 && pt==0 && pl==0 && ih==oh && iw==ow;
    // Compute division once per invocation, outside every transfer loop.
    const int initial_y=start/ow, initial_x=start%ow;
    CHANNEL_TILE: for (int ob=0; ob<oc; ob+=KP_LANES) {
        const int lanes=oc-ob<KP_LANES ? oc-ob : KP_LANES;
        LOAD_BIAS: for (int lane=0; lane<lanes; ++lane) {
#pragma HLS PIPELINE II=1
            bbuf[lane]=bias[ob+lane];
        }
        ZERO_BIAS: for (int lane=lanes; lane<KP_LANES; ++lane) {
#pragma HLS PIPELINE II=1
            bbuf[lane]=0.0f;
        }
        if (mode==KP_CONV) {
            CONV_WEIGHT_LANE: for (int lane=0; lane<lanes; ++lane) {
#pragma HLS LOOP_FLATTEN off
                const int base=(ob+lane)*reduction;
                CONV_WEIGHT_BURST: for (int r=0; r<reduction; ++r) {
#pragma HLS PIPELINE II=1
                    wbuf[lane][r]=weights[base+r];
                }
            }
        } else {
            DW_WEIGHT_KERNEL: for (int r=0; r<reduction; ++r) {
#pragma HLS LOOP_FLATTEN off
                const int base=r*oc+ob;
                DW_WEIGHT_BURST: for (int lane=0; lane<lanes; ++lane) {
#pragma HLS PIPELINE II=1
                    wbuf[lane][r]=weights[base+lane];
                }
            }
        }
        ZERO_WEIGHT_LANE: for (int lane=lanes; lane<KP_LANES; ++lane) {
            ZERO_WEIGHT: for (int r=0; r<reduction; ++r) {
#pragma HLS PIPELINE II=1
                wbuf[lane][r]=0.0f;
            }
        }
        int row=initial_y, column=initial_x;
        PIXEL_TILE: for (int pb=0; pb<count; pb+=KP_PIXELS) {
            const int pixels=count-pb<KP_PIXELS ? count-pb : KP_PIXELS;
            if (direct_pointwise) {
                PW_PIXEL: for (int p=0; p<pixels; ++p) {
#pragma HLS LOOP_FLATTEN off
                    const int base=(start+pb+p)*ic;
                    PW_INPUT_BURST: for (int c=0; c<ic; ++c) {
#pragma HLS PIPELINE II=1
                        xbuf[p][c]=input[base+c];
                    }
                }
                PW_PAD_PIXEL: for (int p=pixels; p<KP_PIXELS; ++p) {
                    PW_ZERO: for (int c=0; c<ic; ++c) {
#pragma HLS PIPELINE II=1
                        xbuf[p][c]=0.0f;
                    }
                }
            } else {
                const int block_channels=mode==KP_CONV ? ic : KP_LANES;
                const int read_channels=mode==KP_CONV ? ic : lanes;
                const int channel_base=mode==KP_CONV ? 0 : ob;
                // Candidate V3a: scalar predicated reads in ONE flat pipeline.
                // V2 starts a separate short burst/loop for each kernel point;
                // the actual RGB/DW shapes only transfer 3/8 floats per call.
                // Carry counters/pointers to avoid division or multiplication
                // per sample, without changing the xbuf or shared MAC layout.
                const int input_row=iw*ic;
                const int pixel_step=sw*ic;
                const int pixel_row_wrap=sh*input_row-(ow-1)*pixel_step;
                const int kernel_row_wrap=input_row-(kw-1)*ic;
                const int sample_count=KP_PIXELS*kh*kw*block_channels;
                int pixel_iy=row*sh-pt, pixel_ix=column*sw-pl;
                int pixel_base=pixel_iy*input_row+pixel_ix*ic+channel_base;
                int iy=pixel_iy, ix=pixel_ix, base=pixel_base;
                int p=0, ky=0, kx=0, c=0, r=0;
                GENERAL_FLAT_LOAD: for (int n=0; n<sample_count; ++n) {
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=8 max=9216
                    const bool valid=p<pixels && iy>=0 && iy<ih &&
                        ix>=0 && ix<iw && c<read_channels;
                    xbuf[p][r]=valid ? input[base+c] : 0.0f;
                    ++r;
                    if (c+1<block_channels) {
                        ++c;
                    } else {
                        c=0;
                        if (kx+1<kw) {
                            ++kx; ++ix; base+=ic;
                        } else {
                            kx=0;
                            if (ky+1<kh) {
                                ++ky; ++iy; ix=pixel_ix; base+=kernel_row_wrap;
                            } else {
                                ky=0; ++p; r=0;
                                if (column+1==ow) {
                                    column=0; ++row;
                                    pixel_iy+=sh; pixel_ix=-pl;
                                    pixel_base+=pixel_row_wrap;
                                } else {
                                    ++column; pixel_ix+=sw; pixel_base+=pixel_step;
                                }
                                iy=pixel_iy; ix=pixel_ix; base=pixel_base;
                            }
                        }
                    }
                }
            }
            INIT_PIXEL: for (int p=0; p<KP_PIXELS; ++p) {
                INIT_LANE: for (int lane=0; lane<KP_LANES; ++lane) {
#pragma HLS UNROLL
                    acc[p][lane]=0.0f;
                }
            }
            // Identical v1 reduction order: kernel_y, kernel_x, input_c.
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
            STORE_PIXEL: for (int p=0; p<pixels; ++p) {
#pragma HLS LOOP_FLATTEN off
                const int base=(start+pb+p)*oc+ob;
                OUTPUT_BURST: for (int lane=0; lane<lanes; ++lane) {
#pragma HLS PIPELINE II=1
                    output[base+lane]=activate(acc[p][lane]+bbuf[lane],act);
                }
            }
        }
    }
    return 0;
}
