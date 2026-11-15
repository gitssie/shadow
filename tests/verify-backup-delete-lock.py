#!/usr/bin/env python3
"""Run deletion-lock cases against production Core/Archive and shared FakeBackend."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("app_state", Path(__file__).with_name("verify-app-state.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
CASES = r'''
static void DeleteLockTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"store"], *data=[base stringByAppendingPathComponent:@"live"];
    Mk(data);Put(data,@"payload",Bytes(@"unchanged"));
    FakeBackend *backend=TimingBackend(data);NSError *error=nil;
    SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];
    Check(store&&[store backupBundle:BID metadata:nil error:&error],@"initial backup");
    NSString *path=SnapshotPath(root,A,@"manifest.plist");
    NSDictionary *old=[NSDictionary dictionaryWithContentsOfFile:path];
    NSString *d=Digest(SnapshotPath(root,A,@"data.tar.zst")),*s=Digest(SnapshotPath(root,A,@"state.tar.zst"));
    Check([store setDeleteLockedBundle:BID idfv:A locked:YES error:&error],@"lock backup");
    NSDictionary *locked=[NSDictionary dictionaryWithContentsOfFile:path];
    NSMutableDictionary *unchanged=[locked mutableCopy];[unchanged removeObjectForKey:@"deleteLocked"];
    Check([unchanged isEqual:old],@"lock changed other metadata");
    NSDictionary *before=Tree(root);
    Check(![store deleteBundle:BID idfv:A error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"backup_locked"],@"locked backup deleted");
    Check([before isEqual:Tree(root)],@"failed deletion changed source");
    Check([store editBundle:BID idfv:A metadata:@{@"title":@"locked title",@"note":@""} error:&error],@"locked edit failed");
    Check([d isEqual:Digest(SnapshotPath(root,A,@"data.tar.zst"))]&&[s isEqual:Digest(SnapshotPath(root,A,@"state.tar.zst"))],@"metadata changed archives");
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"locked update failed");
    Check([[NSDictionary dictionaryWithContentsOfFile:path][@"deleteLocked"]boolValue],@"update dropped lock");
    backend.fingerprint=FP(B,@"other",YES);
    Check([store claimBundle:BID idfv:A error:&error]!=nil,@"locked claim failed");store.requester=@"rv";
    Check(![store setDeleteLockedBundle:BID idfv:A locked:NO error:&error],@"RV toggled lock");
    Check(![store deleteBundle:BID idfv:A error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"backup_locked"],@"RV deleted locked backup");
    NSDictionary *exported=[store exportBundle:BID idfv:A part:@"manifest" expectedStateSHA:nil error:&error];
    NSDictionary *state=[store exportBundle:BID idfv:A part:@"state" expectedStateSHA:exported[@"stateSHA"] error:&error];
    NSMutableDictionary *forged=[[NSPropertyListSerialization propertyListWithData:exported[@"data"] options:NSPropertyListMutableContainers format:NULL error:NULL]mutableCopy];[forged removeObjectForKey:@"deleteLocked"];
    NSData *bytes=[NSPropertyListSerialization dataWithPropertyList:forged format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    Check(![store importBundle:BID idfv:A manifest:bytes state:state[@"data"] expectedManifestSHA:exported[@"manifestSHA"] error:&error],@"import removed lock");
    Check([store releaseBundle:BID idfv:A error:&error]!=nil,@"locked release failed");store.requester=nil;
    Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,@"locked restore failed");
    NSDictionary *valid=[NSDictionary dictionaryWithContentsOfFile:path];
    for (id bad in @[@1,@"YES"]) {
        NSMutableDictionary *damaged=[valid mutableCopy];damaged[@"deleteLocked"]=bad;
        Check([damaged writeToFile:path atomically:YES],@"malformed lock fixture");
        NSData *damagedBytes=[NSData dataWithContentsOfFile:path];
        Check(![store deleteBundle:BID idfv:A error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"invalid_archive"],@"invalid lock allowed deletion");
        Check([damagedBytes isEqual:[NSData dataWithContentsOfFile:path]],@"invalid lock deletion changed manifest");
    }
    Check([valid writeToFile:path atomically:YES],@"restore valid lock");
    Check([store setDeleteLockedBundle:BID idfv:A locked:NO error:&error],@"unlock failed");
    Check([store deleteBundle:BID idfv:A error:&error],@"unlocked delete failed");
    puts("backup deletion lock: metadata, update, restore, ownership, import and deletion passed");
}
'''
start = fixture.HARNESS.index("int main(int argc,const char *argv[])")
fixture.HARNESS = "#pragma clang diagnostic ignored \"-Wunused-function\"\n" + fixture.HARNESS[:start] + CASES + r'''
int main(int argc,const char *argv[]){@autoreleasepool{Check(argc==3,@"arguments");NSString *base=@(argv[1]);Mk(base);DeleteLockTests(base);return 0;}}
'''
if __name__ == "__main__":
    fixture.main()
