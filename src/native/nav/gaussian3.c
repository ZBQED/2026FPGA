/* Exact float64 3x3 Gaussian followed by the original float32 normalization. */
int gaussian3(float *hm, int planes, int height, int width) {
    if (height != 64 || width != 48 || planes < 1 || planes > 17) return -1;
    double horizontal[64 * 48];
    for (int p = 0; p < planes; ++p) {
        float *a = hm + p * height * width, origin = a[0], peak;
        for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
            int i = y * width + x;
            if (a[i] > origin) origin = a[i];
            horizontal[i] = (x ? (double)a[i-1] * .25 : 0.) + (double)a[i] * .5 + (x+1 < width ? (double)a[i+1] * .25 : 0.);
        }
        for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
            int i = y * width + x;
            a[i] = (float)((y ? horizontal[i-width] * .25 : 0.) + horizontal[i] * .5 + (y+1 < height ? horizontal[i+width] * .25 : 0.));
        }
        peak = a[0];
        for (int i = 1; i < height * width; ++i) if (a[i] > peak) peak = a[i];
        float scale = origin / peak;
        for (int i = 0; i < height * width; ++i) a[i] *= scale;
    }
    return 0;
}

int body_prepare(const float *nhwc, float *patch, float *point) {
    double horizontal[64 * 48]; float smooth[64 * 48];
    for (int p=0;p<17;++p) {
        float origin=nhwc[p];int best=0;
        for (int y=0;y<64;++y) for (int x=0;x<48;++x) {
            int i=y*48+x;float v=nhwc[i*17+p];
            union {float f;unsigned int u;} bits;bits.f=v;
            if ((bits.u & 0x7f800000u)==0x7f800000u) return -2;
            if (v>origin) {origin=v;best=i;}
            horizontal[i]=(x ? (double)nhwc[(i-1)*17+p]*.25:0.)+(double)v*.5+(x<47 ? (double)nhwc[(i+1)*17+p]*.25:0.);
        }
        int x=origin>0 ? best%48:0,y=origin>0 ? best/48:0;
        point[p*3]=(float)x;point[p*3+1]=(float)y;point[p*3+2]=origin;
        for (int j=0;j<25;++j) patch[p*25+j]=1.f;
        if (x<=1 || x>=46 || y<=1 || y>=62) continue;
        float peak=0.f;
        for (int row=0;row<64;++row) for (int col=0;col<48;++col) {
            int i=row*48+col;
            float v=(float)((row ? horizontal[i-48]*.25:0.)+horizontal[i]*.5+(row<63 ? horizontal[i+48]*.25:0.));
            smooth[i]=v;if (i==0 || v>peak) peak=v;
        }
        float scale=origin/peak;
        for (int dy=-2;dy<=2;++dy) for (int dx=-2;dx<=2;++dx) {
            float v=smooth[(y+dy)*48+x+dx]*scale;
            patch[p*25+(dy+2)*5+dx+2]=v>1e-10f ? v:1e-10f;
        }
    }
    return 0;
}

int body_finish(const float *patch,float *point,const double *affine) {
    for(int p=0;p<17;++p) {
        float *out=point+p*3;float x=out[0],y=out[1];const float *a=patch+p*25;
        if (x>1 && x<46 && y>1 && y<62) {
            double dx=.5*(double)(a[13]-a[11]),dy=.5*(double)(a[17]-a[7]);
            double dxx=.25*((double)a[14]-2.*(double)a[12]+(double)a[10]);
            double dyy=.25*((double)a[22]-2.*(double)a[12]+(double)a[2]);
            double dxy=.25*(double)((a[18]-a[8])-a[16]+a[6]);
            double det=dxx*dyy-dxy*dxy;
            if (det!=0.) {
                x=(float)((double)x-(dyy*dx-dxy*dy)/det);
                y=(float)((double)y-(dxx*dy-dxy*dx)/det);
            }
        }
        out[0]=(float)((affine[0]*(double)x+affine[1]*(double)y)+affine[2]);
        out[1]=(float)((affine[3]*(double)x+affine[4]*(double)y)+affine[5]);
    }
    return 0;
}
