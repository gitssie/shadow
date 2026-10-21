#import "NetworkQueryPolicy.h"
#include <string.h>
#include <strings.h>

BOOL SHDWNetworkQueryPathMatches(const char *path, const char *bundle) {
    if(!path || !bundle || !bundle[0]) return NO;
    size_t n = strlen(bundle);
    return strncmp(path, bundle, n) == 0 && (path[n] == '/' || path[n] == 0);
}

static BOOL shdw_network_query_interface(const char *name) {
    if(!name) return NO;
    const char *prefixes[] = {"utun", "tun", "tap", "ppp", "ipsec"};
    for(size_t i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); i++)
        if(strncasecmp(name, prefixes[i], strlen(prefixes[i])) == 0) return YES;
    return NO;
}

static NSMutableDictionary *shdw_network_query_dictionary(NSDictionary *settings) {
    NSMutableDictionary *copy = [settings mutableCopy];
    for(NSString *key in @[@"HTTPEnable", @"HTTPProxy", @"HTTPPort",
        @"HTTPSEnable", @"HTTPSProxy", @"HTTPSPort", @"SOCKSEnable", @"SOCKSProxy", @"SOCKSPort",
        @"FTPEnable", @"FTPProxy", @"FTPPort", @"GopherEnable", @"GopherProxy", @"GopherPort",
        @"RTSPEnable", @"RTSPProxy", @"RTSPPort", @"ProxyAutoConfigEnable",
        @"ProxyAutoConfigURLString", @"ProxyAutoConfigJavaScript", @"ProxyAutoDiscoveryEnable"])
        [copy removeObjectForKey:key];
    return copy;
}

NSDictionary *SHDWNetworkQuerySettingsCopy(NSDictionary *settings) {
    if(![settings isKindOfClass:NSDictionary.class]) return nil;
    NSMutableDictionary *copy = shdw_network_query_dictionary(settings);
    id scoped = settings[@"__SCOPED__"];
    if([scoped isKindOfClass:NSDictionary.class]) {
        NSMutableDictionary *interfaces = [scoped mutableCopy];
        for(id key in scoped) {
            if([key isKindOfClass:NSString.class] && shdw_network_query_interface([key UTF8String])) {
                [interfaces removeObjectForKey:key];
            } else if([scoped[key] isKindOfClass:NSDictionary.class]) {
                interfaces[key] = [shdw_network_query_dictionary(scoped[key]) copy];
            }
        }
        copy[@"__SCOPED__"] = [interfaces copy];
    }
    return [copy copy];
}
