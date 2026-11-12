"""Exercise the production Networking bootstrap and session hooks with host runtime doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation and XPC")
root = Path(__file__).resolve().parents[1]

def implementation(path):
    return "\n".join(line for line in (root / path).read_text().splitlines()
                     if not line.startswith("#import"))

source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <xpc/xpc.h>
#include <assert.h>
#import "Bootstrap.h"
static unsigned hookCount, prepared, configured, captured, nativeRequests;
static BOOL ready=YES, webKitBundle=YES;
static NSURLSessionConfiguration *seenConfiguration;
static NSURLRequest *seenRequest;
static id seenCallback;
@interface WKNetworkSessionDelegate : NSObject @end
@implementation WKNetworkSessionDelegate @end
@interface WKURLSessionTaskDelegate : NSObject @end
@implementation WKURLSessionTaskDelegate @end
@interface OtherDelegate : NSObject @end
@implementation OtherDelegate @end
@interface FixtureSession : NSObject
@property(strong) id delegate;
+ (id)sessionWithConfiguration:(NSURLSessionConfiguration *)configuration delegate:(id)delegate delegateQueue:(NSOperationQueue *)queue;
- (id)dataTaskWithRequest:(NSURLRequest *)request;
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)callback;
@end
static id record(NSURLRequest *request,id callback) { nativeRequests++;seenRequest=request;seenCallback=callback;return @"task"; }
@implementation FixtureSession
+ (id)sessionWithConfiguration:(NSURLSessionConfiguration *)configuration delegate:(id)delegate delegateQueue:(NSOperationQueue *)queue {
    (void)queue;seenConfiguration=configuration;FixtureSession *s=[self new];s.delegate=delegate;return s;
}
- (id)dataTaskWithRequest:(NSURLRequest *)request { return record(request,nil); }
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)callback { return record(request,callback); }
@end
@interface InheritedSession : FixtureSession @end
@implementation InheritedSession @end
@interface ConcreteSession : FixtureSession @end
@implementation ConcreteSession
- (id)dataTaskWithRequest:(NSURLRequest *)request { return record(request,nil); }
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)callback { return record(request,callback); }
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
static NSBundle *(*originalBundle)(id,SEL,Class);
@interface FixtureBundle : NSObject
@property(copy) NSString *bundleIdentifier;
@end
@implementation FixtureBundle @end
static NSBundle *testBundle(id cls,SEL sel,Class target) {
    if(target==WKNetworkSessionDelegate.class || target==WKURLSessionTaskDelegate.class) {
        FixtureBundle *b=[FixtureBundle new];b.bundleIdentifier=webKitBundle ? @"com.apple.WebKit" : @"other.bundle";return (id)b;
    }
    return originalBundle(cls,sel,target);
}
static void SHDWCurlTransportPrepareProfile(NSString *profile) { assert([profile isEqual:@"safari184_ios"]);prepared++; }
static BOOL SHDWCurlTransportReady(void) { return ready; }
static NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) {
    configured++;NSURLSessionConfiguration *copy=[configuration copy];copy.timeoutIntervalForRequest=17;return copy;
}
static NSURLRequest *SHDWCurlTransportWebKitRequest(NSURLRequest *request,FixtureSession *session) {
    assert(session.delegate);captured++;NSMutableURLRequest *copy=[request mutableCopy];[copy setValue:@"captured" forHTTPHeaderField:@"X-Fixture"];return copy;
}
static void SHDWCurlTransportAttachTask(NSURLRequest *request,NSURLSessionTask *task) { assert(request && task); }
#define NSURLSession FixtureSession
''' + implementation("src/ShadowNetworking.dylib/Sessions.m") + r'''
#undef NSURLSession
static xpc_object_t launchBootstrap;
static xpc_handler_t installedHandler;
static xpc_object_t fixture_copy_bootstrap(void) { return launchBootstrap; }
static void recordHandler(xpc_connection_t connection,xpc_handler_t handler) { (void)connection;installedHandler=[handler copy]; }
static void SHDWLocalizationHookFunction(const char *name,void *target,void *replacement,void **original) {
    (void)name;(void)target;(void)replacement;(void)original;assert(!"automatic constructor must not run");
}
#define xpc_copy_bootstrap fixture_copy_bootstrap
''' + implementation("src/ShadowNetworking.dylib/Entry.m").replace(
    'extern xpc_object_t xpc_copy_bootstrap(void) __attribute__((weak_import, ns_returns_retained));', '') .replace(
    '__attribute__((constructor)) static void Install(void)', 'static void FixtureInstall(void)') + r'''
#undef xpc_copy_bootstrap
static xpc_object_t event(const char *service,const char *owner) {
    xpc_object_t e=xpc_dictionary_create(NULL,NULL,0);
    xpc_dictionary_set_string(e,"message-name","bootstrap");
    xpc_dictionary_set_string(e,"service-name",service);
    xpc_dictionary_set_string(e,"client-bundle-identifier",owner);return e;
}
int main(void) { @autoreleasepool {
    (void)FixtureInstall;
    launchBootstrap=SHDWTransportBootstrapMessage(xpc_dictionary_create(NULL,NULL,0),@"safari184_ios",@"test.Owner");
    nativeSetHandler=recordHandler;
    __block unsigned forwarded=0;
    __block BOOL expectInstalled=NO;
    errno=EDOM;
    SetHandler(nil,^(xpc_object_t value){assert(value);assert(errno==ERANGE);assert((processSnapshot!=nil)==expectInstalled);forwarded++;});
    assert(errno==EDOM && installedHandler);
    errno=ERANGE;installedHandler(event("com.apple.WebKit.WebContent","test.Owner"));
    installedHandler(event("com.apple.WebKit.Networking","wrong.Owner"));
    assert(!hookCount && !prepared && forwarded==2);
    ready=NO;assert(!SHDWNetworkingInstall(@{@"Profile":@"safari184_ios",@"Owner":@"test.Owner"}));assert(!hookCount);
    ready=YES;expectInstalled=YES;
    installedHandler(event("com.apple.WebKit.Networking","test.Owner"));
    assert(forwarded==3 && processSnapshot && hookCount==5);
    unsigned hooks=hookCount,preparations=prepared;
    installedHandler(event("com.apple.WebKit.Networking","test.Owner"));
    assert(hookCount==hooks && prepared==preparations);
    assert(!SHDWNetworkingInstall(@{@"Profile":@"safari184_ios",@"Owner":@"other.Owner"}));
    assert(hookCount==hooks && [processSnapshot[@"Owner"] isEqual:@"test.Owner"]);
    Method method=class_getClassMethod(NSBundle.class,@selector(bundleForClass:));
    originalBundle=(void *)method_setImplementation(method,(IMP)testBundle);
    NSURLSessionConfiguration *config=[NSURLSessionConfiguration ephemeralSessionConfiguration];config.timeoutIntervalForRequest=42;
    id callback=^(NSData *data,NSURLResponse *response,NSError *error){(void)data;(void)response;(void)error;};
    NSURLRequest *request=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://fixture.test/"]];
    for(Class cls in @[FixtureSession.class,InheritedSession.class,ConcreteSession.class]) {
        for(id delegate in @[[WKNetworkSessionDelegate new],[WKURLSessionTaskDelegate new],[OtherDelegate new],NSNull.null]) {
            FixtureSession *session=(id)[cls sessionWithConfiguration:config delegate:delegate==NSNull.null ? nil : delegate delegateQueue:nil];
            assert(seenConfiguration!=config && seenConfiguration.timeoutIntervalForRequest==17 && config.timeoutIntervalForRequest==42);
            BOOL expected=[delegate isKindOfClass:WKNetworkSessionDelegate.class] || [delegate isKindOfClass:WKURLSessionTaskDelegate.class];
            unsigned before=captured,nativeBefore=nativeRequests;
            assert([[session dataTaskWithRequest:request] isEqual:@"task"]);
            assert(captured==before+expected && nativeRequests==nativeBefore+1 && !seenCallback);
            assert((seenRequest!=request)==expected);
            assert([[session dataTaskWithRequest:request completionHandler:callback] isEqual:@"task"]);
            assert(captured==before+2*expected && nativeRequests==nativeBefore+2 && seenCallback==callback);
            assert((seenRequest!=request)==expected);
        }
    }
    webKitBundle=NO;
    FixtureSession *spoof=[FixtureSession sessionWithConfiguration:config delegate:[WKNetworkSessionDelegate new] delegateQueue:nil];
    unsigned before=captured;[spoof dataTaskWithRequest:request];[spoof dataTaskWithRequest:request completionHandler:callback];
    assert(captured==before && seenRequest==request);
    assert(configured==13);
    method_setImplementation(method,(IMP)originalBundle);
    SetHandler(nil,nil);assert(!installedHandler);
    puts("networking session: real bootstrap gating, install-before-forward, idempotence, owner conflict, copied configuration, concrete/inherited request hooks and delegate bundle isolation passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-networking-session-") as temporary:
    test, binary = Path(temporary) / "test.m", Path(temporary) / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-Wno-pointer-bool-conversion", "-fsanitize=address,undefined", "-framework", "Foundation",
                    "-I", str(root / "src/Transport"), str(test), str(root / "src/Transport/Bootstrap.m"),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
