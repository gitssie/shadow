#import "FingerprintInterfaces.h"
#import "FingerprintStorage.h"
#include <CommonCrypto/CommonHMAC.h>
#include <arpa/inet.h>
#include <net/if.h>
#include <net/if_dl.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

static NSData *shdw_interface_seed(NSString *bundleID) {
    return SHDWFingerprintData(bundleID)[@"InterfaceSeed"];
}

static void shdw_interface_digest(NSData *seed, unsigned char domain,
    const void *bytes, size_t length, unsigned char output[32]) {
    CCHmacContext context;
    CCHmacInit(&context, kCCHmacAlgSHA256, seed.bytes, seed.length);
    CCHmacUpdate(&context, &domain, sizeof(domain));
    CCHmacUpdate(&context, bytes, length);
    CCHmacFinal(&context, output);
}

static uint32_t shdw_interface_v4(NSData *seed, uint32_t address, uint32_t mask) {
    uint32_t fixed, fixedMask;
    if((address & 0xff000000) == 0x0a000000) { fixed = 0x0a000000; fixedMask = 0xff000000; }
    else if((address & 0xfff00000) == 0xac100000) { fixed = 0xac100000; fixedMask = 0xfff00000; }
    else if((address & 0xffff0000) == 0xc0a80000) { fixed = 0xc0a80000; fixedMask = 0xffff0000; }
    else if((address & 0xffff0000) == 0xa9fe0000) { fixed = 0xa9fe0000; fixedMask = 0xffff0000; }
    else { fixed = 0x64400000; fixedMask = 0xffc00000; }
    unsigned char digest[32];
    uint32_t network = htonl(address & mask), input = htonl(address);
    shdw_interface_digest(seed, 4, &network, sizeof(network), digest);
    uint32_t networkBits;
    memcpy(&networkBits, digest, sizeof(networkBits));
    networkBits = ntohl(networkBits);
    shdw_interface_digest(seed, 5, &input, sizeof(input), digest);
    uint32_t hostBits;
    memcpy(&hostBits, digest, sizeof(hostBits));
    hostBits = ntohl(hostBits);
    uint32_t hostMask = ~mask & ~fixedMask;
    hostBits &= hostMask;
    if(hostMask > 1 && (hostBits == 0 || hostBits == hostMask)) hostBits ^= 1;
    uint32_t result = fixed | (networkBits & mask & ~fixedMask) | hostBits;
    if(fixed == 0xa9fe0000 && ((result & 0xff00) == 0 || (result & 0xff00) == 0xff00))
        result = (result & ~0xff00U) | 0x0100;
    return result;
}

static BOOL shdw_interface_v4_visible(uint32_t address) {
    return address == 0 || address == UINT32_MAX || (address & 0xff000000) == 0x7f000000 ||
        (address & 0xff000000) == 0x0a000000 || (address & 0xfff00000) == 0xac100000 ||
        (address & 0xffff0000) == 0xc0a80000 || (address & 0xffff0000) == 0xa9fe0000 ||
        (address & 0xffc00000) == 0x64400000 || (address & 0xf0000000) == 0xe0000000;
}

static BOOL shdw_interface_v4_private(uint32_t address) {
    return address && address != UINT32_MAX && (address & 0xff000000) != 0x7f000000 &&
        (address & 0xf0000000) != 0xe0000000 && shdw_interface_v4_visible(address);
}

static BOOL shdw_interface_visible(const struct sockaddr *address) {
    if(!address) return YES;
    if(address->sa_family == AF_INET && address->sa_len >= sizeof(struct sockaddr_in))
        return shdw_interface_v4_visible(ntohl(((const struct sockaddr_in *)address)->sin_addr.s_addr));
    if(address->sa_family == AF_INET6 && address->sa_len >= sizeof(struct sockaddr_in6)) {
        const struct in6_addr *a = &((const struct sockaddr_in6 *)address)->sin6_addr;
        return IN6_IS_ADDR_UNSPECIFIED(a) || IN6_IS_ADDR_LOOPBACK(a) || IN6_IS_ADDR_LINKLOCAL(a) ||
            IN6_IS_ADDR_MULTICAST(a) || (a->s6_addr[0] & 0xfe) == 0xfc;
    }
    return YES;
}

