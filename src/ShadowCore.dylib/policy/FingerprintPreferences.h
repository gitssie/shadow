#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>

NSDictionary *SHDWFingerprintPreferenceOverrides(CFStringRef applicationID,
    CFStringRef userName, CFStringRef hostName);
NSDictionary *SHDWFingerprintPreferencesByApplying(NSDictionary *preferences,
    NSArray *keys, NSDictionary *overrides);
