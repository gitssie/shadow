"""Run the production HTTP/2 entry scanner against synthetic dyld images."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/Transport/NativeHTTP2.m").read_text()
start = source.index("typedef struct { uintptr_t address; unsigned index;")
end = source.index("_Static_assert", start)
scanner = source[start:end]
prefix = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include "NativeHTTP2Stubs.h"
#define MH_MAGIC_64 0xfeedfacf
#define KERN_SUCCESS 0
#define ptrauth_key_function_pointer 0
#undef ptrauth_strip
#define ptrauth_strip(pointer, key) (pointer)
typedef uintptr_t vm_address_t;
typedef size_t vm_size_t;
struct mach_header_64 { uint32_t magic; };
struct section_64 { uintptr_t addr; uint64_t size; };
static struct mach_header_64 headers[3];
static struct section_64 sections[3];
static const char *names[3];
static uint32_t imageCount;
static unsigned traces, reads;
static uintptr_t unreadable;
static BOOL shortRead;
/* All BL and ADRP destinations remain in architectural immediate range. */
static _Alignas(4096) uint32_t arena[16384];
static unsigned stubCount;
static const unsigned selected[] = {0,1,2,3,4,5,6,7};
static void *expected[8];
static uint32_t _dyld_image_count(void) { return imageCount; }
static const char *_dyld_get_image_name(uint32_t i) { return names[i]; }
static const struct mach_header_64 *_dyld_get_image_header(uint32_t i) { return &headers[i]; }
static intptr_t _dyld_get_image_vmaddr_slide(uint32_t i) { (void)i; return 0; }
static const struct section_64 *getsectbynamefromheader_64(const struct mach_header_64 *h,
    const char *segment, const char *section) {
    assert(!strcmp(segment,"__TEXT") && !strcmp(section,"__text"));
    return &sections[h - headers];
}
#undef mach_task_self
#define mach_task_self fake_mach_task_self
#define vm_read_overwrite fake_vm_read_overwrite
static int mach_task_self(void) { return 1; }
static int vm_read_overwrite(int task, vm_address_t address, vm_size_t size,
    vm_address_t out, vm_size_t *count) {
    assert(task == 1 && size == 16); reads++;
    uintptr_t first = (uintptr_t)&arena[4096];
    if (address == unreadable || address < first || address >= first + stubCount * 16 ||
        (address - first) % 16) { *count = 0; return -1; }
    memcpy((void *)out, (void *)address, size);
    *count = shortRead ? size - 1 : size; return KERN_SUCCESS;
}
static void SHDWCurlTrace(NSString *event, id unused, NSDictionary *details) {
    (void)unused; assert([event isEqualToString:@"http2.coverage.refused"]);
    assert(details[@"images"] && details[@"coverage"] && details[@"required"]); traces++;
}
'''
suffix = r'''
static uintptr_t stub(unsigned n, unsigned index) {
    uint32_t *words = &arena[4096 + n * 4];
    uintptr_t pc = (uintptr_t)words, target = (uintptr_t)expected[index];
    int64_t pages = ((int64_t)(target & ~(uintptr_t)4095) - (int64_t)(pc & ~(uintptr_t)4095)) / 4096;
    assert(pages >= -1048576 && pages < 1048576);
    uint32_t imm = (uint32_t)pages & 0x1fffff;
    words[0] = 0x90000010 | ((imm & 3) << 29) | ((imm >> 2) << 5);
    words[1] = 0x91000210 | ((uint32_t)(target & 4095) << 10);
    words[2] = 0xd61f0200; words[3] = 0xd4200020;
    if (stubCount <= n) stubCount = n + 1;
    return pc;
}
static void call(unsigned image, unsigned offset, uintptr_t target) {
    uint32_t *word = &arena[image * 1024 + offset];
    int64_t delta = (int64_t)target - (int64_t)(uintptr_t)word;
    assert(!(delta & 3) && delta >= -134217728 && delta < 134217728);
    *word = 0x94000000 | ((uint32_t)(delta / 4) & 0x03ffffff);
    if (sections[image].size < (offset + 1) * 4) sections[image].size = (offset + 1) * 4;
}
static void reset(void) {
    memset(arena, 0, sizeof(arena)); memset(expected, 0, sizeof(expected));
    memset(sections, 0, sizeof(sections));
    imageCount = 2; traces = reads = stubCount = 0; unreadable = 0; shortRead = NO;
    names[0] = "/System/Library/Frameworks/CFNetwork.framework/CFNetwork";
    names[1] = "/System/Library/Frameworks/Network.framework/Network";
    names[2] = "/unrelated/Other.framework/Other";
    for (unsigned i = 0; i < 3; i++) {
        headers[i].magic = MH_MAGIC_64; sections[i].addr = (uintptr_t)&arena[i * 1024];
        sections[i].size = 4;
    }
    for (unsigned j = 0; j < 8; j++) expected[selected[j]] = &arena[8192 + j * 4];
    for (unsigned j = 0; j < 8; j++) call(j / 4, j % 4, stub(j, selected[j]));
}
static void refuses(void) {
    H2Entry entries[64]; size_t count = 777;
    assert(!findEntries(expected, entries, &count));
    assert(count == 777 && traces == 1);
}
int main(void) { @autoreleasepool {
    H2Entry entries[64]; size_t count;
    reset(); assert(findEntries(expected, entries, &count) && count == 8 && !traces);
    for (unsigned j = 0; j < 8; j++) {
        assert(entries[j].index == selected[j]);
        assert(entries[j].address == (uintptr_t)&arena[4096 + j * 4]);
        assert(!memcmp(entries[j].bytes, (void *)entries[j].address, 16));
    }
    reset(); call(1, 4, (uintptr_t)&arena[4096]);
    assert(findEntries(expected, entries, &count) && count == 8 && reads == 8);
    reset(); /* A valid common stub to an unrelated target is ignored. */
    void *saved = expected[7];
    expected[7] = &arena[9000]; uintptr_t unrelated = stub(8, 7); expected[7] = saved;
    call(0, 8, unrelated); call(0, 9, (uintptr_t)&arena[12000]);
    arena[10] = 0x14000000; /* B is not BL. */
    imageCount = 3; headers[2].magic = 0; /* Unrelated images are not inspected. */
    assert(findEntries(expected, entries, &count) && count == 8 && !traces);
    reset(); unreadable = (uintptr_t)&arena[4096]; refuses();
    reset(); shortRead = YES; refuses();
    reset(); arena[0] = 0; refuses(); /* One selected target lacks any call. */
    reset(); imageCount = 1; refuses();
    reset(); names[1] = "/unrelated/Network"; refuses();
    reset(); headers[0].magic = 0; refuses();
    reset(); sections[0].size = 0; refuses();
    reset(); sections[0].size = 3; refuses();
    reset(); sections[0].size = 64 * 1024 * 1024 + 4; refuses();
    reset(); sections[0].addr++; refuses();
    for (unsigned word = 0; word < 4; word++) {
        reset(); arena[4096 + word] ^= 1; refuses(); /* Each exact opcode/register matters. */
    }
    reset(); /* Distinct matching entries up to capacity succeed. */
    for (unsigned j = 8; j < 64; j++) call(1, j, stub(j, 0));
    assert(findEntries(expected, entries, &count) && count == 64 && !traces);
    call(1, 64, stub(64, 0)); refuses();
    puts("native HTTP/2 discovery: coverage, deduplication, refusal and entry capacity passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-http2-discovery-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + scanner + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-framework", "Foundation", "-I", str(root / "src/Transport"),
                    str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
