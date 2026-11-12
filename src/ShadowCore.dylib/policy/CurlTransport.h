#import <Foundation/Foundation.h>
void SHDWCurlTransportPrepare(void);
void SHDWCurlTransportPrepareProfile(NSString *profile);
BOOL SHDWCurlTransportReady(void);
BOOL SHDWCurlTransportSupportsWebKitPolicy(NSDictionary *policy);
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration);
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session);
NSURLRequest *SHDWCurlTransportWebKitRequest(NSURLRequest *request, NSURLSession *session);
void SHDWCurlTransportAttachTask(NSURLRequest *request, NSURLSessionTask *task);
