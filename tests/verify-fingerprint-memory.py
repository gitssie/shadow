"""Compile production memory policy/hooks with persisted per-app delta doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
policy = root / "src/ShadowCore.dylib/policy/FingerprintPolicy.m"
fingerprint = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()
syscall = (root / "src/ShadowCore.dylib/hooks/Universal/syscall.x").read_text()
libc = (root / "src/ShadowCore.dylib/hooks/Universal/libc_antidebugging.x").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


memory_group = fingerprint.index("%group shadowhook_fingerprint_memory")
hook_start = fingerprint.index("%hook NSProcessInfo", memory_group) + len("%hook NSProcessInfo")
physical = fingerprint[hook_start:fingerprint.index("%end", hook_start)]
physical = physical.replace("%orig", "[self nativePhysicalMemory]")
hooks = function(fingerprint, "static BOOL shdw_map_app_caller(") + "\n"
hooks += function(fingerprint, "BOOL shdw_fingerprint_sysctl_query(") + "\n"
hooks += function(fingerprint, "BOOL shdw_fingerprint_sysctl_mib_query(") + "\n"
hooks += function(fingerprint, "void shdw_fingerprint_sysctl_value(") + "\n"
hooks += function(syscall, "static int replaced_sysctlbyname(") + "\n"
hooks += function(syscall, "static int replaced___sysctlbyname(") + "\n"
hooks += function(libc, "int replaced_sysctl(") + "\n"
prefix = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
#import <Shadow/FingerprintMemory.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <math.h>
#include <errno.h>
#include <dlfcn.h>
#include <sys/sysctl.h>
static long long persistedDelta = -16384;
NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    assert(bundleID.length);
    return @{@"MemoryDelta": @(persistedDelta)};
}
@interface MemoryTestProcessInfo : NSObject
@end
@interface MemoryTestProcessInfo (NativeMemory)
- (unsigned long long)nativePhysicalMemory;
@end
@interface MemoryTestProcessInfo (Hooks)
- (unsigned long long)physicalMemory;
@end
@implementation MemoryTestProcessInfo @end
'''
hook_prefix = r'''
static unsigned internalDepth, nativePhysicalCalls;
static BOOL externalCaller = YES, shdw_fingerprint_enabled = YES;
static NSString *shdw_fingerprint_bundle_id = @"memory.hook";
static char shdw_map_bundle[] = "/Apps/Probe.app", shdw_map_canonical_bundle[] = "/private/Apps/Probe.app";
static const char *callerPath = "/Apps/Probe.app/Probe";
static const void *fakeCaller = (void *)1;
static uint64_t nativeMemory = UINT64_C(6) * 1024 * 1024 * 1024;
static BOOL shdw_caller_is_external(const void *caller) { return caller && externalCaller && !internalDepth; }
static BOOL SHDWNetworkQueryPathMatches(const char *path, const char *bundle) {
    size_t length = strlen(bundle);
    return !strncmp(path, bundle, length) && (!path[length] || path[length] == '/');
}
static int memory_dladdr(const void *caller, Dl_info *info) {
    (void)caller; assert(internalDepth); info->dli_fname = callerPath; return callerPath != NULL;
}
static void leave_scope(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++internalDepth, YES); active; active = NO)
#define dladdr memory_dladdr
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
static BOOL shdw_fingerprint_resource_caller(const void *caller) { (void)caller; return NO; }
typedef int (*SysctlFunction)(const char *, void *, size_t *, void *, size_t);
static int nativeStatus;
static size_t nativeLength = sizeof(uint64_t);
static unsigned nativeSysctlCalls;
static int nativeSysctl(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    (void)name; (void)newp; (void)newlen; nativeSysctlCalls++;
    if(out && length && *length >= sizeof(nativeMemory)) memcpy(out, &nativeMemory, sizeof(nativeMemory));
    if(length) *length = nativeLength;
    errno = EBUSY; return nativeStatus;
}
static SysctlFunction original_sysctlbyname = nativeSysctl, original___sysctlbyname = nativeSysctl;
static int shdw_sysctlbyname_policy(const char *name, void *out, size_t *length, void *newp,
    size_t newlen, SysctlFunction original) { return original(name, out, length, newp, newlen); }
typedef int (*MIBFunction)(int *, u_int, void *, size_t *, void *, size_t);
static int nativeMIB(int *name, u_int count, void *out, size_t *length, void *newp, size_t newlen) {
    (void)name; (void)count; return nativeSysctl(NULL, out, length, newp, newlen);
}
static MIBFunction original_sysctl = nativeMIB;
typedef enum {
    TEST_MIB_OTHER, SHADW_PROC_MIB_BOOTARGS, SHADW_PROC_MIB_PID_OTHER,
    SHADW_PROC_MIB_ARGS2_OTHER, SHADW_PROC_MIB_ARGS_OTHER, SHADW_PROC_MIB_LIST,
    SHADW_PROC_MIB_PID_SELF, SHADW_PROC_MIB_ARGS2_SELF, SHADW_PROC_MIB_ARGS_SELF
} shdw_proc_mib_kind_t;
static shdw_proc_mib_kind_t shdw_proc_mib_kind(int *name, u_int count) {
    (void)name; (void)count; return TEST_MIB_OTHER;
}
static int shdw_bootargs_filtered(void *out, size_t *length) {
    (void)out; (void)length; assert(!"unexpected MIB policy"); return -1;
}
static BOOL shdw_pid_is_restricted(int pid) { (void)pid; assert(!"unexpected PID policy"); return NO; }
static int shdw_proc_list_filtered(MIBFunction original, int *name, u_int count,
    void *out, size_t *length, BOOL reentrant) {
    (void)original; (void)name; (void)count; (void)out; (void)length; (void)reentrant;
    assert(!"unexpected process-list policy"); return -1;
}
static void shdw_proc_sanitize_self_record(struct kinfo_proc *record) {
    (void)record; assert(!"unexpected process-record policy");
}
static void shdw_procargs2_filter(void *out, size_t *length) {
    (void)out; (void)length; assert(!"unexpected procargs policy");
}
'''
hook_suffix = r'''
static int mibAdapter(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    int mib[] = {CTL_HW, !strcmp(name, "hw.memsize") ? HW_MEMSIZE : 0};
    return replaced_sysctl(mib, 2, out, length, newp, newlen);
}
@implementation MemoryTestProcessInfo (NativeMemory)
- (unsigned long long)nativePhysicalMemory {
    nativePhysicalCalls++; assert(internalDepth);
    uint64_t size = nativeMemory;
    shdw_fingerprint_sysctl_value("hw.memsize", &size, sizeof(size), fakeCaller);
    assert(size == nativeMemory);
    return size;
}
@end
static void verify_hooks(void) {
    persistedDelta = 8 * 16384;
    MemoryTestProcessInfo *info = [MemoryTestProcessInfo new];
    uint64_t expected = nativeMemory + 8 * 16384;
    assert(info.physicalMemory == expected && nativePhysicalCalls == 1 && !internalDepth);
    SysctlFunction wrappers[] = {replaced_sysctlbyname, replaced___sysctlbyname, mibAdapter};
    for(unsigned i = 0; i < sizeof(wrappers) / sizeof(wrappers[0]); i++) {
        SysctlFunction wrapper = wrappers[i];
        uint64_t value = 0; size_t length = sizeof(value); unsigned calls = nativeSysctlCalls;
        assert(!wrapper("hw.memsize", &value, &length, NULL, 0));
        assert(value == expected && length == sizeof(value) && errno == EBUSY && nativeSysctlCalls == calls + 1);
        for(NSString *path in @[@"/System/Library/Frameworks/Foundation.framework/Foundation",
            @"/usr/lib/swift/libswiftFoundation.dylib", @"/Apps/Probe.app.other/SDK"]) {
            callerPath = path.UTF8String; value = 0; length = sizeof(value);
            assert(!wrapper("hw.memsize", &value, &length, NULL, 0) && value == nativeMemory && errno == EBUSY);
            assert(info.physicalMemory == nativeMemory && !internalDepth);
        }
        callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
        length = sizeof(value); assert(!wrapper("hw.memsize", &value, &length, NULL, 0) && value == expected);
        callerPath = "/Apps/Probe.app/Probe";
        nativeStatus = -1; length = sizeof(value);
        assert(wrapper("hw.memsize", &value, &length, NULL, 0) == -1 && value == nativeMemory && errno == EBUSY);
        nativeStatus = 0;
        for(size_t invalid = 0; invalid < 16; invalid++) if(invalid != sizeof(value)) {
            nativeLength = invalid; length = sizeof(value);
            assert(!wrapper("hw.memsize", &value, &length, NULL, 0) && value == nativeMemory && length == invalid && errno == EBUSY);
        }
        nativeLength = sizeof(value); length = sizeof(value);
        assert(!wrapper("hw.memsize", &value, &length, &value, sizeof(value)) && value == nativeMemory);
        length = sizeof(value); assert(!wrapper("hw.other", &value, &length, NULL, 0) && value == nativeMemory);
        assert(!wrapper("hw.memsize", NULL, &length, NULL, 0));
        assert(!wrapper("hw.memsize", &value, NULL, NULL, 0));
        internalDepth = 2; length = sizeof(value);
        assert(!wrapper("hw.memsize", &value, &length, NULL, 0) && value == nativeMemory);
        assert(info.physicalMemory == nativeMemory && internalDepth == 2); internalDepth = 0;
        externalCaller = NO; assert(info.physicalMemory == nativeMemory); externalCaller = YES;
        fakeCaller = NULL; assert(info.physicalMemory == nativeMemory); fakeCaller = (void *)1;
        callerPath = NULL; assert(info.physicalMemory == nativeMemory); callerPath = "/Apps/Probe.app/Probe";
        shdw_fingerprint_enabled = NO; length = sizeof(value);
        assert(info.physicalMemory == nativeMemory);
        assert(!wrapper("hw.memsize", &value, &length, NULL, 0) && value == nativeMemory);
        shdw_fingerprint_enabled = YES;
    }
    uint64_t value = 0; size_t length = sizeof(value);
    int mib[] = {CTL_HW, HW_MEMSIZE, 0};
    assert(!replaced_sysctl(mib, 3, &value, &length, NULL, 0) && value == nativeMemory);
    length = sizeof(value);
    assert(!replaced_sysctl(NULL, 0, &value, &length, NULL, 0) && value == nativeMemory);
    assert(info.physicalMemory == expected && !internalDepth);
}
'''
suffix = r'''
static uint64_t distance(uint64_t a, uint64_t b) { return a > b ? a - b : b - a; }
static void verify_policy(void) {
    const uint64_t native = UINT64_C(6) * 1024 * 1024 * 1024;
    for(long long delta = -64; delta <= 64; delta++) {
        if(!delta) continue;
        persistedDelta = delta * 16384;
        uint64_t first = SHDWFingerprintMemorySize(@"memory.app", native);
        assert(first == native + persistedDelta);
        for(unsigned i = 0; i < 1000; i++)
            assert(SHDWFingerprintMemorySize(@"memory.app", native) == first);
        // A new native result retains the same persisted offset.
        assert(SHDWFingerprintMemorySize(@"memory.app", native + 7) == first + 7);
        assert(distance(first, native) >= 16384 && distance(first, native) <= 1048576);
    }
    persistedDelta = -16384;
    const uint64_t unaligned = UINT64_C(123456789);
    uint64_t value = SHDWFingerprintMemorySize(@"memory.unaligned", unaligned);
    assert(value == unaligned - 16384 && value % 16384 == unaligned % 16384);
    assert(SHDWFingerprintMemorySize(@"memory.zero", 0) == 0);
    assert(SHDWFingerprintMemorySize(@"memory.high", UINT64_MAX) == UINT64_MAX);
    assert(SHDWFingerprintMemorySize(@"memory.low", 8192) == 8192);
    assert(SHDWFingerprintMemorySize(@"memory.threshold", 1048576) == 1048576);
    assert(SHDWFingerprintMemorySize(nil, native) == native);
    assert(SHDWFingerprintMemorySize(@"", native) == native);
    persistedDelta = 18 * 16384;
    _Atomic(uint64_t) published = 0;
    _Atomic(unsigned) mismatches = 0;
    _Atomic(uint64_t) *publishedPtr = &published;
    _Atomic(unsigned) *mismatchPtr = &mismatches;
    dispatch_apply(2000, dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^(size_t i) {
        @autoreleasepool {
            (void)i;
            uint64_t result = SHDWFingerprintMemorySize(@"memory.concurrent", native);
            uint64_t expected = 0;
            atomic_compare_exchange_strong(publishedPtr, &expected, result);
            if(result != atomic_load(publishedPtr)) atomic_fetch_add(mismatchPtr, 1);
        }
    });
    assert(!atomic_load(&mismatches) && atomic_load(&published) == native + 18 * 16384);
}
int main(void) { @autoreleasepool {
    verify_policy();
    verify_hooks();
    puts("fingerprint memory: persisted delta/concurrency, physicalMemory and all three sysctl wrappers passed");
} }
'''

with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-memory-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    policy_source = policy.read_text()
    category = "\n@implementation MemoryTestProcessInfo (Hooks)\n" + physical + "\n@end\n"
    src.write_text(prefix + policy_source + "\n#undef NSProcessInfo\n" + hook_prefix +
                   hooks + category + hook_suffix + suffix)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation",
        "-I", str(policy.parent), "-I", str(root / "src/Shadow.framework/Headers"), str(src), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
