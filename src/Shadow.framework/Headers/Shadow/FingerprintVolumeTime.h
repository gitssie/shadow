#ifndef SHADOW_FINGERPRINT_VOLUME_TIME_H
#define SHADOW_FINGERPRINT_VOLUME_TIME_H

#import <Foundation/Foundation.h>
#include <math.h>
#include <stdint.h>
#include <string.h>

static inline BOOL SHDWFingerprintVolumeTimeValid(id value) {
  if (![value isKindOfClass:NSNumber.class] ||
      CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID())
    return NO;
  const char *type = [value objCType];
  if (type && type[0] && !type[1] && strchr("cCsSiIlLqQ", type[0])) {
    if (strchr("CSILQ", type[0]) && [value unsignedLongLongValue] > INT64_MAX)
      return NO;
    return [value longLongValue] > 0;
  }
  double seconds = [value doubleValue];
  if (!isfinite(seconds) || seconds <= 0 || seconds >= 0x1p63 ||
      floor(seconds) != seconds)
    return NO;
  NSNumber *integer = @((int64_t)seconds);
  if ([value isKindOfClass:NSDecimalNumber.class]) {
    return [value compare:[NSDecimalNumber
                              decimalNumberWithString:integer.stringValue]] ==
           NSOrderedSame;
  }
  return [value compare:integer] == NSOrderedSame;
}

static inline BOOL SHDWFingerprintVolumeTimeRange(NSDate *now, NSTimeZone *zone,
                                                  NSTimeInterval modified,
                                                  int64_t *first,
                                                  uint32_t *count) {
  if (!first || !count || ![now isKindOfClass:NSDate.class] ||
      ![zone isKindOfClass:NSTimeZone.class] || !isfinite(modified) ||
      modified <= 0)
    return NO;
  NSTimeInterval current = now.timeIntervalSince1970;
  if (!isfinite(current) || current <= 0 || current >= 0x1p63)
    return NO;
  NSCalendar *calendar = [[NSCalendar alloc]
      initWithCalendarIdentifier:NSCalendarIdentifierGregorian];
  calendar.timeZone = zone;
  NSDate *currentStart = nil, *previousStart = nil;
  NSTimeInterval interval = 0;
  if (![calendar rangeOfUnit:NSCalendarUnitMonth
                   startDate:&currentStart
                    interval:&interval
                     forDate:now])
    return NO;
  NSDate *previous = [calendar dateByAddingUnit:NSCalendarUnitMonth
                                          value:-1
                                         toDate:currentStart
                                        options:0];
  if (!previous || ![calendar rangeOfUnit:NSCalendarUnitMonth
                                startDate:&previousStart
                                 interval:&interval
                                  forDate:previous])
    return NO;
  NSTimeInterval begin = previousStart.timeIntervalSince1970;
  NSTimeInterval end = begin + interval;
  if (!isfinite(begin) || !isfinite(end) || !isfinite(interval) ||
      interval <= 0)
    return NO;
  double lower = fmax(1, ceil(begin));
  double upper = fmin(ceil(end), fmin(ceil(modified), ceil(current)));
  if (!isfinite(lower) || !isfinite(upper) || lower >= 0x1p63 ||
      upper >= 0x1p63 || upper <= lower)
    return NO;
  int64_t start = (int64_t)lower, limit = (int64_t)upper;
  uint64_t length = (uint64_t)limit - (uint64_t)start;
  if (!length || length > UINT32_MAX)
    return NO;
  *first = start;
  *count = (uint32_t)length;
  return YES;
}

#endif
