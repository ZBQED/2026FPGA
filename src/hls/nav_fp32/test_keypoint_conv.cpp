#include "keypoint_conv.h"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <stdint.h>
#include <vector>

extern "C" int keypoint_conv_f32_reference(const float*,const float*,const float*,float*,const int*);

static bool differential(bool smoke) {
    const int channels[]={1,3,7,8,9,11,16,24,40,1152};
    const int kernels[]={1,2,3,5};
    uint32_t state=0x1927020;
    const int smoke_ids[]={0,1,60,63,64,65};
    int cases=smoke ? 6 : 70;
    for(int test_index=0;test_index<cases;++test_index) {
        int t=smoke ? smoke_ids[test_index] : test_index;
        int mode=t%2, ic=channels[t%10], oc=mode?ic:channels[(t+3)%9];
        int kh=kernels[(t/2)%4],kw=kernels[(t/7)%4];
        if(ic*kh*kw>KP_MAX_REDUCTION && mode==KP_CONV)kh=kw=1;
        int sh=(t/3)%2+1,sw=(t/5)%2+1;
        if(t%6==0) { mode=KP_CONV;kh=kw=sh=sw=1; }
        int ih=7+t%3,iw=9+t%4,oh=(ih+sh-1)/sh,ow=(iw+sw-1)/sw;
        int cfg[KP_CONFIG_WORDS]={1,mode,ih,iw,ic,oh,ow,oc,kh,kw,sh,sw,kh/2,kw/2,0,0,0};
        cfg[KP_ACTIVATION]=(t%3==0?KP_NONE:t%3==1?KP_RELU:KP_RELU6);
        cfg[KP_START]=(t*7)%(oh*ow);
        cfg[KP_COUNT]=std::min(oh*ow-cfg[KP_START], t%4==0?11:t%4==1?3:t%4==2?1:oh*ow);
        // Keep the original first60 cases unchanged; add pointer-carry edges.
        if(t>=60) {
            const int extra[10][KP_CONFIG_WORDS]={
                {1,1,3,512,9,3,512,9,3,3,1,1,1,1,0,510,5},
                {1,0,3,512,3,3,512,9,3,3,1,1,1,1,6,510,10},
                {1,1,258,258,7,128,128,7,3,3,2,2,0,0,1,126,10},
                {1,0,7,9,3,4,9,7,2,5,2,1,1,2,0,8,11},
                {1,1,1,1,1,1,1,1,5,5,1,1,2,2,6,0,1},
                {1,0,1,1,1152,1,1,1,1,1,2,2,0,0,1,0,1},
                {1,1,9,7,1152,5,7,1152,3,1,2,1,1,0,0,6,13},
                {1,0,6,9,16,3,5,17,2,2,2,2,1,1,6,14,1},
                {1,1,7,9,8,7,9,8,5,5,1,1,2,2,0,35,0},
                {1,0,7,9,7,7,9,9,1,1,1,1,0,0,1,8,10}
            };
            std::memcpy(cfg,extra[t-60],sizeof(cfg));
            mode=cfg[1];ih=cfg[2];iw=cfg[3];ic=cfg[4];oh=cfg[5];ow=cfg[6];oc=cfg[7];
            kh=cfg[8];kw=cfg[9];sh=cfg[10];sw=cfg[11];
        }
        size_t wn=(mode==KP_CONV?oc*kh*kw*ic:kh*kw*oc);
        std::vector<float>x(ih*iw*ic),w(wn),b(oc);
        std::vector<float>a(oh*ow*oc,-12345.f),r(a);
        std::vector<float>*arrays[]={&x,&w,&b};
        for(int k=0;k<3;++k)for(size_t i=0;i<arrays[k]->size();++i) {
            state=state*1664525u+1013904223u;
            (*arrays[k])[i]=(int(state%2053)-1026)/127.0f;
        }
        // HLS cosim marshals the declared m_axi depth, including unused cells.
        x.resize(KP_MAX_TENSOR_FLOATS);w.resize(KP_MAX_WEIGHT_FLOATS);b.resize(KP_MAX_CHANNELS);
        a.resize(KP_MAX_TENSOR_FLOATS,-12345.f);r=a;
        int sa=keypoint_conv_f32(x.data(),w.data(),b.data(),a.data(),cfg);
        int sr=keypoint_conv_f32_reference(x.data(),w.data(),b.data(),r.data(),cfg);
        if(sa!=0 || sr!=0 || std::memcmp(a.data(),r.data(),a.size()*sizeof(float))) {
            std::printf("V1_DIFFERENTIAL_FAILED case=%d mode=%d IC=%d OC=%d K=%dx%d status=%d/%d\n",t,mode,ic,oc,kh,kw,sa,sr);
            return false;
        }
    }
    std::printf("V1_DIFFERENTIAL_BITEXACT_PASSED cases=%d\n",cases);
    return true;
}

