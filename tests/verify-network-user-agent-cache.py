"""Check bounded ARM64 cache-reference decoding with adversarial fixtures."""
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
source=r"""
#include "NetworkUserAgentCache.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t adrp(unsigned reg,int pages) {
    uint32_t bits=(uint32_t)pages & 0x1fffff;
    return 0x90000000u | ((bits&3)<<29) | ((bits>>2)<<5) | reg;
}
static uint32_t ldr(unsigned base,unsigned offset) { return 0xf9400001u | (base<<5) | ((offset/8)<<10); }
int main(void) {
    uint32_t code[]={0xd503237fu,0x94000000u,adrp(8,3),ldr(8,0x238),0x14000400u};
    uintptr_t result=0;
    assert(SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result) && result==0x10003238);
    code[2]=adrp(9,-1);code[3]=ldr(9,0x7f8);
    assert(SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result) && result==0x0ffff7f8);
    for(unsigned i=0;i<3;i++) {
        code[4]=i==0?0xd65f03c0u:i==1?0xd65f0bffu:0xd65f0fffu;
        assert(SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));
    }
    code[1]=0xd503201fu;assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));code[1]=0x94000000u;
    code[3]=ldr(8,0x7f8);assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));code[3]=ldr(9,0x7f8);
    code[3]^=1;assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));code[3]^=1;
    code[3]^=0x40000000;assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));code[3]^=0x40000000;
    assert(!SHDWNetworkUserAgentCacheAddress(code,4,0x10000100,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(NULL,5,0x10000100,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,NULL));
    assert(!SHDWNetworkUserAgentCacheAddress(code,0,0x10000100,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(code,65,0x10000100,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000101,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(code,5,UINTPTR_MAX-3,&result));
    assert(!SHDWNetworkUserAgentCacheAddress(code,5,0,&result));
    code[2]=adrp(31,3);code[3]=ldr(31,0);assert(!SHDWNetworkUserAgentCacheAddress(code,5,0x10000100,&result));
    uint32_t ambiguous[]={0x94000000u,adrp(8,3),ldr(8,0),adrp(9,4),ldr(9,0),0xd65f03c0u};
    assert(!SHDWNetworkUserAgentCacheAddress(ambiguous,6,0x10000000,&result));
    ambiguous[3]=adrp(9,3);assert(SHDWNetworkUserAgentCacheAddress(ambiguous,6,0x10000000,&result));
    ambiguous[0]=0xd65f03c0u;assert(!SHDWNetworkUserAgentCacheAddress(ambiguous,6,0x10000000,&result));
    uint32_t tail[]={0x94000000u,0xd61f0200u,adrp(8,3),ldr(8,0),0xd65f03c0u};
    for(unsigned i=0;i<3;i++) {
        tail[1]=i==0?0xd61f0200u:i==1?0xd71f0a11u:0xd73f0a11u;
        assert(!SHDWNetworkUserAgentCacheAddress(tail,5,0x10000000,&result));
    }
    tail[1]=0x54000040u;assert(!SHDWNetworkUserAgentCacheAddress(tail,5,0x10000000,&result));
    tail[1]=0xb4000050u;assert(!SHDWNetworkUserAgentCacheAddress(tail,5,0x10000000,&result));
    tail[1]=0xb6f00050u;assert(!SHDWNetworkUserAgentCacheAddress(tail,5,0x10000000,&result));
    uint32_t pac[]={0x94000000u,adrp(8,3),ldr(8,0),0xb6f00050u,0xd4388e20u,0x14000400u};
    assert(SHDWNetworkUserAgentCacheAddress(pac,6,0x10000000,&result));
    pac[4]=0xd4200000u;assert(!SHDWNetworkUserAgentCacheAddress(pac,6,0x10000000,&result));
    pac[3]=0x14000001u;assert(!SHDWNetworkUserAgentCacheAddress(pac,6,0x10000000,&result));
    puts("network UA cache: bounded ARM64 references, signed pages, overflow, register/width checks and ambiguity passed");
}
"""
with tempfile.TemporaryDirectory(prefix="shadow-network-cache-") as tmp:
    sourcefile=Path(tmp)/"test.c";binary=Path(tmp)/"test"
    sourcefile.write_text(source)
    subprocess.run(["clang","-std=c11","-Wall","-Wextra","-Werror","-fsanitize=address,undefined",
        "-I",str(root/"src/ShadowCore.dylib/policy"),str(sourcefile),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
