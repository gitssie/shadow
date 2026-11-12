#import "Sessions.h"
#import "../Transport/Bootstrap.h"
#import "../Localization/FunctionHook.h"
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
        if (snapshot) SHDWNetworkingInstall(snapshot);
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
            void *target = dlsym(RTLD_DEFAULT, "xpc_connection_set_event_handler");
            if (target) SHDWLocalizationHookFunction("xpc_connection_set_event_handler", target,
                (void *)&SetHandler, (void **)&nativeSetHandler);
        }
    }
    errno = saved;
}
