#ifndef SHADOW_FINGERPRINT_RESET_BASELINE_H
#define SHADOW_FINGERPRINT_RESET_BASELINE_H

#import <Foundation/Foundation.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

static inline BOOL SHDWFingerprintResetInteger(id value, int64_t *output) {
  if (![value isKindOfClass:NSNumber.class] ||
      CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID())
    return NO;
  const char *type = [value objCType];
  if (!type || !type[0] || type[1] || !strchr("cCsSiIlLqQ", type[0]))
    return NO;
  if (strchr("CSILQ", type[0]) && [value unsignedLongLongValue] > INT64_MAX)
    return NO;
  int64_t result = [value longLongValue];
  if (result < 0)
    return NO;
  if (output)
    *output = result;
  return YES;
}

static inline BOOL SHDWFingerprintResetBaselineValid(id value) {
  if (![value isKindOfClass:NSDictionary.class] || [value count] != 2)
    return NO;
  int64_t version;
  if (!SHDWFingerprintResetInteger(value[@"Version"], &version) || version != 1)
    return NO;
  id containers = value[@"Containers"];
  if (![containers isKindOfClass:NSDictionary.class] || [containers count] > 64)
    return NO;
  for (id key in containers) {
    if (![key isKindOfClass:NSString.class] || ![key length] ||
        [key length] > 255 || [key containsString:@"/"])
      return NO;
    id record = containers[key];
    if (![record isKindOfClass:NSDictionary.class] || [record count] != 3)
      return NO;
    id identity = record[@"Identity"];
    if (![identity isKindOfClass:NSString.class] || [identity length] != 64 ||
        [identity
            rangeOfCharacterFromSet:[[NSCharacterSet
                                        characterSetWithCharactersInString:
                                            @"0123456789abcdef"] invertedSet]]
                .location != NSNotFound)
      return NO;
    int64_t seconds, nanoseconds;
    if (!SHDWFingerprintResetInteger(record[@"Seconds"], &seconds) ||
        !SHDWFingerprintResetInteger(record[@"Nanoseconds"], &nanoseconds) ||
        nanoseconds >= 1000000000)
      return NO;
  }
  return YES;
}

static inline BOOL SHDWFingerprintResetBaselineTimesEqual(id left, id right) {
  if (!left || !right)
    return left == right;
  if (!SHDWFingerprintResetBaselineValid(left) ||
      !SHDWFingerprintResetBaselineValid(right))
    return NO;
  NSDictionary *a = left[@"Containers"], *b = right[@"Containers"];
  if (a.count != b.count)
    return NO;
  for (NSString *key in a) {
    if (!b[key] || ![a[key][@"Seconds"] isEqual:b[key][@"Seconds"]] ||
        ![a[key][@"Nanoseconds"] isEqual:b[key][@"Nanoseconds"]])
      return NO;
  }
  return YES;
}

static inline BOOL SHDWFingerprintResetTimeUpperBound(struct timespec baseline,
                                                      struct timespec now,
                                                      uint32_t *upper) {
  if (!upper || baseline.tv_sec < 0 || now.tv_sec < 0 || baseline.tv_nsec < 0 ||
      baseline.tv_nsec >= 1000000000 || now.tv_nsec < 0 ||
      now.tv_nsec >= 1000000000 || baseline.tv_sec > now.tv_sec ||
      (baseline.tv_sec == now.tv_sec && baseline.tv_nsec > now.tv_nsec))
    return NO;
  uintmax_t available = (uintmax_t)now.tv_sec - (uintmax_t)baseline.tv_sec;
  if (now.tv_nsec < baseline.tv_nsec)
    available--;
  *upper = (uint32_t)(available < 864000 ? available : 864000);
  return YES;
}

static inline BOOL SHDWFingerprintResetTime(struct timespec baseline,
                                            struct timespec now,
                                            uint32_t increment,
                                            struct timespec *output) {
  uint32_t upper;
  if (!output || !SHDWFingerprintResetTimeUpperBound(baseline, now, &upper) ||
      increment > upper)
    return NO;
  struct timespec result = baseline;
  result.tv_sec = (time_t)((uintmax_t)baseline.tv_sec + increment);
  *output = result;
  return YES;
}

#endif
