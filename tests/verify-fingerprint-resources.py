#!/usr/bin/env python3
"""Run production Bundle adapters with real localized bundles and warm caches."""
from pathlib import Path
import os
import plistlib
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
hook = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintResources.x").read_text()
hook = "\n".join(line for line in hook.splitlines() if not line.startswith("#import"))
source = r'''
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <assert.h>
static unsigned depth;
@interface Shadow : NSObject
+ (BOOL)shdwIsInternalRead;
@end
@implementation Shadow
+ (BOOL)shdwIsInternalRead { return depth != 0; }
@end
static void Leave(BOOL *active) { (void)active; depth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(Leave))) = (++depth, YES); active; active = NO)
@interface SHDWHookSession : NSObject
@property NSUInteger rebinds;
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original;
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)original;
@end
@implementation SHDWHookSession
- (BOOL)hookMessageInClass:(Class)cls withSelector:(SEL)selector withReplacement:(void *)replacement outOldPtr:(void **)original {
    Method method = class_getInstanceMethod(cls, selector); assert(method);
    *original = (void *)method_getImplementation(method);
    if(!class_addMethod(cls, selector, (IMP)replacement, method_getTypeEncoding(method)))
        method_setImplementation(class_getInstanceMethod(cls, selector), (IMP)replacement);
    return YES;
}
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)original {
    (void)name; (void)replacement; assert(!original); self.rebinds++; return YES;
}
@end
''' + hook + r'''
int main(int argc, const char *argv[]) { @autoreleasepool {
    assert(argc == 2);
    NSBundle *bundle = [NSBundle bundleWithPath:[@(argv[1]) stringByAppendingPathComponent:@"Mixed.bundle"]];
    NSBundle *fallback = [NSBundle bundleWithPath:[@(argv[1]) stringByAppendingPathComponent:@"Fallback.bundle"]];
    assert(bundle && fallback);
    NSString *nativeString = [bundle localizedStringForKey:@"greeting" value:nil table:nil];
    NSArray *nativePreferred = bundle.preferredLocalizations;
    (void)[bundle pathForResource:@"marker" ofType:@"txt"];
    SHDWHookSession *hooks = [SHDWHookSession new];
    assert(!shdw_sym_policy_lookup_resources("CFBundleCopyLocalizedString"));
    shdw_universal_fingerprint_resources(hooks, @{@"OverridesSystem":@NO});
    assert(!hooks.rebinds && [bundle.preferredLocalizations isEqual:nativePreferred]);
    shdw_universal_fingerprint_resources(hooks, @{@"OverridesSystem":@YES,@"Languages":@[@"fr-FR"]});
    assert(hooks.rebinds == 7);
    shdw_universal_fingerprint_resources(hooks, @{@"OverridesSystem":@YES,@"Languages":@[@"en-US"]});
    assert(hooks.rebinds == 7);
    assert([bundle.preferredLocalizations.firstObject isEqual:@"fr"]);
    assert([[bundle localizedStringForKey:@"greeting" value:nil table:nil] isEqual:@"Bonjour"]);
    assert([[bundle localizedStringForKey:@"greeting" value:nil table:@"Root"] isEqual:@"Root Value"]);
    assert([[bundle localizedStringForKey:@"missing" value:@"fallback-value" table:nil] isEqual:@"fallback-value"]);
    assert([[fallback localizedStringForKey:@"greeting" value:nil table:nil] isEqual:@"Hello"]);
    assert([fallback.preferredLocalizations.firstObject isEqual:@"en"]);
    NSBundle *germanFallback = [NSBundle bundleWithPath:[@(argv[1]) stringByAppendingPathComponent:@"GermanFallback.bundle"]];
    assert([germanFallback.preferredLocalizations.firstObject isEqual:@"de"]);
    assert([[germanFallback localizedStringForKey:@"greeting" value:nil table:nil] isEqual:@"Hallo"]);
    NSArray *choices = @[@"en",@"fr"];
    assert([[NSBundle preferredLocalizationsFromArray:choices].firstObject isEqual:@"fr"]);
    assert([[NSBundle preferredLocalizationsFromArray:choices forPreferences:nil].firstObject isEqual:@"fr"]);
    assert([[NSBundle preferredLocalizationsFromArray:choices forPreferences:@[@"en"]].firstObject isEqual:@"en"]);
    NSString *path = [bundle pathForResource:@"marker" ofType:@"txt"];
    assert([path containsString:@"fr.lproj"]);
    assert([[[bundle URLForResource:@"marker" withExtension:@"txt"] path] containsString:@"fr.lproj"]);
    assert([[bundle pathForResource:@"marker" ofType:@"txt" inDirectory:nil forLocalization:@"en"] containsString:@"en.lproj"]);
    assert([[[bundle URLForResource:@"marker" withExtension:@"txt" subdirectory:nil localization:@"en"] path] containsString:@"en.lproj"]);
    CFBundleRef cf = CFBundleCreate(NULL, (__bridge CFURLRef)bundle.bundleURL);
    CFStringRef text = shdw_resource_cfString(cf, CFSTR("greeting"), NULL, NULL);
    assert(CFEqual(text, CFSTR("Bonjour"))); CFRelease(text);
    CFURLRef resource = shdw_resource_cfURL(cf, CFSTR("marker"), CFSTR("txt"), NULL);
    assert([[(__bridge NSURL *)resource path] containsString:@"fr.lproj"]); CFRelease(resource);
    resource = shdw_resource_cfLocalizedURL(cf, CFSTR("marker"), CFSTR("txt"), NULL, CFSTR("en"));
    assert([[(__bridge NSURL *)resource path] containsString:@"en.lproj"]); CFRelease(resource);
    CFArrayRef resources = shdw_resource_cfURLs(cf, CFSTR("txt"), NULL);
    assert(CFArrayGetCount(resources) == 1 && [[[(NSArray *)CFBridgingRelease(resources) firstObject] path] containsString:@"fr.lproj"]);
    text = shdw_resource_cfString(cf, CFSTR("greeting"), NULL, CFSTR("Root"));
    assert(CFEqual(text, CFSTR("Root Value"))); CFRelease(text);
    CFRelease(cf);
    CFArrayRef selected = shdw_resource_cfPreferred((__bridge CFArrayRef)choices);
    assert([[(__bridge NSArray *)selected firstObject] isEqual:@"fr"]); CFRelease(selected);
    selected = shdw_resource_cfPreferences((__bridge CFArrayRef)choices, (__bridge CFArrayRef)@[@"en"]);
    assert([[(__bridge NSArray *)selected firstObject] isEqual:@"en"]); CFRelease(selected);
    depth++;
    assert([[bundle localizedStringForKey:@"greeting" value:nil table:nil] isEqual:nativeString]);
    assert([bundle.preferredLocalizations isEqual:nativePreferred]);
    depth--;
    assert(!depth && !shdw_sym_policy_lookup_resources("unrelated"));
    puts("Bundle localization: real resources, warm caches, default/explicit matching, development fallback, CF ownership and internal reads passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-resources-") as directory:
    temporary = Path(directory)
    for name, languages in [("Mixed", ["en", "fr"]), ("Fallback", ["de", "en"]), ("GermanFallback", ["en", "de"])]:
        bundle = temporary / (name + ".bundle")
        bundle.mkdir()
        (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "fixture." + name,
            "CFBundleDevelopmentRegion": "de" if name == "GermanFallback" else "en", "CFBundleLocalizations": languages}))
        (bundle / "Root.strings").write_text('"greeting" = "Root Value";')
        for language in languages:
            folder = bundle / (language + ".lproj")
            folder.mkdir()
            text = {"en": "Hello", "fr": "Bonjour", "de": "Hallo"}[language]
            (folder / "Localizable.strings").write_text('"greeting" = "' + text + '";')
            (folder / "marker.txt").write_text(language)
    test, binary = temporary / "test.m", temporary / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
        str(test), "-o", str(binary)], check=True)
    subprocess.run([str(binary), str(temporary)], check=True,
        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1"))
