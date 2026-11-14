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
#import "../Localization/Bootstrap.h"
static unsigned hookCount, prepared, configured, captured, nativeRequests;
static NSString *selectedProfile;
static unsigned environmentApplications;
static BOOL requireEnvironment;
static NSDictionary *appliedEnvironment;
static BOOL SHDWLocalizationApplyEnvironment(NSDictionary *values) {
    environmentApplications++;appliedEnvironment=[values copy];return YES;
}
static void SHDWCurlTrace(NSString *stage, NSURLRequest *request, NSDictionary *details) {
    assert([stage isEqual:@"network.localization"] && !request && [details[@"applied"] boolValue]);
}
static BOOL ready=YES, nativeTLSLayer;
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
static void SHDWCurlTransportPrepareProfile(NSString *profile) { assert([profile isEqual:selectedProfile]);if(requireEnvironment)assert(environmentApplications==1);prepared++; }
static BOOL SHDWCurlTransportReady(void) { return ready; }
static void SHDWNetworkDiagnosticsInstall(SHDWHookSession *hooks) { assert(hooks); }
#define NSURLSession FixtureSession
''' + implementation("src/ShadowWebKit.dylib/Sessions.m") + r'''
#undef NSURLSession
static xpc_object_t launchBootstrap;
static xpc_handler_t installedHandler;
static xpc_object_t fixture_copy_bootstrap(void) { return launchBootstrap; }
static void recordHandler(xpc_connection_t connection,xpc_handler_t handler) { (void)connection;installedHandler=[handler copy]; }
static void SHDWLocalizationHookFunction(const char *name,void *target,void *replacement,void **original) {
    (void)name;(void)target;(void)replacement;(void)original;assert(!"automatic constructor must not run");
}
#define xpc_copy_bootstrap fixture_copy_bootstrap
''' + implementation("src/ShadowWebKit.dylib/Networking.m").replace(
    'extern xpc_object_t xpc_copy_bootstrap(void) __attribute__((weak_import, ns_returns_retained));', '') .replace(
    '__attribute__((constructor)) static void Install(void)', 'static void FixtureInstall(void)') + r'''
#undef xpc_copy_bootstrap
static xpc_object_t event(const char *service,const char *owner) {
    xpc_object_t e=xpc_dictionary_create(NULL,NULL,0);
    xpc_dictionary_set_string(e,"message-name","bootstrap");
    xpc_dictionary_set_string(e,"service-name",service);
    xpc_dictionary_set_string(e,"client-bundle-identifier",owner);return e;
}
int main(int argc,const char **argv) { @autoreleasepool {
    selectedProfile = argc > 1 ? @(argv[1]) : @"safari184_ios";
    nativeTLSLayer = YES;
    (void)FixtureInstall;
    launchBootstrap=SHDWTransportBootstrapMessage(xpc_dictionary_create(NULL,NULL,0),selectedProfile,@"test.Owner");
    NSDictionary *locale=@{@"LocaleIdentifier":@"fr_FR",@"Languages":@[@"fr-FR"],@"TimeZone":@"Europe/Paris",@"OverridesSystem":@YES};
    launchBootstrap=SHDWLocalizationBootstrapMessage(launchBootstrap,locale,@"test.Owner");
    nativeSetHandler=recordHandler;
    __block unsigned forwarded=0;
    __block BOOL expectInstalled=NO;
    errno=EDOM;
    SetHandler(nil,^(xpc_object_t value){assert(value);assert(errno==ERANGE);assert((processSnapshot!=nil)==expectInstalled);forwarded++;});
    assert(errno==EDOM && installedHandler);
    errno=ERANGE;installedHandler(event("com.apple.WebKit.WebContent","test.Owner"));
    installedHandler(event("com.apple.WebKit.Networking","wrong.Owner"));
    assert(!hookCount && !prepared && forwarded==2 && !environmentApplications);
    if([selectedProfile isEqual:@"native"]) {
        installedHandler(event("com.apple.WebKit.Networking","test.Owner"));
        assert(environmentApplications==1 && !hookCount && !prepared && !processSnapshot);
        assert([appliedEnvironment[@"Languages"] isEqual:@[@"fr-FR"]]);
        launchBootstrap=SHDWLocalizationBootstrapMessage(xpc_dictionary_create(NULL,NULL,0),locale,@"other.Owner");
        installedHandler(event("com.apple.WebKit.Networking","other.Owner"));
        assert(environmentApplications==1 && !hookCount && !prepared);
        puts("networking localization: TLS-off bootstrap, exact service/owner gating and frozen owner passed");return 0;
    }
    ready=NO;assert(!SHDWNetworkingInstall(@{@"Profile":selectedProfile,@"Owner":@"test.Owner"}));assert(!hookCount);
    ready=YES;expectInstalled=YES;requireEnvironment=YES;
    installedHandler(event("com.apple.WebKit.Networking","test.Owner"));
    assert(forwarded==3 && processSnapshot && !hookCount && environmentApplications==1);
    unsigned hooks=hookCount,preparations=prepared;
    installedHandler(event("com.apple.WebKit.Networking","test.Owner"));
    assert(hookCount==hooks && prepared==preparations && environmentApplications==1);
    xpc_object_t acceptedBootstrap=launchBootstrap;
    launchBootstrap=SHDWLocalizationBootstrapMessage(
        SHDWTransportBootstrapMessage(xpc_dictionary_create(NULL,NULL,0),selectedProfile,@"other.Owner"),locale,@"other.Owner");
    installedHandler(event("com.apple.WebKit.Networking","other.Owner"));
    assert(environmentApplications==1 && hookCount==hooks && prepared==preparations);
    launchBootstrap=acceptedBootstrap;
    assert(!SHDWNetworkingInstall(@{@"Profile":selectedProfile,@"Owner":@"other.Owner"}));
    assert(hookCount==hooks && [processSnapshot[@"Owner"] isEqual:@"test.Owner"]);
    if(nativeTLSLayer) {
        NSURLSessionConfiguration *config=NSURLSessionConfiguration.ephemeralSessionConfiguration;
        NSURLRequest *request=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://fixture.test/"]];
        FixtureSession *session=[FixtureSession sessionWithConfiguration:config delegate:[WKNetworkSessionDelegate new] delegateQueue:nil];
        assert(seenConfiguration==config);
        [session dataTaskWithRequest:request];assert(seenRequest==request);
        [session dataTaskWithRequest:request completionHandler:nil];assert(seenRequest==request);
        assert(!hookCount && !configured && !captured);
        puts("networking native TLS: original session/configuration/request identity, no HTTP task hooks, owner gating and one-time bootstrap passed");
        return 0;
    }

} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-networking-session-") as temporary:
    test, binary = Path(temporary) / "test.m", Path(temporary) / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-Wno-pointer-bool-conversion", "-fsanitize=address,undefined", "-framework", "Foundation",
                    "-I", str(root / "src/Transport"), str(test), str(root / "src/Transport/Bootstrap.m"), str(root / "src/Localization/Bootstrap.m"),
                    "-o", str(binary)], check=True)
    for profile in ("safari172_ios", "safari180_ios", "safari184_ios", "safari187_ios", "native"):
        subprocess.run([str(binary), profile], check=True)
