#import "UniversalHooks.h"
#import "../../policy/FingerprintPolicy.h"
#import "../../policy/NetworkUserAgentCache.h"
#import "../../policy/CurlTransport.h"
#import "../../../Shadow.framework/Fingerprint/DiagnosticsInternal.h"
#include <dlfcn.h>
#include <objc/runtime.h>
#include <stdlib.h>

static unsigned shdw_network_user_agent_state;
static unsigned shdw_network_user_agent_source_state;
static CFStringRef (*shdw_native_network_user_agent)(void);

static NSString *shdw_network_user_agent(NSString *native) {
    if(!native.length) return native;
    const char *release = SHDWFingerprintVersionValue("kern.osrelease");
    if(!release) return native;
    static NSRegularExpression *pattern;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        pattern = [NSRegularExpression regularExpressionWithPattern:
            @"(?:^|[ \t])(CFNetwork|Darwin)/([0-9]+(?:\\.[0-9]+)*)(?=$|[ \t])" options:0 error:NULL];
    });
    NSString *network = SHDWFingerprintCFNetworkVersion();
    NSString *darwin = @(release);
    NSString *result = native;
    NSArray<NSTextCheckingResult *> *matches = [pattern matchesInString:native options:0
        range:NSMakeRange(0, native.length)];
    for(NSTextCheckingResult *match in matches.reverseObjectEnumerator) {
        NSString *token = [native substringWithRange:[match rangeAtIndex:1]];
        NSString *version = [token isEqualToString:@"CFNetwork"] ? network : darwin;
        NSRange range = [match rangeAtIndex:2];
        if(version.length && ![[native substringWithRange:range] isEqualToString:version])
            result = [result stringByReplacingCharactersInRange:range withString:version];
    }
    return result;
}

static id shdw_network_user_agent_header(NSDictionary *headers, NSString **name) {
    for(id key in headers) {
        if([key isKindOfClass:NSString.class] &&
           [key caseInsensitiveCompare:@"User-Agent"] == NSOrderedSame) {
            if(name) *name = key;
            return headers[key];
        }
    }
    if(name) *name = nil;
    return nil;
}

static NSString *shdw_network_native_user_agent(void) {
    CFStringRef (*copyUserAgent)(void) = __atomic_load_n(&shdw_native_network_user_agent, __ATOMIC_ACQUIRE);
    if(!copyUserAgent) {
        copyUserAgent = (CFStringRef (*)(void))dlsym(RTLD_DEFAULT, "_CFNetworkCopyDefaultUserAgentString");
        if(!copyUserAgent) return nil;
        __atomic_store_n(&shdw_native_network_user_agent, copyUserAgent, __ATOMIC_RELEASE);
    }
    return CFBridgingRelease(copyUserAgent());
}

static void shdw_network_prepare_user_agent_source(void) {
    if(!shdw_fingerprint_is_enabled()) return;
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_network_user_agent_source_state, &expected, 1, NO,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    unsigned state = 0;
    SHADOW_INTERNAL_SCOPE {
        NSString *native = shdw_network_native_user_agent();
        if(native) {
            NSString *updated = shdw_network_user_agent(native);
            const void *getter = (const void *)__atomic_load_n(&shdw_native_network_user_agent, __ATOMIC_ACQUIRE);
            state = SHDWNetworkReplaceUserAgentCache(getter, native, updated) ? 2 : 3;
        }
    }
    [SHDWFingerprintDiagnostics recordNetworkUserAgentSourceReady:state == 2];
    __atomic_store_n(&shdw_network_user_agent_source_state, state, __ATOMIC_RELEASE);
}

