"""Exercise production advertising selection and configuration validation."""
from pathlib import Path
import subprocess, sys, tempfile
if sys.platform != "darwin":
    print("SKIP: macOS Foundation required")
    raise SystemExit(0)
root=Path(__file__).resolve().parents[1]
source=r'''
#import <Shadow/FingerprintAdvertising.h>
#import <Shadow/FingerprintConfiguration.h>
#include <assert.h>
int main(void){@autoreleasepool{
NSString *native=@"11111111-1111-4111-8111-111111111111",*saved=@"22222222-2222-4222-8222-222222222222",*zero=@"00000000-0000-0000-0000-000000000000";
for(NSString *mode in @[@"system",@"zero",@"perApp"]){
 NSMutableDictionary *config=[SHDWFingerprintConfiguration.defaultConfiguration mutableCopy];config[@"Advertising"]=@{@"Mode":mode};assert([SHDWFingerprintConfiguration configurationByValidating:config error:NULL]);
}
assert([SHDWFingerprintConfiguration.defaultConfiguration[@"Advertising"][@"Mode"] isEqual:@"zero"]);
assert([SHDWFingerprintAdvertisingValue(@"perApp",saved,native) isEqual:saved]);
assert([SHDWFingerprintAdvertisingValue(@"perApp",saved,zero) isEqual:saved]);
assert([SHDWFingerprintAdvertisingValue(@"zero",saved,native) isEqual:zero]);
assert([SHDWFingerprintAdvertisingValue(@"system",saved,native) isEqual:native]);
assert(SHDWFingerprintAdvertisingValue(@"system",saved,nil)==nil);
for(id invalid in @[@42,@"bad",zero,NSNull.null]){
 assert(!SHDWFingerprintAdvertisingUUIDValid(invalid));
 assert([SHDWFingerprintAdvertisingValue(@"perApp",invalid,native) isEqual:zero]);
}
assert([SHDWFingerprintAdvertisingValue(@"perApp",nil,native) isEqual:zero]);
NSUInteger status=99;
assert(SHDWFingerprintAdvertisingTrackingStatus(@"perApp",&status) && status==3);
assert(SHDWFingerprintAdvertisingTrackingStatus(@"zero",&status) && status==2);
assert(!SHDWFingerprintAdvertisingTrackingStatus(@"system",&status) && status==2);
assert(SHDWFingerprintAdvertisingTrackingStatus(@"perApp",NULL));
NSMutableDictionary *legacy=[SHDWFingerprintConfiguration.defaultConfiguration mutableCopy];[legacy removeObjectForKey:@"Advertising"];assert([SHDWFingerprintConfiguration configurationByValidating:legacy error:NULL]);
for(id invalid in @[@{@"Mode":@"bad"},@{@"Mode":@"perApp",@"extra":@1},NSNull.null,@[]]){legacy[@"Advertising"]=invalid;assert(![SHDWFingerprintConfiguration configurationByValidating:legacy error:NULL]);}
puts("PASS: zero default, configuration-derived ATT and zero/system/perApp, absent/invalid saved ID, legacy and strict mode validation");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-advertising-test-") as d:
    p=Path(d); (p/"fixture.m").write_text(source)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-framework","Foundation","-I",str(root/"src/Shadow.framework/Headers"),str(p/"fixture.m"),str(root/"src/Shadow.framework/Fingerprint/Configuration.m"),"-o",str(p/"fixture")],check=True)
    subprocess.run([str(p/"fixture")],check=True)
