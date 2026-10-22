"""Execute the shared manager API and production Settings against an isolated suite."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
framework = root / "src/Shadow.framework"

def without_imports(path):
    return "\n".join(line for line in path.read_text().splitlines()
                     if not line.startswith("#import"))

source = r'''
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#import <Shadow/Settings.h>
#import <Shadow/SHDWPlugin.h>
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>
#import <CoreFoundation/CoreFoundation.h>
#import <Shadow/FingerprintState.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <math.h>
#include <assert.h>
#include <string.h>
#define SHADOW_PREFS_PLIST "shadow-manager-host-tests"
#define JBPath(path) (path)
static const char *managerProductType = "iPhone14,5";
static BOOL managerFailVersionQueries;
static int managerSysctl(const char *name, void *out, size_t *length, void *input, size_t inputLength) {
  assert(!input && !inputLength);
  if (!strcmp(name, "hw.machine")) {
    assert(*length > strlen(managerProductType));
    strcpy(out, managerProductType); *length = strlen(managerProductType) + 1; return 0;
  }
  const char *nativeValue = NULL;
  if (!strcmp(name,"kern.osproductversion")) nativeValue = "15.8.8";
  if (!strcmp(name,"kern.osversion")) nativeValue = "19H440";
  if (!strcmp(name,"kern.osrelease")) nativeValue = "21.6.0";
  if (!strcmp(name,"kern.version")) nativeValue = "native-kernel-from-sysctl";
  if (nativeValue) {
    if (managerFailVersionQueries) return -1;
    assert(*length >= strlen(nativeValue)+1);
    strcpy(out,nativeValue); *length=strlen(nativeValue)+1; return 0;
  }
  if (!strcmp(name, "kern.boottime")) {
    struct timeval boot = {(time_t)(NSDate.date.timeIntervalSince1970 - 3 * 86400), 0};
    memcpy(out, &boot, sizeof boot); *length = sizeof boot; return 0;
  }
  assert(!strcmp(name, "kern.bootsessionuuid"));
  const char *value = "00112233-4455-6677-8899-AABBCCDDEEFF";
  strcpy(out, value); *length = strlen(value) + 1; return 0;
}
static int managerStat(const char *path, struct stat *value) {
  assert(!strcmp(path, "/private/var")); memset(value, 0, sizeof *value);
  value->st_birthtimespec.tv_sec = (time_t)(NSDate.date.timeIntervalSince1970 - 5 * 86400);
  return 0;
}
#define sysctlbyname managerSysctl
#define stat(path, value) managerStat(path, value)
NSDictionary *SHDWDefaultHookSettings(void) { return @{SHDWUniversalFingerprintID:@NO}; }
'''
source += without_imports(framework / "SettingsMigration.m")
source += "\n" + without_imports(framework / "Settings.m")
source += "\n" + (framework / "Fingerprint/Profile.h").read_text()
source += r'''
NSDictionary *SHDWFingerprintInputsForData(NSDictionary *data) {
  if (![data[@"MemoryDelta"] isKindOfClass:NSNumber.class]) return nil;
  return @{@"deviceType":@"iPhone", @"deviceModel":@"D17AP",
           @"displayResolution":@"1170.0x2532.0", @"displayScale":@"3.0",
           @"memorySize":[NSString stringWithFormat:@"%lld", 3824435200LL + [data[@"MemoryDelta"] longLongValue]],
           @"processorCount":@"6", @"biometryType":@"Face ID"};
}
'''
source += "\n" + without_imports(framework / "Fingerprint/Profile.m")
source += "\n" + without_imports(framework / "Fingerprint/Configuration.m")
source += "\n" + without_imports(framework / "Fingerprint/Store.m")
source += r'''
@interface FailingDefaults : NSObject
@property(nonatomic, strong) NSMutableDictionary *values;
@property(nonatomic) NSUInteger failures;
- (BOOL)synchronize;
- (id)objectForKey:(NSString *)key;
- (void)setObject:(id)value forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
@end
@implementation FailingDefaults
- (BOOL)synchronize { if (self.failures) { self.failures--; return NO; } return YES; }
- (id)objectForKey:(NSString *)key { return self.values[key]; }
- (void)setObject:(id)value forKey:(NSString *)key { self.values[key] = value; }
- (void)removeObjectForKey:(NSString *)key { [self.values removeObjectForKey:key]; }
@end
int main(int argc, const char **argv) { @autoreleasepool {
  if (argc == 2 && !strcmp(argv[1], "--migration-write")) {
    NSUserDefaults *fixture = [[NSUserDefaults alloc] initWithSuiteName:@SHADOW_PREFS_PLIST];
    [fixture setPersistentDomain:@{
      @"migration.app":@{SHDWAppEnabledID:@YES, @"Fingerprint_Managed":@YES,
                         @"Fingerprint_Enabled":@NO, @"Fingerprint_Locked":@YES,
                         @"Fingerprint_Config":@{@"Version":@1},
                         @"Fingerprint_Data":@{@"Version":@1, @"UpdatedAt":@1234},
                         @"Obsolete_Scalar":@1},
      @"pending.app":@{@"Fingerprint_Managed":@YES, @"Fingerprint_Enabled":@YES,
                       @"Fingerprint_Locked":@YES},
      @"legacy.app":@{@"Fingerprint_Data":@{@"Version":@1}}
    } forName:@SHADOW_PREFS_PLIST];
    assert([fixture synchronize]);
    return 0;
  }
  ShadowSettings *settings = ShadowSettings.sharedInstance;
  if (argc == 2 && !strcmp(argv[1], "--migration-read")) {
    NSDictionary *app = [settings.userDefaults dictionaryForKey:@"migration.app"];
    assert([app[@"Fingerprint_Managed"] boolValue]);
    assert([app[@"Fingerprint_Enabled"] isEqual:@NO]);
    assert([app[@"Fingerprint_Locked"] isEqual:@YES]);
    assert(([app[@"Fingerprint_Config"] isEqual:@{@"Version":@1}]));
    assert(([app[@"Fingerprint_Data"] isEqual:@{@"Version":@1, @"UpdatedAt":@1234}]));
    assert(!app[@"Obsolete_Scalar"]);
    NSDictionary *pending = [settings.userDefaults dictionaryForKey:@"pending.app"];
    assert([pending[@"Fingerprint_Managed"] boolValue] &&
           [pending[@"Fingerprint_Enabled"] boolValue] && [pending[@"Fingerprint_Locked"] boolValue]);
    assert(!pending[@"Fingerprint_Data"]);
    NSDictionary *legacy = [settings.userDefaults dictionaryForKey:@"legacy.app"];
    assert(!legacy[@"Fingerprint_Enabled"] && !legacy[@"Fingerprint_Locked"]);
    assert([SHDWFingerprintStore.sharedStore enabledForApplication:@"legacy.app"]);
    assert(![SHDWFingerprintStore.sharedStore lockedForApplication:@"legacy.app"]);
    [settings reset];
    puts("fingerprint manager: fresh-process migration preserves managed/enabled/locked state and saved profiles");
    return 0;
  }
  [settings.userDefaults removePersistentDomainForName:@SHADOW_PREFS_PLIST];
  [settings.userDefaults synchronize];
  NSUserDefaults *defaults = settings.userDefaults;
  SHDWFingerprintStore *store = SHDWFingerprintStore.sharedStore;
  NSError *error;
  assert(![store enabledForApplication:@"unregistered.app"]);
  assert(![store lockedForApplication:@"unregistered.app"]);
  assert(![store setEnabled:YES forApplication:@"unregistered.app" error:&error] && error.code == 4);
  assert(![store setLocked:YES forApplication:@"unregistered.app" error:&error] && error.code == 4);
  assert(![store profileForBundleIdentifier:@"unregistered.app"]);
  assert(![defaults objectForKey:@"unregistered.app"]);
  assert(![store deviceFingerprintForApplication:@"unregistered.app"]);
  assert(store.registeredBundleIdentifiers.count == 0);
  NSDictionary *emptyApp = @{SHDWAppEnabledID:@YES, @"Fingerprint_Data":@{}, @"Other":@42};
  [defaults setObject:emptyApp forKey:@"empty.app"];
  assert(![store profileForBundleIdentifier:@"empty.app"]);
  assert(![store deviceFingerprintForApplication:@"empty.app"]);
  assert([[defaults dictionaryForKey:@"empty.app"] isEqual:emptyApp]);
  assert(store.registeredBundleIdentifiers.count == 0);
  assert(![[settings getPreferencesForIdentifier:@"empty.app"][SHDWUniversalFingerprintID] boolValue]);
  NSDictionary *legacyApp = @{@"Fingerprint_Data":@{@"Version":@0}, @"Fingerprint_Managed":@YES};
  [defaults setObject:legacyApp forKey:@"invalid.legacy"];
  assert([[store profileForBundleIdentifier:@"invalid.legacy"] isEqual:legacyApp[@"Fingerprint_Data"]]);
  assert(![store deviceFingerprintForApplication:@"invalid.legacy"]);
  assert([[defaults dictionaryForKey:@"invalid.legacy"] isEqual:legacyApp]);
  [defaults removeObjectForKey:@"invalid.legacy"];
  [defaults setObject:@{SHDWAppEnabledID:@YES, @"Unrelated":@"keep"} forKey:@"enabled.only"];
  assert(![[settings getPreferencesForIdentifier:@"enabled.only"][SHDWUniversalFingerprintID] boolValue]);
  [defaults setObject:@{SHDWAppDisabledID:@YES, SHDWDetectorAggressiveID:@YES, @"Other":@42} forKey:@"b.app"];
  assert([store registerApplication:@"b.app" error:&error]);
  assert([store enabledForApplication:@"b.app"]);
  assert(![store lockedForApplication:@"b.app"]);
  assert([[defaults dictionaryForKey:@"b.app"][@"Fingerprint_Enabled"] boolValue]);
  assert(![[defaults dictionaryForKey:@"b.app"][@"Fingerprint_Locked"] boolValue]);
  assert(![store profileForBundleIdentifier:@"b.app"]);
  assert(![store deviceFingerprintForApplication:@"b.app"]);
  assert(![[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert([[defaults dictionaryForKey:@"b.app"][@"Fingerprint_Managed"] boolValue]);
  assert(![defaults dictionaryForKey:@"b.app"][@"Fingerprint_Data"]);
  assert([store refreshApplication:@"b.app" error:&error]);
  assert([store lockedForApplication:@"b.app"]);
  NSDictionary *autoLocked = [[defaults dictionaryForKey:@"b.app"] copy];
  assert(![store refreshApplication:@"b.app" error:&error] && error.code == 6);
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:autoLocked]);
  NSDictionary *first = [store profileForBundleIdentifier:@"b.app"];
  assert(first[@"VendorIdentifier"] && first[@"BootSessionUUID"]);
  assert([first[@"UpdatedAt"] isKindOfClass:NSNumber.class]);
  assert([first[@"UpdatedAt"] doubleValue] > 0 && [first[@"UpdatedAt"] doubleValue] <= NSDate.date.timeIntervalSince1970);
  assert([[store profileForBundleIdentifier:@"b.app"][@"UpdatedAt"] isEqual:first[@"UpdatedAt"]]);
  assert([defaults dictionaryForKey:@"b.app"][@"App_Disabled"] == nil);
  assert([[defaults dictionaryForKey:@"b.app"][@"Other"] isEqual:@42]);
  assert([store aggressiveForApplication:@"b.app"]);
  assert([[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert([store registerApplication:@"a.app" error:&error]);
  assert(![store profileForBundleIdentifier:@"a.app"]);
  assert([store refreshApplication:@"a.app" error:&error]);
  assert([store lockedForApplication:@"a.app"]);
  assert(([store.registeredBundleIdentifiers isEqual:@[@"a.app", @"b.app"]]));
  assert([store registerApplication:@"b.app" error:&error]);
  assert([[store profileForBundleIdentifier:@"b.app"] isEqual:first]);
  NSString *identifier = [store deviceFingerprintForApplication:@"b.app"];
  assert(identifier.length == 64 && [identifier isEqual:[store deviceFingerprintForApplication:@"b.app"]]);
  assert([settings isValidFingerprintData:first]);
  assert([identifier isEqual:[SHDWFingerprintStore deviceFingerprintForData:first]]);
  assert(![settings isValidFingerprintData:@{@"Version":@1}]);
  assert(![SHDWFingerprintStore deviceFingerprintForData:@{@"Version":@1}]);
  NSMutableDictionary *timeChanged = [first mutableCopy];
  timeChanged[@"NativeBootTimestamp"] = @100;
  timeChanged[@"BootTimeOffset"] = @500;
  timeChanged[@"BootSessionUUID"] = NSUUID.UUID.UUIDString;
  timeChanged[@"VendorIdentifier"] = NSUUID.UUID.UUIDString;
  timeChanged[@"InterfaceSeed"] = [NSMutableData dataWithLength:32];
  assert([identifier isEqual:[SHDWFingerprintProfile displayIdentifierForData:timeChanged]]);
  timeChanged[@"MemoryDelta"] = @([first[@"MemoryDelta"] longLongValue] + 16384);
  assert(![identifier isEqual:[SHDWFingerprintProfile displayIdentifierForData:timeChanged]]);
  NSDictionary *a = [store profileForBundleIdentifier:@"a.app"];
  NSDictionary *otherApp = [[defaults dictionaryForKey:@"a.app"] copy];
  NSDictionary *beforeShadowToggle = [[defaults dictionaryForKey:@"b.app"] copy];
  assert([store shadowEnabledForApplication:@"b.app"]);
  assert([store setShadowEnabled:NO forApplication:@"b.app" error:&error]);
  assert(![store shadowEnabledForApplication:@"b.app"]);
  assert(![[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  NSMutableDictionary *expectedShadowOff = [beforeShadowToggle mutableCopy];
  expectedShadowOff[SHDWAppEnabledID] = @NO;
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:expectedShadowOff]);
  assert([store setShadowEnabled:YES forApplication:@"b.app" error:&error]);
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:beforeShadowToggle]);
  assert([[defaults dictionaryForKey:@"a.app"] isEqual:otherApp]);
  NSDictionary *profileSnapshot = [first copy];
  assert([store setEnabled:NO forApplication:@"b.app" error:&error]);
  assert(![store enabledForApplication:@"b.app"]);
  assert(![[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert(![store refreshApplication:@"b.app" error:&error] && error.code == 5);
  assert(![settings refreshFingerprintDataForIdentifier:@"b.app"]);
  NSDictionary *blockedApplication = [[defaults dictionaryForKey:@"b.app"] copy];
  assert([settings fingerprintDataForIdentifier:@"b.app"]);
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:blockedApplication]);
  assert([[store profileForBundleIdentifier:@"b.app"] isEqual:first]);
  assert([[store profileForBundleIdentifier:@"b.app"][@"UpdatedAt"] isEqual:first[@"UpdatedAt"]]);
  assert([store registerApplication:@"b.app" error:&error]);
  assert(![store enabledForApplication:@"b.app"]);
  assert([store setEnabled:YES forApplication:@"b.app" error:&error]);
  assert([store enabledForApplication:@"b.app"]);
  assert([[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert([[store profileForBundleIdentifier:@"b.app"] isEqual:first]);
  assert([store setLocked:YES forApplication:@"b.app" error:&error]);
  assert([store lockedForApplication:@"b.app"]);
  assert([[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert(![store refreshApplication:@"b.app" error:&error] && error.code == 6);
  assert(![settings refreshFingerprintDataForIdentifier:@"b.app"]);
  assert([store registerApplication:@"b.app" error:&error]);
  assert([store lockedForApplication:@"b.app"]);
  assert([[store profileForBundleIdentifier:@"b.app"] isEqual:first]);
  assert([profileSnapshot isEqual:[store profileForBundleIdentifier:@"b.app"]]);
  assert([[defaults dictionaryForKey:@"a.app"] isEqual:otherApp]);
  NSDictionary *lockedBefore = [[defaults dictionaryForKey:@"b.app"] copy];
  assert([settings fingerprintDataForIdentifier:@"b.app"]);
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:lockedBefore]);
  assert([store setLocked:NO forApplication:@"b.app" error:&error]);
  assert(![store lockedForApplication:@"b.app"]);
  assert([[store profileForBundleIdentifier:@"b.app"] isEqual:first]);
  assert([store refreshApplication:@"b.app" error:&error]);
  NSDictionary *fresh = [store profileForBundleIdentifier:@"b.app"];
  assert([store lockedForApplication:@"b.app"]);
  assert(![first[@"VendorIdentifier"] isEqual:fresh[@"VendorIdentifier"]]);
  assert([fresh[@"UpdatedAt"] doubleValue] > [first[@"UpdatedAt"] doubleValue]);
  assert([[store deviceFingerprintForApplication:@"b.app"]
      isEqual:[SHDWFingerprintProfile stableFingerprintForInputs:SHDWFingerprintInputsForData(fresh)]]);
  assert([[store profileForBundleIdentifier:@"a.app"] isEqual:a]);
  assert([store setAggressive:NO forApplication:@"b.app" error:&error]);
  assert(![store aggressiveForApplication:@"b.app"]);
  NSDictionary *beforeLockedRemoval = [[defaults dictionaryForKey:@"b.app"] copy];
  assert(![store removeApplication:@"b.app" error:&error] && error.code == 6);
  assert([[defaults dictionaryForKey:@"b.app"] isEqual:beforeLockedRemoval]);
  assert([store setLocked:NO forApplication:@"b.app" error:&error]);
  assert([store removeApplication:@"b.app" error:&error]);
  assert(![store profileForBundleIdentifier:@"b.app"]);
  NSDictionary *remaining = [defaults dictionaryForKey:@"b.app"];
  assert([remaining[SHDWAppEnabledID] boolValue] && [remaining[@"Other"] isEqual:@42]);
  for (NSString *key in @[@"Fingerprint_Data", @"Fingerprint_Managed", @"Fingerprint_Enabled", @"Fingerprint_Locked"])
    assert(!remaining[key]);
  assert(![store enabledForApplication:@"b.app"] && ![store lockedForApplication:@"b.app"]);
  assert(![[settings getPreferencesForIdentifier:@"b.app"][SHDWUniversalFingerprintID] boolValue]);
  assert(([store.registeredBundleIdentifiers isEqual:@[@"a.app"]]));
  assert(![store refreshApplication:@"b.app" error:&error] && error.code == 4);
  assert([store removeApplication:@"missing.app" error:&error]);
  assert(![defaults objectForKey:@"missing.app"]);
  assert(![store registerApplication:@"bad app" error:&error] && error.code == 1);
  [defaults setObject:@{SHDWAppEnabledID:@NO, @"Fingerprint_Data":a} forKey:@"disabled.app"];
  NSDictionary *legacyBefore = [[defaults dictionaryForKey:@"disabled.app"] copy];
  assert([store enabledForApplication:@"disabled.app"] && ![store lockedForApplication:@"disabled.app"]);
  assert([[defaults dictionaryForKey:@"disabled.app"] isEqual:legacyBefore]);
  assert(![[settings getPreferencesForIdentifier:@"disabled.app"][SHDWUniversalFingerprintID] boolValue]);
  assert([store registerApplication:@"pending.app" error:&error]);
  assert([store setLocked:YES forApplication:@"pending.app" error:&error]);
  NSDictionary *pending = [[defaults dictionaryForKey:@"pending.app"] copy];
  assert(![store refreshApplication:@"pending.app" error:&error] && error.code == 6);
  assert(![settings refreshFingerprintDataForIdentifier:@"pending.app"]);
  assert(![settings fingerprintDataForIdentifier:@"pending.app"]);
  assert(![store profileForBundleIdentifier:@"pending.app"]);
  assert([[defaults dictionaryForKey:@"pending.app"] isEqual:pending]);
  assert(![store removeApplication:@"pending.app" error:&error] && error.code == 6);
  assert([store setLocked:NO forApplication:@"pending.app" error:&error]);
  assert([store removeApplication:@"pending.app" error:&error]);
  NSDictionary *corruptLocked = @{@"Fingerprint_Managed":@YES, @"Fingerprint_Locked":@YES,
                                @"Fingerprint_Data":@{@"Version":@0}};
  [defaults setObject:corruptLocked forKey:@"corrupt.locked"];
  assert(![settings fingerprintDataForIdentifier:@"corrupt.locked"]);
  assert([[defaults dictionaryForKey:@"corrupt.locked"] isEqual:corruptLocked]);
  FailingDefaults *failure = [FailingDefaults new];
  failure.values = [NSMutableDictionary new];
  [settings setValue:failure forKey:@"userDefaults"];
  // The initial synchronize consumes one failure, and the write consumes the second.
  failure.failures = 2;
  assert(![store registerApplication:@"failed.new" error:&error]);
  assert(!failure.values[@"failed.new"]);
  NSDictionary *before = @{SHDWAppEnabledID:@NO, @"Other":@42, @"Fingerprint_Data":a};
  failure.values[@"failed.existing"] = before;
  failure.failures = 2;
  assert(![store registerApplication:@"failed.existing" error:&error]);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 3;
  assert(![store refreshApplication:@"failed.existing" error:&error]);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 2;
  assert(![store removeApplication:@"failed.existing" error:&error]);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 2;
  assert(![store setEnabled:NO forApplication:@"failed.existing" error:&error] && error.code == 3);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 2;
  assert(![store setLocked:YES forApplication:@"failed.existing" error:&error] && error.code == 3);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 2;
  assert(![store setShadowEnabled:YES forApplication:@"failed.existing" error:&error] && error.code == 3);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  failure.failures = 2;
  assert(![store setConfiguration:SHDWFingerprintConfiguration.defaultConfiguration forApplication:@"failed.existing" error:&error] && error.code == 3);
  assert([failure.values[@"failed.existing"] isEqual:before]);
  [settings setValue:defaults forKey:@"userDefaults"];
  NSDictionary *resetProtected = @{@"Fingerprint_Data":a, @"Fingerprint_Managed":@YES,
      @"Fingerprint_Enabled":@NO, @"Fingerprint_Locked":@YES, @"Fingerprint_Future":@"keep", @"UnrelatedPayload":@[@1,@2]};
  NSMutableDictionary *resetConfigured=[resetProtected mutableCopy];
  resetConfigured[SHDWAppEnabledID]=@YES;resetConfigured[SHDWDetectorAggressiveID]=@YES;
  [defaults setObject:resetConfigured forKey:@"reset.protected"];
  [defaults setObject:@{SHDWAppEnabledID:@YES} forKey:@"reset.configonly"];
  [defaults setBool:YES forKey:SHDWSingleToggleMigrationID];
  [defaults setBool:YES forKey:SHDWGlobalEnabledID];
  [defaults setBool:YES forKey:SHDWDetectorAggressiveID];
  [settings reset];
  assert([[defaults dictionaryForKey:@"reset.protected"] isEqual:resetProtected]);
  assert([[defaults dictionaryForKey:@"reset.configonly"] isEqual:@{}]);
  assert(![defaults objectForKey:SHDWGlobalEnabledID] && ![defaults objectForKey:SHDWDetectorAggressiveID]);
  assert([[store profileForBundleIdentifier:@"a.app"] isEqual:a]);
  assert([store lockedForApplication:@"a.app"]);
  assert([defaults boolForKey:SHDWSingleToggleMigrationID]);
  assert([SHDWFingerprintConfiguration.defaultConfiguration[@"System"][@"Mode"] isEqual:@"profile"]);
  assert([SHDWFingerprintConfiguration.defaultConfiguration[@"System"][@"ProfileID"] isEqual:@"iphone14-5_ios18.7.1_22H31"]);
  assert(SHDWFingerprintConfiguration.systemProfilesForCurrentDevice.count == 1);
  for (NSString *product in @[@"iPhone9,2", @"iPhone9,4", @"iPhone12,1", @"iPhone13,2", @"iPhone15,2", @"unknown"]) {
    managerProductType = product.UTF8String;
    assert([SHDWFingerprintConfiguration.defaultConfiguration[@"System"][@"Mode"] isEqual:@"native"]);
    assert(SHDWFingerprintConfiguration.systemProfilesForCurrentDevice.count == 0);
  }
  managerProductType = "iPhone9,2";
  NSDictionary *configuration = SHDWFingerprintConfiguration.defaultConfiguration;
  assert([configuration[@"System"][@"Mode"] isEqual:@"native"]);
  NSDictionary *resolvedNative = [SHDWFingerprintConfiguration resolvedSystemForConfiguration:configuration];
  assert([resolvedNative[@"Version"] isEqual:@"15.8.8"]);
  assert([resolvedNative[@"Build"] isEqual:@"19H440"]);
  assert([resolvedNative[@"Darwin"] isEqual:@"21.6.0"]);
  assert([resolvedNative[@"Kernel"] isEqual:@"native-kernel-from-sysctl"]);
  managerFailVersionQueries = YES;
  NSDictionary *fallbackNative = [SHDWFingerprintConfiguration resolvedSystemForConfiguration:configuration];
  NSOperatingSystemVersion nativeHostVersion = NSProcessInfo.processInfo.operatingSystemVersion;
  NSString *nativeHostString = [NSString stringWithFormat:@"%ld.%ld.%ld", (long)nativeHostVersion.majorVersion,
     (long)nativeHostVersion.minorVersion, (long)nativeHostVersion.patchVersion];
  assert([fallbackNative[@"Version"] isEqual:nativeHostString]);
  assert(!fallbackNative[@"Build"] && !fallbackNative[@"Darwin"] && !fallbackNative[@"Kernel"]);
  managerFailVersionQueries = NO;
  managerProductType = "iPhone14,5";
  NSDictionary *resolvedProfile = [SHDWFingerprintConfiguration resolvedSystemForConfiguration:SHDWFingerprintConfiguration.defaultConfiguration];
  assert([resolvedProfile[@"Version"] isEqual:@"18.7.1"] && [resolvedProfile[@"Build"] isEqual:@"22H31"]);
  assert(resolvedProfile == [SHDWFingerprintConfiguration systemProfileForConfiguration:SHDWFingerprintConfiguration.defaultConfiguration]);
  assert([configuration[@"Receipts"][@"InterceptEnabled"] boolValue]);
  assert(([configuration[@"Network"][@"RadioTechnologies"] isEqual:@[@"4g",@"5g"]]));
  [defaults setObject:@{@"Fingerprint_Managed":@YES, @"Fingerprint_Data":a} forKey:@"config.legacy"];
  NSDictionary *legacyConfigurationBefore = [defaults dictionaryForKey:@"config.legacy"];
  assert([[store configurationForApplication:@"config.legacy"] isEqual:SHDWFingerprintConfiguration.defaultConfiguration]);
  assert([[defaults dictionaryForKey:@"config.legacy"] isEqual:legacyConfigurationBefore]);
  assert([store registerApplication:@"config.new" error:&error]);
  NSDictionary *registeredConfig = [defaults dictionaryForKey:@"config.new"][@"Fingerprint_Config"];
  assert([registeredConfig[@"UpdatedAt"] doubleValue] > 0);
  assert(![store profileForBundleIdentifier:@"config.new"]);
  NSMutableDictionary *chosen = [configuration mutableCopy];
  chosen[@"Network"] = @{@"RadioTechnologies":@[]};
  chosen[@"Receipts"] = @{@"InterceptEnabled":@NO};
  assert([store setEnabled:NO forApplication:@"config.legacy" error:&error]);
  assert([store setConfiguration:chosen forApplication:@"config.legacy" error:&error]);
  assert([[store profileForBundleIdentifier:@"config.legacy"] isEqual:a]);
  NSDictionary *savedConfig = [store configurationForApplication:@"config.legacy"];
  assert([savedConfig[@"UpdatedAt"] doubleValue] > 0);
  assert([savedConfig[@"Network"][@"RadioTechnologies"] count] == 0);
  assert(![savedConfig[@"Receipts"][@"InterceptEnabled"] boolValue]);
  assert([store setLocked:YES forApplication:@"config.legacy" error:&error]);
  NSDictionary *lockedConfigApp = [defaults dictionaryForKey:@"config.legacy"];
  assert(![store setConfiguration:configuration forApplication:@"config.legacy" error:&error] && error.code == 6);
  assert([[defaults dictionaryForKey:@"config.legacy"] isEqual:lockedConfigApp]);
  assert(![store setConfiguration:configuration forApplication:@"config.unknown" error:&error] && error.code == 4);
  assert([store setLocked:NO forApplication:@"config.legacy" error:&error]);
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.7.1_22H31"};
  assert([SHDWFingerprintConfiguration configurationByValidating:chosen error:&error]);
  assert([SHDWFingerprintConfiguration systemProfileForConfiguration:chosen]);
  managerProductType = "iPhone9,2";
  assert(SHDWFingerprintConfiguration.systemProfilesForCurrentDevice.count == 0);
  assert(![SHDWFingerprintConfiguration configurationByValidating:chosen error:&error]);
  assert([SHDWFingerprintConfiguration systemProfileForConfiguration:chosen]);
  assert([SHDWFingerprintConfiguration configurationByValidating:configuration error:&error]);
  managerProductType = "iPhone14,5";
  for (NSDictionary *invalidPart in @[
      @{@"Version":@YES}, @{@"Version":@2}, @{@"UpdatedAt":@YES}, @{@"UpdatedAt":@(-1)},
      @{@"System":@{@"Mode":@"native", @"ProfileID":@"extra"}},
      @{@"System":@{@"Mode":@"profile", @"ProfileID":@"unknown"}},
      @{@"Network":@{@"RadioTechnologies":@[@"5g",@"5g"]}},
      @{@"Network":@{@"RadioTechnologies":@[@"3g"]}},
      @{@"Network":@{@"RadioTechnologies":@"4g"}},
      @{@"Receipts":@{@"InterceptEnabled":@1}}, @{@"Region":@"FR"}]) {
    NSMutableDictionary *invalid = [configuration mutableCopy]; [invalid addEntriesFromDictionary:invalidPart];
    NSDictionary *beforeInvalid = [defaults dictionaryForKey:@"config.legacy"];
    assert(![store setConfiguration:invalid forApplication:@"config.legacy" error:&error] && error.code == 7);
    assert([[defaults dictionaryForKey:@"config.legacy"] isEqual:beforeInvalid]);
  }
  puts("fingerprint configuration: validation, hardware catalog, literal radio selections, defaults, read-only legacy, locks, data isolation and rollback passed");
  puts("fingerprint manager: default off, registration, persistence, refresh, digest stability, isolation and removal passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-manager-tests-") as tmp:
    tmp = Path(tmp)
    src, binary = tmp / "test.m", tmp / "test"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-Wno-deprecated-declarations", "-Wno-unused-variable", "-fsanitize=address,undefined",
                    "-framework", "Foundation", "-I", str(framework / "Headers"),
                    str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary), "--migration-write"], check=True)
    subprocess.run([str(binary), "--migration-read"], check=True)
    subprocess.run([str(binary)], check=True)
