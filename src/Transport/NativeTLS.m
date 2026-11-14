#import "NativeTLS.h"
#if SHADOW_CURL_IMPERSONATE
#import "../ShadowCore.dylib/SHDWHookSession.h"
#include "ExternalTLS.h"
#include "CurlDiagnostics.h"
#import <Network/Network.h>
#import <Security/Security.h>
#include <dlfcn.h>
#include <netinet/in.h>
#import <objc/runtime.h>
#include <ptrauth.h>
#include <string.h>
#include <sys/socket.h>
#include <unwind.h>

// Preserve the native connection, HTTP implementation and verifier while
// replacing only the TLS record engine for supported client sessions.
typedef uint64_t (*SessionSetBIO)(void *, void *, void *);
typedef uint64_t (*SessionHandshake)(void *);
typedef uint64_t (*NativeOuterHandshake)(id);
typedef int (*NativeBIORead)(void *, void *, int);
typedef int (*NativeBIOWrite)(void *, const void *, int);
static void *originals[10];
static NativeBIORead appleBIORead;
static NativeBIOWrite appleBIOWrite;
static int (*appleBIOShouldRead)(const void *);
static int (*appleBIOShouldWrite)(const void *);
static void *(*findEnclosing)(void *);
static Ivar legacyIvar, ownerIvar, ownerContextIvar, ownerBIOIvar,
    handshakeIvar;
static Ivar nameIvar, addressIvar, stateIvar, metadataIvar, sslIvar, verifyIvar,
    verifyQueueIvar, clientQueueIvar;
static Ivar readIvar, writeIvar;
static Class ctxClass, ownerClass;
static char stateKey;
static char factsKey;
static NSObject *lock;
static NSMapTable *sessions;
static NSString *configuredProfile, *configuredLibrary, *configuredCA;
static BOOL adapterEnabled, installationAttempted;
static void *appleLibrary;
static uint64_t (*isServerMode)(nw_parameters_t);
static uint64_t (*isDTLS)(void *);
static Ivar parametersIvar, identityIvar;
static NSMapTable *sslSessions;
typedef sec_trust_t (*NativeCopyTrust)(sec_protocol_metadata_t)
    __attribute__((ns_returns_retained));
// The hook session publishes these persistent cells before patching code.
// Authenticate each continuation at its call boundary, including installation.
#define ORIGINAL(index, type)                                                  \
  ((type)ptrauth_sign_unauthenticated(                                         \
      ptrauth_strip(originals[index], ptrauth_key_function_pointer),           \
      ptrauth_key_function_pointer, 0))
#define originalSetBIO ORIGINAL(0, SessionSetBIO)
#define originalGetError ORIGINAL(1, int (*)(void *, int))
#define originalShutdown ORIGINAL(2, int (*)(void *))
#define originalDisconnect ORIGINAL(3, uint64_t (*)(void *))
#define originalDestroy ORIGINAL(4, void (*)(void *))
#define originalALPN                                                           \
  ORIGINAL(5, __typeof__(&sec_protocol_metadata_get_negotiated_protocol))
#define originalVersion                                                        \
  ORIGINAL(                                                                    \
      6,                                                                       \
      __typeof__(&sec_protocol_metadata_get_negotiated_tls_protocol_version))
#define originalCipher                                                         \
  ORIGINAL(7, __typeof__(&sec_protocol_metadata_get_negotiated_tls_ciphersuite))
#define originalChain                                                          \
  ORIGINAL(8, __typeof__(&sec_protocol_metadata_access_peer_certificate_chain))
#define originalTrust ORIGINAL(9, NativeCopyTrust)
@interface SHDWNativeTLSFacts : NSObject
@property(nonatomic, copy) NSString *alpn;
@property(nonatomic) unsigned version, cipher;
@property(nonatomic, strong) NSArray *chain;
@property(nonatomic, strong) sec_trust_t trust;
@end
@implementation SHDWNativeTLSFacts
@end
@interface SHDWNativeSessionState : NSObject
@property(nonatomic, weak) id owner;
@property(nonatomic, weak) id context;
@property(nonatomic) void *legacy;
@property(nonatomic) void *bio;
@property(nonatomic) SessionHandshake originalHandshake;
@property(nonatomic) NativeOuterHandshake originalOuter;
@property(nonatomic) SHDWExternalTLS *engine;
@property(nonatomic, strong) dispatch_queue_t queue;
@property(nonatomic, strong) NSMutableData *plaintext;
@property(nonatomic) BOOL takeover, ready, verifyStarted, accepted,
    failed, cancelled, closing, verifyCompleted;
