#!/usr/bin/env python3
"""Execute backup reload/selection methods with Foundation service/view doubles."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import runpy

ROOT = Path(__file__).resolve().parents[1]
pagination = runpy.run_path(str(ROOT / "tests/verify-backup-pagination.py"))
source = (ROOT / "src/Shadow.app/Screens/Backup/BackupViewController.m").read_text()
home = (ROOT / "src/Shadow.app/Screens/Home/HomeViewController.m").read_text()
constants = "\n".join(re.findall(r'^static NSString \*const \w*ApplicationKey = .*?;', source, re.M))
home_key = re.search(r'SHDWSelectedApplicationKey = (@"[^"]+")', home)[1]
prelude = pagination["PRELUDE"]
prelude = prelude.replace('@interface UIView : NSObject', '''@interface UIView : NSObject
- (void)showApplication:(id)application fingerprint:(id)fingerprint;
- (void)showApplications:(id)applications selected:(id)selected;''')
prelude = prelude.replace('@implementation UIView', '''@implementation UIView
- (void)showApplication:(id)application fingerprint:(id)fingerprint { (void)application; (void)fingerprint; }
- (void)showApplications:(id)applications selected:(id)selected { (void)applications; (void)selected; }''')
prelude = prelude.replace('@interface Controller : NSObject', r'''
#define SHDWInstalledApplication UIView
static NSArray *installed;
static NSArray *registered;
static BOOL running;
@interface SHDWInstalledApplications : NSObject
+ (NSArray *)applications;
@end
@implementation SHDWInstalledApplications
+ (NSArray *)applications { return installed; }
@end
@interface SHDWFingerprintStore : NSObject
+ (instancetype)sharedStore;
- (NSArray *)registeredBundleIdentifiers;
- (id)deviceFingerprintForApplication:(NSString *)identifier;
@end
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { static id store; if (!store) store=[self new]; return store; }
- (NSArray *)registeredBundleIdentifiers { return registered; }
- (id)deviceFingerprintForApplication:(NSString *)identifier { return identifier; }
@end
#define SHDWBackupService Service
@interface Service (Selection)
- (instancetype)initWithBundleIdentifier:(NSString *)identifier;
@end
@implementation Service (Selection)
- (instancetype)initWithBundleIdentifier:(NSString *)identifier {
    if ((self=[self init])) self.search=identifier;
    return self;
}
@end
@interface Controller : NSObject
@property(copy) NSArray *applications;
- (void)showSelection;
''')
prelude = prelude.replace('+ (BOOL)isRunning { return NO; }', '+ (BOOL)isRunning { extern BOOL SelectionRunning(void); return SelectionRunning(); }')
prelude = prelude.replace('- (void)reloadApplications { NSCAssert(NO,@"unexpected application reload"); }', '- (void)loadCatalog {}')
prelude = re.sub(r'^- \(void\)(toggleDateOrder|toggleRegion|loadMore|loadMoreIfNeeded|scrollViewDidScroll:|scrollViewWillBeginDragging:|loadPage:|updateControls|perform:).*?;\n|^- \(NSDictionary \*\)currentSnapshot;\n', '', prelude, flags=re.M)
prelude = re.sub(r'^static .*?(UIAccessibilityPostNotification|SHDWText|SHDWAccent|CanonicalIDFV|ProgressTitle)\(.*?\n', '', prelude, flags=re.M)
code = '#import <Foundation/Foundation.h>\n' + constants + '\n' + prelude
code = code.replace('@implementation Controller', r'''static NSUserDefaults *testDefaults;
@interface SelectionDefaults : NSObject
+ (NSUserDefaults *)standardUserDefaults;
@end
@implementation SelectionDefaults
+ (NSUserDefaults *)standardUserDefaults { return testDefaults; }
@end
#define NSUserDefaults SelectionDefaults
@implementation Controller''')
code += pagination["method"](source, '- (void)reloadApplications {')
code += '\n' + pagination["method"](source, '- (void)showSelection {')
code += r'''
@end
@interface HomeController : Controller
@property BOOL busy, isViewLoaded;
@property(copy) NSArray *registered;
- (void)renderSelection;
- (void)activityChanged;
@end
@implementation HomeController
- (void)renderSelection {
    if (self.selected) [NSUserDefaults.standardUserDefaults setObject:self.selected.bundleIdentifier forKey:SHDWSelectedApplicationKey];
}
'''.replace('SHDWSelectedApplicationKey', 'SelectedApplicationKey')
code += pagination["method"](home, '- (void)reloadApplications {').replace('SHDWSelectedApplicationKey', 'SelectedApplicationKey')
code += '\n' + pagination["method"](home, '- (void)activityChanged {')
code += r'''
@end
#undef NSUserDefaults
BOOL SelectionRunning(void) { return running; }
static void Check(BOOL condition, NSString *message) { if (!condition) { fprintf(stderr,"FAIL: %s\n",message.UTF8String); exit(1); } }
static UIView *App(NSString *identifier) { UIView *app=[UIView new]; app.bundleIdentifier=identifier; return app; }
static Controller *NewController(void) {
    Controller *c=[Controller new]; c.selector=[UIView new]; c.table=[UIView new]; return c;
}
int main(void) { @autoreleasepool {
    NSString *suite=[@"shadow-backup-selection-" stringByAppendingString:NSUUID.UUID.UUIDString];
    testDefaults=[[NSUserDefaults alloc] initWithSuiteName:suite];
    NSUserDefaults *defaults=testDefaults;
    NSString *homeKey=HOME_KEY;
    UIView *first=App(@"home.app"), *second=App(@"backup.app"), *other=App(@"other.app");
    installed=@[other,first,second]; registered=@[@"home.app",@"backup.app",@"other.app"];
    [defaults setObject:first.bundleIdentifier forKey:homeKey];
    HomeController *h=[HomeController new]; h.isViewLoaded=YES; [h reloadApplications];
    Controller *c=NewController(); [c reloadApplications];
    Check(c.selected==first && h.selected==first,@"pages start with the shared choice");
    c.selected=second; [c showSelection];
    Check([[defaults stringForKey:homeKey] isEqual:second.bundleIdentifier],@"backup selection becomes the shared choice");
    running=YES; [h activityChanged];
    Check(h.selected==second && [[defaults stringForKey:homeKey] isEqual:second.bundleIdentifier],@"operation notification must synchronize stale home selection instead of overwriting the latest choice");
    running=NO; [c reloadApplications];
    Check(c.selected==second && [c.service.search isEqual:second.bundleIdentifier],@"post-operation backup refresh retains the latest shared target");
    h.selected=first; [h renderSelection]; [c reloadApplications];
    Check(c.selected==first && [c.service.search isEqual:first.bundleIdentifier],@"home choice updates backup target and service");
    c.selected=second; [c showSelection]; [h activityChanged];
    Check(h.selected==second,@"backup choice updates home in the reverse direction");
    Controller *reopened=NewController(); [reopened reloadApplications];
    Check(reopened.selected==second,@"recreated controller follows the latest shared choice");
    c.working=YES; [c reloadApplications];
    Check(c.reloadPending && c.selected==second,@"reload defers during backup operation");
    c.working=NO; c.loading=YES; [c reloadApplications];
    Check(c.reloadPending && c.selected==second,@"reload defers during catalog query");
    c.loading=NO; running=YES; [c reloadApplications];
    Check(c.reloadPending && c.selected==second,@"reload defers during restore operation");
    running=NO; [c reloadApplications];
    Check(!c.reloadPending && c.selected==second,@"deferred reload uses latest shared choice");
    installed=@[other,first]; [c reloadApplications]; [h activityChanged];
    Check(c.selected==other && h.selected==other,@"removed app fallback is shared by both pages");
    installed=@[]; [c reloadApplications];
    Check(!c.selected && !c.service,@"empty application list clears target and service");
    [defaults removePersistentDomainForName:suite];
    puts("backup selection: latest shared choice, stale home operation notification, bidirectional reload, recreation and deferred restore checks passed");
} return 0; }
'''.replace('HOME_KEY', home_key)
with tempfile.TemporaryDirectory(prefix="shadow-backup-selection-") as directory:
    temp = Path(directory)
    (temp / "main.m").write_text(code)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-framework", "CoreGraphics",
                    "-I" + str(ROOT / "src/Shadow.app"), str(temp / "main.m"), "-o", str(temp / "check")], check=True)
    subprocess.run([str(temp / "check")], env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1"), check=True, timeout=30)
