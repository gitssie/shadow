#import <Shadow/Settings.h>

#import "../common.h"
#import "SettingsMigration.h"
#import <Shadow/HookConfiguration.h>
#import <Shadow/JBPath.h>
#include <math.h>
#include <sys/sysctl.h>
#include <sys/stat.h>
#include <sys/time.h>

static NSString *const kSHDWDetectorRunnerOverridesKey =
    @"Test_DetectorOverrides";
static const NSInteger kSHDWBootOffsetLimit = 24 * 60 * 60;

static double SHDWNativeBootTimestamp(void) {
  struct timeval boot = {0};
  size_t size = sizeof(boot);
  if (sysctlbyname("kern.boottime", &boot, &size, NULL, 0) != 0 ||
      size != sizeof(boot) || boot.tv_sec <= 0 ||
      boot.tv_usec < 0 || boot.tv_usec >= 1000000) {
    return 0;
  }
  return (double)boot.tv_sec + (double)boot.tv_usec / 1000000.0;
}

static NSString *SHDWNativeBootSessionUUID(void) {
  char value[128] = {0};
  size_t size = sizeof(value);
  if (sysctlbyname("kern.bootsessionuuid", value, &size, NULL, 0) != 0 ||
      size == 0 || size > sizeof(value) || value[size - 1] != '\0') {
    return nil;
  }
  NSString *string = [NSString stringWithUTF8String:value];
  NSUUID *uuid = string ? [[NSUUID alloc] initWithUUIDString:string] : nil;
  return uuid.UUIDString;
}

static BOOL SHDWFingerprintBootOffsetBounds(double nativeBoot, double now,
                                           NSInteger *minimum,
                                           NSInteger *maximum) {
  struct stat info = {0};
  if (!isfinite(nativeBoot) || nativeBoot <= 0 || !isfinite(now) ||
      stat("/private/var", &info) != 0 || info.st_birthtimespec.tv_sec <= 0 ||
      info.st_birthtimespec.tv_nsec < 0 ||
      info.st_birthtimespec.tv_nsec >= 1000000000) {
    return NO;
  }
  double birth = (double)info.st_birthtimespec.tv_sec +
                 (double)info.st_birthtimespec.tv_nsec / 1000000000.0;
  double lower = fmax(-kSHDWBootOffsetLimit, ceil(birth - nativeBoot));
  double upper =
      fmin(kSHDWBootOffsetLimit, floor(now - 3600 - nativeBoot) - 1);
  if (lower > upper) {
    return NO;
  }
  *minimum = (NSInteger)lower;
  *maximum = (NSInteger)upper;
  return YES;
}

static BOOL SHDWValidFingerprintData(id value) {
  if (![value isKindOfClass:[NSDictionary class]]) {
    return NO;
  }
  id version = value[@"Version"];
  id delta = value[@"MemoryDelta"];
  id seed = value[@"InterfaceSeed"];
  id bootOffset = value[@"BootTimeOffset"];
  id nativeBoot = value[@"NativeBootTimestamp"];
  id bootUUID = value[@"BootSessionUUID"];
  id nativeBootUUID = value[@"NativeBootSessionUUID"];
  id vendorIdentifier = value[@"VendorIdentifier"];
  if (vendorIdentifier) {
    if (![vendorIdentifier isKindOfClass:[NSString class]]) {
      return NO;
    }
    NSUUID *vendorUUID = [[NSUUID alloc] initWithUUIDString:vendorIdentifier];
    if (!vendorUUID || ![vendorIdentifier isEqualToString:vendorUUID.UUIDString]) {
      return NO;
    }
  }
  if (![version isKindOfClass:[NSNumber class]] ||
      [version doubleValue] != 1.0 ||
      ![delta isKindOfClass:[NSNumber class]] ||
      ![seed isKindOfClass:[NSData class]] || [seed length] != 32 ||
      ![bootOffset isKindOfClass:[NSNumber class]] ||
      ![nativeBoot isKindOfClass:[NSNumber class]] ||
      ![bootUUID isKindOfClass:[NSString class]] ||
      ![nativeBootUUID isKindOfClass:[NSString class]]) {
    return NO;
  }
  double memory = [delta doubleValue];
  double offset = [bootOffset doubleValue];
  double baseline = [nativeBoot doubleValue];
  NSUUID *uuid = [[NSUUID alloc] initWithUUIDString:bootUUID];
  NSUUID *nativeUUID = [[NSUUID alloc] initWithUUIDString:nativeBootUUID];
  if (!isfinite(memory) || memory == 0 || fabs(memory) > 64.0 * 16384.0 ||
      !isfinite(offset) || floor(offset) != offset || fabs(offset) > kSHDWBootOffsetLimit ||
      !isfinite(baseline) || baseline <= 0 ||
      !uuid || ![bootUUID isEqualToString:uuid.UUIDString] ||
      !nativeUUID || ![nativeBootUUID isEqualToString:nativeUUID.UUIDString]) {
    return NO;
  }
  return fmod(fabs(memory), 16384.0) == 0;
}