@property(nonatomic) int lastError;
@property(nonatomic) void *nativeSSL;
@property(nonatomic, copy) NSString *host, *profile, *library, *ca;
@property(nonatomic) unsigned port;
@property(nonatomic) BOOL declined;
@end
@implementation SHDWNativeSessionState
- (void)dealloc {
  @synchronized(lock) {
    NSValue *k = [NSValue valueWithPointer:_legacy];
    id value = [sessions objectForKey:k];
    if (!value || value == self)
      [sessions removeObjectForKey:k];
    k = [NSValue valueWithPointer:_nativeSSL];
    value = [sslSessions objectForKey:k];
    if (!value || value == self)
      [sslSessions removeObjectForKey:k];
  }
  if (_engine)
    SHDWExternalTLSFree(_engine);
}
@end

static void *pointerIvar(id object, Ivar ivar) {
  void *p = NULL;
  if (object && ivar)
    memcpy(&p, (const char *)(__bridge void *)object + ivar_getOffset(ivar),
           sizeof(p));
  return p;
}
static BOOL encoding(Ivar ivar, const char *expected) {
  return ivar && strcmp(ivar_getTypeEncoding(ivar), expected) == 0;
}
static int nativeState(id context) {
  int value = 5;
  if (context)
    memcpy(&value,
           (const char *)(__bridge void *)context + ivar_getOffset(stateIvar),
           sizeof(value));
  return value;
}
static id decodeContext(void *legacy) {
  // Layout derived from this running class's actual aggregate encoding.
  // Do not use a copied OS-version offset or cast this object to SSL.
  if (!legacy)
    return nil;
  struct RuntimeLegacy {
    uint32_t tag;
    void *object;
  } value;
  const char *type = ivar_getTypeEncoding(legacyIvar);
  NSUInteger size = 0, alignment = 0;
  if (!type || strcmp(type, "^{boringssl_legacy_ctx=I^v}"))
    return nil;
  NSGetSizeAndAlignment(type + 1, &size, &alignment);
  if (size != sizeof(value) || alignment != _Alignof(struct RuntimeLegacy))
    return nil;
  memcpy(&value, legacy, sizeof(value));
  if (value.tag != (uint32_t)-1252936367 || !value.object)
    return nil;
  id context = (__bridge id)value.object;
  if (![context isKindOfClass:ctxClass] ||
      pointerIvar(context, legacyIvar) != legacy)
    return nil;
  return context;
}
static SHDWNativeSessionState *lookup(void *legacy) {
  @synchronized(lock) {
    return [sessions objectForKey:[NSValue valueWithPointer:legacy]];
  }
}
static SHDWNativeTLSFacts *facts(sec_protocol_metadata_t m) {
  return objc_getAssociatedObject(m, &factsKey);
}
static const char *actualALPN(sec_protocol_metadata_t m) {
  SHDWNativeTLSFacts *f = facts(m);
  return f ? f.alpn.UTF8String : originalALPN(m);
}
static tls_protocol_version_t actualVersion(sec_protocol_metadata_t m) {
  SHDWNativeTLSFacts *f = facts(m);
  return f ? (tls_protocol_version_t)f.version : originalVersion(m);
}
static tls_ciphersuite_t actualCipher(sec_protocol_metadata_t m) {
  SHDWNativeTLSFacts *f = facts(m);
  return f ? (tls_ciphersuite_t)f.cipher : originalCipher(m);
}
static bool actualChain(sec_protocol_metadata_t m,
                        void (^callback)(sec_certificate_t)) {
  SHDWNativeTLSFacts *f = facts(m);
  if (!f)
    return originalChain(m, callback);
  if (!callback)
    return false;
  for (id c in f.chain)
    callback(sec_certificate_create((__bridge SecCertificateRef)c));
  return f.chain.count > 0;
}
static sec_trust_t actualTrust(sec_protocol_metadata_t m)
    __attribute__((ns_returns_retained));
