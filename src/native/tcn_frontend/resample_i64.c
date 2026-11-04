#include <stdint.h>

/* Exact 32-position resampling of Q30 features to Q10; no network or device IO. */
int tcn_resample_i64(const int64_t *v, const uint8_t *mask,
                     uint32_t count, uint32_t width, int16_t *out, uint8_t *valid) {
    const int64_t bound = INT64_MAX / 31;
    const uint32_t den = 31u << 20;
    if (!count || count > 65535 || !width || width > 4096) return -1;
    for (uint32_t i = 0; i < count * width; ++i)
        if (v[i] > bound || v[i] < -bound) return -2;
    int clips = 0;
    for (uint32_t t = 0; t < 32; ++t) {
        uint32_t position = t * (count - 1), lo = position / 31;
        uint32_t rem = position - lo * 31, hi = lo + (lo + 1 < count);
        for (uint32_t j = 0; j < width; ++j) {
            uint32_t a = lo * width + j, b = hi * width + j, k = t * width + j;
            valid[k] = mask[a] & (mask[b] != 0 || rem == 0);
            if (!valid[k]) { out[k] = 0; continue; }
            int64_t n = v[a] * (31 - rem) + v[b] * rem;
            uint64_t magnitude = n < 0 ? (uint64_t)-n : (uint64_t)n;
            const uint64_t cap = (uint64_t)32769 * den;
            if (magnitude > cap) magnitude = cap;
            uint32_t q = (uint32_t)(magnitude >> 20) / 31;
            uint32_t r = (uint32_t)(magnitude - (uint64_t)q * den);
            q += r > den / 2 || (r == den / 2 && (q & 1));
            int value = n < 0 ? -(int)q : (int)q;
            if (value < -32768) { value = -32768; ++clips; }
            if (value > 32767) { value = 32767; ++clips; }
            out[k] = (int16_t)value;
        }
    }
    return clips;
}
