#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import "../Localization/Bootstrap.h"
#import "../Localization/Environment.h"
#import "../Localization/WebTimeZone.h"
#import "../Localization/FunctionHook.h"
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>

extern xpc_object_t xpc_copy_bootstrap(void)
    __attribute__((weak_import, ns_returns_retained));

typedef void (*SetEventHandler)(xpc_connection_t, xpc_handler_t);
static SetEventHandler nativeSetEventHandler;

static void SetHandler(xpc_connection_t connection, xpc_handler_t handler) {
    int saved = errno;
    xpc_handler_t wrapped = handler ? ^(xpc_object_t event) {
        int eventErrno = errno;
        xpc_object_t bootstrap = xpc_copy_bootstrap ? xpc_copy_bootstrap() : nil;
        NSDictionary *snapshot = SHDWLocalizationSnapshot(bootstrap, event);
        if (snapshot) {
            static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
            static BOOL applied;
            pthread_mutex_lock(&lock);
            if (!applied && SHDWLocalizationInstallWebTimeZone(snapshot))
                applied = SHDWLocalizationApplyEnvironment(snapshot);
            pthread_mutex_unlock(&lock);
        }
        errno = eventErrno;
        handler(event);
    } : nil;
    SetEventHandler original = __atomic_load_n(&nativeSetEventHandler, __ATOMIC_ACQUIRE);
    errno = saved;
    original(connection, wrapped);
}

__attribute__((constructor)) static void Install(void) {
    int saved = errno;
    @autoreleasepool {
        if (SHDWLocalizationIsWebContentService(NSBundle.mainBundle.bundleIdentifier.UTF8String) &&
            xpc_copy_bootstrap) {
            static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
            static BOOL attempted;
            pthread_mutex_lock(&lock);
            if (!attempted) {
                void *target = dlsym(RTLD_DEFAULT, "xpc_connection_set_event_handler");
                if (target) {
                    attempted = YES;
                    SHDWLocalizationHookFunction("xpc_connection_set_event_handler", target,
                        (void *)&SetHandler, (void **)&nativeSetEventHandler);
                }
            }
            pthread_mutex_unlock(&lock);
        }
    }
    errno = saved;
}
