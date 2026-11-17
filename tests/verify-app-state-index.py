"""Exercise the production SQLite backup index independently of backup storage."""
from pathlib import Path
import subprocess, tempfile, os
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#import <Foundation/Foundation.h>
#import "Index.h"
#include <assert.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sqlite3.h>
// Older iOS JSON1 functions are deterministic but lack SQLITE_INNOCUOUS.
static void LegacyJSONValid(sqlite3_context *context,int argc,sqlite3_value **values) {
 (void)argc;const void *bytes=sqlite3_value_text(values[0]);int length=sqlite3_value_bytes(values[0]);
 NSData *data=bytes?[NSData dataWithBytes:bytes length:length]:nil;
 sqlite3_result_int(context,data&&[NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingFragmentsAllowed error:NULL]!=nil);
}
int SHDWIndexTestOpen(const char *path,sqlite3 **database,int flags,const char *vfs) {
 int result=sqlite3_open_v2(path,database,flags,vfs);
 if(result==SQLITE_OK&&getenv("SHDW_INDEX_LEGACY_JSON"))
  result=sqlite3_create_function_v2(*database,"json_valid",1,SQLITE_UTF8|SQLITE_DETERMINISTIC,NULL,LegacyJSONValid,NULL,NULL,NULL);
 return result;
}
static NSDictionary *Entry(NSString *bundle,NSString *identifier,NSString *title,NSString *region,double time){
 return @{@"bundleID":bundle,@"idfv":identifier,@"title":title,@"note":@"note 100%_ and CAFÉ",@"date":[NSDate dateWithTimeIntervalSince1970:time],@"version":@"30.2",@"build":@"30260",@"digest":@"abc",@"owner":@"phone",@"size":@42,@"Fingerprint_Data":@{@"VendorIdentifier":identifier,@"InterfaceSeed":[NSData dataWithBytes:"\0\1\2" length:3]},@"Fingerprint_Config":@{@"Localization":@{@"Region":region}},@"status":@"backed_up"};
}
int main(int argc,char **argv){@autoreleasepool{
 assert(argc==2);NSString *root=@(argv[1]);assert(!mkdir(root.fileSystemRepresentation,0700));NSError *error=nil;
 SHDWAppStateIndex *index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:&error];if(!index)fprintf(stderr,"%s\n",error.description.UTF8String);assert(index&&!error);
 assert(index.requiresMigration);assert([index beginMigration:&error]);
 NSDictionary *migrationEntry=Entry(@"migration.app",@"M",@"old",@"FR",1);
 assert([index replaceEntries:@[migrationEntry] forBundle:@"migration.app" error:&error]);[index cancelMigration];
 assert(index.requiresMigration&&[index identifiersForBundle:@"migration.app" error:NULL].count==0);
 assert([index beginMigration:&error]);assert([index replaceEntries:@[migrationEntry] forBundle:@"migration.app" error:&error]);
 assert([index completeMigration:&error]);assert(!index.requiresMigration);[index close];
 index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:&error];assert(index&&!index.requiresMigration&&[index identifiersForBundle:@"migration.app" error:NULL].count==1);
 assert([index markMigrationRequired:&error]);assert(index.requiresMigration);[index close];
 index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:&error];assert(index&&index.requiresMigration);
 assert([index markConsistent:&error]);[index close];index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:&error];assert(index&&!index.requiresMigration);
 assert([index beginMigration:&error]);assert(![index markMigrationRequired:NULL]);assert(![index markConsistent:NULL]);[index cancelMigration];
 NSDictionary *a=Entry(@"app.one",@"A",@"été",@"FR",1.25),*b=Entry(@"app.one",@"B",@"Paris",@"FR",2),*c=Entry(@"app.one",@"C",@"London",@"GB",3),*foreign=Entry(@"app.two",@"A",@"other",@"US",4);
 assert(([index replaceEntries:@[a,b,c] forBundle:@"app.one" error:&error]));assert([index upsertEntry:foreign error:&error]);
 NSDictionary *row=[index entryForBundle:@"app.one" idfv:@"A" error:&error];NSMutableDictionary *expected=[a mutableCopy];expected[@"deleteLocked"]=@NO;assert([row isEqual:expected]);
 assert(CFGetTypeID((__bridge CFTypeRef)row[@"deleteLocked"])==CFBooleanGetTypeID());
 NSMutableDictionary *locked=[a mutableCopy];locked[@"deleteLocked"]=@YES;
 assert([index upsertEntry:locked error:NULL]);
 row=[index entryForBundle:@"app.one" idfv:@"A" error:NULL];assert(row[@"deleteLocked"]==(__bridge id)kCFBooleanTrue);
 assert(([index replaceEntries:@[row,b,c] forBundle:@"app.one" error:NULL]));
 [index close];index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL];assert(index);
 assert([index entryForBundle:@"app.one" idfv:@"A" error:NULL][@"deleteLocked"]==(__bridge id)kCFBooleanTrue);
 for(id invalid in @[@1,@0,@"true",NSNull.null]){locked[@"deleteLocked"]=invalid;assert(![index upsertEntry:locked error:NULL]);}
 locked[@"deleteLocked"]=@NO;assert([index upsertEntry:locked error:NULL]);
 assert([index entryForBundle:@"app.one" idfv:@"A" error:NULL][@"deleteLocked"]==(__bridge id)kCFBooleanFalse);
 NSDictionary *page=[index queryBundle:@"app.one" query:@{@"limit":@1} currentIDFV:@"A" error:&error];assert([page[@"total"]intValue]==3&&[page[@"hasMore"]boolValue]);assert([page[@"items"][0][@"idfv"]isEqual:@"A"]);assert(!page[@"items"][0][@"Fingerprint_Data"]);assert(page[@"items"][0][@"deleteLocked"]==(__bridge id)kCFBooleanFalse);
 page=[index queryBundle:@"app.one" query:@{@"limit":@1,@"offset":@1} currentIDFV:@"A" error:&error];assert([page[@"items"][0][@"idfv"]isEqual:@"C"]);
 page=[index queryBundle:@"app.one" query:@{@"dateOrder":@"asc"} currentIDFV:@"C" error:&error];assert(([[page[@"items"]valueForKey:@"idfv"]isEqual:@[@"C",@"A",@"B"]]));
 page=[index queryBundle:@"app.one" query:@{@"dateOrder":@"desc"} currentIDFV:@"A" error:&error];assert(([[page[@"items"]valueForKey:@"idfv"]isEqual:@[@"A",@"C",@"B"]]));
 page=[index queryBundle:@"app.one" query:@{@"dateOrder":@"asc",@"offset":@1,@"limit":@1} currentIDFV:@"C" error:&error];assert([page[@"items"][0][@"idfv"]isEqual:@"A"]);
 for(id order in @[@"ASC",@"invalid",@1])assert(![index queryBundle:@"app.one" query:@{@"dateOrder":order} currentIDFV:nil error:NULL]);
 page=[index queryBundle:@"app.one" query:@{@"region":@"FR"} currentIDFV:nil error:&error];assert([page[@"total"]intValue]==2);
 for(NSString *search in @[@"ÉTÉ",@"100%_",@"café",@"  ÉTÉ \n"]){page=[index queryBundle:@"app.one" query:@{@"search":search} currentIDFV:nil error:&error];assert([page[@"total"]intValue]==([search containsString:@"ÉTÉ"]?1:3));}
 assert([index setStatus:@"restored" bundle:@"app.one" idfv:@"A" error:&error]);assert([[index entryForBundle:@"app.one" idfv:@"A" error:&error][@"status"]isEqual:@"restored"]);
 assert((![index replaceEntries:@[b,@{}] forBundle:@"app.one" error:&error]));assert([index identifiersForBundle:@"app.one" error:NULL].count==3);assert([index identifiersForBundle:@"app.two" error:NULL].count==1);
 assert([index deleteBundle:@"app.one" idfv:@"B" error:NULL]);assert([index identifiersForBundle:@"app.one" error:NULL].count==2);
 assert(![index queryBundle:@"app.one" query:@{@"limit":@201} currentIDFV:nil error:NULL]);
 assert(![index queryBundle:@"app.one" query:@{@"offset":@(ULLONG_MAX)} currentIDFV:nil error:NULL]);
 assert(![index queryBundle:@"app.one" query:@{@"limit":@1.5} currentIDFV:nil error:NULL]);
 page=[index queryBundle:@"app.one" query:@{@"search":@"  \n"} currentIDFV:nil error:NULL];assert([page[@"total"]intValue]==2);
 NSMutableDictionary *nul=[a mutableCopy];unichar name[]={ 'a',0,'s','u','f','f','i','x' };nul[@"bundleID"]=@"app.nul";nul[@"title"]=[NSString stringWithCharacters:name length:8];
 assert([index upsertEntry:nul error:NULL]);
 page=[index queryBundle:@"app.nul" query:@{@"search":@"suffix"} currentIDFV:nil error:NULL];assert([page[@"total"]intValue]==1);assert([page[@"items"][0][@"title"]isEqual:nul[@"title"]]);
 // A second helper cannot race a rebuilding connection.
 SHDWAppStateIndex *busy=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:&error];assert(!busy&&[error.userInfo[@"errorCode"]isEqual:@"busy"]);
 [index close];[index close];assert(![index queryBundle:@"app.one" query:@{} currentIDFV:nil error:NULL]);
 index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL];assert(index);[index close];index=nil;
 SHDWAppStateIndex *holder=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL];assert(holder);
 dispatch_semaphore_t done=dispatch_semaphore_create(0);__block SHDWAppStateIndex *waited=nil;
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{waited=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL];dispatch_semaphore_signal(done);});
 [NSThread sleepForTimeInterval:0.05];[holder close];assert(!dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,3*NSEC_PER_SEC)));assert(waited);[waited close];
 sqlite3 *db=NULL;NSString *path=[root stringByAppendingPathComponent:@".index/backup-index.sqlite"];
 assert(sqlite3_open(path.fileSystemRepresentation,&db)==SQLITE_OK);sqlite3_stmt *s=NULL;assert(sqlite3_prepare_v2(db,"SELECT typeof(Fingerprint_Data),typeof(Fingerprint_Config),json_extract(Fingerprint_Config,'$.Localization.Region'),typeof(deleteLocked),deleteLocked FROM backup_entries WHERE bundleID='app.one' AND idfv='A'",-1,&s,NULL)==SQLITE_OK);assert(sqlite3_step(s)==SQLITE_ROW);assert(!strcmp((const char*)sqlite3_column_text(s,0),"blob"));assert(!strcmp((const char*)sqlite3_column_text(s,1),"text"));assert(!strcmp((const char*)sqlite3_column_text(s,2),"FR"));assert(!strcmp((const char*)sqlite3_column_text(s,3),"integer")&&sqlite3_column_int(s,4)==0);sqlite3_finalize(s);
 assert(sqlite3_exec(db,"UPDATE backup_entries SET deleteLocked=1 WHERE bundleID='app.one' AND idfv='A'",NULL,NULL,NULL)==SQLITE_OK);
 assert(sqlite3_exec(db,"UPDATE backup_entries SET deleteLocked=2",NULL,NULL,NULL)==SQLITE_CONSTRAINT);sqlite3_close(db);
 index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL];assert(index&&[index identifiersForBundle:@"app.one" error:NULL].count==2);assert([index entryForBundle:@"app.one" idfv:@"A" error:NULL][@"deleteLocked"]==(__bridge id)kCFBooleanTrue);index=nil;
 assert(!unlink(path.fileSystemRepresentation));assert(!symlink("/tmp",path.fileSystemRepresentation));assert(![[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL]);assert(!unlink(path.fileSystemRepresentation));
 assert([[@"not sqlite" dataUsingEncoding:NSUTF8StringEncoding]writeToFile:path atomically:YES]);assert(!chmod(path.fileSystemRepresentation,0600));assert(![[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() error:NULL]);
 NSString *sentinel=[root stringByAppendingPathComponent:@"backup-sentinel"];assert([[@"backup bytes" dataUsingEncoding:NSUTF8StringEncoding]writeToFile:sentinel atomically:YES]);
 index=[[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() rebuildIfCorrupt:YES error:NULL];assert(index&&index.requiresMigration);assert([index identifiersForBundle:@"app.one" error:NULL].count==0);assert([[NSString stringWithContentsOfFile:sentinel encoding:NSUTF8StringEncoding error:NULL]isEqual:@"backup bytes"]);[index close];
 assert(sqlite3_open(path.fileSystemRepresentation,&db)==SQLITE_OK);assert(sqlite3_exec(db,"PRAGMA user_version=999",NULL,NULL,NULL)==SQLITE_OK);sqlite3_close(db);
 assert(![[SHDWAppStateIndex alloc]initWithRoot:root ownerUID:getuid() ownerGID:getgid() rebuildIfCorrupt:YES error:NULL]);
 assert(sqlite3_open(path.fileSystemRepresentation,&db)==SQLITE_OK);assert(sqlite3_prepare_v2(db,"PRAGMA user_version",-1,&s,NULL)==SQLITE_OK);assert(sqlite3_step(s)==SQLITE_ROW&&sqlite3_column_int(s,0)==999);sqlite3_finalize(s);sqlite3_close(db);
 puts("app-state index: plist/JSON roundtrip, region, Unicode/literal search, active-first pagination, isolated CRUD, rollback, status, locks, corruption and symlink checks passed");
}}
'''
with tempfile.TemporaryDirectory(prefix='shadow-app-state-index-') as directory:
    base=Path(directory);main=base/'main.m';main.write_text(HARNESS);binary=base/'test'
    flags=['xcrun','clang','-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'src/AppState')]
    # Intercept only the production connection open to reproduce legacy JSON1 flags.
    index_object=base/'Index.o'
    subprocess.run(flags+['-Dsqlite3_open_v2=SHDWIndexTestOpen','-c',str(ROOT/'src/AppState/Index.m'),'-o',str(index_object)],check=True)
    subprocess.run(flags+['-framework','Foundation',str(main),str(index_object),'-lsqlite3','-o',str(binary)],check=True)
    subprocess.run([str(binary),str(base/'storage')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))

    subprocess.run([str(binary),str(base/'legacy-json-storage')],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0',SHDW_INDEX_LEGACY_JSON='1'))
