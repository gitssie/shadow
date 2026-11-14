"""Exercise production native SSL shutdown with curl completion and I/O states."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/Transport/NativeTLS.m").read_text()

def function(name):
    start = source.index("static int " + name)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

setup = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
typedef int CURLcode;
enum { CURLE_OK, CURLE_AGAIN, CURLE_SEND_ERROR,
    SHDWExternalTLSWantRead=1, SHDWExternalTLSWantWrite=2 };
@interface SHDWNativeSessionState : NSObject
@property(nonatomic) BOOL takeover, ready, closing;
@property(nonatomic) int lastError;
@property(nonatomic) void *engine;
@end
@implementation SHDWNativeSessionState @end
static NSObject *lock;
static NSMapTable *sslSessions;
static SHDWNativeSessionState *state;
static int backendComplete, backendNeed;
static CURLcode backendResult, queryResult;
static unsigned shutdownCalls, queries, nativeCalls;
static BOOL releaseMapDuringCall;
static int originalShutdown(void *ssl) { assert(ssl==(void *)(uintptr_t)1); nativeCalls++; return 17; }
static CURLcode SHDWExternalTLSShutdown(void *engine, int *complete) {
    assert(engine==(void *)(uintptr_t)2); shutdownCalls++;
    SHDWNativeSessionState *current=[sslSessions objectForKey:[NSValue valueWithPointer:(void *)(uintptr_t)1]];
    assert(current && current.closing);
    if(releaseMapDuringCall) {
        // Once lookup has retained the session, removing the map's reference
        // must not destroy it while the backend callback is executing.
        __weak SHDWNativeSessionState *weak=current;
        [sslSessions removeAllObjects]; state=nil; current=nil;
        assert(weak && weak.closing);
    }
    *complete=backendComplete;return backendResult;
}
static CURLcode SHDWExternalTLSIOState(void *engine,int *need,int *shutdown) {
    assert(engine==(void *)(uintptr_t)2); queries++;
    *need=backendNeed;*shutdown=0;return queryResult;
}
static void traceTLS(SHDWNativeSessionState *s,NSString *stage,CURLcode code) {
    assert(s==state && [stage isEqual:@"tls.shutdown.begin"] && code==CURLE_OK);
}
'''
tests = r'''
static void reset(CURLcode result,int complete,int need) {
    [sslSessions removeAllObjects];
    state=[SHDWNativeSessionState new];state.takeover=YES;state.ready=YES;
    state.engine=(void *)(uintptr_t)2;state.lastError=99;
    [sslSessions setObject:state forKey:[NSValue valueWithPointer:(void *)(uintptr_t)1]];
    backendResult=result;backendComplete=complete;backendNeed=need;queryResult=CURLE_OK;
    shutdownCalls=queries=nativeCalls=0;releaseMapDuringCall=NO;
}
static int run(void) { return actualShutdown((void *)(uintptr_t)1); }
int main(void) { @autoreleasepool {
    lock=[NSObject new];sslSessions=[NSMapTable strongToStrongObjectsMapTable];
    reset(CURLE_OK,0,SHDWExternalTLSWantWrite);
    assert(run()==-1 && state.lastError==3 && !state.closing && shutdownCalls==1 && queries==1);
    reset(CURLE_OK,0,SHDWExternalTLSWantRead);
    assert(run()==-1 && state.lastError==2 && !state.closing);
    reset(CURLE_OK,1,SHDWExternalTLSWantWrite);
    assert(run()==1 && state.lastError==0 && !state.closing && !queries);
    reset(CURLE_OK,0,0);
    assert(run()==0 && state.lastError==0 && !state.closing);
    reset(CURLE_AGAIN,0,SHDWExternalTLSWantWrite);
    assert(run()==-1 && state.lastError==3 && !state.closing);
    reset(CURLE_AGAIN,0,SHDWExternalTLSWantRead);
    assert(run()==-1 && state.lastError==2 && !state.closing);
    reset(CURLE_AGAIN,0,0);
    assert(run()==-1 && state.lastError==3 && !state.closing);
    reset(CURLE_OK,0,SHDWExternalTLSWantRead);queryResult=CURLE_SEND_ERROR;
    assert(run()==-1 && state.lastError==1 && !state.closing);
    reset(CURLE_AGAIN,0,SHDWExternalTLSWantRead);queryResult=CURLE_SEND_ERROR;
    assert(run()==-1 && state.lastError==1 && !state.closing);
    reset(CURLE_SEND_ERROR,0,0);
    assert(run()==-1 && state.lastError==1 && !state.closing && !queries);
    reset(CURLE_OK,1,0);state.takeover=NO;
    assert(run()==17 && nativeCalls==1 && !shutdownCalls);
    reset(CURLE_OK,1,0);[sslSessions removeAllObjects];
    assert(run()==17 && nativeCalls==1 && !shutdownCalls);
    reset(CURLE_OK,1,0);state.engine=NULL;
    assert(run()==1 && state.lastError==0 && !shutdownCalls);
    reset(CURLE_OK,1,0);state.ready=NO;
    assert(run()==1 && state.lastError==0 && !shutdownCalls);
    reset(CURLE_OK,1,0);releaseMapDuringCall=YES;
    assert(run()==1 && shutdownCalls==1 && !state);
    puts("native TLS shutdown: incomplete I/O direction, completion, fatal errors and retained session passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-native-tls-shutdown-") as tmp:
    src = Path(tmp) / "shutdown.m"
    binary = Path(tmp) / "shutdown"
    src.write_text(setup + function("nativeWaitError(") + function("actualShutdown(") + tests)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
