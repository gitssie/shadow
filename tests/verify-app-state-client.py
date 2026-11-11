#!/usr/bin/env python3
"""Exercise the shared SDK against an isolated unprivileged process (no device data)."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HELPER = r'''#!/usr/bin/python3
import base64, json, os, plistlib, stat, sys, time
assert len(sys.argv) == 5 and sys.argv[1] == "state"
assert sys.argv[2] == "local.fixture.app"
action = sys.argv[3]
if action == "importState":
    assert sys.argv[4] == "-"
    info = os.fstat(0)
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_nlink == 0
    raw = sys.stdin.buffer.read()
    assert len(raw) > 8192
    request = plistlib.loads(raw)
    assert request["state"] == b"\x00\xff\x01\x80" * 300000
else:
    assert sys.stdin.buffer.read() == b""
    request = plistlib.loads(base64.b64decode(sys.argv[4], validate=True))
with open(__file__ + ".calls", "a") as calls:
    calls.write(action + "\n")
mode = request.get("mode", "valid")
def emit(value):
    sys.stdout.buffer.write(json.dumps(value, separators=(",", ":")).encode() + b"\n")
    sys.stdout.buffer.flush()
if mode.startswith("error:"):
    emit({"ok":False,"error":"本地化消息，与分类无关","errorCode":mode[6:],"sourceDomain":"fixture.source","sourceCode":41,"posixCode":13,"details":{"phase":"fixture"},"stateMayBePartial":True})
elif mode == "timeout":
    time.sleep(10)
elif mode == "malformed":
    os.write(1, b"{bad}\n")
elif mode == "partial":
    os.write(1, b'{"ok":true')
else:
    emit({"event":"progress", "progress":{"phase":"fixture"}})
    data = b"x" * (7 * 1024 * 1024) if mode == "large" else b"\x00\xff"
    result = {"data": data, "stdin": action == "importState"}
    emit({"ok":True, "result":base64.b64encode(plistlib.dumps(result, fmt=plistlib.FMT_BINARY)).decode()})
'''
HARNESS = r'''
#import <Foundation/Foundation.h>
#import "SHDWAppStateClient.h"
#include <math.h>
static void Check(BOOL value, NSString *message) { if (!value) { fprintf(stderr,"SDK fixture failed: %s\n",message.UTF8String); exit(1); } }
@interface FixtureClient : SHDWAppStateClient @end
@implementation FixtureClient
- (BOOL)validateHelperAtPath:(NSString *)path error:(NSError **)error { (void)path; (void)error; return YES; }
@end
static NSUInteger Calls(NSString *path) {
    NSString *value=[NSString stringWithContentsOfFile:[path stringByAppendingString:@".calls"] encoding:NSUTF8StringEncoding error:NULL];
    return value.length ? [value componentsSeparatedByString:@"\n"].count-1 : 0;
}
static NSDictionary *Import(NSString *mode) {
    NSMutableData *state=[NSMutableData dataWithLength:1200000];
    unsigned char pattern[]={0,255,1,128};
    for (NSUInteger i=0;i<state.length;i++) ((unsigned char *)state.mutableBytes)[i]=pattern[i%4];
    return @{@"state":state,@"mode":mode};
}
int main(int argc,const char *argv[]) { @autoreleasepool {
    Check(argc==2,@"arguments"); NSString *path=@(argv[1]); NSError *error=nil;
    FixtureClient *client=[[FixtureClient alloc]initWithHelperPath:path];
    client.timeout=10;
    __block NSUInteger progress=0; NSThread *caller=NSThread.currentThread;
    NSDictionary *value=[client invokeAction:@"importState" bundleIdentifier:@"local.fixture.app" request:Import(@"valid") progress:^(NSDictionary *event) {
        Check(NSThread.currentThread==caller && [event[@"phase"]isEqual:@"fixture"],@"progress calling thread"); progress++;
    } error:&error];
    Check(value && !error && [value[@"stdin"]boolValue] && progress==1,@"large binary stdin request");
    value=[client invokeAction:@"exportState" bundleIdentifier:@"local.fixture.app" request:@{@"mode":@"large"} progress:nil error:&error];
    Check(value && !error && [value[@"data"]length]==7*1024*1024,@"external response exceeds old frame limit");
    for(NSString *action in @[@"externalClaim",@"externalRelease",@"externalOwnership",@"backupAndReset"])
        Check([client invokeAction:action bundleIdentifier:@"local.fixture.app" request:@{@"idfv":@"11111111-2222-3333-4444-555555555555"} progress:nil error:&error]!=nil,@"ownership action rejected by shared SDK");
    NSUInteger calls=Calls(path);
    for (NSString *action in @[@"unknown",@"state;touch"]) {
        Check(![client invokeAction:action bundleIdentifier:@"local.fixture.app" request:@{} progress:nil error:&error] && error.code==2,@"unsupported action rejected");
    }
    for (NSString *bundle in @[@"",@"../local/app",@"local app",@"local\napp"]) {
        Check(![client invokeAction:@"externalCatalog" bundleIdentifier:bundle request:@{} progress:nil error:&error] && error.code==2,@"bad bundle rejected");
    }
    for (NSNumber *timeout in @[@0,@(-1),@(NAN),@(INFINITY)]) {
        client.timeout=timeout.doubleValue;
        Check(![client invokeAction:@"externalCatalog" bundleIdentifier:@"local.fixture.app" request:@{} progress:nil error:&error] && error.code==2,@"invalid timeout rejected");
    }
    client.timeout=10;
    Check(![client invokeAction:@"importState" bundleIdentifier:@"local.fixture.app" request:@{@"unsupported":[NSObject new]} progress:nil error:&error] && error.code==2,@"non-plist request rejected without exception");
    Check(Calls(path)==calls,@"validation spawned no processes");
    SHDWAppStateClient *production=[[SHDWAppStateClient alloc]initWithHelperPath:path];
    Check(![production invokeAction:@"capabilities" bundleIdentifier:@"local.fixture.app" request:@{} progress:nil error:&error] && error.code==1 && Calls(path)==calls,@"untrusted helper rejected");
    for (NSString *mode in @[@"malformed",@"partial"]) {
        Check(![client invokeAction:@"exportState" bundleIdentifier:@"local.fixture.app" request:@{@"mode":mode} progress:nil error:&error] && error.code==4,@"malformed/partial frame rejected");
    }
    calls=Calls(path); client.timeout=0.3;
    NSTimeInterval start=NSProcessInfo.processInfo.systemUptime;

    for(NSString *code in @[@"busy",@"shadow_unavailable",@"invalid_request",@"restore_pending",@"active_environment",@"ownership_conflict",@"snapshot_unavailable",@"invalid_archive",@"permission_denied",@"operation_failed",@"outcome_unknown"]){
        Check(![client invokeAction:@"externalVerify" bundleIdentifier:@"local.fixture.app" request:@{@"mode":[@"error:" stringByAppendingString:code]} progress:nil error:&error],@"structured error returned success");
        NSError *source=error.userInfo[NSUnderlyingErrorKey],*posix=source.userInfo[NSUnderlyingErrorKey];
        Check([error.userInfo[@"errorCode"]isEqual:code]&&[source.domain isEqual:@"fixture.source"]&&source.code==41&&[posix.domain isEqual:NSPOSIXErrorDomain]&&posix.code==13&&[error.userInfo[@"helperDetails"][@"phase"]isEqual:@"fixture"]&&[error.userInfo[@"stateMayBePartial"]boolValue],@"stable structured helper error lost in SDK");
    }
    calls=Calls(path);start=NSProcessInfo.processInfo.systemUptime;
    Check(![client invokeAction:@"importState" bundleIdentifier:@"local.fixture.app" request:Import(@"timeout") progress:nil error:&error] && error.code==4 && [error.userInfo[@"outcomeUnknown"]boolValue],@"import timeout preserves unknown outcome");
    Check(NSProcessInfo.processInfo.systemUptime-start<3 && Calls(path)==calls+1,@"timeout supervised with no automatic retry");
    puts("shared AppState SDK: bounded stdin, private unlinked input, >8MiB response, validation, caller-thread progress, malformed frames and timeout/no-retry passed");
} return 0; }
'''

def main():
    if sys.platform != "darwin":
        raise SystemExit("This optional check requires macOS Foundation")
    with tempfile.TemporaryDirectory(prefix="shadow-app-state-client-") as directory:
        temp=Path(directory).resolve()
        helper=temp/"helper"
        helper.write_text(HELPER)
        helper.chmod(0o700)
        harness=temp/"main.m"
        harness.write_text(HARNESS)
        binary=temp/"check"
        subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-framework","Foundation","-fsanitize=address,undefined","-fno-omit-frame-pointer","-g","-O1","-I"+str(ROOT/"sdk/AppState"),str(harness),str(ROOT/"sdk/AppState/SHDWAppStateClient.m"),"-o",str(binary)],check=True)
        env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(binary),str(helper)],env=env,check=True,timeout=40)

if __name__ == "__main__":
    main()
