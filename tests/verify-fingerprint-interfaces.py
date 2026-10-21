"""Run production interface policy/wrappers with native API and allocation doubles."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    raise SystemExit("This optional check requires Darwin sockaddr layouts and Foundation")
root = Path(__file__).resolve().parents[1]
policy = (root / "src/ShadowCore.dylib/policy/FingerprintInterfaces.m").read_text()
policy = policy.replace('#import "FingerprintInterfaces.h"', '')
wrapper = (root / "src/ShadowCore.dylib/hooks/Universal/FingerprintInterfaces.x").read_text()
wrapper = wrapper.replace('#import "UniversalHooks.h"', '').replace('#import "../../policy/FingerprintInterfaces.h"', '')
mapping_switch = "static const BOOL shdw_fingerprint_interface_mapping_enabled = NO;"
assert mapping_switch in wrapper
wrapper = wrapper.replace(mapping_switch, "static BOOL shdw_fingerprint_interface_mapping_enabled = NO;")
prefix = r'''
#import <Foundation/Foundation.h>
#include <string.h>
NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    unsigned char bytes[32];
    memset(bytes, [bundleID isEqual:@"another.bundle"] ? 2 : 1, sizeof(bytes));
    return @{@"InterfaceSeed": [NSData dataWithBytes:bytes length:sizeof(bytes)]};
}

#include <CommonCrypto/CommonHMAC.h>
#include <ifaddrs.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <net/if_dl.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <errno.h>
#include <assert.h>
static _Thread_local long failAt = -1, allocationCount;
static BOOL failAllocation(void) {
    if(allocationCount++ == failAt) { errno = ENOMEM; return YES; } return NO;
}
static void *faultMalloc(size_t n) { return failAllocation() ? NULL : malloc(n); }
static void *faultCalloc(size_t n, size_t s) { return failAllocation() ? NULL : calloc(n, s); }
static char *faultStrdup(const char *s) { return failAllocation() ? NULL : strdup(s); }
#define malloc faultMalloc
#define calloc faultCalloc
#define strdup faultStrdup
'''
middle = r'''
#undef malloc
#undef calloc
#undef strdup
static struct ifaddrs *nativeFixture;
static int nativeStatus;
static unsigned nativeGets, nativeFrees;
static unsigned hookRequests;
static BOOL failGetInstall, failFreeInstall, missingSymbols;
static _Thread_local unsigned internalDepth;
static _Thread_local BOOL appCaller = YES;
static void leaveScope(BOOL *active) { (void)active; assert(internalDepth); internalDepth--; }
#define SHADOW_INTERNAL_SCOPE for(BOOL active __attribute__((cleanup(leaveScope))) = (++internalDepth, YES); active; active = NO)
#define __builtin_return_address(n) ((void *)1)
#define __builtin_extract_return_addr(c) (c)
static NSString *shdw_fingerprint_bundle_identifier_for_caller(const void *caller) {
    assert(caller); return appCaller && !internalDepth ? @"test.bundle" : nil;
}
static struct sockaddr *plainAddress(const struct sockaddr *a) {
    if(!a) return NULL;
    size_t size = MAX((size_t)a->sa_len, sizeof(struct sockaddr_storage));
    struct sockaddr *copy = calloc(1, size); assert(copy);
    memcpy(copy, a, MAX((size_t)a->sa_len, (size_t)2)); return copy;
}
static struct ifaddrs *plainClone(const struct ifaddrs *source) {
    struct ifaddrs *head = NULL, **tail = &head;
    for(; source; source = source->ifa_next) {
        struct ifaddrs *node = calloc(1, sizeof(*node)); assert(node);
        node->ifa_flags = source->ifa_flags;
        node->ifa_name = source->ifa_name ? strdup(source->ifa_name) : NULL;
        node->ifa_addr = plainAddress(source->ifa_addr);
        node->ifa_netmask = plainAddress(source->ifa_netmask);
        node->ifa_dstaddr = plainAddress(source->ifa_dstaddr);
        if(source->ifa_data) { node->ifa_data = malloc(sizeof(struct if_data)); memcpy(node->ifa_data, source->ifa_data, sizeof(struct if_data)); }
        *tail = node; tail = &node->ifa_next;
    }
    return head;
}
static void plainFree(struct ifaddrs *head) {
    while(head) { struct ifaddrs *next = head->ifa_next;
        free(head->ifa_name); free(head->ifa_addr); free(head->ifa_netmask);
        free(head->ifa_dstaddr); free(head->ifa_data); free(head); head = next; }
}
static int nativeGet(struct ifaddrs **out) {
    __atomic_fetch_add(&nativeGets, 1, __ATOMIC_RELAXED);
    errno = EINPROGRESS;
    if(nativeStatus) return nativeStatus;
    if(out) *out = plainClone(nativeFixture); return 0;
}
static void nativeFree(struct ifaddrs *head) {
    __atomic_fetch_add(&nativeFrees, 1, __ATOMIC_RELAXED); plainFree(head); errno = EDOM;
}
static void *fakeDlsym(void *handle, const char *name) {
    (void)handle; if(missingSymbols) return NULL;
    if(!strcmp(name, "getifaddrs")) return (void *)nativeGet;
    if(!strcmp(name, "freeifaddrs")) return (void *)nativeFree;
    assert(0); return NULL;
}
#define dlsym fakeDlsym
@interface SHDWHookSession : NSObject
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)cell;
@end
@implementation SHDWHookSession
- (BOOL)hookRebindSymbol:(NSString *)name withReplacement:(void *)replacement outOldPtr:(void **)cell {
    hookRequests++;
    assert(replacement && cell);
    BOOL get = [name isEqual:@"getifaddrs"];
    BOOL fail = get ? failGetInstall : failFreeInstall;
    *cell = fail ? NULL : get ? (void *)nativeGet : (void *)nativeFree;
    return !fail;
}
@end
'''
suffix = r'''
static struct sockaddr *address(int family, const char *text) {
    struct sockaddr_storage *storage = calloc(1, sizeof(*storage)); assert(storage);
    if(family == AF_INET) {
        struct sockaddr_in *a = (void *)storage; a->sin_len = sizeof(*a); a->sin_family = AF_INET;
        assert(inet_pton(AF_INET, text, &a->sin_addr) == 1); a->sin_port = htons(19);
    } else {
        struct sockaddr_in6 *a = (void *)storage; a->sin6_len = sizeof(*a); a->sin6_family = AF_INET6;
        assert(inet_pton(AF_INET6, text, &a->sin6_addr) == 1); a->sin6_scope_id = 7; a->sin6_port = htons(23);
    }
    return (void *)storage;
}
static struct ifaddrs *node(const char *name, int family, const char *text) {
    struct ifaddrs *n = calloc(1, sizeof(*n)); assert(n); n->ifa_name = strdup(name);
    n->ifa_flags = IFF_UP; n->ifa_addr = address(family, text);
    n->ifa_netmask = address(family, family == AF_INET ? "255.255.255.0" : "ffff:ffff:ffff:ffff::");
    return n;
}
static void append(struct ifaddrs **head, struct ifaddrs *next) {
    while(*head) head = &(*head)->ifa_next; *head = next;
}
static struct ifaddrs *find(struct ifaddrs *head, const char *name) {
    for(; head; head = head->ifa_next) if(!strcmp(head->ifa_name, name)) return head; return NULL;
}
static NSData *serialize(const struct ifaddrs *head) {
    NSMutableData *bytes = [NSMutableData data];
    for(; head; head = head->ifa_next) {
        if(head->ifa_name) [bytes appendBytes:head->ifa_name length:strlen(head->ifa_name)+1];
        [bytes appendBytes:&head->ifa_flags length:sizeof(head->ifa_flags)];
        for(unsigned i = 0; i < 3; i++) {
            const struct sockaddr *a = i == 0 ? head->ifa_addr : i == 1 ? head->ifa_netmask : head->ifa_dstaddr;
            if(a) [bytes appendBytes:a length:a->sa_len];
        }
        if(head->ifa_data) [bytes appendBytes:head->ifa_data length:sizeof(struct if_data)];
    }
    return [bytes copy];
}
static uint32_t v4(struct ifaddrs *n) { return ntohl(((struct sockaddr_in *)n->ifa_addr)->sin_addr.s_addr); }
static void checkMapped(struct ifaddrs *copy, const struct ifaddrs *source) {
    for(struct ifaddrs *n = copy; n; n = n->ifa_next) {
        struct ifaddrs *s = find((struct ifaddrs *)source, n->ifa_name); assert(s);
        assert(n != s && n->ifa_name != s->ifa_name && n->ifa_flags == s->ifa_flags);
        if(n->ifa_addr) assert(n->ifa_addr != s->ifa_addr);
        if(n->ifa_netmask) assert(n->ifa_netmask != s->ifa_netmask && !memcmp(n->ifa_netmask, s->ifa_netmask, s->ifa_netmask->sa_len));
        if(n->ifa_data) assert(n->ifa_data != s->ifa_data && !memcmp(n->ifa_data, s->ifa_data, sizeof(struct if_data)));
    }
}
static void install(void) {
    shdw_fingerprint_interfaces_ready = NO; original_getifaddrs = NULL; original_fingerprint_freeifaddrs = NULL;
    shdw_fingerprint_native_getifaddrs = NULL; shdw_fingerprint_native_freeifaddrs = NULL;
    shdw_universal_fingerprint_interfaces([SHDWHookSession new]);
}
static void *worker(void *argument) { @autoreleasepool {
    (void)argument; appCaller = YES;
    for(unsigned i = 0; i < 100; i++) {
        struct ifaddrs *out = NULL; assert(!replaced_getifaddrs(&out) && errno == EINPROGRESS);
        assert(out); appCaller = NO; errno = ERANGE; shdw_fingerprint_freeifaddrs(out);
        assert(errno == ERANGE); appCaller = YES;
    }
    return NULL;
} }
int main(void) { @autoreleasepool {
    assert(!SHDWFingerprintCopyInterfaces(nil, NULL, NULL));
    struct ifaddrs *out = (void *)1;
    assert(!SHDWFingerprintCopyInterfaces(@"", NULL, &out) && out == (void *)1);
    assert(SHDWFingerprintCopyInterfaces(@"test.bundle", NULL, &out) && !out);
    NSData *seed = shdw_interface_seed(@"test.bundle");
    assert(seed.length == 32);
    for(unsigned i = 0; i < 1000; i++) {
        assert(SHDWFingerprintCopyInterfaces(@"test.bundle", NULL, &out));
        assert([seed isEqual:shdw_interface_seed(@"test.bundle")]);
    }
    assert(![seed isEqual:shdw_interface_seed(@"another.bundle")]);
    const char *v4s[] = {"127.0.0.1", "0.0.0.0", "224.0.0.1", "8.8.8.8", "10.20.30.40", "172.19.2.7", "192.168.8.4", "169.254.12.9", "100.79.3.2"};
    for(unsigned i = 0; i < 9; i++) { char name[32]; snprintf(name, sizeof(name), "unusual-%u", i); append(&nativeFixture, node(name, AF_INET, v4s[i])); }
    const char *v6s[] = {"::1", "::", "ff02::1", "fe80::1234", "fd12:3456:789a:bcde::1234", "2001:4860::1"};
    for(unsigned i = 0; i < 6; i++) { char name[32]; snprintf(name, sizeof(name), "v6-odd-%u", i); append(&nativeFixture, node(name, AF_INET6, v6s[i])); }
    struct ifaddrs *broadcast = find(nativeFixture, "unusual-4"); broadcast->ifa_flags |= IFF_BROADCAST;
    broadcast->ifa_broadaddr = address(AF_INET, "10.20.30.255");
    struct ifaddrs *peer = find(nativeFixture, "unusual-5"); peer->ifa_flags |= IFF_POINTOPOINT;
    peer->ifa_dstaddr = address(AF_INET, "172.19.2.1");
    peer = find(nativeFixture, "v6-odd-4"); peer->ifa_flags |= IFF_POINTOPOINT;
    peer->ifa_dstaddr = address(AF_INET6, "fd12:3456:789a:bcde::1235");
    ((struct sockaddr_in6 *)peer->ifa_dstaddr)->sin6_scope_id = 9;
    struct ifaddrs *loopback = node("loopback-linklocal", AF_INET6, "fe80::1");
    loopback->ifa_flags |= IFF_LOOPBACK;
    loopback->ifa_dstaddr = address(AF_INET6, "2001:4860::2"); append(&nativeFixture, loopback);
    loopback = node("loopback-global-alias", AF_INET6, "2001:4860::3");
    loopback->ifa_flags |= IFF_LOOPBACK; append(&nativeFixture, loopback);
    struct ifaddrs *link = calloc(1, sizeof(*link)); link->ifa_name = strdup("link-255");
    link->ifa_addr = calloc(1, 255); link->ifa_addr->sa_len = 255; link->ifa_addr->sa_family = AF_LINK;
    memset((unsigned char *)link->ifa_addr + 2, 0x5a, 253); link->ifa_data = calloc(1, sizeof(struct if_data));
    append(&nativeFixture, link);
    NSData *original = serialize(nativeFixture);
    allocationCount = 0;
    assert(SHDWFingerprintCopyInterfaces(@"test.bundle", nativeFixture, &out));
    long allocations = allocationCount; assert(allocations > 30);
    checkMapped(out, nativeFixture); assert([original isEqual:serialize(nativeFixture)]);
    assert(!find(out, "unusual-3") && !find(out, "v6-odd-5"));
    for(unsigned i = 0; i < 3; i++) { char name[32]; snprintf(name, sizeof(name), "unusual-%u", i); assert(v4(find(out, name)) == v4(find(nativeFixture, name))); }
    for(unsigned i = 0; i < 3; i++) { char name[32]; snprintf(name, sizeof(name), "v6-odd-%u", i); assert(!memcmp(find(out,name)->ifa_addr, find(nativeFixture,name)->ifa_addr, sizeof(struct sockaddr_in6))); }
    assert((v4(find(out,"unusual-4")) & 0xff000000) == 0x0a000000);
    assert((v4(find(out,"unusual-5")) & 0xfff00000) == 0xac100000);
    assert((v4(find(out,"unusual-6")) & 0xffff0000) == 0xc0a80000);
    assert((v4(find(out,"unusual-7")) & 0xffff0000) == 0xa9fe0000);
    assert((v4(find(out,"unusual-8")) & 0xffc00000) == 0x64400000);
    broadcast = find(out,"unusual-4");
    assert(ntohl(((struct sockaddr_in *)broadcast->ifa_broadaddr)->sin_addr.s_addr) == ((v4(broadcast) & 0xffffff00) | 255));
    peer = find(out,"unusual-5");
    assert((ntohl(((struct sockaddr_in *)peer->ifa_dstaddr)->sin_addr.s_addr) & 0xffffff00) == (v4(peer) & 0xffffff00));
    peer = find(out,"v6-odd-4");
    assert(!memcmp(&((struct sockaddr_in6 *)peer->ifa_addr)->sin6_addr, &((struct sockaddr_in6 *)peer->ifa_dstaddr)->sin6_addr, 8));
    assert(((struct sockaddr_in6 *)peer->ifa_dstaddr)->sin6_scope_id == 9);
    struct sockaddr_in6 *local = (void *)find(out,"v6-odd-3")->ifa_addr;
    assert(IN6_IS_ADDR_LINKLOCAL(&local->sin6_addr) && local->sin6_scope_id == 7);
    assert(((struct sockaddr_in6 *)find(out,"v6-odd-4")->ifa_addr)->sin6_addr.s6_addr[0] == 0xfd);
    for(const char **name = (const char *[]){"loopback-linklocal", "loopback-global-alias", NULL}; *name; name++) {
        struct ifaddrs *copy = find(out, *name), *originalNode = find(nativeFixture, *name);
        assert(copy && !memcmp(copy->ifa_addr, originalNode->ifa_addr, originalNode->ifa_addr->sa_len));
        if(copy->ifa_dstaddr) assert(!memcmp(copy->ifa_dstaddr, originalNode->ifa_dstaddr, originalNode->ifa_dstaddr->sa_len));
    }
    assert(!memcmp(find(out,"link-255")->ifa_addr, link->ifa_addr, 255));
    struct ifaddrs *second = NULL;
    assert(SHDWFingerprintCopyInterfaces(@"test.bundle", nativeFixture, &second));
    assert([serialize(out) isEqual:serialize(second)] && out != second && out->ifa_addr != second->ifa_addr);
    assert(SHDWFingerprintReleaseInterfaces(out) && SHDWFingerprintReleaseInterfaces(second));
    for(long i = 0; i < allocations; i++) {
        failAt = i; allocationCount = 0; out = (void *)1;
        assert(!SHDWFingerprintCopyInterfaces(@"test.bundle", nativeFixture, &out) && out == (void *)1);
        assert(!shdw_interface_owned_lists && [original isEqual:serialize(nativeFixture)]);
    }
    failAt = -1;
    install(); assert(!shdw_fingerprint_interfaces_ready);
    assert(hookRequests == 0);
    assert(!shdw_sym_policy_lookup_fingerprint("getifaddrs") && !shdw_sym_policy_lookup_fingerprint("freeifaddrs"));
    assert(!replaced_getifaddrs(&out) && errno == EINPROGRESS && [original isEqual:serialize(out)]);
    shdw_fingerprint_freeifaddrs(out);
    shdw_fingerprint_interface_mapping_enabled = YES;
    install(); assert(shdw_fingerprint_interfaces_ready);
    assert(hookRequests == 2);
    assert(shdw_sym_policy_lookup_fingerprint("getifaddrs") == (void *)replaced_getifaddrs);
    assert(shdw_sym_policy_lookup_fingerprint("freeifaddrs") == (void *)shdw_fingerprint_freeifaddrs);
    assert(!shdw_sym_policy_lookup_fingerprint(NULL) && !shdw_sym_policy_lookup_fingerprint("unknown"));
    for(long i = 0; i < allocations; i++) {
        failAt = i; allocationCount = 0; unsigned freed = nativeFrees;
        assert(!replaced_getifaddrs(&out) && errno == EINPROGRESS && [original isEqual:serialize(out)]);
        assert(nativeFrees == freed); errno = EBUSY; shdw_fingerprint_freeifaddrs(out); assert(errno == EBUSY && nativeFrees == freed + 1);
    }
    failAt = -1; unsigned freed = nativeFrees;
    assert(!replaced_getifaddrs(&out) && errno == EINPROGRESS && nativeFrees == freed + 1);
    appCaller = NO; errno = EBUSY; shdw_fingerprint_freeifaddrs(out);
    assert(errno == EBUSY && nativeFrees == freed + 1);
    assert(!replaced_getifaddrs(&out) && [original isEqual:serialize(out)]);
    shdw_fingerprint_freeifaddrs(out); appCaller = YES;
    internalDepth = 2; assert(!replaced_getifaddrs(&out) && [original isEqual:serialize(out)]);
    shdw_fingerprint_freeifaddrs(out); assert(internalDepth == 2); internalDepth = 0;
    nativeStatus = -1; out = (void *)1; assert(replaced_getifaddrs(&out) == -1 && errno == EINPROGRESS && out == (void *)1); nativeStatus = 0;
    struct ifaddrs *saved = nativeFixture; nativeFixture = NULL;
    assert(!replaced_getifaddrs(&out) && !out && errno == EINPROGRESS); nativeFixture = saved;
    struct ifaddrs *global = node("global-only", AF_INET6, "2001:4860::9");
    nativeFixture = global;
    assert(!replaced_getifaddrs(&out) && !out && errno == EINPROGRESS);
    plainFree(global); nativeFixture = saved;
    failGetInstall = YES; install(); assert(!shdw_sym_policy_lookup_fingerprint("getifaddrs"));
    assert(!replaced_getifaddrs(&out) && out); shdw_fingerprint_freeifaddrs(out); failGetInstall = NO;
    failFreeInstall = YES; install(); assert(!shdw_fingerprint_interfaces_ready); failFreeInstall = NO;
    missingSymbols = YES; install(); assert(!shdw_fingerprint_interfaces_ready); missingSymbols = NO; install();
    // Independent single-family fixtures and randomized names/counts.
    for(unsigned family = 0; family < 2; family++) for(unsigned count = 1; count <= 40; count += 13) {
        struct ifaddrs *list = NULL;
        for(unsigned i = 0; i < count; i++) { char name[64], ip[64];
            snprintf(name,sizeof(name),"random-%08x-%u", arc4random(),i);
            if(family) snprintf(ip,sizeof(ip),"fd12:3456::%x",i + 1); else snprintf(ip,sizeof(ip),"192.168.3.%u",i + 1);
            append(&list,node(name,family ? AF_INET6 : AF_INET,ip)); }
        assert(SHDWFingerprintCopyInterfaces(@"random.bundle",list,&out)); checkMapped(out,list);
        unsigned total = 0; for(struct ifaddrs *n=out;n;n=n->ifa_next) total++; assert(total == count);
        assert(SHDWFingerprintReleaseInterfaces(out)); plainFree(list);
    }
    pthread_t workers[6]; for(unsigned i=0;i<6;i++) assert(!pthread_create(&workers[i],NULL,worker,NULL));
    for(unsigned i=0;i<6;i++) assert(!pthread_join(workers[i],NULL));
    assert(!shdw_interface_owned_lists && [original isEqual:serialize(nativeFixture)]);
    plainFree(nativeFixture); nativeFixture = NULL;
    puts("fingerprint interfaces: production policy/wrappers, persisted seed stability, cloning, scopes, errno, OOM and concurrency passed");
} }
'''
with tempfile.TemporaryDirectory(prefix="shadow-interface-test-") as tmp:
    src = Path(tmp) / "test.m"
    binary = Path(tmp) / "test"
    src.write_text(prefix + policy + middle + wrapper + suffix)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-pthread", "-framework", "Foundation", "-I", str(root / "src/ShadowCore.dylib/policy"), str(src), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
