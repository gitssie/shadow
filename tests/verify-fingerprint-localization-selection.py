#!/usr/bin/env python3
"""Execute the Manager's actual picker setup and save callbacks on Foundation."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
ROOT = Path(__file__).resolve().parents[1]
ui = (ROOT / "src/Shadow.app/Screens/Fingerprint/FingerprintDetailViewController.m").read_text()

def method(signature):
    start = ui.rindex(signature)
    opening = ui.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (ui[end] == "{") - (ui[end] == "}")
        end += 1
    return ui[start:end]

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Shadow/FingerprintConfiguration.h>
#include <assert.h>
static NSString *SHDWText(NSString *value) { return value; }
static void SHDWShowError(id controller, NSError *error) { (void)controller; (void)error; }
enum { UITableViewStyleInsetGrouped = 2 };
@interface NSIndexPath (Fixture)
@property(nonatomic, readonly) NSInteger row;
@property(nonatomic, readonly) NSInteger section;
@end
@implementation NSIndexPath (Fixture)
- (NSInteger)row { return [self indexAtPosition:1]; }
- (NSInteger)section { return [self indexAtPosition:0]; }
@end
@interface UITableView : NSObject
- (void)deselectRowAtIndexPath:(NSIndexPath *)path animated:(BOOL)animated;
- (void)reloadData;
@end
@implementation UITableView
- (void)deselectRowAtIndexPath:(NSIndexPath *)path animated:(BOOL)animated { (void)path; (void)animated; }
- (void)reloadData {}
@end
@interface UIDevice : NSObject
+ (instancetype)currentDevice;
@property(nonatomic, readonly) NSString *systemVersion;
@end
@implementation UIDevice
+ (instancetype)currentDevice { static UIDevice *device; if (!device) device = [UIDevice new]; return device; }
- (NSString *)systemVersion { return @"18.0"; }
@end
@interface SHDWConfigurationSelectionController : NSObject
@property(nonatomic, copy) NSArray<NSDictionary *> *options;
@property(nonatomic, strong) NSMutableSet<NSString *> *selection;
@property(nonatomic) BOOL multiple;
@property(nonatomic) BOOL searchable;
@property(nonatomic, copy) NSString *title;
@property(nonatomic, copy) BOOL (^saveSelection)(NSSet<NSString *> *selection);
- (instancetype)initWithStyle:(NSInteger)style;
@end
@implementation SHDWConfigurationSelectionController
- (instancetype)initWithStyle:(NSInteger)style { (void)style; return [super init]; }
@end
@interface FixtureNavigation : NSObject
@property(nonatomic, strong) SHDWConfigurationSelectionController *topViewController;
@property(nonatomic) NSUInteger pushes;
- (void)pushViewController:(SHDWConfigurationSelectionController *)controller animated:(BOOL)animated;
@end
@implementation FixtureNavigation
- (void)pushViewController:(SHDWConfigurationSelectionController *)controller animated:(BOOL)animated {
    (void)animated; self.topViewController = controller; self.pushes++;
}
@end
@interface SHDWFingerprintStore : NSObject
@property(nonatomic, copy) NSDictionary *configuration;
@property(nonatomic) BOOL locked;
@property(nonatomic) NSUInteger writes;
+ (instancetype)sharedStore;
- (NSDictionary *)configurationForApplication:(NSString *)identifier;
- (BOOL)lockedForApplication:(NSString *)identifier;
- (BOOL)setConfiguration:(NSDictionary *)configuration forApplication:(NSString *)identifier error:(NSError **)error;
@end
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { static SHDWFingerprintStore *store; if (!store) store = [SHDWFingerprintStore new]; return store; }
- (NSDictionary *)configurationForApplication:(NSString *)identifier { assert([identifier isEqual:@"fixture.app"]); return self.configuration; }
- (BOOL)lockedForApplication:(NSString *)identifier { assert([identifier isEqual:@"fixture.app"]); return self.locked; }
- (BOOL)setConfiguration:(NSDictionary *)configuration forApplication:(NSString *)identifier error:(NSError **)error {
    assert([identifier isEqual:@"fixture.app"]); (void)error;
    if (self.locked) return NO;
    NSDictionary *valid = [SHDWFingerprintConfiguration configurationByValidating:configuration error:nil];
    assert(valid); self.configuration = valid; self.writes++; return YES;
}
@end
@interface SHDWFingerprintDetailViewController : NSObject
@property(nonatomic, copy) NSString *bundleIdentifier;
@property(nonatomic, strong) FixtureNavigation *navigationController;
@property(nonatomic, strong) UITableView *tableView;
- (BOOL)saveConfiguration:(NSDictionary *)configuration;
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)path;
@end
@implementation SHDWFingerprintDetailViewController
''' + method("- (BOOL)saveConfiguration:") + "\n" + method("- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:") + r'''
@end
static SHDWConfigurationSelectionController *Open(SHDWFingerprintDetailViewController *detail, NSUInteger row) {
    NSUInteger indexes[] = {0, row};
    NSUInteger pushes = detail.navigationController.pushes;
    NSUInteger writes = SHDWFingerprintStore.sharedStore.writes;
    [detail tableView:detail.tableView didSelectRowAtIndexPath:[NSIndexPath indexPathWithIndexes:indexes length:2]];
    assert(SHDWFingerprintStore.sharedStore.writes == writes);
    return detail.navigationController.pushes == pushes ? nil : detail.navigationController.topViewController;
}
static void AssertPreserved(NSDictionary *before, NSDictionary *after) {
    for (NSString *key in before) if (![key isEqual:@"Localization"])
        assert([before[key] isEqual:after[key]]);
}
int main(void) { @autoreleasepool {
    SHDWFingerprintStore *store = SHDWFingerprintStore.sharedStore;
    store.configuration = SHDWFingerprintConfiguration.defaultConfiguration;
    SHDWFingerprintDetailViewController *detail = [SHDWFingerprintDetailViewController new];
    detail.bundleIdentifier = @"fixture.app"; detail.navigationController = [FixtureNavigation new]; detail.tableView = [UITableView new];
    SHDWConfigurationSelectionController *region = Open(detail, 1);
    assert(region && !region.searchable && !region.multiple && store.writes == 0);
    assert([[region.options valueForKey:@"ID"] isEqual:(@[@"native", @"FR", @"GB", @"US"])]);
    assert([region.selection isEqual:[NSSet setWithObject:@"native"]]);
    // Concurrent store edits after opening must survive the real save callback.
    NSMutableDictionary *latest = [store.configuration mutableCopy];
    latest[@"Network"] = @{@"RadioTechnologies":@[@"4g"]};
    latest[@"Advertising"] = @{@"Mode":@"zero"};
    latest[@"Receipts"] = @{@"InterceptEnabled":@NO};
    store.configuration = latest;
    NSDictionary *before = store.configuration;
    assert(region.saveSelection([NSSet setWithObject:@"GB"]) && store.writes == 1);
    assert([store.configuration[@"Localization"] isEqual:([SHDWFingerprintConfiguration localizationForRegion:@"GB"])]);
    AssertPreserved(before, store.configuration);
    SHDWConfigurationSelectionController *language = Open(detail, 3);
    assert(language && !language.searchable && !language.multiple && store.writes == 1);
    assert([[language.options valueForKey:@"ID"] isEqual:(@[@"native", @"fr-FR", @"en-GB", @"en-US"])]);
    assert([language.selection isEqual:[NSSet setWithObject:@"en-GB"]]);
    latest = [store.configuration mutableCopy];
    latest[@"Network"] = @{@"RadioTechnologies":@[@"5g"]};
    latest[@"Advertising"] = @{@"Mode":@"system"};
    latest[@"Receipts"] = @{@"InterceptEnabled":@YES};
    store.configuration = latest; before = store.configuration;
    assert(language.saveSelection([NSSet setWithObject:@"fr-FR"]) && store.writes == 2);
    assert([store.configuration[@"Localization"] isEqual:([SHDWFingerprintConfiguration localizationForRegion:@"FR"])]);
    AssertPreserved(before, store.configuration);
    assert(!language.saveSelection([NSSet setWithObject:@"en"]) && store.writes == 2);
    before = store.configuration;
    assert(language.saveSelection([NSSet setWithObject:@"native"]) && store.writes == 3);
    assert([store.configuration[@"Localization"] isEqual:([SHDWFingerprintConfiguration localizationForRegion:@"native"])]);
    AssertPreserved(before, store.configuration);
    region = Open(detail, 1);
    assert(region.saveSelection([NSSet setWithObject:@"US"]) && store.writes == 4);
    assert(region.saveSelection([NSSet setWithObject:@"native"]) && store.writes == 5);
    assert([store.configuration[@"Localization"] isEqual:([SHDWFingerprintConfiguration localizationForRegion:@"native"])]);
    assert(!Open(detail, 2) && store.writes == 5);
    store.locked = YES;
    assert(!Open(detail, 1) && !Open(detail, 3) && store.writes == 5);
    // A picker opened before locking must also respect the store's save lock.
    assert(!region.saveSelection([NSSet setWithObject:@"FR"]) && store.writes == 5);
    puts("Manager localization selection: real picker catalogs/callbacks, linked triplets, latest-state preservation, native reset, lock and readonly timezone passed");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-localization-selection-") as directory:
    temporary = Path(directory)
    source, binary = temporary / "test.m", temporary / "test"
    source.write_text(HARNESS)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-framework", "Foundation",
                    "-I", str(ROOT / "src/Shadow.framework/Headers"), str(source),
                    str(ROOT / "src/Shadow.framework/Fingerprint/Configuration.m"), "-o", str(binary)], check=True)
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
    subprocess.run([str(binary)], check=True, env=environment)
