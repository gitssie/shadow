#import "CurlTransport.h"
#import "FingerprintStorage.h"

void SHDWCurlTransportPrepare(void) {
#if SHADOW_CURL_IMPERSONATE
    NSDictionary *configuration = SHDWFingerprintConfig(NSBundle.mainBundle.bundleIdentifier);
    SHDWCurlTransportPrepareProfile(configuration[@"Network"][@"Transport"]);
#endif
}
