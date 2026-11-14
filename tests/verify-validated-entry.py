"""Check the actual validated-entry request: pinned bytes, no original, strict backend."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
source=(root/'src/ShadowCore.dylib/SHDWHookSession.m').read_text()
start=source.index('- (BOOL)hookEntry:')
end=source.index('\n- (BOOL)hookRebindSymbol:',start)
method=source[start:end]
prefix=r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <dlfcn.h>
#include <stdint.h>
#include <string.h>
typedef void *hk_runtime_t;
typedef void *SHDWHKRuntimeCreateWithBackendOverride;
enum {HK_TARGET_FUNCTION_ADDRESS=1,HK_REACH_ENTRYPOINT=2,HK_ORIGINAL_NONE=3,HK_ABI_VERSION_3_0=4};
typedef struct { size_t struct_size; unsigned struct_version; uintptr_t address;
 const uint8_t *expected_initial_bytes; size_t expected_initial_bytes_size; } Address;
typedef struct { int kind,reach,original; void *replacement; struct {Address address;} target; } hk_hook_spec_t;
static BOOL available=YES,result=YES;
static unsigned applies,lookups;
static void *entry,*replacement;
static NSData *expected;
static void *lookup(void *scope,const char *name) {
 assert(scope==RTLD_DEFAULT && !strcmp(name,"hk_runtime_create_with_backend_override"));
 lookups++; return available ? (void *)1 : NULL;
}
#define dlsym lookup
static void shdw_init_spec(hk_hook_spec_t *spec,const char *name,int kind,void *r,int reach,int original) {
 assert(!strcmp(name,"shadow.validated-entry")); memset(spec,0,sizeof(*spec));
 spec->kind=kind; spec->replacement=r; spec->reach=reach; spec->original=original;
}
static BOOL shdw_apply_hook_spec_once(const hk_hook_spec_t *spec,void **old,const char *backend,
 SHDWHKRuntimeCreateWithBackendOverride creator,BOOL *clean,BOOL *retry,BOOL *cache,hk_runtime_t *runtime) {
 applies++; assert(!old && !clean && !retry && !cache && !runtime);
 assert(creator==(void *)1 && !strcmp(backend,"provider-ellekit"));
 assert(spec->kind==HK_TARGET_FUNCTION_ADDRESS && spec->reach==HK_REACH_ENTRYPOINT && spec->original==HK_ORIGINAL_NONE);
 assert(spec->replacement==replacement && spec->target.address.address==(uintptr_t)entry);
 assert(spec->target.address.struct_size==sizeof(Address) && spec->target.address.struct_version==HK_ABI_VERSION_3_0);
 assert(spec->target.address.expected_initial_bytes==expected.bytes && spec->target.address.expected_initial_bytes_size==16);
 return result;
}
@interface Session : NSObject
- (BOOL)hookEntry:(void *)e withReplacement:(void *)r expectedBytes:(NSData *)b backend:(NSString *)s;
@end
@implementation Session
'''
suffix=r'''
@end
int main(void) { @autoreleasepool {
 Session *session=[Session new]; char a,b; entry=&a;replacement=&b;
 expected=[NSMutableData dataWithLength:16];
 assert([session hookEntry:entry withReplacement:replacement expectedBytes:expected backend:@"provider-ellekit"]);
 assert(applies==1 && lookups==1);
 result=NO;
 assert(![session hookEntry:entry withReplacement:replacement expectedBytes:expected backend:@"provider-ellekit"]);
 assert(applies==2 && lookups==2);
 available=NO;
 assert(![session hookEntry:entry withReplacement:replacement expectedBytes:expected backend:@"provider-ellekit"]);
 assert(applies==2 && lookups==3);
 available=YES;
 assert(![session hookEntry:NULL withReplacement:replacement expectedBytes:expected backend:@"provider-ellekit"]);
 assert(![session hookEntry:entry withReplacement:NULL expectedBytes:expected backend:@"provider-ellekit"]);
 assert(![session hookEntry:entry withReplacement:replacement expectedBytes:nil backend:@"provider-ellekit"]);
 assert(![session hookEntry:entry withReplacement:replacement expectedBytes:[NSMutableData dataWithLength:17] backend:@"provider-ellekit"]);
 assert(![session hookEntry:entry withReplacement:replacement expectedBytes:expected backend:@""]);
 assert(applies==2 && lookups==3);
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix='shadow-validated-entry-') as tmp:
 unit=Path(tmp)/'test.m'; binary=Path(tmp)/'test'
 unit.write_text(prefix+method+suffix)
 subprocess.run(['clang','-fobjc-arc','-Wall','-Wextra','-Werror','-framework','Foundation',str(unit),'-o',str(binary)],check=True)
 subprocess.run([str(binary)],check=True)
print('validated entry: pinned bytes, no original cell, strict backend and refusal passed')
