#import "UniversalHooks.h"
#import "../../policy/FingerprintStorage.h"
#import <Shadow/FingerprintAdvertising.h>
#import <objc/message.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    SEL selector;
    NSUUID *(*original)(id, SEL);
} SHDWAdvertisingGetter;
typedef struct { SEL selector; BOOL (*original)(id, SEL); } SHDWAdvertisingTracking;
static NSString *shdw_advertising_bundle;
static SHDWHookSession *shdw_advertising_hooks;
static NSMutableSet *shdw_advertising_attempted_classes;
static unsigned shdw_advertising_registered;

static BOOL shdw_advertising_override_status(NSUInteger *status) {
    int saved = errno;
    BOOL result = NO;
    if(shdw_fingerprint_is_enabled() && ![Shadow shdwIsInternalRead]) {
        SHADOW_INTERNAL_SCOPE {
            NSString *mode = SHDWFingerprintConfig(shdw_advertising_bundle)[@"Advertising"][@"Mode"] ?: @"zero";
            result = SHDWFingerprintAdvertisingTrackingStatus(mode, status);
        }
    }
    errno = saved;
    return result;
}

static NSUUID *shdw_advertising_identifier(id manager, SHDWAdvertisingGetter *getter) {
    NSUUID *native = getter->original(manager, getter->selector);
    int saved = errno;
    BOOL applies = shdw_fingerprint_is_enabled() && ![Shadow shdwIsInternalRead];
    NSUUID *result = native;
    if(applies) {
        SHADOW_INTERNAL_SCOPE {
            NSString *mode = SHDWFingerprintConfig(shdw_advertising_bundle)[@"Advertising"][@"Mode"] ?: @"zero";
            NSString *value = SHDWFingerprintAdvertisingValue(mode,
                SHDWFingerprintData(shdw_advertising_bundle)[@"AdvertisingIdentifier"], native.UUIDString);
            if(value && ![value isEqual:native.UUIDString]) result = [[NSUUID alloc] initWithUUIDString:value] ?: native;
        }
    }
    errno = saved;
    return result;
}

static BOOL shdw_advertising_getter_supported(Method method) {
    if(!method || method_getNumberOfArguments(method) != 2) return NO;
    char type[8] = {0};
    method_getReturnType(method, type, sizeof(type));
    return type[0] == '@';
}

static void shdw_advertising_prepare_class(Class cls) {
    if(!cls || !shdw_advertising_hooks) return;
    @synchronized(shdw_advertising_attempted_classes) {
        for(NSString *name in @[@"advertisingIdentifier", @"isAdvertisingTrackingEnabled"]) {
            NSString *key = [NSString stringWithFormat:@"%p:%@", cls, name];
            if([shdw_advertising_attempted_classes containsObject:key]) continue;
            SEL selector = NSSelectorFromString(name);
            Method method = class_getInstanceMethod(cls, selector);
            if(!method || method_getNumberOfArguments(method) != 2) continue;
            Class parent = class_getSuperclass(cls);
            if(parent && method == class_getInstanceMethod(parent, selector)) continue;
            IMP replacement = NULL;
            void **original = NULL;
            if([name isEqual:@"advertisingIdentifier"] && shdw_advertising_getter_supported(method)) {
                SHDWAdvertisingGetter *getter = calloc(1, sizeof(*getter));
                if(!getter) continue;
                getter->selector = selector;
                replacement = imp_implementationWithBlock(^NSUUID *(id manager) {
                    return shdw_advertising_identifier(manager, getter);
                });
                if(!replacement) { free(getter); continue; }
                original = (void **)&getter->original;
            } else if([name isEqual:@"isAdvertisingTrackingEnabled"]) {
                char type[8] = {0}; method_getReturnType(method, type, sizeof(type));
                if(type[0] != 'B' && type[0] != 'c') continue;
                SHDWAdvertisingTracking *getter = calloc(1, sizeof(*getter));
                if(!getter) continue;
                getter->selector = selector;
                replacement = imp_implementationWithBlock(^BOOL(id manager) {
                    NSUInteger status;
                    if(shdw_advertising_override_status(&status)) return status == 3;
                    return getter->original(manager, getter->selector);
                });
                if(!replacement) { free(getter); continue; }
                original = (void **)&getter->original;
            }
            if(!replacement) continue;
            [shdw_advertising_attempted_classes addObject:key];
            [shdw_advertising_hooks hookMessageInClass:cls withSelector:selector
                withReplacement:(void *)replacement outOldPtr:original];
        }
    }
}

