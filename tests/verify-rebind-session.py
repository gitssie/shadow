"""Exercise the production replay method with runtime and application doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/SHDWHookSession.m").read_text()
start = source.index("- (BOOL)replayRebindEntries:")
end = source.index("- (SHDWImageRef)openImage:", start)
method = source[start:end]
prefix = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <dlfcn.h>
typedef struct { int value; } hk_runtime_t;
typedef struct { size_t struct_size; int struct_version, install_context; } hk_runtime_config_t;
typedef int hk_status_t;
enum { HK_STATUS_OK, HK_ABI_VERSION_3_0, HK_INSTALL_CONTEXT_EARLY_PROCESS,
       HK_IMAGE_EXACT_HEADER, HK_IMAGE_EXPLICIT_SET, HK_SYMBOL_ALIAS_EXACT_ONLY };
typedef struct hk_image_selector {
    size_t struct_size; int struct_version, kind; const void *header;
    const struct hk_image_selector *const *explicit_set; size_t explicit_set_count;
} hk_image_selector_t;
typedef struct {
    struct { struct { hk_image_selector_t caller_image_scope;
        int alias_policy; } symbol; } target;
    const char *name; void *replacement; void **cell;
} hk_hook_spec_t;
typedef struct { const char *name; void *replacement; void **originalCell;
    BOOL *cacheScopeUnavailable; uint64_t imageMask; } SHDWRebindEntry;
typedef hk_status_t (*SHDWHKRuntimeCreateWithBackendOverride)(
    const hk_runtime_config_t *, const char *, hk_runtime_t **);
static char gSHDWBackendOverride[128];
static hk_runtime_t sharedRuntime;
static unsigned creates, overrideCreates, releases, attempts, borrowedAttempts, fallbackAttempts;
static char selectedBackend[128];
static BOOL failCreation, exposeOverride, failClean, failUnsafe, throwAttempt, failWrapperAllocation;
static void **expectedCell;
static int scenario;
static uint64_t covered, rejectedMasks, fakeCached;
static void *test_malloc(size_t size) { return failWrapperAllocation ? NULL : malloc(size); }
#define malloc test_malloc
static hk_status_t hk_runtime_create(const hk_runtime_config_t *config, hk_runtime_t **out) {
    assert(config->struct_size == sizeof(*config)); creates++;
    *out = failCreation ? NULL : &sharedRuntime;
    return failCreation ? -1 : HK_STATUS_OK;
}
static hk_status_t override_create(const hk_runtime_config_t *config,
    const char *backend, hk_runtime_t **out) {
    assert(backend && (!strcmp(backend, "strict") || !strcmp(backend, "fishhook")));
    overrideCreates++; strcpy(selectedBackend, backend);
    return hk_runtime_create(config, out);
}
static void hk_runtime_release(hk_runtime_t *runtime) { if(runtime) releases++; }
static void *fake_dlsym(void *handle, const char *name) {
    (void)handle; assert(!strcmp(name, "hk_runtime_create_with_backend_override"));
    return exposeOverride ? (void *)override_create : NULL;
}
#define dlsym fake_dlsym
static void shdw_init_rebind_spec(hk_hook_spec_t *spec, NSString *name,
    void *replacement, void **cell) {
    memset(spec, 0, sizeof(*spec)); spec->name = name.UTF8String;
    spec->replacement = replacement; spec->cell = cell;
}
static BOOL shdw_apply_hook_spec_once(const hk_hook_spec_t *spec, void **cell,
    const char *backend, SHDWHKRuntimeCreateWithBackendOverride create,
    BOOL *clean, BOOL *subsets, BOOL *cache, hk_runtime_t *borrowed) {
    (void)create;
    const hk_image_selector_t *scope = &spec->target.symbol.caller_image_scope;
    assert(scope->kind == HK_IMAGE_EXPLICIT_SET && scope->explicit_set_count && scope->explicit_set_count <= 64);
    uint64_t mask = 0;
    for(size_t j = 0; j < scope->explicit_set_count; j++) {
        const hk_image_selector_t *image = scope->explicit_set[j];
        assert(image->kind == HK_IMAGE_EXACT_HEADER);
        uintptr_t index = (uintptr_t)image->header / 0x1000 - 1;
        assert(index < 64); mask |= UINT64_C(1) << index;
    }
    attempts++; borrowedAttempts += borrowed != NULL; fallbackAttempts += borrowed == NULL;
    if(clean) *clean = NO; if(cache) *cache = NO; if(subsets) *subsets = NO;
    if(throwAttempt) @throw [NSException exceptionWithName:@"test" reason:nil userInfo:nil];
    if(spec->replacement == (void *)1) assert(cell == (expectedCell && !*expectedCell ? expectedCell : NULL));
    if(spec->replacement == (void *)2) assert(!cell);
    if(spec->replacement == (void *)3) { if(clean) *clean = YES; if(cache) *cache = YES; return NO; }
    if((scenario == 1 && (mask & 4)) || scenario == 2 || scenario == 3 || scenario == 5 ||
       (scenario == 4 && (mask & fakeCached))) {
        rejectedMasks |= mask;
        if(clean) *clean = scenario != 2;
        if(subsets) *subsets = scenario == 1 || scenario == 4 || scenario == 5;
        if(cache) *cache = scenario == 4;
        return NO;
    }
    if(backend && (failClean || failUnsafe)) { if(clean) *clean = failClean; return NO; }
    covered |= mask;
    if(cell) *cell = (void *)0x4567;
    return YES;
}
@interface SHDWHookSession : NSObject
- (BOOL)replayRebindEntries:(const SHDWRebindEntry *)entries count:(NSUInteger)count
    inCallerImage:(const void *)imageHeader;
- (BOOL)replayRebindEntries:(const SHDWRebindEntry *)entries count:(NSUInteger)count
    inCallerImages:(const void *const *)headers imageCount:(NSUInteger)imageCount cachedMask:(uint64_t)cached;
@end
@implementation SHDWHookSession
'''
suffix = r'''
@end
static void reset(void) {
    creates = overrideCreates = releases = attempts = borrowedAttempts = fallbackAttempts = 0;
    failCreation = exposeOverride = failClean = failUnsafe = throwAttempt = failWrapperAllocation = NO;
    gSHDWBackendOverride[0] = 0;
    selectedBackend[0] = 0;
    scenario = 0; covered = rejectedMasks = fakeCached = 0;
}
int main(void) { @autoreleasepool {
    SHDWHookSession *session = [SHDWHookSession new];
    void *missing = NULL, *live = (void *)0x1234;
    BOOL unavailable = NO;
    SHDWRebindEntry entries[] = {{"first", (void *)1, &missing, NULL, 0},
        {"second", (void *)2, &live, NULL, 0}, {"third", (void *)3, NULL, &unavailable, 0},
        {"fourth", (void *)4, NULL, NULL, 0},
        {NULL, (void *)4, NULL, NULL, 0}, {"invalid", NULL, NULL, NULL, 0}};
    reset(); expectedCell = &missing;
    assert([session replayRebindEntries:entries count:6 inCallerImage:(void *)0x1000]);
    assert(creates == 1 && releases == 1 && attempts == 4 && borrowedAttempts == 4);
    assert(!overrideCreates && !selectedBackend[0]);
    assert(missing == (void *)0x4567 && live == (void *)0x1234 && unavailable);
    reset(); expectedCell = NULL;
    assert([session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(attempts == 2 && releases == 1);
    reset(); exposeOverride = YES;
    assert([session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(creates == 1 && overrideCreates == 1 && !strcmp(selectedBackend, "fishhook"));
    assert(attempts == 2 && borrowedAttempts == 2 && !fallbackAttempts && releases == 1);
    reset(); exposeOverride = failClean = YES; strcpy(gSHDWBackendOverride, "strict");
    assert([session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(creates == 1 && releases == 1 && attempts == 4 && borrowedAttempts == 2 && fallbackAttempts == 2);
    assert(overrideCreates == 1 && !strcmp(selectedBackend, "strict"));
    reset(); exposeOverride = failUnsafe = YES; strcpy(gSHDWBackendOverride, "strict");
    assert([session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(attempts == 2 && !fallbackAttempts && releases == 1);
    reset(); failCreation = YES;
    assert(![session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(creates == 1 && !attempts && !releases);
    reset(); throwAttempt = YES;
    @try { [session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]; }
    @catch(NSException *exception) { (void)exception; }
    assert(attempts == 1 && releases == 1);
    reset();
    assert(![session replayRebindEntries:NULL count:2 inCallerImage:(void *)0x1000]);
    assert([session replayRebindEntries:entries count:0 inCallerImage:(void *)0x1000]);
    assert(![session replayRebindEntries:entries count:2 inCallerImage:NULL]);
    assert(!creates && !attempts);
    const void *headers[64];
    for(uintptr_t j = 0; j < 64; j++) headers[j] = (const void *)((j + 1) * 0x1000);
    SHDWRebindEntry batch = {"batch", (void *)1, &missing, &unavailable, 15};
    reset(); missing = NULL; expectedCell = &missing; unavailable = NO; scenario = 1;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(covered == 11 && attempts == 5 && creates == 1 && releases == 1 && missing);
    reset(); scenario = 2;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(attempts == 1 && !covered);
    reset(); scenario = 3;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(attempts == 1 && !covered);
    reset(); unavailable = NO; scenario = 4; fakeCached = 5;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:5]);
    assert(attempts == 2 && covered == 10 && unavailable);
    reset(); scenario = 4; fakeCached = 5;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:5]);
    assert(attempts == 1 && covered == 10 && !rejectedMasks);
    reset(); batch.imageMask = 0;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(!attempts && !creates);
    reset(); batch.imageMask = UINT64_C(1) << 63; unavailable = NO;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:64 cachedMask:0]);
    assert(attempts == 1 && covered == (UINT64_C(1) << 63));
    reset(); batch.imageMask = UINT64_MAX; scenario = 1;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:64 cachedMask:0]);
    assert(covered == (UINT64_MAX & ~UINT64_C(4)) && attempts == 13);
    reset(); scenario = 5;
    assert([session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:64 cachedMask:0]);
    assert(!covered && attempts == 127 && creates == 1 && releases == 1);
    reset(); failWrapperAllocation = YES;
    assert(![session replayRebindEntries:entries count:2 inCallerImage:(void *)0x1000]);
    assert(!creates && !attempts && live == (void *)0x1234);
    reset();
    SHDWRebindEntry scoped[] = {{"a", (void *)4, NULL, NULL, 1},
        {"b", (void *)4, NULL, NULL, 8}};
    assert([session replayRebindEntries:scoped count:2 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(attempts == 2 && covered == 9 && creates == 1 && releases == 1);
    reset(); failCreation = YES;
    assert(![session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert([session replayRebindEntries:NULL count:0 inCallerImages:headers imageCount:4 cachedMask:0]);
    assert(![session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:0 cachedMask:0]);
    assert(![session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:65 cachedMask:0]);
    assert(![session replayRebindEntries:NULL count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    headers[0] = NULL;
    assert(![session replayRebindEntries:&batch count:1 inCallerImages:headers imageCount:4 cachedMask:0]);
    puts("rebind session: shared runtime, independent entries, original cells, override fallback and cleanup passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-rebind-session-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + method + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
