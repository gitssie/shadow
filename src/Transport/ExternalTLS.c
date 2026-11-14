#include "ExternalTLS.h"
#include "DiagnosticsConfig.h"
#include "CurlReference.h"
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct SHDWExternalTLS {
#if SHDW_TRANSPORT_DIAGNOSTICS
  char trace[4096];
#endif
  char error[CURL_ERROR_SIZE], verificationALPN[256];
  void *image;
  CURL *easy;
  CURLM *multi;
  int added, finished, transportSet, nativeVerify, verifyPending, verifyDecision;
  CURLcode result;
  CURL *(*easyInit)(void);
  CURLcode (*set)(CURL *, CURLoption, ...);
  CURLcode (*profile)(CURL *, const char *, int);
  void (*easyFree)(CURL *);
  CURLM *(*multiInit)(void);
  CURLMcode (*multiAdd)(CURLM *, CURL *);
  CURLMcode (*multiRemove)(CURLM *, CURL *);
  CURLMcode (*multiRun)(CURLM *, int *);
  CURLMsg *(*multiInfo)(CURLM *, int *);
  CURLMcode (*multiFree)(CURLM *);
  CURLcode (*send)(CURL *, const void *, size_t, size_t *);
  CURLcode (*recv)(CURL *, void *, size_t, size_t *);
  CURLcode (*externalIO)(CURL *);
  CURLcode (*setTransport)(CURL *, SHDWExternalTLSReadCallback,
                           SHDWExternalTLSWriteCallback, void *);
  CURLcode (*setNativeVerify)(CURL *, int (*)(void *), void *);
  CURLcode (*verifyFacts)(CURL *, char *, size_t, unsigned *, unsigned *,
      int (*)(const unsigned char *, size_t, void *), void *);
  CURLcode (*shutdown)(CURL *, int *);
  CURLcode (*ioState)(CURL *, int *, int *);
};

#if SHDW_TRANSPORT_DIAGNOSTICS
static int traceEngine(CURL *curl, curl_infotype type, char *data,
                       size_t size, void *context) {
  (void)curl;
  int saved = errno;
  SHDWExternalTLS *e = context;
  if (type == CURLINFO_TEXT && size < sizeof(e->trace) &&
      (memmem(data, size, "ossl_", 5) || memmem(data, size, "recv", 4) ||
       memmem(data, size, "closed", 6))) {
    size_t used = strlen(e->trace);
    if (used + size >= sizeof(e->trace)) used = 0;
    memcpy(e->trace + used, data, size);
    e->trace[used + size] = 0;
  }
  errno = saved;
  return 0;
}

#endif

void SHDWExternalTLSFree(SHDWExternalTLS *e) {
  if (!e) return;
  if (e->multi && e->easy && e->added) e->multiRemove(e->multi, e->easy);
  if (e->easy) e->easyFree(e->easy);
  if (e->multi) e->multiFree(e->multi);
  if (e->image) dlclose(e->image);
  free(e);
}

SHDWExternalTLS *SHDWExternalTLSCreate(const char *library, const char *host,
    unsigned port, const char *profile, const char *ca, CURLcode *error) {
  if (error) *error = CURLE_BAD_FUNCTION_ARGUMENT;
  if (!library || !host || !host[0] || !port || port > 65535 || !profile || !ca)
    return NULL;
  SHDWExternalTLS *e = calloc(1, sizeof(*e));
  if (!e) {
    if (error) *error = CURLE_OUT_OF_MEMORY;
    return NULL;
  }
  e->result = CURLE_AGAIN;
  // BoringSSL registers thread-exit callbacks that outlive individual handles.
  e->image = dlopen(library, RTLD_NOW | RTLD_LOCAL | RTLD_NODELETE);
  CURLcode r = CURLE_FAILED_INIT;
  if (!e->image) goto fail;
#define LOAD(field, name) do { \
  *(void **)&e->field = dlsym(e->image, name); \
  if (!e->field) goto fail; \
} while (0)
  LOAD(ioState, "curl_shadow_connect_only_get_io_state");
  LOAD(setTransport, "curl_shadow_connect_only_set_transport");
  LOAD(shutdown, "curl_shadow_connect_only_shutdown");
  LOAD(setNativeVerify, "curl_shadow_connect_only_set_native_verify");
  LOAD(verifyFacts, "curl_shadow_connect_only_get_verification_snapshot");
  LOAD(externalIO, "curl_shadow_connect_only_enable_external_io");
  LOAD(easyInit, "curl_easy_init");
  LOAD(set, "curl_easy_setopt");
  LOAD(profile, "curl_easy_impersonate");
  LOAD(easyFree, "curl_easy_cleanup");
  LOAD(multiInit, "curl_multi_init");
  LOAD(multiAdd, "curl_multi_add_handle");
  LOAD(multiRemove, "curl_multi_remove_handle");
  LOAD(multiRun, "curl_multi_perform");
  LOAD(multiInfo, "curl_multi_info_read");
  LOAD(multiFree, "curl_multi_cleanup");
  LOAD(send, "curl_easy_send");
  LOAD(recv, "curl_easy_recv");
