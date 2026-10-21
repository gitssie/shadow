#import "UniversalHooks.h"
#import "../../policy/NetworkQueryPolicy.h"
#include <limits.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>

static CFDictionaryRef (*original_network_settings)(void);
static CFDictionaryRef (*original_network_store_settings)(CFTypeRef);
static CFArrayRef (*original_network_url_settings)(CFURLRef, CFDictionaryRef);
static char shdw_network_bundle[PATH_MAX], shdw_network_canonical_bundle[PATH_MAX];
static BOOL shdw_network_queries_enabled;

static BOOL shdw_network_query_applies(const void *caller) {
    if(!shdw_network_queries_enabled || !shdw_caller_is_external(caller)) return NO;
    Dl_info image = {0};
    BOOL applies = NO;
    SHADOW_INTERNAL_SCOPE {
        if(dladdr(caller, &image) && image.dli_fname)
            applies = SHDWNetworkQueryPathMatches(image.dli_fname, shdw_network_bundle) ||
                SHDWNetworkQueryPathMatches(image.dli_fname, shdw_network_canonical_bundle);
    }
    return applies;
}

static CFDictionaryRef shdw_network_query_copy(CFDictionaryRef settings) {
    if(!settings) return NULL;
    NSDictionary *filtered = SHDWNetworkQuerySettingsCopy((__bridge NSDictionary *)settings);
    return filtered ? CFBridgingRetain(filtered) : CFRetain(settings);
}

static CFDictionaryRef shdw_network_settings(void) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    CFDictionaryRef result = original_network_settings();
    int saved = errno;
    @autoreleasepool {
        if(result && shdw_network_query_applies(caller)) {
            CFDictionaryRef next = shdw_network_query_copy(result);
            CFRelease(result); result = next;
        }
    }
    errno = saved; return result;
}

static CFDictionaryRef shdw_network_store_settings(CFTypeRef store) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    CFDictionaryRef result = original_network_store_settings(store);
    int saved = errno;
    @autoreleasepool {
        if(result && shdw_network_query_applies(caller)) {
            CFDictionaryRef next = shdw_network_query_copy(result);
            CFRelease(result); result = next;
        }
    }
    errno = saved; return result;
}

static CFArrayRef shdw_network_url_settings(CFURLRef url, CFDictionaryRef settings) {
    const void *caller = __builtin_extract_return_addr(__builtin_return_address(0));
    int before = errno;
    CFDictionaryRef filtered = NULL;
    @autoreleasepool {
        if(settings && shdw_network_query_applies(caller)) filtered = shdw_network_query_copy(settings);
    }
    errno = before;
    CFArrayRef result = original_network_url_settings(url, filtered ?: settings);
    int saved = errno;
    if(filtered) CFRelease(filtered);
    errno = saved; return result;
}

void *shdw_sym_policy_lookup_network(const char *name) {
    if(!shdw_network_queries_enabled || !name) return NULL;
    if(strcmp(name, "CFNetworkCopySystemProxySettings") == 0 && original_network_settings)
        return (void *)&shdw_network_settings;
    if(strcmp(name, "SCDynamicStoreCopyProxies") == 0 && original_network_store_settings)
        return (void *)&shdw_network_store_settings;
    if(strcmp(name, "CFNetworkCopyProxiesForURL") == 0 && original_network_url_settings)
        return (void *)&shdw_network_url_settings;
    return NULL;
}

void shdw_universal_network_queries(SHDWHookSession *hooks) {
    const char *path = NSBundle.mainBundle.bundlePath.fileSystemRepresentation;
    if(path) {
        snprintf(shdw_network_bundle, sizeof(shdw_network_bundle), "%s", path);
        realpath(path, shdw_network_canonical_bundle);
    }
    shdw_network_queries_enabled = YES;
    [hooks hookRebindSymbol:@"CFNetworkCopySystemProxySettings" withReplacement:shdw_network_settings
        outOldPtr:(void **)&original_network_settings];
    [hooks hookRebindSymbol:@"SCDynamicStoreCopyProxies" withReplacement:shdw_network_store_settings
        outOldPtr:(void **)&original_network_store_settings];
    [hooks hookRebindSymbol:@"CFNetworkCopyProxiesForURL" withReplacement:shdw_network_url_settings
        outOldPtr:(void **)&original_network_url_settings];
}
