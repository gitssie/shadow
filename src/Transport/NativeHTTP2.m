#import "NativeHTTP2.h"
#if SHADOW_CURL_IMPERSONATE
#include "NativeHTTP2Policy.h"
#include "NativeHTTP2Stubs.h"
#include "CurlDiagnostics.h"
#import "../ShadowCore.dylib/SHDWHookSession.h"
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <ptrauth.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

typedef struct { uintptr_t address; unsigned index; uint8_t bytes[16]; } H2Entry;
static BOOL findEntries(void *const expected[8], H2Entry entries[64], size_t *outCount) {
    enum { CandidateCapacity = 32768 };
    uintptr_t *seen = calloc(CandidateCapacity, sizeof(*seen));
    if (!seen) return NO;
    size_t count = 0;
    unsigned coverage = 0, images = 0;
    BOOL valid = YES;
    for (uint32_t i = 0; valid && i < _dyld_image_count(); i++) {
        const char *name = _dyld_get_image_name(i);
        if (!name || (!strstr(name, "/CFNetwork.framework/") && !strstr(name, "/Network.framework/"))) continue;
        const struct mach_header_64 *header = (const void *)_dyld_get_image_header(i);
        if (!header || header->magic != MH_MAGIC_64) { valid = NO; break; }
        const struct section_64 *text = getsectbynamefromheader_64(header, "__TEXT", "__text");
        if (!text || !text->size || text->size > 64 * 1024 * 1024 || (text->size & 3)) { valid = NO; break; }
        uintptr_t start = text->addr + _dyld_get_image_vmaddr_slide(i);
        if ((start & 3) || text->size > UINTPTR_MAX - start) { valid = NO; break; }
        images++;
        for (size_t offset = 0; valid && offset < text->size; offset += 4) {
            uint32_t instruction;
            memcpy(&instruction, (const void *)(start + offset), 4);
            if ((instruction & 0xfc000000u) != 0x94000000u) continue;
            int64_t delta = instruction & 0x03ffffffu;
            if (delta & 0x02000000) delta -= 0x04000000;
            delta *= 4;
            uintptr_t pc = start + offset;
            if ((delta < 0 && pc < (uintptr_t)-delta) ||
                (delta > 0 && pc > UINTPTR_MAX - (uintptr_t)delta)) continue;
            uintptr_t address = delta < 0 ? pc - (uintptr_t)-delta : pc + (uintptr_t)delta;
            if (!address) continue;
            size_t slot = (address >> 2) % CandidateCapacity, probes = 0;
            while (seen[slot] && seen[slot] != address && ++probes < CandidateCapacity)
                slot = (slot + 1) % CandidateCapacity;
            if (probes == CandidateCapacity) { valid = NO; break; }
            if (seen[slot]) continue;
            seen[slot] = address;
            H2Entry entry = {.address = address};
            vm_size_t read = 0;
            if (vm_read_overwrite(mach_task_self(), address, sizeof(entry.bytes),
                    (vm_address_t)entry.bytes, &read) != KERN_SUCCESS || read != sizeof(entry.bytes)) continue;
            uintptr_t target;
            if (!SHDWH2DecodeCommonStub(entry.bytes, sizeof(entry.bytes), address, &target)) continue;
            for (unsigned j = 0; j < 8; j++) {
                if (!expected[j] || target != (uintptr_t)ptrauth_strip(expected[j], ptrauth_key_function_pointer)) continue;
                if (count == 64) { valid = NO; break; }
                entry.index = j;
                entries[count++] = entry;
                coverage |= 1u << j;
                break;
            }
        }
    }
    free(seen);
    unsigned required = 0;
    for (unsigned j = 0; j < 8; j++) if (expected[j]) required |= 1u << j;
    if (!valid || images != 2 || coverage != required) {
        SHDWCurlTrace(@"http2.coverage.refused", nil, @{@"images":@(images), @"coverage":@(coverage), @"required":@(required)});
        return NO;
    }
    *outCount = count;
    return YES;
}

_Static_assert(sizeof(SHDWH2Setting) == 8, "HTTP/2 settings ABI");
_Static_assert(sizeof(SHDWH2Header) == 40, "HTTP/2 header ABI");
typedef struct { int age, version; const char *versionString, *protocol; } H2Version;
typedef int (*SettingsFunction)(void *, uint8_t, const SHDWH2Setting *, size_t);
typedef int (*WindowFunction)(void *, uint8_t, int32_t, int32_t);
typedef int (*AbsoluteWindowFunction)(void *, uint8_t, int32_t, int32_t);
typedef int32_t (*RequestFunction)(void *, const void *, const SHDWH2Header *, size_t, const void *, void *);
typedef int32_t (*HeadersFunction)(void *, uint8_t, int32_t, const void *, const SHDWH2Header *, size_t, void *);
typedef int (*PriorityFunction)(void *, uint8_t, int32_t, const void *);
typedef void (*DeleteFunction)(void *);
typedef int (*New2Function)(void **, const void *, void *, const void *);
static void *originals[8];
#define H2_ORIGINAL(i, type) ((type)ptrauth_sign_unauthenticated(ptrauth_strip(originals[i], ptrauth_key_function_pointer), ptrauth_key_function_pointer, 0))
static int (*clientAllowed)(void *);
static unsigned enabled;
static BOOL installed;
static void *library;
static pthread_mutex_t sessionsLock = PTHREAD_MUTEX_INITIALIZER;
typedef struct H2Session { void *session; BOOL windowSet, configured, settingsSeen; struct H2Session *next; } H2Session;
static H2Session *sessions;

