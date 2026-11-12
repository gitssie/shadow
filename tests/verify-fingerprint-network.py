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
if "--without-cached-default-fix" in sys.argv:
    production = production.replace("NSRange separator = NSMakeRange(NSNotFound, 0);",
        "if(present) return nil; NSRange separator = NSMakeRange(NSNotFound, 0);")
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
static unsigned depth, nativeCalls, installCalls, sessionCalls, concreteCalls, parentCalls, childCalls;
static id factoryResult;
static BOOL diagnosticSourceReady;
@interface SHDWFingerprintDiagnostics : NSObject
+ (void)recordNetworkUserAgentSourceReady:(BOOL)ready;
@end
@implementation SHDWFingerprintDiagnostics
+ (void)recordNetworkUserAgentSourceReady:(BOOL)ready { diagnosticSourceReady=ready; }
@end
static BOOL SHDWNetworkReplaceUserAgentCache(const void *getter,NSString *native,NSString *updated);
static void shdw_universal_url_session(id hooks) { (void)hooks; }
static void shdw_universal_bundle_metadata(id hooks) { (void)hooks; }
static BOOL shdw_bundle_metadata_paths_enabled;
static NSDictionary *metadataFixture;
static NSDictionary *nativeBundleInfo(void) { return metadataFixture; }
static id nativeBundleValue(NSString *key) { return metadataFixture[key]; }
#define isCallerExternal() (external && !depth)
static BOOL enabled=YES, external=YES, available=YES, installs=YES;
static void SHDWCurlTransportPrepare(void) {}
static NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration) { return configuration; }
static NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, id session) { (void)session;return request; }
static NSString *release=@"24.6.0", *nativeValue;
static BOOL sourcePublicationSucceeds;
static BOOL SHDWNetworkReplaceUserAgentCache(const void *getter,NSString *native,NSString *updated) {
    assert(getter && native && updated);
    if(!sourcePublicationSucceeds) return NO;
    nativeValue=updated;return YES;
}
static NSString *networkVersion=@"3826.600.41";
static NSString *SHDWFingerprintCFNetworkVersion(void) { assert(depth); return networkVersion; }
static NSURLSessionConfiguration *received;
static id receivedDelegate;
static NSOperationQueue *receivedQueue;
static BOOL shdw_fingerprint_is_enabled(void) { return enabled; }
static BOOL shdw_caller_is_external(const void *caller) { return caller && external && !depth; }
static const char *SHDWFingerprintVersionValue(const char *name) {
    assert(depth && !strcmp(name,"kern.osrelease")); return release.UTF8String;
}
static void leave(BOOL *active) { (void)active; assert(depth); depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leave)))=(++depth,YES); active; active=NO)
static CFStringRef nativeCopy(void) { nativeCalls++; assert(depth); return nativeValue ? (CFStringRef)CFBridgingRetain(nativeValue) : NULL; }
static NSURLSession *nativeSession(id self,SEL selector,NSURLSessionConfiguration *configuration) {
    (void)self;(void)selector;sessionCalls++;received=configuration;return (NSURLSession *)factoryResult;
}
static NSURLSession *nativeSessionDelegate(id self,SEL selector,NSURLSessionConfiguration *configuration,id delegate,NSOperationQueue *queue) {
    receivedDelegate=delegate;receivedQueue=queue;return nativeSession(self,selector,configuration);
}
static NSURLSession *nativeShared(id self,SEL selector) { (void)self;(void)selector;return (NSURLSession *)factoryResult; }
static void *networkSymbol(void *handle,const char *name) {
    (void)handle; assert(depth && !strcmp(name,"_CFNetworkCopyDefaultUserAgentString"));
    return available ? (void *)nativeCopy : NULL;
}
#define dlsym networkSymbol
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
    SessionDouble *session=[SessionDouble new];
    available=NO;enabled=NO;shdw_universal_fingerprint_network_prepare(session);
    assert(installCalls==0 && shdw_network_user_agent_state==0);enabled=YES;
    shdw_universal_fingerprint_network_prepare(session);
    assert(installCalls==3 && shdw_network_user_agent_state==2);
    NSURLSessionConfiguration *early=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),early);
    assert(received==early && nativeCalls==0);available=YES;shdw_network_user_agent_source_state=3;
    shdw_universal_fingerprint_network_prepare(session);assert(installCalls==3);
    nativeValue=@"Vinted/30260 CFNetwork/1404.0.5 Darwin/22.3.0";
    NSString *expected=@"Vinted/30260 CFNetwork/3826.600.41 Darwin/24.6.0";
    NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
    configuration.HTTPAdditionalHeaders=@{@"X-Custom":@"preserved"};
    for(unsigned mode=0;mode<4;mode++) {
        enabled=mode!=1;depth=mode==2?1:0;external=mode!=3;
        unsigned before=nativeCalls;
        shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
        if(mode==0) {
            assert(received!=configuration && [received.HTTPAdditionalHeaders[@"User-Agent"] isEqual:expected]);
            assert([received.HTTPAdditionalHeaders[@"X-Custom"] isEqual:@"preserved"]);
        }else assert(received==configuration);
        assert(nativeCalls==before+(mode==0) && depth==(mode==2?1:0));
        assert(!configuration.HTTPAdditionalHeaders[@"User-Agent"]);
    }
    enabled=YES;external=YES;depth=0;
    NSObject *delegate=[NSObject new];NSOperationQueue *queue=[NSOperationQueue new];
    shdw_network_session_delegate(NSURLSession.class,@selector(sessionWithConfiguration:delegate:delegateQueue:),configuration,(id)delegate,queue);
    assert(receivedDelegate==delegate && receivedQueue==queue && [received.HTTPAdditionalHeaders[@"User-Agent"] isEqual:expected]);
    configuration.HTTPAdditionalHeaders=@{@"user-agent":nativeValue,@"X-Custom":@"preserved"};
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
    assert(received!=configuration && [received.HTTPAdditionalHeaders[@"user-agent"] isEqual:expected]);
    assert(!received.HTTPAdditionalHeaders[@"User-Agent"] && [received.HTTPAdditionalHeaders[@"X-Custom"] isEqual:@"preserved"]);
    assert([configuration.HTTPAdditionalHeaders[@"user-agent"] isEqual:nativeValue]);
    configuration.HTTPAdditionalHeaders=@{@"uSeR-aGeNt":@"Explicit/1 Darwin/22.3.0"};
    unsigned before=nativeCalls;
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
    assert(received==configuration && nativeCalls==before);
    configuration.HTTPAdditionalHeaders=nil;
    for(NSString *value in @[@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0",
        @"Vinted/30260",@"Darwin/22.3.0suffix",@"Darwin/",@"NotDarwin/22.3.0",@""]) {
        nativeValue=value;
        shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
        assert(received==configuration);
    }
    nativeValue=@"SDK%20Probe/1 CFNetwork/1404.0.5 Darwin/22.3.0";
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
    assert([received.HTTPAdditionalHeaders[@"User-Agent"] isEqual:@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
    for(NSString *input in @[@"App/1 CFNetwork/1404.0.5 Darwin/24.6.0", @"App/1 CFNetwork/3826.600.41 Darwin/22.3.0"]) {
        depth=1;
        assert([shdw_network_user_agent(input) isEqual:@"App/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
        depth=0;
    }
    metadataFixture=@{@"CFBundleVersion":@"1404.0.5",@"CFBundleShortVersionString":@"1404.0.5",@"SignerIdentity":@"native-signer",@"Unrelated":@"preserved"};
    FixtureBundle *networkBundle=[FixtureBundle new];networkBundle.bundleIdentifier=@"com.apple.CFNetwork";
    FixtureBundle *appBundle=[FixtureBundle new];appBundle.bundleIdentifier=@"app.test";
    NSDictionary *info=bundleInfo(networkBundle);
    assert([info[@"CFBundleVersion"] isEqual:@"3826.600.41"] && [info[@"CFBundleShortVersionString"] isEqual:@"3826.600.41"]);
    assert([info[@"SignerIdentity"] isEqual:@"native-signer"] && [info[@"Unrelated"] isEqual:@"preserved"]);
    assert([bundleValue(networkBundle,@"CFBundleVersion") isEqual:@"3826.600.41"]);
    assert([bundleValue(networkBundle,@"CFBundleShortVersionString") isEqual:@"3826.600.41"]);
    assert(bundleInfo(appBundle)==metadataFixture && [metadataFixture[@"CFBundleVersion"] isEqual:@"1404.0.5"]);
    enabled=NO;assert(bundleInfo(networkBundle)==metadataFixture);enabled=YES;
    depth=1;assert(bundleInfo(networkBundle)==metadataFixture);depth=0;
    shdw_bundle_metadata_paths_enabled=YES;
    assert(!bundleInfo(appBundle)[@"SignerIdentity"] && !bundleValue(appBundle,@"SignerIdentity"));
    shdw_bundle_metadata_paths_enabled=NO;
    assert([bundleValue(appBundle,@"SignerIdentity") isEqual:@"native-signer"]);
    RequestSessionDouble *shared=[RequestSessionDouble new];shared.configuration=configuration;
    NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"http://127.0.0.1/sdk/"]];
    request.HTTPMethod=@"POST";request.HTTPBody=[@"payload=preserved" dataUsingEncoding:NSUTF8StringEncoding];
    request.timeoutInterval=73;[request setValue:@"preserved" forHTTPHeaderField:@"X-Custom"];
    NSURLRequest *updated=shdw_fingerprint_network_request((id)shared,request,(void *)1);
    assert(updated!=request && [updated valueForHTTPHeaderField:@"User-Agent"]);
    assert([[updated valueForHTTPHeaderField:@"User-Agent"] isEqual:@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
    assert([updated.HTTPBody isEqual:request.HTTPBody] && [updated.HTTPMethod isEqual:@"POST"] && updated.timeoutInterval==73);
    assert([[updated valueForHTTPHeaderField:@"X-Custom"] isEqual:@"preserved"] && ![request valueForHTTPHeaderField:@"User-Agent"]);
    for(unsigned mode=0;mode<3;mode++) {
        enabled=mode!=0;depth=mode==1?1:0;external=mode!=2;
        assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    }
    enabled=YES;depth=0;external=YES;
    [request setValue:@"ExplicitRequest/1" forHTTPHeaderField:@"User-Agent"];
    assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    [request setValue:nil forHTTPHeaderField:@"User-Agent"];
    configuration.HTTPAdditionalHeaders=@{@"user-agent":@"ExplicitSession/1"};
    assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    configuration.HTTPAdditionalHeaders=nil;
    assert(!shdw_fingerprint_network_request((id)shared,nil,(void *)1));
    NSArray *cached=@[nativeValue,@"SDK%20Probe/1 CFNetwork/1404.0.5 Darwin/24.6.0",@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/22.3.0"];
    for(NSString *value in cached) {
        [request setValue:value forHTTPHeaderField:@"User-Agent"];
        NSURLRequest *fixed=shdw_fingerprint_network_request((id)shared,request,(void *)1);
        assert(fixed!=request && [[fixed valueForHTTPHeaderField:@"User-Agent"] isEqual:@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
        assert([[request valueForHTTPHeaderField:@"User-Agent"] isEqual:value] && [fixed.HTTPBody isEqual:request.HTTPBody]);
    }
    for(NSString *value in @[@"Other/1 CFNetwork/1404.0.5 Darwin/22.3.0",@"SDK%20Probe/1 CFNetwork/1404.0.5 Darwin/22.3.0 Custom/1",@"ExplicitRequest/1",@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]) {
        [request setValue:value forHTTPHeaderField:@"User-Agent"];
        assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    }
    configuration.HTTPAdditionalHeaders=@{@"User-Agent":nativeValue};
    [request setValue:@"ExplicitRequest/1" forHTTPHeaderField:@"User-Agent"];
    assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    [request setValue:nil forHTTPHeaderField:@"User-Agent"];
    NSURLRequest *fromSession=shdw_fingerprint_network_request((id)shared,request,(void *)1);
    assert(fromSession!=request && [[fromSession valueForHTTPHeaderField:@"User-Agent"] isEqual:@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
    assert([configuration.HTTPAdditionalHeaders[@"User-Agent"] isEqual:nativeValue]);
    configuration.HTTPAdditionalHeaders=@{@"User-Agent":@""};
    assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    configuration.HTTPAdditionalHeaders=nil;
    ChildSession *child=[ChildSession new];child.configuration=configuration;
    factoryResult=child;
    assert(shdw_network_shared_session(NSURLSession.class,@selector(sharedSession))==(id)child);
    assert(concreteCalls==2);
    assert([child dataTaskWithRequest:request completionHandler:delegate]==child);
    assert(parentCalls==1 && childCalls==1 && receivedDelegate==delegate);
    assert([[(NSURLRequest *)(id)received valueForHTTPHeaderField:@"User-Agent"] isEqual:@"SDK%20Probe/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
    assert(![request valueForHTTPHeaderField:@"User-Agent"]);
    shdw_network_shared_session(NSURLSession.class,@selector(sharedSession));assert(concreteCalls==2);
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);assert(concreteCalls==2);
    factoryResult=nil;
    release=nil;
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);assert(received==configuration);
    nativeValue=nil;
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);assert(received==configuration);
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),nil);assert(received==nil);
    release=@"24.6.0";nativeValue=@"Source/1 CFNetwork/1404.0.5 Darwin/22.3.0";
    sourcePublicationSucceeds=YES;shdw_network_user_agent_source_state=0;
    shdw_network_prepare_user_agent_source();
    assert(diagnosticSourceReady && shdw_network_user_agent_source_state==2 && [nativeValue isEqual:@"Source/1 CFNetwork/3826.600.41 Darwin/24.6.0"]);
    shdw_network_session(NSURLSession.class,@selector(sessionWithConfiguration:),configuration);
    assert(received==configuration && !configuration.HTTPAdditionalHeaders[@"User-Agent"]);
    assert(shdw_fingerprint_network_request((id)shared,request,(void *)1)==request);
    __atomic_store_n(&shdw_native_network_user_agent,NULL,__ATOMIC_RELEASE);
    shdw_network_user_agent_source_state=0;available=NO;
    shdw_network_prepare_user_agent_source();assert(shdw_network_user_agent_source_state==0);
    available=YES;shdw_network_prepare_user_agent_source();assert(shdw_network_user_agent_source_state==2);
    assert(sessionCalls>0);
    shdw_network_user_agent_state=0;installs=NO;
    shdw_universal_fingerprint_network_prepare(session);
    assert(shdw_network_user_agent_state==3 && installCalls==6);
    shdw_universal_fingerprint_network_prepare(session);assert(installCalls==6);
    puts("fingerprint network: default-UA session boundary, explicit headers, caller scope and configuration copy passed");
} }
"""
with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-network-") as tmp:
    source=Path(tmp)/"test.m"
    binary=Path(tmp)/"test"
    source.write_text(prefix+production+metadata+suffix)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror",
        "-fsanitize=address,undefined","-framework","Foundation",str(source),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
