#!/usr/bin/env python3
"""Fault-inject real storage syscalls in production AppState translation units."""
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("app_state_fixtures", ROOT / "tests/verify-app-state.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

HARNESS = fixtures.HARNESS.split("static void ArchiveTests(", 1)[0] + r'''
#include <sys/file.h>
static NSMutableArray *syncs;
static NSString *failSyncPath, *failCleanupPath, *cleanupLock, *inspectRoot;
static BOOL inspectLinks, preferencesReplayed, requireReplay;
static NSUInteger cleanupAttempts;
static NSArray *requiredSyncRoots;
static NSString *requiredPreferenceFile;
static void Ordered(NSString *root,BOOL replay);
static NSString *FDPath(int fd) { char path[PATH_MAX]; Check(!fcntl(fd,F_GETPATH,path),@"resolve intercepted descriptor");return @(path); }
int DurabilityFsync(int fd) {
    struct stat st;Check(!fstat(fd,&st),@"stat intercepted descriptor");NSString *path=FDPath(fd);
    if(syncs) [syncs addObject:@{@"path":path,@"directory":@(S_ISDIR(st.st_mode)),@"dev":@(st.st_dev),@"ino":@(st.st_ino),@"replayed":@(preferencesReplayed)}];
    if(S_ISDIR(st.st_mode)&&inspectRoot&&([path isEqual:inspectRoot]||[path hasPrefix:[inspectRoot stringByAppendingString:@"/"]])) {
        Check([Get(inspectRoot,@"deep/child/value") isEqual:Bytes(@"durable")],@"directory flush preceded file completion");
        if(inspectLinks) {struct stat a,b,l;Check(!lstat([inspectRoot stringByAppendingPathComponent:@"deep/child/value"].fileSystemRepresentation,&a)&&!lstat([inspectRoot stringByAppendingPathComponent:@"deep/alias"].fileSystemRepresentation,&b)&&a.st_ino==b.st_ino,@"directory flush preceded hardlink creation");Check(!lstat([inspectRoot stringByAppendingPathComponent:@"symbolic"].fileSystemRepresentation,&l)&&S_ISLNK(l.st_mode),@"directory flush preceded symlink creation");}
    }
    if([path isEqual:failSyncPath]&&(!requireReplay||preferencesReplayed)) {errno=EIO;return -1;}
    return fsync(fd);
}
int DurabilityUnlinkat(int fd,const char *name,int flags) {
    NSString *path=[FDPath(fd) stringByAppendingPathComponent:@(name)];
    if(cleanupLock&&([path containsString:@"/.capture-"]||[path containsString:@"/.delete-"])) {
        int lock=open(cleanupLock.fileSystemRepresentation,O_RDWR);Check(lock>=0,@"open collector lock probe");int result=flock(lock,LOCK_EX|LOCK_NB);int failure=errno;if(!result)flock(lock,LOCK_UN);close(lock);Check(result==-1&&(failure==EWOULDBLOCK||failure==EAGAIN),@"garbage collection did not hold exclusive state lock");
    }
    if(failCleanupPath&&([path isEqual:failCleanupPath]||[path hasPrefix:[failCleanupPath stringByAppendingString:@"/"]] )){cleanupAttempts++;errno=EACCES;return -1;}
    return unlinkat(fd,name,flags);
}
@interface DurableBackend : FakeBackend
@end
@implementation DurableBackend
- (BOOL)restorePreferences:(NSDictionary *)records target:(NSDictionary *)target error:(NSError **)error {
    BOOL result=[super restorePreferences:records target:target error:error];preferencesReplayed=YES;return result;
}
- (BOOL)restoreFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error {
    if(requireReplay) {
        Check(preferencesReplayed,@"identity committed before preference replay");
        for(NSString *root in requiredSyncRoots)Ordered(root,YES);
        BOOL flushed=NO;for(NSDictionary *event in syncs)if([event[@"path"] isEqual:requiredPreferenceFile]&&[event[@"replayed"] boolValue])flushed=YES;
        Check(flushed,@"identity committed before replayed preference file fsync");
    }
    return [super restoreFingerprint:fingerprint target:target error:error];
}
@end
static DurableBackend *Backend(NSString *data) {
    DurableBackend *backend=[DurableBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"durability-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"saved",NO);backend.keychain=@[];backend.preferences=@{@"version":@1,@"records":@[]};return backend;
}
static BOOL Exists(NSString *path) {struct stat st;return !lstat(path.fileSystemRepresentation,&st);}
static void Ordered(NSString *root,BOOL replay) {
    NSMutableDictionary *indices=[NSMutableDictionary new];
    for(NSUInteger i=0;i<syncs.count;i++){NSDictionary *event=syncs[i];NSString *path=event[@"path"];if(![event[@"directory"] boolValue]||(replay&&![event[@"replayed"] boolValue]))continue;if([path isEqual:root]||[path hasPrefix:[root stringByAppendingString:@"/"]])indices[path]=@(i);}
    Check(indices[root]!=nil,@"destination root was not fsynced");
    NSDirectoryEnumerator *scan=[NSFileManager.defaultManager enumeratorAtPath:root];NSString *relative;
    while((relative=[scan nextObject])) {NSString *path=[root stringByAppendingPathComponent:relative];struct stat st;Check(!lstat(path.fileSystemRepresentation,&st),@"inspect directory order");if(S_ISLNK(st.st_mode)){[scan skipDescendants];continue;}if(!S_ISDIR(st.st_mode))continue;Check(indices[path]!=nil,@"destination child directory was not fsynced");Check([indices[path] unsignedIntegerValue]<[indices[path.stringByDeletingLastPathComponent] unsignedIntegerValue],@"parent directory synced before child");}
}
static void ArchiveDurability(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"source"],*destination=[base stringByAppendingPathComponent:@"destination"],*archive=[base stringByAppendingPathComponent:@"archive.zst"];Mk(source);Mk(destination);Put(source,@"deep/child/value",Bytes(@"durable"));Check(!link([source stringByAppendingPathComponent:@"deep/child/value"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"deep/alias"].fileSystemRepresentation),@"hardlink fixture");Check(!symlink("deep/child/value",[source stringByAppendingPathComponent:@"symbolic"].fileSystemRepresentation),@"symlink fixture");
    NSError *error=nil;NSDictionary *info=[SHDWStateArchive captureRoots:@{@"containers/data":source} payloads:@{} toPath:archive progress:nil error:&error];Check(info!=nil,@"archive capture");syncs=[NSMutableArray new];inspectRoot=destination;inspectLinks=YES;
    Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":destination} progress:nil error:&error],[NSString stringWithFormat:@"archive restore: %@",error]);Check([SHDWStateArchive synchronizeRoots:@{@"containers/data":destination} progress:nil error:&error],@"archive destination commit barrier");Ordered(destination,NO);inspectRoot=nil;inspectLinks=NO;
    NSString *failed=[base stringByAppendingPathComponent:@"failed-destination"];Mk(failed);Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":failed} progress:nil error:&error],@"prepare failing commit barrier");failSyncPath=[failed stringByAppendingPathComponent:@"deep/child"];Check(![SHDWStateArchive synchronizeRoots:@{@"containers/data":failed} progress:nil error:&error]&&error!=nil,@"directory fsync error was ignored by archive commit barrier");failSyncPath=nil;syncs=nil;
}
static void CollectionTests(NSString *base) {
    NSString *data=[base stringByAppendingPathComponent:@"gc-data"],*root=[base stringByAppendingPathComponent:@"gc-store"];Mk(data);Mk(root);chmod(root.fileSystemRepresentation,0700);Put(data,@"value",Bytes(@"saved"));DurableBackend *backend=Backend(data);NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store&&[store backupBundle:BID metadata:nil error:&error],@"GC initial snapshot");NSString *app=[root stringByAppendingPathComponent:BID];cleanupLock=[app stringByAppendingPathComponent:@".lock"];
    NSArray *garbage=@[[@".capture-" stringByAppendingString:A],[@".capture-" stringByAppendingString:B],[@".delete-" stringByAppendingString:C]];
    for(NSString *name in garbage){NSString *path=[app stringByAppendingPathComponent:name];Mk(path);chmod(path.fileSystemRepresentation,0700);Put(path,@"nested/partial",Bytes(@"abandoned"));}
    // The second capture models the complete old snapshot left by an exchange.
    NSString *old=[app stringByAppendingPathComponent:garbage[1]];for(NSString *name in @[@"manifest.plist",@"data.tar.zst",@"state.tar.zst"])Put(old,name,Bytes(@"old snapshot"));
    NSArray *preserved=@[@".capture-not-a-uuid",[@".capture-" stringByAppendingFormat:@"%@-extra",A],@"unrelated"];
    for(NSString *name in preserved){Mk([app stringByAppendingPathComponent:name]);Put([app stringByAppendingPathComponent:name],@"keep",Bytes(@"keep"));}
    NSString *outside=[base stringByAppendingPathComponent:@"gc-outside"];Mk(outside);Put(outside,@"keep",Bytes(@"outside"));NSString *symbol=[app stringByAppendingPathComponent:[@".capture-" stringByAppendingString:@"44444444-4444-4444-8444-444444444444"]];Check(!symlink(outside.fileSystemRepresentation,symbol.fileSystemRepresentation),@"collector symlink fixture");
    Check([[store catalogBundle:BID error:&error] count]==1,@"catalog fixture");for(NSString *name in garbage)Check(Exists([app stringByAppendingPathComponent:name]),@"shared catalog performed collection");
    NSString *manifestPath=[[[app stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:A] stringByAppendingPathComponent:@"manifest.plist"];NSData *manifestBytes=[NSData dataWithContentsOfFile:manifestPath];Check(manifestBytes!=nil,@"read snapshot manifest");Check([Bytes(@"invalid manifest") writeToFile:manifestPath atomically:NO],@"corrupt preflight fixture");NSDictionary *beforeInvalid=StoreTree(root);[backend.calls removeAllObjects];Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"invalid restore fixture accepted");Check([StoreTree(root) isEqual:beforeInvalid]&&![backend.calls containsObject:@"stop"],@"invalid restore mutated abandoned storage or reached backend");Check([manifestBytes writeToFile:manifestPath atomically:NO],@"repair preflight fixture");
    failCleanupPath=[app stringByAppendingPathComponent:garbage[0]];cleanupAttempts=0;
    Check([store editBundle:BID idfv:A metadata:@{@"title":@"first",@"note":@""} error:&error],@"exclusive operation with deferred cleanup");Check(cleanupAttempts>0&&Exists(failCleanupPath),@"collector failure did not leave retryable data");failCleanupPath=nil;
    NSString *pending=[app stringByAppendingPathComponent:@"pending.plist"];NSDictionary *manifest=[NSDictionary dictionaryWithContentsOfFile:manifestPath];NSDictionary *pendingRecord=@{@"format":manifest[@"format"],@"idfv":B,@"bundleID":BID,@"archiveSHA":manifest[@"archiveInfo"][@"sha256"],@"stateArchiveSHA":manifest[@"stateArchiveInfo"][@"sha256"],@"date":NSDate.date,@"phase":@"restoring"};NSData *sentinel=[NSPropertyListSerialization dataWithPropertyList:pendingRecord format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];Check(sentinel!=nil,@"pending preservation fixture");Put(app,@"pending.plist",sentinel);chmod(pending.fileSystemRepresentation,0600);
    Check([store editBundle:BID idfv:A metadata:@{@"title":@"retry",@"note":@""} error:&error],@"validated writer did not retry collection");for(NSString *name in garbage)Check(!Exists([app stringByAppendingPathComponent:name]),@"next validated writer did not reclaim abandoned capture/delete");
    for(NSString *name in preserved)Check([Get([app stringByAppendingPathComponent:name],@"keep") isEqual:Bytes(@"keep")],@"collector removed unrelated directory");Check([Get(outside,@"keep") isEqual:Bytes(@"outside")],@"collector followed staging symlink");Check([[NSData dataWithContentsOfFile:pending] isEqual:sentinel],@"collector changed pending state");Check(Exists([[app stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:A]),@"collector removed published snapshot");cleanupLock=nil;
}
static void RestoreDurability(NSString *base) {
    NSString *data=[base stringByAppendingPathComponent:@"restore-data"],*extra=[base stringByAppendingPathComponent:@"restore-extra"],*root=[base stringByAppendingPathComponent:@"restore-store"];Mk(data);Mk(extra);Mk(root);chmod(root.fileSystemRepresentation,0700);Put(data,@"deep/child/value",Bytes(@"durable"));DurableBackend *backend=Backend(data);NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store&&[store backupBundle:BID metadata:nil error:&error],@"durability state snapshot");backend.fingerprint=FP(B,@"current",NO);
    NSString *pending=[[root stringByAppendingPathComponent:BID] stringByAppendingPathComponent:@"pending.plist"];
    failSyncPath=[data stringByAppendingPathComponent:@"deep/child"];Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"restore ignored directory EIO");Check(![backend.calls containsObject:@"restore-fingerprint"]&&[backend.fingerprint[@"data"][@"VendorIdentifier"] isEqual:B],@"commit barrier fsync failure committed identity");Check([[NSDictionary dictionaryWithContentsOfFile:pending][@"phase"] isEqual:@"restoring"],@"commit barrier fsync failure lost pending state");failSyncPath=nil;
    NSMutableDictionary *target=[backend.target mutableCopy];target[@"containers"]=@{@"data":data,@"scope-extension":extra};backend.target=target;backend.additionalPreferenceRecords=@[@{@"container":@"",@"domain":@"example.new-extension",@"host":@"any",@"values":@{}},@{@"container":@"",@"domain":@"example.new-extension",@"host":@"current",@"values":@{}}];NSData *empty=[NSPropertyListSerialization dataWithPropertyList:@{} format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];backend.additionalPreferenceArtifacts=@{@"Library/Preferences/ByHost/new.plist":empty};
    requiredSyncRoots=@[data,extra];requiredPreferenceFile=[extra stringByAppendingPathComponent:@"Library/Preferences/ByHost/new.plist"];requireReplay=YES;preferencesReplayed=NO;failSyncPath=[extra stringByAppendingPathComponent:@"Library/Preferences/ByHost"];[backend.calls removeAllObjects];syncs=[NSMutableArray new];
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"post-preference directory fsync EIO was ignored");Check(preferencesReplayed&&![backend.calls containsObject:@"restore-fingerprint"],@"preference flush failure crossed identity boundary");Check([[NSDictionary dictionaryWithContentsOfFile:pending][@"phase"] isEqual:@"restoring"],@"post-preference fsync failure advanced pending identity phase");Check(Exists([extra stringByAppendingPathComponent:@"Library/Preferences/ByHost/new.plist"]),@"preference replay did not create new directory fixture");
    failSyncPath=nil;preferencesReplayed=NO;[syncs removeAllObjects];[backend.calls removeAllObjects];Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"retry after fsync failure: %@",error]);Ordered(data,YES);Ordered(extra,YES);BOOL flushedPreference=NO;for(NSDictionary *event in syncs)if([event[@"path"] isEqual:[extra stringByAppendingPathComponent:@"Library/Preferences/ByHost/new.plist"]]&&[event[@"replayed"] boolValue])flushedPreference=YES;Check(flushedPreference,@"replayed preference file was not synced");Check([backend.calls containsObject:@"restore-fingerprint"]&&!Exists(pending),@"retry did not commit and complete");syncs=nil;requireReplay=NO;requiredSyncRoots=nil;requiredPreferenceFile=nil;
}
int main(int argc,const char **argv){@autoreleasepool{Check(argc==2,@"fixture argument");NSString *base=@(argv[1]);Mk(base);ArchiveDurability(base);CollectionTests(base);RestoreDurability(base);puts("app-state durability: exclusive abandoned-stage collection/retry, deepest-first directory fsync, pre-identity EIO failures, post-preference file/directory sync and recovery passed");}return 0;}
'''


def main():
    prefix = fixtures.archive_prefix()
    with tempfile.TemporaryDirectory(prefix="shadow-state-durability-") as directory:
        temp = Path(directory).resolve()
        harness = temp / "main.m"
        harness.write_text(HARNESS)
        wrappers = []
        for name in ("Archive", "State"):
            wrapper = temp / (name + "-instrumented.m")
            wrapper.write_text('#import <Foundation/Foundation.h>\n#include <unistd.h>\nint DurabilityFsync(int);\nint DurabilityUnlinkat(int,const char *,int);\n#define fsync DurabilityFsync\n' + ('#define unlinkat DurabilityUnlinkat\n' if name == "State" else '') + '#include "' + str(ROOT / "src/AppState" / (name + ".m")) + '"\n')
            wrappers.append(wrapper)
        binary = temp / "durability"
        command = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-Wno-deprecated-declarations", "-g", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-I" + str(ROOT / "src/AppState"), "-L" + str(prefix / "lib"), "-Wl,-rpath," + str(prefix / "lib"), str(harness), *map(str, wrappers), "-larchive", "-lzstd", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-o", str(binary)]
        zstd = os.environ.get("ZSTD_PREFIX") or next((p for p in ("/opt/homebrew/opt/zstd", "/usr/local/opt/zstd") if Path(p, "lib").is_dir()), None)
        if zstd:
            command += ["-L" + str(Path(zstd) / "lib"), "-Wl,-rpath," + str(Path(zstd) / "lib")]
        subprocess.run(command, check=True)
        subprocess.run([str(binary), str(temp / "fixture")], env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"), check=True)


if __name__ == "__main__":
    main()
