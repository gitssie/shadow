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
    @"Receipts":@{@"InterceptEnabled":@YES}};
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

+ (NSDictionary *)configurationByValidating:(id)value error:(NSError **)error {
  if (!SHDWConfigurationKeys(value, @[@"Version",@"System",@"Network",@"Receipts"], @[@"UpdatedAt"]))
    return SHDWConfigurationInvalid(error);
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
  return [NSPropertyListSerialization propertyListWithData:
    [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil]
    options:NSPropertyListImmutable format:NULL error:nil];
}
@end
