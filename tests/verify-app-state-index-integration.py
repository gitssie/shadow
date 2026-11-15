#!/usr/bin/env python3
"""Exercise the production backup store and SQLite index with real archives."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
fixtures = runpy.run_path(str(ROOT / "tests/verify-app-state.py"))
harness = fixtures["HARNESS"].replace("int main(", "int OriginalFixtureMain(")
harness += r'''
#import "Index.h"
#import "BackupStatus.h"
static NSUInteger payloadReads;
static IMP originalPayloadRead;
static NSDictionary *ObservedPayloadRead(id cls, SEL selector, NSString *path, NSDictionary *info, NSArray *names, NSError **error) {
    payloadReads++;
    return ((NSDictionary *(*)(id,SEL,NSString *,NSDictionary *,NSArray *,NSError **))originalPayloadRead)(cls,selector,path,info,names,error);
}
static NSDictionary *IndexedFP(NSString *idfv,NSString *region) {
    NSMutableDictionary *value=[FP(idfv,region,NO)mutableCopy];
    value[@"configuration"]=@{@"Version":@1,@"Localization":@{@"Region":region,@"Language":@"fr-FR",@"TimeZone":@"Europe/Paris"},@"Network":@{@"Transport":@"auto"}};
    return value;
}
static NSDictionary *Page(SHDWAppStateStore *store,NSDictionary *query) {
    static NSUInteger call;call++;
    NSError *error=nil;NSDictionary *page=[store queryCatalogBundle:BID query:query error:&error];
    Check(page!=nil,[NSString stringWithFormat:@"query %lu %@ failed: %@",(unsigned long)call,query,error]);return page;
}
int main(int argc,const char **argv) {@autoreleasepool {
    Check(argc==2,@"index integration arguments");NSString *base=@(argv[1]),*live=[base stringByAppendingPathComponent:@"live"],*root=[base stringByAppendingPathComponent:@"backups"];Mk(live);Put(live,@"Documents/value",Bytes(@"saved"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.keychain=@[];backend.preferences=@{};
    backend.target=@{@"bundleID":BID,@"token":@"fixture",@"version":@"3.2",@"build":@"42",@"containers":@{@"data":live},@"keychainGroups":@[]};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,error.localizedDescription);
    __block NSString *current=A;store.currentIdentityProvider=^NSString *(NSString *bundle){(void)bundle;return current;};
    NSArray *ids=@[A,B,C],*regions=@[@"FR",@"GB",@"FR"],*titles=@[@"Été Paris",@"London",@"Paris second"];
    for(NSUInteger i=0;i<ids.count;i++){backend.fingerprint=IndexedFP(ids[i],regions[i]);Reset(backend);Check([store backupBundle:BID metadata:@{@"title":titles[i],@"note":i==1?@"SUMMER travel":@""} error:&error]!=nil,error.localizedDescription);}
    NSString *secondBundle=@"other.state.fixture",*secondApp=[root stringByAppendingPathComponent:secondBundle];
    Check([NSFileManager.defaultManager copyItemAtPath:[root stringByAppendingPathComponent:BID] toPath:secondApp error:&error],@"second application legacy backup fixture");
    for(NSString *idfv in ids){NSString *manifestPath=[[[secondApp stringByAppendingPathComponent:@"snapshots"]stringByAppendingPathComponent:idfv]stringByAppendingPathComponent:@"manifest.plist"];NSMutableDictionary *manifest=[[NSDictionary dictionaryWithContentsOfFile:manifestPath]mutableCopy];manifest[@"bundleID"]=secondBundle;Check([manifest writeToFile:manifestPath atomically:YES]&&!chmod(manifestPath.fileSystemRepresentation,0600),@"second app manifest identity");}
    NSString *indexPath=[root stringByAppendingPathComponent:@".index"];
    if([NSFileManager.defaultManager fileExistsAtPath:indexPath])Check([NSFileManager.defaultManager removeItemAtPath:indexPath error:&error],@"prepare legacy backups without an index");
    NSMutableDictionary *before=[NSMutableDictionary new];for(NSString *bundle in @[BID,secondBundle])for(NSString *idfv in ids)for(NSString *name in @[@"manifest.plist",@"data.tar.zst",@"state.tar.zst"]){NSString *path=[[[[root stringByAppendingPathComponent:bundle]stringByAppendingPathComponent:@"snapshots"]stringByAppendingPathComponent:idfv]stringByAppendingPathComponent:name];before[path]=[NSData dataWithContentsOfFile:path];}
    Method method=class_getClassMethod(SHDWStateArchive.class,@selector(readPayloadsAtPath:info:names:error:));originalPayloadRead=method_getImplementation(method);method_setImplementation(method,(IMP)ObservedPayloadRead);
    NSDictionary *page=Page(store,@{@"limit":@1});Check([page[@"total"]isEqual:@3]&&[page[@"items"]count]==1&&[page[@"hasMore"]boolValue],@"initial pagination");Check([page[@"items"][0][@"idfv"]isEqual:A],@"active backup not first");Check(payloadReads==6,@"initial migration did not read all applications identity payloads");
    for(NSString *path in before)Check([before[path]isEqual:[NSData dataWithContentsOfFile:path]],@"index changed original backup bytes");
    NSUInteger warm=payloadReads;NSDictionary *other=[store queryCatalogBundle:secondBundle query:@{} error:&error];Check([other[@"total"]isEqual:@3]&&payloadReads==warm,@"initial migration omitted other applications");
    page=Page(store,@{@"refresh":@YES});Check(payloadReads==warm,@"normal refresh repeated archive migration");
    page=Page(store,@{@"search":@"missing"});Check([page[@"total"]isEqual:@0]&&[page[@"currentSnapshot"][@"idfv"]isEqual:A],@"filtered query lost active backup");
    page=Page(store,@{@"search":@"  summer  "});Check([page[@"total"]isEqual:@1]&&[page[@"items"][0][@"idfv"]isEqual:B],@"title/note case-insensitive search");
    page=Page(store,@{@"region":@"FR",@"limit":@1,@"offset":@1});Check([page[@"total"]isEqual:@2]&&[page[@"items"]count]==1&&! [page[@"hasMore"]boolValue],@"JSON region filtering and second page");Check(payloadReads==warm,@"warm search/list decoded state archives");
    for(NSDictionary *query in @[@{@"limit":@0},@{@"limit":@YES},@{@"offset":@(-1)},@{@"limit":@201},@{@"search":@42},@{@"refresh":@1},@{@"unknown":@YES}]){error=nil;Check(![store queryCatalogBundle:BID query:query error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"invalid_request"],@"malformed query accepted");}
    Check([store editBundle:BID idfv:A metadata:@{@"title":@"Renamed",@"note":@"updated note"} error:&error],error.localizedDescription);page=Page(store,@{@"search":@"renamed"});Check([page[@"total"]isEqual:@1],@"edit did not update index");
    int heldLock=open([[root stringByAppendingPathComponent:@".index"]stringByAppendingPathComponent:@".lock"].fileSystemRepresentation,O_RDWR);Check(heldLock>=0&&!flock(heldLock,LOCK_EX|LOCK_NB),@"hold advisory index writer lock");
    NSData *beforeBusy=[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"manifest.plist")];error=nil;
    Check(![store editBundle:BID idfv:A metadata:@{@"title":@"Renamed after busy index",@"note":@"metadata committed\0tail"} error:&error]&&error!=nil,@"contended index gate did not reject before source write");
    Check([beforeBusy isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"manifest.plist")]],@"index contention changed source manifest before gate");
    Check(!flock(heldLock,LOCK_UN),@"release advisory index lock");close(heldLock);error=nil;
    Check([store editBundle:BID idfv:A metadata:@{@"title":@"Renamed after busy index",@"note":@"metadata committed\0tail"} error:&error],@"metadata retry after released index gate failed");
    warm=payloadReads;page=Page(store,@{@"refresh":@YES,@"search":@"busy index"});Check([page[@"total"]isEqual:@1]&&[page[@"items"][0][@"note"]isEqual:@"metadata committed\0tail"],@"committed metadata missing from index");Check(payloadReads==warm,@"warm refresh decoded archives after successful edit");
    page=Page(store,@{@"search":@"tail"});Check([page[@"total"]isEqual:@1],@"search truncated metadata at embedded NUL");
    current=C;backend.fingerprint=IndexedFP(C,@"FR");Check([store claimBundle:BID idfv:A error:&error]!=nil,error.localizedDescription);page=Page(store,@{@"search":@"renamed"});Check([page[@"items"][0][@"owner"]isEqual:@"rv"],@"claim did not update owner index");Check([store releaseBundle:BID idfv:A error:&error]!=nil,error.localizedDescription);
    current=B;backend.fingerprint=IndexedFP(B,@"GB");Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:YES error:&error]!=nil,error.localizedDescription);current=A;page=Page(store,@{});Check([page[@"currentSnapshot"][@"status"]isEqual:SHDWBackupStatusRestored],@"restore completion status not persisted");
    Check([store deleteBundle:BID idfv:B error:&error],error.localizedDescription);page=Page(store,@{});Check([page[@"total"]isEqual:@2],@"delete not removed from index");
    NSString *state=SnapshotPath(root,C,@"state.tar.zst"),*held=[state stringByAppendingString:@".held"];Check(!rename(state.fileSystemRepresentation,held.fileSystemRepresentation),@"temporarily remove source archive");page=Page(store,@{@"refresh":@YES,@"search":@"Paris second"});Check([page[@"items"][0][@"unavailable"]boolValue],@"refresh concealed missing source archive");Check(!rename(held.fileSystemRepresentation,state.fileSystemRepresentation),@"restore source archive");
    page=Page(store,@{@"refresh":@YES});Check([page[@"total"]isEqual:@2],@"refresh lost valid backup");current=@"44444444-4444-4444-8444-444444444444";page=Page(store,@{});Check([page[@"currentSnapshot"]count]==0,@"absent active environment presented as saved backup");
    SHDWAppStateIndex *dirty=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:geteuid() ownerGID:getegid() error:&error];Check(dirty!=nil,error.localizedDescription);Check([dirty markMigrationRequired:&error],@"mark interrupted index mutation");[dirty close];
    NSString *changedManifest=SnapshotPath(root,C,@"manifest.plist");NSMutableDictionary *changed=[[NSDictionary dictionaryWithContentsOfFile:changedManifest]mutableCopy];changed[@"title"]=@"Recovered Paris second";Check([changed writeToFile:changedManifest atomically:YES]&&!chmod(changedManifest.fileSystemRepresentation,0600),@"simulate source commit before index update");
    warm=payloadReads;page=Page(store,@{@"search":@"recovered"});Check([page[@"total"]isEqual:@1]&&payloadReads==warm+5,@"dirty index did not recover all applications exactly once");
    warm=payloadReads;page=Page(store,@{@"refresh":@YES});Check(payloadReads==warm,@"recovered index repeated archive migration");
    NSData *sourceAfterRecovery=[NSData dataWithContentsOfFile:changedManifest];NSString *database=[indexPath stringByAppendingPathComponent:@"backup-index.sqlite"];Check([Bytes(@"broken SQLite fixture")writeToFile:database atomically:NO],@"corrupt only index database fixture");
    warm=payloadReads;page=Page(store,@{@"refresh":@YES});Check([page[@"total"]isEqual:@2]&&payloadReads==warm+5,@"corrupt database did not rebuild all applications");Check([sourceAfterRecovery isEqual:[NSData dataWithContentsOfFile:changedManifest]],@"cache corruption repair changed source manifest");
    warm=payloadReads;page=Page(store,@{@"refresh":@YES});Check(payloadReads==warm,@"repaired database repeated archive migration");
    backend.fingerprint=IndexedFP(A,@"FR");current=A;Reset(backend);
    Check([store backupAndResetBundle:BID expectedIDFV:A reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;NSMutableDictionary *fresh=[IndexedFP(@"44444444-4444-4444-8444-444444444444",@"FR")mutableCopy];fresh[@"locked"]=@YES;backend.fingerprint=fresh;return @{@"verified":@YES};} error:&error]!=nil,error.localizedDescription);
    current=backend.fingerprint[@"data"][@"VendorIdentifier"];page=Page(store,@{@"search":@"renamed"});Check([page[@"items"][0][@"status"]isEqual:SHDWBackupStatusResetCompleted],@"backup/reset completion status lost");
    NSUInteger count=[Page(store,@{})[@"total"]unsignedIntegerValue];Reset(backend);NSString *discarded=current;
    Check([store discardAndResetBundle:BID expectedIDFV:discarded reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;NSMutableDictionary *fresh=[IndexedFP(@"55555555-5555-4555-8555-555555555555",@"FR")mutableCopy];fresh[@"locked"]=@YES;backend.fingerprint=fresh;return @{@"verified":@YES};} error:&error]!=nil,error.localizedDescription);current=backend.fingerprint[@"data"][@"VendorIdentifier"];
    Check([Page(store,@{})[@"total"]unsignedIntegerValue]==count,@"discard created a phantom backup index row");
    NSString *firstRoot=[base stringByAppendingPathComponent:@"first-reset-backups"];
    SHDWAppStateStore *firstStore=[[SHDWAppStateStore alloc]initWithRoot:firstRoot backend:backend error:&error];Check(firstStore!=nil,error.localizedDescription);backend.fingerprint=IndexedFP(A,@"FR");Reset(backend);
    firstStore.currentIdentityProvider=^NSString *(NSString *bundle){(void)bundle;return backend.fingerprint[@"data"][@"VendorIdentifier"];};
    Check([firstStore backupAndResetBundle:BID expectedIDFV:A reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;NSMutableDictionary *fresh=[IndexedFP(B,@"GB")mutableCopy];fresh[@"locked"]=@YES;backend.fingerprint=fresh;return @{@"verified":@YES};} error:&error]!=nil,error.localizedDescription);
    page=Page(firstStore,@{});Check([page[@"items"]count]==1&&[page[@"items"][0][@"status"]isEqual:SHDWBackupStatusResetCompleted],@"first backup/reset before any query lost lifecycle status");
    method_setImplementation(method,originalPayloadRead);
    puts("app-state index integration: immutable existing backups, one-time identity extraction, paging/search/JSON region, active lookup, validation, edit/claim/delete/restore and missing-source checks, busy gates and unified interrupted/corrupt migration recovery passed");
}return 0;}
'''
prefix=fixtures["archive_prefix"]()
with tempfile.TemporaryDirectory(prefix="shadow-state-index-integration-") as directory:
    temp=Path(directory);source=temp/"main.m";source.write_text(harness)
    command=["xcrun","--sdk","macosx","clang","-fobjc-arc","-fblocks","-O1","-Wall","-Wextra","-Werror","-Wno-unused-function","-Wno-deprecated-declarations","-fsanitize=address,undefined","-framework","Foundation","-I"+str(prefix/"include"),"-I"+str(ROOT/"src/AppState"),"-L"+str(prefix/"lib"),"-Wl,-rpath,"+str(prefix/"lib"),str(source),str(ROOT/"src/AppState/Archive.m"),str(ROOT/"src/AppState/State.m"),str(ROOT/"src/AppState/Index.m"),"-larchive","-lzstd","-lsqlite3","-o",str(temp/"test")]
    zstd=next((Path(p)for p in [os.environ.get("ZSTD_PREFIX",""),"/opt/homebrew/opt/zstd","/usr/local/opt/zstd"]if p and Path(p,"lib").exists()),None)
    if zstd:command += ["-L"+str(zstd/"lib"),"-Wl,-rpath,"+str(zstd/"lib")]
    subprocess.run(command,check=True)
    subprocess.run([str(temp/"test"),str(temp/"fixtures")],check=True,env=dict(os.environ,ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",UBSAN_OPTIONS="halt_on_error=1"))