#undef LOAD
#if SHDW_TRANSPORT_DIAGNOSTICS
  CURLcode (*traceConfig)(const char *) = dlsym(e->image, "curl_global_trace");
  if (traceConfig) traceConfig("ssl,tcp");
#endif
  e->easy = e->easyInit();
  e->multi = e->multiInit();
  if (!e->easy || !e->multi) goto fail;
  char url[1024];
  int n = snprintf(url, sizeof(url), "https://%s:%u/", host, port);
  if (n < 0 || (size_t)n >= sizeof(url)) {
    r = CURLE_BAD_FUNCTION_ARGUMENT;
    goto fail;
  }
  r = SHDWCurlApplyProfile(e->easy, profile, e->profile, e->set);
  if (r) goto fail;
#define SET(option, value) do { \
  r = e->set(e->easy, option, value); \
  if (r) goto fail; \
} while (0)
  SET(CURLOPT_VERBOSE, (long)SHDW_TRANSPORT_DIAGNOSTICS);
#if SHDW_TRANSPORT_DIAGNOSTICS
  SET(CURLOPT_DEBUGFUNCTION, traceEngine);
  SET(CURLOPT_DEBUGDATA, e);
#endif
  SET(CURLOPT_ERRORBUFFER, e->error);
  SET(CURLOPT_URL, url);
  SET(CURLOPT_CONNECT_ONLY, 1L);
  SET(CURLOPT_PROXY, "");
  SET(CURLOPT_CAINFO, ca);
  SET(CURLOPT_SSL_VERIFYPEER, 1L);
  SET(CURLOPT_SSL_VERIFYHOST, 2L);
  SET(CURLOPT_NOSIGNAL, 1L);
  SET(CURLOPT_TIMEOUT_MS, 0L);
#undef SET
  r = e->externalIO(e->easy);
  if (r) goto fail;
  if (error) *error = CURLE_OK;
  return e;
fail:
  if (error) *error = r;
  SHDWExternalTLSFree(e);
  return NULL;
}

CURLcode SHDWExternalTLSSetTransport(SHDWExternalTLS *e,
    SHDWExternalTLSReadCallback read, SHDWExternalTLSWriteCallback write,
    void *context) {
  if (!e || !read || !write || e->added || e->transportSet)
    return CURLE_BAD_FUNCTION_ARGUMENT;
  CURLcode r = e->setTransport(e->easy, read, write, context);
  if (!r) e->transportSet = 1;
  return r;
}

CURLcode SHDWExternalTLSStep(SHDWExternalTLS *e) {
  if (!e || !e->transportSet) return CURLE_BAD_FUNCTION_ARGUMENT;
  if (e->finished) return e->result;
  if (!e->added) {
    if (e->multiAdd(e->multi, e->easy) != CURLM_OK) {
      e->finished = 1;
      return e->result = CURLE_FAILED_INIT;
    }
    e->added = 1;
  }
  int running = 0;
  CURLMcode m;
  do { m = e->multiRun(e->multi, &running); } while (m == CURLM_CALL_MULTI_PERFORM);
  if (m != CURLM_OK) {
    e->finished = 1;
    return e->result = CURLE_FAILED_INIT;
  }
  int left;
  CURLMsg *message;
  while ((message = e->multiInfo(e->multi, &left))) {
    if (message->msg == CURLMSG_DONE && message->easy_handle == e->easy) {
      e->finished = 1;
      e->result = message->data.result;
    }
  }
  return e->finished ? e->result : CURLE_AGAIN;
}

