#import "WebLocalization.h"
#import "FingerprintLocalization.h"
#import "../../Localization/FunctionHook.h"
#import "../../Localization/Bootstrap.h"
#import "../../WebUserAgent/Bootstrap.h"
#import "FingerprintStorage.h"
#import "FingerprintPolicy.h"
#if SHADOW_CURL_IMPERSONATE
#import "../../Transport/Bootstrap.h"
#import "FingerprintStorage.h"
#import "CurlTransport.h"
#endif
#import <Shadow/Core.h>
#include <dlfcn.h>
#include <errno.h>
#include <string.h>

static void (*originalSetBootstrap)(xpc_connection_t, xpc_object_t);
static NSString *ownerIdentifier;
static NSDictionary *localizationSnapshot;
static NSString *userAgentVersion;
#if SHADOW_CURL_IMPERSONATE
static NSString *transportProfile;
#endif
static unsigned ready;

static void SetBootstrap(xpc_connection_t connection, xpc_object_t bootstrap) {
    int saved = errno;
    xpc_object_t message = bootstrap;
    if (connection) {
        SHADOW_INTERNAL_SCOPE {
            if (SHDWLocalizationIsWebContentService(xpc_connection_get_name(connection))) {
                message = SHDWLocalizationBootstrapMessage(bootstrap,
                    localizationSnapshot, ownerIdentifier);
                message = SHDWWebUserAgentBootstrapMessage(message, userAgentVersion, ownerIdentifier);
            }
#if SHADOW_CURL_IMPERSONATE
            if (SHDWTransportIsNetworkingService(xpc_connection_get_name(connection)))
                message = SHDWTransportBootstrapMessage(message, transportProfile, ownerIdentifier);
#endif
        }
    }
    errno = saved;
    void (*original)(xpc_connection_t, xpc_object_t) = __atomic_load_n(&originalSetBootstrap, __ATOMIC_ACQUIRE);
    original(connection, message);
}

void *shdw_sym_policy_lookup_web_localization(const char *name) {
    if (!name || !__atomic_load_n(&ready, __ATOMIC_ACQUIRE)) return NULL;
    return !strcmp(name, "xpc_connection_set_bootstrap") ? (void *)&SetBootstrap : NULL;
}

void SHDWFingerprintInstallWebLocalization(void) {
    if (__atomic_load_n(&ready, __ATOMIC_ACQUIRE)) return;
    NSDictionary *resolved = SHDWFingerprintLocalization();
    BOOL needsBootstrap = [resolved[@"OverridesSystem"] boolValue];
    SHADOW_INTERNAL_SCOPE {
        NSDictionary *configuration = SHDWFingerprintConfig(NSBundle.mainBundle.bundleIdentifier);
        if ([configuration[@"System"][@"Mode"] isEqual:@"profile"] &&
            SHDWWebUserAgentVersionIsValid(SHDWFingerprintOSVersionString()))
            userAgentVersion = [SHDWFingerprintOSVersionString() copy];
#if SHADOW_CURL_IMPERSONATE
        if ([configuration[@"Network"][@"Transport"] isEqual:@"safari184_ios"] &&
            SHDWCurlTransportSupportsWebKitPolicy(NSBundle.mainBundle.infoDictionary[@"NSAppTransportSecurity"]))
            transportProfile = @"safari184_ios";
#endif
    }
    needsBootstrap |= userAgentVersion != nil;
#if SHADOW_CURL_IMPERSONATE
    needsBootstrap |= transportProfile != nil;
#endif
    if (!needsBootstrap) return;
    SHADOW_INTERNAL_SCOPE {
        ownerIdentifier = [NSBundle.mainBundle.bundleIdentifier copy];
        localizationSnapshot = [resolved copy];
    }
    if (!ownerIdentifier.length) return;
    SHADOW_INTERNAL_SCOPE {
        void *target = dlsym(RTLD_DEFAULT, "xpc_connection_set_bootstrap");
        if (!target || target == (void *)&SetBootstrap) return;
        if (SHDWLocalizationHookFunction("xpc_connection_set_bootstrap", target,
                (void *)&SetBootstrap, (void **)&originalSetBootstrap))
            __atomic_store_n(&ready, 1, __ATOMIC_RELEASE);
    }
}
