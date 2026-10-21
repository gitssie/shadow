#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../src/ShadowCore.dylib/hooks/Universal/rebind_import_index.h"

static unsigned char image[4096];
static void u32(size_t at, uint32_t v) { memcpy(image + at, &v, 4); }
static void u64(size_t at, uint64_t v) { memcpy(image + at, &v, 8); }
static const size_t sym = 176, dysym = 200, dyld = 280;
static void fixture(void) {
    memset(image, 0, sizeof(image));
    u32(0, 0xfeedfacf); u32(16, 5); u32(20, 296);
    u32(32, 0x19); u32(36, 72); memcpy(image + 40, "__TEXT", 6);
    u64(56, 0x100000000ULL); u64(64, 1024); u64(80, 1024); u32(92, 5);
    u32(104, 0x19); u32(108, 72); memcpy(image + 112, "__LINKEDIT", 10);
    u64(128, 0x100000400ULL); u64(136, 3072); u64(144, 1024); u64(152, 3072); u32(164, 1);
    u32(sym, 2); u32(sym + 4, 24); u32(sym + 8, 1100); u32(sym + 12, 2);
    u32(sym + 16, 1200); u32(sym + 20, 40);
    u32(dysym, 0xb); u32(dysym + 4, 80); u32(dysym + 56, 1300); u32(dysym + 60, 3);
    u32(1100, 1); u32(1116, 9); memcpy(image + 1200, "\0_malloc\0__hidden\0", 19);
    u32(1300, 0); u32(1304, 1); u32(1308, 0x80000000U);
    u32(dyld, 0x80000022); u32(dyld + 4, 48);
}
static int run(uint64_t *mask) {
    const char *names[] = {"malloc", "_hidden", "bind", "weak", "lazy", "absent"};
    return shdw_rebind_import_mask(image, names, 6, mask);
}
int main(void) {
    uint64_t mask[5]; fixture(); assert(run(mask) == 1 && mask[0] == 3);
    const unsigned char bind[] = {0x20, 1, 0x40, 'b','i','n','d',0, 0x60,0x7f,0x70,1,0x80,1,0xa0,1,0xc0,1,1,0xd0,1,0xd1,0x90,0};
    memcpy(image + 1400, bind, sizeof(bind)); u32(dyld + 16, 1400); u32(dyld + 20, sizeof(bind));
    memcpy(image + 1500, "\x40weak\0\x90\0", 8); u32(dyld + 24, 1500); u32(dyld + 28, 8);
    memcpy(image + 1600, "\0\x40lazy\0\x90\0", 9); u32(dyld + 32, 1600); u32(dyld + 36, 9);
    assert(run(mask) == 1 && mask[0] == 31);
    image[1400] = 0xe0; assert(run(mask) == 0 && mask[0] == UINT64_MAX);
    fixture(); u32(1300, 2); assert(run(mask) == 0 && mask[0] == UINT64_MAX);
    fixture(); u32(1100, 40); assert(run(mask) == 0);
    fixture(); memset(image + 1200, 'a', 40); assert(run(mask) == 0);
    fixture(); u32(sym + 8, 4090); assert(run(mask) == 0);
    fixture(); u32(dysym + 60, UINT32_MAX); assert(run(mask) == 0);
    fixture(); u32(dyld + 16, 4090); u32(dyld + 20, 20); assert(run(mask) == 0);
    fixture(); image[1400] = 0x40; memset(image + 1401, 'a', 10);
    u32(dyld + 16, 1400); u32(dyld + 20, 11); assert(run(mask) == 0);
    fixture(); image[1400] = 0x20; image[1401] = 0x80;
    u32(dyld + 16, 1400); u32(dyld + 20, 2); assert(run(mask) == 0);
    fixture(); u32(dyld, 0x80000034); assert(run(mask) == 0 && mask[0] == UINT64_MAX);
    fixture(); u32(36, 0); assert(run(mask) == 0);
    fixture(); u32(20, 8); assert(run(mask) == 0);
    fixture(); u32(0, 0xcffaedfe); assert(run(mask) == 0);
    fixture(); u32(24, 0x80000000U); assert(run(mask) == 0);
    fixture(); u64(128, UINT64_MAX - 100); assert(run(mask) == 0);
    fixture(); u64(128, 0x0); assert(run(mask) == 0);
    fixture(); u32(dysym + 60, 0); u32(dyld + 20, 0); assert(run(mask) == 1 && mask[0] == 0);
    fixture(); const char *many[320]; for(size_t i = 0; i < 320; i++) many[i] = "malloc";
    assert(shdw_rebind_import_mask(image, many, 320, mask) == 1);
    for(size_t i = 0; i < 5; i++) assert(mask[i] == UINT64_MAX);
    for(size_t i = 0; i < 320; i++) many[i] = "absent";
    many[0] = many[63] = many[64] = many[319] = "malloc";
    assert(shdw_rebind_import_mask(image, many, 320, mask) == 1);
    assert(mask[0] == (UINT64_C(1) | (UINT64_C(1) << 63)));
    assert(mask[1] == 1 && mask[2] == 0 && mask[3] == 0 && mask[4] == (UINT64_C(1) << 63));
    many[319] = NULL; assert(shdw_rebind_import_mask(image, many, 320, mask) == 0);
    assert(!shdw_rebind_import_mask(image, many, 321, mask));
    assert(!shdw_rebind_import_mask(NULL, many, 1, mask));
    assert(!shdw_rebind_import_mask(image, NULL, 1, mask));
    fixture(); assert(shdw_rebind_import_mask(image, NULL, 0, NULL));
    puts("rebind import index: indirect, bind/weak/lazy, normalization, word boundaries and unknown fallback passed");
}
