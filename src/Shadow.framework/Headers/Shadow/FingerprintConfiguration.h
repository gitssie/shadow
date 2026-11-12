#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
__attribute__((visibility("default")))
@interface SHDWFingerprintConfiguration : NSObject
+ (NSDictionary *)defaultConfiguration;
// Linked selection presets; stored configurations retain their language semantics.
+ (NSArray<NSString *> *)supportedLocalizationRegions;
+ (nullable NSDictionary *)localizationForRegion:(NSString *)region;
+ (nullable NSDictionary *)localizationForLanguage:(NSString *)language;
// Region-linked default: native, FR, GB or US.
+ (nullable NSString *)timeZoneForRegion:(NSString *)region;
+ (nullable NSDictionary *)configurationByValidating:(id)value error:(NSError * _Nullable * _Nullable)error;
+ (NSArray<NSDictionary *> *)systemProfilesForCurrentDevice;
+ (nullable NSDictionary *)systemProfileForConfiguration:(NSDictionary *)configuration;
+ (NSDictionary *)resolvedSystemForConfiguration:(NSDictionary *)configuration;
// Concrete process snapshot: LocaleIdentifier, Languages, TimeZone, CountryCode, OverridesSystem.
+ (nullable NSDictionary *)resolvedLocalizationForConfiguration:(NSDictionary *)configuration;
@end
NS_ASSUME_NONNULL_END
