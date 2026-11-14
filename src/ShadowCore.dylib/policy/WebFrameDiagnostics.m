#import "WebFrameDiagnostics.h"
#include "../../Transport/DiagnosticsConfig.h"
#if SHADOW_CURL_IMPERSONATE && SHDW_TRANSPORT_DIAGNOSTICS
#import <WebKit/WebKit.h>
#import <objc/runtime.h>
#include <math.h>
#import "../../Transport/CurlDiagnostics.h"

static char controllerHandlerKey, controllerScriptKey;
static NSString *const frameHandlerName = @"shadowFrameDiagnostics";

static NSString *SHDWWebFrameDiagnosticSource(void) {
    return @"(function(){'use strict';"
        @"function post(value){try{window.webkit.messageHandlers.shadowFrameDiagnostics.postMessage(value);}catch(e){}}"
        @"function environment(phase){return {phase:phase,href:String(location.href),documentURL:String(document.URL),"
        @"baseURI:String(document.baseURI),origin:String(location.origin),isSecureContext:window.isSecureContext,"
        @"userAgent:String(navigator.userAgent),language:String(navigator.language),"
        @"languages:Array.prototype.slice.call(navigator.languages||[]),platform:String(navigator.platform),isTop:window===window.top};}"
        @"function report(phase){try{var params={},frames=[],cookie=null,cookieError=null,cookieString=null;"
        @"var d=window.dd;if(d&&typeof d==='object'){"
        @"['rt','cid','hsh','cookie','t','s','e','host','r','rr','qp'].forEach(function(k){"
        @"var v=d[k];if(v===null||typeof v==='string'||typeof v==='number'||typeof v==='boolean')params[k]=v;});"
        @"if(d.cp&&typeof d.cp==='object')params.cp={name:d.cp.name,value:d.cp.value};}"
        @"if(document.querySelectorAll){var nodes=document.querySelectorAll('iframe');"
        @"for(var i=0;i<nodes.length&&i<16;i++)frames.push(String(nodes[i].src));}"
        @"try{cookieString=String(document.cookie);var match=/(?:^|;\\s*)datadome=([^;]*)/.exec(cookieString);"
        @"if(match){try{cookie=decodeURIComponent(match[1]);}catch(e){cookie=match[1];}}}"
        @"catch(e){cookieError=String(e.name||'cookie-read-error');}"
        @"var value=environment(phase);value.ddParameters=params;value.iframeURLs=frames;"
        @"value.documentCookies=cookieString;value.documentDatadomeCookie=cookie;value.cookieReadError=cookieError;post(value);}catch(e){}}"
        @"function dom(phase){try{var host=String(location.hostname||'').toLowerCase();"
        @"if(!host){var match=/^https?:\\/\\/([^\\/?#:]+)/i.exec(String(location.href));host=match?match[1].toLowerCase():'';}"
        @"if(host!=='geo.captcha-delivery.com')return;"
        @"var html=document.documentElement?String(document.documentElement.outerHTML||''):'';"
        @"var end=0,bytes=0;while(end<html.length){var code=html.charCodeAt(end),units=1,size=code<128?1:code<2048?2:3;"
        @"if(code>=55296&&code<=56319&&end+1<html.length){var next=html.charCodeAt(end+1);if(next>=56320&&next<=57343){units=2;size=4;}}"
        @"if(bytes+size>98304)break;bytes+=size;end+=units;}"
        @"var value=environment(phase);value.kind='dom';value.html=html.slice(0,end);value.htmlLength=html.length;"
        @"value.htmlCapturedLength=end;value.htmlCapturedBytes=bytes;value.htmlTruncated=end<html.length;post(value);}catch(e){}}"
        @"function failure(kind,event){try{var value=environment(kind);value.kind=kind;"
        @"var reason=kind==='js-rejection'?event.reason:event.error;"
        @"var text=kind==='js-rejection'?(reason!=null&&reason.message!==undefined?reason.message:reason):event.message;"
        @"value.message=text===undefined?'':String(text);value.filename=event.filename==null?'':String(event.filename);"
        @"value.line=event.lineno==null?'':String(event.lineno);value.column=event.colno==null?'':String(event.colno);"
        @"value.stack=String(reason&&reason.stack||'');post(value);}catch(e){}}"
        @"window.addEventListener('error',function(event){failure('js-error',event);},true);"
        @"window.addEventListener('unhandledrejection',function(event){failure('js-rejection',event);},false);"
        @"report('start');document.addEventListener('DOMContentLoaded',function(){report('dom-ready');dom('dom-ready');},false);"
        @"window.addEventListener('pageshow',function(){report('pageshow');dom('pageshow');},false);})();";
}

