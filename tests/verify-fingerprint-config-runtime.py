"""Exercise production config policy and startup snapshot bodies with explicit fixtures."""
from pathlib import Path
import subprocess
import re
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
framework = root / "src/Shadow.framework"
policy = root / "src/ShadowCore.dylib/policy"
source = r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintConfiguration.h>
@interface SHDWFingerprintConfiguration (TestProfiles)
+ (NSArray<NSDictionary *> *)allSystemProfiles;
@end
#import "FingerprintPolicy.h"
#include <assert.h>
#include <string.h>
#include <sys/utsname.h>
#include <errno.h>
static BOOL mappedHostname;
static unsigned nativeHostnameCalls;
static BOOL shdw_fingerprint_app_caller(const void *caller) { (void)caller; errno=EINTR; return mappedHostname; }
static int nativeHostname(char *name, size_t length) {
  nativeHostnameCalls++;
  if (length < sizeof("real-device-with-long-hostname")) { errno=ENAMETOOLONG; return -1; }
  memcpy(name,"real-device-with-long-hostname",sizeof("real-device-with-long-hostname")); return 0;
}
static NSDictionary *fixture;
static NSDictionary *fixtureData;
NSDictionary *SHDWFingerprintConfig(NSString *bundleID) { (void)bundleID; return fixture; }
NSDictionary *SHDWFingerprintData(NSString *bundleID) { (void)bundleID; return fixtureData; }
NSDictionary *SHDWFingerprintSystem(NSString *bundleID) { (void)bundleID; return [SHDWFingerprintConfiguration resolvedSystemForConfiguration:fixture]; }
@interface ConfigurationStoreDouble : NSObject
+ (instancetype)sharedStore;
- (NSDictionary *)configurationForApplication:(NSString *)identifier;
@end
@implementation ConfigurationStoreDouble
+ (instancetype)sharedStore { static id store; if (!store) store = [self new]; return store; }
- (NSDictionary *)configurationForApplication:(NSString *)identifier { (void)identifier; return fixture; }
@end
@interface SettingsDouble : NSObject
+ (instancetype)sharedInstance;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendor;
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier;
- (NSUUID *)storedFingerprintVendorIdentifierForIdentifier:(NSString *)identifier;
@end
@implementation SettingsDouble
+ (instancetype)sharedInstance { static id settings; if (!settings) settings = [self new]; return settings; }
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier { (void)identifier; return fixtureData; }
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendor { *vendor=nil; return [self runtimeFingerprintDataForIdentifier:identifier]; }
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier { return identifier; }
- (NSUUID *)storedFingerprintVendorIdentifierForIdentifier:(NSString *)identifier { (void)identifier; return nil; }
@end
'''
storage = "\n".join(line for line in (policy / "FingerprintStorage.m").read_text().splitlines()
                    if not line.startswith("#import"))
storage = storage.replace("SHDWFingerprintConfig(", "PinnedConfiguration(").replace("SHDWFingerprintData(", "PinnedData(").replace("SHDWFingerprintSystem(", "PinnedSystem(")
storage = re.sub(r"\bSHDWFingerprintStore\b", "ConfigurationStoreDouble", storage).replace("ShadowSettings", "SettingsDouble")
source += "\n" + storage
hostname_source = (root / "src/ShadowCore.dylib/hooks/Universal/libc_antidebugging.x").read_text()
source += "\n" + hostname_source[hostname_source.index("int (*original_gethostname)"):hostname_source.index("int replaced_uname(")]
source += r'''
int main(void) { @autoreleasepool {
  NSDictionary *transportAuto = @{@"Network":@{@"Transport":@"auto"}};
  NSDictionary *transportLegacy = @{@"Network":@{@"Transport":@"safari184_ios"}};
  for (NSDictionary *off in @[@{}, @{@"Network":@{}}, @{@"Network":@{@"Transport":@"native"}}, SHDWFingerprintConfiguration.defaultConfiguration]) {
    assert(![SHDWFingerprintConfiguration usesCurlTransportForConfiguration:off]);
    assert(![SHDWFingerprintConfiguration curlTransportProfileForConfiguration:off systemVersion:@"18.7"]);
  }
  for (NSDictionary *enabled in @[transportAuto, transportLegacy]) {
    assert([SHDWFingerprintConfiguration usesCurlTransportForConfiguration:enabled]);
    for (NSArray *pair in @[@[@"16.0.3",@"safari172_ios"], @[@"16.7.2",@"safari172_ios"],
        @[@"17.7.2",@"safari172_ios"], @[@"18.0",@"safari180_ios"], @[@"18.0.1",@"safari180_ios"],
        @[@"18.3",@"safari180_ios"], @[@"18.3.9",@"safari180_ios"], @[@"18.4",@"safari184_ios"],
        @[@"18.4.0",@"safari184_ios"], @[@"18.10",@"safari184_ios"], @[@"18.7.8",@"safari184_ios"], @[@"19.0",@"safari184_ios"]])
      assert([[SHDWFingerprintConfiguration curlTransportProfileForConfiguration:enabled systemVersion:pair[0]] isEqual:pair[1]]);
    for (id invalid in @[@"",@"18",@"18.",@".18",@"18..4",@"18.4.0.1",@"18.4beta",@" 18.4",@"18.4\n",@"１８.４",@"18.-4",@18,NSNull.null])
      assert(![SHDWFingerprintConfiguration curlTransportProfileForConfiguration:enabled systemVersion:invalid]);
    assert(![SHDWFingerprintConfiguration curlTransportProfileForConfiguration:enabled systemVersion:nil]);
  }
  original_gethostname = nativeHostname;
  mappedHostname = YES; char hostname[128] = {0}; errno=EBUSY;
  assert(replaced_gethostname(hostname, 7) == 0);
  assert(!strcmp(hostname,"iPhone") && errno == EBUSY && nativeHostnameCalls == 0);
  memset(hostname,0x55,sizeof(hostname)); errno=0;
  assert(replaced_gethostname(hostname,6) == -1 && errno == ENAMETOOLONG && hostname[0] == 0x55);
  assert(replaced_gethostname(NULL,7) == -1 && errno == EFAULT && nativeHostnameCalls == 0);
  mappedHostname = NO; errno=EBUSY;
  assert(replaced_gethostname(hostname,sizeof(hostname)) == 0);
  assert(!strcmp(hostname,"real-device-with-long-hostname") && errno == EBUSY && nativeHostnameCalls == 1);
  assert(replaced_gethostname(hostname,7) == -1 && errno == ENAMETOOLONG && nativeHostnameCalls == 2);
  for (NSDictionary *profile in SHDWFingerprintConfiguration.allSystemProfiles) {
    NSString *version=profile[@"Version"];
    BOOL is187=[version isEqual:@"18.7"] || [version hasPrefix:@"18.7."];
    NSString *expectedNetwork = is187 ? @"3826.600.41" : @{@"18.4":@"3826.500.111.2.2", @"17.7.2":@"1498.700.2", @"17.6.1":@"1498.700.2", @"17.5.1":@"1496.0.7", @"17.4.1":@"1494.0.7", @"17.3.1":@"1492.0.1", @"17.2.1":@"1490.0.4", @"17.1.2":@"1485", @"17.0.3":@"1474", @"16.7.2":@"1410.0.3", @"16.6.1":@"1410.0.3", @"16.5.1":@"1408.0.4", @"16.4.1":@"1406.0.4", @"16.3.1":@"1404.0.5", @"16.2":@"1402.0.8", @"16.1.2":@"1399", @"16.0.3":@"1390"}[version];
    assert(expectedNetwork ? [profile[@"CFNetwork"] isEqual:expectedNetwork] : !profile[@"CFNetwork"]);
  }
  fixture = SHDWFingerprintConfiguration.defaultConfiguration;
  NSDictionary *nativeSystem = [SHDWFingerprintConfiguration resolvedSystemForConfiguration:fixture];
  assert([SHDWFingerprintOSVersionString() isEqual:nativeSystem[@"Version"]]);
  for (NSArray *pair in @[@[@"Build",@"kern.osversion"],@[@"Darwin",@"kern.osrelease"],@[@"Kernel",@"kern.version"]]) {
    const char *resolved = SHDWFingerprintVersionValue([pair[1] UTF8String]);
    if (nativeSystem[pair[0]]) assert(resolved && !strcmp(resolved,[nativeSystem[pair[0]] UTF8String]));
    else assert(!resolved);
  }
  NSOperatingSystemVersion native = NSProcessInfo.processInfo.operatingSystemVersion;
  NSOperatingSystemVersion version = SHDWFingerprintOSVersion();
  assert(version.majorVersion == native.majorVersion && version.minorVersion == native.minorVersion && version.patchVersion == native.patchVersion);
  NSString *ua = @"Mozilla/5.0 (iPhone; CPU iPhone OS 15_8_8 like Mac OS X) AppleWebKit/605.1.15";
  NSString *nativeUA = [NSString stringWithFormat:@"OS %@ like Mac OS X",[nativeSystem[@"Version"] stringByReplacingOccurrencesOfString:@"." withString:@"_"]];
  assert([SHDWFingerprintUserAgent(ua) containsString:nativeUA]);
  assert(SHDWFingerprintInterceptsReceipts());
  assert(!strcmp(SHDWFingerprintVersionValue("kern.hostname"), "iPhone"));
  struct utsname value; memset(&value, 0, sizeof(value));
  strcpy(value.release, "native-release"); strcpy(value.version, "native-kernel"); strcpy(value.machine, "iPhone9,2");
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, nativeSystem[@"Darwin"] ? [nativeSystem[@"Darwin"] UTF8String] : "native-release"));
  assert(!strcmp(value.version, nativeSystem[@"Kernel"] ? [nativeSystem[@"Kernel"] UTF8String] : "native-kernel"));
  assert(!strcmp(value.nodename, "iPhone") && !strcmp(value.machine, "iPhone9,2"));
  NSMutableDictionary *chosen = [fixture mutableCopy];
  for (NSString *transport in @[@"native", @"auto", @"safari184_ios"]) {
    chosen[@"Network"] = @{@"RadioTechnologies":@[@"5g"], @"Transport":transport};
    NSDictionary *normalized = [SHDWFingerprintConfiguration configurationByValidating:chosen error:nil];
    assert([normalized[@"Network"][@"Transport"] isEqual:transport]);
  }
  for (id invalidTransport in @[@"safari172_ios", @"safari180_ios", @"AUTO", @YES, @{}, NSNull.null]) {
    chosen[@"Network"] = @{@"RadioTechnologies":@[@"5g"], @"Transport":invalidTransport};
    assert(![SHDWFingerprintConfiguration configurationByValidating:chosen error:nil]);
  }
  chosen[@"Network"] = @{@"RadioTechnologies":@[@"4g",@"5g"],@"Transport":@"safari184_ios"};
  assert([SHDWFingerprintConfiguration configurationByValidating:chosen error:NULL]);
  chosen[@"Network"] = @{@"RadioTechnologies":@[],@"Transport":@"safari184"};
  assert(![SHDWFingerprintConfiguration configurationByValidating:chosen error:NULL]);
  chosen[@"Network"] = @{@"RadioTechnologies":@[@"4g",@"5g"]};
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.7.1_22H31"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"18.7.1"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"3826.600.41"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "22H31"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 18_7_1 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "24.6.0") && strstr(value.version, "T8110"));
  assert(!strcmp(value.nodename, "iPhone"));
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.7.2_22H124"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"18.7.2"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"3826.600.41"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "22H124"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 18_7_2 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "24.6.0"));
  assert(strstr(value.version, "xnu-11417.140.69.702.20~1/RELEASE_ARM64_T8110"));
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.4_22E240"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"18.4"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"3826.500.111.2.2"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "22E240"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 18_4 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "24.4.0"));
  assert(strstr(value.version, "xnu-11417.102.9~20/RELEASE_ARM64_T8110"));
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios16.7.2_20H115"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"16.7.2"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"1410.0.3"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "20H115"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 16_7_2 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "22.6.0"));
  assert(strstr(value.version, "xnu-8796.142.1.701.11~1/RELEASE_ARM64_T8110"));
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios16.3.1_20D67"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"16.3.1"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"1404.0.5"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "20D67"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 16_3_1 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "22.3.0"));
  assert(strstr(value.version, "xnu-8792.82.2~1/RELEASE_ARM64_T8110"));
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.7.8_22H352"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"18.7.8"]);
  assert([SHDWFingerprintCFNetworkVersion() isEqual:@"3826.600.41"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "22H352"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 18_7_8 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(strstr(value.version, "xnu-11417.140.69.706.9~1/RELEASE_ARM64_T8110"));
  NSArray *latestSystemCases = @[      @[@"17.7.2", @"21H221", @"1498.700.2", @"23.6.0"],
      @[@"17.6.1", @"21G101", @"1498.700.2", @"23.6.0"],
      @[@"17.5.1", @"21F90", @"1496.0.7", @"23.5.0"],
      @[@"17.4.1", @"21E236", @"1494.0.7", @"23.4.0"],
      @[@"17.3.1", @"21D61", @"1492.0.1", @"23.3.0"],
      @[@"17.2.1", @"21C66", @"1490.0.4", @"23.2.0"],
      @[@"17.1.2", @"21B101", @"1485", @"23.1.0"],
      @[@"17.0.3", @"21A360", @"1474", @"23.0.0"],
      @[@"16.7.2", @"20H115", @"1410.0.3", @"22.6.0"],
      @[@"16.6.1", @"20G81", @"1410.0.3", @"22.6.0"],
      @[@"16.5.1", @"20F75", @"1408.0.4", @"22.5.0"],
      @[@"16.4.1", @"20E252", @"1406.0.4", @"22.4.0"],
      @[@"16.3.1", @"20D67", @"1404.0.5", @"22.3.0"],
      @[@"16.2", @"20C65", @"1402.0.8", @"22.2.0"],
      @[@"16.1.2", @"20B110", @"1399", @"22.1.0"],
      @[@"16.0.3", @"20A392", @"1390", @"22.0.0"]];
  for (NSArray *system in latestSystemCases) {
    NSString *identifier = [NSString stringWithFormat:@"iphone14-5_ios%@_%@", system[0], system[1]];
    chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":identifier};
    fixture = [chosen copy];
    assert([SHDWFingerprintOSVersionString() isEqual:system[0]]);
    assert([SHDWFingerprintCFNetworkVersion() isEqual:system[2]]);
    assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), [system[1] UTF8String]));
    assert(!strcmp(SHDWFingerprintVersionValue("kern.osrelease"), [system[3] UTF8String]));
    NSString *expectedUA = [NSString stringWithFormat:@"OS %@ like Mac OS X", [system[0] stringByReplacingOccurrencesOfString:@"." withString:@"_"]];
    assert([SHDWFingerprintUserAgent(ua) containsString:expectedUA]);
    NSArray *parts = [system[0] componentsSeparatedByString:@"."];
    NSOperatingSystemVersion parsed = SHDWFingerprintOSVersion();
    assert(parsed.majorVersion == [parts[0] integerValue] && parsed.minorVersion == [parts[1] integerValue]);
    assert(parsed.patchVersion == (parts.count > 2 ? [parts[2] integerValue] : 0));
    assert(SHDWFingerprintUnameValue(&value));
    assert(!strcmp(value.release, [system[3] UTF8String]) && strstr(value.version, "/RELEASE_ARM64_T8110"));
  }
  for (NSArray *radios in @[@[], @[@"4g"], @[@"5g"], @[@"4g",@"5g"]]) {
    chosen[@"Network"] = @{@"RadioTechnologies":radios}; fixture = [chosen copy];
    NSDictionary *result = SHDWFingerprintRadioTechnologies(@{@"real-service":@"CTRadioAccessTechnologyGPRS"});
    assert(result.count == radios.count);
    assert((result[@"0000000100000001"] != nil) == [radios containsObject:@"4g"]);
    assert((result[@"0000000100000002"] != nil) == [radios containsObject:@"5g"]);
    assert([SHDWFingerprintSIMState()[@"newRadioCoverage"] boolValue] == [radios containsObject:@"5g"]);
    assert([SHDWFingerprintSIMState()[@"attached"] boolValue]);
  }
  chosen[@"Receipts"] = @{@"InterceptEnabled":@NO}; fixture = [chosen copy];
  assert(!SHDWFingerprintInterceptsReceipts());
  NSArray *countries = @[@"FR",@"GB",@"US",@"CN",@""];
  const double latitude[] = {46.227638,55.378051,37.09024,37.09024,37.09024};
  const double longitude[] = {2.213749,-3.435973,-95.712891,-95.712891,-95.712891};
  for (NSUInteger i=0; i<countries.count; i++) {
    SHDWFingerprintCoordinate center = SHDWFingerprintCountryCenterForCode(countries[i]);
    assert(center.latitude == latitude[i] && center.longitude == longitude[i]);
  }
  SHDWFingerprintCoordinate fallback = SHDWFingerprintCountryCenterForCode(nil);
  assert(fallback.latitude == latitude[2] && fallback.longitude == longitude[2]);
  fixtureData = @{@"VendorIdentifier":@"00112233-4455-6677-8899-AABBCCDDEEFF"};
  NSDictionary *pinnedConfig = PinnedConfiguration(@"one.app"), *pinnedData = PinnedData(@"one.app");
  NSDictionary *pinnedSystem = PinnedSystem(@"one.app");
  fixture = SHDWFingerprintConfiguration.defaultConfiguration; fixtureData = @{@"changed":@YES};
  assert([PinnedConfiguration(@"one.app") isEqual:pinnedConfig]);
  assert([PinnedData(@"one.app") isEqual:pinnedData]);
  assert([PinnedSystem(@"one.app") isEqual:pinnedSystem]);
  assert([PinnedConfiguration(@"two.app") isEqual:fixture]);
  assert([PinnedData(@"two.app") isEqual:fixtureData]);
  fixtureData = nil;
  assert(PinnedData(@"failed.app").count == 0);
  fixtureData = @{@"late":@YES};
  assert(PinnedData(@"failed.app").count == 0);
  puts("fingerprint config runtime: native/profile, UA/kernel/hostname, receipt, radio selections, country fallback and startup snapshots passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-config-runtime-") as temporary:
    temporary = Path(temporary)
    test, binary = temporary / "test.m", temporary / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation",
                    "-I", str(framework / "Headers"), "-I", str(policy),
                    str(framework / "Fingerprint/Configuration.m"), str(policy / "FingerprintPolicy.m"),
                    str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
