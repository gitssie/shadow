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
#include <stdarg.h>
#include "CurlTransport.h"
static unsigned loads,lookups,initializations,creates,probes,destroys,reentries;
static unsigned sets,failAt;
static const char *mode="success",*missing,*expectedProfile="safari184_ios";
static NSMutableString *callerProfile;
static CURLcode initialize(long flags) {
    assert(flags==CURL_GLOBAL_DEFAULT && !SHDWCurlTransportReady());initializations++;
    return !strcmp(mode,"init") ? CURLE_FAILED_INIT : CURLE_OK;
}
static CURL *create(void) {
    assert(!SHDWCurlTransportReady());creates++;
    return !strcmp(mode,"create") ? NULL : (CURL *)1;
}
static CURLcode impersonate(CURL *curl,const char *profile,int defaultHeaders) {
    const char *base=!strcmp(expectedProfile,"impit465") ? "safari184_ios" : expectedProfile;
    assert(curl==(CURL *)1 && !strcmp(profile,base) && defaultHeaders==0);
    assert(!SHDWCurlTransportReady());probes++;
    return !strcmp(mode,"preset") ? CURLE_BAD_FUNCTION_ARGUMENT : CURLE_OK;
}
static void destroy(CURL *curl) { assert(curl==(CURL *)1 && !SHDWCurlTransportReady());destroys++; }
static CURLcode set(CURL *curl,CURLoption option,...) {
    assert(curl==(CURL *)1 && !strcmp(expectedProfile,"impit465") && !SHDWCurlTransportReady());
    sets++;va_list args;va_start(args,option);
    if(option<CURLOPTTYPE_OBJECTPOINT) {
        long value=va_arg(args,long);
        switch(option) {
            case CURLOPT_TLS_KEY_SHARES_LIMIT: assert(value==2);break;
            case CURLOPT_SSLVERSION: assert(value==(CURL_SSLVERSION_TLSv1_2|CURL_SSLVERSION_MAX_TLSv1_3));break;
            case CURLOPT_SSL_PERMUTE_EXTENSIONS: case CURLOPT_SSL_ENABLE_TICKET: assert(value==0);break;
            case CURLOPT_TLS_GREASE: case CURLOPT_HTTP2_NO_PRIORITY: assert(value==1);break;
            case CURLOPT_HTTP2_WINDOW_UPDATE: assert(value==10420225);break;
            default: assert(!"unexpected profile long option");
        }
    } else {
        const char *value=va_arg(args,const char *);assert(value);
        switch(option) {
            case CURLOPT_SSL_CIPHER_LIST: assert(strstr(value,"TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:")==value);break;
            case CURLOPT_SSL_EC_CURVES: assert(!strcmp(value,"X25519MLKEM768:X25519:P-256:P-384:P-521"));break;
            case CURLOPT_SSL_SIG_HASH_ALGS: assert(strstr(value,"rsa_pss_rsae_sha384:rsa_pss_rsae_sha384:"));break;
            case CURLOPT_TLS_EXTENSION_ORDER: assert(!strcmp(value,"0-23-65281-10-11-16-5-13-18-51-45-43-27"));break;
            case CURLOPT_SSL_CERT_COMPRESSION: assert(!strcmp(value,"zlib"));break;
            case CURLOPT_HTTP2_SETTINGS: assert(!strcmp(value,"2:0;3:100;4:2097152;9:1"));break;
            case CURLOPT_HTTP2_PSEUDO_HEADERS_ORDER: assert(!strcmp(value,"msap"));break;
            default: assert(!"unexpected profile string option");
        }
    }
    va_end(args);
    return sets==failAt ? CURLE_UNKNOWN_OPTION : CURLE_OK;
}
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
    [callerProfile setString:@"changed-after-snapshot"];
    for (NSString *profile in @[@"safari172_ios",@"safari180_ios",@"safari184_ios",@"impit465"])
        SHDWCurlTransportPrepareProfile(profile);
    reentries++;
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
    if(argc>2 && *argv[2]) missing=argv[2];
    if(argc>3) expectedProfile=argv[3];
    if(argc>4) failAt=(unsigned)strtoul(argv[4],NULL,10);
    assert(!SHDWCurlTransportReady());
    for(id profile in @[NSNull.null,@"native",@"unknown",@"",@"safari184_ios\n"]) {
        SHDWCurlTransportPrepareProfile(profile);assert(!loads && !SHDWCurlTransportReady());
    }
    SHDWCurlTransportPrepareProfile(nil);assert(!loads);
    callerProfile=[@(expectedProfile) mutableCopy];
    SHDWCurlTransportPrepareProfile(callerProfile);
    assert(loads==1 && reentries==1);
    assert([callerProfile isEqual:@"changed-after-snapshot"]);
    assert([transportProfile isEqual:@(expectedProfile)]);
    BOOL expected=!strcmp(mode,"success");assert(SHDWCurlTransportReady()==expected);
    if(expected) assert(lookups==10 && initializations==1 && creates==1 && probes==1 && destroys==1);
    if(missing) assert(!initializations && !creates && !probes && !destroys);
    if(!strcmp(mode,"init")) assert(initializations==1 && !creates && !probes && !destroys);
    if(!strcmp(mode,"create")) assert(initializations==1 && creates==1 && !probes && !destroys);
    if(!strcmp(mode,"preset")) assert(initializations==1 && creates==1 && probes==1 && destroys==1);
    if(!strcmp(mode,"load")) assert(!lookups && !initializations);
    if(!strcmp(mode,"option")) assert(sets==failAt && probes==1 && destroys==1);
    if(expected && !strcmp(expectedProfile,"impit465")) assert(sets==14);
    unsigned beforeLookups=lookups,beforeInitializations=initializations,beforeCreates=creates,beforeProbes=probes;
    for(unsigned attempt=0;attempt<3;attempt++)
        for(NSString *profile in @[@"safari172_ios",@"safari180_ios",@"safari184_ios",@"impit465"])
            SHDWCurlTransportPrepareProfile(profile);
    SHDWCurlTransportPrepareProfile(@"native");
    assert(loads==1 && reentries==1 && lookups==beforeLookups && initializations==beforeInitializations && creates==beforeCreates && probes==beforeProbes);
    assert(SHDWCurlTransportReady()==expected && [transportProfile isEqual:@(expectedProfile)]);
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
    for profile in ("safari172_ios", "safari180_ios", "safari184_ios", "impit465"):
        for mode in ("success", "load", "init", "create", "preset"):
            subprocess.run([str(binary), mode, "", profile], check=True, timeout=20)
        for symbol in ("curl_global_init", "curl_easy_init", "curl_easy_impersonate", "curl_easy_setopt",
                       "curl_easy_perform", "curl_easy_getinfo", "curl_easy_cleanup", "curl_slist_append",
                       "curl_slist_free_all", "curl_easy_strerror"):
            subprocess.run([str(binary), "missing", symbol, profile], check=True, timeout=20)
    for option in range(1, 15):
        subprocess.run([str(binary), "option", "", "impit465", str(option)], check=True, timeout=20)
    print("curl initialization: all four profiles, immutable profile freeze, reentry, ready publication and every load/init/preset/custom-option refusal passed")
