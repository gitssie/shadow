"""Run production persisted-data generation, refresh and process snapshot bodies."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
settings = (root / "src/Shadow.framework/Settings.m").read_text()


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


helpers = "static const NSInteger kSHDWBootOffsetLimit = 24 * 60 * 60;\n"
if "static double SHDWNativeBootTimestamp(" in settings:
    helpers += function(settings, "static double SHDWNativeBootTimestamp(") + "\n"
helpers += function(settings, "static NSString *SHDWNativeBootSessionUUID(") + "\n"
helpers += function(settings, "static BOOL SHDWFingerprintBootOffsetBounds(") + "\n"
helpers += function(settings, "static BOOL SHDWValidFingerprintData(") + "\n"
helpers += function(settings, "static NSDictionary *SHDWRepairedFingerprintVendorData(") + "\n"
helpers += function(settings, "static NSDictionary *SHDWNewFingerprintData(")
for signature in ["static NSUUID *SHDWStoredVendorIdentifier(",
                  "static NSDictionary *SHDWStoredFingerprintApplication(",
                  "static NSDictionary *SHDWFingerprintRuntimeSnapshot("]:
    helpers += "\n" + function(settings, signature).replace("NSUserDefaults *defaults", "FileDefaults *defaults")
methods = function(settings, "- (NSDictionary *)fingerprintDataForIdentifier:") + "\n"
methods += function(settings, "- (BOOL)refreshFingerprintDataForIdentifier:")
methods += function(settings, "- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)bundleIdentifier\n                            lockOnSuccess:")
methods += "\n" + function(settings, "- (NSString *)fingerprintOwnerIdentifierForIdentifier:")
methods += "\n" + function(settings, "- (NSDictionary *)runtimeFingerprintDataForIdentifier:")
methods += "\n" + function(settings, "- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)bundleIdentifier\n                                   vendorIdentifier:")
customized = function((root / "src/ShadowSettings.bundle/SHDWPrefs.m").read_text(), "BOOL SHDWAppIsCustomized(")
source = r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintState.h>
#import <Shadow/FingerprintOwner.h>
#include <assert.h>
#include <math.h>
#include <sys/time.h>
#include <sys/sysctl.h>
#include <sys/stat.h>
#include <string.h>
static BOOL maximumEntropy;
static uint32_t storageUniform(uint32_t bound) { assert(bound); return maximumEntropy ? bound - 1 : 0; }
#define arc4random_uniform storageUniform
static double nativeBoot = 1700000000.25;
static double varBirth = 1699800000.125;
static BOOL statFailure;
static int storageStat(const char *path, struct stat *out) {
    assert(!strcmp(path, "/private/var"));
    if(statFailure) return -1;
    memset(out, 0, sizeof(*out));
    out->st_birthtimespec.tv_sec = (time_t)varBirth;
    out->st_birthtimespec.tv_nsec = (long)((varBirth - floor(varBirth)) * 1000000000);
    return 0;
}
#define stat(path, out) storageStat(path, out)
static NSString *nativeBootUUID = @"00112233-4455-6677-8899-AABBCCDDEEFF";
static int storageSysctl(const char *name, void *out, size_t *length, void *newp, size_t newlen) {
    assert(!newp && !newlen && out && length);
    if(!strcmp(name, "kern.bootsessionuuid")) {
        size_t needed = strlen(nativeBootUUID.UTF8String) + 1;
        assert(*length >= needed); memcpy(out, nativeBootUUID.UTF8String, needed); *length = needed;
        return 0;
    }
    assert(!strcmp(name, "kern.boottime") && *length >= sizeof(struct timeval));
    struct timeval value = {(time_t)nativeBoot, (suseconds_t)((nativeBoot - floor(nativeBoot)) * 1000000)};
    memcpy(out, &value, sizeof(value)); *length = sizeof(value); return 0;
}
#define sysctlbyname storageSysctl
#define SHADOW_PREFS_PLIST "/tmp/shadow-storage-unused.plist"
#define SHDWAppEnabledID @"App_Enabled"
#define SHDWAppDisabledID @"App_Disabled"
#define SHDWDetectorAggressiveID @"Detector_Aggressive"
static NSString *fallbackPath;
#define JBPath(path) (fallbackPath)
@interface FileDefaults : NSObject
@property(nonatomic, copy) NSString *path;
@property(nonatomic, strong) NSMutableDictionary *values;
- (id)objectForKey:(NSString *)key;
- (void)setObject:(id)object forKey:(NSString *)key;
- (void)removeObjectForKey:(NSString *)key;
- (BOOL)synchronize;
@end
@implementation FileDefaults
- (id)objectForKey:(NSString *)key { return self.values[key]; }
- (void)setObject:(id)object forKey:(NSString *)key { self.values[key] = object; }
- (void)removeObjectForKey:(NSString *)key { [self.values removeObjectForKey:key]; }
- (BOOL)synchronize { return [self.values writeToFile:self.path atomically:YES]; }
@end
@interface ShadowSettings : NSObject
@property(nonatomic, strong) FileDefaults *userDefaults;
+ (instancetype)sharedInstance;
- (NSDictionary *)fingerprintDataForIdentifier:(NSString *)identifier;
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier;
- (NSDictionary *)runtimeFingerprintDataForIdentifier:(NSString *)identifier vendorIdentifier:(NSUUID *__autoreleasing *)vendor;
- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)identifier;
- (BOOL)refreshFingerprintDataForIdentifier:(NSString *)identifier lockOnSuccess:(BOOL)lockOnSuccess;
@end
static ShadowSettings *sharedSettings;
'''
source += helpers + "\n" + customized + "\n@implementation ShadowSettings\n"
source += "+ (instancetype)sharedInstance { return sharedSettings; }\n" + methods + "\n@end\n"
storage = (root / "src/ShadowCore.dylib/policy/FingerprintStorage.m").read_text()
source += function(storage, "NSString *SHDWFingerprintOwnerIdentifier(") + "\n"
source += function(storage, "static NSDictionary *SHDWFingerprintProcessSnapshot(") + "\n"
source += function(storage, "NSDictionary *SHDWFingerprintData(")
source += r'''
int main(int argc, const char **argv) { @autoreleasepool {
    assert(argc == 3);
    NSString *path = @(argv[1]), *phase = @(argv[2]);
    fallbackPath = [path stringByAppendingString:@".fallback"];
    sharedSettings = [ShadowSettings new];
    FileDefaults *store = [FileDefaults new];
    store.path = path;
    store.values = [[NSDictionary dictionaryWithContentsOfFile:path] mutableCopy] ?: [NSMutableDictionary new];
    sharedSettings.userDefaults = store;
    assert(![sharedSettings fingerprintDataForIdentifier:nil]);
    assert(![sharedSettings refreshFingerprintDataForIdentifier:@""]);
    if([phase isEqual:@"seed"]) {
        for(unsigned i = 0; i < 2; i++) {
            maximumEntropy = i;
            NSDictionary *edge = SHDWNewFingerprintData();
            assert(SHDWValidFingerprintData(edge));
            assert([edge[@"BootTimeOffset"] longLongValue] == (i ? 86400 : -86400));
        }
        maximumEntropy = NO;
        store.values[@"Global_Enabled"] = @YES;
        store.values[@"a.app"] = @{@"App_Enabled":@YES, @"Detector_Aggressive":@NO, @"Unrelated":@"keep"};
        assert(![sharedSettings fingerprintDataForIdentifier:@"a.app"]);
        assert(![sharedSettings fingerprintDataForIdentifier:@"b.app"]);
        assert(!store.values[@"b.app"]);
        assert([sharedSettings refreshFingerprintDataForIdentifier:@"a.app"]);
        assert([sharedSettings refreshFingerprintDataForIdentifier:@"b.app"]);
        NSDictionary *a = SHDWFingerprintData(@"a.app");
        NSDictionary *b = SHDWFingerprintData(@"b.app");
        assert(SHDWValidFingerprintData(a) && SHDWValidFingerprintData(b) && ![a isEqual:b]);
        assert(!a[@"ActivationTimestamp"] && !b[@"ActivationTimestamp"]);
        assert([a[@"VendorIdentifier"] isEqual:[[NSUUID alloc] initWithUUIDString:a[@"VendorIdentifier"]].UUIDString]);
        assert(![a[@"VendorIdentifier"] isEqual:b[@"VendorIdentifier"]]);
        assert(![a isKindOfClass:NSMutableDictionary.class]);
        assert(!SHDWAppIsCustomized(store.values[@"b.app"]));
        assert([sharedSettings fingerprintDataForIdentifier:@"a.app"] && [a isEqual:SHDWFingerprintData(@"a.app")]);
        assert(([@{@"a":a, @"b":b} writeToFile:[path stringByAppendingString:@".baseline"] atomically:YES]));
        for(NSString *field in @[@"Version", @"MemoryDelta", @"InterfaceSeed", @"BootTimeOffset", @"NativeBootTimestamp", @"BootSessionUUID", @"NativeBootSessionUUID"]) {
            NSMutableDictionary *bad = [a mutableCopy]; [bad removeObjectForKey:field];
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[@0, @1, @16385, @1048577, @(NAN), @"16384"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"MemoryDelta"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[@0, @(-1), @"legacy unused field"]) {
            NSMutableDictionary *legacy = [a mutableCopy]; legacy[@"ActivationTimestamp"] = value;
            assert(SHDWValidFingerprintData(legacy));
        }
        for(id value in @[@0, @2, @"1"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"Version"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[[NSData data], [NSMutableData dataWithLength:31], @"seed"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"InterfaceSeed"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[@(-86401), @86401, @0.5, @(NAN), @"0"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"BootTimeOffset"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[@0, @(-1), @(NAN), @"1700000000"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"NativeBootTimestamp"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        for(id value in @[@0, @"", @"invalid", @"12345678-abcd-1234-abcd-123456789abc"]) {
            NSMutableDictionary *bad = [a mutableCopy]; bad[@"BootSessionUUID"] = value;
            assert(!SHDWValidFingerprintData(bad));
            bad = [a mutableCopy]; bad[@"VendorIdentifier"] = value;
            assert(!SHDWValidFingerprintData(bad));
        }
        double originalBoot = nativeBoot;
        NSDictionary *beforeFailure = [store.values copy];
        nativeBoot = [[NSDate date] timeIntervalSince1970] + 2 * kSHDWBootOffsetLimit;
        NSDictionary *fallback = [sharedSettings fingerprintDataForIdentifier:@"a.app"];
        NSMutableDictionary *expectedFallback = [a mutableCopy];
        [expectedFallback removeObjectForKey:@"BootTimeOffset"];
        assert([fallback isEqual:expectedFallback]);
        assert(![sharedSettings refreshFingerprintDataForIdentifier:@"a.app"]);
        assert(SHDWFingerprintData(@"failure.app").count == 0);
        assert([beforeFailure isEqual:store.values]);
        nativeBoot = originalBoot;
        assert(![sharedSettings fingerprintDataForIdentifier:@"failure.app"]);
        assert([sharedSettings refreshFingerprintDataForIdentifier:@"failure.app"]);
        assert(SHDWValidFingerprintData([sharedSettings fingerprintDataForIdentifier:@"failure.app"]));
        assert(SHDWFingerprintData(@"failure.app").count == 0);
        assert([sharedSettings refreshFingerprintDataForIdentifier:@"a.app"]);
        NSDictionary *fresh = [sharedSettings fingerprintDataForIdentifier:@"a.app"];
        assert(SHDWValidFingerprintData(fresh) && ![a isEqual:fresh]);
        assert(![fresh[@"VendorIdentifier"] isEqual:a[@"VendorIdentifier"]]);
        // Existing processes retain their original immutable snapshot.
        assert([SHDWFingerprintData(@"a.app") isEqual:a]);
        assert([[sharedSettings fingerprintDataForIdentifier:@"b.app"] isEqual:b]);
        NSDictionary *app = store.values[@"a.app"];
        assert([app[@"App_Enabled"] boolValue] && ![app[@"Detector_Aggressive"] boolValue]);
        assert([app[@"Unrelated"] isEqual:@"keep"] && [store.values[@"Global_Enabled"] boolValue]);
        assert(!SHDWAppIsCustomized(store.values[@"b.app"]));
        // Corrupt stored payload regenerates without deleting app configuration.
        store.values[@"bad.app"] = @{@"App_Disabled":@YES, @"Fingerprint_Data":@{@"Version":@999}};
        assert(SHDWValidFingerprintData([sharedSettings fingerprintDataForIdentifier:@"bad.app"]));
        assert([store.values[@"bad.app"][@"App_Disabled"] boolValue]);
        assert([store synchronize]);
    } else if([phase isEqual:@"vendor-migrate"]) {
        NSDictionary *otherApp = [store.values[@"b.app"] copy];
        NSMutableDictionary *legacy = [store.values[@"a.app"][@"Fingerprint_Data"] mutableCopy];
        legacy[@"FutureField"] = @{@"nested":@"preserve"};
        legacy[@"ActivationTimestamp"] = @123456.75;
        [legacy removeObjectForKey:@"VendorIdentifier"];
        for(id invalid in @[NSNull.null, @0, @"invalid", @"12345678-abcd-1234-abcd-123456789abc"]) {
            NSMutableDictionary *input = [legacy mutableCopy];
            if(invalid != NSNull.null) input[@"VendorIdentifier"] = invalid;
            NSDictionary *existing = @{@"App_Enabled":@NO, @"Detector_Aggressive":@YES,
                                      @"Unrelated":@"keep", @"Fingerprint_Data":input};
            store.values[@"legacy.app"] = existing;
            NSDictionary *migrated = [sharedSettings fingerprintDataForIdentifier:@"legacy.app"];
            assert(SHDWValidFingerprintData(migrated) && migrated[@"VendorIdentifier"]);
            NSMutableDictionary *withoutVendor = [migrated mutableCopy];
            [withoutVendor removeObjectForKey:@"VendorIdentifier"];
            assert([withoutVendor isEqual:legacy]);
            assert([migrated isEqual:[sharedSettings fingerprintDataForIdentifier:@"legacy.app"]]);
            NSMutableDictionary *withoutData = [store.values[@"legacy.app"] mutableCopy];
            [withoutData removeObjectForKey:@"Fingerprint_Data"];
            assert(([withoutData isEqual:@{@"App_Enabled":@NO, @"Detector_Aggressive":@YES, @"Unrelated":@"keep"}]));
            assert([otherApp isEqual:store.values[@"b.app"]]);
        }
        assert([store synchronize]);
    } else if([phase isEqual:@"vendor-restart"]) {
        NSDictionary *persisted = [store.values[@"legacy.app"][@"Fingerprint_Data"] copy];
        NSDictionary *restarted = [sharedSettings fingerprintDataForIdentifier:@"legacy.app"];
        assert([persisted isEqual:restarted]);
        assert([restarted[@"VendorIdentifier"] isEqual:persisted[@"VendorIdentifier"]]);
    } else if([phase isEqual:@"bounds"]) {
        NSDictionary *otherApp = [store.values[@"b.app"] copy];
        NSMutableDictionary *profile = [store.values[@"a.app"][@"Fingerprint_Data"] mutableCopy];
        profile[@"BootTimeOffset"] = @(-86400);
        profile[@"ActivationTimestamp"] = @123456.75;
        store.values[@"bounds.app"] = @{@"App_Enabled":@NO, @"Detector_Aggressive":@YES,
                                        @"Unrelated":@"keep", @"Fingerprint_Data":profile};
        varBirth = nativeBoot + 120.25;
        for(unsigned i = 0; i < 2; i++) {
            maximumEntropy = i;
            NSDictionary *generated = SHDWNewFingerprintData();
            assert(SHDWValidFingerprintData(generated));
            assert([generated[@"BootTimeOffset"] longLongValue] == (i ? 86400 : 121));
            assert(nativeBoot + [generated[@"BootTimeOffset"] doubleValue] >= varBirth);
        }
        maximumEntropy = NO;
        NSDictionary *clamped = [sharedSettings fingerprintDataForIdentifier:@"bounds.app"];
        NSMutableDictionary *expected = [profile mutableCopy];
        expected[@"BootTimeOffset"] = @121;
        assert([clamped isEqual:expected]);
        assert([clamped[@"BootSessionUUID"] isEqual:profile[@"BootSessionUUID"]]);
        assert(nativeBoot + [clamped[@"BootTimeOffset"] doubleValue] >= varBirth);
        assert([otherApp isEqual:store.values[@"b.app"]]);

        // Safety states permit only bounded, read-only runtime snapshots.
        for (NSString *flag in @[@"Fingerprint_Enabled", @"Fingerprint_Locked"]) {
            NSDictionary *guarded = @{@"Fingerprint_Data":profile,
                                      flag:@([flag isEqual:@"Fingerprint_Locked"])};
            store.values[@"guarded.app"] = guarded;
            NSDictionary *readOnly = [sharedSettings fingerprintDataForIdentifier:@"guarded.app"];
            assert([readOnly[@"BootTimeOffset"] integerValue] == 121);
            assert([readOnly[@"BootSessionUUID"] isEqual:profile[@"BootSessionUUID"]]);
            assert([store.values[@"guarded.app"] isEqual:guarded]);
            assert(![sharedSettings refreshFingerprintDataForIdentifier:@"guarded.app"]);
            assert([store.values[@"guarded.app"] isEqual:guarded]);
            statFailure = YES;
            NSDictionary *nativeBootFallback = [sharedSettings fingerprintDataForIdentifier:@"guarded.app"];
            assert(!nativeBootFallback[@"BootTimeOffset"]);
            assert([nativeBootFallback[@"VendorIdentifier"] isEqual:profile[@"VendorIdentifier"]]);
            assert([store.values[@"guarded.app"] isEqual:guarded]);
            statFailure = NO;
        }

        // Missing metadata and incompatible ranges preserve the complete stored profile.
        NSDictionary *beforeFailure = [store.values copy];
        for(unsigned mode = 0; mode < 3; mode++) {
            statFailure = mode == 0;
            varBirth = mode == 1 ? [[NSDate date] timeIntervalSince1970] - 1800
                                 : nativeBoot + 86401;
            assert(!SHDWNewFingerprintData());
            assert(![sharedSettings refreshFingerprintDataForIdentifier:@"bounds.app"]);
            NSDictionary *fallback = [sharedSettings fingerprintDataForIdentifier:@"bounds.app"];
            NSMutableDictionary *expectedFallback = [clamped mutableCopy];
            [expectedFallback removeObjectForKey:@"BootTimeOffset"];
            assert([fallback isEqual:expectedFallback]);
            assert([fallback[@"VendorIdentifier"] isEqual:clamped[@"VendorIdentifier"]]);
            assert([fallback[@"MemoryDelta"] isEqual:clamped[@"MemoryDelta"]]);
            assert([fallback[@"InterfaceSeed"] isEqual:clamped[@"InterfaceSeed"]]);
            assert([beforeFailure isEqual:store.values]);
        }
    } else if([phase isEqual:@"clock"]) {
        NSDictionary *previous = store.values[@"a.app"][@"Fingerprint_Data"];
        NSDictionary *untouched = [store.values[@"b.app"] copy];
        nativeBoot += 1.0;
        NSDictionary *corrected = [sharedSettings fingerprintDataForIdentifier:@"a.app"];
        assert(SHDWValidFingerprintData(corrected));
        assert([corrected[@"NativeBootTimestamp"] doubleValue] == nativeBoot);
        for(NSString *key in @[@"MemoryDelta", @"InterfaceSeed", @"BootTimeOffset", @"BootSessionUUID", @"NativeBootSessionUUID", @"VendorIdentifier"])
            assert([corrected[key] isEqual:previous[key]]);
        assert([untouched isEqual:store.values[@"b.app"]]);
    } else if([phase isEqual:@"reboot"]) {
        NSMutableDictionary *positive = [store.values[@"a.app"][@"Fingerprint_Data"] mutableCopy];
        positive[@"BootTimeOffset"] = @86400;
        NSMutableDictionary *priorApp = [store.values[@"a.app"] mutableCopy];
        priorApp[@"Fingerprint_Data"] = positive;
        store.values[@"a.app"] = priorApp;
        NSDictionary *previous = [positive copy];
        NSDictionary *untouched = [store.values[@"b.app"] copy];
        nativeBoot = floor([[NSDate date] timeIntervalSince1970]) - 60;
        nativeBootUUID = @"00112233-4455-6677-8899-AABBCCDDEEEE";
        NSDictionary *rebooted = [sharedSettings fingerprintDataForIdentifier:@"a.app"];
        assert(SHDWValidFingerprintData(rebooted));
        assert([rebooted[@"NativeBootTimestamp"] doubleValue] == nativeBoot);
        assert([rebooted[@"NativeBootSessionUUID"] isEqual:nativeBootUUID]);
        assert(![rebooted[@"BootSessionUUID"] isEqual:previous[@"BootSessionUUID"]]);
        for(NSString *key in @[@"MemoryDelta", @"InterfaceSeed", @"VendorIdentifier"])
            assert([rebooted[key] isEqual:previous[key]]);
        double offset = [rebooted[@"BootTimeOffset"] doubleValue];
        assert(offset >= -86400 && offset <= 86400);
        assert(nativeBoot + offset < [[NSDate date] timeIntervalSince1970] - 3600);
        assert([untouched isEqual:store.values[@"b.app"]]);
        assert([rebooted isEqual:SHDWFingerprintData(@"a.app")]);
    } else {
        NSDictionary *old = [NSDictionary dictionaryWithContentsOfFile:[path stringByAppendingString:@".baseline"]];
        NSDictionary *a = SHDWFingerprintData(@"a.app");
        assert(SHDWValidFingerprintData(a) && ![a isEqual:old[@"a"]]);
        assert([a isEqual:store.values[@"a.app"][@"Fingerprint_Data"]]);
        assert(![a[@"VendorIdentifier"] isEqual:old[@"a"][@"VendorIdentifier"]]);
        assert([SHDWFingerprintData(@"b.app") isEqual:old[@"b"]]);
    }
    puts("fingerprint storage: generation, persistence/restart, refresh isolation, immutable process snapshots and toggle retention passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-fingerprint-storage-") as tmp:
    tmp = Path(tmp)
    src, binary, prefs = tmp / "test.m", tmp / "test", tmp / "prefs.plist"
    src.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation", "-I", str(root / "src/Shadow.framework/Headers"), "-I",
        str(root / "src/ShadowCore.dylib/policy"), str(src), "-o", str(binary)], check=True)
    for phase in ["seed", "restart", "restart", "vendor-migrate", "vendor-restart", "bounds", "clock", "reboot"]:
        subprocess.run([str(binary), str(prefs), phase], check=True)
