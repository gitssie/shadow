#import "NetworkDiagnostics.h"
#include "DiagnosticsConfig.h"
#if SHDW_TRANSPORT_DIAGNOSTICS
#import "../ShadowCore.dylib/SHDWHookSession.h"
#import "CurlDiagnostics.h"
#import <objc/runtime.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

typedef struct SHDWNetworkObservation {
    const void *task;
    SEL selector;
    struct SHDWNetworkObservation *previous;
} SHDWNetworkObservation;
static _Thread_local SHDWNetworkObservation *activeObservation;
static char taskIdentifierKey, uploadBodyKey;

static BOOL SHDWNetworkNeedsStack(NSURLRequest *request) {
    NSString *path = request.URL.path;
    return [path isEqualToString:@"/interstitial"] || [path isEqualToString:@"/captcha"] ||
        [path isEqualToString:@"/captcha/"] || [path hasSuffix:@"/email_code"];
}

static NSDictionary *SHDWNetworkStack(void) {
    NSArray *symbols = NSThread.callStackSymbols;
    NSArray *addresses = NSThread.callStackReturnAddresses;
    return @{@"callStackSymbols":[symbols subarrayWithRange:NSMakeRange(0, MIN(symbols.count, 64))],
        @"callStackAddresses":[addresses subarrayWithRange:NSMakeRange(0, MIN(addresses.count, 64))]};
}

void SHDWNetworkDiagnosticsTraceRequestOrigin(NSURLRequest *request, NSString *stage) {
    int saved = errno;
    @try {
        if (SHDWCurlDiagnosticsEnabled() && SHDWNetworkNeedsStack(request))
            SHDWCurlTrace(stage, request, SHDWNetworkStack());
    } @catch (__unused NSException *exception) { }
    errno = saved;
}

void SHDWNetworkDiagnosticsTraceWebHTMLOrigin(NSString *html, NSURL *baseURL) {
    int saved = errno;
    @try {
        if (SHDWCurlDiagnosticsEnabled() && html.length &&
            ([html rangeOfString:@"captcha-delivery.com"].location != NSNotFound ||
             [html rangeOfString:@"/interstitial"].location != NSNotFound)) {
            NSMutableDictionary *details = [SHDWNetworkStack() mutableCopy];
            details[@"htmlLength"] = @(html.length);
            details[@"htmlTruncated"] = @(html.length > 32768);
            details[@"html"] = [html substringToIndex:MIN(html.length, 32768)];
            SHDWCurlTrace(@"webview.loadHTML.origin", baseURL ? [NSURLRequest requestWithURL:baseURL] : nil, details);
        }
    } @catch (__unused NSException *exception) { }
    errno = saved;
}