static NSString *SHDWWebFrameDiagnosticHTML(NSString *html) {
    NSString *bounded = SHDWCurlDiagnosticString(html, 98304);
    NSData *bytes = [bounded dataUsingEncoding:NSUTF8StringEncoding allowLossyConversion:YES];
    if (bytes.length <= 98304) return bounded;
    NSUInteger length = 98304;
    while (length && (((const unsigned char *)bytes.bytes)[length] & 0xc0) == 0x80) length--;
    return [[NSString alloc] initWithData:[bytes subdataWithRange:NSMakeRange(0, length)] encoding:NSUTF8StringEncoding] ?: @"";
}

@interface SHDWWebFrameDiagnosticHandler : NSObject <WKScriptMessageHandler>
@end
@implementation SHDWWebFrameDiagnosticHandler
- (void)userContentController:(WKUserContentController *)controller didReceiveScriptMessage:(WKScriptMessage *)message {
    (void)controller;
    int saved = errno;
    @try {
        if (!SHDWCurlDiagnosticsEnabled() || ![message.body isKindOfClass:NSDictionary.class]) return;
        NSDictionary *body = message.body;
        NSMutableDictionary *details = [NSMutableDictionary new];
        for (NSString *key in @[@"phase", @"href", @"documentURL", @"baseURI", @"origin", @"userAgent", @"language", @"platform"])
            if ([body[key] isKindOfClass:NSString.class]) details[key] = SHDWCurlDiagnosticString(body[key], 4096);
        id secure = body[@"isSecureContext"];
        if ([secure isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)secure) == CFBooleanGetTypeID())
            details[@"isSecureContext"] = secure;
        NSMutableArray *languages = [NSMutableArray new];
        if ([body[@"languages"] isKindOfClass:NSArray.class])
            for (id language in body[@"languages"]) {
                if (languages.count == 16) break;
                if ([language isKindOfClass:NSString.class]) [languages addObject:SHDWCurlDiagnosticString(language, 128)];
            }
        details[@"languages"] = languages;
        NSString *kind = [body[@"kind"] isKindOfClass:NSString.class] ? body[@"kind"] : @"";
        BOOL failure = [kind isEqual:@"js-error"] || [kind isEqual:@"js-rejection"];
        BOOL dom = [kind isEqual:@"dom"];
        if (!failure && !dom) {
        NSMutableDictionary *parameters = [NSMutableDictionary new];
        NSDictionary *supplied = [body[@"ddParameters"] isKindOfClass:NSDictionary.class] ? body[@"ddParameters"] : nil;
        for (NSString *key in @[@"rt", @"cid", @"hsh", @"cookie", @"t", @"s", @"e", @"host", @"r", @"rr", @"qp"]) {
            id value = supplied[key];
            if ([value isKindOfClass:NSString.class]) parameters[key] = SHDWCurlDiagnosticString(value, 16384);
            else if ([value isKindOfClass:NSNumber.class] || value == NSNull.null) parameters[key] = value;
        }
        if ([supplied[@"cp"] isKindOfClass:NSDictionary.class]) {
            NSMutableDictionary *custom = [NSMutableDictionary new];
            for (NSString *key in @[@"name", @"value"]) {
                id value = supplied[@"cp"][key];
                if ([value isKindOfClass:NSString.class]) custom[key] = SHDWCurlDiagnosticString(value, 16384);
                else if ([value isKindOfClass:NSNumber.class] || value == NSNull.null) custom[key] = value;
            }
            parameters[@"cp"] = custom;
        }
        details[@"ddParameters"] = parameters;
        NSMutableArray *frames = [NSMutableArray new];
        if ([body[@"iframeURLs"] isKindOfClass:NSArray.class])
            for (id url in body[@"iframeURLs"]) {
                if (frames.count == 16) break;
                if ([url isKindOfClass:NSString.class]) [frames addObject:SHDWCurlDiagnosticString(url, 16384)];
            }
        details[@"iframeURLs"] = frames;
        for (NSString *key in @[@"documentCookies", @"documentDatadomeCookie", @"cookieReadError"])
            if ([body[key] isKindOfClass:NSString.class]) details[key] = SHDWCurlDiagnosticString(body[key], 16384);
        }
        if (failure) {
            details[@"kind"] = kind;
            for (NSString *key in @[@"message", @"filename", @"line", @"column", @"stack"])
                if ([body[key] isKindOfClass:NSString.class]) details[key] = SHDWCurlDiagnosticString(body[key], [key isEqual:@"line"] || [key isEqual:@"column"] ? 128 : 16384);
        }
        if (dom) {
            if (![[NSURLComponents componentsWithString:details[@"href"] ?: @""].host.lowercaseString isEqual:@"geo.captcha-delivery.com"]) return;
            details[@"kind"] = kind;
            if ([body[@"html"] isKindOfClass:NSString.class]) {
                NSString *html = SHDWWebFrameDiagnosticHTML(body[@"html"]); details[@"html"] = html;
                details[@"htmlCapturedLength"] = @(html.length);
                details[@"htmlCapturedBytes"] = @([html lengthOfBytesUsingEncoding:NSUTF8StringEncoding]);
            }
            id length = body[@"htmlLength"];
            if ([length isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)length) != CFBooleanGetTypeID() &&
                isfinite([length doubleValue]) && [length doubleValue] >= 0) details[@"htmlLength"] = length;
            id truncated = body[@"htmlTruncated"];
            if ([truncated isKindOfClass:NSNumber.class] && CFGetTypeID((__bridge CFTypeRef)truncated) == CFBooleanGetTypeID())
                details[@"htmlTruncated"] = @([truncated boolValue] || ([body[@"html"] isKindOfClass:NSString.class] && [body[@"html"] length] > [details[@"html"] length]));
        }
        NSMutableArray *query = [NSMutableArray new];
        NSURLComponents *url = [NSURLComponents componentsWithString:details[@"href"] ?: @""];
        for (NSURLQueryItem *item in url.queryItems) {
            if (query.count == 64) break;
            [query addObject:@{@"name":SHDWCurlDiagnosticString(item.name, 1024),
                @"value":item.value ? SHDWCurlDiagnosticString(item.value, 16384) : (id)NSNull.null}];
        }
        details[@"urlQueryItems"] = query;
        details[@"isMainFrame"] = @(message.frameInfo.mainFrame);
        details[@"frameHost"] = message.frameInfo.securityOrigin.host ?: @"";
        NSString *scheme = message.frameInfo.securityOrigin.protocol;
        if ([scheme isKindOfClass:NSString.class]) details[@"securityOriginScheme"] = SHDWCurlDiagnosticString(scheme, 128);
        details[@"webView"] = [NSString stringWithFormat:@"%p", (__bridge void *)message.webView];
        SHDWCurlTrace(failure ? @"webview.frame.error" : dom ? @"webview.frame.dom" : @"webview.frame.environment", message.frameInfo.request, details);
    } @catch (__unused NSException *exception) {
    } @finally { errno = saved; }
}
@end

