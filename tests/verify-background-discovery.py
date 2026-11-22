#!/usr/bin/env python3
"""Check bounded ARM64 construction discovery and ambiguity rejection."""
from pathlib import Path
import os
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
source=r"""
#include "BackgroundDiscoveryPolicy.h"
#include <assert.h>
#include <stdio.h>
#define BASE 0x100000u
#define DICT 0x180000u
#define RETAIN 0x180040u
#define NEW2 0x180080u
static uint8_t bytes[4096];
static uintptr_t bounds[8][2];
static size_t boundCount;
static uintptr_t Resolve(uintptr_t target,void *context){(void)context;return target;}
static uintptr_t Boundary(uintptr_t pc,void *context){(void)context;for(size_t i=0;i<boundCount;i++)if(pc>=bounds[i][0] && pc<bounds[i][1])return bounds[i][0];return 0;}
static void Put(uintptr_t pc,uint32_t value){assert(pc>=BASE && pc-BASE+4<=sizeof(bytes));memcpy(bytes+(pc-BASE),&value,4);}
static uint32_t Branch(uintptr_t pc,uintptr_t target,bool link){return (link?0x94000000u:0x14000000u)|((uint32_t)((int64_t)target-(int64_t)pc)/4&0x3ffffffu);}
static void Bound(uintptr_t a,size_t length){bounds[boundCount][0]=a;bounds[boundCount++][1]=a+length;}
static void Getter(uintptr_t start){
    uint32_t words[]={0xd503237f,0xa9bf7bfd,0x910003fd,0xaa0003e8,0xf9402000,0xb40001e0,
      0xf9400010,0xaa0003f1,0xf2e00011,0xdac11a30,0xf8410e02,0xaa1003e3,
      0xa8c17bfd,0xd50323ff,0xca1e07d0,0xb6f00050,0xd4388e20,0xaa0303f0,
      0xf2e00010,0xd71f0850,0xf9404100,0xb4000120,0,0xb40000e0,
      0xa8c17bfd,0xd50323ff,0xca1e07d0,0xb6f00050,0xd4388e20,0,
      0xd2800000,0xa8c17bfd,0xd65f0fff};
    words[22]=Branch(start+88,DICT,true);words[29]=Branch(start+116,RETAIN,false);
    for(size_t i=0;i<33;i++)Put(start+i*4,words[i]);Bound(start,132);
}
static void Initializer(uintptr_t start){Put(start,0xd503237f);Put(start+16,Branch(start+16,NEW2,true));Bound(start,64);}
static void Ingest(uintptr_t start,uintptr_t initializer){
    Put(start,0xd503237f);Put(start+4,0xaa0003f3);Put(start+8,0xaa0103f4);Put(start+12,0xaa0203f5);
    assert((start&~4095u)==(initializer&~4095u));
    Put(start+24,0x90000010);Put(start+28,0x91000210|((initializer&4095u)<<10));
    Put(start+32,0xa902a3f0);Put(start+48,Branch(start+48,initializer,true));Bound(start,96);
}
static SHDWBGDiscoveryInput Fixture(void){
    memset(bytes,0,sizeof(bytes));boundCount=0;
    Getter(BASE+128);Initializer(BASE+1024);Ingest(BASE+1536,BASE+1024);
    SHDWBGDiscoveryInput input={bytes,sizeof(bytes),BASE,DICT,RETAIN,NEW2,Resolve,Boundary,NULL};return input;
}
static void Reject(SHDWBGDiscoveryInput *input){uintptr_t a=99,b=99;assert(!SHDWBGDiscover(input,&a,&b) && !a && !b);}
int main(void){
    SHDWBGDiscoveryInput input=Fixture();uintptr_t a,b;
    assert(SHDWBGDiscover(&input,&a,&b) && a==BASE+1536 && b==BASE+128);
    Put(BASE+128+16,0xf9410000);Put(BASE+128+80,0xf9420100);
    assert(SHDWBGDiscover(&input,&a,&b));
    input=Fixture();Put(BASE+128+12,0xaa0003e1);Reject(&input);
    input=Fixture();Put(BASE+128+84,0xb4000100);Reject(&input);
    input=Fixture();Put(BASE+128+88,Branch(BASE+128+88,RETAIN,true));Reject(&input);
    input=Fixture();Put(BASE+128+116,Branch(BASE+128+116,DICT,false));Reject(&input);
    input=Fixture();Getter(BASE+384);Reject(&input);
    input=Fixture();Initializer(BASE+1152);Reject(&input);
    input=Fixture();Ingest(BASE+1792,BASE+1024);Reject(&input);
    input=Fixture();Put(BASE+1536+28,0x91000010);Reject(&input);
    input=Fixture();Put(BASE+1536+12,0xaa0303f5);Reject(&input);
    input=Fixture();boundCount=0;Reject(&input);
    input=Fixture();input.length=129;Reject(&input);
    input=Fixture();input.address=UINTPTR_MAX-2;Reject(&input);
    input=Fixture();input.resolveBranch=NULL;Reject(&input);
    input=Fixture();input.createSession=0;Reject(&input);
    puts("background discovery: semantic dataflow, variable displacements, graph uniqueness, ABI guards and bounds passed");
}
"""
with tempfile.TemporaryDirectory(prefix="shadow-background-discovery-") as directory:
    path=Path(directory)/"test.c";binary=Path(directory)/"test";path.write_text(source)
    subprocess.run([os.environ.get("CC","cc"),"-std=c11","-Wall","-Wextra","-Werror","-fsanitize=address,undefined","-I",str(root/"src/Transport"),str(path),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0",UBSAN_OPTIONS="halt_on_error=1"))
