#pragma once
#include <curl/curl.h>
#include <string.h>

/* Reference: https://github.com/apify/impit/issues/450 (OS/WKWebView scope unverified). */
static inline CURLcode SHDWCurlApplyProfile(CURL *curl, const char *profile,
        CURLcode (*impersonate)(CURL *, const char *, int),
        CURLcode (*set)(CURL *, CURLoption, ...)) {
    int custom = !strcmp(profile, "impit465");
    CURLcode result = impersonate(curl, custom ? "safari184_ios" : profile, 0);
#define SET(option, value) do { if (result == CURLE_OK) { result = set(curl, option, value);  } } while (0)
    if (custom) {
        SET(CURLOPT_SSL_CIPHER_LIST,
            "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:"
            "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256:"
            "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256:TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384:"
            "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256:"
            "TLS_ECDHE_ECDSA_WITH_AES_256_CBC_SHA:TLS_ECDHE_ECDSA_WITH_AES_128_CBC_SHA:"
            "TLS_ECDHE_RSA_WITH_AES_256_CBC_SHA:TLS_ECDHE_RSA_WITH_AES_128_CBC_SHA:"
            "TLS_RSA_WITH_AES_256_GCM_SHA384:TLS_RSA_WITH_AES_128_GCM_SHA256:"
            "TLS_RSA_WITH_AES_256_CBC_SHA:TLS_RSA_WITH_AES_128_CBC_SHA:"
            "TLS_ECDHE_ECDSA_WITH_3DES_EDE_CBC_SHA:TLS_ECDHE_RSA_WITH_3DES_EDE_CBC_SHA:TLS_RSA_WITH_3DES_EDE_CBC_SHA");
        SET(CURLOPT_SSL_EC_CURVES, "X25519MLKEM768:X25519:P-256:P-384:P-521");
        SET(CURLOPT_TLS_KEY_SHARES_LIMIT, 2L);
        SET(CURLOPT_SSLVERSION, (long)(CURL_SSLVERSION_TLSv1_2 | CURL_SSLVERSION_MAX_TLSv1_3));
        SET(CURLOPT_SSL_SIG_HASH_ALGS, "ecdsa_secp256r1_sha256:rsa_pss_rsae_sha256:rsa_pkcs1_sha256:ecdsa_secp384r1_sha384:rsa_pss_rsae_sha384:rsa_pss_rsae_sha384:rsa_pkcs1_sha384:rsa_pss_rsae_sha512:rsa_pkcs1_sha512:rsa_pkcs1_sha1");
        SET(CURLOPT_TLS_EXTENSION_ORDER, "0-23-65281-10-11-16-5-13-18-51-45-43-27");
        SET(CURLOPT_SSL_PERMUTE_EXTENSIONS, 0L);
        SET(CURLOPT_TLS_GREASE, 1L);
        SET(CURLOPT_SSL_ENABLE_TICKET, 0L);
        SET(CURLOPT_SSL_CERT_COMPRESSION, "zlib");
        SET(CURLOPT_HTTP2_SETTINGS, "2:0;3:100;4:2097152;9:1");
        SET(CURLOPT_HTTP2_WINDOW_UPDATE, 10420225L);
        SET(CURLOPT_HTTP2_PSEUDO_HEADERS_ORDER, "msap");
        SET(CURLOPT_HTTP2_NO_PRIORITY, 1L);
    }
#undef SET
    return result;
}
