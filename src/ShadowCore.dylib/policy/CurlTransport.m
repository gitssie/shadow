#import "CurlTransport.h"
#import "../../Transport/Profiles.h"
#import <Shadow/JBPath.h>

#if SHADOW_CURL_IMPERSONATE
#import <CFNetwork/CFNetwork.h>
#import "../../Transport/CurlTrust.h"
#include <curl/curl.h>
#include "../../Transport/CurlReference.h"
#include <dlfcn.h>
#include <math.h>
#include <limits.h>
#include <stdint.h>

static NSString *const SHDWCurlContext = @"me.jjolano.shadow.transport.configuration";
static NSString *const SHDWCurlBody = @"me.jjolano.shadow.transport.body";
static NSString *const SHDWCurlTrustContext = @"me.jjolano.shadow.transport.webkit-trust";
static NSString *const SHDWCurlSessionContext = @"me.jjolano.shadow.transport.session";
static unsigned transportReady;
static NSString *transportProfile;
static struct {
    CURLcode (*initialize)(long);
    CURL *(*create)(void);
    CURLcode (*impersonate)(CURL *, const char *, int);
    CURLcode (*set)(CURL *, CURLoption, ...);
    CURLcode (*perform)(CURL *);
    CURLcode (*info)(CURL *, CURLINFO, ...);
    void (*destroy)(CURL *);
    struct curl_slist *(*append)(struct curl_slist *, const char *);
    void (*freeHeaders)(struct curl_slist *);
    const char *(*error)(CURLcode);
} engine;

@interface SHDWCurlSessionReference : NSObject
@property(nonatomic, weak) NSURLSession *session;
@property(nonatomic, weak) NSURLSessionTask *task;
@end
@implementation SHDWCurlSessionReference @end

@interface SHDWSafari184Protocol : NSURLProtocol
@property(nonatomic, strong) NSRecursiveLock *callbackLock;
@property(atomic) BOOL stopped;
@property(nonatomic) BOOL redirected;
@property(nonatomic) BOOL responseDelivered;
@property(nonatomic) NSInteger status;
@property(nonatomic, strong) NSMutableDictionary *responseHeaders;
@property(nonatomic, strong) NSMutableArray *cookieLines;
@property(nonatomic, strong) NSURLSessionConfiguration *settings;
@property(nonatomic) CURL *transfer;
@property(nonatomic) BOOL trustChecked;
@property(nonatomic) BOOL trustRejected;
@property(nonatomic) BOOL trustCancelled;
@property(nonatomic, copy) NSString *trustFailureReason;
- (BOOL)deliverHeaders;
- (void)runTransfer;
- (BOOL)approveTrust;
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

static int SHDWCurlPrerequisite(void *context, char *remote, char *local, int remotePort, int localPort) {
    (void)remote; (void)local; (void)remotePort; (void)localPort;
    SHDWSafari184Protocol *protocol = (__bridge id)context;
    return !SHDWCurlStopped(protocol) && [protocol approveTrust] ? CURL_PREREQFUNC_OK : CURL_PREREQFUNC_ABORT;
}

static id SHDWCurlHeaderValue(NSDictionary *headers, NSString *name) {
    for (NSString *key in headers) if ([key caseInsensitiveCompare:name] == NSOrderedSame) return headers[key];
    return nil;
}

static NSString *SHDWCurlResponseHTTPVersion(CURL *transfer) {
    long version = CURL_HTTP_VERSION_NONE;
    if (!transfer || engine.info(transfer, CURLINFO_HTTP_VERSION, &version) != CURLE_OK) return nil;
    switch (version) {
        case CURL_HTTP_VERSION_1_0: return @"HTTP/1.0";
        case CURL_HTTP_VERSION_1_1: return @"HTTP/1.1";
        case CURL_HTTP_VERSION_2_0: return @"HTTP/2";
        case CURL_HTTP_VERSION_3: return @"HTTP/3";
        default: return nil;
    }
}

static BOOL SHDWCurlHeaderFieldsContain(NSArray<NSArray *> *fields, NSString *name) {
    for (NSArray *field in fields)
        if ([field[0] isKindOfClass:NSString.class] && [field[0] caseInsensitiveCompare:name] == NSOrderedSame) return YES;
    return NO;
}

