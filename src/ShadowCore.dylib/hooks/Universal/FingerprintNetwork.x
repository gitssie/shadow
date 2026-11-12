#import "UniversalHooks.h"
#import "../../policy/FingerprintPolicy.h"
#import "../../policy/CurlTransport.h"
#import "../../policy/WebLocalization.h"
#include <objc/runtime.h>
#include <stdlib.h>

static unsigned shdw_network_session_state;

static NSURLSessionConfiguration *shdw_network_configuration(NSURLSessionConfiguration *configuration) {
    return configuration ? SHDWCurlTransportConfiguration(configuration) : nil;
}

NSURLRequest *shdw_fingerprint_network_request(NSURLSession *session, NSURLRequest *request, const void *caller) {
    if(!request || !shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller)) return request;
    SHADOW_INTERNAL_SCOPE { return SHDWCurlTransportRequest(request, session); }
    return request;
}

NSString *shdw_fingerprint_cfnetwork_bundle_version(NSBundle *bundle, const void *caller) {
    if(!shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller)) return nil;
    SHADOW_INTERNAL_SCOPE {
        if([bundle.bundleIdentifier isEqualToString:@"com.apple.CFNetwork"])
            return SHDWFingerprintCFNetworkVersion();
    }
    return nil;
}

typedef struct {
    IMP original;
    SEL selector;
} SHDWNetworkRequestHook;
static SHDWHookSession *shdw_network_session_hooks;

static BOOL shdw_network_class_declares(Class cls, SEL selector) {
    unsigned count = 0;
    Method *methods = class_copyMethodList(cls, &count);
    BOOL found = NO;
    for(unsigned i = 0; i < count; i++)
        if(sel_isEqual(method_getName(methods[i]), selector)) { found = YES; break; }
    free(methods);
    return found;
}

static IMP shdw_network_request_implementation(SHDWNetworkRequestHook *cell, unsigned arguments) {
    if(arguments == 3) return imp_implementationWithBlock(^id(id session, NSURLRequest *request) {
        const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
        request = shdw_fingerprint_network_request(session, request, caller);
        return ((id (*)(id, SEL, NSURLRequest *))cell->original)(session, cell->selector, request);
    });
    if(arguments == 4) return imp_implementationWithBlock(^id(id session, NSURLRequest *request, id argument) {
        const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
        request = shdw_fingerprint_network_request(session, request, caller);
        return ((id (*)(id, SEL, NSURLRequest *, id))cell->original)(session, cell->selector, request, argument);
    });
    return imp_implementationWithBlock(^id(id session, NSURLRequest *request, id argument, id completion) {
        const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
        request = shdw_fingerprint_network_request(session, request, caller);
        return ((id (*)(id, SEL, NSURLRequest *, id, id))cell->original)(session, cell->selector, request, argument, completion);
    });
}

static void shdw_network_prepare_session(NSURLSession *session) {
    if(!session || !shdw_network_session_hooks || ![session isKindOfClass:NSURLSession.class]) return;
    static NSMutableDictionary *attempted;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ attempted = [NSMutableDictionary new]; });
    static const struct { const char *name; unsigned arguments; } selectors[] = {
        {"dataTaskWithRequest:", 3}, {"dataTaskWithRequest:completionHandler:", 4},
        {"downloadTaskWithRequest:", 3}, {"downloadTaskWithRequest:completionHandler:", 4},
        {"uploadTaskWithRequest:fromData:", 4}, {"uploadTaskWithRequest:fromData:completionHandler:", 5},
        {"uploadTaskWithRequest:fromFile:", 4}, {"uploadTaskWithRequest:fromFile:completionHandler:", 5},
        {"uploadTaskWithStreamedRequest:", 3},
    };
    SHADOW_INTERNAL_SCOPE {
        @synchronized(attempted) {
            for(Class cls = object_getClass(session); cls && cls != NSURLSession.class; cls = class_getSuperclass(cls)) {
                NSValue *key = [NSValue valueWithPointer:(__bridge const void *)cls];
                NSMutableSet *names = attempted[key];
                if(!names) attempted[key] = names = [NSMutableSet new];
                for(unsigned i = 0; i < sizeof(selectors) / sizeof(*selectors); i++) {
                    SEL selector = sel_registerName(selectors[i].name);
                    NSString *name = @(selectors[i].name);
                    if([names containsObject:name] || !shdw_network_class_declares(cls, selector)) continue;
                    Method method = class_getInstanceMethod(cls, selector);
                    if(method_getNumberOfArguments(method) != selectors[i].arguments) continue;
                    SHDWNetworkRequestHook *cell = calloc(1, sizeof(*cell));
                    if(!cell) continue;
                    cell->selector = selector;
                    IMP replacement = shdw_network_request_implementation(cell, selectors[i].arguments);
                    if(!replacement) { free(cell); continue; }
                    [names addObject:name];
                    [shdw_network_session_hooks hookMessageInClass:cls withSelector:selector
                        withReplacement:(void *)replacement outOldPtr:(void **)&cell->original];
                }
            }
        }
    }
}