static bool read_array(FILE *f,std::vector<float> &v) {
    uint32_t n=0;if(fread(&n,4,1,f)!=1 || n>KP_MAX_TENSOR_FLOATS)return false;
    v.resize(n);return fread(v.data(),4,n,f)==n;
}
static int run_case(int id, bool smoke) {
    char name[100];std::snprintf(name,sizeof(name),"case_%03d.bin",id);
    FILE *f=fopen(name,"rb");
    if(!f) {std::snprintf(name,sizeof(name),"fixtures/case_%03d.bin",id);f=fopen(name,"rb");}
    if(!f)return -2;
    char magic[8];int cfg[KP_CONFIG_WORDS];
    bool ok=fread(magic,1,8,f)==8 && !std::memcmp(magic,"KPF32V1\0",8) && fread(cfg,4,KP_CONFIG_WORDS,f)==KP_CONFIG_WORDS;
    std::vector<float>x,w,b,expected;
    ok=ok&&read_array(f,x)&&read_array(f,w)&&read_array(f,b)&&read_array(f,expected);
    fclose(f);if(!ok)return -1;
    // Smoke covers first standard Conv, first pointwise and first depthwise.
    // Caller selects representative IDs from the generated manifest.
    if(smoke && id!=0 && id!=18 && id!=46)return 0;
    x.resize(KP_MAX_TENSOR_FLOATS);w.resize(KP_MAX_WEIGHT_FLOATS);b.resize(KP_MAX_CHANNELS);
    const float sentinel=-12345.0f;
    std::vector<float>actual(KP_MAX_TENSOR_FLOATS,sentinel);
    int status=keypoint_conv_f32(x.data(),w.data(),b.data(),actual.data(),cfg);
    double maximum=0;int failures=0;
    const int lo=cfg[KP_START]*cfg[KP_OC], hi=(cfg[KP_START]+cfg[KP_COUNT])*cfg[KP_OC];
    for(int i=0;i<(int)expected.size();++i) {
        if(i<lo||i>=hi) {if(actual[i]!=sentinel)++failures;continue;}
        double error=std::fabs(double(actual[i])-expected[i]);maximum=std::max(maximum,error);
        if(!std::isfinite(actual[i])||error>3e-4+2e-5*std::fabs(expected[i]))++failures;
    }
    std::printf("case=%03d mode=%d IC=%d OC=%d K=%dx%d S=%dx%d start=%d count=%d status=%d max_abs_error=%.9g failures=%d\n",
        id,cfg[1],cfg[4],cfg[7],cfg[8],cfg[9],cfg[10],cfg[11],cfg[15],cfg[16],status,maximum,failures);
    return status==0&&failures==0?0:-1;
}
int main(int argc,char **argv) {
    bool smoke=argc>1&&!std::strcmp(argv[1],"--smoke");
    bool ok=differential(smoke);int cases=0;
    const int selected[3]={0,18,46};
    for(int i=0;i<(smoke?3:1000);++i){int id=smoke?selected[i]:i;int r=run_case(id,smoke);if(r==-2&&!smoke)break;ok=ok&&r==0;++cases;}
    if(!smoke){
        int cfg[KP_CONFIG_WORDS]={};float sentinel=123.f;
        ok=ok&&keypoint_conv_f32(0,0,0,&sentinel,cfg)==-1&&sentinel==123.f;
    }
    std::printf("KEYPOINT_CONV_TEST_%s fixtures=%d\n",ok?"PASSED":"FAILED",cases);
    return ok?0:1;
}