static NSString *shdw_network_default_user_agent(id supplied, BOOL present) {
    NSRange separator = NSMakeRange(NSNotFound, 0);
    if(present) {
        if(![supplied isKindOfClass:NSString.class]) return nil;
        separator = [supplied rangeOfString:@" CFNetwork/" options:NSBackwardsSearch];
        if(separator.location == NSNotFound) return nil;
        static NSRegularExpression *shape;
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            shape = [NSRegularExpression regularExpressionWithPattern:
                @"\\A CFNetwork/[0-9]+(?:\\.[0-9]+)* Darwin/[0-9]+(?:\\.[0-9]+)*\\z" options:0 error:NULL];
        });
        NSString *suffix = [supplied substringFromIndex:separator.location];
        if(![shape firstMatchInString:suffix options:0 range:NSMakeRange(0, suffix.length)]) return nil;
    }
    NSString *native = shdw_network_native_user_agent();
    if(!native) return nil;
    if(present) {
        NSRange nativeSeparator = [native rangeOfString:@" CFNetwork/" options:NSBackwardsSearch];
        if(nativeSeparator.location == NSNotFound ||
           ![[supplied substringToIndex:separator.location] isEqualToString:
             [native substringToIndex:nativeSeparator.location]]) return nil;
    }
    NSString *value = present ? supplied : native;
    NSString *updated = shdw_network_user_agent(value);
    return updated && ![updated isEqualToString:value] ? updated : nil;
}

static NSURLSessionConfiguration *shdw_network_configuration(NSURLSessionConfiguration *configuration) {
    if(!configuration) return configuration;
    configuration = SHDWCurlTransportConfiguration(configuration);
    NSDictionary *headers = configuration.HTTPAdditionalHeaders;
    NSString *key;
    id supplied = shdw_network_user_agent_header(headers, &key);
    NSString *updated = shdw_network_default_user_agent(supplied, key != nil);
    if(!updated) return configuration;
    NSURLSessionConfiguration *copy = [configuration copy];
    NSMutableDictionary *values = [headers mutableCopy] ?: [NSMutableDictionary new];
    values[key ?: @"User-Agent"] = updated;
    copy.HTTPAdditionalHeaders = values;
    return copy;
}

NSURLRequest *shdw_fingerprint_network_request(NSURLSession *session, NSURLRequest *request, const void *caller) {
    if(!request || !shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller)) return request;
    SHADOW_INTERNAL_SCOPE {
        request = SHDWCurlTransportRequest(request, session);
        NSString *key;
        id supplied = shdw_network_user_agent_header(request.allHTTPHeaderFields, &key);
        if(!key) supplied = shdw_network_user_agent_header(session.configuration.HTTPAdditionalHeaders, &key);
        NSString *updated = shdw_network_default_user_agent(supplied, key != nil);
        if(!updated) return request;
        NSMutableURLRequest *copy = [request mutableCopy];
        [copy setValue:updated forHTTPHeaderField:@"User-Agent"];
        return copy;
    }
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
    shdw_network_prepare_user_agent_source();
    NSURLSession *session = shdw_native_network_shared_session(self, selector);
    if(shdw_fingerprint_is_enabled()) shdw_network_prepare_session(session);
    return session;
}

static NSURLSession *(*shdw_native_network_session)(id, SEL, NSURLSessionConfiguration *);
static NSURLSession *shdw_network_session(id self, SEL selector, NSURLSessionConfiguration *configuration) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    if(!shdw_fingerprint_is_enabled() || !shdw_caller_is_external(caller))
        return shdw_native_network_session(self, selector, configuration);
    shdw_network_prepare_user_agent_source();
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
    shdw_network_prepare_user_agent_source();
    NSURLSessionConfiguration *updated;
    SHADOW_INTERNAL_SCOPE { updated = shdw_network_configuration(configuration); }
    NSURLSession *session = shdw_native_network_session_delegate(self, selector, updated, delegate, queue);
    shdw_network_prepare_session(session);
    return session;
}

void shdw_universal_fingerprint_network_prepare(SHDWHookSession *hooks) {
    if(!hooks || !shdw_fingerprint_is_enabled()) return;
    SHDWCurlTransportPrepare();
    shdw_network_prepare_user_agent_source();
    shdw_universal_bundle_metadata(hooks);
    shdw_universal_url_session(hooks);
    unsigned expected = 0;
    if(!__atomic_compare_exchange_n(&shdw_network_user_agent_state, &expected, 1, NO,
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
    __atomic_store_n(&shdw_network_user_agent_state,
        sessionInstalled && delegateInstalled && sharedInstalled ? 2 : 3, __ATOMIC_RELEASE);
}
