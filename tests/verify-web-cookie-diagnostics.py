"""Verify observation-only WebKit/Foundation cookie diagnostics and forwarding."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
implementation = "\n".join(line for line in (root / "src/ShadowCore.dylib/policy/WebCookieDiagnostics.m").read_text().splitlines()
                           if not line.startswith("#import"))
source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <time.h>
static NSMutableArray *records;
static BOOL throwTrace;
static NSString *SHDWCurlDiagnosticString(NSString *value,NSUInteger limit){return value.length>limit?[value substringToIndex:limit]:value;}
static int64_t SHDWCurlDiagnosticMilliseconds(void){struct timespec value;assert(!clock_gettime(CLOCK_MONOTONIC,&value));return (int64_t)value.tv_sec*1000+value.tv_nsec/1000000;}
static void SHDWCurlTrace(NSString *stage,NSURLRequest *request,NSDictionary *details){
    if(throwTrace)[NSException raise:@"trace-fixture" format:@"fixture"];
    assert([NSJSONSerialization isValidJSONObject:details]);
    [records addObject:@{@"stage":stage,@"request":request ?: NSNull.null,@"details":details}];errno=E2BIG;
}
@interface SHDWHookSession:NSObject
@property(nonatomic) unsigned calls;
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original;
@end
@implementation SHDWHookSession
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original{
    Method method=class_getInstanceMethod(cls,selector);assert(method);*original=(void *)method_setImplementation(method,(IMP)replacement);self.calls++;errno=ENOSYS;return YES;
}
@end
@interface WKHTTPCookieStore:NSObject
@property(nonatomic,strong) NSHTTPCookie *lastCookie;
@property(nonatomic,copy) void (^pendingSet)(void);
@property(nonatomic,copy) void (^pendingGet)(NSArray *);
@property(nonatomic) unsigned setCalls,getCalls;
@property(nonatomic) BOOL sawNilCompletion,throwOnSet;
@property(nonatomic) int incomingErrno;
@property(nonatomic) const void *completionAddress;
- (void)setCookie:(NSHTTPCookie *)cookie completionHandler:(void (^)(void))completion;
- (void)getAllCookies:(void (^)(NSArray *))completion;
@end
@implementation WKHTTPCookieStore
- (void)setCookie:(NSHTTPCookie *)cookie completionHandler:(void (^)(void))completion{
    self.incomingErrno=errno;self.setCalls++;self.lastCookie=cookie;self.sawNilCompletion=completion==nil;
    self.completionAddress=(__bridge const void *)completion;self.pendingSet=completion;
    if(self.throwOnSet)[NSException raise:@"native-set-fixture" format:@"fixture"];
    errno=ENOSPC;
}
- (void)getAllCookies:(void (^)(NSArray *))completion {self.getCalls++;self.pendingGet=completion;errno=ERANGE;}
@end
@interface WKWebsiteDataStore:NSObject
@property(nonatomic,strong) WKHTTPCookieStore *httpCookieStore;
@property(nonatomic) BOOL persistent;
@end
@implementation WKWebsiteDataStore @end
@interface WKWebViewConfiguration:NSObject
@property(nonatomic,strong) WKWebsiteDataStore *websiteDataStore;
@end
@implementation WKWebViewConfiguration @end
@interface WKWebView:NSObject
@property(nonatomic,strong) WKWebViewConfiguration *configuration;
@property(nonatomic,strong) NSURL *URL;
@end
@implementation WKWebView @end
@interface FixtureCookieStorage:NSObject
@property(nonatomic,strong) NSArray *result;
@property(nonatomic,strong) NSURL *lastURL;
@property(nonatomic) unsigned calls;
@property(nonatomic) BOOL throwOnLookup;
+ (instancetype)sharedHTTPCookieStorage;
- (NSArray *)cookiesForURL:(NSURL *)url;
@end
static FixtureCookieStorage *sharedStorage;
@implementation FixtureCookieStorage
+ (instancetype)sharedHTTPCookieStorage{return sharedStorage;}
- (NSArray *)cookiesForURL:(NSURL *)url{
    self.calls++;self.lastURL=url;if(self.throwOnLookup)[NSException raise:@"native-lookup-fixture" format:@"fixture"];
    errno=ENOENT;return self.result;
}
@end
@interface InheritedCookieStorage:FixtureCookieStorage @end
@implementation InheritedCookieStorage @end
@interface ConcreteCookieStorage:InheritedCookieStorage
@property(nonatomic) unsigned concreteCalls;
@end
@implementation ConcreteCookieStorage
- (NSArray *)cookiesForURL:(NSURL *)url{self.concreteCalls++;return [super cookiesForURL:url];}
@end
@interface FixtureTask:NSObject
@property(nonatomic) unsigned unsafeGetterCalls;
@end
@implementation FixtureTask
- (NSURL *)_siteForCookies{return [NSURL URLWithString:@"https://www.vinted.fr/"];}
- (NSString *)_partitionIdentifier{return @"partition-fixture";}
- (NSString *)cookiePartitionIdentifier{return @"request-partition-fixture";}
- (NSUInteger)_cookiePartition{self.unsafeGetterCalls++;return 3;}
- (void *)_topLevelSiteForCookies{self.unsafeGetterCalls++;return NULL;}
@end
#define NSHTTPCookieStorage FixtureCookieStorage
''' + implementation + r'''
#undef NSHTTPCookieStorage
static NSHTTPCookie *makeCookie(NSString *name){return [NSHTTPCookie cookieWithProperties:@{
    NSHTTPCookieName:name,NSHTTPCookieValue:@"value-fixture",NSHTTPCookieDomain:@".vinted.fr",NSHTTPCookiePath:@"/",
    NSHTTPCookieSecure:@"TRUE",NSHTTPCookieExpires:[NSDate dateWithTimeIntervalSince1970:1900000000]}];}
int main(void){@autoreleasepool{
    records=[NSMutableArray new];sharedStorage=[FixtureCookieStorage new];SHDWHookSession *hooks=[SHDWHookSession new];
    errno=EBUSY;SHDWWebCookieDiagnosticsInstall(nil);assert(errno==EBUSY && !hooks.calls);
    SHDWWebCookieDiagnosticsInstall(hooks);assert(errno==EBUSY && hooks.calls==3);
    SHDWWebCookieDiagnosticsInstall(hooks);assert(errno==EBUSY && hooks.calls==3);
    SHDWHookSession *otherHooks=[SHDWHookSession new];SHDWWebCookieDiagnosticsInstall(otherHooks);assert(otherHooks.calls==0 && hooks.calls==3);
    NSHTTPCookie *datadome=makeCookie(@"datadome"),*other=makeCookie(@"other");assert(datadome && other);
    // A stored alternate must never replace the exact incoming cookie.
    NSHTTPCookie *alternate=makeCookie(@"datadome");sharedStorage.result=@[alternate];
    WKHTTPCookieStore *store=[WKHTTPCookieStore new];
    errno=EACCES;[store setCookie:datadome completionHandler:nil];assert(errno==ENOSPC);
    assert(store.setCalls==1 && store.lastCookie==datadome && store.lastCookie!=alternate && store.sawNilCompletion && !store.pendingSet && sharedStorage.calls==0);
    assert(records.count==2 && [records[0][@"stage"] isEqual:@"webview.cookie.set.before"] && [records[1][@"stage"] isEqual:@"webview.cookie.set.return"]);
    assert(store.incomingErrno==EACCES);
    __block unsigned completions=0;
    void (^completion)(void)=[^{assert(errno==EINTR);completions++;errno=EDOM;}copy];
    errno=EBUSY;[store setCookie:datadome completionHandler:completion];assert(errno==ENOSPC && store.incomingErrno==EBUSY);
    assert(completions==0 && records.count==4 && !store.sawNilCompletion && store.pendingSet);
    errno=EINTR;store.pendingSet();assert(errno==EDOM && completions==1 && records.count==5);
    assert([records.lastObject[@"stage"] isEqual:@"webview.cookie.set.ack"]);
    NSUInteger before=records.count;errno=EBUSY;[store setCookie:other completionHandler:completion];
    assert(errno==ENOSPC && store.lastCookie==other && records.count==before && store.completionAddress==(__bridge const void *)completion);
    store.throwOnSet=YES;BOOL threw=NO;
    @try{[store setCookie:datadome completionHandler:nil];}@catch(NSException *exception){threw=[exception.name isEqual:@"native-set-fixture"];}
    assert(threw);store.throwOnSet=NO;
    throwTrace=YES;errno=EIO;[store setCookie:datadome completionHandler:nil];assert(errno==ENOSPC && store.incomingErrno==EIO);throwTrace=NO;
    NSArray *original=@[other,datadome];
    for(Class cls in @[FixtureCookieStorage.class,InheritedCookieStorage.class,ConcreteCookieStorage.class]){
        FixtureCookieStorage *storage=[cls new];storage.result=original;before=records.count;
        NSURL *url=[NSURL URLWithString:@"https://www.vinted.fr/account"];
        errno=EBUSY;NSArray *returned=[storage cookiesForURL:url];assert(errno==ENOENT && returned==original && storage.lastURL==url && storage.calls==1);
        assert(records.count==before+1 && [records.lastObject[@"stage"] isEqual:@"webview.cookie.lookup"]);
        assert([records.lastObject[@"details"][@"datadomePresent"] boolValue] && [records.lastObject[@"details"][@"cookies"] count]==1);
        if([storage isKindOfClass:ConcreteCookieStorage.class])assert([(ConcreteCookieStorage *)storage concreteCalls]==1);
        before=records.count;[storage cookiesForURL:[NSURL URLWithString:@"https://not-vinted.example/"]];assert(records.count==before);
        storage.result=@[];[storage cookiesForURL:url];assert(![records.lastObject[@"details"][@"datadomePresent"] boolValue]);
        storage.throwOnLookup=YES;threw=NO;
        @try{[storage cookiesForURL:url];}@catch(NSException *exception){threw=[exception.name isEqual:@"native-lookup-fixture"];}
        assert(threw && cookieLookupDepth==0);
    }
    WKWebsiteDataStore *dataStore=[WKWebsiteDataStore new];dataStore.httpCookieStore=store;dataStore.persistent=YES;
    WKWebViewConfiguration *configuration=[WKWebViewConfiguration new];configuration.websiteDataStore=dataStore;
    WKWebView *view=[WKWebView new];view.configuration=configuration;view.URL=[NSURL URLWithString:@"https://www.vinted.fr/current"];
    NSURL *base=[NSURL URLWithString:@"https://www.vinted.fr/base"];before=records.count;unsigned sets=store.setCalls;
    errno=EACCES;SHDWWebCookieDiagnosticsObserveView(view,base,@"loadHTML");assert(errno==EACCES);
    assert(store.getCalls==1 && store.setCalls==sets && records.count==before+1 && store.pendingGet);
    NSDictionary *details=records.lastObject[@"details"];
    assert([details[@"persistent"] boolValue] && [details[@"baseURL"] isEqual:base.absoluteString] && [details[@"phase"] isEqual:@"loadHTML"]);
    assert([details[@"viewID"] length] && [details[@"websiteDataStoreID"] length] && [details[@"cookieStoreID"] length]);
    errno=EINTR;store.pendingGet(@[other,datadome]);assert(errno==EINTR && records.count==before+2);
    assert([records.lastObject[@"stage"] isEqual:@"webview.cookie.snapshot"] && [records.lastObject[@"details"][@"cookies"] count]==1);
    FixtureTask *task=[FixtureTask new];NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:base];request.mainDocumentURL=view.URL;
    before=records.count;errno=EBUSY;SHDWWebCookieDiagnosticsStored(request,(id)sharedStorage,(id)task,@[other,datadome]);assert(errno==EBUSY && records.count==before+1);
    details=records.lastObject[@"details"];
    assert([records.lastObject[@"stage"] isEqual:@"response.cookie.stored"] && [details[@"sharedMatch"] boolValue]);
    assert([details[@"requestContext"][@"mainDocumentURL"] isEqual:view.URL.absoluteString]);
    assert([details[@"taskContext"][@"_siteForCookies"] isEqual:@"https://www.vinted.fr/"] && [details[@"taskContext"][@"_partitionIdentifier"] isEqual:@"partition-fixture"]);
    assert([details[@"taskContext"][@"cookiePartitionIdentifier"] isEqual:@"request-partition-fixture"]);
    assert(task.unsafeGetterCalls==0 && !details[@"taskContext"][@"_cookiePartition"] && !details[@"taskContext"][@"_topLevelSiteForCookies"]);
    NSDictionary *attributes=details[@"cookies"][0];assert([attributes[@"name"] isEqual:@"datadome"] && [attributes[@"value"] isEqual:@"value-fixture"]);
    assert([attributes[@"secure"] boolValue]==datadome.secure && [attributes[@"expires"] doubleValue]==datadome.expiresDate.timeIntervalSince1970);
    before=records.count;SHDWWebCookieDiagnosticsStored(request,(id)sharedStorage,(id)task,@[other]);assert(records.count==before);
    SHDWWebCookieDiagnosticsObserveView(nil,nil,@"nil");assert(records.count==before);
    int64_t previous=-1;for(NSDictionary *record in records){int64_t value=[record[@"details"][@"monotonicMilliseconds"] longLongValue];assert(value>=previous);previous=value;}
    puts("web cookie diagnostics: native forwarding/nil completion, deferred acknowledgement, exact lookup result, inherited dedup, asynchronous store snapshot, native exceptions, object-only context ABI, cookie attributes and errno passed");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-web-cookie-diagnostics-") as directory:
    temporary=Path(directory);test,binary=temporary/"test.m",temporary/"check";test.write_text(source)
    subprocess.run(["xcrun","clang","-I",str(root / "src/Transport"),"-I",str(root / "src/ShadowCore.dylib/policy"),"-DSHDW_TRANSPORT_DIAGNOSTICS=1","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-DSHADOW_CURL_IMPERSONATE=1",
                    "-fsanitize=address,undefined","-framework","Foundation",str(test),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    disabled=r'''
#import <Foundation/Foundation.h>
@class WKWebView,SHDWHookSession;
'''+implementation+r'''
int main(void){@autoreleasepool{SHDWWebCookieDiagnosticsInstall(nil);SHDWWebCookieDiagnosticsObserveView(nil,nil,nil);SHDWWebCookieDiagnosticsStored(nil,nil,nil,nil);}return 0;}
'''
    test.write_text(disabled)
    subprocess.run(["xcrun","clang","-I",str(root / "src/Transport"),"-I",str(root / "src/ShadowCore.dylib/policy"),"-DSHDW_TRANSPORT_DIAGNOSTICS=1","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-DSHADOW_CURL_IMPERSONATE=0",
                    "-framework","Foundation",str(test),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
    symbols=subprocess.check_output(["nm","-u",str(binary)],text=True)
    assert "WebKit" not in symbols and "WKWebView" not in symbols and "WKHTTPCookieStore" not in symbols
