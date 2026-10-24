#!/usr/bin/env python3
"""Run real backup IPC/coordinator with an isolated, unprivileged helper double."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = r'''#!/usr/bin/python3
import base64
import datetime
import json
import os
import plistlib
import sys
import time

scenario = os.path.basename(__file__).removeprefix("fixture-")
assert len(sys.argv) == 5 and sys.argv[1] == "state"
assert sys.argv[2] == "local.fixture.app"
request = plistlib.loads(base64.b64decode(sys.argv[4], validate=True))
assert isinstance(request, dict)
if request:
    assert request["nested"]["unicode"] == "中文 🗃"
    assert request["binary"] == b"\x00\xff\x01\x00"
    assert request["expectedAction"] == sys.argv[3]

def emit(value):
    os.write(1, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")

def payload(value):
    return base64.b64encode(plistlib.dumps(value, fmt=plistlib.FMT_BINARY)).decode()

result = ({"fixture": scenario, "request": request, "verified": True}
          if sys.argv[3] != "catalog" else
          [{"idfv": "11111111-1111-4111-8111-111111111111", "title": "Fixture", "note": "中文", "date": datetime.datetime(2020, 1, 2)}])
terminal = {"ok": True, "result": payload(result)}
if scenario == "malformed":
    os.write(1, b"{bad json}\n")
elif scenario == "truncated":
    os.write(1, b'{"ok":true,"result":"')
elif scenario == "missing":
    emit({"event": "progress", "progress": {"phase": "backup", "bytes": 1}})
elif scenario == "failure":
    emit({"ok": False, "error": "fixture rejected operation", "partial": True})
elif scenario == "invalid-base64":
    emit({"ok": True, "result": "!not-base64!"})
elif scenario == "invalid-plist":
    emit({"ok": True, "result": base64.b64encode(b"not a plist").decode()})
elif scenario == "wrong-catalog":
    emit({"ok": True, "result": payload({"wrong": "dictionary"})})
elif scenario == "numeric-ok":
    emit({"ok": 1, "result": payload(result)})
elif scenario == "bad-progress":
    emit({"event": "progress", "progress": ["wrong type"]})
elif scenario == "too-many-progress-keys":
    emit({"event": "progress", "progress": {str(i): i for i in range(17)}})
elif scenario == "oversized":
    os.write(1, b'{"event":"progress","progress":{"padding":"' + b"x" * (8 * 1024 * 1024 + 1))
elif scenario == "timeout":
    emit({"event": "progress", "progress": {"phase": "backup", "bytes": 1}})
    time.sleep(10)
elif scenario == "split":
    encoded = json.dumps({"event": "progress", "progress": {"phase": "backup", "bytes": 17, "message": "中文 🗃"}}, ensure_ascii=False).encode() + b"\n"
    for index in range(0, len(encoded), 3):
        os.write(1, encoded[index:index + 3])
        time.sleep(0.001)
    emit(terminal)
elif scenario == "stream":
    for index in range(4096):
        emit({"event": "progress", "progress": {"phase": "backup", "bytes": index + 1, "padding": "x" * 4096}})
    emit(terminal)
elif scenario == "duplicate":
    emit(terminal)
    emit(terminal)
elif scenario == "after-result":
    emit(terminal)
    emit({"event": "progress", "progress": {"bytes": 99}})
elif scenario == "bad-exit":
    emit(terminal)
    sys.exit(7)
elif scenario == "hold":
    emit({"event": "progress", "progress": {"phase": "backup", "bytes": 1}})
    time.sleep(0.3)
    emit(terminal)
else:
    emit(terminal)
'''

HARNESS = r'''
#import <Foundation/Foundation.h>
#import <Shadow/Fingerprint.h>
#import "Services/BackupService.h"
#import "Services/CleanupService.h"
#import "Services/OperationCoordinator.h"
#import "Services/BackupPolicy.h"
#include <sys/wait.h>
#include <errno.h>
#include <unistd.h>

static NSString *fixtures;
static NSUInteger completedCases,notifications;
static void Check(BOOL value, NSString *message) { if (!value) { fprintf(stderr,"FAIL: %s\n",message.UTF8String); exit(1); } }
NSString *SHDWLocalizedText(NSString *value) { return value; }
NSString *JBPath(NSString *value) { return value; }
@implementation SHDWFingerprintStore
+ (instancetype)sharedStore { static id value; if (!value) value=[self new]; return value; }
- (NSArray *)registeredBundleIdentifiers { return @[@"local.fixture.app"]; }
- (NSDictionary *)profileForBundleIdentifier:(NSString *)identifier { (void)identifier; return @{@"Generation":@1}; }
- (BOOL)enabledForApplication:(NSString *)identifier { (void)identifier; return YES; }
- (BOOL)lockedForApplication:(NSString *)identifier { (void)identifier; return YES; }
@end
@interface SHDWBackupService (FixtureSeam)
- (NSString *)helperPath;
- (BOOL)validateHelperAtPath:(NSString *)path error:(NSError **)error;
- (NSTimeInterval)operationTimeout;
@end
@interface TestBackup : SHDWBackupService
@property(nonatomic,copy) NSString *fixture;
@property(nonatomic) NSUInteger validations;
@property(nonatomic) NSTimeInterval timeout;
@property(nonatomic) BOOL rejectHelper;
@end
@implementation TestBackup
- (NSString *)helperPath { return [fixtures stringByAppendingPathComponent:[@"fixture-" stringByAppendingString:self.fixture]]; }
- (BOOL)validateHelperAtPath:(NSString *)path error:(NSError **)error { (void)path;self.validations++;if(self.rejectHelper){if(error)*error=[NSError errorWithDomain:@"fixture" code:9 userInfo:@{NSLocalizedDescriptionKey:@"untrusted fixture"}];return NO;}return YES; }
- (NSTimeInterval)operationTimeout { return self.timeout ?: 5; }
@end
@interface SHDWCleanupService (FixtureSeam)
- (NSDictionary *)invokeHelper:(NSArray *)arguments error:(NSError **)error;
@end
@interface TestCleanup : SHDWCleanupService @end
@implementation TestCleanup
- (NSDictionary *)invokeHelper:(NSArray *)arguments error:(NSError **)error { (void)error;if([arguments.firstObject isEqual:@"prepare"])[NSThread sleepForTimeInterval:0.3];return @{@"ok":@YES,@"token":@"fixture-token",@"recheckVerified":@YES}; }
@end
static TestBackup *Service(NSString *fixture) { TestBackup *service=[[TestBackup alloc]initWithBundleIdentifier:@"local.fixture.app"];service.fixture=fixture;return service; }
static NSDictionary *Request(NSString *action) { return @{@"expectedAction":action,@"nested":@{@"unicode":@"中文 🗃"},@"binary":[NSData dataWithBytes:"\0\xff\1\0" length:4],@"date":[NSDate dateWithTimeIntervalSince1970:1000.25]}; }
static void Later(void (^block)(void)) { dispatch_after(dispatch_time(DISPATCH_TIME_NOW,120*NSEC_PER_MSEC),dispatch_get_main_queue(),block); }
static void Next(void);
static NSArray *Cases(void) {
    return @[
        @{@"fixture":@"valid",@"action":@"backup",@"ok":@YES},
        @{@"fixture":@"split",@"action":@"restore",@"ok":@YES},
        @{@"fixture":@"stream",@"action":@"backup",@"ok":@YES},
        @{@"fixture":@"valid",@"action":@"edit",@"ok":@YES},
        @{@"fixture":@"valid",@"action":@"delete",@"ok":@YES},
        @{@"fixture":@"valid",@"action":@"recheck",@"ok":@YES},
        @{@"fixture":@"malformed",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"truncated",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"missing",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"failure",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"invalid-base64",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"invalid-plist",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"numeric-ok",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"bad-progress",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"too-many-progress-keys",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"duplicate",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"after-result",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"oversized",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"timeout",@"action":@"restore",@"ok":@NO,@"partial":@YES},
        @{@"fixture":@"bad-exit",@"action":@"backup",@"ok":@NO,@"partial":@NO},
        @{@"fixture":@"bad-exit",@"action":@"restore",@"ok":@NO,@"partial":@YES}
    ];
}
static void Transport(NSDictionary *item) {
    TestBackup *service=Service(item[@"fixture"]);if([item[@"fixture"] isEqual:@"timeout"])service.timeout=0.2;
    NSString *action=item[@"action"];NSDictionary *request=Request(action);__block NSUInteger completions=0,progressCount=0;__block unsigned long long lastBytes=0;NSTimeInterval start=NSProcessInfo.processInfo.systemUptime;
    [service performAction:action request:request progress:^(NSDictionary *event){Check(NSThread.isMainThread,@"progress off main thread");Check(completions==0,@"progress after completion");progressCount++;lastBytes=[event[@"bytes"] unsignedLongLongValue];} completion:^(id result,NSError *error){
        Check(NSThread.isMainThread&&!service.running,@"completion thread/running lifecycle");Check(++completions==1,@"duplicate completion");BOOL expected=[item[@"ok"] boolValue];Check((result!=nil)==expected&&((error==nil)==expected),[NSString stringWithFormat:@"%@ %@ success/error mismatch: %@",action,item[@"fixture"],error]);
        Check(![SHDWOperationCoordinator isRunning],@"transport did not release operation gate");
        if(expected){Check([result[@"request"] isEqual:request],@"base64 binary plist request/result roundtrip");if([item[@"fixture"] isEqual:@"split"])Check(progressCount>0&&lastBytes==17,@"split UTF-8 progress missing");if([item[@"fixture"] isEqual:@"stream"])Check(progressCount>0&&lastBytes==4096,@"stream final progress missing");}
        else Check([error.userInfo[@"stateMayBePartial"] boolValue]==[item[@"partial"] boolValue],[NSString stringWithFormat:@"%@ %@ incorrect partial-state flag %@",action,item[@"fixture"],error]);
        if([item[@"fixture"] isEqual:@"timeout"])Check(NSProcessInfo.processInfo.systemUptime-start<2,@"transport timeout was unbounded");
        Later(^{int status=0;Check(waitpid(-1,&status,WNOHANG)==-1&&errno==ECHILD,@"helper remained alive/unreaped after completion");Check(completions==1,@"delayed duplicate completion");Next();});
    }];
}
static void ReadOnlyGate(void (^done)(void)) {
    NSError *error=nil;Check([SHDWOperationCoordinator beginOperation:&error],@"claim manual refresh gate");TestBackup *service=Service(@"valid");
    [service loadCatalog:^(NSArray *items,NSError *failure){Check(NSThread.isMainThread&&items.count==1&&!failure,@"catalog transport");Check(!items[0][@"archiveInfo"]&&[items[0][@"date"] isKindOfClass:NSDate.class],@"catalog not compact plist metadata");Check([SHDWOperationCoordinator isRunning],@"readonly catalog released another operation");
        TestBackup *check=Service(@"valid");[check performAction:@"recheck" request:Request(@"recheck") progress:nil completion:^(id result,NSError *checkError){Check(result&&!checkError&&[SHDWOperationCoordinator isRunning],@"readonly recheck claimed/released global gate");TestBackup *blocked=Service(@"valid");[blocked performAction:@"backup" request:Request(@"backup") progress:nil completion:^(id value,NSError *blockedError){Check(!value&&blockedError&&blocked.validations==0&&[SHDWOperationCoordinator isRunning],@"backup bypassed manual-refresh gate or released owner");[SHDWOperationCoordinator endOperation];done();}];}];
    }];
}
static void DuplicateGate(void (^done)(void)) {
    TestBackup *owner=Service(@"hold");__block NSUInteger refused=0;
    [owner performAction:@"backup" request:Request(@"backup") progress:nil completion:^(id result,NSError *error){Check(result&&!error&&refused==2&&!owner.running&&![SHDWOperationCoordinator isRunning],@"owner/duplicate gate completion");done();}];
    [owner performAction:@"backup" request:Request(@"backup") progress:nil completion:^(id result,NSError *error){Check(!result&&error&&owner.running&&[SHDWOperationCoordinator isRunning],@"same-service duplicate released owner");refused++;}];
    TestBackup *second=Service(@"valid");[second performAction:@"restore" request:Request(@"restore") progress:nil completion:^(id result,NSError *error){Check(!result&&error&&second.validations==0&&[SHDWOperationCoordinator isRunning],@"cross-service duplicate released owner");refused++;}];
}
static void CleanupGate(void (^done)(void)) {
    // Opening and cancelling cleanup must not reserve the global gate.
    @autoreleasepool { TestCleanup *cancelled=[[TestCleanup alloc]initWithBundleIdentifier:@"local.fixture.app"];Check(!cancelled.running&&![SHDWOperationCoordinator isRunning],@"cancelled cleanup claimed gate"); }
    TestCleanup *cleanup=[[TestCleanup alloc]initWithBundleIdentifier:@"local.fixture.app"];__block BOOL rejected=NO;
    [cleanup startWithSteps:@[@"files"] progress:^(NSString *step,NSString *state,NSString *message){(void)step;(void)state;(void)message;} completion:^(BOOL ok,NSError *error){Check(ok&&!error&&rejected&&![SHDWOperationCoordinator isRunning],@"cleanup gate release or completion");done();}];
    TestBackup *backup=Service(@"valid");[backup performAction:@"backup" request:Request(@"backup") progress:nil completion:^(id result,NSError *error){Check(!result&&error&&backup.validations==0&&[SHDWOperationCoordinator isRunning],@"backup overlapped active cleanup");rejected=YES;}];
}
static void Preflight(NSUInteger index,void (^done)(void)) {
    TestBackup *service=Service(@"valid");NSDictionary *request=Request(@"backup");NSString *action=@"backup";
    if(index==0)action=@"unknown";
    if(index==1)request=@{@"unsupported":[NSSet setWithObject:@"not a plist"]};
    if(index==2)request=@{@"large":[@"x" stringByPaddingToLength:20000 withString:@"x" startingAtIndex:0]};
    if(index==3)service.rejectHelper=YES;
    if(index==4)service.fixture=@"does-not-exist";
    [service performAction:action request:request progress:nil completion:^(id result,NSError *error){Check(!result&&error&&!service.running&&![SHDWOperationCoordinator isRunning],@"preflight/spawn failure gate leak");if(index==0)Check(service.validations==0,@"unknown action invoked transport");if(index<4)Preflight(index+1,done);else done();}];
}
static void Next(void) {
    static NSUInteger index;NSArray *cases=Cases();
    if(index<cases.count){completedCases++;Transport(cases[index++]);return;}
    switch(index++){
    case 21:ReadOnlyGate(^{Next();});break;
    case 22:DuplicateGate(^{Next();});break;
    case 23:CleanupGate(^{Next();});break;
    case 24:Preflight(0,^{Next();});break;
    case 25:{TestBackup *service=Service(@"wrong-catalog");[service loadCatalog:^(NSArray *items,NSError *error){Check(!items&&error&&!service.running,@"catalog accepted dictionary result");Next();}];break;}
    default:Check(notifications>0,@"operation notifications missing");printf("backup service: %lu transport cases, NDJSON bounds, main callbacks, timeout/reaping and shared operation gates passed\n",(unsigned long)completedCases);exit(0);
    }
}
int main(int argc,const char *argv[]){@autoreleasepool{Check(argc==2,@"fixture directory argument");fixtures=[NSString stringWithUTF8String:argv[1]];
Check(!SHDWBackupCanRestore(@{},YES)&&SHDWBackupCanRestore(@{},NO),@"ordinary same-IDFV restore was enabled");
NSDictionary *pending=@{@"restorePending":@YES,@"recoverySource":@YES};
Check(!SHDWBackupCanRestore(pending,YES)&&SHDWBackupCanRestore(pending,NO),@"incomplete restore bypassed identity rule");
NSDictionary *finalizing=@{@"restorePending":@YES,@"recoverySource":@YES,@"finalizationPending":@YES};
Check(SHDWBackupCanRestore(finalizing,YES)&&SHDWBackupFinalizationOnly(finalizing,YES)&&!SHDWBackupFinalizationOnly(finalizing,NO),@"pending finalization action unavailable");
Check(!SHDWBackupCanRestore(@{@"restorePending":@YES},NO),@"unrelated snapshot allowed during pending restore");
Check(!SHDWBackupCanRestore(@{@"unavailable":@YES,@"recoverySource":@YES,@"finalizationPending":@YES},YES),@"corrupt snapshot became restorable");
[NSNotificationCenter.defaultCenter addObserverForName:SHDWOperationDidChangeNotification object:nil queue:nil usingBlock:^(NSNotification *note){(void)note;Check(NSThread.isMainThread,@"coordinator notification off main");notifications++;}];dispatch_async(dispatch_get_main_queue(),^{Next();});while(YES)[NSRunLoop.currentRunLoop runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.02]];}return 0;}
'''


def main():
    if sys.platform != "darwin":
        raise SystemExit("This optional check requires macOS Foundation")
    names = ["valid", "split", "stream", "malformed", "truncated", "missing", "failure", "invalid-base64", "invalid-plist", "numeric-ok", "bad-progress", "too-many-progress-keys", "duplicate", "after-result", "oversized", "timeout", "bad-exit", "hold", "wrong-catalog"]
    with tempfile.TemporaryDirectory(prefix="shadow-backup-service-") as directory:
        temp = Path(directory).resolve()
        for name in names:
            fixture = temp / ("fixture-" + name)
            fixture.write_text(HELPER)
            fixture.chmod(0o700)
        harness = temp / "main.m"
        harness.write_text(HARNESS)
        sources = [ROOT / "src/Shadow.app/Services" / (name + ".m") for name in ("BackupService", "OperationCoordinator", "CleanupService")]
        binary = temp / "check"
        command = ["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-incomplete-implementation", "-framework", "Foundation", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g", "-O1", "-I" + str(ROOT / "src/Shadow.framework/Headers"), "-I" + str(ROOT / "src/Shadow.app"), str(harness), *map(str, sources), "-o", str(binary)]
        subprocess.run(command, check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(binary), str(temp)], env=environment, check=True, timeout=60)


if __name__ == "__main__":
    main()
