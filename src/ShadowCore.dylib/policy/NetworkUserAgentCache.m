#import "NetworkUserAgentCache.h"
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach-o/loader.h>
#include <stdatomic.h>
#include <string.h>
#if __has_feature(ptrauth_calls)
#include <ptrauth.h>
#endif

#if defined(__arm64__) || defined(__aarch64__)
static BOOL SHDWNetworkRead(uintptr_t address, void *out, size_t size) {
    vm_size_t copied = 0;
    return vm_read_overwrite(mach_task_self(), address, size,
        (vm_address_t)out, &copied) == KERN_SUCCESS && copied == size;
}

static BOOL SHDWNetworkWritableSlot(const void *getter, uintptr_t slot) {
    Dl_info image = {0};
    const char prefix[] = "/System/Library/Frameworks/CFNetwork.framework/";
    if(!dladdr(getter, &image) || !image.dli_fbase || !image.dli_fname ||
       strncmp(image.dli_fname, prefix, sizeof(prefix) - 1)) return NO;
    uintptr_t base = (uintptr_t)image.dli_fbase;
    struct mach_header_64 header;
    if(!SHDWNetworkRead(base, &header, sizeof(header)) || header.magic != MH_MAGIC_64 ||
       !header.ncmds || header.ncmds > 512 || header.sizeofcmds > 1024 * 1024 ||
       base > UINTPTR_MAX - sizeof(header) - header.sizeofcmds) return NO;
    NSMutableData *data = [NSMutableData dataWithLength:header.sizeofcmds];
    if(!SHDWNetworkRead(base + sizeof(header), data.mutableBytes, data.length)) return NO;
    const uint8_t *bytes = data.bytes;
    uint64_t text = UINT64_MAX;
    size_t offset = 0;
    for(unsigned pass = 0; pass < 2; pass++) {
        offset = 0;
        for(uint32_t i = 0; i < header.ncmds; i++) {
            if(offset > data.length || data.length - offset < sizeof(struct load_command)) return NO;
            struct load_command command;
            memcpy(&command, bytes + offset, sizeof(command));
            if(command.cmdsize < sizeof(command) || command.cmdsize > data.length - offset) return NO;
            if(command.cmd == LC_SEGMENT_64) {
                if(command.cmdsize < sizeof(struct segment_command_64)) return NO;
                struct segment_command_64 segment;
                memcpy(&segment, bytes + offset, sizeof(segment));
                if(pass == 0 && !strncmp(segment.segname, "__TEXT", 16)) text = segment.vmaddr;
                if(pass == 1 && (segment.initprot & VM_PROT_WRITE) && segment.vmsize >= sizeof(uintptr_t)) {
                    if(text == UINT64_MAX || base < text || segment.vmaddr > UINTPTR_MAX - (base - text)) return NO;
                    uintptr_t start = segment.vmaddr + (base - text);
                    if(slot >= start && slot - start <= segment.vmsize - sizeof(uintptr_t)) return YES;
                }
            }
            offset += command.cmdsize;
        }
        if(text == UINT64_MAX) return NO;
    }
    return NO;
}
#endif

BOOL SHDWNetworkReplaceUserAgentCache(const void *getter, NSString *native, NSString *updated) {
#if defined(__arm64__) || defined(__aarch64__)
    if(!getter || !native || !updated) return NO;
#if __has_feature(ptrauth_calls)
    getter = ptrauth_strip(getter, ptrauth_key_function_pointer);
#endif
    uint32_t instructions[64];
    if(!SHDWNetworkRead((uintptr_t)getter, instructions, sizeof(instructions))) return NO;
    uintptr_t slot;
    if(!SHDWNetworkUserAgentCacheAddress(instructions, 64, (uintptr_t)getter, &slot) ||
       !SHDWNetworkWritableSlot(getter, slot)) return NO;
    vm_address_t region = slot;
    vm_size_t size = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t status = vm_region_64(mach_task_self(), &region, &size,
        VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object);
    if(object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    if(status != KERN_SUCCESS || !(info.protection & VM_PROT_WRITE) || region > slot ||
       size < sizeof(uintptr_t) || slot - region > size - sizeof(uintptr_t)) return NO;
    uintptr_t expected = (uintptr_t)(__bridge CFStringRef)native;
    if(atomic_load_explicit((_Atomic(uintptr_t) *)slot, memory_order_acquire) != expected) return NO;
    if(native == updated) return YES;
    CFStringRef retained = (CFStringRef)CFBridgingRetain(updated);
    BOOL changed = atomic_compare_exchange_strong_explicit((_Atomic(uintptr_t) *)slot,
        &expected, (uintptr_t)retained, memory_order_acq_rel, memory_order_acquire);
    // Keep the previous immutable value alive for readers that already loaded it.
    if(!changed) CFRelease(retained);
    return changed;
#else
    (void)getter; (void)native; (void)updated;
    return NO;
#endif
}
