#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
__attribute__((visibility("default")))
@interface SHDWFingerprintConfiguration : NSObject
+ (NSDictionary *)defaultConfiguration;
+ (nullable NSDictionary *)configurationByValidating:(id)value error:(NSError * _Nullable * _Nullable)error;
+ (NSArray<NSDictionary *> *)systemProfilesForCurrentDevice;
+ (nullable NSDictionary *)systemProfileForConfiguration:(NSDictionary *)configuration;
+ (NSDictionary *)resolvedSystemForConfiguration:(NSDictionary *)configuration;
// Concrete process snapshot: LocaleIdentifier, Languages, TimeZone, CountryCode, OverridesSystem.
+ (nullable NSDictionary *)resolvedLocalizationForConfiguration:(NSDictionary *)configuration;
@end
NS_ASSUME_NONNULL_END
