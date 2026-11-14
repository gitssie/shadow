#pragma once
#import <Foundation/Foundation.h>
@class SHDWHookSession;
void SHDWNetworkDiagnosticsInstall(SHDWHookSession *hooks);
void SHDWNetworkDiagnosticsTraceRequestOrigin(NSURLRequest *request, NSString *stage);
void SHDWNetworkDiagnosticsTraceWebHTMLOrigin(NSString *html, NSURL *baseURL);
void SHDWNetworkDiagnosticsAttachUploadData(NSURLSessionTask *task, NSData *data);
void SHDWNetworkDiagnosticsAttachUploadFile(NSURLSessionTask *task, NSURL *fileURL);
