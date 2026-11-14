#import "WebCookieDiagnostics.h"
#include "../../Transport/DiagnosticsConfig.h"
#if SHADOW_CURL_IMPERSONATE && SHDW_TRANSPORT_DIAGNOSTICS
#import "WebCookieBridge.h"
#import <WebKit/WebKit.h>
#import "../SHDWHookSession.h"
#import "../../Transport/CurlDiagnostics.h"
#import <objc/runtime.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static NSString *SHDWCookieObjectID(id object) {
    return object ? [NSString stringWithFormat:@"%p", (__bridge void *)object] : @"";
}

static NSArray *SHDWDatadomeCookies(NSArray *cookies) {
    NSMutableArray *result = [NSMutableArray new];
    for (id value in cookies) {
        if (![value isKindOfClass:NSHTTPCookie.class] || ![[value name] isEqualToString:@"datadome"]) continue;
        NSHTTPCookie *cookie = value;
        NSMutableDictionary *properties = [NSMutableDictionary new];
        for (id key in cookie.properties) {
            id item = cookie.properties[key];
            if ([key isKindOfClass:NSString.class] && ([item isKindOfClass:NSString.class] || [item isKindOfClass:NSNumber.class]))
                properties[key] = item;
        }
        [result addObject:@{@"name":cookie.name ?: @"", @"value":cookie.value ?: @"", @"domain":cookie.domain ?: @"",
            @"path":cookie.path ?: @"", @"secure":@(cookie.secure), @"httpOnly":@(cookie.HTTPOnly),
            @"sessionOnly":@(cookie.sessionOnly), @"expires":cookie.expiresDate ? @([cookie.expiresDate timeIntervalSince1970]) : (id)NSNull.null,
            @"properties":properties}];
        if (result.count == 32) break;
    }
    return result;
}

static void SHDWCookieTrace(NSString *stage, NSURLRequest *request, NSDictionary *details) {
    int saved = errno;
    @try {
        NSMutableDictionary *snapshot = [details mutableCopy];
        snapshot[@"monotonicMilliseconds"] = @(SHDWCurlDiagnosticMilliseconds());
        SHDWCurlTrace(stage, request, snapshot);
    } @catch (__unused NSException *exception) { }
    errno = saved;
}

static BOOL SHDWCookieVintedURL(NSURL *url) {
    NSArray *labels = url.host.lowercaseString ? [url.host.lowercaseString componentsSeparatedByString:@"."] : @[];
    NSUInteger index = [labels indexOfObject:@"vinted"];
    if (index == NSNotFound) return NO;
    NSUInteger remaining = labels.count - index;
    return remaining == 2 || (remaining == 3 && [labels[index + 1] isEqual:@"co"] && [labels[index + 2] isEqual:@"uk"]);
}

static NSDictionary *SHDWCookieStoreDetails(NSHTTPCookieStorage *storage) {
    return @{@"storageID":SHDWCookieObjectID(storage), @"storageClass":storage ? NSStringFromClass(storage.class) : @"",
        @"sharedMatch":@(storage && storage == NSHTTPCookieStorage.sharedHTTPCookieStorage)};
}

static id SHDWCookieObjectGetter(id object, NSString *name) {
    if (!object) return nil;
    SEL selector = NSSelectorFromString(name);
    Method method = class_getInstanceMethod(object_getClass(object), selector);
    if (!method || method_getNumberOfArguments(method) != 2 || ![object respondsToSelector:selector]) return nil;
    char *type = method_copyReturnType(method);
    BOOL valid = type && type[0] == '@'; free(type);
    if (!valid) return nil;
    id value = ((id (*)(id, SEL))[object methodForSelector:selector])(object, selector);
    if ([value isKindOfClass:NSString.class]) return SHDWCurlDiagnosticString(value, 4096);
    if ([value isKindOfClass:NSURL.class]) return [value absoluteString] ?: @"";
    if ([value isKindOfClass:NSNumber.class] || value == NSNull.null) return value;
    return value ? @{@"class":NSStringFromClass([value class]), @"objectID":SHDWCookieObjectID(value)} : nil;
}

static NSDictionary *SHDWCookieContext(id object) {
    NSMutableDictionary *result = [NSMutableDictionary new];
    for (NSString *name in @[@"_siteForCookies", @"siteForCookies", @"_partitionIdentifier", @"partitionIdentifier",
            @"_storagePartitionIdentifier", @"_cookiePartitionIdentifier", @"cookiePartitionIdentifier", @"_cookiePartition", @"_topLevelSiteForCookies", @"mainDocumentURL"])
        @try { id value = SHDWCookieObjectGetter(object, name); if (value) result[name] = value; }
        @catch (__unused NSException *exception) { }
    return result;
}

