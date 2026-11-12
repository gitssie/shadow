"""Exercise the default-UA session configuration and installer with fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
production = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintNetwork.x").read_text()
production = "\n".join(line for line in production.splitlines() if not line.startswith("#import"))
for forbidden in ("SHDWNetworkReplaceUserAgentCache", "_CFNetworkCopyDefaultUserAgentString", "shdw_network_user_agent", "setValue:", "HTTPAdditionalHeaders ="):
    assert forbidden not in production, f"HTTP header/cache rewriting remains: {forbidden}"
bundle_source = (root / "src/ShadowCore.dylib/hooks/Universal/NSBundle.x").read_text()
def bundle_body(signature):
    start = bundle_source.index("{", bundle_source.index(signature)) + 1
    end = start
    depth = 1
    while depth:
        depth += (bundle_source[end] == "{") - (bundle_source[end] == "}")
        end += 1
    return bundle_source[start:end-1]
metadata = "static NSDictionary *bundleInfo(id self) {" + bundle_body("- (NSDictionary<NSString *, id> *)infoDictionary").replace("%orig", "nativeBundleInfo()") + "}\n"
metadata += "static id bundleValue(id self, NSString *key) {" + bundle_body("- (id)objectForInfoDictionaryKey:").replace("%orig", "nativeBundleValue(key)") + "}\n"
prefix = r"""
#import <Foundation/Foundation.h>
#include <objc/runtime.h>
#include <assert.h>
#include <errno.h>
static unsigned depth, installCalls, sessionCalls, concreteCalls, parentCalls, childCalls;
static unsigned transportStarts, bootstrapStarts, configurationCalls, requestCalls;
static id factoryResult;
static void shdw_universal_url_session(id hooks) { (void)hooks; }
static void shdw_universal_bundle_metadata(id hooks) { (void)hooks; }
static BOOL shdw_bundle_metadata_paths_enabled;
static NSDictionary *metadataFixture;
static NSDictionary *nativeBundleInfo(void) { return metadataFixture; }
static id nativeBundleValue(NSString *key) { return metadataFixture[key]; }
#define isCallerExternal() (external && !depth)
static BOOL enabled=YES, external=YES, installs=YES, transportEnabled;
static void SHDWCurlTransportPrepare(void) { transportStarts++; }
static void SHDWFingerprintInstallWebLocalization(void) { bootstrapStarts++; }
static NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) {
    assert(depth);configurationCalls++;
    if(!transportEnabled) return configuration;
    NSURLSessionConfiguration *copy=[configuration copy];copy.protocolClasses=@[NSURLProtocol.class];return copy;
}
static NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request,id session) {
    (void)session;assert(depth);requestCalls++;
    if(!transportEnabled) return request;
    NSMutableURLRequest *copy=[request mutableCopy];
    [NSURLProtocol setProperty:@YES forKey:@"transport.fixture" inRequest:copy];return copy;
}
static NSString *SHDWFingerprintCFNetworkVersion(void) { assert(depth);return @"3826.600.41"; }
static NSURLSessionConfiguration *received;
static id receivedDelegate;
static NSOperationQueue *receivedQueue;
static BOOL shdw_fingerprint_is_enabled(void) { return enabled; }
static BOOL shdw_caller_is_external(const void *caller) { return caller && external && !depth; }
static void leave(BOOL *active) { (void)active; assert(depth); depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave)))=(++depth,YES); active; active=NO)
static NSURLSession *nativeSession(id self,SEL selector,NSURLSessionConfiguration *configuration) {
    (void)self;(void)selector;sessionCalls++;received=configuration;return (NSURLSession *)factoryResult;
}
static NSURLSession *nativeSessionDelegate(id self,SEL selector,NSURLSessionConfiguration *configuration,id delegate,NSOperationQueue *queue) {
    receivedDelegate=delegate;receivedQueue=queue;return nativeSession(self,selector,configuration);
}
static NSURLSession *nativeShared(id self,SEL selector) { (void)self;(void)selector;return (NSURLSession *)factoryResult; }
@interface FixtureBundle : NSObject
@property(nonatomic,copy) NSString *bundleIdentifier;
@end
@implementation FixtureBundle
@end
@interface RequestSessionDouble : NSObject
@property(nonatomic,strong) NSURLSessionConfiguration *configuration;
@end
@implementation RequestSessionDouble
@end
@interface ParentSession : RequestSessionDouble
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)completion;
@end
@implementation ParentSession
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)completion {
    parentCalls++;received=(id)request;receivedDelegate=completion;return self;
}
@end
@interface ChildSession : ParentSession
@end
@implementation ChildSession
- (id)dataTaskWithRequest:(NSURLRequest *)request completionHandler:(id)completion {
    childCalls++;return [super dataTaskWithRequest:request completionHandler:completion];
}
@end
@interface SessionDouble : NSObject
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)old;
@end
@implementation SessionDouble
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)old {
    assert(depth && replacement && old);
    if(!class_isMetaClass(cls)) {
        concreteCalls++;
        Method method=class_getInstanceMethod(cls,selector);
        *old=(void *)method_getImplementation(method);
        class_replaceMethod(cls,selector,(IMP)replacement,method_getTypeEncoding(method));
        return YES;
    }
    installCalls++;
    if(!installs) return NO;
    *old=sel_isEqual(selector,@selector(sharedSession)) ? (void *)nativeShared :
        sel_isEqual(selector,@selector(sessionWithConfiguration:)) ? (void *)nativeSession : (void *)nativeSessionDelegate;
    return YES;
}
@end
#define SHDWHookSession SessionDouble
#define NSURLSession RequestSessionDouble
"""
suffix = r"""
int main(void) { @autoreleasepool {
    SessionDouble *hooks=[SessionDouble new];
    enabled=NO;shdw_universal_fingerprint_network_prepare(hooks);
    shdw_universal_fingerprint_network_prepare(nil);
    assert(!installCalls && !transportStarts && !bootstrapStarts && !shdw_network_session_state);
    enabled=YES;shdw_universal_fingerprint_network_prepare(hooks);
    assert(installCalls==3 && shdw_network_session_state==2 && transportStarts==1 && bootstrapStarts==1);
    shdw_universal_fingerprint_network_prepare(hooks);assert(installCalls==3);
    NSString *nativeCache=@"SDK%20Probe/1 CFNetwork/1404.0.5 Darwin/22.3.0";
    NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    NSArray *headerSets=@[@{},@{@"X-Custom":@"preserved"},@{@"User-Agent":nativeCache},
        @{@"uSeR-aGeNt":@"Explicit/1 Darwin/22.3.0",@"Accept-Language":@"fr-FR"},@{@"User-Agent":@""}];
    for(NSDictionary *headers in headerSets) {
        configuration.HTTPAdditionalHeaders=headers;
        for(unsigned active=0;active<2;active++) {
            transportEnabled=active;
            unsigned before=configurationCalls;
            shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
            assert(configurationCalls==before+1 && (received!=configuration)==active);
            assert([received.HTTPAdditionalHeaders isEqual:headers] && [configuration.HTTPAdditionalHeaders isEqual:headers]);
            if(active) assert([received.protocolClasses isEqual:@[NSURLProtocol.class]]);
        }
    }
    NSObject *delegate=[NSObject new];NSOperationQueue *queue=[NSOperationQueue new];
    shdw_network_session_delegate(NSURLSession.class,@selector(sessionWithConfiguration:delegate:delegateQueue:),configuration,(id)delegate,queue);
    assert(receivedDelegate==delegate && receivedQueue==queue && received!=configuration);
    assert([received.HTTPAdditionalHeaders isEqual:configuration.HTTPAdditionalHeaders]);
    for(unsigned mode=0;mode<3;mode++) {
        enabled=mode!=0;depth=mode==1?1:0;external=mode!=2;
        unsigned before=configurationCalls;
        shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
        assert(received==configuration && configurationCalls==before);
        shdw_network_session_delegate(NSURLSession.class,@selector(sessionWithConfiguration:delegate:delegateQueue:),configuration,(id)delegate,queue);
        assert(received==configuration && configurationCalls==before && receivedDelegate==delegate && receivedQueue==queue);
    }
    enabled=YES;external=YES;depth=0;
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),nil);assert(!received);
    RequestSessionDouble *shared=[RequestSessionDouble new];shared.configuration=configuration;
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://fixture.test/path"]];
    request.HTTPMethod=@"POST";request.HTTPBody=[@"payload" dataUsingEncoding:NSUTF8StringEncoding];request.timeoutInterval=73;
    for(NSDictionary *headers in headerSets) {
        request.allHTTPHeaderFields=headers;
        NSDictionary *originalHeaders=[request.allHTTPHeaderFields copy];
        for(unsigned active=0;active<2;active++) {
            transportEnabled=active;unsigned before=requestCalls;
            NSURLRequest *result=shdw_fingerprint_network_request((id)shared,request,(void *)1);
            assert(requestCalls==before+1 && (result!=request)==active);
            assert([result.allHTTPHeaderFields isEqual:originalHeaders] && [request.allHTTPHeaderFields isEqual:originalHeaders]);
            assert([result.HTTPBody isEqual:request.HTTPBody] && [result.HTTPMethod isEqual:@"POST"] && result.timeoutInterval==73);
            assert(([NSURLProtocol propertyForKey:@"transport.fixture" inRequest:result]!=nil)==active);
        }
    }
    for(unsigned mode=0;mode<3;mode++) {
        enabled=mode!=0;depth=mode==1?1:0;external=mode!=2;unsigned before=requestCalls;
        assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request && requestCalls==before);
    }
    enabled=YES;external=YES;depth=0;
    assert(!shdw_fingerprint_network_request((id)shared,nil,(void *)1));
    metadataFixture=@{@"CFBundleVersion":@"1404.0.5",@"CFBundleShortVersionString":@"1404.0.5",@"SignerIdentity":@"native-signer",@"Unrelated":@"preserved"};
    FixtureBundle *network=[FixtureBundle new];network.bundleIdentifier=@"com.apple.CFNetwork";
    FixtureBundle *app=[FixtureBundle new];app.bundleIdentifier=@"test.app";
    assert([bundleInfo(network)[@"CFBundleVersion"] isEqual:@"3826.600.41"]);
    assert([bundleValue(network,@"CFBundleShortVersionString") isEqual:@"3826.600.41"]);
    assert([bundleInfo(network)[@"Unrelated"] isEqual:@"preserved"] && bundleInfo(app)==metadataFixture);
    enabled=NO;assert(bundleInfo(network)==metadataFixture);enabled=YES;
    depth=1;assert(bundleInfo(network)==metadataFixture);depth=0;
    shdw_bundle_metadata_paths_enabled=YES;assert(!bundleInfo(app)[@"SignerIdentity"]);shdw_bundle_metadata_paths_enabled=NO;
    ChildSession *child=[ChildSession new];child.configuration=configuration;factoryResult=child;
    assert(shdw_network_shared_session(NSURLSession.class,@selector(sharedSession))==(id)child && concreteCalls==2);
    transportEnabled=NO;
    assert([child dataTaskWithRequest:request completionHandler:delegate]==child);
    assert(parentCalls==1 && childCalls==1 && receivedDelegate==delegate && (id)received==request);
    transportEnabled=YES;
    assert([child dataTaskWithRequest:request completionHandler:delegate]==child);
    assert(parentCalls==2 && childCalls==2 && (id)received!=request);
    assert([((NSURLRequest *)(id)received).allHTTPHeaderFields isEqual:request.allHTTPHeaderFields]);
    shdw_network_shared_session(NSURLSession.class,@selector(sharedSession));assert(concreteCalls==2);
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);assert(concreteCalls==2);
    assert([nativeCache isEqual:@"SDK%20Probe/1 CFNetwork/1404.0.5 Darwin/22.3.0"]);
    assert(sessionCalls>0 && !depth);
    shdw_network_session_state=0;installs=NO;
    shdw_universal_fingerprint_network_prepare(hooks);assert(shdw_network_session_state==3 && installCalls==6);
    shdw_universal_fingerprint_network_prepare(hooks);assert(installCalls==6);
    puts("fingerprint network: native/explicit/default headers unchanged, transport-only copies, dormant UA cache, metadata separation, caller scope and hook topology passed");
} }
"""
with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-network-") as tmp:
    source=Path(tmp)/"test.m"
    binary=Path(tmp)/"test"
    source.write_text(prefix+production+metadata+suffix)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",
        "-DSHADOW_CURL_IMPERSONATE=1","-fsanitize=address,undefined","-framework","Foundation",str(source),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