static NSDictionary *SHDWRepairedFingerprintVendorData(id value) {
  if (![value isKindOfClass:[NSDictionary class]]) {
    return nil;
  }
  if (SHDWValidFingerprintData(value) && value[@"VendorIdentifier"]) {
    return value;
  }
  NSMutableDictionary *repaired = [value mutableCopy];
  [repaired removeObjectForKey:@"VendorIdentifier"];
  if (!SHDWValidFingerprintData(repaired)) {
    return nil;
  }
  repaired[@"VendorIdentifier"] = [NSUUID UUID].UUIDString;
  return [repaired copy];
}

static NSDictionary *SHDWNewFingerprintData(void) {
  double nativeBoot = SHDWNativeBootTimestamp();
  NSString *nativeBootUUID = SHDWNativeBootSessionUUID();
  double now = [[NSDate date] timeIntervalSince1970];
  NSInteger minimumOffset, maximumOffset;
  if (!nativeBootUUID ||
      !SHDWFingerprintBootOffsetBounds(nativeBoot, now, &minimumOffset,
                                       &maximumOffset)) {
    return nil;
  }
  NSInteger bootOffset =
      (NSInteger)arc4random_uniform((uint32_t)(maximumOffset - minimumOffset + 1)) +
      minimumOffset;
  unsigned char seed[32];
  arc4random_buf(seed, sizeof(seed));
  long long delta = (long long)(arc4random_uniform(64) + 1) * 16384;
  if (arc4random_uniform(2)) {
    delta = -delta;
  }
  return @{
    @"Version" : @1,
    @"MemoryDelta" : @(delta),
    @"InterfaceSeed" : [NSData dataWithBytes:seed length:sizeof(seed)],
    @"BootTimeOffset" : @(bootOffset),
    @"NativeBootTimestamp" : @(nativeBoot),
    @"NativeBootSessionUUID" : nativeBootUUID,
    @"BootSessionUUID" : [NSUUID UUID].UUIDString,
    @"VendorIdentifier" : [NSUUID UUID].UUIDString
  };
}

@implementation ShadowSettings
@synthesize defaultSettings, userDefaults;

- (instancetype)init {
  if ((self = [super init])) {
    // Enabled apps all receive this one built-in profile. Stored hook
    // values are intentionally ignored — getPreferencesForIdentifier:
    // copies this dictionary directly, so the profile is never read back
    // through userDefaults. Deliberately no registerDefaults: registering
    // the fixed profile would re-materialize every hook key into the
    // persisted plist as a phantom switch and undo the migration prune.
    defaultSettings = SHDWDefaultHookSettings();

    userDefaults =
        [[NSUserDefaults alloc] initWithSuiteName:@SHADOW_PREFS_PLIST];
    [self migrateLegacyHookSettings];
  }

  return self;
}

