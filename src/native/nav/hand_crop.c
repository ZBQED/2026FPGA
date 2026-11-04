/* Current 800x480 BGR image -> 224x224 RGB INT8, with constant-zero borders.
 * Uses the 10-bit affine grid and 5-bit interpolation fractions of OpenCV 3.4.3:
 * https://raw.githubusercontent.com/opencv/opencv/3.4.3/modules/imgproc/src/imgwarp.cpp
 * No cached pixels or landmarks. Unsupported transforms return -1 for OpenCV.
 */
#include <math.h>
#include <stdint.h>

int hand_crop224(const uint8_t *src,const float *forward,uint8_t *dst){
    double a=forward[0],b=forward[1],c=forward[2];
    double d=forward[3],e=forward[4],f=forward[5];
    double determinant=a*e-b*d;
    if(!isfinite(determinant)||determinant==0)return -1;
    double reciprocal=1./determinant;
    double ux=e*reciprocal,uy=b*(-reciprocal);
    double vx=d*(-reciprocal),vy=a*reciprocal;
    double ut=-ux*c-uy*f,vt=-vx*c-vy*f;
    double bound_u=(fabs(ux)+fabs(uy))*224+fabs(ut);
    double bound_v=(fabs(vx)+fabs(vy))*224+fabs(vt);
    if(!isfinite(bound_u)||!isfinite(bound_v)||bound_u>1000000||bound_v>1000000)return -1;
    int columns_u[224],columns_v[224];
    for(int x=0;x<224;++x){columns_u[x]=(int)lrint(ux*x*1024);columns_v[x]=(int)lrint(vx*x*1024);}
    const uint8_t black[3]={0,0,0};
    for(int y=0;y<224;++y){
        int row_u=(int)lrint((uy*y+ut)*1024)+16;
        int row_v=(int)lrint((vy*y+vt)*1024)+16;
        for(int x=0;x<224;++x){
            int fixed_u=(row_u+columns_u[x])>>5,fixed_v=(row_v+columns_v[x])>>5;
            int ix=fixed_u>>5,iy=fixed_v>>5,fx=fixed_u&31,fy=fixed_v&31;
            int w0=(32-fx)*(32-fy),w1=fx*(32-fy),w2=(32-fx)*fy,w3=fx*fy;
            const uint8_t *p0,*p1,*p2,*p3;
            if((unsigned)ix<799&&(unsigned)iy<479){
                p0=src+(iy*800+ix)*3;p1=p0+3;p2=p0+2400;p3=p2+3;
            }else{
                p0=(unsigned)ix<800&&(unsigned)iy<480?src+(iy*800+ix)*3:black;
                p1=(unsigned)(ix+1)<800&&(unsigned)iy<480?src+(iy*800+ix+1)*3:black;
                p2=(unsigned)ix<800&&(unsigned)(iy+1)<480?src+((iy+1)*800+ix)*3:black;
                p3=(unsigned)(ix+1)<800&&(unsigned)(iy+1)<480?src+((iy+1)*800+ix+1)*3:black;
            }
            for(int ch=0;ch<3;++ch){
                int value=(p0[ch]*w0+p1[ch]*w1+p2[ch]*w2+p3[ch]*w3+512)>>10;
                dst[(y*224+x)*3+2-ch]=(uint8_t)(value^128);
            }
        }
    }
    return 0;
}