static struct sockaddr *shdw_interface_address_copy(const struct sockaddr *source) {
    if(!source) return NULL;
    size_t length = source->sa_len;
    if(length < 2) length = 2;
    struct sockaddr *copy = calloc(1, MAX(length, sizeof(struct sockaddr_storage)));
    if(copy) memcpy(copy, source, length);
    return copy;
}

static void shdw_interface_list_free(struct ifaddrs *head) {
    while(head) {
        struct ifaddrs *next = head->ifa_next;
        free(head->ifa_name); free(head->ifa_addr); free(head->ifa_netmask);
        free(head->ifa_dstaddr); free(head->ifa_data); free(head);
        head = next;
    }
}

static void shdw_interface_transform(NSData *seed, struct ifaddrs *node) {
    struct sockaddr *address = node->ifa_addr;
    if(!address) return;
    if(node->ifa_flags & IFF_LOOPBACK) return;
    if(node->ifa_dstaddr && !shdw_interface_visible(node->ifa_dstaddr)) {
        free(node->ifa_dstaddr); node->ifa_dstaddr = NULL;
    }
    if(address->sa_family == AF_INET && address->sa_len >= sizeof(struct sockaddr_in)) {
        struct sockaddr_in *a = (struct sockaddr_in *)address;
        uint32_t original = ntohl(a->sin_addr.s_addr);
        if(!shdw_interface_v4_private(original)) return;
        uint32_t mask = 0xffffff00;
        if(node->ifa_netmask && node->ifa_netmask->sa_len >= sizeof(struct sockaddr_in))
            mask = ntohl(((struct sockaddr_in *)node->ifa_netmask)->sin_addr.s_addr);
        uint32_t mapped = shdw_interface_v4(seed, original, mask);
        a->sin_addr.s_addr = htonl(mapped);
        if(node->ifa_dstaddr && node->ifa_dstaddr->sa_family == AF_INET &&
           node->ifa_dstaddr->sa_len >= sizeof(struct sockaddr_in)) {
            struct sockaddr_in *peer = (struct sockaddr_in *)node->ifa_dstaddr;
            if(node->ifa_flags & IFF_BROADCAST) peer->sin_addr.s_addr = htonl((mapped & mask) | ~mask);
            else if(shdw_interface_v4_private(ntohl(peer->sin_addr.s_addr)))
                peer->sin_addr.s_addr = htonl(shdw_interface_v4(seed, ntohl(peer->sin_addr.s_addr), mask));
        }
    } else if(address->sa_family == AF_INET6 && address->sa_len >= sizeof(struct sockaddr_in6)) {
        struct sockaddr_in6 *a = (struct sockaddr_in6 *)address;
        if(IN6_IS_ADDR_LOOPBACK(&a->sin6_addr) || IN6_IS_ADDR_UNSPECIFIED(&a->sin6_addr) ||
           IN6_IS_ADDR_MULTICAST(&a->sin6_addr)) return;
        unsigned char digest[32], original[16], mask[16], network[16];
        BOOL linkLocal = IN6_IS_ADDR_LINKLOCAL(&a->sin6_addr);
        memcpy(original, a->sin6_addr.s6_addr, sizeof(original));
        memset(mask, 0, sizeof(mask)); memset(mask, 0xff, 8);
        if(node->ifa_netmask && node->ifa_netmask->sa_len >= sizeof(struct sockaddr_in6))
            memcpy(mask, ((struct sockaddr_in6 *)node->ifa_netmask)->sin6_addr.s6_addr, sizeof(mask));
        for(unsigned i = 0; i < 16; i++) network[i] = original[i] & mask[i];
        shdw_interface_digest(seed, 6, network, sizeof(network), digest);
        for(unsigned i = 0; i < 16; i++) a->sin6_addr.s6_addr[i] = digest[i] & mask[i];
        shdw_interface_digest(seed, 7, original, sizeof(original), digest);
        for(unsigned i = 0; i < 16; i++) a->sin6_addr.s6_addr[i] |= digest[i] & ~mask[i];
        if(linkLocal) {
            memset(a->sin6_addr.s6_addr, 0, 8);
            a->sin6_addr.s6_addr[0] = 0xfe; a->sin6_addr.s6_addr[1] = 0x80;
            a->sin6_addr.s6_addr[2] = original[2]; a->sin6_addr.s6_addr[3] = original[3];
            if(!memcmp(a->sin6_addr.s6_addr + 8, "\0\0\0\0\0\0\0\0", 8)) a->sin6_addr.s6_addr[15] = 1;
        } else a->sin6_addr.s6_addr[0] = 0xfd;
        if(node->ifa_dstaddr && node->ifa_dstaddr->sa_family == AF_INET6 &&
           node->ifa_dstaddr->sa_len >= sizeof(struct sockaddr_in6)) {
            struct ifaddrs peer = {.ifa_addr = node->ifa_dstaddr, .ifa_netmask = node->ifa_netmask};
            shdw_interface_transform(seed, &peer);
        }
    }
}

