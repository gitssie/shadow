#pragma once
#include "DiagnosticsConfig.h"
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <time.h>
#include <unistd.h>

#ifndef SHDW_CURL_DIAGNOSTICS_PORT
#define SHDW_CURL_DIAGNOSTICS_PORT 17866
#endif

#ifndef SHDW_CURL_DIAGNOSTIC_BODY_LIMIT
#define SHDW_CURL_DIAGNOSTIC_BODY_LIMIT (32 * 1024)
#endif

static __thread unsigned SHDWCurlDiagnosticDepth;

static BOOL SHDWCurlDiagnosticsEnabled(void) {
    return SHDW_TRANSPORT_DIAGNOSTICS && SHDWCurlDiagnosticDepth == 0;
}

static NSString *SHDWCurlDiagnosticString(NSString *value, NSUInteger limit) {
    return value.length > limit ? [value substringToIndex:limit] : value;
}

static NSDictionary *SHDWCurlDiagnosticBodyPrefix(NSData *data, NSNumber *byteLength, NSString *availability) {
    int saved = errno;
    @try {
        NSUInteger count = MIN(data.length, (NSUInteger)SHDW_CURL_DIAGNOSTIC_BODY_LIMIT);
        NSData *prefix = count == data.length ? data : [data subdataWithRange:NSMakeRange(0, count)];
        return @{@"availability":availability, @"encoding":@"base64",
            @"byteLength":byteLength ?: (id)NSNull.null, @"capturedByteLength":@(count),
            @"truncated":@(byteLength && byteLength.unsignedLongLongValue > count),
            @"base64":[prefix base64EncodedStringWithOptions:0] ?: @""};
    } @finally { errno = saved; }
}

static NSDictionary *SHDWCurlDiagnosticBody(NSData *data) {
    return SHDWCurlDiagnosticBodyPrefix(data, data ? @(data.length) : nil, data ? @"available" : @"unavailable");
}

static NSDictionary *SHDWCurlDiagnosticRequestBody(NSURLRequest *request) {
    int saved = errno;
    @try {
        NSData *body = request.HTTPBody;
        if (body) return SHDWCurlDiagnosticBody(body);
        return SHDWCurlDiagnosticBodyPrefix(nil, nil, request.HTTPBodyStream ? @"stream-not-read" : @"not-present");
    } @finally { errno = saved; }
}

static id SHDWCurlDiagnosticJSONValue(id value, unsigned depth) {
    if (depth > 8) return nil;
    if ([value isKindOfClass:NSString.class]) return SHDWCurlDiagnosticString(value, 128 * 1024);
    if ([value isKindOfClass:NSNumber.class] || value == NSNull.null) return value;
    if ([value isKindOfClass:NSArray.class]) {
        NSMutableArray *copy = [NSMutableArray new];
        for (id element in value) {
            if (copy.count == 512) break;
            id item = SHDWCurlDiagnosticJSONValue(element, depth + 1);
            if (item) [copy addObject:item];
        }
        return copy;
    }
    if ([value isKindOfClass:NSDictionary.class]) {
        NSMutableDictionary *copy = [NSMutableDictionary new];
        for (id key in value) {
            if (copy.count == 512) break;
            if (![key isKindOfClass:NSString.class] || [key length] > 1024) continue;
            id item = SHDWCurlDiagnosticJSONValue(value[key], depth + 1);
            if (item) copy[key] = item;
        }
        return copy;
    }
    return nil;
}

static int64_t SHDWCurlDiagnosticMilliseconds(void) {
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value) != 0) return -1;
    return (int64_t)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}

static BOOL SHDWCurlDiagnosticWritable(int socket, int64_t deadline) {
    for (;;) {
        int64_t now = SHDWCurlDiagnosticMilliseconds();
        if (now < 0 || now >= deadline) return NO;
        struct pollfd descriptor = { .fd = socket, .events = POLLOUT };
        int status = poll(&descriptor, 1, (int)(deadline - now));
        if (status < 0 && errno == EINTR) continue;
        return status > 0 && (descriptor.revents & POLLOUT) &&
            !(descriptor.revents & (POLLERR | POLLHUP | POLLNVAL));
    }
}