static void shdw_advertising_prepare_manager(id manager) {
    Class base = objc_getClass("ASIdentifierManager");
    if(!base || ![manager isKindOfClass:base]) return;
    for(Class cls = object_getClass(manager); cls && cls != NSObject.class; cls = class_getSuperclass(cls)) {
        shdw_advertising_prepare_class(cls);
        if(cls == base) break;
    }
}

static id (*shdw_advertising_original_shared)(id, SEL);
static id shdw_advertising_shared(id self, SEL selector) {
    id manager = shdw_advertising_original_shared(self, selector);
    int saved = errno;
    if(manager && shdw_fingerprint_is_enabled()) {
        SHADOW_INTERNAL_SCOPE { shdw_advertising_prepare_manager(manager); }
    }
    errno = saved;
    return manager;
}

static NSUInteger (*shdw_advertising_original_status)(id, SEL);
static NSUInteger shdw_advertising_status(id self, SEL selector) {
    NSUInteger status;
    if(shdw_advertising_override_status(&status)) return status;
    return shdw_advertising_original_status(self, selector);
}
static void (*shdw_advertising_original_request)(id, SEL, void (^)(NSUInteger));
static void shdw_advertising_request(id self, SEL selector, void (^completion)(NSUInteger)) {
    NSUInteger status;
    if(!shdw_advertising_override_status(&status)) {
        shdw_advertising_original_request(self, selector, completion);
        return;
    }
    int saved = errno;
    if(completion) dispatch_async(dispatch_get_main_queue(), ^{ completion(status); });
    errno = saved;
}

void shdw_universal_fingerprint_advertising(SHDWHookSession *hooks, NSString *bundleID) {
    if(!hooks || !bundleID.length || !shdw_fingerprint_is_enabled()) return;
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_advertising_registered, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    shdw_advertising_bundle = [bundleID copy];
    shdw_advertising_hooks = hooks;
    shdw_advertising_attempted_classes = [NSMutableSet new];
    [hooks performWhenTargetAvailable:^BOOL(SHDWHookSession *session) {
        Class cls = objc_getClass("ATTrackingManager");
        if(!cls) return NO;
        Class metaclass = object_getClass(cls);
        SEL status = sel_registerName("trackingAuthorizationStatus");
        Method method = class_getInstanceMethod(metaclass, status);
        if(!method) return NO;
        char type[8] = {0};
        method_getReturnType(method, type, sizeof(type));
        if(method && method_getNumberOfArguments(method) == 2 && !strcmp(type, @encode(NSUInteger)))
            [session hookMessageInClass:metaclass withSelector:status
                withReplacement:shdw_advertising_status outOldPtr:(void **)&shdw_advertising_original_status];
        return YES;
    }];
    [hooks performWhenTargetAvailable:^BOOL(SHDWHookSession *session) {
        Class cls = objc_getClass("ATTrackingManager");
        if(!cls) return NO;
        Class metaclass = object_getClass(cls);
        SEL request = sel_registerName("requestTrackingAuthorizationWithCompletionHandler:");
        Method method = class_getInstanceMethod(metaclass, request);
        if(!method) return NO;
        char result[8] = {0}, argument[8] = {0};
        if(method) { method_getReturnType(method, result, sizeof(result)); method_getArgumentType(method, 2, argument, sizeof(argument)); }
        if(method && method_getNumberOfArguments(method) == 3 && result[0] == 'v' && !strcmp(argument, "@?"))
            [session hookMessageInClass:metaclass withSelector:request
                withReplacement:shdw_advertising_request outOldPtr:(void **)&shdw_advertising_original_request];
        return YES;
    }];
    [hooks performWhenTargetAvailable:^BOOL(SHDWHookSession *session) {
        Class cls = objc_getClass("ASIdentifierManager");
        if(!cls) return NO;
        Class metaclass = object_getClass(cls);
        SEL shared = sel_registerName("sharedManager");
        Method factory = class_getInstanceMethod(metaclass, shared);
        if(!factory) return NO;
        if(!shdw_advertising_getter_supported(factory)) return YES;
        SHADOW_INTERNAL_SCOPE {
            shdw_advertising_prepare_class(cls);
            id manager = ((id (*)(id, SEL))objc_msgSend)(cls, shared);
            if(manager) shdw_advertising_prepare_manager(manager);
            [session hookMessageInClass:metaclass withSelector:shared
                withReplacement:shdw_advertising_shared outOldPtr:(void **)&shdw_advertising_original_shared];
        }
        return YES;
    }];
}
