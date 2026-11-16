"""Execute the Foundation path adapter with controlled policy and alias decisions."""

from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/NSFileManager.x").read_text()


def function(signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


# The two legacy attribute wrappers must also consult explicit policy first.
for selector in (
    "- (NSDictionary<NSFileAttributeKey, id> *)attributesOfFileSystemForPath:",
    "- (NSDictionary *)fileSystemAttributesAtPath:",
):
    wrapper = function(selector)
    assert wrapper.index("[_shadow isPathRestricted:") < wrapper.index(
        "shdw_path_is_main_bundle_exempt(")

production = "\n".join(function(signature) for signature in (
    "static NSDictionary* _shdw_optionsForAbsolute(",
    "static NSDictionary* _shdw_writeNoFollowOptions(",
    "static BOOL shdw_foundation_path_denied(",
    "static BOOL shdw_foundation_url_denied(",
))
attribute_wrapper = function("- (NSDictionary *)fileSystemAttributesAtPath:")
attribute_wrapper = (
    "static NSDictionary *file_system_attributes(NSFileManager *self, NSString *path) "
    + attribute_wrapper[attribute_wrapper.index("{"):]
).replace("%orig", "native_attributes()")

fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <string.h>
static NSString *const kShadowRestrictionWorkingDir = @"cwd";
static NSString *const kShadowRestrictionOperation = @"operation";
static NSString *const kShadowRestrictionOpWrite = @"write";
static NSString *const kShadowRestrictionNoFollow = @"nofollow";
static BOOL writePolicy, callerExternal = YES;
static unsigned engineCalls, classifierCalls, nativeCalls;
static NSString *lastPath, *classifiedPath;
static NSDictionary *lastOptions;
@interface MockShadow : NSObject
- (BOOL)isPathRestricted:(NSString *)path options:(NSDictionary *)options;
@end
@implementation MockShadow
- (BOOL)isPathRestricted:(NSString *)path options:(NSDictionary *)options {
    engineCalls++;
    lastPath = path;
    lastOptions = options;
    NSString *absolute = path.isAbsolutePath ? path :
        [options[kShadowRestrictionWorkingDir] stringByAppendingPathComponent:path];
    if([absolute isEqualToString:@"/app/embedded.mobileprovision"])
        return YES;
    return writePolicy && [absolute hasPrefix:@"/app/"] &&
        [options[kShadowRestrictionOperation] isEqual:kShadowRestrictionOpWrite];
}
@end
static MockShadow *_shadow;
@interface FixtureFileManager : NSFileManager
@end
@implementation FixtureFileManager
- (NSString *)currentDirectoryPath { return @"/work"; }
@end
static BOOL shdw_path_is_main_bundle_exempt(const char *path) {
    return path && strncmp(path, "/app/", 5) == 0;
}
static BOOL classify(const char *path, BOOL nofollow) {
    classifierCalls++;
    classifiedPath = path ? @(path) : nil;
    // Include the ordinary bundle path to exercise the alias exemption.
    return [classifiedPath isEqualToString:@"/app/readme"] ||
        [classifiedPath isEqualToString:@"/external/hidden"] ||
        (!nofollow && [classifiedPath isEqualToString:@"/work/link"]);
}
static BOOL shdw_path_is_external_hidden(const char *path) { return classify(path, NO); }
static BOOL shdw_path_is_external_hidden_nofollow(const char *path) { return classify(path, YES); }
static BOOL isCallerExternal(void) { return callerExternal; }
static NSDictionary *native_attributes(void) { nativeCalls++; return @{}; }
'''

fixture += production + "\n" + attribute_wrapper
fixture += r'''
static BOOL read_allowed(NSFileManager *fm, NSString *path) {
    return file_system_attributes(fm, path) != nil;
}
static void reset(void) {
    engineCalls = classifierCalls = nativeCalls = 0;
    lastPath = classifiedPath = nil;
    lastOptions = nil;
}
int main(void) { @autoreleasepool {
    _shadow = [MockShadow new];
    NSFileManager *fm = [FixtureFileManager new];
    reset();
    assert(read_allowed(fm, @"/app/readme"));
    assert(engineCalls == 1 && classifierCalls == 0 && nativeCalls == 1);

    writePolicy = YES;
    assert(shdw_foundation_path_denied(fm, @"/app/readme",
        _shdw_writeNoFollowOptions(fm, YES), YES));
    assert([lastOptions[kShadowRestrictionNoFollow] boolValue]);
    writePolicy = NO;
    assert(!shdw_foundation_path_denied(fm, @"/app/readme",
        _shdw_writeNoFollowOptions(fm, YES), YES));
    assert(shdw_foundation_path_denied(fm, @"/app/embedded.mobileprovision", nil, NO));
    assert(!read_allowed(fm, @"/app/embedded.mobileprovision"));
    assert(shdw_foundation_url_denied(
        [NSURL fileURLWithPath:@"/app/embedded.mobileprovision"], nil, NO));
    assert(shdw_foundation_path_denied(fm, @"/external/hidden", nil, NO));

    NSDictionary *options = _shdw_optionsForAbsolute(fm, NO);
    reset();
    assert(!shdw_foundation_path_denied(fm, @"link", options, YES));
    assert([lastPath isEqualToString:@"link"]);
    assert([classifiedPath isEqualToString:@"/work/link"]);
    assert([lastOptions[kShadowRestrictionWorkingDir] isEqualToString:@"/work"]);
    assert([lastOptions[kShadowRestrictionNoFollow] boolValue]);
    assert(options[kShadowRestrictionNoFollow] == nil);
    assert(shdw_foundation_path_denied(fm, @"link", options, NO));
    assert(lastOptions == options);
    options = _shdw_writeNoFollowOptions(fm, NO);
    assert(!shdw_foundation_path_denied(fm, @"ordinary", options, YES));
    assert(lastOptions == options);
    assert([lastOptions[kShadowRestrictionOperation] isEqual:kShadowRestrictionOpWrite]);
    assert([lastOptions[kShadowRestrictionWorkingDir] isEqualToString:@"/work"]);

    reset();
    assert(!shdw_foundation_path_denied(fm, nil, nil, NO));
    assert(!shdw_foundation_url_denied([NSURL URLWithString:@"https://example.invalid"], nil, NO));
    assert(engineCalls == 0 && classifierCalls == 0);
    assert(read_allowed(fm, @"/work/ordinary"));
    assert(engineCalls == 1 && nativeCalls == 1);
    reset();
    callerExternal = NO;
    assert(read_allowed(fm, @"/app/embedded.mobileprovision"));
    assert(engineCalls == 0 && classifierCalls == 0 && nativeCalls == 1);
}}
'''

with tempfile.TemporaryDirectory(prefix="shadow-foundation-policy-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(fixture)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation",
        str(src), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)

print("Foundation path policy: explicit bundle policy, alias filtering, relative/no-follow options and caller scope passed")