static sec_trust_t actualTrust(sec_protocol_metadata_t m) {
  SHDWNativeTLSFacts *f = facts(m);
  return f ? f.trust : originalTrust(m);
}
static int actualError(void *ssl, int result) {
  SHDWNativeSessionState *s;
  @synchronized(lock) {
    s = [sslSessions objectForKey:[NSValue valueWithPointer:ssl]];
  }
  return s && s.takeover ? s.lastError : originalGetError(ssl, result);
}
static int collectDER(const unsigned char *bytes, size_t length,
                      void *context) {
  NSMutableArray *a = (__bridge id)context;
  SecCertificateRef c = SecCertificateCreateWithData(
      NULL, (__bridge CFDataRef)[NSData dataWithBytes:bytes length:length]);
  if (!c)
    return 0;
  [a addObject:CFBridgingRelease(c)];
  return 1;
}
static void removePrefix(NSMutableData *d, size_t n) {
  if (n)
    [d replaceBytesInRange:NSMakeRange(0, n) withBytes:NULL length:0];
}
static void traceTLS(SHDWNativeSessionState *s, NSString *stage, CURLcode code) {
  SHDWCurlTrace(stage, nil, @{@"host":s.host ?: @"", @"curlCode":@(code),
    @"session":[NSString stringWithFormat:@"%p", s.legacy],
    @"ready":@(s.ready), @"verified":@(s.verifyCompleted),
    @"accepted":@(s.accepted), @"error":[NSString stringWithUTF8String:SHDWExternalTLSError(s.engine)] ?: @"", @"trace": code ? ([NSString stringWithUTF8String:SHDWExternalTLSTrace(s.engine)] ?: @"") : @""});
}
static int nativeWaitError(SHDWNativeSessionState *s, int fallback) {
  int need = 0, shutdown = 0;
  if (SHDWExternalTLSIOState(s.engine, &need, &shutdown) != CURLE_OK)
    return 1;
  if (need & SHDWExternalTLSWantWrite)
    return 3;
  if (need & SHDWExternalTLSWantRead)
    return 2;
  return fallback;
}
static CURLcode transportRead(void *context, void *bytes, size_t length,
                              size_t *count) {
  SHDWNativeSessionState *s = (__bridge SHDWNativeSessionState *)context;
  if (!s || !count || (!bytes && length))
    return CURLE_BAD_FUNCTION_ARGUMENT;
  *count = 0;
  if (!length)
    return CURLE_OK;
  if (!s.bio || (s.cancelled && !s.closing))
    return CURLE_ABORTED_BY_CALLBACK;
  int n = appleBIORead(s.bio, bytes, (int)MIN(length, (size_t)INT_MAX));
  if (n > 0) {
    *count = (size_t)n;
    return CURLE_OK;
  }
  if (appleBIOShouldRead(s.bio) || appleBIOShouldWrite(s.bio))
    return CURLE_AGAIN;
  return n == 0 ? CURLE_OK : CURLE_RECV_ERROR;
}
static CURLcode transportWrite(void *context, const void *bytes, size_t length,
                               size_t *count) {
  SHDWNativeSessionState *s = (__bridge SHDWNativeSessionState *)context;
  if (!s || !count || (!bytes && length))
    return CURLE_BAD_FUNCTION_ARGUMENT;
  *count = 0;
  if (!length)
    return CURLE_OK;
  if (!s.bio || (s.cancelled && !s.closing))
    return CURLE_ABORTED_BY_CALLBACK;
  int n = appleBIOWrite(s.bio, bytes, (int)MIN(length, (size_t)INT_MAX));
  if (n > 0) {
    *count = (size_t)n;
    return CURLE_OK;
  }
  if (appleBIOShouldRead(s.bio) || appleBIOShouldWrite(s.bio))
    return CURLE_AGAIN;
  return CURLE_SEND_ERROR;
}
static BOOL prepareFacts(SHDWNativeSessionState *s) {
  const char *alpn = NULL;
  unsigned version = 0, cipher = 0;
  NSMutableArray *chain = [NSMutableArray new];
  CURLcode r = SHDWExternalTLSVerificationFacts(
      s.engine, &alpn, &version, &cipher, collectDER, (__bridge void *)chain);
  if (r || !version || !cipher || !chain.count)
    return NO;
  SecPolicyRef policy = SecPolicyCreateSSL(true, (__bridge CFStringRef)s.host);
  SecTrustRef trust = NULL;
  OSStatus status = SecTrustCreateWithCertificates((__bridge CFArrayRef)chain,
                                                   policy, &trust);
  CFRelease(policy);
  if (status || !trust)
    return NO;
  SHDWNativeTLSFacts *f = [SHDWNativeTLSFacts new];
  f.alpn = alpn ? [NSString stringWithUTF8String:alpn] : nil;
  f.version = version;
  f.cipher = cipher;
  f.chain = chain;
  f.trust = sec_trust_create(trust);
  CFRelease(trust);
  id ctx = s.context;
  id metadata = ctx ? object_getIvar(ctx, metadataIvar) : nil;
  if (!metadata || !nw_protocol_metadata_is_tls(metadata))
    return NO;
  objc_setAssociatedObject(metadata, &factsKey, f,
                           OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  sec_protocol_verify_t verify = ctx ? object_getIvar(ctx, verifyIvar) : nil;
  dispatch_queue_t queue = ctx ? object_getIvar(ctx, verifyQueueIvar) : nil;
  if (!verify || !queue)
    return NO;

  s.verifyStarted = YES;
  __weak SHDWNativeSessionState *weak = s;
  dispatch_async(queue, ^{
    verify(metadata, f.trust, ^(bool accepted) {
      SHDWNativeSessionState *strong = weak;
      if (!strong)
        return;
      dispatch_async(strong.queue, ^{
        id owner = strong.owner, context = strong.context;
        int stateBefore = nativeState(context);
        if (!owner || !context ||
            pointerIvar(owner, ownerContextIvar) != strong.legacy ||
            strong.cancelled || stateBefore >= 3 || strong.verifyCompleted) {
          return;
        }
        strong.verifyCompleted = YES;
        strong.accepted = accepted;
      traceTLS(strong, @"tls.verify.completed", accepted ? CURLE_OK : CURLE_PEER_FAILED_VERIFICATION);
        CURLcode decision =
            SHDWExternalTLSCompleteVerification(strong.engine, accepted);
        if (decision != CURLE_OK) {
          strong.failed = YES;
          strong.lastError = 1;
        }
        if (strong.originalOuter)
          strong.originalOuter(owner);
      });
    });
  });
  return YES;
}
static uint64_t adapterRead(void *legacy, void *buffer, int length, int peek) {
  SHDWNativeSessionState *s = lookup(legacy);
  if (!s || !s.takeover)
    return (uint64_t)-1;
  if (length <= 0)
    return 0;
  if (!s.ready) {
    s.lastError = 2;
    return (uint64_t)-1;
  }
  CURLcode r;
  if (!s.plaintext.length) {
    NSUInteger capacity = MIN((NSUInteger)length, (NSUInteger)65536);
    NSMutableData *data = [NSMutableData dataWithLength:capacity];
    if (!data) {
      s.lastError = 1;
      return (uint64_t)-1;
    }
    size_t count = 0;
    r = SHDWExternalTLSRead(s.engine, data.mutableBytes, data.length, &count);
    if (r != CURLE_OK && r != CURLE_AGAIN) {
      traceTLS(s, @"tls.read.failed", r);
      s.lastError = 1;
      return (uint64_t)-1;
    }
    if (count) {
      data.length = count;
      [s.plaintext appendData:data];
    } else if (r == CURLE_OK) {
      s.lastError = 6;
      return 0;
    }
  }
  size_t count = MIN((NSUInteger)length, s.plaintext.length);
  if (!count) {
    s.lastError = nativeWaitError(s, 2);
    return (uint64_t)-1;
  }
  if (buffer)
    memcpy(buffer, s.plaintext.bytes, count);
  if (!peek)
    removePrefix(s.plaintext, count);
  s.lastError = 0;
  return count;
}
static uint64_t adapterWrite(void *legacy, const void *bytes, int length) {
  SHDWNativeSessionState *s = lookup(legacy);
  if (!s || !s.takeover)
    return (uint64_t)-1;
  if (length <= 0)
    return 0;
  if (!s.ready) {
    s.lastError = 3;
    return (uint64_t)-1;
  }
  size_t count = 0;
  CURLcode r = SHDWExternalTLSWrite(s.engine, bytes, (size_t)length, &count);
  if (r != CURLE_OK && r != CURLE_AGAIN) {
    traceTLS(s, @"tls.write.failed", r);
    s.lastError = 1;
    return (uint64_t)-1;
  }
  if (count) {
    s.lastError = 0;
    return count;
  }
  s.lastError = nativeWaitError(s, 3);
  return (uint64_t)-1;
}
static int actualShutdown(void *ssl) {
  SHDWNativeSessionState *s;
  @synchronized(lock) {
    s = [sslSessions objectForKey:[NSValue valueWithPointer:ssl]];
  }
  if (!s || !s.takeover)
    return originalShutdown(ssl);
  if (!s.engine || !s.ready) {
    s.lastError = 0;
    return 1;
  }
  traceTLS(s, @"tls.shutdown.begin", CURLE_OK);
  s.closing = YES;
  int complete = 0;
  CURLcode result = SHDWExternalTLSShutdown(s.engine, &complete);
  s.closing = NO;
  if (result == CURLE_AGAIN) {
    s.lastError = nativeWaitError(s, 3);
    return -1;
  }
  if (result != CURLE_OK) {
    s.lastError = 1;
    return -1;
  }
  if (!complete) {
    int need = 0, shutdown = 0;
    if (SHDWExternalTLSIOState(s.engine, &need, &shutdown) != CURLE_OK) {
      s.lastError = 1;
      return -1;
    }
    if (need & (SHDWExternalTLSWantRead | SHDWExternalTLSWantWrite)) {
      s.lastError = need & SHDWExternalTLSWantWrite ? 3 : 2;
      return -1;
    }
  }
  s.lastError = 0;
  return complete ? 1 : 0;
}
static uint64_t observeDisconnect(void *legacy) {
  SHDWNativeSessionState *s = lookup(legacy);
  if (s && s.takeover) {
    s.cancelled = YES;
  }
  return originalDisconnect(legacy);
}
static void observeDestroy(void *legacy) {
  SHDWNativeSessionState *s = lookup(legacy);
  if (s && s.takeover) {
    s.cancelled = YES;
    if (s.engine) {
      SHDWExternalTLSFree(s.engine);
      s.engine = NULL;
    }
  }
  originalDestroy(legacy);
}
static BOOL clientInfo(SHDWNativeSessionState *s) {
  id context = s.context, owner = s.owner;
  const char *name = pointerIvar(context, nameIvar);
  nw_parameters_t parameters =
      owner ? object_getIvar(owner, parametersIvar) : nil;
  if (!context || !owner || !name || !name[0] || !parameters ||
      isDTLS(s.legacy) || isServerMode(parameters) ||
      object_getIvar(context, identityIvar))
    return NO;
  NSUInteger size = 0;
  NSGetSizeAndAlignment(ivar_getTypeEncoding(addressIvar), &size, NULL);
  if (size < sizeof(struct sockaddr_in) ||
      size > sizeof(struct sockaddr_storage))
    return NO;
  struct sockaddr_storage address = {0};
  memcpy(&address,
         (const char *)(__bridge void *)context + ivar_getOffset(addressIvar),
         size);
  unsigned port = 0;
  if (address.ss_family == AF_INET)
    port = ntohs(((struct sockaddr_in *)&address)->sin_port);
  else if (address.ss_family == AF_INET6)
    port = ntohs(((struct sockaddr_in6 *)&address)->sin6_port);
  if (!port)
    return NO;
  s.host = [NSString stringWithUTF8String:name];
  s.port = port;
  return s.host.length > 0;
}
static uint64_t observeHandshake(void *legacy) {
  SHDWNativeSessionState *s = lookup(legacy);
  if (!s)
    return (uint64_t)-1;
  id owner = s.owner, context = s.context;
  void *pc =
      ptrauth_strip(__builtin_return_address(0), ptrauth_key_return_address);
  void *entry = findEnclosing ? findEnclosing((char *)pc - 4) : NULL;
  Dl_info image = {0};
  BOOL native = entry && dladdr(entry, &image) && image.dli_fname &&
                strstr(image.dli_fname, "libboringssl");
  if (native)
    s.originalOuter = (NativeOuterHandshake)ptrauth_sign_unauthenticated(
        entry, ptrauth_key_function_pointer, 0);
  if (!s.takeover && !s.declined) {
    dispatch_queue_t (*currentQueue)(void) =
        dlsym(RTLD_DEFAULT, "dispatch_get_current_queue");
    s.queue = object_getIvar(owner, clientQueueIvar);
    if (!s.queue && currentQueue)
      s.queue = currentQueue();
    id nativeMetadata = context ? object_getIvar(context, metadataIvar) : nil;
    if (!s.queue || !s.originalOuter || !clientInfo(s) || !nativeMetadata ||
        !nw_protocol_metadata_is_tls(nativeMetadata) ||
        !object_getIvar(context, verifyIvar) ||
        !object_getIvar(context, verifyQueueIvar)) {
      s.declined = YES;
      return s.originalHandshake(legacy);
    }
    @synchronized(lock) {
      s.profile = configuredProfile;
      s.library = configuredLibrary;
      s.ca = configuredCA;
    }
    s.plaintext = [NSMutableData new];
    CURLcode error = CURLE_OK;
    s.engine = SHDWExternalTLSCreate(
        s.library.fileSystemRepresentation, s.host.UTF8String, s.port,
        s.profile.UTF8String, s.ca.fileSystemRepresentation, &error);
    if (!s.engine) {
      s.declined = YES;
      return s.originalHandshake(legacy);
    }
    if (SHDWExternalTLSSetTransport(s.engine, transportRead, transportWrite,
                                    (__bridge void *)s) != CURLE_OK ||
        SHDWExternalTLSUseNativeVerification(s.engine) != CURLE_OK) {
      SHDWExternalTLSFree(s.engine);
      s.engine = NULL;
      s.declined = YES;
      return s.originalHandshake(legacy);
    }
    void *ssl = pointerIvar(context, sslIvar);
    if (!ssl) {
      SHDWExternalTLSFree(s.engine);
      s.engine = NULL;
      s.declined = YES;
      return s.originalHandshake(legacy);
    }
    s.nativeSSL = ssl;
    s.takeover = YES;
    s.lastError = 2;
    void *replacement = ptrauth_sign_unauthenticated(
        ptrauth_strip((void *)adapterRead, ptrauth_key_function_pointer),
        ptrauth_key_function_pointer, 0);
    memcpy((char *)(__bridge void *)owner + ivar_getOffset(readIvar),
           &replacement, sizeof(replacement));
    replacement = ptrauth_sign_unauthenticated(
        ptrauth_strip((void *)adapterWrite, ptrauth_key_function_pointer),
        ptrauth_key_function_pointer, 0);
    memcpy((char *)(__bridge void *)owner + ivar_getOffset(writeIvar),
           &replacement, sizeof(replacement));
    @synchronized(lock) {
      [sslSessions setObject:s forKey:[NSValue valueWithPointer:ssl]];
    }
  }
  if (s.takeover) {
    if (s.failed || s.cancelled)
      return (uint64_t)-1;
    CURLcode result = SHDWExternalTLSStep(s.engine);
    if (result != CURLE_OK && result != CURLE_AGAIN) {
      s.failed = YES;
      s.lastError = 1;
      return (uint64_t)-1;
    }
    if (SHDWExternalTLSVerificationPending(s.engine) && !s.verifyStarted &&
        !prepareFacts(s)) {
      s.failed = YES;
      s.lastError = 1;
      return (uint64_t)-1;
    }
    if (result == CURLE_AGAIN)
      s.lastError = nativeWaitError(s, 2);
    if (result == CURLE_OK) {
      if (!s.verifyCompleted || !s.accepted) {
        s.failed = YES;
        s.lastError = 1;
        return (uint64_t)-1;
      }
      if (!s.ready) traceTLS(s, @"tls.handshake.ready", CURLE_OK);
      s.ready = YES;
      s.lastError = 0;
      int state = 2;
      memcpy((char *)(__bridge void *)context + ivar_getOffset(stateIvar),
             &state, sizeof(state));
    }
    return 0;
  }
  return s.originalHandshake(legacy);
}
static uint64_t observeSetBIO(void *legacy, void *readBIO, void *writeBIO) {
  uint64_t result = originalSetBIO(legacy, readBIO, writeBIO);
  if (!result || !adapterEnabled)
    return result;
  id context = decodeContext(legacy);
  if (!context || nativeState(context) >= 2 || lookup(legacy))
    return result;
  id owner = object_getIvar(context, ownerIvar);
  if (![owner isKindOfClass:ownerClass] || readBIO != writeBIO)
    return result;
  if (pointerIvar(owner, ownerContextIvar) != legacy ||
      pointerIvar(owner, ownerBIOIvar) != readBIO)
    return result;
  SHDWNativeSessionState *s = [SHDWNativeSessionState new];
  s.owner = owner;
  s.context = context;
  s.legacy = legacy;
  s.bio = readBIO;
  void *original = pointerIvar(owner, handshakeIvar);
  if (!original)
    return result;
  s.originalHandshake = (SessionHandshake)ptrauth_sign_unauthenticated(
      ptrauth_strip(original, ptrauth_key_function_pointer),
      ptrauth_key_function_pointer, 0);
  objc_setAssociatedObject(owner, &stateKey, s,
                           OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  @synchronized(lock) {
    [sessions setObject:s forKey:[NSValue valueWithPointer:legacy]];
  }
  void *replacement = ptrauth_sign_unauthenticated(
      ptrauth_strip((void *)observeHandshake, ptrauth_key_function_pointer),
      ptrauth_key_function_pointer, 0);
  memcpy((char *)(__bridge void *)owner + ivar_getOffset(handshakeIvar),
         &replacement, sizeof(replacement));

  return result;
}
BOOL SHDWNativeTLSInstall(NSString *profile, NSString *libraryPath,
                          NSString *CAPath, SHDWHookSession *hooks) {
  @synchronized(SHDWNativeSessionState.class) {
    if (!hooks || ![@[
          @"safari172_ios", @"safari180_ios", @"safari184_ios", @"safari187_ios"
        ] containsObject:profile] ||
        !libraryPath.length || !CAPath.length)
      return NO;
    if (adapterEnabled) {
      @synchronized(lock) {
        configuredProfile = [profile copy];
        configuredLibrary = [libraryPath copy];
        configuredCA = [CAPath copy];
      }
      return YES;
    }
    if (installationAttempted)
      return NO;
    if (!appleLibrary)
      appleLibrary =
          dlopen("/usr/lib/libboringssl.dylib", RTLD_NOW | RTLD_LOCAL);
    void *library = appleLibrary;
    if (!library)
      return NO;
    ctxClass = NSClassFromString(@"boringssl_concrete_boringssl_ctx");
    ownerClass = NSClassFromString(@"boringssl_concrete_nw_protocol_boringssl");
    if (!ctxClass || !ownerClass)
      return NO;
    legacyIvar = class_getInstanceVariable(ctxClass, "legacy_context");
    ownerIvar = class_getInstanceVariable(ctxClass, "boringssl_handle");
    ownerContextIvar = class_getInstanceVariable(ownerClass, "context");
    ownerBIOIvar = class_getInstanceVariable(ownerClass, "boringssl_bio");
    handshakeIvar = class_getInstanceVariable(ownerClass, "handshake_func");
    nameIvar = class_getInstanceVariable(ctxClass, "subject_name");
    addressIvar = class_getInstanceVariable(ctxClass, "remote_address");
    stateIvar = class_getInstanceVariable(ctxClass, "ssl_state");
    metadataIvar = class_getInstanceVariable(ctxClass, "metadata");
    sslIvar = class_getInstanceVariable(ctxClass, "ssl_session");
    verifyIvar = class_getInstanceVariable(ctxClass, "verify_block");
    verifyQueueIvar = class_getInstanceVariable(ctxClass, "verify_queue");
    clientQueueIvar = class_getInstanceVariable(ownerClass, "client_queue");
    parametersIvar = class_getInstanceVariable(ownerClass, "parameters");
    identityIvar = class_getInstanceVariable(ctxClass, "identity");
    readIvar = class_getInstanceVariable(ownerClass, "read_func");
    writeIvar = class_getInstanceVariable(ownerClass, "write_func");
    const char *addressType =
        addressIvar ? ivar_getTypeEncoding(addressIvar) : NULL;
    if (!encoding(legacyIvar, "^{boringssl_legacy_ctx=I^v}") ||
        !encoding(ownerIvar, "@\"boringssl_concrete_nw_protocol_boringssl\"") ||
        !encoding(metadataIvar, "@\"NSObject<OS_nw_protocol_metadata>\"") ||
        !encoding(sslIvar, "^{ssl_st=}") || !encoding(verifyIvar, "@?") ||
        !encoding(verifyQueueIvar, "@\"NSObject<OS_dispatch_queue>\"") ||
        !encoding(clientQueueIvar, "@\"NSObject<OS_dispatch_queue>\"") ||
        !encoding(parametersIvar, "@\"NSObject<OS_nw_parameters>\"") ||
        !encoding(identityIvar, "@\"boringssl_concrete_boringssl_identity\"") ||
        !addressType ||
        strncmp(addressType,
                "(sockaddr_in_4_6=", strlen("(sockaddr_in_4_6=")) ||
        !encoding(ownerContextIvar, "^v") || !encoding(ownerBIOIvar, "^v") ||
        !encoding(handshakeIvar, "^?") || !encoding(readIvar, "^?") ||
        !encoding(writeIvar, "^?") || !encoding(nameIvar, "*") ||
        !encoding(stateIvar, "i"))
      return NO;
    appleBIORead = dlsym(library, "BIO_read");
    appleBIOWrite = dlsym(library, "BIO_write");
    appleBIOShouldRead = dlsym(library, "BIO_should_read");
    appleBIOShouldWrite = dlsym(library, "BIO_should_write");
    findEnclosing = dlsym(RTLD_DEFAULT, "_Unwind_FindEnclosingFunction");
    isDTLS = dlsym(library, "boringssl_context_is_dtls");
    isServerMode = dlsym(RTLD_DEFAULT, "nw_parameters_get_server_mode");
    if (!appleBIORead || !appleBIOWrite || !appleBIOShouldRead ||
        !appleBIOShouldWrite || !findEnclosing || !isDTLS || !isServerMode)
      return NO;
    const char *names[] = {
        "boringssl_session_set_bio",
        "SSL_get_error",
        "SSL_shutdown",
        "boringssl_session_disconnect",
        "boringssl_session_destroy",
        "sec_protocol_metadata_get_negotiated_protocol",
        "sec_protocol_metadata_get_negotiated_tls_protocol_version",
        "sec_protocol_metadata_get_negotiated_tls_ciphersuite",
        "sec_protocol_metadata_access_peer_certificate_chain",
        "sec_protocol_metadata_copy_sec_trust"};
    void *targets[10];
    for (unsigned i = 0; i < 10; i++) {
      targets[i] = dlsym(library, names[i]);
      if (!targets[i])
        targets[i] = dlsym(RTLD_DEFAULT, names[i]);
      if (!targets[i])
        return NO;
    }
    lock = [NSObject new];
    sessions = [NSMapTable strongToWeakObjectsMapTable];
    sslSessions = [NSMapTable strongToWeakObjectsMapTable];
    configuredProfile = [profile copy];
    configuredLibrary = [libraryPath copy];
    configuredCA = [CAPath copy];
#define HOOK(index, replacement, original)                                     \
  do {                                                                         \
    if (![hooks hookFunction:ptrauth_strip(targets[index],                     \
                                           ptrauth_key_function_pointer)       \
             withReplacement:ptrauth_strip((void *)replacement,                \
                                           ptrauth_key_function_pointer)       \
                   outOldPtr:&originals[index]] ||                             \
        !originals[index]) {                                                   \
      SHDWCurlTrace(@"transport.nativeTLS.refused", nil,                       \
          @{@"symbol": @(names[index])});                                     \
      return NO;                                                               \
    }                                                                         \
  } while (0)
    installationAttempted = YES;
    HOOK(0, observeSetBIO, originalSetBIO);
    HOOK(1, actualError, originalGetError);
    HOOK(2, actualShutdown, originalShutdown);
    HOOK(3, observeDisconnect, originalDisconnect);
    HOOK(4, observeDestroy, originalDestroy);
    HOOK(5, actualALPN, originalALPN);
    HOOK(6, actualVersion, originalVersion);
    HOOK(7, actualCipher, originalCipher);
    HOOK(8, actualChain, originalChain);
    HOOK(9, actualTrust, originalTrust);
#undef HOOK
    adapterEnabled = YES;
    return YES;
  }
}
#else
BOOL SHDWNativeTLSInstall(NSString *profile, NSString *libraryPath,
                          NSString *CAPath, SHDWHookSession *hooks) {
  (void)profile;
  (void)libraryPath;
  (void)CAPath;
  (void)hooks;
  return NO;
}
#endif

BOOL SHDWNativeTLSPrepare(NSString *profile, NSString *libraryPath,
                          NSString *CAPath) {
#if SHADOW_CURL_IMPERSONATE
  static SHDWHookSession *hooks;
  static dispatch_once_t once;
  dispatch_once(&once, ^{
    hooks = [SHDWHookSession new];
    hooks.requiresPreparedFunctionOriginal = YES;
  });
  return SHDWNativeTLSInstall(profile, libraryPath, CAPath, hooks);
#else
  (void)profile;
  (void)libraryPath;
  (void)CAPath;
  return NO;
#endif
}
