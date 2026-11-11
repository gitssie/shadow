#import <Foundation/Foundation.h>
void SHDWCurlTransportPrepare(void);
BOOL SHDWCurlTransportReady(void);
NSURLSessionConfiguration *SHDWCurlTransportConfiguration(NSURLSessionConfiguration *configuration);
NSURLRequest *SHDWCurlTransportRequest(NSURLRequest *request, NSURLSession *session);
