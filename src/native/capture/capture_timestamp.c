#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "cameracapturetiming.h"
int mc_camera_copy(const void *,size_t,void *,size_t,uint32_t,uint32_t *,uint32_t *);
struct timed_header { uint32_t magic,sequence,width,height,stride,slots[3],reserved[8]; };
_Static_assert(sizeof(struct timed_header)==64,"preview ABI");
int mc_camera_copy_timed_kind(const void *mapping,size_t bytes,void *destination,size_t capacity,
 uint32_t previous,uint32_t *copied,uint32_t *current,uint64_t *capture_ns,uint32_t *kind) {
 if(bytes<64)return -1;
 const struct timed_header *h=mapping;
 const uint32_t seq=__atomic_load_n(&h->sequence,__ATOMIC_ACQUIRE);
 if(seq==previous || !seq)return 0;
 if(__atomic_load_n(&h->reserved[7],__ATOMIC_ACQUIRE)!=seq)return 2;
 const uint32_t tag=__atomic_load_n(&h->reserved[6],__ATOMIC_RELAXED);
 if(tag!=CameraTimingTIM8 && tag!=CameraTimingTIM9)return -3;
 const unsigned slot=seq%3;
 const uint32_t guard=__atomic_load_n(&h->slots[slot],__ATOMIC_ACQUIRE);
 if(guard!=seq*2u)return 2;
 const uint64_t ns=(uint64_t)__atomic_load_n(&h->reserved[slot*2],__ATOMIC_RELAXED)|
  ((uint64_t)__atomic_load_n(&h->reserved[slot*2+1],__ATOMIC_RELAXED)<<32);
 const int rc=mc_camera_copy(mapping,bytes,destination,capacity,previous,copied,current);
 if(rc!=1)return rc;
 __atomic_thread_fence(__ATOMIC_ACQUIRE);
 if(*copied!=seq || __atomic_load_n(&h->slots[slot],__ATOMIC_ACQUIRE)!=guard ||
    __atomic_load_n(&h->reserved[7],__ATOMIC_ACQUIRE)!=seq ||
    __atomic_load_n(&h->reserved[6],__ATOMIC_RELAXED)!=tag)return 2;
 *capture_ns=ns;*kind=tag;return 1;
}
// Retain TIM8 reader ABI for existing private callers.
int mc_camera_copy_timed(const void *mapping,size_t bytes,void *destination,size_t capacity,
 uint32_t previous,uint32_t *copied,uint32_t *current,uint64_t *capture_ns) {
 uint32_t kind;
 return mc_camera_copy_timed_kind(mapping,bytes,destination,capacity,previous,copied,current,capture_ns,&kind);
}
int mc_camera_timing_snapshot(const void *mapping,size_t bytes,uint32_t sequence,CameraTimingSlot *out) {
 if(bytes!=sizeof(CameraTimingMap))return -1;
 const CameraTimingMap *m=mapping;
 if(m->magic!=CameraTimingMagic || m->version!=1 || m->bytes!=sizeof(*m))return -1;
 const CameraTimingSlot *s=&m->entries[sequence%3];
 const uint32_t guard=__atomic_load_n(&s->guard,__ATOMIC_ACQUIRE);
 if(guard!=sequence*2u)return 0;
 memcpy(out,s,sizeof(*out));
 __atomic_thread_fence(__ATOMIC_ACQUIRE);
 return out->previewSequence==sequence && guard==__atomic_load_n(&s->guard,__ATOMIC_ACQUIRE);
}
