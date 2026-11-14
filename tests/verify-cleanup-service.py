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
static BOOL enabled, locked, rejectRefresh, noOpRefresh;
static NSDictionary *configuration;
static NSUInteger generation;
static NSString *CurrentVendor(void) { return [NSString stringWithFormat:@"11111111-1111-4111-8111-%012lu", (unsigned long)generation]; }
static NSString *failure;
static NSMutableArray *calls, *events;
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { static id s; if (!s) s=[self new]; return s; }
- (NSArray *)registeredBundleIdentifiers { return @[@"local.fixture.app"]; }
- (BOOL)enabledForApplication:(NSString *)identifier { return enabled; }
- (BOOL)lockedForApplication:(NSString *)identifier { return locked; }
- (BOOL)setLocked:(BOOL)value forApplication:(NSString *)identifier error:(NSError **)error { locked=value; [calls addObject:value ? @"lock" : @"unlock"]; return YES; }
- (NSDictionary *)profileForBundleIdentifier:(NSString *)identifier { return @{@"Generation":@(generation), @"VendorIdentifier":CurrentVendor()}; }
- (NSDictionary *)configurationForApplication:(NSString *)identifier { return configuration; }
- (BOOL)setConfiguration:(NSDictionary *)value forApplication:(NSString *)identifier error:(NSError **)error { assert(!"cleanup must preserve existing configuration"); return NO; }
- (BOOL)refreshApplication:(NSString *)identifier error:(NSError **)error { assert(!"cleanup must explicitly replace backed data"); return NO; }
- (BOOL)refreshApplication:(NSString *)identifier replaceBackedData:(BOOL)replaceBackedData error:(NSError **)error {
    assert(replaceBackedData); assert(enabled && !locked); [calls addObject:@"refresh"]; if(rejectRefresh) { *error=[NSError errorWithDomain:@"fixture" code:98 userInfo:@{NSLocalizedDescriptionKey:@"refresh failed"}]; return NO; } if(!noOpRefresh) generation++; locked=YES; return YES;
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
    NSDictionary *beforeConfig = [configuration copy];
    TestCleanup *service=[[TestCleanup alloc]initWithBundleIdentifier:@"local.fixture.app"];
    [service startWithSteps:selected progress:^(NSString *step,NSString *state,NSString *message) {
        assert(NSThread.isMainThread);[events addObject:[NSString stringWithFormat:@"%@:%@",step,state]];
    } completion:^(BOOL ok,NSError *error) {
        assert(NSThread.isMainThread && !service.running);assert(ok==success);assert([calls isEqual:expected]);
        if (success) assert([events.lastObject isEqual:@"recheck:completed"]);
        else assert(![events containsObject:@"recheck:completed"]);
        assert([configuration isEqual:beforeConfig]);
        if(assertions)assertions(error);Next();
    }];
}
static void Next(void) {
    enabled=YES;locked=NO;failure=nil;rejectRefresh=NO;noOpRefresh=NO;
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
    case 11: {
        // The backup prompt finishes before cleanup starts its selected stages.
        NSString *snapshot = [[@SHDW_FINGERPRINT_BACKUP_ROOT stringByAppendingPathComponent:@"local.fixture.app/snapshots"] stringByAppendingPathComponent:CurrentVendor()];
        assert([NSFileManager.defaultManager createDirectoryAtPath:snapshot withIntermediateDirectories:YES attributes:nil error:NULL]);
        NSDictionary *archivedData = [[SHDWFingerprintStore.sharedStore profileForBundleIdentifier:@"local.fixture.app"] copy];
        NSDictionary *archivedConfig = [configuration copy];
        Run(@[@"files",@"fingerprint"],@[@"inspect",@"prepare",@"files",@"refresh",@"finalize",@"recheck"],YES,^(NSError *e){
            assert(!e && generation==4 && locked);
            assert(![CurrentVendor() isEqual:archivedData[@"VendorIdentifier"]]);
            assert([archivedData[@"Generation"] unsignedIntegerValue]==3 && [configuration isEqual:archivedConfig]);
            assert([NSFileManager.defaultManager fileExistsAtPath:snapshot]);
        });break;
    }
    case 12: {
        locked=YES;
        NSString *snapshot = [[@SHDW_FINGERPRINT_BACKUP_ROOT stringByAppendingPathComponent:@"local.fixture.app/snapshots"] stringByAppendingPathComponent:CurrentVendor()];
        assert([NSFileManager.defaultManager createDirectoryAtPath:snapshot withIntermediateDirectories:YES attributes:nil error:NULL]);
        Run(@[@"files",@"fingerprint"],@[@"inspect",@"prepare",@"files",@"unlock",@"refresh",@"finalize",@"recheck"],YES,^(NSError *e){assert(!e && generation==5 && locked);});break;
    }
    case 13: {
        noOpRefresh=YES;
        NSString *snapshot = [[@SHDW_FINGERPRINT_BACKUP_ROOT stringByAppendingPathComponent:@"local.fixture.app/snapshots"] stringByAppendingPathComponent:CurrentVendor()];
        assert([NSFileManager.defaultManager createDirectoryAtPath:snapshot withIntermediateDirectories:YES attributes:nil error:NULL]);
        Run(@[@"fingerprint"],@[@"inspect",@"prepare",@"refresh",@"finalize",@"recheck"],NO,^(NSError *e){assert(e.code==9 && generation==5 && locked);});break;
    }
    case 14:
        noOpRefresh=YES;
        assert([NSFileManager.defaultManager removeItemAtPath:@SHDW_FINGERPRINT_BACKUP_ROOT error:NULL]);
        Run(@[@"fingerprint"],@[@"inspect",@"prepare",@"refresh",@"finalize",@"recheck"],NO,^(NSError *e){assert(e.code==9 && generation==5 && locked);});break;
    default:
        puts("cleanup service: ordered stages, automatic unlock/lock restoration, disabled preflight, optional refresh, backed replacement, configuration preservation and strict final recheck passed");exit(0);
    }
}
int main(void) { @autoreleasepool { configuration = @{@"Network":@{@"Transport":@"native"}, @"System":@{@"Mode":@"native"}, @"Localization":@{@"Region":@"US", @"Language":@"en", @"TimeZone":@"America/New_York"}}; dispatch_async(dispatch_get_main_queue(),^{ Next(); }); while (YES) [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]]; } }
'''
with tempfile.TemporaryDirectory(prefix="shadow-cleanup-service-") as temp:
    path = Path(temp)
    (path / "test.m").write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-framework", "Foundation",
                    "-DSHDW_FINGERPRINT_BACKUP_ROOT=\"" + str(path / "backups") + "\"",
                    "-Wno-incomplete-implementation", "-fsanitize=address,undefined", "-g",
                    "-I" + str(root / "src/Shadow.framework/Headers"),
                    "-I" + str(root / "src/Shadow.app"),
                    str(path / "test.m"), str(root / "src/Shadow.app/Services/CleanupService.m"),
                    str(root / "src/Shadow.app/Services/OperationCoordinator.m"),
                    str(root / "src/Shadow.app/Services/OwnershipDiagnostics.m"),
                    "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True, timeout=40)
