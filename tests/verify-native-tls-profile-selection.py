#!/usr/bin/env python3
"""Exercise production TLS profile selection with independent native parameters."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
production = (root / "src/Transport/NativeTLS.m").read_text()
start = production.index("static BOOL selectSessionProfile(")
end = production.index("static uint64_t observeHandshake(", start)
selector = production[start:end]
start = production.index("BOOL SHDWNativeTLSSetProfileResolver(")
end = production.index("BOOL SHDWNativeTLSInstall(", start)
setter = production[start:end]
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include "Profiles.h"
typedef NSString * _Nullable (^SHDWNativeTLSProfileResolver)(id);
@interface SHDWNativeSessionState:NSObject
@property(nonatomic,copy) NSString *profile, *library, *ca;
@end
@implementation SHDWNativeSessionState
@end
static NSObject *lock;
static NSString *configuredProfile, *configuredLibrary, *configuredCA;
static SHDWNativeTLSProfileResolver configuredResolver;
static BOOL adapterEnabled, installationAttempted;
''' + selector + setter + r'''
int main(void) { @autoreleasepool {
    lock = [NSObject new];
    configuredProfile = @"safari187_ios";
    configuredLibrary = @"library"; configuredCA = @"CA";
    SHDWNativeSessionState *ordinary = [SHDWNativeSessionState new];
    assert(selectSessionProfile(ordinary, @"unknown") && [ordinary.profile isEqual:configuredProfile]);
    NSMutableDictionary *profiles = [@{@"a":@"safari172_ios", @"b":@"safari187_ios", @"invalid":@"not-a-profile"} mutableCopy];
    assert(SHDWNativeTLSSetProfileResolver(^NSString *(id owner) {return profiles[owner];}));
    SHDWNativeSessionState *a = [SHDWNativeSessionState new], *b = [SHDWNativeSessionState new];
    assert(selectSessionProfile(a, @"a") && [a.profile isEqual:@"safari172_ios"]);
    assert(selectSessionProfile(b, @"b") && [b.profile isEqual:@"safari187_ios"]);
    for(NSString *profile in @[@"safari172_ios", @"safari180_ios", @"safari184_ios", @"safari187_ios"]) {
        profiles[@"selected"] = profile;
        SHDWNativeSessionState *session = [SHDWNativeSessionState new];
        assert(selectSessionProfile(session, @"selected") && [session.profile isEqual:profile]);
    }
    profiles[@"a"] = @"safari180_ios";
    assert([a.profile isEqual:@"safari172_ios"] && [b.profile isEqual:@"safari187_ios"]);
    SHDWNativeSessionState *unknown = [SHDWNativeSessionState new];
    assert(!selectSessionProfile(unknown, @"unknown") && !unknown.profile);
    assert(!selectSessionProfile(unknown, @"invalid"));
    assert([a.library isEqual:@"library"] && [a.ca isEqual:@"CA"]);
    installationAttempted = YES;
    assert(!SHDWNativeTLSSetProfileResolver(nil) && configuredResolver);
    installationAttempted = NO; adapterEnabled = YES;
    assert(!SHDWNativeTLSSetProfileResolver(nil) && configuredResolver);
    puts("native TLS profile selection: independent parameters, immutable sessions, native refusal and startup-only resolver passed");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-tls-profile-") as directory:
    path = Path(directory) / "main.m"
    binary = Path(directory) / "test"
    path.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Transport"), str(path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
