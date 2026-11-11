#import "CurlTransport.h"
#import "FingerprintStorage.h"
#import <Shadow/JBPath.h>

#if SHADOW_CURL_IMPERSONATE
#import <CFNetwork/CFNetwork.h>
#include <curl/curl.h>
#include <dlfcn.h>
#include <math.h>
#include <limits.h>
#include <stdint.h>

static NSString *const SHDWCurlContext = @"me.jjolano.shadow.transport.configuration";
static NSString *const SHDWCurlBody = @"me.jjolano.shadow.transport.body";
static unsigned transportReady;
static struct {
    CURLcode (*initialize)(long);
    CURL *(*create)(void);
    CURLcode (*impersonate)(CURL *, const char *, int);
    CURLcode (*set)(CURL *, CURLoption, ...);
    CURLcode (*perform)(CURL *);
    void (*destroy)(CURL *);
    struct curl_slist *(*append)(struct curl_slist *, const char *);
    void (*freeHeaders)(struct curl_slist *);
    const char *(*error)(CURLcode);
} engine;

@interface SHDWSafari184Protocol : NSURLProtocol
@property(nonatomic, strong) NSRecursiveLock *callbackLock;
@property(atomic) BOOL stopped;
@property(nonatomic) BOOL redirected;
@property(nonatomic) BOOL responseDelivered;
@property(nonatomic) NSInteger status;
@property(nonatomic, strong) NSMutableDictionary *responseHeaders;
@property(nonatomic, strong) NSMutableArray *cookieLines;
@property(nonatomic, strong) NSURLSessionConfiguration *settings;
- (BOOL)deliverHeaders;
- (void)runTransfer;
@end

static BOOL SHDWCurlStopped(SHDWSafari184Protocol *protocol) {
    return protocol.stopped;
}

static size_t SHDWCurlWrite(char *bytes, size_t size, size_t count, void *context) {
    SHDWSafari184Protocol *protocol = (__bridge id)context;
    if (count && size > SIZE_MAX / count) return 0;
    size_t length = size * count;
    [protocol.callbackLock lock];
    BOOL deliver = !SHDWCurlStopped(protocol) && !protocol.redirected;
    if (deliver) [protocol.client URLProtocol:protocol didLoadData:[NSData dataWithBytes:bytes length:length]];
    [protocol.callbackLock unlock];
    return deliver ? length : 0;
}

