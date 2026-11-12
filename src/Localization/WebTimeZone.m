#import "WebTimeZone.h"
#import "FunctionHook.h"
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdint.h>

typedef int32_t (*HostTimeZone)(uint16_t *, int32_t, int32_t *);
typedef uint16_t *(*FromUTF8)(uint16_t *, int32_t, int32_t *, const char *, int32_t, int32_t *);
static HostTimeZone nativeHostTimeZone;
static FromUTF8 fromUTF8;
static NSString *configuredZone;
static pthread_rwlock_t zoneLock = PTHREAD_RWLOCK_INITIALIZER;

static int32_t GetHostTimeZone(uint16_t *buffer, int32_t capacity, int32_t *status) {
    if (!status || *status > 0) return 0;
    int saved = errno;
    pthread_rwlock_rdlock(&zoneLock);
    int32_t length = 0;
    if (configuredZone) {
        fromUTF8(buffer, capacity, &length, configuredZone.UTF8String, -1, status);
    } else {
        HostTimeZone original = __atomic_load_n(&nativeHostTimeZone, __ATOMIC_ACQUIRE);
        length = original(buffer, capacity, status);
    }
    pthread_rwlock_unlock(&zoneLock);
    errno = saved;
    return length;
}

BOOL SHDWLocalizationInstallWebTimeZone(NSDictionary *resolved) {
    int saved = errno;
    NSString *zone = [resolved isKindOfClass:NSDictionary.class] ? resolved[@"TimeZone"] : nil;
    if (![zone isKindOfClass:NSString.class] || ![NSTimeZone timeZoneWithName:zone]) {
        errno = saved;
        return NO;
    }
    static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
    static BOOL attempted, installed;
    pthread_mutex_lock(&lock);
    if (!attempted) {
        attempted = YES;
        fromUTF8 = (FromUTF8)dlsym(RTLD_DEFAULT, "u_strFromUTF8");
        nativeHostTimeZone = (HostTimeZone)dlsym(RTLD_DEFAULT, "ucal_getHostTimeZone");
        if (fromUTF8 && nativeHostTimeZone) {
            pthread_rwlock_wrlock(&zoneLock);
            configuredZone = [zone copy];
            pthread_rwlock_unlock(&zoneLock);
            installed = SHDWLocalizationHookFunction("ucal_getHostTimeZone",
                (void *)nativeHostTimeZone, (void *)&GetHostTimeZone, (void **)&nativeHostTimeZone);
        }
    } else if (installed) {
        pthread_rwlock_wrlock(&zoneLock);
        configuredZone = [zone copy];
        pthread_rwlock_unlock(&zoneLock);
    }
    pthread_mutex_unlock(&lock);
    errno = saved;
    return installed;
}
