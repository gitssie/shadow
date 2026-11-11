#ifndef SHADOW_NETWORK_USER_AGENT_CACHE_H
#define SHADOW_NETWORK_USER_AGENT_CACHE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

static inline bool SHDWNetworkUserAgentCacheAddress(const uint32_t *code,
    size_t count, uintptr_t start, uintptr_t *result) {
    if(!code || !result || !count || count > 64 || (start & 3) ||
       start > UINTPTR_MAX - count * sizeof(*code)) return false;
    bool called = false;
    uintptr_t candidate = 0;
    for(size_t i = 0; i < count; i++) {
        uint32_t word = code[i];
        if(word == 0xb6f00050u && candidate && i + 1 < count && code[i + 1] == 0xd4388e20u) {
            i++;
            continue;
        }
        if((word & 0xff000010u) == 0x54000000u ||
           (word & 0x7e000000u) == 0x34000000u ||
           (word & 0x7e000000u) == 0x36000000u ||
           (word & 0xff000000u) == 0xd4000000u) return false;
        if((word & 0xfc000000u) == 0x94000000u) called = true;
        if(called && i + 1 < count && (word & 31) != 31 && (word & 0x9f000000u) == 0x90000000u) {
            uint32_t load = code[i + 1];
            if((load & 0xffc0001fu) == 0xf9400001u &&
               ((load >> 5) & 31) == (word & 31)) {
                int64_t pages = ((word >> 5) & 0x7ffffu) * 4u + ((word >> 29) & 3u);
                if(pages & 0x100000) pages -= 0x200000;
                int64_t delta = pages * 4096;
                uintptr_t page = (start + i * 4) & ~(uintptr_t)4095;
                if((delta < 0 && page < (uint64_t)-delta) ||
                   (delta >= 0 && page > UINTPTR_MAX - (uint64_t)delta)) return false;
                uintptr_t address = delta < 0 ? page - (uint64_t)-delta : page + (uint64_t)delta;
                uintptr_t offset = ((load >> 10) & 0xfff) * 8u;
                if(address > UINTPTR_MAX - offset) return false;
                address += offset;
                if(!address || (address & 7) || (candidate && candidate != address)) return false;
                candidate = address;
            }
        }
        if((word & 0xfc000000u) == 0x14000000u) {
            int64_t displacement = word & 0x3ffffffu;
            if(displacement & 0x2000000) displacement -= 0x4000000;
            displacement *= 4;
            uintptr_t pc = start + i * 4;
            if((displacement < 0 && pc < (uint64_t)-displacement) ||
               (displacement >= 0 && pc > UINTPTR_MAX - (uint64_t)displacement)) return false;
            uintptr_t target = displacement < 0 ? pc - (uint64_t)-displacement : pc + (uint64_t)displacement;
            if(target >= start && target < start + count * 4) return false;
        }
        if((word & 0xfc000000u) == 0x14000000u || (word & 0xfffffc1fu) == 0xd65f0000u ||
           word == 0xd65f0bffu || word == 0xd65f0fffu) {
            if(!candidate) return false;
            *result = candidate;
            return true;
        }
        if((word & 0xfe000000u) == 0xd6000000u) return false;
    }
    return false;
}

#ifdef __OBJC__
#import <Foundation/Foundation.h>
BOOL SHDWNetworkReplaceUserAgentCache(const void *getter, NSString *native, NSString *updated);
#endif

#endif
