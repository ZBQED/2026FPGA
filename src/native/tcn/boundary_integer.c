/* All numerical operations are integer; parameters are compiled offline.
 * Caller executes the INT8 core/head graphs between these typed boundaries. */
#include <stdint.h>
#include <stddef.h>
typedef struct {
 int features,phases,core_zero,mask_one,core_output_zero,head_input_zero,head_output_zero;
 int64_t pool_multiplier;
 const int64_t *multiplier,*bias;
 const int32_t *order,*sign;
 const uint32_t *exp;
} Model;
#include "boundary_parameters.inc"
static int64_t round_div(int64_t n,int64_t d){return n<0?-((-n+d/2)/d):(n+d/2)/d;}
static int8_t clip8(int64_t n){return (int8_t)(n< -128?-128:n>127?127:n);}
static const Model *model(int profile){return profile==0?&primary:profile==1?&roof:NULL;}
static int valid_source(const Model*m,const uint8_t*mask,int t,int mirrored){
 for(int c=0;c<84;c++){int source=mirrored?m->order[m->features+c]-m->features:c;if(mask[t*m->features+source])return 1;}return 0;
}
int tcni_normalize(int profile,const int16_t*values,const uint8_t*mask,int mirrored,int8_t*output){
 const Model*m=model(profile);if(!m||!values||!mask||!output||(mirrored!=0&&mirrored!=1))return -1;
 int any=0;for(int t=0;t<32;t++)any|=valid_source(m,mask,t,0);if(!any)return -2;
 for(int t=0;t<32;t++)for(int c=0;c<m->features;c++){
  int source=mirrored?m->order[c]:c;int64_t value=values[t*m->features+source];if(mirrored)value*=m->sign[c];
  source=mirrored?m->order[m->features+c]-m->features:c;int present=mask[t*m->features+source];if(present>1)return -3;
  int64_t q=present?round_div(value*m->multiplier[c]+m->bias[c],(int64_t)1<<24)+m->core_zero:m->core_zero;
  output[t*2*m->features+c]=clip8(q);output[t*2*m->features+m->features+c]=(int8_t)(present?m->mask_one:m->core_zero);
 }return 0;
}
int tcni_pool(int profile,const int8_t*core,const uint8_t*mask,int mirrored,int8_t*output){
 const Model*m=model(profile);if(!m||!core||!mask||!output)return -1;int width=32/m->phases;
 for(int phase=0;phase<m->phases;phase++){
  int count=0;int64_t sum[64]={0};for(int t=phase*width;t<(phase+1)*width;t++)if(valid_source(m,mask,t,mirrored)){
   count++;for(int c=0;c<64;c++)sum[c]+=(int)core[t*64+c]-m->core_output_zero;
  }if(!count)count=1;
  for(int c=0;c<64;c++)output[c*m->phases+phase]=clip8(round_div(sum[c]*m->pool_multiplier,(int64_t)count*((int64_t)1<<24))+m->head_input_zero);
 }return 0;
}
int tcni_finalize(int profile,const int8_t*first,const int8_t*second,int16_t*logits,uint16_t*prob){
 const Model*m=model(profile);if(!m||!first||!second||!logits||!prob)return -1;int maximum=-10000,best=0;uint64_t den=0;
 for(int c=0;c<27;c++){logits[c]=(int16_t)((int)first[c]+(int)second[c]-2*m->head_output_zero);if(logits[c]>maximum){maximum=logits[c];best=c;}}
 for(int c=0;c<27;c++)den+=m->exp[maximum-logits[c]];
 for(int c=0;c<27;c++)prob[c]=(uint16_t)(((uint64_t)m->exp[maximum-logits[c]]*32768+den/2)/den);
 return best;
}
