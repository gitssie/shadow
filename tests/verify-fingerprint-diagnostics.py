"""Execute production diagnostic snapshot methods with controlled storage changes."""
from pathlib import Path
import subprocess,tempfile,sys
if sys.platform!="darwin":
    print("SKIP: macOS Foundation required")
    raise SystemExit(0)
root=Path(__file__).resolve().parents[1]
body=(root/"src/Shadow.framework/Fingerprint/Diagnostics.m").read_text()
body="\n".join(line for line in body.splitlines() if not line.startswith("#import"))
body=body.replace("ShadowSettings","FixtureSettings").replace("NSBundle","FixtureBundle")
fixture=r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintDiagnostics.h>
#import <Shadow/FingerprintConfiguration.h>
#import <Shadow/FingerprintMemory.h>
#include <assert.h>
#define SHDWAppEnabledID @"App_Enabled"
#define SHDWUniversalFingerprintID @"Universal_Fingerprint"
static NSDictionary *savedApplication,*prefs;static NSString *owner;
@interface FixtureBundle:NSObject
+ (instancetype)mainBundle;
- (NSString *)bundleIdentifier;
@end
@implementation FixtureBundle
+ (instancetype)mainBundle{return [self new];}
- (NSString *)bundleIdentifier{return @"current.app";}
@end
@interface FixtureSettings:NSObject
+ (instancetype)sharedInstance;
- (NSDictionary *)storedFingerprintApplicationForIdentifier:(NSString *)identifier;
- (NSDictionary *)getPreferencesForIdentifier:(NSString *)identifier;
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier;
@end
@implementation FixtureSettings
+ (instancetype)sharedInstance{return [self new];}
- (NSDictionary *)storedFingerprintApplicationForIdentifier:(NSString *)identifier{(void)identifier;return savedApplication;}
- (NSDictionary *)getPreferencesForIdentifier:(NSString *)identifier{(void)identifier;return prefs;}
- (NSString *)fingerprintOwnerIdentifierForIdentifier:(NSString *)identifier{(void)identifier;return owner;}
@end
'''+body+r'''
int main(void){@autoreleasepool{
 assert(![[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"runtimeAvailable"]boolValue]);
 NSDictionary *data=@{@"AdvertisingIdentifier":@"11111111-1111-4111-8111-111111111111",@"UpdatedAt":@1,@"MemoryDelta":@1,@"InterfaceSeed":@"private-seed"};
 NSDictionary *config=SHDWFingerprintConfiguration.defaultConfiguration;
 savedApplication=@{@"Fingerprint_Data":data,@"Fingerprint_Config":config};prefs=@{@"App_Enabled":@YES,@"Universal_Fingerprint":@YES};owner=@"current.app";
 [SHDWFingerprintDiagnostics recordData:data configuration:config owner:owner enabled:YES];
 NSDictionary *snapshot=[SHDWFingerprintDiagnostics currentApplicationSnapshot];
 assert(![snapshot[@"networkUserAgentSourceReady"]boolValue]);
 [SHDWFingerprintDiagnostics recordNetworkUserAgentSourceReady:YES];
 assert([[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"networkUserAgentSourceReady"]boolValue]);
 assert([snapshot[@"runtimeAvailable"]boolValue]);assert(![snapshot[@"stale"]boolValue]);assert(!snapshot[@"fields"][@"InterfaceSeed"]);
 NSMutableDictionary *changed=[data mutableCopy];changed[@"AdvertisingIdentifier"]=@"22222222-2222-4222-8222-222222222222";
 savedApplication=@{@"Fingerprint_Data":changed,@"Fingerprint_Config":config};assert([[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"stale"]boolValue]);
 savedApplication=@{@"Fingerprint_Data":data,@"Fingerprint_Config":config};prefs=@{@"App_Enabled":@YES,@"Universal_Fingerprint":@NO};assert([[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"stale"]boolValue]);
 prefs=@{@"App_Enabled":@YES,@"Universal_Fingerprint":@YES};owner=@"other.app";assert([[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"stale"]boolValue]);
 owner=@"current.app";savedApplication=nil;assert([[SHDWFingerprintDiagnostics currentApplicationSnapshot][@"stale"]boolValue]);
 NSDictionary *again=[SHDWFingerprintDiagnostics currentApplicationSnapshot];assert([again[@"fields"][@"AdvertisingIdentifier"] isEqual:data[@"AdvertisingIdentifier"]]);
 puts("PASS: runtime-unavailable, read-only whitelist, first-call refresh detection, enable/owner changes, unavailable storage and immutable process snapshot");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-diagnostics-test-") as d:
 p=Path(d);(p/"fixture.m").write_text(fixture)
 subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-framework","Foundation","-I",str(root/"src/Shadow.framework/Headers"),str(p/"fixture.m"),str(root/"src/Shadow.framework/Fingerprint/Configuration.m"),"-o",str(p/"fixture")],check=True)
 subprocess.run([str(p/"fixture")],check=True)
