"""Exercise production fingerprint getters with in-memory framework doubles."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text()
helpers = source[:source.index("%group")]
helpers = "\n".join(line for line in helpers.splitlines() if not line.startswith("#import"))
methods = source[source.index("%hook MKMapView") + len("%hook MKMapView"):source.index("%end")]
methods = methods.replace("%orig(frame)", "[self nativeInitWithFrame:frame]")
methods = re.sub(r"%orig\([^;]*\);", "[self nativeExplicit];", methods)
methods = methods.replace("return %orig;", "return [self nativeCenter];")
radio_start = source.index("%hook CTTelephonyNetworkInfo") + len("%hook CTTelephonyNetworkInfo")
radio = source[radio_start:source.index("%end", radio_start)]
radio = radio.replace("%orig", "[self nativeRadioTechnologies]")
sim_start = source.index("%hook CoreTelephonyClient") + len("%hook CoreTelephonyClient")
sim = source[sim_start:source.index("%end", sim_start)]
sim = sim.replace("%orig(context, error)", "[self nativeDataStatus:context error:error]")
assert "%init(shadowhook_fingerprint_pasteboard, UIPasteboard = pasteboardClass)" in source
pasteboard_start = source.index("%hook UIPasteboard") + len("%hook UIPasteboard")
pasteboard = source[pasteboard_start:source.index("%end", pasteboard_start)]
pasteboard = pasteboard.replace("%orig", "[self nativeChangeCount]")
url_source = (root / "src/ShadowCore.dylib/hooks/Universal/NSURL.x").read_text()
url_start = url_source.index("%group shadowhook_NSURLResources")
url_start = url_source.index("%hook NSURL", url_start) + len("%hook NSURL")
url_methods = url_source[url_start:url_source.index("%end", url_start)]
url_methods = url_methods.replace("%orig", "[self nativeGetResourceValue:value forKey:key error:error]", 1)
url_methods = url_methods.replace("%orig", "[self nativeResourceValuesForKeys:keys error:error]", 1)
file_source = (root / "src/ShadowCore.dylib/hooks/Universal/NSFileManager.x").read_text()
file_start = file_source.index("%group shadowhook_NSFileAttributes")
file_start = file_source.index("%hook NSFileManager", file_start) + len("%hook NSFileManager")
file_methods = file_source[file_start:file_source.index("%end", file_start)]
file_methods = file_methods.replace("%orig", "[self nativeAttributesAtPath:path error:error]")
syscall_source = (root / "src/ShadowCore.dylib/hooks/Universal/syscall.x").read_text()
def c_function(name, signature="static int "):
    start = syscall_source.index(signature + name + "(")
    body = syscall_source.index("{", start)
    end, depth = body + 1, 1
    while depth:
        if syscall_source[end] == "{": depth += 1
        elif syscall_source[end] == "}": depth -= 1
        end += 1
    return syscall_source[start:end]
sysctl_methods = c_function("replaced_sysctlbyname") + "\n" + c_function("replaced___sysctlbyname")
sysctl_methods += "\n" + c_function("shdw_sym_policy_lookup_syscall", "void *")
assert 'hookRebindSymbol:@"sysctlbyname" withReplacement:replaced_sysctlbyname' in syscall_source
assert 'hookRebindSymbol:@"_sysctlbyname"' not in syscall_source
dyld_source = (root / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
assert "shdw_sym_policy_lookup_syscall(symbol)" in dyld_source
assert "shdw_sym_policy_lookup_syscall(name)" in dyld_source
prefix = r'''
#import <Foundation/Foundation.h>
NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    (void)bundleID;
    return @{@"MemoryDelta": @16384};
}

#import <CoreGraphics/CoreGraphics.h>
#include <objc/runtime.h>
#include <dlfcn.h>
#include <assert.h>
#include <execinfo.h>
#include <errno.h>
typedef struct { double latitude, longitude; } CLLocationCoordinate2D;
#import "FingerprintPolicy.h"
typedef struct { CLLocationCoordinate2D center; double span; } MKCoordinateRegion;
typedef CGRect MKMapRect;
typedef struct { CGFloat top, left, bottom, right; } UIEdgeInsets;
typedef NSInteger MKUserTrackingMode;
@interface MKMapCamera : NSObject @end
static unsigned internalDepth;
static const char *callerPath = "/Apps/Probe.app/Probe";
static BOOL externalCaller = YES;
static const char *framePaths[24];
static unsigned frameCount, backtraceCalls;
static const void *fakeCaller = (void *)1;
static BOOL shdw_caller_is_external(const void *caller) { return caller && externalCaller && !internalDepth; }
static BOOL SHDWNetworkQueryPathMatches(const char *path, const char *bundle) {
    if(!path || !bundle || !bundle[0]) return NO;
    size_t n = strlen(bundle); return !strncmp(path, bundle, n) && (!path[n] || path[n] == '/');
}
static int fake_dladdr(const void *caller, Dl_info *info) {
    assert(internalDepth);
    uintptr_t index = (uintptr_t)caller - 100;
    info->dli_fname = index < 24 ? framePaths[index] : callerPath;
    return info->dli_fname != NULL;
}
static int fake_backtrace(void **frames, int size) {
    backtraceCalls++; assert(size == 24);
    for(unsigned i = 0; i < frameCount; i++) frames[i] = (void *)(uintptr_t)(100 + i);
    return (int)frameCount;
}
#define backtrace fake_backtrace
static void leave_scope(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave_scope))) = (++internalDepth, YES); active; active = NO)
#define dladdr fake_dladdr
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
@interface UIPasteboard : NSObject
@property(nonatomic) NSInteger nativeCount;
@property(nonatomic) unsigned nativeCalls;
@property(nonatomic, copy) NSString *name;
- (NSInteger)nativeChangeCount;
- (NSInteger)changeCount;
@end
@interface ConcretePasteboard : UIPasteboard @end
static NSString *const UIPasteboardNameGeneral = @"com.apple.UIKit.pboard.general";
@implementation UIPasteboard
- (NSInteger)changeCount { return 0; }
- (NSInteger)nativeChangeCount { _nativeCalls++; return _nativeCount; }
- (NSString *)string { assert(!"unexpected clipboard content read"); return nil; }
- (NSArray *)items { assert(!"unexpected clipboard content read"); return nil; }
@end
@interface MKMapView : NSObject
@property(nonatomic, strong) id superview;
@property(nonatomic, strong) id window;
@property(nonatomic) CLLocationCoordinate2D nativeValue;
@property(nonatomic) unsigned nativeCalls;
- (instancetype)nativeInitWithFrame:(CGRect)frame __attribute__((objc_method_family(init)));
- (CLLocationCoordinate2D)nativeCenter;
- (void)nativeExplicit;
@end
@implementation MKMapView
- (instancetype)nativeInitWithFrame:(CGRect)frame {
    (void)frame; self = [super init]; if(self) _nativeValue = (CLLocationCoordinate2D){51, 9}; return self;
}
- (CLLocationCoordinate2D)nativeCenter { return _nativeValue; }
- (void)nativeExplicit { _nativeCalls++; _nativeValue = (CLLocationCoordinate2D){12, 34}; }
@end
@interface CTTelephonyNetworkInfo : NSObject
@property(nonatomic, strong) NSDictionary<NSString *, NSString *> *nativeServices;
@property(nonatomic) unsigned nativeCalls;
- (NSDictionary<NSString *, NSString *> *)nativeRadioTechnologies;
@end
@implementation CTTelephonyNetworkInfo
- (NSDictionary<NSString *, NSString *> *)nativeRadioTechnologies {
    _nativeCalls++; return _nativeServices;
}
@end
static unsigned simCopyMode;
static BOOL simClassAvailable = YES, failSIMInit;
@interface CTDataStatusBasic : NSObject <NSCopying>
@property(nonatomic) BOOL attached, hasIndicator, inHomeCountry, roamAllowed, cellularDataPossible, newRadioCoverage;
@property(nonatomic, copy) NSString *unrelated;
@end
@implementation CTDataStatusBasic
- (instancetype)init { if(failSIMInit) return nil; return [super init]; }
- (id)copyWithZone:(NSZone *)zone {
    if(simCopyMode == 1) @throw [NSException exceptionWithName:@"copy" reason:nil userInfo:nil];
    if(simCopyMode == 2) return nil;
    if(simCopyMode == 3) return self;
    CTDataStatusBasic *copy = [[[self class] allocWithZone:zone] init];
    copy->_attached = _attached; copy->_hasIndicator = _hasIndicator; copy->_inHomeCountry = _inHomeCountry;
    copy->_roamAllowed = _roamAllowed; copy->_cellularDataPossible = _cellularDataPossible;
    copy->_newRadioCoverage = _newRadioCoverage; copy->_unrelated = [_unrelated copy]; return copy;
}
- (void)setValuesForKeysWithDictionary:(NSDictionary *)values {
    if(simCopyMode == 4) @throw [NSException exceptionWithName:@"KVC" reason:nil userInfo:nil];
    [super setValuesForKeysWithDictionary:values];
}
@end
@interface CoreTelephonyClient : NSObject
@property(nonatomic, strong) id nativeStatus;
@property(nonatomic, strong) NSError *nativeError;
@property(nonatomic) unsigned nativeCalls;
- (id)nativeDataStatus:(id)context error:(NSError **)error;
@end
@implementation CoreTelephonyClient
- (id)nativeDataStatus:(id)context error:(NSError **)error {
    assert([context isEqual:@"context"]); _nativeCalls++; if(error) *error = _nativeError; return _nativeStatus;
}
@end
static Class fake_getClass(const char *name) {
    return !simClassAvailable && !strcmp(name,"CTDataStatusBasic") ? Nil : objc_getClass(name);
}
#define objc_getClass fake_getClass
static BOOL shdw_url_resources_paths_enabled, restrictedPath;
static unsigned restrictionCalls;
@interface Shadow : NSObject
+ (NSError *)fileNoSuchFileErrorForURL:(id)url;
+ (NSError *)fileErrorWithCode:(NSInteger)code path:(NSString *)path url:(NSURL *)url;
- (BOOL)isPathRestricted:(NSString *)path options:(NSDictionary *)options;
@end
@implementation Shadow
+ (NSError *)fileNoSuchFileErrorForURL:(id)url {
    (void)url; return [NSError errorWithDomain:NSCocoaErrorDomain code:NSFileReadNoSuchFileError userInfo:nil];
}
+ (NSError *)fileErrorWithCode:(NSInteger)code path:(NSString *)path url:(NSURL *)url {
    (void)path; (void)url; return [NSError errorWithDomain:NSCocoaErrorDomain code:code userInfo:nil];
}
- (BOOL)isPathRestricted:(NSString *)path options:(NSDictionary *)options {
    (void)path; (void)options; restrictionCalls++; return restrictedPath;
}
@end
static Shadow *_shadow;
static BOOL shdw_file_attributes_paths_enabled;
static NSDictionary *_shdw_optionsForAbsolute(id manager, BOOL absolute) { (void)manager; (void)absolute; return nil; }
#define isCallerExternal() shdw_caller_is_external(fakeCaller)
static BOOL _shdw_resultURLRestricted(id url) { (void)url; restrictionCalls++; return restrictedPath; }
@interface FakeURL : NSObject
@property(nonatomic, strong) NSString *path;
@property(nonatomic) BOOL isFileURL;
@property(nonatomic, strong) NSDictionary *nativeValues;
@property(nonatomic, strong) NSError *nativeError;
@property(nonatomic) unsigned nativeCalls;
@property(nonatomic) BOOL nativeSuccess;
- (NSDictionary *)nativeResourceValuesForKeys:(NSArray *)keys error:(NSError **)error;
- (BOOL)nativeGetResourceValue:(id *)value forKey:(NSString *)key error:(NSError **)error;
@end
@implementation FakeURL
- (NSDictionary *)nativeResourceValuesForKeys:(NSArray *)keys error:(NSError **)error {
    _nativeCalls++; if(error && _nativeError) *error = _nativeError;
    if(!_nativeValues) return nil;
    NSMutableDictionary *selected = [NSMutableDictionary dictionary];
    for(NSString *key in keys) if(_nativeValues[key]) selected[key] = _nativeValues[key];
    return [selected copy];
}
- (BOOL)nativeGetResourceValue:(id *)value forKey:(NSString *)key error:(NSError **)error {
    _nativeCalls++; if(error && _nativeError) *error = _nativeError;
    if(value) *value = _nativeValues[key]; return _nativeSuccess;
}
@end
@interface FakeFileManager : NSObject
@property(nonatomic, strong) NSDictionary *nativeAttributes;
@property(nonatomic, strong) NSError *nativeError;
@property(nonatomic) unsigned nativeCalls;
- (NSDictionary *)nativeAttributesAtPath:(NSString *)path error:(NSError **)error;
@end
@implementation FakeFileManager
- (NSDictionary *)nativeAttributesAtPath:(NSString *)path error:(NSError **)error {
    (void)path; _nativeCalls++; if(error && _nativeError) *error = _nativeError; return _nativeAttributes;
}
@end
typedef int (*SysctlFunction)(const char *, void *, size_t *, void *, size_t);
static int nativeSysctlStatus;
static size_t nativeSysctlLength = sizeof(int);
static unsigned nativeSysctlCalls, priorPolicyCalls;
static int nativeSysctl(const char *name, void *oldp, size_t *oldlenp, void *newp, size_t newlen) {
    (void)name; (void)newp; (void)newlen; nativeSysctlCalls++;
    if(oldp && oldlenp && *oldlenp >= sizeof(int)) { int value = 1; memcpy(oldp, &value, sizeof(value)); }
    if(oldlenp) *oldlenp = nativeSysctlLength;
    errno = EBUSY; return nativeSysctlStatus;
}
static SysctlFunction original_sysctlbyname = nativeSysctl, original___sysctlbyname = nativeSysctl;
static long (*original_syscall)(int, ...), (*original___syscall)(int, ...);
static void *shdw_syscall_c_aliases[2];
static long replaced_syscall(int number, ...) { (void)number; assert(!"unexpected raw call"); return -1; }
static long replaced___syscall(int number, ...) { (void)number; assert(!"unexpected raw call"); return -1; }

static int shdw_sysctlbyname_policy(const char *name, void *oldp, size_t *oldlenp, void *newp,
    size_t newlen, SysctlFunction original) {
    priorPolicyCalls++; return original(name, oldp, oldlenp, newp, newlen);
}
'''
suffix = r'''
static void verify_pasteboard(void) {
    UIPasteboard *general = [ConcretePasteboard new], *other = [ConcretePasteboard new];
    UIPasteboard *named = [ConcretePasteboard new];
    general.name = UIPasteboardNameGeneral; other.name = [UIPasteboardNameGeneral mutableCopy];
    named.name = @"custom.board"; general.nativeCount = 29; other.nativeCount = 31; named.nativeCount = 17;
    shdw_fingerprint_enabled = YES; callerPath = "/Apps/Probe.app/Probe";
    assert([general changeCount] == 0 && [other changeCount] == 0);
    assert(!general.nativeCalls && !other.nativeCalls && !internalDepth);
    assert([named changeCount] == 17 && named.nativeCalls == 1);
    callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
    assert([general changeCount] == 0 && [other changeCount] == 0);
    for(NSString *path in @[@"/System/Library/Frameworks/UIKit.framework/UIKit", @"/Apps/Probe.app.other/Probe"]) {
        callerPath = path.UTF8String;
        assert([general changeCount] == 29 && [named changeCount] == 17);
    }
    callerPath = "/Apps/Probe.app/Probe";
    internalDepth = 2; assert([general changeCount] == 29 && internalDepth == 2); internalDepth = 0;
    externalCaller = NO; assert([general changeCount] == 29); externalCaller = YES;
    fakeCaller = NULL; assert([general changeCount] == 29); fakeCaller = (void *)1;
    shdw_fingerprint_enabled = NO; assert([general changeCount] == 29); shdw_fingerprint_enabled = YES;
    assert(!internalDepth && general.nativeCount == 29 && other.nativeCount == 31 && named.nativeCount == 17);
}
static void verify_center(MKMapView *map, double latitude, double longitude) {
    CLLocationCoordinate2D value = [map centerCoordinate];
    assert(value.latitude == latitude && value.longitude == longitude);
}
static void verify_radio(CTTelephonyNetworkInfo *info, NSDictionary *expected) {
    unsigned calls = info.nativeCalls;
    NSDictionary *result = [info serviceCurrentRadioAccessTechnology];
    assert([result isEqual:expected] && info.nativeCalls == calls);
}
static void verify_native_radio(CTTelephonyNetworkInfo *info) {
    unsigned calls = info.nativeCalls;
    NSDictionary *result = [info serviceCurrentRadioAccessTechnology];
    assert(result == info.nativeServices && info.nativeCalls == calls + 1);
}
static void verify_radio_cases(void) {
    shdw_fingerprint_enabled = YES;
    CTTelephonyNetworkInfo *info = [CTTelephonyNetworkInfo new];
    NSDictionary *fallback = @{@"0000000100000001": @"CTRadioAccessTechnologyLTE",
        @"0000000100000002": @"CTRadioAccessTechnologyNRNSA"};
    callerPath = "/Apps/Probe.app/Probe";
    verify_radio(info, fallback);
    info.nativeServices = @{}; verify_radio(info, fallback);
    for(NSString *technology in @[@"CTRadioAccessTechnologyLTE", @"CTRadioAccessTechnologyNR", @"CTRadioAccessTechnologyNRNSA"]) {
        info.nativeServices = @{@"service-one":technology};
        verify_radio(info, fallback);
        assert([SHDWFingerprintRadioTechnologies(info.nativeServices) isEqual:fallback]);
    }
    info.nativeServices = @{@"service-one":@"CTRadioAccessTechnologyEdge"};
    verify_radio(info, fallback);
    info.nativeServices = @{@"":@"CTRadioAccessTechnologyNR", @7:@"CTRadioAccessTechnologyLTE",
        @"invalid":NSNull.null};
    verify_radio(info, fallback);
    for(NSDictionary *older in @[
        @{@"z-slot":@"CTRadioAccessTechnologyEdge", @"a-slot":NSNull.null},
        @{@"a-slot":NSNull.null, @"z-slot":@"CTRadioAccessTechnologyEdge"}]) {
        info.nativeServices = older;
        verify_radio(info, fallback);
    }
    info.nativeServices = @{@"":@"CTRadioAccessTechnologyNR", @7:@"CTRadioAccessTechnologyLTE"};
    verify_radio(info, fallback);
    NSMutableDictionary *native = [@{@"0000000100000001": @"CTRadioAccessTechnologyNR",
        @"0000000100000002": @"CTRadioAccessTechnologyLTE",
        @"older":@"CTRadioAccessTechnologyEdge", @"invalid":@7} mutableCopy];
    NSDictionary *snapshot = [native copy];
    info.nativeServices = native;
    NSDictionary *selected = fallback;
    verify_radio(info, selected);
    callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
    NSDictionary *result = [info serviceCurrentRadioAccessTechnology];
    assert([result isEqual:selected] && result != native && [native isEqual:snapshot]);
    [native removeObjectForKey:@"0000000100000002"];
    assert(result.count == 2 && [result[@"0000000100000002"] isEqual:@"CTRadioAccessTechnologyNRNSA"]);
    [native addEntriesFromDictionary:snapshot];
    for(NSString *path in @[@"/System/Library/Frameworks/CoreTelephony.framework/CoreTelephony",
        @"/Apps/Probe.app.other/Probe", @"/private/Apps/Probe.app.other/SDK"]) {
        callerPath = path.UTF8String; verify_native_radio(info);
    }
    callerPath = "/Apps/Probe.app/Probe";
    shdw_fingerprint_enabled = NO; verify_native_radio(info); shdw_fingerprint_enabled = YES;
    internalDepth = 2; verify_native_radio(info); assert(internalDepth == 2); internalDepth = 0;
    externalCaller = NO; verify_native_radio(info); externalCaller = YES;
    fakeCaller = NULL; verify_native_radio(info); fakeCaller = (void *)1;
    callerPath = NULL; verify_native_radio(info);
    callerPath = "/System/Library/Frameworks/CoreTelephony.framework/CoreTelephony";
    info.nativeServices = nil; verify_native_radio(info);
    info.nativeServices = @{}; verify_native_radio(info);
    callerPath = "/Apps/Probe.app/Probe";
    assert([native isEqual:snapshot] && !internalDepth);
}
static void verify_resource_values(void) {
    NSDate *created = [NSDate dateWithTimeIntervalSince1970:1234];
    NSDate *modified = [NSDate dateWithTimeIntervalSince1970:5678];
    NSMutableDictionary *native = [@{NSURLCreationDateKey:created, NSURLContentModificationDateKey:modified,
        NSURLFileSizeKey:@987} mutableCopy];
    NSDictionary *snapshot = [native copy];
    FakeURL *url = [FakeURL new]; url.isFileURL = YES;
    url.nativeValues = native; url.nativeSuccess = YES;
    NSArray *keys = snapshot.allKeys;
    // Resource timestamps retain native values for every alias, calling image and scope.
    for(NSString *path in @[@"/private/var", @"/private/var/", @"/var", @"/var/",
        @"/private/var/other", @"/var/other", @"/private/various", @"relative"]) {
        url.path = path;
        for(NSString *caller in @[@"/Apps/Probe.app/Probe",
            @"/private/Apps/Probe.app/Frameworks/SDK.framework/SDK",
            @"/System/Library/Frameworks/Foundation.framework/Foundation",
            @"/usr/lib/swift/libswiftFoundation.dylib",
            @"/System/Library/Frameworks/CoreTelephony.framework/CoreTelephony"]) {
            callerPath = caller.UTF8String;
            frameCount = 2; framePaths[0] = callerPath; framePaths[1] = "/Apps/Probe.app/Probe";
            for(unsigned mode = 0; mode < 5; mode++) {
                shdw_fingerprint_enabled = mode != 1;
                externalCaller = mode != 2;
                internalDepth = mode == 3 ? 2 : 0;
                url.isFileURL = mode != 4;
                NSDictionary *result = [url resourceValuesForKeys:keys error:NULL];
                assert([result isEqual:snapshot] && [native isEqual:snapshot]);
                assert(result[NSURLCreationDateKey] == created && result[NSURLContentModificationDateKey] == modified);
                for(NSString *key in keys) {
                    id value = nil;
                    assert([url getResourceValue:&value forKey:key error:NULL] && value == native[key]);
                }
                assert(internalDepth == (mode == 3 ? 2 : 0));
            }
        }
    }
    internalDepth = 0; externalCaller = YES; shdw_fingerprint_enabled = YES;
    callerPath = "/Apps/Probe.app/Probe"; url.path = @"/private/var"; url.isFileURL = YES;
    NSError *sentinel = [NSError errorWithDomain:@"test" code:9 userInfo:nil], *error = sentinel;
    unsigned calls = url.nativeCalls;
    assert([[url resourceValuesForKeys:keys error:&error] isEqual:snapshot]);
    assert(error == sentinel && url.nativeCalls == calls + 1);
    url.nativeError = sentinel; url.nativeValues = nil; error = nil;
    assert(![url resourceValuesForKeys:keys error:&error] && error == sentinel);
    url.nativeValues = native; url.nativeSuccess = NO; error = nil; id value = @"sentinel";
    assert(![url getResourceValue:&value forKey:NSURLCreationDateKey error:&error] && value == created && error == sentinel);
    url.nativeError = nil; url.nativeSuccess = YES;
    assert([url getResourceValue:NULL forKey:NSURLCreationDateKey error:NULL]);
    NSDictionary *selected = [url resourceValuesForKeys:@[NSURLFileSizeKey] error:NULL];
    assert(selected.count == 1 && [selected[NSURLFileSizeKey] isEqual:@987]);
    // Shared resource hooks retain optional filesystem restrictions and native errors.
    restrictedPath = YES; restrictionCalls = 0;
    assert([url resourceValuesForKeys:keys error:NULL] && !restrictionCalls);
    shdw_url_resources_paths_enabled = YES; error = nil; calls = url.nativeCalls;
    assert(![url resourceValuesForKeys:keys error:&error] && error.code == NSFileReadNoSuchFileError);
    assert(url.nativeCalls == calls); value = created; error = nil;
    assert(![url getResourceValue:&value forKey:NSURLCreationDateKey error:&error] && !value && error.code == NSFileReadNoSuchFileError);
    internalDepth = 1;
    assert([[url resourceValuesForKeys:keys error:NULL] isEqual:snapshot]);
    internalDepth = 0; shdw_url_resources_paths_enabled = NO; restrictedPath = NO;
    assert([native isEqual:snapshot]);
}
static void verify_sim_attributes(void) {
    _shadow = [Shadow new];
    FakeFileManager *manager = [FakeFileManager new];
    NSDate *created = [NSDate dateWithTimeIntervalSince1970:1234];
    NSDate *modified = [NSDate dateWithTimeIntervalSince1970:5678];
    NSMutableDictionary *native = [@{NSFileCreationDate:created, NSFileModificationDate:modified,
        NSFileSize:@42, NSFileType:NSFileTypeRegular} mutableCopy];
    NSDictionary *snapshot = [native copy]; manager.nativeAttributes = native;
    NSArray *paths = @[@"/var/mobile/Library/Carrier Bundles", @"/var/mobile/Library/Carrier Bundles/a.plist",
        @"/private/var/mobile/Library/Carrier Bundles/", @"/private/var/mobile/Library/Carrier Bundles/x/y",
        @"/System/Library/Carrier Bundles", @"/System/Library/Carrier Bundles/sim.bundle/file",
        @"/var/mobile/Library/Carrier BundlesOther/a", @"/private/var", @"Carrier Bundles/a"];
    for(NSString *path in paths) for(NSString *caller in @[@"/Apps/Probe.app/Probe",
        @"/private/Apps/Probe.app/Frameworks/SDK.framework/SDK",
        @"/System/Library/Frameworks/Foundation.framework/Foundation",
        @"/usr/lib/swift/libswiftFoundation.dylib"]) {
        callerPath = caller.UTF8String;
        frameCount = 2; framePaths[1] = "/Apps/Probe.app/Probe";
        for(unsigned mode = 0; mode < 4; mode++) {
            shdw_fingerprint_enabled = mode != 1;
            externalCaller = mode != 2; internalDepth = mode == 3 ? 2 : 0;
            NSDictionary *result = [manager attributesOfItemAtPath:path error:NULL];
            assert(result == native && [native isEqual:snapshot]);
            assert(result[NSFileCreationDate] == created && result[NSFileModificationDate] == modified);
            assert(internalDepth == (mode == 3 ? 2 : 0));
        }
    }
    shdw_fingerprint_enabled = YES; externalCaller = YES; internalDepth = 0;
    callerPath = "/Apps/Probe.app/Probe"; NSString *path = paths[1];
    for(NSString *key in @[NSFileCreationDate, NSFileModificationDate]) {
        manager.nativeAttributes = @{key:created, NSFileSize:@42};
        assert([manager attributesOfItemAtPath:path error:NULL] == manager.nativeAttributes);
    }
    manager.nativeAttributes = @{NSFileSize:@42};
    assert([manager attributesOfItemAtPath:path error:NULL] == manager.nativeAttributes);
    NSError *sentinel = [NSError errorWithDomain:@"test" code:29 userInfo:nil], *error = nil;
    manager.nativeAttributes = nil; manager.nativeError = sentinel;
    assert(![manager attributesOfItemAtPath:path error:&error] && error == sentinel);
    manager.nativeAttributes = native; manager.nativeError = nil; error = sentinel;
    unsigned calls = manager.nativeCalls;
    assert([manager attributesOfItemAtPath:path error:&error] == native && error == sentinel && manager.nativeCalls == calls + 1);
    restrictedPath = YES; restrictionCalls = 0;
    assert([manager attributesOfItemAtPath:path error:NULL] && !restrictionCalls);
    shdw_file_attributes_paths_enabled = YES; error = nil; calls = manager.nativeCalls;
    assert(![manager attributesOfItemAtPath:path error:&error] && error.code == NSFileReadNoSuchFileError);
    assert(manager.nativeCalls == calls); shdw_file_attributes_paths_enabled = NO; restrictedPath = NO;
    assert([native isEqual:snapshot]);
}
static void verify_sysctl_wrappers(void) {
    const char *name = "security.mac.amfi.developer_mode_status";
    SysctlFunction wrappers[] = {replaced_sysctlbyname, replaced___sysctlbyname};
    assert(shdw_sym_policy_lookup_syscall("sysctlbyname") == (void *)replaced_sysctlbyname);
    assert(!shdw_sym_policy_lookup_syscall(NULL) && !shdw_sym_policy_lookup_syscall("_sysctlbyname"));
    assert(!shdw_sym_policy_lookup_syscall("___sysctlbyname") && !shdw_sym_policy_lookup_syscall("other"));
    original_sysctlbyname = NULL;
    assert(!shdw_sym_policy_lookup_syscall("sysctlbyname")); original_sysctlbyname = nativeSysctl;
    for(unsigned i = 0; i < 2; i++) {
        SysctlFunction wrapper = wrappers[i]; callerPath = "/Apps/Probe.app/Probe";
        shdw_fingerprint_enabled = YES; nativeSysctlStatus = 0; nativeSysctlLength = sizeof(int);
        struct { unsigned char before; unsigned char bytes[sizeof(int)]; unsigned char after; } unaligned;
        memset(&unaligned, 0x5a, sizeof(unaligned)); size_t length = sizeof(int);
        unsigned calls = nativeSysctlCalls, policies = priorPolicyCalls;
        assert(!wrapper(name, unaligned.bytes, &length, NULL, 0) && errno == EBUSY);
        int result = -1; memcpy(&result, unaligned.bytes, sizeof(result));
        assert(!result && unaligned.before == 0x5a && unaligned.after == 0x5a && length == sizeof(int));
        assert(nativeSysctlCalls == calls + 1 && priorPolicyCalls == policies + 1);
        int value = 9, input = 1;
        length = sizeof(value); nativeSysctlStatus = -1;
        assert(wrapper(name,&value,&length,NULL,0) == -1 && value == 1 && errno == EBUSY); nativeSysctlStatus = 0;
        length = sizeof(value); assert(!wrapper(name,&value,&length,&input,sizeof(input)) && value == 1 && errno == EBUSY);
        length = 0; assert(!wrapper(name,NULL,&length,NULL,0) && length == sizeof(int) && errno == EBUSY);
        value = 9; assert(!wrapper(name,&value,NULL,NULL,0) && value == 9 && errno == EBUSY);
        nativeSysctlLength = sizeof(int) + 1; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 1); nativeSysctlLength = sizeof(int);
        for(const char **query = (const char *[]){"security.mac.amfi.developer_mode_status.extra", "other", NULL}; *query; query++) {
            length = sizeof(value); assert(!wrapper(*query,&value,&length,NULL,0) && value == 1);
        }
        shdw_fingerprint_enabled = NO; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 1); shdw_fingerprint_enabled = YES;
        internalDepth = 2; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 1 && internalDepth == 2); internalDepth = 0;
        externalCaller = NO; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 1); externalCaller = YES;
        callerPath = "/System/Library/Frameworks/CoreTelephony.framework/CoreTelephony"; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 1);
        callerPath = "/System/Library/Frameworks/Foundation.framework/Foundation";
        frameCount = 2; framePaths[1] = "/Apps/Probe.app/Probe"; length = sizeof(value);
        assert(!wrapper(name,&value,&length,NULL,0) && value == 0);
    }
}
static void verify_sim_policy(void) {
    NSDictionary *enabled = @{@"attached":@YES, @"hasIndicator":@YES, @"inHomeCountry":@YES,
        @"roamAllowed":@NO, @"cellularDataPossible":@YES, @"newRadioCoverage":@YES};
    assert([SHDWFingerprintSIMState() isEqual:enabled]);
}
static void verify_sim_state(void) {
    shdw_fingerprint_enabled = YES; callerPath = "/Apps/Probe.app/Probe";
    CoreTelephonyClient *client = [CoreTelephonyClient new];
    CTDataStatusBasic *native = [CTDataStatusBasic new]; native.unrelated = @"preserved";
    native.roamAllowed = YES; native.newRadioCoverage = YES;
    client.nativeStatus = native;
    NSError *sentinel = [NSError errorWithDomain:@"native" code:31 userInfo:nil], *error = nil;
    client.nativeError = sentinel;
    NSDictionary *wanted = SHDWFingerprintSIMState(); NSArray *keys = wanted.allKeys;
    NSDictionary *snapshot = [native dictionaryWithValuesForKeys:keys];
    unsigned calls = client.nativeCalls;
    CTDataStatusBasic *result = [client getDataStatusBasic:@"context" error:&error];
    assert(result && result != native && !error && client.nativeCalls == calls + 1);
    assert([[result dictionaryWithValuesForKeys:keys] isEqual:wanted] && [result.unrelated isEqual:@"preserved"]);
    assert([[native dictionaryWithValuesForKeys:keys] isEqual:snapshot]);
    assert([client getDataStatusBasic:@"context" error:NULL]);
    client.nativeStatus = nil; error = sentinel;
    result = [client getDataStatusBasic:@"context" error:&error];
    assert(result && !error && [[result dictionaryWithValuesForKeys:keys] isEqual:wanted]);
    failSIMInit = YES; error = nil;
    assert(![client getDataStatusBasic:@"context" error:&error] && error == sentinel); failSIMInit = NO;
    client.nativeStatus = native;
    for(unsigned mode = 1; mode <= 4; mode++) {
        simCopyMode = mode; error = nil;
        result = [client getDataStatusBasic:@"context" error:&error];
        if(mode == 3) {
            assert(result != native && !error && [[result dictionaryWithValuesForKeys:keys] isEqual:wanted]);
        } else assert(result == native && error == sentinel);
        assert([[native dictionaryWithValuesForKeys:keys] isEqual:snapshot]);
    }
    simCopyMode = 0; simClassAvailable = NO; error = nil;
    assert([client getDataStatusBasic:@"context" error:&error] == native && error == sentinel); simClassAvailable = YES;
    client.nativeStatus = @"wrong-class"; error = nil;
    assert([client getDataStatusBasic:@"context" error:&error] == client.nativeStatus && error == sentinel);
    client.nativeStatus = native;
    shdw_fingerprint_enabled = NO;
    assert([client getDataStatusBasic:@"context" error:&error] == native && error == sentinel); shdw_fingerprint_enabled = YES;
    internalDepth = 2;
    assert([client getDataStatusBasic:@"context" error:&error] == native && internalDepth == 2); internalDepth = 0;
    externalCaller = NO; assert([client getDataStatusBasic:@"context" error:&error] == native); externalCaller = YES;
    callerPath = "/System/Library/Frameworks/CoreTelephony.framework/CoreTelephony";
    assert([client getDataStatusBasic:@"context" error:&error] == native);
    callerPath = "/System/Library/Frameworks/Foundation.framework/Foundation";
    frameCount = 2; framePaths[1] = "/Apps/Probe.app/Probe";
    result = [client getDataStatusBasic:@"context" error:&error];
    assert(result != native && !error && [[result dictionaryWithValuesForKeys:keys] isEqual:wanted]);
    assert([[native dictionaryWithValuesForKeys:keys] isEqual:snapshot]);
}
int main(void) { @autoreleasepool {
    strcpy(shdw_map_bundle, "/Apps/Probe.app");
    strcpy(shdw_map_canonical_bundle, "/private/Apps/Probe.app");
    CGRect negative = CGRectMake(0, 0, -1, -1);
    MKMapView *candidate = [[MKMapView alloc] initWithFrame:negative];
    verify_center(candidate, 46.227638, 2.213749);
    callerPath = "/System/Library/Frameworks/MapKit.framework/MapKit";
    verify_center(candidate, 51, 9);
    MKMapView *system = [[MKMapView alloc] initWithFrame:negative];
    callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
    verify_center(system, 51, 9);
    verify_center(candidate, 46.227638, 2.213749);
    internalDepth = 2; verify_center(candidate, 51, 9); assert(internalDepth == 2); internalDepth = 0;
    externalCaller = NO; verify_center(candidate, 51, 9); externalCaller = YES;
    candidate.superview = [NSObject new]; verify_center(candidate, 51, 9); candidate.superview = nil;
    candidate.window = [NSObject new]; verify_center(candidate, 51, 9); candidate.window = nil;
    verify_center(candidate, 46.227638, 2.213749);
    for(NSValue *frame in @[[NSValue valueWithRect:NSMakeRect(0, 0, 100, 100)],
        [NSValue valueWithRect:NSMakeRect(0, 0, -1, 100)], [NSValue valueWithRect:NSMakeRect(0, 0, 100, -1)]]) {
        MKMapView *normal = [[MKMapView alloc] initWithFrame:NSRectToCGRect(frame.rectValue)];
        verify_center(normal, 51, 9);
    }
    for(NSString *selector in @[@"setCenterCoordinate:", @"setCenterCoordinate:animated:",
        @"setRegion:", @"setRegion:animated:", @"setCamera:", @"setCamera:animated:",
        @"setVisibleMapRect:", @"setVisibleMapRect:animated:",
        @"setVisibleMapRect:edgePadding:animated:", @"setUserTrackingMode:", @"setUserTrackingMode:animated:"]) {
        MKMapView *map = [[MKMapView alloc] initWithFrame:negative];
        SEL command = NSSelectorFromString(selector);
        NSMethodSignature *signature = [map methodSignatureForSelector:command];
        NSInvocation *call = [NSInvocation invocationWithMethodSignature:signature];
        call.selector = command; call.target = map;
        unsigned char zero[128] = {0};
        for(NSUInteger i = 2; i < signature.numberOfArguments; i++) [call setArgument:zero atIndex:i];
        [call invoke]; assert(map.nativeCalls == 1); verify_center(map, 12, 34);
    }
    callerPath = "/System/Library/Frameworks/MapKit.framework/MapKit";
    [candidate setCenterCoordinate:(CLLocationCoordinate2D){1, 2}];
    callerPath = "/Apps/Probe.app/Probe"; verify_center(candidate, 46.227638, 2.213749);
    verify_radio_cases();
    verify_resource_values();
    verify_sim_attributes();
    verify_sysctl_wrappers();
    verify_sim_policy();
    verify_sim_state();
    verify_pasteboard();
    assert(!internalDepth);
    puts("fingerprint: map/radio/resource/SIM/pasteboard scopes, native errors, persisted policy and both sysctl wrappers passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-map-defaults-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + helpers + "\n@implementation MKMapView (Hooks)\n" + methods +
        "\n@end\n@implementation CTTelephonyNetworkInfo (Hooks)\n" + radio +
        "\n@end\n@implementation FakeURL (Hooks)\n" + url_methods +
        "\n@end\n@implementation FakeFileManager (Hooks)\n" + file_methods +
        "\n@end\n@implementation CoreTelephonyClient (Hooks)\n" + sim +
        "\n@end\n@implementation ConcretePasteboard\n" + pasteboard + "\n@end\n" + sysctl_methods + "\n" + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-variable", "-Wno-unused-parameter", "-fsanitize=address,undefined", "-framework", "Foundation", "-framework", "CoreGraphics",
        "-I", str(root / "src/Shadow.framework/Headers"), "-I", str(root / "src/ShadowCore.dylib/policy"), str(src), str(root / "src/ShadowCore.dylib/policy/FingerprintPolicy.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
