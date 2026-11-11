"""Run the production curl adapter against deterministic engine and NSURLProtocol clients."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
dependency = Path(os.environ.get("SHADOW_CURL_ROOT", root.parent / "prebuilt/curl-impersonate/2.3.2/ios"))
if not (dependency / "include/curl/curl.h").is_file():
    raise SystemExit("Prepare the pinned curl headers with scripts/prepare-curl-impersonate.sh")
source = r'''
#define SHADOW_CURL_IMPERSONATE 1
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdarg.h>
NSDictionary *SHDWFingerprintConfig(NSString *bundle) { (void)bundle;return @{}; }
#include "CurlTransport.m"
NSString *JBPath(NSString *path) { return path; }
static curl_write_callback writeCallback,headerCallback;
static curl_xferinfo_callback progressCallback;
static void *writeContext,*headerContext,*progressContext;
static struct curl_slist *sentHeaders;
static const void *sentBody;
static curl_off_t sentSize;
static long verifyPeer,verifyHost;
static unsigned performed,destroyed;
static BOOL redirectMode,cancelMode;
static CURLcode transferResult;
static CURL *create(void) { sentBody=NULL;sentSize=0;return (CURL *)1; }
static CURLcode impersonate(CURL *curl,const char *profile,int headers) {
  assert(curl==(CURL *)1 && !strcmp(profile,"safari184_ios") && headers==1);return CURLE_OK;
}
static CURLcode set(CURL *curl,CURLoption option,...) {
  assert(curl==(CURL *)1);va_list args;va_start(args,option);
  if(option==CURLOPT_WRITEFUNCTION) writeCallback=va_arg(args,curl_write_callback);
  else if(option==CURLOPT_HEADERFUNCTION) headerCallback=va_arg(args,curl_write_callback);
  else if(option==CURLOPT_XFERINFOFUNCTION) progressCallback=va_arg(args,curl_xferinfo_callback);
  else if(option==CURLOPT_HTTPHEADER) sentHeaders=va_arg(args,struct curl_slist *);
  else if(option==CURLOPT_POSTFIELDS) sentBody=va_arg(args,const void *);
  else if(option==CURLOPT_POSTFIELDSIZE_LARGE) sentSize=va_arg(args,curl_off_t);
  else if(option<CURLOPTTYPE_OBJECTPOINT) {
    long value=va_arg(args,long);
    if(option==CURLOPT_SSL_VERIFYPEER) verifyPeer=value;
    if(option==CURLOPT_SSL_VERIFYHOST) verifyHost=value;
  } else {
    void *value=va_arg(args,void *);
    if(option==CURLOPT_WRITEDATA) writeContext=value;
    if(option==CURLOPT_HEADERDATA) headerContext=value;
    if(option==CURLOPT_XFERINFODATA) progressContext=value;
  }
  va_end(args);return CURLE_OK;
}
static NSArray *capturedHeaders;
static NSData *capturedBody;
static CURLcode perform(CURL *curl) {
  assert(curl==(CURL *)1 && verifyPeer==1 && verifyHost==2);performed++;
  NSMutableArray *headers=[NSMutableArray new];
  for(struct curl_slist *item=sentHeaders;item;item=item->next) [headers addObject:@(item->data)];
  capturedHeaders=headers;capturedBody=sentBody ? [NSData dataWithBytes:sentBody length:(NSUInteger)sentSize] : nil;
  const char *lines[]={redirectMode ? "HTTP/2 307\r\n" : "HTTP/2 200\r\n",
    "Content-Type: application/json\r\n","Content-Encoding: gzip\r\n","Content-Length: 40\r\n",
    "Set-Cookie: returned=2; Path=/; Secure\r\n",redirectMode ? "Location: https://other.test/path\r\n" : "X-Test: preserved\r\n","\r\n"};
  for(unsigned i=0;i<sizeof(lines)/sizeof(*lines);i++) assert(headerCallback((char *)lines[i],1,strlen(lines[i]),headerContext)==strlen(lines[i]));
  if(cancelMode) [(__bridge SHDWSafari184Protocol *)writeContext stopLoading];
  const char body[]="{\"ok\":true}";
  size_t count=writeCallback((char *)body,1,sizeof(body)-1,writeContext);
  if(count!=sizeof(body)-1) return CURLE_WRITE_ERROR;
  return transferResult;
}
static void destroy(CURL *curl) { assert(curl==(CURL *)1);destroyed++; }
static struct curl_slist *append(struct curl_slist *list,const char *line) {
  struct curl_slist *item=calloc(1,sizeof(*item));item->data=strdup(line);
  if(!list) return item;struct curl_slist *tail=list;while(tail->next) tail=tail->next;tail->next=item;return list;
}
static void freeHeaders(struct curl_slist *list) { while(list) {struct curl_slist *next=list->next;free(list->data);free(list);list=next;}sentHeaders=NULL; }
static const char *errorText(CURLcode code) { (void)code;return "fixture error"; }
@interface Session : NSObject
@property(nonatomic,strong) NSURLSessionConfiguration *configuration;
@property(nonatomic,strong) id delegate;
@end
@implementation Session @end
@interface PinningDelegate : NSObject
- (void)URLSession:(id)session didReceiveChallenge:(id)challenge completionHandler:(id)completion;
@end
@implementation PinningDelegate
- (void)URLSession:(id)session didReceiveChallenge:(id)challenge completionHandler:(id)completion { (void)session;(void)challenge;(void)completion;abort(); }
@end
@interface Client : NSObject <NSURLProtocolClient>
@property(nonatomic,strong) NSMutableArray *events;
@property(nonatomic,strong) NSMutableData *data;
@property(nonatomic,strong) NSHTTPURLResponse *response;
@property(nonatomic,strong) NSURLRequest *redirect;
@property(nonatomic,strong) NSError *error;
@end
@implementation Client
- (instancetype)init { if((self=[super init])) {_events=[NSMutableArray new];_data=[NSMutableData new];}return self; }
- (void)URLProtocol:(NSURLProtocol *)p wasRedirectedToRequest:(NSURLRequest *)request redirectResponse:(NSURLResponse *)response { (void)p;(void)response;self.redirect=request;[self.events addObject:@"redirect"]; }
- (void)URLProtocol:(NSURLProtocol *)p cachedResponseIsValid:(NSCachedURLResponse *)response { (void)p;(void)response;abort(); }
- (void)URLProtocol:(NSURLProtocol *)p didReceiveResponse:(NSURLResponse *)response cacheStoragePolicy:(NSURLCacheStoragePolicy)policy { (void)p;(void)policy;self.response=(id)response;[self.events addObject:@"response"]; }
- (void)URLProtocol:(NSURLProtocol *)p didLoadData:(NSData *)data { (void)p;[self.data appendData:data];[self.events addObject:@"data"]; }
- (void)URLProtocolDidFinishLoading:(NSURLProtocol *)p { (void)p;[self.events addObject:@"finish"]; }
- (void)URLProtocol:(NSURLProtocol *)p didFailWithError:(NSError *)error { (void)p;self.error=error;[self.events addObject:@"error"]; }
- (void)URLProtocol:(NSURLProtocol *)p didReceiveAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge { (void)p;(void)challenge;abort(); }
- (void)URLProtocol:(NSURLProtocol *)p didCancelAuthenticationChallenge:(NSURLAuthenticationChallenge *)challenge { (void)p;(void)challenge;abort(); }
@end
static SHDWSafari184Protocol *protocol(NSURLRequest *request,NSURLSessionConfiguration *settings,Client *client) {
  SHDWSafari184Protocol *p=[[SHDWSafari184Protocol alloc] initWithRequest:request cachedResponse:nil client:client];
  p.callbackLock=[NSRecursiveLock new];p.settings=settings;return p;
}
int main(void) { @autoreleasepool {
  engine.create=create;engine.impersonate=impersonate;engine.set=set;engine.perform=perform;engine.destroy=destroy;
  engine.append=append;engine.freeHeaders=freeHeaders;engine.error=errorText;
  __atomic_store_n(&transportReady,1,__ATOMIC_RELEASE);
  NSURLSessionConfiguration *settings=NSURLSessionConfiguration.ephemeralSessionConfiguration;
  settings.connectionProxyDictionary=@{@"HTTPEnable":@NO,@"HTTPSEnable":@NO,@"ProxyAutoConfigEnable":@NO};
  settings.HTTPAdditionalHeaders=@{@"Authorization":@"secret",@"X-Config":@"preserved"};
  Session *session=[Session new];session.configuration=settings;
  NSMutableURLRequest *request=[NSMutableURLRequest requestWithURL:[NSURL URLWithString:@"https://origin.test/start"]];
  request.HTTPMethod=@"POST";request.HTTPBody=[@"payload" dataUsingEncoding:NSUTF8StringEncoding];
  [request setValue:@"App/1" forHTTPHeaderField:@"User-Agent"];
  assert(![SHDWSafari184Protocol canInitWithRequest:request]);
  NSURLRequest *prepared=SHDWCurlTransportRequest(request,(id)session);
  assert(prepared!=request && [SHDWSafari184Protocol canInitWithRequest:prepared]);
  assert(![NSURLProtocol propertyForKey:SHDWCurlContext inRequest:request]);
  Client *client=[Client new];[protocol(prepared,settings,client) runTransfer];
  assert(([client.events isEqual:@[@"response",@"data",@"finish"]]));
  assert([capturedBody isEqual:request.HTTPBody] && [capturedHeaders containsObject:@"User-Agent: App/1"]);
  assert([capturedHeaders containsObject:@"Authorization: secret"] && [capturedHeaders containsObject:@"X-Config: preserved"]);
  assert(!SHDWCurlHeaderValue(client.response.allHeaderFields,@"Content-Encoding") && !SHDWCurlHeaderValue(client.response.allHeaderFields,@"Content-Length"));
  assert([SHDWCurlHeaderValue(client.response.allHeaderFields,@"X-Test") isEqual:@"preserved"]);
  request.HTTPShouldHandleCookies=NO;prepared=SHDWCurlTransportRequest(request,(id)session);
  [settings.HTTPCookieStorage setCookie:[NSHTTPCookie cookieWithProperties:@{NSHTTPCookieName:@"stored",NSHTTPCookieValue:@"1",NSHTTPCookieDomain:@"origin.test",NSHTTPCookiePath:@"/"}]];
  for(NSHTTPCookie *cookie in [settings.HTTPCookieStorage cookiesForURL:request.URL]) if([cookie.name isEqual:@"returned"]) [settings.HTTPCookieStorage deleteCookie:cookie];
  client=[Client new];[protocol(prepared,settings,client) runTransfer];
  for(NSString *header in capturedHeaders) assert(![header.lowercaseString hasPrefix:@"cookie:"]);
  for(NSHTTPCookie *cookie in [settings.HTTPCookieStorage cookiesForURL:request.URL]) assert(![cookie.name isEqual:@"returned"]);
  session.delegate=[PinningDelegate new];
  NSURLRequest *pinned=SHDWCurlTransportRequest(prepared,(id)session);assert(![SHDWSafari184Protocol canInitWithRequest:pinned]);session.delegate=nil;
  request.HTTPBody=nil;request.HTTPBodyStream=[NSInputStream inputStreamWithData:[NSData data]];
  assert(![SHDWSafari184Protocol canInitWithRequest:SHDWCurlTransportRequest(request,(id)session)]);request.HTTPBodyStream=nil;
  request.HTTPBody=[@"payload" dataUsingEncoding:NSUTF8StringEncoding];
  prepared=SHDWCurlTransportRequest(request,(id)session);redirectMode=YES;
  client=[Client new];[protocol(prepared,settings,client) runTransfer];
  assert(([client.events isEqual:@[@"redirect"]]));assert([client.redirect.HTTPMethod isEqual:@"POST"] && [client.redirect.HTTPBody isEqual:request.HTTPBody]);
  assert(![client.redirect valueForHTTPHeaderField:@"Authorization"]);
  NSURLSessionConfiguration *redirectSettings=[NSURLProtocol propertyForKey:SHDWCurlContext inRequest:client.redirect];
  assert(!SHDWCurlHeaderValue(redirectSettings.HTTPAdditionalHeaders,@"Authorization") && [redirectSettings.HTTPAdditionalHeaders[@"X-Config"] isEqual:@"preserved"]);
  assert(SHDWCurlTransportRequest(client.redirect,(id)session)==client.redirect);
  redirectMode=NO;
  NSMutableURLRequest *changed=[client.redirect mutableCopy];
  changed.HTTPMethod=@"GET";changed.HTTPBody=nil;changed.HTTPBodyStream=nil;
  Client *changedClient=[Client new];[protocol(changed,redirectSettings,changedClient) runTransfer];
  assert(!capturedBody);
  NSURLRequest *bodyless=SHDWCurlTransportRequest(changed,(id)session);
  assert(![NSURLProtocol propertyForKey:SHDWCurlBody inRequest:bodyless]);
  NSData *replacement=[@"replacement" dataUsingEncoding:NSUTF8StringEncoding];
  changed.HTTPMethod=@"POST";changed.HTTPBody=replacement;
  NSURLRequest *replaced=SHDWCurlTransportRequest(changed,(id)session);
  assert([[NSURLProtocol propertyForKey:SHDWCurlBody inRequest:replaced] isEqual:replacement]);
  NSMutableURLRequest *converted=[replaced mutableCopy];converted.HTTPBody=nil;
  converted.HTTPBodyStream=[NSInputStream inputStreamWithData:replacement];
  changedClient=[Client new];[protocol(converted,redirectSettings,changedClient) runTransfer];
  assert([capturedBody isEqual:replacement]);
  assert(SHDWCurlRequiresNativeTrust(@{@"NSRequiresCertificateTransparency":@YES}));
  assert(SHDWCurlRequiresNativeTrust(@{@"NSExceptionDomains":@{@"test":@{@"NSExceptionMinimumTLSVersion":@"TLSv1.3"}}}));
  assert(!SHDWCurlRequiresNativeTrust(@{@"NSExceptionMinimumTLSVersion":@"TLSv1.2"}));
  redirectMode=NO;cancelMode=YES;client=[Client new];[protocol(prepared,settings,client) runTransfer];
  assert(([client.events isEqual:@[@"response"]]));cancelMode=NO;
  transferResult=CURLE_OPERATION_TIMEDOUT;client=[Client new];[protocol(prepared,settings,client) runTransfer];assert(client.error.code==NSURLErrorTimedOut);
  assert(performed==destroyed);
  puts("curl transport: preset, request/body/headers, context isolation, cookie suppression, decoded metadata, redirects, trust/stream exclusions, cancellation and native errors passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-curl-tests-") as temporary:
    source_path, binary = Path(temporary) / "test.m", Path(temporary) / "test"
    source_path.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-framework", "CFNetwork",
                    "-I", str(dependency / "include"), "-I", str(root / "src/Shadow.framework/Headers"),
                    "-I", str(root / "src/ShadowCore.dylib/policy"), str(source_path), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
