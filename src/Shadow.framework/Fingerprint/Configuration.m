#import <Shadow/FingerprintConfiguration.h>
#import <CoreFoundation/CoreFoundation.h>
#include <sys/sysctl.h>
#include <math.h>
#include <string.h>

static NSDictionary *SHDWConfigurationInvalid(NSError **error) {
  if (error) *error = [NSError errorWithDomain:@"me.jjolano.shadow.fingerprint" code:7
    userInfo:@{NSLocalizedDescriptionKey:@"Invalid fingerprint configuration."}];
  return nil;
}
static BOOL SHDWConfigurationKeys(NSDictionary *value, NSArray *required, NSArray *optional) {
  if (![value isKindOfClass:NSDictionary.class]) return NO;
  NSMutableSet *allowed = [NSMutableSet setWithArray:required];
  [allowed addObjectsFromArray:optional];
  for (id key in value) if (![allowed containsObject:key]) return NO;
  for (id key in required) if (!value[key]) return NO;
  return YES;
}
static NSString *SHDWConfigurationCurrentProductType(void) {
  char product[128] = {0}; size_t length = sizeof(product);
  if (sysctlbyname("hw.machine", product, &length, NULL, 0) != 0 ||
      length == 0 || length >= sizeof(product)) return nil;
  product[sizeof(product)-1] = 0;
  return [NSString stringWithUTF8String:product];
}

static NSString *SHDWConfigurationNativeString(const char *name) {
  char buffer[4096] = {0}; size_t length = sizeof(buffer);
  if (sysctlbyname(name, buffer, &length, NULL, 0) != 0 || length == 0 || length > sizeof(buffer)) return nil;
  if (buffer[length - 1] != 0 || strnlen(buffer, length) != length - 1) return nil;
  return [NSString stringWithUTF8String:buffer];
}

static NSString *SHDWConfigurationRegion(id value) {
  if (![value isKindOfClass:NSString.class]) return nil;
  if ([value isEqualToString:@"native"]) return value;
  if ([value length] != 2) return nil;
  for (NSUInteger i = 0; i < 2; i++) {
    unichar c = [value characterAtIndex:i];
    if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'))) return nil;
  }
  NSString *region = [value uppercaseString];
  return [[SHDWFingerprintConfiguration supportedLocalizationRegions] containsObject:region] ? region : nil;
}
static NSString *SHDWConfigurationLanguage(id value) {
  if (![value isKindOfClass:NSString.class]) return nil;
  if ([value isEqualToString:@"native"]) return value;
  if ([value length] > 255) return nil;
  static NSRegularExpression *syntax;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    syntax = [NSRegularExpression regularExpressionWithPattern:
      @"^(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|[A-Za-z]{5,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*(?:-[xX](?:-[A-Za-z0-9]{1,8})+)?$"
      options:0 error:nil];
  });
  NSTextCheckingResult *match = [syntax firstMatchInString:value options:0 range:NSMakeRange(0, [value length])];
  if (!match || match.range.length != [value length]) return nil;
  NSMutableArray *parts = [[[value lowercaseString] componentsSeparatedByString:@"-"] mutableCopy];
  NSString *primary = [NSLocale canonicalLanguageIdentifierFromString:parts.firstObject];
  NSString *language = [NSLocale componentsFromLocaleIdentifier:primary][NSLocaleLanguageCode];
  if (![NSLocale.ISOLanguageCodes containsObject:language]) return nil;
  NSMutableSet *singletons = [NSMutableSet new];
  NSMutableSet *variants = [NSMutableSet new];
  parts[0] = language;
  NSUInteger cursor = 1;
  if ([parts[0] length] <= 3) {
    NSUInteger extlangs = 0;
    while (cursor < parts.count && [parts[cursor] length] == 3 && extlangs < 3 &&
           [parts[cursor] rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet].location == NSNotFound) {
      cursor++; extlangs++;
    }
  }
  if (cursor < parts.count && [parts[cursor] length] == 4 &&
      [parts[cursor] rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet].location == NSNotFound) {
    parts[cursor] = [parts[cursor] capitalizedString]; cursor++;
  }
  if (cursor < parts.count && ([parts[cursor] length] == 2 ||
      ([parts[cursor] length] == 3 && [parts[cursor] rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet].location != NSNotFound)))
    parts[cursor] = [parts[cursor] uppercaseString];
  BOOL extension = NO;
  for (NSUInteger i = 1; i < parts.count; i++) {
    NSString *part = parts[i];
    if ([part isEqualToString:@"x"]) break;
    if (part.length == 1) {
      if ([singletons containsObject:part]) return nil;
      [singletons addObject:part]; extension = YES;
    } else if (!extension && (part.length >= 5 || (part.length == 4 && [@"0123456789" containsString:[part substringToIndex:1]]))) {
      if ([variants containsObject:part]) return nil;
      [variants addObject:part];
    }
  }
  return [parts componentsJoinedByString:@"-"];
}
static NSDictionary *SHDWConfigurationLocalization(id value) {
  if (!value) return @{@"Region":@"native", @"Language":@"native", @"TimeZone":@"native"};
  if (!SHDWConfigurationKeys(value, @[@"Region",@"Language",@"TimeZone"], @[])) return nil;
  NSString *region = SHDWConfigurationRegion(value[@"Region"]);
  NSString *language = SHDWConfigurationLanguage(value[@"Language"]);
  id storedZone = value[@"TimeZone"];
  if (![@[@"native",@"Europe/Paris",@"Europe/London",@"America/New_York"] containsObject:storedZone]) return nil;
  NSString *zone = [SHDWFingerprintConfiguration timeZoneForRegion:region];
  return region && language && zone ? @{@"Region":region, @"Language":language, @"TimeZone":zone} : nil;
}
static NSDictionary *SHDWConfigurationNativeLocalization(void) {
  static NSDictionary *native;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    NSLocale *locale = NSLocale.currentLocale;
    NSArray *languages = [NSLocale.preferredLanguages copy];
    NSString *country = [locale objectForKey:NSLocaleCountryCode] ?: @"";
    if (!languages.count) languages = @[[locale objectForKey:NSLocaleLanguageCode] ?: @"en"];
    native = @{@"LocaleIdentifier":[locale.localeIdentifier copy], @"Languages":languages,
               @"CountryCode":[country copy], @"TimeZone":[NSTimeZone.systemTimeZone.name copy]};
  });
  return native;
}

