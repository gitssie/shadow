"""Exercise previous calendar-month volume timestamp bounds using production policy."""
from pathlib import Path
import subprocess
import sys
import tempfile
if sys.platform != "darwin":
    print("SKIP: volume time fixture requires macOS Foundation")
    raise SystemExit(0)
root = Path(__file__).resolve().parents[1]
fixture=r'''
#import <Shadow/FingerprintVolumeTime.h>
#include <assert.h>
#include <limits.h>
static NSDate *Date(NSString *value, NSTimeZone *zone) {
    NSDateFormatter *formatter=[NSDateFormatter new];formatter.locale=[[NSLocale alloc]initWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.calendar=[[NSCalendar alloc]initWithCalendarIdentifier:NSCalendarIdentifierGregorian];
    formatter.timeZone=zone;formatter.dateFormat=@"yyyy-MM-dd HH:mm:ss";
    NSDate *date=[formatter dateFromString:value];assert(date);return date;
}
static void Month(NSString *today,NSString *start,NSString *end,NSString *zoneName,uint32_t expected) {
    NSTimeZone *zone=[NSTimeZone timeZoneWithName:zoneName];assert(zone);
    NSDate *now=Date(today,zone);int64_t first=-1;uint32_t count=0;
    assert(SHDWFingerprintVolumeTimeRange(now,zone,now.timeIntervalSince1970,&first,&count));
    assert(first==(int64_t)Date(start,zone).timeIntervalSince1970);
    assert(first+count==(int64_t)Date(end,zone).timeIntervalSince1970);
    assert(count==expected);
    assert(SHDWFingerprintVolumeTimeValid(@(first)));
    assert(SHDWFingerprintVolumeTimeValid(@(first+count-1)));
    assert(first+count-1<now.timeIntervalSince1970);
}
int main(void) { @autoreleasepool {
    Month(@"2026-01-12 12:30:00",@"2025-12-01 00:00:00",@"2026-01-01 00:00:00",@"UTC",31*86400);
    Month(@"2024-03-12 12:30:00",@"2024-02-01 00:00:00",@"2024-03-01 00:00:00",@"UTC",29*86400);
    Month(@"2025-03-12 12:30:00",@"2025-02-01 00:00:00",@"2025-03-01 00:00:00",@"UTC",28*86400);
    Month(@"2025-04-12 12:30:00",@"2025-03-01 00:00:00",@"2025-04-01 00:00:00",@"America/New_York",31*86400-3600);
    Month(@"2025-11-12 12:30:00",@"2025-10-01 00:00:00",@"2025-11-01 00:00:00",@"Europe/Berlin",31*86400+3600);
    Month(@"2025-04-01 00:00:00",@"2025-03-01 00:00:00",@"2025-04-01 00:00:00",@"Asia/Shanghai",31*86400);
    NSTimeZone *zone=[NSTimeZone timeZoneForSecondsFromGMT:0];NSDate *now=Date(@"2025-03-15 12:00:00",zone);
    int64_t start=(int64_t)Date(@"2025-02-01 00:00:00",zone).timeIntervalSince1970, first;uint32_t count;
    assert(SHDWFingerprintVolumeTimeRange(now,zone,start+5.25,&first,&count)&&first==start&&count==6);
    assert(SHDWFingerprintVolumeTimeRange(now,zone,start+5,&first,&count)&&count==5);
    assert(SHDWFingerprintVolumeTimeRange(now,zone,start+.25,&first,&count)&&count==1);
    assert(!SHDWFingerprintVolumeTimeRange(now,zone,start,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange(now,zone,start-1,&first,&count));
    for(NSNumber *bad in @[@0,@(-1),@(NAN),@(INFINITY)])assert(!SHDWFingerprintVolumeTimeRange(now,zone,bad.doubleValue,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange(nil,zone,start+1,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange(now,nil,start+1,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange(now,zone,start+1,NULL,&count));
    assert(!SHDWFingerprintVolumeTimeRange(now,zone,start+1,&first,NULL));
    assert(!SHDWFingerprintVolumeTimeRange([NSDate dateWithTimeIntervalSince1970:-1],zone,start+1,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange([NSDate dateWithTimeIntervalSince1970:1],zone,2,&first,&count));
    assert(!SHDWFingerprintVolumeTimeRange([NSDate dateWithTimeIntervalSince1970:0x1p63],zone,1e25,&first,&count));
    for(id value in @[@YES,@NO,@0,@(-1),@1.5,@(NAN),@(INFINITY),@(ULLONG_MAX),@"1",NSNull.null])assert(!SHDWFingerprintVolumeTimeValid(value));
    assert(SHDWFingerprintVolumeTimeValid(@1));assert(SHDWFingerprintVolumeTimeValid(@1.0));
    assert(SHDWFingerprintVolumeTimeValid(@(LLONG_MAX)));
    assert(!SHDWFingerprintVolumeTimeValid(@(0x1p63)));
    assert(!SHDWFingerprintVolumeTimeValid([NSDecimalNumber decimalNumberWithString:@"1.000000000000000001"]));
    puts("PASS: previous natural month, year/leap/DST boundaries, strict modification-time cap and stable integer validation");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-volume-time-test-") as directory:
    path=Path(directory);source=path / "fixture.m";source.write_text(fixture);binary=path / "fixture"
    subprocess.run(["xcrun","clang","-fobjc-arc","-Wall","-Wextra","-Werror","-fsanitize=address,undefined",
                    "-framework","Foundation","-I",str(root / "src/Shadow.framework/Headers"),str(source),"-o",str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
