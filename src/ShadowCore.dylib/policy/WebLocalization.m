#import "WebLocalization.h"
#import "FingerprintLocalization.h"
#import "../../Localization/FunctionHook.h"
#import "../../Localization/Bootstrap.h"
#import <Shadow/Core.h>
#include <dlfcn.h>
#include <errno.h>
#include <string.h>

static void (*originalSetBootstrap)(xpc_connection_t, xpc_object_t);
static NSString *ownerIdentifier;
static NSDictionary *localizationSnapshot;
static unsigned ready;

static void SetBootstrap(xpc_connection_t connection, xpc_object_t bootstrap) {
    int saved = errno;
    xpc_object_t message = bootstrap;
    if (connection) {
        SHADOW_INTERNAL_SCOPE {
            if (SHDWLocalizationIsWebContentService(xpc_connection_get_name(connection))) {
                message = SHDWLocalizationBootstrapMessage(bootstrap,
                    localizationSnapshot, ownerIdentifier);
            }
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
    if (![resolved[@"OverridesSystem"] boolValue]) return;
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