@implementation SHDWFingerprintConfiguration
+ (NSArray<NSString *> *)supportedLocalizationRegions {
  return @[@"FR", @"GB", @"US"];
}
+ (NSDictionary *)localizationForRegion:(NSString *)region {
  NSString *code = SHDWConfigurationRegion(region);
  if (!code) return nil;
  static NSDictionary *presets;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    presets = @{
      @"native":@{@"Region":@"native", @"Language":@"native", @"TimeZone":@"native"},
      @"FR":@{@"Region":@"FR", @"Language":@"fr-FR", @"TimeZone":@"Europe/Paris"},
      @"GB":@{@"Region":@"GB", @"Language":@"en-GB", @"TimeZone":@"Europe/London"},
      @"US":@{@"Region":@"US", @"Language":@"en-US", @"TimeZone":@"America/New_York"}
    };
  });
  return presets[code];
}
+ (NSDictionary *)localizationForLanguage:(NSString *)language {
  NSString *canonical = SHDWConfigurationLanguage(language);
  if (!canonical) return nil;
  if ([canonical isEqualToString:@"native"]) return [self localizationForRegion:@"native"];
  for (NSString *region in self.supportedLocalizationRegions) {
    NSDictionary *preset = [self localizationForRegion:region];
    if ([preset[@"Language"] isEqualToString:canonical]) return preset;
  }
  return nil;
}
+ (NSString *)timeZoneForRegion:(NSString *)region {
  return [self localizationForRegion:region][@"TimeZone"];
}
+ (NSDictionary *)defaultConfiguration {
  NSString *productType = SHDWConfigurationCurrentProductType();
  NSDictionary *system = @{@"Mode":@"native"};
  if ([productType hasPrefix:@"iPhone"] && [[productType substringFromIndex:6] integerValue] >= 13) {
    for (NSDictionary *profile in self.systemProfilesForCurrentDevice) {
      if ([profile[@"Version"] isEqualToString:@"18.7.1"]) {
        system = @{@"Mode":@"profile", @"ProfileID":profile[@"ID"]};
        break;
      }
    }
  }
  return @{@"Version":@1, @"System":system,
    @"Network":@{@"RadioTechnologies":@[@"4g",@"5g"]},
    @"Receipts":@{@"InterceptEnabled":@YES}, @"Advertising":@{@"Mode":@"perApp"},
    @"Localization":@{@"Region":@"native", @"Language":@"native", @"TimeZone":@"native"}};
}
+ (NSArray<NSDictionary *> *)allSystemProfiles {
  static NSArray<NSDictionary *> *profiles;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    profiles = @[@{@"ID":@"iphone14-5_ios18.7.1_22H31", @"Name":@"iOS 18.7.1", @"Version":@"18.7.1",
    @"Build":@"22H31", @"Darwin":@"24.6.0",
    @"Kernel":@"Darwin Kernel Version 24.6.0: Tue Aug 12 00:02:59 PDT 2025; root:xnu-11417.140.69.700.6~5/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios18.7.2_22H124", @"Name":@"iOS 18.7.2", @"Version":@"18.7.2",
    @"Build":@"22H124", @"Darwin":@"24.6.0",
    @"Kernel":@"Darwin Kernel Version 24.6.0: Wed Oct 15 21:14:36 PDT 2025; root:xnu-11417.140.69.702.20~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios18.7.8_22H352", @"Name":@"iOS 18.7.8", @"Version":@"18.7.8",
    @"Build":@"22H352", @"Darwin":@"24.6.0",
    @"Kernel":@"Darwin Kernel Version 24.6.0: Wed Mar 4 22:15:14 PST 2026; root:xnu-11417.140.69.706.9~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios18.4_22E240", @"Name":@"iOS 18.4", @"Version":@"18.4",
    @"Build":@"22E240", @"Darwin":@"24.4.0", @"CFNetwork":@"3826.500.111.2.2",
    @"Kernel":@"Darwin Kernel Version 24.4.0: Sat Mar 15 18:24:37 PDT 2025; root:xnu-11417.102.9~20/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.7.2_21H221", @"Name":@"iOS 17.7.2", @"Version":@"17.7.2",
    @"Build":@"21H221", @"Darwin":@"23.6.0", @"CFNetwork":@"1498.700.2",
    @"Kernel":@"Darwin Kernel Version 23.6.0: Thu Sep 12 23:32:59 PDT 2024; root:xnu-10063.142.1.701.1~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.6.1_21G101", @"Name":@"iOS 17.6.1", @"Version":@"17.6.1",
    @"Build":@"21G101", @"Darwin":@"23.6.0", @"CFNetwork":@"1498.700.2",
    @"Kernel":@"Darwin Kernel Version 23.6.0: Fri Jul  5 18:05:40 PDT 2024; root:xnu-10063.142.1~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.5.1_21F90", @"Name":@"iOS 17.5.1", @"Version":@"17.5.1",
    @"Build":@"21F90", @"Darwin":@"23.5.0", @"CFNetwork":@"1496.0.7",
    @"Kernel":@"Darwin Kernel Version 23.5.0: Wed May  1 20:34:31 PDT 2024; root:xnu-10063.122.3~3/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.4.1_21E236", @"Name":@"iOS 17.4.1", @"Version":@"17.4.1",
    @"Build":@"21E236", @"Darwin":@"23.4.0", @"CFNetwork":@"1494.0.7",
    @"Kernel":@"Darwin Kernel Version 23.4.0: Fri Mar  8 23:31:19 PST 2024; root:xnu-10063.102.14~67/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.3.1_21D61", @"Name":@"iOS 17.3.1", @"Version":@"17.3.1",
    @"Build":@"21D61", @"Darwin":@"23.3.0", @"CFNetwork":@"1492.0.1",
    @"Kernel":@"Darwin Kernel Version 23.3.0: Wed Dec 20 17:29:20 PST 2023; root:xnu-10002.82.4~3/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.2.1_21C66", @"Name":@"iOS 17.2.1", @"Version":@"17.2.1",
    @"Build":@"21C66", @"Darwin":@"23.2.0", @"CFNetwork":@"1490.0.4",
    @"Kernel":@"Darwin Kernel Version 23.2.0: Sun Nov 12 06:35:16 PST 2023; root:xnu-10002.60.75.0.3~27/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.1.2_21B101", @"Name":@"iOS 17.1.2", @"Version":@"17.1.2",
    @"Build":@"21B101", @"Darwin":@"23.1.0", @"CFNetwork":@"1485",
    @"Kernel":@"Darwin Kernel Version 23.1.0: Tue Oct 10 02:21:15 PDT 2023; root:xnu-10002.42.9~2/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios17.0.3_21A360", @"Name":@"iOS 17.0.3", @"Version":@"17.0.3",
    @"Build":@"21A360", @"Darwin":@"23.0.0", @"CFNetwork":@"1474",
    @"Kernel":@"Darwin Kernel Version 23.0.0: Sat Sep 30 17:17:57 PDT 2023; root:xnu-10002.2.13~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.7.2_20H115", @"Name":@"iOS 16.7.2", @"Version":@"16.7.2",
    @"Build":@"20H115", @"Darwin":@"22.6.0", @"CFNetwork":@"1410.0.3",
    @"Kernel":@"Darwin Kernel Version 22.6.0: Wed Oct  4 21:56:34 PDT 2023; root:xnu-8796.142.1.701.11~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.6.1_20G81", @"Name":@"iOS 16.6.1", @"Version":@"16.6.1",
    @"Build":@"20G81", @"Darwin":@"22.6.0", @"CFNetwork":@"1410.0.3",
    @"Kernel":@"Darwin Kernel Version 22.6.0: Wed Jun 28 20:52:14 PDT 2023; root:xnu-8796.142.1~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.5.1_20F75", @"Name":@"iOS 16.5.1", @"Version":@"16.5.1",
    @"Build":@"20F75", @"Darwin":@"22.5.0", @"CFNetwork":@"1408.0.4",
    @"Kernel":@"Darwin Kernel Version 22.5.0: Thu Jun  8 17:14:33 PDT 2023; root:xnu-8796.122.5~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.4.1_20E252", @"Name":@"iOS 16.4.1", @"Version":@"16.4.1",
    @"Build":@"20E252", @"Darwin":@"22.4.0", @"CFNetwork":@"1406.0.4",
    @"Kernel":@"Darwin Kernel Version 22.4.0: Mon Mar  6 20:43:00 PST 2023; root:xnu-8796.102.5~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.3.1_20D67", @"Name":@"iOS 16.3.1", @"Version":@"16.3.1",
    @"Build":@"20D67", @"Darwin":@"22.3.0", @"CFNetwork":@"1404.0.5",
    @"Kernel":@"Darwin Kernel Version 22.3.0: Wed Jan  4 21:25:19 PST 2023; root:xnu-8792.82.2~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.2_20C65", @"Name":@"iOS 16.2", @"Version":@"16.2",
    @"Build":@"20C65", @"Darwin":@"22.2.0", @"CFNetwork":@"1402.0.8",
    @"Kernel":@"Darwin Kernel Version 22.2.0: Mon Nov 28 20:10:56 PST 2022; root:xnu-8792.62.2~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.1.2_20B110", @"Name":@"iOS 16.1.2", @"Version":@"16.1.2",
    @"Build":@"20B110", @"Darwin":@"22.1.0", @"CFNetwork":@"1399",
    @"Kernel":@"Darwin Kernel Version 22.1.0: Thu Oct  6 19:34:09 PDT 2022; root:xnu-8792.42.7~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphone14-5_ios16.0.3_20A392", @"Name":@"iOS 16.0.3", @"Version":@"16.0.3",
    @"Build":@"20A392", @"Darwin":@"22.0.0", @"CFNetwork":@"1390",
    @"Kernel":@"Darwin Kernel Version 22.0.0: Tue Oct  4 16:59:37 PDT 2022; root:xnu-8792.2.15~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]},
    @{@"ID":@"iphonex_ios16.7.12_20H364", @"Name":@"iOS 16.7.12", @"Version":@"16.7.12",
    @"Build":@"20H364", @"Darwin":@"22.6.0",
    @"Kernel":@"Darwin Kernel Version 22.6.0: Tue Jul  2 20:47:35 PDT 2024; root:xnu-8796.142.1.703.8~1/RELEASE_ARM64_T8015",
    @"ProductTypes":@[@"iPhone10,3",@"iPhone10,6"]},
    @{@"ID":@"iphonex_ios16.7.16_20H392", @"Name":@"iOS 16.7.16", @"Version":@"16.7.16",
    @"Build":@"20H392", @"Darwin":@"22.6.0",
    @"Kernel":@"Darwin Kernel Version 22.6.0: Tue Jul  2 20:47:35 PDT 2024; root:xnu-8796.142.1.703.8~1/RELEASE_ARM64_T8015",
    @"ProductTypes":@[@"iPhone10,3",@"iPhone10,6"]}];
    NSMutableArray *resolved = [NSMutableArray arrayWithCapacity:profiles.count];
    for (NSDictionary *profile in profiles) {
      NSString *version = profile[@"Version"];
      if ([version isEqualToString:@"18.7"] || [version hasPrefix:@"18.7."]) {
        NSMutableDictionary *system = [profile mutableCopy];
        system[@"CFNetwork"] = @"3826.600.41";
        [resolved addObject:[system copy]];
      } else [resolved addObject:profile];
    }
    profiles = [resolved copy];
  });
  return profiles;
}
+ (NSArray<NSDictionary *> *)systemProfilesForCurrentDevice {
  NSString *productType = SHDWConfigurationCurrentProductType();
  if (!productType) return @[];
  NSMutableArray *profiles = [NSMutableArray new];
  for (NSDictionary *profile in self.allSystemProfiles)
    if ([profile[@"ProductTypes"] containsObject:productType]) [profiles addObject:profile];
  return [profiles copy];
}
+ (NSDictionary *)systemProfileForConfiguration:(NSDictionary *)configuration {
  NSDictionary *system = configuration[@"System"];
  if (![system isKindOfClass:NSDictionary.class] || ![system[@"Mode"] isEqual:@"profile"]) return nil;
  for (NSDictionary *profile in self.allSystemProfiles)
    if ([profile[@"ID"] isEqual:system[@"ProfileID"]]) return profile;
  return nil;
}
+ (NSDictionary *)resolvedSystemForConfiguration:(NSDictionary *)configuration {
  NSDictionary *profile = [self systemProfileForConfiguration:configuration];
  if (profile) return profile;
  NSMutableDictionary *system = [NSMutableDictionary new];
  NSDictionary *queries = @{@"Version":@"kern.osproductversion", @"Build":@"kern.osversion",
                            @"Darwin":@"kern.osrelease", @"Kernel":@"kern.version"};
  for (NSString *key in queries) {
    NSString *value = SHDWConfigurationNativeString([queries[key] UTF8String]);
    if (value.length) system[key] = value;
  }
  if (!system[@"Version"]) {
    NSOperatingSystemVersion version = NSProcessInfo.processInfo.operatingSystemVersion;
    system[@"Version"] = [NSString stringWithFormat:@"%ld.%ld.%ld", (long)version.majorVersion,
                          (long)version.minorVersion, (long)version.patchVersion];
  }
  return [system copy];
}

