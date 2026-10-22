#import <Shadow/Fingerprint.h>
#import <Shadow/Settings.h>
#import <Shadow/FingerprintState.h>
#import <Shadow/SHDWPlugin.h>
#import "Profile.h"
#import "../../common.h"

static BOOL SHDWFingerprintStoreFailure(NSError **error, NSInteger code,
                                      NSString *message) {
  if (error) {
    *error = [NSError errorWithDomain:@"me.jjolano.shadow.fingerprint" code:code
                            userInfo:@{NSLocalizedDescriptionKey: message}];
  }
  return NO;
}

@implementation SHDWFingerprintStore
+ (instancetype)sharedStore {
  static SHDWFingerprintStore *store;
  static dispatch_once_t once;
  dispatch_once(&once, ^{ store = [self new]; });
  return store;
}

- (BOOL)validIdentifier:(NSString *)bundleID error:(NSError **)error {
  if (![bundleID isKindOfClass:NSString.class] || bundleID.length == 0 ||
      [bundleID rangeOfCharacterFromSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].location != NSNotFound) {
    return SHDWFingerprintStoreFailure(error, 1, @"Invalid application identifier.");
  }
  return YES;
}

- (NSDictionary *)application:(NSString *)bundleID {
  @synchronized(ShadowSettings.sharedInstance) {
    if (![self validIdentifier:bundleID error:nil]) return nil;
    NSUserDefaults *defaults = ShadowSettings.sharedInstance.userDefaults;
    [defaults synchronize];
    id app = [defaults objectForKey:bundleID];
    return [app isKindOfClass:NSDictionary.class] ? app : nil;
  }
}

- (NSArray<NSString *> *)registeredBundleIdentifiers {
  @synchronized(ShadowSettings.sharedInstance) {
    NSUserDefaults *defaults = ShadowSettings.sharedInstance.userDefaults;
    [defaults synchronize];
    NSDictionary *domain = [defaults persistentDomainForName:@SHADOW_PREFS_PLIST];
    NSMutableArray *identifiers = [NSMutableArray new];
    for (NSString *key in domain) {
      id app = domain[key];
      if ([app isKindOfClass:NSDictionary.class] &&
          SHDWFingerprintApplicationIsRegistered(app) &&
          [self validIdentifier:key error:nil]) {
        [identifiers addObject:key];
      }
  }
  return [identifiers sortedArrayUsingSelector:@selector(compare:)];
  }
}

- (NSDictionary *)profileForBundleIdentifier:(NSString *)bundleID {
  if (![self validIdentifier:bundleID error:nil]) return nil;
  id data = [self application:bundleID][@"Fingerprint_Data"];
  return [data isKindOfClass:NSDictionary.class] && [data count] > 0 ? [data copy] : nil;
}

- (BOOL)saveApplication:(NSDictionary *)app identifier:(NSString *)bundleID
                 error:(NSError **)error {
  NSUserDefaults *defaults = ShadowSettings.sharedInstance.userDefaults;
  id previous = [defaults objectForKey:bundleID];
  [defaults setObject:app forKey:bundleID];
  if (![defaults synchronize]) {
    if (previous) [defaults setObject:previous forKey:bundleID];
    else [defaults removeObjectForKey:bundleID];
    [defaults synchronize];
    return SHDWFingerprintStoreFailure(error, 3, @"Unable to save application settings.");
  }
  return YES;
}

- (BOOL)registerApplication:(NSString *)bundleID error:(NSError **)error {
  @synchronized(ShadowSettings.sharedInstance) {
    if (![self validIdentifier:bundleID error:error]) return NO;
    NSMutableDictionary *app = [[self application:bundleID] mutableCopy] ?: [NSMutableDictionary new];
    app[@"Fingerprint_Managed"] = @YES;
    if (!app[@"Fingerprint_Enabled"]) app[@"Fingerprint_Enabled"] = @YES;
    if (!app[@"Fingerprint_Locked"]) app[@"Fingerprint_Locked"] = @NO;
    app[SHDWAppEnabledID] = @YES;
    [app removeObjectForKey:SHDWAppDisabledID];
    return [self saveApplication:app identifier:bundleID error:error];
  }
}

- (BOOL)refreshApplication:(NSString *)bundleID error:(NSError **)error {
  @synchronized(ShadowSettings.sharedInstance) {
    if (![self validIdentifier:bundleID error:error]) return NO;
    NSDictionary *app = [self application:bundleID];
    if (!SHDWFingerprintApplicationIsRegistered(app)) {
      return SHDWFingerprintStoreFailure(error, 4, @"Application is not registered.");
    }
    if (!SHDWFingerprintApplicationEnabled(app)) {
      return SHDWFingerprintStoreFailure(error, 5, @"Fingerprint is disabled.");
    }
    if (SHDWFingerprintApplicationLocked(app)) {
      return SHDWFingerprintStoreFailure(error, 6, @"Fingerprint is locked.");
    }
    if (![ShadowSettings.sharedInstance refreshFingerprintDataForIdentifier:bundleID lockOnSuccess:YES]) {
      return SHDWFingerprintStoreFailure(error, 2, @"Unable to generate a valid device profile.");
    }
    return YES;
  }
}

