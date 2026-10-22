#!/usr/bin/env python3
"""Exercise production app-state storage and streaming archives in isolated fixtures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#import "State.h"
#import <CommonCrypto/CommonDigest.h>
#include <archive.h>
#include <archive_entry.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <sys/attr.h>
#include <sys/xattr.h>
#include <fcntl.h>
#include <errno.h>
#include <unistd.h>

static NSString *const A = @"11111111-1111-4111-8111-111111111111";
static NSString *const B = @"22222222-2222-4222-8222-222222222222";
static NSString *const C = @"33333333-3333-4333-8333-333333333333";
static NSString *const BID = @"example.state.fixture";
static NSString *const MCM = @".com.apple.mobile_container_manager.metadata.plist";
static void Check(BOOL ok, NSString *message) {
    if (!ok) { fprintf(stderr, "FAIL: %s\n", message.UTF8String); exit(1); }
}
static void Mk(NSString *path) {
    Check([NSFileManager.defaultManager createDirectoryAtPath:path withIntermediateDirectories:YES attributes:nil error:NULL], [@"mkdir " stringByAppendingString:path]);
}
static void Put(NSString *root, NSString *name, NSData *data) {
    NSString *path = [root stringByAppendingPathComponent:name]; Mk(path.stringByDeletingLastPathComponent);
    Check([data writeToFile:path options:0 error:NULL], @"write fixture");
}
static NSData *Bytes(NSString *text) { return [text dataUsingEncoding:NSUTF8StringEncoding]; }
static NSData *Get(NSString *root, NSString *name) { return [NSData dataWithContentsOfFile:[root stringByAppendingPathComponent:name]]; }
static void ReplacePreservingMetadata(NSString *root, NSString *name, NSData *data) {
    NSString *path=[root stringByAppendingPathComponent:name];struct stat original;Check(!lstat(path.fileSystemRepresentation,&original),@"stat same-size replacement");Check(data.length==(NSUInteger)original.st_size,@"replacement must preserve size");Put(root,name,data);struct timespec times[2]={{.tv_nsec=UTIME_OMIT},original.st_mtimespec};Check(!utimensat(AT_FDCWD,path.fileSystemRepresentation,times,AT_SYMLINK_NOFOLLOW),@"restore replacement timestamp");
}
static NSDictionary *Times(NSString *path) {
    struct stat value;Check(!lstat(path.fileSystemRepresentation,&value),@"stat file dates");
    return @{@"birthtime":@(value.st_birthtimespec.tv_sec),@"birthtimeNsec":@(value.st_birthtimespec.tv_nsec),@"mtime":@(value.st_mtimespec.tv_sec),@"mtimeNsec":@(value.st_mtimespec.tv_nsec)};
}
static void SetBirth(NSString *path,time_t seconds,long nanoseconds) {
    struct attrlist attributes={.bitmapcount=ATTR_BIT_MAP_COUNT,.commonattr=ATTR_CMN_CRTIME};
    struct timespec birth={.tv_sec=seconds,.tv_nsec=nanoseconds};
    Check(!setattrlist(path.fileSystemRepresentation,&attributes,&birth,sizeof(birth),FSOPT_NOFOLLOW),@"set creation time");
}
static NSDictionary *HistoricalTimes(NSString *path,time_t seconds) {
    struct timespec times[2]={{.tv_nsec=UTIME_OMIT},{.tv_sec=seconds,.tv_nsec=123456789}};
    Check(!utimensat(AT_FDCWD,path.fileSystemRepresentation,times,AT_SYMLINK_NOFOLLOW),@"set historical nanosecond modification time");
    SetBirth(path,seconds-1000,987654321);
    return Times(path); // Assert against actual filesystem precision, not requested precision.
}
static BOOL SameBirth(NSDictionary *left,NSDictionary *right) {
    return [left[@"birthtime"] isEqual:right[@"birthtime"]]&&[left[@"birthtimeNsec"] isEqual:right[@"birthtimeNsec"]];
}
static NSString *DigestData(NSData *data) {
    unsigned char value[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes, (CC_LONG)data.length, value);
    NSMutableString *result = [NSMutableString new]; for (NSUInteger i=0;i<sizeof(value);i++) [result appendFormat:@"%02x", value[i]]; return result;
}
static NSString *Digest(NSString *path) {
    int fd = open(path.fileSystemRepresentation, O_RDONLY|O_NOFOLLOW); Check(fd >= 0, @"open hash fixture");
    CC_SHA256_CTX state; CC_SHA256_Init(&state); unsigned char buffer[131072]; ssize_t n;
    while ((n=read(fd,buffer,sizeof(buffer)))>0) CC_SHA256_Update(&state,buffer,(CC_LONG)n);
    Check(n==0,@"read hash fixture"); close(fd); unsigned char value[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_Final(value,&state);
    NSMutableString *result=[NSMutableString new]; for(NSUInteger i=0;i<sizeof(value);i++) [result appendFormat:@"%02x",value[i]]; return result;
}
static NSDictionary *Tree(NSString *root) {
    NSMutableDictionary *result=[NSMutableDictionary new];
    NSDirectoryEnumerator *scan=[NSFileManager.defaultManager enumeratorAtPath:root]; NSString *name;
    while((name=[scan nextObject])) {
        NSString *path=[root stringByAppendingPathComponent:name]; struct stat st; Check(!lstat(path.fileSystemRepresentation,&st),@"stat tree");
        NSMutableDictionary *item=[Times(path) mutableCopy];item[@"mode"]=@(st.st_mode&07777);item[@"uid"]=@(st.st_uid);item[@"gid"]=@(st.st_gid);
        if(S_ISLNK(st.st_mode)) { [scan skipDescendants];item[@"link"]=[NSFileManager.defaultManager destinationOfSymbolicLinkAtPath:path error:NULL] ?: @""; }
        else if(S_ISREG(st.st_mode)) {item[@"hash"]=Digest(path);item[@"size"]=@(st.st_size);}
        else item[@"directory"]=@YES;
        result[name]=item;
    } return result;
}
static NSDictionary *ContentTree(NSString *root) {
    NSMutableDictionary *result=[Tree(root) mutableCopy]; [result removeObjectForKey:MCM]; [result removeObjectForKey:@".com.apple.mobile_container_manager.acl.plist"];
    for(NSString *name in result.allKeys) { NSMutableDictionary *entry=[result[name] mutableCopy];NSString *link=entry[@"link"];if([link hasPrefix:[root stringByAppendingString:@"/"]])entry[@"link"]=[@"$ROOT/" stringByAppendingString:[link substringFromIndex:root.length+1]]; result[name]=entry; } return result;
}
static NSDictionary *StoreTree(NSString *root) {
    NSMutableDictionary *result=[Tree(root) mutableCopy];
    // Creating and removing a private staging directory changes its parent's mtime.
    for(NSString *name in result.allKeys)if([result[name][@"directory"] boolValue]){NSMutableDictionary *entry=[result[name] mutableCopy];[entry removeObjectForKey:@"mtime"];[entry removeObjectForKey:@"mtimeNsec"];result[name]=entry;}
    return result;
}
static NSDictionary *FP(NSString *idfv, NSString *tag, BOOL locked) {
    return @{@"data":@{@"VendorIdentifier":idfv,@"tag":tag,@"binary":[NSData dataWithBytes:"\0\1\xff" length:3]},@"configuration":@{@"region":tag,@"enabled":@YES},@"locked":@(locked)};
}
static NSError *Problem(NSString *message) { return [NSError errorWithDomain:@"fixture" code:77 userInfo:@{NSLocalizedDescriptionKey:message}]; }
@interface FakeBackend : NSObject <SHDWAppStateBackend>
@property(nonatomic,strong) NSDictionary *target;
@property(nonatomic,strong) NSDictionary *fingerprint;
@property(nonatomic,strong) NSArray *keychain;
@property(nonatomic,strong) NSMutableArray *calls;
@property(nonatomic) BOOL stopped;
@property(nonatomic) BOOL restarted;
@property(nonatomic) BOOL failCapture;
@property(nonatomic) BOOL failRestore;
@property(nonatomic) BOOL failFlush;
@end
@implementation FakeBackend
- (NSDictionary *)resolveBundle:(NSString *)bundleID error:(NSError **)error { (void)error; [self.calls addObject:@"resolve"]; Check([bundleID isEqual:BID],@"invalid bundle reached backend"); return self.target; }
- (BOOL)stopTarget:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;[self.calls addObject:@"stop"];self.stopped=YES;return YES; }
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error { (void)target;[self.calls addObject:@"assert"];Check(self.stopped,@"assert before stop");if(self.restarted){if(error)*error=Problem(@"target restarted");return NO;}return YES; }
- (BOOL)flushPreferencesForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"flush before stop");[self.calls addObject:@"flush"];if(self.failFlush){if(error)*error=Problem(@"flush failed");return NO;}return YES; }
- (NSArray *)captureKeychainForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"keychain capture before stop");[self.calls addObject:@"capture-keychain"];if(self.failCapture){if(error)*error=Problem(@"capture failed");return nil;}return self.keychain; }
- (BOOL)validateKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;return [records isKindOfClass:NSArray.class]; }
- (BOOL)restoreKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"keychain restore before stop");[self.calls addObject:@"restore-keychain"];if(self.failRestore){if(error)*error=Problem(@"restore failed");return NO;}self.keychain=[records copy];return YES; }
- (NSDictionary *)captureFingerprintForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;Check(self.stopped,@"fingerprint capture before stop");[self.calls addObject:@"capture-fingerprint"];return self.fingerprint; }
- (BOOL)validateFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;return [fingerprint[@"data"] isKindOfClass:NSDictionary.class]&&[fingerprint[@"configuration"] isKindOfClass:NSDictionary.class]; }
- (BOOL)restoreFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;Check(self.stopped,@"fingerprint restore before stop");[self.calls addObject:@"restore-fingerprint"];NSMutableDictionary *value=[fingerprint mutableCopy];value[@"locked"]=@YES;self.fingerprint=value;return YES; }
@end

static NSDictionary *RehashInfo(NSDictionary *original, NSString *path, NSArray *entries) {
    NSMutableDictionary *info=[original mutableCopy];struct stat st;Check(!stat(path.fileSystemRepresentation,&st),@"stat archive");info[@"sha256"]=Digest(path);info[@"archiveSize"]=@(st.st_size);info[@"entries"]=entries;return info;
}
static NSDictionary *Entry(NSString *path, NSString *type, NSData *data, NSString *link) {
    NSMutableDictionary *entry=[@{@"path":path,@"type":type,@"mode":@0644,@"uid":@(getuid()),@"gid":@(getgid()),@"mtime":@0,@"mtimeNsec":@0,@"birthtime":@0,@"birthtimeNsec":@0} mutableCopy];
    if([type isEqual:@"file"]){entry[@"size"]=@(data.length);entry[@"sha256"]=DigestData(data);}
    if(link)entry[@"target"]=link;return entry;
}
static void MaliciousArchive(NSString *path, NSArray *entries, NSData *payload) {
    struct archive *writer=archive_write_new();Check(writer!=NULL,@"archive fixture writer");Check(archive_write_add_filter_zstd(writer)==ARCHIVE_OK,@"fixture zstd support");Check(archive_write_set_format_pax_restricted(writer)==ARCHIVE_OK,@"fixture pax support");Check(archive_write_open_filename(writer,path.fileSystemRepresentation)==ARCHIVE_OK,@"fixture archive open");
    for(NSDictionary *item in entries){struct archive_entry *entry=archive_entry_new();archive_entry_set_pathname(entry,[item[@"path"] UTF8String]);archive_entry_set_uid(entry,[item[@"uid"] intValue]);archive_entry_set_gid(entry,[item[@"gid"] intValue]);archive_entry_set_perm(entry,[item[@"mode"] intValue]);archive_entry_set_mtime(entry,0,0);archive_entry_set_birthtime(entry,[item[@"birthtime"] longLongValue],[item[@"birthtimeNsec"] longValue]);NSString *birth=[NSString stringWithFormat:@"%lld:%09ld",[item[@"birthtime"] longLongValue],[item[@"birthtimeNsec"] longValue]];archive_entry_xattr_add_entry(entry,"org.shadow.birthtime",birth.UTF8String,strlen(birth.UTF8String));NSString *type=item[@"type"];archive_entry_set_filetype(entry,[type isEqual:@"directory"]?AE_IFDIR:[type isEqual:@"symlink"]?AE_IFLNK:AE_IFREG);if([type isEqual:@"symlink"])archive_entry_set_symlink(entry,[item[@"target"] UTF8String]);if([type isEqual:@"file"])archive_entry_set_size(entry,payload.length);Check(archive_write_header(writer,entry)==ARCHIVE_OK,@"fixture archive header");if([type isEqual:@"file"])Check(archive_write_data(writer,payload.bytes,payload.length)==(la_ssize_t)payload.length,@"fixture archive data");archive_entry_free(entry);}
    Check(archive_write_close(writer)==ARCHIVE_OK,@"fixture archive close");archive_write_free(writer);
}
static void ArchiveTests(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"archive-source"],*destination=[base stringByAppendingPathComponent:@"archive-destination"],*outside=[base stringByAppendingPathComponent:@"archive-outside"],*archive=[base stringByAppendingPathComponent:@"real.tar.zst"];
    Mk(source);Mk(destination);Mk(outside);Put(source,@"Documents/text",Bytes(@"alpha"));Put(source,@"Library/Preferences/value",Bytes(@"value"));Put(source,@"empty",[NSData data]);unsigned char bytes[]={0,1,2,0,255,128,0};Put(source,@"binary",[NSData dataWithBytes:bytes length:sizeof(bytes)]);Put(outside,@"untouched",Bytes(@"keep"));Check(!symlink([outside stringByAppendingPathComponent:@"untouched"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"external-link"].fileSystemRepresentation),@"external symlink");Check(!symlink("Documents/text",[source stringByAppendingPathComponent:@"relative-link"].fileSystemRepresentation),@"relative symlink");Check(!symlink([source stringByAppendingPathComponent:@"Documents/text"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"absolute-internal"].fileSystemRepresentation),@"absolute internal link");
    for(NSString *name in @[@"equal-dates",@"newer-birth",@"same-second-birth"])Put(source,name,Bytes(name));HistoricalTimes([source stringByAppendingPathComponent:@"equal-dates"],1100000000);SetBirth([source stringByAppendingPathComponent:@"equal-dates"],1100000000,123456789);HistoricalTimes([source stringByAppendingPathComponent:@"newer-birth"],1100000100);SetBirth([source stringByAppendingPathComponent:@"newer-birth"],1100000200,987654321);HistoricalTimes([source stringByAppendingPathComponent:@"same-second-birth"],1100000300);SetBirth([source stringByAppendingPathComponent:@"same-second-birth"],1100000300,987654321);
    NSDictionary *equalDates=Times([source stringByAppendingPathComponent:@"equal-dates"]),*newerDates=Times([source stringByAppendingPathComponent:@"newer-birth"]),*sameSecondDates=Times([source stringByAppendingPathComponent:@"same-second-birth"]);Check([equalDates[@"birthtime"] isEqual:equalDates[@"mtime"]]&&[equalDates[@"birthtimeNsec"] isEqual:equalDates[@"mtimeNsec"]],@"filesystem did not retain equal creation/modification fixture");Check([newerDates[@"birthtime"] longLongValue]>[newerDates[@"mtime"] longLongValue],@"filesystem did not retain creation newer than modification fixture");Check([sameSecondDates[@"birthtime"] isEqual:sameSecondDates[@"mtime"]]&&[sameSecondDates[@"birthtimeNsec"] longValue]>[sameSecondDates[@"mtimeNsec"] longValue],@"filesystem did not retain same-second distinct nanosecond fixture");
    NSDictionary *outsideBefore=Tree(outside);
    NSArray *historical=@[@"Documents/text",@"Documents",@"Library/Preferences/value",@"Library/Preferences",@"Library",@"binary",@"empty",@"external-link",@"relative-link",@"absolute-internal"];NSUInteger historicalIndex=0;for(NSString *name in historical)HistoricalTimes([source stringByAppendingPathComponent:name],978307200+(time_t)historicalIndex++);NSDictionary *sourceRootTimes=HistoricalTimes(source,946684800);NSDictionary *destinationRootTimes=HistoricalTimes(destination,1104537600);NSDictionary *olderDates=Times([source stringByAppendingPathComponent:@"Documents/text"]);Check([olderDates[@"birthtime"] longLongValue]<[olderDates[@"mtime"] longLongValue],@"filesystem did not retain historical creation before modification fixture");NSDictionary *historicalBefore=Tree(source);
    NSDictionary *roots=@{@"containers/data":source};NSError *error=nil;NSDictionary *info=[SHDWStateArchive captureRoots:roots payloads:@{@"payloads/test":[NSData dataWithBytes:bytes length:sizeof(bytes)]} toPath:archive progress:nil error:&error];Check(info!=nil,[NSString stringWithFormat:@"capture real archive: %@",error]);Check([info[@"compression"] isEqual:@"zstd"],@"archive compression");Check([SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"verify real archive");Check([SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],@"verify full source hashes");NSDictionary *payloads=[SHDWStateArchive readPayloadsAtPath:archive info:info names:@[@"payloads/test"] error:&error];Check([payloads[@"payloads/test"] isEqual:[NSData dataWithBytes:bytes length:sizeof(bytes)]],@"binary payload roundtrip");
    Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":destination} progress:nil error:&error],[NSString stringWithFormat:@"restore real archive: %@",error]);Check([ContentTree(source) isEqual:ContentTree(destination)],@"all restored regular files and symlinks equal including original creation and nanosecond modification dates");Check(SameBirth(destinationRootTimes,Times(destination)),@"restore overwrote destination container root creation time");Check([historicalBefore isEqual:Tree(source)]&&[sourceRootTimes isEqual:Times(source)],@"archive capture changed original dates");Check([outsideBefore isEqual:Tree(outside)],@"external symlink date restoration changed outside file");Check([SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"verify restored hashes");ReplacePreservingMetadata(destination,@"Documents/text",Bytes(@"bravo"));Check(![SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"same-size file corruption accepted");ReplacePreservingMetadata(destination,@"Documents/text",Bytes(@"alpha"));ReplacePreservingMetadata(destination,@"binary",[NSData dataWithBytes:"\1\1\2\0\xff\x80\0" length:7]);Check(![SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"same-size binary corruption with unchanged timestamp accepted");ReplacePreservingMetadata(destination,@"binary",[NSData dataWithBytes:bytes length:sizeof(bytes)]);Put(destination,@"extra",Bytes(@"extra"));Check(![SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"extra destination file accepted");
    Check([NSFileManager.defaultManager removeItemAtPath:[destination stringByAppendingPathComponent:@"extra"] error:NULL],@"remove extra-file fixture");Check([SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"date-mutation baseline root verification");
    NSString *datePath=[destination stringByAppendingPathComponent:@"Documents/text"];NSDictionary *savedDates=Times(datePath);SetBirth(datePath,[savedDates[@"birthtime"] longLongValue]+20,[savedDates[@"birthtimeNsec"] longValue]);Check(![SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"changed current creation time was not detected");SetBirth(datePath,[savedDates[@"birthtime"] longLongValue],[savedDates[@"birthtimeNsec"] longValue]);for(NSString *name in historical){errno=0;Check(getxattr([destination stringByAppendingPathComponent:name].fileSystemRepresentation,"org.shadow.birthtime",NULL,0,0,XATTR_NOFOLLOW)==-1&&errno==ENOATTR,@"internal PAX creation annotation leaked into restored app xattrs");}
    NSString *changingArchive=[base stringByAppendingPathComponent:@"changing-dates.tar.zst"];NSString *changingFile=[source stringByAppendingPathComponent:@"Documents/text"];NSDictionary *unchangedDates=Times(changingFile);__block BOOL dateChanged=NO;SHDWStateProgress changeDate=^(NSDictionary *event){if(!dateChanged&&[event[@"phase"] isEqual:@"capture"]&&[event[@"entries"] unsignedIntegerValue]>=3&&[event[@"bytes"] unsignedLongLongValue]>0){dateChanged=YES;SetBirth(changingFile,[unchangedDates[@"birthtime"] longLongValue]+20,[unchangedDates[@"birthtimeNsec"] longValue]);}};Check(![SHDWStateArchive captureRoots:roots payloads:@{} toPath:changingArchive progress:changeDate error:&error]&&dateChanged,@"source creation date change after capture was accepted");Check(![NSFileManager.defaultManager fileExistsAtPath:changingArchive],@"failed source-date capture retained partial archive");SetBirth(changingFile,[unchangedDates[@"birthtime"] longLongValue],[unchangedDates[@"birthtimeNsec"] longValue]);
    NSDictionary *sourceBeforeOverlap=Tree(source);NSString *inside=[source stringByAppendingPathComponent:@"self.tar.zst"];Check(![SHDWStateArchive captureRoots:roots payloads:@{} toPath:inside progress:nil error:&error],@"archive output inside source accepted");Check(![NSFileManager.defaultManager fileExistsAtPath:inside]&&[sourceBeforeOverlap isEqual:Tree(source)],@"source overlap rejection mutated input");
    NSData *original=[NSData dataWithContentsOfFile:archive];NSMutableData *corrupt=[original mutableCopy];((unsigned char *)corrupt.mutableBytes)[corrupt.length/2]^=0x80;Check([corrupt writeToFile:archive atomically:YES],@"corrupt fixture");Check(![SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"archive corruption accepted");Check([[original subdataWithRange:NSMakeRange(0,original.length/2)] writeToFile:archive atomically:YES],@"truncate fixture");Check(![SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"truncated archive accepted");Check([original writeToFile:archive atomically:YES],@"restore archive fixture");
    NSMutableArray *entries=[info[@"entries"] mutableCopy];Check(entries.count>0,@"manifest entries missing");[entries addObject:entries.firstObject];NSMutableDictionary *bad=[info mutableCopy];bad[@"entries"]=entries;Check(![SHDWStateArchive verifyPath:archive info:bad progress:nil error:&error],@"duplicate manifest entries accepted");entries=[info[@"entries"] mutableCopy];[entries addObject:Entry(@"containers/data/not-in-archive",@"file",Bytes(@"x"),nil)];bad=[info mutableCopy];bad[@"entries"]=entries;Check(![SHDWStateArchive verifyPath:archive info:bad progress:nil error:&error],@"extra manifest entry accepted");
    NSString *alias=[base stringByAppendingPathComponent:@"source-alias"];Check(!symlink(source.fileSystemRepresentation,alias.fileSystemRepresentation),@"source root alias");Check(![SHDWStateArchive captureRoots:@{@"containers/data":alias} payloads:@{} toPath:[base stringByAppendingPathComponent:@"alias.tar.zst"] progress:nil error:&error],@"source root symlink accepted");Check(![SHDWStateArchive captureRoots:@{@"../escape":source} payloads:@{} toPath:[base stringByAppendingPathComponent:@"prefix.tar.zst"] progress:nil error:&error],@"archive prefix traversal accepted");
    NSString *blocked=[base stringByAppendingPathComponent:@"blocked-destination"];Mk(blocked);Check(!symlink(outside.fileSystemRepresentation,[blocked stringByAppendingPathComponent:@"Library"].fileSystemRepresentation),@"restore ancestor symlink");Check(![SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":blocked} progress:nil error:&error],@"restore followed symlink ancestor");Check([outsideBefore isEqual:Tree(outside)],@"symlink ancestor modified outside storage");
    NSData *benignData=Bytes(@"benign");NSArray *benignRecords=@[Entry(@"containers/data",@"directory",nil,nil),Entry(@"containers/data/benign",@"file",benignData,nil)];NSString *benignPath=[base stringByAppendingPathComponent:@"benign-crafted.tar.zst"];MaliciousArchive(benignPath,benignRecords,benignData);Check([SHDWStateArchive verifyPath:benignPath info:RehashInfo(info,benignPath,benignRecords) progress:nil error:&error],[NSString stringWithFormat:@"benign crafted archive rejected before adversarial cases: %@",error]);
    NSData *evil=Bytes(@"evil");NSArray *badPaths=@[@"../outside",@"containers/data/../../outside",[outside stringByAppendingPathComponent:@"pwn"]];NSUInteger ordinal=0;
    for(NSString *path in badPaths){NSArray *records=@[Entry(@"containers/data",@"directory",nil,nil),Entry(path,@"file",evil,nil)];NSString *crafted=[base stringByAppendingPathComponent:[NSString stringWithFormat:@"malicious-%lu.tar.zst",(unsigned long)ordinal++]];MaliciousArchive(crafted,records,evil);NSDictionary *craftedInfo=RehashInfo(info,crafted,records);Check(![SHDWStateArchive verifyPath:crafted info:craftedInfo progress:nil error:&error],@"malicious archive pathname accepted");Check(![SHDWStateArchive restorePath:crafted info:craftedInfo roots:@{@"containers/data":blocked} progress:nil error:&error],@"malicious archive extraction accepted");}
    NSArray *duplicate=@[Entry(@"containers/data",@"directory",nil,nil),Entry(@"containers/data/duplicate",@"file",evil,nil),Entry(@"containers/data/duplicate",@"file",evil,nil)];NSString *crafted=[base stringByAppendingPathComponent:@"duplicate.tar.zst"];MaliciousArchive(crafted,duplicate,evil);Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,duplicate) progress:nil error:&error],@"duplicate archive paths accepted");NSArray *linkAncestor=@[Entry(@"containers/data",@"directory",nil,nil),Entry(@"containers/data/link",@"symlink",nil,outside),Entry(@"containers/data/link/pwn",@"file",evil,nil)];crafted=[base stringByAppendingPathComponent:@"link-ancestor.tar.zst"];MaliciousArchive(crafted,linkAncestor,evil);Check(![SHDWStateArchive restorePath:crafted info:RehashInfo(info,crafted,linkAncestor) roots:@{@"containers/data":blocked} progress:nil error:&error],@"archive-created symlink ancestor accepted");Check([outsideBefore isEqual:Tree(outside)],@"malicious archive changed outside storage");NSArray *extraRecords=@[Entry(@"containers/data",@"directory",nil,nil),Entry(@"containers/data/unlisted",@"file",evil,nil)];crafted=[base stringByAppendingPathComponent:@"extra-archive-entry.tar.zst"];MaliciousArchive(crafted,extraRecords,evil);Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,@[extraRecords.firstObject]) progress:nil error:&error],@"unlisted archive entry accepted");
    puts("app-state archive: real zstd, full hashes, nanosecond creation/modification dates, corruption and no-follow traversal passed");
}

static NSString *SnapshotPath(NSString *root,NSString *idfv,NSString *name){return [[[[root stringByAppendingPathComponent:BID] stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:idfv] stringByAppendingPathComponent:name];}
static void Reset(FakeBackend *backend){backend.stopped=NO;[backend.calls removeAllObjects];}
static void StateTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"store"],*data=[base stringByAppendingPathComponent:@"live"],*group=[base stringByAppendingPathComponent:@"live-group"],*other=[base stringByAppendingPathComponent:@"other-app"];Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private store fixture");Mk(data);Mk(group);Mk(other);Put(data,MCM,Bytes(@"MCM-original"));Put(data,@".com.apple.mobile_container_manager.acl.plist",Bytes(@"ACL-original"));Put(data,@"Documents/text",Bytes(@"alpha"));unsigned char raw[]={0,255,0,12,13};Put(data,@"Library/binary",[NSData dataWithBytes:raw length:sizeof(raw)]);Put(group,@"group-file",Bytes(@"group-alpha"));Put(other,@"untouched",Bytes(@"other application"));NSDictionary *otherBefore=Tree(other);
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"stable-fixture-token",@"version":@"1.0",@"build":@"42",@"containers":@{@"data":data,@"group.example.state":group},@"keychainGroups":@[@"TEAM.example.state.fixture"]};backend.fingerprint=FP(A,@"alpha",NO);backend.keychain=@[@{@"class":@"genp",@"data":[NSData dataWithBytes:raw length:sizeof(raw)],@"account":@"alpha"}];NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,[NSString stringWithFormat:@"create store: %@",error]);store.progressHandler=^(NSDictionary *event){NSString *phase=event[@"phase"];if([phase isEqual:@"capture"]||[phase isEqual:@"restore"])Check(backend.stopped,@"archive work before target stop");};
    NSMutableDictionary *withDigest=[backend.fingerprint mutableCopy];NSString *digest=[@"ab" stringByPaddingToLength:64 withString:@"ab" startingAtIndex:0];withDigest[@"digest"]=digest;backend.fingerprint=withDigest;
    NSDictionary *first=[store backupBundle:BID metadata:@{@"title":@"First",@"note":@"retained"} error:&error];Check(first!=nil,[NSString stringWithFormat:@"first backup: %@",error]);Check([backend.calls containsObject:@"stop"],@"backup did not stop target");NSArray *firstCatalog=[store catalogBundle:BID error:&error];Check(firstCatalog.count==1,[NSString stringWithFormat:@"first catalog count=%lu error=%@",(unsigned long)firstCatalog.count,error]);Check([first[@"digest"] isEqual:digest]&&[firstCatalog[0][@"digest"] isEqual:digest],@"archived fingerprint digest not retained in catalog");
    Put(data,@"Documents/text",Bytes(@"bravo"));Reset(backend);Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"same IDFV update");NSArray *catalog=[store catalogBundle:BID error:&error];Check(catalog.count==1,@"same IDFV created duplicate");Check([catalog[0][@"title"] isEqual:@"First"]&&[catalog[0][@"note"] isEqual:@"retained"],@"update lost metadata");NSDictionary *savedData=ContentTree(data),*savedGroup=ContentTree(group),*savedFP=backend.fingerprint;NSArray *savedKeys=backend.keychain;NSString *archiveA=SnapshotPath(root,A,@"data.tar.zst"),*hashA=Digest(archiveA);
    Put(data,@"Documents/text",Bytes(@"failed"));__block BOOL interrupted=NO;store.progressHandler=^(NSDictionary *event){if([event[@"bytes"] unsignedLongLongValue]>0){interrupted=YES;backend.restarted=YES;}};Reset(backend);NSDictionary *beforeInterrupted=StoreTree(root);Check(![store backupBundle:BID metadata:nil error:&error]&&interrupted,@"mid-archive restart did not fail backup");backend.restarted=NO;store.progressHandler=nil;Check([hashA isEqual:Digest(archiveA)]&&[beforeInterrupted isEqual:StoreTree(root)],@"mid-archive failure clobbered old snapshot or retained staging");
    backend.failCapture=YES;Put(data,@"Documents/text",Bytes(@"failed"));Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"failed capture reported success");Check([hashA isEqual:Digest(archiveA)],@"failed backup clobbered old snapshot");backend.failCapture=NO;backend.fingerprint=FP(B,@"beta",NO);backend.keychain=@[@{@"class":@"genp",@"account":@"beta",@"data":Bytes(@"beta")}];Put(data,@"Documents/text",Bytes(@"charl"));Reset(backend);Check([store backupBundle:BID metadata:@{@"title":@"Second",@"note":@"beta"} error:&error]!=nil,@"second IDFV backup");Check([store catalogBundle:BID error:&error].count==2,@"unique IDFV catalog");Check([store editBundle:BID idfv:A metadata:@{@"title":@"Edited",@"note":@"retained-edit"} error:&error],@"edit snapshot metadata");
    NSDictionary *readOnlyBefore=Tree(root);Reset(backend);Check([store catalogBundle:BID error:&error]!=nil&&[store recheckBundle:BID idfv:A error:&error],@"readonly catalog/recheck");Check(backend.calls.count==0&&[readOnlyBefore isEqual:Tree(root)],@"catalog/recheck mutated store or backend");
    Put(data,MCM,Bytes(@"MCM-live"));Put(data,@".com.apple.mobile_container_manager.acl.plist",Bytes(@"ACL-live"));NSDictionary *liveRootDates=HistoricalTimes(data,1200000000),*liveGroupRootDates=HistoricalTimes(group,1200000100),*liveMCMDates=Times([data stringByAppendingPathComponent:MCM]),*liveACLDates=Times([data stringByAppendingPathComponent:@".com.apple.mobile_container_manager.acl.plist"]);Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:YES error:&error]!=nil,[NSString stringWithFormat:@"restore selected snapshot: %@",error]);Check([ContentTree(data) isEqual:savedData]&&[ContentTree(group) isEqual:savedGroup],@"restored full file set differs");Check([Get(data,MCM)isEqual:Bytes(@"MCM-live")]&&[Get(data,@".com.apple.mobile_container_manager.acl.plist")isEqual:Bytes(@"ACL-live")],@"restore replaced MCM registration metadata");Check(SameBirth(liveRootDates,Times(data))&&SameBirth(liveGroupRootDates,Times(group))&&[liveMCMDates isEqual:Times([data stringByAppendingPathComponent:MCM])]&&[liveACLDates isEqual:Times([data stringByAppendingPathComponent:@".com.apple.mobile_container_manager.acl.plist"])],@"restore changed container-root creation or MCM/ACL dates");Check([backend.keychain isEqual:savedKeys],@"restored keychain differs");Check([backend.fingerprint[@"data"] isEqual:savedFP[@"data"]]&&[backend.fingerprint[@"configuration"] isEqual:savedFP[@"configuration"]]&&[backend.fingerprint[@"locked"] boolValue],@"fingerprint data/configuration/lock not restored together");Check([otherBefore isEqual:Tree(other)],@"restore changed another application");Check([hashA isEqual:Digest(archiveA)],@"restore clobbered selected source");
    NSDictionary *liveBefore=Tree(data),*sameStore=Tree(root);Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error],@"same IDFV saveCurrent allowed");Check([sameStore isEqual:Tree(root)]&&[liveBefore isEqual:Tree(data)],@"same IDFV rejection clobbered data");
    backend.fingerprint=FP(C,@"gamma",NO);backend.failCapture=YES;Put(data,@"Documents/text",Bytes(@"current-unsaved"));liveBefore=Tree(data);sameStore=Tree(root);Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error],@"save-current failure allowed restore");Check([liveBefore isEqual:Tree(data)]&&[sameStore isEqual:Tree(root)],@"save-current failure wrote store or live files");backend.failCapture=NO;
    for(NSString *badID in @[@"../escape",@"not-a-uuid",@"",@"11111111/1111-4111-8111-111111111111"]){sameStore=Tree(root);Check(![store restoreBundle:BID idfv:badID saveCurrent:NO error:&error]&&![store deleteBundle:BID idfv:badID error:&error]&&![store editBundle:BID idfv:badID metadata:@{@"title":@"bad",@"note":@""} error:&error]&&![store recheckBundle:BID idfv:badID error:&error],@"invalid IDFV accepted");Check([sameStore isEqual:Tree(root)],@"invalid IDFV changed store");}
    sameStore=Tree(root);Reset(backend);Check(![store backupBundle:@"../escape" metadata:nil error:&error],@"bundle traversal accepted");Check(backend.calls.count==0&&[sameStore isEqual:Tree(root)],@"invalid bundle reached backend or filesystem");backend.fingerprint=FP(@"not-a-uuid",@"invalid",NO);Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"invalid live IDFV accepted");
    backend.fingerprint=FP(C,@"gamma",NO);backend.restarted=YES;liveBefore=Tree(data);Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"restarted target restore succeeded");Check([liveBefore isEqual:Tree(data)],@"target restart failure modified live files");backend.restarted=NO;
    backend.failRestore=YES;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"partial restore reported success");NSString *pending=[[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@"pending.plist"];Check([NSFileManager.defaultManager fileExistsAtPath:pending],@"partial restore lost pending state");sameStore=Tree(root);Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"backup allowed while pending");Check(![store deleteBundle:BID idfv:A error:&error]&&![store editBundle:BID idfv:A metadata:@{@"title":@"bad",@"note":@""} error:&error],@"pending source was mutable");Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error],@"pending retry auto-saved over source");Check([sameStore isEqual:Tree(root)],@"pending protection changed archive/store");Check([store recheckBundle:BID idfv:A error:&error]&&[store catalogBundle:BID error:&error]!=nil,@"pending readonly inspection failed");backend.failRestore=NO;backend.fingerprint=@{};Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,@"pending restore retry failed");Check(![NSFileManager.defaultManager fileExistsAtPath:pending],@"successful retry retained pending state");Check([hashA isEqual:Digest(archiveA)]&&[otherBefore isEqual:Tree(other)],@"pending retry changed source/other app");
    NSData *goodArchive=[NSData dataWithContentsOfFile:archiveA];NSMutableData *brokenArchive=[goodArchive mutableCopy];((unsigned char *)brokenArchive.mutableBytes)[brokenArchive.length/2]^=1;Check([brokenArchive writeToFile:archiveA options:0 error:NULL],@"corrupt stored archive fixture");NSDictionary *preflightStore=Tree(root),*preflightLive=Tree(data),*preflightFP=backend.fingerprint;NSArray *preflightKeys=backend.keychain;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&backend.calls.count==0,@"corrupt selected archive reached backend");Check([preflightStore isEqual:Tree(root)]&&[preflightLive isEqual:Tree(data)]&&[preflightFP isEqual:backend.fingerprint]&&[preflightKeys isEqual:backend.keychain],@"archive preflight failure mutated live/store state");Check([goodArchive writeToFile:archiveA options:0 error:NULL],@"repair stored archive fixture");
    if(!chflags(archiveA.fileSystemRepresentation,UF_IMMUTABLE)){Put(data,@"Documents/text",Bytes(@"fresh"));Reset(backend);NSDictionary *committed=[store backupBundle:BID metadata:nil error:&error];BOOL preserved=committed!=nil||[hashA isEqual:Digest(archiveA)];NSDirectoryEnumerator *cleanup=[NSFileManager.defaultManager enumeratorAtPath:root];NSString *name;while((name=[cleanup nextObject])){NSString *path=[root stringByAppendingPathComponent:name];struct stat info;if(!lstat(path.fileSystemRepresentation,&info)&&S_ISREG(info.st_mode))Check(!chflags(path.fileSystemRepresentation,0),@"clear immutable fixture flag");}Check(preserved,@"post-publication cleanup failure reported failed backup after clobbering old snapshot");}
    NSDictionary *originalTarget=backend.target;NSString *nestedRoot=[data stringByAppendingPathComponent:@"nested-store"];SHDWAppStateStore *nested=[[SHDWAppStateStore alloc]initWithRoot:nestedRoot backend:backend error:&error];Check(nested!=nil,@"nested private store fixture");NSDictionary *overlapBefore=Tree(data);Reset(backend);Check(![nested backupBundle:BID metadata:nil error:&error]&&![backend.calls containsObject:@"stop"],@"storage inside container allowed");Check([overlapBefore isEqual:Tree(data)],@"rejected storage overlap changed container");NSString *nestedContainer=[root stringByAppendingPathComponent:@"nested-container"];Mk(nestedContainer);NSMutableDictionary *badTarget=[originalTarget mutableCopy];badTarget[@"containers"]=@{@"data":nestedContainer};backend.target=badTarget;Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error]&&![backend.calls containsObject:@"stop"],@"container inside storage allowed");backend.target=originalTarget;
    puts("app-state store: IDFV updates, metadata, stop guards, atomic failure, malformed-live-fingerprint recovery and exact restoration passed");
}
static void Stress(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"stress-source"],*destination=[base stringByAppendingPathComponent:@"stress-destination"],*archive=[base stringByAppendingPathComponent:@"stress.tar.zst"];Mk(source);Mk(destination);for(NSUInteger i=0;i<2048;i++)Put(source,[NSString stringWithFormat:@"small/%04lu",(unsigned long)i],Bytes([NSString stringWithFormat:@"record-%lu",(unsigned long)i]));NSString *large=[source stringByAppendingPathComponent:@"large.bin"];int fd=open(large.fileSystemRepresentation,O_CREAT|O_WRONLY|O_TRUNC,0644);Check(fd>=0,@"open large fixture");unsigned char buffer[131072];uint32_t random=0x12345678;for(NSUInteger i=0;i<512;i++){for(NSUInteger j=0;j<sizeof(buffer);j++){random^=random<<13;random^=random>>17;random^=random<<5;buffer[j]=(unsigned char)random;}Check(write(fd,buffer,sizeof(buffer))==sizeof(buffer),@"write large fixture");}close(fd);struct rusage before,after;getrusage(RUSAGE_SELF,&before);__block NSUInteger events=0,chunkEvents=0;__block uint64_t greatest=0,largestChunk=0;NSMutableDictionary *phaseBytes=[NSMutableDictionary new];SHDWStateProgress progress=^(NSDictionary *event){events++;uint64_t current=[event[@"bytes"] unsignedLongLongValue];greatest=MAX(greatest,current);NSString *phase=event[@"phase"];uint64_t prior=[phaseBytes[phase] unsignedLongLongValue];if(current>=prior&&current>prior){largestChunk=MAX(largestChunk,current-prior);chunkEvents++;}phaseBytes[phase]=@(current);};NSError *error=nil;NSDictionary *info=[SHDWStateArchive captureRoots:@{@"containers/data":source} payloads:@{} toPath:archive progress:progress error:&error];Check(info!=nil,[NSString stringWithFormat:@"stress capture %@",error]);Check([SHDWStateArchive verifyPath:archive info:info progress:progress error:&error],@"stress archive verify");Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":destination} progress:progress error:&error],@"stress restore");Check([SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:progress error:&error],@"stress all-file verify");getrusage(RUSAGE_SELF,&after);Check([Digest(large)isEqual:Digest([destination stringByAppendingPathComponent:@"large.bin"])],@"large binary digest mismatch");Check([NSFileManager.defaultManager contentsOfDirectoryAtPath:[destination stringByAppendingPathComponent:@"small"] error:NULL].count==2048,@"many small files lost");Check(events>512&&chunkEvents>=512&&greatest>=64ULL*1024*1024,@"streaming byte progress missing");Check(largestChunk<=131072,@"archive progress omitted bounded chunk records");Check(after.ru_maxrss-before.ru_maxrss<48LL*1024*1024,@"streaming exceeded 48MiB RSS growth for 64MiB file");printf("app-state streaming: 2048 files +64MiB, %lu progress events, RSS growth %.1fMiB passed\n",(unsigned long)events,(after.ru_maxrss-before.ru_maxrss)/1048576.0);
}
int main(int argc,const char *argv[]){@autoreleasepool{Check(argc==3,@"fixture arguments");NSString *base=[NSString stringWithUTF8String:argv[1]];Mk(base);if(!strcmp(argv[2],"stress"))Stress(base);else{ArchiveTests(base);StateTests(base);}return 0;}}
'''


def archive_prefix():
    candidates = [os.environ.get("ARCHIVE_PREFIX"), "/opt/homebrew/opt/libarchive", "/usr/local/opt/libarchive"]
    for candidate in candidates:
        if candidate and (Path(candidate) / "include/archive.h").exists():
            return Path(candidate)
    raise SystemExit("Set ARCHIVE_PREFIX to a host libarchive build with zstd support")


def main():
    prefix = archive_prefix()
    sources = [ROOT / "src/AppState/Archive.m", ROOT / "src/AppState/State.m"]
    missing = [str(path) for path in sources if not path.exists()]
    if missing:
        raise SystemExit("Production sources not available yet: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix="shadow-app-state-test-") as directory:
        temp = Path(directory).resolve()
        harness = temp / "main.m"
        harness.write_text(HARNESS)
        common = ["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-g", "-O1", "-framework", "Foundation", "-I" + str(prefix / "include"), "-I" + str(ROOT / "src/AppState"), "-L" + str(prefix / "lib"), "-Wl,-rpath," + str(prefix / "lib"), str(harness), *map(str, sources), "-larchive", "-lzstd"]
        zstd = os.environ.get("ZSTD_PREFIX")
        if not zstd:
            zstd = next((candidate for candidate in ("/opt/homebrew/opt/zstd", "/usr/local/opt/zstd") if Path(candidate, "lib").is_dir()), None)
        if zstd:
            common += ["-L" + str(Path(zstd) / "lib"), "-Wl,-rpath," + str(Path(zstd) / "lib")]
        sanitized = temp / "sanitized"
        subprocess.run(common + ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-o", str(sanitized)], check=True)
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
        subprocess.run([str(sanitized), str(temp / "functional"), "functional"], env=environment, check=True)
        streaming = temp / "streaming"
        subprocess.run(common + ["-o", str(streaming)], check=True)
        subprocess.run([str(streaming), str(temp / "stress"), "stress"], check=True)


if __name__ == "__main__":
    main()