+ (NSDictionary *)resolvedLocalizationForConfiguration:(NSDictionary *)configuration {
  NSDictionary *chosen = SHDWConfigurationLocalization(configuration[@"Localization"]);
  if (!chosen) return nil;
  NSDictionary *native = SHDWConfigurationNativeLocalization();
  BOOL nativeRegion = [chosen[@"Region"] isEqualToString:@"native"];
  BOOL nativeLanguage = [chosen[@"Language"] isEqualToString:@"native"];
  NSString *country = nativeRegion ? native[@"CountryCode"] : chosen[@"Region"];
  NSArray *languages = nativeLanguage ? native[@"Languages"] : @[chosen[@"Language"]];
  NSString *locale = native[@"LocaleIdentifier"];
  if (!nativeRegion || !nativeLanguage) {
    NSString *source = nativeLanguage ? native[@"LocaleIdentifier"] : chosen[@"Language"];
    NSDictionary *components = [NSLocale componentsFromLocaleIdentifier:source];
    NSMutableDictionary *selected = nativeLanguage ? [NSMutableDictionary new] : [components mutableCopy];
    selected[NSLocaleLanguageCode] = components[NSLocaleLanguageCode] ?: @"en";
    if (components[NSLocaleScriptCode]) selected[NSLocaleScriptCode] = components[NSLocaleScriptCode];
    if ([country length]) selected[NSLocaleCountryCode] = country;
    else [selected removeObjectForKey:NSLocaleCountryCode];
    locale = [NSLocale localeIdentifierFromComponents:selected];
  }
  NSString *zone = [chosen[@"TimeZone"] isEqualToString:@"native"] ? native[@"TimeZone"] : chosen[@"TimeZone"];
  BOOL overrides = ![locale isEqual:native[@"LocaleIdentifier"]] ||
    ![languages isEqual:native[@"Languages"]] || ![zone isEqual:native[@"TimeZone"]];
  return @{@"LocaleIdentifier":locale, @"Languages":languages, @"TimeZone":zone,
           @"CountryCode":country, @"OverridesSystem":@(overrides)};
}

