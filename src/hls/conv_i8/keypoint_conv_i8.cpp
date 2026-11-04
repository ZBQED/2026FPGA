#include "keypoint_conv_i8.h"
#include "packed_dsp_exact.h"
#include <ap_int.h>
#include <hls_stream.h>
#ifndef __SYNTHESIS__
#include <cstdio>
#endif

namespace {
enum {W_BANKS=16,W_DEPTH=2048,X_BANKS=8,X_DEPTH=1024,Y_BANKS=16,Y_DEPTH=4096,TILE=64,MAX_R=1152};
typedef ap_uint<64> Word;
typedef ap_uint<69> Param;
typedef ap_uint<8> Byte;
struct Cfg {ap_uint<1> op;ap_uint<2> mode;ap_uint<1> prelu;ap_uint<10> hi,wi;ap_uint<11> ci;ap_uint<10> ho,wo;ap_uint<11> co;ap_uint<3> kh,kw;ap_uint<2> sh,sw;ap_uint<3> pt,pl;ap_int<9> zx,zo,amin,amax;ap_uint<15> r;ap_uint<12> rpack;};
struct Packet {ap_uint<512> raw;ap_uint<7> p0;ap_uint<11> oc;ap_uint<5> lanes;};
struct PWPacket {ap_uint<1024> raw;ap_uint<7> p0;ap_uint<11> oc;ap_uint<6> lanes;};
int minimum(int a,int b){return a<b?a:b;}
int maximum(int a,int b){return a>b?a:b;}
Word pack_load(const uint64_t* memory,int base,int n){
#pragma HLS INLINE
  int shift=(base&7)*8;Word value=memory[base>>3]>>shift;
  if(shift && (base&7)+n>8)value|=Word(memory[(base>>3)+1])<<(64-shift);
  if(n<8)value&=(Word(1)<<(n*8))-1;
  return value;
}
ap_int<8> byte_at(Word word,int lane){
#pragma HLS INLINE
  return ap_int<8>((word>>(lane*8)).range(7,0));
}
Word xget(Word x[X_BANKS][X_DEPTH],int at){
#pragma HLS INLINE
  return x[at&7][at>>3];
}
void xset(Word x[X_BANKS][X_DEPTH],int at,Word value){
#pragma HLS INLINE
  x[at&7][at>>3]=value;
}

// Per-channel table is an exhaustive A9 INT8 PReLU contract, indexed by raw
// uint8 bits. Loading only occurs before execution. No scales or float math.
void load_prelu_tables(const uint64_t* params,uint32_t offset,uint32_t channels,Word table[16][512]){
#pragma HLS INLINE off
#pragma HLS ARRAY_PARTITION variable=table complete dim=1
  PRELU_LOAD_LUT:for(uint32_t i=0;i<channels*32;++i){
#pragma HLS PIPELINE II=1
    ap_uint<8> channel=i>>5;ap_uint<9> address=(ap_uint<9>(channel>>4)<<5)+ap_uint<5>(i);
    table[int(channel&15)][int(address)]=params[offset+i];
  }
}

uint32_t prelu_lut(const uint64_t* input,const uint64_t* params,uint64_t* output,const uint32_t a[32],Word table[16][512]){
#pragma HLS INLINE off
  if(a[2]!=0||a[4]<1||a[4]>512||a[5]<1||a[5]>512||a[6]<1||a[6]>256||
     a[7]!=a[4]||a[8]!=a[5]||a[9]!=a[6]||a[10]!=1||a[11]!=1||a[12]!=1||a[13]!=1||
     a[14]||a[15]||a[16]||a[17]||a[18]||a[19])return KPI8_BAD_CONFIG;
  for(int i=24;i<32;++i)if(a[i])return KPI8_BAD_CONFIG;
  uint32_t count=a[4]*a[5]*a[6],words=(count+7)/8,channels=a[6];
  if(count>2097152||a[20]!=words||a[21]!=0||a[22]!=words||a[23]!=channels*32)return KPI8_BAD_CAPACITY;
  load_prelu_tables(params,0,channels,table);
  if((channels&7)==0){
    ap_uint<9> channel=0;
    PRELU_NHWC_WORDS:for(uint32_t i=0;i<words;++i){
#pragma HLS PIPELINE II=1
      Word input_word=input[i],low=0,high=0;
      PRELU_BANKS:for(int bank=0;bank<16;++bank){
#pragma HLS UNROLL
        const int lane=bank&7;ap_uint<8> value=input_word.range(lane*8+7,lane*8);
        ap_uint<9> address=(ap_uint<9>(channel>>4)<<5)+ap_uint<5>(value>>3);
        Word values=table[bank][int(address)];ap_uint<8> result=values>>(int(value&7)*8);
        if(bank<8)low.range(lane*8+7,lane*8)=result;else high.range(lane*8+7,lane*8)=result;
      }
      output[i]=channel[3]?high:low;
      ap_uint<10> next=ap_uint<10>(channel)+8;channel=next==channels?ap_uint<9>(0):ap_uint<9>(next);
    }
  }else{
    ap_uint<9> channel=0;uint32_t at=0;
    PRELU_GENERAL_WORDS:for(uint32_t i=0;i<words;++i){
      Word input_word=input[i],result_word=0;
      PRELU_GENERAL_BYTES:for(int lane=0;lane<8;++lane){
#pragma HLS PIPELINE II=1
        if(at<count){ap_uint<8> value=input_word.range(lane*8+7,lane*8);
          ap_uint<9> address=(ap_uint<9>(channel>>4)<<5)+ap_uint<5>(value>>3);
          Word values=table[int(channel&15)][int(address)];ap_uint<8> result=values>>(int(value&7)*8);
          result_word.range(lane*8+7,lane*8)=result;
          if(channel+1==channels)channel=0;else ++channel;
          ++at;
        }
      }
      output[i]=result_word;
    }
  }
  return KPI8_OK;
}

void load_weights(const uint64_t* memory,Word w[W_BANKS][W_DEPTH],const Cfg& c){
#pragma HLS INLINE off
  if(c.op==KPI8_CONV){
    if((c.r&7)==0){
      ap_uint<11> oc=0;ap_uint<8> g=0,rpack=c.rpack;int words=c.co*c.rpack;
      LOAD_W_CONTIGUOUS:for(int at=0;at<words;++at){
#pragma HLS PIPELINE II=1
        ap_uint<11> address=((oc>>5)*rpack+g)*2+(oc&1);w[(oc&31)>>1][address]=memory[at];
        if(g+1==rpack){g=0;++oc;}else ++g;
      }
      return;
    }
    LOAD_W_OC:for(int oc=0;oc<c.co;++oc){
      LOAD_W_PACK:for(int g=0;g<c.rpack;++g){
#pragma HLS PIPELINE II=1
        w[(oc&31)>>1][((oc>>5)*c.rpack+g)*2+(oc&1)]=pack_load(memory,oc*c.r+g*8,minimum(8,c.r-g*8));
      }
    }
  }else{
    // 1HWCO: when CO is word-aligned, one 64-bit DDR word supplies eight
    // adjacent channels for one tap. Transpose to the unchanged W bank layout.
    if((c.co&7)==0){
      const int packs=(int(c.kh)*int(c.kw)+7)/8;
      LOAD_DW8_OC:for(int oc=0;oc<c.co;oc+=8){
        LOAD_DW8_PACK:for(int g=0;g<packs;++g){
          Word values[8];
#pragma HLS ARRAY_PARTITION variable=values complete
          LOAD_DW8_ZERO:for(int lane=0;lane<8;++lane){
#pragma HLS UNROLL
            values[lane]=0;
          }
          LOAD_DW8_TAPS:for(int j=0;j<8;++j){
#pragma HLS PIPELINE II=1
            const int k=g*8+j;
            if(k<int(c.kh)*int(c.kw)){
              const Word channels=memory[(k*int(c.co)+oc)>>3];
              LOAD_DW8_LANES:for(int lane=0;lane<8;++lane){
#pragma HLS UNROLL
                values[lane].range(j*8+7,j*8)=channels.range(lane*8+7,lane*8);
              }
            }
          }
          LOAD_DW8_STORE:for(int lane=0;lane<8;++lane){
#pragma HLS UNROLL
            const int channel=oc+lane;
            w[channel&15][(channel>>4)*packs+g]=values[lane];
          }
        }
      }
      return;
    }
    // Generic non-word-aligned channel counts retain the original byte path.
    // Each bank holds one channel lane; eight consecutive taps share a word.
    LOAD_DW_OC:for(int oc=0;oc<c.co;++oc){
      LOAD_DW_PACK:for(int g=0;g<(c.kh*c.kw+7)/8;++g){
        Word value=0;
        LOAD_DW_TAPS:for(int j=0;j<8;++j){
#pragma HLS PIPELINE II=1
          int k=g*8+j;if(k<c.kh*c.kw){int at=k*c.co+oc;value.range(j*8+7,j*8)=ap_uint<8>(memory[at>>3]>>((at&7)*8));}
        }
        w[oc&15][(oc>>4)*((c.kh*c.kw+7)/8)+g]=value;
      }
    }
  }
}
void load_patch_rgb_rows(const uint64_t* input,Word x[X_BANKS][X_DEPTH],const Cfg& c,int first,int pixels){
#pragma HLS INLINE off
 static Word rows[420];static ap_int<11> loaded=-1;
#pragma HLS BIND_STORAGE variable=rows type=ram_2p impl=bram latency=2
 if(first==0)loaded=-1;
 const int row_words=int(c.wi)*3/8,r=int(c.kh)*int(c.kw)*3,padded=((r+7)/8)*8;int done=0;
 STEM_ROW_CHUNKS:while(done<pixels){
  ap_uint<20> linear=first+done;int oy=int(linear/c.wo),ox0=int(linear%c.wo),span=minimum(pixels-done,int(c.wo)-ox0);
  int need=minimum(int(c.hi)-1,oy*int(c.sh)-int(c.pt)+int(c.kh)-1);
  STEM_NEW_ROWS:while(int(loaded)<need){
   ++loaded;int slot=int(loaded)%5,base=int(loaded)*row_words;
   STEM_ROW_BURST:for(int word=0;word<row_words;++word){
#pragma HLS PIPELINE II=1
    rows[slot*84+word]=input[base+word];
   }
  }
  ap_uint<9> ybase[5];bool yvalid[5];
#pragma HLS ARRAY_PARTITION variable=ybase complete
#pragma HLS ARRAY_PARTITION variable=yvalid complete
  for(int ky=0;ky<5;++ky){int iy=oy*int(c.sh)-int(c.pt)+ky;yvalid[ky]=ky<int(c.kh)&&iy>=0&&iy<int(c.hi);ybase[ky]=yvalid[ky]?ap_uint<9>((iy%5)*84):ap_uint<9>(0);}
  ap_uint<10> ox=ox0;ap_uint<7> at_r=0;ap_uint<2> ic=0;ap_uint<3> ky=0,kx=0;Word packed=0;int base_word=done*padded/8,total=span*padded;
  STEM_CACHED_PATCH_BYTES:for(int at=0;at<total;++at){
#pragma HLS PIPELINE II=1
   ap_int<8> value=c.zx;bool active=int(at_r)<r;int ix=int(ox)*int(c.sw)-int(c.pl)+int(kx);
   if(active&&yvalid[int(ky)]&&ix>=0&&ix<int(c.wi)){int byte=ix*3+int(ic);Word word=rows[int(ybase[int(ky)])+(byte>>3)];value=byte_at(word,byte&7);}
   packed=(packed>>8)|(Word(ap_uint<8>(value))<<56);if((at&7)==7)xset(x,base_word+(at>>3),packed);
   bool last=int(at_r)==padded-1;
   if(last){at_r=0;ic=0;kx=0;ky=0;++ox;}
   else{++at_r;if(active){if(ic==2){ic=0;if(kx+1==c.kw){kx=0;++ky;}else ++kx;}else ++ic;}}
  }
  done+=span;
 }
}
void load_patch(const uint64_t* input,Word x[X_BANKS][X_DEPTH],const Cfg& c,int first,int pixels){
#pragma HLS INLINE off
  if(c.ci==3&&c.wi<=224&&((c.wi*3)&7)==0&&(c.kh==3||c.kh==5)&&(c.kw==3||c.kw==5)){load_patch_rgb_rows(input,x,c,first,pixels);return;}
  bool direct=c.kh==1&&c.kw==1&&c.sh==1&&c.sw==1&&c.pt==0&&c.pl==0&&c.hi==c.ho&&c.wi==c.wo;
  if(direct){
    if((c.ci&7)==0){
      int words=pixels*c.rpack,base=first*(c.ci/8);
      DIRECT_CONTIGUOUS_BURST:for(int at=0;at<words;++at){
#pragma HLS PIPELINE II=1
        xset(x,at,input[base+at]);
      }
      return;
    }
    DIRECT_PIXEL:for(int p=0;p<pixels;++p){
      DIRECT_PACK:for(int g=0;g<c.rpack;++g){
#pragma HLS PIPELINE II=1
        xset(x,p*c.rpack+g,pack_load(input,(first+p)*c.ci+g*8,minimum(8,c.ci-g*8)));
      }
    }
  }else{
    // One continuously running byte pipeline over all pixels/words. The
    // previous PATCH_BYTE invocation restarted/drained for each 8-byte pack.
    int padded_r=int(c.rpack)*8,total=pixels*padded_r;
    ap_uint<10> oy=first/int(c.wo),ox=first%int(c.wo);
    ap_uint<3> ky=0,kx=0;ap_uint<11> ic=0;ap_uint<15> r=0;int last=-1;
    const ap_uint<11> last_ic=c.ci-1;const ap_uint<3> last_kx=c.kw-1;
    const ap_uint<15> last_r=padded_r-1;const ap_uint<10> last_ox=c.wo-1;
    Word cached=0,packed=0;
    PATCH_CONTINUOUS_BYTES:for(int at=0;at<total;++at){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=8 max=73728
      ap_int<8> q=c.zx;
      bool active=r<c.r;
      if(active){
        int iy=oy*c.sh-c.pt+ky,ix=ox*c.sw-c.pl+kx;
        if(iy>=0&&iy<c.hi&&ix>=0&&ix<c.wi){
          int source=(iy*c.wi+ix)*c.ci+ic;
          if((source>>3)!=last){cached=input[source>>3];last=source>>3;}
          q=byte_at(cached,source&7);
        }
      }
      // After eight shifts byte0 is least significant and byte7 most.
      packed=(packed>>8)|(Word(ap_uint<8>(q))<<56);
      if((at&7)==7)xset(x,at>>3,packed);
      bool pixel_end=r==last_r;
      ap_uint<12> next_ic=ap_uint<12>(ic)+1;
      ap_uint<4> next_kx=ap_uint<4>(kx)+1;
      bool ic_wrap=ic==last_ic,kx_wrap=kx==last_kx;
      // A single next-state assignment, not tap-wrap then pixel-reset muxes.
      ic=(pixel_end||active&&ic_wrap)?ap_uint<11>(0):(active?ap_uint<11>(next_ic):ic);
      kx=(pixel_end||active&&ic_wrap&&kx_wrap)?ap_uint<3>(0):(active&&ic_wrap?ap_uint<3>(next_kx):kx);
      ky=pixel_end?ap_uint<3>(0):(active&&ic_wrap&&kx_wrap?ap_uint<3>(ky+1):ky);
      r=pixel_end?ap_uint<15>(0):ap_uint<15>(r+1);
      if(pixel_end){last=-1;if(ox==last_ox){ox=0;++oy;}else ++ox;}
    }
  }
}
void load_row(const uint64_t* input,Word x[X_BANKS][X_DEPTH],Word xsecond[X_BANKS][X_DEPTH],const Cfg& c,int row){
#pragma HLS INLINE off
  int words=c.wi*c.ci/8,slot=row%c.kh;
  ROW_BURST:for(int i=0;i<words;++i){
#pragma HLS PIPELINE II=1
    Word value=input[row*words+i];xset(x,slot*words+i,value);xset(xsecond,slot*words+i,value);
  }
}
struct SumPair {ap_int<32> first,second;};
ap_int<32> dot_original(Word xp,Word wp,ap_int<9> zx){
#pragma HLS INLINE
  ap_int<17> products[8];
#pragma HLS ARRAY_PARTITION variable=products complete
  for(int j=0;j<8;++j){
#pragma HLS UNROLL
    ap_int<9> value=ap_int<9>(byte_at(xp,j))-zx;ap_int<8> weight=byte_at(wp,j);ap_int<17> product=value*weight;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=3
    products[j]=product;
  }
  ap_int<32> a=products[0]+products[1],b=products[2]+products[3],d=products[4]+products[5],e=products[6]+products[7];return (a+b)+(d+e);
}
SumPair dot_pair(Word xp,Word wp0,Word wp1,int zx){
#pragma HLS INLINE
  ap_int<18> a[8],b[8];
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
  DOT_PACKED:for(int j=0;j<8;++j){
#pragma HLS UNROLL
    GQProducts pair=gq_conv_pair(ap_int<9>(byte_at(xp,j))-ap_int<9>(zx),byte_at(wp0,j),byte_at(wp1,j));a[j]=pair.first;b[j]=pair.second;
  }
  ap_int<32> a0=a[0]+a[1],a1=a[2]+a[3],a2=a[4]+a[5],a3=a[6]+a[7];
  ap_int<32> b0=b[0]+b[1],b1=b[2]+b[3],b2=b[4]+b[5],b3=b[6]+b[7];
  return {(a0+a1)+(a2+a3),(b0+b1)+(b2+b3)};
}
void load_dw4(Word x[X_BANKS][X_DEPTH],ap_uint<13> base,Word out[4]){
#pragma HLS INLINE
 Word read8[8];
#pragma HLS ARRAY_PARTITION variable=read8 complete
 for(int bank=0;bank<8;++bank){
#pragma HLS UNROLL
  ap_uint<3> delta=ap_uint<3>(bank)-ap_uint<3>(base);ap_uint<13> at=base+delta;read8[bank]=x[bank][int(at>>3)];
 }
 for(int g=0;g<4;++g){
#pragma HLS UNROLL
  out[g]=read8[int(ap_uint<3>(base+g))];
 }
}
void mac_stage(Word x[X_BANKS][X_DEPTH],Word xsecond[X_BANKS][X_DEPTH],Word w[W_BANKS][W_DEPTH],const Cfg& c,int pixels,int tile_x,int oy,hls::stream<PWPacket>& stream){
#pragma HLS INLINE off
  if(c.op==KPI8_CONV){
    PW_OC16_PACKED:for(int ob=0;ob<c.co;ob+=16){
      ap_int<32> accum[16];
#pragma HLS ARRAY_PARTITION variable=accum complete
      // g0 below defines every valid accumulator before it can be read.
      // A second outer initialization creates a redundant feedback mux after
      // HLS flattens the output-channel loop; the measured critical path was
      // exactly this pair of reset selects plus the accumulator addition.
      int p=0,g=0;int words=pixels*int(c.rpack);
      // One explicit pipeline over all pixels and reduction groups. A new
      // pixel resets its accumulator when its g0 dot reaches this stage.
      PW_PIXEL_REDUCTION:for(int at=0;at<words;++at){
#pragma HLS PIPELINE II=1
#pragma HLS LOOP_TRIPCOUNT min=1 max=8192
        Word value=xget(x,at);int address=((ob>>5)*c.rpack+g)*2;
        for(int pair=0;pair<8;++pair){
#pragma HLS UNROLL
          if(ob+pair*2<c.co){
            int bank=pair+((ob&16)>>1);Word w0=w[bank][address],w1=w[bank][address+1];
            SumPair dot=dot_pair(value,w0,w1,int(c.zx));
            accum[pair*2]=(g==0?ap_int<32>(0):accum[pair*2])+dot.first;
            accum[pair*2+1]=(g==0?ap_int<32>(0):accum[pair*2+1])+dot.second;
          }
        }
        if(g+1==c.rpack){
          PWPacket packet;packet.p0=p;packet.oc=ob;packet.lanes=minimum(16,c.co-ob);packet.raw=0;
          for(int lane=0;lane<16;++lane){
#pragma HLS UNROLL
            packet.raw.range(lane*32+31,lane*32)=ob+lane<c.co?ap_uint<32>(accum[lane]):ap_uint<32>(0);
          }
          stream.write(packet);g=0;++p;
        }else ++g;
      }
    }
  }else{
    ap_uint<8> ciwords=c.ci/8;ap_uint<14> line_words=c.wi*int(ciwords);ap_uint<13> ybase[5];bool yvalid[5];
#pragma HLS ARRAY_PARTITION variable=ybase complete
#pragma HLS ARRAY_PARTITION variable=yvalid complete
    for(int ky=0;ky<c.kh;++ky){int iy=oy*c.sh-c.pt+ky;yvalid[ky]=iy>=0&&iy<c.hi;ybase[ky]=yvalid[ky]?ap_uint<13>((iy%c.kh)*int(line_words)):ap_uint<13>(0);}
    DW_PIXEL_PAIR:for(int p=0;p<pixels;p+=2){
      ap_int<13> ixbase=ap_int<13>(tile_x+p)*ap_int<3>(c.sw)-ap_int<4>(c.pl);bool second=p+1<pixels;
      DW_OC32:for(int ob=0;ob<c.co;ob+=32){
        ap_int<32> a[32],b[32];
#pragma HLS ARRAY_PARTITION variable=a complete
#pragma HLS ARRAY_PARTITION variable=b complete
        for(int l=0;l<32;++l){
#pragma HLS UNROLL
          a[l]=0;b[l]=0;
        }
        DW_TAP_KY:for(ap_uint<3> ky=0;ky<c.kh;++ky){
          DW_TAP_KX:for(ap_uint<3> kx=0;kx<c.kw;++kx){
#pragma HLS LOOP_FLATTEN
#pragma HLS PIPELINE II=1
            ap_int<13> ix0=ixbase+ap_int<4>(kx),ix1=ix0+ap_int<3>(c.sw);int k=ky*c.kw+kx;
            bool valid0=yvalid[ky]&&ix0>=0&&ix0<ap_int<13>(c.wi),valid1=second&&yvalid[ky]&&ix1>=0&&ix1<ap_int<13>(c.wi);
            Word q0[4],q1[4];
#pragma HLS ARRAY_PARTITION variable=q0 complete
#pragma HLS ARRAY_PARTITION variable=q1 complete
            ap_uint<13> base0=ybase[ky]+ix0*ciwords+ap_uint<8>(ob/8),base1=ybase[ky]+ix1*ciwords+ap_uint<8>(ob/8);
            Word read0[4],read1[4];
#pragma HLS ARRAY_PARTITION variable=read0 complete
#pragma HLS ARRAY_PARTITION variable=read1 complete
            load_dw4(x,base0,read0);load_dw4(xsecond,base1,read1);
            for(int g=0;g<4;++g){
#pragma HLS UNROLL
              q0[g]=valid0&&ob+g*8<c.ci?read0[g]:Word(0);q1[g]=valid1&&ob+g*8<c.ci?read1[g]:Word(0);
            }
            DW_PACKED32:for(int l=0;l<32;++l){
#pragma HLS UNROLL
              ap_int<8> weight=ob+l<c.co?byte_at(w[l&15][((ob+l)>>4)*((c.kh*c.kw+7)/8)+(k>>3)],k&7):ap_int<8>(0);
              ap_int<8> left=valid0&&ob+l<c.co?byte_at(q0[l>>3],l&7):ap_int<8>(c.zx);
              ap_int<8> right=valid1&&ob+l<c.co?byte_at(q1[l>>3],l&7):ap_int<8>(c.zx);
              if(ob+l<c.co){GQProducts result=gq_dw_pixels(left,right,weight,ap_int<9>(c.zx));a[l]+=result.first;b[l]+=result.second;}
            }
          }
        }
        PWPacket packet;packet.p0=p;packet.oc=ob;packet.lanes=minimum(32,c.co-ob);packet.raw=0;
        for(int l=0;l<32;++l){
#pragma HLS UNROLL
          packet.raw.range(l*32+31,l*32)=ap_uint<32>(a[l]);
        }
        stream.write(packet);
        if(second){packet.p0=p+1;for(int l=0;l<32;++l){
#pragma HLS UNROLL
          packet.raw.range(l*32+31,l*32)=ap_uint<32>(b[l]);
        }stream.write(packet);}
      }
    }
  }
}
ap_int<8> requantize(ap_int<32> raw,Param parameter,const Cfg& c,bool& bad){
#pragma HLS INLINE off
  ap_int<32> bias=parameter.range(31,0);ap_int<32> mult=ap_uint<31>(parameter.range(62,32));ap_int<32> shift=ap_int<6>(parameter.range(68,63));
  ap_int<33> added=ap_int<33>(raw)+bias;if(added>2147483647LL||added< -2147483648LL)bad=true;
  ap_int<32> acc=added;ap_int<64> product=acc*mult;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=4
  ap_int<64> magnitude=product<0?ap_int<64>(-product):product;
  ap_int<33> high;if(product<0)high=-ap_int<33>((magnitude+1073741823LL)>>31);else high=(product+1073741824LL)>>31;
  int right=-int(shift);ap_int<34> value=high;
  if(right){
    if(c.op==KPI8_DEPTHWISE&&c.kh==5&&c.kw==5)value=(ap_int<34>(high)+(ap_int<34>(1)<<(right-1)))>>right;
    else{ap_uint<32> mask=(ap_uint<32>(1)<<right)-1,remainder=ap_uint<32>(high)&mask,threshold=(mask>>1)+(high<0?1:0);value=(high>>right)+(remainder>threshold?1:0);}
  }
  value+=c.zo;if(value<c.amin)value=c.amin;if(value>c.amax)value=c.amax;return ap_int<8>(value);
}
void write_piece(Byte y[Y_BANKS][Y_DEPTH],int byte_first,ap_uint<512> bits,int bytes){
#pragma HLS INLINE off
 int offset=byte_first&15,first=byte_first>>4,words=(offset+bytes+15)>>4;ap_uint<640> aligned=ap_uint<640>(bits)<<(offset*8);
 RAW_BYTE_BANKS:for(int i=0;i<words;++i){
#pragma HLS PIPELINE II=1
  ap_uint<128> piece=aligned>>(i*128);
  for(int bank=0;bank<16;++bank){
#pragma HLS UNROLL
   int at=i*16+bank;if(at>=offset&&at<offset+bytes)y[bank][first+i]=piece.range(bank*8+7,bank*8);
  }
 }
}
void write8_y(Byte y[Y_BANKS][Y_DEPTH],int byte_first,ap_uint<64> bits,int bytes){
#pragma HLS INLINE
 ap_uint<16> base=byte_first;
 for(int bank=0;bank<16;++bank){
#pragma HLS UNROLL
  ap_uint<4> delta=ap_uint<4>(bank)-ap_uint<4>(base);ap_uint<17> at=ap_uint<17>(base)+delta;
  if(int(delta)<bytes)y[bank][int(at>>4)]=bits>>(int(ap_uint<3>(delta))*8);
 }
}
void post_int8_work(Byte y[Y_BANKS][Y_DEPTH],Param q[8][256],Word table[16][512],const Cfg& c,int packets,hls::stream<Packet>& input,bool& bad){
#pragma HLS INLINE off
  Packet p;p.raw=0;p.p0=0;p.oc=0;p.lanes=0;
  bool lane_bad[8]={false,false,false,false,false,false,false,false};
#pragma HLS ARRAY_PARTITION variable=lane_bad complete
  POST_DIRECT_WORK:for(int at=0;at<packets*2;++at){
#pragma HLS PIPELINE II=1
    ap_uint<1> group=at&1;
    if(group==0)p=input.read();
    ap_uint<256> raw8=p.raw>>(int(group)*256);ap_uint<64> value8=0;
    POST_CONTINUOUS_LANES:for(int lane=0;lane<8;++lane){
#pragma HLS UNROLL
      int i=int(group)*8+lane;bool present=i<p.lanes;
      ap_int<32> raw=raw8.range(lane*32+31,lane*32);
      Param parameter=present?q[lane][(int(p.oc)>>3)+int(group)]:Param(0);
      bool invalid=false;ap_int<8> value=present?requantize(raw,parameter,c,invalid):ap_int<8>(0);
      lane_bad[lane]=lane_bad[lane]|invalid;value8.range(lane*8+7,lane*8)=ap_uint<8>(value);
    }
    if(c.prelu){
      ap_uint<64> halves[2];
#pragma HLS ARRAY_PARTITION variable=halves complete
      for(int part=0;part<2;++part){
#pragma HLS UNROLL
        halves[part]=0;
      }
      FUSED_CONTINUOUS_PRELU_BANKS:for(int bank=0;bank<16;++bank){
#pragma HLS UNROLL
        const int lane=bank&7;ap_uint<8> value=value8.range(lane*8+7,lane*8);
        ap_uint<9> address=(ap_uint<9>(p.oc>>4)<<5)+ap_uint<5>(value>>3);
        Word values=table[bank][int(address)];ap_uint<8> result=values>>(int(value&7)*8);
        halves[bank>>3].range(lane*8+7,lane*8)=result;
      }
      value8=halves[int(group)];
    }
    int valid=minimum(8,maximum(0,int(p.lanes)-int(group)*8));write8_y(y,int(p.p0)*int(c.co)+int(p.oc)+int(group)*8,value8,valid);
  }
  bad=(lane_bad[0]|lane_bad[1])|(lane_bad[2]|lane_bad[3])|(lane_bad[4]|lane_bad[5])|(lane_bad[6]|lane_bad[7]);
}
void post_stage(Byte y[Y_BANKS][Y_DEPTH],Param q[8][256],Word table[16][512],const Cfg& c,int pixels,hls::stream<Packet>& stream,bool& bad){
#pragma HLS INLINE off
  int packets=((c.co+15)/16)*pixels;bad=false;
  if(c.mode==KPI8_OUT_INT8)post_int8_work(y,q,table,c,packets,stream,bad);
  else{
    POST_RAW_PACKET:for(int i=0;i<packets;++i){
      Packet p=stream.read();write_piece(y,(int(p.p0)*int(c.co)+int(p.oc))*4,p.raw,int(p.lanes)*4);
    }
  }
}
void unpack_pw32(const Cfg& c,int pixels,hls::stream<PWPacket>& input,hls::stream<Packet>& output){
#pragma HLS INLINE off
  PWPacket wide;bool high=false;
  PW32_UNPACK:for(int i=0;i<((int(c.co)+15)/16)*pixels;++i){
#pragma HLS PIPELINE II=1
    if(!high)wide=input.read();
    Packet p;p.p0=wide.p0;p.oc=wide.oc+(high?16:0);p.lanes=high?int(wide.lanes)-16:minimum(16,int(wide.lanes));
    p.raw=high?ap_uint<512>(wide.raw.range(1023,512)):ap_uint<512>(wide.raw.range(511,0));
    output.write(p);high=!high&&wide.lanes>16;
  }
}
void compute_tile(Word x[X_BANKS][X_DEPTH],Word xsecond[X_BANKS][X_DEPTH],Word w[W_BANKS][W_DEPTH],Byte y[Y_BANKS][Y_DEPTH],Param q[8][256],Word table[16][512],const Cfg& c,int pixels,int tile_x,int oy,bool& bad){
#pragma HLS INLINE off
#pragma HLS DATAFLOW
  hls::stream<PWPacket> wide;
  hls::stream<Packet> stream;
#pragma HLS STREAM variable=wide depth=2
#pragma HLS STREAM variable=stream depth=2
#pragma HLS BIND_STORAGE variable=wide type=fifo impl=lutram
#pragma HLS BIND_STORAGE variable=stream type=fifo impl=lutram
  mac_stage(x,xsecond,w,c,pixels,tile_x,oy,wide);unpack_pw32(c,pixels,wide,stream);post_stage(y,q,table,c,pixels,stream,bad);
}
void store_tile(uint64_t* output,Byte y[Y_BANKS][Y_DEPTH],int byte_first,int bytes){
#pragma HLS INLINE off
 OUTPUT_CONTIGUOUS_BURST:for(int i=0;i<(bytes+7)/8;++i){
#pragma HLS PIPELINE II=1
  Byte row[16];
#pragma HLS ARRAY_PARTITION variable=row complete
  for(int bank=0;bank<16;++bank){
#pragma HLS UNROLL
   row[bank]=y[bank][i>>1];
  }
  Word value=0;
  for(int lane=0;lane<8;++lane){
#pragma HLS UNROLL
   value.range(lane*8+7,lane*8)=i*8+lane<bytes?row[((i&1)<<3)+lane]:Byte(0);
  }
  output[(byte_first>>3)+i]=value;
 }
}
// Numerical compatibility for valid generic RAW jobs outside fixed-model
// resident bounds. Reuses DDR directly, never allocates a second full cache.
uint32_t generic_raw(const uint64_t* input,const uint64_t* weights,uint64_t* output,const Cfg& c){
#pragma HLS INLINE off
  Word packed=0;int out_index=0;
  for(int oy=0;oy<c.ho;++oy)for(int ox=0;ox<c.wo;++ox)for(int oc=0;oc<c.co;++oc){
    ap_int<32> acc=0;
    for(int ky=0;ky<c.kh;++ky)for(int kx=0;kx<c.kw;++kx){int iy=oy*c.sh-c.pt+ky,ix=ox*c.sw-c.pl+kx;
      if(iy>=0&&iy<c.hi&&ix>=0&&ix<c.wi){int terms=c.op?1:int(c.ci);
        for(int j=0;j<terms;++j){int ic=c.op?oc:j,at=(iy*c.wi+ix)*c.ci+ic,wt=c.op?int((ky*c.kw+kx)*c.co+oc):int(((oc*c.kh+ky)*c.kw+kx)*c.ci+ic);
          ap_int<9> x=ap_int<9>(byte_at(input[at>>3],at&7))-ap_int<9>(c.zx);ap_int<8> w=byte_at(weights[wt>>3],wt&7);acc+=x*w;}
      }
    }
    packed.range((out_index&1)*32+31,(out_index&1)*32)=ap_uint<32>(acc);if(out_index&1)output[out_index>>1]=packed;++out_index;
  }
  if(out_index&1){packed.range(63,32)=0;output[out_index>>1]=packed;}return KPI8_OK;
}
}

