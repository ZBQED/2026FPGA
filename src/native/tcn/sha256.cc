#include "sha256.h"
#include <array>
#include <cstring>
#include <stdexcept>
static uint32_t R(uint32_t x,int n){return (x>>n)|(x<<(32-n));}
std::string GesturePrunedSHA256(const void* data,size_t n){
  if(!data&&n)throw std::invalid_argument("Null hash input");
  static const uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,
    0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
    0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,
    0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,
    0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
  std::array<uint32_t,8> h{{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
  auto block=[&](const uint8_t* p){uint32_t w[64];for(int i=0;i<16;++i)w[i]=(uint32_t(p[4*i])<<24)|(uint32_t(p[4*i+1])<<16)|(uint32_t(p[4*i+2])<<8)|p[4*i+3];
    for(int i=16;i<64;++i){uint32_t a=w[i-15],b=w[i-2];w[i]=w[i-16]+(R(a,7)^R(a,18)^(a>>3))+w[i-7]+(R(b,17)^R(b,19)^(b>>10));}
    auto v=h;for(int i=0;i<64;++i){uint32_t t1=v[7]+(R(v[4],6)^R(v[4],11)^R(v[4],25))+((v[4]&v[5])^(~v[4]&v[6]))+k[i]+w[i];
      uint32_t t2=(R(v[0],2)^R(v[0],13)^R(v[0],22))+((v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]));
      v={{t1+t2,v[0],v[1],v[2],v[3]+t1,v[4],v[5],v[6]}};}
    for(int i=0;i<8;++i)h[i]+=v[i];};
  const auto* p=static_cast<const uint8_t*>(data);size_t remain=n;
  while(remain>=64){block(p);p+=64;remain-=64;}
  uint8_t tail[128]{};if(remain)std::memcpy(tail,p,remain);tail[remain]=0x80;
  size_t total=remain<56?64:128;uint64_t bits=uint64_t(n)*8;
  for(int i=0;i<8;++i)tail[total-1-i]=uint8_t(bits>>(8*i));block(tail);if(total==128)block(tail+64);
  std::string result;const char* hex="0123456789abcdef";for(auto x:h)for(int i=7;i>=0;--i)result+=hex[(x>>(i*4))&15];return result;
}
#ifdef GPI8_MATH_TEST_ONLY
extern "C" int i8_test_sha256(const void* data,size_t n,char* out){try{auto hash=GesturePrunedSHA256(data,n);std::memcpy(out,hash.c_str(),65);return 0;}catch(...){return -1;}}
#endif
