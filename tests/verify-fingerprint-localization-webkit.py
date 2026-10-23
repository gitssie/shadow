#!/usr/bin/env python3
"""Execute native WebContent bootstrap hooks against real XPC under ASAN/UBSAN."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <xpc/xpc.h>
#import "Bootstrap.h"
#import "Environment.h"
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
static void Check(BOOL value, const char *message) {
    if (!value) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static NSDictionary *Resolved;
static BOOL Internal, MissingSymbol, RejectHook;
static NSUInteger SymbolLookups, HookCalls, OriginalCalls;
static xpc_connection_t ReceivedConnection;
static xpc_object_t ReceivedMessage;
static int ReceivedErrno;
@interface FixtureBundle : NSObject
+ (instancetype)mainBundle;
@property(nonatomic, copy) NSString *bundleIdentifier;
@end
@implementation FixtureBundle
+ (instancetype)mainBundle { static FixtureBundle *bundle; if (!bundle) { bundle = [FixtureBundle new]; bundle.bundleIdentifier = @"local.sdkprobe.app"; } return bundle; }
@end
static BOOL SHDWLocalizationHookFunction(const char *symbol, void *target, void *replacement, void **original) {
    Check(symbol && replacement && original, "invalid hook arguments");
    if (!strcmp(symbol, "xpc_connection_set_bootstrap")) Check(Internal, "provider discovery/activation escaped internal scope");
    if (!target || RejectHook) return NO;
    HookCalls++; *original = target; return YES;
}
static NSDictionary *SHDWFingerprintLocalization(void) { return Resolved; }
static BOOL shdwInternalBusy(void) { return Internal; }
typedef struct { BOOL previous, once; } FixtureScope;
static FixtureScope BeginScope(void) { FixtureScope value = {Internal, YES}; Internal = YES; return value; }
static void EndScope(FixtureScope *scope) { Internal = scope->previous; }
#define SHADOW_INTERNAL_SCOPE for (FixtureScope scope __attribute__((cleanup(EndScope))) = BeginScope(); scope.once; scope.once = NO)
static void OriginalBootstrap(xpc_connection_t connection, xpc_object_t message) {
    OriginalCalls++; ReceivedConnection = connection; ReceivedMessage = message; ReceivedErrno = errno;
}
static void *FixtureDlsym(void *handle, const char *name) {
    (void)handle; Check(Internal, "parent symbol lookup escaped internal scope"); SymbolLookups++; Check(!strcmp(name, "xpc_connection_set_bootstrap"), "wrong symbol resolution");
    return MissingSymbol ? NULL : (void *)&OriginalBootstrap;
}
static xpc_connection_t FixtureConnection(const char *name) {
    xpc_object_t connection = xpc_dictionary_create(NULL, NULL, 0); xpc_dictionary_set_string(connection, "fixture-name", name); return (xpc_connection_t)connection;
}
static const char *FixtureConnectionName(xpc_connection_t connection) { return xpc_dictionary_get_string((xpc_object_t)connection, "fixture-name"); }
#define xpc_connection_get_name FixtureConnectionName
#define NSBundle FixtureBundle
#define dlsym FixtureDlsym
#include "Parent.inc"
#undef dlsym
#undef xpc_connection_get_name
#undef NSBundle
static xpc_object_t CurrentBootstrap;
static NSUInteger CopyCalls, NativeCalls;
static xpc_connection_t ExpectedConnection;
static xpc_object_t ExpectedEvent, ExpectedBoost;
static BOOL ExpectCustom;
static void NativeInitializer(xpc_connection_t connection, xpc_object_t event, xpc_object_t boost) {
    Check(errno == ERANGE, "child initializer errno changed");
    NativeCalls++;
    Check(connection == ExpectedConnection && event == ExpectedEvent && boost == ExpectedBoost, "initializer argument forwarding changed");
    Check(!strcmp(getenv("TZ"), ExpectCustom ? "America/New_York" : "Etc/UTC"), "environment not established before native initializer");
}
static void *ChildDlsym(void *handle, const char *name) {
    (void)handle; Check(!strcmp(name, "WebContentServiceInitializer"), "wrong child function lookup");
    SymbolLookups++; return MissingSymbol ? NULL : (void *)&NativeInitializer;
}
#define xpc_copy_bootstrap FixtureCopyBootstrap
#define dlsym ChildDlsym
#define NSBundle FixtureBundle
#include "Child.inc"
#undef NSBundle
#undef xpc_copy_bootstrap
#undef dlsym
xpc_object_t FixtureCopyBootstrap(void) { CopyCalls++; return CurrentBootstrap ? xpc_copy(CurrentBootstrap) : nil; }
static NSDictionary *Custom(void) { return @{@"OverridesSystem":@YES, @"LocaleIdentifier":@"en_US", @"Languages":@[@"en-US", @"fr-FR"], @"TimeZone":@"America/New_York", @"CountryCode":@"US"}; }
static xpc_object_t Message(void) { xpc_object_t value = xpc_dictionary_create(NULL, NULL, 0); xpc_dictionary_set_string(value, "application-value", "keep"); return value; }
static xpc_object_t Event(void) {
    xpc_object_t event = xpc_dictionary_create(NULL, NULL, 0);
    xpc_dictionary_set_string(event, "message-name", "bootstrap"); xpc_dictionary_set_string(event, "service-name", "com.apple.WebKit.WebContent");
    xpc_dictionary_set_string(event, "client-bundle-identifier", "local.sdkprobe.app"); return event;
}
static void ParentTests(void) {
    Resolved = @{@"OverridesSystem":@NO};
    SHDWFingerprintInstallWebLocalization();
    Check(!SymbolLookups && !HookCalls && !shdw_sym_policy_lookup_web_localization("xpc_connection_set_bootstrap"), "native installation changed parent");
    Resolved = Custom(); MissingSymbol = YES; SHDWFingerprintInstallWebLocalization();
    Check(!HookCalls && !shdw_sym_policy_lookup_web_localization("xpc_connection_set_bootstrap"), "unresolved original exposed replacement");
    MissingSymbol = NO; RejectHook = YES; SHDWFingerprintInstallWebLocalization();
    Check(!HookCalls && !shdw_sym_policy_lookup_web_localization("xpc_connection_set_bootstrap"), "failed entrypoint hook exposed replacement");
    RejectHook = NO; SHDWFingerprintInstallWebLocalization();
    Check(!Internal, "parent installation leaked internal scope");
    Check(HookCalls == 1 && shdw_sym_policy_lookup_web_localization("xpc_connection_set_bootstrap") == (void *)&SetBootstrap, "parent symbol hook not registered");
    Check(!shdw_sym_policy_lookup_web_localization(NULL) && !shdw_sym_policy_lookup_web_localization("other"), "unrelated symbol intercepted");
    xpc_connection_t web = FixtureConnection("com.apple.WebKit.WebContent");
    xpc_connection_t network = FixtureConnection("com.apple.WebKit.Networking");
    xpc_object_t original = Message(); errno = EDOM; SetBootstrap(web, original);
    Check(OriginalCalls == 1 && ReceivedConnection == web && ReceivedErrno == EDOM, "parent forwarding or errno changed");
    Check(ReceivedMessage != original && !xpc_dictionary_get_value(original, "me.jjolano.shadow.localization.v1"), "original launch message mutated");
    Check(!strcmp(xpc_dictionary_get_string(ReceivedMessage, "application-value"), "keep"), "application message lost");
    NSDictionary *decoded = SHDWLocalizationSnapshot(ReceivedMessage, Event());
    Check([decoded[@"LocaleIdentifier"] isEqual:Resolved[@"LocaleIdentifier"]] && [decoded[@"Languages"] isEqual:Resolved[@"Languages"]] && [decoded[@"TimeZone"] isEqual:Resolved[@"TimeZone"]], "launch payload differs from resolved snapshot");
    xpc_object_t languages = xpc_dictionary_get_value(ReceivedMessage, "OverrideLanguages");
    Check(xpc_array_get_count(languages) == 2 && !strcmp(xpc_array_get_string(languages, 0), "en-US") && !strcmp(xpc_array_get_string(languages, 1), "fr-FR"), "WebKit language override differs");
    xpc_object_t foreignEvent = Event(); xpc_dictionary_set_string(foreignEvent, "client-bundle-identifier", "other.app");
    Check(!SHDWLocalizationSnapshot(ReceivedMessage, foreignEvent), "payload not bound to exact owner");
    SetBootstrap(network, original); Check(ReceivedMessage == original, "network process modified");
    Internal = YES; SetBootstrap(web, original); Internal = NO; Check(ReceivedMessage == original, "internal operation intercepted");
    SetBootstrap(nil, original); Check(ReceivedMessage == original, "nil connection modified");
    Resolved = @{@"OverridesSystem":@NO}; SetBootstrap(web, original); Check(ReceivedMessage == original, "native bootstrap modified");
    puts("native WebContent parent bootstrap tests passed");
}
static void ChildTests(NSString *mode) {
    setenv("TZ", "Etc/UTC", 1); tzset();
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    [defaults setVolatileDomain:@{@"FixtureValue":@"keep"} forName:NSArgumentDomain];
    NSDictionary *before = [[defaults volatileDomainForName:NSArgumentDomain] copy];
    [FixtureBundle mainBundle].bundleIdentifier = @"ordinary.app"; Install(); Check(!HookCalls && !SymbolLookups, "ordinary app installed WebContent hook");
    [FixtureBundle mainBundle].bundleIdentifier = @"com.apple.WebKit.WebContent";
    CurrentBootstrap = nil; Install(); Check(!HookCalls && !SymbolLookups, "nil bootstrap installed child hook");
    CurrentBootstrap = Message(); Install(); Check(!HookCalls && !SymbolLookups, "absent payload installed child hook");
    xpc_dictionary_set_string(CurrentBootstrap, "me.jjolano.shadow.localization.v1", "wrong");
    Install(); Check(!HookCalls && !SymbolLookups, "wrong payload type installed child hook");
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), Custom(), @"local.sdkprobe.app");
    xpc_dictionary_set_int64(xpc_dictionary_get_value(CurrentBootstrap, "me.jjolano.shadow.localization.v1"), "version", 1);
    Install(); Check(!HookCalls && !SymbolLookups, "wrong version type installed child hook");
    xpc_dictionary_set_uint64(xpc_dictionary_get_value(CurrentBootstrap, "me.jjolano.shadow.localization.v1"), "version", 2);
    Install(); Check(!HookCalls && !SymbolLookups, "unsupported payload version installed child hook");
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), @{@"OverridesSystem":@NO}, @"local.sdkprobe.app");
    Install(); Check(!HookCalls && !SymbolLookups, "native configuration installed child hook");
    Check([before isEqual:[defaults volatileDomainForName:NSArgumentDomain]] && !strcmp(getenv("TZ"), "Etc/UTC"), "constructor changed process environment");
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), Custom(), @"local.sdkprobe.app");
    MissingSymbol = YES; Install(); Check(!HookCalls && !nativeInitializer, "missing initializer installed child hook");
    MissingSymbol = NO; Install(); Check(HookCalls == 1 && nativeInitializer == &NativeInitializer, "WebContent function hook missing");
    CopyCalls = 0;
    void *wrapper = (void *)&Initialize;
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), Custom(), @"local.sdkprobe.app");
    ExpectedConnection = FixtureConnection("com.apple.WebKit.WebContent"); ExpectedEvent = Event(); ExpectedBoost = xpc_string_create("boost");
    ExpectCustom = [mode isEqual:@"valid"];
    if ([mode isEqual:@"nil"]) CurrentBootstrap = nil;
    else if ([mode isEqual:@"nil-event"]) ExpectedEvent = nil;
    else if ([mode isEqual:@"missing-payload"]) CurrentBootstrap = Message();
    else if ([mode isEqual:@"invalid-version"]) xpc_dictionary_set_uint64(xpc_dictionary_get_value(CurrentBootstrap, "me.jjolano.shadow.localization.v1"), "version", 2);
    else if ([mode isEqual:@"mismatched"]) xpc_dictionary_set_string(ExpectedEvent, "client-bundle-identifier", "different.app");
    else if ([mode isEqual:@"unsupported"]) xpc_dictionary_set_string(ExpectedEvent, "service-name", "com.apple.WebKit.Networking");
    else if ([mode isEqual:@"native"]) CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), @{@"OverridesSystem":@NO}, @"local.sdkprobe.app");
    errno = ERANGE; ((Initializer)wrapper)(ExpectedConnection, ExpectedEvent, ExpectedBoost);
    Check(NativeCalls == 1 && CopyCalls == 1, "initializer not called exactly once");
    if (ExpectCustom) {
        NSDictionary *arguments = [defaults volatileDomainForName:NSArgumentDomain];
        Check([arguments[@"AppleLocale"] isEqual:@"en_US"] && [arguments[@"AppleLanguages"] isEqual:@[@"en-US", @"fr-FR"]] && [arguments[@"FixtureValue"] isEqual:@"keep"], "environment differs from payload");
        time_t winter = 1705320000, summer = 1721044800; struct tm w, s; localtime_r(&winter, &w); localtime_r(&summer, &s);
        Check(w.tm_gmtoff == -18000 && s.tm_gmtoff == -14400, "child DST mismatch");
    } else Check([before isEqual:[defaults volatileDomainForName:NSArgumentDomain]], "invalid or native payload changed defaults");
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), @{@"OverridesSystem":@YES, @"LocaleIdentifier":@"fr_FR", @"Languages":@[@"fr-FR"], @"TimeZone":@"Europe/Paris"}, @"local.sdkprobe.app");
    ExpectedEvent = Event(); errno = ERANGE; ((Initializer)wrapper)(ExpectedConnection, ExpectedEvent, ExpectedBoost);
    Check(NativeCalls == 2 && CopyCalls == 1, "child snapshot was reapplied or initializer skipped");
    puts("native WebContent child initializer tests passed");
}
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]); if ([mode isEqual:@"parent"]) ParentTests(); else ChildTests(mode);
} return 0; }
'''

with tempfile.TemporaryDirectory(prefix="shadow-webcontent-bootstrap-") as directory:
    temp = Path(directory)
    parent = (ROOT / "src/ShadowCore.dylib/policy/WebLocalization.m").read_text()
    child = (ROOT / "src/ShadowWebContent.dylib/Entry.m").read_text()
    # Substitute imports and the automatic constructor only; execute actual production functions.
    parent = "\n".join(line for line in parent.splitlines() if not line.startswith("#import"))
    child = "\n".join(line for line in child.splitlines() if not line.startswith("#import"))
    child = child.replace("__attribute__((constructor)) static void Install", "static void Install")
    (temp / "Parent.inc").write_text(parent)
    (temp / "Child.inc").write_text(child)
    source, binary = temp / "main.m", temp / "check"
    source.write_text(HARNESS)
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-g",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    "-I", str(ROOT / "src/Localization"), str(source), str(ROOT / "src/Localization/Environment.m"),
                    str(ROOT / "src/Localization/Bootstrap.m"), "-o", str(binary)], check=True)
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
    for mode in ("parent", "valid", "nil", "nil-event", "missing-payload", "invalid-version", "mismatched", "unsupported", "native"):
        subprocess.run([str(binary), mode], check=True, env=environment)