+ (NSDictionary *)configurationByValidating:(id)value error:(NSError **)error {
  if (!SHDWConfigurationKeys(value, @[@"Version",@"System",@"Network",@"Receipts"], @[@"UpdatedAt",@"Advertising",@"Localization"]))
    return SHDWConfigurationInvalid(error);
  NSDictionary *localization = SHDWConfigurationLocalization(value[@"Localization"]);
  if (!localization) return SHDWConfigurationInvalid(error);
  NSNumber *version = value[@"Version"], *updated = value[@"UpdatedAt"];
  if (![version isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)version) == CFBooleanGetTypeID() ||
      version.doubleValue != 1 || (updated && (![updated isKindOfClass:NSNumber.class] ||
      CFGetTypeID((__bridge CFTypeRef)updated) == CFBooleanGetTypeID() || !isfinite(updated.doubleValue) || updated.doubleValue < 0)))
    return SHDWConfigurationInvalid(error);
  NSDictionary *system=value[@"System"], *network=value[@"Network"], *receipts=value[@"Receipts"];
  if (!SHDWConfigurationKeys(system,@[@"Mode"],@[@"ProfileID"]) ||
      !SHDWConfigurationKeys(network,@[@"RadioTechnologies"],@[@"Transport"]) ||
      !SHDWConfigurationKeys(receipts,@[@"InterceptEnabled"],@[])) return SHDWConfigurationInvalid(error);
  if (network[@"Transport"] && ![@[@"native", @"safari184_ios"] containsObject:network[@"Transport"]])
    return SHDWConfigurationInvalid(error);
  if ([system[@"Mode"] isEqual:@"native"]) {
    if (system[@"ProfileID"]) return SHDWConfigurationInvalid(error);
  } else if (![system[@"Mode"] isEqual:@"profile"] ||
             ![self.systemProfilesForCurrentDevice containsObject:[self systemProfileForConfiguration:value] ?: @{}]) {
    return SHDWConfigurationInvalid(error);
  }
  id advertising=value[@"Advertising"];
  if (advertising && (!SHDWConfigurationKeys(advertising,@[@"Mode"],@[]) ||
      ![@[@"system",@"zero",@"perApp"] containsObject:advertising[@"Mode"]])) return SHDWConfigurationInvalid(error);
  NSArray *radios=network[@"RadioTechnologies"];
  if (![radios isKindOfClass:NSArray.class] || radios.count > 2)
    return SHDWConfigurationInvalid(error);
  NSMutableSet *seen=[NSMutableSet new];
  for (id radio in radios) {
    if (![@[@"4g",@"5g"] containsObject:radio] || [seen containsObject:radio]) return SHDWConfigurationInvalid(error);
    [seen addObject:radio];
  }
  id intercept=receipts[@"InterceptEnabled"];
  if (![intercept isKindOfClass:NSNumber.class] || CFGetTypeID((__bridge CFTypeRef)intercept) != CFBooleanGetTypeID())
    return SHDWConfigurationInvalid(error);
  NSMutableDictionary *normalized = [value mutableCopy];
  normalized[@"Localization"] = localization;
  return [NSPropertyListSerialization propertyListWithData:
    [NSPropertyListSerialization dataWithPropertyList:normalized format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil]
    options:NSPropertyListImmutable format:NULL error:nil];
}
@end
