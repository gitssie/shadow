#import "BackgroundAttribution.h"
#import "BackgroundDiscovery.h"
#import "../Localization/FunctionHook.h"
#import <HookKit/HookKitRuntime.h>
#import <HookKit/HookKitResolver.h>
#import <CoreFoundation/CoreFoundation.h>
#include <pthread.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>

static const char *const cfnImage="/System/Library/Frameworks/CFNetwork.framework/CFNetwork";
static const char *const networkImage="/System/Library/Frameworks/Network.framework/Network";
static const char *(*parameterOwner)(id);
static CFTypeRef (*tubeProperty)(void *,CFStringRef);
static CFStringRef sourceOwnerKey;
static uintptr_t (*nativeIngest)(void *,void *,int);
static uintptr_t (*nativeCreate)(uintptr_t,uintptr_t,uintptr_t,id);
static NSString *(^ownerProfile)(NSString *);
static __thread void *constructionProfile;

NSString *SHDWBackgroundConstructionProfile(void) {
    return (__bridge NSString *)constructionProfile;
}

NSString *SHDWBackgroundOwnerForParameters(id parameters) {
    const char *(*getter)(id)=__atomic_load_n(&parameterOwner,__ATOMIC_ACQUIRE);
    if(!parameters || !getter)return nil;
    const char *value=getter(parameters);
    if(!value)return nil;
    size_t length=strnlen(value,1025);
    if(!length || length>1024)return nil;
    NSString *owner=[[NSString alloc]initWithBytes:value length:length encoding:NSUTF8StringEncoding];
    if([owner rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location!=NSNotFound)return nil;
    return owner;
}

static NSString *ProfileForOwner(NSString *owner) {
    if(!owner.length || !ownerProfile)return nil;
    id value=ownerProfile(owner);
    return [value isKindOfClass:NSString.class] && [value length] ? [value copy] : nil;
}

static uintptr_t Ingest(void *cache,void *tube,int flag) {
    int incoming=errno;
    void *previous=constructionProfile;
    constructionProfile=NULL;
    __attribute__((objc_precise_lifetime)) NSString *selected=nil;
    @try {
        CFTypeRef value=tube && tubeProperty && sourceOwnerKey?tubeProperty(tube,sourceOwnerKey):NULL;
        NSString *owner=nil;
        if(value) {
            if(CFGetTypeID(value)==CFStringGetTypeID())owner=[(__bridge NSString *)value copy];
            CFRelease(value);
        }
        selected=ProfileForOwner(owner);
        constructionProfile=(__bridge void *)selected;
        errno=incoming;
        return nativeIngest(cache,tube,flag);
    } @finally { constructionProfile=previous; }
}

static uintptr_t Create(uintptr_t first,uintptr_t second,uintptr_t third,id parameters) {
    int incoming=errno;
    void *previous=constructionProfile;
    constructionProfile=NULL;
    __attribute__((objc_precise_lifetime)) NSString *selected=nil;
    @try {
        selected=ProfileForOwner(SHDWBackgroundOwnerForParameters(parameters));
        constructionProfile=(__bridge void *)selected;
        errno=incoming;
        return nativeCreate(first,second,third,parameters);
    } @finally { constructionProfile=previous; }
}

static void *Find(hk_runtime_t *runtime,const char *image,const char *symbol) {
    void *address=NULL;
    return hk_runtime_find_symbol(runtime,image,symbol,&address)==HK_STATUS_OK?address:NULL;
}

BOOL SHDWBackgroundAttributionInstall(NSString *(^profileForOwner)(NSString *)) {
    if(!profileForOwner)return NO;
    static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
    static BOOL ingestInstalled,createInstalled;
    pthread_mutex_lock(&lock);
    @try {
        if(!ownerProfile)ownerProfile=[profileForOwner copy];
        hk_runtime_t *runtime=NULL;
        if(hk_runtime_create(NULL,&runtime)!=HK_STATUS_OK || !runtime) {
            hk_runtime_release(runtime);
            return ingestInstalled || createInstalled;
        }
        @try {
            if(!ingestInstalled) {
                void *target=Find(runtime,cfnImage,"_ZN20HTTP2ConnectionCache10ingestTubeEP4Tubei");
                void *property=Find(runtime,cfnImage,"_ZN4Tube22copyConnectionPropertyEPK10__CFString");
                CFStringRef *key=Find(runtime,cfnImage,"kCFStreamPropertySourceApplicationBundleIdentifier");
                if(!target || !property) {
                    void *discoveredTarget=NULL,*discoveredProperty=NULL;
                    if(SHDWBackgroundDiscoveryFind(&discoveredTarget,&discoveredProperty)) {
                        target=discoveredTarget;property=discoveredProperty;
                    }
                }
                if(target && property && key && *key && CFGetTypeID(*key)==CFStringGetTypeID()) {
                    tubeProperty=property;sourceOwnerKey=*key;
                    ingestInstalled=SHDWLocalizationHookFunction("_ZN20HTTP2ConnectionCache10ingestTubeEP4Tubei",target,(void *)Ingest,(void **)&nativeIngest);
                }
            }
            void *getter=Find(runtime,networkImage,"nw_parameters_get_effective_bundle_id");
            if(getter)__atomic_store_n(&parameterOwner,getter,__ATOMIC_RELEASE);
            if(!createInstalled) {
                void *target=Find(runtime,networkImage,"nw_protocol_http2_create");
                if(getter && target) {
                    createInstalled=SHDWLocalizationHookFunction("nw_protocol_http2_create",target,(void *)Create,(void **)&nativeCreate);
                }
            }
        } @finally { hk_runtime_release(runtime); }
        return ingestInstalled || createInstalled;
    } @finally { pthread_mutex_unlock(&lock); }
}
