#import "CurlTransport.h"
#import "../../Transport/Profiles.h"
#import <Shadow/JBPath.h>

#if SHADOW_CURL_IMPERSONATE
#import "../../Transport/NativeTLS.h"
#import "../../Transport/NativeHTTP2.h"
#include "../../Transport/CurlReference.h"
#include "../../Transport/CurlDiagnostics.h"
#include <dlfcn.h>

static unsigned transportReady;
static NSString *transportProfile;
static struct {
    CURLcode (*initialize)(long);
    CURL *(*create)(void);
    CURLcode (*impersonate)(CURL *, const char *, int);
    CURLcode (*set)(CURL *, CURLoption, ...);
    void (*destroy)(CURL *);
} engine;

void SHDWCurlTransportPrepareProfile(NSString *profile) {
    if (!SHDWTransportProfileIsSupported(profile)) return;
    NSString *selectedProfile = [profile copy];
    if (!SHDWTransportProfileIsSupported(selectedProfile)) return;
    static unsigned attempted;
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&attempted, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    transportProfile = selectedProfile;
    NSString *library = JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib");
    void *image = dlopen(library.fileSystemRepresentation, RTLD_NOW | RTLD_LOCAL);
    if (!image) return;
#define SHDW_CURL_SYMBOL(field, name) engine.field = dlsym(image, name); if (!engine.field) return
    SHDW_CURL_SYMBOL(initialize, "curl_global_init");
    SHDW_CURL_SYMBOL(create, "curl_easy_init");
    SHDW_CURL_SYMBOL(impersonate, "curl_easy_impersonate");
    SHDW_CURL_SYMBOL(set, "curl_easy_setopt");
    SHDW_CURL_SYMBOL(destroy, "curl_easy_cleanup");
#undef SHDW_CURL_SYMBOL
    const char *required[] = {
        "curl_shadow_connect_only_enable_external_io",
        "curl_shadow_connect_only_set_native_verify", "curl_shadow_connect_only_get_verification_snapshot",
        "curl_shadow_connect_only_set_transport", "curl_shadow_connect_only_get_io_state",
        "curl_shadow_connect_only_shutdown"
    };
    for (size_t index = 0; index < sizeof(required) / sizeof(required[0]); index++)
        if (!dlsym(image, required[index])) return;
    if (engine.initialize(CURL_GLOBAL_DEFAULT) != CURLE_OK) return;
    CURL *probe = engine.create(); if (!probe) return;
    BOOL available = SHDWCurlApplyProfile(probe, transportProfile.UTF8String, engine.impersonate, engine.set) == CURLE_OK;
    engine.destroy(probe);
    if (!available) return;
    BOOL http2Installed = SHDWNativeHTTP2Prepare(transportProfile);
    SHDWCurlTrace(@"transport.nativeHTTP2.install", nil, @{@"installed":@(http2Installed), @"profile":transportProfile});
    if (!http2Installed) return;
    BOOL installed = SHDWNativeTLSPrepare(transportProfile, library, JBPath(@"/etc/ssl/cert.pem"));
    if (installed) {
        SHDWNativeHTTP2Activate();
        __atomic_store_n(&transportReady, 1, __ATOMIC_RELEASE);
    }
    SHDWCurlTrace(@"transport.nativeTLS.install", nil,
        @{@"installed":@(installed), @"profile":transportProfile});
}
BOOL SHDWCurlTransportReady(void) { return __atomic_load_n(&transportReady, __ATOMIC_ACQUIRE) != 0; }
void SHDWCurlTransportTraceRequest(NSURLRequest *request, NSString *stage, NSString *reason) {
    SHDWCurlTrace(stage, request, @{@"reason":reason ?: @"", @"ready":@(SHDWCurlTransportReady()),
        @"profile":transportProfile ?: @"native"});
}
#else
void SHDWCurlTransportPrepareProfile(NSString *profile) { (void)profile; }
BOOL SHDWCurlTransportReady(void) { return NO; }
void SHDWCurlTransportTraceRequest(NSURLRequest *request, NSString *stage, NSString *reason) {
    (void)request; (void)stage; (void)reason;
}
#endif
