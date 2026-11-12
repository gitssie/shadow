"""Exercise the native WebCore version-source hook without linking WebKit."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")

root = Path(__file__).resolve().parents[1]
source = r'''
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
#include <string>
#include <type_traits>
#include <stdint.h>
static void *fixture_dlsym(void *, const char *);
#define dlsym fixture_dlsym
#include "WebUserAgent.mm"
#undef dlsym

static BOOL targetAvailable=YES, factoryAvailable=YES, backendSucceeds=YES, publishOriginal=YES, reenter;
static unsigned lookups, hooks, nativeCalls, factoryCalls, allocations, destructions, live;
static SHDWWebUserAgentString (*replacement)(void);
static const void *constructedAt;
struct OwnedValue { uint64_t magic=0x319c0f2a4aadc0deULL;std::string bytes; };
struct NativeString {
    OwnedValue *implementation;
    explicit NativeString(const char *bytes,size_t length) : implementation(new OwnedValue) {
        implementation->bytes.assign(bytes,length);allocations++;live++;constructedAt=this;
    }
    NativeString(const NativeString&)=delete;
    NativeString(NativeString&&)=delete;
    ~NativeString() {
        if(!implementation)return;
        assert(implementation->magic==0x319c0f2a4aadc0deULL && live);
        implementation->magic=0;delete implementation;destructions++;live--;
    }
};
static_assert(sizeof(NativeString)==sizeof(SHDWWebUserAgentString));
static_assert(alignof(NativeString)==alignof(SHDWWebUserAgentString));
static_assert(!std::is_trivially_destructible_v<NativeString> && !std::is_trivially_destructible_v<SHDWWebUserAgentString>);
static_assert(!std::is_copy_constructible_v<SHDWWebUserAgentString> && !std::is_move_constructible_v<SHDWWebUserAgentString>);
static NativeString NativeVersion(void) { nativeCalls++;errno=ERANGE;return NativeString("16_3",4); }
static NativeString NativeFactory(const unsigned char *bytes,size_t length) {
    assert(bytes && length && strlen((const char *)bytes)==length);factoryCalls++;errno=EILSEQ;
    return NativeString((const char *)bytes,length);
}
static void consume(SHDWWebUserAgentString (*callback)(void),const char *expected) {
    unsigned before=allocations,dead=destructions;
    {
        errno=EBUSY;
        // The real WebKit caller owns a WTF String. Calling through this native
        // nontrivial-return type exercises the actual indirect return-slot ABI.
        NativeString value=reinterpret_cast<NativeString (*)(void)>((void *)callback)();
        assert(errno==EBUSY);
        if(expected) {
            assert(value.implementation && value.implementation->bytes==expected);
            assert(constructedAt==&value && allocations==before+1 && destructions==dead && live==1);
        } else assert(!value.implementation && allocations==before && destructions==dead && !live);
    }
    assert(!live && destructions==dead+(expected?1:0) && allocations==destructions);
}
static void *fixture_dlsym(void *handle,const char *symbol) {
    assert(handle==RTLD_DEFAULT);lookups++;errno=EIO;
    if(!strcmp(symbol,"_ZN7WebCore40systemMarketingVersionForUserAgentStringEv"))
        return targetAvailable ? (void *)&NativeVersion : NULL;
    const char *factorySymbol=sizeof(size_t)==8 ? "_ZN3WTF6String8fromUTF8EPKhm" : "_ZN3WTF6String8fromUTF8EPKhj";
    assert(!strcmp(symbol,factorySymbol));return factoryAvailable ? (void *)&NativeFactory : NULL;
}
bool SHDWLocalizationHookFunction(const char *symbol,void *target,void *callback,void **original) {
    assert(!strcmp(symbol,"_ZN7WebCore40systemMarketingVersionForUserAgentStringEv") && target==(void *)&NativeVersion && callback && original);
    hooks++;replacement=(SHDWWebUserAgentString (*)(void))callback;
    if(publishOriginal)*original=(void *)&NativeVersion;
    if(reenter) {
        errno=EINTR;
        assert(!SHDWWebUserAgentInstall(@"18.4"));
        assert(errno==EINTR && hooks==1 && lookups==2);
        consume(replacement,"18_4");
    }
    errno=ENOSYS;return backendSucceeds;
}
static BOOL install(NSString *version) {
    errno=EDOM;BOOL result=SHDWWebUserAgentInstall(version);assert(errno==EDOM);return result;
}
@interface LengthSideEffectString : NSString @end
@implementation LengthSideEffectString
- (NSUInteger)length { errno=E2BIG;return 0; }
- (unichar)characterAtIndex:(NSUInteger)index { (void)index;return 0; }
@end
int main(int argc,char **argv) { @autoreleasepool {
    assert(argc==2);
    if(!strcmp(argv[1],"validation")) {
        assert(!install(nil));
        for(id value in @[NSNull.null,@42,@"",@"16",@"16_4",@" 16.4",@"16.4 ",@"16.4\n",@"16..4",@"16.4.1.2",@"16.4(a)",@"１６.４",@"1.222222222222222222222222222222222"])
            assert(!install((NSString *)value));
        assert(!install([LengthSideEffectString new]));
        assert(!lookups && !hooks);
        assert(install(@"16.4.1"));
    } else if(!strcmp(argv[1],"retry")) {
        targetAvailable=NO;
        assert(!install(@"18.4") && !hooks && lookups==2);
        assert(!install(@"18.4") && !hooks && lookups==4);
        targetAvailable=YES;
        assert(install(@"18.4") && hooks==1 && lookups==6);
        assert(install(@"18.4") && hooks==1 && lookups==6);
        assert(!install(@"17.7.2") && hooks==1 && lookups==6);
    } else if(!strcmp(argv[1],"missing-factory")) {
        factoryAvailable=NO;
        assert(!install(@"18.4") && !hooks && lookups==2);
        factoryAvailable=YES;
        assert(install(@"18.4") && hooks==1 && lookups==4);
        consume(replacement,"18_4");
    } else if(!strcmp(argv[1],"snapshot")) {
        NSMutableString *input=[@"18.4" mutableCopy];
        reenter=YES;
        assert(install(input) && hooks==1 && lookups==2);
        [input setString:@"17.7.2"];
        consume(replacement,"18_4");assert(!nativeCalls && factoryCalls==2);
        assert(install(@"18.4") && !install(input) && hooks==1 && lookups==2);
    } else if(!strcmp(argv[1],"terminal")) {
        backendSucceeds=NO;
        assert(!install(@"18.4") && hooks==1 && lookups==2);
        backendSucceeds=YES;
        assert(!install(@"18.4") && !install(@"17.7.2") && hooks==1 && lookups==2);
    } else if(!strcmp(argv[1],"fallback")) {
        consume(&MarketingVersion,NULL);
        nativeMarketingVersion=(SHDWWebUserAgentString (*)(void))(void *)&NativeVersion;
        consume(&MarketingVersion,"16_3");assert(nativeCalls==1);
        nativeMarketingVersion=NULL;
        consume(&MarketingVersion,NULL);assert(nativeCalls==1);
        assert(install(@"16.4.1"));
        consume(replacement,"16_4_1");assert(nativeCalls==1);
        stringFromUTF8=NULL;
        consume(replacement,"16_3");assert(nativeCalls==2);
        nativeMarketingVersion=NULL;
        consume(replacement,NULL);assert(nativeCalls==2);
    } else if(!strcmp(argv[1],"without-original")) {
        publishOriginal=NO;
        assert(install(@"16.4.1"));consume(replacement,"16_4_1");assert(!nativeCalls);
    } else assert(!"unknown scenario");
    assert(!live && allocations==destructions);puts(argv[1]);
} }
'''

with tempfile.TemporaryDirectory(prefix="shadow-web-user-agent-") as directory:
    source_path, binary = Path(directory) / "test.mm", Path(directory) / "test"
    source_path.write_text(source)
    # Two distinct nontrivial types deliberately model the opaque/native ABI
    # boundary. Keep ASan/UBSan checks except their incompatible-type oracle.
    subprocess.run([
        "xcrun", "clang++", "-std=c++17", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize=function", "-framework", "Foundation", "-I",
        str(root / "src/ShadowCore.dylib/policy"), str(source_path), "-o", str(binary),
    ], check=True)
    for scenario in ("validation", "retry", "missing-factory", "snapshot", "terminal", "fallback", "without-original"):
        subprocess.run([str(binary), scenario], check=True, timeout=10)
print("WebCore UA source: native nontrivial sret slot/ownership, underscored factory output, validation, immutable snapshot, reentrant install, missing-target/factory retry, terminal idempotence, conflict and errno/fallback passed")