static NSMutableArray<NSArray *> *SHDWCurlRequestHeaderFields(NSURLRequest *request) {
    NSMutableArray<NSArray *> *fields = [NSMutableArray new];
    // Preserve the source enumeration; dictionary APIs do not promise wire order.
    NSDictionary *requestFields = request.allHTTPHeaderFields;
    for (id name in requestFields) [fields addObject:@[name, requestFields[name]]];
    return fields;
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
        if ([key isEqual:@"NSPinnedDomains"] && (![value isKindOfClass:NSDictionary.class] || [value count])) return YES;
        if (([key isEqual:@"NSRequiresCertificateTransparency"] || [key hasSuffix:@"RequiresForwardSecrecy"]) &&
            [value respondsToSelector:@selector(boolValue)] && [value boolValue]) return YES;
        if ([key hasSuffix:@"MinimumTLSVersion"] && [value isKindOfClass:NSString.class] &&
            [value compare:@"TLSv1.0" options:NSNumericSearch] == NSOrderedDescending) return YES;
        if ([value isKindOfClass:NSDictionary.class] && SHDWCurlRequiresNativeTrust(value)) return YES;
    }
    return NO;
}

BOOL SHDWCurlTransportSupportsWebKitPolicy(NSDictionary *policy) {
    return ([policy[@"NSAllowsArbitraryLoadsInWebContent"] boolValue] || [policy[@"NSAllowsArbitraryLoads"] boolValue]) &&
        !SHDWCurlRequiresNativeTrust(policy);
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
- (BOOL)approveTrust {
    if (![NSURLProtocol propertyForKey:SHDWCurlTrustContext inRequest:self.request]) return YES;
    if (self.trustChecked) return !self.trustRejected;
    self.trustChecked = YES;
    struct curl_certinfo *info = NULL;
    NSMutableArray<NSData *> *certificates = [NSMutableArray new];
    if (engine.info && engine.info(self.transfer, CURLINFO_CERTINFO, &info) == CURLE_OK && info) {
        for (int index = 0; index < info->num_of_certs; index++) {
            for (struct curl_slist *field = info->certinfo[index]; field; field = field->next) {
                if (strncmp(field->data, "Cert:", 5)) continue;
                NSString *pem = @(field->data + 5);
                pem = [pem stringByReplacingOccurrencesOfString:@"-----BEGIN CERTIFICATE-----" withString:@""];
                pem = [pem stringByReplacingOccurrencesOfString:@"-----END CERTIFICATE-----" withString:@""];
                NSData *der = [[NSData alloc] initWithBase64EncodedString:pem options:NSDataBase64DecodingIgnoreUnknownCharacters];
                if (der.length) [certificates addObject:der];
            }
        }
    }
    __block BOOL challengeActive = YES, challengeSent = NO, delegateInvoked = NO, missingTask = NO;
    __block NSInteger dispositionObserved = -1;
    BOOL accepted = SHDWCurlEvaluateTrust(certificates, self.request.URL.host, self.request.URL.port.integerValue ?: 443,
        MIN(self.request.timeoutInterval > 0 ? self.request.timeoutInterval : 60, 60),
        ^(NSURLAuthenticationChallenge *challenge) {
            challengeSent = YES;
            SHDWCurlSessionReference *reference = [NSURLProtocol propertyForKey:SHDWCurlSessionContext inRequest:self.request];
            NSURLSession *session = reference.session;
            NSURLSessionTask *task = reference.task;
            if (!session || !task) { missingTask = YES; [challenge.sender cancelAuthenticationChallenge:challenge]; return; }
            [session.delegateQueue addOperationWithBlock:^{
                [self.callbackLock lock];
                if (!challengeActive || SHDWCurlStopped(self)) [challenge.sender cancelAuthenticationChallenge:challenge];
                else {
                    delegateInvoked = YES;
                    void (^complete)(NSURLSessionAuthChallengeDisposition, NSURLCredential *) =
                        ^(NSURLSessionAuthChallengeDisposition disposition, NSURLCredential *credential) {
                            [self.callbackLock lock];
                            dispositionObserved = disposition;
                            [self.callbackLock unlock];
                            if (disposition == NSURLSessionAuthChallengeUseCredential) [challenge.sender useCredential:credential forAuthenticationChallenge:challenge];
                            else if (disposition == NSURLSessionAuthChallengePerformDefaultHandling) [challenge.sender performDefaultHandlingForAuthenticationChallenge:challenge];
                            else if (disposition == NSURLSessionAuthChallengeRejectProtectionSpace) [challenge.sender rejectProtectionSpaceAndContinueWithChallenge:challenge];
                            else [challenge.sender cancelAuthenticationChallenge:challenge];
                        };
                    id<NSURLSessionTaskDelegate> delegate = (id)session.delegate;
                    if ([delegate respondsToSelector:@selector(URLSession:didReceiveChallenge:completionHandler:)])
                        [delegate URLSession:session didReceiveChallenge:challenge completionHandler:complete];
                    else if ([delegate respondsToSelector:@selector(URLSession:task:didReceiveChallenge:completionHandler:)])
                        [delegate URLSession:session task:task didReceiveChallenge:challenge completionHandler:complete];
                    else [challenge.sender performDefaultHandlingForAuthenticationChallenge:challenge];
                }
                [self.callbackLock unlock];
            }];
        }, ^BOOL { return SHDWCurlStopped(self); });
    [self.callbackLock lock];
    challengeActive = NO;
    self.trustCancelled = dispositionObserved == NSURLSessionAuthChallengeCancelAuthenticationChallenge;
    if (!accepted) {
        if (!certificates.count) self.trustFailureReason = @"TLS peer certificate information is unavailable";
        else if (!challengeSent) self.trustFailureReason = @"System certificate validation failed";
        else if (self.trustCancelled) self.trustFailureReason = @"Authentication was cancelled";
        else if (missingTask) self.trustFailureReason = @"The original session or task is unavailable for authentication";
        else if (!delegateInvoked) self.trustFailureReason = @"The authentication delegate queue timed out";
        else if (dispositionObserved < 0) self.trustFailureReason = @"The authentication delegate did not complete its challenge";
        else self.trustFailureReason = [NSString stringWithFormat:@"The authentication delegate rejected the certificate (disposition %ld)", (long)dispositionObserved];
    }
    [self.callbackLock unlock];
    self.trustRejected = !accepted;
    return accepted;
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
    NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL statusCode:self.status HTTPVersion:SHDWCurlResponseHTTPVersion(self.transfer) headerFields:self.responseHeaders];
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
    self.transfer = curl;
    CURLcode result = curl ? SHDWCurlApplyProfile(curl, transportProfile.UTF8String, engine.impersonate, engine.set) : CURLE_OUT_OF_MEMORY;
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
        if ([NSURLProtocol propertyForKey:SHDWCurlTrustContext inRequest:self.request]) {
            SHDW_CURL_SET(CURLOPT_CERTINFO, 1L);
            SHDW_CURL_SET(CURLOPT_PREREQFUNCTION, SHDWCurlPrerequisite);
            SHDW_CURL_SET(CURLOPT_PREREQDATA, (__bridge void *)self);
        }
        SHDW_CURL_SET(CURLOPT_SUPPRESS_CONNECT_HEADERS, 1L);
        SHDW_CURL_SET(CURLOPT_ACCEPT_ENCODING, "");
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
        NSMutableArray<NSArray *> *fields = SHDWCurlRequestHeaderFields(self.request);
        for (NSArray *field in fields) {
            id name = field[0];
            NSString *value = [field[1] description];
            if (![name isKindOfClass:NSString.class] || ![name length] ||
                [name rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound ||
                [value rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound) { result = CURLE_BAD_FUNCTION_ARGUMENT; break; }
            NSString *line = value.length ? [NSString stringWithFormat:@"%@: %@",name,value] : [name stringByAppendingString:@";"];
            struct curl_slist *next = engine.append(headers, line.UTF8String);
            if (!next) { result = CURLE_OUT_OF_MEMORY; break; } headers = next;
        }
        for (NSString *name in @[@"Accept", @"Accept-Encoding", @"Content-Type"]) {
            if (SHDWCurlHeaderFieldsContain(fields, name)) continue;
            struct curl_slist *next = engine.append(headers, [name stringByAppendingString:@":"].UTF8String);
            if (!next) { result = CURLE_OUT_OF_MEMORY; break; }
            headers = next;
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
    self.transfer = NULL;
    [self.callbackLock lock];
    if (!SHDWCurlStopped(self) && !self.redirected) {
        if (result == CURLE_OK) [self.client URLProtocolDidFinishLoading:self];
        else {
            NSInteger code = NSURLErrorNetworkConnectionLost;
            if (self.trustCancelled) code = NSURLErrorCancelled;
            else if (self.trustRejected) code = NSURLErrorServerCertificateUntrusted;
            else if (result == CURLE_OPERATION_TIMEDOUT) code = NSURLErrorTimedOut;
            else if (result == CURLE_COULDNT_RESOLVE_HOST) code = NSURLErrorCannotFindHost;
            else if (result == CURLE_COULDNT_CONNECT) code = NSURLErrorCannotConnectToHost;
            else if (result == CURLE_PEER_FAILED_VERIFICATION) code = NSURLErrorServerCertificateUntrusted;
            else if (result == CURLE_SSL_CONNECT_ERROR) code = NSURLErrorSecureConnectionFailed;
            else if (result == CURLE_NOT_BUILT_IN) code = NSURLErrorUnsupportedURL;
            NSError *error = [NSError errorWithDomain:NSURLErrorDomain code:code userInfo:@{
                NSLocalizedDescriptionKey:self.trustFailureReason ?: @(engine.error(result)), NSURLErrorFailingURLErrorKey:self.request.URL}];
            [self.client URLProtocol:self didFailWithError:error];
        }
    }
    [self.callbackLock unlock];
}
@end

void SHDWCurlTransportPrepareProfile(NSString *profile) {
    if (!SHDWTransportProfileIsSupported(profile)) return;
    NSString *selectedProfile = [profile copy];
    if (!SHDWTransportProfileIsSupported(selectedProfile)) return;
    static unsigned attempted;
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&attempted, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    transportProfile = selectedProfile;
    void *image = dlopen(JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib").fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
    if (!image) return;
#define SHDW_CURL_SYMBOL(field, name) engine.field = dlsym(image, name); if (!engine.field) return
    SHDW_CURL_SYMBOL(initialize, "curl_global_init");
    SHDW_CURL_SYMBOL(create, "curl_easy_init");
    SHDW_CURL_SYMBOL(impersonate, "curl_easy_impersonate");
    SHDW_CURL_SYMBOL(set, "curl_easy_setopt");
    SHDW_CURL_SYMBOL(perform, "curl_easy_perform");
    SHDW_CURL_SYMBOL(info, "curl_easy_getinfo");
    SHDW_CURL_SYMBOL(destroy, "curl_easy_cleanup");
    SHDW_CURL_SYMBOL(append, "curl_slist_append");
    SHDW_CURL_SYMBOL(freeHeaders, "curl_slist_free_all");
    SHDW_CURL_SYMBOL(error, "curl_easy_strerror");
#undef SHDW_CURL_SYMBOL
    if (engine.initialize(CURL_GLOBAL_DEFAULT) != CURLE_OK) return;
    CURL *probe = engine.create(); if (!probe) return;
    BOOL available = SHDWCurlApplyProfile(probe, transportProfile.UTF8String, engine.impersonate, engine.set) == CURLE_OK;
    engine.destroy(probe);
    if (available) { __atomic_store_n(&transportReady, 1, __ATOMIC_RELEASE); [NSURLProtocol registerClass:SHDWSafari184Protocol.class]; }
}
BOOL SHDWCurlTransportReady(void) { return __atomic_load_n(&transportReady, __ATOMIC_ACQUIRE) != 0; }
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) {
    if (!SHDWCurlTransportReady() || !configuration || configuration.identifier) return configuration;
    NSURLSessionConfiguration *copy = [configuration copy];
    NSMutableArray *protocols = [NSMutableArray arrayWithObject:SHDWSafari184Protocol.class];
    for (Class cls in configuration.protocolClasses) if (cls != SHDWSafari184Protocol.class) [protocols addObject:cls];
    copy.protocolClasses = protocols; return copy;
}
static NSURLRequest *SHDWCurlPrepareRequest(NSURLRequest *request, NSURLSession *session, BOOL webKit) {
    if (!SHDWCurlTransportReady() || !request || !session) return request;
    NSURLSessionConfiguration *configuration = session.configuration;
    id delegate = session.delegate;
    NSDictionary *ats = NSBundle.mainBundle.infoDictionary[@"NSAppTransportSecurity"];
    BOOL customTrust = (!webKit && ([delegate respondsToSelector:@selector(URLSession:didReceiveChallenge:completionHandler:)] ||
        [delegate respondsToSelector:@selector(URLSession:task:didReceiveChallenge:completionHandler:)])) || SHDWCurlRequiresNativeTrust(ats);
    if (configuration.identifier || customTrust ||
        (request.HTTPBodyStream && ![NSURLProtocol propertyForKey:SHDWCurlBody inRequest:request])) {
        if (![NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request]) return request;
        NSMutableURLRequest *copy = [request mutableCopy]; [NSURLProtocol removePropertyForKey:SHDWCurlContext inRequest:copy]; return copy;
    }
    if ([NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request]) {
        NSData *cachedBody = [NSURLProtocol propertyForKey:SHDWCurlBody inRequest:request];
        SHDWCurlSessionReference *reference = [NSURLProtocol propertyForKey:SHDWCurlSessionContext inRequest:request];
        if ((request.HTTPBody && ![request.HTTPBody isEqual:cachedBody]) ||
            (!request.HTTPBody && !request.HTTPBodyStream && cachedBody) ||
            (webKit && (reference.session != session || reference.task != nil))) {
            NSMutableURLRequest *copy = [request mutableCopy];
            if (request.HTTPBody) [NSURLProtocol setProperty:[request.HTTPBody copy] forKey:SHDWCurlBody inRequest:copy];
            else if (!request.HTTPBodyStream) [NSURLProtocol removePropertyForKey:SHDWCurlBody inRequest:copy];
            if (webKit) {
                SHDWCurlSessionReference *updated = [SHDWCurlSessionReference new]; updated.session = session;
                [NSURLProtocol setProperty:@YES forKey:SHDWCurlTrustContext inRequest:copy];
                [NSURLProtocol setProperty:updated forKey:SHDWCurlSessionContext inRequest:copy];
            }
            return copy;
        }
        return request;
    }
    NSMutableURLRequest *copy = [request mutableCopy];
    [NSURLProtocol setProperty:[configuration copy] forKey:SHDWCurlContext inRequest:copy];
    if (webKit) {
        [NSURLProtocol setProperty:@YES forKey:SHDWCurlTrustContext inRequest:copy];
        SHDWCurlSessionReference *reference = [SHDWCurlSessionReference new]; reference.session = session;
        [NSURLProtocol setProperty:reference forKey:SHDWCurlSessionContext inRequest:copy];
    }
    if (request.HTTPBody) [NSURLProtocol setProperty:[request.HTTPBody copy] forKey:SHDWCurlBody inRequest:copy];
    return copy;
}
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session) {
    return SHDWCurlPrepareRequest(request, session, NO);
}
NSURLRequest *SHDWCurlTransportWebKitRequest(NSURLRequest *request, NSURLSession *session) {
    return SHDWCurlPrepareRequest(request, session, YES);
}
void SHDWCurlTransportAttachTask(NSURLRequest *request, NSURLSessionTask *task) {
    SHDWCurlSessionReference *reference = [NSURLProtocol propertyForKey:SHDWCurlSessionContext inRequest:request];
    reference.task = task;
}
#else
void SHDWCurlTransportPrepareProfile(NSString *profile) { (void)profile; }
BOOL SHDWCurlTransportReady(void) { return NO; }
BOOL SHDWCurlTransportSupportsWebKitPolicy(NSDictionary *policy) { (void)policy; return NO; }
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) { return configuration; }
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session) { (void)session; return request; }
NSURLRequest *SHDWCurlTransportWebKitRequest(NSURLRequest *request, NSURLSession *session) { (void)session; return request; }
void SHDWCurlTransportAttachTask(NSURLRequest *request, NSURLSessionTask *task) { (void)request; (void)task; }
#endif
