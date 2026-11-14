"""Exercise production diagnostics through an isolated loopback collector."""
from pathlib import Path
import base64
import json
import socket
import subprocess
import sys
import tempfile
import threading

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <dispatch/dispatch.h>
#include <errno.h>
#include <unistd.h>
static dispatch_queue_t lastQueue;
static unsigned reentryChecks;
static BOOL SHDWCurlDiagnosticsEnabled(void);
static void SHDWCurlTraceImpl(NSString *, NSURLRequest *, NSDictionary *);
@interface GuardedRequest : NSObject
@property(nonatomic, strong) NSURLRequest *backing;
@end
@implementation GuardedRequest
- (NSURL *)URL { return self.backing.URL; }
- (NSString *)HTTPMethod { return self.backing.HTTPMethod; }
- (NSData *)HTTPBody { return self.backing.HTTPBody; }
- (NSInputStream *)HTTPBodyStream { return self.backing.HTTPBodyStream; }
- (NSDictionary *)allHTTPHeaderFields {
    assert(!SHDWCurlDiagnosticsEnabled());
    SHDWCurlTraceImpl(@"recursive-headers", nil, @{});
    reentryChecks++;
    return self.backing.allHTTPHeaderFields;
}
@end
static void TestDispatchAsync(dispatch_queue_t queue, dispatch_block_t block) {
    lastQueue = queue;
    dispatch_async(queue, block);
}
#define dispatch_async TestDispatchAsync
#include "CurlDiagnostics.h"
#undef dispatch_async
static void drain(void) { assert(lastQueue); dispatch_sync(lastQueue, ^{}); }

