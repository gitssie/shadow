#!/usr/bin/env python3
"""Check process-local defaults without accessing the persistent preference store."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HOOK_SOURCE = ROOT / "src/ShadowCore.dylib/hooks/Universal/FingerprintLocalization.x"
HARNESS = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import "Environment.h"
#include <errno.h>
#include <time.h>

static void Check(BOOL success, const char *message) {
    if(!success) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
int main(void) { @autoreleasepool {
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    NSString *domain = NSBundle.mainBundle.bundleIdentifier ?: @"shadow.runtime.fixture";
    NSDictionary *persistent = [[defaults persistentDomainForName:domain] copy];
    [defaults setVolatileDomain:@{@"UnrelatedFixture":@"preserve"} forName:NSArgumentDomain];
    NSString *originalTZ = getenv("TZ") ? @(getenv("TZ")) : nil;
    NSDate *instant = [NSDate dateWithTimeIntervalSince1970:1705320000];
    NSArray *invalid = @[@{}, @{@"LocaleIdentifier":@"en_US", @"Languages":@[@"en-US"], @"TimeZone":@"Invalid/Zone"},
        @{@"LocaleIdentifier":@"en_US", @"Languages":@[@1], @"TimeZone":@"America/New_York"}];
    for(NSDictionary *value in invalid) {
        errno = EDOM;
        Check(!SHDWLocalizationApplyEnvironment(value), "invalid environment accepted");
        Check(errno == EDOM, "invalid environment changed errno");
        NSString *currentTZ = getenv("TZ") ? @(getenv("TZ")) : nil;
        Check([currentTZ isEqual:originalTZ] || (!currentTZ && !originalTZ), "invalid environment changed TZ");
    }
    NSDictionary *resolved = @{@"LocaleIdentifier":@"en_US", @"Languages":@[@"en-US"], @"TimeZone":@"America/New_York"};
    errno = ERANGE;
    Check(SHDWLocalizationApplyEnvironment(resolved), "valid environment rejected");
    Check(errno == ERANGE, "environment changed errno");
    NSDictionary *arguments = [defaults volatileDomainForName:NSArgumentDomain];
    Check([arguments[@"AppleLocale"] isEqual:@"en_US"] && [arguments[@"AppleLanguages"] isEqual:@[@"en-US"]], "volatile language/locale mismatch");
    Check([arguments[@"UnrelatedFixture"] isEqual:@"preserve"], "existing volatile values overwritten");
    Check([NSTimeZone.defaultTimeZone.name isEqual:@"America/New_York"], "Foundation default zone mismatch");
    CFTimeZoneRef zone = CFTimeZoneCopyDefault();
    Check([(__bridge NSString *)CFTimeZoneGetName(zone) isEqual:@"America/New_York"], "CF default zone mismatch");
    CFRelease(zone);
    time_t winter = 1705320000, summer = 1721044800;
    struct tm localWinter, localSummer;
    localtime_r(&winter, &localWinter); localtime_r(&summer, &localSummer);
    Check(localWinter.tm_gmtoff == -18000 && localSummer.tm_gmtoff == -14400, "libc winter/summer DST offset mismatch");
    NSDateFormatter *formatter = [NSDateFormatter new]; formatter.dateFormat = @"yyyy-MM-dd HH:mm XXX";
    Check([[formatter stringFromDate:instant] hasSuffix:@"-05:00"], "new date formatter default zone mismatch");
    Check(instant.timeIntervalSince1970 == 1705320000, "UTC instant was changed");
    NSDictionary *after = [defaults persistentDomainForName:domain];
    Check([persistent isEqual:after] || (!persistent && !after), "persistent preferences modified");
    Check(SHDWLocalizationApplyEnvironment(resolved), "reapplying resolved environment failed");
    puts("fingerprint localization runtime: passed (volatile defaults, libc/Foundation/CF timezones, DST, UTC, invalid inputs)");
} return 0; }
'''

CALENDAR_HARNESS = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <errno.h>
#include <string.h>
static NSLocale *shdw_localization_locale;
static NSTimeZone *shdw_localization_zone;
static NSArray *shdw_localization_preferred_languages;
static BOOL applies;
static BOOL shdw_localization_applies(void) { return applies; }
static NSCalendar *nativeCalendar;
static id OriginalCalendar(id self, SEL command) { (void)self; (void)command; return nativeCalendar; }
__CALENDAR_HOOK__
__CF_HOOKS__
static void Check(BOOL value, const char *message) {
    if(!value) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
int main(void) { @autoreleasepool {
    nativeCalendar = [[NSCalendar alloc] initWithCalendarIdentifier:NSCalendarIdentifierBuddhist];
    nativeCalendar.timeZone = [NSTimeZone timeZoneWithName:@"Asia/Bangkok"];
    shdw_localization_locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US"];
    shdw_localization_zone = [NSTimeZone timeZoneWithName:@"America/New_York"];
    applies = YES;
    errno = EDOM;
    NSCalendar *calendar = shdw_localization_calendar(nil, @selector(currentCalendar), OriginalCalendar);
    Check([calendar.calendarIdentifier isEqual:NSCalendarIdentifierGregorian], "custom en_US retained native Buddhist calendar");
    Check([calendar.locale.localeIdentifier isEqual:@"en_US"], "custom calendar locale mismatch");
    Check([calendar.timeZone.name isEqual:@"America/New_York"], "custom calendar timezone mismatch");
    Check(errno == EDOM, "calendar override changed errno");
    Check([nativeCalendar.calendarIdentifier isEqual:NSCalendarIdentifierBuddhist] &&
          [nativeCalendar.timeZone.name isEqual:@"Asia/Bangkok"], "native calendar instance mutated");
    shdw_localization_locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US@calendar=buddhist"];
    calendar = shdw_localization_calendar(nil, @selector(currentCalendar), OriginalCalendar);
    Check([calendar.calendarIdentifier isEqual:NSCalendarIdentifierBuddhist], "explicit target locale calendar ignored");
    applies = NO;
    Check(shdw_localization_calendar(nil, @selector(currentCalendar), OriginalCalendar) == nativeCalendar,
          "internal/native calendar did not pass through unchanged");
    Check(!shdw_sym_policy_lookup_localization("CFLocaleCopyCurrent"), "unpublished CF symbol exposed");
    shdw_localization_cf_ready = 1;
    Check(!shdw_sym_policy_lookup_localization("CFLocaleCopyCurrent"), "CF symbol without native original exposed");
    shdw_original_copyLocale = CFLocaleCopyCurrent;
    shdw_original_copyLanguages = CFLocaleCopyPreferredLanguages;
    shdw_original_copySystemZone = CFTimeZoneCopySystem;
    shdw_original_copyDefaultZone = CFTimeZoneCopyDefault;
    Check(!shdw_sym_policy_lookup_localization(NULL) && !shdw_sym_policy_lookup_localization("unknown"), "unrelated CF symbol intercepted");
    Check(shdw_sym_policy_lookup_localization("CFLocaleCopyCurrent") == (void *)&shdw_localization_copyLocale &&
          shdw_sym_policy_lookup_localization("CFLocaleCopyPreferredLanguages") == (void *)&shdw_localization_copyLanguages &&
          shdw_sym_policy_lookup_localization("CFTimeZoneCopySystem") == (void *)&shdw_localization_copySystemZone &&
          shdw_sym_policy_lookup_localization("CFTimeZoneCopyDefault") == (void *)&shdw_localization_copyDefaultZone,
          "CF symbol lookup did not select corresponding production wrappers");
    applies = YES;
    shdw_localization_locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US"];
    shdw_localization_preferred_languages = @[@"en-US"];
    errno = ERANGE;
    CFLocaleRef locale = shdw_localization_copyLocale();
    Check(errno == ERANGE, "CF locale wrapper changed errno");
    Check(CFEqual(CFLocaleGetIdentifier(locale), CFSTR("en_US")), "CF locale wrapper did not return configured locale");
    CFRelease(locale);
    errno = EDOM;
    CFArrayRef languages = shdw_localization_copyLanguages();
    Check(errno == EDOM, "CF languages wrapper changed errno");
    Check(CFEqual(languages, (__bridge CFArrayRef)shdw_localization_preferred_languages), "CF languages wrapper mismatch");
    CFRelease(languages);
    errno = E2BIG;
    CFTimeZoneRef systemZone = shdw_localization_copySystemZone(), defaultZone = shdw_localization_copyDefaultZone();
    Check(errno == E2BIG, "CF timezone wrappers changed errno");
    Check(CFEqual(CFTimeZoneGetName(systemZone), CFSTR("America/New_York")) &&
          CFEqual(CFTimeZoneGetName(defaultZone), CFSTR("America/New_York")), "CF zone wrapper mismatch");
    CFRelease(systemZone); CFRelease(defaultZone);
    applies = NO;
    CFLocaleRef expected = CFLocaleCopyCurrent(); locale = shdw_localization_copyLocale();
    Check(CFEqual(locale, expected), "CF internal/native read did not preserve original locale");
    CFRelease(locale); CFRelease(expected);
    CFArrayRef expectedLanguages = CFLocaleCopyPreferredLanguages(); languages = shdw_localization_copyLanguages();
    Check(CFEqual(languages, expectedLanguages), "CF internal/native languages did not pass through");
    CFRelease(languages); CFRelease(expectedLanguages);
    CFTimeZoneRef expectedSystemZone = CFTimeZoneCopySystem(), expectedDefaultZone = CFTimeZoneCopyDefault();
    systemZone = shdw_localization_copySystemZone(); defaultZone = shdw_localization_copyDefaultZone();
    Check(CFEqual(systemZone, expectedSystemZone) && CFEqual(defaultZone, expectedDefaultZone), "CF internal/native timezones did not pass through");
    CFRelease(systemZone); CFRelease(defaultZone); CFRelease(expectedSystemZone); CFRelease(expectedDefaultZone);
    puts("fingerprint localization calendar: passed (actual hook, Buddhist native/Gregorian target, explicit target calendar, native pass-through)");
    puts("fingerprint localization CF: passed (actual wrappers, lookup publication, concrete values, Copy ownership, native pass-through)");
} return 0; }
'''

hook = HOOK_SOURCE.read_text()
assert "hookFunction:" not in hook, "CF localization must use the supported import-symbol registration"
assert "hookRebindSymbol:@#symbol" in hook, "CF localization rebind registration missing"
assert "dlsym(RTLD_DEFAULT, #symbol)" in hook, "native CF originals must be captured separately"
assert "outOldPtr:NULL" in hook, "late image replay must not replace captured native CF originals"
dyld = (ROOT / "src/ShadowCore.dylib/hooks/Universal/dyld.x").read_text()
assert "shdw_sym_policy_lookup_localization(symbol)" in dyld, "dlsym localization dispatch missing"
assert "shdw_sym_policy_lookup_localization(name)" in dyld, "CFBundle localization dispatch missing"
assert "shdw_sym_policy_lookup_localization(const char *name)" in (ROOT / "src/ShadowCore.dylib/hooks/UniversalHooks.h").read_text(), "localization dispatch declaration missing"
calendar_start = hook.index("static id shdw_localization_calendar(")
calendar_end = hook.index("static id shdw_localization_currentCalendar(", calendar_start)
calendar_hook = hook[calendar_start:calendar_end]
cf_start = hook.index("static CFLocaleRef (*shdw_original_copyLocale)")
cf_end = hook.index("void shdw_universal_fingerprint_localization(", cf_start)
cf_hooks = hook[cf_start:cf_end]

CFBUNDLE_HARNESS = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <string.h>
static BOOL external = YES, denied, nestedBatch, missingExport;
static BOOL isCallerExternal(void) { return external; }
static BOOL shdw_cfbundle_denied(CFBundleRef bundle) { (void)bundle; return denied; }
static void KnownNative(void) {}
static void HiddenNative(void) {}
static CFLocaleRef NativeLocale(void) { return CFLocaleCreate(NULL, CFSTR("en_FR")); }
static CFLocaleRef CustomLocale(void) { return CFLocaleCreate(NULL, CFSTR("en_US")); }
static BOOL shdw_addr_is_restricted(void *address) { return address == (void *)CustomLocale || address == (void *)HiddenNative; }
typedef struct { const char *name; void *replacement; } shdw_sym_policy_entry_t;
__CFBUNDLE_DECLARATIONS__
static const shdw_sym_policy_entry_t shdw_sym_policy_table[] = {
__CFBUNDLE_ENTRIES__
};
#define SHADOW_SYM_POLICY_COUNT (sizeof(shdw_sym_policy_table)/sizeof(shdw_sym_policy_table[0]))
#define NULL_LOOKUP(name) static void *shdw_sym_policy_lookup_##name(const char *symbol) { (void)symbol; return NULL; }
NULL_LOOKUP(libc) NULL_LOOKUP(mach) NULL_LOOKUP(sandbox) NULL_LOOKUP(mem) NULL_LOOKUP(iokit)
NULL_LOOKUP(network) NULL_LOOKUP(system_version) NULL_LOOKUP(fingerprint) NULL_LOOKUP(syscall)
static void *shdw_sym_policy_lookup_web_localization(const char *symbol) { (void)symbol; return NULL; }
static void *shdw_sym_policy_lookup_localization(const char *symbol) {
    return !strcmp(symbol, "CFLocaleCopyCurrent") ? (void *)CustomLocale : NULL;
}
__CFBUNDLE_WRAPPERS__
static void *NativeSingle(CFBundleRef bundle, CFStringRef name) {
    (void)bundle;
    if(missingExport) return NULL;
    if(CFEqual(name, CFSTR("CFLocaleCopyCurrent"))) return (void *)NativeLocale;
    if(CFEqual(name, CFSTR("HiddenName"))) return (void *)HiddenNative;
    return (void *)KnownNative;
}
static void NativeBatch(CFBundleRef bundle, CFArrayRef names, void *table[]) {
    if(!names || !table) return;
    for(CFIndex i=0;i<CFArrayGetCount(names);i++) {
        CFStringRef name = CFArrayGetValueAtIndex(names,i);
        table[i] = nestedBatch ? replaced_CFBundleGetFunctionPointerForName(bundle,name) : NativeSingle(bundle,name);
    }
}
static void *NativeData(CFBundleRef bundle, CFStringRef name) { (void)bundle; (void)name; return missingExport ? NULL : (void *)KnownNative; }
@interface SHDWHookSession:NSObject
@property BOOL entrypointSuccess;
@property BOOL preserveOnFailure;
@property NSUInteger rebinds;
@property BOOL requestedOriginalFromRebind;
@property void *continuation;
-(BOOL)hookFunction:(void *)target withReplacement:(void *)replacement outOldPtr:(void **)original;
-(BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)original;
@end
@implementation SHDWHookSession
-(BOOL)hookFunction:(void *)target withReplacement:(void *)replacement outOldPtr:(void **)original {
    (void)target; (void)replacement; *original = (self.entrypointSuccess || self.preserveOnFailure) ? self.continuation : NULL; return self.entrypointSuccess;
}
-(BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)original {
    (void)symbol; (void)replacement; self.rebinds++; self.requestedOriginalFromRebind |= original != NULL; return YES;
}
@end
__CFBUNDLE_INSTALLER__
static void Check(BOOL value,const char *message) { if(!value){fprintf(stderr,"FAIL: %s\n",message);exit(1);} }
int main(void) { @autoreleasepool {
    SHDWHookSession *hooks=[SHDWHookSession new];
    shdw_install_cfbundle_lookup(hooks,@"CFBundleGetFunctionPointerForName",NativeSingle,replaced_CFBundleGetFunctionPointerForName,(void **)&original_CFBundleGetFunctionPointerForName);
    shdw_install_cfbundle_lookup(hooks,@"CFBundleGetFunctionPointersForNames",NativeBatch,replaced_CFBundleGetFunctionPointersForNames,(void **)&original_CFBundleGetFunctionPointersForNames);
    shdw_install_cfbundle_lookup(hooks,@"CFBundleGetDataPointerForName",NativeData,replaced_CFBundleGetDataPointerForName,(void **)&original_CFBundleGetDataPointerForName);
    Check(hooks.rebinds==3 && !hooks.requestedOriginalFromRebind,"entrypoint failures did not register stable-original rebinds");
    Check(original_CFBundleGetFunctionPointerForName==NativeSingle && original_CFBundleGetFunctionPointersForNames==NativeBatch && original_CFBundleGetDataPointerForName==NativeData,"failed registration lost native originals");
    void *address=replaced_CFBundleGetFunctionPointerForName(NULL,CFSTR("CFLocaleCopyCurrent"));
    Check(address==(void *)CustomLocale,"CFBundle single lookup escaped localization dispatch");
    CFLocaleRef locale=((CFLocaleRef(*)(void))address)();
    Check(CFEqual(CFLocaleGetIdentifier(locale),CFSTR("en_US")),"CFBundle result did not execute custom locale");CFRelease(locale);
    NSArray *names=@[@"CFLocaleCopyCurrent",@"UnknownName",@"HiddenName"];
    for(NSNumber *nested in @[@NO,@YES]) {
        nestedBatch=nested.boolValue; void *table[3]={0};
        replaced_CFBundleGetFunctionPointersForNames(NULL,(__bridge CFArrayRef)names,table);
        Check(table[0]==(void *)CustomLocale && table[1]==(void *)KnownNative && !table[2],"CFBundle batch lost localized replacement, unrelated result or hidden filtering");
    }
    address=replaced_CFBundleGetFunctionPointerForName(NULL,CFSTR("CFBundleGetFunctionPointerForName"));
    Check(address==(void *)replaced_CFBundleGetFunctionPointerForName,"CFBundle lookup API self-symbol escaped policy table");
    Check(((void *(*)(CFBundleRef,CFStringRef))address)(NULL,CFSTR("CFLocaleCopyCurrent"))==(void *)CustomLocale,"dynamically obtained CFBundle API escaped localization");
    Check(replaced_CFBundleGetDataPointerForName(NULL,CFSTR("UnknownData"))==(void *)KnownNative,"unrelated data symbol changed");
    missingExport=YES;
    Check(!replaced_CFBundleGetFunctionPointerForName(NULL,CFSTR("CFLocaleCopyCurrent")) &&
          !replaced_CFBundleGetDataPointerForName(NULL,CFSTR("CFLocaleCopyCurrent")),"missing bundle export fabricated a localized pointer");
    for(NSNumber *nested in @[@NO,@YES]) {
        nestedBatch=nested.boolValue;void *missing[3]={(void *)1,(void *)1,(void *)1};
        replaced_CFBundleGetFunctionPointersForNames(NULL,(__bridge CFArrayRef)names,missing);
        Check(!missing[0]&&!missing[1]&&!missing[2],"batch fabricated absent bundle exports");
    }
    missingExport=NO;
    external=NO;
    Check(replaced_CFBundleGetFunctionPointerForName(NULL,CFSTR("CFLocaleCopyCurrent"))==(void *)NativeLocale,"internal single lookup did not preserve native result");
    void *table[3]={0};replaced_CFBundleGetFunctionPointersForNames(NULL,(__bridge CFArrayRef)names,table);
    Check(table[0]==(void *)NativeLocale && table[2]==(void *)HiddenNative,"internal batch was filtered");
    external=YES;denied=YES;
    Check(!replaced_CFBundleGetFunctionPointerForName(NULL,CFSTR("CFLocaleCopyCurrent")) && !replaced_CFBundleGetDataPointerForName(NULL,CFSTR("UnknownData")),"denied bundle lookup exposed pointer");
    replaced_CFBundleGetFunctionPointersForNames(NULL,(__bridge CFArrayRef)names,table);
    Check(!table[0]&&!table[1]&&!table[2],"denied bundle batch exposed pointer");
    hooks.entrypointSuccess=YES;hooks.continuation=(void *)KnownNative;
    void *original=NULL;shdw_install_cfbundle_lookup(hooks,@"fixture",NativeSingle,CustomLocale,&original);
    Check(original==(void *)KnownNative && hooks.rebinds==4 && !hooks.requestedOriginalFromRebind,"successful entrypoint continuation overwritten by import rebind");
    hooks.entrypointSuccess=NO;hooks.preserveOnFailure=YES;original=NULL;
    shdw_install_cfbundle_lookup(hooks,@"uncertain",NativeSingle,CustomLocale,&original);
    Check(original==(void *)KnownNative && hooks.rebinds==5 && !hooks.requestedOriginalFromRebind,"failed entrypoint discarded preserved continuation");
    puts("fingerprint localization CFBundle: passed (actual installer and wrappers, fallback, single/batch/nested/dynamic lookup, internal reads, denied bundles)");
} return 0; }
'''
bundle_start = dyld.index("static void* shdw_cfbundle_symbol_replacement(")
bundle_end = dyld.index("// A hidden image", bundle_start)
installer_start = dyld.index("static void shdw_install_cfbundle_lookup(")
installer_end = dyld.index("void shdw_universal_symlookup(", installer_start)
declarations = "\n".join(re.findall(r"^static .*replaced_CFBundle[^\n]+;$", dyld, re.M))
entries = "\n".join(re.findall(r'^    \{ "CFBundle[^\n]+$', dyld, re.M))
assert len(entries.splitlines()) == 3, "CFBundle lookup APIs missing from symbol policy"
table_source = dyld[dyld.index("static const shdw_sym_policy_entry_t shdw_sym_policy_table[]") : dyld.index("#define SHADOW_SYM_POLICY_COUNT")]
policy_names = re.findall(r'\{ "([^"]+)"', table_source)
assert policy_names == sorted(policy_names), "symbol policy table must stay sorted for dlsym bsearch"
bundle_harness = CFBUNDLE_HARNESS.replace("__CFBUNDLE_DECLARATIONS__", declarations).replace("__CFBUNDLE_ENTRIES__", entries).replace("__CFBUNDLE_WRAPPERS__", dyld[bundle_start:bundle_end]).replace("__CFBUNDLE_INSTALLER__", dyld[installer_start:installer_end])

with tempfile.TemporaryDirectory(prefix="shadow-localization-runtime-") as temp:
    temp = Path(temp)
    source, binary = temp / "main.m", temp / "check"
    source.write_text(HARNESS)
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    "-I", str(ROOT / "src/Localization"), str(source),
                    str(ROOT / "src/Localization/Environment.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
    source.write_text(bundle_harness)
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
    source.write_text(CALENDAR_HARNESS.replace("__CALENDAR_HOOK__", calendar_hook).replace("__CF_HOOKS__", cf_hooks))
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    str(source), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
