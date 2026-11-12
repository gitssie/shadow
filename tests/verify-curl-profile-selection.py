"""Exercise the App-side transport activation using production OS-profile selection."""
from pathlib import Path
import subprocess
import tempfile
import sys

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
implementation = (root / "src/ShadowCore.dylib/policy/CurlTransportConfiguration.m").read_text()
implementation = "\n".join(line for line in implementation.splitlines() if not line.startswith("#import"))
source = r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintConfiguration.h>
#include <assert.h>
static NSString *mode, *version, *prepared;
static unsigned calls;
static NSDictionary *SHDWFingerprintConfig(NSString *bundle) {
    (void)bundle;return mode ? @{@"Network":@{@"Transport":mode}} : @{};
}
static NSString *SHDWFingerprintOSVersionString(void) { return version; }
void SHDWCurlTransportPrepareProfile(NSString *profile) { calls++;prepared=[profile copy]; }
''' + implementation + r'''
int main(void) { @autoreleasepool {
    NSArray *versions=@[@"16.3",@"17.2",@"17.7.2",@"18.0",@"18.3.1",@"18.4",@"18.7.2",@"18.10"];
    NSArray *profiles=@[@"safari172_ios",@"safari172_ios",@"safari172_ios",@"safari180_ios",@"safari180_ios",@"safari184_ios",@"safari184_ios",@"safari184_ios"];
    (void)profiles;
    for(id selected in @[NSNull.null,@"native",@"auto",@"safari184_ios",@"impit465"]) {
        mode=selected==NSNull.null ? nil : selected;
        for(NSUInteger i=0;i<versions.count;i++) {
            version=versions[i];prepared=nil;unsigned before=calls;
            SHDWCurlTransportPrepare();
#if SHADOW_CURL_IMPERSONATE
            assert(calls==before+1);
            if([mode isEqual:@"impit465"]) assert([prepared isEqual:@"impit465"]);
            else if([mode isEqual:@"auto"] || [mode isEqual:@"safari184_ios"]) assert([prepared isEqual:profiles[i]]);
            else assert(!prepared);
#else
            assert(calls==before && !prepared);
#endif
        }
    }
    mode=@"auto";version=nil;prepared=nil;SHDWCurlTransportPrepare();assert(!prepared);
    mode=@"impit465";version=nil;prepared=nil;SHDWCurlTransportPrepare();
#if SHADOW_CURL_IMPERSONATE
    assert([prepared isEqual:@"impit465"]);
#else
    assert(!prepared);
#endif
    puts("App curl activation: saved fingerprint version mapping, legacy mode, native/missing defaults and disabled build passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-curl-selection-") as directory:
    test,binary=Path(directory)/"test.m",Path(directory)/"check"
    test.write_text(source)
    for enabled in (0,1):
        subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-Wno-unused-function",
            "-fsanitize=address,undefined","-framework","Foundation",f"-DSHADOW_CURL_IMPERSONATE={enabled}",
            "-I",str(root/"src/Shadow.framework/Headers"),str(test),
            str(root/"src/Shadow.framework/Fingerprint/Configuration.m"),"-o",str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