void SHDWWebCookieDiagnosticsStored(NSURLRequest *request, NSHTTPCookieStorage *storage,
        NSURLSessionTask *task, NSArray<NSHTTPCookie *> *cookies) {
    int saved = errno;
    @try {
        NSArray *matches = SHDWDatadomeCookies(cookies);
        if (!matches.count) return;
        NSMutableDictionary *details = [SHDWCookieStoreDetails(storage) mutableCopy];
        details[@"cookies"] = matches;
        details[@"taskID"] = SHDWCookieObjectID(task);
        details[@"taskClass"] = task ? NSStringFromClass(task.class) : @"";
        details[@"requestContext"] = SHDWCookieContext(request);
        details[@"taskContext"] = SHDWCookieContext(task);
        SHDWCookieTrace(@"response.cookie.stored", request, details);
    } @catch (__unused NSException *exception) { }
    @finally { errno = saved; }
}

void SHDWWebCookieDiagnosticsObserveView(WKWebView *view, NSURL *baseURL, NSString *phase) {
    int saved = errno;
    @try {
        if (!view) return;
        WKWebsiteDataStore *store = view.configuration.websiteDataStore;
        WKHTTPCookieStore *cookies = store.httpCookieStore;
        NSURL *url = baseURL ?: view.URL;
        NSURLRequest *request = url ? [NSURLRequest requestWithURL:url] : nil;
        NSDictionary *details = @{@"viewID":SHDWCookieObjectID(view), @"websiteDataStoreID":SHDWCookieObjectID(store),
            @"persistent":@(store.persistent), @"cookieStoreID":SHDWCookieObjectID(cookies), @"phase":phase ?: @"",
            @"baseURL":url.absoluteString ?: @""};
        SHDWCookieTrace(@"webview.cookie.view", request, details);
        [cookies getAllCookies:^(NSArray<NSHTTPCookie *> *values) {
            int callbackErrno = errno;
            @try {
                NSMutableDictionary *snapshot = [details mutableCopy]; snapshot[@"cookies"] = SHDWDatadomeCookies(values);
                SHDWCookieTrace(@"webview.cookie.snapshot", request, snapshot);
            } @catch (__unused NSException *exception) { }
            errno = callbackErrno;
        }];
    } @catch (__unused NSException *exception) { }
    @finally { errno = saved; }
}

typedef struct { IMP original; SEL selector; } SHDWCookieMethodHook;
static _Thread_local unsigned cookieLookupDepth;

static BOOL SHDWCookieDeclaredMethod(Class cls, SEL selector, unsigned arguments, char result) {
    unsigned count = 0; Method *methods = class_copyMethodList(cls, &count); Method found = NULL;
    for (unsigned i = 0; i < count; i++) if (sel_isEqual(method_getName(methods[i]), selector)) { found = methods[i]; break; }
    free(methods);
    if (!found || method_getNumberOfArguments(found) != arguments) return NO;
    char *type = method_copyReturnType(found); BOOL valid = type && type[0] == result; free(type);
    return valid;
}

static BOOL SHDWCookieInstallSetter(SHDWHookSession *hooks, Class cls) {
    SEL selector = @selector(setCookie:completionHandler:);
    if (!SHDWCookieDeclaredMethod(cls, selector, 4, 'v')) return NO;
    SHDWCookieMethodHook *hook = calloc(1, sizeof(*hook)); if (!hook) return NO; hook->selector = selector;
    id replacement = ^(id store, NSHTTPCookie *cookie, void (^completion)(void)) {
        int incomingErrno = errno;
        /* Retired Cookie replacement; retained for reference.
        @try {
            if ([cookie.name isEqualToString:@"datadome"] &&
                [NSBundle.mainBundle.bundleIdentifier isEqualToString:@"lt.manodrabuziai.fr"]) {
                NSHTTPCookie *selected = SHDWWebCookieBridgeSelect(cookie, NSHTTPCookieStorage.sharedHTTPCookieStorage,
                    NSBundle.mainBundle.bundleIdentifier);
                if (selected != cookie) {
                    SHDWCookieTrace(@"webview.cookie.bridge.replaced", nil, @{
                        @"cookieStoreID":SHDWCookieObjectID(store), @"sourceStorageID":SHDWCookieObjectID(NSHTTPCookieStorage.sharedHTTPCookieStorage),
                        @"original":SHDWDatadomeCookies(@[cookie]), @"selected":SHDWDatadomeCookies(@[selected])});
                    cookie = selected;
                }
            }
        } @catch (__unused NSException *exception) { }
        */
        NSDictionary *details;
        @try {
            if ([cookie.name isEqualToString:@"datadome"])
                details = @{@"cookieStoreID":SHDWCookieObjectID(store), @"cookieStoreClass":NSStringFromClass([store class]),
                    @"cookies":SHDWDatadomeCookies(cookie ? @[cookie] : @[]), @"hasCompletion":@(completion != nil)};
        } @catch (__unused NSException *exception) { }
        if (!details) {
            errno = incomingErrno;
            ((void (*)(id, SEL, id, id))hook->original)(store, hook->selector, cookie, completion); return;
        }
        SHDWCookieTrace(@"webview.cookie.set.before", nil, details);
        void (^callback)(void) = completion ? ^{
            SHDWCookieTrace(@"webview.cookie.set.ack", nil, details); completion();
        } : nil;
        errno = incomingErrno;
        ((void (*)(id, SEL, id, id))hook->original)(store, hook->selector, cookie, callback);
        int returnedErrno = errno;
        SHDWCookieTrace(@"webview.cookie.set.return", nil, details);
        errno = returnedErrno;
    };
    return [hooks hookMessageInClass:cls withSelector:selector withReplacement:(void *)imp_implementationWithBlock(replacement) outOldPtr:(void **)&hook->original];
}

