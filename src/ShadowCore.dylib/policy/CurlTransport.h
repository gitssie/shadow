#import <Foundation/Foundation.h>
void SHDWCurlTransportPrepare(void);
void SHDWCurlTransportPrepareProfile(NSString *profile);
BOOL SHDWCurlTransportReady(void);
void SHDWCurlTransportTraceRequest(NSURLRequest *request, NSString *stage, NSString *reason);
