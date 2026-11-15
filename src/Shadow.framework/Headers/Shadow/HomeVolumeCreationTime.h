#import <Foundation/Foundation.h>
#include <math.h>
#include <stdlib.h>
#include <stdint.h>

// A persisted test input. Never substitute a directory mtime for volume metadata.
static inline NSDictionary *SHDWGenerateHomeVolumeCreationTime(
    NSDate *now, NSTimeZone *zone, NSNumber *confirmedModificationTime) {
  if (!now || !zone || !isfinite(now.timeIntervalSince1970)) return nil;
  NSCalendar *calendar = [[NSCalendar alloc] initWithCalendarIdentifier:NSCalendarIdentifierGregorian];
  calendar.timeZone = zone;
  NSDate *month = nil;
  NSTimeInterval interval = 0;
  if (![calendar rangeOfUnit:NSCalendarUnitMonth startDate:&month interval:&interval forDate:now]) return nil;
  NSDate *previous = [calendar dateByAddingUnit:NSCalendarUnitMonth value:-1 toDate:month options:0];
  if (!previous) return nil;
  double lower = ceil(previous.timeIntervalSince1970);
  double upper = fmin(ceil(month.timeIntervalSince1970), ceil(now.timeIntervalSince1970));
  if (confirmedModificationTime) {
    if (![confirmedModificationTime isKindOfClass:NSNumber.class] ||
        !isfinite(confirmedModificationTime.doubleValue)) return nil;
    upper = fmin(upper, ceil(confirmedModificationTime.doubleValue));
  }
  double count = upper - lower;
  if (!isfinite(count) || count < 1 || count > UINT32_MAX) return nil;
  return @{@"HomeVolumeCreationTime": @(lower + arc4random_uniform((uint32_t)count)),
           @"HomeVolumeCreationTimeZone": zone.name,
           @"HomeVolumeCreationTimeValidation": confirmedModificationTime ? @"verified" : @"unverified",
           @"HomeVolumeCreationTimeGeneratedAt": @(now.timeIntervalSince1970)};
}
