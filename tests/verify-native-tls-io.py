"""Exercise production native BIO transport callbacks without a socketpair/pump."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/Transport/NativeTLS.m").read_text()

def function(marker):
    start = source.index(marker)
    opening = source.index("{", start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

callbacks = function("static CURLcode transportRead(") + function("static CURLcode transportWrite(")
setup = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <string.h>
typedef int CURLcode;
enum { CURLE_OK=0,CURLE_AGAIN=81,CURLE_ABORTED_BY_CALLBACK=42,
       CURLE_RECV_ERROR=56,CURLE_SEND_ERROR=55,CURLE_BAD_FUNCTION_ARGUMENT=43 };
@interface SHDWNativeSessionState:NSObject
@property(nonatomic) BOOL cancelled,closing;
@property(nonatomic) void *bio;
@end
@implementation SHDWNativeSessionState @end
static unsigned char payload[32771],received[sizeof(payload)],written[sizeof(payload)];
static size_t readOffset,writeOffset,fragment;
static int resultOverride,retryFlags;
static unsigned bioReads,bioWrites,flagReads;
static int lastLength;
static int appleBIORead(void *bio,void *bytes,int length) {
  assert(bio==(void *)1 && length>0);bioReads++;lastLength=length;
  if(resultOverride<=0)return resultOverride;
  size_t n=MIN(fragment,MIN(sizeof(payload)-readOffset,(size_t)length));
  memcpy(bytes,payload+readOffset,n);readOffset+=n;return (int)n;
}
static int appleBIOWrite(void *bio,const void *bytes,int length) {
  assert(bio==(void *)1 && length>0);bioWrites++;lastLength=length;
  if(resultOverride<=0)return resultOverride;
  size_t n=MIN(fragment,MIN(sizeof(payload)-writeOffset,(size_t)length));
  memcpy(written+writeOffset,bytes,n);writeOffset+=n;return (int)n;
}
static int appleBIOShouldRead(const void *bio) {
  assert(bio==(void *)1);flagReads++;return retryFlags & 1;
}
static int appleBIOShouldWrite(const void *bio) {
  assert(bio==(void *)1);flagReads++;return retryFlags & 2;
}
static void reset(void) {
  readOffset=writeOffset=0;fragment=997;resultOverride=1;retryFlags=0;
  bioReads=bioWrites=flagReads=0;lastLength=0;
  memset(received,0,sizeof(received));memset(written,0,sizeof(written));
}
'''
tests = r'''
int main(void){@autoreleasepool{
  for(size_t i=0;i<sizeof(payload);i++)payload[i]=(unsigned char)(i*37u);
  SHDWNativeSessionState *state=[SHDWNativeSessionState new];state.bio=(void *)1;
  void *context=(__bridge void *)state;size_t count;
  reset();
  while(readOffset<sizeof(payload)){
    size_t before=readOffset;count=SIZE_MAX;
    assert(transportRead(context,received+before,sizeof(received)-before,&count)==CURLE_OK);
    assert(count>0 && count<=fragment && readOffset==before+count);
  }
  assert(bioReads>8 && !memcmp(received,payload,sizeof(payload)) && !flagReads);
  while(writeOffset<sizeof(payload)){
    size_t before=writeOffset;count=SIZE_MAX;
    assert(transportWrite(context,payload+before,sizeof(payload)-before,&count)==CURLE_OK);
    assert(count>0 && count<=fragment && writeOffset==before+count);
  }
  assert(bioWrites>8 && !memcmp(written,payload,sizeof(payload)) && !flagReads);
  reset();retryFlags=3;
  assert(transportRead(context,received,SIZE_MAX,&count)==CURLE_OK && lastLength==INT_MAX);
  assert(transportWrite(context,payload,SIZE_MAX,&count)==CURLE_OK && lastLength==INT_MAX);

  assert(!flagReads); /* A stale retry flag cannot override positive progress. */

  for(int result=-1;result<=0;result++){
    for(int flags=1;flags<=3;flags++){
      reset();resultOverride=result;retryFlags=flags;count=SIZE_MAX;
      assert(transportRead(context,received,1,&count)==CURLE_AGAIN && count==0);
      count=SIZE_MAX;
      assert(transportWrite(context,payload,1,&count)==CURLE_AGAIN && count==0);
      assert(flagReads==(flags==2 ? 4u : 2u));
    }
    reset();resultOverride=result;retryFlags=0;count=SIZE_MAX;
    assert(transportRead(context,received,1,&count)==(result==0?CURLE_OK:CURLE_RECV_ERROR) && count==0);
    count=SIZE_MAX;
    assert(transportWrite(context,payload,1,&count)==CURLE_SEND_ERROR && count==0);
    assert(flagReads==4);
  }
  reset();count=SIZE_MAX;
  assert(transportRead(context,NULL,0,&count)==CURLE_OK && count==0);
  count=SIZE_MAX;
  assert(transportWrite(context,NULL,0,&count)==CURLE_OK && count==0);
  assert(!bioReads && !bioWrites && !flagReads);
  assert(transportRead(NULL,received,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(transportWrite(NULL,payload,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(transportRead(context,received,1,NULL)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(transportWrite(context,payload,1,NULL)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(transportRead(context,NULL,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(transportWrite(context,NULL,1,&count)==CURLE_BAD_FUNCTION_ARGUMENT);
  assert(!bioReads && !bioWrites && !flagReads);
  state.bio=NULL;
  assert(transportRead(context,received,1,&count)==CURLE_ABORTED_BY_CALLBACK);
  assert(transportWrite(context,payload,1,&count)==CURLE_ABORTED_BY_CALLBACK);
  state.bio=(void *)1;
  state.cancelled=YES;
  assert(transportRead(context,received,1,&count)==CURLE_ABORTED_BY_CALLBACK && !bioReads);
  assert(transportWrite(context,payload,1,&count)==CURLE_ABORTED_BY_CALLBACK && !bioWrites);
  state.closing=YES;
  assert(transportRead(context,received,1,&count)==CURLE_OK && count>0);
  assert(transportWrite(context,payload,1,&count)==CURLE_OK && count>0);
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-native-tls-io-") as temporary:
    directory=Path(temporary)
    unit=directory / "transport.m"
    binary=directory / "transport"
    unit.write_text(setup+callbacks+tests)
    command=["clang","-fobjc-arc","-Wall","-Wextra","-Werror","-framework","Foundation"]
    if "--sanitize" in sys.argv:
        command += ["-fsanitize=address,undefined"]
    subprocess.run(command+[str(unit),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print("Native TLS thin BIO transport checks passed")
