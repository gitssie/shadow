#pragma once
#include <stddef.h>
#include <stdint.h>

static inline uint32_t SHDWH2StubWord(const uint8_t *bytes) {
  return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
         (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}

static inline int SHDWH2DecodeCommonStub(const void *bytes, size_t length,
                                        uintptr_t pc, uintptr_t *target) {
  if (!bytes || !target || length < 16 || (pc & 3u) ||
      pc > UINTPTR_MAX - 15u)
    return 0;
  const uint8_t *code = bytes;
  uint32_t adrp = SHDWH2StubWord(code);
  uint32_t add = SHDWH2StubWord(code + 4);
  if ((adrp & UINT32_C(0x9f00001f)) != UINT32_C(0x90000010) ||
      (add & UINT32_C(0xffc003ff)) != UINT32_C(0x91000210) ||
      SHDWH2StubWord(code + 8) != UINT32_C(0xd61f0200) ||
      SHDWH2StubWord(code + 12) != UINT32_C(0xd4200020))
    return 0;

  uint32_t immediate = ((adrp >> 5) & UINT32_C(0x7ffff)) << 2 |
                       ((adrp >> 29) & 3u);
  int64_t pages = (int64_t)immediate;
  if (immediate & UINT32_C(0x100000))
    pages -= INT64_C(0x200000);
  int64_t delta = pages * INT64_C(4096);
  uintptr_t page = pc & ~(uintptr_t)4095u;
  if (delta < 0) {
    uint64_t magnitude = (uint64_t)(-delta);
    if (magnitude > page) return 0;
    page -= (uintptr_t)magnitude;
  } else {
    if ((uint64_t)delta > UINTPTR_MAX - page) return 0;
    page += (uintptr_t)delta;
  }
  uintptr_t offset = (add >> 10) & 4095u;
  if (offset > UINTPTR_MAX - page) return 0;
  *target = page + offset;
  return 1;
}
