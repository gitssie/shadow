"""Check real cleanup orchestration without touching installed applications."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = r'''
#import <Foundation/Foundation.h>
#import <Shadow/Fingerprint.h>
#import "Services/CleanupService.h"
#include <assert.h>
NSString *SHDWLocalizedText(NSString *value) { return value; }
NSString *JBPath(NSString *value) { return value; }
static BOOL enabled, locked, rejectRefresh;
static NSUInteger generation;
static NSString *failure;
static NSMutableArray *calls, *events;
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { static id s; if (!s) s=[self new]; return s; }
- (NSArray *)registeredBundleIdentifiers { return @[@"local.fixture.app"]; }
- (BOOL)enabledForApplication:(NSString *)identifier { return enabled; }
- (BOOL)lockedForApplication:(NSString *)identifier { return locked; }
- (BOOL)setLocked:(BOOL)value forApplication:(NSString *)identifier error:(NSError **)error { locked=value; [calls addObject:value ? @"lock" : @"unlock"]; return YES; }
- (NSDictionary *)profileForBundleIdentifier:(NSString *)identifier { return @{@"Generation":@(generation)}; }
- (BOOL)refreshApplication:(NSString *)identifier error:(NSError **)error {
    assert(enabled && !locked); [calls addObject:@"refresh"]; if(rejectRefresh) { *error=[NSError errorWithDomain:@"fixture" code:98 userInfo:@{NSLocalizedDescriptionKey:@"refresh failed"}]; return NO; } generation++; locked=YES; return YES;
}
@end
@interface SHDWCleanupService (TestSeam)
- (NSDictionary *)invokeHelper:(NSArray *)arguments error:(NSError **)error;
@end
@interface TestCleanup : SHDWCleanupService @end
@implementation TestCleanup
- (NSDictionary *)invokeHelper:(NSArray *)arguments error:(NSError **)error {
    NSString *command=arguments[0];
    NSString *call=[command isEqual:@"run"] ? arguments[3] : command;
    [calls addObject:call];
    if ([failure isEqual:call]) {
        *error=[NSError errorWithDomain:@"fixture" code:99 userInfo:@{NSLocalizedDescriptionKey:@"fixture failure",@"stateMayBePartial":@NO}];return nil;
    }
    if ([command isEqual:@"prepare"] || [command isEqual:@"finalize"] || [command isEqual:@"recheck"]) assert([arguments[2] isEqual:@"stable-token"]);
    return @{@"ok":@YES,@"token":@"stable-token",@"recheckVerified":@YES};
}
@end
static NSUInteger test;
static void Next(void);
static void Run(NSArray *selected, NSArray *expected, BOOL success, void (^assertions)(NSError *)) {
    calls=[NSMutableArray new];events=[NSMutableArray new];
    TestCleanup *service=[[TestCleanup alloc]initWithBundleIdentifier:@"local.fixture.app"];
    [service startWithSteps:selected progress:^(NSString *step,NSString *state,NSString *message) {
        assert(NSThread.isMainThread);[events addObject:[NSString stringWithFormat:@"%@:%@",step,state]];
    } completion:^(BOOL ok,NSError *error) {
        assert(NSThread.isMainThread && !service.running);assert(ok==success);assert([calls isEqual:expected]);
        if (success) assert([events.lastObject isEqual:@"recheck:completed"]);
        else assert(![events containsObject:@"recheck:completed"]);
        if(assertions)assertions(error);Next();
    }];
}
static void Next(void) {
    enabled=YES;locked=NO;failure=nil;rejectRefresh=NO;
    switch(test++) {
    case 0:
        Run(@[@"fingerprint",@"receipts",@"keychain",@"web",@"preferences",@"files"],
            @[@"inspect",@"prepare",@"files",@"preferences",@"web",@"keychain",@"receipts",@"refresh",@"finalize",@"recheck"],YES,^(NSError *e){assert(!e&&generation==1&&locked);});break;
    case 1:
        locked=YES;
        Run(@[@"files",@"fingerprint"],@[@"inspect",@"prepare",@"files",@"unlock",@"refresh",@"finalize",@"recheck"],YES,^(NSError *e){assert(!e&&generation==2&&locked);});break;
    case 2:
        enabled=NO;
        Run(@[@"fingerprint"],@[],NO,^(NSError *e){assert(e.code==4&&generation==2);});break;
    case 3:
        locked=YES;
        Run(@[@"receipts",@"files"],@[@"inspect",@"prepare",@"files",@"receipts",@"finalize",@"recheck"],YES,^(NSError *e){assert(!e&&generation==2&&locked);assert([events containsObject:@"fingerprint:skipped"]);});break;
    case 4:
        failure=@"web";
        Run(@[@"files",@"web",@"keychain",@"fingerprint"],@[@"inspect",@"prepare",@"files",@"web"],NO,^(NSError *e){assert([e.userInfo[@"stateMayBePartial"]boolValue]&&generation==2);assert([events.lastObject isEqual:@"web:failed"]);});break;
    case 5:
        failure=@"recheck";
        Run(@[@"files"],@[@"inspect",@"prepare",@"files",@"finalize",@"recheck"],NO,^(NSError *e){assert([events.lastObject isEqual:@"recheck:failed"]&&[e.userInfo[@"stateMayBePartial"]boolValue]);});break;
    case 6:
        Run(@[@"fingerprint"],@[@"inspect",@"prepare",@"refresh",@"finalize",@"recheck"],YES,^(NSError *e){assert(generation==3&&locked);});break;
    case 7:
        Run(@[@"files",@"files"],@[],NO,^(NSError *e){assert(e.code==2);});break;
    case 8:
        failure=@"prepare";
        Run(@[@"files",@"keychain"],@[@"inspect",@"prepare"],NO,^(NSError *e){assert(![e.userInfo[@"stateMayBePartial"]boolValue]);});break;
    case 9:
        locked=YES;rejectRefresh=YES;
        Run(@[@"fingerprint"],@[@"inspect",@"prepare",@"unlock",@"refresh",@"lock"],NO,^(NSError *e){assert(locked&&generation==3&&e.code==98);});break;
    case 10:
        failure=@"finalize";
        Run(@[@"files"],@[@"inspect",@"prepare",@"files",@"finalize"],NO,^(NSError *e){assert([events.lastObject isEqual:@"recheck:failed"]&&[e.userInfo[@"stateMayBePartial"]boolValue]);});break;
    default:
        puts("cleanup service: ordered stages, automatic unlock/lock restoration, disabled preflight, optional refresh, fail-stop and mandatory final recheck passed");exit(0);
    }
}
int main(void) { @autoreleasepool { dispatch_async(dispatch_get_main_queue(),^{ Next(); }); while (YES) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]]; } }
'''
with tempfile.TemporaryDirectory(prefix="shadow-cleanup-service-") as temp:
    path = Path(temp)
    (path / "test.m").write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-framework", "Foundation",
                    "-Wno-incomplete-implementation", "-fsanitize=address,undefined", "-g",
                    "-I" + str(root / "src/Shadow.framework/Headers"),
                    "-I" + str(root / "src/Shadow.app"),
                    str(path / "test.m"), str(root / "src/Shadow.app/Services/CleanupService.m"),
                    str(root / "src/Shadow.app/Services/OperationCoordinator.m"),
                    str(root / "src/Shadow.app/Services/OwnershipDiagnostics.m"),
                    "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True, timeout=40)
