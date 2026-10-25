#!/usr/bin/env python3
"""Exercise production IP switching with NSURLProtocol fixtures; never use live networking."""
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r"""
#import <Foundation/Foundation.h>
#import "IPSwitchService.h"
NSString *SHDWLocalizedText(NSString *key) { return key; }
static NSMutableDictionary *routes;
static NSMutableArray *requests;
static NSMutableArray *lookupStartTimes;
static BOOL unexpected;
static void Require(BOOL value, NSString *message) { if (!value) { NSLog(@"FAIL: %@", message); exit(1); } }
static NSString *Route(NSURL *url) {
    if ([url.host isEqual:@"ipv4.is"]) return @"v4";
    if ([url.host isEqual:@"ipwho.is"]) return @"who";
    return [@"action:" stringByAppendingString:url.absoluteString];
}
@interface FixtureProtocol : NSURLProtocol @end
@implementation FixtureProtocol
+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return YES; }
+ (NSURLRequest *)canonicalRequestForRequest:(NSURLRequest *)request { return request; }
- (void)startLoading {
    NSDictionary *step;
    @synchronized(FixtureProtocol.class) {
        [requests addObject:self.request.URL.absoluteString];
        if ([Route(self.request.URL) isEqual:@"who"]) [lookupStartTimes addObject:@(NSDate.timeIntervalSinceReferenceDate)];
        NSMutableArray *queue = routes[Route(self.request.URL)];
        if (!queue.count) { unexpected = YES; step = @{@"error":@(NSURLErrorNetworkConnectionLost)}; }
        else { step = queue.firstObject; if (![step[@"repeat"] boolValue]) [queue removeObjectAtIndex:0]; }
    }
    if ([self.request.URL.host isEqual:@"ipwho.is"] || [self.request.URL.host isEqual:@"ipv4.is"])
        Require([self.request.URL.path isEqual:@"/"],@"no address-specific API or metadata lookup");
    Require([self.request.HTTPMethod isEqual:@"GET"], @"GET only");
    Require(self.request.cachePolicy == NSURLRequestReloadIgnoringLocalCacheData, @"cache bypass");
    if (step[@"hang"]) return;
    if (step[@"error"]) { [self.client URLProtocol:self didFailWithError:[NSError errorWithDomain:NSURLErrorDomain code:[step[@"error"] integerValue] userInfo:nil]]; return; }
    if (step[@"redirect"]) {
        NSURL *target = [NSURL URLWithString:step[@"redirect"]];
        NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL statusCode:302 HTTPVersion:@"HTTP/1.1" headerFields:@{@"Location":target.absoluteString}];
        NSMutableURLRequest *redirect = self.request.mutableCopy; redirect.URL = target;
        [self.client URLProtocol:self wasRedirectedToRequest:redirect redirectResponse:response];
        [self.client URLProtocolDidFinishLoading:self]; return;
    }
    NSHTTPURLResponse *response = [[NSHTTPURLResponse alloc] initWithURL:self.request.URL statusCode:[step[@"status"] ?: @200 integerValue] HTTPVersion:@"HTTP/1.1" headerFields:@{}];
    [self.client URLProtocol:self didReceiveResponse:response cacheStoragePolicy:NSURLCacheStorageNotAllowed];
    id body = step[@"body"] ?: @{};
    NSData *data = [body isKindOfClass:NSString.class] ? [body dataUsingEncoding:NSUTF8StringEncoding] : [NSJSONSerialization dataWithJSONObject:body options:0 error:nil];
    [self.client URLProtocol:self didLoadData:data]; [self.client URLProtocolDidFinishLoading:self];
}
- (void)stopLoading {}
@end
@interface SHDWIPSwitchService (Timing)
- (NSTimeInterval)pollInterval;
- (NSTimeInterval)operationTimeout;
- (NSTimeInterval)queryTimeout;
@end
@interface TestService : SHDWIPSwitchService
- (NSArray *)productionTiming;
@end
@implementation TestService
- (NSURLSessionConfiguration *)sessionConfiguration { NSURLSessionConfiguration *config = NSURLSessionConfiguration.ephemeralSessionConfiguration; config.protocolClasses = @[FixtureProtocol.class]; return config; }
- (NSArray *)productionTiming { return @[@([super pollInterval]), @([super operationTimeout]), @([super queryTimeout])]; }
- (NSTimeInterval)pollInterval { return .0375; }
- (NSTimeInterval)operationTimeout { return .3; }
- (NSTimeInterval)queryTimeout { return .3; }
- (NSTimeInterval)requestTimeout { return .035; }
@end
static NSURL *Action(void) { return [NSURL URLWithString:@"https://action.invalid/chosen/switch?line=second&mode=once"]; }
static NSDictionary *Who(NSString *ip, NSString *country, NSString *region, NSString *city) {
    return @{@"body":@{@"success":@YES,@"ip":ip,@"type":[ip containsString:@":"] ? @"IPv6" : @"IPv4",@"country":country?:@"",@"region":region?:@"",@"city":city?:@""}};
}
static NSDictionary *IP(NSString *ip) { return Who(ip, nil, nil, nil); }
static NSDictionary *Raw(NSString *ip) { return @{@"body":ip}; }
static NSDictionary *Error(NSInteger code) { return @{@"error":@(code)}; }
static void Reset(NSDictionary *script) {
    routes = [NSMutableDictionary new]; for (NSString *key in script) routes[key] = [script[key] mutableCopy];
    requests = [NSMutableArray new]; lookupStartTimes = [NSMutableArray new]; unexpected = NO;
}
static void Pump(NSTimeInterval seconds) { NSDate *until = [NSDate dateWithTimeIntervalSinceNow:seconds]; while (until.timeIntervalSinceNow > 0) [NSRunLoop.mainRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.002]]; }
static void Await(BOOL *done) { NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:2]; while (!*done && limit.timeIntervalSinceNow > 0) Pump(.004); Require(*done, @"completion deadline"); }
static NSUInteger Actions(void) { NSUInteger count = 0; for (NSString *url in requests) if ([url hasPrefix:@"https://action.invalid/"]) count++; return count; }
static void Quiescent(NSUInteger calls) { NSUInteger count = requests.count; Pump(.04); Require(requests.count == count && calls == 1 && !unexpected, @"no late requests, duplicate completion or unexpected endpoint"); }
static SHDWIPSnapshot *Snapshot(NSString *ip, NSString *ipv4) { return [[SHDWIPSnapshot alloc] initWithIP:ip region:nil ipv4:ipv4 checkedAt:NSDate.date]; }
static NSDictionary *Simple(NSArray *who, NSArray *v4, NSArray *action) { return @{@"who":who,@"v4":v4,Route(Action()):action}; }
static void Query(NSDictionary *script, void (^check)(SHDWIPSnapshot *, NSError *)) {
    Reset(script); TestService *service = [TestService new]; __block BOOL done = NO; __block NSUInteger calls = 0;
    [service queryWithProgress:^(SHDWIPSwitchPhase phase, SHDWIPSnapshot *snapshot) { Require(NSThread.isMainThread, @"query progress main"); } completion:^(SHDWIPSnapshot *snapshot, NSError *error) {
        Require(NSThread.isMainThread, @"query completion main"); calls++; check(snapshot,error); done = YES;
    }];
    Await(&done); Require(!service.running && Actions() == 0, @"query sends no action"); Quiescent(calls);
}
static void Switch(NSDictionary *script, NSInteger errorCode, void (^check)(SHDWIPSnapshot *, SHDWIPSnapshot *)) {
    Reset(script); TestService *service = [TestService new]; __block BOOL done = NO; __block NSUInteger calls = 0;
    [service startWithURL:Action() progress:^(SHDWIPSwitchPhase phase, SHDWIPSnapshot *snapshot) {
        Require(NSThread.isMainThread, @"switch progress main"); if (phase == SHDWIPSwitchPhaseRequesting) Require(snapshot.ip || snapshot.ipv4, @"requesting supplies baseline");
    } completion:^(SHDWIPSnapshot *before, SHDWIPSnapshot *current, NSError *error) {
        Require(NSThread.isMainThread, @"switch completion main"); calls++;
        Require(errorCode ? error.code == errorCode : !error, [NSString stringWithFormat:@"expected error %ld, got %@",(long)errorCode,error]); check(before,current); done = YES;
    }];
    __block BOOL busy = NO;
    [service queryWithProgress:nil completion:^(SHDWIPSnapshot *snapshot, NSError *error) { busy = error.code == 6; }]; Require(busy, @"query cannot overlap switch");
    Await(&done); Require(!service.running, @"switch finishes"); Quiescent(calls);
}
static void RevisionCase(NSString *name) {
    if ([name isEqual:@"monitor"]) {
        Switch(Simple(@[IP(@"192.0.2.1"),Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),@{@"status":@503},Error(NSURLErrorTimedOut),IP(@"192.0.2.2")],@[Raw(@"192.0.2.1"),Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),@{@"status":@503},Error(NSURLErrorTimedOut),Raw(@"192.0.2.2")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([after.ip isEqual:@"192.0.2.2"] && Actions()==1,@"late monitor recovery without action resend");});
    } else if ([name isEqual:@"baseline"]) {
        Switch(Simple(@[Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),IP(@"192.0.2.1"),IP(@"192.0.2.2")],@[Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),Raw(@"192.0.2.1"),Raw(@"192.0.2.2")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([before.ip isEqual:@"192.0.2.1"] && [after.ip isEqual:@"192.0.2.2"] && Actions()==1,@"baseline retries before single action");});
    } else if ([name isEqual:@"query"]) {
        Query(Simple(@[Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),IP(@"192.0.2.2")],@[Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Error(NSURLErrorNetworkConnectionLost),Raw(@"192.0.2.2")],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && [snapshot.ip isEqual:@"192.0.2.2"],@"query retries without action");});
    } else if ([name isEqual:@"partialprovider"]) {
        Switch(Simple(@[IP(@"2001:db8::1"),IP(@"2001:db8::2"),IP(@"2001:db8::2")],@[Raw(@"192.0.2.1"),Error(NSURLErrorNetworkConnectionLost),Raw(@"192.0.2.1")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([after.ipv4 isEqual:@"192.0.2.1"] && [after.ip isEqual:@"2001:db8::2"] && Actions()==1,@"original providers restored before auto-success");});
    } else if ([name isEqual:@"action500"]) {
        Switch(Simple(@[IP(@"192.0.2.1"),Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},IP(@"192.0.2.2")],@[Raw(@"192.0.2.1"),Error(NSURLErrorServerCertificateUntrusted),@{@"status":@429},Raw(@"192.0.2.2")],@[@{@"status":@500}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([after.ip isEqual:@"192.0.2.2"] && Actions()==1,@"HTTP500 action outcome still observed");});
    }
    for (NSUInteger i=1;i<lookupStartTimes.count;i++) Require([lookupStartTimes[i] doubleValue]-[lookupStartTimes[i-1] doubleValue]>=.03,@"lookup retries respect scaled 15-second spacing");
}
int main(void) { @autoreleasepool {
    const char *revisionCase = getenv("IP_SWITCH_CASE"); if (revisionCase) { RevisionCase([NSString stringWithUTF8String:revisionCase]); puts("isolated regression passed"); return 0; }

    Require([[[TestService new] productionTiming] isEqual:@[@15,@120,@120]],@"production timing: 15-second rounds and 120-second operation/query budgets");
    for (NSString *name in @[@"monitor",@"baseline",@"query",@"partialprovider",@"action500"]) RevisionCase(name);
    NSDate *queryStarted=NSDate.date;
    Query(Simple(@[@{@"error":@(NSURLErrorServerCertificateUntrusted),@"repeat":@YES}],@[@{@"status":@429,@"repeat":@YES}],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!snapshot && error.code==SHDWIPSwitchErrorUnconfirmed && -queryStarted.timeIntervalSinceNow>=.27,@"initial query remains unconfirmed until total 120-second budget");});
    // Each round uses exactly two providers; ipwho's IP and region stay together.
    Switch(Simple(@[Who(@"2001:0db8:0:0:0:0:0:1",@"France",@"Ile-de-France",@"Paris"),Who(@"2001:db8::2",@"Country2",@"Region2",@"City2")],@[Raw(@"192.0.2.1\n"),Raw(@"192.0.2.2")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){
        Require([before.ip isEqual:@"2001:0db8:0:0:0:0:0:1"] && [before.region isEqual:@"France, Ile-de-France, Paris"] && [before.ipv4 isEqual:@"192.0.2.1"],@"raw JSON IP/region and trimmed plaintext preserved");
        Require([after.ip isEqual:@"2001:db8::2"] && [after.region isEqual:@"Country2, Region2, City2"] && [after.ipv4 isEqual:@"192.0.2.2"] && after.checkedAt,@"new provider values displayed without inferred geography");
        Require(requests.count==5 && Actions()==1 && [requests containsObject:Action().absoluteString],@"exactly two requests per lookup round plus selected action once");
        Require(![requests containsObject:@"https://action.invalid/switch"],@"unselected endpoint unused");
    });
    Query(Simple(@[Who(@"192.0.2.99",@"Country",@"Country",@"City")],@[Raw(@"192.0.2.1")],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && [snapshot.ip isEqual:@"192.0.2.99"] && [snapshot.region isEqual:@"Country, City"] && [snapshot.ipv4 isEqual:@"192.0.2.1"] && requests.count==2,@"IPv4 JSON remains ip with its own region; no per-IP metadata request");});
    Query(Simple(@[IP(@"2001:db8::1")],@[Raw(@"bad")],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && [snapshot.ip isEqual:@"2001:db8::1"] && !snapshot.ipv4 && !snapshot.region && requests.count==2,@"invalid plaintext discarded, ipwho result retained");});
    Query(Simple(@[Error(NSURLErrorNetworkConnectionLost)],@[Raw(@"192.0.2.1")],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && !snapshot.ip && !snapshot.region && [snapshot.ipv4 isEqual:@"192.0.2.1"] && requests.count==2,@"plaintext never acquires inferred IP or region");});
    Query(Simple(@[Who(@"192.0.2.1",@"Raw Country",@"Raw Region",@"Raw City")],@[Error(NSURLErrorNetworkConnectionLost)],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && snapshot.ip && snapshot.region && !snapshot.ipv4 && requests.count==2,@"ipwho IPv4 never fills unavailable plaintext-provider field");});
    for (id body in @[@"{bad",@[],@{@"success":@YES,@"ip":@42},@{@"success":@{},@"ip":@"192.0.2.1"},@{@"success":@1,@"ip":@"192.0.2.1"}])
        Switch(Simple(@[@{@"body":body,@"repeat":@YES}],@[@{@"body":@"bad",@"repeat":@YES}],@[]),7,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require(!before && !after && Actions()==0,@"invalid baseline never triggers action");});
    Require(![SHDWIPSwitchService hasIPChangeFrom:Snapshot(nil,@"192.0.2.1") to:Snapshot(@"2001:db8::1",@"192.0.2.1")],@"appearance on previously unavailable provider proves no change");
    Require(![SHDWIPSwitchService hasIPChangeFrom:Snapshot(@"2001:db8::1",nil) to:Snapshot(@"2001:0db8:0:0:0:0:0:1",nil)],@"canonical comparison ignores equivalent IPv6 formatting");
    Require([SHDWIPSwitchService hasIPChangeFrom:Snapshot(@"192.0.2.1",nil) to:Snapshot(@"2001:db8::1",nil)],@"different family returned by same provider is changed IP");
    Switch(Simple(@[IP(@"2001:0db8:0:0:0:0:0:1"),IP(@"2001:db8::1"),IP(@"2001:db8::2")],@[Raw(@"bad"),Raw(@"bad"),Raw(@"bad")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([before.ip isEqual:@"2001:0db8:0:0:0:0:0:1"] && [after.ip isEqual:@"2001:db8::2"],@"raw representation preserved without false formatting change");});
    Switch(Simple(@[IP(@"192.0.2.1"),IP(@"2001:db8::1")],@[Raw(@"192.0.2.1"),Raw(@"192.0.2.1")],@[@{}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require([after.ip isEqual:@"2001:db8::1"] && Actions()==1,@"provider output can change family");});
    Switch(Simple(@[IP(@"192.0.2.1"),IP(@"192.0.2.2")],@[Raw(@"192.0.2.1"),Raw(@"192.0.2.2")],@[Error(NSURLErrorNetworkConnectionLost)]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require(Actions()==1 && [SHDWIPSwitchService hasIPChangeFrom:before to:after],@"action disconnect observed without resend");});
    Switch(Simple(@[IP(@"192.0.2.1"),IP(@"192.0.2.2")],@[Raw(@"192.0.2.1"),Raw(@"192.0.2.2")],@[@{@"redirect":@"https://other.invalid/back"}]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require(Actions()==1,@"action redirect does not repeat trigger");for(NSString *url in requests)Require(![url containsString:@"other.invalid"],@"action redirect refused");});
    Query(Simple(@[@{@"redirect":@"https://third.invalid/lookup",@"repeat":@YES}],@[@{@"body":@"bad",@"repeat":@YES}],@[]),^(SHDWIPSnapshot *snapshot,NSError *error){Require(!snapshot && error,@"third-provider redirect refused");for(NSString *url in requests)Require(![url containsString:@"third.invalid"],@"no third provider call");});
    for(NSNumber *code in @[@(NSURLErrorUnsupportedURL),@(NSURLErrorAppTransportSecurityRequiresSecureConnection),@(NSURLErrorServerCertificateUntrusted)])
        Switch(Simple(@[IP(@"192.0.2.1"),IP(@"192.0.2.2")],@[Raw(@"192.0.2.1"),Raw(@"192.0.2.2")],@[Error(code.integerValue)]),0,^(SHDWIPSnapshot *before,SHDWIPSnapshot *after){Require(Actions()==1,@"action error still observes outcome");});
    // Full-budget unconfirmed result can be followed by observation only, never another action.
    Reset(Simple(@[@{@"body":@{@"success":@YES,@"ip":@"192.0.2.1"},@"repeat":@YES}],@[@{@"body":@"192.0.2.1",@"repeat":@YES}],@[@{}]));
    TestService *service=[TestService new];__block BOOL done=NO;__block NSUInteger calls=0;__block SHDWIPSnapshot *baseline;
    [service startWithURL:Action() progress:nil completion:^(SHDWIPSnapshot *before,SHDWIPSnapshot *after,NSError *error){Require(error.code==SHDWIPSwitchErrorUnconfirmed && before && after,@"deadline is unconfirmed with last observation");baseline=before;calls++;done=YES;}];Await(&done);Require(Actions()==1,@"deadline action once");Quiescent(calls);
    routes[@"who"]=[@[IP(@"192.0.2.2")] mutableCopy];routes[@"v4"]=[@[Raw(@"192.0.2.2")] mutableCopy];done=NO;
    [service queryWithProgress:nil completion:^(SHDWIPSnapshot *snapshot,NSError *error){Require(!error && [SHDWIPSwitchService hasIPChangeFrom:baseline to:snapshot],@"manual query compares original baseline");done=YES;}];Await(&done);Require(Actions()==1,@"manual query cannot reactuate");Quiescent(1);
    Reset(Simple(@[@{@"hang":@YES}],@[@{@"hang":@YES}],@[]));done=NO;calls=0;
    [service startWithURL:Action() progress:nil completion:^(SHDWIPSnapshot *before,SHDWIPSnapshot *after,NSError *error){Require([error.domain isEqual:NSURLErrorDomain] && error.code==NSURLErrorCancelled,@"cancel result");calls++;done=YES;}];Pump(.008);[service cancel];[service cancel];Await(&done);Require(Actions()==0 && !service.running,@"cancel before baseline cannot trigger action");Quiescent(calls);
    Reset(Simple(@[IP(@"192.0.2.1")],@[Raw(@"192.0.2.1")],@[@{}]));done=NO;calls=0;
    [service startWithURL:Action() progress:^(SHDWIPSwitchPhase phase,SHDWIPSnapshot *snapshot){if(phase==SHDWIPSwitchPhaseWaitingForNetwork)[service cancel];} completion:^(SHDWIPSnapshot *before,SHDWIPSnapshot *after,NSError *error){Require(error.code==NSURLErrorCancelled && before && after,@"cancel retains observation");calls++;done=YES;}];Await(&done);Require(Actions()==1,@"cancel monitoring never resends");Quiescent(calls);
    Reset(Simple(@[IP(@"192.0.2.10"),IP(@"192.0.2.11")],@[Raw(@"192.0.2.10"),Raw(@"192.0.2.11")],@[@{}]));done=NO;
    [service startWithURL:Action() progress:nil completion:^(SHDWIPSnapshot *before,SHDWIPSnapshot *after,NSError *error){Require(!error && [before.ip isEqual:@"192.0.2.10"] && [after.ip isEqual:@"192.0.2.11"],@"reuse acquires new baseline");done=YES;}];Await(&done);Require(Actions()==1,@"retry new run single action");Quiescent(1);
    for(NSString *value in @[@"file:///tmp/switch",@"https://user:pass@action.invalid/",@"https://action.invalid/#fragment",@"https:/missing-host"]){__block BOOL rejected=NO;[service startWithURL:[NSURL URLWithString:value] progress:nil completion:^(SHDWIPSnapshot *before,SHDWIPSnapshot *after,NSError *error){rejected=error!=nil;}];Require(rejected,@"invalid action URL rejected");}
    puts("IP snapshot/switch fixtures passed (two provider doubles; no live requests).");
} return 0; }
"""

def main():
    if platform.system() != "Darwin":
        raise SystemExit("verify-ip-switch requires macOS Foundation and clang")
    with tempfile.TemporaryDirectory(prefix="shadow-ip-switch-") as directory:
        directory = Path(directory)
        source = directory / "fixture.m"
        source.write_text(HARNESS)
        executable = directory / "fixture"
        subprocess.run(["clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                        "-Wno-unused-parameter", "-Wno-incompatible-pointer-types",
                        "-framework", "Foundation", "-I", str(ROOT / "src/Shadow.app/Services"),
                        str(source), str(ROOT / "src/Shadow.app/Services/IPSwitchService.m"),
                        "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True, timeout=20)

if __name__ == "__main__":
    main()
