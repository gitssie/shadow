#ifndef shadow_settings_h
#define shadow_settings_h

#import <Foundation/Foundation.h>

__attribute__((visibility("default")))
@interface ShadowSettings : NSObject
@property(strong, nonatomic, readonly)
    NSDictionary<NSString *, id> *defaultSettings;
@property(strong, nonatomic, readonly) NSUserDefaults *userDefaults;

+ (instancetype)sharedInstance;
- (BOOL)isValidFingerprintData:(NSDictionary *)data;

- (NSDictionary<NSString *, id> *)getPreferencesForIdentifier:
    (NSString *)bundleIdentifier;
- (NSDictionary *)fingerprintDataForIdentifier:(NSString *)bundleIdentifier;
- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)bundleIdentifier;
- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)bundleIdentifier
                            lockOnSuccess:(BOOL)lockOnSuccess;
- (void)reset;
@end
#endif
