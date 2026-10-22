"""Exercise production receipt policy, proxy and hook bodies without StoreKit RPCs."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
policy = (root / "src/ShadowCore.dylib/policy/ReceiptPolicy.m").read_text().replace('#import "ReceiptPolicy.h"', '')
source = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintReceipts.x").read_text()
proxy = "\n".join(line for line in source[:source.index("%group")].splitlines() if not line.startswith("#import"))
bundle_start = source.index("%hook NSBundle") + len("%hook NSBundle")
bundle = source[bundle_start:source.index("%end", bundle_start)]
bundle = bundle.replace("%orig", "[self nativeReceiptURL]").replace("NSBundle.mainBundle", "fakeMainBundle")
broker_start = source.index("%hook SKServiceBroker") + len("%hook SKServiceBroker")
broker = source[broker_start:source.index("%end", broker_start)].replace("%orig(handler)", "[self nativeServiceWithHandler:handler]")
core = (root / "src/Shadow.framework/Core.m").read_text()
def method(text, signature):
    start = text.index(signature)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        if text[end] == "{": depth += 1
        elif text[end] == "}": depth -= 1
        end += 1
    return text[start:end]
receipt_init = method(source, "void shdw_universal_fingerprint_receipts(SHDWHookSession *hooks)")
assert "shdw_receipts_enabled = SHDWFingerprintInterceptsReceipts();" in receipt_init
assert "if(!shdw_receipts_enabled) return;" in receipt_init
core_methods = method(core, "+ (void)shdwSetReceiptPathPredicate:") + "\n" + method(core, "+ (BOOL)shdwIsReceiptPathRestricted:")
engine = (root / "src/Shadow.framework/RestrictionEngine.m").read_text()
query = method(engine, "- (BOOL)_pathRestrictedQuery:")
assert query.index("shdwReceiptPathRestricted(path.fileSystemRepresentation)") < query.index("if (lastValid")
path_policy = (root / "src/ShadowCore.dylib/policy/PathPolicy.m").read_text()
lexical = method(path_policy, "BOOL shdw_path_is_external_hidden_lexical(")
assert lexical.index("shdw_standardize_lexical") < lexical.index("shdw_fingerprint_receipt_path_is_restricted")
exemption = method(path_policy, "BOOL shdw_path_is_main_bundle_exempt(")
assert exemption.index("shdw_fingerprint_receipt_path_is_restricted") < exemption.index("static NSString *cachedBundle")
prefix = r'''
#import <Foundation/Foundation.h>
#include <objc/runtime.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
static long failAt = -1, allocations;
static BOOL failAllocation(void) { return allocations++ == failAt; }
static void *faultMalloc(size_t n) { return failAllocation() ? NULL : malloc(n); }
static void *faultCalloc(size_t n, size_t s) { return failAllocation() ? NULL : calloc(n,s); }
static char *faultStrdup(const char *s) { return failAllocation() ? NULL : strdup(s); }
#define malloc faultMalloc
#define calloc faultCalloc
#define strdup faultStrdup
'''
middle = r'''
#undef malloc
#undef calloc
#undef strdup
typedef BOOL (*SHDWReceiptPathPredicate)(const char *);
static _Atomic(SHDWReceiptPathPredicate) shdw_receipt_path_predicate;
@interface Shadow : NSObject
+ (void)shdwSetReceiptPathPredicate:(BOOL (*)(const char *))predicate;
+ (BOOL)shdwIsReceiptPathRestricted:(const char *)path;
@end
static unsigned internalDepth;
static BOOL externalCaller = YES;
static BOOL isCallerExternal(void) { return externalCaller && !internalDepth; }
static NSUInteger shdwInternalBusy(void) { return internalDepth; }
static NSMutableArray *tasks;
static unsigned scheduled;
static void fakeAsync(dispatch_queue_t queue, dispatch_block_t block) {
    assert(queue == dispatch_get_main_queue()); scheduled++; [tasks addObject:[block copy]];
}
#define dispatch_async fakeAsync
@interface FakeBundle : NSObject
@property(nonatomic, strong) NSURL *nativeURL;
@property(nonatomic) unsigned nativeCalls;
- (NSURL *)nativeReceiptURL;
@end
@implementation FakeBundle
- (NSURL *)nativeReceiptURL { _nativeCalls++; return _nativeURL; }
@end
static FakeBundle *fakeMainBundle;
@protocol PurchaseProtocol <NSObject>
- (NSString *)purchaseProduct:(NSString *)product;
@end
@interface NativeService : NSObject <PurchaseProtocol>
@property(nonatomic) unsigned purchaseCalls, appCalls, renewCalls;
@end
@implementation NativeService
- (NSString *)purchaseProduct:(NSString *)product { _purchaseCalls++; return product; }
- (NSRange)rangeForNumber:(NSUInteger)value { return NSMakeRange(value, value + 1); }
- (void)appTransactionForClient:(NSDictionary *)client ignoreCache:(BOOL)ignoreCache reply:(void (^)(NSString *, NSError *))reply {
    (void)client; (void)ignoreCache; _appCalls++; if(reply) reply(@"native", nil);
}
- (void)renewReceiptWithOptions:(NSDictionary *)options client:(NSDictionary *)client replyBlock:(void (^)(BOOL, NSError *))reply {
    (void)options; (void)client; _renewCalls++; if(reply) reply(YES,nil);
}
@end
@interface FakeBroker : NSObject
@property(nonatomic, strong) id target;
@property(nonatomic, copy) void (^nativeHandler)(NSError *);
@property(nonatomic) unsigned nativeCalls;
- (id)nativeServiceWithHandler:(void (^)(NSError *))handler;
@end
@implementation FakeBroker
- (id)nativeServiceWithHandler:(void (^)(NSError *))handler { _nativeCalls++; _nativeHandler = handler; return _target; }
@end
'''
suffix = r'''
static void resetPaths(void) {
    SHDWReceiptPaths *paths = atomic_exchange_explicit(&shdw_receipt_paths, NULL, memory_order_acq_rel);
    if(paths) { free(paths->path); free(paths->alias); free(paths); }
    failAt = -1; allocations = 0;
}
static void drain(void) {
    assert(NSThread.isMainThread);
    while(tasks.count) { @autoreleasepool {
        dispatch_block_t block = tasks[0]; [tasks removeObjectAtIndex:0]; block();
    } }
}
static id nilProxyAlloc(id self, SEL selector) { (void)self; (void)selector; return nil; }
static void verifyPolicy(void) {
    resetPaths(); assert(!SHDWReceiptPathMatches(NULL) && !SHDWReceiptPathMatches("/var/missing"));
    SHDWReceiptCaptureURL(nil); SHDWReceiptCaptureURL([NSURL URLWithString:@"https://example.invalid/receipt"]);
    assert(!atomic_load(&shdw_receipt_paths));
    for(NSString *path in @[@"/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt",
        @"/private/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"]) {
        resetPaths(); SHDWReceiptCaptureURL([NSURL fileURLWithPath:path]);
        assert(SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"));
        assert(SHDWReceiptPathMatches("/private/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"));
        assert(!SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt2"));
        assert(!SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt/child"));
        assert(!SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app.other/_MASReceipt/receipt"));
        assert(!SHDWReceiptPathMatches("/var/containers/Bundle/Application/Other.app/_MASReceipt/receipt"));
        assert(SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/./_MASReceipt/receipt"));
        assert(SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/other/../_MASReceipt/receipt"));
        assert(SHDWReceiptPathMatches("/var//containers/Bundle/Application/Test.app/_MASReceipt/receipt"));
        assert(!SHDWReceiptPathMatches("/var/containers/Bundle/Application/Test.app/../Other.app/_MASReceipt/receipt"));
    }
    NSURL *url = [NSURL fileURLWithPath:@"/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"];
    resetPaths(); SHDWReceiptCaptureURL(url); long total = allocations; assert(total == 3);
    for(long i=0;i<total;i++) {
        resetPaths(); failAt=i; SHDWReceiptCaptureURL(url);
        assert(!atomic_load(&shdw_receipt_paths));
        failAt=-1; SHDWReceiptCaptureURL(url); assert(SHDWReceiptPathMatches(url.path.fileSystemRepresentation));
        assert(SHDWReceiptPathMatches("/private/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"));
    }
    resetPaths(); SHDWReceiptCaptureURL([NSURL fileURLWithPath:@"/Applications/Test.app/receipt"]);
    assert(SHDWReceiptPathMatches("/Applications/Test.app/receipt") && !SHDWReceiptPathMatches("/Applications/Test.app/receipt2"));
    SHDWReceiptCaptureURL(url); assert(!SHDWReceiptPathMatches(url.path.fileSystemRepresentation));
    resetPaths(); SHDWReceiptCaptureURL(url);
    [Shadow shdwSetReceiptPathPredicate:NULL]; assert(![Shadow shdwIsReceiptPathRestricted:url.path.fileSystemRepresentation]);
    [Shadow shdwSetReceiptPathPredicate:shdw_fingerprint_receipt_path_is_restricted];
    shdw_receipts_enabled=NO; assert(![Shadow shdwIsReceiptPathRestricted:url.path.fileSystemRepresentation]);
    shdw_receipts_enabled=YES; assert([Shadow shdwIsReceiptPathRestricted:url.path.fileSystemRepresentation]);
}
static void verifyHooks(void) {
    resetPaths(); shdw_receipts_enabled=YES;
    fakeMainBundle=[FakeBundle new]; fakeMainBundle.nativeURL=[NSURL fileURLWithPath:@"/var/containers/Bundle/Application/Test.app/_MASReceipt/receipt"];
    assert(![fakeMainBundle appStoreReceiptURL] && fakeMainBundle.nativeCalls==1);
    assert(SHDWReceiptPathMatches(fakeMainBundle.nativeURL.path.fileSystemRepresentation));
    FakeBundle *other=[FakeBundle new]; other.nativeURL=[NSURL fileURLWithPath:@"/var/Other.bundle/receipt"];
    assert([other appStoreReceiptURL]==other.nativeURL && !SHDWReceiptPathMatches(other.nativeURL.path.fileSystemRepresentation));
    internalDepth=2; assert([fakeMainBundle appStoreReceiptURL]==fakeMainBundle.nativeURL && internalDepth==2); internalDepth=0;
    externalCaller=NO; assert([fakeMainBundle appStoreReceiptURL]==fakeMainBundle.nativeURL); externalCaller=YES;
    shdw_receipts_enabled=NO; assert([fakeMainBundle appStoreReceiptURL]==fakeMainBundle.nativeURL); shdw_receipts_enabled=YES;
    FakeBroker *broker=[FakeBroker new]; NativeService *target=[NativeService new]; broker.target=target;
    __block unsigned handlerCalls=0; void (^handler)(NSError *)=^(NSError *error){ assert(error); handlerCalls++; };
    id proxy=[broker storeKitServiceWithErrorHandler:handler];
    assert(proxy && proxy!=target && broker.nativeCalls==1 && !handlerCalls);
    assert([SHDWReceiptServiceProxy proxyWithTarget:proxy]==proxy && ![SHDWReceiptServiceProxy proxyWithTarget:nil]);
    assert([proxy respondsToSelector:@selector(appTransactionForClient:ignoreCache:reply:)]);
    assert([proxy respondsToSelector:@selector(renewReceiptWithOptions:client:replyBlock:)]);
    assert([proxy conformsToProtocol:@protocol(PurchaseProtocol)] && [proxy isKindOfClass:NativeService.class]);
    assert([proxy class]==target.class && ![proxy respondsToSelector:NSSelectorFromString(@"missingSelector")]);
    assert([[proxy purchaseProduct:@"product"] isEqual:@"product"] && target.purchaseCalls==1);
    NSRange range=[proxy rangeForNumber:19]; assert(range.location==19 && range.length==20);
    __block unsigned appReplies=0, renewReplies=0;
    [proxy appTransactionForClient:@{} ignoreCache:NO reply:^(NSString *transaction,NSError *error){
        assert(!transaction && [error.domain isEqual:@"SKErrorDomain"] && error.code==0); appReplies++;
    }];
    [proxy appTransactionForClient:@{} ignoreCache:YES reply:^(NSString *transaction,NSError *error){ assert(!transaction && error); appReplies++; }];
    [proxy renewReceiptWithOptions:@{} client:@{} replyBlock:^(BOOL success,NSError *error){ assert(!success && error); renewReplies++; }];
    assert(!appReplies && !renewReplies && tasks.count==3 && !target.appCalls && !target.renewCalls && !handlerCalls);
    drain(); assert(appReplies==2 && renewReplies==1 && !tasks.count); drain(); assert(appReplies==2 && renewReplies==1);
    unsigned before=scheduled;
    [proxy appTransactionForClient:nil ignoreCache:NO reply:nil]; [proxy renewReceiptWithOptions:nil client:nil replyBlock:nil];
    assert(scheduled==before && !handlerCalls && !target.appCalls && !target.renewCalls);
    __block unsigned nativeReplies=0;
    shdw_receipts_enabled=NO;
    [proxy appTransactionForClient:nil ignoreCache:NO reply:^(NSString *transaction,NSError *error){
        assert([transaction isEqual:@"native"] && !error); nativeReplies++;
    }];
    [proxy renewReceiptWithOptions:nil client:nil replyBlock:^(BOOL success,NSError *error){
        assert(success && !error); nativeReplies++;
    }];
    assert(nativeReplies==2 && scheduled==before && target.appCalls==1 && target.renewCalls==1);
    shdw_receipts_enabled=YES; internalDepth=2;
    [proxy appTransactionForClient:nil ignoreCache:YES reply:^(NSString *transaction,NSError *error){
        assert([transaction isEqual:@"native"] && !error && internalDepth==2); nativeReplies++;
    }];
    [proxy renewReceiptWithOptions:nil client:nil replyBlock:^(BOOL success,NSError *error){
        assert(success && !error && internalDepth==2); nativeReplies++;
    }];
    assert(nativeReplies==4 && scheduled==before && internalDepth==2);
    internalDepth=0;
    broker.nativeHandler(SHDWReceiptUnavailableError()); assert(handlerCalls==1);
    shdw_receipts_enabled=NO; assert([broker storeKitServiceWithErrorHandler:handler]==target); shdw_receipts_enabled=YES;
    internalDepth=2; assert([broker storeKitServiceWithErrorHandler:handler]==target && internalDepth==2); internalDepth=0;
    broker.target=nil; assert(![broker storeKitServiceWithErrorHandler:handler]); broker.target=target;
    Class meta=object_getClass(SHDWReceiptServiceProxy.class); SEL allocation=@selector(alloc);
    IMP original=class_getMethodImplementation(meta,allocation);
    class_replaceMethod(meta,allocation,(IMP)nilProxyAlloc,method_getTypeEncoding(class_getClassMethod(SHDWReceiptServiceProxy.class,allocation)));
    @try { assert((id)[SHDWReceiptServiceProxy proxyWithTarget:target]==target); }
    @finally { class_replaceMethod(meta,allocation,original,"@16@0:8"); }
}
static void verifyLifetime(void) {
    __weak NativeService *weakTarget;
    __attribute__((objc_precise_lifetime)) id proxy;
    @autoreleasepool { NativeService *target=[NativeService new]; weakTarget=target; proxy=[SHDWReceiptServiceProxy proxyWithTarget:target]; }
    assert(proxy && weakTarget); proxy=nil; assert(!weakTarget);
    __block unsigned replies=0; __weak NSObject *weakMarker;
    @autoreleasepool {
        NSObject *marker=[NSObject new]; weakMarker=marker;
        id service=[SHDWReceiptServiceProxy proxyWithTarget:[NativeService new]];
        [service appTransactionForClient:nil ignoreCache:NO reply:^(NSString *transaction,NSError *error){ assert(marker && !transaction && error); replies++; }];
    }
    assert(weakMarker && !replies); drain(); assert(replies==1 && !weakMarker);
}
int main(void) { @autoreleasepool {
    tasks=[NSMutableArray new]; verifyPolicy(); verifyHooks(); verifyLifetime(); resetPaths();
    [Shadow shdwSetReceiptPathPredicate:NULL];
    puts("receipts: production policy/proxy/hooks, aliases, OOM, async typed replies, forwarding and ownership passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-receipts-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + policy + middle + "\n@implementation Shadow\n" + core_methods + "\n@end\n" + proxy +
        "\n@implementation FakeBundle (Hooks)\n" + bundle + "\n@end\n@implementation FakeBroker (Hooks)\n" + broker + "\n@end\n" + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-variable", "-Wno-unused-parameter", "-fsanitize=address,undefined",
        "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
