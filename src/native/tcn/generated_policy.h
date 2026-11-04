#ifndef GESTURE_I8_POLICY_H
#define GESTURE_I8_POLICY_H
#include "i8_math.h"
namespace gesture_i8_pruned {
struct Spec {int node,input,weight,bias,output,activation,allow_i8;Config config;};
static const char kPoseSHA[]="e9a5c5cb17f736fafd4c2ec1da3b3d331d6edbe8a0d32395855aeb2cdfd64b9f";
static const int kSelectedCount=5;
static const Spec kSpecs[]={{145,257,474,491,258,3,1,{{944328779u,2u,0u,0u,8u,8u,144u,8u,8u,864u,1u,1u,1u,1u,0u,0u,0u,0u,0u,0u,1152u,15552u,27648u,0u,0u,0u,0u,0u,0u,0u,0u,0u}}},
{151,259,446,456,260,0,1,{{944328779u,2u,0u,0u,8u,8u,864u,8u,8u,144u,1u,1u,1u,1u,0u,0u,0u,0u,0u,0u,6912u,15552u,4608u,0u,0u,0u,0u,0u,0u,0u,0u,0u}}},
{155,261,515,366,262,3,1,{{944328779u,2u,0u,0u,8u,8u,144u,8u,8u,864u,1u,1u,1u,1u,0u,0u,0u,0u,0u,0u,1152u,15552u,27648u,0u,0u,0u,0u,0u,0u,0u,0u,0u}}},
{161,263,489,500,264,0,1,{{944328779u,2u,0u,0u,8u,8u,864u,8u,8u,144u,1u,1u,1u,1u,0u,0u,0u,0u,0u,0u,6912u,15552u,4608u,0u,0u,0u,0u,0u,0u,0u,0u,0u}}},
{171,267,364,422,268,0,1,{{944328779u,2u,0u,0u,8u,8u,864u,8u,8u,144u,1u,1u,1u,1u,0u,0u,0u,0u,0u,0u,6912u,15552u,4608u,0u,0u,0u,0u,0u,0u,0u,0u,0u}}}};
static const char* kOriginalModelSHAs[]={"1b14e9422c6ad006cde6581a46c8b90dd573c07ab7f3934b5589e7cea3f89a54","11c272b891e1a99ab034208e23937a8008388cf11ed2a9d776ed3d01d0ba00e3","9ba9dd3d42efaaba86b4ff0122b06f29c4122e756b329d89dca1e297fd8f866c","e9a5c5cb17f736fafd4c2ec1da3b3d331d6edbe8a0d32395855aeb2cdfd64b9f","67d996ce96f9d36fe17d2693022c6da93168026ab2f028f9e2365398d8ac7d5d"};
}
#endif
