#include "../src/Transport/CurlReference.h"
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

/* Standalone live probe; does not change Shadow's transport selection. */
int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: %s library baseline|safari187_ios output.json\n", argv[0]);
        return 2;
    }
    int custom = !strcmp(argv[2], "safari187_ios");
    if (!custom && strcmp(argv[2], "baseline")) return 2;
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) { fprintf(stderr, "%s\n", dlerror()); return 2; }
    CURLcode (*initialize)(long) = dlsym(library, "curl_global_init");
    CURL *(*create)(void) = dlsym(library, "curl_easy_init");
    CURLcode (*impersonate)(CURL *, const char *, int) = dlsym(library, "curl_easy_impersonate");
    CURLcode (*set)(CURL *, CURLoption, ...) = dlsym(library, "curl_easy_setopt");
    CURLcode (*perform)(CURL *) = dlsym(library, "curl_easy_perform");
    void (*cleanup)(CURL *) = dlsym(library, "curl_easy_cleanup");
    if (!initialize || !create || !impersonate || !set || !perform || !cleanup || initialize(CURL_GLOBAL_DEFAULT)) return 2;
    CURL *curl = create();
    if (!curl) return 2;
    FILE *output = fopen(argv[3], "wb");
    if (!output) { cleanup(curl); return 2; }
    CURLcode result = SHDWCurlApplyProfile(curl, custom ? "safari187_ios" : "safari184_ios", impersonate, set);
#define SET(option, value) do { if (result == CURLE_OK) result = set(curl, option, value); } while (0)
    SET(CURLOPT_URL, "https://tls.peet.ws/api/all");
    SET(CURLOPT_PROXY, "");
    SET(CURLOPT_SSL_VERIFYPEER, 1L);
    SET(CURLOPT_SSL_VERIFYHOST, 2L);
    SET(CURLOPT_TIMEOUT, 30L);
    SET(CURLOPT_WRITEDATA, output);
    SET(CURLOPT_USERAGENT, "ShadowTransportReferenceProbe/1.0");
    if (result == CURLE_OK) result = perform(curl);
    fprintf(stderr, "profile=%s curl_result=%d\n", argv[2], result);
    int outputFailed = ferror(output);
    if (fclose(output)) outputFailed = 1;
    cleanup(curl);
    return result == CURLE_OK && !outputFailed ? 0 : 1;
}