void SHDWWebFrameDiagnosticsInstall(WKWebViewConfiguration *configuration) {
    int saved = errno;
    @try {
        WKUserContentController *controller = configuration.userContentController;
        if (!controller) return;
        @synchronized(controller) {
            if (!objc_getAssociatedObject(controller, &controllerHandlerKey)) {
                SHDWWebFrameDiagnosticHandler *handler = [SHDWWebFrameDiagnosticHandler new];
                [controller addScriptMessageHandler:handler name:frameHandlerName];
                objc_setAssociatedObject(controller, &controllerHandlerKey, handler, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
            }
            WKUserScript *script = objc_getAssociatedObject(controller, &controllerScriptKey);
            if (script && [controller.userScripts containsObject:script]) return;
            Class scriptClass = objc_getClass("WKUserScript");
            script = [[scriptClass alloc] initWithSource:SHDWWebFrameDiagnosticSource()
                injectionTime:WKUserScriptInjectionTimeAtDocumentStart forMainFrameOnly:NO];
            if (script) {
                [controller addUserScript:script];
                objc_setAssociatedObject(controller, &controllerScriptKey, script, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
            }
        }
    } @catch (__unused NSException *exception) {
    } @finally { errno = saved; }
}
#else
void SHDWWebFrameDiagnosticsInstall(WKWebViewConfiguration *configuration) { (void)configuration; }
#endif
