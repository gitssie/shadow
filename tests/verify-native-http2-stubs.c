#include "../src/Transport/NativeHTTP2Stubs.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void word(uint8_t *out, uint32_t value) {
  for (unsigned i = 0; i < 4; ++i) out[i] = (uint8_t)(value >> (8 * i));
}
static void stub(uint8_t *out, int32_t pages, uint32_t offset) {
  uint32_t immediate = (uint32_t)pages & 0x1fffffu;
  word(out, 0x90000010u | (immediate & 3u) << 29 |
      (immediate >> 2) << 5);
  word(out + 4, 0x91000210u | offset << 10);
  word(out + 8, 0xd61f0200u);
  word(out + 12, 0xd4200020u);
}
static void rejected(const void *code, size_t length, uintptr_t pc) {
  uintptr_t result = 123;
  assert(!SHDWH2DecodeCommonStub(code, length, pc, &result));
  assert(result == 123);
}
int main(void) {
  uint8_t code[16], altered[16];
  uintptr_t target = 0;
  stub(code, 1, 0x344);
  assert(SHDWH2DecodeCommonStub(code, 16, 0x1234, &target));
  assert(target == 0x2344);
  stub(code, -1, 0xabc);
  assert(SHDWH2DecodeCommonStub(code, 16, 0x2340, &target));
  assert(target == 0x1abc);
  stub(code, 0, 0xfff);
  assert(SHDWH2DecodeCommonStub(code, 16, 0, &target) && target == 0xfff);
  assert(SHDWH2DecodeCommonStub(code, 16, UINTPTR_MAX - 15, &target));
  assert(target == UINTPTR_MAX);
  stub(code, -1048576, 0);
#if UINTPTR_MAX > UINT32_MAX
  assert(SHDWH2DecodeCommonStub(code, 16, UINT64_C(0x100000000), &target));
  assert(target == 0);
  stub(code, 1048575, 0xfff);
  assert(SHDWH2DecodeCommonStub(code, 16, 0, &target));
  assert(target == UINT64_C(0xffffffff));
  /* Captured common-stub instruction words, independently decoded address. */
  word(code, 0x90245950); word(code + 4, 0x91311210);
  assert(SHDWH2DecodeCommonStub(code, 16, UINT64_C(0x18ca3c930), &target));
  assert(target == UINT64_C(0x1d5564c44));
#endif
  stub(code, -1, 0);
  rejected(code, 16, 0);
  stub(code, 1, 0);
  rejected(code, 16, UINTPTR_MAX - 15);
  stub(code, 0, 0);
  rejected(code, 16, UINTPTR_MAX - 3);
  rejected(code, 16, 2);
  rejected(code, 15, 0);
  rejected(NULL, 16, 0);
  assert(!SHDWH2DecodeCommonStub(code, 16, 0, NULL));
  /* Every fixed opcode/register bit must match; immediate bits remain free. */
  const uint32_t masks[] = {0x9f00001f, 0xffc003ff, 0xffffffff, 0xffffffff};
  for (unsigned i = 0; i < 4; ++i) {
    for (unsigned bit = 0; bit < 32; ++bit) {
      if (!(masks[i] & (UINT32_C(1) << bit))) continue;
      memcpy(altered, code, sizeof(code));
      altered[i * 4 + bit / 8] ^= (uint8_t)(1u << (bit % 8));
      rejected(altered, 16, 0x1000);
    }
  }
  /* Byte buffers may be unaligned even though the instruction PC is aligned. */
  uint8_t unaligned[17];
  memcpy(unaligned + 1, code, 16);
  assert(SHDWH2DecodeCommonStub(unaligned + 1, 16, 0x1000, &target));
  assert(target == 0x1000);
  puts("Native HTTP/2 common stub decoder checks passed");
  return 0;
}