static NSURLSession *(*shdw_native_network_shared_session)(id, SEL);
static NSURLSession *shdw_network_shared_session(id self, SEL selector) {
    NSURLSession *session = shdw_native_network_shared_session(self, selector);
    if(shdw_fingerprint_is_enabled()) shdw_network_prepare_session(session);
    return session;
}

static NSURLSession *(*shdw_native_network_session)(id, SEL, NSURLSessionConfiguration *);
static NSURLSession *shdw_network_session(id self, SEL selector, NSURLSessionConfiguration *configuration) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller))
        return shdw_native_network_session(self, selector, configuration);
    NSURLSessionConfiguration *updated;
    SHADOW_INTERNAL_SCOPE { updated = shdw_network_configuration(configuration); }
    NSURLSession *session = shdw_native_network_session(self, selector, updated);
    shdw_network_prepare_session(session);
    return session;
}

static NSURLSession *(*shdw_native_network_session_delegate)(id, SEL, NSURLSessionConfiguration *, id<NSURLSessionDelegate>, NSOperationQueue *);
static NSURLSession *shdw_network_session_delegate(id self, SEL selector,
    NSURLSessionConfiguration *configuration, id<NSURLSessionDelegate> delegate, NSOperationQueue *queue) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller))
        return shdw_native_network_session_delegate(self, selector, configuration, delegate, queue);
    NSURLSessionConfiguration *updated;
    SHADOW_INTERNAL_SCOPE { updated = shdw_network_configuration(configuration); }
    NSURLSession *session = shdw_native_network_session_delegate(self, selector, updated, delegate, queue);
    shdw_network_prepare_session(session);
    return session;
}

void shdw_universal_fingerprint_network_prepare(SHDWHookSession *hooks) {
    if(!hooks || !shdw_fingerprint_is_enabled()) return;
    SHDWCurlTransportPrepare();
#if SHADOW_CURL_IMPERSONATE
    SHDWFingerprintInstallWebLocalization();
#endif
    shdw_universal_bundle_metadata(hooks);
    shdw_universal_url_session(hooks);
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_network_session_state, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    BOOL sessionInstalled, delegateInstalled, sharedInstalled;
    SHADOW_INTERNAL_SCOPE {
        shdw_network_session_hooks = hooks;
        Class metaclass = object_getClass(NSURLSession.class);
        sharedInstalled = [hooks hookMessageInClass:metaclass withSelector:@selector(sharedSession)
            withReplacement:shdw_network_shared_session outOldPtr:(void **)&shdw_native_network_shared_session];
        sessionInstalled = [hooks hookMessageInClass:metaclass withSelector:@selector(sessionWithConfiguration:)
            withReplacement:shdw_network_session outOldPtr:(void **)&shdw_native_network_session];
        delegateInstalled = [hooks hookMessageInClass:metaclass withSelector:@selector(sessionWithConfiguration:delegate:delegateQueue:)
            withReplacement:shdw_network_session_delegate outOldPtr:(void **)&shdw_native_network_session_delegate];
    }
    __atomic_store_n(&shdw_network_session_state,
        sessionInstalled && delegateInstalled && sharedInstalled ? 2 : 3, __ATOMIC_RELEASE);
}
