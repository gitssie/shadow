#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

typedef uintptr_t (*SHDWBGBranchResolver)(uintptr_t target, void *context);
typedef uintptr_t (*SHDWBGBoundaryResolver)(uintptr_t pc, void *context);
typedef struct {
    const uint8_t *bytes;
    size_t length;
    uintptr_t address;
    uintptr_t dictionaryGet, retainValue, createSession;
    SHDWBGBranchResolver resolveBranch;
    SHDWBGBoundaryResolver enclosingFunction;
    void *context;
} SHDWBGDiscoveryInput;

static inline uint32_t SHDWBGWord(const uint8_t *bytes) {
    uint32_t word;memcpy(&word,bytes,4);return word;
}
static inline bool SHDWBGAdd(uintptr_t pc,int64_t delta,uintptr_t *out) {
    if(delta<0) {if((uint64_t)(-delta)>pc)return false;*out=pc-(uintptr_t)(-delta);}
    else {if((uint64_t)delta>UINTPTR_MAX-pc)return false;*out=pc+(uintptr_t)delta;}
    return true;
}
static inline bool SHDWBGBranch(uint32_t word,uintptr_t pc,bool link,uintptr_t *out) {
    if((word&0xfc000000u)!=(link?0x94000000u:0x14000000u))return false;
    int64_t imm=word&0x3ffffffu;if(imm&0x2000000)imm-=0x4000000;
    return SHDWBGAdd(pc,imm*4,out);
}
static inline bool SHDWBGCompareBranch(uint32_t word,uintptr_t pc,uintptr_t *out) {
    if((word&0xff00001fu)!=0xb4000000u)return false;
    int64_t imm=(word>>5)&0x7ffff;if(imm&0x40000)imm-=0x80000;
    return SHDWBGAdd(pc,imm*4,out);
}
static inline bool SHDWBGIsTarget(const SHDWBGDiscoveryInput *input,uintptr_t pc,uint32_t word,bool link,uintptr_t expected) {
    uintptr_t target;
    return SHDWBGBranch(word,pc,link,&target) && input->resolveBranch(target,input->context)==expected;
}
static inline bool SHDWBGGetter(const SHDWBGDiscoveryInput *input,uintptr_t start) {
    enum {Words=33,Bytes=Words*4};
    if(start<input->address || start-input->address>input->length || input->length-(start-input->address)<Bytes)return false;
    const uint8_t *p=input->bytes+(start-input->address);
    static const uint32_t masks[Words]={
        0xffffffff,0xffc07fff,0xffc003ff,0xffffffff,0xffc003ff,0xff00001f,
        0xffffffff,0xffffffff,0xffe0001f,0xffffffff,0xffe00fff,0xffffffff,
        0xffc07fff,0xffffffff,0xffffffff,0xfff8001f,0xffffffff,0xffffffff,
        0xffe0001f,0xffffffff,0xffc003ff,0xff00001f,0xfc000000,0xff00001f,
        0xffc07fff,0xffffffff,0xffffffff,0xfff8001f,0xffffffff,0xfc000000,
        0xffffffff,0xffc07fff,0xffffffff};
    static const uint32_t forms[Words]={
        0xd503237f,0xa9807bfd,0x910003fd,0xaa0003e8,0xf9400000,0xb4000000,
        0xf9400010,0xaa0003f1,0xf2e00011,0xdac11a30,0xf8400e02,0xaa1003e3,
        0xa8c07bfd,0xd50323ff,0xca1e07d0,0xb6f00010,0xd4388e20,0xaa0303f0,
        0xf2e00010,0xd71f0850,0xf9400100,0xb4000000,0x94000000,0xb4000000,
        0xa8c07bfd,0xd50323ff,0xca1e07d0,0xb6f00010,0xd4388e20,0x14000000,
        0xd2800000,0xa8c07bfd,0xd65f0fff};
    for(size_t i=0;i<Words;i++)if((SHDWBGWord(p+4*i)&masks[i])!=forms[i])return false;
    uintptr_t destination;
    if(!SHDWBGCompareBranch(SHDWBGWord(p+20),start+20,&destination) || destination!=start+80)return false;
    if(!SHDWBGCompareBranch(SHDWBGWord(p+84),start+84,&destination) || destination!=start+120)return false;
    if(!SHDWBGCompareBranch(SHDWBGWord(p+92),start+92,&destination) || destination!=start+120)return false;
    for(size_t i=15;i<=27;i+=12) {
        int64_t imm=(SHDWBGWord(p+4*i)>>5)&0x3fff;if(imm&0x2000)imm-=0x4000;
        if(!SHDWBGAdd(start+4*i,imm*4,&destination) || destination!=start+4*(i+2))return false;
    }
    return SHDWBGIsTarget(input,start+88,SHDWBGWord(p+88),true,input->dictionaryGet) &&
           SHDWBGIsTarget(input,start+116,SHDWBGWord(p+116),false,input->retainValue) &&
           input->enclosingFunction(start,input->context)==start &&
           input->enclosingFunction(start+128,input->context)==start &&
           input->enclosingFunction(start+132,input->context)!=start;
}
static inline bool SHDWBGThreeArguments(const SHDWBGDiscoveryInput *input,uintptr_t start) {
    if(start<input->address || start-input->address>input->length || input->length-(start-input->address)<64)return false;
    const uint8_t *p=input->bytes+(start-input->address);
    if(SHDWBGWord(p)!=0xd503237fu)return false;
    unsigned sources=0,destinations=0;
    for(size_t offset=4;offset<64;offset+=4) {
        uint32_t word=SHDWBGWord(p+offset);
        if((word&0xffe0ffe0u)==0xaa0003e0u) {
            unsigned source=(word>>16)&31,destination=word&31;
            if(source<3 && destination>=19 && destination<=28) {
                unsigned bit=1u<<(destination-19);if(destinations&bit)return false;
                sources|=1u<<source;destinations|=bit;
            }
        }
    }
    return sources==7;
}
static inline bool SHDWBGBlockReference(const SHDWBGDiscoveryInput *input,uintptr_t caller,uintptr_t call,uintptr_t initializer) {
    if(call<caller || call-caller>65536 || caller<input->address)return false;
    uintptr_t begin=call-caller>128?call-128:caller;
    for(uintptr_t pc=begin;pc<call && call-pc>8;pc+=4) {
        uint32_t adrp=SHDWBGWord(input->bytes+(pc-input->address)),add=SHDWBGWord(input->bytes+(pc+4-input->address));
        unsigned reg=adrp&31;
        if((adrp&0x9f000000u)!=0x90000000u || (add&0xffc00000u)!=0x91000000u || (add&31)!=reg || ((add>>5)&31)!=reg)continue;
        int64_t pages=(((adrp>>5)&0x7ffffu)<<2)|((adrp>>29)&3);if(pages&0x100000)pages-=0x200000;
        uintptr_t page,target;
        if(!SHDWBGAdd(pc&~(uintptr_t)4095,pages*4096,&page) || !SHDWBGAdd(page,(add>>10)&4095,&target) || target!=initializer)continue;
        for(uintptr_t store=pc+8;store<call;store+=4) {
            uint32_t word=SHDWBGWord(input->bytes+(store-input->address));
            if((word&0xffc003e0u)==0xa90003e0u && ((word&31)==reg || ((word>>10)&31)==reg))return true;
        }
    }
    return false;
}
static inline bool SHDWBGDiscover(const SHDWBGDiscoveryInput *input,uintptr_t *ingest,uintptr_t *property) {
    if(ingest)*ingest=0;if(property)*property=0;
    if(!input || !ingest || !property || !input->bytes || !input->length || input->length%4 ||
       input->length>64*1024*1024 || input->address%4 || input->length>UINTPTR_MAX-input->address ||
       !input->dictionaryGet || !input->retainValue || !input->createSession || !input->resolveBranch || !input->enclosingFunction)return false;
    uintptr_t getter=0,initializer=0;
    for(size_t offset=0;offset<input->length;offset+=4) {
        uintptr_t pc=input->address+offset;uint32_t word=SHDWBGWord(input->bytes+offset);
        if(SHDWBGIsTarget(input,pc,word,true,input->dictionaryGet)) {
            uintptr_t start=input->enclosingFunction(pc,input->context);
            if(SHDWBGGetter(input,start)) {if(getter && getter!=start)return false;getter=start;}
        }
        if(SHDWBGIsTarget(input,pc,word,true,input->createSession)) {
            uintptr_t start=input->enclosingFunction(pc,input->context);
            if(start<input->address || start>pc || pc-start>65536)return false;
            if(initializer && initializer!=start)return false;initializer=start;
        }
    }
    if(!getter || !initializer)return false;
    uintptr_t owner=0;
    for(size_t offset=0;offset<input->length;offset+=4) {
        uintptr_t pc=input->address+offset,target;uint32_t word=SHDWBGWord(input->bytes+offset);
        if(!SHDWBGBranch(word,pc,true,&target) || target!=initializer)continue;
        uintptr_t start=input->enclosingFunction(pc,input->context);
        if(!SHDWBGThreeArguments(input,start) || !SHDWBGBlockReference(input,start,pc,initializer))return false;
        if(owner && owner!=start)return false;owner=start;
    }
    if(!owner || owner==getter || owner==initializer || initializer==getter)return false;
    *ingest=owner;*property=getter;return true;
}