- (BOOL)removeApplication:(NSString *)bundleID error:(NSError **)error {
  @synchronized(ShadowSettings.sharedInstance) {
    if (![self validIdentifier:bundleID error:error]) return NO;
    NSDictionary *existing = [self application:bundleID];
    if (SHDWFingerprintApplicationLocked(existing)) {
      return SHDWFingerprintStoreFailure(error, 6, @"Fingerprint is locked.");
    }
    if (!existing[@"Fingerprint_Data"] && !existing[@"Fingerprint_Managed"] &&
        !existing[@"Fingerprint_Enabled"] && !existing[@"Fingerprint_Locked"]) return YES;
    NSMutableDictionary *app = [existing mutableCopy];
    [app removeObjectForKey:@"Fingerprint_Data"];
    [app removeObjectForKey:@"Fingerprint_Managed"];
    [app removeObjectForKey:@"Fingerprint_Enabled"];
    [app removeObjectForKey:@"Fingerprint_Locked"];
    return [self saveApplication:app identifier:bundleID error:error];
  }
}

- (BOOL)enabledForApplication:(NSString *)bundleID {
  NSDictionary *app = [self application:bundleID];
  return SHDWFingerprintApplicationIsRegistered(app) &&
         SHDWFingerprintApplicationEnabled(app);
}

- (BOOL)lockedForApplication:(NSString *)bundleID {
  NSDictionary *app = [self application:bundleID];
  return SHDWFingerprintApplicationIsRegistered(app) &&
         SHDWFingerprintApplicationLocked(app);
}

- (BOOL)setStateValue:(BOOL)value key:(NSString *)key
    forApplication:(NSString *)bundleID error:(NSError **)error {
  if (![self validIdentifier:bundleID error:error]) return NO;
  @synchronized(ShadowSettings.sharedInstance) {
    NSDictionary *existing = [self application:bundleID];
    if (!SHDWFingerprintApplicationIsRegistered(existing)) {
      return SHDWFingerprintStoreFailure(error, 4, @"Application is not registered.");
    }
    NSMutableDictionary *app = [existing mutableCopy];
    app[key] = @(value);
    if ([key isEqualToString:SHDWAppEnabledID]) [app removeObjectForKey:SHDWAppDisabledID];
    return [self saveApplication:app identifier:bundleID error:error];
  }
}

- (BOOL)setEnabled:(BOOL)value forApplication:(NSString *)bundleID error:(NSError **)error {
  return [self setStateValue:value key:@"Fingerprint_Enabled" forApplication:bundleID error:error];
}

- (BOOL)setLocked:(BOOL)value forApplication:(NSString *)bundleID error:(NSError **)error {
  return [self setStateValue:value key:@"Fingerprint_Locked" forApplication:bundleID error:error];
}

- (BOOL)aggressiveForApplication:(NSString *)bundleID {
  if (![self validIdentifier:bundleID error:nil]) return NO;
  return [[ShadowSettings.sharedInstance getPreferencesForIdentifier:bundleID][SHDWDetectorAggressiveID] boolValue];
}

- (BOOL)shadowEnabledForApplication:(NSString *)bundleID {
  if (![self validIdentifier:bundleID error:nil]) return NO;
  return [[ShadowSettings.sharedInstance getPreferencesForIdentifier:bundleID][SHDWAppEnabledID] boolValue];
}

- (BOOL)setShadowEnabled:(BOOL)value forApplication:(NSString *)bundleID error:(NSError **)error {
  return [self setStateValue:value key:SHDWAppEnabledID forApplication:bundleID error:error];
}

- (BOOL)setAggressive:(BOOL)value forApplication:(NSString *)bundleID error:(NSError **)error {
  @synchronized(ShadowSettings.sharedInstance) {
    if (![self validIdentifier:bundleID error:error]) return NO;
    NSMutableDictionary *app = [[self application:bundleID] mutableCopy] ?: [NSMutableDictionary new];
    app[SHDWDetectorAggressiveID] = @(value);
    return [self saveApplication:app identifier:bundleID error:error];
  }
}

- (NSString *)deviceFingerprintForApplication:(NSString *)bundleID {
  NSDictionary *data = [self profileForBundleIdentifier:bundleID];
  return data ? [SHDWFingerprintProfile displayIdentifierForData:data] : nil;
}
@end
