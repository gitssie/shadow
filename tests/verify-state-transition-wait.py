#!/usr/bin/env python3
"""Run the actual native settling method against timed host authority doubles."""
from pathlib import Path
import os
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SIGNATURE = "- (BOOL)waitForStoppedTarget:(NSDictionary *)target duration:(NSTimeInterval)duration error:(NSError **)error"


def production_method():
    source = (ROOT / "src/ShadowCleaner/StateBackend.inc").read_text()
    if source.count(SIGNATURE) != 1:
        raise SystemExit("Expected exactly one native transition-wait method")
    start = source.index(SIGNATURE)
    opening = source.index("{", start + len(SIGNATURE))
    depth = 0
    # Match Objective-C braces while ignoring comments and quoted literals.
    state = "code"
    escaped = False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index:index + 2]
        if state in ("string", "character"):
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == ('"' if state == "string" else "'"):
                state = "code"
        elif state == "line":
            if char == "\n":
                state = "code"
        elif state == "block":
            if following == "*/":
                state = "code"
                index += 1
        elif following in ("//", "/*"):
            state = "line" if following == "//" else "block"
            index += 1
        elif char in ('"', "'"):
            state = "string" if char == '"' else "character"
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
        index += 1
    raise SystemExit("Unterminated native transition-wait method")


HARNESS = r'''
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>

static NSTimeInterval Start, AuthorityFailureAt;
static NSUInteger AuthorityChecks;
static void Check(BOOL value, NSString *message) {
    if (!value) { fprintf(stderr,"FAIL: %s\n",message.UTF8String); exit(1); }
}
static void StateParent(void) {
    AuthorityChecks++;
    if (AuthorityFailureAt >= 0 && NSProcessInfo.processInfo.systemUptime - Start >= AuthorityFailureAt)
        @throw [NSException exceptionWithName:@"fixture-authority" reason:@"authority expired" userInfo:nil];
}
static BOOL StateFailure(NSError **error, NSException *exception) {
    if (error) *error=[NSError errorWithDomain:@"fixture-authority" code:1 userInfo:@{NSLocalizedDescriptionKey:exception.reason}];
    return NO;
}
@interface WaitBackend : NSObject
@property NSUInteger stoppedChecks;
@property NSTimeInterval restartAt;
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error;
- (BOOL)waitForStoppedTarget:(NSDictionary *)target duration:(NSTimeInterval)duration error:(NSError **)error;
@end
@implementation WaitBackend
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error {
    Check([target[@"fixture"] isEqual:@YES],@"native method changed its target");
    self.stoppedChecks++;
    if (self.restartAt >= 0 && NSProcessInfo.processInfo.systemUptime - Start >= self.restartAt) {
        if (error) *error=[NSError errorWithDomain:@"fixture-restart" code:2 userInfo:nil];
        return NO;
    }
    return YES;
}
/* PRODUCTION_METHOD */
@end

static void Run(NSString *name, NSTimeInterval duration, NSTimeInterval restartAt, NSTimeInterval authorityAt) {
    WaitBackend *backend=[WaitBackend new];backend.restartAt=restartAt;
    AuthorityFailureAt=authorityAt;AuthorityChecks=0;
    NSError *error=nil;Start=NSProcessInfo.processInfo.systemUptime;
    BOOL ok=[backend waitForStoppedTarget:@{@"fixture":@YES} duration:duration error:&error];
    NSTimeInterval elapsed=NSProcessInfo.processInfo.systemUptime-Start;
    if (restartAt < 0 && authorityAt < 0) {
        Check(ok && !error,[name stringByAppendingString:@": stopped target failed"]);
        Check(elapsed >= duration,[name stringByAppendingString:@": native wait returned early"]);
        Check(backend.stoppedChecks > 1 && AuthorityChecks > 1,@"native wait did not revalidate authority/process state");
    } else {
        Check(!ok && error,[name stringByAppendingString:@": invalid target/authority passed"]);
        Check([error.domain isEqual:restartAt >= 0 ? @"fixture-restart" : @"fixture-authority"],@"native wait lost the actual failure");
        NSTimeInterval injected=restartAt >= 0 ? restartAt : authorityAt;
        Check(elapsed >= injected,@"failure reported before its injection");
        // The native implementation checks in <=250ms steps; permit host
        // scheduler noise, while rejecting a full-duration sleep before checks.
        Check(elapsed < 1.0 && elapsed < duration,@"wait did not fail promptly after restart/authority loss");
        if (injected > 0) Check(backend.stoppedChecks > 0 && AuthorityChecks > 1,@"no valid initial interval before injected failure");
    }
    printf("PASS %s: %.3fs, process checks=%lu, authority checks=%lu\n",name.UTF8String,elapsed,(unsigned long)backend.stoppedChecks,(unsigned long)AuthorityChecks);
}
int main(void) { @autoreleasepool {
    Run(@"minimum stop settle",3.0,-1,-1);
    Run(@"minimum transition settle",1.0,-1,-1);
    Run(@"restart during stop settle",3.0,.1,-1);
    Run(@"restart during transition settle",1.0,.1,-1);
    Run(@"authority loss during settle",3.0,-1,.1);
    Run(@"already restarted",3.0,0,-1);
    Run(@"authority already lost",3.0,-1,0);
    return 0;
} }
'''


def main():
    method = production_method()
    with tempfile.TemporaryDirectory(prefix="shadow-transition-wait-") as directory:
        temporary = Path(directory)
        source = temporary / "main.m"
        source.write_text(HARNESS.replace("/* PRODUCTION_METHOD */", method))
        binary = temporary / "native-wait"
        subprocess.run([
            "xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
            "-g", "-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-framework", "Foundation", str(source), "-o", str(binary),
        ], check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
                           UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(binary)], check=True, env=environment, timeout=20)


if __name__ == "__main__":
    main()
