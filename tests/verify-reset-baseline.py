"""Exercise the production reset-baseline schema and bounded timestamp policy."""
from pathlib import Path
import subprocess
import sys
import tempfile

if sys.platform != "darwin":
    print("SKIP: reset-baseline fixture requires macOS Foundation")
    raise SystemExit(0)
root = Path(__file__).resolve().parents[1]
fixture = r'''
#import <Shadow/FingerprintResetBaseline.h>
#include <assert.h>
#include <limits.h>
int main(void) { @autoreleasepool {
    NSString *hash = [@"a" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0];
    NSDictionary *record = @{@"Identity":hash,@"Seconds":@100,@"Nanoseconds":@123};
    NSDictionary *valid = @{@"Version":@1,@"Containers":@{@"example.app":record}};
    assert(SHDWFingerprintResetBaselineValid(valid));
    assert(SHDWFingerprintResetBaselineTimesEqual(nil,nil));
    assert(!SHDWFingerprintResetBaselineTimesEqual(valid,nil));
    assert(!SHDWFingerprintResetBaselineTimesEqual(nil,valid));
    NSMutableDictionary *rebound = [record mutableCopy];
    rebound[@"Identity"] = [@"b" stringByPaddingToLength:64 withString:@"b" startingAtIndex:0];
    assert(SHDWFingerprintResetBaselineTimesEqual(valid,@{@"Version":@1,@"Containers":@{@"example.app":rebound}}));
    rebound[@"Seconds"] = @101;
    assert(!SHDWFingerprintResetBaselineTimesEqual(valid,@{@"Version":@1,@"Containers":@{@"example.app":rebound}}));
    assert(!SHDWFingerprintResetBaselineTimesEqual(valid,@{}));
    assert(SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":@{}}));
    for (id value in @[@YES,@(-1),@1.5,@(NAN),@(INFINITY),@(ULLONG_MAX),@"1",NSNull.null]) {
        NSMutableDictionary *bad = [record mutableCopy]; bad[@"Seconds"] = value;
        assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":@{@"a":bad}}));
    }
    for (id value in @[@YES,@(-1),@1000000000,@1.5]) {
        NSMutableDictionary *bad = [record mutableCopy]; bad[@"Nanoseconds"] = value;
        assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":@{@"a":bad}}));
    }
    for (NSString *key in @[@"",@"a/b",[@"x" stringByPaddingToLength:256 withString:@"x" startingAtIndex:0]])
        assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":@{key:record}}));
    for (NSString *identity in @[@"abc",[hash uppercaseString],[hash stringByReplacingOccurrencesOfString:@"a" withString:@"g"]]) {
        NSMutableDictionary *bad = [record mutableCopy]; bad[@"Identity"] = identity;
        assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":@{@"a":bad}}));
    }
    assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@YES,@"Containers":@{}}));
    assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@2,@"Containers":@{}}));
    NSMutableDictionary *extra = [valid mutableCopy]; extra[@"extra"] = @1;
    assert(!SHDWFingerprintResetBaselineValid(extra));
    NSMutableDictionary *many = [NSMutableDictionary new];
    for (int i=0;i<65;i++) many[[NSString stringWithFormat:@"c%d",i]] = record;
    assert(!SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":many}));
    [many removeObjectForKey:@"c64"];
    assert(SHDWFingerprintResetBaselineValid(@{@"Version":@1,@"Containers":many}));
    struct timespec baseline = {.tv_sec=100,.tv_nsec=900}, now = {.tv_sec=1000000,.tv_nsec=0}, result;
    uint32_t upper=0;
    assert(SHDWFingerprintResetTimeUpperBound(baseline,now,&upper) && upper==864000);
    assert(SHDWFingerprintResetTime(baseline,now,upper,&result) && result.tv_sec==864100 && result.tv_nsec==900);
    assert(!SHDWFingerprintResetTime(baseline,now,864001,&result));
    for (uint32_t increment=0;increment<=864000;increment+=1000) {
        assert(SHDWFingerprintResetTime(baseline,now,increment,&result));
        assert(result.tv_sec>=baseline.tv_sec && result.tv_sec<=baseline.tv_sec+864000 && result.tv_nsec==900);
    }
    // Every operation starts from the stored baseline, not a previous result.
    assert(SHDWFingerprintResetTime(baseline,now,700000,&result));
    assert(SHDWFingerprintResetTime(baseline,now,10,&result) && result.tv_sec==110);
    now=(struct timespec){.tv_sec=101,.tv_nsec=899};
    assert(SHDWFingerprintResetTimeUpperBound(baseline,now,&upper) && upper==0);
    assert(!SHDWFingerprintResetTime(baseline,now,1,&result));
    now.tv_nsec=900;
    assert(SHDWFingerprintResetTimeUpperBound(baseline,now,&upper) && upper==1);
    assert(SHDWFingerprintResetTime(baseline,now,1,&result) && result.tv_sec==101 && result.tv_nsec==900);
    now=baseline;
    assert(SHDWFingerprintResetTimeUpperBound(baseline,now,&upper) && upper==0);
    now.tv_nsec=899;
    assert(!SHDWFingerprintResetTimeUpperBound(baseline,now,&upper));
    now=(struct timespec){.tv_sec=99,.tv_nsec=999999999};
    assert(!SHDWFingerprintResetTimeUpperBound(baseline,now,&upper));
    for (long ns=-1;ns<=1000000000;ns+=1000000001) {
        struct timespec bad={.tv_sec=100,.tv_nsec=ns};
        assert(!SHDWFingerprintResetTimeUpperBound(bad,baseline,&upper));
        assert(!SHDWFingerprintResetTimeUpperBound(baseline,bad,&upper));
    }
    struct timespec high={.tv_sec=(time_t)LLONG_MAX-5,.tv_nsec=0};
    now=(struct timespec){.tv_sec=(time_t)LLONG_MAX,.tv_nsec=0};
    if (sizeof(time_t)==sizeof(long long)) {
        assert(SHDWFingerprintResetTimeUpperBound(high,now,&upper) && upper==5);
        assert(SHDWFingerprintResetTime(high,now,5,&result) && result.tv_sec==now.tv_sec);
        assert(!SHDWFingerprintResetTime(high,now,6,&result));
    }
    assert(!SHDWFingerprintResetTimeUpperBound(baseline,now,NULL));
    assert(!SHDWFingerprintResetTime(baseline,now,0,NULL));
    puts("PASS: reset baseline schema, bounded nanosecond timestamps, future rejection and non-drifting reuse");
} return 0; }
'''
with tempfile.TemporaryDirectory(prefix="shadow-reset-baseline-test-") as directory:
    path = Path(directory)
    (path / "fixture.m").write_text(fixture)
    binary = path / "fixture"
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                    "-framework", "Foundation", "-I", str(root / "src/Shadow.framework/Headers"),
                    str(path / "fixture.m"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
