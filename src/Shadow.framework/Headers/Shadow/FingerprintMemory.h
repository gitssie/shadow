#ifndef shadow_fingerprint_memory_h
#define shadow_fingerprint_memory_h
#include <stdint.h>

static inline uint64_t SHDWFingerprintProjectedMemory(uint64_t nativeSize, int64_t delta) {
    const uint64_t limit = 64 * UINT64_C(16384);
    if (nativeSize <= limit || nativeSize > UINT64_MAX - limit ||
        delta < -(int64_t)limit || delta > (int64_t)limit) return nativeSize;
    return delta < 0 ? nativeSize - (uint64_t)(-delta) : nativeSize + (uint64_t)delta;
}
#endif
