"""Exercise the actual native TLS read adapter with bounded allocation doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
compiler = ["clang"] + (["-fsanitize=address,undefined"] if "--sanitize" in sys.argv else [])
source = (root / "src/Transport/NativeTLS.m").read_text()

def function(name):
    start = source.index("static ", source.index(name) - 30)
    opening = source.index("{", source.index(name))
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

adapter = function("adapterRead(")
remove_prefix = function("removePrefix(")
wait_error = function("nativeWaitError(")
setup = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <string.h>
typedef int CURLcode;
enum { CURLE_OK=0, CURLE_AGAIN=81, CURLE_RECV_ERROR=56 };
enum { SHDWExternalTLSWantRead=1, SHDWExternalTLSWantWrite=2 };
static NSUInteger allocationSize, allocations, externalReads;
static BOOL failAllocation;
static CURLcode readResult,ioResult;
static int ioNeed;
static NSData *reply;
@interface ReadAllocation : NSMutableData
@end
@implementation ReadAllocation
+ (instancetype)dataWithLength:(NSUInteger)length {
  allocations++; allocationSize=length;
  // Never allocate the old INT_MAX buffer even when testing a regression.
  assert(length <= 65536);
  if (failAllocation) return nil;
  return (ReadAllocation *)[NSMutableData dataWithLength:length];
}
@end
@interface SHDWNativeSessionState : NSObject
@property(nonatomic) BOOL takeover, ready;
@property(nonatomic) int lastError;
@property(nonatomic) void *engine;
@property(nonatomic,strong) NSMutableData *plaintext;
@end
@implementation SHDWNativeSessionState
@end
static SHDWNativeSessionState *state;
static SHDWNativeSessionState *lookup(void *legacy) { (void)legacy; return state; }
static CURLcode SHDWExternalTLSIOState(void *engine,int *need,int *shutdown) {
    (void)engine; *need=ioNeed; *shutdown=0; return ioResult;
}
static void traceTLS(SHDWNativeSessionState *s, NSString *stage, CURLcode code) {
  (void)s; (void)stage; (void)code;
}
static CURLcode SHDWExternalTLSRead(void *engine, void *bytes, size_t length, size_t *count) {
  (void)engine; externalReads++;
  assert(bytes && length > 0 && length <= 65536);
  *count=MIN(length, reply.length);
  if (*count) memcpy(bytes, reply.bytes, *count);
  return readResult;
}
static void reset(void) {
  state=[SHDWNativeSessionState new]; state.takeover=YES; state.ready=YES;
  state.plaintext=[NSMutableData new];
  allocationSize=allocations=externalReads=0; failAllocation=NO;
  reply=[NSData data]; readResult=CURLE_AGAIN; ioNeed=SHDWExternalTLSWantRead; ioResult=CURLE_OK;
}
'''
tests = r'''
int main(void) { @autoreleasepool {
  char output[16]={0};
  reset(); reply=[@"abc" dataUsingEncoding:NSUTF8StringEncoding]; readResult=CURLE_OK;
  assert(adapterRead(NULL,output,INT_MAX,0)==3);
  assert(allocationSize==65536 && externalReads==1 && !state.plaintext.length);
  assert(!memcmp(output,"abc",3) && state.lastError==0);

  reset(); failAllocation=YES;
  assert(adapterRead(NULL,output,INT_MAX,0)==UINT64_MAX);
  assert(allocations==1 && externalReads==0 && state.lastError==1);

  reset();
  assert(adapterRead(NULL,output,0,0)==0);
  assert(adapterRead(NULL,output,-1,0)==0);
  assert(!allocations && !externalReads);
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX);
  assert(externalReads==1 && state.lastError==2);
  ioNeed=SHDWExternalTLSWantWrite;
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX && state.lastError==3);
  ioNeed=SHDWExternalTLSWantRead|SHDWExternalTLSWantWrite;
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX && state.lastError==3);
  ioNeed=0;
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX && state.lastError==2);
  ioResult=CURLE_RECV_ERROR;
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX && state.lastError==1);
  ioResult=CURLE_OK;
  readResult=CURLE_OK;
  assert(adapterRead(NULL,output,8,0)==0 && state.lastError==6);

  reset(); reply=[@"abcdef" dataUsingEncoding:NSUTF8StringEncoding]; readResult=CURLE_OK;
  assert(adapterRead(NULL,output,6,1)==6 && state.plaintext.length==6);
  assert(!memcmp(output,"abcdef",6));
  assert(adapterRead(NULL,output,2,1)==2 && state.plaintext.length==6);
  assert(adapterRead(NULL,output,2,0)==2 && state.plaintext.length==4);
  assert(adapterRead(NULL,output,8,0)==4 && !state.plaintext.length);
  assert(!memcmp(output,"cdef",4) && externalReads==1 && allocations==1);

  reset(); readResult=CURLE_RECV_ERROR;
  assert(adapterRead(NULL,output,8,0)==UINT64_MAX && state.lastError==1);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-native-tls-read-") as temporary:
    directory = Path(temporary)
    def run(body, name):
        unit = directory / (name + ".m")
        binary = directory / name
        unit.write_text(setup + remove_prefix + wait_error + "\n#define NSMutableData ReadAllocation\n" + body
                        + "\n#undef NSMutableData\n" + tests)
        subprocess.run(compiler + ["-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-framework", "Foundation", str(unit),
                        "-o", str(binary)], check=True)
        return subprocess.run([str(binary)], capture_output=True)
    result = run(adapter, "current")
    assert result.returncode == 0, result.stderr.decode()
    if "--check-regression" in sys.argv:
        old = adapter.replace("MIN((NSUInteger)length, (NSUInteger)65536)", "(NSUInteger)length")
        assert old != adapter, "Could not reconstruct the unbounded allocation"
        result = run(old, "unbounded")
        assert result.returncode != 0, "Regression escaped the allocation bound check"
        print("Unbounded allocation regression rejected")
external_source = (root / "src/Transport/ExternalTLS.c").read_text()
def external_function(name):
    start = external_source.index("CURLcode " + name + "(")
    opening = external_source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (external_source[end] == "{") - (external_source[end] == "}")
        end += 1
    return external_source[start:end]

external_functions = "\n".join(external_function(name) for name in
                               ("SHDWExternalTLSRead", "SHDWExternalTLSWrite"))
external_setup = r'''
#include <assert.h>
#include <stddef.h>
typedef int CURLcode;
typedef void CURL;
enum { CURLE_OK=0, CURLE_AGAIN=81, CURLE_BAD_FUNCTION_ARGUMENT=43 };
typedef struct SHDWExternalTLS {
  int finished; CURLcode result; CURL *easy;
  CURLcode (*send)(CURL *,const void *,size_t,size_t *);
  CURLcode (*recv)(CURL *,void *,size_t,size_t *);
} SHDWExternalTLS;
static unsigned calls;
static CURLcode fakeSend(CURL *easy,const void *bytes,size_t length,size_t *count) {
  (void)easy; assert(bytes && length==1); calls++; *count=1; return CURLE_OK;
}
static CURLcode fakeRecv(CURL *easy,void *bytes,size_t length,size_t *count) {
  (void)easy; assert(bytes && length==1); calls++; *count=1; return CURLE_OK;
}
'''
external_tests = r'''
int main(void) {
  SHDWExternalTLS e={0}; e.send=fakeSend; e.recv=fakeRecv;
  char byte=0; size_t count=99;
  // Empty calls are harmless even before handshake or after terminal failure.
  for(int stage=0; stage<3; stage++) {
    e.finished=stage>0; e.result=stage==2 ? 56 : CURLE_OK;
    assert(SHDWExternalTLSRead(&e,NULL,0,&count)==CURLE_OK && count==0);
    count=99;
    assert(SHDWExternalTLSWrite(&e,NULL,0,&count)==CURLE_OK && count==0);
    assert(!calls);
  }
  e.finished=1; e.result=CURLE_OK;
  assert(SHDWExternalTLSRead(&e,&byte,1,&count)==CURLE_OK && count==1);
  assert(SHDWExternalTLSWrite(&e,&byte,1,&count)==CURLE_OK && count==1 && calls==2);
  assert(SHDWExternalTLSRead(&e,NULL,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(SHDWExternalTLSWrite(&e,NULL,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(SHDWExternalTLSRead(&e,&byte,1,NULL)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(SHDWExternalTLSWrite(&e,&byte,1,NULL)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(calls==2);
  return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="shadow-external-tls-read-") as temporary:
    directory = Path(temporary)
    unit = directory / "external.c"
    binary = directory / "external"
    unit.write_text(external_setup + external_functions + external_tests)
    subprocess.run(compiler + ["-Wall", "-Wextra", "-Werror", str(unit), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("Native TLS read adapter and external empty I/O checks passed")
