"""Run the production network query hooks and policy with native API doubles."""
from pathlib import Path
import subprocess
import tempfile
import sys
if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/hooks/Universal/NetworkQueries.x").read_text()
source = source.replace('#import "UniversalHooks.h"', '').replace('#import "../../policy/NetworkQueryPolicy.h"', '')
header = str(root / "src/ShadowCore.dylib/policy/NetworkQueryPolicy.h")
prefix = r'''
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
static unsigned internalDepth, resolverCalls, urlCalls;
static const void *fakeCaller = (void *)1;
static const char *callerPath;
static NSDictionary *nativeSettings;
static BOOL expectFiltered;
static BOOL shdw_caller_is_external(const void *c) { return c && c != (void *)2 && !internalDepth; }
static int fake_dladdr(const void *c, Dl_info *info) {
    (void)c; resolverCalls++; info->dli_fname = callerPath; errno = EINVAL; return callerPath != NULL;
}
static void scope_leave(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(scope_leave))) = (++internalDepth, YES); active; active = NO)
#define __builtin_return_address(n) fakeCaller
#define __builtin_extract_return_addr(c) (c)
#define dladdr fake_dladdr
static CFDictionaryRef native_settings(void) { errno = EINPROGRESS; return nativeSettings ? CFBridgingRetain(nativeSettings) : NULL; }
static CFDictionaryRef native_store(CFTypeRef store) { assert(store == (CFTypeRef)0x1234); return native_settings(); }
static CFArrayRef native_url(CFURLRef url, CFDictionaryRef settings) {
    assert(url == (CFURLRef)0x1234); urlCalls++;
    NSDictionary *d = (__bridge NSDictionary *)settings;
    if(d) assert((d[@"HTTPProxy"] == nil) == expectFiltered);
    errno = EBUSY; return CFBridgingRetain(@[@"native-result"]);
}
@interface SHDWHookSession : NSObject
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell;
@end
@implementation SHDWHookSession
- (BOOL)hookRebindSymbol:(NSString *)symbol withReplacement:(void *)replacement outOldPtr:(void **)cell {
    assert(replacement);
    *cell = [symbol isEqual:@"CFNetworkCopySystemProxySettings"] ? (void *)native_settings :
        [symbol isEqual:@"SCDynamicStoreCopyProxies"] ? (void *)native_store : (void *)native_url;
    return YES;
}
@end
'''
suffix = r'''
static void verify_filtered(CFDictionaryRef result) {
    assert(result && errno == EINPROGRESS);
    NSDictionary *d = (__bridge NSDictionary *)result;
    assert(!d[@"HTTPProxy"] && !d[@"HTTPSProxy"] && !d[@"HTTPPort"] && !d[@"ProxyAutoConfigEnable"]);
    assert([d[@"unrelated"] isEqual:@"preserved"]);
    NSDictionary *scoped = d[@"__SCOPED__"];
    assert(!scoped[@"utun5"] && !scoped[@"PPP0"]);
    assert(scoped[@"en0"] && !scoped[@"en0"][@"SOCKSProxy"]);
    assert([scoped[@"en0"][@"unrelated"] isEqual:@42]);
    CFRelease(result);
}
int main(void) { @autoreleasepool {
    assert(SHDWNetworkQueryPathMatches("/Apps/Probe.app/Frameworks/SDK", "/Apps/Probe.app"));
    assert(!SHDWNetworkQueryPathMatches("/Apps/Probe.app.other/SDK", "/Apps/Probe.app"));
    assert(!SHDWNetworkQueryPathMatches("/Apps/Probe.app/SDK", ""));
    assert(!SHDWNetworkQuerySettingsCopy(nil));
    assert(!SHDWNetworkQuerySettingsCopy((id)@"invalid"));
    nativeSettings = @{@"HTTPProxy": @"fixture", @"HTTPSProxy": @"fixture", @"HTTPPort": @8080,
        @"ProxyAutoConfigEnable": @1, @"unrelated": @"preserved",
        @"__SCOPED__": @{@"utun5": @{}, @"PPP0": @{}, @"en0": @{@"SOCKSProxy": @"fixture", @"unrelated": @42}}};
    NSDictionary *snapshot = [nativeSettings copy];
    shdw_universal_network_queries([SHDWHookSession new]);
    strcpy(shdw_network_bundle, "/Apps/Probe.app");
    strcpy(shdw_network_canonical_bundle, "/private/Apps/Probe.app");
    callerPath = "/Apps/Probe.app/Probe";
    verify_filtered(shdw_network_settings());
    callerPath = "/private/Apps/Probe.app/Frameworks/SDK.framework/SDK";
    verify_filtered(shdw_network_store_settings((CFTypeRef)0x1234));
    assert([nativeSettings isEqual:snapshot] && !internalDepth);
    expectFiltered = YES;
    CFArrayRef urls = shdw_network_url_settings((CFURLRef)0x1234, (__bridge CFDictionaryRef)nativeSettings);
    assert(urls && errno == EBUSY && urlCalls == 1); CFRelease(urls);
    for(NSString *path in @[@"/System/Library/Frameworks/CFNetwork.framework/CFNetwork", @"/Apps/Probe.app.other/Binary"]) {
        callerPath = path.UTF8String;
        CFDictionaryRef result = shdw_network_settings();
        assert(result == (__bridge CFDictionaryRef)nativeSettings && errno == EINPROGRESS); CFRelease(result);
        expectFiltered = NO;
        urls = shdw_network_url_settings((CFURLRef)0x1234, (__bridge CFDictionaryRef)nativeSettings);
        assert(urls && errno == EBUSY); CFRelease(urls);
    }
    callerPath = "/Apps/Probe.app/Probe"; internalDepth = 2;
    unsigned before = resolverCalls;
    CFDictionaryRef result = shdw_network_settings();
    assert(result == (__bridge CFDictionaryRef)nativeSettings && internalDepth == 2 && resolverCalls == before);
    CFRelease(result); internalDepth = 0;
    fakeCaller = NULL; result = shdw_network_settings();
    assert(result == (__bridge CFDictionaryRef)nativeSettings); CFRelease(result); fakeCaller = (void *)1;
    nativeSettings = nil; assert(!shdw_network_settings() && errno == EINPROGRESS);
    assert(shdw_sym_policy_lookup_network("CFNetworkCopySystemProxySettings") == (void *)shdw_network_settings);
    assert(!shdw_sym_policy_lookup_network("unknown"));
    original_network_settings = NULL;
    assert(!shdw_sym_policy_lookup_network("CFNetworkCopySystemProxySettings"));
    shdw_network_queries_enabled = NO; assert(!shdw_sym_policy_lookup_network("CFNetworkCopySystemProxySettings"));
    puts("network queries: app/system/internal scope, scoped values, native preservation, Copy ownership, URL query and errno passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-network-query-") as tmp:
    src = Path(tmp) / "test.m"; binary = Path(tmp) / "test"
    src.write_text(prefix + '\n#import "' + header + '"\n' + source + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-framework", "Foundation", str(src),
        str(root / "src/ShadowCore.dylib/policy/NetworkQueryPolicy.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
