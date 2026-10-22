#import "State.h"
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <dirent.h>
#include <errno.h>
#include <stdio.h>

NSString *const SHDWAppStateErrorDomain = @"me.jjolano.shadow.app-state";
static NSString *const StateFormat = @"ShadowAppState1";
static NSString *const IdentityPayload = @"identity/state.plist";
static NSString *const KeychainPayload = @"keychain/records.plist";
static NSUInteger const MaximumPlistSize = 64 * 1024 * 1024;
static NSUInteger const MaximumPayloadSize = 16 * 1024 * 1024;

static BOOL Fail(NSError **error, NSString *message) {
    if (error) *error = [NSError errorWithDomain:SHDWAppStateErrorDomain code:1 userInfo:@{NSLocalizedDescriptionKey: message}];
    return NO;
}
static BOOL POSIXFail(NSError **error, NSString *message) {
    int saved = errno;
    if (error) *error = [NSError errorWithDomain:SHDWAppStateErrorDomain code:2 userInfo:@{NSLocalizedDescriptionKey: message, NSUnderlyingErrorKey:[NSError errorWithDomain:NSPOSIXErrorDomain code:saved userInfo:nil]}];
    return NO;
}
static BOOL Same(id a, id b) { return a == b || [a isEqual:b]; }
static NSString *UUIDValue(id value) {
    if (![value isKindOfClass:NSString.class] || [value length] != 36) return nil;
    return [[NSUUID alloc] initWithUUIDString:value].UUIDString;
}
static BOOL BundleValue(NSString *value) {
    if (![value isKindOfClass:NSString.class] || !value.length || value.length > 255) return NO;
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-."] invertedSet];
    if ([value rangeOfCharacterFromSet:invalid].location != NSNotFound) return NO;
    for (NSString *part in [value componentsSeparatedByString:@"."]) if (!part.length) return NO;
    return YES;
}
static BOOL PlainString(id value) { return [value isKindOfClass:NSString.class] && [value length] > 0 && [value length] <= 4096; }
static BOOL PrivateNode(struct stat info, BOOL directory) {
    return (directory ? S_ISDIR(info.st_mode) : S_ISREG(info.st_mode)) && info.st_uid == getuid() && (info.st_mode & 0777) == (directory ? 0700 : 0600);
}
static BOOL Overlaps(NSString *a, NSString *b) { return [a isEqual:b] || [a hasPrefix:[b stringByAppendingString:@"/"]] || [b hasPrefix:[a stringByAppendingString:@"/"]]; }
static BOOL SameNode(struct stat a, struct stat b) { return a.st_dev == b.st_dev && a.st_ino == b.st_ino; }
static BOOL MetadataName(const char *name) {
    return !strcmp(name, ".com.apple.mobile_container_manager.metadata.plist") || !strcmp(name, ".com.apple.mobile_container_manager.acl.plist");
}
static NSDictionary *Metadata(id metadata, NSString *fallback, NSError **error) {
    if (!metadata) return @{ @"title": [fallback substringToIndex:MIN(fallback.length, (NSUInteger)100)], @"note": @"" };
    if (![metadata isKindOfClass:NSDictionary.class] || [metadata count] != 2 || ![metadata[@"title"] isKindOfClass:NSString.class] || ![metadata[@"note"] isKindOfClass:NSString.class]) { Fail(error, @"Invalid snapshot name or note."); return nil; }
    NSString *title = [metadata[@"title"] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!title.length || title.length > 100 || [metadata[@"note"] length] > 1000) { Fail(error, @"Invalid snapshot name or note."); return nil; }
    return @{ @"title": title, @"note": metadata[@"note"] };
}
static NSData *Encode(id value, NSError **error) { return [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:error]; }
static id ReadPlistAt(int parent, NSString *name, NSError **error) {
    int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) { POSIXFail(error, @"Cannot read snapshot metadata."); return nil; }
    id result = nil;
    @try {
        struct stat info;
        if (fstat(fd, &info) || !PrivateNode(info, NO) || info.st_size <= 0 || (uint64_t)info.st_size > MaximumPlistSize) { Fail(error, @"Snapshot metadata is unsafe."); return nil; }
        NSMutableData *data = [NSMutableData dataWithLength:(NSUInteger)info.st_size];
        NSUInteger offset = 0;
        while (offset < data.length) { ssize_t count = read(fd, (char *)data.mutableBytes + offset, data.length - offset); if (count < 0 && errno == EINTR) continue; if (count <= 0) { POSIXFail(error, @"Cannot read snapshot metadata."); return nil; } offset += (NSUInteger)count; }
        result = [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:error];
    } @finally { close(fd); }
    return result;
}
static BOOL WritePlistAt(int parent, NSString *name, id value, NSError **error) {
    NSData *data = Encode(value, error); if (!data || data.length > MaximumPlistSize) return data ? Fail(error, @"Snapshot metadata is too large.") : NO;
    NSString *temporary = [@".write-" stringByAppendingString:NSUUID.UUID.UUIDString];
    int fd = openat(parent, temporary.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return POSIXFail(error, @"Cannot write snapshot metadata.");
    BOOL success = NO;
    @try {
        NSUInteger offset = 0;
        while (offset < data.length) { ssize_t count = write(fd, (const char *)data.bytes + offset, data.length - offset); if (count < 0 && errno == EINTR) continue; if (count <= 0) return POSIXFail(error, @"Cannot write snapshot metadata."); offset += (NSUInteger)count; }
        if (fsync(fd) || renameat(parent, temporary.fileSystemRepresentation, parent, name.fileSystemRepresentation) || fsync(parent)) return POSIXFail(error, @"Cannot commit snapshot metadata.");
        success = YES;
    } @finally { close(fd); if (!success) unlinkat(parent, temporary.fileSystemRepresentation, 0); }
    return success;
}
static BOOL ClearDirectory(int fd, BOOL preserveMetadata, SHDWStateProgress progress, NSError **error);
static BOOL RemoveChild(int parent, const char *name, SHDWStateProgress progress, NSError **error) {
    struct stat info;
    if (fstatat(parent, name, &info, AT_SYMLINK_NOFOLLOW)) return POSIXFail(error, @"Cannot inspect stored data.");
    if (progress) progress(@{ @"stage": @"clear" });
    if (!S_ISDIR(info.st_mode)) return unlinkat(parent, name, 0) == 0 || POSIXFail(error, @"Cannot remove stored data.");
    int child = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (child < 0) return POSIXFail(error, @"Cannot open stored data.");
    BOOL success = NO;
    @try {
        struct stat opened, owner;
        if (fstat(child, &opened) || fstat(parent, &owner) || !SameNode(opened, info) || opened.st_dev != owner.st_dev) return Fail(error, @"Stored data changed during cleanup.");
        if (!ClearDirectory(child, NO, progress, error)) return NO;
        if (progress) progress(@{ @"stage": @"clear" });
        success = unlinkat(parent, name, AT_REMOVEDIR) == 0 || POSIXFail(error, @"Cannot remove stored directory.");
    } @finally { close(child); }
    return success;
}
static BOOL ClearDirectory(int fd, BOOL preserveMetadata, SHDWStateProgress progress, NSError **error) {
    DIR *directory = fdopendir(dup(fd)); if (!directory) return POSIXFail(error, @"Cannot enumerate stored data.");
    BOOL success = YES;
    @try {
        for (;;) {
            errno = 0; struct dirent *entry = readdir(directory);
            if (!entry) { if (errno) success = POSIXFail(error, @"Cannot enumerate stored data."); break; }
            if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..") || (preserveMetadata && MetadataName(entry->d_name))) continue;
            if (!RemoveChild(fd, entry->d_name, progress, error)) { success = NO; break; }
        }
    } @finally { closedir(directory); }
    return success;
}

@interface SHDWStateDirectory : NSObject
@property(nonatomic) int fd;
@property(nonatomic) int snapshots;
@property(nonatomic) int lock;
@property(nonatomic) struct stat info;
@property(nonatomic) struct stat snapshotInfo;
@property(nonatomic, copy) NSString *path;
- (void)releaseLock;
@end
@implementation SHDWStateDirectory
- (instancetype)init { if ((self = [super init])) { _fd = -1; _snapshots = -1; _lock = -1; } return self; }
- (void)releaseLock { if (_lock >= 0) { flock(_lock, LOCK_UN); close(_lock); _lock = -1; } }
- (void)dealloc { if (_snapshots >= 0) close(_snapshots); if (_lock >= 0) { flock(_lock, LOCK_UN); close(_lock); } if (_fd >= 0) close(_fd); }
@end
@interface SHDWAppStateStore ()
@property(nonatomic, copy) NSString *root;
@property(nonatomic) int rootFD;
@property(nonatomic) struct stat rootInfo;
@property(nonatomic, strong) id<SHDWAppStateBackend> backend;
@end
@implementation SHDWAppStateStore
- (instancetype)initWithRoot:(NSString *)root backend:(id<SHDWAppStateBackend>)backend error:(NSError **)error {
    if (!(self = [super init])) return nil; _rootFD = -1;
    if (![root isKindOfClass:NSString.class] || !root.isAbsolutePath || !backend) { Fail(error, @"Invalid backup storage."); return nil; }
    NSString *name = root.lastPathComponent; char *parent = realpath(root.stringByDeletingLastPathComponent.fileSystemRepresentation, NULL);
    if (!parent || !name.length || [name isEqual:@"."] || [name isEqual:@".."]) { if (parent) free(parent); Fail(error, @"Backup storage parent is unavailable."); return nil; }
    NSString *parentPath = @(parent); free(parent);
    int parentFD = open(parentPath.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (parentFD < 0) { POSIXFail(error, @"Cannot open backup storage."); return nil; }
    if (mkdirat(parentFD, name.fileSystemRepresentation, 0700) && errno != EEXIST) { close(parentFD); POSIXFail(error, @"Cannot create backup storage."); return nil; }
    int fd = openat(parentFD, name.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); close(parentFD);
    struct stat info;
    if (fd < 0 || fstat(fd, &info) || !PrivateNode(info, YES)) { if (fd >= 0) close(fd); Fail(error, @"Backup storage must be a private directory."); return nil; }
    _rootFD = fd; _rootInfo = info; _root = [parentPath stringByAppendingPathComponent:name]; _backend = backend;
    return self;
}
- (void)dealloc { if (_rootFD >= 0) close(_rootFD); }
- (BOOL)checkRoot:(NSError **)error {
    struct stat info; return (!lstat(self.root.fileSystemRepresentation, &info) && PrivateNode(info, YES) && SameNode(info, self.rootInfo)) || Fail(error, @"Backup storage changed.");
}
- (SHDWStateDirectory *)directory:(NSString *)bundle create:(BOOL)create exclusive:(BOOL)exclusive missing:(BOOL *)missing error:(NSError **)error {
    if (missing) *missing = NO;
    if (!BundleValue(bundle) || ![self checkRoot:error]) { if (error && !*error) Fail(error, @"Invalid application identifier."); return nil; }
    struct stat info;
    if (fstatat(self.rootFD, bundle.fileSystemRepresentation, &info, AT_SYMLINK_NOFOLLOW)) {
        if (errno == ENOENT && !create) { if (missing) *missing = YES; return nil; }
        if (!create || errno != ENOENT || mkdirat(self.rootFD, bundle.fileSystemRepresentation, 0700)) { POSIXFail(error, @"Cannot open application backup storage."); return nil; }
    }
    SHDWStateDirectory *directory = [SHDWStateDirectory new]; directory.path = [self.root stringByAppendingPathComponent:bundle];
    directory.fd = openat(self.rootFD, bundle.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (directory.fd < 0 || fstat(directory.fd, &info) || !PrivateNode(info, YES)) { Fail(error, @"Application backup storage is unsafe."); return nil; } directory.info = info;
    directory.lock = openat(directory.fd, ".lock", O_RDWR | O_NOFOLLOW | O_CLOEXEC | (create ? O_CREAT : 0), 0600);
    if (directory.lock < 0 || fstat(directory.lock, &info) || !PrivateNode(info, NO)) { Fail(error, @"Application backup lock is unsafe."); return nil; }
    if (flock(directory.lock, (exclusive ? LOCK_EX : LOCK_SH) | LOCK_NB)) { Fail(error, @"An application state operation is already running."); return nil; }
    if (create && mkdirat(directory.fd, "snapshots", 0700) && errno != EEXIST) { POSIXFail(error, @"Cannot create snapshot storage."); return nil; }
    directory.snapshots = openat(directory.fd, "snapshots", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (directory.snapshots < 0 || fstat(directory.snapshots, &info) || !PrivateNode(info, YES)) { Fail(error, @"Snapshot storage is unsafe."); return nil; } directory.snapshotInfo = info;
    return directory;
}
- (BOOL)checkDirectory:(SHDWStateDirectory *)directory error:(NSError **)error {
    if (![self checkRoot:error]) return NO;
    struct stat info;
    return (!lstat(directory.path.fileSystemRepresentation, &info) && PrivateNode(info, YES) && SameNode(info, directory.info) && !fstatat(directory.fd, "snapshots", &info, AT_SYMLINK_NOFOLLOW) && PrivateNode(info, YES) && SameNode(info, directory.snapshotInfo)) || Fail(error, @"Application backup storage changed.");
}
- (NSDictionary *)pending:(SHDWStateDirectory *)directory error:(NSError **)error {
    struct stat info;
    if (fstatat(directory.fd, "pending.plist", &info, AT_SYMLINK_NOFOLLOW)) { if (errno == ENOENT) return @{}; POSIXFail(error, @"Cannot inspect restoration state."); return nil; }
    id pending = ReadPlistAt(directory.fd, @"pending.plist", error);
    if (![pending isKindOfClass:NSDictionary.class] || !Same(pending[@"format"], StateFormat) || !UUIDValue(pending[@"idfv"]) || !Same(pending[@"idfv"], UUIDValue(pending[@"idfv"])) || !Same(pending[@"bundleID"], directory.path.lastPathComponent) || ![pending[@"archiveSHA"] isKindOfClass:NSString.class] || [pending[@"archiveSHA"] length] != 64 || ![pending[@"date"] isKindOfClass:NSDate.class]) { if (error && !*error) Fail(error, @"Restoration state is invalid."); return nil; }
    return pending;
}
- (NSDictionary *)target:(NSString *)bundle error:(NSError **)error {
    NSDictionary *value = [self.backend resolveBundle:bundle error:error];
    if (![value isKindOfClass:NSDictionary.class] || !Same(value[@"bundleID"], bundle) || !PlainString(value[@"token"]) || !PlainString(value[@"version"]) || !PlainString(value[@"build"]) || ![value[@"containers"] isKindOfClass:NSDictionary.class] || !value[@"containers"][@"data"] || ![value[@"keychainGroups"] isKindOfClass:NSArray.class]) { if (error && !*error) Fail(error, @"Cannot verify the selected application."); return nil; }
    NSMutableDictionary *roots = [NSMutableDictionary new], *mapping = [NSMutableDictionary new], *pins = [NSMutableDictionary new];
    for (id identifier in value[@"containers"]) if (!PlainString(identifier)) { Fail(error, @"Invalid application container identifier."); return nil; }
    NSArray *ids = [[value[@"containers"] allKeys] sortedArrayUsingSelector:@selector(compare:)]; NSUInteger group = 0;
    for (id identifier in ids) {
        id path = value[@"containers"][identifier];
        if (!PlainString(identifier) || !PlainString(path) || ![path isAbsolutePath]) { Fail(error, @"Invalid application container."); return nil; }
        struct stat info; char *resolved = realpath([path fileSystemRepresentation], NULL);
        if (!resolved || lstat([path fileSystemRepresentation], &info) || !S_ISDIR(info.st_mode)) { if (resolved) free(resolved); Fail(error, @"Application container is unavailable."); return nil; }
        NSString *physical = @(resolved); free(resolved);
        if (lstat(physical.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode)) { Fail(error, @"Application container is unsafe."); return nil; }
        if (Overlaps(physical, self.root)) { Fail(error, @"Backup storage and application containers must not overlap."); return nil; }
        NSString *prefix = [identifier isEqual:@"data"] ? @"containers/data" : [NSString stringWithFormat:@"containers/group-%04lu", (unsigned long)group++];
        for (NSString *other in roots.allValues) if (Overlaps(physical, other)) { Fail(error, @"Application containers overlap."); return nil; }
        roots[prefix] = physical; mapping[prefix] = @{ @"containerID": identifier, @"nativePath": physical }; pins[prefix] = @{ @"device": @((uint64_t)info.st_dev), @"inode": @((uint64_t)info.st_ino) };
    }
    for (id groupID in value[@"keychainGroups"]) if (!PlainString(groupID)) { Fail(error, @"Invalid application credential scope."); return nil; }
    return @{ @"target": value, @"roots": roots, @"mapping": mapping, @"pins": pins };
}
- (BOOL)guard:(NSDictionary *)context directory:(SHDWStateDirectory *)directory refresh:(BOOL)refresh error:(NSError **)error {
    if (![self checkDirectory:directory error:error] || ![self.backend assertStopped:context[@"target"] error:error]) return NO;
    for (NSString *prefix in context[@"roots"]) {
        struct stat info; NSString *path = context[@"roots"][prefix]; NSDictionary *pin = context[@"pins"][prefix];
        if (lstat(path.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode) || (uint64_t)info.st_dev != [pin[@"device"] unsignedLongLongValue] || (uint64_t)info.st_ino != [pin[@"inode"] unsignedLongLongValue]) return Fail(error, @"Application containers changed.");
    }
    if (refresh) {
        NSDictionary *again = [self target:context[@"target"][@"bundleID"] error:error]; if (!again) return NO;
        for (NSString *key in @[@"bundleID", @"token", @"version", @"build", @"keychainGroups"]) if (!Same(again[@"target"][key], context[@"target"][key])) return Fail(error, @"Application installation changed.");
        if (!Same(again[@"mapping"], context[@"mapping"]) || !Same(again[@"pins"], context[@"pins"])) return Fail(error, @"Application containers changed.");
    }
    return YES;
}
- (void)event:(NSString *)phase stage:(NSString *)stage { if (self.progressHandler) self.progressHandler(@{ @"phase": phase, @"stage": stage }); }
- (SHDWStateProgress)guardedProgress:(NSDictionary *)context directory:(SHDWStateDirectory *)directory phase:(NSString *)phase failure:(NSError * __strong *)failure {
    return ^(NSDictionary *event) {
        NSError *error = nil;
        if (![self guard:context directory:directory refresh:NO error:&error]) { if (failure) *failure = error; @throw [NSException exceptionWithName:@"SHDWStateInterrupted" reason:error.localizedDescription userInfo:nil]; }
        if (self.progressHandler) { NSMutableDictionary *value = [event mutableCopy]; value[@"phase"] = phase; self.progressHandler(value); }
        if (![self guard:context directory:directory refresh:NO error:&error]) { if (failure) *failure = error; @throw [NSException exceptionWithName:@"SHDWStateInterrupted" reason:error.localizedDescription userInfo:nil]; }
    };
}
- (NSDictionary *)fingerprint:(NSDictionary *)context error:(NSError **)error {
    NSDictionary *value = [self.backend captureFingerprintForTarget:context[@"target"] error:error];
    if (![value isKindOfClass:NSDictionary.class] || ![value[@"data"] isKindOfClass:NSDictionary.class] || ![value[@"configuration"] isKindOfClass:NSDictionary.class] || ![value[@"locked"] isKindOfClass:NSNumber.class] || !UUIDValue(value[@"data"][@"VendorIdentifier"]) || !Same(value[@"data"][@"VendorIdentifier"], UUIDValue(value[@"data"][@"VendorIdentifier"]))) { if (error && !*error) Fail(error, @"The application has no valid fingerprint."); return nil; }
    return [self.backend validateFingerprint:value target:context[@"target"] error:error] ? value : nil;
}
- (NSDictionary *)manifest:(NSString *)bundle idfv:(NSString *)idfv directory:(SHDWStateDirectory *)directory verify:(BOOL)verify error:(NSError **)error {
    int fd = openat(directory.snapshots, idfv.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); if (fd < 0) { POSIXFail(error, @"Snapshot is unavailable."); return nil; }
    NSDictionary *manifest = nil;
    @try {
        struct stat info;
        if (fstat(fd, &info) || !PrivateNode(info, YES)) { Fail(error, @"Snapshot directory is unsafe."); return nil; }
        id value = ReadPlistAt(fd, @"manifest.plist", error);
        if (![value isKindOfClass:NSDictionary.class] || !Same(value[@"format"], StateFormat) || !Same(value[@"bundleID"], bundle) || !Same(value[@"idfv"], idfv) || !Metadata(@{ @"title": value[@"title"] ?: @0, @"note": value[@"note"] ?: @0 }, bundle, NULL) || ![value[@"date"] isKindOfClass:NSDate.class] || !PlainString(value[@"version"]) || !PlainString(value[@"build"]) || ![value[@"roots"] isKindOfClass:NSDictionary.class] || ![value[@"roots"] count] || ![value[@"archiveInfo"] isKindOfClass:NSDictionary.class] || ![value[@"keychainGroups"] isKindOfClass:NSArray.class]) { if (error && !*error) Fail(error, @"Snapshot manifest is invalid."); return nil; }
        NSMutableDictionary *sourceRoots = [NSMutableDictionary new];
        for (id prefix in value[@"roots"]) { id root = value[@"roots"][prefix]; if (![prefix isKindOfClass:NSString.class] || ![prefix hasPrefix:@"containers/"] || ![root isKindOfClass:NSDictionary.class] || !PlainString(root[@"containerID"]) || !PlainString(root[@"nativePath"]) || ![root[@"nativePath"] isAbsolutePath]) { Fail(error, @"Snapshot container mapping is invalid."); return nil; } sourceRoots[prefix] = root[@"nativePath"]; }
        if (!Same(sourceRoots, value[@"archiveInfo"][@"sourceRoots"])) { Fail(error, @"Snapshot archive mapping differs."); return nil; }
        if (fstatat(fd, "data.tar.zst", &info, AT_SYMLINK_NOFOLLOW) || !PrivateNode(info, NO)) { Fail(error, @"Snapshot archive is unsafe."); return nil; }
        NSString *archive = [[directory.path stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:[idfv stringByAppendingPathComponent:@"data.tar.zst"]];
        if (verify && ![SHDWStateArchive verifyPath:archive info:value[@"archiveInfo"] progress:self.progressHandler error:error]) return nil;
        manifest = value;
    } @finally { close(fd); }
    return manifest;
}
- (NSDictionary *)payloads:(NSDictionary *)manifest directory:(SHDWStateDirectory *)directory error:(NSError **)error {
    NSString *path = [[directory.path stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:[manifest[@"idfv"] stringByAppendingPathComponent:@"data.tar.zst"]];
    NSDictionary *data = [SHDWStateArchive readPayloadsAtPath:path info:manifest[@"archiveInfo"] names:@[IdentityPayload, KeychainPayload] error:error]; if (!data) return nil;
    id identity = [NSPropertyListSerialization propertyListWithData:data[IdentityPayload] ?: [NSData data] options:NSPropertyListImmutable format:NULL error:error];
    id keychain = [NSPropertyListSerialization propertyListWithData:data[KeychainPayload] ?: [NSData data] options:NSPropertyListImmutable format:NULL error:error];
    if (![identity isKindOfClass:NSDictionary.class] || [identity count] != 2 || ![identity[@"data"] isKindOfClass:NSDictionary.class] || ![identity[@"configuration"] isKindOfClass:NSDictionary.class] || !Same(identity[@"data"][@"VendorIdentifier"], manifest[@"idfv"]) || ![keychain isKindOfClass:NSArray.class]) { if (error && !*error) Fail(error, @"Snapshot identity or credential payload is invalid."); return nil; }
    return @{ @"fingerprint": @{ @"data": identity[@"data"], @"configuration": identity[@"configuration"], @"locked": @YES }, @"keychain": keychain };
}
- (BOOL)records:(NSArray *)a equal:(NSArray *)b {
    if (![a isKindOfClass:NSArray.class] || ![b isKindOfClass:NSArray.class] || a.count != b.count) return NO;
    NSCountedSet *left = [[NSCountedSet alloc] initWithArray:a], *right = [[NSCountedSet alloc] initWithArray:b];
    for (id value in left) if ([left countForObject:value] != [right countForObject:value]) return NO;
    return YES;
}
- (NSDictionary *)backup:(NSString *)bundle metadata:(NSDictionary *)metadata directory:(SHDWStateDirectory *)directory error:(NSError **)error {
    NSDictionary *pending = [self pending:directory error:error]; if (!pending) return nil;
    if (pending.count) { Fail(error, @"Retry the incomplete restoration before creating a backup."); return nil; }
    NSDictionary *context = [self target:bundle error:error]; if (!context) return nil;
    [self event:@"backup" stage:@"stop"];
    if (![self.backend stopTarget:context[@"target"] error:error] || ![self guard:context directory:directory refresh:YES error:error] || ![self.backend flushPreferencesForTarget:context[@"target"] error:error]) return nil;
    if (![self guard:context directory:directory refresh:YES error:error]) return nil;
    NSDictionary *fingerprint = [self fingerprint:context error:error]; if (!fingerprint) return nil;
    NSArray *records = [self.backend captureKeychainForTarget:context[@"target"] error:error];
    if (![records isKindOfClass:NSArray.class] || ![self.backend validateKeychain:records target:context[@"target"] error:error]) { if (error && !*error) Fail(error, @"Cannot capture application credentials."); return nil; }
    NSString *idfv = fingerprint[@"data"][@"VendorIdentifier"];
    struct stat previousInfo; BOOL replacing = fstatat(directory.snapshots, idfv.fileSystemRepresentation, &previousInfo, AT_SYMLINK_NOFOLLOW) == 0;
    if (!replacing && errno != ENOENT) { POSIXFail(error, @"Cannot inspect the existing snapshot."); return nil; }
    NSDictionary *previous = replacing ? [self manifest:bundle idfv:idfv directory:directory verify:NO error:error] : nil; if (replacing && !previous) return nil;
    NSDictionary *display = Metadata(metadata ?: (previous ? @{ @"title": previous[@"title"], @"note": previous[@"note"] } : nil), bundle, error); if (!display) return nil;
    NSDictionary *identity = @{ @"data": fingerprint[@"data"], @"configuration": fingerprint[@"configuration"] };
    NSData *identityData = Encode(identity, error), *keychainData = Encode(records, error); if (!identityData || !keychainData || identityData.length > MaximumPayloadSize || keychainData.length > MaximumPayloadSize) { if (error && !*error) Fail(error, @"Snapshot identity or credentials are too large."); return nil; }
    NSString *stage = [@".capture-" stringByAppendingString:NSUUID.UUID.UUIDString];
    if (![self guard:context directory:directory refresh:YES error:error] || mkdirat(directory.fd, stage.fileSystemRepresentation, 0700)) { if (error && !*error) POSIXFail(error, @"Cannot create snapshot staging."); return nil; }
    int stageFD = openat(directory.fd, stage.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (stageFD < 0) { POSIXFail(error, @"Cannot open snapshot staging."); unlinkat(directory.fd, stage.fileSystemRepresentation, AT_REMOVEDIR); return nil; }
    BOOL keepStage = NO, published = NO; NSDictionary *result = nil; __block NSError *interruption = nil;
    @try {
        NSString *archive = [[directory.path stringByAppendingPathComponent:stage] stringByAppendingPathComponent:@"data.tar.zst"];
        SHDWStateProgress progress = [self guardedProgress:context directory:directory phase:@"backup" failure:&interruption];
        NSDictionary *archiveInfo = [SHDWStateArchive captureRoots:context[@"roots"] payloads:@{ IdentityPayload: identityData, KeychainPayload: keychainData } toPath:archive progress:progress error:error];
        if (!archiveInfo || ![SHDWStateArchive verifyPath:archive info:archiveInfo progress:progress error:error]) { if (interruption && error) *error = interruption; return nil; }
        NSDictionary *live = [self fingerprint:context error:error]; NSArray *again = [self.backend captureKeychainForTarget:context[@"target"] error:error];
        if (!live || !again || !Same(live[@"data"], identity[@"data"]) || !Same(live[@"configuration"], identity[@"configuration"]) || ![self records:records equal:again]) { if (error && !*error) Fail(error, @"Application state changed during backup."); return nil; }
        NSMutableDictionary *manifest = [@{ @"format": StateFormat, @"bundleID": bundle, @"idfv": idfv, @"title": display[@"title"], @"note": display[@"note"], @"date": NSDate.date, @"version": context[@"target"][@"version"], @"build": context[@"target"][@"build"], @"roots": context[@"mapping"], @"keychainGroups": context[@"target"][@"keychainGroups"], @"archiveInfo": archiveInfo } mutableCopy];
        if (!WritePlistAt(stageFD, @"manifest.plist", manifest, error)) return nil;
        int archiveFD = openat(stageFD, "data.tar.zst", O_RDONLY | O_NOFOLLOW | O_CLOEXEC); struct stat archiveStat;
        if (archiveFD < 0 || fstat(archiveFD, &archiveStat) || !PrivateNode(archiveStat, NO) || fsync(archiveFD)) { if (archiveFD >= 0) close(archiveFD); Fail(error, @"Cannot synchronize the captured archive."); return nil; } close(archiveFD);
        [self event:@"backup" stage:@"publish"];
        if (![self guard:context directory:directory refresh:YES error:error]) return nil;
        if (fsync(stageFD)) { POSIXFail(error, @"Cannot synchronize snapshot staging."); return nil; }
        struct stat current;
        if (replacing) {
            if (fstatat(directory.snapshots, idfv.fileSystemRepresentation, &current, AT_SYMLINK_NOFOLLOW) || !SameNode(current, previousInfo) || !Same(previous, [self manifest:bundle idfv:idfv directory:directory verify:NO error:error])) { if (error && !*error) Fail(error, @"The previous snapshot changed."); return nil; }
#if defined(__APPLE__) && defined(RENAME_SWAP)
            if (renameatx_np(directory.fd, stage.fileSystemRepresentation, directory.snapshots, idfv.fileSystemRepresentation, RENAME_SWAP)) { POSIXFail(error, @"Atomic snapshot replacement is unavailable."); return nil; }
#else
            Fail(error, @"Atomic snapshot replacement is unavailable."); return nil;
#endif
        } else {
#if defined(__APPLE__) && defined(RENAME_EXCL)
            if (renameatx_np(directory.fd, stage.fileSystemRepresentation, directory.snapshots, idfv.fileSystemRepresentation, RENAME_EXCL)) { POSIXFail(error, @"Cannot publish the new snapshot."); return nil; }
#else
            if (renameat(directory.fd, stage.fileSystemRepresentation, directory.snapshots, idfv.fileSystemRepresentation)) { POSIXFail(error, @"Cannot publish the new snapshot."); return nil; }
#endif
        }
        published = YES; keepStage = replacing;
        if (fsync(directory.snapshots) || fsync(directory.fd)) {
            POSIXFail(error, @"Cannot synchronize the published snapshot.");
#if defined(__APPLE__) && defined(RENAME_SWAP)
            if (replacing && !renameatx_np(directory.fd, stage.fileSystemRepresentation, directory.snapshots, idfv.fileSystemRepresentation, RENAME_SWAP)) { published = NO; keepStage = NO; fsync(directory.snapshots); fsync(directory.fd); }
#endif
            return nil;
        }
        // Publication is committed. Deferred private cleanup must not turn a
        // successful replacement into a reported failed backup.
        if (replacing && !fstatat(directory.fd, stage.fileSystemRepresentation, &current, AT_SYMLINK_NOFOLLOW) && SameNode(current, previousInfo)) {
            NSError *cleanupError = nil;
            if (RemoveChild(directory.fd, stage.fileSystemRepresentation, nil, &cleanupError)) { keepStage = NO; fsync(directory.fd); }
        }
        result = manifest;
    } @finally {
        close(stageFD);
        if (!keepStage && !published) { NSError *cleanupError = nil; if (!RemoveChild(directory.fd, stage.fileSystemRepresentation, nil, &cleanupError) && error && !*error) *error = cleanupError; }
    }
    return result;
}
- (NSDictionary *)backupBundle:(NSString *)bundleID metadata:(NSDictionary *)metadata error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil;
        if (!BundleValue(bundleID)) { Fail(error, @"Invalid application identifier."); return nil; }
        // Resolve overlap before creating even lock or catalog files: storage
        // accidentally inside a live container must remain untouched.
        if (![self target:bundleID error:error]) return nil;
        SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:YES exclusive:YES missing:NULL error:error];
        return directory ? [self backup:bundleID metadata:metadata directory:directory error:error] : nil;
    } @catch (NSException *exception) { Fail(error, exception.reason ?: @"Backup failed."); return nil; }
    @finally { [operationDirectory releaseLock]; }
}
- (NSArray<NSDictionary *> *)catalogBundle:(NSString *)bundleID error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil; BOOL missing = NO;
        SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:NO exclusive:NO missing:&missing error:error]; if (!directory) return missing ? @[] : nil;
        NSDictionary *pending = [self pending:directory error:error]; if (!pending) return nil;
        DIR *stream = fdopendir(dup(directory.snapshots)); if (!stream) { POSIXFail(error, @"Cannot enumerate snapshots."); return nil; }
        NSMutableArray *entries = [NSMutableArray new]; BOOL valid = YES;
        @try {
            for (;;) {
                errno = 0; struct dirent *entry = readdir(stream); if (!entry) { if (errno) valid = POSIXFail(error, @"Cannot enumerate snapshots."); break; }
                if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
                NSString *idfv = @(entry->d_name); if (!Same(idfv, UUIDValue(idfv))) { valid = Fail(error, @"Invalid snapshot directory."); break; }
                NSDictionary *manifest = [self manifest:bundleID idfv:idfv directory:directory verify:NO error:error]; if (!manifest) { valid = NO; break; }
                NSMutableDictionary *item = [manifest mutableCopy]; item[@"restorePending"] = @(pending.count > 0); item[@"recoverySource"] = @(Same(pending[@"idfv"], idfv)); [entries addObject:item];
            }
        } @finally { closedir(stream); }
        if (!valid || ![self checkDirectory:directory error:error]) return nil;
        [entries sortUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [b[@"date"] compare:a[@"date"]]; }]; return entries;
    } @finally { [operationDirectory releaseLock]; }
}
- (BOOL)recheckBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil; NSString *canonical = UUIDValue(idfv); if (!canonical) return Fail(error, @"Invalid snapshot identity.");
        SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:NO exclusive:NO missing:NULL error:error]; if (!directory) return NO;
        NSDictionary *manifest = [self manifest:bundleID idfv:canonical directory:directory verify:YES error:error];
        return manifest && [self payloads:manifest directory:directory error:error] && [self checkDirectory:directory error:error];
    } @finally { [operationDirectory releaseLock]; }
}
- (BOOL)editBundle:(NSString *)bundleID idfv:(NSString *)idfv metadata:(NSDictionary *)metadata error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil; if (!metadata) return Fail(error, @"Snapshot name and note are required."); NSString *canonical = UUIDValue(idfv); NSDictionary *display = Metadata(metadata, bundleID ?: @"", error); if (!canonical || !display) return display ? Fail(error, @"Invalid snapshot identity.") : NO;
        SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:NO exclusive:YES missing:NULL error:error]; if (!directory) return NO;
        NSDictionary *pending = [self pending:directory error:error]; if (!pending) return NO; if (Same(pending[@"idfv"], canonical)) return Fail(error, @"The pending restoration source cannot be edited.");
        NSMutableDictionary *manifest = [[self manifest:bundleID idfv:canonical directory:directory verify:NO error:error] mutableCopy]; if (!manifest) return NO; [manifest addEntriesFromDictionary:display];
        if (![self checkDirectory:directory error:error]) return NO;
        int fd = openat(directory.snapshots, canonical.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); if (fd < 0) return POSIXFail(error, @"Cannot open the snapshot.");
        BOOL success = WritePlistAt(fd, @"manifest.plist", manifest, error); close(fd); return success;
    } @finally { [operationDirectory releaseLock]; }
}
- (BOOL)deleteBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil; NSString *canonical = UUIDValue(idfv); if (!canonical) return Fail(error, @"Invalid snapshot identity.");
        SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:NO exclusive:YES missing:NULL error:error]; if (!directory) return NO;
        NSDictionary *pending = [self pending:directory error:error]; if (!pending) return NO; if (Same(pending[@"idfv"], canonical)) return Fail(error, @"The pending restoration source cannot be deleted.");
        if (![self manifest:bundleID idfv:canonical directory:directory verify:NO error:error] || ![self checkDirectory:directory error:error]) return NO;
        return RemoveChild(directory.snapshots, canonical.fileSystemRepresentation, nil, error) && (fsync(directory.snapshots) == 0 || POSIXFail(error, @"Cannot synchronize snapshot deletion."));
    } @finally { [operationDirectory releaseLock]; }
}
- (NSDictionary *)restoreBundle:(NSString *)bundleID idfv:(NSString *)idfv saveCurrent:(BOOL)saveCurrent error:(NSError **)error {
    SHDWStateDirectory *operationDirectory = nil;
    @try {
        if (error) *error = nil; BOOL mutated = NO, restored = NO; NSDictionary *recovery = nil; __block NSError *interruption = nil;
        @try {
            NSString *canonical = UUIDValue(idfv); if (!canonical) { Fail(error, @"Invalid snapshot identity."); return nil; }
            SHDWStateDirectory *directory = operationDirectory = [self directory:bundleID create:NO exclusive:YES missing:NULL error:error]; if (!directory) return nil;
            NSDictionary *pending = [self pending:directory error:error]; if (!pending) return nil;
            if (pending.count && (!Same(pending[@"idfv"], canonical) || saveCurrent)) { Fail(error, @"Retry the pending source without saving the incomplete current state."); return nil; }
            NSDictionary *manifest = [self manifest:bundleID idfv:canonical directory:directory verify:YES error:error]; if (!manifest) return nil;
            if (pending.count && !Same(pending[@"archiveSHA"], manifest[@"archiveInfo"][@"sha256"])) { Fail(error, @"The restoration source changed."); return nil; }
            NSDictionary *payloads = [self payloads:manifest directory:directory error:error]; if (!payloads) return nil;
            NSDictionary *context = [self target:bundleID error:error]; if (!context) return nil;
            NSDictionary *target = context[@"target"];
            if (!Same(manifest[@"version"], target[@"version"]) || !Same(manifest[@"build"], target[@"build"]) || ![[NSSet setWithArray:manifest[@"keychainGroups"]] isEqual:[NSSet setWithArray:target[@"keychainGroups"]]]) { Fail(error, @"The installed application is incompatible with this snapshot."); return nil; }
            NSMutableDictionary *roots = [NSMutableDictionary new]; NSMutableSet *ids = [NSMutableSet new];
            for (NSString *prefix in manifest[@"roots"]) { NSString *identifier = manifest[@"roots"][prefix][@"containerID"]; if ([ids containsObject:identifier] || !target[@"containers"][identifier]) { Fail(error, @"Snapshot containers differ from the installed application."); return nil; } [ids addObject:identifier]; char *physical = realpath([target[@"containers"][identifier] fileSystemRepresentation], NULL); if (!physical) { Fail(error, @"A restoration container is unavailable."); return nil; } roots[prefix] = @(physical); free(physical); }
            if (![ids isEqual:[NSSet setWithArray:[target[@"containers"] allKeys]]]) { Fail(error, @"Snapshot containers differ from the installed application."); return nil; }
            [self event:@"restore" stage:@"stop"];
            if (![self.backend stopTarget:target error:error] || ![self guard:context directory:directory refresh:YES error:error] || ![self.backend validateKeychain:payloads[@"keychain"] target:target error:error] || ![self.backend validateFingerprint:payloads[@"fingerprint"] target:target error:error]) return nil;
            if (saveCurrent) {
                NSDictionary *live = [self fingerprint:context error:error]; if (!live) return nil;
                if (Same(live[@"data"][@"VendorIdentifier"], canonical)) { Fail(error, @"Saving the current state would overwrite the selected restoration source. Restore without saving it instead."); return nil; }
                if (![self backup:bundleID metadata:nil directory:directory error:error]) return nil;
            }
            if (![self guard:context directory:directory refresh:YES error:error] || ![self.backend flushPreferencesForTarget:target error:error] || ![self guard:context directory:directory refresh:YES error:error]) return nil;
            recovery = pending.count ? pending : @{ @"format": StateFormat, @"bundleID": bundleID, @"idfv": canonical, @"archiveSHA": manifest[@"archiveInfo"][@"sha256"], @"date": NSDate.date };
            if (!pending.count && !WritePlistAt(directory.fd, @"pending.plist", recovery, error)) return nil;
            SHDWStateProgress progress = [self guardedProgress:context directory:directory phase:@"restore" failure:&interruption];
            [self event:@"restore" stage:@"keychain"];
            if (![self guard:context directory:directory refresh:YES error:error]) return nil;
            mutated = YES; if (![self.backend restoreKeychain:payloads[@"keychain"] target:target error:error]) return nil;
            for (NSString *prefix in roots) {
                [self event:@"restore" stage:@"clear"];
                if (![self guard:context directory:directory refresh:YES error:error]) return nil;
                int fd = open([roots[prefix] fileSystemRepresentation], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); if (fd < 0) { POSIXFail(error, @"Cannot open the restoration container."); return nil; }
                BOOL cleared = NO; @try { cleared = ClearDirectory(fd, YES, progress, error); } @finally { close(fd); } if (!cleared) return nil;
            }
            NSString *archive = [[directory.path stringByAppendingPathComponent:@"snapshots"] stringByAppendingPathComponent:[canonical stringByAppendingPathComponent:@"data.tar.zst"]];
            if (![self guard:context directory:directory refresh:YES error:error] || ![SHDWStateArchive restorePath:archive info:manifest[@"archiveInfo"] roots:roots progress:progress error:error]) return nil;
            [self event:@"restore" stage:@"fingerprint"];
            if (![self guard:context directory:directory refresh:YES error:error] || ![self.backend restoreFingerprint:payloads[@"fingerprint"] target:target error:error]) return nil;
            if (![self guard:context directory:directory refresh:YES error:error] || ![self.backend flushPreferencesForTarget:target error:error]) return nil;
            [self event:@"restore" stage:@"recheck"];
            if (![self guard:context directory:directory refresh:YES error:error] || ![SHDWStateArchive verifyRoots:roots info:manifest[@"archiveInfo"] progress:progress error:error]) return nil;
            NSArray *actualRecords = [self.backend captureKeychainForTarget:target error:error]; NSDictionary *actualFingerprint = [self fingerprint:context error:error];
            if (!actualRecords || !actualFingerprint || ![self records:actualRecords equal:payloads[@"keychain"]] || !Same(actualFingerprint[@"data"], payloads[@"fingerprint"][@"data"]) || !Same(actualFingerprint[@"configuration"], payloads[@"fingerprint"][@"configuration"]) || ![actualFingerprint[@"locked"] boolValue]) { if (error && !*error) Fail(error, @"Restored data, credentials, or fingerprint did not pass verification."); return nil; }
            if (![self guard:context directory:directory refresh:YES error:error] || unlinkat(directory.fd, "pending.plist", 0) || fsync(directory.fd)) { if (error && !*error) POSIXFail(error, @"Cannot complete the verified restoration."); return nil; }
            restored = YES; return @{ @"idfv": canonical, @"restored": @YES, @"locked": @YES };
        } @catch (NSException *exception) { if (interruption && error) *error = interruption; else Fail(error, exception.reason ?: @"Restoration failed."); return nil; }
        @finally {
            if (mutated && !restored) {
                if (error && !*error) Fail(error, @"Restoration failed before verification completed.");
                BOOL pendingRetained = YES; struct stat info;
                if (recovery && fstatat(operationDirectory.fd, "pending.plist", &info, AT_SYMLINK_NOFOLLOW)) pendingRetained = WritePlistAt(operationDirectory.fd, @"pending.plist", recovery, NULL);
                if (error && *error) { NSMutableDictionary *details = [(*error).userInfo mutableCopy]; details[@"stateMayBePartial"] = @YES; if (!pendingRetained) details[@"pendingPersistenceFailed"] = @YES; *error = [NSError errorWithDomain:(*error).domain code:(*error).code userInfo:details]; }
            }
        }
    } @finally { [operationDirectory releaseLock]; }
}
@end