- (void)migrateLegacyHookSettings {
  // Read and write the same store. initWithSuiteName: persists through
  // cfprefsd (on rootless, to /var/jb/var/mobile/...), whereas the literal
  // SHADOW_PREFS_PLIST path names a different, stale /var/mobile/... file; a
  // file-sourced snapshot diffs against the wrong store and prunes nothing.
  // persistentDomainForName: returns exactly this suite's stored keys (no
  // global/registration domains), so the rebuild below can never drop a
  // system default.
  NSDictionary *root =
      [userDefaults persistentDomainForName:@SHADOW_PREFS_PLIST];
  if (![root isKindOfClass:[NSDictionary class]]) {
    return;
  }

  NSDictionary *migratedRoot = SHDWMigratedHookSettings(root);
  BOOL firstSingleToggleMigration =
      ![root[SHDWSingleToggleMigrationID] boolValue];
  BOOL legacyGlobalEnabled = [root[SHDWGlobalEnabledID] boolValue];

  // Rebuild the migrated domain and write it back wholesale with
  // setPersistentDomain:forName: — a single atomic replace, rather than
  // per-key setObject:/removeObjectForKey: calls whose removals are the
  // unreliable half through the cfprefsd bridge. The result is exactly the
  // pruned shape.
  NSMutableDictionary *domain = [NSMutableDictionary dictionary];
  for (NSString *key in migratedRoot) {
    id value = migratedRoot[key];
    if ([value isKindOfClass:[NSDictionary class]]) {
      NSMutableDictionary *migratedApp =
          [SHDWMigratedHookSettings(value) mutableCopy];
      if (firstSingleToggleMigration && legacyGlobalEnabled &&
          ![value[SHDWAppDisabledID] boolValue] &&
          ![value[SHDWAppEnabledID] boolValue]) {
        migratedApp[SHDWAppEnabledID] = @YES;
      }
      domain[key] = [migratedApp copy];
    } else {
      domain[key] = value;
    }
  }
  if (firstSingleToggleMigration) {
    domain[SHDWSingleToggleMigrationID] = @YES;
  }

  if (![domain isEqualToDictionary:root]) {
    [userDefaults setPersistentDomain:domain forName:@SHADOW_PREFS_PLIST];
    [userDefaults synchronize];
  }
}

+ (instancetype)sharedInstance {
  static ShadowSettings *sharedInstance = nil;
  static dispatch_once_t onceToken = 0;

  dispatch_once(&onceToken, ^{
    sharedInstance = [self new];
  });

  return sharedInstance;
}

- (void)reset {
  // Wipe the whole persistent domain in one atomic write: global toggle,
  // aggressive mode, and every per-app override drop back to defaults. Same
  // suite name as init so cfprefsd clears the store the runtime reads.
  [userDefaults setPersistentDomain:@{} forName:@SHADOW_PREFS_PLIST];
  [userDefaults synchronize];
}