extern "C" uint32_t keypoint_conv_i8(const uint64_t* input,const uint64_t* weights,const uint64_t* params,uint64_t* output,const uint64_t* config){
#pragma HLS INTERFACE m_axi port=input offset=slave bundle=gmem depth=262144 max_read_burst_length=64 max_write_burst_length=64 num_read_outstanding=8 num_write_outstanding=8
#pragma HLS INTERFACE m_axi port=weights offset=slave bundle=gmem depth=131072 max_read_burst_length=64 max_write_burst_length=64 num_read_outstanding=8 num_write_outstanding=8
#pragma HLS INTERFACE m_axi port=params offset=slave bundle=gmem depth=8704 max_read_burst_length=64 max_write_burst_length=64 num_read_outstanding=8 num_write_outstanding=8
#pragma HLS INTERFACE m_axi port=output offset=slave bundle=gmem depth=1048576 max_read_burst_length=64 max_write_burst_length=64 num_read_outstanding=8 num_write_outstanding=8
#pragma HLS INTERFACE m_axi port=config offset=slave bundle=gmem depth=16 max_read_burst_length=64 max_write_burst_length=64 num_read_outstanding=8 num_write_outstanding=8
#pragma HLS INTERFACE s_axilite port=input bundle=control
#pragma HLS INTERFACE s_axilite port=weights bundle=control
#pragma HLS INTERFACE s_axilite port=params bundle=control
#pragma HLS INTERFACE s_axilite port=output bundle=control
#pragma HLS INTERFACE s_axilite port=config bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
  uint32_t a[32];
#pragma HLS ARRAY_PARTITION variable=a complete
  for(int i=0;i<16;++i){Word v=config[i];a[i*2]=v.range(31,0);a[i*2+1]=v.range(63,32);}
  if(a[0]!=KPI8_MAGIC||a[1]!=KPI8_ABI)return KPI8_BAD_ABI;
  Word prelu_table[16][512];
#pragma HLS ARRAY_PARTITION variable=prelu_table complete dim=1
#pragma HLS BIND_STORAGE variable=prelu_table type=ram_s2p impl=bram latency=2
#pragma HLS ALLOCATION function instances=load_prelu_tables limit=1
  if(a[3]==KPI8_OUT_PRELU_LUT)return prelu_lut(input,params,output,a,prelu_table);
  if(a[3]>2)return KPI8_UNSUPPORTED;
  if(a[24]>1||(a[24]&&(a[3]!=1||a[9]>256)))return KPI8_BAD_CONFIG;
  for(int i=25;i<32;++i)if(a[i])return KPI8_BAD_CONFIG;
  if(a[24]&&a[23]!=34*a[9])return KPI8_BAD_CAPACITY;
  if(a[2]>1||a[4]<1||a[4]>512||a[5]<1||a[5]>512||a[6]<1||a[6]>1152||a[7]<1||a[7]>512||a[8]<1||a[8]>512||a[9]<1||a[9]>1152||a[10]<1||a[10]>5||a[11]<1||a[11]>5||a[12]<1||a[12]>2||a[13]<1||a[13]>2||a[14]>=a[10]||a[15]>=a[11]||int32_t(a[16])< -128||int32_t(a[16])>127||(a[2]&&a[6]!=a[9]))return KPI8_BAD_CONFIG;
  if(a[3]&&(int32_t(a[17])< -128||int32_t(a[17])>127||int32_t(a[18])< -128||int32_t(a[19])>127||int32_t(a[18])>int32_t(a[19])))return KPI8_BAD_CONFIG;
  Cfg c={a[2],a[3],a[24],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15],int32_t(a[16]),int32_t(a[17]),int32_t(a[18]),int32_t(a[19]),0,0};
  uint32_t ni=c.hi*c.wi*c.ci,no=c.ho*c.wo*c.co,nw=c.kh*c.kw*c.co*(c.op?ap_uint<11>(1):c.ci),out_bytes=no*(c.mode?1:4);
  if(ni>2097152||no>2097152||nw>1048576||a[20]<(ni+7)/8||a[21]<(nw+7)/8||a[22]<(out_bytes+7)/8){
#ifndef __SYNTHESIS__
    std::printf("capacity ni=%u no=%u nw=%u out_bytes=%u caps=%u/%u/%u mode=%u\n",ni,no,nw,out_bytes,a[20],a[21],a[22],unsigned(c.mode));
#endif
    return KPI8_BAD_CAPACITY;
  }
  if(c.mode&&(c.zo< -128||c.zo>127||c.amin< -128||c.amax>127||c.amin>c.amax||a[23]<uint32_t(c.co*2)))return KPI8_BAD_CONFIG;
  c.r=c.kh*c.kw*c.ci;c.rpack=(c.r+7)/8;
  bool resident=c.op?(c.ci%8==0&&c.kh*((c.wi*c.ci+7)/8)<=X_BANKS*X_DEPTH):
    (c.r<=MAX_R&&((c.co+31)/32)*c.rpack*2<=W_DEPTH);
  if(!resident){if(c.mode)return KPI8_UNSUPPORTED;return generic_raw(input,weights,output,c);}
  Word w[W_BANKS][W_DEPTH],x[X_BANKS][X_DEPTH],xsecond[X_BANKS][X_DEPTH];Byte y[Y_BANKS][Y_DEPTH];Param q[8][256];
