"""Run production version policy and API hooks with deterministic native doubles."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
policy = root / "src/ShadowCore.dylib/policy/FingerprintPolicy.m"
fingerprint = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()
libc = (root / "src/ShadowCore.dylib/hooks/Universal/libc_antidebugging.x").read_text()
syscall = (root / "src/ShadowCore.dylib/hooks/Universal/syscall.x").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


hooks = function(fingerprint, "static BOOL shdw_map_app_caller(") + "\n"
hooks += function(fingerprint, "BOOL shdw_fingerprint_sysctl_query(") + "\n"
hooks += function(fingerprint, "BOOL shdw_fingerprint_sysctl_mib_query(") + "\n"
hooks += function(fingerprint, "void shdw_fingerprint_sysctl_value(") + "\n"
hooks += function(syscall, "static int replaced_sysctlbyname(") + "\n"
hooks += function(syscall, "static int replaced___sysctlbyname(") + "\n"
hooks += function(libc, "int replaced_sysctl(") + "\n"
hooks += function(fingerprint, "void shdw_fingerprint_uname_value(") + "\n"
hooks += function(libc, "int replaced_uname(") + "\n"
# Negative control: disable only the early named-query seam in the temporary source.
if "--without-early-query" in sys.argv:
    hooks = hooks.replace("if(shdw_fingerprint_sysctl_query(", "if(NO && shdw_fingerprint_sysctl_query(")
libc_installer = (root / "src/ShadowCore.dylib/hooks/Universal/libc.x").read_text()
descriptor_end = libc_installer.index("} shdw_hook_desc_t;") + len("} shdw_hook_desc_t;")
descriptor_start = libc_installer.rindex("typedef struct {", 0, descriptor_end)
descriptor = libc_installer[descriptor_start:descriptor_end]
assert re.search(r'\{\s*"uname",\s*\(void\*\)&replaced_uname,\s*\(void\*\*\)&original_uname,\s*ANTIDBG,\s*0\s*\}', libc_installer)
fallback = function(libc_installer, "static void shdw_libc_rebind_proclist(")
replay = function(libc, "void shdw_universal_antidebugging_rebind_image(")
assert replay.count('hookRebindSymbol:@"uname"') == 1
features = (root / "src/ShadowCore.dylib/hooks/Universal/UniversalFeatures.x").read_text()
assert features.count("shdw_universal_antidebugging_rebind_image(hooks, imageHeader);") == 1

version_group = fingerprint.index("%group shadowhook_fingerprint_version")
version_end = fingerprint.index("%group shadowhook_fingerprint_memory", version_group)
version_hooks = fingerprint[version_group:version_end]
# Compile the real Logos method bodies as ordinary Objective-C categories.
methods = ""
for name, replacement in [("UIDevice", "VersionTestDevice"), ("NSProcessInfo", "VersionTestProcessInfo")]:
    start = version_hooks.index("%hook " + name) + len("%hook " + name)
    body = version_hooks[start:version_hooks.index("%end", start)]
    for selector in ["systemVersion", "operatingSystemVersion", "operatingSystemVersionString"]:
        signature = next((line for line in body.splitlines() if line.startswith("- (") and selector + " {" in line), None)
        if signature:
            method = function(body, signature).replace("%orig", "[self native" + selector[0].upper() + selector[1:] + "]")
            methods += "\n@implementation " + replacement + " (" + selector + ")\n" + method + "\n@end\n"

predicate = function(version_hooks, "- (BOOL)isOperatingSystemAtLeastVersion:")
predicate = predicate.replace("%orig", "[self nativeIsOperatingSystemAtLeastVersion:version]")
methods += "\n@implementation VersionTestProcessInfo (VersionPredicate)\n" + predicate + "\n@end\n"
assert "shadowhook_fingerprint_boot" not in fingerprint
assert "systemUptime {" not in fingerprint
assert "NSProcessInfo = processInfoClass" in fingerprint

prefix = r'''
#import <Foundation/Foundation.h>
NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    (void)bundleID;
    return @{@"MemoryDelta": @16384,
        @"NativeBootTimestamp": @1600000000.25, @"BootTimeOffset": @3600,
        @"BootSessionUUID": @"12345678-ABCD-1234-ABCD-123456789ABC"};
}

#include <assert.h>
#include <errno.h>
#include <dlfcn.h>
#include <stdint.h>
#include <string.h>
#include <sys/sysctl.h>
#include <sys/utsname.h>
#include <sys/time.h>
#include <math.h>
static unsigned internalDepth;
static BOOL requireBootInternal;
static double policyNativeBoot = 1700000000.25;
static int policyBootStatus;
static size_t policyBootLength = sizeof(struct timeval);
static int versionPolicySysctl(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    assert(!strcmp(name, "kern.boottime") && !newp && !newlen);
    if(requireBootInternal) assert(internalDepth);
    struct timeval boot = {(time_t)floor(policyNativeBoot),
        (suseconds_t)llround((policyNativeBoot - floor(policyNativeBoot)) * 1000000)};
    if(out && length && *length >= sizeof(boot)) memcpy(out, &boot, sizeof(boot));
    if(length) *length = policyBootLength;
    errno = EIO; return policyBootStatus;
}
#define sysctlbyname versionPolicySysctl
@interface VersionTestDevice : NSObject
- (NSString *)nativeSystemVersion;
@end
@interface VersionTestDevice (systemVersion)
- (NSString *)systemVersion;
@end
@implementation VersionTestDevice
- (NSString *)nativeSystemVersion { return @"16.3"; }
@end
@interface VersionTestProcessInfo : NSObject
- (NSTimeInterval)systemUptime;
- (BOOL)nativeIsOperatingSystemAtLeastVersion:(NSOperatingSystemVersion)version;
- (NSOperatingSystemVersion)nativeOperatingSystemVersion;
- (NSString *)nativeOperatingSystemVersionString;
@end
@interface VersionTestProcessInfo (operatingSystemVersion)
- (NSOperatingSystemVersion)operatingSystemVersion;
@end
@interface VersionTestProcessInfo (operatingSystemVersionString)
- (NSString *)operatingSystemVersionString;
@end
@interface VersionTestProcessInfo (VersionPredicate)
- (BOOL)isOperatingSystemAtLeastVersion:(NSOperatingSystemVersion)version;
@end
static unsigned nativePredicateCalls;
@implementation VersionTestProcessInfo
- (NSTimeInterval)systemUptime { return 100000; }
- (BOOL)nativeIsOperatingSystemAtLeastVersion:(NSOperatingSystemVersion)version {
    nativePredicateCalls++;
    return version.majorVersion < 16 || (version.majorVersion == 16 &&
        (version.minorVersion < 3 || (version.minorVersion == 3 && version.patchVersion <= 0)));
}
- (NSOperatingSystemVersion)nativeOperatingSystemVersion { return (NSOperatingSystemVersion){16, 3, 0}; }
- (NSString *)nativeOperatingSystemVersionString { return @"Version 16.3 (Build 20D47)"; }
@end
'''
hook_prefix = r'''
static unsigned nativeCalls;
static BOOL externalCaller = YES, shdw_fingerprint_enabled = YES;
static NSString *shdw_fingerprint_bundle_id = @"version.test";
static char shdw_map_bundle[] = "/Apps/Probe.app", shdw_map_canonical_bundle[] = "/private/Apps/Probe.app";
static const char *callerPath = "/Apps/Probe.app/Probe";
static const void *fakeCaller = (void *)1;
static BOOL shdw_caller_is_external(const void *caller) { return caller && externalCaller && !internalDepth; }
static BOOL SHDWNetworkQueryPathMatches(const char *path, const char *bundle) {
    size_t length = strlen(bundle);
    return !strncmp(path, bundle, length) && (!path[length] || path[length] == '/');
}
static int version_dladdr(const void *caller, Dl_info *info) {
    (void)caller; assert(internalDepth); info->dli_fname = callerPath; errno = EIO; return callerPath != NULL;
}
static void leave_scope(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++internalDepth, YES); active; active = NO)
#define dladdr version_dladdr
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
static unsigned nativeUnameCalls;
static int nativeUnameStatus;
static struct utsname nativeUnameValue;
static int nativeUname(struct utsname *value) {
    nativeUnameCalls++;
    if(value) memcpy(value, &nativeUnameValue, sizeof(*value));
    errno = EBUSY; return nativeUnameStatus;
}
static int (*original_uname)(struct utsname *) = nativeUname;
static BOOL shdw_fingerprint_resource_caller(const void *caller) { (void)caller; return NO; }
typedef int (*SysctlFunction)(const char *, void *, size_t *, void *, size_t);
static int nativeStatus = -1;
static int nativeSysctl(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    (void)name; (void)out; (void)length; (void)newp; (void)newlen; nativeCalls++;
    errno = EBUSY; return nativeStatus;
}
static SysctlFunction original_sysctlbyname = nativeSysctl, original___sysctlbyname = nativeSysctl;
static int shdw_sysctlbyname_policy(const char *name, void *out, size_t *length, void *newp,
    size_t newlen, SysctlFunction original) { return original(name, out, length, newp, newlen); }

static int version_nametomib(const char *name, int *mib, size_t *count) {
    assert(internalDepth && *count >= 2);
    mib[0] = CTL_KERN;
    mib[1] = !strcmp(name, "kern.osproductversion") ? 9001 : !strcmp(name, "kern.osversion") ? 9002 :
        !strcmp(name, "kern.boottime") ? 9003 : !strcmp(name, "kern.bootsessionuuid") ? 9004 :
        !strcmp(name, "kern.osrelease") ? 9005 : !strcmp(name, "kern.version") ? 9006 : 9007;
    *count = 2; errno = EIO; return 0;
}
#define sysctlnametomib version_nametomib
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
install_prefix = r'''
#define SHADW_HOOK_GROUP_ANTIDEBUG 8
static unsigned rebindRequests, unameReplays;
static BOOL rebindSuccess;
static void *rebindPredecessor;
static const void *expectedImage;
@interface SHDWHookSession : NSObject
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell;
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell inCallerImage:(const void *)image;
@end
@implementation SHDWHookSession
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell {
    assert([symbol isEqual:@"uname"] && replacement == (void *)replaced_uname && cell);
    rebindRequests++;
    *cell = rebindPredecessor;
    return rebindSuccess;
}
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell inCallerImage:(const void *)image {
    assert(image == expectedImage && !cell && replacement);
    rebindRequests++;
    if([symbol isEqual:@"uname"]) {
        assert(replacement == (void *)replaced_uname); unameReplays++;
    }
    return YES;
}
@end
static void *original_getppid, *resolved_getppid, *original_getuid, *resolved_getuid,
    *original_geteuid, *resolved_geteuid, *original_getgid, *resolved_getgid,
    *original_getegid, *resolved_getegid, *original_issetugid, *resolved_issetugid;
static void replaced_getppid(void) {}
static void replaced_getuid(void) {}
static void replaced_geteuid(void) {}
static void replaced_getgid(void) {}
static void replaced_getegid(void) {}
static void replaced_issetugid(void) {}
static void *replayDlsym(void *handle, const char *name) { (void)handle; (void)name; return NULL; }
#define dlsym replayDlsym
'''
install_source = install_prefix + descriptor + "\n" + fallback + "\n" + replay + "\n#undef dlsym\n"

suffix = r'''
static const char expectedKernel[] = "Darwin Kernel Version 24.6.0: Tue Aug 12 00:02:59 PDT 2025; root:xnu-11417.140.69.700.6~5/RELEASE_ARM64_T8110";
static int mibAdapter(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    int mib[] = {CTL_KERN, name && !strcmp(name, "kern.osproductversion") ? 9001 :
        name && !strcmp(name, "kern.osversion") ? 9002 :
        name && !strcmp(name, "kern.boottime") ? 9003 :
        name && !strcmp(name, "kern.bootsessionuuid") ? 9004 :
        name && !strcmp(name, "kern.osrelease") ? 9005 :
        name && !strcmp(name, "kern.version") ? 9006 : 9007};
    return replaced_sysctl(name ? mib : NULL, name ? 2 : 0, out, length, newp, newlen);
}
static void verify_native_string_contract(void) {
    size_t needed = 0;
    assert(!sysctlbyname("kern.osversion", NULL, &needed, NULL, 0) && needed > 1);
    for(size_t capacity = 0; capacity < needed; capacity++) {
        unsigned char *buffer = malloc(needed + 2); assert(buffer);
        memset(buffer, 0xa5, needed + 2);
        size_t length = capacity;
        assert(sysctlbyname("kern.osversion", buffer + 1, &length, NULL, 0) == -1);
        assert(errno == ENOMEM && !length);
        for(size_t i = 0; i < needed + 2; i++) assert(buffer[i] == 0xa5);
        free(buffer);
    }
    errno = EDOM;
    assert(!sysctlbyname("kern.osversion", NULL, NULL, NULL, 0) && errno == EDOM);
    char untouched[8] = "native";
    assert(sysctlbyname("kern.osversion", untouched, NULL, NULL, 0) == -1);
    assert(errno == ENOMEM && !strcmp(untouched, "native"));
}
static void verify_policy(void) {
    NSOperatingSystemVersion version = SHDWFingerprintOSVersion();
    assert(version.majorVersion == 18 && version.minorVersion == 7 && version.patchVersion == 1);
    assert([SHDWFingerprintOSVersionString() isEqual:@"18.7.1"]);
    const char *names[] = {"kern.osproductversion", "kern.osversion", "kern.osrelease", "kern.version"};
    const char *values[] = {"18.7.1", "22H31", "24.6.0", expectedKernel};
    for(unsigned i = 0; i < 4; i++) {
        const char *expected = values[i]; size_t needed = strlen(expected) + 1;
        assert(!strcmp(SHDWFingerprintVersionValue(names[i]), expected));
        int result = 71; size_t length = 999;
        errno = EDOM;
        assert(SHDWFingerprintVersionQuery(names[i], NULL, &length, &result));
        assert(!result && length == needed && errno == EDOM);
        for(size_t capacity = 0; capacity <= needed + 3; capacity++) {
            unsigned char buffer[1024]; memset(buffer, 0xa5, sizeof(buffer));
            length = capacity; result = 71; errno = EDOM;
            assert(SHDWFingerprintVersionQuery(names[i], buffer + 1, &length, &result));
            size_t copied = capacity < needed ? 0 : needed;
            assert(!memcmp(buffer + 1, expected, copied));
            assert(buffer[0] == 0xa5);
            for(size_t tail = copied + 1; tail < sizeof(buffer); tail++) assert(buffer[tail] == 0xa5);
            assert(length == copied);
            assert(result == (capacity < needed ? -1 : 0));
            assert(errno == (capacity < needed ? ENOMEM : EDOM));
        }
        result = 71; errno = EDOM;
        assert(SHDWFingerprintVersionQuery(names[i], NULL, NULL, &result));
        assert(!result && errno == EDOM);
        char untouched[8] = "native"; errno = EDOM;
        assert(SHDWFingerprintVersionQuery(names[i], untouched, NULL, &result));
        assert(result == -1 && errno == ENOMEM && !strcmp(untouched, "native"));
    }
    const char *unknown[] = {NULL, "kern.osrelease.extra", "kern.osversion.extra", "hw.memsize"};
    for(unsigned i = 0; i < 4; i++) {
        char buffer[8] = "native"; size_t length = 7; int result = 71; errno = EDOM;
        assert(!SHDWFingerprintVersionValue(unknown[i]));
        assert(!SHDWFingerprintVersionQuery(unknown[i], buffer, &length, &result));
        assert(!strcmp(buffer, "native") && length == 7 && result == 71 && errno == EDOM);
    }
}
static void verify_foundation(BOOL mapped) {
    VersionTestDevice *device = [VersionTestDevice new];
    VersionTestProcessInfo *info = [VersionTestProcessInfo new];
    assert(info.systemUptime == 100000);
    assert([device.systemVersion isEqual:(mapped ? @"18.7.1" : @"16.3")]);
    NSOperatingSystemVersion version = info.operatingSystemVersion;
    assert(version.majorVersion == (mapped ? 18 : 16));
    assert(version.minorVersion == (mapped ? 7 : 3) && version.patchVersion == (mapped ? 1 : 0));
    assert([info.operatingSystemVersionString isEqual:(mapped ? @"Version 18.7.1 (Build 22H31)" : @"Version 16.3 (Build 20D47)")]);
}
static void passthrough(SysctlFunction wrapper, const char *name, void *newp, size_t newlen) {
    char buffer[32] = "native"; size_t length = sizeof(buffer); unsigned before = nativeCalls;
    nativeStatus = -1;
    assert(wrapper(name, buffer, &length, newp, newlen) == -1 && errno == EBUSY);
    assert(nativeCalls == before + 1 && !strcmp(buffer, "native") && length == sizeof(buffer));
    nativeStatus = 0;
    assert(!wrapper(name, buffer, &length, newp, newlen) && errno == EBUSY);
    assert(nativeCalls == before + 2 && !strcmp(buffer, "native") && length == sizeof(buffer));
    nativeStatus = -1;
}
static void verify_hooks(void) {
    SysctlFunction wrappers[] = {replaced_sysctlbyname, replaced___sysctlbyname, mibAdapter};
    const char *names[] = {"kern.osproductversion", "kern.osversion", "kern.osrelease", "kern.version"};
    const char *values[] = {"18.7.1", "22H31", "24.6.0", expectedKernel};
    verify_foundation(YES);
    for(unsigned w = 0; w < 3; w++) for(unsigned n = 0; n < 4; n++) {
        SysctlFunction wrapper = wrappers[w]; const char *name = names[n];
        size_t needed = strlen(values[n]) + 1, length = 999; unsigned before = nativeCalls;
        errno = EDOM;
        assert(!wrapper(name, NULL, &length, NULL, 0));
        assert(length == needed && errno == EDOM && nativeCalls == before);
        for(size_t capacity = 0; capacity <= needed + 2; capacity++) {
            unsigned char buffer[1024]; memset(buffer, 0xa5, sizeof(buffer)); length = capacity; errno = EDOM;
            int status = wrapper(name, buffer + 1, &length, NULL, 0);
            size_t copied = capacity < needed ? 0 : needed;
            assert(status == (capacity < needed ? -1 : 0));
            assert(errno == (capacity < needed ? ENOMEM : EDOM));
            assert(length == copied && !memcmp(buffer + 1, values[n], copied));
            assert(buffer[0] == 0xa5 && nativeCalls == before);
            for(size_t tail = copied + 1; tail < sizeof(buffer); tail++) assert(buffer[tail] == 0xa5);
        }
        errno = EDOM;
        assert(!wrapper(name, NULL, NULL, NULL, 0) && errno == EDOM && nativeCalls == before);
        char untouched[8] = "native"; errno = EDOM;
        assert(wrapper(name, untouched, NULL, NULL, 0) == -1 && errno == ENOMEM);
        assert(!strcmp(untouched, "native") && nativeCalls == before);
        for(NSString *path in @[@"/System/Library/Frameworks/Foundation.framework/Foundation",
            @"/usr/lib/swift/libswiftFoundation.dylib", @"/Apps/Probe.app.other/SDK"]) {
            callerPath = path.UTF8String; passthrough(wrapper, name, NULL, 0); verify_foundation(NO);
        }
        callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
        length = 0; assert(!wrapper(name, NULL, &length, NULL, 0) && length == needed); verify_foundation(YES);
        callerPath = "/Apps/Probe.app/Probe";
        char input = 1; passthrough(wrapper, name, &input, 1);
        passthrough(wrapper, name, &input, 0); passthrough(wrapper, name, NULL, 1);
        passthrough(wrapper, "kern.osrelease.extra", NULL, 0); passthrough(wrapper, NULL, NULL, 0);
        internalDepth = 2; passthrough(wrapper, name, NULL, 0); verify_foundation(NO);
        assert(internalDepth == 2); internalDepth = 0;
        externalCaller = NO; passthrough(wrapper, name, NULL, 0); verify_foundation(NO); externalCaller = YES;
        fakeCaller = NULL; passthrough(wrapper, name, NULL, 0); verify_foundation(NO); fakeCaller = (void *)1;
        callerPath = NULL; passthrough(wrapper, name, NULL, 0); verify_foundation(NO); callerPath = "/Apps/Probe.app/Probe";
        shdw_fingerprint_enabled = NO; passthrough(wrapper, name, NULL, 0); verify_foundation(NO); shdw_fingerprint_enabled = YES;
    }
    char buffer[32] = "native"; size_t length = sizeof(buffer); unsigned before = nativeCalls;
    int mib[] = {CTL_KERN, 9001, 42};
    assert(replaced_sysctl(mib, 3, buffer, &length, NULL, 0) == -1);
    assert(nativeCalls == before + 1 && errno == EBUSY && !strcmp(buffer, "native"));
    assert(!internalDepth);
}
static void verify_boot(void) {
    const char *names[] = {"kern.boottime", "kern.bootsessionuuid"};
    struct timeval boot = {1700003600, 250000};
    const char uuid[] = "12345678-ABCD-1234-ABCD-123456789ABC";
    const void *values[] = {&boot, uuid};
    const size_t sizes[] = {sizeof(boot), sizeof(uuid)};
    SysctlFunction wrappers[] = {replaced_sysctlbyname, replaced___sysctlbyname, mibAdapter};
    requireBootInternal = YES;
    for(unsigned n = 0; n < 2; n++) {
        assert(SHDWFingerprintBootName(names[n]));
        for(unsigned w = 0; w < 3; w++) {
            SysctlFunction wrapper = wrappers[w];
            unsigned calls = nativeCalls;
            size_t needed = sizes[n], length = 0;
            errno = EDOM;
            assert(!wrapper(names[n], NULL, &length, NULL, 0));
            assert(length == needed && nativeCalls == calls && errno == EDOM);
            for(size_t capacity = 0; capacity <= needed + 2; capacity++) {
                unsigned char buffer[80]; memset(buffer, 0xa5, sizeof(buffer));
                length = capacity; errno = EDOM;
                int status = wrapper(names[n], buffer + 1, &length, NULL, 0);
                size_t copied = capacity < needed ? 0 : needed;
                assert(status == (capacity < needed ? -1 : 0));
                assert(length == copied && !memcmp(buffer + 1, values[n], copied));
                assert(nativeCalls == calls && errno == (capacity < needed ? ENOMEM : EDOM));
                assert(buffer[0] == 0xa5);
                for(size_t tail = copied + 1; tail < sizeof(buffer); tail++) assert(buffer[tail] == 0xa5);
            }
            errno = EDOM;
            assert(!wrapper(names[n], NULL, NULL, NULL, 0) && errno == EDOM);
            unsigned char untouched[64]; memset(untouched, 0xa5, sizeof(untouched));
            assert(wrapper(names[n], untouched, NULL, NULL, 0) == -1 && errno == ENOMEM);
            for(unsigned i = 0; i < sizeof(untouched); i++) assert(untouched[i] == 0xa5);
            assert(nativeCalls == calls);
            char input = 1;
            passthrough(wrapper, names[n], &input, 1);
            passthrough(wrapper, names[n], &input, 0);
            passthrough(wrapper, names[n], NULL, 1);
            internalDepth = 2; passthrough(wrapper, names[n], NULL, 0); internalDepth = 0;
            externalCaller = NO; passthrough(wrapper, names[n], NULL, 0); externalCaller = YES;
            callerPath = "/System/Library/Frameworks/Foundation.framework/Foundation";
            passthrough(wrapper, names[n], NULL, 0);
            callerPath = "/Apps/Probe.app/Probe";
            shdw_fingerprint_enabled = NO; passthrough(wrapper, names[n], NULL, 0); shdw_fingerprint_enabled = YES;
        }
    }
    requireBootInternal = NO;
    int result = 42; size_t length = 7; unsigned char bytes[8] = {0};
    assert(!SHDWFingerprintBootName(NULL) && !SHDWFingerprintBootName("kern.boottime.extra"));
    assert(!SHDWFingerprintBootQuery("kern.boottime.extra", bytes, &length, &result));
    assert(result == 42 && length == 7);
    assert(!SHDWFingerprintBootQuery("kern.boottime", bytes, &length, NULL));
}
static void verify_version_predicate(void) {
    struct { NSOperatingSystemVersion request; BOOL mapped, native; } cases[] = {
        {{18,7,0},YES,NO}, {{18,7,1},YES,NO}, {{18,7,2},NO,NO},
        {{18,8,0},NO,NO}, {{19,0,0},NO,NO}, {{17,99,99},YES,NO},
        {{18,6,99},YES,NO}, {{16,3,0},YES,YES}, {{16,3,1},YES,NO}, {{15,99,99},YES,YES}
    };
    VersionTestProcessInfo *info = [VersionTestProcessInfo new];
    for(unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        assert(SHDWFingerprintOSVersionAtLeast(cases[i].request) == cases[i].mapped);
        for(unsigned mode = 0; mode < 7; mode++) {
            callerPath = mode == 1 ? "/System/Library/Frameworks/Foundation.framework/Foundation" :
                mode == 2 ? "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK" : "/Apps/Probe.app/Probe";
            shdw_fingerprint_enabled = mode != 3; externalCaller = mode != 4;
            internalDepth = mode == 5 ? 2 : 0; fakeCaller = mode == 6 ? NULL : (void *)1;
            unsigned before = nativePredicateCalls;
            BOOL mapped = mode == 0 || mode == 2;
            assert([info isOperatingSystemAtLeastVersion:cases[i].request] == (mapped ? cases[i].mapped : cases[i].native));
            assert(nativePredicateCalls == before + (mapped ? 0 : 1));
            assert(info.systemUptime == 100000);
        }
    }
    callerPath = "/Apps/Probe.app/Probe"; shdw_fingerprint_enabled = YES; externalCaller = YES;
    internalDepth = 0; fakeCaller = (void *)1;
}
static void verify_current_boot(void) {
    struct timeval boot; size_t length = sizeof(boot); int result;
    policyNativeBoot += 17.5;
    assert(SHDWFingerprintBootQuery("kern.boottime", &boot, &length, &result) && !result);
    assert(boot.tv_sec == 1700003617 && boot.tv_usec == 750000);
    policyNativeBoot -= 17.5;
    SysctlFunction wrappers[] = {replaced_sysctlbyname, replaced___sysctlbyname, mibAdapter};
    for(unsigned mode = 0; mode < 2; mode++) {
        policyBootStatus = mode == 0 ? -1 : 0;
        policyBootLength = mode == 1 ? sizeof(boot) - 1 : sizeof(boot);
        int untouched = 71; size_t capacity = sizeof(boot); memset(&boot, 0xa5, sizeof(boot)); errno = EDOM;
        assert(!SHDWFingerprintBootQuery("kern.boottime", &boot, &capacity, &untouched));
        assert(untouched == 71 && capacity == sizeof(boot) && errno == EDOM);
        const unsigned char *bytes = (void *)&boot;
        for(unsigned i = 0; i < sizeof(boot); i++) assert(bytes[i] == 0xa5);
        requireBootInternal = YES;
        for(unsigned i = 0; i < sizeof(wrappers) / sizeof(wrappers[0]); i++)
            passthrough(wrappers[i], "kern.boottime", NULL, 0);
        requireBootInternal = NO;
    }
    policyBootStatus = 0; policyBootLength = sizeof(boot);
}
static void verify_uname_value(const struct utsname *value, BOOL mapped) {
    assert(!memcmp(value->sysname, nativeUnameValue.sysname, sizeof(value->sysname)));
    assert(!memcmp(value->nodename, nativeUnameValue.nodename, sizeof(value->nodename)));
    assert(!memcmp(value->machine, nativeUnameValue.machine, sizeof(value->machine)));
    assert(!strcmp(value->release, mapped ? "24.6.0" : nativeUnameValue.release));
    assert(!strcmp(value->version, mapped ? expectedKernel : nativeUnameValue.version));
}
static void verify_uname(void) {
    memset(&nativeUnameValue, 0xa5, sizeof(nativeUnameValue));
    strcpy(nativeUnameValue.sysname, "Darwin");
    strcpy(nativeUnameValue.nodename, "Original device");
    strcpy(nativeUnameValue.machine, "iPhone14,5");
    strcpy(nativeUnameValue.release, "22.3.0");
    strcpy(nativeUnameValue.version, "Original kernel");
    assert(!SHDWFingerprintUnameValue(NULL));
    struct utsname value = nativeUnameValue;
    assert(SHDWFingerprintUnameValue(&value));
    verify_uname_value(&value, YES);
    for(unsigned mode = 0; mode < 8; mode++) {
        callerPath = mode == 1 ? "/System/Library/Frameworks/Foundation.framework/Foundation" :
            mode == 2 ? "/Apps/Probe.app.other/SDK" :
            mode == 3 ? "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK" : "/Apps/Probe.app/Probe";
        shdw_fingerprint_enabled = mode != 4;
        internalDepth = mode == 5 ? 2 : 0;
        externalCaller = mode != 6;
        fakeCaller = mode == 7 ? NULL : (void *)1;
        for(unsigned failed = 0; failed < 2; failed++) {
            unsigned calls = nativeUnameCalls;
            nativeUnameStatus = failed ? -1 : 0; errno = EDOM;
            memset(&value, 0, sizeof(value));
            assert(replaced_uname(&value) == nativeUnameStatus);
            assert(nativeUnameCalls == calls + 1 && errno == EBUSY);
            BOOL mapped = !failed && (mode == 0 || mode == 3);
            verify_uname_value(&value, mapped);
            calls = nativeUnameCalls;
            assert(replaced_uname(NULL) == nativeUnameStatus);
            assert(nativeUnameCalls == calls + 1 && errno == EBUSY);
        }
    }
    shdw_fingerprint_enabled = YES; internalDepth = 0; externalCaller = YES; fakeCaller = (void *)1;
    callerPath = "/Apps/Probe.app/Probe"; nativeUnameStatus = 0;
}
static void verify_uname_installs(void) {
    SHDWHookSession *session = [SHDWHookSession new];
    shdw_hook_desc_t descriptor = {"uname", (void *)replaced_uname,
        (void **)&original_uname, SHADW_HOOK_GROUP_ANTIDEBUG, 0};
    unsigned requests = rebindRequests;
    // Missing imports or a refused rebind must retain a callable original.
    original_uname = NULL; rebindPredecessor = NULL; rebindSuccess = NO;
    shdw_libc_rebind_proclist(session, &descriptor, SHADW_HOOK_GROUP_ANTIDEBUG, (void *)nativeUname);
    assert(rebindRequests == requests + 1 && original_uname == nativeUname);
    // A captured predecessor takes precedence over the export fallback.
    original_uname = NULL; rebindPredecessor = (void *)(uintptr_t)0x1234; rebindSuccess = YES;
    shdw_libc_rebind_proclist(session, &descriptor, SHADW_HOOK_GROUP_ANTIDEBUG, (void *)nativeUname);
    assert(rebindRequests == requests + 2 && (void *)original_uname == rebindPredecessor);
    requests = rebindRequests;
    shdw_libc_rebind_proclist(session, &descriptor, 0, (void *)nativeUname);
    descriptor.original = NULL;
    shdw_libc_rebind_proclist(session, &descriptor, SHADW_HOOK_GROUP_ANTIDEBUG, (void *)nativeUname);
    descriptor.original = (void **)&original_uname; descriptor.symbol = "unknown";
    shdw_libc_rebind_proclist(session, &descriptor, SHADW_HOOK_GROUP_ANTIDEBUG, (void *)nativeUname);
    assert(rebindRequests == requests);
    shdw_universal_antidebugging_rebind_image(session, NULL);
    assert(rebindRequests == requests);
    expectedImage = (void *)(uintptr_t)0x2345;
    original_uname = NULL;
    shdw_universal_antidebugging_rebind_image(session, expectedImage);
    assert(!unameReplays);
    original_uname = nativeUname;
    for(unsigned i = 1; i <= 2; i++) {
        shdw_universal_antidebugging_rebind_image(session, expectedImage);
        assert(unameReplays == i && original_uname == nativeUname);
    }
}
int main(void) { @autoreleasepool {
    verify_native_string_contract(); verify_policy(); verify_hooks(); verify_boot(); verify_current_boot(); verify_version_predicate(); verify_uname(); verify_uname_installs();
    puts("fingerprint version/boot: policy, native uptime, version predicate, Foundation, named/MIB sysctl, uname wrappers and installation/replay fallbacks passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-version-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + policy.read_text() + "\n#undef sysctlbyname\n" + hook_prefix + hooks + methods + install_source + suffix)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation",
        "-I", str(root / "src/Shadow.framework/Headers"), "-I", str(policy.parent), str(src), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