- (NSDictionary *)fingerprintDataForIdentifier:(NSString *)bundleIdentifier {
  if (bundleIdentifier.length == 0) {
    return nil;
  }
  @synchronized(self) {
    [self.userDefaults synchronize];
    id storedApp = [self.userDefaults objectForKey:bundleIdentifier];
    NSDictionary *app = [storedApp isKindOfClass:[NSDictionary class]]
                            ? storedApp : nil;
    id originalData = app[@"Fingerprint_Data"];
    id data = SHDWRepairedFingerprintVendorData(originalData);
    BOOL needsVendor = data && ![data isEqual:originalData];
    // A sandboxed defaults connection can omit another app's suite data.
    if (!SHDWValidFingerprintData(data)) {
      for (NSString *path in @[
             JBPath(@SHADOW_PREFS_PLIST), @SHADOW_PREFS_PLIST
           ]) {
        NSDictionary *root = [NSDictionary dictionaryWithContentsOfFile:path];
        id fileApp = root[bundleIdentifier];
        if (![fileApp isKindOfClass:[NSDictionary class]]) {
          continue;
        }
        id repaired =
            SHDWRepairedFingerprintVendorData(fileApp[@"Fingerprint_Data"]);
        if (repaired) {
          data = repaired;
          needsVendor = ![data isEqual:fileApp[@"Fingerprint_Data"]];
          if (!app) {
            app = fileApp;
          }
          break;
        }
        if (!app) {
          app = fileApp;
        }
      }
    }

    if (SHDWValidFingerprintData(data)) {
      double nativeBoot = SHDWNativeBootTimestamp();
      NSString *nativeBootUUID = SHDWNativeBootSessionUUID();
      double now = [[NSDate date] timeIntervalSince1970];
      NSInteger minimumOffset, maximumOffset;
      if (!nativeBootUUID ||
          !SHDWFingerprintBootOffsetBounds(nativeBoot, now, &minimumOffset,
                                           &maximumOffset)) {
        NSMutableDictionary *fallback = [data mutableCopy];
        [fallback removeObjectForKey:@"BootTimeOffset"];
        if (needsVendor) {
          [fallback removeObjectForKey:@"VendorIdentifier"];
        }
        return [fallback copy];
      }
      BOOL rebooted =
          ![data[@"NativeBootSessionUUID"] isEqualToString:nativeBootUUID];
      BOOL changedBaseline =
          fabs([data[@"NativeBootTimestamp"] doubleValue] - nativeBoot) >
          0.000001;
      NSInteger existingOffset = [data[@"BootTimeOffset"] integerValue];
      BOOL needsOffset = existingOffset > maximumOffset ||
                         existingOffset < minimumOffset;
      if (!rebooted && !changedBaseline && !needsOffset && !needsVendor) {
        return [data copy];
      }
      NSMutableDictionary *updated = [data mutableCopy];
      updated[@"NativeBootTimestamp"] = @(nativeBoot);
      updated[@"NativeBootSessionUUID"] = nativeBootUUID;
      if (rebooted) {
        updated[@"BootSessionUUID"] = [NSUUID UUID].UUIDString;
      }
      if (needsOffset) {
        updated[@"BootTimeOffset"] =
            @(MIN(maximumOffset, MAX(minimumOffset, existingOffset)));
      }
      NSMutableDictionary *updatedApp =
          [app mutableCopy] ?: [NSMutableDictionary new];
      updatedApp[@"Fingerprint_Data"] = updated;
      [self.userDefaults setObject:updatedApp forKey:bundleIdentifier];
      return [self.userDefaults synchronize] ? [updated copy] : nil;
    }

    NSMutableDictionary *updatedApp =
        [app mutableCopy] ?: [NSMutableDictionary new];
    NSDictionary *generated = SHDWNewFingerprintData();
    if (!generated) {
      return nil;
    }
    updatedApp[@"Fingerprint_Data"] = generated;
    [self.userDefaults setObject:updatedApp forKey:bundleIdentifier];
    return [self.userDefaults synchronize] ? generated : nil;
  }
}

- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)bundleIdentifier {
  if (bundleIdentifier.length == 0) {
    return NO;
  }
  @synchronized(self) {
    [self.userDefaults synchronize];
    id storedApp = [self.userDefaults objectForKey:bundleIdentifier];
    if (![storedApp isKindOfClass:[NSDictionary class]]) {
      for (NSString *path in @[
             JBPath(@SHADOW_PREFS_PLIST), @SHADOW_PREFS_PLIST
           ]) {
        NSDictionary *root = [NSDictionary dictionaryWithContentsOfFile:path];
        id fileApp = root[bundleIdentifier];
        if ([fileApp isKindOfClass:[NSDictionary class]]) {
          storedApp = fileApp;
          break;
        }
      }
    }
    NSMutableDictionary *app =
        [storedApp isKindOfClass:[NSDictionary class]]
            ? [storedApp mutableCopy] : [NSMutableDictionary new];
    NSDictionary *generated = SHDWNewFingerprintData();
    if (!generated) {
      return NO;
    }
    app[@"Fingerprint_Data"] = generated;
    [self.userDefaults setObject:app forKey:bundleIdentifier];
    return [self.userDefaults synchronize];
  }
}

