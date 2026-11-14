#import "Sessions.h"
#import "../Transport/Bootstrap.h"
#import "../Localization/FunctionHook.h"
#import "../Localization/Bootstrap.h"
#import "../Localization/Environment.h"
#import "../Transport/CurlDiagnostics.h"
#include <pthread.h>
#import "../Transport/NetworkDiagnostics.h"
#import "../ShadowCore.dylib/SHDWHookSession.h"
#include <dlfcn.h>
#include <errno.h>

extern xpc_object_t xpc_copy_bootstrap(void) __attribute__((weak_import, ns_returns_retained));
static void (*nativeSetHandler)(xpc_connection_t, xpc_handler_t);

static void SetHandler(xpc_connection_t connection, xpc_handler_t handler) {
    int saved = errno;
    xpc_handler_t wrapped = handler ? ^(xpc_object_t event) {
        int incoming = errno;
        xpc_object_t bootstrap = xpc_copy_bootstrap ? xpc_copy_bootstrap() : nil;
        NSDictionary *snapshot = SHDWTransportSnapshot(bootstrap, event);
        NSDictionary *localization = SHDWLocalizationNetworkingSnapshot(bootstrap, event);
        NSString *candidate = localization[@"Owner"] ?: snapshot[@"Owner"];
        if (candidate) {
            static pthread_mutex_t ownerLock = PTHREAD_MUTEX_INITIALIZER;
            static NSString *owner;
            static BOOL localizationApplied;
            pthread_mutex_lock(&ownerLock);
            @try {
                if (!owner) owner = [candidate copy];
                if ([owner isEqualToString:candidate]) {
                    if (localization && !localizationApplied) {
                        localizationApplied = SHDWLocalizationApplyEnvironment(localization);
                        SHDWCurlTrace(@"network.localization", nil, @{
                            @"owner": owner, @"applied": @(localizationApplied),
                            @"locale": localization[@"LocaleIdentifier"], @"languages": localization[@"Languages"]});
                    }
                    if (snapshot) SHDWNetworkingInstall(snapshot);
                }
            } @finally { pthread_mutex_unlock(&ownerLock); }
        }
        errno = incoming;
        handler(event);
    } : nil;
    errno = saved;
    nativeSetHandler(connection, wrapped);
}

__attribute__((constructor)) static void Install(void) {
    int saved = errno;
    @autoreleasepool {
        if (xpc_copy_bootstrap && SHDWTransportIsNetworkingService(NSBundle.mainBundle.bundleIdentifier.UTF8String)) {
            static SHDWHookSession *diagnosticsHooks;
            diagnosticsHooks = [SHDWHookSession new];
            SHDWNetworkDiagnosticsInstall(diagnosticsHooks);
            void *target = dlsym(RTLD_DEFAULT, "xpc_connection_set_event_handler");
            if (target) SHDWLocalizationHookFunction("xpc_connection_set_event_handler", target,
                (void *)&SetHandler, (void **)&nativeSetHandler);
        }
    }
    errno = saved;
}
