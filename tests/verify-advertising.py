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
 assert([SHDWFingerprintAdvertisingValue(mode,saved,native,NO) isEqual:native]);
 assert([SHDWFingerprintAdvertisingValue(mode,saved,zero,NO) isEqual:zero]);
 NSMutableDictionary *config=[SHDWFingerprintConfiguration.defaultConfiguration mutableCopy];config[@"Advertising"]=@{@"Mode":mode};assert([SHDWFingerprintConfiguration configurationByValidating:config error:NULL]);
}
assert([SHDWFingerprintConfiguration.defaultConfiguration[@"Advertising"][@"Mode"] isEqual:@"zero"]);
assert([SHDWFingerprintAdvertisingValue(@"perApp",saved,native,YES) isEqual:saved]);
assert([SHDWFingerprintAdvertisingValue(@"zero",saved,native,YES) isEqual:zero]);
assert([SHDWFingerprintAdvertisingValue(@"system",saved,native,YES) isEqual:native]);
for(id invalid in @[@42,@"bad",zero,NSNull.null]){
 assert(!SHDWFingerprintAdvertisingUUIDValid(invalid));
 assert([SHDWFingerprintAdvertisingValue(@"perApp",invalid,native,YES) isEqual:native]);
}
assert([SHDWFingerprintAdvertisingValue(@"perApp",nil,native,YES) isEqual:native]);
assert(SHDWFingerprintAdvertisingValue(@"perApp",nil,nil,YES)==nil);
NSMutableDictionary *legacy=[SHDWFingerprintConfiguration.defaultConfiguration mutableCopy];[legacy removeObjectForKey:@"Advertising"];assert([SHDWFingerprintConfiguration configurationByValidating:legacy error:NULL]);
for(id invalid in @[@{@"Mode":@"bad"},@{@"Mode":@"perApp",@"extra":@1},NSNull.null,@[]]){legacy[@"Advertising"]=invalid;assert(![SHDWFingerprintConfiguration configurationByValidating:legacy error:NULL]);}
puts("PASS: zero default, consent gates, zero/system/perApp, absent/invalid saved ID, legacy and strict mode validation");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-advertising-test-") as d:
    p=Path(d); (p/"fixture.m").write_text(source)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-framework","Foundation","-I",str(root/"src/Shadow.framework/Headers"),str(p/"fixture.m"),str(root/"src/Shadow.framework/Fingerprint/Configuration.m"),"-o",str(p/"fixture")],check=True)
    subprocess.run([str(p/"fixture")],check=True)
