#!/usr/bin/env python3
"""Execute native-construction attribution scopes with controlled native factories."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root=Path(__file__).resolve().parents[1]
production="\n".join(line for line in (root/"src/Transport/BackgroundAttribution.m").read_text().splitlines() if not line.startswith("#import"))
prefix=r"""
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
typedef struct { int value; } hk_runtime_t;
#define HK_STATUS_OK 0
static int hk_runtime_create(const void *config,hk_runtime_t **out);
static int hk_runtime_find_symbol(hk_runtime_t *runtime,const char *image,const char *name,void **out);
static void hk_runtime_release(hk_runtime_t *runtime);
static bool SHDWLocalizationHookFunction(const char *symbol,void *target,void *replacement,void **original);
static BOOL SHDWBackgroundDiscoveryFind(void **target,void **property) {(void)target;(void)property;return NO;}
"""
suffix=r"""
static BOOL exposeIngest,exposeCreate,exposeOwner,rejectHook;
static unsigned installs;
static CFStringRef key=CFSTR("native-source-key");
static uintptr_t NativeIngest(void *cache,void *tube,int flag);
static uintptr_t NativeCreate(uintptr_t a,uintptr_t b,uintptr_t c,id params);
static const char *Owner(id parameters) {errno=ENOSPC;return [parameters isKindOfClass:NSString.class]?[parameters UTF8String]:NULL;}
static CFTypeRef Property(void *tube,CFStringRef name) {
    assert(name==key);errno=EIO;return CFRetain((__bridge CFTypeRef)(__bridge id)tube);
}
static int hk_runtime_create(const void *config,hk_runtime_t **out) {
    (void)config;static hk_runtime_t runtime;*out=&runtime;return HK_STATUS_OK;
}
static void hk_runtime_release(hk_runtime_t *runtime) {(void)runtime;}
static int hk_runtime_find_symbol(hk_runtime_t *runtime,const char *image,const char *name,void **out) {
    assert(runtime);*out=NULL;
    if(!strcmp(image,cfnImage)) {
        if(!strcmp(name,"_ZN20HTTP2ConnectionCache10ingestTubeEP4Tubei") && exposeIngest)*out=(void *)NativeIngest;
        else if(!strcmp(name,"_ZN4Tube22copyConnectionPropertyEPK10__CFString") && exposeIngest)*out=(void *)Property;
        else if(!strcmp(name,"kCFStreamPropertySourceApplicationBundleIdentifier") && exposeIngest)*out=&key;
    }else {
        assert(!strcmp(image,networkImage));
        if(!strcmp(name,"nw_protocol_http2_create") && exposeCreate)*out=(void *)NativeCreate;
        else if(!strcmp(name,"nw_parameters_get_effective_bundle_id") && exposeOwner)*out=(void *)Owner;
    }
    return *out?0:1;
}
static bool SHDWLocalizationHookFunction(const char *symbol,void *target,void *replacement,void **original) {
    assert(symbol && target && replacement && original);installs++;
    if(rejectHook)return false;
    *original=target;return true;
}
static void CheckScope(id owner) {
    if([owner isEqual:@"selected.app"])assert([SHDWBackgroundConstructionProfile() isEqual:@"profile-selected"]);
    else assert(!SHDWBackgroundConstructionProfile());
}
static uintptr_t NativeCreate(uintptr_t a,uintptr_t b,uintptr_t action,id parameters) {
    assert(a==11 && b==22 && errno==EDOM);CheckScope(parameters);
    if(action==1) {
        assert(Ingest(NULL,(__bridge void *)@"unknown.app",0)==UINTPTR_MAX-1);
        CheckScope(parameters);
    }
    if(action==2)@throw [NSException exceptionWithName:@"fixture" reason:nil userInfo:nil];
    errno=ERANGE;return UINTPTR_MAX-2;
}
static uintptr_t NativeIngest(void *cache,void *tube,int action) {
    (void)cache;assert(errno==EDOM);CheckScope((__bridge id)tube);
    if(action==1) {
        assert(Create(11,22,0,@"unknown.app")==UINTPTR_MAX-2);
        CheckScope((__bridge id)tube);
    }
    if(action==2)@throw [NSException exceptionWithName:@"fixture" reason:nil userInfo:nil];
    errno=ERANGE;return UINTPTR_MAX-1;
}
int main(int argc,const char **argv) { @autoreleasepool {
    assert(argc==2);NSString *mode=@(argv[1]);
    NSString *(^resolver)(NSString *)=^NSString *(NSString *owner){errno=EACCES;return [owner isEqual:@"selected.app"]?[@"profile-selected" mutableCopy]:nil;};
    assert(!SHDWBackgroundAttributionInstall(nil));
    if([mode isEqual:@"none"]) {assert(!SHDWBackgroundAttributionInstall(resolver));assert(installs==0);return 0;}
    exposeIngest=![mode isEqual:@"network"];
    exposeCreate=![mode isEqual:@"tube"];
    exposeOwner=YES;
    rejectHook=[mode isEqual:@"refusal"];
    assert(SHDWBackgroundAttributionInstall(resolver)==!rejectHook);
    assert([SHDWBackgroundOwnerForParameters(@"selected.app") isEqual:@"selected.app"]);
    if(rejectHook) {assert(!SHDWBackgroundConstructionProfile());return 0;}
    unsigned before=installs;assert(SHDWBackgroundAttributionInstall(resolver));assert(installs==before);
    if(exposeIngest) {
        for(id owner in @[@"selected.app",@"unknown.app",@42]) {
            errno=EDOM;assert(Ingest(NULL,(__bridge void *)owner,0)==UINTPTR_MAX-1 && errno==ERANGE);
            assert(!SHDWBackgroundConstructionProfile());
        }
        @try {errno=EDOM;Ingest(NULL,(__bridge void *)@"selected.app",2);assert(NO);} @catch(NSException *exception) {(void)exception;assert(!SHDWBackgroundConstructionProfile());}
    }
    if(exposeCreate) {
        for(id owner in @[@"selected.app",@"unknown.app",@42]) {
            errno=EDOM;assert(Create(11,22,0,owner)==UINTPTR_MAX-2 && errno==ERANGE);
            assert(!SHDWBackgroundConstructionProfile());
        }
        @try {errno=EDOM;Create(11,22,2,@"selected.app");assert(NO);} @catch(NSException *exception) {(void)exception;assert(!SHDWBackgroundConstructionProfile());}
    }
    if(exposeIngest && exposeCreate) {
        errno=EDOM;assert(Ingest(NULL,(__bridge void *)@"selected.app",1)==UINTPTR_MAX-1);assert(!SHDWBackgroundConstructionProfile());
        errno=EDOM;assert(Create(11,22,1,@"selected.app")==UINTPTR_MAX-2);assert(!SHDWBackgroundConstructionProfile());
        constructionProfile=(__bridge void *)@"outer-thread-profile";
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{assert(!SHDWBackgroundConstructionProfile());dispatch_semaphore_signal(done);});
        assert(!dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,5*NSEC_PER_SEC)));
        assert([SHDWBackgroundConstructionProfile() isEqual:@"outer-thread-profile"]);constructionProfile=NULL;
    }
    printf("background attribution: %s passed (scope, owner isolation, nested/native, failure and full-width return)\n",argv[1]);
}return 0;}
"""
with tempfile.TemporaryDirectory(prefix="shadow-background-attribution-") as directory:
    source=Path(directory)/"test.m";binary=Path(directory)/"test"
    source.write_text(prefix+production+suffix)
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-framework","Foundation",str(source),"-o",str(binary)],check=True)
    for mode in ["none","tube","network","both","refusal"]:
        subprocess.run([str(binary),mode],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0",UBSAN_OPTIONS="halt_on_error=1"))