- (NSDictionary<NSString *, id> *)getPreferencesForIdentifier:
    (NSString *)bundleIdentifier {
  if (!userDefaults) {
    return nil;
  }

  NSMutableDictionary *result = [defaultSettings mutableCopy];
  NSDictionary *app_settings =
      bundleIdentifier ? [userDefaults objectForKey:bundleIdentifier] : nil;
  NSDictionary *filePreferences = nil;
  NSDictionary *fileAppSettings = nil;
  // Sandboxed cfprefsd can omit another app's dictionary despite libSandy's
  // file grant.
  if (bundleIdentifier) {
    id fileRoot =
        [NSDictionary dictionaryWithContentsOfFile:@SHADOW_PREFS_PLIST];
    filePreferences =
        [fileRoot isKindOfClass:[NSDictionary class]] ? fileRoot : nil;
    id fileSettings = filePreferences[bundleIdentifier];
    fileAppSettings = [fileSettings isKindOfClass:[NSDictionary class]]
                          ? SHDWMigratedHookSettings(fileSettings)
                          : nil;
  }
  if (!app_settings) {
    app_settings = fileAppSettings;
  }

  // Test profiles are file-authoritative so cfprefsd cannot retain an old
  // arm while the device driver swaps the backing plist.
  if ([bundleIdentifier isEqualToString:@"me.jjolano.shadow.harness"] &&
      filePreferences) {
    app_settings = fileAppSettings;
  }

  BOOL enabled = SHDWApplicationEnabled(
      app_settings, [userDefaults boolForKey:SHDWGlobalEnabledID],
      [userDefaults boolForKey:SHDWSingleToggleMigrationID],
      [bundleIdentifier isEqualToString:@"me.jjolano.shadow.harness"] ||
          bundleIdentifier.length == 0);
  result[SHDWAppEnabledID] = @(enabled);

  // Aggressive detector neutralization: per-app override, else the global
  // default. Written into the returned profile so the coordinator/adapters
  // can gate their disable-style paths on it. Detector runners resolve it the
  // same way (their app_settings are file-authoritative), so the harness can
  // exercise natural vs aggressive by writing the key into a runner's profile
  // or the global scalar; it defaults to NO (natural) like every other app.
  result[SHDWDetectorAggressiveID] = @(SHDWDetectorAggressiveEnabled(
      app_settings, [userDefaults boolForKey:SHDWDetectorAggressiveID]));

  // Pseudo-sandbox mode: a global scalar resolved from userDefaults rather
  // than the fixed profile's constant. The profile exists to force full
  // capability, so taking the mode from it would leave the engine permanently
  // off. Absent (the normal case) reads 0 = off, which keeps every belt
  // verdict byte-identical to a build without the mode.
  result[SHDWUniversalPseudoSandboxModeID] =
      @([userDefaults integerForKey:SHDWUniversalPseudoSandboxModeID]);

  if (enabled) {
    // Not user configuration: the device evidence driver can disable one
    // adapter for the harness's embedded detectors without weakening
    // normal app profiles.
    NSDictionary *overrides =
        [bundleIdentifier isEqualToString:@"me.jjolano.shadow.harness"] &&
                [app_settings[kSHDWDetectorRunnerOverridesKey]
                    isKindOfClass:[NSDictionary class]]
            ? app_settings[kSHDWDetectorRunnerOverridesKey]
            : nil;
    for (NSString *key in @[
           SHDWAdapterDeviceCheckID, SHDWAdapterFreeRASPID,
           SHDWAdapterDeviceSecurityKitID, SHDWAdapterIOSSecuritySuiteID
         ]) {
      id value = overrides[key];
      if ([value isKindOfClass:[NSNumber class]]) {
        result[key] = @([value boolValue]);
      }
    }

    // Harness normally records a universal baseline before SDK-specific
    // hooks load. Its explicit test mode may opt into a fully prearmed
    // detector run without changing any other app's behavior.
    if ([bundleIdentifier isEqualToString:@"me.jjolano.shadow.harness"]) {
      id baseline = [app_settings objectForKey:SHDWUniversalHarnessBaselineID];
      if (baseline != nil) {
        result[SHDWUniversalHarnessBaselineID] = baseline;
      }
    }
  }

  return [result copy];
}
@end
