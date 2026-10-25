#!/usr/bin/env python3
"""Exercise the production ownership error formatter without accessing a Keychain."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory(prefix="shadow-ownership-") as directory:
    directory = Path(directory)
    source = directory / "main.m"
    source.write_text(r'''#import <Foundation/Foundation.h>
#import "OwnershipDiagnostics.h"
NSString *SHDWLocalizedText(NSString *text) { return [@"localized:" stringByAppendingString:text]; }
int main(void) { @autoreleasepool {
    NSDictionary *details = @{@"kind":@"keychainOwnership", @"sharedKeychainGroups":@[@"TEAM.shared"], @"sharedKeychainOwners":@{@"TEAM.shared":@[@"other.app"]}, @"ownershipIssues":@[@{@"bundleID":@"unreadable.app", @"reason":@"DER-only signed entitlements unavailable"}]};
    NSString *message = SHDWOwnershipErrorDescription(@"blocked", details);
    for (NSString *value in @[@"localized:blocked", @"TEAM.shared", @"other.app", @"unreadable.app", @"localized:DER-only signed entitlements unavailable"]) if (![message containsString:value]) return 1;
    if (![SHDWOwnershipErrorDescription(@"ordinary", @{}) isEqual:@"localized:ordinary"]) return 2;
    if (![SHDWOwnershipErrorDescription(@"ordinary", nil) isEqual:@"localized:ordinary"]) return 3;
    NSDictionary *container = @{@"kind":@"containerOwnership", @"containerGroups":@[@"group.shared",@"group.unverified"], @"sharedAppGroups":@[@"group.shared"], @"sharedGroupOwners":@{@"group.shared":@[@"other.container.app"]}, @"ownershipIssues":@[@{@"bundleID":@"unreadable.container.app", @"reason":@"Unreadable target signature"}]};
    NSString *containerMessage = SHDWOwnershipErrorDescription(@"blocked", container);
    for (NSString *value in @[@"localized:Shared app group: group.shared", @"localized:App group being checked: group.unverified", @"other.container.app", @"unreadable.container.app", @"localized:Unreadable target signature"]) if (![containerMessage containsString:value]) return 4;
    puts("Ownership diagnostics: localized reasons, conflicting apps and ordinary errors passed");
} return 0; }
''')
    services = ROOT / "src/Shadow.app/Services"
    binary = directory / "check"
    subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-I", str(services), "-framework", "Foundation", str(source), str(services / "OwnershipDiagnostics.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
