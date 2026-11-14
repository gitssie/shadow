#pragma once
#import <Foundation/Foundation.h>
@class SHDWHookSession, WKWebView;
void SHDWWebCookieDiagnosticsInstall(SHDWHookSession *hooks);
void SHDWWebCookieDiagnosticsObserveView(WKWebView *view, NSURL *baseURL, NSString *phase);
void SHDWWebCookieDiagnosticsStored(NSURLRequest *request, NSHTTPCookieStorage *storage,
    NSURLSessionTask *task, NSArray<NSHTTPCookie *> *cookies);