int main(void) { @autoreleasepool {
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://user:password@example.com/resource?secret=private#fragment"]];
    NSString *longHeader = [@"header-value-" stringByPaddingToLength:65536 withString:@"x" startingAtIndex:0];
    [request setValue:@"token=local-test-cookie" forHTTPHeaderField:@"Cookie"];
    [request setValue:@"Bearer local-test-authorization" forHTTPHeaderField:@"Authorization"];
    [request setValue:longHeader forHTTPHeaderField:@"X-Long"];
    request.HTTPBody = [@"body-must-not-be-recorded" dataUsingEncoding:NSUTF8StringEncoding];
    unsigned char rawBytes[] = {0, 0xff, 0x1f, 0x8b, '\n'};
    NSData *raw = [NSData dataWithBytes:rawBytes length:sizeof(rawBytes)];
    errno = EBUSY;
    NSDictionary *rawBody = SHDWCurlDiagnosticBody(raw);
    assert(errno == EBUSY && [rawBody[@"availability"] isEqual:@"available"]);
    assert([rawBody[@"byteLength"] unsignedIntegerValue] == raw.length && ![rawBody[@"truncated"] boolValue]);
    assert([[[NSData alloc] initWithBase64EncodedString:rawBody[@"base64"] options:0] isEqual:raw]);
    NSMutableData *large = [NSMutableData dataWithLength:SHDW_CURL_DIAGNOSTIC_BODY_LIMIT + 19];
    memset(large.mutableBytes, 0xa5, large.length);
    NSDictionary *bounded = SHDWCurlDiagnosticBody(large);
    assert([bounded[@"byteLength"] unsignedIntegerValue] == large.length && [bounded[@"truncated"] boolValue]);
    assert([bounded[@"capturedByteLength"] unsignedIntegerValue] == SHDW_CURL_DIAGNOSTIC_BODY_LIMIT);
    assert([[[NSData alloc] initWithBase64EncodedString:bounded[@"base64"] options:0] isEqual:[large subdataWithRange:NSMakeRange(0, SHDW_CURL_DIAGNOSTIC_BODY_LIMIT)]]);
    assert([SHDWCurlDiagnosticBody(nil)[@"availability"] isEqual:@"unavailable"]);
    assert([SHDWCurlDiagnosticBody(NSData.data)[@"availability"] isEqual:@"available"]);
    NSMutableURLRequest *streamed = [request mutableCopy]; streamed.HTTPBody = nil;
    NSInputStream *stream = [NSInputStream inputStreamWithData:raw]; streamed.HTTPBodyStream = stream;
    NSDictionary *streamBody = SHDWCurlDiagnosticRequestBody(streamed);
    assert([streamBody[@"availability"] isEqual:@"stream-not-read"] && stream.streamStatus == NSStreamStatusNotOpen);
    [stream open]; unsigned char readBytes[sizeof(rawBytes)] = {0};
    assert([stream read:readBytes maxLength:sizeof(readBytes)] == sizeof(rawBytes) && !memcmp(readBytes, rawBytes, sizeof(rawBytes))); [stream close];
    errno = EBUSY;
    assert(SHDWCurlDiagnosticsEnabled() && errno == EBUSY);
    GuardedRequest *guarded = [GuardedRequest new]; guarded.backing = request;
    errno = ERANGE;
    SHDWCurlTrace(@"headers", (NSURLRequest *)guarded, @{@"traceID":@"abc", @"code":@0, @"ignored":NSData.data,
        @"responseHeaders":@{@"Set-Cookie":@[@"one=1", @"two=2"], @"X-Long":longHeader},
        @"task":@{@"metrics":@[@{@"bytes":@123, @"protocol":@"h2"}]}, @"binaryBody":rawBody});
    assert(errno == ERANGE);
    drain();
    assert(reentryChecks == 1 && SHDWCurlDiagnosticDepth == 0);
    SHDWCurlTrace(@"session-without-request", nil, @{@"task":@1});
    drain();
    // A record above the collector line limit must be dropped, not split.
    NSMutableDictionary *tooLarge = [NSMutableDictionary new];
    for (unsigned i = 0; i < 6; i++) tooLarge[[@(i) stringValue]] = longHeader;
    SHDWCurlTrace(@"oversized", nil, tooLarge);
    drain();
    SHDWCurlTrace(@"after-oversized", nil, @{@"successful":@YES});
    drain();
    puts("collector-ready"); fflush(stdout);
    assert(getchar() == 'x');
    errno = EDOM;
    int64_t before = SHDWCurlDiagnosticMilliseconds();
    SHDWCurlTrace(@"collector-unavailable", request, @{});
    assert(errno == EDOM && SHDWCurlDiagnosticMilliseconds() - before < 250);
    drain();
    assert(SHDWCurlDiagnosticMilliseconds() - before < 1500);
    assert(SHDWCurlDiagnosticDepth == 0);
    puts("curl diagnostics: explicitly enabled, reentry, errno, full query/headers, nested JSON, exact bounded raw bodies, unread streams, JSONL line cap and bounded unavailable collector passed");
} return 0; }
'''

with tempfile.TemporaryDirectory(prefix="shadow-curl-diagnostics-") as directory:
    temporary = Path(directory)
    test, binary = temporary / "test.m", temporary / "check"
    test.write_text(source)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.settimeout(10)
    port = listener.getsockname()[1]
    subprocess.run([
        "xcrun", "clang", "-DSHDW_TRANSPORT_DIAGNOSTICS=1", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Transport"),
        f"-DSHDW_CURL_DIAGNOSTICS_PORT={port}", str(test), "-o", str(binary),
    ], check=True)
    records, errors = [], []

    def collect():
        try:
            while len(records) < 3:
                connection, peer = listener.accept()
                with connection:
                    assert peer[0] == "127.0.0.1"
                    connection.settimeout(3)
                    line = b""
                    while True:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        line += chunk
                        assert len(line) <= 262144
                    assert line.endswith(b"\n") and line.count(b"\n") == 1
                    records.append(json.loads(line))
        except BaseException as error:
            errors.append(error)
        finally:
            listener.close()

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=temporary)
    try:
        assert process.stdout.readline().strip() == "collector-ready"
        collector.join(5)
        assert not collector.is_alive() and not errors, errors
        assert [record["stage"] for record in records] == ["headers", "session-without-request", "after-oversized"]
        record = records[0]
        assert record["url"] == "https://example.com/resource?secret=private#fragment"
        assert record["host"] == "example.com" and record["path"] == "/resource"
        assert record["method"] == "GET" and record["scheme"] == "https"
        assert record["requestHeaders"]["Cookie"] == "token=local-test-cookie"
        assert record["requestHeaders"]["Authorization"] == "Bearer local-test-authorization"
        assert len(record["requestHeaders"]["X-Long"]) == 65536
        assert record["details"]["responseHeaders"]["X-Long"] == record["requestHeaders"]["X-Long"]
        assert record["details"]["responseHeaders"]["Set-Cookie"] == ["one=1", "two=2"]
        assert record["details"]["task"]["metrics"][0]["bytes"] == 123
        assert record["details"]["traceID"] == "abc" and "ignored" not in record["details"]
        assert record["requestBody"]["availability"] == "available"
        assert base64.b64decode(record["requestBody"]["base64"]) == b"body-must-not-be-recorded"
        assert base64.b64decode(record["details"]["binaryBody"]["base64"]) == b"\x00\xff\x1f\x8b\x0a"
        assert record["pid"] == process.pid and record["epoch"] > 0
        assert records[1]["url"] == "" and records[1]["requestHeaders"] == {}
        process.stdin.write("x")
        process.stdin.flush()
        output, _ = process.communicate(timeout=5)
        assert process.returncode == 0, process.returncode
        assert not list(temporary.glob("**/*.jsonl")) and not (temporary / "Library").exists()
        print(output.strip())
    finally:
        listener.close()
        if process.poll() is None:
            process.kill()
            process.wait()
