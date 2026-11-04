/* SPDX-License-Identifier: MIT
 * Integer BGR geometry and same-framebuffer DRM presentation receipts.
 * Coordinates use the existing 640-wide logical image and Q20 interface.
 */
#define _POSIX_C_SOURCE 200809L
#include "live_integer_frame.h"
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmmode.h>

uint64_t li_monotonic_ns(void) {
    struct timespec t;
    return clock_gettime(CLOCK_MONOTONIC,&t)?0:(uint64_t)t.tv_sec*1000000000u+t.tv_nsec;
}
static int64_t rounded(int64_t n,int64_t d) {return n<0?-((-n+d/2)/d):(n+d/2)/d;}
int64_t li_logical_x_q20_to_capture(int64_t x) {
    uint64_t value=(uint64_t)x*5u;
    return (value>>63?-((int64_t)(2-value)>>2):((int64_t)(value+2)>>2))+(1<<17);
}
_Static_assert(sizeof(struct li_scan_receipt)==88,"Receipt ABI");
_Static_assert(sizeof(struct li_scan_profile)==64,"Profile ABI");
static int image_valid(const void*p,uint32_t w,uint32_t h,uint32_t stride) {
    return p&&w&&h&&w<=INT_MAX/3&&h<=INT_MAX&&stride>=w*3;
}
static int coordinate_valid(int64_t x) {return x>=-(INT64_C(1)<<32)&&x<=(INT64_C(1)<<32);}
static int xpixel(int64_t x) {return (int)rounded(5*x+(1<<19),INT64_C(1)<<22);}
static int ypixel(int64_t y) {return (int)rounded(y,INT64_C(1)<<20);}
static void pixel(uint8_t*p,uint32_t w,uint32_t h,uint32_t stride,int x,int y,uint32_t rgb) {
    if(x<0||y<0||(uint32_t)x>=w||(uint32_t)y>=h)return;
    p+=(size_t)y*stride+(size_t)x*3;p[0]=rgb;p[1]=rgb>>8;p[2]=rgb>>16;
}
int li_resize_800_640_bgr(const uint8_t*src,uint32_t ss,uint8_t*dst,uint32_t ds) {
    if(!src||!dst||ss<2400||ds<1920)return-EINVAL;
    for(unsigned y=0;y<480;y++)for(unsigned x=0;x<640;x++) {
        unsigned t=x*10+1,left=t>>3,f=t&7;
        for(unsigned c=0;c<3;c++)dst[(size_t)y*ds+x*3+c]=
            ((8-f)*src[(size_t)y*ss+left*3+c]+f*src[(size_t)y*ss+(left+1)*3+c]+4)>>3;
    }
    return 0;
}
int li_draw_point_q20(uint8_t*p,uint32_t w,uint32_t h,uint32_t stride,int64_t x,int64_t y,uint32_t rgb,uint32_t radius) {
    if(!image_valid(p,w,h,stride)||!coordinate_valid(x)||!coordinate_valid(y)||radius>12)return-EINVAL;
    int cx=xpixel(x),cy=ypixel(y),r=radius;
    for(int dy=-r;dy<=r;dy++)for(int dx=-r;dx<=r;dx++)if(dx*dx+dy*dy<=r*r)pixel(p,w,h,stride,cx+dx,cy+dy,rgb);
    return 0;
}
int li_draw_line_q20(uint8_t*p,uint32_t w,uint32_t h,uint32_t stride,int64_t ax,int64_t ay,int64_t bx,int64_t by,uint32_t rgb,uint32_t thickness) {
    if(!image_valid(p,w,h,stride)||thickness<1||thickness>8)return-EINVAL;
    if(!coordinate_valid(ax)||!coordinate_valid(ay)||!coordinate_valid(bx)||!coordinate_valid(by))return-ERANGE;
    int x=xpixel(ax),y=ypixel(ay),endx=xpixel(bx),endy=ypixel(by),dx=abs(endx-x),dy=-abs(endy-y),sx=x<endx?1:-1,sy=y<endy?1:-1,error=dx+dy,r=thickness/2;
    for(;;) {
        for(int yy=-r;yy<=r;yy++)for(int xx=-r;xx<=r;xx++)pixel(p,w,h,stride,x+xx,y+yy,rgb);
        if(x==endx&&y==endy)break;
        int e=2*error;if(e>=dy){error+=dy;x+=sx;}if(e<=dx){error+=dx;y+=sy;}
    }
    return 0;
}

