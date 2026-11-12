#import "WebUserAgent.h"
#import "../../Localization/FunctionHook.h"
#include <dlfcn.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include "WebUserAgentString.h"

static unsigned installState;
static NSString *versionStorage;
static uintptr_t versionPointer;
static SHDWWebUserAgentString (*nativeMarketingVersion)(void);
static SHDWWebUserAgentString (*stringFromUTF8)(const unsigned char *, size_t);

static SHDWWebUserAgentString MarketingVersion(void) {
    struct RestoreErrno {
        int saved = errno;
        ~RestoreErrno() { errno = saved; }
    } restore;
    NSString *version = (__bridge NSString *)(void *)__atomic_load_n(&versionPointer, __ATOMIC_ACQUIRE);
    if (version) {
        auto factory = __atomic_load_n(&stringFromUTF8, __ATOMIC_ACQUIRE);
        const char *bytes = version.UTF8String;
        if (factory && bytes) return factory((const unsigned char *)bytes, strlen(bytes));
    }
    auto original = __atomic_load_n(&nativeMarketingVersion, __ATOMIC_ACQUIRE);
    if (original) return original();
    return SHDWWebUserAgentString{};
}

BOOL SHDWWebUserAgentVersionIsValid(NSString *version) {
    int saved = errno;
    if (![version isKindOfClass:NSString.class] || !version.length || version.length > 32) {
        errno = saved;
        return NO;
    }
    static NSRegularExpression *format;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        format = [NSRegularExpression regularExpressionWithPattern:@"[0-9]+(?:\\.[0-9]+){1,2}" options:0 error:NULL];
    });
    NSRange whole = NSMakeRange(0, version.length);
    BOOL valid = NSEqualRanges([format rangeOfFirstMatchInString:version options:0 range:whole], whole);
    errno = saved;
    return valid;
}

BOOL SHDWWebUserAgentInstall(NSString *version) {
    int saved = errno;
    if (!SHDWWebUserAgentVersionIsValid(version)) {
        errno = saved;
        return NO;
    }
    NSString *snapshot = [version copy];
    unsigned state = __atomic_load_n(&installState, __ATOMIC_ACQUIRE);
    if (state) {
        BOOL ready = state == 2 && [versionStorage isEqualToString:snapshot];
        errno = saved;
        return ready;
    }
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&installState, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        errno = saved;
        return NO;
    }
    const char *symbol = "_ZN7WebCore40systemMarketingVersionForUserAgentStringEv";
    void *target = dlsym(RTLD_DEFAULT, symbol);
    const char *factorySymbol = sizeof(size_t) == 8 ? "_ZN3WTF6String8fromUTF8EPKhm" : "_ZN3WTF6String8fromUTF8EPKhj";
    auto factory = (SHDWWebUserAgentString (*)(const unsigned char *, size_t))dlsym(RTLD_DEFAULT, factorySymbol);
    if (!target || !factory) {
        __atomic_store_n(&installState, 0, __ATOMIC_RELEASE);
        errno = saved;
        return NO;
    }
    versionStorage = snapshot;
    static NSString *underscoredVersion;
    underscoredVersion = [snapshot stringByReplacingOccurrencesOfString:@"." withString:@"_"];
    __atomic_store_n(&stringFromUTF8, factory, __ATOMIC_RELEASE);
    __atomic_store_n(&versionPointer, (uintptr_t)(__bridge void *)underscoredVersion, __ATOMIC_RELEASE);
    BOOL installed = SHDWLocalizationHookFunction(symbol, target, (void *)&MarketingVersion, (void **)&nativeMarketingVersion);
    __atomic_store_n(&installState, installed ? 2 : 3, __ATOMIC_RELEASE);
    errno = saved;
    return installed;
}
