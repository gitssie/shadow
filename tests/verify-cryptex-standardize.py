#!/usr/bin/env python3
"""Exercise stock Cryptex aliases through the production path standardizer."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
framework = root / "src/Shadow.framework"
source = (framework / "Core+Utilities.m").read_text()
start = source.index("+ (NSString *)getStandardizedPath:")
end = source.index("// code from Choicy", start)
method = source[start:end]
helper = source[source.index("static NSString *shdwCanonicalStockCryptexPath"):source.index("@implementation")] if "static NSString *shdwCanonicalStockCryptexPath" in source else ""
prefix = r'''
#import <Foundation/Foundation.h>
#import <Shadow/JBPath.h>
#include <assert.h>
static const char *capturedRoot;
BOOL shdw_is_restricted_root(const char *path) {
    return shdw_is_restricted_root_with_prefix(path, capturedRoot);
}
@interface Shadow : NSObject
+ (NSString *)getStandardizedPath:(NSString *)path;
@end
'''
cases = r'''
@end
int main(void) { @autoreleasepool {
    for (NSString *name in @[@"OS", @"App"]) {
        NSString *tail = [@"/Cryptexes/" stringByAppendingString:name];
        tail = [tail stringByAppendingString:@"/usr/lib/libobjc-trampolines.dylib"];
        NSString *expected = [@"/System" stringByAppendingString:tail];
        for (NSString *root in @[@"/private/preboot", @"/preboot"]) {
            NSString *raw = [root stringByAppendingString:tail];
            assert([[Shadow getStandardizedPath:raw] isEqualToString:expected]);
            assert([[Shadow getStandardizedPath:[raw stringByAppendingString:@"/"]] isEqualToString:expected]);
        }
    }
    for (NSString *raw in @[@"/private/preboot/Cryptexes/OS-other/usr/lib/test",
        @"/private/preboot/Cryptexes/Apps/usr/lib/test",
        @"/private/preboot/fixture/jb/usr/lib/test"]) {
        assert([[Shadow getStandardizedPath:raw] isEqualToString:raw]);
    }
    NSString *escape = @"/private/preboot/Cryptexes/OS/../../fixture/jb/test";
    assert(![[Shadow getStandardizedPath:escape] hasPrefix:@"/System/"]);
    capturedRoot = "/private/preboot/Cryptexes/OS/custom";
    NSString *captured = @"/private/preboot/Cryptexes/OS/custom/test";
    assert([[Shadow getStandardizedPath:captured] isEqualToString:captured]);
    puts("stock Cryptex standardization: system aliases and sibling boundaries passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-cryptex-standardize-") as directory:
    directory = Path(directory)
    fixture, binary = directory / "fixture.m", directory / "fixture"
    fixture.write_text(prefix + helper + "\n@implementation Shadow\n" + method + cases)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-framework", "Foundation", "-I", str(framework / "Headers"), str(fixture), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