#pragma HLS ARRAY_PARTITION variable=w complete dim=1
#pragma HLS ARRAY_PARTITION variable=x complete dim=1
#pragma HLS ARRAY_PARTITION variable=xsecond complete dim=1
#pragma HLS ARRAY_PARTITION variable=y complete dim=1
#pragma HLS ARRAY_PARTITION variable=q complete dim=1
#pragma HLS BIND_STORAGE variable=w type=ram_2p impl=bram latency=2
#pragma HLS BIND_STORAGE variable=x type=ram_2p impl=bram latency=2
#pragma HLS BIND_STORAGE variable=xsecond type=ram_2p impl=bram latency=2
#pragma HLS BIND_STORAGE variable=y type=ram_2p impl=bram latency=2
#pragma HLS BIND_STORAGE variable=q type=ram_2p impl=bram latency=2
  if(c.mode){
    LOAD_POST:for(int oc=0;oc<c.co;++oc){ap_uint<128> value=ap_uint<128>(params[oc*2])|(ap_uint<128>(params[oc*2+1])<<64);ap_int<32> mult=value.range(63,32),shift=value.range(95,64);if(value.range(127,96)!=0||mult<0||shift>0||shift< -31)return KPI8_BAD_CONFIG;Param packed=0;packed.range(31,0)=value.range(31,0);packed.range(62,32)=value.range(62,32);packed.range(68,63)=value.range(69,64);q[oc&7][oc>>3]=packed;}
  }
  if(c.prelu)load_prelu_tables(params,uint32_t(c.co)*2,uint32_t(c.co),prelu_table);
  load_weights(weights,w,c);int size=c.mode?1:4,max_pixels=minimum(TILE,(Y_BANKS*Y_DEPTH)/(c.co*size));
  if(!c.op)max_pixels=minimum(max_pixels,(X_BANKS*X_DEPTH)/int(c.rpack));
  if(max_pixels>=8)max_pixels=(max_pixels/8)*8;
  if(max_pixels<1){
#ifndef __SYNTHESIS__
    std::printf("resident capacity co=%u size=%d r=%u rpack=%u pixels=%d\n",unsigned(c.co),size,unsigned(c.r),unsigned(c.rpack),max_pixels);
#endif
    return KPI8_BAD_CAPACITY;
  }
  if(!c.op){
    int total=c.ho*c.wo;
    for(int first=0;first<total;first+=max_pixels){int count=minimum(max_pixels,total-first);load_patch(input,x,c,first,count);bool bad=false;compute_tile(x,xsecond,w,y,q,prelu_table,c,count,0,0,bad);if(bad)return KPI8_BAD_CONFIG;store_tile(output,y,first*c.co*size,count*c.co*size);}
  }else{
    int loaded=-1;
    for(int oy=0;oy<c.ho;++oy){int need=minimum(c.hi-1,oy*c.sh-c.pt+c.kh-1);while(loaded<need){++loaded;load_row(input,x,xsecond,c,loaded);}
      for(int ox=0;ox<c.wo;ox+=max_pixels){int count=minimum(max_pixels,c.wo-ox);bool bad=false;compute_tile(x,xsecond,w,y,q,prelu_table,c,count,ox,oy,bad);if(bad)return KPI8_BAD_CONFIG;store_tile(output,y,(oy*c.wo+ox)*c.co*size,count*c.co*size);}
    }
  }
  return KPI8_OK;
}
