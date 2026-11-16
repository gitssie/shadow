#pragma once
#include <curl/curl.h>
#include "NativeHTTP2Policy.h"

typedef CURLcode (*SHDWCurlHTTP2ConfigFunction)(CURL *, char *, size_t,
    char *, size_t, long *, long *, long *, long *);

static inline CURLcode SHDWCurlReadHTTP2Configuration(CURL *curl,
    SHDWCurlHTTP2ConfigFunction read, SHDWH2Configuration *out) {
  if (!curl || !read || !out) return CURLE_BAD_FUNCTION_ARGUMENT;
  char settings[4096] = {0}, order[5] = {0};
  long windowUpdate = 0, weight = 0, exclusive = 0, noPriority = 0;
  CURLcode result = read(curl, settings, sizeof(settings), order, sizeof(order),
      &windowUpdate, &weight, &exclusive, &noPriority);
  if (result != CURLE_OK) return result;
  if (!memchr(settings, 0, sizeof(settings)) || !memchr(order, 0, sizeof(order)) ||
      !SHDWH2ConfigurationParse(out, settings, order, windowUpdate, weight,
                               exclusive, noPriority))
    return CURLE_BAD_FUNCTION_ARGUMENT;
  return CURLE_OK;
}
