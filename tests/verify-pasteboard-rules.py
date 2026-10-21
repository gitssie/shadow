"""Reproduce and verify the narrow pasteboard storage structure exception."""
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
framework = root / "src/Shadow.framework"
rules_path = framework / "layout/Library/Shadow/Rulesets/StandardRules.plist"
entry = "/var/mobile/Library/Caches/com.apple.Pasteboard"
rules = plistlib.loads(rules_path.read_bytes())
assert rules["FileSystemStructure"]["paths"].count(entry) == 1
assert entry not in rules["FileSystemStructure"]["dirs"]
old_rules = plistlib.loads(rules_path.read_bytes())
old_rules["FileSystemStructure"]["paths"].remove(entry)


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start) + 1
    depth = 1
    while depth:
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
        end += 1
    return source[start:end]


standardizer = function((framework / "Core+Utilities.m").read_text(),
                        "+ (NSString *)getStandardizedPath:")
matcher = function((framework / "RestrictionEngine.m").read_text(),
                   "static BOOL shdwSnapshotDeniesPath(")
prefix = r'''
#import <Foundation/Foundation.h>
#import "Ruleset.h"
#import "RulesetCompiler.h"
#include <assert.h>
#include <string.h>
@interface Shadow : NSObject
+ (NSString *)getStandardizedPath:(NSString *)path;
@end
@implementation Shadow
'''
middle = r'''
@end
@interface ShadowRulesetSnapshot : NSObject
@property(nonatomic, copy) NSArray<RulesetEngine *> *rulesets;
@end
@implementation ShadowRulesetSnapshot @end
'''
suffix = r'''
// Exercise the production snapshot matcher at each ancestor, as the engine does.
static BOOL restricted(ShadowRulesetSnapshot *snapshot, NSString *raw) {
    NSString *path = [Shadow getStandardizedPath:raw];
    while(path.length > 1) {
        if(shdwSnapshotDeniesPath(snapshot, path)) return YES;
        path = path.stringByDeletingLastPathComponent;
    }
    return NO;
}
int main(int argc, char **argv) { @autoreleasepool {
    assert(argc == 3);
    RulesetEngine *before = [ShadowRulesetCompiler compileRulesetAtURL:
        [NSURL fileURLWithPath:@(argv[1])]];
    RulesetEngine *after = [ShadowRulesetCompiler compileRulesetAtURL:
        [NSURL fileURLWithPath:@(argv[2])]];
    assert(before && after);
    ShadowRulesetSnapshot *oldSnapshot = [ShadowRulesetSnapshot new]; oldSnapshot.rulesets = @[before];
    ShadowRulesetSnapshot *newSnapshot = [ShadowRulesetSnapshot new]; newSnapshot.rulesets = @[after];
    NSString *base = @"/var/mobile/Library/Caches/com.apple.Pasteboard";
    NSArray *allowed = @[base, [base stringByAppendingString:@"/hash"],
        [base stringByAppendingString:@"/hash/hash"],
        [base stringByAppendingString:@"/hash/payload.txt"],
        [base stringByAppendingString:@"/hash/.metadata"],
        [base stringByAppendingString:@"/hash/nested/anything"]];
    for(NSString *path in allowed) {
        assert(![before isPathCompliant:path]);
        assert(restricted(oldSnapshot, path));
        assert([after isPathCompliant:path]);
        assert(![after isPathBlacklisted:path]);
        assert(!restricted(newSnapshot, path));
        NSString *alias = [@"/private" stringByAppendingString:path];
        assert([[Shadow getStandardizedPath:alias] isEqualToString:path]);
        assert(restricted(oldSnapshot, alias) && !restricted(newSnapshot, alias));
    }
    for(NSString *path in @[@"/var/mobile/Library/Caches/com.apple.PasteboardEvil",
        @"/var/mobile/Library/Caches/com.apple.PasteboardEvil/hash/hash",
        @"/var/mobile/Library/Caches/com.apple.Pasteboard-backup/payload",
        @"/var/mobile/Library/Caches/Filza/pasteboard.plist",
        @"/var/mobile/Library/Caches/com.tigisoftware.Filza/pasteboard.plist",
        @"/var/mobile/Library/Filza/pasteboard.plist",
        @"/var/mobile/Library/Caches/com.example.cache/payload"]) {
        assert(![after isPathCompliant:path] && restricted(newSnapshot, path));
        assert(restricted(newSnapshot, [@"/private" stringByAppendingString:path]));
    }
    for(NSString *path in @[@"/System/Developer", @"/System/Developer/usr/bin/tool"]) {
        assert([after isPathBlacklisted:path] && restricted(newSnapshot, path));
    }
    // The fixture is loaded through the real compiler, including its cache round trip.
    RulesetEngine *cached = [ShadowRulesetCompiler compileRulesetAtURL:
        [NSURL fileURLWithPath:@(argv[2])]];
    assert(cached && [cached isPathCompliant:[base stringByAppendingString:@"/hash/hash"]]);
    puts("pasteboard rules: old denial reproduced; exact subtree, aliases and sibling denials passed");
} }
'''

with tempfile.TemporaryDirectory(prefix="shadow-pasteboard-rules-") as tmp:
    tmp = Path(tmp)
    old_path, new_path = tmp / "before.plist", tmp / "after.plist"
    old_path.write_bytes(plistlib.dumps(old_rules))
    new_path.write_bytes(plistlib.dumps(rules))
    src, binary = tmp / "test.m", tmp / "test"
    src.write_text(prefix + standardizer + middle + matcher + suffix)
    subprocess.run([
        "xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-Wno-incompatible-pointer-types", "-fsanitize=address,undefined", "-framework", "Foundation",
        "-I", str(framework), str(src), str(framework / "Ruleset.m"),
        str(framework / "RulesetCompiler.m"), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary), str(old_path), str(new_path)], check=True)
