#pragma once
#include <stddef.h>
#include <curl/curl.h>

typedef struct SHDWExternalTLS SHDWExternalTLS;
typedef CURLcode (*SHDWExternalTLSReadCallback)(void *context, void *bytes,
                                              size_t capacity, size_t *count);
typedef CURLcode (*SHDWExternalTLSWriteCallback)(void *context, const void *bytes,
                                               size_t length, size_t *count);
enum { SHDWExternalTLSWantRead = 1, SHDWExternalTLSWantWrite = 2 };
enum { SHDWExternalTLSSentShutdown = 1, SHDWExternalTLSReceivedShutdown = 2 };

SHDWExternalTLS *SHDWExternalTLSCreate(const char *library, const char *host,
    unsigned port, const char *profile, const char *ca, CURLcode *error);
CURLcode SHDWExternalTLSSetTransport(SHDWExternalTLS *engine,
    SHDWExternalTLSReadCallback read, SHDWExternalTLSWriteCallback write,
    void *context);
CURLcode SHDWExternalTLSStep(SHDWExternalTLS *engine);
CURLcode SHDWExternalTLSIOState(SHDWExternalTLS *engine, int *need, int *shutdown);
CURLcode SHDWExternalTLSWrite(SHDWExternalTLS *engine, const void *bytes,
    size_t length, size_t *count);
CURLcode SHDWExternalTLSRead(SHDWExternalTLS *engine, void *bytes,
    size_t capacity, size_t *count);
CURLcode SHDWExternalTLSShutdown(SHDWExternalTLS *engine, int *complete);
CURLcode SHDWExternalTLSUseNativeVerification(SHDWExternalTLS *engine);
int SHDWExternalTLSVerificationPending(SHDWExternalTLS *engine);
CURLcode SHDWExternalTLSVerificationFacts(SHDWExternalTLS *engine,
    const char **alpn, unsigned *version, unsigned *cipher,
    int (*certificate)(const unsigned char *, size_t, void *), void *context);
CURLcode SHDWExternalTLSCompleteVerification(SHDWExternalTLS *engine, int accepted);
void SHDWExternalTLSFree(SHDWExternalTLS *engine);
const char *SHDWExternalTLSError(SHDWExternalTLS *engine);
const char *SHDWExternalTLSTrace(SHDWExternalTLS *engine);
