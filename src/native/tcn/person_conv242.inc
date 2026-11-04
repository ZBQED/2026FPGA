/* Only Conv_242 is replaced. All other conv2d calls retain the exact shipped
 * conv_neon.h dispatcher. Existing requant and decoder arithmetic are reused. */
extern int yf2_owner_conv242_raw(const int8_t*,const int8_t*,int32_t*);
static int person_conv242(int8_t *buf,const yf2_layer_t *L) {
    if(strcmp(L->name,"Conv_242")||L->widx!=64||L->type!=1||L->k!=1||L->stride!=1||L->pad!=0||
       L->h_in!=12||L->w_in!=12||L->c_in!=288||L->h_out!=12||L->w_out!=12||L->c_out!=72||
       L->zp_in!=-128||L->zp_out!=-128||L->relu!=1)return -1;
    int32_t *raw=(int32_t*)malloc(41472);if(!raw)return -1;
    const int8_t *w=YF2_W_PTRS[64];
    if(yf2_owner_conv242_raw(buf+L->in_off,w,raw)) {free(raw);return -1;}
    int64_t corrected_bias[72];
    for(int o=0;o<72;o++) {
        int64_t sum=0;for(int c=0;c<288;c++)sum+=w[o*288+c];
        corrected_bias[o]=(int64_t)YF2_BIAS_PTRS[64][o]-128*sum;
    }
    for(int p=0;p<144;p++)for(int o=0;o<72;o++) {
        int64_t acc=(int64_t)raw[p*72+o]+corrected_bias[o];
        buf[L->out_off+p*72+o]=(int8_t)requant(acc,YF2_M_PTRS[64][o],YF2_SHIFT_PTRS[64][o],-128,1);
    }
    free(raw);return 0;
}
