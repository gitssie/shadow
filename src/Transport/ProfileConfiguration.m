#import "ProfileConfiguration.h"
#import "Profiles.h"
#import <Shadow/JBPath.h>
#if SHADOW_CURL_IMPERSONATE
#include "CurlReference.h"
#include "CurlHTTP2.h"
#include <dlfcn.h>

static unsigned configurationState;
static NSMutableDictionary *configurationCache;
static struct {
    CURLcode (*initialize)(long);
    CURL *(*create)(void);
    CURLcode (*impersonate)(CURL *,const char *,int);
    CURLcode (*set)(CURL *,CURLoption,...);
    SHDWCurlHTTP2ConfigFunction read;
    void (*destroy)(CURL *);
} configurationEngine;

static BOOL ConfigurationEngineReady(void) {
    if(__atomic_load_n(&configurationState,__ATOMIC_ACQUIRE)==2)return YES;
    unsigned expected=0;
    if(!__atomic_compare_exchange_n(&configurationState,&expected,1,NO,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return NO;
    BOOL available=NO;
    @try {
        void *image=dlopen(JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib").fileSystemRepresentation,RTLD_NOW|RTLD_LOCAL);
        if(!image)return NO;
#define SHDW_PROFILE_SYMBOL(field,name) configurationEngine.field=dlsym(image,name);if(!configurationEngine.field)return NO
        SHDW_PROFILE_SYMBOL(initialize,"curl_global_init");
        SHDW_PROFILE_SYMBOL(create,"curl_easy_init");
        SHDW_PROFILE_SYMBOL(impersonate,"curl_easy_impersonate");
        SHDW_PROFILE_SYMBOL(set,"curl_easy_setopt");
        SHDW_PROFILE_SYMBOL(read,"curl_shadow_get_http2_config");
        SHDW_PROFILE_SYMBOL(destroy,"curl_easy_cleanup");
#undef SHDW_PROFILE_SYMBOL
        const char *required[]={
            "curl_shadow_connect_only_enable_external_io",
            "curl_shadow_connect_only_set_native_verify","curl_shadow_connect_only_get_verification_snapshot",
            "curl_shadow_connect_only_set_transport","curl_shadow_connect_only_get_io_state",
            "curl_shadow_connect_only_shutdown"
        };
        for(size_t i=0;i<sizeof(required)/sizeof(required[0]);i++)if(!dlsym(image,required[i]))return NO;
        if(configurationEngine.initialize(CURL_GLOBAL_DEFAULT)!=CURLE_OK)return NO;
        configurationCache=[NSMutableDictionary new];
        available=YES;
        return YES;
    } @finally { __atomic_store_n(&configurationState,available?2:3,__ATOMIC_RELEASE); }
}
#endif
BOOL SHDWTransportCopyHTTP2Configuration(NSString *profile,SHDWH2Configuration *out) {
#if SHADOW_CURL_IMPERSONATE
    if(!out || !SHDWTransportProfileIsSupported(profile))return NO;
    NSString *selected=[profile copy];
    if(!SHDWTransportProfileIsSupported(selected) || !ConfigurationEngineReady())return NO;
    @synchronized(configurationCache) {
        id value=configurationCache[selected];
        if(value==NSNull.null)return NO;
        if(!value) {
            configurationCache[selected]=NSNull.null;
            CURL *probe=NULL;
            @try {
                probe=configurationEngine.create();if(!probe)return NO;
                SHDWH2Configuration configuration={0};
                if(SHDWCurlApplyProfile(probe,selected.UTF8String,configurationEngine.impersonate,configurationEngine.set)!=CURLE_OK ||
                   SHDWCurlReadHTTP2Configuration(probe,configurationEngine.read,&configuration)!=CURLE_OK)return NO;
                value=[NSData dataWithBytes:&configuration length:sizeof(configuration)];
                configurationCache[selected]=value;
            } @finally {
                if(probe)configurationEngine.destroy(probe);
                if(configurationCache[selected]==NSNull.null)[configurationCache removeObjectForKey:selected];
            }
        }
        if(![value isKindOfClass:NSData.class] || [value length]!=sizeof(*out))return NO;
        memcpy(out,[value bytes],sizeof(*out));
        return YES;
    }
#else
    (void)profile;(void)out;return NO;
#endif
}
