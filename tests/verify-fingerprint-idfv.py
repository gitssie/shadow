"""Compile the production IDFV policy and hook with caller/storage doubles."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[1]
def body(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]
policy = body((root / "src/ShadowCore.dylib/policy/FingerprintPolicy.m").read_text(), "NSUUID *SHDWFingerprintVendorIdentifier(")
hook = body((root / "src/ShadowCore.dylib/hooks/Universal/Fingerprint.x").read_text(), "- (NSUUID *)identifierForVendor")
hook = hook.replace("%orig", "[self nativeIdentifier]")
source = r"""
#import <Foundation/Foundation.h>
#include <assert.h>
static NSDictionary *profile;
static BOOL shdw_fingerprint_enabled = YES;
static NSString *shdw_fingerprint_bundle_id = @"idfv.test";
static unsigned nativeCalls;
static NSDictionary *SHDWFingerprintData(NSString *bundle) { assert([bundle isEqual:shdw_fingerprint_bundle_id]); return profile; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active=YES;active;active=NO)
@interface Device : NSObject
- (NSUUID *)nativeIdentifier;
- (NSUUID *)identifierForVendor;
@end
""" + policy + r"""
@implementation Device
- (NSUUID *)nativeIdentifier { nativeCalls++; return [[NSUUID alloc] initWithUUIDString:@"00000000-0000-4000-8000-000000000001"]; }
""" + hook + r"""
@end
int main(void) { @autoreleasepool {
    Device *device = [Device new];
    NSString *expected = @"A17E1807-1001-4000-8000-000000000001";
    profile = @{ @"VendorIdentifier": expected };
    for(unsigned i=0;i<100;i++) {
        NSUUID *value = device.identifierForVendor;
        assert([value isKindOfClass:NSUUID.class] && [value.UUIDString isEqual:expected]);
    }
    assert(!nativeCalls);
    shdw_fingerprint_enabled=NO; assert(device.identifierForVendor && nativeCalls==1);
    shdw_fingerprint_enabled=YES;
    for(id invalid in @[@{}, @{@"VendorIdentifier":@123}, @{@"VendorIdentifier":@"invalid"}]) {
        profile=invalid; assert(device.identifierForVendor);
    }
    assert(nativeCalls==4);
    puts("fingerprint IDFV: UUID type, stable value, enabled-process scope and native fallback passed");
} }
"""
with tempfile.TemporaryDirectory(prefix="shadow-idfv-") as tmp:
    src=Path(tmp)/"test.m"; binary=Path(tmp)/"test"
    src.write_text(source)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-framework","Foundation",str(src),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
