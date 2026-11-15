#import <Shadow/HomeVolumeCreationTime.h>
#include <assert.h>

int main(void) { @autoreleasepool {
  for (NSString *name in @[@"UTC", @"America/New_York", @"Australia/Sydney"]) {
    NSTimeZone *zone = [NSTimeZone timeZoneWithName:name];
    NSCalendar *calendar = [[NSCalendar alloc] initWithCalendarIdentifier:NSCalendarIdentifierGregorian];
    calendar.timeZone = zone;
    for (NSString *text in @[@"2026-01-15", @"2024-03-15", @"2026-11-15", @"2026-04-15"]) {
      NSDateFormatter *formatter = [NSDateFormatter new];
      formatter.calendar = calendar; formatter.timeZone = zone;
      formatter.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
      formatter.dateFormat = @"yyyy-MM-dd";
      NSDate *now = [formatter dateFromString:text], *month = nil;
      NSTimeInterval duration;
      assert([calendar rangeOfUnit:NSCalendarUnitMonth startDate:&month interval:&duration forDate:now]);
      NSDate *previous = [calendar dateByAddingUnit:NSCalendarUnitMonth value:-1 toDate:month options:0];
      for (int i=0; i<100; ++i) {
        NSDictionary *value = SHDWGenerateHomeVolumeCreationTime(now, zone, nil);
        double stamp = [value[@"HomeVolumeCreationTime"] doubleValue];
        assert(value && stamp >= previous.timeIntervalSince1970 && stamp < month.timeIntervalSince1970);
        assert(stamp < now.timeIntervalSince1970 && stamp == floor(stamp));
        assert([value[@"HomeVolumeCreationTimeValidation"] isEqual:@"unverified"]);
        NSDictionary *saved = [NSPropertyListSerialization propertyListWithData:
          [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]
          options:0 format:NULL error:NULL];
        assert([saved isEqual:value]);
      }
      assert(!SHDWGenerateHomeVolumeCreationTime(now, zone, @(previous.timeIntervalSince1970)));
      NSDictionary *one = SHDWGenerateHomeVolumeCreationTime(now, zone, @(previous.timeIntervalSince1970+1));
      assert([one[@"HomeVolumeCreationTime"] doubleValue] == previous.timeIntervalSince1970);
      assert([one[@"HomeVolumeCreationTimeValidation"] isEqual:@"verified"]);
    }
  }
  puts("HomeVolumeCreationTime calendar and persistence tests passed");
} return 0; }
