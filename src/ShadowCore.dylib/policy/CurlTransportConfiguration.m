#import "CurlTransport.h"
#import "FingerprintStorage.h"
#import "FingerprintPolicy.h"
#import <Shadow/FingerprintConfiguration.h>

void SHDWCurlTransportPrepare(void) {
#if SHADOW_CURL_IMPERSONATE
    NSDictionary *configuration = SHDWFingerprintConfig(NSBundle.mainBundle.bundleIdentifier);
    SHDWCurlTransportPrepareProfile([SHDWFingerprintConfiguration curlTransportProfileForConfiguration:configuration
        systemVersion:SHDWFingerprintOSVersionString()]);
#endif
}
