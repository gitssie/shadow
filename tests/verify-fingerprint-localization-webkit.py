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
#import <Shadow/FingerprintConfiguration.h>
#import "Bootstrap.h"
#import "Environment.h"
#include <dlfcn.h>
#include <errno.h>
#include <string.h>
static void Check(BOOL value, const char *message) {
    if (!value) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static NSDictionary *Resolved;
static NSString *TransportProfile;
static NSString *SystemMode = @"native", *OSVersion = @"18.7.1";
static id UserAgentOverride;
#if SHADOW_CURL_IMPERSONATE
static BOOL SupportsPolicy = YES;
static BOOL SHDWCurlTransportSupportsWebKitPolicy(NSDictionary *policy) { (void)policy; return SupportsPolicy; }
#endif
static NSDictionary *SHDWFingerprintConfig(NSString *bundle) {
    (void)bundle;NSMutableDictionary *configuration=[@{@"Network":@{@"Transport":TransportProfile ?: @"native"}, @"System":@{@"Mode":SystemMode}} mutableCopy];
    if(UserAgentOverride)configuration[@"WebKit"]=@{@"OverrideUserAgent":UserAgentOverride};
    return configuration;
}
static NSString *SHDWFingerprintOSVersionString(void) { return OSVersion; }
BOOL SHDWWebUserAgentVersionIsValid(NSString *version) {
    return [version isKindOfClass:NSString.class] && [version isEqual:@"18.7.1"];
}
static NSUInteger UserAgentInstalls;
static NSString *InstalledUserAgentVersion;
BOOL SHDWWebUserAgentInstall(NSString *version) {
    Check(SHDWWebUserAgentVersionIsValid(version), "invalid UA version reached installer");
    UserAgentInstalls++; InstalledUserAgentVersion = [version copy]; errno = EINVAL; return YES;
}
static BOOL Internal, MissingSymbol, RejectHook;
static NSUInteger SymbolLookups, HookCalls, OriginalCalls;
static xpc_connection_t ReceivedConnection;
static xpc_object_t ReceivedMessage;
static int ReceivedErrno;
@interface FixtureBundle : NSObject
+ (instancetype)mainBundle;
@property(nonatomic, copy) NSString *bundleIdentifier;
@property(nonatomic, readonly) NSDictionary *infoDictionary;
@end
@implementation FixtureBundle
- (NSDictionary *)infoDictionary { return @{}; }
+ (instancetype)mainBundle { static FixtureBundle *bundle; if (!bundle) { bundle = [FixtureBundle new]; bundle.bundleIdentifier = @"local.sdkprobe.app"; } return bundle; }
@end
static void OriginalBootstrap(xpc_connection_t connection, xpc_object_t message);
static void NativeSetHandler(xpc_connection_t connection, xpc_handler_t handler);
static NSUInteger HookAttempts;
static void *ChildReplacement;
static BOOL PartialHook;
static BOOL SHDWLocalizationHookFunction(const char *symbol, void *target, void *replacement, void **original) {
    Check(symbol && target && replacement && original, "invalid hook arguments");
    if (!strcmp(symbol, "xpc_connection_set_bootstrap")) {
        Check(Internal && target == (void *)&OriginalBootstrap, "parent activation escaped scope or changed target");
    } else {
        Check(!strcmp(symbol, "xpc_connection_set_event_handler") && target == (void *)&NativeSetHandler,
              "child activation changed target");
        ChildReplacement = replacement;
    }
    HookAttempts++;
    if (RejectHook && !PartialHook) return NO;
    __atomic_store_n(original, target, __ATOMIC_RELEASE);
    if (RejectHook) return NO;
    HookCalls++; return YES;
}
static NSDictionary *SHDWFingerprintLocalization(void) { return Resolved; }
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
static NSUInteger CopyCalls, NativeCalls, SetterCalls, ReentrantCalls;
static xpc_handler_t CapturedHandler, ReentrantHandler;
static xpc_object_t UnrelatedEvent;
static xpc_connection_t ExpectedConnection;
static xpc_object_t ExpectedEvent;
static BOOL FailEnvironment, FailTimeZone;
static NSUInteger EnvironmentCalls, TimeZoneCalls;
static BOOL SHDWLocalizationInstallWebTimeZone(NSDictionary *snapshot) {
    Check(snapshot != nil, "timezone hook received absent snapshot");
    TimeZoneCalls++; errno = EINVAL; return !FailTimeZone;
}
static BOOL FixtureApplyEnvironment(NSDictionary *snapshot) {
    EnvironmentCalls++;
    if (ReentrantHandler) { errno = ERANGE; ReentrantHandler(UnrelatedEvent); }
    if (FailEnvironment) { errno = ENOMEM; return NO; }
    return SHDWLocalizationApplyEnvironment(snapshot);
}
static BOOL ExpectCustom, ExpectUserAgent;
static void NativeSetHandler(xpc_connection_t connection, xpc_handler_t handler) {
    Check(errno == EDOM && connection == ExpectedConnection, "setter connection or errno changed");
    SetterCalls++; CapturedHandler = [handler copy]; errno = EINTR;
}
static void NativeEvent(xpc_object_t event) {
    Check(errno == ERANGE && event == ExpectedEvent, "event identity or errno changed");
    NativeCalls++;
    Check(!ExpectUserAgent || (UserAgentInstalls && [InstalledUserAgentVersion isEqual:@"18.7.1"]), "UA source not installed before native event");
    Check(!strcmp(getenv("TZ"), ExpectCustom ? "America/New_York" : "Etc/UTC"), "environment not established before original handler");
    errno = ENOTTY;
}
static void *ChildDlsym(void *handle, const char *name) {
    (void)handle; Check(!strcmp(name, "xpc_connection_set_event_handler"), "wrong child event setter lookup");
    SymbolLookups++; return MissingSymbol ? NULL : (void *)&NativeSetHandler;
}
#define SHDWLocalizationApplyEnvironment FixtureApplyEnvironment
#define xpc_copy_bootstrap FixtureCopyBootstrap
#define dlsym ChildDlsym
#define NSBundle FixtureBundle
#include "Child.inc"
#undef NSBundle
#undef SHDWLocalizationApplyEnvironment
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
    Check(!HookCalls && !shdw_sym_policy_lookup_web_localization("xpc_connection_set_bootstrap"), "rejected parent hook exposed replacement");
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
    Internal = YES; SetBootstrap(web, original); Internal = NO; Check(SHDWLocalizationSnapshot(ReceivedMessage, Event()) != nil, "internal launch lost configured payload");
    SetBootstrap(nil, original); Check(ReceivedMessage == original, "nil connection modified");
    Resolved = @{@"OverridesSystem":@NO}; SetBootstrap(web, original); Check([SHDWLocalizationSnapshot(ReceivedMessage, Event())[@"TimeZone"] isEqual:Custom()[@"TimeZone"]], "installed parent snapshot changed");
    puts("native WebContent parent bootstrap tests passed");
}
static void ChildTests(NSString *mode) {
    setenv("TZ", "Etc/UTC", 1); tzset();
    NSUserDefaults *defaults = NSUserDefaults.standardUserDefaults;
    [defaults setVolatileDomain:@{@"FixtureValue":@"keep"} forName:NSArgumentDomain];
    NSDictionary *before = [[defaults volatileDomainForName:NSArgumentDomain] copy];
    [FixtureBundle mainBundle].bundleIdentifier = @"ordinary.app"; Install(); Check(!HookCalls && !SymbolLookups, "ordinary app installed WebContent hook");
    [FixtureBundle mainBundle].bundleIdentifier = @"com.apple.WebKit.WebContent";
    CurrentBootstrap = nil;
    MissingSymbol = YES; errno = EDOM; Install();
    Check(errno == EDOM && !HookCalls && !nativeSetEventHandler && !HookAttempts, "missing event setter installed child hook or changed errno");
    MissingSymbol = NO;
    RejectHook = [mode isEqual:@"rejected-hook"] || [mode isEqual:@"partial-hook"];
    PartialHook = [mode isEqual:@"partial-hook"]; Install();
    if (RejectHook) {
        Check(!HookCalls && nativeSetEventHandler == (PartialHook ? &NativeSetHandler : NULL), "failed child hook changed continuation safety");
        Install();
        Check(HookAttempts == 1 && !HookCalls, "failed child hook retried without mutation evidence");
        if (PartialHook) {
            ExpectedConnection = FixtureConnection("com.apple.WebKit.WebContent"); ExpectedEvent = Event();
            errno = EDOM; ((SetEventHandler)ChildReplacement)(ExpectedConnection, ^(xpc_object_t event) { NativeEvent(event); });
            Check(errno == EINTR && SetterCalls == 1, "partial hook setter forwarding changed");
            errno = ERANGE; CapturedHandler(ExpectedEvent);
            Check(errno == ENOTTY && NativeCalls == 1 && !EnvironmentCalls && !TimeZoneCalls, "partial hook could not forward absent bootstrap");
        }
        puts("native WebContent failed hook tests passed"); return;
    }
    Check(HookCalls == 1 && nativeSetEventHandler == &NativeSetHandler && ChildReplacement == (void *)&SetHandler, "WebContent hook missing before bootstrap arrival");
    NSUInteger lookups = SymbolLookups;
    Install();
    Check(HookCalls == 1 && HookAttempts == 1 && SymbolLookups == lookups && CopyCalls == 0, "child installation repeated or read bootstrap early");
    Check([before isEqual:[defaults volatileDomainForName:NSArgumentDomain]] && !strcmp(getenv("TZ"), "Etc/UTC"), "constructor changed process environment");
    CopyCalls = 0;
    ExpectedConnection = FixtureConnection("com.apple.WebKit.WebContent");
    SetEventHandler wrapper = (SetEventHandler)ChildReplacement;
    errno = EDOM; wrapper(ExpectedConnection, nil);
    Check(errno == EINTR && SetterCalls == 1 && !CapturedHandler && !CopyCalls, "null handler was wrapped");
    @autoreleasepool {
        xpc_handler_t handler = ^(xpc_object_t event) { NativeEvent(event); };
        errno = EDOM; wrapper(ExpectedConnection, handler);
    }
    Check(errno == EINTR && SetterCalls == 2 && CapturedHandler && !CopyCalls, "setter did not retain wrapped handler or changed errno");
    xpc_handler_t primary = CapturedHandler;
    if ([mode isEqual:@"reentrant"]) {
        UnrelatedEvent = Message();
        errno = EDOM; wrapper(ExpectedConnection, ^(xpc_object_t event) {
            Check(event == UnrelatedEvent && errno == ERANGE, "reentrant unrelated event changed");
            ReentrantCalls++;
        });
        ReentrantHandler = CapturedHandler;
    }
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), Custom(), @"local.sdkprobe.app");
    ExpectedConnection = FixtureConnection("com.apple.WebKit.WebContent"); ExpectedEvent = Event();
    ExpectCustom = [mode isEqual:@"valid"] || [mode isEqual:@"reentrant"];
    if ([mode isEqual:@"nil"]) CurrentBootstrap = nil;
    else if ([mode isEqual:@"nil-event"]) ExpectedEvent = nil;
    else if ([mode isEqual:@"missing-payload"]) CurrentBootstrap = Message();
    else if ([mode isEqual:@"wrong-payload"]) xpc_dictionary_set_string(CurrentBootstrap, "me.jjolano.shadow.localization.v1", "wrong");
    else if ([mode isEqual:@"wrong-version-type"]) xpc_dictionary_set_int64(xpc_dictionary_get_value(CurrentBootstrap, "me.jjolano.shadow.localization.v1"), "version", 1);
    else if ([mode isEqual:@"invalid-version"]) xpc_dictionary_set_uint64(xpc_dictionary_get_value(CurrentBootstrap, "me.jjolano.shadow.localization.v1"), "version", 2);
    else if ([mode isEqual:@"mismatched"]) xpc_dictionary_set_string(ExpectedEvent, "client-bundle-identifier", "different.app");
    else if ([mode isEqual:@"unsupported"]) xpc_dictionary_set_string(ExpectedEvent, "service-name", "com.apple.WebKit.Networking");
    else if ([mode isEqual:@"native"]) CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), @{@"OverridesSystem":@NO}, @"local.sdkprobe.app");
    FailEnvironment = [mode isEqual:@"failed-environment"];
    FailTimeZone = [mode isEqual:@"failed-timezone"];
    errno = ERANGE; primary(ExpectedEvent);
    Check(errno == ENOTTY, "original event handler errno result changed");
    Check(NativeCalls == 1 && CopyCalls == ([mode isEqual:@"reentrant"] ? 2u : 1u), "event not delivered exactly once");
    if (ExpectCustom) {
        NSDictionary *arguments = [defaults volatileDomainForName:NSArgumentDomain];
        Check([arguments[@"AppleLocale"] isEqual:@"en_US"] && [arguments[@"AppleLanguages"] isEqual:@[@"en-US", @"fr-FR"]] && [arguments[@"FixtureValue"] isEqual:@"keep"], "environment differs from payload");
        time_t winter = 1705320000, summer = 1721044800; struct tm w, s; localtime_r(&winter, &w); localtime_r(&summer, &s);
        Check(w.tm_gmtoff == -18000 && s.tm_gmtoff == -14400, "child DST mismatch");
    } else Check([before isEqual:[defaults volatileDomainForName:NSArgumentDomain]], "invalid or native payload changed defaults");
    Check(EnvironmentCalls == (ExpectCustom || FailEnvironment ? 1u : 0u), "unvalidated snapshot reached environment application");
    Check(TimeZoneCalls == (ExpectCustom || FailEnvironment || FailTimeZone ? 1u : 0u), "unvalidated snapshot reached timezone hook");
    Check(ReentrantCalls == ([mode isEqual:@"reentrant"] ? 1u : 0u), "unrelated event did not reenter configuration safely");
    ReentrantHandler = nil;
    FailEnvironment = NO; FailTimeZone = NO;
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), Custom(), @"local.sdkprobe.app");
    ExpectedEvent = Event(); ExpectCustom = YES;
    errno = ERANGE; primary(ExpectedEvent);
    Check(errno == ENOTTY, "original event handler errno result changed");
    Check(NativeCalls == 2 && CopyCalls == ([mode isEqual:@"reentrant"] ? 3u : 2u), "valid retry not delivered");
    Check(EnvironmentCalls == ([mode isEqual:@"failed-environment"] ? 2u : 1u), "environment application did not retry exactly until success");
    NSDictionary *arguments = [defaults volatileDomainForName:NSArgumentDomain];
    Check([arguments[@"AppleLocale"] isEqual:@"en_US"] && [arguments[@"AppleLanguages"] isEqual:@[@"en-US", @"fr-FR"]] && [arguments[@"FixtureValue"] isEqual:@"keep"], "retry environment differs from payload");
    NSUInteger copies = CopyCalls, applications = EnvironmentCalls, zones = TimeZoneCalls;
    CurrentBootstrap = SHDWLocalizationBootstrapMessage(Message(), @{@"OverridesSystem":@YES, @"LocaleIdentifier":@"fr_FR", @"Languages":@[@"fr-FR"], @"TimeZone":@"Europe/Paris"}, @"local.sdkprobe.app");
    errno = ERANGE; primary(ExpectedEvent);
    Check(errno == ENOTTY, "original event handler errno result changed");
    Check(NativeCalls == 3 && CopyCalls == copies + 1 && EnvironmentCalls == applications && TimeZoneCalls == zones, "successful child snapshot changed");
    puts("native WebContent child event handler tests passed");
}
static void UserAgentParentTests(void) {
    Resolved = @{@"OverridesSystem":@NO};
    SystemMode = @"native";
    SHDWFingerprintInstallWebLocalization();
    Check(!HookCalls && !SymbolLookups, "native system mode activated UA bootstrap");
    SystemMode = @"profile";
    SHDWFingerprintInstallWebLocalization();
    Check(HookCalls == 1, "UA-only profile did not install bootstrap with native localization");
    xpc_object_t original = Message();
    SetBootstrap(FixtureConnection("com.apple.WebKit.WebContent"), original);
    Check(ReceivedMessage != original && !xpc_dictionary_get_value(original, "me.jjolano.shadow.web-user-agent.v1"), "UA bootstrap mutated original");
    NSDictionary *snapshot = SHDWWebUserAgentSnapshot(ReceivedMessage, Event());
    Check([snapshot[@"Version"] isEqual:@"18.7.1"] && [snapshot[@"Owner"] isEqual:@"local.sdkprobe.app"], "UA-only version or owner missing");
    Check(!SHDWLocalizationSnapshot(ReceivedMessage, Event()), "UA-only launch acquired locale override");
    xpc_object_t wrongOwner = Event();
    xpc_dictionary_set_string(wrongOwner, "client-bundle-identifier", "different.app");
    Check(!SHDWWebUserAgentSnapshot(ReceivedMessage, wrongOwner), "UA payload accepted wrong owner");
    xpc_object_t wrongService = Event();
    xpc_dictionary_set_string(wrongService, "service-name", "com.apple.WebKit.Networking");
    Check(!SHDWWebUserAgentSnapshot(ReceivedMessage, wrongService), "UA payload accepted wrong service");
    SetBootstrap(FixtureConnection("com.apple.WebKit.Networking"), original);
    Check(ReceivedMessage == original, "UA-only profile modified Networking launch");
    puts("UA-only native-localization parent bootstrap passed");
}
static void UserAgentDisabledParentTests(NSString *mode) {
    BOOL locale = [mode isEqual:@"ua-disabled-locale"];
    BOOL transport = [mode isEqual:@"ua-disabled-transport"];
    SystemMode = @"profile"; UserAgentOverride = @NO;
    Resolved = locale ? Custom() : @{@"OverridesSystem":@NO};
    TransportProfile = transport ? @"safari184_ios" : nil;
    SHDWFingerprintInstallWebLocalization();
    Check(HookCalls == ((locale || transport) ? 1u : 0u), "disabled UA changed independent bootstrap activation");
    if (!locale && !transport) {
        Check(!SymbolLookups, "disabled UA activated bootstrap with native locale/transport");
        return;
    }
    xpc_object_t original = Message();
    SetBootstrap(FixtureConnection("com.apple.WebKit.WebContent"), original);
    Check(!SHDWWebUserAgentSnapshot(ReceivedMessage, Event()), "disabled UA sent child source override");
    Check((SHDWLocalizationSnapshot(ReceivedMessage, Event()) != nil) == locale, "UA switch changed locale routing");
#if SHADOW_CURL_IMPERSONATE
    if (transport) {
        SetBootstrap(FixtureConnection("com.apple.WebKit.Networking"), original);
        xpc_object_t event = Event();
        xpc_dictionary_set_string(event, "service-name", "com.apple.WebKit.Networking");
        Check([SHDWTransportSnapshot(ReceivedMessage, event)[@"Profile"] isEqual:@"safari184_ios"], "disabled UA removed transport profile");
    }
#endif
    puts("disabled UA preserves independent localization and transport passed");
}
static void UserAgentChildTests(NSString *mode) {
    setenv("TZ", "Etc/UTC", 1); tzset();
    NSDictionary *before = [[NSUserDefaults.standardUserDefaults volatileDomainForName:NSArgumentDomain] copy];
    [FixtureBundle mainBundle].bundleIdentifier = @"com.apple.WebKit.WebContent";
    Install();
    Check(HookCalls == 1 && !UserAgentInstalls && !CopyCalls, "child installed UA before validated bootstrap event");
    ExpectedConnection = FixtureConnection("com.apple.WebKit.WebContent");
    ExpectedEvent = Event();
    CurrentBootstrap = SHDWWebUserAgentBootstrapMessage(Message(), @"18.7.1", @"local.sdkprobe.app");
    ExpectUserAgent = [mode isEqual:@"ua-valid"] || [mode isEqual:@"ua-owner-conflict"];
    if ([mode isEqual:@"ua-wrong-owner"]) xpc_dictionary_set_string(ExpectedEvent, "client-bundle-identifier", "other.app");
    if ([mode isEqual:@"ua-wrong-service"]) xpc_dictionary_set_string(ExpectedEvent, "service-name", "com.apple.WebKit.Networking");
    if ([mode isEqual:@"ua-native"]) CurrentBootstrap = Message();
    errno = EDOM;
    ((SetEventHandler)ChildReplacement)(ExpectedConnection, ^(xpc_object_t event) { NativeEvent(event); });
    errno = ERANGE; CapturedHandler(ExpectedEvent);
    Check(NativeCalls == 1 && CopyCalls == 1 && errno == ENOTTY, "UA child forwarding identity or errno changed");
    Check(UserAgentInstalls == (ExpectUserAgent ? 1u : 0u), "unvalidated UA reached source installer");
    Check(!EnvironmentCalls && !TimeZoneCalls && !strcmp(getenv("TZ"), "Etc/UTC"), "UA-only bootstrap changed localization");
    Check([before isEqual:[NSUserDefaults.standardUserDefaults volatileDomainForName:NSArgumentDomain]], "UA-only bootstrap changed locale defaults");
    if ([mode isEqual:@"ua-owner-conflict"]) {
        CurrentBootstrap = SHDWWebUserAgentBootstrapMessage(Message(), @"18.7.1", @"other.app");
        ExpectedEvent = Event();
        xpc_dictionary_set_string(ExpectedEvent, "client-bundle-identifier", "other.app");
        Check(SHDWWebUserAgentSnapshot(CurrentBootstrap, ExpectedEvent) != nil, "owner conflict fixture is not individually valid");
        errno = ERANGE; CapturedHandler(ExpectedEvent);
        Check(UserAgentInstalls == 1 && NativeCalls == 2 && CopyCalls == 2 && errno == ENOTTY,
              "child changed frozen owner or failed to forward owner conflict");
        Check(!EnvironmentCalls && !TimeZoneCalls, "owner conflict acquired localization side effects");
    }
    puts("UA child install ordering and owner isolation passed");
}
#if SHADOW_CURL_IMPERSONATE
static void TransportParentTests(NSString *mode) {
    Resolved = @{@"OverridesSystem":@NO}; TransportProfile = @"auto";
    if ([mode isEqual:@"transport-172"]) OSVersion = @"17.2.1";
    if ([mode isEqual:@"transport-180"]) OSVersion = @"18.3.1";
    NSString *expectedProfile = [SHDWFingerprintConfiguration curlTransportProfileForConfiguration:SHDWFingerprintConfig(@"local.sdkprobe.app") systemVersion:OSVersion];
    SupportsPolicy = NO;
    SHDWFingerprintInstallWebLocalization();
    Check(HookCalls == 0, "unsupported trust policy activated transport bootstrap");
    SupportsPolicy = YES;
    SHDWFingerprintInstallWebLocalization();
    Check(HookCalls == 1, "native localization suppressed transport bootstrap");
    xpc_object_t original = Message();
    xpc_connection_t network = FixtureConnection("com.apple.WebKit.Networking");
    SetBootstrap(network, original);
    xpc_object_t event = Event();
    xpc_dictionary_set_string(event, "service-name", "com.apple.WebKit.Networking");
    Check([SHDWTransportSnapshot(ReceivedMessage, event)[@"Profile"] isEqual:expectedProfile], "transport profile not delivered");
    Check(!xpc_dictionary_get_value(original, "me.jjolano.shadow.transport.v1"), "original launch message mutated");
    SetBootstrap(FixtureConnection("com.apple.WebKit.WebContent"), original);
    Check(!xpc_dictionary_get_value(ReceivedMessage, "me.jjolano.shadow.transport.v1"), "transport payload reached rendering process");
    puts("native-localization transport bootstrap routing passed");
}
#endif
int main(int argc, const char **argv) { @autoreleasepool {
    if (argc != 2) return 2;
    NSString *mode = @(argv[1]); if ([mode isEqual:@"parent"]) ParentTests();
    else if ([mode isEqual:@"ua-parent"]) UserAgentParentTests();
    else if ([mode hasPrefix:@"ua-disabled"]) UserAgentDisabledParentTests(mode);
    else if ([mode hasPrefix:@"ua-"]) UserAgentChildTests(mode);
#if SHADOW_CURL_IMPERSONATE
    else if ([mode hasPrefix:@"transport-"]) TransportParentTests(mode);
#endif
    else ChildTests(mode);
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
    source.write_text('#import "Transport/Bootstrap.h"\n#import "WebUserAgent/Bootstrap.h"\n' + HARNESS)
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
    for curl_enabled in (0, 1):
        subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-g",
                        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation", f"-DSHADOW_CURL_IMPERSONATE={curl_enabled}",
                        "-I", str(ROOT / "src"), "-I", str(ROOT / "src/Shadow.framework/Headers"),
                        "-I", str(ROOT / "src/Localization"), str(source), str(ROOT / "src/Localization/Environment.m"),
                        str(ROOT / "src/Localization/Bootstrap.m"), str(ROOT / "src/Transport/Bootstrap.m"),
                        str(ROOT / "src/WebUserAgent/Bootstrap.m"), str(ROOT / "src/Shadow.framework/Fingerprint/Configuration.m"), "-o", str(binary)], check=True)
        modes = ["parent", "ua-parent", "ua-disabled", "ua-disabled-locale", "ua-valid", "ua-owner-conflict", "ua-wrong-owner", "ua-wrong-service", "ua-native", "rejected-hook", "partial-hook", "valid", "reentrant", "nil", "nil-event", "missing-payload", "wrong-payload", "wrong-version-type", "invalid-version", "mismatched", "unsupported", "native", "failed-environment", "failed-timezone"]
        if curl_enabled:
            modes.extend(["transport-parent", "transport-172", "transport-180", "ua-disabled-transport"])
        for mode in modes:
            subprocess.run([str(binary), mode], check=True, env=environment)