static void SHDWCurlDiagnosticSend(NSData *line) {
    int64_t start = SHDWCurlDiagnosticMilliseconds();
    if (start < 0) return;
    int stream = socket(AF_INET, SOCK_STREAM, 0);
    if (stream < 0) return;
    int flags = fcntl(stream, F_GETFL, 0), noSignal = 1;
    if (flags < 0 || fcntl(stream, F_SETFL, flags | O_NONBLOCK) != 0 ||
        setsockopt(stream, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, sizeof(noSignal)) != 0) { close(stream); return; }
    struct sockaddr_in address = { .sin_len = sizeof(address), .sin_family = AF_INET,
        .sin_port = htons(SHDW_CURL_DIAGNOSTICS_PORT), .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
    int status = connect(stream, (struct sockaddr *)&address, sizeof(address));
    if (status != 0) {
        if (errno != EINPROGRESS || !SHDWCurlDiagnosticWritable(stream, start + 250)) { close(stream); return; }
        int error = 0; socklen_t length = sizeof(error);
        if (getsockopt(stream, SOL_SOCKET, SO_ERROR, &error, &length) != 0 || error) { close(stream); return; }
    }
    const char *bytes = line.bytes; NSUInteger remaining = line.length;
    while (remaining && SHDWCurlDiagnosticMilliseconds() < start + 1000) {
        ssize_t sent = send(stream, bytes, remaining, 0);
        if (sent > 0) { remaining -= (NSUInteger)sent; bytes += sent; continue; }
        if (sent < 0 && errno == EINTR) continue;
        if (sent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) &&
            SHDWCurlDiagnosticWritable(stream, start + 1000)) continue;
        break;
    }
    close(stream);
}

static void SHDWCurlTraceImpl(NSString *stage, NSURLRequest *request, NSDictionary *details) {
    int saved = errno;
    if (!SHDWCurlDiagnosticsEnabled()) { errno = saved; return; }
    SHDWCurlDiagnosticDepth++;
    @try {
        NSURL *url = request.URL;
        NSURLComponents *components = url ? [NSURLComponents componentsWithURL:url resolvingAgainstBaseURL:NO] : nil;
        components.user = nil; components.password = nil;
        NSMutableDictionary *record = [@{
            @"epoch": @([NSDate.date timeIntervalSince1970]), @"pid": @(getpid()),
            @"stage": SHDWCurlDiagnosticString(stage ?: @"", 96),
            @"method": request.HTTPMethod ?: @"GET", @"url": components.string ?: @"",
            @"scheme": url.scheme ?: @"", @"host": url.host ?: @"", @"path": url.path ?: @"",
            @"requestHeaders": SHDWCurlDiagnosticJSONValue(request.allHTTPHeaderFields ?: @{}, 0),
            @"requestBody": SHDWCurlDiagnosticRequestBody(request)
        } mutableCopy];
        id safeDetails = SHDWCurlDiagnosticJSONValue(details, 0);
        if (safeDetails) record[@"details"] = safeDetails;
        NSData *json = [NSJSONSerialization isValidJSONObject:record] ?
            [NSJSONSerialization dataWithJSONObject:record options:0 error:NULL] : nil;
        if (!json || json.length >= 256 * 1024) return;
        NSMutableData *line = [json mutableCopy]; [line appendBytes:"\n" length:1];
        static dispatch_queue_t queue;
        static dispatch_once_t once;
        dispatch_once(&once, ^{ queue = dispatch_queue_create("me.jjolano.shadow.curl-diagnostics", DISPATCH_QUEUE_SERIAL); });
        dispatch_async(queue, ^{
            int workerErrno = errno;
            if (!SHDWCurlDiagnosticsEnabled()) { errno = workerErrno; return; }
            SHDWCurlDiagnosticDepth++;
            @try { @autoreleasepool {
                SHDWCurlDiagnosticSend(line);
            } } @finally {
                SHDWCurlDiagnosticDepth--;
                errno = workerErrno;
            }
        });
    } @finally {
        SHDWCurlDiagnosticDepth--;
        errno = saved;
    }
}

#define SHDWCurlTrace(...) do { if (SHDW_TRANSPORT_DIAGNOSTICS) SHDWCurlTraceImpl(__VA_ARGS__); } while (0)