typedef struct shdw_interface_owned {
    struct ifaddrs *head;
    struct shdw_interface_owned *next;
} shdw_interface_owned;
static shdw_interface_owned *shdw_interface_owned_lists;
static pthread_mutex_t shdw_interface_owned_lock = PTHREAD_MUTEX_INITIALIZER;

BOOL SHDWFingerprintCopyInterfaces(NSString *bundleID, const struct ifaddrs *source,
                                  struct ifaddrs **result) {
    if(!bundleID.length || !result) return NO;
    NSData *seed = shdw_interface_seed(bundleID);
    if(seed.length != 32) return NO;
    struct ifaddrs *head = NULL, **tail = &head;
    for(const struct ifaddrs *item = source; item; item = item->ifa_next) {
        if(!(item->ifa_flags & IFF_LOOPBACK) && !shdw_interface_visible(item->ifa_addr)) continue;
        struct ifaddrs *copy = calloc(1, sizeof(*copy));
        if(!copy) goto failure;
        *tail = copy; tail = &copy->ifa_next;
        copy->ifa_flags = item->ifa_flags;
        if(item->ifa_name && !(copy->ifa_name = strdup(item->ifa_name))) goto failure;
        if(item->ifa_addr && !(copy->ifa_addr = shdw_interface_address_copy(item->ifa_addr))) goto failure;
        if(item->ifa_netmask && !(copy->ifa_netmask = shdw_interface_address_copy(item->ifa_netmask))) goto failure;
        if(item->ifa_dstaddr && !(copy->ifa_dstaddr = shdw_interface_address_copy(item->ifa_dstaddr))) goto failure;
        if(item->ifa_data) {
            if(!item->ifa_addr || item->ifa_addr->sa_family != AF_LINK) goto failure;
            copy->ifa_data = malloc(sizeof(struct if_data));
            if(!copy->ifa_data) goto failure;
            memcpy(copy->ifa_data, item->ifa_data, sizeof(struct if_data));
        }
        shdw_interface_transform(seed, copy);
    }
    if(head) {
        shdw_interface_owned *owned = malloc(sizeof(*owned));
        if(!owned) goto failure;
        owned->head = head;
        pthread_mutex_lock(&shdw_interface_owned_lock);
        owned->next = shdw_interface_owned_lists; shdw_interface_owned_lists = owned;
        pthread_mutex_unlock(&shdw_interface_owned_lock);
    }
    *result = head;
    return YES;
failure:
    shdw_interface_list_free(head);
    return NO;
}

BOOL SHDWFingerprintReleaseInterfaces(struct ifaddrs *interfaces) {
    if(!interfaces) return NO;
    pthread_mutex_lock(&shdw_interface_owned_lock);
    shdw_interface_owned **link = &shdw_interface_owned_lists;
    while(*link && (*link)->head != interfaces) link = &(*link)->next;
    shdw_interface_owned *owned = *link;
    if(owned) *link = owned->next;
    pthread_mutex_unlock(&shdw_interface_owned_lock);
    if(!owned) return NO;
    shdw_interface_list_free(interfaces); free(owned);
    return YES;
}
