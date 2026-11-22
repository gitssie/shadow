#import "BackgroundDiscovery.h"
#include "BackgroundDiscoveryPolicy.h"
#include "NativeHTTP2Stubs.h"
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach-o/dyld.h>
#include <mach-o/getsect.h>
#include <ptrauth.h>
#include <stdlib.h>

typedef struct { uintptr_t address,resolved; } BranchEntry;
typedef struct { void *(*enclosing)(void *); uintptr_t textStart,textEnd; BranchEntry *branches; BOOL exhausted; } DiscoveryContext;
enum {BranchCapacity=32768};
static uintptr_t ResolveBranch(uintptr_t target,void *context) {
    DiscoveryContext *state=context;
    if(target>=state->textStart && target<state->textEnd)return target;
    size_t slot=(target>>2)%BranchCapacity,probes=0;
    while(state->branches[slot].address && state->branches[slot].address!=target) {
        if(++probes==BranchCapacity){state->exhausted=YES;return 0;}
        slot=(slot+1)%BranchCapacity;
    }
    if(state->branches[slot].address)return state->branches[slot].resolved;
    uint8_t bytes[16];vm_size_t length=0;uintptr_t decoded=target;
    if(vm_read_overwrite(mach_task_self(),target,sizeof(bytes),(vm_address_t)bytes,&length)==KERN_SUCCESS &&
       length==sizeof(bytes)) {
        uintptr_t candidate;
        if(SHDWH2DecodeCommonStub(bytes,sizeof(bytes),target,&candidate))decoded=candidate;
    }
    state->branches[slot]=(BranchEntry){target,decoded};
    return decoded;
}
static uintptr_t Enclosing(uintptr_t pc,void *context) {
    DiscoveryContext *state=context;
    void *result=state->enclosing((void *)pc);
    return (uintptr_t)ptrauth_strip(result,ptrauth_key_function_pointer);
}
BOOL SHDWBackgroundDiscoveryFind(void **ingest,void **property) {
    if(ingest)*ingest=NULL;if(property)*property=NULL;if(!ingest || !property)return NO;
    const char *image="/System/Library/Frameworks/CFNetwork.framework/CFNetwork";
    DiscoveryContext context={.enclosing=dlsym(RTLD_DEFAULT,"_Unwind_FindEnclosingFunction")};
    if(!context.enclosing)return NO;
    void *handle=dlopen("/usr/lib/libapple_nghttp2.dylib",RTLD_LAZY|RTLD_NOLOAD);if(!handle)return NO;
    SHDWBGDiscoveryInput input={0};
    input.dictionaryGet=(uintptr_t)ptrauth_strip((void *)CFDictionaryGetValue,ptrauth_key_function_pointer);
    input.retainValue=(uintptr_t)ptrauth_strip((void *)CFRetain,ptrauth_key_function_pointer);
    input.createSession=(uintptr_t)ptrauth_strip(dlsym(handle,"nghttp2_session_client_new2"),ptrauth_key_function_pointer);
    dlclose(handle);
    input.resolveBranch=ResolveBranch;input.enclosingFunction=Enclosing;input.context=&context;
    for(uint32_t index=0;index<_dyld_image_count();index++) {
        const char *name=_dyld_get_image_name(index);if(!name || strcmp(name,image))continue;
        const struct mach_header_64 *header=(const void *)_dyld_get_image_header(index);
        if(!header || header->magic!=MH_MAGIC_64)return NO;
        const struct section_64 *text=getsectbynamefromheader_64(header,"__TEXT","__text");
        if(!text || text->size>64*1024*1024)return NO;
        input.address=text->addr+_dyld_get_image_vmaddr_slide(index);input.bytes=(const void *)input.address;input.length=text->size;
        if(input.length>UINTPTR_MAX-input.address)return NO;
        context.textStart=input.address;context.textEnd=input.address+input.length;
        context.branches=calloc(BranchCapacity,sizeof(*context.branches));if(!context.branches)return NO;
        uintptr_t foundIngest,foundProperty;
        BOOL matched=SHDWBGDiscover(&input,&foundIngest,&foundProperty) && !context.exhausted;
        free(context.branches);
        if(!matched)return NO;
        *ingest=ptrauth_sign_unauthenticated((void *)foundIngest,ptrauth_key_function_pointer,0);
        *property=ptrauth_sign_unauthenticated((void *)foundProperty,ptrauth_key_function_pointer,0);
        return YES;
    }
    return NO;
}
