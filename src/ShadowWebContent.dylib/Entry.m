#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import "../Localization/Bootstrap.h"
#import "../Localization/Environment.h"
#import "../Localization/FunctionHook.h"
#include <dlfcn.h>
#include <errno.h>

extern xpc_object_t xpc_copy_bootstrap(void)
    __attribute__((weak_import, ns_returns_retained));

typedef void (*Initializer)(xpc_connection_t, xpc_object_t, xpc_object_t);
static Initializer nativeInitializer;

static void Initialize(xpc_connection_t connection, xpc_object_t event, xpc_object_t boost) {
    int saved = errno;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        if (!xpc_copy_bootstrap) return;
        xpc_object_t bootstrap = xpc_copy_bootstrap();
        NSDictionary *snapshot = SHDWLocalizationSnapshot(bootstrap, event);
        if (snapshot) SHDWLocalizationApplyEnvironment(snapshot);
    });
    Initializer original = __atomic_load_n(&nativeInitializer, __ATOMIC_ACQUIRE);
    errno = saved;
    original(connection, event, boost);
}

__attribute__((constructor)) static void Install(void) {
    @autoreleasepool {
        if (!SHDWLocalizationIsWebContentService(NSBundle.mainBundle.bundleIdentifier.UTF8String)) return;
        if (!xpc_copy_bootstrap) return;
        xpc_object_t bootstrap = xpc_copy_bootstrap();
        if (!SHDWLocalizationBootstrapHasPayload(bootstrap)) return;
        void *target = dlsym(RTLD_DEFAULT, "WebContentServiceInitializer");
        SHDWLocalizationHookFunction("WebContentServiceInitializer", target,
            (void *)&Initialize, (void **)&nativeInitializer);
    }
}
