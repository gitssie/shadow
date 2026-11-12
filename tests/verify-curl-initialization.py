"""Exercise the production curl loader's nonblocking reentry and refusal paths."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires macOS Foundation")
root = Path(__file__).resolve().parents[1]
dependency = Path(os.environ.get("SHADOW_CURL_ROOT", root.parent / "prebuilt/curl-impersonate/2.3.2/ios"))
if not (dependency / "include/curl/curl.h").is_file():
    raise SystemExit("Prepare the pinned curl headers with scripts/prepare-curl-impersonate.sh")
source = r'''
#define SHADOW_CURL_IMPERSONATE 1
#import <Foundation/Foundation.h>
#include <curl/curl.h>
#include <dlfcn.h>
#include <assert.h>
#include <string.h>
#include "CurlTransport.h"
static unsigned loads,lookups,initializations,creates,probes,destroys,reentries;
static const char *mode="success",*missing;
static CURLcode initialize(long flags) {
    assert(flags==CURL_GLOBAL_DEFAULT && !SHDWCurlTransportReady());initializations++;
    return !strcmp(mode,"init") ? CURLE_FAILED_INIT : CURLE_OK;
}
static CURL *create(void) {
    assert(!SHDWCurlTransportReady());creates++;
    return !strcmp(mode,"create") ? NULL : (CURL *)1;
}
static CURLcode impersonate(CURL *curl,const char *profile,int defaultHeaders) {
    assert(curl==(CURL *)1 && !strcmp(profile,"safari184_ios") && defaultHeaders==0);
    assert(!SHDWCurlTransportReady());probes++;
    return !strcmp(mode,"preset") ? CURLE_BAD_FUNCTION_ARGUMENT : CURLE_OK;
}
static void destroy(CURL *curl) { assert(curl==(CURL *)1 && !SHDWCurlTransportReady());destroys++; }
static CURLcode set(CURL *curl,CURLoption option,...) { (void)curl;(void)option;abort(); }
static CURLcode perform(CURL *curl) { (void)curl;abort(); }
static CURLcode info(CURL *curl,CURLINFO option,...) { (void)curl;(void)option;abort(); }
static struct curl_slist *append(struct curl_slist *list,const char *value) { (void)list;(void)value;abort(); }
static void freeHeaders(struct curl_slist *list) { (void)list;abort(); }
static const char *errorText(CURLcode error) { (void)error;abort(); }
static void *openImage(const char *path,int flags) {
    assert(!strcmp(path,"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib"));
    assert(flags==(RTLD_NOW|RTLD_LOCAL) && !SHDWCurlTransportReady());loads++;
    assert(loads==1);
    // A blocking dispatch_once guard deadlocks here, inside the first load.
    SHDWCurlTransportPrepareProfile(@"safari184_ios");reentries++;
    assert(loads==1 && !SHDWCurlTransportReady() && !lookups && !initializations);
    return !strcmp(mode,"load") ? NULL : (void *)2;
}
static void *lookup(void *image,const char *name) {
    assert(image==(void *)2 && !SHDWCurlTransportReady());lookups++;
    if(missing && !strcmp(name,missing)) return NULL;
    if(!strcmp(name,"curl_global_init")) return (void *)initialize;
    if(!strcmp(name,"curl_easy_init")) return (void *)create;
    if(!strcmp(name,"curl_easy_impersonate")) return (void *)impersonate;
    if(!strcmp(name,"curl_easy_setopt")) return (void *)set;
    if(!strcmp(name,"curl_easy_perform")) return (void *)perform;
    if(!strcmp(name,"curl_easy_getinfo")) return (void *)info;
    if(!strcmp(name,"curl_easy_cleanup")) return (void *)destroy;
    if(!strcmp(name,"curl_slist_append")) return (void *)append;
    if(!strcmp(name,"curl_slist_free_all")) return (void *)freeHeaders;
    if(!strcmp(name,"curl_easy_strerror")) return (void *)errorText;
    abort();
}
#define dlopen openImage
#define dlsym lookup
#include "CurlTransport.m"
#undef dlopen
#undef dlsym
NSString *JBPath(NSString *path) { return path; }
BOOL SHDWCurlEvaluateTrust(NSArray<NSData *> *certificates,NSString *host,NSInteger port,NSTimeInterval timeout,
    void (^challenge)(NSURLAuthenticationChallenge *),BOOL (^cancelled)(void)) {
    (void)certificates;(void)host;(void)port;(void)timeout;(void)challenge;(void)cancelled;abort();
}
int main(int argc,char **argv) { @autoreleasepool {
    if(argc>1) mode=argv[1];
    if(argc>2) missing=argv[2];
    assert(!SHDWCurlTransportReady());
    for(id profile in @[NSNull.null,@"native",@"unknown",@"",@"safari184_ios\n"]) {
        SHDWCurlTransportPrepareProfile(profile);assert(!loads && !SHDWCurlTransportReady());
    }
    SHDWCurlTransportPrepareProfile(nil);assert(!loads);
    SHDWCurlTransportPrepareProfile(@"safari184_ios");
    assert(loads==1 && reentries==1);
    BOOL expected=!strcmp(mode,"success");assert(SHDWCurlTransportReady()==expected);
    if(expected) assert(lookups==10 && initializations==1 && creates==1 && probes==1 && destroys==1);
    if(missing) assert(!initializations && !creates && !probes && !destroys);
    if(!strcmp(mode,"init")) assert(initializations==1 && !creates && !probes && !destroys);
    if(!strcmp(mode,"create")) assert(initializations==1 && creates==1 && !probes && !destroys);
    if(!strcmp(mode,"preset")) assert(initializations==1 && creates==1 && probes==1 && destroys==1);
    if(!strcmp(mode,"load")) assert(!lookups && !initializations);
    unsigned beforeLookups=lookups,beforeInitializations=initializations,beforeCreates=creates,beforeProbes=probes;
    for(unsigned attempt=0;attempt<3;attempt++) SHDWCurlTransportPrepareProfile(@"safari184_ios");
    SHDWCurlTransportPrepareProfile(@"native");
    assert(loads==1 && reentries==1 && lookups==beforeLookups && initializations==beforeInitializations && creates==beforeCreates && probes==beforeProbes);
    assert(SHDWCurlTransportReady()==expected);
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-curl-initialization-") as temporary:
    test, binary = Path(temporary) / "test.m", Path(temporary) / "test"
    test.write_text(source)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-framework", "Foundation", "-framework", "CFNetwork",
                    "-framework", "Security", "-I", str(dependency / "include"),
                    "-I", str(root / "src/Shadow.framework/Headers"),
                    "-I", str(root / "src/ShadowCore.dylib/policy"), str(test), "-o", str(binary)], check=True)
    for mode in ("success", "load", "init", "create", "preset"):
        subprocess.run([str(binary), mode], check=True, timeout=20)
    for symbol in ("curl_global_init", "curl_easy_init", "curl_easy_impersonate", "curl_easy_setopt",
                   "curl_easy_perform", "curl_easy_getinfo", "curl_easy_cleanup", "curl_slist_append",
                   "curl_slist_free_all", "curl_easy_strerror"):
        subprocess.run([str(binary), "missing", symbol], check=True, timeout=20)
    print("curl initialization: reentrant load, ready publication, single attempt, unsupported profiles, all missing symbols and init/preset refusal passed")
