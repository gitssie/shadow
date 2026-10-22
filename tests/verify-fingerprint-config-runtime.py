"""Exercise production config policy and startup snapshot bodies with explicit fixtures."""
from pathlib import Path
import subprocess
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
- (NSDictionary *)fingerprintDataForIdentifier:(NSString *)identifier;
@end
@implementation SettingsDouble
+ (instancetype)sharedInstance { static id settings; if (!settings) settings = [self new]; return settings; }
- (NSDictionary *)fingerprintDataForIdentifier:(NSString *)identifier { (void)identifier; return fixtureData; }
@end
'''
storage = "\n".join(line for line in (policy / "FingerprintStorage.m").read_text().splitlines()
                    if not line.startswith("#import"))
storage = storage.replace("SHDWFingerprintConfig(", "PinnedConfiguration(").replace("SHDWFingerprintData(", "PinnedData(").replace("SHDWFingerprintSystem(", "PinnedSystem(")
storage = storage.replace("SHDWFingerprintStore", "ConfigurationStoreDouble").replace("ShadowSettings", "SettingsDouble")
source += "\n" + storage
hostname_source = (root / "src/ShadowCore.dylib/hooks/Universal/libc_antidebugging.x").read_text()
source += "\n" + hostname_source[hostname_source.index("int (*original_gethostname)"):hostname_source.index("int replaced_uname(")]
source += r'''
int main(void) { @autoreleasepool {
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
  chosen[@"System"] = @{@"Mode":@"profile", @"ProfileID":@"iphone14-5_ios18.7.1_22H31"};
  fixture = [chosen copy];
  assert([SHDWFingerprintOSVersionString() isEqual:@"18.7.1"]);
  assert(!strcmp(SHDWFingerprintVersionValue("kern.osversion"), "22H31"));
  assert([SHDWFingerprintUserAgent(ua) containsString:@"OS 18_7_1 like Mac OS X"]);
  assert(SHDWFingerprintUnameValue(&value));
  assert(!strcmp(value.release, "24.6.0") && strstr(value.version, "T8110"));
  assert(!strcmp(value.nodename, "iPhone"));
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
