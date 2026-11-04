#ifndef PYNQ_HAND_GUARDED_SPANS_H
#define PYNQ_HAND_GUARDED_SPANS_H
/* Match native leading64 and each rounded-payload tail64. No ABI change. */
static inline int gpi8_validate_guarded_spans(const struct gpi8_job *j,
        gpi8_u32 pool, const gpi8_u64 size[4])
{
    unsigned a,b;
    for(a=0;a<4;a++) {
        gpi8_u64 end;
        if(!size[a]) continue;
        if((j->offset[a]&7u) || j->offset[a]<64u ||
           size[a]>pool || j->offset[a]>pool ||
           size[a]+64u>(gpi8_u64)pool-j->offset[a]) return -2;
        end=(gpi8_u64)j->offset[a]+size[a]+64u;
        for(b=0;b<a;b++) {
            if(size[b] && j->offset[a]<(gpi8_u64)j->offset[b]+size[b]+64u &&
               j->offset[b]<end) return -2;
        }
    }
    return 0;
}
#endif