static BOOL SHDWCookieInstallLookup(SHDWHookSession *hooks, Class cls) {
    SEL selector = @selector(cookiesForURL:);
    if (!SHDWCookieDeclaredMethod(cls, selector, 3, '@')) return NO;
    SHDWCookieMethodHook *hook = calloc(1, sizeof(*hook)); if (!hook) return NO; hook->selector = selector;
    id replacement = ^id(NSHTTPCookieStorage *storage, NSURL *url) {
        cookieLookupDepth++;
        @try {
            id result = ((id (*)(id, SEL, id))hook->original)(storage, hook->selector, url);
            if (cookieLookupDepth == 1 && SHDWCookieVintedURL(url)) {
                int returnedErrno = errno;
                @try {
                    NSMutableDictionary *details = [SHDWCookieStoreDetails(storage) mutableCopy];
                    NSArray *matches = SHDWDatadomeCookies(result);
                    details[@"cookies"] = matches; details[@"datadomePresent"] = @(matches.count != 0);
                    SHDWCookieTrace(@"webview.cookie.lookup", [NSURLRequest requestWithURL:url], details);
                } @catch (__unused NSException *exception) { }
                errno = returnedErrno;
            }
            return result;
        } @finally { cookieLookupDepth--; }
    };
    return [hooks hookMessageInClass:cls withSelector:selector withReplacement:(void *)imp_implementationWithBlock(replacement) outOldPtr:(void **)&hook->original];
}

void SHDWWebCookieDiagnosticsInstall(SHDWHookSession *hooks) {
    int saved = errno;
    @try {
        if (!hooks) return;
        @synchronized(NSHTTPCookieStorage.class) {
            static NSMutableSet *installed; if (!installed) installed = [NSMutableSet new];
            Class webStore = objc_getClass("WKHTTPCookieStore");
            NSString *setterKey = @"WKHTTPCookieStore/setCookie";
            if (webStore && ![installed containsObject:setterKey] && SHDWCookieInstallSetter(hooks, webStore)) [installed addObject:setterKey];
            unsigned count = 0; Class *classes = objc_copyClassList(&count);
            for (unsigned i = 0; i < count; i++) {
                Class cls = classes[i], parent = cls;
                while (parent && parent != NSHTTPCookieStorage.class) parent = class_getSuperclass(parent);
                if (!parent) continue;
                NSString *key = [NSStringFromClass(cls) stringByAppendingString:@"/cookiesForURL"];
                if (![installed containsObject:key] && SHDWCookieInstallLookup(hooks, cls)) [installed addObject:key];
            }
            free(classes);
        }
    } @catch (__unused NSException *exception) { }
    @finally { errno = saved; }
}
#else
void SHDWWebCookieDiagnosticsInstall(SHDWHookSession *hooks) { (void)hooks; }
void SHDWWebCookieDiagnosticsObserveView(WKWebView *view, NSURL *url, NSString *phase) { (void)view; (void)url; (void)phase; }
void SHDWWebCookieDiagnosticsStored(NSURLRequest *request, NSHTTPCookieStorage *storage, NSURLSessionTask *task, NSArray<NSHTTPCookie *> *cookies) {
    (void)request; (void)storage; (void)task; (void)cookies;
}
#endif