static BOOL nativeCaller(const void *caller) {
    if (!__atomic_load_n(&enabled, __ATOMIC_ACQUIRE)) return NO;
    Dl_info image = {0};
    const void *pc = ptrauth_strip(caller, ptrauth_key_return_address);
    if (!dladdr(pc, &image) || !image.dli_fname) return NO;
    return strstr(image.dli_fname, "/CFNetwork.framework/") ||
        strstr(image.dli_fname, "/Network.framework/") || strstr(image.dli_fname, "/libnetwork.dylib");
}
static BOOL tracked(void *session) {
    BOOL found = NO;
    pthread_mutex_lock(&sessionsLock);
    for (H2Session *s = sessions; s; s = s->next) if (s->session == session) { found = s->configured; break; }
    pthread_mutex_unlock(&sessionsLock);
    return found;
}
static BOOL beginSession(void *session) {
    H2Session *fresh = calloc(1, sizeof(*fresh));
    if (!fresh) return NO;
    fresh->session = session;
    pthread_mutex_lock(&sessionsLock);
    for (H2Session *s = sessions; s; s = s->next) if (s->session == session) {
        s->windowSet = s->configured = s->settingsSeen = NO;
        pthread_mutex_unlock(&sessionsLock); free(fresh); return YES;
    }
    fresh->next = sessions; sessions = fresh;
    pthread_mutex_unlock(&sessionsLock);
    return YES;
}
static void forgetSession(void *session) {
    pthread_mutex_lock(&sessionsLock);
    H2Session **link = &sessions;
    while (*link) {
        H2Session *s = *link;
        if (s->session == session) { *link = s->next; free(s); break; }
        link = &s->next;
    }
    pthread_mutex_unlock(&sessionsLock);
}
static BOOL claimWindow(void *session) {
    BOOL claimed = NO;
    pthread_mutex_lock(&sessionsLock);
    for (H2Session *s = sessions; s; s = s->next) if (s->session == session) {
        if (s->configured && !s->windowSet) { s->windowSet = YES; claimed = YES; }
        break;
    }
    pthread_mutex_unlock(&sessionsLock);
    return claimed;
}
static BOOL claimSettings(void *session) {
    BOOL claimed = NO;
    pthread_mutex_lock(&sessionsLock);
    for (H2Session *s = sessions; s; s = s->next) if (s->session == session) {
        if (!s->settingsSeen) { s->settingsSeen = YES; claimed = YES; }
        break;
    }
    pthread_mutex_unlock(&sessionsLock);
    return claimed;
}
static void configureSession(void *session) {
    pthread_mutex_lock(&sessionsLock);
    for (H2Session *s = sessions; s; s = s->next)
        if (s->session == session) { s->configured = YES; break; }
    pthread_mutex_unlock(&sessionsLock);
}
static int createSession2(void **out, const void *callbacks, void *user, const void *options) {
    BOOL native = nativeCaller(__builtin_return_address(0));
    int result = H2_ORIGINAL(7, New2Function)(out, callbacks, user, options);
    if (!result && native && out && *out) beginSession(*out);
    return result;
}
static int setSettings(void *session, uint8_t flags, const SHDWH2Setting *settings, size_t count) {
    SettingsFunction original = H2_ORIGINAL(0, SettingsFunction);
    BOOL first = !(flags & 1u) && claimSettings(session);
    if (!first || !nativeCaller(__builtin_return_address(0)) || flags || count > 120 ||
        !clientAllowed(session)) return original(session, flags, settings, count);
    SHDWH2Setting updated[128];
    size_t length = SHDWH2Settings(settings, count, updated, 128);
    if (!length) return original(session, flags, settings, count);
    configureSession(session);
    int result = original(session, flags, updated, length);
    if (result) forgetSession(session);
    SHDWCurlTrace(@"http2.settings.applied", nil, @{@"result":@(result), @"count":@(length)});
    return result;
}
static int updateWindow(void *session, uint8_t flags, int32_t stream, int32_t increment) {
    WindowFunction original = H2_ORIGINAL(1, WindowFunction);
    if (stream || flags || increment <= 0 || !nativeCaller(__builtin_return_address(0)) || !claimWindow(session))
        return original(session, flags, stream, increment);
    int32_t updated = increment == 10485760 ? 10420225 : increment;
    int result = original(session, flags, stream, updated);
    SHDWCurlTrace(@"http2.window.applied", nil, @{@"result":@(result), @"original":@(increment), @"increment":@(updated)});
    return result;
}
static int absoluteWindow(void *session, uint8_t flags, int32_t stream, int32_t size) {
    AbsoluteWindowFunction original = H2_ORIGINAL(2, AbsoluteWindowFunction);
    if (stream || flags || size <= 0 || !nativeCaller(__builtin_return_address(0)) || !claimWindow(session))
        return original(session, flags, stream, size);
    int result = original(session, flags, stream, 10485760);
    SHDWCurlTrace(@"http2.window.applied", nil, @{@"result":@(result), @"original":@(size), @"absolute":@10485760});
    return result;
}
static SHDWH2Header *orderedHeaders(const SHDWH2Header *headers, size_t count) {
    if (!headers || !count || count > 4096) return NULL;
    SHDWH2Header *copy = malloc(count * sizeof(*copy));
    if (copy && !SHDWH2Headers(headers, count, copy, count)) { free(copy); copy = NULL; }
    return copy;
}
static int32_t submitRequest(void *session, const void *priority, const SHDWH2Header *headers,
                             size_t count, const void *body, void *user) {
    RequestFunction original = H2_ORIGINAL(3, RequestFunction);
    if (!nativeCaller(__builtin_return_address(0)) || !tracked(session))
        return original(session, priority, headers, count, body, user);
    SHDWH2Header *copy = orderedHeaders(headers, count);
    int32_t result = original(session, NULL, copy ?: headers, count, body, user);
    free(copy);
    return result;
}
static int32_t submitHeaders(void *session, uint8_t flags, int32_t stream, const void *priority,
                             const SHDWH2Header *headers, size_t count, void *user) {
    HeadersFunction original = H2_ORIGINAL(4, HeadersFunction);
    if (!nativeCaller(__builtin_return_address(0)) || !tracked(session))
        return original(session, flags, stream, priority, headers, count, user);
    SHDWH2Header *copy = orderedHeaders(headers, count);
    int32_t result = original(session, flags & ~0x20u, stream, NULL, copy ?: headers, count, user);
    free(copy);
    return result;
}
static int submitPriority(void *session, uint8_t flags, int32_t stream, const void *priority) {
    if (nativeCaller(__builtin_return_address(0)) && tracked(session)) return 0;
    return H2_ORIGINAL(5, PriorityFunction)(session, flags, stream, priority);
}
static void deleteSession(void *session) {
    forgetSession(session);
    H2_ORIGINAL(6, DeleteFunction)(session);
}
BOOL SHDWNativeHTTP2Prepare(NSString *profile) {
    if (![profile isEqualToString:@"safari187_ios"]) return YES;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        library = dlopen("/usr/lib/libapple_nghttp2.dylib", RTLD_NOW | RTLD_LOCAL);
        if (!library) return;
        const H2Version *(*version)(int) = dlsym(library, "nghttp2_version");
        clientAllowed = dlsym(library, "nghttp2_session_check_request_allowed");
        const H2Version *info = version ? version(0) : NULL;
        if (!info || info->age != 1 || info->version != 0x012f00 || !clientAllowed) return;
        const char *names[] = {"nghttp2_submit_settings", "nghttp2_submit_window_update",
            "nghttp2_session_set_local_window_size", "nghttp2_submit_request", "nghttp2_submit_headers",
            "nghttp2_submit_priority", "nghttp2_session_del", "nghttp2_session_client_new2"};
        void *replacements[] = {(void *)setSettings, (void *)updateWindow, (void *)absoluteWindow,
            (void *)submitRequest, (void *)submitHeaders, (void *)submitPriority, (void *)deleteSession,
            (void *)createSession2};
        void *expected[8] = {0};
        for (unsigned j = 0; j < sizeof(expected) / sizeof(expected[0]); j++)
            if (!(expected[j] = dlsym(library, names[j]))) return;
        H2Entry entries[64];
        size_t count = 0;
        if (!findEntries(expected, entries, &count)) return;
        // Stub patches never alter these function bodies. Publish all continuations
        // before the first patch, including when a later patch refuses activation.
        for (unsigned i = 0; i < 8; i++) originals[i] = expected[i];
        static SHDWHookSession *hooks;
        hooks = [SHDWHookSession new];
        for (size_t j = 0; j < count; j++) {
            H2Entry *entry = &entries[j];
            unsigned i = entry->index;
            if (![hooks hookEntry:(void *)entry->address
                    withReplacement:ptrauth_strip(replacements[i], ptrauth_key_function_pointer)
                    expectedBytes:[NSData dataWithBytes:entry->bytes length:sizeof(entry->bytes)]
                    backend:@"provider-ellekit"]) {
                SHDWCurlTrace(@"http2.install.refused", nil, @{@"symbol":@(names[i]), @"entry":@(j)});
                return;
            }
        }
        installed = YES;
        SHDWCurlTrace(@"http2.install", nil, @{@"installed":@YES, @"version":@(info->versionString), @"entries":@(count)});
    });
    return installed;
}
void SHDWNativeHTTP2Activate(void) {
    if (installed) __atomic_store_n(&enabled, 1, __ATOMIC_RELEASE);
}
#else
void SHDWNativeHTTP2Activate(void) {}
BOOL SHDWNativeHTTP2Prepare(NSString *profile) { (void)profile; return YES; }
#endif
