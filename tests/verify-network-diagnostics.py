"""Check production task observers against concrete and inherited native-style tasks."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
implementation = "\n".join(line for line in (root / "src/Transport/NetworkDiagnostics.m").read_text().splitlines()
                           if not line.startswith("#import"))
body_helpers = (root / "src/Transport/CurlDiagnostics.h").read_text()
body_helpers = body_helpers[body_helpers.index("static NSDictionary *SHDWCurlDiagnosticBodyPrefix"):body_helpers.index("static id SHDWCurlDiagnosticJSONValue")]
source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <assert.h>
#include <fcntl.h>
#include <unistd.h>
static BOOL enabled;
static unsigned hookCount, baseResumes, concreteResumes, baseResponses, concreteResponses, baseStates, concreteStates;
static NSMutableArray *records;
static BOOL SHDWCurlDiagnosticsEnabled(void) { return enabled; }
static void SHDWCurlTrace(NSString *stage, NSURLRequest *request, NSDictionary *details) {
    [records addObject:@{@"stage":stage, @"request":request ?: NSNull.null, @"details":details}];
    errno=E2BIG;
}
@interface FixtureTask : NSObject
@property(nonatomic,strong) NSURLRequest *currentRequest;
@property(nonatomic,strong) NSURLRequest *originalRequest;
@property(nonatomic,strong) NSURLResponse *response;
@property(nonatomic,strong) NSError *error;
@property(nonatomic) NSInteger state;
@property NSUInteger taskIdentifier;
@property int64_t countOfBytesReceived;
@property int64_t countOfBytesSent;
@property(nonatomic,strong) id fixtureMetrics;
- (void)resume;
- (id)_incompleteTaskMetrics;
@end
@implementation FixtureTask
- (void)resume { baseResumes++;errno=EBUSY; }
- (id)_incompleteTaskMetrics { return self.fixtureMetrics; }
- (void)setResponse:(NSURLResponse *)response { baseResponses++;_response=response;errno=ENOENT; }
- (void)setState:(NSInteger)state { baseStates++;_state=state;errno=ERANGE; }
@end
@interface FixtureTransaction : NSObject
@property(nonatomic,strong) NSURLRequest *request;
@property(nonatomic,strong) NSURLResponse *response;
@property(nonatomic,strong) NSString *networkProtocolName;
@property NSInteger resourceFetchType;
@end
@implementation FixtureTransaction @end
// Partial snapshots expose only some optional metric getters.
@interface TimedFixtureTransaction : FixtureTransaction
@property(nonatomic,strong) NSDate *fetchStartDate;
@property(nonatomic,strong) NSDate *connectStartDate;
@property(nonatomic,strong) NSDate *requestStartDate;
@property(nonatomic,strong) NSDate *responseEndDate;
@property(nonatomic,getter=isProxyConnection) BOOL proxyConnection;
@property(nonatomic,getter=isReusedConnection) BOOL reusedConnection;
@end
@implementation TimedFixtureTransaction @end
@interface FixtureMetrics : NSObject
@property(nonatomic,strong) NSArray *transactionMetrics;
@end
@implementation FixtureMetrics
- (BOOL)isKindOfClass:(Class)cls { return cls==NSURLSessionTaskMetrics.class || [super isKindOfClass:cls]; }
@end
@interface InheritedTask : FixtureTask @end
@implementation InheritedTask @end
@interface ConcreteTask : InheritedTask @end
@implementation ConcreteTask
- (void)resume { concreteResumes++;[super resume]; }
- (void)setResponse:(NSURLResponse *)response { concreteResponses++;[super setResponse:response]; }
- (void)setState:(NSInteger)state { concreteStates++;[super setState:state]; }
@end
@interface OtherFixture : NSObject
- (void)resume;
@end
@implementation OtherFixture
- (void)resume { }
@end
@interface SHDWHookSession : NSObject
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original;
@end
@implementation SHDWHookSession
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original {
    Method method=class_getInstanceMethod(cls,selector);assert(method);
    *original=(void *)method_setImplementation(method,(IMP)replacement);hookCount++;return YES;
}
@end
#define SHDW_CURL_DIAGNOSTIC_BODY_LIMIT (32 * 1024)
''' + body_helpers + r'''
#define NSURLSessionTask FixtureTask
''' + implementation + r'''
#undef NSURLSessionTask
int main(void) { @autoreleasepool {
    records=[NSMutableArray new];
    enabled=YES;
    NSURLRequest *ordinary=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.test/ordinary"]];
    NSURLRequest *challenge=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.test/interstitial"]];
    errno=EACCES;
    SHDWNetworkDiagnosticsTraceRequestOrigin(ordinary,@"request.create.origin");
    assert(!records.count && errno==EACCES);
    SHDWNetworkDiagnosticsTraceRequestOrigin(challenge,@"request.create.origin");
    assert(records.count==1 && errno==EACCES);
    assert([records.lastObject[@"details"][@"callStackSymbols"] count]>0);
    assert([records.lastObject[@"details"][@"callStackAddresses"] count]>0);
    SHDWNetworkDiagnosticsTraceWebHTMLOrigin(@"ordinary page",nil);
    SHDWNetworkDiagnosticsTraceWebHTMLOrigin(nil,nil);
    assert(records.count==1);
    NSString *html=@"<iframe src='https://geo.captcha-delivery.com/interstitial'></iframe>";
    SHDWNetworkDiagnosticsTraceWebHTMLOrigin(html,nil);
    assert(records.count==2 && [records.lastObject[@"details"][@"html"] isEqual:html]);
    assert(errno==EACCES);
    enabled=NO;
    SHDWNetworkDiagnosticsTraceRequestOrigin(challenge,@"request.create.origin");
    assert(records.count==2);
    [records removeAllObjects];
    SHDWHookSession *hooks=[SHDWHookSession new];
    SHDWNetworkDiagnosticsInstall(nil);assert(!hookCount);
    SHDWNetworkDiagnosticsInstall(hooks);assert(hookCount==6);
    SHDWNetworkDiagnosticsInstall(hooks);assert(hookCount==6);
    NSURLRequest *request=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://example.test/native?fixture=1"]];
    NSMutableURLRequest *configured=[request mutableCopy];
    configured.timeoutInterval=17.5;
    configured.HTTPBody=[@"native body" dataUsingEncoding:NSUTF8StringEncoding];
    [configured setValue:@"fr-FR" forHTTPHeaderField:@"Accept-Language"];
    request=[configured copy];
    NSHTTPURLResponse *response=[[NSHTTPURLResponse alloc]initWithURL:request.URL statusCode:304 HTTPVersion:@"HTTP/2" headerFields:@{@"ETag":@"fixture-tag",@"X-Fixture":@"response"}];
    for(Class cls in @[FixtureTask.class,InheritedTask.class,ConcreteTask.class]) {
        FixtureTask *task=[cls new];task.currentRequest=request;task.originalRequest=request;task.taskIdentifier=13;
        assert(!objc_getAssociatedObject(task,&taskIdentifierKey));
        enabled=NO;NSUInteger before=records.count;
        [task resume];assert(errno==EBUSY);
        [task setResponse:response];assert(errno==ENOENT);
        [task setState:NSURLSessionTaskStateCompleted];assert(errno==ERANGE);
        assert(records.count==before && !objc_getAssociatedObject(task,&taskIdentifierKey));
        enabled=YES;before=records.count;
        [task resume];assert(errno==EBUSY);
        [task setResponse:response];assert(errno==ENOENT && task.response==response);
        task.error=[NSError errorWithDomain:@"fixture" code:-12 userInfo:nil];
        task.countOfBytesReceived=4096;task.countOfBytesSent=11;
        [task setState:NSURLSessionTaskStateCompleted];assert(errno==ERANGE);
        assert(records.count==before+3 && task.currentRequest==request && task.originalRequest==request);
        assert([records[before][@"stage"] isEqual:@"task.resume"]);
        assert([records[before+1][@"stage"] isEqual:@"task.response"]);
        assert([records[before+2][@"stage"] isEqual:@"task.complete"]);
        NSString *identifier=records[before][@"details"][@"taskID"];
        assert(identifier.length && [identifier isEqual:records[before+1][@"details"][@"taskID"]]);
        assert([identifier isEqual:records[before+2][@"details"][@"taskID"]]);
        assert([records[before][@"details"][@"requestHeaders"] isEqual:request.allHTTPHeaderFields]);
        NSDictionary *body = records[before][@"details"][@"currentRequestBody"];
        assert([body[@"availability"] isEqual:@"available"] && [body[@"byteLength"] unsignedIntegerValue] == request.HTTPBody.length);
        assert([[[NSData alloc] initWithBase64EncodedString:body[@"base64"] options:0] isEqual:request.HTTPBody]);
        assert([records[before][@"details"][@"originalRequestBody"] isEqual:body]);
        assert([records[before+1][@"details"][@"responseHeaders"] isEqual:response.allHeaderFields]);
        assert([records[before+2][@"details"][@"httpStatus"] integerValue]==304);
        assert([records[before+2][@"details"][@"bytesReceived"] integerValue]==4096);
        assert([records[before+2][@"details"][@"errorCode"] integerValue]==-12);
        [task setState:NSURLSessionTaskStateRunning];assert([records.lastObject[@"stage"] isEqual:@"task.state"]);
    }
    FixtureTask *metricTask=[FixtureTask new];metricTask.currentRequest=request;metricTask.originalRequest=request;
    NSMutableURLRequest *sent=[request mutableCopy];
    [sent setValue:@"fixture=auto-cookie" forHTTPHeaderField:@"Cookie"];
    TimedFixtureTransaction *first=[TimedFixtureTransaction new];
    first.fetchStartDate=[NSDate dateWithTimeIntervalSince1970:1700000000.25];
    first.connectStartDate=nil; first.requestStartDate=[NSDate dateWithTimeIntervalSince1970:1700000001.5];
    first.responseEndDate=[NSDate dateWithTimeIntervalSince1970:1700000002.75];
    first.proxyConnection=YES;first.reusedConnection=YES;
    first.request=sent;first.response=response;
    first.networkProtocolName=@"h2";first.resourceFetchType=NSURLSessionTaskMetricsResourceFetchTypeNetworkLoad;
    FixtureTransaction *second=[FixtureTransaction new];second.request=request;
    second.resourceFetchType=NSURLSessionTaskMetricsResourceFetchTypeLocalCache;
    FixtureMetrics *metrics=[FixtureMetrics new];metrics.transactionMetrics=@[first,second];metricTask.fixtureMetrics=metrics;
    NSError *leaf=[NSError errorWithDomain:@"leaf" code:5 userInfo:@{@"secret":@"must-not-escape"}];
    NSError *deep=leaf;
    for (NSInteger i=4;i>=0;i--)
        deep=[NSError errorWithDomain:[NSString stringWithFormat:@"underlying-%ld",(long)i] code:i
            userInfo:@{NSUnderlyingErrorKey:deep,@"_kCFStreamErrorDomainKey":@4,
                @"_kCFStreamErrorCodeKey":@(-9806),@"token":@"must-not-escape"}];
    metricTask.error=[NSError errorWithDomain:NSURLErrorDomain code:NSURLErrorTimedOut
        userInfo:@{NSUnderlyingErrorKey:deep,@"_kCFStreamErrorDomainKey":@1,
            @"_kCFStreamErrorCodeKey":@"not-numeric",@"token":@"must-not-escape"}];
    NSUInteger metricBefore=records.count;errno=EACCES;
    SHDWNetworkObserve(@"task.complete",metricTask,nil,nil);assert(errno==EACCES);
    assert(records.count==metricBefore+3);
    NSDictionary *transaction=records[metricBefore];
    assert([transaction[@"stage"] isEqual:@"task.transaction"]);
    assert(transaction[@"request"]==sent);
    assert([transaction[@"details"][@"cookieHeader"] isEqual:@"fixture=auto-cookie"]);
    assert([transaction[@"details"][@"cookieHeaderPresent"] boolValue]);
    assert([transaction[@"details"][@"headerSource"] isEqual:@"transaction-metrics"]);
    NSDictionary *timings=transaction[@"details"][@"timings"];
    assert(timings.count==11);
    assert([timings[@"fetchStart"] doubleValue]==1700000000.25);
    assert([timings[@"requestStart"] doubleValue]==1700000001.5);
    assert([timings[@"responseEnd"] doubleValue]==1700000002.75);
    assert(timings[@"connectStart"]==NSNull.null && timings[@"responseStart"]==NSNull.null);
    assert([transaction[@"details"][@"proxyConnection"] boolValue]);
    assert([transaction[@"details"][@"reusedConnection"] boolValue]);
    NSDictionary *missing=records[metricBefore+1][@"details"];
    for(id value in [missing[@"timings"] allValues]) assert(value==NSNull.null);
    assert([missing[@"timings"] count]==11 && !missing[@"proxyConnection"] && !missing[@"reusedConnection"]);
    NSDictionary *complete=records.lastObject[@"details"];
    assert([complete[@"requestTimeoutInterval"] doubleValue]==17.5 && request.timeoutInterval==17.5);
    NSArray *chain=complete[@"errorChain"];
    assert(chain.count==4 && [chain[0][@"domain"] isEqual:NSURLErrorDomain]);
    assert([chain[0][@"code"] integerValue]==NSURLErrorTimedOut);
    assert([chain[0][@"_kCFStreamErrorDomainKey"] integerValue]==1);
    assert(!chain[0][@"_kCFStreamErrorCodeKey"] && !chain[0][@"token"]);
    assert([chain[3][@"domain"] isEqual:@"underlying-2"]);
    for(NSUInteger i=1;i<chain.count;i++) {
        assert([chain[i][@"_kCFStreamErrorCodeKey"] integerValue]==-9806);
        assert([chain[i] count]==4);
    }
    assert(metricTask.currentRequest==request && metricTask.originalRequest==request && metricTask.error.code==NSURLErrorTimedOut);
    assert([transaction[@"details"][@"responseHeaders"] isEqual:response.allHeaderFields]);
    assert(![records[metricBefore+1][@"details"][@"cookieHeaderPresent"] boolValue]);
    assert(!records[metricBefore+1][@"details"][@"cookieHeader"]);
    assert([records[metricBefore+1][@"details"][@"transactionIndex"] unsignedIntegerValue]==1);
    assert([records.lastObject[@"details"][@"transactions"] count]==2);
    assert([records.lastObject[@"details"][@"taskID"] isEqual:transaction[@"details"][@"taskID"]]);
    assert(![metricTask.currentRequest valueForHTTPHeaderField:@"Cookie"]);
    FixtureTask *upload = [FixtureTask new]; upload.currentRequest=request; upload.originalRequest=request;
    NSMutableData *raw = [NSMutableData dataWithLength:SHDW_CURL_DIAGNOSTIC_BODY_LIMIT + 7];
    memset(raw.mutableBytes, 0x8b, raw.length);
    NSData *expected = [raw subdataWithRange:NSMakeRange(0, SHDW_CURL_DIAGNOSTIC_BODY_LIMIT)];
    errno = EACCES; SHDWNetworkDiagnosticsAttachUploadData(upload,raw); assert(errno == EACCES);
    memset(raw.mutableBytes, 0, raw.length);
    SHDWNetworkObserve(@"task.resume",upload,nil,nil);
    NSDictionary *snapshot = records.lastObject[@"details"][@"uploadBody"];
    assert([snapshot[@"source"] isEqual:@"upload-data-snapshot"] && [snapshot[@"truncated"] boolValue]);
    assert([snapshot[@"byteLength"] unsignedIntegerValue] == raw.length);
    assert([[[NSData alloc] initWithBase64EncodedString:snapshot[@"base64"] options:0] isEqual:expected]);
    NSString *path = [NSTemporaryDirectory() stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
    NSMutableData *fileBody = [expected mutableCopy]; [fileBody appendData:[NSData dataWithBytes:"seven!!" length:7]];
    assert([fileBody writeToFile:path atomically:YES]);
    errno = EBUSY; SHDWNetworkDiagnosticsAttachUploadFile(upload,[NSURL fileURLWithPath:path]); assert(errno == EBUSY);
    assert([NSData.data writeToFile:path atomically:YES]);
    SHDWNetworkObserve(@"task.resume",upload,nil,nil);
    snapshot = records.lastObject[@"details"][@"uploadBody"];
    assert([snapshot[@"source"] isEqual:@"upload-file-snapshot"] && [snapshot[@"truncated"] boolValue]);
    assert([snapshot[@"byteLength"] unsignedIntegerValue] == fileBody.length);
    assert([[[NSData alloc] initWithBase64EncodedString:snapshot[@"base64"] options:0] isEqual:expected]);
    assert([NSFileManager.defaultManager removeItemAtPath:path error:NULL]);
    SHDWNetworkDiagnosticsAttachUploadFile(upload,[NSURL fileURLWithPath:path]);
    SHDWNetworkObserve(@"task.resume",upload,nil,nil);
    assert([records.lastObject[@"details"][@"uploadBody"][@"availability"] isEqual:@"file-unreadable"]);
    SHDWNetworkDiagnosticsAttachUploadFile(upload,[NSURL URLWithString:@"https://example.test/not-a-file"]);
    SHDWNetworkObserve(@"task.resume",upload,nil,nil);
    assert([records.lastObject[@"details"][@"uploadBody"][@"availability"] isEqual:@"invalid-file-url"]);
    NSString *fifo = [path stringByAppendingString:@"-fifo"];
    assert(mkfifo(fifo.fileSystemRepresentation,0600) == 0);
    SHDWNetworkDiagnosticsAttachUploadFile(upload,[NSURL fileURLWithPath:fifo]);
    SHDWNetworkObserve(@"task.resume",upload,nil,nil);
    assert([records.lastObject[@"details"][@"uploadBody"][@"availability"] isEqual:@"file-not-regular"]);
    assert([NSFileManager.defaultManager removeItemAtPath:fifo error:NULL]);
    SHDWNetworkDiagnosticsAttachUploadData(nil,expected);
    assert(baseResumes==6 && concreteResumes==2);
    assert(baseResponses==6 && concreteResponses==2);
    assert(baseStates==9 && concreteStates==3);
    puts("network diagnostics: native untagged tasks, exact forwarding, concrete/inherited super dedup, stable associated IDs, full headers, request/upload raw body snapshots, bounded file reads, status/error/counts, errno and disabled collection passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-network-diagnostics-") as directory:
    test, binary=Path(directory)/"test.m",Path(directory)/"check"
    test.write_text(source)
    subprocess.run(["xcrun","clang","-I",str(root / "src/Transport"),"-I",str(root / "src/ShadowCore.dylib/policy"),"-DSHDW_TRANSPORT_DIAGNOSTICS=1","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror", "-fsanitize=address,undefined",
                    "-framework","Foundation",str(test),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