static size_t SHDWCurlHeader(char *bytes, size_t size, size_t count, void *context) {
    SHDWSafari184Protocol *protocol = (__bridge id)context;
    if (count && size > SIZE_MAX / count) return 0;
    size_t length = size * count;
    if (SHDWCurlStopped(protocol)) return 0;
    NSString *line = [[NSString alloc] initWithBytes:bytes length:length encoding:NSISOLatin1StringEncoding];
    if ([line hasPrefix:@"HTTP/"]) {
        NSRange space = [line rangeOfString:@" "];
        protocol.status = space.location == NSNotFound ? 0 : [[line substringFromIndex:space.location + 1] integerValue];
        protocol.responseHeaders = [NSMutableDictionary new];
        protocol.cookieLines = [NSMutableArray new];
        protocol.responseDelivered = NO;
    } else if ([line isEqual:@"\r\n"] || [line isEqual:@"\n"]) {
        if (protocol.status >= 200 && !protocol.responseDelivered) [protocol deliverHeaders];
    } else if (!protocol.responseDelivered) {
        NSRange colon = [line rangeOfString:@":"];
        if (colon.location != NSNotFound) {
            NSString *name = [line substringToIndex:colon.location];
            NSString *value = [[line substringFromIndex:colon.location + 1] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
            protocol.responseHeaders[name] = value;
            if ([name caseInsensitiveCompare:@"Set-Cookie"] == NSOrderedSame) [protocol.cookieLines addObject:value];
        }
    }
    return length;
}

static int SHDWCurlProgress(void *context, curl_off_t total, curl_off_t downloaded, curl_off_t upload, curl_off_t uploaded) {
    (void)total; (void)downloaded; (void)upload; (void)uploaded;
    return SHDWCurlStopped((__bridge id)context) ? 1 : 0;
}

static id SHDWCurlHeaderValue(NSDictionary *headers, NSString *name) {
    for (NSString *key in headers) if ([key caseInsensitiveCompare:name] == NSOrderedSame) return headers[key];
    return nil;
}

static BOOL SHDWCurlSameOrigin(NSURL *a, NSURL *b) {
    NSNumber *portA = a.port ?: @([a.scheme.lowercaseString isEqual:@"https"] ? 443 : 80);
    NSNumber *portB = b.port ?: @([b.scheme.lowercaseString isEqual:@"https"] ? 443 : 80);
    return [a.scheme.lowercaseString isEqual:b.scheme.lowercaseString] &&
        [a.host.lowercaseString isEqual:b.host.lowercaseString] && [portA isEqual:portB];
}

static BOOL SHDWCurlRequiresNativeTrust(NSDictionary *policy) {
    for (NSString *key in policy) {
        id value = policy[key];
        if ([key isEqual:@"NSPinnedDomains"] && [value count]) return YES;
        if (([key isEqual:@"NSRequiresCertificateTransparency"] || [key hasSuffix:@"RequiresForwardSecrecy"]) &&
            [value respondsToSelector:@selector(boolValue)] && [value boolValue]) return YES;
        if ([key hasSuffix:@"MinimumTLSVersion"] && [value isKindOfClass:NSString.class] &&
            [value compare:@"TLSv1.2" options:NSNumericSearch] == NSOrderedDescending) return YES;
        if ([value isKindOfClass:NSDictionary.class] && SHDWCurlRequiresNativeTrust(value)) return YES;
    }
    return NO;
}

@implementation SHDWSafari184Protocol
+ (BOOL)canInitWithRequest:(NSURLRequest *)request {
    return SHDWCurlTransportReady() && [request.URL.scheme.lowercaseString isEqual:@"https"] &&
        (!request.HTTPBodyStream || [NSURLProtocol propertyForKey:SHDWCurlBody inRequest:request]) &&
        [NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request] != nil;
}
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    self.callbackLock = [NSRecursiveLock new];
    self.settings = [NSURLProtocol propertyForKey:SHDWCurlContext inRequest:self.request];
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{ @autoreleasepool { [self runTransfer]; } });
}
- (void)stopLoading {
    [self.callbackLock lock];
    self.stopped = YES;
    [self.callbackLock unlock];
}
- (BOOL)deliverHeaders {
    if (self.request.HTTPShouldHandleCookies && self.settings.HTTPShouldSetCookies && self.settings.HTTPCookieStorage) {
        for (NSString *line in self.cookieLines) {
            NSArray *cookies = [NSHTTPCookie cookiesWithResponseHeaderFields:@{@"Set-Cookie":line} forURL:self.request.URL];
            [self.settings.HTTPCookieStorage setCookies:cookies forURL:self.request.URL mainDocumentURL:self.request.mainDocumentURL];
        }
    }
    if (SHDWCurlHeaderValue(self.responseHeaders,@"Content-Encoding"))
        for (NSString *name in self.responseHeaders.allKeys)
            if ([name caseInsensitiveCompare:@"Content-Encoding"] == NSOrderedSame ||
                [name caseInsensitiveCompare:@"Content-Length"] == NSOrderedSame) [self.responseHeaders removeObjectForKey:name];
    NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL statusCode:self.status HTTPVersion:@"HTTP/2" headerFields:self.responseHeaders];
    NSString *location = SHDWCurlHeaderValue(self.responseHeaders, @"Location");
    NSURL *redirect = location ? [NSURL URLWithString:location relativeToURL:self.request.URL].absoluteURL : nil;
    BOOL redirects = [@[@301,@302,@303,@307,@308] containsObject:@(self.status)] && redirect;
    [self.callbackLock lock];
    if (!SHDWCurlStopped(self)) {
        self.responseDelivered = YES;
        if (redirects) {
            NSMutableURLRequest *next = [self.request mutableCopy]; next.URL = redirect;
            NSData *body = self.request.HTTPBody ?: (self.request.HTTPBodyStream ?
                [NSURLProtocol propertyForKey:SHDWCurlBody inRequest:self.request] : nil);
            if (body) { next.HTTPBodyStream = nil; next.HTTPBody = body; }
            if ((self.status == 303 && ![next.HTTPMethod isEqual:@"HEAD"]) ||
                ((self.status == 301 || self.status == 302) && [next.HTTPMethod isEqual:@"POST"])) {
                next.HTTPMethod = @"GET"; next.HTTPBody = nil; next.HTTPBodyStream = nil;
                [NSURLProtocol removePropertyForKey:SHDWCurlBody inRequest:next];
                [next setValue:nil forHTTPHeaderField:@"Content-Length"];
                [next setValue:nil forHTTPHeaderField:@"Content-Type"];
            }
            if (!SHDWCurlSameOrigin(self.request.URL, redirect)) {
                for (NSString *name in @[@"Authorization",@"Proxy-Authorization",@"Cookie"])
                    [next setValue:nil forHTTPHeaderField:name];
                NSURLSessionConfiguration *redirectSettings = [self.settings copy];
                NSMutableDictionary *values = [redirectSettings.HTTPAdditionalHeaders mutableCopy] ?: [NSMutableDictionary new];
                for (NSString *key in values.allKeys)
                    for (NSString *name in @[@"Authorization",@"Proxy-Authorization",@"Cookie"])
                        if ([key caseInsensitiveCompare:name] == NSOrderedSame) [values removeObjectForKey:key];
                redirectSettings.HTTPAdditionalHeaders = values;
                [NSURLProtocol setProperty:redirectSettings forKey:SHDWCurlContext inRequest:next];
            }
            if ([self.request.URL.scheme.lowercaseString isEqual:@"https"] && ![redirect.scheme.lowercaseString isEqual:@"https"])
                [next setValue:nil forHTTPHeaderField:@"Referer"];
            self.redirected = YES;
            [self.client URLProtocol:self wasRedirectedToRequest:next redirectResponse:response];
        } else [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
    }
    [self.callbackLock unlock];
    return !self.redirected;
}
- (void)runTransfer {
    if (SHDWCurlStopped(self)) return;
    CURL *curl = engine.create();
    CURLcode result = curl ? engine.impersonate(curl, "safari184_ios", 1) : CURLE_OUT_OF_MEMORY;
    struct curl_slist *headers = NULL;
    NSData *body = self.request.HTTPBody ?: (self.request.HTTPBodyStream ?
        [NSURLProtocol propertyForKey:SHDWCurlBody inRequest:self.request] : nil);
    NSString *method = self.request.HTTPMethod ?: @"GET";
    if (curl && result == CURLE_OK) {
#define SHDW_CURL_SET(option, value) do { if (result == CURLE_OK) result = engine.set(curl, option, value); } while (0)
        SHDW_CURL_SET(CURLOPT_URL, self.request.URL.absoluteString.UTF8String);
        SHDW_CURL_SET(CURLOPT_FOLLOWLOCATION, 0L);
        SHDW_CURL_SET(CURLOPT_NOSIGNAL, 1L);
        SHDW_CURL_SET(CURLOPT_SSL_VERIFYPEER, 1L);
        SHDW_CURL_SET(CURLOPT_SSL_VERIFYHOST, 2L);
        SHDW_CURL_SET(CURLOPT_SUPPRESS_CONNECT_HEADERS, 1L);
        SHDW_CURL_SET(CURLOPT_ACCEPT_ENCODING, "gzip, deflate, br");
        double timeout = self.request.timeoutInterval;
        if (!isfinite(timeout) || timeout <= 0) timeout = 60;
        SHDW_CURL_SET(CURLOPT_TIMEOUT_MS, (long)MIN(timeout * 1000, (double)LONG_MAX));
        SHDW_CURL_SET(CURLOPT_WRITEFUNCTION, SHDWCurlWrite);
        SHDW_CURL_SET(CURLOPT_WRITEDATA, (__bridge void *)self);
        SHDW_CURL_SET(CURLOPT_HEADERFUNCTION, SHDWCurlHeader);
        SHDW_CURL_SET(CURLOPT_HEADERDATA, (__bridge void *)self);
        SHDW_CURL_SET(CURLOPT_XFERINFOFUNCTION, SHDWCurlProgress);
        SHDW_CURL_SET(CURLOPT_XFERINFODATA, (__bridge void *)self);
        SHDW_CURL_SET(CURLOPT_NOPROGRESS, 0L);
        if ([method isEqual:@"HEAD"]) SHDW_CURL_SET(CURLOPT_NOBODY, 1L);
        else if (body) {
            SHDW_CURL_SET(CURLOPT_POSTFIELDS, body.length ? body.bytes : "");
            SHDW_CURL_SET(CURLOPT_POSTFIELDSIZE_LARGE, (curl_off_t)body.length);
        } else if (self.request.HTTPBodyStream) result = CURLE_NOT_BUILT_IN;
        SHDW_CURL_SET(CURLOPT_CUSTOMREQUEST, method.UTF8String);
        NSMutableDictionary *values = [self.settings.HTTPAdditionalHeaders mutableCopy] ?: [NSMutableDictionary new];
        for (NSString *key in self.request.allHTTPHeaderFields) {
            for (NSString *old in values.allKeys) if ([old caseInsensitiveCompare:key] == NSOrderedSame) [values removeObjectForKey:old];
            values[key] = self.request.allHTTPHeaderFields[key];
        }
        if (self.request.HTTPShouldHandleCookies && self.settings.HTTPShouldSetCookies && !SHDWCurlHeaderValue(values,@"Cookie")) {
            NSArray *cookies = [self.settings.HTTPCookieStorage cookiesForURL:self.request.URL];
            [values addEntriesFromDictionary:[NSHTTPCookie requestHeaderFieldsWithCookies:cookies ?: @[]]];
        }
        for (NSString *name in values) {
            NSString *value = [values[name] description];
            if ([name rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound ||
                [value rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound) { result = CURLE_BAD_FUNCTION_ARGUMENT; break; }
            NSString *line = value.length ? [NSString stringWithFormat:@"%@: %@",name,value] : [name stringByAppendingString:@";"];
            struct curl_slist *next = engine.append(headers, line.UTF8String);
            if (!next) { result = CURLE_OUT_OF_MEMORY; break; } headers = next;
        }
        SHDW_CURL_SET(CURLOPT_HTTPHEADER, headers);
        NSDictionary *proxySettings = self.settings.connectionProxyDictionary;
        if (!proxySettings) proxySettings = CFBridgingRelease(CFNetworkCopySystemProxySettings());
        NSArray *proxies = CFBridgingRelease(CFNetworkCopyProxiesForURL((__bridge CFURLRef)self.request.URL, (__bridge CFDictionaryRef)proxySettings));
        NSDictionary *proxy = proxies.firstObject;
        NSString *type = proxy[(__bridge NSString *)kCFProxyTypeKey];
        if (!type || [type isEqual:(__bridge NSString *)kCFProxyTypeNone]) SHDW_CURL_SET(CURLOPT_PROXY, "");
        else if ([type isEqual:(__bridge NSString *)kCFProxyTypeHTTP] || [type isEqual:(__bridge NSString *)kCFProxyTypeHTTPS] || [type isEqual:(__bridge NSString *)kCFProxyTypeSOCKS]) {
            NSString *address = [NSString stringWithFormat:@"%@:%@",proxy[(__bridge NSString *)kCFProxyHostNameKey],proxy[(__bridge NSString *)kCFProxyPortNumberKey]];
            SHDW_CURL_SET(CURLOPT_PROXY, address.UTF8String);
            long proxyType = [type isEqual:(__bridge NSString *)kCFProxyTypeSOCKS] ? CURLPROXY_SOCKS5_HOSTNAME : CURLPROXY_HTTP;
            SHDW_CURL_SET(CURLOPT_PROXYTYPE, proxyType);
        } else result = CURLE_NOT_BUILT_IN;
        if (result == CURLE_OK) result = engine.perform(curl);
#undef SHDW_CURL_SET
    }
    if (headers) engine.freeHeaders(headers);
    if (curl) engine.destroy(curl);
    [self.callbackLock lock];
    if (!SHDWCurlStopped(self) && !self.redirected) {
        if (result == CURLE_OK) [self.client URLProtocolDidFinishLoading:self];
        else {
            NSInteger code = NSURLErrorNetworkConnectionLost;
            if (result == CURLE_OPERATION_TIMEDOUT) code = NSURLErrorTimedOut;
            else if (result == CURLE_COULDNT_RESOLVE_HOST) code = NSURLErrorCannotFindHost;
            else if (result == CURLE_COULDNT_CONNECT) code = NSURLErrorCannotConnectToHost;
            else if (result == CURLE_PEER_FAILED_VERIFICATION) code = NSURLErrorServerCertificateUntrusted;
            else if (result == CURLE_SSL_CONNECT_ERROR) code = NSURLErrorSecureConnectionFailed;
            else if (result == CURLE_NOT_BUILT_IN) code = NSURLErrorUnsupportedURL;
            NSError *error = [NSError errorWithDomain:NSURLErrorDomain code:code userInfo:@{
                NSLocalizedDescriptionKey:@(engine.error(result)), NSURLErrorFailingURLErrorKey:self.request.URL}];
            [self.client URLProtocol:self didFailWithError:error];
        }
    }
    [self.callbackLock unlock];
}
@end

void SHDWCurlTransportPrepare(void) {
    NSDictionary *configuration = SHDWFingerprintConfig(NSBundle.mainBundle.bundleIdentifier);
    if (![configuration[@"Network"][@"Transport"] isEqual:@"safari184_ios"]) return;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        void *image = dlopen(JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib").fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
        if (!image) return;
#define SHDW_CURL_SYMBOL(field, name) engine.field = dlsym(image, name); if (!engine.field) return
        SHDW_CURL_SYMBOL(initialize, "curl_global_init");
        SHDW_CURL_SYMBOL(create, "curl_easy_init");
        SHDW_CURL_SYMBOL(impersonate, "curl_easy_impersonate");
        SHDW_CURL_SYMBOL(set, "curl_easy_setopt");
        SHDW_CURL_SYMBOL(perform, "curl_easy_perform");
        SHDW_CURL_SYMBOL(destroy, "curl_easy_cleanup");
        SHDW_CURL_SYMBOL(append, "curl_slist_append");
        SHDW_CURL_SYMBOL(freeHeaders, "curl_slist_free_all");
        SHDW_CURL_SYMBOL(error, "curl_easy_strerror");
#undef SHDW_CURL_SYMBOL
        if (engine.initialize(CURL_GLOBAL_DEFAULT) != CURLE_OK) return;
        CURL *probe = engine.create(); if (!probe) return;
        BOOL available = engine.impersonate(probe, "safari184_ios", 0) == CURLE_OK;
        engine.destroy(probe);
        if (available) { __atomic_store_n(&transportReady, 1, __ATOMIC_RELEASE); [NSURLProtocol registerClass:SHDWSafari184Protocol.class]; }
    });
}
BOOL SHDWCurlTransportReady(void) { return __atomic_load_n(&transportReady, __ATOMIC_ACQUIRE) != 0; }
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) {
    if (!SHDWCurlTransportReady() || !configuration || configuration.identifier) return configuration;
    NSURLSessionConfiguration *copy = [configuration copy];
    NSMutableArray *protocols = [NSMutableArray arrayWithObject:SHDWSafari184Protocol.class];
    for (Class cls in configuration.protocolClasses) if (cls != SHDWSafari184Protocol.class) [protocols addObject:cls];
    copy.protocolClasses = protocols; return copy;
}
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session) {
    if (!SHDWCurlTransportReady() || !request || !session) return request;
    NSURLSessionConfiguration *configuration = session.configuration;
    id delegate = session.delegate;
    NSDictionary *ats = NSBundle.mainBundle.infoDictionary[@"NSAppTransportSecurity"];
    BOOL customTrust = [delegate respondsToSelector:@selector(URLSession:didReceiveChallenge:completionHandler:)] ||
        [delegate respondsToSelector:@selector(URLSession:task:didReceiveChallenge:completionHandler:)] || SHDWCurlRequiresNativeTrust(ats);
    if (configuration.identifier || customTrust ||
        (request.HTTPBodyStream && ![NSURLProtocol propertyForKey:SHDWCurlBody inRequest:request])) {
        if (![NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request]) return request;
        NSMutableURLRequest *copy = [request mutableCopy]; [NSURLProtocol removePropertyForKey:SHDWCurlContext inRequest:copy]; return copy;
    }
    if ([NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request]) {
        NSData *cachedBody = [NSURLProtocol propertyForKey:SHDWCurlBody inRequest:request];
        if ((request.HTTPBody && ![request.HTTPBody isEqual:cachedBody]) ||
            (!request.HTTPBody && !request.HTTPBodyStream && cachedBody)) {
            NSMutableURLRequest *copy = [request mutableCopy];
            if (request.HTTPBody) [NSURLProtocol setProperty:[request.HTTPBody copy] forKey:SHDWCurlBody inRequest:copy];
            else [NSURLProtocol removePropertyForKey:SHDWCurlBody inRequest:copy];
            return copy;
        }
        return request;
    }
    NSMutableURLRequest *copy = [request mutableCopy];
    [NSURLProtocol setProperty:[configuration copy] forKey:SHDWCurlContext inRequest:copy];
    if (request.HTTPBody) [NSURLProtocol setProperty:[request.HTTPBody copy] forKey:SHDWCurlBody inRequest:copy];
    return copy;
}
#else
void SHDWCurlTransportPrepare(void) {}
BOOL SHDWCurlTransportReady(void) { return NO; }
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) { return configuration; }
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session) { (void)session; return request; }
#endif
