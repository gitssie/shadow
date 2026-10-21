"""Exercise synchronous image replay before any queued task or client callback."""
from pathlib import Path
import subprocess
import tempfile
import sys

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/RebindRepair.x").read_text()
source = source.replace('#import "UniversalHooks.h"', '').replace('#import "../HookCoordinator.h"', '')
source = source.replace('#include "rebind_import_index.h"', '')
dyld = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
start = dyld.index('void shdw_universal_dyld_updatelibs(')
end = dyld.index('void shdw_universal_dyld_updatelibs_r(', start)
callback = dyld[start:end]
assert callback.index('SHDWRebindRepairSlots();') < callback.index('SHDWRebindRepairImage(')
assert callback.index('shadowhook_dyld_rebuild_dyldinfo();') < callback.index('SHDWRebindRepairImage(')
assert 'SHADOW_INTERNAL_SCOPE' in callback
assert callback.index('SHDWRebindRepairImage(') < callback.index('func(mh, vmaddr_slide);')
assert callback.index('if(_shdw_dyld_bulk_repair_available) return;') < callback.index('func(mh, vmaddr_slide);')
assert 'SHDWRequestRebindRepairImage' not in source + dyld
assert dyld.index('_shdw_dyld_rebind_session = hooks;') < dyld.index('_dyld_register_func_for_add_image(shdw_universal_dyld_updatelibs);')
prefix = r'''
#import <Foundation/Foundation.h>
#import <mach-o/dyld.h>
#include <assert.h>
#include <pthread.h>
typedef struct {
    const char *name; void *replacement; void **originalCell; BOOL *cacheScopeUnavailable; uint64_t imageMask;
} SHDWRebindEntry;
static NSMutableArray *calls, *tasks;
static int mode;
static pthread_t caller;
static unsigned char images[260][32];
static BOOL nested, nestedCohort, throwReplay, failReplay;
static int shdw_rebind_import_mask(const void *image, const char *const *names, size_t count, uint64_t *mask) {
    (void)image; (void)names; assert(count <= 4);
    mask[0] = mode == 1 ? 5 : (mode == 2 ? 0 : ((UINT64_C(1) << count) - 1));
    return mode != 0;
}
static void fake_async(dispatch_queue_t q, dispatch_block_t block) { (void)q; [tasks addObject:[block copy]]; }
extern const void *fake_cache_range(size_t *) __attribute__((weak_import));
const void *fake_cache_range(size_t *size) { *size = mode == 3 ? sizeof(images) : 0; return mode == 3 ? images : NULL; }
#define _dyld_get_shared_cache_range fake_cache_range
#define dispatch_async fake_async
uint32_t SHDWRebindRepairSlots(void) { return 0; }
@interface SHDWHookSession : NSObject
- (BOOL)replayRebindEntries:(const SHDWRebindEntry *)entries count:(NSUInteger)count
    inCallerImages:(const void *const *)headers imageCount:(NSUInteger)imageCount cachedMask:(uint64_t)cached;
@end
'''
suffix = r'''
@implementation SHDWHookSession
- (BOOL)replayRebindEntries:(const SHDWRebindEntry *)entries count:(NSUInteger)count
    inCallerImages:(const void *const *)headers imageCount:(NSUInteger)imageCount cachedMask:(uint64_t)cached {
    (void)cached;
    assert(pthread_equal(caller, pthread_self()));
    if(throwReplay) @throw [NSException exceptionWithName:@"test" reason:nil userInfo:nil];
    if(failReplay) return NO;
    if(nestedCohort) {
        nestedCohort = NO;
        const struct mach_header *nestedImages[] = {(const struct mach_header *)images[200]};
        SHDWRebindRepairImages(self, nestedImages, 1);
    }
    for (NSUInteger i = 0; i < count; i++) {
        const SHDWRebindEntry *entry = &entries[i];
        for(NSUInteger j = 0; j < imageCount; j++) if(entry->imageMask & (UINT64_C(1) << j))
            [calls addObject:@{ @"name": @(entry->name), @"header": [NSValue valueWithPointer:headers[j]] }];
        if (entry->originalCell && !*entry->originalCell) *entry->originalCell = (void *)0x1234;
        if (mode == 3) *entry->cacheScopeUnavailable = YES;
        if (nested) {
            nested = NO;
            SHDWRebindRepairImage(self, images[1]);
            assert(calls.count == 4);
        }
    }
    return YES;
}
@end
int main(void) { @autoreleasepool {
    tasks = [NSMutableArray new]; calls = [NSMutableArray new]; caller = pthread_self();
    SHDWHookSession *session = [SHDWHookSession new];
    void *live = (void *)0x5678, *missing = NULL;
    SHDWRebindJournalNote("access", (void *)1, &live);
    SHDWRebindJournalNote("vm_protect", (void *)2, &missing);
    SHDWRebindJournalNote("open", (void *)3, NULL);
    SHDWRebindRepairImage(session, images[0]);
    assert(calls.count == 3 && !tasks.count && live == (void *)0x5678 && missing == (void *)0x1234);
    assert([calls[0][@"name"] isEqual:@"vm_protect"]);
    assert([calls[1][@"name"] isEqual:@"access"] && [calls[2][@"name"] isEqual:@"open"]);
    [calls removeAllObjects]; mode = 1;
    SHDWRebindRepairImage(session, images[0]);
    assert(calls.count == 2 && [calls[0][@"name"] isEqual:@"access"]);
    [calls removeAllObjects]; mode = 2;
    SHDWRebindRepairImage(session, images[0]); assert(!calls.count);
    mode = 0; nested = YES;
    SHDWRebindRepairImage(session, images[0]); assert(calls.count == 6 && !tasks.count);
    [calls removeAllObjects]; mode = 3;
    SHDWRebindRepairImage(session, images[0]); assert(calls.count == 3);
    [calls removeAllObjects]; SHDWRebindRepairImage(session, images[1]); assert(!calls.count);
    mode = 0; SHDWRebindRepairImage(session, images[1]); assert(calls.count == 3);
    [calls removeAllObjects];
    const struct mach_header *loaded[130];
    for(unsigned i = 0; i < 130; i++) loaded[i] = (const struct mach_header *)images[i];
    SHDWRebindRepairImages(session, loaded, 130);
    assert(calls.count == 390 && !tasks.count);
    NSMutableSet *covered = [NSMutableSet new];
    for(NSDictionary *call in calls) [covered addObject:call[@"header"]];
    assert(covered.count == 130 && ![covered containsObject:[NSValue valueWithPointer:images[200]]]);
    [calls removeAllObjects]; nestedCohort = YES;
    SHDWRebindRepairImages(session, loaded, 130); assert(calls.count == 393 && !tasks.count);
    [calls removeAllObjects]; failReplay = YES;
    SHDWRebindRepairImages(session, loaded, 130); assert(!calls.count);
    failReplay = NO; SHDWRebindRepairImages(session, loaded, 130); assert(calls.count == 390);
    [calls removeAllObjects]; throwReplay = YES;
    @try { SHDWRebindRepairImages(session, loaded, 130); assert(0); }
    @catch(NSException *exception) { assert([exception.name isEqual:@"test"]); }
    throwReplay = NO; SHDWRebindRepairImages(session, loaded, 130); assert(calls.count == 390);
    puts("image replay: synchronous, guard first, conservative import mask, exact loader batches, nested loads, exceptions and callback ordering passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-rebind-sync-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + source + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
