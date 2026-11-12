#import "FingerprintLocalization.h"
#import "FingerprintStorage.h"
#import "../hooks/UniversalHooks.h"
#import <Shadow/FingerprintConfiguration.h>

NSDictionary *SHDWFingerprintLocalization(void) {
    static NSDictionary *snapshot;
    static dispatch_once_t once;
    if(!shdw_fingerprint_is_enabled()) return nil;
    dispatch_once(&once, ^{
        SHADOW_INTERNAL_SCOPE {
            NSString *bundleID = NSBundle.mainBundle.bundleIdentifier;
            snapshot = [[SHDWFingerprintConfiguration
                resolvedLocalizationForConfiguration:SHDWFingerprintConfig(bundleID)] copy];
        }
    });
    return snapshot;
}
