"""Exercise Documents reset persistence and metadata using real filesystem fixtures."""
from pathlib import Path
import subprocess
import sys
import tempfile
if sys.platform != "darwin":
    print("SKIP: Documents reset fixture requires macOS Foundation")
    raise SystemExit(0)
root = Path(__file__).resolve().parents[1]
fixture = r'''
#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
static void Fail(NSString *message) { @throw [NSException exceptionWithName:@"TestFailure" reason:message userInfo:nil]; }
static void Require(BOOL value,NSString *message) { if(!value)Fail(message); }
static NSString *Hash(id object) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:object options:0 error:NULL];unsigned char bytes[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes,(CC_LONG)data.length,bytes);NSMutableString *value=[NSMutableString new];
    for(unsigned i=0;i<sizeof(bytes);i++)[value appendFormat:@"%02x",bytes[i]];return value;
}
#import "__MODULE__"
@interface Defaults : NSObject
@property NSMutableDictionary *values;
@property BOOL failSync;
@end
@implementation Defaults
- (instancetype)init {if((self=[super init]))_values=[NSMutableDictionary new];return self;}
- (NSDictionary *)dictionaryForKey:(NSString *)key {return self.values[key];}
- (void)setObject:(id)value forKey:(NSString *)key {self.values[key]=value;}
- (BOOL)synchronize {return !self.failSync;}
@end
static struct stat Info(NSString *path) {struct stat value;assert(!lstat(path.fileSystemRepresentation,&value));return value;}
static void SetBirth(NSString *path,time_t seconds,long nanos) {
    struct attrlist attrs={.bitmapcount=ATTR_BIT_MAP_COUNT,.commonattr=ATTR_CMN_CRTIME};struct timespec time={seconds,nanos};
    assert(!setattrlist(path.fileSystemRepresentation,&attrs,&time,sizeof(time),FSOPT_NOFOLLOW));
}
static NSDictionary *Target(NSString *root) {
    assert([NSFileManager.defaultManager createDirectoryAtPath:[root stringByAppendingPathComponent:@"Documents"] withIntermediateDirectories:YES attributes:nil error:NULL]);
    struct stat st=Info(root);
    return @{@"bundleID":@"fixture.app",@"containers":@[@{@"identifier":@"fixture.app",@"path":root,@"device":@((uint64_t)st.st_dev),@"inode":@((uint64_t)st.st_ino)}]};
}
static BOOL SameBirth(struct stat a,struct stat b) {return a.st_birthtimespec.tv_sec==b.st_birthtimespec.tv_sec&&a.st_birthtimespec.tv_nsec==b.st_birthtimespec.tv_nsec;}
#define REJECT(expression) do {BOOL rejected=NO;@try{(void)(expression);}@catch(NSException *e){(void)e;rejected=YES;}assert(rejected);}while(0)
int main(int argc,const char **argv) { @autoreleasepool {
    (void)argc;NSString *base=@(argv[1]);NSString *root=[base stringByAppendingPathComponent:@"one"];
    NSDictionary *target=Target(root);NSString *documents=[root stringByAppendingPathComponent:@"Documents"];
    SetBirth(documents,1000000000,123456000);struct stat original=Info(documents);
    Defaults *defaults=[Defaults new];NSDictionary *app=@{@"Fingerprint_Data":@{@"keep":@YES},@"Other":@"keep"};
    [defaults setObject:app forKey:@"fixture.app"];
    NSDictionary *baseline=StateResetDocuments(target,defaults,app,NO);
    assert(SameBirth(original,Info(documents)));
    assert([StateCaptureDocumentsBaseline(target,baseline)isEqual:baseline]);
    assert([defaults dictionaryForKey:@"fixture.app"][@"Other"]);
    assert([baseline[@"Containers"][@"fixture.app"][@"Seconds"]longLongValue]==1000000000);
    for(int attempt=0;attempt<2;attempt++) {
        if(attempt)SetBirth(documents,1500000000,0);
        NSDictionary *again=StateResetDocuments(target,defaults,[defaults dictionaryForKey:@"fixture.app"],YES);
        assert([again isEqual:baseline]);struct stat changed=Info(documents);
        assert(changed.st_ino==original.st_ino&&changed.st_uid==original.st_uid&&changed.st_gid==original.st_gid&&changed.st_mode==original.st_mode);
        assert(changed.st_birthtimespec.tv_sec>=1000000000&&changed.st_birthtimespec.tv_sec<=1000864000&&changed.st_birthtimespec.tv_nsec==123456000);
        assert(changed.st_birthtimespec.tv_sec<=time(NULL));
    }
    NSMutableDictionary *staleRecords=[baseline[@"Containers"] mutableCopy];
    staleRecords[@"removed.extension"] = baseline[@"Containers"][@"fixture.app"];
    NSMutableDictionary *withStale=[[defaults dictionaryForKey:@"fixture.app"] mutableCopy];
    withStale[@"Fingerprint_ResetBaseline"]=@{@"Version":@1,@"Containers":staleRecords};
    [defaults setObject:withStale forKey:@"fixture.app"];
    struct stat beforeCapture=Info(documents);
    assert([StateCaptureDocumentsBaseline(target,withStale[@"Fingerprint_ResetBaseline"])isEqual:baseline]);
    assert(SameBirth(beforeCapture,Info(documents)));
    assert([[defaults dictionaryForKey:@"fixture.app"]isEqual:withStale]);
    assert([StateResetDocuments(target,defaults,withStale,NO) isEqual:baseline]);
    NSMutableDictionary *futureRecord=[baseline[@"Containers"][@"fixture.app"]mutableCopy];
    futureRecord[@"Seconds"]=@(time(NULL)+100);
    NSMutableDictionary *withFuture=[[defaults dictionaryForKey:@"fixture.app"]mutableCopy];
    withFuture[@"Fingerprint_ResetBaseline"]=@{@"Version":@1,@"Containers":@{@"fixture.app":futureRecord}};
    struct stat beforeFuture=Info(documents);
    REJECT(StateResetDocuments(target,defaults,withFuture,YES));
    assert(SameBirth(beforeFuture,Info(documents)));
    defaults.failSync=YES;
    REJECT(StateResetDocuments(target,defaults,[defaults dictionaryForKey:@"fixture.app"],YES));
    defaults.failSync=NO;
    assert(SameBirth(beforeFuture,Info(documents)));
    NSDictionary *other=Target([base stringByAppendingPathComponent:@"two"]);
    NSString *otherDocuments=[other[@"containers"][0][@"path"]stringByAppendingPathComponent:@"Documents"];
    SetBirth(otherDocuments,1200000000,0);
    assert([StateCaptureDocumentsBaseline(other,baseline)[@"Containers"]count]==0);
    assert([StateCaptureDocumentsBaseline(@{@"containers":@[]},baseline)[@"Containers"]count]==0);
    NSDictionary *missingTarget=Target([base stringByAppendingPathComponent:@"missing"]);
    NSString *missingDocuments=[missingTarget[@"containers"][0][@"path"]stringByAppendingPathComponent:@"Documents"];
    assert([NSFileManager.defaultManager removeItemAtPath:missingDocuments error:NULL]);
    assert([StateCaptureDocumentsBaseline(missingTarget,baseline)[@"Containers"]count]==0);
    NSDictionary *rebound=StateRebindDocumentsBaseline(other,baseline);
    assert(SHDWFingerprintResetBaselineTimesEqual(baseline,rebound));
    assert(![rebound isEqual:baseline]);
    NSDictionary *recaptured=StateResetDocuments(other,defaults,[defaults dictionaryForKey:@"fixture.app"],NO);
    assert([recaptured[@"Containers"][@"fixture.app"][@"Seconds"]longLongValue]==1200000000);
    Defaults *failed=[Defaults new];[failed setObject:app forKey:@"fixture.app"];failed.failSync=YES;
    struct stat unchanged=Info(otherDocuments);
    REJECT(StateResetDocuments(other,failed,app,YES));
    assert(SameBirth(unchanged,Info(otherDocuments))&&[[failed dictionaryForKey:@"fixture.app"]isEqual:app]);
    NSDictionary *malformed=@{@"Fingerprint_ResetBaseline":@{@"Version":@2}};
    REJECT(StateResetDocuments(other,defaults,malformed,YES));assert(SameBirth(unchanged,Info(otherDocuments)));
    SetBirth(otherDocuments,time(NULL)+100,0);
    Defaults *fresh=[Defaults new];[fresh setObject:app forKey:@"fixture.app"];
    REJECT(StateResetDocuments(other,fresh,app,YES));assert([[fresh dictionaryForKey:@"fixture.app"]isEqual:app]);
    assert([NSFileManager.defaultManager removeItemAtPath:otherDocuments error:NULL]);
    assert(!symlink(documents.fileSystemRepresentation,otherDocuments.fileSystemRepresentation));
    REJECT(StateResetDocuments(other,fresh,app,YES));REJECT(StateRebindDocumentsBaseline(other,baseline));
    REJECT(StateRebindDocumentsBaseline(@{@"containers":@[]},baseline));
    puts("PASS: fixed Documents baseline, repeated reset, persistence rollback, ownership, restore rebind, malformed/future rejection and symlink scope");
}return 0;}
'''
with tempfile.TemporaryDirectory(prefix="shadow-documents-reset-test-") as directory:
    temporary=Path(directory)
    source=temporary / "fixture.m"
    source.write_text(fixture.replace("__MODULE__",str(root / "src/ShadowCleaner/DocumentsReset.inc")))
    binary=temporary / "fixture"
    subprocess.run(["xcrun","clang","-fobjc-arc","-fblocks","-Wall","-Wextra","-Werror","-Wno-deprecated-declarations",
                    "-fsanitize=address,undefined","-framework","Foundation",str(source),"-o",str(binary)],check=True)
    subprocess.run([str(binary),str(temporary / "fixtures")],check=True)
