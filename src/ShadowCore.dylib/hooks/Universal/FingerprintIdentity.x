#import "UniversalHooks.h"
#import "../../policy/FingerprintPolicy.h"
#import "../../policy/FingerprintStorage.h"
#import <objc/message.h>

static BOOL shdw_identity_requested;
static NSString *shdw_identity_bundle_id;
static NSString *shdw_identity_owner_id;
static unsigned shdw_identity_device_state;
static unsigned shdw_identity_workspace_state;
static unsigned shdw_identity_proxy_state;

static BOOL shdw_identity_is_requested(void) {
    return __atomic_load_n(&shdw_identity_requested, __ATOMIC_ACQUIRE);
}

static NSUUID *shdw_identity_value(void) {
    SHADOW_INTERNAL_SCOPE {
        return SHDWFingerprintVendorIdentifier(shdw_identity_owner_id);
    }
    return nil;
}

static BOOL shdw_identity_own_proxy(id proxy) {
    if(!shdw_identity_is_requested() || ![proxy respondsToSelector:@selector(bundleIdentifier)]) return NO;
    SHADOW_INTERNAL_SCOPE {
        id bundleID = ((id (*)(id, SEL))objc_msgSend)(proxy, @selector(bundleIdentifier));
        if(![bundleID isKindOfClass:NSString.class]) return NO;
        return [bundleID isEqualToString:shdw_identity_bundle_id] ||
            [bundleID isEqualToString:shdw_identity_owner_id];
    }
    return NO;
}

static BOOL shdw_identity_has_getter(Class cls, SEL selector) {
    Method method = cls ? class_getInstanceMethod(cls, selector) : NULL;
    if(!method || method_getNumberOfArguments(method) != 2) return NO;
    char type[8] = {0};
    method_getReturnType(method, type, sizeof(type));
    return type[0] == '@';
}

%group shadowhook_fingerprint_identity_device
%hook UIDevice
- (NSUUID *)identifierForVendor {
    if(shdw_identity_is_requested()) return shdw_identity_value();
    return %orig;
}
%end
%end

%group shadowhook_fingerprint_identity_workspace
%hook LSApplicationWorkspace
- (NSUUID *)deviceIdentifierForVendor {
    if(shdw_identity_is_requested()) return shdw_identity_value();
    return %orig;
}
%end
%end

%group shadowhook_fingerprint_identity_proxy
%hook LSApplicationProxy
- (NSUUID *)deviceIdentifierForVendor {
    if(shdw_identity_own_proxy(self)) return shdw_identity_value();
    return %orig;
}
%end
%end

void shdw_universal_fingerprint_identity_prepare(SHDWHookSession *hooks) {
    if(!shdw_identity_is_requested() || !hooks) return;
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        Class deviceClass = objc_getClass("UIDevice");
        unsigned expected = 0;
        if(shdw_identity_has_getter(deviceClass, @selector(identifierForVendor)) &&
           __atomic_compare_exchange_n(&shdw_identity_device_state, &expected, 1, NO,
               __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_identity_device, UIDevice = deviceClass);
            __atomic_store_n(&shdw_identity_device_state, 2, __ATOMIC_RELEASE);
        }
        Class workspaceClass = objc_getClass("LSApplicationWorkspace");
        expected = 0;
        if(shdw_identity_has_getter(workspaceClass, @selector(deviceIdentifierForVendor)) &&
           __atomic_compare_exchange_n(&shdw_identity_workspace_state, &expected, 1, NO,
               __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_identity_workspace, LSApplicationWorkspace = workspaceClass);
            __atomic_store_n(&shdw_identity_workspace_state, 2, __ATOMIC_RELEASE);
        }
        Class proxyClass = objc_getClass("LSApplicationProxy");
        expected = 0;
        if(shdw_identity_has_getter(proxyClass, @selector(deviceIdentifierForVendor)) &&
           shdw_identity_has_getter(proxyClass, @selector(bundleIdentifier)) &&
           __atomic_compare_exchange_n(&shdw_identity_proxy_state, &expected, 1, NO,
               __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_identity_proxy, LSApplicationProxy = proxyClass);
            __atomic_store_n(&shdw_identity_proxy_state, 2, __ATOMIC_RELEASE);
        }
    } @finally {
        SHDWHookSessionSetCurrent(previous);
    }
}

void shdw_universal_fingerprint_identity(SHDWHookSession *hooks, NSString *bundleID) {
    shdw_identity_bundle_id = [bundleID copy];
    SHADOW_INTERNAL_SCOPE {
        shdw_identity_owner_id = [SHDWFingerprintOwnerIdentifier(bundleID) copy];
    }
    __atomic_store_n(&shdw_identity_requested, YES, __ATOMIC_RELEASE);
    shdw_universal_fingerprint_identity_prepare(hooks);
}
