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

typedef struct {
  SHDWH2Setting settings[SHDW_H2_MAX_SETTINGS];
  size_t count;
  int32_t windowUpdate, weight;
  uint8_t exclusive, noPriority;
  char order[5];
} SHDWH2Configuration;

typedef struct {
  int32_t stream, weight;
  uint8_t exclusive;
} SHDWH2Priority;

static inline int SHDWH2ValidSetting(SHDWH2Setting entry) {
  return entry.id >= 0 && entry.id <= 65535 &&
      ((entry.id != 2 && entry.id != 8 && entry.id != 9) || entry.value <= 1) &&
      (entry.id != 4 || entry.value <= INT32_MAX) &&
      (entry.id != 5 || (entry.value >= 16384 && entry.value <= 16777215));
}

static inline int SHDWH2ConfigurationValid(const SHDWH2Configuration *config) {
  if (!config || !config->count || config->count > SHDW_H2_MAX_SETTINGS ||
      config->windowUpdate <= 0 || config->windowUpdate > INT32_MAX - 65535 ||
      config->weight < 1 || config->weight > 256 ||
      config->exclusive > 1 || config->noPriority > 1 || config->order[4])
    return 0;
  unsigned seen = 0;
  static const char alphabet[] = "masp";
  for (size_t i = 0; i < 4; ++i) {
    const char *letter = config->order[i] ? strchr(alphabet, config->order[i]) : NULL;
    if (!letter || (seen & (1u << (letter - alphabet)))) return 0;
    seen |= 1u << (letter - alphabet);
  }
  for (size_t i = 0; i < config->count; ++i) {
    if (!SHDWH2ValidSetting(config->settings[i])) return 0;
    for (size_t j = 0; j < i; ++j)
      if (config->settings[j].id == config->settings[i].id) return 0;
  }
  return 1;
}

static inline int SHDWH2Number(const char **cursor, uint32_t maximum, uint32_t *out) {
  const char *p = *cursor;
  uint32_t value = 0;
  if (*p < '0' || *p > '9') return 0;
  do {
    unsigned digit = (unsigned)(*p++ - '0');
    if (value > maximum / 10 ||
        (value == maximum / 10 && digit > maximum % 10)) return 0;
    value = value * 10 + digit;
  } while (*p >= '0' && *p <= '9');
  *cursor = p;
  *out = value;
  return 1;
}

static inline int SHDWH2ConfigurationParse(SHDWH2Configuration *out,
    const char *settings, const char *order, long windowUpdate, long weight,
    long exclusive, long noPriority) {
  if (!out || !settings || !order || strlen(order) != 4 ||
      windowUpdate <= 0 || windowUpdate > INT32_MAX - 65535 ||
      weight < 1 || weight > 256 || exclusive < 0 || exclusive > 1 ||
      noPriority < 0 || noPriority > 1) return 0;
  SHDWH2Configuration config = {0};
  config.windowUpdate = (int32_t)windowUpdate;
  config.weight = (int32_t)weight;
  config.exclusive = (uint8_t)exclusive;
  config.noPriority = (uint8_t)noPriority;
  memcpy(config.order, order, 5);
  const char *cursor = settings;
  while (*cursor) {
    uint32_t id, value;
    if (config.count == SHDW_H2_MAX_SETTINGS ||
        !SHDWH2Number(&cursor, 65535, &id) || *cursor++ != ':' ||
        !SHDWH2Number(&cursor, UINT32_MAX, &value)) return 0;
    config.settings[config.count++] = (SHDWH2Setting){(int32_t)id, value};
    if (!*cursor) break;
    if (*cursor++ != ';' || !*cursor) return 0;
  }
  if (!SHDWH2ConfigurationValid(&config)) return 0;
  *out = config;
  return 1;
}

static inline int SHDWH2Separate(const void *in, size_t inbytes,
                               const void *out, size_t outbytes) {
  uintptr_t a = (uintptr_t)in, b = (uintptr_t)out;
  return a <= b ? b - a >= inbytes : a - b >= outbytes;
}

static inline size_t SHDWH2Settings(const SHDWH2Configuration *config,
                                  const SHDWH2Setting *in, size_t count,
                                  SHDWH2Setting *out, size_t capacity) {
  if (!SHDWH2ConfigurationValid(config) || (!in && count) || !out ||
      count > SHDW_H2_MAX_SETTINGS || capacity < config->count ||
      (count && !SHDWH2Separate(in, count * sizeof(*in), out,
                               config->count * sizeof(*out))))
    return 0;
  for (size_t i = 0; i < count; ++i) {
    if (!SHDWH2ValidSetting(in[i])) return 0;
    for (size_t j = 0; j < i; ++j)
      if (in[j].id == in[i].id) return 0;
  }
  memcpy(out, config->settings, config->count * sizeof(*out));
  return config->count;
}

static inline int SHDWH2Name(const SHDWH2Header *header, const char *name) {
  size_t length = strlen(name);
  return header->namelen == length && !memcmp(header->name, name, length);
}

static inline size_t SHDWH2Headers(const SHDWH2Configuration *config,
                                 const SHDWH2Header *in, size_t count,
                                 SHDWH2Header *out, size_t capacity) {
  if (!SHDWH2ConfigurationValid(config) || !in || !out || !count ||
      count > SHDW_H2_MAX_HEADERS || capacity < count ||
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
      if (SHDWH2Name(&in[i], config->order[k] == 'm' ? ":method" :
          config->order[k] == 'a' ? ":authority" :
          config->order[k] == 's' ? ":scheme" : ":path"))
        out[n++] = in[i];
  for (size_t i = 0; i < pseudo; ++i) {
    int known = 0;
    known = SHDWH2Name(&in[i], ":method") || SHDWH2Name(&in[i], ":authority") ||
        SHDWH2Name(&in[i], ":scheme") || SHDWH2Name(&in[i], ":path");
    if (!known)
      out[n++] = in[i];
  }
  for (size_t i = pseudo; i < count; ++i)
    out[n++] = in[i];
  return n;
}
