"""Run production notification handlers with loader and client doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile
if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
def function(name):
    start = source.index("static void " + name + "(")
    body = source.index("{", start)
    depth = 1
    end = body + 1
    while depth:
        if source[end] == "{": depth += 1
        elif source[end] == "}": depth -= 1
        end += 1
    return source[start:end]
core = (root / "src/Shadow.framework/Headers/Shadow/Core.h").read_text()
macro = core[core.index("#define SHADOW_INTERNAL_SCOPE"):core.index("#endif", core.index("#define SHADOW_INTERNAL_SCOPE"))]
prefix = r'''
#import <Foundation/Foundation.h>
#include <mach-o/loader.h>
#include <assert.h>
static unsigned internalDepth;
@interface Shadow : NSObject
+ (void)shdwEnterInternalRead;
+ (void)shdwExitInternalRead;
+ (BOOL)shdwIsInternalRead;
@end
@implementation Shadow
+ (void)shdwEnterInternalRead { internalDepth++; }
+ (void)shdwExitInternalRead { assert(internalDepth); internalDepth--; }
+ (BOOL)shdwIsInternalRead { return internalDepth != 0; }
@end
#define SHADOW_MAX_IMAGE_LOAD_CBS 8
#define SHADOW_MAX_BULK_LOAD_CBS 8
#define SHADOW_DYLD_MIRROR_CAPACITY 256
static BOOL _shdw_dyld_bulk_registration_replay, _shdw_dyld_bulk_repair_available;
static BOOL _shdw_dyld_replay_in_progress, shdw_detector_present = YES;
static void *_shdw_dyld_rebind_session;
static NSMutableArray *_shdw_dyld_collection, *_shdw_dyld_add_image, *events;
static NSMutableDictionary *_shdw_dyld_pending_image_loads;
static struct mach_header images[202];
static BOOL nested, nestedClient, throwClient;
static unsigned repairCount, slotsCount;
static BOOL shdw_dyld_image_is_hidden(const void *h) { return h == &images[129]; }
static void (*shdw_image_load_cbs[SHADOW_MAX_IMAGE_LOAD_CBS])(const struct mach_header *, const char *, bool);
static void (*shdw_bulk_load_cbs[SHADOW_MAX_BULK_LOAD_CBS])(unsigned, const struct mach_header *[], const char *[]);
static void shdw_bulk_load_handler(unsigned, const struct mach_header *[], const char *[]);
static void shdw_image_load_handler(const struct mach_header *, const char *, bool);
static uint32_t SHDWRebindRepairSlots(void) { slotsCount++; return 0; }
static void SHDWRebindRepairImages(void *session, const struct mach_header *const *headers, size_t count) {
    (void)session; assert(internalDepth); assert(count && headers); repairCount++;
    if(nested) {
        nested = NO;
        const struct mach_header *sub[] = { &images[200] };
        shdw_bulk_load_handler(1, sub, NULL);
    }
}
static void shdw_objc_notify_image(const struct mach_header *h, const char *path) {
    (void)h; (void)path; assert(!internalDepth); [events addObject:@"objc"];
}
static void add_callback(const struct mach_header *h, intptr_t slide) {
    (void)h; assert(slide == 7 && repairCount); assert(!internalDepth);
    if(throwClient) @throw [NSException exceptionWithName:@"client" reason:nil userInfo:nil];
    [events addObject:@"add"];
    if(nestedClient) {
        nestedClient = NO;
        const struct mach_header *sub[] = { &images[200] }; const char *paths[] = { "nested" };
        shdw_image_load_handler(sub[0], paths[0], true);
        shdw_bulk_load_handler(1, sub, paths);
    }
}
static void image_callback(const struct mach_header *h, const char *path, bool unloadable) {
    (void)h; (void)path; assert(unloadable && repairCount); assert(!internalDepth); [events addObject:@"image"];
}
static void bulk_callback(unsigned count, const struct mach_header *headers[], const char *paths[]) {
    (void)headers; (void)paths; assert(count == 129 || count == 1); assert(repairCount && !internalDepth);
    [events addObject:@"bulk"];
}
'''
suffix = r'''
int main(void) { @autoreleasepool {
    _shdw_dyld_collection = [NSMutableArray new]; _shdw_dyld_add_image = [NSMutableArray new];
    events = [NSMutableArray new]; _shdw_dyld_pending_image_loads = [NSMutableDictionary new];
    [_shdw_dyld_add_image addObject:[NSValue valueWithPointer:add_callback]];
    shdw_image_load_cbs[0] = image_callback; shdw_bulk_load_cbs[0] = bulk_callback;
    const struct mach_header *headers[130]; const char *paths[130];
    for(unsigned i = 0; i < 130; i++) {
        headers[i] = &images[i]; paths[i] = "fixture";
        [_shdw_dyld_collection addObject:@{@"mach_header": [NSValue valueWithPointer:headers[i]],
            @"slide": [NSValue valueWithPointer:(void *)7]}];
    }
    [_shdw_dyld_collection addObject:@{@"mach_header": [NSValue valueWithPointer:&images[200]],
        @"slide": [NSValue valueWithPointer:(void *)7]}];
    _shdw_dyld_bulk_repair_available = YES;
    _shdw_dyld_bulk_registration_replay = YES;
    shdw_bulk_load_handler(130, headers, paths); assert(!events.count && !repairCount);
    _shdw_dyld_bulk_registration_replay = NO;
    for(unsigned i = 0; i < 130; i++) shdw_image_load_handler(headers[i], paths[i], true);
    assert(!events.count && _shdw_dyld_pending_image_loads.count == 129);
    shdw_bulk_load_handler(130, headers, paths);
    assert(repairCount == 1 && slotsCount == 1 && !internalDepth);
    assert(events.count == 129 * 3 + 1 && !_shdw_dyld_pending_image_loads.count);
    for(unsigned i = 0; i < 129; i++) assert([events[i] isEqual:@"add"]);
    for(unsigned i = 129; i < 129 * 3; i += 2) {
        assert([events[i] isEqual:@"image"] && [events[i + 1] isEqual:@"objc"]);
    }
    assert([events.lastObject isEqual:@"bulk"]);
    [events removeAllObjects]; nested = YES;
    shdw_bulk_load_handler(130, headers, paths);
    assert(!internalDepth && repairCount == 3 && _shdw_dyld_pending_image_loads.count == 0);
    [events removeAllObjects]; nestedClient = YES;
    shdw_bulk_load_handler(130, headers, paths);
    assert(!internalDepth && repairCount == 5 && !_shdw_dyld_pending_image_loads.count);
    [Shadow shdwEnterInternalRead]; [Shadow shdwEnterInternalRead]; throwClient = YES;
    @try { shdw_bulk_load_handler(130, headers, paths); assert(0); }
    @catch(NSException *exception) { assert([exception.name isEqual:@"client"]); }
    assert(internalDepth == 2);
    [Shadow shdwExitInternalRead]; [Shadow shdwExitInternalRead]; throwClient = NO;
    puts("loader notifications: exact bulk, synchronous repair before clients, registration replay, hidden images and nested scopes passed");
} }
'''
handlers = "\n".join(function(name) for name in (
    "shdw_forward_image_load", "shdw_image_load_handler", "shdw_bulk_load_handler"))
if "static void shdw_dyld_deliver_external(" in source:
    handlers = function("shdw_dyld_deliver_external") + "\n" + handlers
with tempfile.TemporaryDirectory(prefix="shadow-load-order-") as tmp:
    src = Path(tmp) / "test.m"; binary = Path(tmp) / "test"
    src.write_text(prefix + macro + handlers + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