static int irq_count(uint64_t*out) {
    FILE*f=fopen("/proc/interrupts","r");if(!f)return-errno;
    char line[512],controller[32],trigger[32],name[80];unsigned irq,hardware;unsigned long long a,b;int found=0;
    while(fgets(line,sizeof line,f))if(sscanf(line," %u: %llu %llu %31s %u %31s %79s",&irq,&a,&b,controller,&hardware,trigger,name)==7&&hardware==84&&!strcmp(controller,"GIC-0")&&!strcmp(name,"xilinx_framebuffer")){*out=a+b;found++;}
    fclose(f);return found==1?0:-ENODEV;
}
int li_scan_validate_fd(int fd,struct li_topology*out) {
    if(fd<0||!out)return-EINVAL;
    memset(out,0,sizeof *out);uint64_t cap=0;
    if(drmGetCap(fd,DRM_CAP_TIMESTAMP_MONOTONIC,&cap)||cap!=1)return-ENOTSUP;
    if(drmIsMaster(fd)!=1)return-EACCES;
    drmModeRes*r=drmModeGetResources(fd);if(!r)return-errno;
    int active=0,connected=0;
    for(int i=0;i<r->count_crtcs;i++) {
        drmModeCrtc*c=drmModeGetCrtc(fd,r->crtcs[i]);
        if(c&&c->mode_valid&&c->buffer_id&&c->width&&c->height){active++;out->crtc_id=c->crtc_id;out->width=c->width;out->height=c->height;out->mode_clock_khz=c->mode.clock;out->htotal=c->mode.htotal;out->vtotal=c->mode.vtotal;}
        if(c)drmModeFreeCrtc(c);
    }
    for(int i=0;i<r->count_connectors;i++) {
        drmModeConnector*c=drmModeGetConnectorCurrent(fd,r->connectors[i]);
        if(c&&c->connection==DRM_MODE_CONNECTED){connected++;out->connector_id=c->connector_id;}
        if(c)drmModeFreeConnector(c);
    }
    drmModeFreeResources(r);out->timestamp_monotonic=1;
    return active==1&&connected==1?0:-ENODEV;
}
static int same_framebuffer_request(int fd,uint32_t crtc,drmModeAtomicReq**result,uint32_t*framebuffer) {
    static const char*names[]={"FB_ID","CRTC_ID","SRC_X","SRC_Y","SRC_W","SRC_H","CRTC_X","CRTC_Y","CRTC_W","CRTC_H"};
    if(drmSetClientCap(fd,DRM_CLIENT_CAP_UNIVERSAL_PLANES,1)||drmSetClientCap(fd,DRM_CLIENT_CAP_ATOMIC,1))return-errno;
    drmModeCrtc*c=drmModeGetCrtc(fd,crtc);if(!c)return-errno;*framebuffer=c->buffer_id;drmModeFreeCrtc(c);
    drmModePlaneRes*resources=drmModeGetPlaneResources(fd);if(!resources)return-errno;
    int code=-ENODEV;drmModeAtomicReq*request=NULL;
    for(uint32_t i=0;i<resources->count_planes;i++) {
        drmModePlane*p=drmModeGetPlane(fd,resources->planes[i]);if(!p)continue;
        if(p->crtc_id!=crtc||p->fb_id!=*framebuffer){drmModeFreePlane(p);continue;}
        drmModeObjectProperties*props=drmModeObjectGetProperties(fd,p->plane_id,DRM_MODE_OBJECT_PLANE);
        uint32_t ids[10]={0};uint64_t values[10]={0};int primary=0;
        if(props)for(uint32_t j=0;j<props->count_props;j++) {
            drmModePropertyRes*prop=drmModeGetProperty(fd,props->props[j]);if(!prop)continue;
            if(!strcmp(prop->name,"type"))primary=props->prop_values[j]==DRM_PLANE_TYPE_PRIMARY;
            for(int k=0;k<10;k++)if(!strcmp(prop->name,names[k])){ids[k]=prop->prop_id;values[k]=props->prop_values[j];}
            drmModeFreeProperty(prop);
        }
        if(props)drmModeFreeObjectProperties(props);
        if(primary) {
            request=drmModeAtomicAlloc();code=request?0:-ENOMEM;
            for(int k=0;k<10&&!code;k++)if(!ids[k]||drmModeAtomicAddProperty(request,p->plane_id,ids[k],values[k])<0)code=-EINVAL;
        }
        drmModeFreePlane(p);if(primary)break;
    }
    drmModeFreePlaneResources(resources);
    if(code){if(request)drmModeAtomicFree(request);return code;}
    *result=request;return 0;
}
static int event_wait(int fd,uintptr_t cookie,uint64_t deadline,uint64_t*stamp,uint64_t*observed,uint32_t*sequence) {
    for(;;) {
        uint64_t now=li_monotonic_ns();if(now>=deadline)return-ETIMEDOUT;
        struct pollfd p={fd,POLLIN,0};int timeout=(int)((deadline-now+999999)/1000000),rc=poll(&p,1,timeout);
        if(rc<0){if(errno==EINTR)continue;return-errno;}if(!rc)return-ETIMEDOUT;
        if(p.revents&(POLLERR|POLLHUP|POLLNVAL))return-EIO;
        char bytes[4096];ssize_t length=read(fd,bytes,sizeof bytes);if(length<0){if(errno==EINTR||errno==EAGAIN)continue;return-errno;}
        for(size_t i=0;i+sizeof(struct drm_event)<=(size_t)length;) {
            struct drm_event*h=(void*)(bytes+i);if(h->length<sizeof *h||i+h->length>(size_t)length)return-EPROTO;
            if(h->type==DRM_EVENT_FLIP_COMPLETE&&h->length>=sizeof(struct drm_event_vblank)) {
                struct drm_event_vblank*v=(void*)h;
                if(v->user_data==cookie){*stamp=(uint64_t)v->tv_sec*1000000000u+(uint64_t)v->tv_usec*1000u;*sequence=v->sequence;*observed=li_monotonic_ns();return 0;}
            }
            i+=h->length;
        }
    }
}
int li_scan_after_copy_profile(int fd,uint32_t publication,uint32_t timeout_ms,struct li_scan_receipt*out,struct li_scan_profile*profile) {
    if(!out||!profile||!timeout_ms||timeout_ms>5000)return-EINVAL;
    memset(out,0,sizeof *out);memset(profile,0,sizeof *profile);profile->entered_ns=li_monotonic_ns();
    struct li_topology topology;drmModeAtomicReq*request=NULL;uint32_t framebuffer=0;int code=li_scan_validate_fd(fd,&topology);
    profile->topology_done_ns=li_monotonic_ns();if(code)goto done;out->crtc_id=topology.crtc_id;
    code=same_framebuffer_request(fd,topology.crtc_id,&request,&framebuffer);profile->plane_request_done_ns=li_monotonic_ns();if(code)goto done;
    if(drmModeAtomicCommit(fd,request,DRM_MODE_ATOMIC_TEST_ONLY,NULL)){code=-errno;goto done;}out->atomic_test_only=1;
    code=irq_count(&out->irq_before);profile->irq_before_done_ns=li_monotonic_ns();if(code)goto done;
    __sync_synchronize();out->copy_fence_ns=li_monotonic_ns();uint64_t deadline=out->copy_fence_ns+(uint64_t)timeout_ms*1000000u;
    for(unsigned i=0;i<2;i++) {
        uintptr_t cookie=((publication&0x3fffffffu)<<2)|(i+1u);
        if(drmModeAtomicCommit(fd,request,DRM_MODE_ATOMIC_NONBLOCK|DRM_MODE_PAGE_FLIP_EVENT,(void*)cookie)){code=-errno;goto done;}
        out->same_fb_atomic_commits++;
        code=event_wait(fd,cookie,deadline,i?&out->event2_ns:&out->event1_ns,i?&out->observed2_ns:&out->observed1_ns,i?&out->sequence2:&out->sequence1);
        if(code)goto done;out->events_seen++;if(i)profile->event2_done_ns=li_monotonic_ns();else profile->event1_done_ns=li_monotonic_ns();
    }
    code=irq_count(&out->irq_after);profile->irq_after_done_ns=li_monotonic_ns();if(code)goto done;
    struct li_topology after;code=li_scan_validate_fd(fd,&after);if(code)goto done;
    drmModeCrtc*c=drmModeGetCrtc(fd,topology.crtc_id);if(!c){code=-errno;goto done;}
    int same=c->buffer_id==framebuffer;drmModeFreeCrtc(c);
    if(!same||memcmp(&topology,&after,sizeof after)||out->copy_fence_ns>=out->event1_ns||out->event1_ns>=out->event2_ns||out->event2_ns>out->observed2_ns||!(uint32_t)(out->sequence2-out->sequence1)||out->irq_after<=out->irq_before){code=-EIO;goto done;}
    out->verified=1;
done:
    if(request)drmModeAtomicFree(request);profile->release_done_ns=li_monotonic_ns();out->error=code;return code;
}
int li_scan_after_copy(int fd,uint32_t publication,uint32_t timeout_ms,struct li_scan_receipt*out) {
    struct li_scan_profile profile;return li_scan_after_copy_profile(fd,publication,timeout_ms,out,&profile);
}
