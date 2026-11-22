#!/usr/bin/env python3
"""Exercise country getter installation and late-loaded Contacts classes."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
hook = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintLocalization.x").read_text()
hook = "\n".join(line for line in hook.splitlines() if not line.startswith("#import"))
source = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static BOOL internalRead, reject;
static NSString *region;
static unsigned nativeCalls;
@interface Shadow : NSObject
+ (BOOL)shdwIsInternalRead;
@end
@implementation Shadow
+ (BOOL)shdwIsInternalRead { errno = EINTR; return internalRead; }
@end
#define SHADOW_INTERNAL_SCOPE for(BOOL once = YES; once; once = NO)
static NSDictionary *SHDWFingerprintLocalization(void) { return @{@"OverridesSystem":@NO}; }
static NSString *SHDWFingerprintCountryCodeOverride(void) { return [region isEqual:@"native"] ? nil : region; }
static BOOL SHDWLocalizationApplyEnvironment(NSDictionary *value) { (void)value; return NO; }
static void SHDWFingerprintInstallWebLocalization(void) {}
static void shdw_universal_fingerprint_resources(id hooks, NSDictionary *resolved) { (void)hooks; (void)resolved; }
@interface SHDWHookSession : NSObject
@property(nonatomic, strong) NSMutableArray *pending;
@property(nonatomic) NSUInteger attempts;
- (BOOL)performWhenTargetAvailable:(BOOL (^)(SHDWHookSession *))attempt;
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original;
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)original;
- (void)drain;
@end
@implementation SHDWHookSession
- (instancetype)init { if((self = [super init])) _pending = [NSMutableArray new]; return self; }
- (BOOL)performWhenTargetAvailable:(BOOL (^)(SHDWHookSession *))attempt {
    BOOL done = attempt(self); if(!done) [self.pending addObject:[attempt copy]]; return done;
}
- (void)drain {
    for(BOOL (^attempt)(SHDWHookSession *) in self.pending.copy)
        if(attempt(self)) [self.pending removeObject:attempt];
}
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original {
    self.attempts++;
    if(reject) { *original = NULL; return NO; }
    Method method = class_getInstanceMethod(cls, selector);
    *original = (void *)method_getImplementation(method);
    method_setImplementation(method, (IMP)replacement);
    return YES;
}
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)original {
    (void)name; (void)replacement; (void)original; assert(NO); return NO;
}
@end
''' + hook + r'''
static id NativeCountry(id self, SEL selector) {
    (void)self; (void)selector; nativeCalls++; return @"cn";
}
static NSInteger WrongCountry(id self, SEL selector) { (void)self; (void)selector; return 7; }
static Class RegisterWithSuperclass(const char *name, Class superclass, BOOL classMethod, BOOL invalid) {
    Class cls = objc_allocateClassPair(superclass, name, 0);
    assert(cls);
    assert(class_addMethod(classMethod ? object_getClass(cls) : cls,
        sel_registerName(classMethod ? "defaultCountryCode" : "countryCode"),
        invalid ? (IMP)WrongCountry : (IMP)NativeCountry, invalid ? "q@:" : "@@:"));
    objc_registerClassPair(cls); return cls;
}
static Class Register(const char *name, BOOL classMethod, BOOL invalid) {
    return RegisterWithSuperclass(name, NSObject.class, classMethod, invalid);
}
static id Read(id target, const char *name) {
    return ((id (*)(id, SEL))objc_msgSend)(target, sel_registerName(name));
}
int main(int argc, const char *argv[]) { @autoreleasepool {
    assert(argc == 2); region = @(argv[1]);
    BOOL native = [region isEqual:@"native"];
    BOOL invalid = [region isEqual:@"invalid"];
    reject = [region isEqual:@"reject"];
    if(invalid || reject) region = @"FR";
    SHDWHookSession *session = [SHDWHookSession new];
    shdw_universal_fingerprint_localization(session);
    assert(session.pending.count == (native ? 0 : 3) && session.attempts == 0);
    Class defaults = Register("CNContactsUserDefaults", NO, invalid);
    id userDefaults = [defaults new];
    [session drain];
    assert(session.pending.count == (native ? 0 : 2));
    Class concrete = RegisterWithSuperclass("CNiOSABContactsUserDefaults", defaults, NO, invalid);
    id concreteDefaults = [concrete new];
    Class phone = Register("CNPhoneNumber", YES, invalid);
    [session drain]; [session drain];
    assert(!session.pending.count);
    if(invalid) {
        assert(session.attempts == 0);
        assert(((NSInteger (*)(id, SEL))objc_msgSend)(userDefaults, sel_registerName("countryCode")) == 7);
    } else {
        assert(session.attempts == (native ? 0 : 3));
        NSString *expected = native || reject ? @"cn" : region.lowercaseString;
        assert([Read(concreteDefaults, "countryCode") isEqual:expected]);
        errno = EDOM;
        assert([Read(userDefaults, "countryCode") isEqual:expected] && errno == EDOM);
        errno = ERANGE;
        assert([Read(phone, "defaultCountryCode") isEqual:expected] && errno == ERANGE);
        if(!native && !reject) assert(nativeCalls == 0);
        internalRead = YES;
        assert([Read(userDefaults, "countryCode") isEqual:@"cn"]);
        assert([Read(concreteDefaults, "countryCode") isEqual:@"cn"]);
        assert([Read(phone, "defaultCountryCode") isEqual:@"cn"]);
        internalRead = NO;
    }
    printf("Contacts country: %s passed (selection, late load, ABI, native/internal, refusal)\n", argv[1]);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-contacts-") as directory:
    source_path, binary = Path(directory) / "test.m", Path(directory) / "test"
    source_path.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    str(source_path), "-o", str(binary)], check=True)
    for mode in ["FR", "GB", "US", "native", "invalid", "reject"]:
        subprocess.run([str(binary), mode], check=True,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
