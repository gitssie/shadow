#import <Foundation/Foundation.h>
#import <Shadow/Settings.h>
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>
#import <Shadow/SHDWPlugin.h>
#import <Shadow/JBPath.h>
#import <libSandy.h>
#import "../Transport/NativeTLS.h"
#import "../Transport/NativeHTTP2.h"
#import "../Transport/BackgroundAttribution.h"
#import <objc/message.h>
#include <unistd.h>
#if SHADOW_CURL_IMPERSONATE
#import "../Transport/ProfileConfiguration.h"

static NSString *CanonicalIdentifier(NSString *identifier) {
    if(![identifier isKindOfClass:NSString.class] || !identifier.length) return nil;
    NSRange separator = [identifier rangeOfString:@"."];
    if(separator.location == NSNotFound || !separator.location || NSMaxRange(separator) == identifier.length) return identifier;
    NSString *candidate = [identifier substringFromIndex:NSMaxRange(separator)];
    Class proxyClass = NSClassFromString(@"LSApplicationProxy");
    SEL selector = NSSelectorFromString(@"applicationProxyForIdentifier:");
    if(![proxyClass respondsToSelector:selector]) return identifier;
    @try {
        id proxy = ((id(*)(id,SEL,id))objc_msgSend)(proxyClass, selector, candidate);
        id bundle = [proxy valueForKey:@"applicationIdentifier"];
        id entitlements = [proxy valueForKey:@"entitlements"];
        if([bundle isKindOfClass:NSString.class] && [bundle isEqual:candidate] &&
           [entitlements isKindOfClass:NSDictionary.class] &&
           [entitlements[@"application-identifier"] isEqual:identifier]) return candidate;
    } @catch(__unused NSException *exception) { }
    return identifier;
}

static unsigned backgroundReady;
static NSString *ProfileForOwner(NSString *identifier) {
    if(!__atomic_load_n(&backgroundReady, __ATOMIC_ACQUIRE) || !identifier.length) return nil;
    ShadowSettings *settings = ShadowSettings.sharedInstance;
    NSString *owner = [settings fingerprintOwnerIdentifierForIdentifier:CanonicalIdentifier(identifier)];
    if(!owner.length) return nil;
    NSDictionary *preferences = [settings getPreferencesForIdentifier:owner];
    if(![preferences[SHDWAppEnabledID] boolValue] || ![preferences[SHDWUniversalFingerprintID] boolValue]) return nil;
    NSDictionary *configuration = [SHDWFingerprintStore.sharedStore configurationForApplication:owner];
    NSDictionary *system = [SHDWFingerprintConfiguration resolvedSystemForConfiguration:configuration];
    return [SHDWFingerprintConfiguration curlTransportProfileForConfiguration:configuration systemVersion:system[@"Version"]];
}

static BOOL SelectHTTP2(void *user, SHDWH2Configuration *out) {
    (void)user;
    return __atomic_load_n(&backgroundReady, __ATOMIC_ACQUIRE) && SHDWTransportCopyHTTP2Configuration(SHDWBackgroundConstructionProfile(), out);
}

__attribute__((constructor)) static void Install(void) {
    @autoreleasepool {
        if(getuid() != 501 || ![NSProcessInfo.processInfo.processName isEqualToString:@"nsurlsessiond"]) return;
        libSandy_applyProfile("ShadowSettings");
        if(!SHDWBackgroundAttributionInstall(^NSString *(NSString *owner) { return ProfileForOwner(owner); })) return;
        if(!SHDWNativeHTTP2SetConfigurationResolver(SelectHTTP2)) return;
        SHDWH2Configuration initial = {0};
        if(!SHDWTransportCopyHTTP2Configuration(@"safari187_ios", &initial) || !SHDWNativeHTTP2Prepare(&initial)) return;
        if(!SHDWNativeTLSSetProfileResolver(^NSString *(id parameters) {
            return ProfileForOwner(SHDWBackgroundOwnerForParameters(parameters));
        })) return;
        if(!SHDWNativeTLSPrepare(@"safari187_ios", JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib"), JBPath(@"/etc/ssl/cert.pem"))) return;
        __atomic_store_n(&backgroundReady, 1, __ATOMIC_RELEASE);
        SHDWNativeHTTP2Activate();
    }
}
#endif
