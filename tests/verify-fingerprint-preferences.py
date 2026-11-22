#!/usr/bin/env python3
"""Exercise process-local preference reads with production wrappers and policy."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
ROOT = Path(__file__).resolve().parents[1]
libc = (ROOT / "src/ShadowCore.dylib/hooks/Universal/libc.x").read_text()
start = libc.index("static BOOL shdw_cf_suite_restricted(")
end = libc.index("static Boolean (*original_CFPreferencesAppSynchronize)", start)
wrappers = libc[start:end]
policy = "\n".join(line for line in (ROOT / "src/ShadowCore.dylib/policy/FingerprintPreferences.m").read_text().splitlines() if not line.startswith("#import"))
policy = policy.replace("NSBundle.mainBundle.bundleIdentifier", '@"fixture.app"')
appenv = (ROOT / "src/ShadowCore.dylib/hooks/Universal/AppEnvironment.x").read_text()
start = appenv.index("- (NSDictionary *)persistentDomainForName:")
end = appenv.index("\n%end", start)
method = re.sub(r" __attribute__\(\(annotate\([^\n]+?\)\)\)", "", appenv[start:end])
method = method.replace("%orig", "[self nativeDomain:domainName]")
source = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <assert.h>
#include <errno.h>
static BOOL external = YES, enabled = YES, missingNative;
static BOOL shdw_defaults_restrictions_enabled = YES;
static unsigned internalDepth, nativeCalls, detections;
static NSDictionary *resolved;
static NSDictionary *nativePreferences;
@interface Shadow:NSObject
+ (BOOL)shdwIsInternalRead;
@end
@implementation Shadow
+ (BOOL)shdwIsInternalRead { errno=EINTR; return internalDepth != 0; }
@end
static void Leave(BOOL *active) { (void)active; assert(internalDepth);internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL once __attribute__((cleanup(Leave)))=(++internalDepth,YES);once;once=NO)
static BOOL isCallerExternal(void) { errno=EINTR; return external && !internalDepth; }
static BOOL shdw_nsuserdefaults_suite_restricted(NSString *domain) { errno=EINTR;return [domain isEqual:@"restricted"]; }
static void shdw_detector_detected(const char *name) { (void)name;detections++;errno=EINTR; }
static NSDictionary *SHDWFingerprintLocalization(void) { assert(internalDepth);errno=EINTR;return enabled ? resolved : nil; }
''' + policy + "\n" + wrappers + r'''
static CFPropertyListRef NativeApp(CFStringRef key, CFStringRef domain) {
    (void)domain; assert(errno==EDOM); nativeCalls++;errno=EIO;
    id value = key ? nativePreferences[(__bridge NSString *)key] : nil;
    return value && !missingNative ? CFRetain((__bridge CFTypeRef)value) : NULL;
}
static CFPropertyListRef NativeValue(CFStringRef key, CFStringRef domain, CFStringRef user, CFStringRef host) {
    (void)user;(void)host;return NativeApp(key,domain);
}
static CFDictionaryRef NativeMultiple(CFArrayRef keys, CFStringRef domain, CFStringRef user, CFStringRef host) {
    (void)domain;(void)user;(void)host;assert(errno==EDOM);nativeCalls++;errno=EIO;
    if(missingNative) return NULL;
    NSMutableDictionary *result=[NSMutableDictionary new];
    for(NSString *key in nativePreferences)
        if(!keys || [(__bridge NSArray *)keys containsObject:key]) result[key]=nativePreferences[key];
    return (CFDictionaryRef)CFBridgingRetain([result copy]);
}
static CFArrayRef NativeKeys(CFStringRef domain, CFStringRef user, CFStringRef host) {
    (void)domain;(void)user;(void)host;assert(errno==EDOM);nativeCalls++;errno=EIO;
    return missingNative ? NULL : (CFArrayRef)CFBridgingRetain(nativePreferences.allKeys);
}
@interface FixtureDefaults:NSObject
- (NSDictionary *)nativeDomain:(NSString *)domain;
- (NSDictionary *)persistentDomainForName:(NSString *)domain;
@end
@implementation FixtureDefaults
- (NSDictionary *)nativeDomain:(NSString *)domain { (void)domain;assert(errno==EDOM);nativeCalls++;errno=EIO;return missingNative ? nil : nativePreferences; }
''' + method + r'''
@end
static id Read(CFStringRef key, CFStringRef domain, CFStringRef user, CFStringRef host, BOOL app) {
    errno=EDOM;
    CFPropertyListRef value=app ? replaced_CFPreferencesCopyAppValue(key,domain) : replaced_CFPreferencesCopyValue(key,domain,user,host);
    return CFBridgingRelease(value);
}
static NSDictionary *ReadMultiple(NSArray *keys, CFStringRef domain, CFStringRef user, CFStringRef host) {
    errno=EDOM;
    return CFBridgingRelease(replaced_CFPreferencesCopyMultiple((__bridge CFArrayRef)keys,domain,user,host));
}
static NSArray *ReadKeys(CFStringRef domain, CFStringRef user, CFStringRef host) {
    errno=EDOM;
    return CFBridgingRelease(replaced_CFPreferencesCopyKeyList(domain,user,host));
}
int main(void) { @autoreleasepool {
    NSDictionary *persistentBefore=[NSUserDefaults.standardUserDefaults persistentDomainForName:NSGlobalDomain];
    resolved=@{@"OverridesSystem":@YES,@"LocaleIdentifier":@"fr_FR",@"Languages":@[@"fr-FR"]};
    nativePreferences=@{@"AppleLocale":@"zh_CN",@"AppleLanguages":@[@"zh-Hans-CN"],@"Unrelated":@42};
    NSDictionary *nativeBefore=[nativePreferences copy];
    shdw_cf_preferences_restrictions_enabled=YES;
    original_CFPreferencesCopyKeyList=NativeKeys;
    original_CFPreferencesCopyAppValue=NativeApp;
    original_CFPreferencesCopyValue=NativeValue;
    original_CFPreferencesCopyMultiple=NativeMultiple;
    NSArray *domains=@[(__bridge id)kCFPreferencesCurrentApplication,(__bridge id)kCFPreferencesAnyApplication,
        NSGlobalDomain,@".GlobalPreferences",@"fixture.app"];
    for(NSString *domain in domains) for(id host in @[(__bridge id)kCFPreferencesAnyHost,(__bridge id)kCFPreferencesCurrentHost]) {
        for(NSNumber *app in @[@NO,@YES]) {
            unsigned before=nativeCalls;
            assert([Read(CFSTR("AppleLocale"),(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host,app.boolValue) isEqual:@"fr_FR"]);
            assert(errno==EDOM && nativeCalls==before);
            assert([Read(CFSTR("AppleLanguages"),(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host,app.boolValue) isEqual:@[@"fr-FR"]]);
            assert(errno==EDOM && nativeCalls==before);
        }
        NSDictionary *all=ReadMultiple(nil,(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host);
        assert([all[@"AppleLocale"] isEqual:@"fr_FR"] && [all[@"AppleLanguages"] isEqual:@[@"fr-FR"]] && [all[@"Unrelated"] isEqual:@42] && all.count==3 && errno==EIO);
        NSArray *listed=ReadKeys((__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host);
        assert([[NSSet setWithArray:listed] isEqual:[NSSet setWithArray:all.allKeys]] && listed.count==all.count && errno==EIO);
        NSDictionary *subset=ReadMultiple(@[@"AppleLanguages",@"Unrelated"],(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host);
        assert(subset.count==2 && !subset[@"AppleLocale"] && [subset[@"AppleLanguages"] isEqual:@[@"fr-FR"]] && errno==EIO);
        assert(ReadMultiple(@[],(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host).count==0 && errno==EIO);
        assert(ReadMultiple(@[@"Unrelated"],(__bridge CFStringRef)domain,kCFPreferencesCurrentUser,(__bridge CFStringRef)host).count==1 && errno==EIO);
    }
    NSArray *nativeScopes=@[
        @[@"other.app",(__bridge id)kCFPreferencesCurrentUser,(__bridge id)kCFPreferencesAnyHost],
        @[NSGlobalDomain,(__bridge id)kCFPreferencesAnyUser,(__bridge id)kCFPreferencesAnyHost],
        @[NSGlobalDomain,@"someone",(__bridge id)kCFPreferencesAnyHost],
        @[NSGlobalDomain,(__bridge id)kCFPreferencesCurrentUser,@"other.host"]];
    for(NSArray *scope in nativeScopes) {
        assert([Read(CFSTR("AppleLocale"),(__bridge CFStringRef)scope[0],(__bridge CFStringRef)scope[1],(__bridge CFStringRef)scope[2],NO) isEqual:@"zh_CN"] && errno==EIO);
        NSDictionary *all=ReadMultiple(nil,(__bridge CFStringRef)scope[0],(__bridge CFStringRef)scope[1],(__bridge CFStringRef)scope[2]);
        assert([all isEqual:nativeBefore] && errno==EIO);
        assert([[NSSet setWithArray:ReadKeys((__bridge CFStringRef)scope[0],(__bridge CFStringRef)scope[1],(__bridge CFStringRef)scope[2])] isEqual:[NSSet setWithArray:nativeBefore.allKeys]] && errno==EIO);
    }
    assert([Read(CFSTR("AppleLocale"),CFSTR("other.app"),NULL,NULL,YES) isEqual:@"zh_CN"] && errno==EIO);
    assert([Read(CFSTR("Unrelated"),kCFPreferencesCurrentApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost,YES) isEqual:@42] && errno==EIO);
    assert(!Read(CFSTR("Missing"),kCFPreferencesCurrentApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost,YES) && errno==EIO);
    for(NSUInteger mode=0;mode<4;mode++) {
        external=mode!=0;internalDepth=mode==1 ? 1 : 0;enabled=mode!=2;
        if(mode==3) resolved=@{@"OverridesSystem":@NO};
        assert([Read(CFSTR("AppleLocale"),kCFPreferencesCurrentApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost,YES) isEqual:@"zh_CN"] && errno==EIO);
        assert([ReadMultiple(nil,kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost) isEqual:nativeBefore] && errno==EIO);
        assert([[NSSet setWithArray:ReadKeys(kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost)] isEqual:[NSSet setWithArray:nativeBefore.allKeys]] && errno==EIO);
    }
    external=enabled=YES;internalDepth=0;
    resolved=@{@"OverridesSystem":@YES,@"LocaleIdentifier":@"fr_FR",@"Languages":@[@"fr-FR"]};
    nativePreferences=@{@"Unrelated":@42};
    NSDictionary *projected=ReadMultiple(nil,kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    NSArray *listed=ReadKeys(kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    assert(listed.count==3 && [[NSSet setWithArray:listed] isEqual:[NSSet setWithArray:projected.allKeys]]);
    nativePreferences=nativeBefore;
    missingNative=YES;
    NSArray *emptyDomainKeys=ReadKeys(kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    assert(emptyDomainKeys.count==2 && [emptyDomainKeys containsObject:@"AppleLocale"] && [emptyDomainKeys containsObject:@"AppleLanguages"] && errno==EIO);
    NSDictionary *all=ReadMultiple(nil,kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost);
    assert(all.count==2 && [all[@"AppleLocale"] isEqual:@"fr_FR"] && errno==EIO);
    assert(!ReadMultiple(@[@"Unrelated"],kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost) && errno==EIO);
    assert(!ReadMultiple(@[],kCFPreferencesAnyApplication,kCFPreferencesCurrentUser,kCFPreferencesAnyHost) && errno==EIO);
    missingNative=NO;
    assert(!Read(CFSTR("AppleLocale"),CFSTR("restricted"),kCFPreferencesCurrentUser,kCFPreferencesAnyHost,YES) && errno==EDOM);
    assert(ReadMultiple(nil,CFSTR("restricted"),kCFPreferencesCurrentUser,kCFPreferencesAnyHost).count==0 && errno==EDOM);
    assert(!ReadKeys(CFSTR("restricted"),kCFPreferencesCurrentUser,kCFPreferencesAnyHost) && errno==EDOM);
    FixtureDefaults *defaults=[FixtureDefaults new];
    for(NSString *domain in domains) {
        errno=EDOM;NSDictionary *projected=[defaults persistentDomainForName:domain];
        assert([projected[@"AppleLocale"] isEqual:@"fr_FR"] && [projected[@"Unrelated"] isEqual:@42] && errno==EIO);
    }
    errno=EDOM;assert([[defaults persistentDomainForName:@"other.app"] isEqual:nativeBefore] && errno==EIO);
    errno=EDOM;assert(![defaults persistentDomainForName:@"restricted"] && errno==EDOM);
    internalDepth=1;errno=EDOM;assert([[defaults persistentDomainForName:NSGlobalDomain] isEqual:nativeBefore] && errno==EIO);internalDepth=0;
    missingNative=YES;errno=EDOM;assert([defaults persistentDomainForName:NSGlobalDomain].count==2 && errno==EIO);missingNative=NO;
    assert(detections==4 && [nativePreferences isEqual:nativeBefore] && !internalDepth);
    shdw_cf_preferences_restrictions_enabled=NO;shdw_defaults_restrictions_enabled=NO;
    assert([Read(CFSTR("AppleLocale"),CFSTR("restricted"),kCFPreferencesCurrentUser,kCFPreferencesAnyHost,YES) isEqual:@"zh_CN"]);
    assert(ReadKeys(CFSTR("restricted"),kCFPreferencesCurrentUser,kCFPreferencesAnyHost).count==nativeBefore.count);
    errno=EDOM;assert([[defaults persistentDomainForName:@"restricted"] isEqual:nativeBefore]);
    assert(detections==4);
    NSDictionary *persistentAfter=[NSUserDefaults.standardUserDefaults persistentDomainForName:NSGlobalDomain];
    assert([persistentBefore isEqual:persistentAfter] || (!persistentBefore && !persistentAfter));
    puts("fingerprint preferences: scoped CF/NSUserDefaults reads, selected/all keys, Copy ownership, native/internal errors, restrictions and unchanged persistent store passed");
} return 0; }
'''
installer_start = appenv.index("static void shdw_install_defaults_domain(void)")
installer_end = appenv.index('#import "../../policy/EnvironmentPolicy.h"', installer_start)
installers = appenv[installer_start:installer_end]
installers = installers.replace("%init(shadowhook_NSUserDefaultsDomain);", "domainInstalls++;")
installers = installers.replace("%init(shadowhook_NSUserDefaults);", "(void)hooks; suiteInstalls++;")
installer_source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <string.h>
@class SHDWHookSession;
static BOOL shdw_defaults_restrictions_enabled;
static unsigned shdw_defaults_domain_attempted, domainInstalls, suiteInstalls, preferenceRequests;
''' + re.search(r"SHADW_HOOK_GROUP_PREFERENCES\s*=\s*([^,]+)",
    (ROOT / "src/ShadowCore.dylib/hooks/hooks.h").read_text()).expand(r"enum { SHADW_HOOK_GROUP_PREFERENCES = \1 };") + r'''
static void shdw_libc_install_group(SHDWHookSession *hooks, uint32_t group) {
    (void)hooks; assert(group == SHADW_HOOK_GROUP_PREFERENCES); preferenceRequests++;
}
''' + installers + r'''
int main(int argc, const char **argv) { @autoreleasepool {
    assert(argc == 2);
    if(!strcmp(argv[1], "fingerprint-first")) {
        shdw_universal_fingerprint_preferences(nil);
        assert(domainInstalls == 1 && !suiteInstalls && !shdw_defaults_restrictions_enabled);
        shdw_universal_user_defaults(nil);
    } else {
        shdw_universal_user_defaults(nil);
        assert(domainInstalls == 1 && suiteInstalls == 1 && shdw_defaults_restrictions_enabled);
        shdw_universal_fingerprint_preferences(nil);
    }
    shdw_universal_fingerprint_preferences(nil);
    assert(domainInstalls == 1 && suiteInstalls == 1 && preferenceRequests == 2);
    assert(shdw_defaults_restrictions_enabled);
    puts("preference installation: both orders retain one domain hook and independent restrictions");
} return 0; }
'''

with tempfile.TemporaryDirectory(prefix="shadow-preferences-") as directory:
    source_path,binary=Path(directory)/"test.m",Path(directory)/"test"
    source_path.write_text(source)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",
                    "-fsanitize=address,undefined","-fno-omit-frame-pointer","-framework","Foundation",
                    str(source_path),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0",UBSAN_OPTIONS="halt_on_error=1"))
    source_path.write_text(installer_source)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",
                    "-fsanitize=address,undefined","-framework","Foundation",str(source_path),"-o",str(binary)],check=True)
    for order in ["fingerprint-first", "foundation-first"]:
        subprocess.run([str(binary),order],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0",UBSAN_OPTIONS="halt_on_error=1"))
