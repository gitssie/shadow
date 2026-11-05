#!/usr/bin/env python3
"""Exercise both store backup entries after their two archives are complete."""
from pathlib import Path
import os
import runpy
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
EXTRA = r'''
@interface LateSourceBackend : FakeBackend
@property NSUInteger captures;
@property(copy) void (^afterArchives)(void);
@end
@implementation LateSourceBackend
- (NSArray *)captureKeychainForTarget:(NSDictionary *)target error:(NSError **)error {
    NSArray *records=[super captureKeychainForTarget:target error:error];self.captures++;
    if(self.captures==2 && self.afterArchives){void(^callback)(void)=self.afterArchives;self.afterArchives=nil;callback();}
    return records;
}
@end
int main(int argc,const char **argv){@autoreleasepool{
    Check(argc==3,@"boundary fixture arguments");NSString *base=@(argv[1]),*scenario=@(argv[2]);
    BOOL combined=[scenario hasPrefix:@"combined"],changeContent=[scenario hasSuffix:@"content"];
    NSString *data=[base stringByAppendingPathComponent:@"data"],*group=[base stringByAppendingPathComponent:@"group"],*root=[base stringByAppendingPathComponent:@"store"];
    Mk(data);Mk(group);Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private boundary store");
    Put(data,@"Documents/value",Bytes(@"first-original"));Put(data,@".hidden",Bytes(@"hidden"));Put(data,@"tmp/temp",Bytes(@"temporary"));Put(group,@"shared",Bytes(@"shared-original"));
    LateSourceBackend *backend=[LateSourceBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"boundary-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data,@"group":group},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"first",NO);backend.keychain=@[];backend.preferences=@{};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,@"initialize boundary store");
    NSDictionary *firstData=ContentTree(data);NSData *firstArchive=nil;
    if(combined){Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"seed restore source");firstArchive=[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"data.tar.zst")];backend.fingerprint=FP(B,@"second",NO);Put(data,@"Documents/value",Bytes(@"second-original"));}
    NSDictionary *capturedData=ContentTree(data),*capturedGroup=ContentTree(group);NSString *capturedID=combined?B:A;
    __block BOOL mutated=NO;__block NSData *completedData=nil,*completedState=nil;backend.captures=0;
    backend.afterArchives=^{
        for(NSString *name in [NSFileManager.defaultManager subpathsOfDirectoryAtPath:root error:NULL]){
            if(![name containsString:@".capture-"])continue;
            if([name hasSuffix:@"data.tar.zst"])completedData=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:name]];
            if([name hasSuffix:@"state.tar.zst"])completedState=[NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:name]];
        }
        Check(completedData.length>0&&completedState.length>0,@"both archives are complete before late source drift");mutated=YES;
        if(changeContent)Put(data,@"Documents/value",Bytes(@"changed-after-both-archives"));
        else Check(!chmod([data stringByAppendingPathComponent:@"Documents/value"].fileSystemRepresentation,0600),@"change source metadata after both archives");
    };
    NSDictionary *result=combined?[store restoreBundle:BID idfv:A saveCurrent:YES error:&error]:[store backupBundle:BID metadata:nil error:&error];
    Check(mutated,@"second keychain capture reached archive completion boundary");
    Check(result!=nil,[NSString stringWithFormat:@"completed business backup must not reread source: %@",error]);
    NSString *savedData=SnapshotPath(root,capturedID,@"data.tar.zst"),*savedState=SnapshotPath(root,capturedID,@"state.tar.zst");
    Check([completedData isEqual:[NSData dataWithContentsOfFile:savedData]]&&[completedState isEqual:[NSData dataWithContentsOfFile:savedState]],@"published packages equal the completed bytes before source drift");
    if(combined)Check([ContentTree(data)isEqual:firstData]&&[firstArchive isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"data.tar.zst")]],@"combined operation restores chosen source and preserves its archive");
    backend.fingerprint=FP(C,@"third",NO);backend.afterArchives=nil;
    Check([store restoreBundle:BID idfv:capturedID saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"late-drift backup remains restorable: %@",error]);
    Check([ContentTree(data)isEqual:capturedData]&&[ContentTree(group)isEqual:capturedGroup],@"restore every original captured entry and metadata, not later source state");
    Check([completedData isEqual:[NSData dataWithContentsOfFile:savedData]]&&[completedState isEqual:[NSData dataWithContentsOfFile:savedState]],@"restoring leaves original archives unchanged");
    printf("store capture boundary %s passed\n",scenario.UTF8String);
}return 0;}
'''


def main():
    module = runpy.run_path(str(ROOT / "tests/verify-app-state.py"))
    prefix = module["archive_prefix"]()
    zstd = Path(os.environ.get("ZSTD_PREFIX", "/opt/homebrew/opt/zstd"))
    with tempfile.TemporaryDirectory(prefix="shadow-backup-boundary-") as directory:
        temp = Path(directory).resolve()
        source = temp / "main.m"
        source.write_text("#define main OriginalFixtureMain\n" + module["HARNESS"] + "\n#undef main\n" + EXTRA)
        binary = temp / "check"
        command = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-g", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-I" + str(ROOT / "src/AppState"), "-L" + str(prefix / "lib"), "-L" + str(zstd / "lib"), "-Wl,-rpath," + str(prefix / "lib"), "-Wl,-rpath," + str(zstd / "lib"), str(source), str(ROOT / "src/AppState/Archive.m"), str(ROOT / "src/AppState/State.m"), "-larchive", "-lzstd", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-o", str(binary)]
        subprocess.run(command, check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        failed = []
        for scenario in ("direct-content", "direct-metadata", "combined-content", "combined-metadata"):
            result = subprocess.run([str(binary), str(temp / scenario), scenario], env=environment)
            if result.returncode:
                failed.append(scenario)
        if failed:
            raise SystemExit("Store boundary scenarios failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
