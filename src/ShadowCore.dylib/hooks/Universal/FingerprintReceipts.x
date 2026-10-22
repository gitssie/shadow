#import "UniversalHooks.h"
#import "../../policy/ReceiptPolicy.h"
#import "../../policy/FingerprintPolicy.h"

static BOOL shdw_receipts_enabled;
static unsigned shdw_receipt_bundle_state, shdw_receipt_service_state;

BOOL shdw_fingerprint_receipt_path_is_restricted(const char *path) {
    return shdw_receipts_enabled && SHDWReceiptPathMatches(path);
}

@interface SHDWReceiptServiceProxy : NSProxy {
    id _target;
}
+ (instancetype)proxyWithTarget:(id)target;
- (void)appTransactionForClient:(NSDictionary *)client ignoreCache:(BOOL)ignoreCache
    reply:(void (^)(NSString *, NSError *))reply;
- (void)renewReceiptWithOptions:(NSDictionary *)options client:(NSDictionary *)client
    replyBlock:(void (^)(BOOL, NSError *))reply;
@end

@implementation SHDWReceiptServiceProxy
+ (instancetype)proxyWithTarget:(id)target {
    if(!target || object_getClass(target) == self) return target;
    SHDWReceiptServiceProxy *proxy = [self alloc];
    if(!proxy) return target;
    proxy->_target = target;
    return proxy;
}
- (NSMethodSignature *)methodSignatureForSelector:(SEL)selector {
    return [_target methodSignatureForSelector:selector];
}
- (void)forwardInvocation:(NSInvocation *)invocation { [invocation invokeWithTarget:_target]; }
- (BOOL)respondsToSelector:(SEL)selector {
    return selector == @selector(appTransactionForClient:ignoreCache:reply:) ||
        selector == @selector(renewReceiptWithOptions:client:replyBlock:) || [_target respondsToSelector:selector];
}
- (BOOL)conformsToProtocol:(Protocol *)protocol { return [_target conformsToProtocol:protocol]; }
- (Class)class { return [_target class]; }
- (BOOL)isKindOfClass:(Class)cls { return [_target isKindOfClass:cls]; }
- (void)appTransactionForClient:(NSDictionary *)client ignoreCache:(BOOL)ignoreCache
    reply:(void (^)(NSString *, NSError *))reply {
    if(!shdw_receipts_enabled || shdwInternalBusy()) {
        [_target appTransactionForClient:client ignoreCache:ignoreCache reply:reply];
        return;
    }
    if(reply) dispatch_async(dispatch_get_main_queue(), ^{ reply(nil, SHDWReceiptUnavailableError()); });
}
- (void)renewReceiptWithOptions:(NSDictionary *)options client:(NSDictionary *)client
    replyBlock:(void (^)(BOOL, NSError *))reply {
    if(!shdw_receipts_enabled || shdwInternalBusy()) {
        [_target renewReceiptWithOptions:options client:client replyBlock:reply];
        return;
    }
    if(reply) dispatch_async(dispatch_get_main_queue(), ^{ reply(NO, SHDWReceiptUnavailableError()); });
}
@end

%group shadowhook_fingerprint_receipt_bundle
%hook NSBundle
- (NSURL *)appStoreReceiptURL {
    NSURL *url = %orig;
    if(self == NSBundle.mainBundle) {
        SHDWReceiptCaptureURL(url);
        if(shdw_receipts_enabled && isCallerExternal()) return nil;
    }
    return url;
}
%end
%end

%group shadowhook_fingerprint_receipt_service
%hook SKServiceBroker
- (id)storeKitServiceWithErrorHandler:(void (^)(NSError *))handler {
    id target = %orig(handler);
    if(!shdw_receipts_enabled || shdwInternalBusy()) return target;
    return [SHDWReceiptServiceProxy proxyWithTarget:target];
}
%end
%end

void shdw_universal_fingerprint_receipts_prepare(SHDWHookSession *hooks) {
    if(!shdw_receipts_enabled || !hooks) return;
    SHDWHookSession *previous = SHDWHookSessionSetCurrent(hooks);
    @try {
        unsigned expected = 0;
        if(class_getInstanceMethod(NSBundle.class, @selector(appStoreReceiptURL)) &&
           __atomic_compare_exchange_n(&shdw_receipt_bundle_state, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            SHADOW_INTERNAL_SCOPE {
                SHDWReceiptCaptureURL(NSBundle.mainBundle.appStoreReceiptURL);
            }
            %init(shadowhook_fingerprint_receipt_bundle);
            __atomic_store_n(&shdw_receipt_bundle_state, 2, __ATOMIC_RELEASE);
        }
        expected = 0;
        Class broker = objc_getClass("SKServiceBroker");
        Method method = broker ? class_getInstanceMethod(broker, @selector(storeKitServiceWithErrorHandler:)) : NULL;
        char resultType[8] = {0}, argumentType[8] = {0};
        if(method) {
            method_getReturnType(method, resultType, sizeof(resultType));
            method_getArgumentType(method, 2, argumentType, sizeof(argumentType));
        }
        if(method && method_getNumberOfArguments(method) == 3 && resultType[0] == '@' &&
           argumentType[0] == '@' && argumentType[1] == '?' &&
           __atomic_compare_exchange_n(&shdw_receipt_service_state, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            %init(shadowhook_fingerprint_receipt_service);
            __atomic_store_n(&shdw_receipt_service_state, 2, __ATOMIC_RELEASE);
        }
    } @finally { SHDWHookSessionSetCurrent(previous); }
}

void shdw_universal_fingerprint_receipts(SHDWHookSession *hooks) {
    shdw_receipts_enabled = SHDWFingerprintInterceptsReceipts();
    if(!shdw_receipts_enabled) return;
    [Shadow shdwSetReceiptPathPredicate:shdw_fingerprint_receipt_path_is_restricted];
    shdw_universal_fingerprint_receipts_prepare(hooks);
}
