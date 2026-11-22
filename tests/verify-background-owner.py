#!/usr/bin/env python3
"""Exercise installed-app identity normalization using the production resolver."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
text = (root / "src/ShadowWebKit.dylib/Background.m").read_text()
resolver = text[text.index("static NSString *CanonicalIdentifier("):text.index("static unsigned backgroundReady;")]
source = r'''
#import <Foundation/Foundation.h>
#import <objc/message.h>
#include <assert.h>
static NSString *expectedCandidate;
static id installedBundle, installedEntitlements;
static BOOL unavailable, throws;
@interface FixtureProxy : NSObject
+ (id)applicationProxyForIdentifier:(NSString *)identifier;
@end
@implementation FixtureProxy
+ (id)applicationProxyForIdentifier:(NSString *)identifier {
    assert([identifier isEqual:expectedCandidate]); return [self new];
}
- (id)valueForKey:(NSString *)key {
    if(throws) @throw [NSException exceptionWithName:@"fixture" reason:nil userInfo:nil];
    if([key isEqual:@"applicationIdentifier"]) return installedBundle;
    if([key isEqual:@"entitlements"]) return installedEntitlements;
    assert(NO); return nil;
}
@end
static Class FixtureClass(NSString *name) {
    assert([name isEqual:@"LSApplicationProxy"]); return unavailable ? Nil : FixtureProxy.class;
}
#define NSClassFromString FixtureClass
''' + resolver + r'''
int main(void) { @autoreleasepool {
    assert(!CanonicalIdentifier(nil)); assert(!CanonicalIdentifier(@""));
    assert(!CanonicalIdentifier((id)@42));
    for(NSString *s in @[@"plain",@".invalid",@"invalid."]) assert([CanonicalIdentifier(s) isEqual:s]);
    NSString *signedID=@"TEAM.example.app";
    expectedCandidate=@"example.app"; installedBundle=expectedCandidate;
    installedEntitlements=@{@"application-identifier":signedID};
    assert([CanonicalIdentifier(signedID) isEqual:expectedCandidate]);
    installedEntitlements=@{@"application-identifier":@"OTHER.example.app"};
    assert([CanonicalIdentifier(signedID) isEqual:signedID]);
    installedEntitlements=@{@"application-identifier":signedID}; installedBundle=@"other.app";
    assert([CanonicalIdentifier(signedID) isEqual:signedID]);
    installedBundle=@42; assert([CanonicalIdentifier(signedID) isEqual:signedID]);
    installedBundle=expectedCandidate; installedEntitlements=@[];
    assert([CanonicalIdentifier(signedID) isEqual:signedID]);
    installedEntitlements=nil; assert([CanonicalIdentifier(signedID) isEqual:signedID]);
    throws=YES; assert([CanonicalIdentifier(signedID) isEqual:signedID]); throws=NO;
    unavailable=YES; assert([CanonicalIdentifier(signedID) isEqual:signedID]); unavailable=NO;
    expectedCandidate=@"app"; installedBundle=@"app"; installedEntitlements=@{@"application-identifier":signedID};
    assert([CanonicalIdentifier(@"example.app") isEqual:@"example.app"]);
    puts("Background owner: exact signed identity, installed bundle agreement and native refusal passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-owner-") as directory:
    path = Path(directory)
    (path / "main.m").write_text(source)
    subprocess.run([os.environ.get("CC", "clang"), "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", str(path / "main.m"),
                    "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
