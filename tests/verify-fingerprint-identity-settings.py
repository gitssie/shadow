"""Run persisted IDFV and extension-owner settings against host Foundation."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
settings = (root / "src/Shadow.framework/Settings.m").read_text()

def function(signature):
    start = settings.index(signature)
    end = settings.index("{", start) + 1
    depth = 1
    while depth:
        depth += (settings[end] == "{") - (settings[end] == "}")
        end += 1
    return settings[start:end]

helpers = "\n".join(function(signature) for signature in [
    "static BOOL SHDWValidFingerprintData(",
    "static NSUUID *SHDWStoredVendorIdentifier(",
    "static NSDictionary *SHDWStoredFingerprintApplication(",
    "static NSDictionary *SHDWFingerprintRuntimeSnapshot(",
])
helpers += "\n" + (root / "src/Shadow.framework/Headers/Shadow/FingerprintOwner.h").read_text()
loader = (root / "src/Shadow.dylib/dylib.x").read_text()
assert "#import <Shadow/FingerprintOwner.h>" in loader
assert "#import <Shadow/FingerprintOwner.h>" in settings
bootstrap = loader[loader.index("    NSString* preferenceIdentifier ="):loader.index("    // Load the payload")]
bootstrap = bootstrap.replace("[NSBundle mainBundle]", "testBundle")
bootstrap = bootstrap.replace('NSUserDefaults* defaults = [[NSUserDefaults alloc] initWithSuiteName:@SHADOW_PREFS_PLIST];', 'ReadDefaults* defaults = supplied;')
bootstrap = bootstrap.replace("return;", "return NO;")
methods = "\n".join(function(signature) for signature in [
    "- (NSString *)fingerprintOwnerIdentifierForIdentifier:",
    "- (NSUUID *)storedFingerprintVendorIdentifierForIdentifier:",
    "- (NSDictionary *)runtimeFingerprintDataForIdentifier:",
    "- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)bundleIdentifier\n                                   vendorIdentifier:",
    "- (NSDictionary<NSString *, id> *)getPreferencesForIdentifier:",
]).replace("[NSBundle mainBundle]", "testBundle")
constants = set(re.findall(r"\bSHDW[A-Za-z]+ID\b", methods))
source = r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintState.h>
#include <assert.h>
#include <math.h>
static const NSInteger kSHDWBootOffsetLimit = 86400;
static NSString *const kSHDWDetectorRunnerOverridesKey = @"Test_DetectorOverrides";
static NSBundle *testBundle;
static NSString *fallbackPath;
#define SHADOW_PREFS_PLIST "/tmp/shadow-identity-unused.plist"
#define JBPath(path) fallbackPath
static double boot = 1700000000;
static BOOL bootAvailable = YES;
static double SHDWNativeBootTimestamp(void) { return boot; }
static NSString *SHDWNativeBootSessionUUID(void) { return bootAvailable ? @"00112233-4455-6677-8899-AABBCCDDEEFF" : nil; }
static BOOL SHDWFingerprintBootOffsetBounds(double native, double now, NSInteger *lo, NSInteger *hi) {
    assert(native == boot && now > native);
    *lo = -50; *hi = 50; return bootAvailable;
}
static NSDictionary *SHDWMigratedHookSettings(NSDictionary *value) { return value; }
static BOOL SHDWApplicationEnabled(NSDictionary *app, BOOL global, BOOL migration, BOOL harness) {
    (void)migration; (void)harness;
    return app[@"App_Enabled"] ? [app[@"App_Enabled"] boolValue] : global;
}
static BOOL SHDWDetectorAggressiveEnabled(NSDictionary *app, BOOL global) {
    return app[@"Detector_Aggressive"] ? [app[@"Detector_Aggressive"] boolValue] : global;
}
@interface ReadDefaults : NSObject
@property(nonatomic, strong) NSMutableDictionary *values;
- (id)objectForKey:(NSString *)key;
- (BOOL)boolForKey:(NSString *)key;
- (NSInteger)integerForKey:(NSString *)key;
@end
@implementation ReadDefaults
- (id)objectForKey:(NSString *)key { return self.values[key]; }
- (BOOL)boolForKey:(NSString *)key { return [self.values[key] boolValue]; }
- (NSInteger)integerForKey:(NSString *)key { return [self.values[key] integerValue]; }
@end
@interface ShadowSettings : NSObject {
    ReadDefaults *userDefaults;
    NSDictionary *defaultSettings;
}
@property(nonatomic, strong) ReadDefaults *userDefaults;
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier;
- (NSUUID *)storedFingerprintVendorIdentifierForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendorIdentifier;
- (NSDictionary *)getPreferencesForIdentifier:(NSString *)identifier;
@end
'''
source += "\n".join(f'#define {key} @"{key}"' for key in sorted(constants))
source = source.replace('#define SHDWAppEnabledID @"SHDWAppEnabledID"', '#define SHDWAppEnabledID @"App_Enabled"')
source += "\n" + helpers.replace("NSUserDefaults *defaults", "ReadDefaults *defaults")
source += "\nstatic BOOL LoaderAllows(NSString *bundleIdentifier, ReadDefaults *supplied, BOOL isDetectorRunner) {\n" + bootstrap + "return YES;\n}\n"
source += "\n@implementation ShadowSettings\n@synthesize userDefaults;\n- (instancetype)init { if ((self = [super init])) defaultSettings = @{}; return self; }\n" + methods + "\n@end\n"
source += r'''
static NSBundle *MakeBundle(NSString *path, NSString *identifier, BOOL extension) {
    assert([[NSFileManager defaultManager] createDirectoryAtPath:path withIntermediateDirectories:YES attributes:nil error:NULL]);
    NSMutableDictionary *info = [@{@"CFBundleIdentifier":identifier, @"CFBundlePackageType":@"APPL"} mutableCopy];
    if(extension) info[@"NSExtension"] = @{@"NSExtensionPointIdentifier":@"com.apple.widgetkit-extension"};
    assert([info writeToFile:[path stringByAppendingPathComponent:@"Info.plist"] atomically:YES]);
    NSBundle *bundle = [NSBundle bundleWithPath:path];
    assert([bundle.bundleIdentifier isEqual:identifier]); return bundle;
}
int main(int argc, const char **argv) { @autoreleasepool {
    assert(argc == 2); NSString *tmp = @(argv[1]);
    NSString *appPath = [tmp stringByAppendingPathComponent:@"Host.app"];
    NSBundle *host = MakeBundle(appPath, @"owner.app", NO);
    NSBundle *extension = MakeBundle([appPath stringByAppendingPathComponent:@"PlugIns/Widget.appex"], @"arbitrary.extension", YES);
    assert([SHDWFingerprintOwnerForBundle(@"arbitrary.extension", extension) isEqual:@"owner.app"]);
    assert([SHDWFingerprintOwnerForBundle(@"other.query", extension) isEqual:@"other.query"]);
    assert([SHDWFingerprintOwnerForBundle(@"owner.app", host) isEqual:@"owner.app"]);
    NSBundle *loose = MakeBundle([tmp stringByAppendingPathComponent:@"Loose.appex"], @"loose.extension", YES);
    assert([SHDWFingerprintOwnerForBundle(@"loose.extension", loose) isEqual:@"loose.extension"]);
    NSBundle *wrong = MakeBundle([appPath stringByAppendingPathComponent:@"Frameworks/Wrong.appex"], @"wrong.extension", YES);
    assert([SHDWFingerprintOwnerForBundle(@"wrong.extension", wrong) isEqual:@"wrong.extension"]);
    NSBundle *notExtension = MakeBundle([appPath stringByAppendingPathComponent:@"PlugIns/Other.appex"], @"other.extension", NO);
    assert([SHDWFingerprintOwnerForBundle(@"other.extension", notExtension) isEqual:@"other.extension"]);
    testBundle = extension;
    fallbackPath = [tmp stringByAppendingPathComponent:@"fallback.plist"];
    ShadowSettings *settings = [ShadowSettings new]; ReadDefaults *defaults = [ReadDefaults new];
    defaults.values = [NSMutableDictionary new]; settings.userDefaults = defaults;
    NSString *uuid = @"12345678-ABCD-1234-ABCD-123456789ABC";
    NSDictionary *profile = @{@"VendorIdentifier":uuid, @"Version":@1, @"MemoryDelta":@16384,
        @"InterfaceSeed":[NSMutableData dataWithLength:32], @"BootTimeOffset":@100,
        @"NativeBootTimestamp":@1600000000, @"BootSessionUUID":uuid, @"NativeBootSessionUUID":uuid};
    NSDictionary *app = @{@"App_Enabled":@YES, @"Fingerprint_Data":profile};
    defaults.values[@"owner.app"] = app;
    NSDictionary *before = [defaults.values copy];
    assert([[settings storedFingerprintVendorIdentifierForIdentifier:@"arbitrary.extension"].UUIDString isEqual:uuid]);
    NSDictionary *runtime = [settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"];
    assert([runtime[@"VendorIdentifier"] isEqual:uuid]);
    assert([runtime[@"BootTimeOffset"] integerValue] == 50 && [runtime[@"NativeBootTimestamp"] doubleValue] == boot);
    assert([runtime[@"BootSessionUUID"] isEqual:profile[@"BootSessionUUID"]]);
    NSUUID *pairedIdentifier;
    NSDictionary *paired = [settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension" vendorIdentifier:&pairedIdentifier];
    assert([paired isEqual:runtime] && [pairedIdentifier.UUIDString isEqual:uuid]);
    bootAvailable = NO;
    assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"][@"BootTimeOffset"]);
    assert([defaults.values isEqual:before]); bootAvailable = YES;
    assert(![settings storedFingerprintVendorIdentifierForIdentifier:@"other.query"]);
    assert(LoaderAllows(@"arbitrary.extension", defaults, NO));
    assert(!LoaderAllows(@"other.query", defaults, NO));
    NSDictionary *prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
    assert([prefs[SHDWAppEnabledID] boolValue] && [prefs[SHDWUniversalFingerprintID] boolValue]);
    defaults.values[@"owner.app"] = @{@"App_Enabled":@NO, @"Fingerprint_Data":profile};
    prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
    assert(![prefs[SHDWAppEnabledID] boolValue] && ![prefs[SHDWUniversalFingerprintID] boolValue]);
    assert(!LoaderAllows(@"arbitrary.extension", defaults, NO));
    defaults.values[@"owner.app"] = @{@"App_Enabled":@YES, @"Fingerprint_Enabled":@NO, @"Fingerprint_Data":profile};
    prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
    assert([prefs[SHDWAppEnabledID] boolValue] && ![prefs[SHDWUniversalFingerprintID] boolValue]);
    for(id bad in @[@{}, @{@"VendorIdentifier":@1}, @{@"VendorIdentifier":@"bad"}]) {
        defaults.values[@"owner.app"] = @{@"Fingerprint_Data":bad};
        before = [defaults.values copy];
        assert(![settings storedFingerprintVendorIdentifierForIdentifier:@"arbitrary.extension"]);
        assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"]);
        pairedIdentifier = [NSUUID UUID];
        assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension" vendorIdentifier:&pairedIdentifier]);
        assert(!pairedIdentifier);
        assert([defaults.values isEqual:before]);
    }
    defaults.values[@"owner.app"] = @{@"Fingerprint_Data":@{@"VendorIdentifier":uuid}};
    assert([settings storedFingerprintVendorIdentifierForIdentifier:@"arbitrary.extension"]);
    assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"]);
    before = [defaults.values copy];
    assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension" vendorIdentifier:&pairedIdentifier]);
    assert([pairedIdentifier.UUIDString isEqual:uuid] && [defaults.values isEqual:before]);
    NSMutableDictionary *otherProfile = [profile mutableCopy];
    otherProfile[@"VendorIdentifier"] = @"AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE";
    assert(([@{@"owner.app":@{@"Fingerprint_Data":otherProfile}} writeToFile:fallbackPath atomically:YES]));
    pairedIdentifier = nil;
    assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension" vendorIdentifier:&pairedIdentifier]);
    assert([pairedIdentifier.UUIDString isEqual:uuid] && [defaults.values isEqual:before]);
    assert([[NSFileManager defaultManager] removeItemAtPath:fallbackPath error:NULL]);
    for(id registration in @[@{}, @{@"Fingerprint_Data":@{}}, @{@"Fingerprint_Data":@"bad"}]) {
        NSMutableDictionary *managed = [registration mutableCopy];
        managed[@"App_Enabled"] = @YES; managed[@"Fingerprint_Managed"] = @YES;
        defaults.values[@"owner.app"] = managed;
        prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
        assert([prefs[SHDWUniversalFingerprintID] boolValue]);
        assert(![settings storedFingerprintVendorIdentifierForIdentifier:@"arbitrary.extension"]);
        assert(![settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"]);
        managed[@"Fingerprint_Enabled"] = @NO;
        prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
        assert(![prefs[SHDWUniversalFingerprintID] boolValue]);
    }
    defaults.values[@"owner.app"] = @{@"App_Enabled":@YES};
    prefs = [settings getPreferencesForIdentifier:@"arbitrary.extension"];
    assert(![prefs[SHDWUniversalFingerprintID] boolValue]);
    [defaults.values removeAllObjects];
    assert(([@{@"owner.app":app} writeToFile:fallbackPath atomically:YES]));
    assert([[settings storedFingerprintVendorIdentifierForIdentifier:@"arbitrary.extension"].UUIDString isEqual:uuid]);
    assert([settings runtimeFingerprintDataForIdentifier:@"arbitrary.extension"]);
    assert(defaults.values.count == 0);
    puts("fingerprint identity settings: owner scope, read-only storage, boot snapshot and activation passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-identity-settings-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation", "-I",
        str(root / "src/Shadow.framework/Headers"), str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary), tmp], check=True)
