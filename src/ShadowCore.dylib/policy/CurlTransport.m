#import "CurlTransport.h"
#import "../../Transport/Profiles.h"
#import <Shadow/JBPath.h>

#if SHADOW_CURL_IMPERSONATE
#import "../../Transport/NativeTLS.h"
#import "../../Transport/NativeHTTP2.h"
#import "../../Transport/ProfileConfiguration.h"
#include "../../Transport/CurlDiagnostics.h"

static unsigned transportReady;
static NSString *transportProfile;

void SHDWCurlTransportPrepareProfile(NSString *profile) {
    if (!SHDWTransportProfileIsSupported(profile)) return;
    NSString *selectedProfile = [profile copy];
    if (!SHDWTransportProfileIsSupported(selectedProfile)) return;
    static unsigned attempted;
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&attempted, &expected, 1, NO, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    transportProfile = selectedProfile;
    NSString *library = JBPath(@"/usr/lib/shadow/curl/libcurl-impersonate.4.dylib");
    SHDWH2Configuration http2 = {0};
    if (!SHDWTransportCopyHTTP2Configuration(transportProfile, &http2)) return;
    BOOL http2Installed = SHDWNativeHTTP2Prepare(&http2);
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