CURLcode SHDWExternalTLSWrite(SHDWExternalTLS *e, const void *bytes,
                              size_t length, size_t *count) {
  if (!e || !count || (!bytes && length)) return CURLE_BAD_FUNCTION_ARGUMENT;
  *count = 0;
  if (!length) return CURLE_OK;
  if (!e->finished) return CURLE_AGAIN;
  if (e->result) return e->result;
  return e->send(e->easy, bytes, length, count);
}

CURLcode SHDWExternalTLSRead(SHDWExternalTLS *e, void *bytes,
                             size_t capacity, size_t *count) {
  if (!e || !count || (!bytes && capacity)) return CURLE_BAD_FUNCTION_ARGUMENT;
  *count = 0;
  if (!capacity) return CURLE_OK;
  if (!e->finished) return CURLE_AGAIN;
  if (e->result) return e->result;
  return e->recv(e->easy, bytes, capacity, count);
}

CURLcode SHDWExternalTLSIOState(SHDWExternalTLS *e, int *need, int *shutdown) {
  if (!need || !shutdown) return CURLE_BAD_FUNCTION_ARGUMENT;
  *need = *shutdown = 0;
  if (!e || !e->easy) return CURLE_BAD_FUNCTION_ARGUMENT;
  return e->ioState(e->easy, need, shutdown);
}

CURLcode SHDWExternalTLSShutdown(SHDWExternalTLS *e, int *complete) {
  if (!e || !complete) return CURLE_BAD_FUNCTION_ARGUMENT;
  *complete = 0;
  if (!e->finished) return CURLE_AGAIN;
  if (e->result) return e->result;
  return e->shutdown(e->easy, complete);
}

static int nativeVerification(void *context) {
  SHDWExternalTLS *e = context;
  if (!e->verifyDecision) e->verifyPending = 1;
  return e->verifyDecision;
}

CURLcode SHDWExternalTLSUseNativeVerification(SHDWExternalTLS *e) {
  if (!e || e->added || e->nativeVerify) return CURLE_BAD_FUNCTION_ARGUMENT;
  CURLcode r = e->setNativeVerify(e->easy, nativeVerification, e);
  if (!r) e->nativeVerify = 1;
  return r;
}

int SHDWExternalTLSVerificationPending(SHDWExternalTLS *e) {
  return e && e->nativeVerify && e->verifyPending;
}

CURLcode SHDWExternalTLSVerificationFacts(SHDWExternalTLS *e, const char **alpn,
    unsigned *version, unsigned *cipher,
    int (*certificate)(const unsigned char *, size_t, void *), void *context) {
  if (!e || !alpn || !version || !cipher || !certificate)
    return CURLE_BAD_FUNCTION_ARGUMENT;
  if (!e->verifyPending) return CURLE_AGAIN;
  CURLcode r = e->verifyFacts(e->easy, e->verificationALPN,
      sizeof(e->verificationALPN), version, cipher, certificate, context);
  *alpn = e->verificationALPN[0] ? e->verificationALPN : NULL;
  return r;
}

CURLcode SHDWExternalTLSCompleteVerification(SHDWExternalTLS *e, int accepted) {
  if (!e || !e->verifyPending || e->verifyDecision)
    return CURLE_BAD_FUNCTION_ARGUMENT;
  e->verifyDecision = accepted ? 1 : -1;
  e->verifyPending = 0;
  return CURLE_OK;
}

const char *SHDWExternalTLSError(SHDWExternalTLS *e) {
  return e ? e->error : "";
}

const char *SHDWExternalTLSTrace(SHDWExternalTLS *e) {
#if SHDW_TRANSPORT_DIAGNOSTICS
  return e ? e->trace : "";
#else
  (void)e;
  return "";
#endif
}
