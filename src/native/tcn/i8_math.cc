#include "i8_math.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
namespace gesture_i8_pruned {
// Callers prove finite quotient magnitude <=32640 before this helper.
// Fraction after truncation preserves nextafter-half cases that x+0.5 loses.
static inline double RoundBounded(double value) {
  int32_t whole=static_cast<int32_t>(value);
  const double fraction=value-double(whole);
  if(fraction>=0.5)++whole;
  else if(fraction<=-0.5)--whole;
  return double(whole);
}
Span Validate(const Config& c) {
  gpi8p_job j{};std::copy(c.begin(),c.end(),j.config);j.timeout_ms=30000;
  const uint64_t ni=uint64_t(c[4])*c[5]*c[6],no=uint64_t(c[7])*c[8]*c[9];
  // Bound dimensions before products involving all kernel dimensions.
  for(int i=4;i<=11;++i) if(c[i]>1152) throw std::invalid_argument("ABI2 dimension overflow");
  const uint64_t nw=uint64_t(c[10])*c[11]*c[9]*(c[2]==0?c[6]:1);
  uint64_t cursor=64;j.offset[0]=uint32_t(cursor);cursor+=((ni+7)&~uint64_t(7))+64;
  if(cursor>GPI8_POOL_BYTES) throw std::invalid_argument("Input capacity");
  j.offset[1]=uint32_t(cursor);cursor+=((nw+7)&~uint64_t(7))+64;
  if(cursor>GPI8_POOL_BYTES) throw std::invalid_argument("Weight capacity");
  j.offset[3]=uint32_t(cursor);cursor+=((no*4+7)&~uint64_t(7))+64;
  Span s; if(cursor>GPI8_POOL_BYTES || gpi8p_validate(&j,GPI8_POOL_BYTES,s.bytes.data()))
    throw std::invalid_argument("Invalid canonical ABI2 RAW config");
  s.input=ni;s.weights=nw;s.output=no;return s;
}
ActivationRange QuantizeInput(const float *x,size_t n,std::vector<int8_t>* out) {
  if(!x || !out || !n || n>GPI8_MAX_TENSOR) throw std::invalid_argument("Invalid input span");
  ActivationRange p;p.lo=p.hi=double(x[0]);
  for(size_t i=0;i<n;++i) { double v=x[i];if(!std::isfinite(v))throw std::invalid_argument("Nonfinite activation");
    p.lo=std::min(p.lo,v);p.hi=std::max(p.hi,v); }
  if(p.lo==0 && p.hi==0) {p.scale=1;p.zero=0;}
  else {const double lo=std::min(p.lo,0.0),hi=std::max(p.hi,0.0);p.scale=(hi-lo)/255.;
    if(!std::isfinite(p.scale)||p.scale<=0)throw std::invalid_argument("Invalid activation scale");
    p.zero=int(std::max(-128.,std::min(127.,std::round(-128.-lo/p.scale))));}
  out->resize(n);
  for(size_t i=0;i<n;++i) { double q=RoundBounded(double(x[i])/p.scale)+p.zero;
    if(q< -128 || q>127)++p.clipped;(*out)[i]=int8_t(std::max(-128.,std::min(127.,q))); }
  return p;
}
Weights QuantizeWeights(const float* w,const Config& c) {
  Span s=Validate(c);if(!w)throw std::invalid_argument("Null weights");
  const size_t channels=c[9],reduction=s.weights/channels;
  Weights q;q.values.resize(s.weights);q.scales.resize(channels);
  for(size_t co=0;co<channels;++co) {
    double largest=0;
    for(size_t r=0;r<reduction;++r) {size_t i=c[2]==0?co*reduction+r:r*channels+co;
      double v=w[i];if(!std::isfinite(v))throw std::invalid_argument("Nonfinite weight");largest=std::max(largest,std::abs(v));}
    const double scale=largest>0?largest/127.:1.;q.scales[co]=scale;
    for(size_t r=0;r<reduction;++r) {size_t i=c[2]==0?co*reduction+r:r*channels+co;
      double v=std::round(double(w[i])/scale);q.values[i]=int8_t(std::max(-127.,std::min(127.,v)));}
  }
  return q;
}
void BalancedSplit(int32_t q,int8_t* high,int8_t* low) {
  if(!high||!low||q< -32639||q>32639)throw std::invalid_argument("Balanced signed16 bounds");
  const int v=q+128,h=v>=0?v/256:-((-v+255)/256),l=q-256*h;
  if(h< -127||h>127||l< -128||l>127)throw std::logic_error("Balanced radix overflow");
  *high=int8_t(h);*low=int8_t(l);
}
ActivationRange QuantizeInput16(const float* x,size_t n,std::vector<int8_t>* high,std::vector<int8_t>* low) {
  if(!x||!high||!low||!n||n>GPI8_MAX_TENSOR)throw std::invalid_argument("Invalid balanced16 input");
  ActivationRange p;p.lo=p.hi=x[0];double maximum=0;
  for(size_t i=0;i<n;++i){double v=x[i];if(!std::isfinite(v))throw std::invalid_argument("Nonfinite balanced16 input");
    p.lo=std::min(p.lo,v);p.hi=std::max(p.hi,v);maximum=std::max(maximum,std::abs(v));}
  p.scale=maximum>0?maximum/32639.:1.;p.zero=0;high->resize(n);low->resize(n);
  for(size_t i=0;i<n;++i){double q=RoundBounded(double(x[i])/p.scale);if(q< -32639||q>32639)++p.clipped;
    BalancedSplit(int32_t(std::max(-32639.,std::min(32639.,q))),&(*high)[i],&(*low)[i]);}
  return p;
}
BalancedWeights QuantizeWeights16(const float* w,const Config& c) {
  const Span s=Validate(c);if(!w)throw std::invalid_argument("Null balanced16 weights");
  const size_t channels=c[9],reduction=s.weights/channels;BalancedWeights q;
  q.high.resize(s.weights);q.low.resize(s.weights);q.scales.resize(channels);
  for(size_t co=0;co<channels;++co){double largest=0;
    for(size_t r=0;r<reduction;++r){size_t i=c[2]==0?co*reduction+r:r*channels+co;double v=w[i];
      if(!std::isfinite(v))throw std::invalid_argument("Nonfinite balanced16 weights");largest=std::max(largest,std::abs(v));}
    double scale=largest>0?largest/32639.:1.;q.scales[co]=scale;
    for(size_t r=0;r<reduction;++r){size_t i=c[2]==0?co*reduction+r:r*channels+co;
      BalancedSplit(int32_t(std::max(-32639.,std::min(32639.,std::round(double(w[i])/scale)))),&q.high[i],&q.low[i]);}
  }return q;
}
template<class Integer> void DequantizeImpl(const Integer* x,size_t n,int channels,double sx,const double* sw,
                const float* bias,int act,float* y) {
  if(!x||!sw||!bias||!y||!n||channels<1||channels>1152||n%channels||n>GPI8_MAX_TENSOR||
     !std::isfinite(sx)||sx<=0||(act!=0&&act!=1&&act!=3))throw std::invalid_argument("Invalid dequantization");
  for(int c=0;c<channels;++c)if(!std::isfinite(sw[c])||sw[c]<=0||!std::isfinite(bias[c]))
    throw std::invalid_argument("Nonfinite channel scale/bias");
  double scales[1152];
  for(int c=0;c<channels;++c)scales[c]=sx*sw[c];
  for(size_t base=0;base<n;base+=size_t(channels))for(int c=0;c<channels;++c) {
    const size_t i=base+size_t(c);double v=double(x[i])*scales[c]+double(bias[c]);
    if(act==1||act==3)v=std::max(0.,v);if(act==3)v=std::min(6.,v);
    if(!std::isfinite(v)||std::abs(v)>std::numeric_limits<float>::max())throw std::overflow_error("Nonfinite dequantized output");
    y[i]=float(v);}
}
void Dequantize(const int32_t* x,size_t n,int channels,double sx,const double* sw,const float* b,int a,float* y){DequantizeImpl(x,n,channels,sx,sw,b,a,y);}
void Dequantize64(const int64_t* x,size_t n,int channels,double sx,const double* sw,const float* b,int a,float* y){DequantizeImpl(x,n,channels,sx,sw,b,a,y);}
#ifdef GPI8_MATH_TEST_ONLY
void RawReference(const int8_t* x,const int8_t* w,const Config& c,int32_t* y) {
  const Span s=Validate(c);if(!x||!w||!y)throw std::invalid_argument("Null RAW tensor");
  const int hi=c[4],wi=c[5],ci=c[6],ho=c[7],wo=c[8],co=c[9],kh=c[10],kw=c[11],sh=c[12],sw=c[13],pt=c[14],pl=c[15],zx=int32_t(c[16]);
  for(int oy=0;oy<ho;++oy)for(int ox=0;ox<wo;++ox)for(int oc=0;oc<co;++oc){
    int64_t accumulator=0;
    for(int ky=0;ky<kh;++ky)for(int kx=0;kx<kw;++kx){int iy=oy*sh+ky-pt,ix=ox*sw+kx-pl;
      if(iy<0||iy>=hi||ix<0||ix>=wi)continue;
      if(c[2]==1)accumulator+=int64_t(int(x[(iy*wi+ix)*ci+oc])-zx)*int(w[(ky*kw+kx)*co+oc]);
      else for(int ic=0;ic<ci;++ic)accumulator+=int64_t(int(x[(iy*wi+ix)*ci+ic])-zx)*int(w[((oc*kh+ky)*kw+kx)*ci+ic]);}
    if(accumulator<INT32_MIN||accumulator>INT32_MAX)throw std::overflow_error("RAW INT32 overflow");
    y[(oy*wo+ox)*co+oc]=int32_t(accumulator);}
}
#endif
}
