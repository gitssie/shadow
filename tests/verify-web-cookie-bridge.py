"""Verify the temporary App cookie selector reuses original storage without rewriting cookies."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include "WebCookieBridge.h"
@interface OriginalCookieStorage : NSHTTPCookieStorage
@property(nonatomic,strong) NSArray<NSHTTPCookie *> *results;
@property(nonatomic,strong) NSArray<NSHTTPCookie *> *lastReturned;
@property(nonatomic,strong) NSHTTPCookieStorage *nativeBacking;
@property(nonatomic,strong) NSURL *queriedURL;
@property(nonatomic) NSUInteger reads,allReads,writes;
@end
@implementation OriginalCookieStorage
- (NSArray<NSHTTPCookie *> *)cookiesForURL:(NSURL *)url {
    self.reads++;self.queriedURL=url;
    self.lastReturned=self.nativeBacking ? [self.nativeBacking cookiesForURL:url] : self.results;
    return self.lastReturned;
}
- (NSArray<NSHTTPCookie *> *)cookies { self.allReads++;return self.results; }
- (void)setCookie:(NSHTTPCookie *)cookie { (void)cookie;self.writes++; }
- (void)setCookies:(NSArray<NSHTTPCookie *> *)cookies forURL:(NSURL *)url mainDocumentURL:(NSURL *)main {
    (void)cookies;(void)url;(void)main;self.writes++;
}
- (void)storeCookies:(NSArray<NSHTTPCookie *> *)cookies forTask:(NSURLSessionTask *)task {
    (void)cookies;(void)task;self.writes++;
}
@end
static NSHTTPCookie *makeCookie(NSString *name,NSString *value,NSString *domain,NSString *path,NSDate *expiry) {
    NSMutableDictionary *properties=[@{NSHTTPCookieName:name,NSHTTPCookieValue:value,
        NSHTTPCookieDomain:domain,NSHTTPCookiePath:path,NSHTTPCookieSecure:@"TRUE"} mutableCopy];
    if(expiry)properties[NSHTTPCookieExpires]=expiry;
    NSHTTPCookie *cookie=[NSHTTPCookie cookieWithProperties:properties];assert(cookie);return cookie;
}
static void queriedOnce(OriginalCookieStorage *storage) {
    assert(storage.reads==1 && !storage.allReads && !storage.writes);
    assert([storage.queriedURL.absoluteString isEqual:@"https://www.vinted.com/"]);
}
static void reset(OriginalCookieStorage *storage) {
    storage.reads=0;storage.allReads=0;storage.writes=0;storage.queriedURL=nil;storage.lastReturned=nil;
}
static void unchanged(NSHTTPCookie *candidate,OriginalCookieStorage *storage,NSString *bundle,BOOL query) {
    reset(storage);
    NSDictionary *before=[candidate.properties copy];
    assert(SHDWWebCookieBridgeSelect(candidate,storage,bundle)==candidate);
    if(candidate)assert([candidate.properties isEqual:before]);
    if(query)queriedOnce(storage);else assert(!storage.reads && !storage.allReads && !storage.writes);
}
int main(void) { @autoreleasepool {
    NSString *bundle=@"lt.manodrabuziai.fr";
    NSHTTPCookie *wrong=makeCookie(@"datadome",@"facebook-value",@".facebook.com",@"/",nil);
    NSHTTPCookie *right=makeCookie(@"datadome",@"vinted-value",@".vinted.com",@"/",nil);
    NSHTTPCookie *unrelated=makeCookie(@"other",@"other-value",@".vinted.com",@"/",nil);
    OriginalCookieStorage *storage=[OriginalCookieStorage new];storage.results=@[unrelated,right];
    NSDictionary *wrongBefore=[wrong.properties copy],*rightBefore=[right.properties copy];
    NSHTTPCookie *selected=SHDWWebCookieBridgeSelect(wrong,storage,bundle);
    assert(selected==right && [selected.value isEqual:@"vinted-value"] && [selected.domain isEqual:right.domain]);
    assert([wrong.properties isEqual:wrongBefore] && [right.properties isEqual:rightBefore]);queriedOnce(storage);
    for(NSString *other in @[@"other.app",@"lt.manodrabuziai.fr.suffix",@""])
        unchanged(wrong,storage,other,NO);
    unchanged(wrong,storage,nil,NO);
    unchanged(unrelated,storage,bundle,NO);
    unchanged(makeCookie(@"DataDome",@"case-sensitive",@".facebook.com",@"/",nil),storage,bundle,NO);
    reset(storage);assert(SHDWWebCookieBridgeSelect(nil,storage,bundle)==nil && !storage.reads && !storage.writes);
    assert(SHDWWebCookieBridgeSelect(wrong,nil,bundle)==wrong);
    // Every datadome candidate in the target App consults the original URL API,
    // including candidates already belonging to the target domain.
    for(NSString *domain in @[@"vinted.com",@".vinted.com",@"www.vinted.com",@".sub.vinted.com",@"notvinted.com",@"vinted.com.evil.example"]) {
        reset(storage);NSHTTPCookie *candidate=makeCookie(@"datadome",@"candidate-value",domain,@"/",nil);
        NSDictionary *before=[candidate.properties copy];
        assert(SHDWWebCookieBridgeSelect(candidate,storage,bundle)==right);queriedOnce(storage);
        assert([candidate.properties isEqual:before]);
    }
    // Preserve the original API's order and exact cookie object; do not add a
    // separate root-domain filter after native URL filtering.
    NSHTTPCookie *hostOnly=makeCookie(@"datadome",@"host-only-value",@"www.vinted.com",@"/",nil);
    storage.results=@[unrelated,hostOnly,right];reset(storage);
    assert(SHDWWebCookieBridgeSelect(right,storage,bundle)==hostOnly);queriedOnce(storage);
    storage.results=@[];unchanged(wrong,storage,bundle,YES);unchanged(right,storage,bundle,YES);
    storage.results=@[unrelated];unchanged(wrong,storage,bundle,YES);
    // Real Foundation supplies domain/secure/expiry/path filtering for the exact
    // HTTPS URL. Host-only www.vinted.com is valid and must remain eligible.
    for(NSString *kind in @[@"valid",@"expired",@"path",@"subdomain",@"other-domain"]) {
        NSURLSessionConfiguration *configuration=NSURLSessionConfiguration.ephemeralSessionConfiguration;
        NSHTTPCookieStorage *native=configuration.HTTPCookieStorage;
        NSDate *expiry=[NSDate dateWithTimeIntervalSinceNow:[kind isEqual:@"expired"] ? -3600 : 3600];
        NSString *domain=[kind isEqual:@"subdomain"] ? @"www.vinted.com" : ([kind isEqual:@"other-domain"] ? @".facebook.com" : @".vinted.com");
        NSHTTPCookie *cookie=makeCookie(@"datadome",@"native-storage-value",domain,[kind isEqual:@"path"] ? @"/login" : @"/",expiry);
        [native setCookie:cookie];
        storage.nativeBacking=native;reset(storage);
        NSDictionary *before=[cookie.properties copy];
        NSHTTPCookie *result=SHDWWebCookieBridgeSelect(wrong,storage,bundle);
        queriedOnce(storage);assert([cookie.properties isEqual:before]);
        NSHTTPCookie *first=nil;for(NSHTTPCookie *item in storage.lastReturned)if([item.name isEqual:@"datadome"]){first=item;break;}
        if([kind isEqual:@"valid"] || [kind isEqual:@"subdomain"]) {
            assert(first && result==first && [result.value isEqual:@"native-storage-value"] && result.isSecure);
        } else assert(!first && result==wrong);
        [native removeCookiesSinceDate:NSDate.distantPast];
    }
    puts("web cookie bridge: target App/name scope, always prefer first native URL-cookie object, no rewrite/store, exact HTTPS query, no-match identity and native secure/expired/path/domain controls passed");
} }

'''
with tempfile.TemporaryDirectory(prefix="shadow-web-cookie-bridge-") as directory:
    temporary = Path(directory)
    test, binary = temporary / "test.m", temporary / "check"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "-framework", "Foundation", "-I", str(root / "src/ShadowCore.dylib/policy"), str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
