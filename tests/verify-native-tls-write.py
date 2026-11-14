"""Exercise the production thin write adapter while curl owns TLS retry state."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/Transport/NativeTLS.m").read_text()

def function(marker):
    start = source.index("static ", source.index(marker) - 40)
    opening = source.index("{", source.index(marker))
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

adapter = function("adapterWrite(")
wait = function("nativeWaitError(")
setup = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdint.h>
typedef int CURLcode;
enum { CURLE_OK=0, CURLE_AGAIN=81, CURLE_SEND_ERROR=55, CURLE_BAD_FUNCTION_ARGUMENT=43 };
enum { SHDWExternalTLSWantRead=1, SHDWExternalTLSWantWrite=2 };
@interface SHDWNativeSessionState : NSObject
@property(nonatomic) BOOL takeover,ready;
@property(nonatomic) int lastError;
@property(nonatomic) void *engine;
@end
@implementation SHDWNativeSessionState @end
static SHDWNativeSessionState *state;
static unsigned writes,traces,queries;
static const void *expectedBytes;
static size_t expectedLength, accepted;
static CURLcode writeResult, ioResult;
static int ioNeed;
static SHDWNativeSessionState *lookup(void *legacy) { (void)legacy; return state; }
static CURLcode SHDWExternalTLSWrite(void *engine,const void *bytes,size_t length,size_t *count) {
  assert(engine==state.engine && bytes==expectedBytes && length==expectedLength);
  writes++; *count=0;
  if (!bytes && length) return CURLE_BAD_FUNCTION_ARGUMENT;
  if (writeResult==CURLE_OK) *count=accepted;
  return writeResult;
}
static CURLcode SHDWExternalTLSIOState(void *engine,int *need,int *shutdown) {
  assert(engine==state.engine); queries++; *need=ioNeed; *shutdown=0;
  return ioResult;
}
static void traceTLS(SHDWNativeSessionState *session,NSString *stage,CURLcode code) {
  assert(session==state && [stage isEqual:@"tls.write.failed"] && code!=CURLE_OK);
  traces++;
}
static void reset(const void *bytes,size_t length) {
  state=[SHDWNativeSessionState new]; state.takeover=YES; state.ready=YES;
  state.engine=(void *)(uintptr_t)1;
  writes=traces=queries=0; expectedBytes=bytes; expectedLength=length;
  accepted=length; writeResult=ioResult=CURLE_OK; ioNeed=0;
}
'''
tests = r'''
int main(void) { @autoreleasepool {
  unsigned char body[131072]={0};
  // Large input is forwarded intact exactly once; curl owns record splitting.
  reset(body,sizeof(body));
  assert(adapterWrite(NULL,body,sizeof(body))==sizeof(body));
  assert(writes==1 && !queries && !traces && state.lastError==0);
  reset(body,sizeof(body)); accepted=16384;
  assert(adapterWrite(NULL,body,sizeof(body))==16384);
  assert(writes==1 && !queries && state.lastError==0);

  // No adapter retry loops: preserve curl's WANT direction until a native event.
  for(unsigned direction=0;direction<4;direction++) {
    reset(body,8478); writeResult=CURLE_AGAIN; ioNeed=direction;
    assert(adapterWrite(NULL,body,8478)==UINT64_MAX);
    assert(writes==1 && queries==1 && !traces);
    assert(state.lastError==((direction&SHDWExternalTLSWantWrite) ? 3 :
           (direction&SHDWExternalTLSWantRead) ? 2 : 3));
    // Only the caller's next readiness event retries the unchanged operation.
    writeResult=CURLE_OK;
    assert(adapterWrite(NULL,body,8478)==8478);
    assert(writes==2 && queries==1 && state.lastError==0);
  }
  reset(body,8478); accepted=3;
  assert(adapterWrite(NULL,body,8478)==3 && writes==1 && state.lastError==0);
  reset(body,8478); writeResult=CURLE_SEND_ERROR;
  assert(adapterWrite(NULL,body,8478)==UINT64_MAX);
  assert(writes==1 && queries==0 && traces==1 && state.lastError==1);
  reset(body,8478); writeResult=CURLE_AGAIN; ioResult=CURLE_SEND_ERROR;
  assert(adapterWrite(NULL,body,8478)==UINT64_MAX);
  assert(writes==1 && queries==1 && state.lastError==1);
  reset(body,8478); accepted=0;
  assert(adapterWrite(NULL,body,8478)==UINT64_MAX);
  assert(writes==1 && queries==1 && state.lastError==3);

  reset(NULL,1);
  assert(adapterWrite(NULL,NULL,1)==UINT64_MAX && writes==1 && state.lastError==1);
  reset(NULL,0);
  assert(adapterWrite(NULL,NULL,0)==0 && !writes && !queries);
  assert(adapterWrite(NULL,NULL,-1)==0 && !writes && !queries);
  state.ready=NO;
  assert(adapterWrite(NULL,body,sizeof(body))==UINT64_MAX && state.lastError==3 && !writes);
  state.takeover=NO;
  assert(adapterWrite(NULL,body,sizeof(body))==UINT64_MAX && !writes);
  state=nil;
  assert(adapterWrite(NULL,body,sizeof(body))==UINT64_MAX && !writes);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-native-tls-write-") as temporary:
    directory=Path(temporary)
    unit=directory / "write.m"
    binary=directory / "write"
    unit.write_text(setup + wait + "\n" + adapter + tests)
    subprocess.run(["clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation",
                    str(unit), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Native TLS thin write adapter checks passed")
