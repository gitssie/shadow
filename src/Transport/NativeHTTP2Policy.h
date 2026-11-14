#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct { int32_t id; uint32_t value; } SHDWH2Setting;
typedef struct {
  uint8_t *name, *value;
  size_t namelen, valuelen;
  uint8_t flags;
} SHDWH2Header;

#define SHDW_H2_MAX_SETTINGS 128u
#define SHDW_H2_MAX_HEADERS 1024u

static inline int SHDWH2Separate(const void *in, size_t inbytes,
                               const void *out, size_t outbytes) {
  uintptr_t a = (uintptr_t)in, b = (uintptr_t)out;
  return a <= b ? b - a >= inbytes : a - b >= outbytes;
}

static inline size_t SHDWH2Settings(const SHDWH2Setting *in, size_t count,
                                  SHDWH2Setting *out, size_t capacity) {
  static const SHDWH2Setting target[] = {
    {2, 0}, {3, 100}, {4, 2097152}, {9, 1}
  };
  if ((!in && count) || !out || count > SHDW_H2_MAX_SETTINGS)
    return 0;
  size_t extras = 0;
  for (size_t i = 0; i < count; ++i) {
    int32_t id = in[i].id;
    uint32_t value = in[i].value;
    if (id < 0 || id > 65535 ||
        ((id == 2 || id == 8 || id == 9) && value > 1) ||
        (id == 4 && value > INT32_MAX) ||
        (id == 5 && (value < 16384 || value > 16777215)))
      return 0;
    for (size_t j = 0; j < i; ++j)
      if (in[j].id == id)
        return 0;
    if (id != 2 && id != 3 && id != 4 && id != 9)
      ++extras;
  }
  size_t needed = 4 + extras;
  if (capacity < needed ||
      (count && !SHDWH2Separate(in, count * sizeof(*in), out,
                               needed * sizeof(*out))))
    return 0;
  memcpy(out, target, sizeof(target));
  size_t n = 4;
  for (size_t i = 0; i < count; ++i)
    if (in[i].id != 2 && in[i].id != 3 && in[i].id != 4 && in[i].id != 9)
      out[n++] = in[i];
  return n;
}

static inline int SHDWH2Name(const SHDWH2Header *header, const char *name) {
  size_t length = strlen(name);
  return header->namelen == length && !memcmp(header->name, name, length);
}

static inline size_t SHDWH2Headers(const SHDWH2Header *in, size_t count,
                                 SHDWH2Header *out, size_t capacity) {
  static const char *const order[] = {":method", ":scheme", ":authority", ":path"};
  if (!in || !out || !count || count > SHDW_H2_MAX_HEADERS || capacity < count ||
      !SHDWH2Separate(in, count * sizeof(*in), out, count * sizeof(*out)))
    return 0;
  size_t pseudo = 0;
  for (size_t i = 0; i < count; ++i) {
    if (!in[i].name || !in[i].namelen || (!in[i].value && in[i].valuelen))
      return 0;
    if (in[i].name[0] != ':')
      continue;
    if (i != pseudo || in[i].namelen == 1)
      return 0;
    for (size_t j = 0; j < pseudo; ++j)
      if (in[j].namelen == in[i].namelen &&
          !memcmp(in[j].name, in[i].name, in[i].namelen))
        return 0;
    ++pseudo;
  }
  if (!pseudo)
    return 0;
  size_t n = 0;
  for (size_t k = 0; k < 4; ++k)
    for (size_t i = 0; i < pseudo; ++i)
      if (SHDWH2Name(&in[i], order[k]))
        out[n++] = in[i];
  for (size_t i = 0; i < pseudo; ++i) {
    int known = 0;
    for (size_t k = 0; k < 4; ++k)
      known |= SHDWH2Name(&in[i], order[k]);
    if (!known)
      out[n++] = in[i];
  }
  for (size_t i = pseudo; i < count; ++i)
    out[n++] = in[i];
  return n;
}
