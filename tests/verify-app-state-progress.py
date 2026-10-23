#!/usr/bin/env python3
"""Ensure streaming progress does not turn into per-file process enumeration."""
import ast
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parent.parent
module = ast.parse((ROOT / "tests/verify-app-state.py").read_text())
harness = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "HARNESS" for t in n.targets))
harness = harness.replace("int main(", "int OriginalFixtureMain(")
harness += r'''
static NSUInteger ProcessChecks(FakeBackend *backend) { return [[[NSCountedSet alloc] initWithArray:backend.calls] countForObject:@"assert"]; }
int main(int argc, const char *argv[]) { @autoreleasepool {
    Check(argc==2,@"performance fixture arguments");NSString *base=@(argv[1]);Mk(base);
    for (NSNumber *number in @[@1,@128]) {
        NSString *scope=[base stringByAppendingPathComponent:number.stringValue],*live=[scope stringByAppendingPathComponent:@"live"],*storage=[scope stringByAppendingPathComponent:@"backup"];Mk(live);
        for(NSUInteger i=0;i<number.unsignedIntegerValue;i++)Put(live,[NSString stringWithFormat:@"file-%lu",(unsigned long)i],Bytes(@"small fixture"));
        Put(live,@"large.bin",[NSMutableData dataWithLength:8*1024*1024]);
        FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"fixture",@"version":@"1",@"build":@"1",@"containers":@{@"data":live},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"fixture",NO);backend.keychain=@[];
        NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:storage backend:backend error:&error];Check(store!=nil,error.localizedDescription);__block NSUInteger events=0;store.progressHandler=^(NSDictionary *event){(void)event;events++;};
        Check([store backupBundle:BID metadata:nil error:&error]!=nil,error.localizedDescription);NSUInteger backupChecks=ProcessChecks(backend);
        Check(events>100,@"fixture did not exercise streaming progress");Check(backupChecks<=12,[NSString stringWithFormat:@"backup made %lu process checks for %lu progress callbacks",(unsigned long)backupChecks,(unsigned long)events]);
        backend.fingerprint=FP(B,@"different-environment",NO);Reset(backend);events=0;Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,error.localizedDescription);NSUInteger restoreChecks=ProcessChecks(backend);
        Check(events>100,@"restore did not exercise streaming progress");Check(restoreChecks<=20,[NSString stringWithFormat:@"restore made %lu process checks for %lu progress callbacks",(unsigned long)restoreChecks,(unsigned long)events]);
        Check([Get(live,@"large.bin") length]==8*1024*1024,@"restored file differs");printf("app-state progress: %lu files, backup checks %lu, restore checks %lu, restored and verified\n",(unsigned long)number.unsignedIntegerValue,(unsigned long)backupChecks,(unsigned long)restoreChecks);
    }
}return 0;}
'''
archive = next((Path(p) for p in [os.environ.get("ARCHIVE_PREFIX", ""), "/opt/homebrew/opt/libarchive", "/usr/local/opt/libarchive"] if p and Path(p,"include/archive.h").exists()),None)
if not archive: raise SystemExit("Set ARCHIVE_PREFIX to libarchive with Zstd support")
zstd = next((Path(p) for p in [os.environ.get("ZSTD_PREFIX", ""), "/opt/homebrew/opt/zstd", "/usr/local/opt/zstd"] if p and Path(p,"lib").exists()),None)
with tempfile.TemporaryDirectory(prefix="shadow-state-progress-") as directory:
    temp=Path(directory);source=temp/"main.m";source.write_text(harness)
    command=["xcrun","--sdk","macosx","clang","-fobjc-arc","-fblocks","-O1","-Wall","-Wextra","-Werror","-Wno-unused-function","-Wno-deprecated-declarations","-fsanitize=address,undefined","-framework","Foundation","-I"+str(archive/"include"),"-I"+str(ROOT/"src/AppState"),"-L"+str(archive/"lib"),"-Wl,-rpath,"+str(archive/"lib"),str(source),str(ROOT/"src/AppState/Archive.m"),str(ROOT/"src/AppState/State.m"),"-larchive","-lzstd","-o",str(temp/"test")]
    if zstd: command += ["-L"+str(zstd/"lib"),"-Wl,-rpath,"+str(zstd/"lib")]
    subprocess.run(command,check=True)
    subprocess.run([str(temp/"test"),str(temp/"fixtures")],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",UBSAN_OPTIONS="halt_on_error=1"))
