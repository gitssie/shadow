#import "FingerprintPreferences.h"
#import "FingerprintLocalization.h"
#import "../hooks/UniversalHooks.h"
#include <errno.h>

NSDictionary *SHDWFingerprintPreferenceOverrides(CFStringRef applicationID,
    CFStringRef userName, CFStringRef hostName) {
    int saved = errno;
    NSDictionary *result = nil;
    if(!applicationID || !userName || !hostName || [Shadow shdwIsInternalRead]) {
        errno = saved;
        return nil;
    }
    SHADOW_INTERNAL_SCOPE {
        if(CFEqual(userName, kCFPreferencesCurrentUser) &&
           (CFEqual(hostName, kCFPreferencesAnyHost) || CFEqual(hostName, kCFPreferencesCurrentHost))) {
            NSString *domain = (__bridge NSString *)applicationID;
            BOOL applies = CFEqual(applicationID, kCFPreferencesCurrentApplication) ||
                CFEqual(applicationID, kCFPreferencesAnyApplication) ||
                [domain isEqualToString:NSGlobalDomain] || [domain isEqualToString:@".GlobalPreferences"] ||
                [domain isEqualToString:NSBundle.mainBundle.bundleIdentifier];
            if(applies) {
                NSDictionary *snapshot = SHDWFingerprintLocalization();
                if([snapshot[@"OverridesSystem"] boolValue])
                    result = @{@"AppleLocale":snapshot[@"LocaleIdentifier"],
                        @"AppleLanguages":snapshot[@"Languages"]};
            }
        }
    }
    errno = saved;
    return result;
}

NSDictionary *SHDWFingerprintPreferencesByApplying(NSDictionary *preferences,
    NSArray *keys, NSDictionary *overrides) {
    int saved = errno;
    BOOL applies = NO;
    for(NSString *key in overrides)
        if(!keys || [keys containsObject:key]) { applies = YES; break; }
    if(!applies) {
        errno = saved;
        return preferences;
    }
    NSMutableDictionary *result = preferences ? [preferences mutableCopy] : [NSMutableDictionary new];
    for(NSString *key in overrides)
        if(!keys || [keys containsObject:key]) result[key] = overrides[key];
    NSDictionary *copy = [result copy];
    errno = saved;
    return copy;
}
