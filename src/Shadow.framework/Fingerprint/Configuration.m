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
  return [NSLocale.ISOCountryCodes containsObject:region] ? region : nil;
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
static NSString *SHDWConfigurationTimeZone(id value) {
  if (![value isKindOfClass:NSString.class]) return nil;
  if ([value isEqualToString:@"native"]) return value;
  if ([value isEqualToString:@"UTC"] || [value isEqualToString:@"Etc/UTC"]) return @"Etc/UTC";
  // Reject Foundation's GMT-offset parser: the persisted choice is an IANA identifier.
  if (![NSTimeZone.knownTimeZoneNames containsObject:value]) return nil;
  return [NSTimeZone timeZoneWithName:value].name;
}
static NSDictionary *SHDWConfigurationLocalization(id value) {
  if (!SHDWConfigurationKeys(value, @[@"Region",@"Language",@"TimeZone"], @[])) return nil;
  NSString *region = SHDWConfigurationRegion(value[@"Region"]);
  NSString *language = SHDWConfigurationLanguage(value[@"Language"]);
  NSString *zone = SHDWConfigurationTimeZone(value[@"TimeZone"]);
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
    @"Receipts":@{@"InterceptEnabled":@YES},
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
    @{@"ID":@"iphone14-5_ios18.7.8_22H352", @"Name":@"iOS 18.7.8", @"Version":@"18.7.8",
    @"Build":@"22H352", @"Darwin":@"24.6.0",
    @"Kernel":@"Darwin Kernel Version 24.6.0: Wed Mar 4 22:15:14 PST 2026; root:xnu-11417.140.69.706.9~1/RELEASE_ARM64_T8110",
    @"ProductTypes":@[@"iPhone14,5"]}];
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
  if (!SHDWConfigurationKeys(value, @[@"Version",@"System",@"Network",@"Receipts",@"Localization"], @[@"UpdatedAt"]))
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
      !SHDWConfigurationKeys(network,@[@"RadioTechnologies"],@[]) ||
      !SHDWConfigurationKeys(receipts,@[@"InterceptEnabled"],@[])) return SHDWConfigurationInvalid(error);
  if ([system[@"Mode"] isEqual:@"native"]) {
    if (system[@"ProfileID"]) return SHDWConfigurationInvalid(error);
  } else if (![system[@"Mode"] isEqual:@"profile"] ||
             ![self.systemProfilesForCurrentDevice containsObject:[self systemProfileForConfiguration:value] ?: @{}]) {
    return SHDWConfigurationInvalid(error);
  }
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