static void SHDWNetworkAttachUploadBody(NSURLSessionTask *task, NSDictionary *body, NSString *source) {
    if (!task) return;
    NSMutableDictionary *snapshot = [body mutableCopy]; snapshot[@"source"] = source;
    @synchronized(task) {
        objc_setAssociatedObject(task, &uploadBodyKey, [snapshot copy], OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }
}

void SHDWNetworkDiagnosticsAttachUploadData(NSURLSessionTask *task, NSData *data) {
    int saved = errno;
    @try { SHDWNetworkAttachUploadBody(task, SHDWCurlDiagnosticBody(data), @"upload-data-snapshot"); }
    @catch (__unused NSException *exception) { }
    errno = saved;
}

void SHDWNetworkDiagnosticsAttachUploadFile(NSURLSessionTask *task, NSURL *fileURL) {
    int saved = errno;
    @try {
        NSDictionary *snapshot;
        if (!fileURL.isFileURL) snapshot = SHDWCurlDiagnosticBodyPrefix(nil, nil, @"invalid-file-url");
        else {
            int file = open(fileURL.fileSystemRepresentation, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            if (file < 0) snapshot = SHDWCurlDiagnosticBodyPrefix(nil, nil, @"file-unreadable");
            else {
                @try {
                    struct stat info;
                    if (fstat(file, &info) != 0) snapshot = SHDWCurlDiagnosticBodyPrefix(nil, nil, @"file-read-failed");
                    else if (!S_ISREG(info.st_mode) || info.st_size < 0)
                        snapshot = SHDWCurlDiagnosticBodyPrefix(nil, nil, @"file-not-regular");
                    else {
                        NSUInteger wanted = (NSUInteger)MIN((uint64_t)info.st_size, (uint64_t)SHDW_CURL_DIAGNOSTIC_BODY_LIMIT);
                        NSMutableData *prefix = [NSMutableData dataWithLength:wanted];
                        NSUInteger captured = 0; BOOL failed = NO;
                        while (captured < wanted) {
                            ssize_t count = read(file, (char *)prefix.mutableBytes + captured, wanted - captured);
                            if (count < 0 && errno == EINTR) continue;
                            if (count <= 0) { failed = count < 0; break; }
                            captured += (NSUInteger)count;
                        }
                        prefix.length = captured;
                        snapshot = SHDWCurlDiagnosticBodyPrefix(prefix, @(info.st_size), failed ? @"file-read-failed" : @"available");
                    }
                } @finally { close(file); }
            }
        }
        SHDWNetworkAttachUploadBody(task, snapshot, @"upload-file-snapshot");
    } @catch (__unused NSException *exception) {
        SHDWNetworkAttachUploadBody(task, SHDWCurlDiagnosticBodyPrefix(nil, nil, @"file-read-failed"), @"upload-file-snapshot");
    }
    errno = saved;
}

static BOOL SHDWNetworkObservationIsNested(NSURLSessionTask *task, SEL selector) {
    for (SHDWNetworkObservation *entry = activeObservation; entry; entry = entry->previous)
        if (entry->task == (__bridge const void *)task && sel_isEqual(entry->selector, selector)) return YES;
    return NO;
}

// Optional metrics getters are checked before messaging older runtime snapshots.
static BOOL SHDWNetworkMetricGetter(id object, SEL selector, char type) {
    if (![object respondsToSelector:selector]) return NO;
    NSMethodSignature *signature = [object methodSignatureForSelector:selector];
    return signature.numberOfArguments == 2 && signature.methodReturnType[0] == type;
}

static NSDictionary *SHDWNetworkTransactionTimings(NSURLSessionTaskTransactionMetrics *transaction) {
    NSMutableDictionary *timings = [NSMutableDictionary new];
#define SHDW_METRIC_DATE(key, getter) do { \
    NSDate *date = SHDWNetworkMetricGetter(transaction, @selector(getter), '@') ? transaction.getter : nil; \
    timings[@key] = [date isKindOfClass:NSDate.class] ? @([date timeIntervalSince1970]) : (id)NSNull.null; \
} while (0)
    SHDW_METRIC_DATE("fetchStart", fetchStartDate);
    SHDW_METRIC_DATE("domainLookupStart", domainLookupStartDate);
    SHDW_METRIC_DATE("domainLookupEnd", domainLookupEndDate);
    SHDW_METRIC_DATE("connectStart", connectStartDate);
    SHDW_METRIC_DATE("connectEnd", connectEndDate);
    SHDW_METRIC_DATE("secureConnectionStart", secureConnectionStartDate);
    SHDW_METRIC_DATE("secureConnectionEnd", secureConnectionEndDate);
    SHDW_METRIC_DATE("requestStart", requestStartDate);
    SHDW_METRIC_DATE("requestEnd", requestEndDate);
    SHDW_METRIC_DATE("responseStart", responseStartDate);
    SHDW_METRIC_DATE("responseEnd", responseEndDate);
#undef SHDW_METRIC_DATE
    return timings;
}

static NSArray *SHDWNetworkErrorChain(NSError *error) {
    NSMutableArray *chain = [NSMutableArray new];
    // Include the outer error; cycles and deep underlying chains stay bounded.
    for (unsigned i = 0; i < 4 && [error isKindOfClass:NSError.class]; i++) {
        NSMutableDictionary *entry = [@{@"domain":error.domain, @"code":@(error.code)} mutableCopy];
        for (NSString *key in @[@"_kCFStreamErrorDomainKey", @"_kCFStreamErrorCodeKey"]) {
            id value = error.userInfo[key];
            if ([value isKindOfClass:NSNumber.class]) entry[key] = value;
        }
        [chain addObject:entry];
        id underlying = error.userInfo[NSUnderlyingErrorKey];
        error = [underlying isKindOfClass:NSError.class] ? underlying : nil;
    }
    return chain;
}

static void SHDWNetworkObserve(NSString *stage, NSURLSessionTask *task, NSURLResponse *response, NSNumber *state) {
    int saved = errno;
    @try {
        if (SHDWCurlDiagnosticsEnabled()) {
            NSString *identifier;
            @synchronized(task) {
                identifier = objc_getAssociatedObject(task, &taskIdentifierKey);
                if (!identifier) {
                    identifier = NSUUID.UUID.UUIDString;
                    objc_setAssociatedObject(task, &taskIdentifierKey, identifier, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
                }
            }
            NSURLRequest *request = task.currentRequest ?: task.originalRequest;
            NSMutableDictionary *details = [@{@"taskID": identifier,
                @"taskClass": NSStringFromClass(task.class), @"taskIdentifier": @(task.taskIdentifier),
                @"requestHeaders": request.allHTTPHeaderFields ?: @{},
                @"requestTimeoutInterval": @(request.timeoutInterval),
                @"bytesReceived": @(task.countOfBytesReceived), @"bytesSent": @(task.countOfBytesSent)} mutableCopy];
            details[@"currentRequestBody"] = SHDWCurlDiagnosticRequestBody(task.currentRequest);
            details[@"originalRequestBody"] = SHDWCurlDiagnosticRequestBody(task.originalRequest);
            @synchronized(task) {
                NSDictionary *upload = objc_getAssociatedObject(task, &uploadBodyKey);
                if (upload) details[@"uploadBody"] = upload;
            }
            if (state) details[@"state"] = state;
            if ([stage isEqualToString:@"task.complete"]) {
                SEL selector = NSSelectorFromString(@"_incompleteTaskMetrics");
                if ([task respondsToSelector:selector]) {
                    NSURLSessionTaskMetrics *metrics = ((id (*)(id, SEL))[task methodForSelector:selector])(task, selector);
                    if ([metrics isKindOfClass:NSURLSessionTaskMetrics.class]) {
                        NSMutableArray *transactions = [NSMutableArray new];
                        for (NSURLSessionTaskTransactionMetrics *transaction in metrics.transactionMetrics) {
                            NSURLRequest *transactionRequest = transaction.request;
                            NSDictionary *headers = transactionRequest.allHTTPHeaderFields ?: @{};
                            NSString *cookie = nil;
                            for (NSString *name in headers)
                                if ([name caseInsensitiveCompare:@"Cookie"] == NSOrderedSame) {
                                    cookie = headers[name]; break;
                                }
                            NSMutableDictionary *entry = [@{
                                @"fetchType":@(transaction.resourceFetchType),
                                @"protocol":transaction.networkProtocolName ?: @"",
                                @"url":transactionRequest.URL.absoluteString ?: @"",
                                @"method":transactionRequest.HTTPMethod ?: @"",
                                @"requestHeaders":headers,
                                @"headerSource":@"transaction-metrics",
                                @"cookieHeaderPresent":@(cookie != nil)
                            } mutableCopy];
                            entry[@"timings"] = SHDWNetworkTransactionTimings(transaction);
                            // These flags explain absent connection timings for a reused connection.
                            if (SHDWNetworkMetricGetter(transaction, @selector(isProxyConnection), @encode(BOOL)[0]))
                                entry[@"proxyConnection"] = @(transaction.isProxyConnection);
                            if (SHDWNetworkMetricGetter(transaction, @selector(isReusedConnection), @encode(BOOL)[0]))
                                entry[@"reusedConnection"] = @(transaction.isReusedConnection);
                            if (cookie) entry[@"cookieHeader"] = cookie;
                            if ([transaction.response isKindOfClass:NSHTTPURLResponse.class]) {
                                NSHTTPURLResponse *http = (NSHTTPURLResponse *)transaction.response;
                                entry[@"httpStatus"] = @(http.statusCode);
                                entry[@"responseHeaders"] = http.allHeaderFields ?: @{};
                            }
                            [transactions addObject:entry];
                            NSMutableDictionary *transactionDetails = [entry mutableCopy];
                            transactionDetails[@"taskID"] = identifier;
                            transactionDetails[@"transactionIndex"] = @(transactions.count - 1);
                            if (details[@"trace"]) transactionDetails[@"trace"] = details[@"trace"];
                            // Metrics expose a system request snapshot, not raw wire bytes.
                            SHDWCurlTrace(@"task.transaction", transactionRequest, transactionDetails);
                        }
                        details[@"transactions"] = transactions;
                    }
                }
            }
            NSURLResponse *observed = response ?: task.response;
            if (SHDWNetworkNeedsStack(request) &&
                ([stage isEqualToString:@"task.resume"] || [stage isEqualToString:@"task.response"]))
                [details addEntriesFromDictionary:SHDWNetworkStack()];
            if ([observed isKindOfClass:NSHTTPURLResponse.class]) {
                details[@"httpStatus"] = @([(NSHTTPURLResponse *)observed statusCode]);
                details[@"responseHeaders"] = [(NSHTTPURLResponse *)observed allHeaderFields] ?: @{};
            }
            NSError *error = task.error;
            if (error) {
                details[@"errorDomain"] = error.domain; details[@"errorCode"] = @(error.code);
                details[@"errorChain"] = SHDWNetworkErrorChain(error);
            }
            SHDWCurlTrace(stage, request, details);
        }
    } @catch (__unused NSException *exception) {
    }
    errno = saved;
}

typedef struct { IMP original; SEL selector; } SHDWNetworkTaskHook;

static BOOL SHDWNetworkDeclaredMethod(Class cls, SEL selector) {
    unsigned count = 0;
    Method *methods = class_copyMethodList(cls, &count);
    Method found = NULL;
    for (unsigned i = 0; i < count; i++)
        if (sel_isEqual(method_getName(methods[i]), selector)) { found = methods[i]; break; }
    free(methods);
    if (!found) return NO;
    char *result = method_copyReturnType(found);
    BOOL valid = result && !strcmp(result, "v");
    free(result);
    BOOL resume = sel_isEqual(selector, @selector(resume));
    if (method_getNumberOfArguments(found) != (resume ? 2u : 3u)) return NO;
    if (!resume) {
        char *argument = method_copyArgumentType(found, 2);
        valid &= argument && (sel_isEqual(selector, NSSelectorFromString(@"setResponse:")) ? argument[0] == '@' : !strcmp(argument, @encode(NSInteger)));
        free(argument);
    }
    return valid;
}

static BOOL SHDWNetworkInstallMethod(SHDWHookSession *hooks, Class cls, SEL selector) {
    if (!SHDWNetworkDeclaredMethod(cls, selector)) return NO;
    SHDWNetworkTaskHook *hook = calloc(1, sizeof(*hook));
    if (!hook) return NO;
    hook->selector = selector;
    id replacement;
    if (sel_isEqual(selector, @selector(resume))) {
        replacement = ^(NSURLSessionTask *task) {
            BOOL nested = SHDWNetworkObservationIsNested(task, hook->selector);
            SHDWNetworkObservation observation = {(__bridge const void *)task, hook->selector, activeObservation};
            activeObservation = &observation;
            @try {
                if (!nested) SHDWNetworkObserve(@"task.resume", task, nil, nil);
                ((void (*)(id, SEL))hook->original)(task, hook->selector);
            } @finally { activeObservation = observation.previous; }
        };
    } else if (sel_isEqual(selector, NSSelectorFromString(@"setResponse:"))) {
        replacement = ^(NSURLSessionTask *task, NSURLResponse *response) {
            BOOL nested = SHDWNetworkObservationIsNested(task, hook->selector);
            SHDWNetworkObservation observation = {(__bridge const void *)task, hook->selector, activeObservation};
            activeObservation = &observation;
            @try {
                ((void (*)(id, SEL, id))hook->original)(task, hook->selector, response);
                if (!nested) SHDWNetworkObserve(@"task.response", task, response, nil);
            } @finally { activeObservation = observation.previous; }
        };
    } else {
        replacement = ^(NSURLSessionTask *task, NSInteger state) {
            BOOL nested = SHDWNetworkObservationIsNested(task, hook->selector);
            SHDWNetworkObservation observation = {(__bridge const void *)task, hook->selector, activeObservation};
            activeObservation = &observation;
            @try {
                ((void (*)(id, SEL, NSInteger))hook->original)(task, hook->selector, state);
                if (!nested) SHDWNetworkObserve(state == NSURLSessionTaskStateCompleted ? @"task.complete" : @"task.state", task, nil, @(state));
            } @finally { activeObservation = observation.previous; }
        };
    }
    IMP implementation = imp_implementationWithBlock(replacement);
    return [hooks hookMessageInClass:cls withSelector:selector withReplacement:(void *)implementation outOldPtr:(void **)&hook->original];
}

void SHDWNetworkDiagnosticsInstall(SHDWHookSession *hooks) {
    int saved = errno;
    if (!hooks) { errno = saved; return; }
    @synchronized(NSURLSessionTask.class) {
        static NSMutableSet<NSString *> *installed;
        if (!installed) installed = [NSMutableSet new];
        unsigned count = 0;
        Class *classes = objc_copyClassList(&count);
        for (unsigned i = 0; i < count; i++) {
            Class cls = classes[i], parent = cls;
            while (parent && parent != NSURLSessionTask.class) parent = class_getSuperclass(parent);
            if (!parent) continue;
            for (NSString *name in @[@"resume", @"setResponse:", @"setState:"]) {
                SEL selector = NSSelectorFromString(name);
                NSString *key = [NSStringFromClass(cls) stringByAppendingFormat:@"/%@", name];
                if ([installed containsObject:key]) continue;
                if (SHDWNetworkInstallMethod(hooks, cls, selector)) [installed addObject:key];
            }
        }
        free(classes);
    }
    errno = saved;
}

#else
void SHDWNetworkDiagnosticsInstall(SHDWHookSession *hooks) { (void)hooks; }
void SHDWNetworkDiagnosticsTraceRequestOrigin(NSURLRequest *request, NSString *stage) { (void)request; (void)stage; }
void SHDWNetworkDiagnosticsTraceWebHTMLOrigin(NSString *html, NSURL *url) { (void)html; (void)url; }
void SHDWNetworkDiagnosticsAttachUploadData(NSURLSessionTask *task, NSData *data) { (void)task; (void)data; }
void SHDWNetworkDiagnosticsAttachUploadFile(NSURLSessionTask *task, NSURL *url) { (void)task; (void)url; }
#endif
