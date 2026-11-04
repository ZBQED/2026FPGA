#ifndef PYNQ_HAND_COHERENT_DMA_BOUNDS_H
#define PYNQ_HAND_COHERENT_DMA_BOUNDS_H
/* Exclusive end may equal1GiB; every payload/config byte must be below it. */
static inline int gpi8_coherent_dma_span(gpi8_u64 address,gpi8_u64 bytes)
{
    const gpi8_u64 limit=0x40000000ull;
    return bytes && address<limit && bytes<=limit-address;
}
#endif
