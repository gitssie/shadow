#!/usr/bin/env python3
"""Exercise production app-state storage and streaming archives in isolated fixtures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HARNESS = r'''
#import "State.h"
#include <sys/file.h>
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
@property(nonatomic,strong) NSDictionary *preferences;
@property(nonatomic) BOOL corruptPreferencesRestore;
@property(nonatomic) BOOL failCurrentIdentifier;
@property(nonatomic,strong) NSMutableArray *calls;
@property(nonatomic) BOOL stopped;
@property(nonatomic) BOOL restarted;
@property(nonatomic) BOOL failCapture;
@property(nonatomic) BOOL failRestore;
@property(nonatomic) BOOL failFlush;
@property(nonatomic) BOOL failFingerprintCaptureAfterRestore;
@property(nonatomic) BOOL failFingerprintRestore;
@property(nonatomic,strong) NSArray *additionalPreferenceRecords;
@property(nonatomic,strong) NSDictionary *additionalPreferenceArtifacts;
@property(nonatomic,strong) NSString *additionalPreferenceLinkTarget;
@property(nonatomic,strong) NSDictionary *physicalPreferences;
@end
@implementation FakeBackend
- (NSDictionary *)resolveBundle:(NSString *)bundleID error:(NSError **)error { (void)error; [self.calls addObject:@"resolve"]; Check([bundleID isEqual:BID],@"invalid bundle reached backend"); return self.target; }
- (NSString *)currentVendorIdentifierForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;[self.calls addObject:@"current-vendor"];if(self.failCurrentIdentifier){if(error)*error=Problem(@"Cannot read current vendor identifier");return nil;}return self.fingerprint[@"data"][@"VendorIdentifier"] ?: @""; }
- (BOOL)stopTarget:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;[self.calls addObject:@"stop"];self.stopped=YES;return YES; }
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error { (void)target;[self.calls addObject:@"assert"];Check(self.stopped,@"assert before stop");if(self.restarted){if(error)*error=Problem(@"target restarted");return NO;}return YES; }
- (BOOL)flushPreferencesForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"flush before stop");[self.calls addObject:@"flush"];if(self.failFlush){if(error)*error=Problem(@"flush failed");return NO;}return YES; }
- (NSArray *)captureKeychainForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"keychain capture before stop");[self.calls addObject:@"capture-keychain"];if(self.failCapture){if(error)*error=Problem(@"capture failed");return nil;}return self.keychain; }
- (BOOL)validateKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error { if (![records isKindOfClass:NSArray.class]) return NO;for(NSDictionary *record in records)if(record[@"group"]&&![target[@"keychainGroups"] containsObject:record[@"group"]]){if(error)*error=Problem(@"Archived credential is outside current authorization");return NO;}return YES; }
- (BOOL)restoreKeychain:(NSArray *)records target:(NSDictionary *)target error:(NSError **)error { (void)target;Check(self.stopped,@"keychain restore before stop");[self.calls addObject:@"restore-keychain"];if(self.failRestore){if(error)*error=Problem(@"restore failed");return NO;}self.keychain=[records copy];return YES; }
- (NSDictionary *)capturePreferencesForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;[self.calls addObject:@"capture-preferences"];if(self.additionalPreferenceRecords&&[self.preferences[@"records"] isKindOfClass:NSArray.class]){NSMutableDictionary *result=[self.preferences mutableCopy];result[@"records"]=[self.preferences[@"records"] arrayByAddingObjectsFromArray:self.additionalPreferenceRecords];return result;}return self.preferences ?: @{}; }
- (BOOL)validatePreferences:(NSDictionary *)records target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;return [records isKindOfClass:NSDictionary.class]; }
- (BOOL)restorePreferences:(NSDictionary *)records target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;[self.calls addObject:@"restore-preferences"];for (NSString *path in self.physicalPreferences) Put(path.stringByDeletingLastPathComponent,path.lastPathComponent,[NSPropertyListSerialization dataWithPropertyList:self.physicalPreferences[path] format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL]);self.preferences=self.corruptPreferencesRestore ? @{@"corrupt":@YES} : [records copy];NSString *extra=target[@"containers"][@"scope-extension"];for(NSString *name in self.additionalPreferenceArtifacts)Put(extra,name,self.additionalPreferenceArtifacts[name]);if(self.additionalPreferenceLinkTarget){NSString *link=[extra stringByAppendingPathComponent:@"Library/Preferences/SDK Alias.plist"];Mk(link.stringByDeletingLastPathComponent);Check(!symlink(self.additionalPreferenceLinkTarget.fileSystemRepresentation,link.fileSystemRepresentation),@"extra preference link fixture");}return YES; }
- (NSDictionary *)captureFingerprintForTarget:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;Check(self.stopped,@"fingerprint capture before stop");[self.calls addObject:@"capture-fingerprint"];if(self.failFingerprintCaptureAfterRestore&&[self.calls containsObject:@"restore-fingerprint"]){if(error)*error=Problem(@"fingerprint readback interrupted");return nil;}return self.fingerprint; }
- (BOOL)validateFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;return [fingerprint[@"data"] isKindOfClass:NSDictionary.class]&&[fingerprint[@"configuration"] isKindOfClass:NSDictionary.class]; }
- (BOOL)restoreFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error { (void)target;(void)error;if(self.failFingerprintRestore){if(error)*error=Problem(@"fingerprint write failed");return NO;}Check(self.stopped,@"fingerprint restore before stop");[self.calls addObject:@"restore-fingerprint"];NSMutableDictionary *value=[fingerprint mutableCopy];value[@"locked"]=@YES;self.fingerprint=value;return YES; }
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
    for(NSDictionary *item in entries){struct archive_entry *entry=archive_entry_new();archive_entry_set_pathname(entry,[item[@"path"] UTF8String]);archive_entry_set_uid(entry,[item[@"uid"] intValue]);archive_entry_set_gid(entry,[item[@"gid"] intValue]);archive_entry_set_perm(entry,[item[@"mode"] intValue]);archive_entry_set_mtime(entry,0,0);archive_entry_set_birthtime(entry,[item[@"birthtime"] longLongValue],[item[@"birthtimeNsec"] longValue]);NSString *birth=[NSString stringWithFormat:@"%lld:%09ld",[item[@"birthtime"] longLongValue],[item[@"birthtimeNsec"] longValue]];archive_entry_xattr_add_entry(entry,"org.shadow.birthtime",birth.UTF8String,strlen(birth.UTF8String));NSString *type=item[@"type"];archive_entry_set_filetype(entry,[type isEqual:@"directory"]?AE_IFDIR:[type isEqual:@"symlink"]?AE_IFLNK:AE_IFREG);if([type isEqual:@"symlink"])archive_entry_set_symlink(entry,[item[@"target"] UTF8String]);if(item[@"hardlink"])archive_entry_set_hardlink_utf8(entry,[item[@"hardlink"] UTF8String]);if([type isEqual:@"file"])archive_entry_set_size(entry,item[@"hardlink"]?0:payload.length);Check(archive_write_header(writer,entry)==ARCHIVE_OK,@"fixture archive header");if([type isEqual:@"file"]&&!item[@"hardlink"])Check(archive_write_data(writer,payload.bytes,payload.length)==(la_ssize_t)payload.length,@"fixture archive data");archive_entry_free(entry);}
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
    NSString *changingArchive=[base stringByAppendingPathComponent:@"changing-dates.tar.zst"];NSString *changingFile=[source stringByAppendingPathComponent:@"Documents/text"];NSDictionary *unchangedDates=Times(changingFile);__block BOOL dateChanged=NO;SHDWStateProgress changeDate=^(NSDictionary *event){if(!dateChanged&&[event[@"phase"] isEqual:@"verify_archive"]){dateChanged=YES;SetBirth(changingFile,[unchangedDates[@"birthtime"] longLongValue]+20,[unchangedDates[@"birthtimeNsec"] longValue]);}};error=nil;NSDictionary *completedInfo=[SHDWStateArchive captureRoots:roots payloads:@{} toPath:changingArchive progress:changeDate error:&error];Check(completedInfo&&dateChanged,@"completed capture was rejected after source creation date changed");Check([SHDWStateArchive verifyPath:changingArchive info:completedInfo progress:nil error:&error],@"completed archive is independent of later source date changes");SetBirth(changingFile,[unchangedDates[@"birthtime"] longLongValue],[unchangedDates[@"birthtimeNsec"] longValue]);
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

static void RestoredMtimeTests(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"mtime-source"],*destination=[base stringByAppendingPathComponent:@"mtime-destination"],*archive=[base stringByAppendingPathComponent:@"mtime.tar.zst"];
    Mk(source);Mk(destination);Put(source,@"Documents/value",Bytes(@"value"));Put(source,@"Library/Caches/test.app/Cache.db-shm",Bytes(@"cache"));
    Check(!symlink("Documents/value",[source stringByAppendingPathComponent:@"alias"].fileSystemRepresentation),@"mtime symlink fixture");
    Check(!link([source stringByAppendingPathComponent:@"Documents/value"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"hardlink"].fileSystemRepresentation),@"mtime hardlink fixture");
    NSError *error=nil;NSDictionary *roots=@{@"containers/data":destination};
    NSDictionary *info=[SHDWStateArchive captureRoots:@{@"containers/data":source} payloads:@{} toPath:archive progress:nil error:&error];
    Check(info&&[SHDWStateArchive restorePath:archive info:info roots:roots progress:nil error:&error],@"restore mtime fixture");
    NSString *archiveSHA=Digest(archive);
    for(NSNumber *nsec in @[@0,@987654321]) {
        for(NSString *name in @[@"Documents/value",@"Library/Caches/test.app/Cache.db-shm",@"Documents",@"Library/Caches/test.app",@"alias",@"hardlink"]) {
            NSString *path=[destination stringByAppendingPathComponent:name];struct timespec dates[2]={{.tv_nsec=UTIME_OMIT},{.tv_sec=2000000000,.tv_nsec=nsec.longValue}};
            Check(!utimensat(AT_FDCWD,path.fileSystemRepresentation,dates,AT_SYMLINK_NOFOLLOW),@"change restored modification time only");
        }
        NSDictionary *before=Tree(destination);
        Check([SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],[NSString stringWithFormat:@"mtime-only differences blocked verification: %@",error]);
        Check([before isEqual:Tree(destination)]&&[archiveSHA isEqual:Digest(archive)],@"mtime verification rewrote destination or archive");
    }
    NSString *file=[destination stringByAppendingPathComponent:@"Documents/value"];struct stat original;Check(!lstat(file.fileSystemRepresentation,&original),@"mtime safety fixture stat");
    Check(!chmod(file.fileSystemRepresentation,(original.st_mode&07777)^S_IXUSR),@"change permission fixture");
    Check(![SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],@"mtime tolerance ignored permission mismatch");
    Check(!chmod(file.fileSystemRepresentation,original.st_mode&07777),@"restore permission fixture");
    NSDictionary *dates=Times(file);SetBirth(file,[dates[@"birthtime"]longLongValue]+1,[dates[@"birthtimeNsec"]longValue]);
    Check(![SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],@"mtime tolerance ignored creation mismatch");
    SetBirth(file,[dates[@"birthtime"]longLongValue],[dates[@"birthtimeNsec"]longValue]);
    Put(destination,@"Documents/value",Bytes(@"other"));
    Check(![SHDWStateArchive verifyRoots:roots info:info progress:nil error:&error],@"mtime tolerance ignored same-size content corruption");
    Check([SHDWStateArchive verifyPath:archive info:info progress:nil error:&error],@"mtime tolerance changed archive integrity");
    puts("restored mtime: seconds/nanoseconds tolerated for all entry types; no writes; permissions, creation dates and content remain strict passed");
}
static void HardlinkTests(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"hardlink-source"],*destination=[base stringByAppendingPathComponent:@"hardlink-destination"],*outside=[base stringByAppendingPathComponent:@"hardlink-outside"],*archive=[base stringByAppendingPathComponent:@"hardlinks.tar.zst"];
    Mk(source);Mk(destination);Mk(outside);Put(source,@"a",Bytes(@"linked content"));Mk([source stringByAppendingPathComponent:@"nested"]);
    Check(!link([source stringByAppendingPathComponent:@"a"].fileSystemRepresentation,[source stringByAppendingPathComponent:@"nested/b"].fileSystemRepresentation),@"create internal hardlink");
    Check(!link([source stringByAppendingPathComponent:@"a"].fileSystemRepresentation,[outside stringByAppendingPathComponent:@"external"].fileSystemRepresentation),@"create external hardlink");
    NSDictionary *outsideBefore=Tree(outside);NSError *error=nil;NSDictionary *roots=@{@"containers/data":source};
    NSDictionary *info=[SHDWStateArchive captureRoots:roots payloads:@{} toPath:archive progress:nil error:&error];Check(info!=nil,[NSString stringWithFormat:@"capture legitimate hardlinks: %@",error]);
    Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":destination} progress:nil error:&error],[NSString stringWithFormat:@"restore legitimate hardlinks: %@",error]);
    struct stat a,b;Check(!lstat([destination stringByAppendingPathComponent:@"a"].fileSystemRepresentation,&a)&&!lstat([destination stringByAppendingPathComponent:@"nested/b"].fileSystemRepresentation,&b)&&a.st_ino==b.st_ino&&a.st_dev==b.st_dev&&a.st_nlink==2,@"restored hardlink identity differs");
    Check([SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"hardlink restored recheck");Check([outsideBefore isEqual:Tree(outside)],@"external hardlink mutated");
    NSUInteger linkedEntries=0;for(NSDictionary *entry in info[@"entries"])if(entry[@"hardlink"]){linkedEntries++;Check([entry[@"hardlink"] isEqual:@"containers/data/a"],@"hardlink did not point to original content");}Check(linkedEntries==1,@"hardlink content was duplicated");
    NSString *alias=[destination stringByAppendingPathComponent:@"nested/b"];NSDictionary *dates=Times(alias);NSData *content=[NSData dataWithContentsOfFile:alias];Check(!unlink(alias.fileSystemRepresentation),@"break restored hardlink");Check([content writeToFile:alias options:0 error:NULL],@"replace hardlink with independent copy");SetBirth(alias,[dates[@"birthtime"] longLongValue],[dates[@"birthtimeNsec"] longValue]);struct timespec times[2]={{.tv_nsec=UTIME_OMIT},{.tv_sec=[dates[@"mtime"] longLongValue],.tv_nsec=[dates[@"mtimeNsec"] longValue]}};Check(!utimensat(AT_FDCWD,alias.fileSystemRepresentation,times,0),@"restore independent copy timestamps");Check(![SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:nil error:&error],@"independent copy passed hardlink identity verification");
    NSData *data=Bytes(@"fixture");NSString *root=@"containers/data",*original=@"containers/data/original",*linked=@"containers/data/linked";
    NSMutableDictionary *goodLink=[Entry(linked,@"file",data,nil) mutableCopy];goodLink[@"hardlink"]=original;
    NSArray *valid=@[Entry(root,@"directory",nil,nil),Entry(original,@"file",data,nil),goodLink];NSString *crafted=[base stringByAppendingPathComponent:@"hardlink-crafted.tar.zst"];MaliciousArchive(crafted,valid,data);Check([SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,valid) progress:nil error:&error],@"valid crafted hardlink rejected");
    NSArray *targets=@[@"../escape",@"/tmp/escape",@"containers/data/missing",linked,@"containers/data/symlink",@"payloads/private"];
    NSUInteger ordinal=0;for(NSString *target in targets){NSMutableDictionary *evilLink=[goodLink mutableCopy];evilLink[@"hardlink"]=target;NSArray *records=@[Entry(root,@"directory",nil,nil),Entry(original,@"file",data,nil),Entry(@"containers/data/symlink",@"symlink",nil,@"original"),Entry(@"payloads/private",@"file",data,nil),evilLink];NSString *evilArchive=[base stringByAppendingPathComponent:[NSString stringWithFormat:@"hardlink-evil-%lu.tar.zst",(unsigned long)ordinal++]];MaliciousArchive(evilArchive,records,data);NSDictionary *bad=RehashInfo(info,evilArchive,records);Check(![SHDWStateArchive verifyPath:evilArchive info:bad progress:nil error:&error],@"unsafe hardlink target accepted");Check(![SHDWStateArchive restorePath:evilArchive info:bad roots:@{@"containers/data":destination} progress:nil error:&error],@"unsafe hardlink extracted");}
    NSMutableDictionary *mismatch=[goodLink mutableCopy];mismatch[@"mode"]=@0600;NSArray *wrong=@[valid[0],valid[1],mismatch];MaliciousArchive(crafted,wrong,data);Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,wrong) progress:nil error:&error],@"hardlink metadata mismatch accepted");
    NSArray *forward=@[valid[0],goodLink,valid[1]];MaliciousArchive(crafted,forward,data);Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,forward) progress:nil error:&error],@"forward hardlink target accepted");
    NSMutableDictionary *chain=[goodLink mutableCopy];chain[@"path"]=@"containers/data/chained";chain[@"hardlink"]=linked;NSArray *chained=@[valid[0],valid[1],goodLink,chain];MaliciousArchive(crafted,chained,data);Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,chained) progress:nil error:&error],@"hardlink chain accepted");
    NSArray *wire=@[valid[0],valid[1],goodLink];MaliciousArchive(crafted,wire,data);NSMutableDictionary *manifestLink=[goodLink mutableCopy];manifestLink[@"hardlink"]=@"containers/data/different";NSArray *wireMismatch=@[valid[0],valid[1],Entry(@"containers/data/different",@"file",data,nil),manifestLink];Check(![SHDWStateArchive verifyPath:crafted info:RehashInfo(info,crafted,wireMismatch) progress:nil error:&error],@"archive hardlink disagreed with manifest but was accepted");
    Check([outsideBefore isEqual:Tree(outside)],@"hardlink adversarial fixtures modified external data");
    NSString *group=[base stringByAppendingPathComponent:@"hardlink-group"],*groupDestination=[base stringByAppendingPathComponent:@"hardlink-group-restored"],*dataDestination=[base stringByAppendingPathComponent:@"hardlink-data-restored"],*multiArchive=[base stringByAppendingPathComponent:@"hardlink-multi-root.tar.zst"];Mk(group);Mk(groupDestination);Mk(dataDestination);
    Check(!link([source stringByAppendingPathComponent:@"a"].fileSystemRepresentation,[group stringByAppendingPathComponent:@"shared"].fileSystemRepresentation),@"create cross-root hardlink");
    Put(source,@"external-only",Bytes(@"outside count"));Check(!link([source stringByAppendingPathComponent:@"external-only"].fileSystemRepresentation,[outside stringByAppendingPathComponent:@"second"].fileSystemRepresentation),@"create singly scoped hardlink");
    for(NSUInteger i=0;i<32;i++)Check(!link([source stringByAppendingPathComponent:@"a"].fileSystemRepresentation,[group stringByAppendingPathComponent:[NSString stringWithFormat:@"alias-%02lu",(unsigned long)i]].fileSystemRepresentation),@"create cache aliases");
    NSDictionary *multiRoots=@{@"containers/data":source,@"containers/groups/shared":group},*multiDestinations=@{@"containers/data":dataDestination,@"containers/groups/shared":groupDestination};NSDictionary *multi=[SHDWStateArchive captureRoots:multiRoots payloads:@{} toPath:multiArchive progress:nil error:&error];Check(multi!=nil,@"capture cross-root aliases");Check([SHDWStateArchive restorePath:multiArchive info:multi roots:multiDestinations progress:nil error:&error],@"restore cross-root aliases");
    Check(!lstat([dataDestination stringByAppendingPathComponent:@"a"].fileSystemRepresentation,&a)&&!lstat([groupDestination stringByAppendingPathComponent:@"shared"].fileSystemRepresentation,&b)&&a.st_dev==b.st_dev&&a.st_ino==b.st_ino&&a.st_nlink==35,@"cross-root aliases not preserved");Check(!lstat([dataDestination stringByAppendingPathComponent:@"external-only"].fileSystemRepresentation,&a)&&a.st_nlink==1,@"external-only source alias recreated outside scope");
    Check([SHDWStateArchive verifyRoots:multiDestinations info:multi progress:nil error:&error],@"multi-root hardlink final recheck");
    puts("app-state hardlinks: same inode, external scope isolation, copied-file detection and adversarial targets passed");
}

static NSString *SnapshotPath(NSString *root,NSString *idfv,NSString *name){return [[[[root stringByAppendingPathComponent:BID] stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:idfv] stringByAppendingPathComponent:name];}
static void Reset(FakeBackend *backend){backend.stopped=NO;[backend.calls removeAllObjects];}
static void CheckStorageOwner(NSString *root) {
    NSArray *paths = [@[@""] arrayByAddingObjectsFromArray:[NSFileManager.defaultManager subpathsOfDirectoryAtPath:root error:NULL]];
    for (NSString *name in paths) {
        struct stat info; NSString *path = name.length ? [root stringByAppendingPathComponent:name] : root;
        Check(!lstat(path.fileSystemRepresentation, &info), @"inspect backup owner");
        Check(info.st_uid == geteuid() && info.st_gid == getegid(), @"backup owner differs from configured storage authority");
        Check((info.st_mode & 07777) == (S_ISDIR(info.st_mode) ? 0700 : 0600), @"backup node permissions changed");
        Check(S_ISDIR(info.st_mode) || (S_ISREG(info.st_mode) && info.st_nlink == 1), @"unsafe backup node");
    }
}
static void CheckBusinessOwnership(SHDWAppStateStore *store, FakeBackend *backend, NSString *root) {
    NSError *error=nil;NSDictionary *oldFingerprint=backend.fingerprint;backend.fingerprint=FP(A,@"active-owner",YES);
    NSString *path=SnapshotPath(root,A,@"manifest.plist");NSData *original=[NSData dataWithContentsOfFile:path];
    NSString *dataSHA=Digest(SnapshotPath(root,A,@"data.tar.zst")),*stateSHA=Digest(SnapshotPath(root,A,@"state.tar.zst"));
    Check([[store ownershipBundle:BID idfv:A error:&error][@"owner"] isEqual:@"phone"],@"new backup must belong to phone");
    Check(![store claimBundle:BID idfv:A error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"active_environment"],@"active ownership claim accepted");
    NSMutableDictionary *legacy=[[NSDictionary dictionaryWithContentsOfFile:path]mutableCopy];[legacy removeObjectForKey:@"owner"];
    Check([[NSPropertyListSerialization dataWithPropertyList:legacy format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]writeToFile:path options:0 error:NULL],@"legacy owner fixture");
    NSData *legacyBytes=[NSData dataWithContentsOfFile:path];
    Check([[store ownershipBundle:BID idfv:A error:&error][@"owner"]isEqual:@"phone"]&&[legacyBytes isEqual:[NSData dataWithContentsOfFile:path]],@"legacy read rewrote metadata");
    backend.fingerprint=FP(B,@"ownership-other",NO);
    Check([[store claimBundle:BID idfv:A error:&error][@"owner"]isEqual:@"rv"],@"inactive claim failed");
    NSData *claimed=[NSData dataWithContentsOfFile:path];
    Check([store claimBundle:BID idfv:A error:&error]&&[claimed isEqual:[NSData dataWithContentsOfFile:path]],@"single-RV claim was not idempotent");
    Check(![store exportBundle:BID idfv:A part:@"manifest" expectedStateSHA:nil error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"ownership_conflict"],@"phone exported RV state");
    Check(![store recheckBundle:BID idfv:A error:&error],@"phone verified RV state");
    Check(![store editBundle:BID idfv:A metadata:@{@"title":@"blocked"} error:&error],@"phone edited RV backup");
    Check(![store deleteBundle:BID idfv:A error:&error],@"phone deleted RV backup");
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"phone restored RV backup");
    backend.fingerprint=FP(A,@"active-owner",YES);NSUInteger before=backend.calls.count;
    Check(![store backupBundle:BID metadata:nil error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"ownership_conflict"],@"phone overwrote RV backup");
    Check(![[backend.calls subarrayWithRange:NSMakeRange(before,backend.calls.count-before)]containsObject:@"stop"],@"blocked backup stopped active app");
    backend.fingerprint=FP(B,@"ownership-other",NO);store.requester=@"rv";
    NSDictionary *exported=[store exportBundle:BID idfv:A part:@"manifest" expectedStateSHA:nil error:&error];Check(exported!=nil,@"RV cannot export its manifest");
    NSDictionary *state=[store exportBundle:BID idfv:A part:@"state" expectedStateSHA:exported[@"stateSHA"] error:&error];Check(state!=nil,@"RV cannot export its state");
    Check([store recheckBundle:BID idfv:A error:&error],@"RV cannot verify its state");
    Check([store importBundle:BID idfv:A manifest:exported[@"data"] state:state[@"data"] expectedManifestSHA:exported[@"manifestSHA"] error:&error],@"RV cannot import its state");
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"RV bypassed return-before-restore rule");
    NSMutableDictionary *forged=[[NSPropertyListSerialization propertyListWithData:exported[@"data"] options:NSPropertyListMutableContainers format:NULL error:NULL]mutableCopy];forged[@"owner"]=@"phone";
    NSData *forgedBytes=[NSPropertyListSerialization dataWithPropertyList:forged format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    Check(![store importBundle:BID idfv:A manifest:forgedBytes state:state[@"data"] expectedManifestSHA:exported[@"manifestSHA"] error:&error],@"upload changed owner");
    Check([[store releaseBundle:BID idfv:A error:&error][@"owner"]isEqual:@"phone"],@"release failed");
    Check(![store exportBundle:BID idfv:A part:@"manifest" expectedStateSHA:nil error:&error],@"RV accessed returned state");
    store.requester=nil;Check([store recheckBundle:BID idfv:A error:&error],@"phone access not restored");
    Check([original writeToFile:path options:0 error:NULL],@"restore ownership fixture metadata");backend.fingerprint=oldFingerprint;
    Check([dataSHA isEqual:Digest(SnapshotPath(root,A,@"data.tar.zst"))]&&[stateSHA isEqual:Digest(SnapshotPath(root,A,@"state.tar.zst"))],@"ownership changed archive bytes");
    puts("app-state business ownership: active rejection, legacy defaults, RV exclusion, requester access, import protection and release passed");
}
static void RejectBeforeRestore(SHDWAppStateStore *store, FakeBackend *backend, NSString *root, NSString *data, NSString *group, NSString *message) {
    NSDictionary *stored=StoreTree(root),*live=Tree(data),*groups=Tree(group),*fingerprint=backend.fingerprint;NSArray *keys=backend.keychain;NSDictionary *preferences=backend.preferences;NSError *error=nil;
    Reset(backend);Check(![store recheckBundle:BID idfv:A error:&error],message);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&backend.calls.count==0,message);
    Check([stored isEqual:StoreTree(root)]&&[live isEqual:Tree(data)]&&[groups isEqual:Tree(group)]&&[fingerprint isEqual:backend.fingerprint]&&[keys isEqual:backend.keychain]&&[preferences isEqual:backend.preferences],@"invalid split snapshot mutated application or storage");
}
static void RejectSameEnvironment(SHDWAppStateStore *store, FakeBackend *backend, NSString *root, NSString *data, NSString *group) {
    NSDictionary *stored=StoreTree(root),*live=Tree(data),*groups=Tree(group),*fingerprint=backend.fingerprint,*preferences=backend.preferences;NSArray *keys=backend.keychain;
    for(NSNumber *save in @[@NO,@YES]) {
        NSError *error=nil;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:save.boolValue error:&error]&&error!=nil,@"same active IDFV restore was permitted");
        Check([error.userInfo[@"errorCode"]isEqual:(save.boolValue&&[NSFileManager.defaultManager fileExistsAtPath:[[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@"pending.plist"]]?@"restore_pending":@"active_environment")],@"active environment machine code");
        for(NSString *call in backend.calls)Check([@[@"resolve",@"current-vendor"] containsObject:call],@"same IDFV rejection stopped or mutated the application");
        Check([stored isEqual:StoreTree(root)]&&[live isEqual:Tree(data)]&&[groups isEqual:Tree(group)]&&[fingerprint isEqual:backend.fingerprint]&&[preferences isEqual:backend.preferences]&&[keys isEqual:backend.keychain],@"same IDFV rejection changed application data, preferences, keys or backup storage");
    }
}
static void ReinstallationTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"reinstall-store"],*oldData=[base stringByAppendingPathComponent:@"old-container-UUID"],*newData=[base stringByAppendingPathComponent:@"new-container-UUID"],*group=[base stringByAppendingPathComponent:@"new-owned-group"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private reinstall store");Mk(oldData);Mk(newData);Mk(group);
    Put(oldData,@"Documents/saved",Bytes(@"original archived data"));Put(oldData,MCM,Bytes(@"old registration"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.fingerprint=FP(A,@"archived",NO);backend.preferences=@{@"saved":Bytes(@"preferences")};backend.keychain=@[@{@"class":@"genp",@"group":@"TEAM.old",@"data":Bytes(@"credential")}];
    backend.target=@{@"bundleID":BID,@"token":@"old-installation",@"version":@"1.0",@"build":@"1",@"containers":@{@"data":oldData},@"keychainGroups":@[@"TEAM.old"]};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,@"create reinstall store");Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"capture legacy data-only snapshot");
    NSDictionary *savedData=ContentTree(oldData),*oldTree=Tree(oldData),*savedPreferences=backend.preferences;NSArray *savedKeys=backend.keychain;
    NSString *snapshot=SnapshotPath(root,A,@"manifest.plist");NSData *manifest=[NSData dataWithContentsOfFile:snapshot],*archive=[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"data.tar.zst")],*state=[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"state.tar.zst")];
    NSDictionary *current=@{@"bundleID":BID,@"token":@"new-installation",@"version":@"2.0",@"build":@"999",@"containers":@{@"data":newData,@"scope-group.lt.vinted.vinted":group},@"keychainGroups":@[@"TEAM.old",@"TEAM.new"]};backend.target=current;backend.fingerprint=FP(B,@"current",NO);backend.preferences=@{@"live":@YES};backend.keychain=@[@{@"class":@"genp",@"data":Bytes(@"live credential")}];Put(newData,MCM,Bytes(@"new registration"));Put(newData,@"Documents/live",Bytes(@"remove live data"));Put(group,MCM,Bytes(@"group registration"));Put(group,@"Library/old-user-data",Bytes(@"remove extra group data"));
    NSDictionary *beforeData=Tree(newData),*beforeGroup=Tree(group),*beforeStore=StoreTree(root),*beforePreferences=backend.preferences;NSArray *beforeKeys=backend.keychain;
    NSMutableDictionary *unauthorized=[current mutableCopy];unauthorized[@"keychainGroups"]=@[@"TEAM.new"];backend.target=unauthorized;Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&![backend.calls containsObject:@"restore-keychain"],@"out-of-scope archived credential bypassed current authorization");Check([beforeData isEqual:Tree(newData)]&&[beforeGroup isEqual:Tree(group)]&&[beforeStore isEqual:StoreTree(root)]&&[beforeKeys isEqual:backend.keychain]&&[beforePreferences isEqual:backend.preferences],@"credential authorization failure mutated current data or snapshot");backend.target=current;
    NSMutableDictionary *missing=[NSPropertyListSerialization propertyListWithData:manifest options:NSPropertyListMutableContainersAndLeaves format:NULL error:NULL];missing[@"roots"][@"containers/data"][@"containerID"]=@"missing-archived-group";Check([[NSPropertyListSerialization dataWithPropertyList:missing format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]writeToFile:snapshot atomically:YES],@"create missing destination manifest");Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&[error.localizedDescription containsString:@"missing-archived-group"]&&![backend.calls containsObject:@"stop"],@"missing archived destination was not rejected precisely before mutation");Check([beforeData isEqual:Tree(newData)]&&[beforeGroup isEqual:Tree(group)],@"missing destination cleared current files");Check([manifest writeToFile:snapshot atomically:YES],@"repair missing destination manifest");
    Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"restore old data-only snapshot after reinstall/update: %@",error]);
    Check([savedData isEqual:ContentTree(newData)]&&[ContentTree(group) count]==0,@"reinstallation failed to restore archived data or clear newly added group");Check([Get(newData,MCM)isEqual:Bytes(@"new registration")]&&[Get(group,MCM)isEqual:Bytes(@"group registration")],@"reinstallation changed live MCM metadata");Check([savedKeys isEqual:backend.keychain]&&[savedPreferences isEqual:backend.preferences]&&[backend.fingerprint[@"data"] isEqual:FP(A,@"archived",NO)[@"data"]]&&[backend.fingerprint[@"locked"] boolValue],@"reinstallation failed to restore logical state");
    Check([oldTree isEqual:Tree(oldData)]&&[manifest isEqual:[NSData dataWithContentsOfFile:snapshot]]&&[archive isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"data.tar.zst")]]&&[state isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"state.tar.zst")]],@"reinstallation changed original path or selected snapshot source");
    backend.fingerprint=FP(B,@"current-again",NO);store.progressHandler=^(NSDictionary *event){if([event[@"stage"]isEqual:@"recheck"])Put(group,@"unexpected",Bytes(@"post-restore residue"));};Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&[error.userInfo[@"stateMayBePartial"] boolValue],@"additional container residue passed final restore verification");
    store.progressHandler=nil;backend.fingerprint=FP(B,@"retry",NO);Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil&&[ContentTree(group) count]==0,@"retry failed to clear additional-container residue");
    puts("app-state reinstall/update container mapping: passed");
}
static void ResetBaselineArchiveTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"baseline-store"],*data=[base stringByAppendingPathComponent:@"baseline-live"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private baseline store");Mk(data);Put(data,@"Documents/value",Bytes(@"saved"));
    NSString *documents=[data stringByAppendingPathComponent:@"Documents"];
    SetBirth(documents,1000000000,123456789);NSDictionary *savedDates=Times(documents);
    NSDictionary *baseline=@{@"Version":@1,@"Containers":@{BID:@{@"Identity":[@"a" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0],@"Seconds":@999000000,@"Nanoseconds":@123456789}}};
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.keychain=@[];backend.preferences=@{};
    backend.target=@{@"bundleID":BID,@"token":@"baseline-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};
    NSMutableDictionary *saved=[FP(A,@"saved-baseline",NO) mutableCopy];saved[@"resetBaseline"]=baseline;backend.fingerprint=saved;
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,@"create reset baseline store");
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,[NSString stringWithFormat:@"backup optional baseline: %@",error]);
    NSString *statePath=SnapshotPath(root,A,@"state.tar.zst");NSData *oldState=[NSData dataWithContentsOfFile:statePath];
    backend.fingerprint=FP(B,@"current",NO);SetBirth(documents,1700000000,0);Put(data,@"Documents/value",Bytes(@"live"));Reset(backend);
    Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"restore optional baseline: %@",error]);
    Check([backend.fingerprint[@"resetBaseline"]isEqual:baseline],@"backup did not restore original reset baseline");
    Check(SameBirth(savedDates,Times(documents))&&[Get(data,@"Documents/value")isEqual:Bytes(@"saved")],@"baseline restore changed archived Documents time or content");
    Check([oldState isEqual:[NSData dataWithContentsOfFile:statePath]],@"restore rewrote saved baseline archive");
    backend.fingerprint=FP(C,@"legacy-without-baseline",NO);Reset(backend);
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"capture legacy identity without optional baseline");
    NSDictionary *legacyDates=Times(documents);backend.fingerprint=FP(B,@"live",NO);SetBirth(documents,1700000100,0);Reset(backend);
    Check([store restoreBundle:BID idfv:C saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"legacy backup baseline compatibility: %@",error]);
    Check(SameBirth(legacyDates,Times(documents)),@"legacy restore randomized Documents creation time");
    puts("app-state reset baseline: optional metadata roundtrip, old identity compatibility, preserved archive bytes and exact Documents creation time passed");
}
static void StatePreferenceReplayTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"replay-store"], *data=[base stringByAppendingPathComponent:@"replay-live"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private replay store");Mk(data);
    NSString *name=@"Library/Preferences/example.state.fixture.plist", *physical=[data stringByAppendingPathComponent:name];
    NSDictionary *old=@{@"token":@"old"}, *updated=@{@"token":@"updated",@"scope":@"read write"};
    Put(data,name,[NSPropertyListSerialization dataWithPropertyList:old format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]);
    Put(data,@"Documents/value",Bytes(@"alpha"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.fingerprint=FP(A,@"saved",NO);backend.preferences=@{@"version":@1,@"records":@[@{@"container":@"data",@"domain":BID,@"host":@"any",@"values":updated}]};backend.keychain=@[];
    backend.target=@{@"bundleID":BID,@"token":@"stable",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,@"create replay store");
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"capture independent data/state baseline");
    NSString *archive=SnapshotPath(root,A,@"data.tar.zst"), *sha=Digest(archive);
    backend.physicalPreferences=@{physical:updated};backend.fingerprint=FP(B,@"live",NO);
    __block BOOL corrupted=NO;
    store.progressHandler=^(NSDictionary *event){
        if(!corrupted && event[@"entries"] && [event[@"phase"]isEqual:@"restore"] && [backend.calls containsObject:@"restore-keychain"] && [Get(data,@"Documents/value")isEqual:Bytes(@"alpha")]) {
            ReplacePreservingMetadata(data,@"Documents/value",Bytes(@"bravo"));corrupted=YES;
        }
    };
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error] && corrupted && ![backend.calls containsObject:@"restore-preferences"],@"corrupt extracted data reached state replay before full raw verification");
    store.progressHandler=nil;Reset(backend);
    Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,[NSString stringWithFormat:@"updated state preference replay: %@",error]);
    Check([[NSDictionary dictionaryWithContentsOfFile:physical] isEqual:updated] && [sha isEqual:Digest(archive)],@"replay failed to install updated values with unchanged data archive");
    NSString *pending=[[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@"pending.plist"];
    NSDictionary *manifest=[NSDictionary dictionaryWithContentsOfFile:SnapshotPath(root,A,@"manifest.plist")];
    NSDictionary *interrupted=@{@"format":manifest[@"format"],@"bundleID":BID,@"idfv":A,@"archiveSHA":manifest[@"archiveInfo"][@"sha256"],@"stateArchiveSHA":manifest[@"stateArchiveInfo"][@"sha256"],@"date":NSDate.date,@"phase":@"identity-committed"};
    Check([interrupted writeToFile:pending atomically:NO] && !chmod(pending.fileSystemRepresentation,0600),@"simulate finalization interruption");
    NSDictionary *before=Tree(data);Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"unverifiable post-replay raw baseline passed finalization");
    Check([before isEqual:Tree(data)] && [NSFileManager.defaultManager fileExistsAtPath:pending],@"failed finalization changed data or dropped pending");
    for(NSString *call in backend.calls)Check(![call hasPrefix:@"restore-"],@"failed finalization replayed state");
    puts("app-state preference replay: immutable data, updated state and fail-closed post-replay finalization passed");
}

static void RestoreCurrentBackupTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"mandatory-save-store"],*data=[base stringByAppendingPathComponent:@"mandatory-save-live"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private mandatory-save store");Mk(data);Put(data,MCM,Bytes(@"metadata"));Put(data,@"Documents/account",Bytes(@"source A"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"mandatory-save-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"source",YES);backend.keychain=@[];backend.preferences=@{};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"mandatory-save source fixture");
    backend.fingerprint=FP(B,@"current",YES);Put(data,@"Documents/account",Bytes(@"old B"));
    Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"mandatory-save current fixture");
    Put(data,@"Documents/account",Bytes(@"latest B"));NSDictionary *live=Tree(data),*saved=StoreTree(root);Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"backup_required"]&&![error.userInfo[@"stateMayBePartial"]boolValue],@"restore skipped existing current backup");
    Check([live isEqual:Tree(data)]&&[saved isEqual:StoreTree(root)]&&![backend.calls containsObject:@"stop"],@"rejected restore mutated live data or backup");
    backend.failCapture=YES;Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error]&&![backend.calls containsObject:@"restore-keychain"]&&[live isEqual:Tree(data)]&&[saved isEqual:StoreTree(root)],@"failed mandatory backup allowed restoration");
    backend.failCapture=NO;
    Check([store restoreBundle:BID idfv:A saveCurrent:YES error:&error]!=nil&&[Get(data,@"Documents/account")isEqual:Bytes(@"source A")],@"mandatory backup blocked valid restoration");
    Check([store restoreBundle:BID idfv:B saveCurrent:YES error:&error]!=nil&&[Get(data,@"Documents/account")isEqual:Bytes(@"latest B")],@"mandatory backup did not preserve latest current data");
    puts("restore mandatory save: current snapshot requires backup, rejected/failed saves preserve live state, latest data retained passed");
}
static void DiscardResetTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"discard-store"],*data=[base stringByAppendingPathComponent:@"discard-live"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private discard store");Mk(data);Put(data,MCM,Bytes(@"metadata"));Put(data,@"Documents/account",Bytes(@"failed account"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"discard-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"failed",YES);backend.keychain=@[];backend.preferences=@{};backend.failCapture=YES;
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];
    __block NSUInteger resets=0;
    NSDictionary *(^reset)(NSDictionary *,NSError **)=^NSDictionary *(NSDictionary *target,NSError **failure){
        (void)target;(void)failure;resets++;
        Check(![NSFileManager.defaultManager fileExistsAtPath:SnapshotPath(root,A,@"manifest.plist")],@"discard created backup");
        NSError *busy=nil;Check(![store deleteBundle:BID idfv:A error:&busy]&&[busy.userInfo[@"errorCode"]isEqual:@"busy"],@"discard released exclusive lock before reset");
        backend.fingerprint=FP(B,@"cleaned",YES);return @{@"verified":@YES};
    };
    Check(![store discardAndResetBundle:BID expectedIDFV:B reset:reset error:&error]&&resets==0&&[error.userInfo[@"errorCode"]isEqual:@"idfv_mismatch"],@"discard ignored identity mismatch");
    NSDictionary *reply=[store discardAndResetBundle:BID expectedIDFV:A reset:reset error:&error];
    Check(reply&&resets==1&&[reply[@"previous_idfv"]isEqual:A]&&[reply[@"current_idfv"]isEqual:B]&&[reply[@"verified"]boolValue]&&[reply[@"reset"]boolValue]&&[reply[@"backup_created"]isEqual:@NO]&&!reply[@"backup_id"],@"discard failed without backup capture");
    Check([store catalogBundle:BID error:&error].count==0,@"discard published a snapshot");
    Check(![store discardAndResetBundle:BID expectedIDFV:B reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;*failure=Problem(@"discard reset failure");return nil;} error:&error]&&[error.userInfo[@"stateMayBePartial"]boolValue]&&!error.userInfo[@"backupIDFV"],@"discard failure lost partial-state semantics");
    Check(![store discardAndResetBundle:BID expectedIDFV:B reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;return @{@"verified":@YES};} error:&error],@"discard accepted unchanged fingerprint");
    Check([store catalogBundle:BID error:&error].count==0,@"failed discard created backup");
    backend.failCapture=NO;Check([store backupBundle:BID metadata:@{@"note":@"preserve"} error:&error]!=nil,@"discard existing archive fixture");
    NSString *beforeSHA=Digest(SnapshotPath(root,B,@"data.tar.zst"));
    NSString *beforeStateSHA=Digest(SnapshotPath(root,B,@"state.tar.zst")),*beforeManifestSHA=Digest(SnapshotPath(root,B,@"manifest.plist"));
    NSUInteger beforeResets=resets;
    NSDictionary *(^existingReset)(NSDictionary *,NSError **)=^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;resets++;backend.fingerprint=FP(A,@"new",YES);return @{@"verified":@YES};};
    reply=[store discardAndResetBundle:BID expectedIDFV:B reset:existingReset error:&error];
    Check(!reply&&[error.userInfo[@"errorCode"]isEqual:@"backup_required"]&&![error.userInfo[@"stateMayBePartial"]boolValue]&&resets==beforeResets,@"discard accepted backed-up current IDFV");
    Check([backend.fingerprint[@"data"][@"VendorIdentifier"]isEqual:B]&&[beforeSHA isEqual:Digest(SnapshotPath(root,B,@"data.tar.zst"))]&&[beforeStateSHA isEqual:Digest(SnapshotPath(root,B,@"state.tar.zst"))]&&[beforeManifestSHA isEqual:Digest(SnapshotPath(root,B,@"manifest.plist"))],@"rejected discard altered identity or existing backup");
    backend.fingerprint=FP(A,@"unsaved",YES);
    reply=[store discardAndResetBundle:BID expectedIDFV:A reset:reset error:&error];
    Check(reply&&resets==beforeResets+1&&[beforeSHA isEqual:Digest(SnapshotPath(root,B,@"data.tar.zst"))]&&[store recheckBundle:BID idfv:B error:&error],@"unrelated snapshot blocked discard or was altered");
    puts("discard/reset: identity guard, exclusive lock, existing-current rejection, unrelated snapshot preservation, no capture/archive, verified identity and partial failure passed");
}
static void BackupResetTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"reset-store"],*data=[base stringByAppendingPathComponent:@"reset-live"];
    Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private reset store");Mk(data);Put(data,MCM,Bytes(@"metadata"));Put(data,@"Documents/account",Bytes(@"original account"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"reset-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"before",YES);backend.keychain=@[];backend.preferences=@{};
    NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];
    __block NSUInteger resets=0;
    NSDictionary *(^reset)(NSDictionary *,NSError **)=^NSDictionary *(NSDictionary *target,NSError **failure){
        (void)target;(void)failure;resets++;
        Check([NSFileManager.defaultManager fileExistsAtPath:SnapshotPath(root,A,@"manifest.plist")],@"reset ran before backup publication");
        NSError *busy=nil;Check(![store deleteBundle:BID idfv:A error:&busy]&&[busy.userInfo[@"errorCode"]isEqual:@"busy"],@"backup lock was released before reset");
        backend.fingerprint=FP(B,@"after",YES);return @{@"verified":@YES};
    };
    Check(![store backupAndResetBundle:BID expectedIDFV:B reset:reset error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"idfv_mismatch"]&&resets==0,@"mismatched IDFV reached backup/reset");
    Check(![NSFileManager.defaultManager fileExistsAtPath:SnapshotPath(root,A,@"manifest.plist")],@"mismatched IDFV created a snapshot");
    backend.failCapture=YES;Check(![store backupAndResetBundle:BID expectedIDFV:A reset:reset error:&error]&&resets==0,@"backup failure reached reset");backend.failCapture=NO;
    Check([store backupAndResetBundle:BID expectedIDFV:A reset:reset error:&error]!=nil&&resets==1,@"verified backup/reset failed");
    Check([store recheckBundle:BID idfv:A error:&error],@"reset damaged its backup");
    NSDictionary *reply=nil;backend.fingerprint=FP(A,@"before again",YES);
    reply=[store backupAndResetBundle:BID expectedIDFV:A reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;*failure=Problem(@"reset failure");return nil;} error:&error];
    Check(!reply&&[error.userInfo[@"backupIDFV"]isEqual:A]&&[error.userInfo[@"stateMayBePartial"]boolValue],@"reset failure lost the saved recovery identity");
    Check([store recheckBundle:BID idfv:A error:&error],@"failed reset damaged its backup");
    backend.fingerprint=FP(A,@"before again",NO);
    NSString *originalSHA=Digest(SnapshotPath(root,A,@"data.tar.zst"));
    NSUInteger oldResets=resets;
    Check(![store backupAndResetBundle:BID expectedIDFV:A reset:reset error:&error]&&resets==oldResets&&[error.userInfo[@"errorCode"]isEqual:@"restore_pending"],@"reset retry overwrote its recovery backup");
    Check(![store discardAndResetBundle:BID expectedIDFV:A reset:reset error:&error]&&resets==oldResets&&[error.userInfo[@"errorCode"]isEqual:@"restore_pending"],@"discard ignored pending recovery");
    Check([originalSHA isEqual:Digest(SnapshotPath(root,A,@"data.tar.zst"))],@"reset retry changed its good archive");
    Put(data,@"Documents/partial",Bytes(@"partially cleaned state"));
    backend.failRestore=YES;Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"forced recovery failure succeeded");backend.failRestore=NO;
    backend.failFingerprintRestore=YES;
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"forced fingerprint recovery failure succeeded");
    NSDictionary *resetCatalog=[store catalogBundle:BID error:&error].firstObject;
    Check([resetCatalog[@"resetPending"]boolValue]&&![resetCatalog[@"finalizationPending"]boolValue],@"uncommitted fingerprint recovery became verification-only");
    backend.failFingerprintRestore=NO;
    Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,@"same-IDFV reset recovery could not retry a failed restore");
    Check(!Get(data,@"Documents/partial")&&[Get(data,@"Documents/account")isEqual:Bytes(@"original account")],@"reset recovery did not fully restore original data");
    backend.fingerprint=FP(A,@"same",YES);
    Check(![store backupAndResetBundle:BID expectedIDFV:A reset:^NSDictionary *(NSDictionary *target,NSError **failure){(void)target;(void)failure;return @{@"verified":@YES};} error:&error],@"unchanged fingerprint passed reset");
    Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,@"recover unchanged-fingerprint reset fixture");
    backend.fingerprint=FP(B,@"rv owner",YES);Check([store claimBundle:BID idfv:A error:&error]!=nil,@"claim reset fixture");backend.fingerprint=FP(A,@"owned current",YES);
    NSUInteger before=resets;Check(![store backupAndResetBundle:BID expectedIDFV:A reset:reset error:&error]&&resets==before&&[error.userInfo[@"errorCode"]isEqual:@"ownership_conflict"],@"RV ownership bypassed mandatory backup");
    Check(![store discardAndResetBundle:BID expectedIDFV:A reset:reset error:&error]&&resets==before&&[error.userInfo[@"errorCode"]isEqual:@"ownership_conflict"],@"discard bypassed RV ownership");
    puts("backup/reset: IDFV mismatch, mandatory backup, full-operation lock, retained recovery backup, changed fingerprint and ownership passed");
}
static void StateTests(NSString *base) {
    NSString *root=[base stringByAppendingPathComponent:@"store"],*data=[base stringByAppendingPathComponent:@"live"],*group=[base stringByAppendingPathComponent:@"live-group"],*other=[base stringByAppendingPathComponent:@"other-app"];Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private store fixture");Mk(data);Mk(group);Mk(other);Put(data,MCM,Bytes(@"MCM-original"));Put(data,@".com.apple.mobile_container_manager.acl.plist",Bytes(@"ACL-original"));Put(data,@"Documents/text",Bytes(@"alpha"));unsigned char raw[]={0,255,0,12,13};Put(data,@"Library/binary",[NSData dataWithBytes:raw length:sizeof(raw)]);Put(group,@"group-file",Bytes(@"group-alpha"));Put(other,@"untouched",Bytes(@"other application"));NSDictionary *otherBefore=Tree(other);
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.preferences=@{@"example.state.fixture":@{@"theme":@"alpha",@"binary":Bytes(@"prefs")}};backend.target=@{@"bundleID":BID,@"token":@"stable-fixture-token",@"version":@"1.0",@"build":@"42",@"containers":@{@"data":data,@"group.example.state":group},@"keychainGroups":@[@"TEAM.example.state.fixture"]};backend.fingerprint=FP(A,@"alpha",NO);backend.keychain=@[@{@"class":@"genp",@"data":[NSData dataWithBytes:raw length:sizeof(raw)],@"account":@"alpha"}];NSError *error=nil;SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store!=nil,[NSString stringWithFormat:@"create store: %@",error]);store.progressHandler=^(NSDictionary *event){NSString *phase=event[@"phase"];if([phase isEqual:@"capture"]||[phase isEqual:@"restore"])Check(backend.stopped,@"archive work before target stop");};
    NSMutableDictionary *withDigest=[backend.fingerprint mutableCopy];NSString *digest=[@"ab" stringByPaddingToLength:64 withString:@"ab" startingAtIndex:0];withDigest[@"digest"]=digest;backend.fingerprint=withDigest;
    NSDictionary *newPartial=[store backupBundle:BID metadata:@{@"note":@"initial-note"} error:&error];Check([newPartial[@"title"]length]==19&&[newPartial[@"note"]isEqual:@"initial-note"],@"new partial metadata must preserve timestamp-title baseline");
    NSDictionary *first=[store backupBundle:BID metadata:@{@"title":@"First",@"note":@"retained"} error:&error];Check(first!=nil,[NSString stringWithFormat:@"first backup: %@",error]);CheckStorageOwner(root);
    Check(![store recheckBundle:BID idfv:@"bad" error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"invalid_request"],@"invalid identity machine code");
    Check(![store recheckBundle:BID idfv:B error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"snapshot_unavailable"],@"missing snapshot machine code");
    int busyLock=open([[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@".lock"].fileSystemRepresentation,O_RDWR);Check(busyLock>=0&&!flock(busyLock,LOCK_EX|LOCK_NB),@"hold real app operation lock");
    Check(![store catalogBundle:BID error:&error]&&[error.userInfo[@"errorCode"]isEqual:@"busy"],@"real lock contention machine code");flock(busyLock,LOCK_UN);close(busyLock);
    NSDictionary *noteOnly=[store backupBundle:BID metadata:@{@"note":@"changed-note"} error:&error];Check([noteOnly[@"title"]isEqual:@"First"]&&[noteOnly[@"note"]isEqual:@"changed-note"],@"partial note lost existing title");
    NSDictionary *titleOnly=[store backupBundle:BID metadata:@{@"title":@"changed-title"} error:&error];Check([titleOnly[@"title"]isEqual:@"changed-title"]&&[titleOnly[@"note"]isEqual:@"changed-note"],@"partial title lost existing note");
    Check([store backupBundle:BID metadata:@{@"title":@"First",@"note":@"retained"} error:&error]!=nil,@"restore original metadata fixture");
    NSUInteger transferCalls=backend.calls.count;
    NSDictionary *exportedManifest=[store exportBundle:BID idfv:A part:@"manifest" expectedStateSHA:nil error:&error];Check(exportedManifest!=nil,@"export manifest");
    NSDictionary *exportedState=[store exportBundle:BID idfv:A part:@"state" expectedStateSHA:exportedManifest[@"stateSHA"] error:&error];Check(exportedState!=nil,@"export consistent state");
    NSDictionary *transferBefore=StoreTree(root);Check(![store exportBundle:BID idfv:A part:@"state" expectedStateSHA:@"stale" error:&error],@"reject stale export");
    Check(![store importBundle:BID idfv:A manifest:exportedManifest[@"data"] state:exportedState[@"data"] expectedManifestSHA:@"0000000000000000000000000000000000000000000000000000000000000000" error:&error],@"reject stale import");
    Check([transferBefore isEqual:StoreTree(root)],@"stale import changed snapshot");
    Check([store importBundle:BID idfv:A manifest:exportedManifest[@"data"] state:exportedState[@"data"] expectedManifestSHA:exportedManifest[@"manifestSHA"] error:&error],[NSString stringWithFormat:@"atomic import %@",error]);
    Check([exportedManifest[@"data"] isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"manifest.plist")]] && [exportedState[@"data"] isEqual:[NSData dataWithContentsOfFile:SnapshotPath(root,A,@"state.tar.zst")]],@"same-content import changed snapshot bytes");
    transferBefore=StoreTree(root);
    NSMutableDictionary *wrongManifest=[[NSPropertyListSerialization propertyListWithData:exportedManifest[@"data"] options:NSPropertyListMutableContainers format:NULL error:NULL]mutableCopy];wrongManifest[@"bundleID"]=@"other.fixture.app";
    NSData *wrongBytes=[NSPropertyListSerialization dataWithPropertyList:wrongManifest format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    Check(![store importBundle:BID idfv:A manifest:wrongBytes state:exportedState[@"data"] expectedManifestSHA:exportedManifest[@"manifestSHA"] error:&error],@"unexpected import identity accepted");
    Check(backend.calls.count==transferCalls,@"transfers touched live backend");
    NSString *absentRoot=[base stringByAppendingPathComponent:@"absent-readonly-store"];
    Check(![[SHDWAppStateStore alloc]initWithRoot:absentRoot ownerUID:geteuid() ownerGID:getegid() backend:backend readOnly:YES error:&error]&&![NSFileManager.defaultManager fileExistsAtPath:absentRoot],@"read-only store initialization created storage");

    Check(![store importBundle:BID idfv:A manifest:exportedManifest[@"data"] state:[@"corrupt" dataUsingEncoding:NSUTF8StringEncoding] expectedManifestSHA:exportedManifest[@"manifestSHA"] error:&error],@"reject corrupt state import");Check([error.userInfo[@"errorCode"]isEqual:@"invalid_archive"],@"archive verification machine code");
    Check([transferBefore isEqual:StoreTree(root)],@"corrupt import damaged published snapshot");

    SHDWAppStateStore *explicitOwner=[[SHDWAppStateStore alloc]initWithRoot:root ownerUID:geteuid() ownerGID:getegid() backend:backend error:&error];Check(explicitOwner!=nil&&[explicitOwner recheckBundle:BID idfv:A error:&error],@"explicit storage owner cannot read snapshot");
    NSDictionary *ownerBefore=StoreTree(root);Check(![[SHDWAppStateStore alloc]initWithRoot:root ownerUID:geteuid()+10000 ownerGID:getegid() backend:backend error:&error],@"foreign storage authority accepted");Check([ownerBefore isEqual:StoreTree(root)],@"foreign owner initialization changed stored data");Check([backend.calls containsObject:@"stop"],@"backup did not stop target");NSArray *firstCatalog=[store catalogBundle:BID error:&error];Check(firstCatalog.count==1,[NSString stringWithFormat:@"first catalog count=%lu error=%@",(unsigned long)firstCatalog.count,error]);Check([first[@"digest"] isEqual:digest]&&[firstCatalog[0][@"digest"] isEqual:digest],@"archived fingerprint digest not retained in catalog");
    NSString *firstArchive=SnapshotPath(root,A,@"data.tar.zst"), *firstManifest=SnapshotPath(root,A,@"manifest.plist");
    NSData *safeArchive=[NSData dataWithContentsOfFile:firstArchive], *safeManifest=[NSData dataWithContentsOfFile:firstManifest];
    NSDictionary *safeManifestValue=[NSPropertyListSerialization propertyListWithData:safeManifest options:NSPropertyListImmutable format:NULL error:NULL];
    store.progressHandler=nil;
    NSString *firstState=SnapshotPath(root,A,@"state.tar.zst");NSData *safeState=[NSData dataWithContentsOfFile:firstState];
    CheckBusinessOwnership(store,backend,root);
    Check([safeManifestValue[@"format"] isEqual:@"ShadowAppState2"]&&safeState.length>0,@"backup did not publish split archive format");
    Check([safeManifestValue[@"archiveInfo"][@"payloads"] count]==0&&[safeManifestValue[@"stateArchiveInfo"][@"sourceRoots"] count]==0,@"split archives mix container roots and state payloads");
    for(NSDictionary *entry in safeManifestValue[@"archiveInfo"][@"entries"])Check([entry[@"path"] hasPrefix:@"containers/"],@"application archive contains state payloads");
    NSSet *stateNames=[NSSet setWithArray:[safeManifestValue[@"stateArchiveInfo"][@"entries"] valueForKey:@"path"]];Check([stateNames isEqual:[NSSet setWithArray:@[@"identity/state.plist",@"keychain/records.plist",@"preferences/records.plist"]]],@"state archive does not contain exact identity/keychain/preferences payloads");
    Check(!unlink(firstState.fileSystemRepresentation),@"remove state package fixture");RejectBeforeRestore(store,backend,root,data,group,@"missing state archive accepted");Check([safeState writeToFile:firstState options:0 error:NULL],@"repair missing state archive");Check(!chmod(firstState.fileSystemRepresentation,0600),@"restore state archive mode");
    NSMutableData *badState=[safeState mutableCopy];((unsigned char *)badState.mutableBytes)[badState.length/2]^=1;Check([badState writeToFile:firstState options:0 error:NULL],@"corrupt state package fixture");RejectBeforeRestore(store,backend,root,data,group,@"corrupt state archive accepted");Check([safeState writeToFile:firstState options:0 error:NULL],@"repair corrupt state archive");
    NSDictionary *statePayloads=[SHDWStateArchive readPayloadsAtPath:firstState info:safeManifestValue[@"stateArchiveInfo"] names:@[@"identity/state.plist",@"keychain/records.plist",@"preferences/records.plist"] error:&error];Check(statePayloads!=nil,@"read standalone state package");
    NSMutableDictionary *obsolete=[safeManifestValue mutableCopy];obsolete[@"format"]=@"ShadowAppState1";NSData *obsoleteManifest=[NSPropertyListSerialization dataWithPropertyList:obsolete format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];Check([obsoleteManifest writeToFile:firstManifest options:0 error:NULL],@"install unsupported format fixture");RejectBeforeRestore(store,backend,root,data,group,@"unsupported old snapshot format accepted");Check([safeManifest writeToFile:firstManifest options:0 error:NULL],@"restore current snapshot format");
    for (NSDictionary *override in @[@{@"uid":@(geteuid()+1)},@{@"gid":@(getegid()+1)},@{@"gid":@0},@{@"mode":@04755},@{@"mode":@02755}]) {
        NSMutableArray *records=[NSMutableArray new];for(NSString *prefix in safeManifestValue[@"archiveInfo"][@"sourceRoots"]) [records addObject:Entry(prefix,@"directory",nil,nil)];
        NSMutableDictionary *entry=[Entry(@"containers/data/payload",@"file",Bytes(@"x"),nil) mutableCopy];[entry addEntriesFromDictionary:override];[records addObject:entry];
        MaliciousArchive(firstArchive,records,Bytes(@"x"));NSDictionary *forgedInfo=RehashInfo(safeManifestValue[@"archiveInfo"],firstArchive,records);
        Check([SHDWStateArchive verifyPath:firstArchive info:forgedInfo progress:nil error:&error],@"crafted ownership fixture is not a self-consistent archive");
        NSMutableDictionary *forged=[safeManifestValue mutableCopy];forged[@"archiveInfo"]=forgedInfo;NSData *encoded=[NSPropertyListSerialization dataWithPropertyList:forged format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];Check([encoded writeToFile:firstManifest options:0 error:NULL],@"write forged manifest");
        NSDictionary *live=ContentTree(data);Reset(backend);
        if (override[@"mode"]) Check(![store recheckBundle:BID idfv:A error:&error]&&![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&backend.calls.count==0,@"mobile-managed archive allowed SUID/SGID");
        else Check([store recheckBundle:BID idfv:A error:&error],@"archive rejected source ownership differing from backup storage");
        Check([live isEqual:ContentTree(data)],@"ownership preflight touched live data");CheckStorageOwner(root);
    }
    Check([safeArchive writeToFile:firstArchive options:0 error:NULL]&&[safeManifest writeToFile:firstManifest options:0 error:NULL],@"restore safe ownership fixture");
    NSString *sourceFile=[data stringByAppendingPathComponent:@"Documents/text"];Check(!chmod(sourceFile.fileSystemRepresentation,04755),@"set unsupported source permissions");Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"backup published unsupported source permissions");Check([safeArchive isEqual:[NSData dataWithContentsOfFile:firstArchive]],@"rejected unsafe capture changed snapshot");Check(!chmod(sourceFile.fileSystemRepresentation,0644),@"restore source permissions");
    Put(data,@"Documents/text",Bytes(@"bravo"));Reset(backend);Check([store backupBundle:BID metadata:nil error:&error]!=nil,@"same IDFV update");NSArray *catalog=[store catalogBundle:BID error:&error];Check(catalog.count==1,@"same IDFV created duplicate");Check([catalog[0][@"title"] isEqual:@"First"]&&[catalog[0][@"note"] isEqual:@"retained"],@"update lost metadata");NSDictionary *savedData=ContentTree(data),*savedGroup=ContentTree(group),*savedFP=backend.fingerprint,*savedPreferences=backend.preferences;NSArray *savedKeys=backend.keychain;NSString *archiveA=SnapshotPath(root,A,@"data.tar.zst"),*hashA=Digest(archiveA),*stateA=SnapshotPath(root,A,@"state.tar.zst"),*stateHashA=Digest(stateA);
    Put(data,@"Documents/text",Bytes(@"failed"));__block BOOL interrupted=NO;store.progressHandler=^(NSDictionary *event){if([event[@"bytes"] unsignedLongLongValue]>0){interrupted=YES;backend.restarted=YES;}};Reset(backend);NSDictionary *beforeInterrupted=StoreTree(root);Check(![store backupBundle:BID metadata:nil error:&error]&&interrupted,@"mid-archive restart did not fail backup");backend.restarted=NO;store.progressHandler=nil;Check([hashA isEqual:Digest(archiveA)]&&[stateHashA isEqual:Digest(stateA)]&&[beforeInterrupted isEqual:StoreTree(root)],@"mid-archive failure clobbered old snapshot or retained staging");
    backend.failCapture=YES;Put(data,@"Documents/text",Bytes(@"failed"));Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"failed capture reported success");Check([hashA isEqual:Digest(archiveA)]&&[stateHashA isEqual:Digest(stateA)],@"failed backup clobbered old snapshot");backend.failCapture=NO;backend.fingerprint=FP(B,@"beta",NO);backend.preferences=@{@"example.state.fixture":@{@"theme":@"beta"}};backend.keychain=@[@{@"class":@"genp",@"account":@"beta",@"data":Bytes(@"beta")}];Put(data,@"Documents/text",Bytes(@"charl"));Reset(backend);Check([store backupBundle:BID metadata:@{@"title":@"Second",@"note":@"beta"} error:&error]!=nil,@"second IDFV backup");Check([store catalogBundle:BID error:&error].count==2,@"unique IDFV catalog");Check([store editBundle:BID idfv:A metadata:@{@"title":@"Edited",@"note":@"retained-edit"} error:&error],@"edit snapshot metadata");
    NSString *manifestA=SnapshotPath(root,A,@"manifest.plist");NSData *savedManifestA=[NSData dataWithContentsOfFile:manifestA],*savedStateA=[NSData dataWithContentsOfFile:stateA];NSDictionary *valueA=[NSPropertyListSerialization propertyListWithData:savedManifestA options:NSPropertyListImmutable format:NULL error:NULL];NSDictionary *valueB=[NSDictionary dictionaryWithContentsOfFile:SnapshotPath(root,B,@"manifest.plist")];NSMutableDictionary *swapped=[valueA mutableCopy];swapped[@"stateArchiveInfo"]=valueB[@"stateArchiveInfo"];NSData *swappedManifest=[NSPropertyListSerialization dataWithPropertyList:swapped format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];Check([[NSData dataWithContentsOfFile:SnapshotPath(root,B,@"state.tar.zst")] writeToFile:stateA options:0 error:NULL]&&[swappedManifest writeToFile:manifestA options:0 error:NULL],@"swap valid foreign-IDFV state package");RejectBeforeRestore(store,backend,root,data,group,@"foreign IDFV state archive accepted with matching hash metadata");Check([savedStateA writeToFile:stateA options:0 error:NULL]&&[savedManifestA writeToFile:manifestA options:0 error:NULL],@"restore state package after swap");
    NSDictionary *readOnlyBefore=Tree(root);Reset(backend);Check([store catalogBundle:BID error:&error]!=nil&&[store recheckBundle:BID idfv:A error:&error],@"readonly catalog/recheck");Check(backend.calls.count==0&&[readOnlyBefore isEqual:Tree(root)],@"catalog/recheck mutated store or backend");
    { NSDictionary *untouched=StoreTree(root),*live=Tree(data),*liveGroup=Tree(group),*fp=backend.fingerprint,*prefs=backend.preferences;NSArray *keys=backend.keychain;backend.failCurrentIdentifier=YES;Reset(backend);NSError *identityError=nil;Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&identityError]&&[identityError.domain isEqual:@"fixture"]&&identityError.code==77,@"unreadable current IDFV allowed restore");for(NSString *call in backend.calls)Check([@[@"resolve",@"current-vendor"] containsObject:call],@"IDFV read failure stopped or modified the application");Check([untouched isEqual:StoreTree(root)]&&[live isEqual:Tree(data)]&&[liveGroup isEqual:Tree(group)]&&[fp isEqual:backend.fingerprint]&&[prefs isEqual:backend.preferences]&&[keys isEqual:backend.keychain],@"IDFV read failure modified environment or backups");backend.failCurrentIdentifier=NO; }
    Put(data,MCM,Bytes(@"MCM-live"));Put(data,@".com.apple.mobile_container_manager.acl.plist",Bytes(@"ACL-live"));NSDictionary *liveRootDates=HistoricalTimes(data,1200000000),*liveGroupRootDates=HistoricalTimes(group,1200000100),*liveMCMDates=Times([data stringByAppendingPathComponent:MCM]),*liveACLDates=Times([data stringByAppendingPathComponent:@".com.apple.mobile_container_manager.acl.plist"]);Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:YES error:&error]!=nil,[NSString stringWithFormat:@"restore selected snapshot: %@",error]);Check([ContentTree(data) isEqual:savedData]&&[ContentTree(group) isEqual:savedGroup],@"restored full file set differs");Check([Get(data,MCM)isEqual:Bytes(@"MCM-live")]&&[Get(data,@".com.apple.mobile_container_manager.acl.plist")isEqual:Bytes(@"ACL-live")],@"restore replaced MCM registration metadata");Check(SameBirth(liveRootDates,Times(data))&&SameBirth(liveGroupRootDates,Times(group))&&[liveMCMDates isEqual:Times([data stringByAppendingPathComponent:MCM])]&&[liveACLDates isEqual:Times([data stringByAppendingPathComponent:@".com.apple.mobile_container_manager.acl.plist"])],@"restore changed container-root creation or MCM/ACL dates");Check([backend.keychain isEqual:savedKeys],@"restored keychain differs");Check([backend.preferences isEqual:savedPreferences],@"restored iOS preferences differ");Check([backend.fingerprint[@"data"] isEqual:savedFP[@"data"]]&&[backend.fingerprint[@"configuration"] isEqual:savedFP[@"configuration"]]&&[backend.fingerprint[@"locked"] boolValue],@"fingerprint data/configuration/lock not restored together");Check([otherBefore isEqual:Tree(other)],@"restore changed another application");Check([hashA isEqual:Digest(archiveA)],@"restore clobbered selected source");
    Put(data,@"Documents/new-session-data",Bytes(@"accumulated after snapshot"));Put(group,@"new-session-data",Bytes(@"group accumulated after snapshot"));backend.preferences=@{@"new-session":@YES};backend.keychain=@[@{@"account":@"new-session"}];RejectSameEnvironment(store,backend,root,data,group);
    NSDictionary *liveBefore=Tree(data),*sameStore=Tree(root);
    backend.fingerprint=FP(C,@"gamma",NO);backend.failCapture=YES;Put(data,@"Documents/text",Bytes(@"current-unsaved"));liveBefore=Tree(data);sameStore=Tree(root);Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error],@"save-current failure allowed restore");Check([liveBefore isEqual:Tree(data)]&&[sameStore isEqual:Tree(root)],@"save-current failure wrote store or live files");backend.failCapture=NO;
    for(NSString *badID in @[@"../escape",@"not-a-uuid",@"",@"11111111/1111-4111-8111-111111111111"]){sameStore=Tree(root);Check(![store restoreBundle:BID idfv:badID saveCurrent:NO error:&error]&&![store deleteBundle:BID idfv:badID error:&error]&&![store editBundle:BID idfv:badID metadata:@{@"title":@"bad",@"note":@""} error:&error]&&![store recheckBundle:BID idfv:badID error:&error],@"invalid IDFV accepted");Check([sameStore isEqual:Tree(root)],@"invalid IDFV changed store");}
    sameStore=Tree(root);Reset(backend);Check(![store backupBundle:@"../escape" metadata:nil error:&error],@"bundle traversal accepted");Check(backend.calls.count==0&&[sameStore isEqual:Tree(root)],@"invalid bundle reached backend or filesystem");backend.fingerprint=FP(@"not-a-uuid",@"invalid",NO);Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"invalid live IDFV accepted");
    backend.fingerprint=FP(C,@"gamma",NO);backend.restarted=YES;liveBefore=Tree(data);Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"restarted target restore succeeded");Check([liveBefore isEqual:Tree(data)],@"target restart failure modified live files");backend.restarted=NO;
    backend.failRestore=YES;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"partial restore reported success");NSString *pending=[[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@"pending.plist"];Check([NSFileManager.defaultManager fileExistsAtPath:pending],@"partial restore lost pending state");CheckStorageOwner(root);sameStore=Tree(root);Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error],@"backup allowed while pending");Check(![store deleteBundle:BID idfv:A error:&error]&&![store editBundle:BID idfv:A metadata:@{@"title":@"bad",@"note":@""} error:&error],@"pending source was mutable");Check([error.userInfo[@"errorCode"]isEqual:@"restore_pending"],@"pending machine code");Check(![store importBundle:BID idfv:A manifest:[NSData dataWithContentsOfFile:manifestA] state:[NSData dataWithContentsOfFile:stateA] expectedManifestSHA:Digest(manifestA) error:&error],@"pending source import was allowed");Check(![store restoreBundle:BID idfv:A saveCurrent:YES error:&error],@"pending retry auto-saved over source");Check([sameStore isEqual:Tree(root)],@"pending protection changed archive/store");Check([store recheckBundle:BID idfv:A error:&error]&&[store catalogBundle:BID error:&error]!=nil,@"pending readonly inspection failed");NSData *pendingState=[NSData dataWithContentsOfFile:stateA],*pendingManifest=[NSData dataWithContentsOfFile:manifestA];NSDictionary *pendingValue=[NSPropertyListSerialization propertyListWithData:pendingManifest options:NSPropertyListImmutable format:NULL error:NULL];NSDictionary *pendingPayloads=[SHDWStateArchive readPayloadsAtPath:stateA info:pendingValue[@"stateArchiveInfo"] names:@[@"identity/state.plist",@"keychain/records.plist",@"preferences/records.plist"] error:&error];NSMutableDictionary *changedPayloads=[pendingPayloads mutableCopy];changedPayloads[@"keychain/records.plist"]=[NSPropertyListSerialization dataWithPropertyList:@[@{@"class":@"genp",@"account":@"changed"}] format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];NSString *replacementState=[base stringByAppendingPathComponent:@"replacement-state.tar.zst"];NSDictionary *replacementInfo=[SHDWStateArchive captureRoots:@{} payloads:changedPayloads toPath:replacementState progress:nil error:&error];Check(replacementInfo!=nil,@"capture replacement state package");NSMutableDictionary *replacementManifest=[pendingValue mutableCopy];replacementManifest[@"stateArchiveInfo"]=replacementInfo;NSData *replacementMetadata=[NSPropertyListSerialization dataWithPropertyList:replacementManifest format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];Check([[NSData dataWithContentsOfFile:replacementState] writeToFile:stateA options:0 error:NULL]&&[replacementMetadata writeToFile:manifestA options:0 error:NULL],@"replace pending state with valid changed archive");Check([store recheckBundle:BID idfv:A error:&error],@"replacement state fixture is invalid independently of pending pin");Reset(backend);NSDictionary *pendingLive=Tree(data);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&backend.calls.count==0&&[pendingLive isEqual:Tree(data)],@"pending retry accepted different state archive");Check([pendingState writeToFile:stateA options:0 error:NULL]&&[pendingManifest writeToFile:manifestA options:0 error:NULL],@"restore pinned state source");backend.failRestore=NO;backend.fingerprint=@{};backend.corruptPreferencesRestore=YES;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&[backend.calls containsObject:@"restore-preferences"]&&[NSFileManager.defaultManager fileExistsAtPath:pending],@"incorrect restored preferences passed final recheck");Check(![backend.calls containsObject:@"restore-fingerprint"],@"fingerprint committed before preference verification");backend.corruptPreferencesRestore=NO;backend.fingerprint=FP(A,@"manual-same-IDFV",YES);RejectSameEnvironment(store,backend,root,data,group);backend.fingerprint=FP(B,@"different-current-environment",NO);Reset(backend);Check([store restoreBundle:BID idfv:A saveCurrent:NO error:&error]!=nil,@"pending restore retry failed");Check(![NSFileManager.defaultManager fileExistsAtPath:pending],@"successful retry retained pending state");Check([hashA isEqual:Digest(archiveA)]&&[otherBefore isEqual:Tree(other)],@"pending retry changed source/other app");
    NSData *goodArchive=[NSData dataWithContentsOfFile:archiveA];NSMutableData *brokenArchive=[goodArchive mutableCopy];((unsigned char *)brokenArchive.mutableBytes)[brokenArchive.length/2]^=1;Check([brokenArchive writeToFile:archiveA options:0 error:NULL],@"corrupt stored archive fixture");NSDictionary *preflightStore=Tree(root),*preflightLive=Tree(data),*preflightFP=backend.fingerprint;NSArray *preflightKeys=backend.keychain;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&backend.calls.count==0,@"corrupt selected archive reached backend");Check([preflightStore isEqual:Tree(root)]&&[preflightLive isEqual:Tree(data)]&&[preflightFP isEqual:backend.fingerprint]&&[preflightKeys isEqual:backend.keychain],@"archive preflight failure mutated live/store state");Check([goodArchive writeToFile:archiveA options:0 error:NULL],@"repair stored archive fixture");
    if(!chflags(archiveA.fileSystemRepresentation,UF_IMMUTABLE)){Put(data,@"Documents/text",Bytes(@"fresh"));Reset(backend);NSDictionary *committed=[store backupBundle:BID metadata:nil error:&error];BOOL preserved=committed!=nil||[hashA isEqual:Digest(archiveA)];NSDirectoryEnumerator *cleanup=[NSFileManager.defaultManager enumeratorAtPath:root];NSString *name;while((name=[cleanup nextObject])){NSString *path=[root stringByAppendingPathComponent:name];struct stat info;if(!lstat(path.fileSystemRepresentation,&info)&&S_ISREG(info.st_mode))Check(!chflags(path.fileSystemRepresentation,0),@"clear immutable fixture flag");}Check(preserved,@"post-publication cleanup failure reported failed backup after clobbering old snapshot");}
    NSDictionary *originalTarget=backend.target;NSString *nestedRoot=[data stringByAppendingPathComponent:@"nested-store"];SHDWAppStateStore *nested=[[SHDWAppStateStore alloc]initWithRoot:nestedRoot backend:backend error:&error];Check(nested!=nil,@"nested private store fixture");NSDictionary *overlapBefore=Tree(data);Reset(backend);Check(![nested backupBundle:BID metadata:nil error:&error]&&![backend.calls containsObject:@"stop"],@"storage inside container allowed");Check([overlapBefore isEqual:Tree(data)],@"rejected storage overlap changed container");NSString *nestedContainer=[root stringByAppendingPathComponent:@"nested-container"];Mk(nestedContainer);NSMutableDictionary *badTarget=[originalTarget mutableCopy];badTarget[@"containers"]=@{@"data":nestedContainer};backend.target=badTarget;Reset(backend);Check(![store backupBundle:BID metadata:nil error:&error]&&![backend.calls containsObject:@"stop"],@"container inside storage allowed");backend.target=originalTarget;
    NSString *manifestPath=SnapshotPath(root,A,@"manifest.plist"),*linked=[base stringByAppendingPathComponent:@"outside-manifest-link"];
    Check(!link(manifestPath.fileSystemRepresentation,linked.fileSystemRepresentation),@"create hard-linked manifest fixture");
    Check(![store recheckBundle:BID idfv:A error:&error],@"hard-linked stored metadata accepted");Check(!unlink(linked.fileSystemRepresentation),@"remove manifest link");
    Check(!link(archiveA.fileSystemRepresentation,linked.fileSystemRepresentation),@"create hard-linked archive fixture");
    Check(![store recheckBundle:BID idfv:A error:&error],@"hard-linked archive accepted");Check(!unlink(linked.fileSystemRepresentation),@"remove archive link");
    Check(!link(stateA.fileSystemRepresentation,linked.fileSystemRepresentation),@"create hard-linked state archive fixture");Check(![store recheckBundle:BID idfv:A error:&error],@"hard-linked state archive accepted");Check(!unlink(linked.fileSystemRepresentation),@"remove state archive link");
    NSString *savedStatePath=[base stringByAppendingPathComponent:@"saved-state-package"];Check(!rename(stateA.fileSystemRepresentation,savedStatePath.fileSystemRepresentation)&&!symlink(savedStatePath.fileSystemRepresentation,stateA.fileSystemRepresentation),@"create state archive symlink fixture");RejectBeforeRestore(store,backend,root,data,group,@"symbolic state archive accepted");Check(!unlink(stateA.fileSystemRepresentation)&&!rename(savedStatePath.fileSystemRepresentation,stateA.fileSystemRepresentation),@"restore state archive after symlink fixture");
    puts("app-state split snapshots: independent packages, missing/corrupt/swapped state rejection, pending state pin, obsolete format rejection, preferences final verification and atomic preservation passed");
    puts("app-state store: IDFV updates, metadata, stop guards, atomic failure, malformed-live-fingerprint recovery and exact restoration passed");
}
static void RecoveryAndCatalogTests(NSString *base) {
    NSString *data=[base stringByAppendingPathComponent:@"recovery-data"],*extra=[base stringByAppendingPathComponent:@"recovery-extension"],*root=[base stringByAppendingPathComponent:@"recovery-store"];
    Mk(data);Mk(extra);Mk(root);Check(!chmod(root.fileSystemRepresentation,0700),@"private recovery store");Put(data,@"Documents/content",Bytes(@"archived"));Put(data,MCM,Bytes(@"registration"));
    FakeBackend *backend=[FakeBackend new];backend.calls=[NSMutableArray new];backend.target=@{@"bundleID":BID,@"token":@"recovery-install",@"version":@"1",@"build":@"1",@"containers":@{@"data":data},@"keychainGroups":@[]};backend.fingerprint=FP(A,@"saved",NO);backend.keychain=@[@{@"account":@"saved"}];
    backend.preferences=@{@"version":@1,@"records":@[@{@"container":@"data",@"domain":BID,@"host":@"any",@"values":@{@"saved":@YES}}]};NSError *error=nil;
    SHDWAppStateStore *store=[[SHDWAppStateStore alloc]initWithRoot:root backend:backend error:&error];Check(store&&[store backupBundle:BID metadata:nil error:&error],@"capture recovery snapshot");
    NSDictionary *savedData=ContentTree(data),*savedPrefs=backend.preferences;NSArray *savedKeys=backend.keychain;NSString *hashA=Digest(SnapshotPath(root,A,@"data.tar.zst"));
    backend.additionalPreferenceRecords=@[@{@"container":@"",@"domain":@"example.state.fixture.new-extension",@"host":@"any",@"values":@{}},@{@"container":@"",@"domain":@"example.state.fixture.new-extension",@"host":@"current",@"values":@{}}];
    NSMutableDictionary *updated=[backend.target mutableCopy];updated[@"containers"]=@{@"data":data,@"scope-extension":extra};updated[@"token"]=@"updated-install";backend.target=updated;Put(extra,@"stale",Bytes(@"remove"));
    NSData *emptyPreference=[NSPropertyListSerialization dataWithPropertyList:@{} format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
    NSData *nonemptyPreference=[NSPropertyListSerialization dataWithPropertyList:@{@"stale":@YES} format:NSPropertyListXMLFormat_v1_0 options:0 error:NULL];
    backend.fingerprint=FP(B,@"current",NO);backend.preferences=@{@"current":@YES};backend.keychain=@[@{@"account":@"current"}];
    for(NSDictionary *artifacts in @[@{@"Library/Preferences/SDK Custom.plist":nonemptyPreference},@{@"Library/Preferences/SDK Custom.plist":Bytes(@"invalid plist")},@{@"Library/other.plist":emptyPreference}]){
        backend.additionalPreferenceArtifacts=artifacts;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&![backend.calls containsObject:@"restore-fingerprint"],@"unexpected extra container data passed verification");
    }
    NSString *outsideEmpty=[base stringByAppendingPathComponent:@"outside-empty-preference.plist"];Check([emptyPreference writeToFile:outsideEmpty atomically:NO],@"outside preference fixture");
    backend.additionalPreferenceArtifacts=nil;backend.additionalPreferenceLinkTarget=outsideEmpty;Reset(backend);Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&![backend.calls containsObject:@"restore-fingerprint"],@"extra preference symlink was followed");backend.additionalPreferenceLinkTarget=nil;
    backend.additionalPreferenceArtifacts=@{@"Library/Preferences/SDK Custom.plist":emptyPreference,@"Library/Preferences/ByHost/SDK 中文.11111111-1111-4111-8111-111111111111.plist":emptyPreference};
    backend.failFingerprintCaptureAfterRestore=YES;Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error]&&[backend.fingerprint[@"data"][@"VendorIdentifier"] isEqual:A],@"late identity verification failure fixture");
    Check([ContentTree(data) isEqual:savedData]&&[backend.preferences isEqual:savedPrefs]&&[backend.keychain isEqual:savedKeys],@"data was not verified before identity commit");
    NSString *pending=[[root stringByAppendingPathComponent:BID]stringByAppendingPathComponent:@"pending.plist"];NSDictionary *state=[NSDictionary dictionaryWithContentsOfFile:pending];Check([state[@"phase"] isEqual:@"identity-committed"],@"late failure lost committed phase");
    NSArray *catalog=[store catalogBundle:BID error:&error];Check(catalog.count==1&&[catalog[0][@"finalizationPending"] boolValue],@"catalog did not expose finalization-only recovery");
    backend.failFingerprintCaptureAfterRestore=NO;backend.keychain=@[@{@"account":@"changed after identity commit"}];NSDictionary *beforeFiles=Tree(data),*beforePrefs=backend.preferences,*beforeFP=backend.fingerprint;NSArray *beforeKeys=backend.keychain;Reset(backend);
    Check(![store restoreBundle:BID idfv:A saveCurrent:NO error:&error],@"finalization overwrote changed same-IDFV environment");
    for(NSString *call in backend.calls)Check(![call hasPrefix:@"restore-"],@"finalization attempted application state restoration");
    Check([beforeFiles isEqual:Tree(data)]&&[beforePrefs isEqual:backend.preferences]&&[beforeFP isEqual:backend.fingerprint]&&[beforeKeys isEqual:backend.keychain]&&[NSFileManager.defaultManager fileExistsAtPath:pending],@"failed finalization changed current state or lost pending");
    backend.keychain=savedKeys;NSMutableDictionary *interrupted=[state mutableCopy];interrupted[@"phase"]=@"identity-pending";Check([interrupted writeToFile:pending atomically:NO],@"simulate interruption after identity commit");Check(!chmod(pending.fileSystemRepresentation,0600),@"secure pending fixture");Reset(backend);
    NSDictionary *finished=[store restoreBundle:BID idfv:A saveCurrent:NO error:&error];Check([finished[@"finalized"] boolValue]&&![NSFileManager.defaultManager fileExistsAtPath:pending],@"committed identity could not finish verification");
    for(NSString *call in backend.calls)Check(![call hasPrefix:@"restore-"],@"successful finalization replayed restoration");
    Check([hashA isEqual:Digest(SnapshotPath(root,A,@"data.tar.zst"))]&&[ContentTree(data) isEqual:savedData],@"finalization changed source archive or live files");
    backend.fingerprint=FP(B,@"second",NO);backend.additionalPreferenceRecords=nil;Check([store backupBundle:BID metadata:nil error:&error],@"capture healthy second snapshot");
    NSData *deletionMetadata=Get(SnapshotPath(root,A,@""),@"manifest.plist");NSString *healthyHash=Digest(SnapshotPath(root,B,@"data.tar.zst"));Put(SnapshotPath(root,A,@""),@"manifest.plist",Bytes(@"truncated manifest"));
    catalog=[store catalogBundle:BID error:&error];Check(catalog.count==2,@"corrupt entry hid healthy backups");NSUInteger unavailable=0;for(NSDictionary *item in catalog)if([item[@"unavailable"] boolValue]){unavailable++;Check([item[@"idfv"] isEqual:A]&&[item[@"error"] length],@"corrupt entry lost identity or diagnostic");}Check(unavailable==1,@"corrupt backup not represented individually");
    Check(![store deleteBundle:BID idfv:A error:&error],@"unreadable ownership permitted deletion");
    Put(SnapshotPath(root,A,@""),@"manifest.plist",deletionMetadata);
    Check([store deleteBundle:BID idfv:A error:&error],@"repaired ownership prevented safe snapshot deletion");Check([[store catalogBundle:BID error:&error] count]==1&&[healthyHash isEqual:Digest(SnapshotPath(root,B,@"data.tar.zst"))],@"corrupt deletion damaged healthy backup");
    NSString *healthyArchive=SnapshotPath(root,B,@"data.tar.zst");Check(!chflags(healthyArchive.fileSystemRepresentation,UF_IMMUTABLE),@"make interrupted deletion fixture");
    Check([store deleteBundle:BID idfv:B error:&error]&&[[store catalogBundle:BID error:&error] count]==0,@"failed physical cleanup left published broken backup");
    NSString *appRoot=[root stringByAppendingPathComponent:BID];NSArray *children=[NSFileManager.defaultManager contentsOfDirectoryAtPath:appRoot error:NULL];NSUInteger tombstones=0;
    for(NSString *name in children)if([name hasPrefix:@".delete-"]){tombstones++;NSString *archive=[[appRoot stringByAppendingPathComponent:name]stringByAppendingPathComponent:@"data.tar.zst"];Check(!chflags(archive.fileSystemRepresentation,0),@"release deletion failure fixture");}
    Check(tombstones==1,@"interrupted deletion lost deferred cleanup record");backend.fingerprint=FP(C,@"third",NO);Check([store backupBundle:BID metadata:nil error:&error],@"new backup blocked by unpublished deletion");
    for(NSString *name in [NSFileManager.defaultManager contentsOfDirectoryAtPath:appRoot error:NULL])Check(![name hasPrefix:@".delete-"],@"next writer did not reclaim deletion tombstone");
    puts("app-state recovery: pre-identity verification, same-IDFV verify-only finalization, new empty extension scopes/artifacts, invalid/nonempty/symlink extra data rejection, corrupt-entry isolation and atomic/deferred deletion passed");
}
static void Stress(NSString *base) {
    NSString *source=[base stringByAppendingPathComponent:@"stress-source"],*destination=[base stringByAppendingPathComponent:@"stress-destination"],*archive=[base stringByAppendingPathComponent:@"stress.tar.zst"];Mk(source);Mk(destination);for(NSUInteger i=0;i<2048;i++)Put(source,[NSString stringWithFormat:@"small/%04lu",(unsigned long)i],Bytes([NSString stringWithFormat:@"record-%lu",(unsigned long)i]));NSString *large=[source stringByAppendingPathComponent:@"large.bin"];int fd=open(large.fileSystemRepresentation,O_CREAT|O_WRONLY|O_TRUNC,0644);Check(fd>=0,@"open large fixture");unsigned char buffer[131072];uint32_t random=0x12345678;for(NSUInteger i=0;i<512;i++){for(NSUInteger j=0;j<sizeof(buffer);j++){random^=random<<13;random^=random>>17;random^=random<<5;buffer[j]=(unsigned char)random;}Check(write(fd,buffer,sizeof(buffer))==sizeof(buffer),@"write large fixture");}close(fd);struct rusage before,after;getrusage(RUSAGE_SELF,&before);__block NSUInteger events=0,chunkEvents=0;__block uint64_t greatest=0,largestChunk=0;NSMutableDictionary *phaseBytes=[NSMutableDictionary new];SHDWStateProgress progress=^(NSDictionary *event){events++;uint64_t current=[event[@"bytes"] unsignedLongLongValue];greatest=MAX(greatest,current);NSString *phase=event[@"phase"];uint64_t prior=[phaseBytes[phase] unsignedLongLongValue];if(current>=prior&&current>prior){largestChunk=MAX(largestChunk,current-prior);chunkEvents++;}phaseBytes[phase]=@(current);};NSError *error=nil;NSDictionary *info=[SHDWStateArchive captureRoots:@{@"containers/data":source} payloads:@{} toPath:archive progress:progress error:&error];Check(info!=nil,[NSString stringWithFormat:@"stress capture %@",error]);Check([SHDWStateArchive verifyPath:archive info:info progress:progress error:&error],@"stress archive verify");Check([SHDWStateArchive restorePath:archive info:info roots:@{@"containers/data":destination} progress:progress error:&error],@"stress restore");Check([SHDWStateArchive verifyRoots:@{@"containers/data":destination} info:info progress:progress error:&error],@"stress all-file verify");getrusage(RUSAGE_SELF,&after);Check([Digest(large)isEqual:Digest([destination stringByAppendingPathComponent:@"large.bin"])],@"large binary digest mismatch");Check([NSFileManager.defaultManager contentsOfDirectoryAtPath:[destination stringByAppendingPathComponent:@"small"] error:NULL].count==2048,@"many small files lost");Check(events>512&&chunkEvents>=512&&greatest>=64ULL*1024*1024,@"streaming byte progress missing");Check(largestChunk<=131072,@"archive progress omitted bounded chunk records");Check(after.ru_maxrss-before.ru_maxrss<48LL*1024*1024,@"streaming exceeded 48MiB RSS growth for 64MiB file");printf("app-state streaming: 2048 files +64MiB, %lu progress events, RSS growth %.1fMiB passed\n",(unsigned long)events,(after.ru_maxrss-before.ru_maxrss)/1048576.0);
}
int main(int argc,const char *argv[]){@autoreleasepool{Check(argc==3,@"fixture arguments");NSString *base=[NSString stringWithUTF8String:argv[1]];Mk(base);if(!strcmp(argv[2],"stress"))Stress(base);else{ArchiveTests(base);RestoredMtimeTests(base);ResetBaselineArchiveTests(base);BackupResetTests(base);RestoreCurrentBackupTests(base);DiscardResetTests(base);StatePreferenceReplayTests(base);HardlinkTests(base);ReinstallationTests(base);StateTests(base);RecoveryAndCatalogTests(base);}return 0;}}
'''


OWNERSHIP_HARNESS = r'''#import "State.h"
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
static NSMutableSet *adopted;
static uid_t fixtureUID;
static gid_t fixtureGID;
static NSString *NodeKey(struct stat *st) { return [NSString stringWithFormat:@"%llu:%llu", (unsigned long long)st->st_dev, (unsigned long long)st->st_ino]; }
static void ReportOwner(struct stat *st) { st->st_uid = [adopted containsObject:NodeKey(st)] ? fixtureUID : 0; st->st_gid = fixtureGID; }
static int OwnerStat(int fd, struct stat *st) { int result = fstat(fd, st); if (!result) ReportOwner(st); return result; }
static int OwnerStatAt(int fd, const char *name, struct stat *st, int flags) { int result = fstatat(fd, name, st, flags); if (!result) ReportOwner(st); return result; }
static int OwnerChange(int fd, uid_t uid, gid_t gid) { struct stat st; if (fstat(fd, &st)) return -1; if (uid != fixtureUID || gid != fixtureGID) { errno = EPERM; return -1; } [adopted addObject:NodeKey(&st)]; return 0; }
static uid_t RootAuthority(void) { return 0; }
static BOOL FailCode(NSError **error,NSString *code,NSString *message) { if(error)*error=[NSError errorWithDomain:@"fixture" code:1 userInfo:@{NSLocalizedDescriptionKey:message,@"errorCode":code}];return NO;}
static BOOL Fail(NSError **error, NSString *message) { if (error) *error=[NSError errorWithDomain:@"fixture" code:1 userInfo:@{NSLocalizedDescriptionKey:message}]; return NO; }
static BOOL POSIXFail(NSError **error, NSString *message) { return Fail(error,message); }
static BOOL BundleValue(NSString *value) { return [value isEqual:@"example.app"]; }
static void Check(BOOL value, NSString *message) { if (!value) { fprintf(stderr,"FAIL ownership: %s\n",message.UTF8String); exit(1); } }
#define fstat OwnerStat
#define fstatat OwnerStatAt
#define fchown OwnerChange
#define geteuid RootAuthority
#include "ownership.inc"
#undef fstat
#undef fstatat
#undef fchown
#undef geteuid
int main(int argc, const char **argv) { @autoreleasepool {
    Check(argc == 2,@"arguments"); fixtureUID=geteuid(); fixtureGID=getegid(); adopted=[NSMutableSet new];
    NSString *base=@(argv[1]); Check(!mkdir(base.fileSystemRepresentation,0700),@"root fixture");
    int root=open(base.fileSystemRepresentation,O_RDONLY|O_DIRECTORY); Check(root>=0,@"open root fixture");
    Check(!mkdirat(root,"example.app",0700),@"app fixture");int app=openat(root,"example.app",O_RDONLY|O_DIRECTORY);
    int lock=openat(app,".lock",O_RDWR|O_CREAT|O_EXCL,0600);Check(lock>=0,@"lock fixture");
    Check(!mkdirat(app,"snapshots",0700),@"snapshots fixture");int snapshots=openat(app,"snapshots",O_RDONLY|O_DIRECTORY);
    int archive=openat(snapshots,"data.tar.zst",O_WRONLY|O_CREAT|O_EXCL,0600);Check(archive>=0&&write(archive,"unchanged",9)==9,@"archive fixture");close(archive);
    NSError *error=nil;Check(!flock(lock,LOCK_EX|LOCK_NB),@"hold app lock");Check(!MigrateStorage(root,fixtureUID,fixtureGID,&error)&&adopted.count==0,@"migration ignored active operation");flock(lock,LOCK_UN);
    Check(!symlinkat("/tmp",snapshots,"unsafe"),@"symlink fixture");Check(!MigrateStorage(root,fixtureUID,fixtureGID,&error),@"migration followed symbolic link");Check(!unlinkat(snapshots,"unsafe",0),@"remove symlink");[adopted removeAllObjects];
    Check(!linkat(snapshots,"data.tar.zst",app,"linked-archive",0),@"hardlink fixture");Check(!MigrateStorage(root,fixtureUID,fixtureGID,&error),@"migration accepted multiply-linked data");Check(!unlinkat(app,"linked-archive",0),@"remove hardlink");[adopted removeAllObjects];
    Check(!mkfifoat(snapshots,"unsafe",0600),@"fifo fixture");Check(!MigrateStorage(root,fixtureUID,fixtureGID,&error),@"migration accepted special node");Check(!unlinkat(snapshots,"unsafe",0),@"remove fifo");[adopted removeAllObjects];
    struct stat st;Check(!fstat(root,&st),@"inspect root");st.st_uid=12345;Check(!LegacyNode(st,YES,fixtureGID)&&!PrivateNode(st,YES,fixtureUID,fixtureGID),@"foreign owner accepted");
    Check(MigrateStorage(root,fixtureUID,fixtureGID,&error),[NSString stringWithFormat:@"migrate ownership: %@",error]);Check(adopted.count==5,@"migration did not cover root/app/lock/snapshots/archive");
    NSUInteger count=adopted.count;Check(MigrateStorage(root,fixtureUID,fixtureGID,&error)&&adopted.count==count,@"migrated tree was not fast path");
    archive=openat(snapshots,"data.tar.zst",O_RDONLY);char bytes[9];Check(archive>=0&&read(archive,bytes,9)==9&&!memcmp(bytes,"unchanged",9),@"migration changed archive data");close(archive);close(lock);close(snapshots);close(app);close(root);
    puts("app-state ownership: descriptor migration, locked operations, symbolic/hard links, special nodes, foreign owners, unchanged archive bytes and fast path passed (UID syscall double)");
} return 0; }
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
        ownership = temp / "ownership.m"
        ownership.write_text(OWNERSHIP_HARNESS)
        production = (ROOT / "src/AppState/State.m").read_text()
        ownership_start = production.index("static BOOL PrivateNode(")
        ownership_end = production.index("static BOOL Overlaps(", ownership_start)
        (temp / "ownership.inc").write_text(production[ownership_start:ownership_end])
        owner_binary = temp / "ownership"
        subprocess.run(["xcrun", "--sdk", "macosx", "clang", "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-g", "-O1", "-framework", "Foundation", "-I" + str(ROOT / "src/AppState"), str(ownership), "-fsanitize=address,undefined", "-o", str(owner_binary)], check=True)
        subprocess.run([str(owner_binary), str(temp / "ownership-fixture")], env=environment, check=True)
        streaming = temp / "streaming"
        subprocess.run(common + ["-o", str(streaming)], check=True)
        subprocess.run([str(streaming), str(temp / "stress"), "stress"], check=True)


if __name__ == "__main__":
    main()
