"""Exercise the exact frame observer script and native message handling."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation and Node.js")
root = Path(__file__).resolve().parents[1]
implementation = "\n".join(line for line in (root / "src/ShadowCore.dylib/policy/WebFrameDiagnostics.m").read_text().splitlines()
                           if not line.startswith("#import"))
string_helper = (root / "src/Transport/CurlDiagnostics.h").read_text()
string_helper = string_helper[string_helper.index("static NSString *SHDWCurlDiagnosticString"):string_helper.index("static NSDictionary *SHDWCurlDiagnosticBodyPrefix")]
source = r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <assert.h>
#include <errno.h>
static BOOL enabled=YES;
static NSMutableArray *records;
static BOOL SHDWCurlDiagnosticsEnabled(void) { return enabled; }
static void SHDWCurlTrace(NSString *stage,NSURLRequest *request,NSDictionary *details) {
    [records addObject:@{@"stage":stage,@"request":request ?: NSNull.null,@"details":details}];errno=E2BIG;
}
@class WKUserContentController, WKScriptMessage;
@protocol WKScriptMessageHandler <NSObject>
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message;
@end
static const NSInteger WKUserScriptInjectionTimeAtDocumentStart=0;
@interface WKUserScript : NSObject
@property(nonatomic,copy) NSString *source;
@property(nonatomic) NSInteger injectionTime;
@property(nonatomic) BOOL forMainFrameOnly;
- (instancetype)initWithSource:(NSString *)source injectionTime:(NSInteger)time forMainFrameOnly:(BOOL)main;
@end
@implementation WKUserScript
- (instancetype)initWithSource:(NSString *)source injectionTime:(NSInteger)time forMainFrameOnly:(BOOL)main {
    if((self=[super init])){_source=[source copy];_injectionTime=time;_forMainFrameOnly=main;}return self;
}
@end
@interface WKUserContentController : NSObject
@property(nonatomic,strong) NSMutableArray *userScripts;
@property(nonatomic,strong) NSMutableDictionary *handlers;
@property(nonatomic) unsigned handlerAdds;
- (void)addScriptMessageHandler:(id<WKScriptMessageHandler>)handler name:(NSString *)name;
- (void)addUserScript:(WKUserScript *)script;
@end
@implementation WKUserContentController
- (instancetype)init {if((self=[super init])){_userScripts=[NSMutableArray new];_handlers=[NSMutableDictionary new];}return self;}
- (void)addScriptMessageHandler:(id<WKScriptMessageHandler>)handler name:(NSString *)name {self.handlerAdds++;self.handlers[name]=handler;}
- (void)addUserScript:(WKUserScript *)script {[self.userScripts addObject:script];}
@end
@interface WKWebViewConfiguration:NSObject
@property(nonatomic,strong) WKUserContentController *userContentController;
@end
@implementation WKWebViewConfiguration @end
@interface FixtureOrigin:NSObject
@property(nonatomic,copy) NSString *host;
@property(nonatomic,copy) NSString *protocol;
@end
@implementation FixtureOrigin @end
@interface FixtureFrame:NSObject
@property(nonatomic) BOOL mainFrame;
@property(nonatomic,strong) FixtureOrigin *securityOrigin;
@property(nonatomic,strong) NSURLRequest *request;
@end
@implementation FixtureFrame @end
@interface WKScriptMessage:NSObject
@property(nonatomic,strong) id body;
@property(nonatomic,strong) FixtureFrame *frameInfo;
@property(nonatomic,strong) id webView;
@end
@implementation WKScriptMessage @end
''' + string_helper + "\n" + implementation + r'''
int main(int argc,char **argv){@autoreleasepool{
    assert(argc==2);records=[NSMutableArray new];
    assert([SHDWWebFrameDiagnosticSource() writeToFile:@(argv[1]) atomically:YES encoding:NSUTF8StringEncoding error:NULL]);
    WKWebViewConfiguration *configuration=[WKWebViewConfiguration new];
    errno=EBUSY;SHDWWebFrameDiagnosticsInstall(configuration);assert(errno==EBUSY);
    WKUserContentController *controller=[WKUserContentController new];configuration.userContentController=controller;
    SHDWWebFrameDiagnosticsInstall(configuration);assert(errno==EBUSY);
    assert(controller.handlerAdds==1 && controller.userScripts.count==1);
    WKUserScript *script=controller.userScripts[0];
    assert(script.injectionTime==WKUserScriptInjectionTimeAtDocumentStart && !script.forMainFrameOnly);
    assert([script.source isEqual:SHDWWebFrameDiagnosticSource()]);
    SHDWWebFrameDiagnosticsInstall(configuration);assert(controller.handlerAdds==1 && controller.userScripts.count==1);
    [controller.userScripts removeAllObjects];SHDWWebFrameDiagnosticsInstall(configuration);
    assert(controller.handlerAdds==1 && controller.userScripts.count==1 && controller.userScripts[0]!=script);
    SHDWWebFrameDiagnosticHandler *handler=controller.handlers[@"shadowFrameDiagnostics"];assert(handler);
    WKScriptMessage *message=[WKScriptMessage new];message.webView=[NSObject new];message.frameInfo=[FixtureFrame new];
    message.frameInfo.mainFrame=NO;message.frameInfo.request=[NSURLRequest requestWithURL:[NSURL URLWithString:@"https://frame.example/path"]];
    message.frameInfo.securityOrigin=[FixtureOrigin new];message.frameInfo.securityOrigin.host=@"frame.example";message.frameInfo.securityOrigin.protocol=@"https";
    for(id invalid in @[NSNull.null,@3,@"text",@[]]){
        message.body=invalid;errno=ERANGE;[handler userContentController:controller didReceiveScriptMessage:message];assert(errno==ERANGE && !records.count);
    }
    NSMutableArray *languages=[NSMutableArray arrayWithObjects:@"fr-FR",@3,NSNull.null,[@"x" stringByPaddingToLength:300 withString:@"x" startingAtIndex:0],nil];
    for(unsigned i=0;i<20;i++)[languages addObject:[NSString stringWithFormat:@"language-%u",i]];
    NSString *longUA=[@"UA" stringByPaddingToLength:5000 withString:@"x" startingAtIndex:0];
    message.body=@{@"phase":@7,@"href":NSNull.null,@"userAgent":longUA,@"language":@"fr-FR",@"platform":@"iPhone",@"languages":languages,@"isTop":@YES,@"frameHost":@"spoofed.example",@"documentURL":NSNull.null,@"baseURI":@3,@"origin":@{},@"isSecureContext":@1,@"securityOriginScheme":@"spoofed"};
    errno=EDOM;[handler userContentController:controller didReceiveScriptMessage:message];assert(errno==EDOM && records.count==1);
    NSDictionary *details=records[0][@"details"];
    assert(!details[@"phase"] && !details[@"href"] && [details[@"userAgent"] length]==4096);
    assert([details[@"language"] isEqual:@"fr-FR"] && [details[@"platform"] isEqual:@"iPhone"]);
    assert([details[@"languages"] count]==16 && [details[@"languages"][1] length]==128);
    assert([details[@"frameHost"] isEqual:@"frame.example"] && ![details[@"isMainFrame"] boolValue]);
    assert([details[@"securityOriginScheme"] isEqual:@"https"] && !details[@"documentURL"] && !details[@"baseURI"] && !details[@"origin"] && !details[@"isSecureContext"]);
    assert(records[0][@"request"]==message.frameInfo.request && [records[0][@"stage"] isEqual:@"webview.frame.environment"]);
    NSString *href=@"https://captcha.example/captcha/?cid=a%2Fb%3D&cid=second%20value&empty=&missing&plus=a+b&unicode=%E6%B3%95%E5%9B%BD#fragment";
    message.body=@{@"href":href,@"documentURL":@"https://frame.example/document",@"baseURI":@"https://base.example/assets/",@"origin":@"null",@"isSecureContext":@NO,@"ddParameters":@{@"rt":@"c",@"cid":@"a/b=",@"s":@45631,@"r":@NO,@"rr":NSNull.null,@"cp":@{@"name":@"query",@"value":@42},@"unknown":@"drop"},
        @"iframeURLs":@[@"https://one.example/frame?cid=first",@"https://two.example/frame?cid=second"],@"documentCookies":@"notdatadome=wrong; datadome=decoded%2Ftoken%3D; other=1",@"documentDatadomeCookie":@"decoded/token=",@"cookieReadError":NSNull.null};
    errno=EAGAIN;[handler userContentController:controller didReceiveScriptMessage:message];assert(errno==EAGAIN && records.count==2);
    details=records.lastObject[@"details"];
    assert([details[@"documentURL"] isEqual:@"https://frame.example/document"] && [details[@"baseURI"] isEqual:@"https://base.example/assets/"] && [details[@"origin"] isEqual:@"null"]);
    assert(details[@"isSecureContext"]==(__bridge id)kCFBooleanFalse);
    assert([details[@"ddParameters"][@"cid"] isEqual:@"a/b="] && [details[@"ddParameters"][@"s"] intValue]==45631);
    assert([details[@"ddParameters"][@"r"] isEqual:@NO] && details[@"ddParameters"][@"rr"]==NSNull.null && !details[@"ddParameters"][@"unknown"]);
    assert([details[@"ddParameters"][@"cp"][@"name"] isEqual:@"query"] && [details[@"ddParameters"][@"cp"][@"value"] intValue]==42);
    assert([details[@"documentCookies"] isEqual:@"notdatadome=wrong; datadome=decoded%2Ftoken%3D; other=1"]);
    assert([details[@"iframeURLs"] count]==2 && [details[@"documentDatadomeCookie"] isEqual:@"decoded/token="] && !details[@"cookieReadError"]);
    NSArray *query=details[@"urlQueryItems"];
    assert(query.count==6 && [query[0][@"name"] isEqual:@"cid"] && [query[1][@"name"] isEqual:@"cid"]);
    assert([query[0][@"value"] isEqual:@"a/b="] && [query[1][@"value"] isEqual:@"second value"]);
    assert([query[2][@"value"] isEqual:@""] && query[3][@"value"]==NSNull.null);
    assert([query[4][@"value"] isEqual:@"a+b"] && [query[5][@"value"] isEqual:@"法国"]);
    NSString *longValue=[@"value" stringByPaddingToLength:17000 withString:@"x" startingAtIndex:0];
    NSMutableArray *frames=[NSMutableArray arrayWithObjects:@7,NSNull.null,nil];
    for(unsigned i=0;i<20;i++)[frames addObject:longValue];
    NSMutableString *manyQuery=[@"https://captcha.example/?" mutableCopy];
    [manyQuery appendString:[@"n" stringByPaddingToLength:1100 withString:@"n" startingAtIndex:0]];[manyQuery appendString:@"=value"];
    for(unsigned i=0;i<80;i++)[manyQuery appendFormat:@"&k%u=v",i];
    message.body=@{@"href":manyQuery,@"documentURL":longValue,@"baseURI":longValue,@"origin":longValue,@"isSecureContext":@YES,@"ddParameters":@{@"rt":@{},@"cid":longValue,@"cp":@{@"name":longValue,@"value":@[],@"unknown":@"drop"}},
        @"iframeURLs":frames,@"documentCookies":longValue,@"documentDatadomeCookie":longValue,@"cookieReadError":longValue};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==3);details=records.lastObject[@"details"];
    assert([details[@"documentURL"] length]==4096 && [details[@"baseURI"] length]==4096 && [details[@"origin"] length]==4096 && details[@"isSecureContext"]==(__bridge id)kCFBooleanTrue);
    assert(!details[@"ddParameters"][@"rt"] && [details[@"ddParameters"][@"cid"] length]==16384);
    assert([details[@"ddParameters"][@"cp"][@"name"] length]==16384 && !details[@"ddParameters"][@"cp"][@"value"] && !details[@"ddParameters"][@"cp"][@"unknown"]);
    assert([details[@"iframeURLs"] count]==16 && [details[@"iframeURLs"][0] length]==16384);
    assert([details[@"documentCookies"] length]==16384 && [details[@"documentDatadomeCookie"] length]==16384 && [details[@"cookieReadError"] length]==16384);
    assert([details[@"urlQueryItems"] count]==64 && [details[@"urlQueryItems"][0][@"name"] length]==1024);
    message.body=@{@"href":@7,@"documentURL":@3,@"baseURI":@[],@"origin":NSNull.null,@"isSecureContext":@"true",@"ddParameters":@[],@"iframeURLs":@"bad",@"documentCookies":@3,@"documentDatadomeCookie":@3,@"cookieReadError":@{}};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==4);details=records.lastObject[@"details"];
    assert([details[@"ddParameters"] count]==0 && [details[@"iframeURLs"] count]==0 && [details[@"urlQueryItems"] count]==0);
    assert(!details[@"documentCookies"] && !details[@"documentDatadomeCookie"] && !details[@"cookieReadError"]);
    assert(!details[@"documentURL"] && !details[@"baseURI"] && !details[@"origin"] && !details[@"isSecureContext"]);
    message.body=@{@"kind":@"js-error",@"phase":@"js-error",@"href":@"https://frame.example/path",@"message":longValue,@"filename":@"https://frame.example/script.js",@"line":@"0",@"column":@"0",@"stack":longValue,@"ddParameters":@{@"cid":@"not-duplicated"}};
    errno=ERANGE;[handler userContentController:controller didReceiveScriptMessage:message];assert(errno==ERANGE && records.count==5);details=records.lastObject[@"details"];
    assert([records.lastObject[@"stage"] isEqual:@"webview.frame.error"] && [details[@"kind"] isEqual:@"js-error"]);
    assert([details[@"message"] length]==16384 && [details[@"stack"] length]==16384 && [details[@"line"] isEqual:@"0"] && [details[@"column"] isEqual:@"0"]);
    assert([details[@"filename"] isEqual:@"https://frame.example/script.js"] && !details[@"ddParameters"]);
    message.body=@{@"kind":@"js-rejection",@"href":@"https://frame.example/path",@"message":@"false",@"filename":@4,@"line":@0,@"column":@[],@"stack":@{}};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==6);details=records.lastObject[@"details"];
    assert([records.lastObject[@"stage"] isEqual:@"webview.frame.error"] && [details[@"message"] isEqual:@"false"]);
    assert(!details[@"filename"] && !details[@"line"] && !details[@"column"] && !details[@"stack"]);
    NSMutableString *largeHTML=[NSMutableString new];for(unsigned i=0;i<40000;i++)[largeHTML appendString:@"汉😀"];
    message.body=@{@"kind":@"dom",@"href":@"https://geo.captcha-delivery.com/captcha/?cid=fixture",@"html":largeHTML,@"htmlLength":@(largeHTML.length),@"htmlTruncated":@NO};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==7);details=records.lastObject[@"details"];
    assert([records.lastObject[@"stage"] isEqual:@"webview.frame.dom"] && [largeHTML hasPrefix:details[@"html"]]);
    assert([details[@"html"] lengthOfBytesUsingEncoding:NSUTF8StringEncoding]<=98304 && [details[@"htmlTruncated"] boolValue]);
    assert([details[@"htmlLength"] unsignedIntegerValue]==largeHTML.length && [details[@"htmlCapturedLength"] unsignedIntegerValue]==[details[@"html"] length]);
    assert([details[@"htmlCapturedBytes"] unsignedIntegerValue]==[details[@"html"] lengthOfBytesUsingEncoding:NSUTF8StringEncoding]);
    assert(!details[@"ddParameters"] && !details[@"iframeURLs"] && !details[@"documentDatadomeCookie"]);
    assert([NSJSONSerialization dataWithJSONObject:details options:0 error:NULL].length<250*1024);
    message.body=@{@"kind":@"dom",@"href":@"https://geo.captcha-delivery.com/captcha/",@"html":@[],@"htmlLength":@YES,@"htmlTruncated":@"true"};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==8);details=records.lastObject[@"details"];
    assert(!details[@"html"] && !details[@"htmlLength"] && !details[@"htmlTruncated"]);
    message.body=@{@"kind":@"dom",@"href":@"https://geo.captcha-delivery.com.evil.example/",@"html":@"never-log"};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==8);
    message.body=@{@"documentCookies":NSNull.null,@"cookieReadError":@"SecurityError"};
    [handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==9);details=records.lastObject[@"details"];
    assert(!details[@"documentCookies"] && [details[@"cookieReadError"] isEqual:@"SecurityError"]);
    enabled=NO;[handler userContentController:controller didReceiveScriptMessage:message];assert(records.count==9);
    puts("native frame diagnostics: start/all-frame injection, idempotence/reinstall, typed bounded origin/security payloads/DD snapshots/URLs/cookies, decoded duplicate query items, native frame authority, typed error/DOM stages, UTF8 HTML bounds, disabled logging and errno passed");
}return 0;}
'''
node_source = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
for(const isTop of [true,false])for(const cookieCase of ['encoded','malformed','blocked'])for(const originCase of [
  {origin:'https://frame.example',secure:true},{origin:'http://frame.example',secure:false},
  {origin:'null',secure:true},{origin:'null',secure:false}]){
  const messages=[],listeners={document:new Map(),window:new Map()};
  let mutations=0,parentReads=0;
  const ua=isTop?'UA-main-native-18.7.1':'UA-cross-origin-frame-native-18.7.1';
  const rawNavigator=Object.freeze({userAgent:ua,language:'fr-FR',languages:Object.freeze(['fr-FR','en-FR']),platform:'iPhone'});
  const readonly={set(){mutations++;throw Error('read-only value');},defineProperty(){mutations++;throw Error('read-only value');},deleteProperty(){mutations++;throw Error('read-only value');}};
  const navigator=new Proxy(rawNavigator,readonly);
  const ddTarget=Object.freeze({rt:'c',cid:'cid/value=',hsh:'hash-fixture',cookie:'dd-cookie',t:'fe',s:45631,e:'signature',host:'geo.captcha.example',r:false,rr:null,qp:'a%3Db',cp:Object.freeze({name:'custom',value:42}),unknown:'not-captured'});
  const ddBefore=JSON.stringify(ddTarget),dd=new Proxy(ddTarget,readonly);
  const expectedDD={rt:'c',cid:'cid/value=',hsh:'hash-fixture',cookie:'dd-cookie',t:'fe',s:45631,e:'signature',host:'geo.captcha.example',r:false,rr:null,qp:'a%3Db',cp:{name:'custom',value:42}};
  const href=isTop?'https://vinted.example/native?cid=one':'https://captcha.example/iframe?cid=two';
  const iframeURLs=Array.from({length:20},(_,i)=>`https://child.example/${i}?cid=${i}`);
  const documentURL=href+'&document=own-frame',baseURI='https://base.example/own-frame/';
  const rawDocument={URL:documentURL,baseURI,addEventListener(name,fn){listeners.document.set(name,fn);},querySelectorAll(selector){assert.equal(selector,'iframe');return iframeURLs.map(src=>Object.freeze({src}));}};
  Object.defineProperty(rawDocument,'cookie',{get(){
    if(cookieCase==='blocked'){const error=new Error('blocked');error.name='SecurityError';throw error;}
    return cookieCase==='encoded'?'notdatadome=wrong; datadome=decoded%2Ftoken%3D; other=1':'other=1; datadome=%E0%A4%A';
  }});
  Object.freeze(rawDocument);const document=new Proxy(rawDocument,readonly);
  const rawLocation=Object.freeze({href,origin:originCase.origin});
  const opaqueTop=new Proxy({}, {get(){parentReads++;throw Error('cross-origin parent');}});
  const context=vm.createContext({navigator,location:new Proxy(rawLocation,readonly),document,dd,isSecureContext:originCase.secure,
    webkit:Object.freeze({messageHandlers:Object.freeze({shadowFrameDiagnostics:Object.freeze({postMessage(message){messages.push(JSON.parse(JSON.stringify(message)));}})})}),
    addEventListener(name,fn){listeners.window.set(name,fn);}});
  context.window=context;context.top=isTop?context:opaqueTop;context.parent=isTop?context:opaqueTop;
  vm.runInContext(source,context,{timeout:1000});
  assert.equal(messages.length,1);assert.equal(messages[0].phase,'start');
  assert.ok(listeners.document.has('DOMContentLoaded'));assert.ok(listeners.window.has('pageshow'));
  listeners.document.get('DOMContentLoaded')({type:'DOMContentLoaded'});
  listeners.window.get('pageshow')({type:'pageshow',persisted:true});
  assert.deepEqual(messages.map(x=>x.phase),['start','dom-ready','pageshow']);
  for(const message of messages){
    assert.equal(message.userAgent,ua);assert.equal(message.href,href);assert.equal(message.isTop,isTop);
    assert.equal(message.documentURL,documentURL);assert.equal(message.baseURI,baseURI);assert.equal(message.origin,originCase.origin);assert.equal(message.isSecureContext,originCase.secure);
    assert.equal(message.language,'fr-FR');assert.deepEqual(message.languages,['fr-FR','en-FR']);assert.equal(message.platform,'iPhone');
    assert.deepEqual(message.ddParameters,expectedDD);assert.deepEqual(message.iframeURLs,iframeURLs.slice(0,16));
    if(cookieCase==='encoded'){assert.equal(message.documentCookies,'notdatadome=wrong; datadome=decoded%2Ftoken%3D; other=1');assert.equal(message.documentDatadomeCookie,'decoded/token=');assert.equal(message.cookieReadError,null);}
    else if(cookieCase==='malformed'){assert.equal(message.documentCookies,'other=1; datadome=%E0%A4%A');assert.equal(message.documentDatadomeCookie,'%E0%A4%A');assert.equal(message.cookieReadError,null);}
    else{assert.equal(message.documentCookies,null);assert.equal(message.documentDatadomeCookie,null);assert.equal(message.cookieReadError,'SecurityError');}
  }
  let cancelled=0;
  const errorEvent=Object.freeze({message:'fixture exception',filename:'https://frame.example/script.js',lineno:0,colno:0,error:Object.freeze({stack:'fixture stack'}),preventDefault(){cancelled++;},stopPropagation(){cancelled++;}});
  const rejection=Object.freeze({reason:Object.freeze({message:'fixture rejected',stack:'rejection stack'}),preventDefault(){cancelled++;},stopPropagation(){cancelled++;}});
  assert.ok(listeners.window.has('error') && listeners.window.has('unhandledrejection'));
  assert.equal(listeners.window.get('error')(errorEvent),undefined);
  assert.equal(listeners.window.get('unhandledrejection')(rejection),undefined);
  assert.equal(messages.length,5);assert.equal(cancelled,0);
  const failure=messages[3],rejected=messages[4];
  assert.equal(failure.kind,'js-error');assert.equal(failure.phase,'js-error');assert.equal(failure.message,'fixture exception');
  assert.equal(failure.filename,errorEvent.filename);assert.equal(failure.line,'0');assert.equal(failure.column,'0');assert.equal(failure.stack,'fixture stack');
  assert.equal(rejected.kind,'js-rejection');assert.equal(rejected.message,'fixture rejected');assert.equal(rejected.stack,'rejection stack');
  assert.equal(failure.userAgent,ua);assert.equal(rejected.href,href);assert.ok(!('ddParameters' in failure));
  assert.equal(navigator.userAgent,ua);assert.equal(mutations,0);assert.equal(parentReads,0);assert.ok(Object.isFrozen(rawNavigator));
  assert.equal(JSON.stringify(ddTarget),ddBefore);assert.ok(Object.isFrozen(ddTarget.cp));
  assert.ok(Object.isFrozen(rawDocument));assert.ok(Object.isFrozen(rawLocation));
}
for(const host of ['geo.captcha-delivery.com','geo.captcha-delivery.com.evil.example','other.example',undefined])for(const html of ['<html><body>fixture</body></html>','汉😀'.repeat(40000),'"\\'.repeat(60000)]){
  const messages=[],listeners=new Map(),geo=host===undefined||host==='geo.captcha-delivery.com';
  const href=`https://${host||'geo.captcha-delivery.com'}/captcha/?cid=fixture`;
  const location=Object.freeze({href,hostname:host,origin:`https://${host||'geo.captcha-delivery.com'}`});
  const document=Object.freeze({URL:href,baseURI:href,cookie:'',documentElement:Object.freeze({outerHTML:html}),querySelectorAll(){return [];},addEventListener(name,fn){listeners.set(name,fn);}});
  const navigator=Object.freeze({userAgent:'GEO-original-UA',language:'fr-FR',languages:Object.freeze(['fr-FR']),platform:'iPhone'});
  const context=vm.createContext({location,document,navigator,isSecureContext:true,webkit:{messageHandlers:{shadowFrameDiagnostics:{postMessage(value){messages.push(JSON.parse(JSON.stringify(value)));}}}},addEventListener(name,fn){listeners.set(name,fn);}});
  context.window=context;context.top=context;
  vm.runInContext(source,context,{timeout:1000});assert.equal(messages.length,1);
  listeners.get('DOMContentLoaded')({type:'DOMContentLoaded'});listeners.get('pageshow')({type:'pageshow'});
  const dom=messages.filter(x=>x.kind==='dom'),environment=messages.filter(x=>!x.kind);
  assert.deepEqual(environment.map(x=>x.phase),['start','dom-ready','pageshow']);
  assert.equal(dom.length,geo?2:0);
  for(const message of dom){
    assert.equal(message.htmlLength,html.length);assert.ok(html.startsWith(message.html));
    assert.equal(message.htmlCapturedLength,message.html.length);assert.equal(message.htmlCapturedBytes,Buffer.byteLength(message.html));
    assert.ok(message.htmlCapturedBytes<=98304);assert.equal(message.htmlTruncated,message.html.length<html.length);
    assert.ok(Buffer.byteLength(JSON.stringify(message))<250*1024);
    assert.ok(!('ddParameters' in message)&&!('iframeURLs' in message)&&!('documentDatadomeCookie' in message)&&!('documentCookies' in message));
  }
  assert.equal(document.documentElement.outerHTML,html);assert.equal(navigator.userAgent,'GEO-original-UA');
  const before=messages.length;listeners.get('unhandledrejection')({reason:false,preventDefault(){throw Error('must not cancel');}});
  assert.equal(messages.length,before+1);assert.equal(messages.at(-1).message,'false');
}
console.log('frame JavaScript: exact production source, main/cross-origin own-frame values, start/DOM-ready/pageshow immutable navigator/DD, frozen own-document/location origin/security values, frame URLs/raw visible cookies, noncanceling errors/rejections and GEO-only UTF8-bounded DOM passed');
'''
with tempfile.TemporaryDirectory(prefix="shadow-web-frame-diagnostics-") as directory:
    temporary=Path(directory)
    test,binary,script,runner=(temporary/name for name in ("test.m","check","source.js","check.js"))
    test.write_text(source);runner.write_text(node_source)
    subprocess.run(["xcrun","clang","-I",str(root / "src/Transport"),"-I",str(root / "src/ShadowCore.dylib/policy"),"-DSHDW_TRANSPORT_DIAGNOSTICS=1","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-DSHADOW_CURL_IMPERSONATE=1",
                    "-fsanitize=address,undefined","-framework","Foundation",str(test),"-o",str(binary)],check=True)
    subprocess.run([str(binary),str(script)],check=True)
    subprocess.run(["node",str(runner),str(script)],check=True)
