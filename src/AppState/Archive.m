#import "Archive.h"
#include <archive.h>
#include <archive_entry.h>
#include <CommonCrypto/CommonDigest.h>
#include <sys/stat.h>
#include <sys/attr.h>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <errno.h>
#include <limits.h>
#include <math.h>

NSString *const SHDWStateArchiveErrorDomain = @"Shadow.AppState.Archive";
static const size_t Chunk = 128 * 1024;
static const NSUInteger PayloadLimit = 16 * 1024 * 1024;

static void Check(BOOL value, NSString *message) {
    if (!value) @throw [NSException exceptionWithName:SHDWStateArchiveErrorDomain reason:message userInfo:nil];
}
static void PublishError(NSError **error, NSException *exception) {
    if (error) *error = [NSError errorWithDomain:SHDWStateArchiveErrorDomain code:1 userInfo:@{NSLocalizedDescriptionKey:exception.reason ?: @"Archive operation failed"}];
}
static NSString *Hex(const unsigned char *bytes, size_t count) {
    NSMutableString *value = [NSMutableString new];
    for (size_t i = 0; i < count; i++) [value appendFormat:@"%02x", bytes[i]];
    return value;
}
static BOOL SafePath(NSString *value) {
    if (![value isKindOfClass:NSString.class] || !value.length || value.isAbsolutePath ||
        [value rangeOfCharacterFromSet:[NSCharacterSet characterSetWithRange:NSMakeRange(0, 1)]].location != NSNotFound) return NO;
    for (NSString *piece in [value componentsSeparatedByString:@"/"]) if (!piece.length || [piece isEqual:@"."] || [piece isEqual:@".."]) return NO;
    return YES;
}
static BOOL Below(NSString *path, NSString *root) { return [path hasPrefix:[root stringByAppendingString:@"/"]]; }
static NSString *Physical(NSString *path) {
    char value[PATH_MAX]; Check([path isKindOfClass:NSString.class] && path.length && realpath(path.fileSystemRepresentation, value), @"Cannot resolve archive path");
    return [NSString stringWithUTF8String:value];
}
static BOOL Excluded(NSString *prefix, NSString *relative) {
    if ([@[@".com.apple.mobile_container_manager.metadata.plist", @".com.apple.mobile_container_manager.acl.plist"] containsObject:relative]) return YES;
    return [prefix isEqual:@"containers/data"] && ([relative isEqual:@"Library/SplashBoard"] || Below(relative, @"Library/SplashBoard"));
}
static void Progress(SHDWStateProgress progress, NSString *phase, unsigned long long bytes, NSUInteger entries) {
    if (progress) { @autoreleasepool { progress(@{@"phase":phase, @"bytes":@(bytes), @"entries":@(entries)}); } }
}
static NSDictionary *StatEntry(NSString *path, struct stat st) {
    Check(S_ISDIR(st.st_mode) || S_ISREG(st.st_mode) || S_ISLNK(st.st_mode), @"Unsupported archive source type");
    return @{@"path":path, @"type":S_ISDIR(st.st_mode) ? @"directory" : S_ISREG(st.st_mode) ? @"file" : @"symlink",
        @"mode":@(st.st_mode & 07777), @"uid":@(st.st_uid), @"gid":@(st.st_gid),
        @"mtime":@(st.st_mtimespec.tv_sec), @"mtimeNsec":@(st.st_mtimespec.tv_nsec),
        @"birthtime":@(st.st_birthtimespec.tv_sec), @"birthtimeNsec":@(st.st_birthtimespec.tv_nsec)};
}
static NSString *InodeKey(struct stat st) { return [NSString stringWithFormat:@"%llu:%llu", (unsigned long long)st.st_dev, (unsigned long long)st.st_ino]; }
static BOOL SameStat(struct stat before, struct stat after) {
    return before.st_dev == after.st_dev && before.st_ino == after.st_ino && before.st_mode == after.st_mode &&
        before.st_uid == after.st_uid && before.st_gid == after.st_gid && before.st_size == after.st_size &&
        before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec &&
        before.st_birthtimespec.tv_sec == after.st_birthtimespec.tv_sec && before.st_birthtimespec.tv_nsec == after.st_birthtimespec.tv_nsec &&
        before.st_ctimespec.tv_sec == after.st_ctimespec.tv_sec && before.st_ctimespec.tv_nsec == after.st_ctimespec.tv_nsec;
}

@interface ArchiveRoot : NSObject
@property (nonatomic, copy) NSString *prefix;
@property (nonatomic, copy) NSString *path;
@property (nonatomic, assign) int fd;
@property (nonatomic, assign) dev_t device;
@property (nonatomic, assign) ino_t inode;
@property (nonatomic, assign) struct timespec birthtime;
@end
@implementation ArchiveRoot
- (instancetype)init { if ((self = [super init])) _fd = -1; return self; }
- (void)dealloc { if (_fd >= 0) close(_fd); }
- (void)pin {
    struct stat st, named;
    Check(!fstat(self.fd, &st) && !lstat(self.path.fileSystemRepresentation, &named) && S_ISDIR(named.st_mode) &&
        st.st_dev == self.device && st.st_ino == self.inode && named.st_dev == self.device && named.st_ino == self.inode &&
        st.st_birthtimespec.tv_sec == self.birthtime.tv_sec && st.st_birthtimespec.tv_nsec == self.birthtime.tv_nsec &&
        named.st_birthtimespec.tv_sec == self.birthtime.tv_sec && named.st_birthtimespec.tv_nsec == self.birthtime.tv_nsec &&
        [Physical(self.path) isEqual:self.path], @"Archive root changed during operation");
}
@end
static NSArray<ArchiveRoot *> *OpenRoots(NSDictionary *roots) {
    Check([roots isKindOfClass:NSDictionary.class], @"Archive roots are missing");
    NSMutableArray *result = [NSMutableArray new];
    for (NSString *prefix in [[roots allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
        Check(SafePath(prefix), @"Invalid archive root prefix"); NSString *path = roots[prefix];
        Check([path isKindOfClass:NSString.class] && [Physical(path) isEqual:path], @"Archive root must be canonical");
        for (ArchiveRoot *other in result) Check(![prefix isEqual:other.prefix] && !Below(prefix, other.prefix) && !Below(other.prefix, prefix) &&
            ![path isEqual:other.path] && !Below(path, other.path) && !Below(other.path, path), @"Archive roots overlap");
        int fd = open(path.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); struct stat st;
        Check(fd >= 0, @"Cannot open archive root");
        if (fstat(fd, &st) || !S_ISDIR(st.st_mode)) { close(fd); Check(NO, @"Invalid archive root directory"); }
        ArchiveRoot *root = [ArchiveRoot new]; root.prefix = prefix; root.path = path; root.fd = fd; root.device = st.st_dev; root.inode = st.st_ino; root.birthtime = st.st_birthtimespec; [result addObject:root];
        [root pin];
    }
    return result;
}
static NSArray<NSString *> *Names(int fd) {
    int duplicate = openat(fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); Check(duplicate >= 0, @"Cannot enumerate archive source");
    DIR *directory = fdopendir(duplicate); if (!directory) { close(duplicate); Check(NO, @"Cannot enumerate archive directory"); }
    NSMutableArray *result = [NSMutableArray new]; struct dirent *entry; errno = 0;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        NSString *name = [NSString stringWithUTF8String:entry->d_name];
        if (!name || !SafePath(name) || [name containsString:@"/"]) { closedir(directory); Check(NO, @"Invalid source filename"); }
        [result addObject:name]; errno = 0;
    }
    int failure = errno; closedir(directory); Check(!failure, @"Cannot finish archive directory enumeration");
    return [result sortedArrayUsingSelector:@selector(compare:)];
}
static NSString *ReadLink(int fd, NSString *name) {
    char bytes[PATH_MAX]; ssize_t count = readlinkat(fd, name.fileSystemRepresentation, bytes, sizeof(bytes));
    Check(count >= 0 && count < (ssize_t)sizeof(bytes), @"Cannot read symbolic link");
    NSString *value = [[NSString alloc] initWithBytes:bytes length:(NSUInteger)count encoding:NSUTF8StringEncoding]; Check(value != nil, @"Unsupported symbolic link encoding"); return value;
}
static NSString *HashFDProgress(int fd, unsigned long long *size, void (^progress)(size_t)) {
    unsigned char buffer[128 * 1024], digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_CTX context; CC_SHA256_Init(&context);
    unsigned long long total = 0; ssize_t count;
    while ((count = read(fd, buffer, sizeof(buffer))) != 0) {
        if (count < 0 && errno == EINTR) continue;
        Check(count > 0, @"Cannot read archive file"); CC_SHA256_Update(&context, buffer, (CC_LONG)count); total += (unsigned long long)count; if (progress) progress((size_t)count);
    }
    CC_SHA256_Final(digest, &context); if (size) *size = total; return Hex(digest, sizeof(digest));
}
static NSDictionary *HashPath(NSString *path, SHDWStateProgress progress) {
    int fd = open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); struct stat before, after;
    Check(fd >= 0, @"Cannot open archive file");
    @try {
        Check(!fstat(fd, &before) && S_ISREG(before.st_mode) && before.st_nlink == 1, @"Archive is not a private regular file");
        unsigned long long size = 0; __block unsigned long long consumed = 0;
        NSString *digest = HashFDProgress(fd, &size, ^(size_t count) { consumed += count; Progress(progress, @"verify_archive", consumed, 0); });
        Check(!fstat(fd, &after) && SameStat(before, after), @"Archive file changed while reading");
        return @{@"sha256":digest, @"archiveSize":@(size)};
    } @finally { close(fd); }
}
static void WriteHeader(struct archive *writer, NSDictionary *entry, unsigned long long size) {
    struct archive_entry *header = archive_entry_new(); Check(header != NULL, @"Cannot allocate archive entry");
    @try {
        archive_entry_set_pathname_utf8(header, [entry[@"path"] UTF8String]);
        NSString *type = entry[@"type"]; archive_entry_set_filetype(header, [type isEqual:@"file"] ? AE_IFREG : [type isEqual:@"directory"] ? AE_IFDIR : AE_IFLNK);
        archive_entry_set_perm(header, [entry[@"mode"] unsignedIntValue]); archive_entry_set_uid(header, [entry[@"uid"] longLongValue]); archive_entry_set_gid(header, [entry[@"gid"] longLongValue]);
        archive_entry_set_mtime(header, [entry[@"mtime"] longLongValue], [entry[@"mtimeNsec"] longValue]); archive_entry_set_size(header, (la_int64_t)size);
        archive_entry_set_birthtime(header, [entry[@"birthtime"] longLongValue], [entry[@"birthtimeNsec"] longValue]);
        NSString *creation = [NSString stringWithFormat:@"%lld:%09ld", [entry[@"birthtime"] longLongValue], [entry[@"birthtimeNsec"] longValue]];
        archive_entry_xattr_add_entry(header, "org.shadow.birthtime", creation.UTF8String, strlen(creation.UTF8String));
        if ([type isEqual:@"symlink"]) archive_entry_set_symlink_utf8(header, [entry[@"target"] UTF8String]);
        if (entry[@"hardlink"]) archive_entry_set_hardlink_utf8(header, [entry[@"hardlink"] UTF8String]);
        Check(archive_write_header(writer, header) == ARCHIVE_OK, @"Cannot write archive entry header");
    } @finally { archive_entry_free(header); }
}
static void WriteBytes(struct archive *writer, const void *bytes, size_t length) {
    const unsigned char *cursor = bytes;
    while (length) { la_ssize_t written = archive_write_data(writer, cursor, length); Check(written > 0, @"Cannot write compressed archive data"); cursor += written; length -= (size_t)written; }
}
static void CaptureNode(struct archive *writer, ArchiveRoot *root, int parent, NSString *name, NSString *relative,
                        NSMutableArray *entries, NSMutableDictionary *inodes, SHDWStateProgress progress, unsigned long long *bytes) {
    [root pin]; Progress(progress, @"capture", *bytes, entries.count); struct stat before, after;
    Check(!fstatat(parent, name.fileSystemRepresentation, &before, AT_SYMLINK_NOFOLLOW), @"Cannot inspect archive source");
    Check(before.st_dev == root.device, @"Archive source crosses a filesystem boundary");
    NSString *path = relative.length ? [root.prefix stringByAppendingPathComponent:relative] : root.prefix;
    NSMutableDictionary *entry = [StatEntry(path, before) mutableCopy];
    if (S_ISDIR(before.st_mode)) {
        int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); Check(fd >= 0, @"Cannot open source directory");
        @try {
            Check(!fstat(fd, &after) && SameStat(before, after), @"Source directory changed before capture"); WriteHeader(writer, entry, 0); [entries addObject:entry];
            for (NSString *child in Names(fd)) {
                NSString *next = relative.length ? [relative stringByAppendingPathComponent:child] : child;
                if (!Excluded(root.prefix, next)) CaptureNode(writer, root, fd, child, next, entries, inodes, progress, bytes);
            }
            Check(!fstat(fd, &after) && SameStat(before, after), @"Source directory changed during capture");
        } @finally { close(fd); }
    } else if (S_ISLNK(before.st_mode)) {
        entry[@"target"] = ReadLink(parent, name); WriteHeader(writer, entry, 0); [entries addObject:entry];
        Check(!fstatat(parent, name.fileSystemRepresentation, &after, AT_SYMLINK_NOFOLLOW) && SameStat(before, after), @"Source link changed during capture");
    } else {
        Check(before.st_size >= 0, @"Invalid source file size");
        NSDictionary *first = inodes[InodeKey(before)];
        if (first) {
            entry[@"hardlink"] = first[@"path"]; entry[@"size"] = first[@"size"]; entry[@"sha256"] = first[@"sha256"];
            for (NSString *key in @[@"mode", @"uid", @"gid", @"mtime", @"mtimeNsec", @"birthtime", @"birthtimeNsec"]) Check([entry[key] isEqual:first[key]], @"Source hardlink metadata changed");
            Check((unsigned long long)before.st_size == [first[@"size"] unsignedLongLongValue], @"Source hardlink size changed");
            WriteHeader(writer, entry, 0); [entries addObject:entry];
            Check(!fstatat(parent, name.fileSystemRepresentation, &after, AT_SYMLINK_NOFOLLOW) && SameStat(before, after), @"Source hardlink changed during capture");
            Check(archive_write_finish_entry(writer) == ARCHIVE_OK, @"Cannot finish hardlink entry"); Progress(progress, @"capture", *bytes, entries.count); return;
        }
        int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); Check(fd >= 0, @"Cannot open source file"); unsigned char *buffer = NULL;
        @try {
            Check(!fstat(fd, &after) && SameStat(before, after), @"Source file changed before capture"); WriteHeader(writer, entry, (unsigned long long)before.st_size);
            buffer = malloc(Chunk); Check(buffer != NULL, @"Cannot allocate streaming source buffer");
            unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_CTX context; CC_SHA256_Init(&context);
            unsigned long long total = 0; ssize_t count;
            while ((count = read(fd, buffer, Chunk)) != 0) {
                if (count < 0 && errno == EINTR) continue; Check(count > 0, @"Cannot read source file");
                Progress(progress, @"capture", *bytes, entries.count); WriteBytes(writer, buffer, (size_t)count); CC_SHA256_Update(&context, buffer, (CC_LONG)count); total += (unsigned long long)count; *bytes += (unsigned long long)count;
                Progress(progress, @"capture", *bytes, entries.count);
            }
            Check(total == (unsigned long long)before.st_size && !fstat(fd, &after) && SameStat(before, after), @"Source file changed during capture");
            CC_SHA256_Final(digest, &context); entry[@"size"] = @(total); entry[@"sha256"] = Hex(digest, sizeof(digest)); [entries addObject:entry]; inodes[InodeKey(before)] = entry;
        } @finally { free(buffer); close(fd); }
    }
    Check(archive_write_finish_entry(writer) == ARCHIVE_OK, @"Cannot finish archive entry"); Progress(progress, @"capture", *bytes, entries.count);
}
static NSString *EntryPath(struct archive_entry *entry) {
    const char *raw = archive_entry_pathname_utf8(entry); if (!raw) raw = archive_entry_pathname(entry);
    NSString *path = raw ? [NSString stringWithUTF8String:raw] : nil;
    if ([path hasSuffix:@"/"] && archive_entry_filetype(entry) == AE_IFDIR) path = [path substringToIndex:path.length - 1];
    Check(SafePath(path), @"Archive contains an unsafe path"); return path;
}
static BOOL IntegralNumber(id value) {
    return [value isKindOfClass:NSNumber.class] && isfinite([value doubleValue]) && [value compare:@([value longLongValue])] == NSOrderedSame;
}
static NSDictionary *InfoEntries(NSDictionary *info) {
    Check([info isKindOfClass:NSDictionary.class] && [info[@"format"] isEqual:@"pax"] && [info[@"compression"] isEqual:@"zstd"] &&
        [info[@"entries"] isKindOfClass:NSArray.class] && [info[@"entries"] count] <= 1000000 && [info[@"sha256"] isKindOfClass:NSString.class] && [info[@"sha256"] length] == 64 && [info[@"archiveSize"] isKindOfClass:NSNumber.class], @"Invalid archive information");
    NSMutableDictionary *result = [NSMutableDictionary new];
    for (NSDictionary *entry in info[@"entries"]) {
        Check([entry isKindOfClass:NSDictionary.class] && SafePath(entry[@"path"]) && !result[entry[@"path"]] &&
            [@[@"file", @"directory", @"symlink"] containsObject:entry[@"type"]], @"Archive information contains duplicate or invalid entries");
        for (NSString *key in @[@"mode", @"uid", @"gid", @"mtime", @"mtimeNsec", @"birthtime", @"birthtimeNsec"]) Check(IntegralNumber(entry[key]), @"Archive metadata is incomplete or nonintegral");
        Check([entry[@"mode"] unsignedLongLongValue] <= 07777 && [entry[@"mtimeNsec"] unsignedLongLongValue] < 1000000000 && [entry[@"birthtimeNsec"] unsignedLongLongValue] < 1000000000, @"Invalid archive permissions or timestamp");
        Check([entry[@"uid"] longLongValue] >= 0 && [entry[@"uid"] unsignedLongLongValue] <= UINT_MAX && [entry[@"gid"] longLongValue] >= 0 && [entry[@"gid"] unsignedLongLongValue] <= UINT_MAX, @"Invalid archived ownership");
        if ([entry[@"type"] isEqual:@"file"]) Check(IntegralNumber(entry[@"size"]) && [entry[@"size"] longLongValue] >= 0 && [entry[@"sha256"] isKindOfClass:NSString.class] && [entry[@"sha256"] length] == 64, @"Invalid file archive information");
        if ([entry[@"type"] isEqual:@"symlink"]) Check([entry[@"target"] isKindOfClass:NSString.class] && [entry[@"target"] length], @"Invalid archive link target");
        if (entry[@"hardlink"]) {
            NSDictionary *target = SafePath(entry[@"hardlink"]) ? result[entry[@"hardlink"]] : nil;
            Check([entry[@"type"] isEqual:@"file"] && [target[@"type"] isEqual:@"file"] && !target[@"hardlink"], @"Invalid or forward archive hardlink target");
            for (NSString *key in @[@"mode", @"uid", @"gid", @"mtime", @"mtimeNsec", @"birthtime", @"birthtimeNsec", @"size", @"sha256"]) Check([entry[key] isEqual:target[key]], @"Archive hardlink metadata differs");
        }
        result[entry[@"path"]] = entry;
    }
    NSDictionary *sources = info[@"sourceRoots"]; Check([sources isKindOfClass:NSDictionary.class], @"Archive source roots are missing");
    for (NSString *prefix in sources) {
        NSString *source = sources[prefix]; Check(SafePath(prefix) && [source isKindOfClass:NSString.class] && source.isAbsolutePath && SafePath([source substringFromIndex:1]) && [result[prefix][@"type"] isEqual:@"directory"], @"Invalid archive source root mapping");
        for (NSString *other in sources) if (![other isEqual:prefix]) Check(!Below(prefix, other) && ![source isEqual:sources[other]] && !Below(source, sources[other]), @"Archive source roots overlap");
    }
    for (NSString *path in result) {
        if (result[path][@"hardlink"]) {
            BOOL scoped = NO, targetScoped = NO;
            for (NSString *prefix in sources) { if (Below(path, prefix)) scoped = YES; if (Below(result[path][@"hardlink"], prefix)) targetScoped = YES; }
            Check(scoped && targetScoped, @"Archive hardlink escapes container scope");
        }
        NSString *parent = path.stringByDeletingLastPathComponent;
        while (parent.length) { if (result[parent]) Check([result[parent][@"type"] isEqual:@"directory"], @"Archive parent is not a directory"); parent = parent.stringByDeletingLastPathComponent; }
        for (NSString *prefix in sources) if (Below(path, prefix)) Check(!Excluded(prefix, [path substringFromIndex:prefix.length + 1]), @"Archive includes protected container metadata");
    }
    return result;
}
typedef void (^ReadEvent)(NSDictionary *, const void *, size_t, BOOL);
static void ReadArchive(NSString *path, NSDictionary *info, SHDWStateProgress progress, ReadEvent event) {
    NSDictionary *expected = InfoEntries(info);
    int fd = open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); Check(fd >= 0, @"Cannot open compressed archive");
    struct archive *reader = NULL;
    @try {
        struct stat before, after, named; Check(!fstat(fd, &before) && S_ISREG(before.st_mode) && before.st_nlink == 1, @"Archive is not a private regular file");
        unsigned long long size = 0; __block unsigned long long consumed = 0;
        NSString *digest = HashFDProgress(fd, &size, ^(size_t count) { consumed += count; Progress(progress, @"verify_archive", consumed, 0); });
        Check([digest isEqual:info[@"sha256"]] && [@(size) isEqual:info[@"archiveSize"]] && !fstat(fd, &after) && SameStat(before, after) && lseek(fd, 0, SEEK_SET) == 0, @"Archive checksum or size differs");
        reader = archive_read_new(); Check(reader != NULL, @"Cannot allocate archive reader");
        Check(archive_read_support_filter_zstd(reader) == ARCHIVE_OK && archive_read_support_format_tar(reader) == ARCHIVE_OK && archive_read_open_fd(reader, fd, Chunk) == ARCHIVE_OK, @"Cannot read tar.zst archive");
        NSMutableSet *seen = [NSMutableSet new]; struct archive_entry *header; int status; unsigned long long bytes = 0;
        while ((status = archive_read_next_header(reader, &header)) == ARCHIVE_OK) {
            Check(archive_filter_code(reader, 0) == ARCHIVE_FILTER_ZSTD && (archive_format(reader) & ARCHIVE_FORMAT_BASE_MASK) == ARCHIVE_FORMAT_TAR, @"Unexpected archive format or compression");
            NSString *name = EntryPath(header); NSDictionary *entry = expected[name];
            Check(entry && ![seen containsObject:name] && !archive_entry_sparse_count(header), @"Archive contains an extra, duplicate, or linked entry");
            const char *rawHardlink = archive_entry_hardlink_utf8(header); if (!rawHardlink) rawHardlink = archive_entry_hardlink(header);
            NSString *hardlink = rawHardlink ? [NSString stringWithUTF8String:rawHardlink] : nil;
            Check((!rawHardlink && !entry[@"hardlink"]) || (hardlink && [hardlink isEqual:entry[@"hardlink"]] && [seen containsObject:hardlink]), @"Archive hardlink target differs or precedes its content");
            [seen addObject:name]; mode_t type = archive_entry_filetype(header); if (hardlink) { Check(type == 0 || type == AE_IFREG, @"Archive hardlink is not regular"); type = AE_IFREG; }
            NSString *kind = type == AE_IFREG ? @"file" : type == AE_IFDIR ? @"directory" : type == AE_IFLNK ? @"symlink" : @"unsupported";
            Check([entry[@"type"] isEqual:kind] && (archive_entry_perm(header) & 07777) == [entry[@"mode"] unsignedIntValue] &&
                archive_entry_uid(header) == [entry[@"uid"] longLongValue] && archive_entry_gid(header) == [entry[@"gid"] longLongValue] &&
                archive_entry_mtime(header) == [entry[@"mtime"] longLongValue] && archive_entry_mtime_nsec(header) == [entry[@"mtimeNsec"] longValue], @"Archive entry metadata differs");
            if (archive_entry_birthtime_is_set(header)) Check(archive_entry_birthtime(header) == [entry[@"birthtime"] longLongValue] && archive_entry_birthtime_nsec(header) == [entry[@"birthtimeNsec"] longValue], @"Archive creation time differs");
            NSString *creation = [NSString stringWithFormat:@"%lld:%09ld", [entry[@"birthtime"] longLongValue], [entry[@"birthtimeNsec"] longValue]];
            BOOL creationFound = NO; const char *attribute; const void *attributeValue; size_t attributeSize;
            archive_entry_xattr_reset(header);
            while (archive_entry_xattr_next(header, &attribute, &attributeValue, &attributeSize) == ARCHIVE_OK) {
                if (!strcmp(attribute, "org.shadow.birthtime")) { Check(attributeSize == strlen(creation.UTF8String) && !memcmp(attributeValue, creation.UTF8String, attributeSize), @"Archive creation metadata differs"); creationFound = YES; }
            }
            Check(creationFound, @"Archive creation metadata is missing");
            if (type == AE_IFLNK) {
                const char *raw = archive_entry_symlink_utf8(header); if (!raw) raw = archive_entry_symlink(header);
                NSString *target = raw ? [NSString stringWithUTF8String:raw] : nil; Check([target isEqual:entry[@"target"]], @"Archive symbolic link target differs");
            }
            la_int64_t size = archive_entry_size(header); Check(size >= 0 && (type == AE_IFREG && !hardlink ? (unsigned long long)size == [entry[@"size"] unsignedLongLongValue] : size == 0), @"Archive entry size differs");
            if (event) event(entry, NULL, 0, NO);
            unsigned char buffer[128 * 1024], hash[CC_SHA256_DIGEST_LENGTH]; CC_SHA256_CTX context; CC_SHA256_Init(&context);
            unsigned long long total = 0; la_ssize_t count;
            while ((count = archive_read_data(reader, buffer, sizeof(buffer))) != 0) {
                Check(count > 0 && type == AE_IFREG, @"Archive data is truncated or malformed"); total += (unsigned long long)count; bytes += (unsigned long long)count;
                Check(total <= (unsigned long long)size, @"Archive file exceeded its declared size"); CC_SHA256_Update(&context, buffer, (CC_LONG)count);
                if (event) event(entry, buffer, (size_t)count, NO); Progress(progress, @"verify", bytes, seen.count);
            }
            Check(total == (unsigned long long)size, @"Archive file is truncated"); CC_SHA256_Final(hash, &context);
            if (type == AE_IFREG && !hardlink) Check([Hex(hash, sizeof(hash)) isEqual:entry[@"sha256"]], @"Archived file checksum differs");
            if (event) event(entry, NULL, 0, YES);
        }
        Check(status == ARCHIVE_EOF && seen.count == expected.count, @"Archive is truncated or has missing entries");
        Check(archive_read_close(reader) == ARCHIVE_OK, @"Cannot finish compressed archive validation"); Progress(progress, @"verify", bytes, seen.count);
        Check(!fstat(fd, &after) && SameStat(before, after) && !lstat(path.fileSystemRepresentation, &named) && SameStat(before, named), @"Archive file changed during validation");
    } @finally { if (reader) archive_read_free(reader); close(fd); }
}
static ArchiveRoot *RootForPath(NSString *path, NSArray<ArchiveRoot *> *roots, NSString **relative) {
    for (ArchiveRoot *root in roots) if ([path isEqual:root.prefix] || Below(path, root.prefix)) { if (relative) *relative = [path isEqual:root.prefix] ? @"" : [path substringFromIndex:root.prefix.length + 1]; return root; }
    return nil;
}
static int ParentFD(ArchiveRoot *root, NSString *relative, BOOL create, NSString **leaf) {
    Check(SafePath(relative), @"Invalid extraction path"); NSArray *pieces = [relative componentsSeparatedByString:@"/"];
    int fd = dup(root.fd); Check(fd >= 0, @"Cannot duplicate destination root");
    @try {
        for (NSUInteger i = 0; i + 1 < pieces.count; i++) {
            NSString *piece = pieces[i];
            if (create && mkdirat(fd, piece.fileSystemRepresentation, 0700)) Check(errno == EEXIST, @"Cannot create archive parent directory");
            int next = openat(fd, piece.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); Check(next >= 0, @"Extraction parent is not a real directory");
            struct stat st; if (fstat(next, &st) || st.st_dev != root.device) { close(next); Check(NO, @"Extraction parent crosses a filesystem boundary"); } close(fd); fd = next;
        }
        if (leaf) *leaf = pieces.lastObject; return fd;
    } @catch (NSException *exception) { close(fd); @throw exception; }
}
static NSString *RelocatedLink(NSString *target, NSDictionary *sources, NSDictionary *destinations) {
    if (!target.isAbsolutePath) return target;
    for (NSString *piece in target.pathComponents) if ([piece isEqual:@".."] || [piece isEqual:@"."]) return target;
    NSString *candidate = [target hasPrefix:@"/var/"] ? [@"/private" stringByAppendingString:target] : target;
    for (NSString *prefix in sources) {
        NSString *old = sources[prefix];
        if ([candidate isEqual:old] || Below(candidate, old)) return [destinations[prefix] stringByAppendingString:[candidate substringFromIndex:old.length]];
    }
    return target;
}
static void CreationTimeFD(int fd, NSDictionary *entry) {
    struct attrlist attributes = {0}; attributes.bitmapcount = ATTR_BIT_MAP_COUNT; attributes.commonattr = ATTR_CMN_CRTIME;
    struct timespec creation = {.tv_sec = [entry[@"birthtime"] longLongValue], .tv_nsec = [entry[@"birthtimeNsec"] longValue]};
    Check(!fsetattrlist(fd, &attributes, &creation, sizeof(creation), 0), @"Cannot restore archived creation time");
    struct stat st; Check(!fstat(fd, &st) && st.st_birthtimespec.tv_sec == creation.tv_sec && st.st_birthtimespec.tv_nsec == creation.tv_nsec, @"Restored creation time does not match");
}
static void MetadataFD(int fd, NSDictionary *entry, BOOL timestamps) {
    struct stat st; Check(!fstat(fd, &st), @"Cannot inspect restored metadata");
    uid_t uid = [entry[@"uid"] unsignedIntValue]; gid_t gid = [entry[@"gid"] unsignedIntValue];
    if (st.st_uid != uid || st.st_gid != gid) Check(!fchown(fd, uid, gid), @"Cannot restore archived ownership");
    Check(!fchmod(fd, [entry[@"mode"] unsignedIntValue]), @"Cannot restore archived permissions");
    if (!timestamps) return;
    struct timespec times[2] = {{.tv_nsec = UTIME_OMIT}, {.tv_sec = [entry[@"mtime"] longLongValue], .tv_nsec = [entry[@"mtimeNsec"] longValue]}};
    Check(!futimens(fd, times), @"Cannot restore archived modification time");
    CreationTimeFD(fd, entry);
}
static int OpenDirectoryAt(int parent, NSString *leaf, dev_t device) {
    int fd = openat(parent, leaf.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC); Check(fd >= 0, @"Restored directory conflicts with a link");
    struct stat st;
    if (fstat(fd, &st) || st.st_dev != device) { close(fd); Check(NO, @"Restored directory crosses a filesystem boundary"); }
    return fd;
}

@implementation SHDWStateArchive
+ (NSDictionary *)captureRoots:(NSDictionary<NSString *,NSString *> *)roots payloads:(NSDictionary<NSString *,NSData *> *)payloads toPath:(NSString *)path progress:(SHDWStateProgress)progress error:(NSError **)error {
    struct archive *writer = NULL; int fd = -1; BOOL created = NO, complete = NO;
    @try {
        NSArray *opened = OpenRoots(roots); Check([payloads isKindOfClass:NSDictionary.class] && (roots.count || payloads.count), @"Invalid or empty archive sources");
        Check([Physical(path.stringByDeletingLastPathComponent) isEqual:path.stringByDeletingLastPathComponent] && SafePath(path.lastPathComponent), @"Archive destination parent must be canonical");
        for (ArchiveRoot *root in opened) Check(![path isEqual:root.path] && !Below(path, root.path), @"Archive destination overlaps its source");
        for (NSString *name in payloads) {
            NSData *data = payloads[name]; Check(SafePath(name) && [data isKindOfClass:NSData.class] && data.length <= PayloadLimit, @"Invalid or oversized archive payload");
            for (ArchiveRoot *root in opened) Check(![name isEqual:root.prefix] && !Below(name, root.prefix) && !Below(root.prefix, name), @"Archive payload overlaps a container");
            for (NSString *other in payloads) if (![other isEqual:name]) Check(!Below(name, other), @"Archive payload paths overlap");
        }
        fd = open(path.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600); Check(fd >= 0, @"Cannot create private archive file"); created = YES;
        writer = archive_write_new(); Check(writer != NULL, @"Cannot allocate archive writer");
        Check(archive_write_set_format_pax(writer) == ARCHIVE_OK && archive_write_add_filter_zstd(writer) == ARCHIVE_OK &&
            archive_write_set_filter_option(writer, "zstd", "compression-level", "1") == ARCHIVE_OK && archive_write_open_fd(writer, fd) == ARCHIVE_OK, @"Cannot initialize PAX and Zstd archive");
        NSMutableArray *entries = [NSMutableArray new]; NSMutableDictionary *inodes = [NSMutableDictionary new]; unsigned long long bytes = 0;
        for (ArchiveRoot *root in opened) CaptureNode(writer, root, root.fd, @".", @"", entries, inodes, progress, &bytes);
        for (NSString *name in [[payloads allKeys] sortedArrayUsingSelector:@selector(compare:)]) {
            NSData *data = payloads[name]; unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
            NSMutableDictionary *entry = [@{@"path":name, @"type":@"file", @"mode":@0600, @"uid":@(getuid()), @"gid":@(getgid()), @"mtime":@0, @"mtimeNsec":@0, @"birthtime":@0, @"birthtimeNsec":@0, @"size":@(data.length), @"sha256":Hex(digest, sizeof(digest))} mutableCopy];
            WriteHeader(writer, entry, data.length);
            for (NSUInteger offset = 0; offset < data.length;) { NSUInteger count = MIN(Chunk, data.length - offset); WriteBytes(writer, (const unsigned char *)data.bytes + offset, count); offset += count; bytes += count; Progress(progress, @"capture", bytes, entries.count); }
            Check(archive_write_finish_entry(writer) == ARCHIVE_OK, @"Cannot finish bounded archive payload"); [entries addObject:entry];
        }
        Check(archive_write_close(writer) == ARCHIVE_OK && !fsync(fd), @"Cannot flush completed archive"); archive_write_free(writer); writer = NULL; close(fd); fd = -1;
        for (ArchiveRoot *root in opened) [root pin];
        NSMutableDictionary *info = [@{@"format":@"pax", @"compression":@"zstd", @"compressionLevel":@1, @"entries":entries, @"sourceRoots":[roots copy]} mutableCopy]; [info addEntriesFromDictionary:HashPath(path, progress)];
        NSError *verification = nil;
        Check([self verifyRoots:roots info:info progress:progress error:&verification], verification.localizedDescription ?: @"Capture sources changed before completion");
        ReadArchive(path, info, progress, nil); complete = YES; return info;
    } @catch (NSException *exception) { PublishError(error, exception); return nil; }
    @finally { if (writer) archive_write_free(writer); if (fd >= 0) close(fd); if (created && !complete) unlink(path.fileSystemRepresentation); }
}
+ (BOOL)verifyPath:(NSString *)path info:(NSDictionary *)info progress:(SHDWStateProgress)progress error:(NSError **)error {
    @try { ReadArchive(path, info, progress, nil); return YES; } @catch (NSException *exception) { PublishError(error, exception); return NO; }
}
+ (NSDictionary<NSString *,NSData *> *)readPayloadsAtPath:(NSString *)path info:(NSDictionary *)info names:(NSArray<NSString *> *)names error:(NSError **)error {
    @try {
        NSDictionary *entries = InfoEntries(info); Check([names isKindOfClass:NSArray.class] && names.count <= 64 && [NSSet setWithArray:names].count == names.count, @"Invalid payload request");
        NSMutableDictionary *payloads = [NSMutableDictionary new];
        for (NSString *name in names) { NSDictionary *entry = entries[name]; Check(SafePath(name) && [entry[@"type"] isEqual:@"file"] && !entry[@"hardlink"] && [entry[@"size"] unsignedLongLongValue] <= PayloadLimit, @"Missing or oversized bounded payload"); payloads[name] = [NSMutableData new]; }
        ReadArchive(path, info, nil, ^(NSDictionary *entry, const void *bytes, size_t length, BOOL finished) { (void)finished; NSMutableData *data = payloads[entry[@"path"]]; if (data && length) { Check(data.length + length <= PayloadLimit, @"Payload exceeded its bound"); [data appendBytes:bytes length:length]; } });
        return payloads;
    } @catch (NSException *exception) { PublishError(error, exception); return nil; }
}
+ (BOOL)restorePath:(NSString *)path info:(NSDictionary *)info roots:(NSDictionary<NSString *,NSString *> *)roots progress:(SHDWStateProgress)progress error:(NSError **)error {
    __block int current = -1;
    @try {
        NSArray<ArchiveRoot *> *opened = OpenRoots(roots); Check([[NSSet setWithArray:roots.allKeys] isEqual:[NSSet setWithArray:[info[@"sourceRoots"] allKeys]]], @"Restore root scope differs");
        ReadArchive(path, info, progress, nil);
        NSMutableArray *directories = [NSMutableArray new], *links = [NSMutableArray new]; __block unsigned long long written = 0; __block NSUInteger completed = 0;
        ReadArchive(path, info, nil, ^(NSDictionary *entry, const void *bytes, size_t length, BOOL finished) {
            NSString *relative = nil; ArchiveRoot *root = RootForPath(entry[@"path"], opened, &relative); if (!root) return; [root pin];
            Progress(progress, @"restore", written, completed);
            if (length) { Check(current >= 0, @"No restored file is open"); const unsigned char *cursor = bytes; size_t remaining = length; while (remaining) { ssize_t count = write(current, cursor, remaining); if (count < 0 && errno == EINTR) continue; Check(count > 0, @"Cannot write restored file"); cursor += count; remaining -= (size_t)count; written += (unsigned long long)count; } Progress(progress, @"restore", written, completed); return; }
            if (finished) { if (current >= 0) { MetadataFD(current, entry, YES); Check(!fsync(current), @"Cannot flush restored file"); close(current); current = -1; } completed++; return; }
            NSString *type = entry[@"type"];
            if ([type isEqual:@"symlink"]) { [links addObject:entry]; return; }
            if ([type isEqual:@"directory"]) {
                [directories addObject:entry]; if (!relative.length) return;
                NSString *leaf = nil; int parent = ParentFD(root, relative, YES, &leaf);
                @try { if (mkdirat(parent, leaf.fileSystemRepresentation, 0700)) Check(errno == EEXIST, @"Cannot create restored directory"); int child = OpenDirectoryAt(parent, leaf, root.device); close(child); } @finally { close(parent); } return;
            }
            if (entry[@"hardlink"]) {
                NSString *targetRelative = nil; ArchiveRoot *targetRoot = RootForPath(entry[@"hardlink"], opened, &targetRelative);
                Check(targetRoot && targetRelative.length && relative.length, @"Invalid restored hardlink location"); [targetRoot pin];
                NSString *targetLeaf = nil, *leaf = nil; int sourceParent = ParentFD(targetRoot, targetRelative, NO, &targetLeaf), parent = -1, targetFD = -1;
                @try {
                    parent = ParentFD(root, relative, NO, &leaf);
                    targetFD = openat(sourceParent, targetLeaf.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); Check(targetFD >= 0, @"Cannot open restored hardlink target");
                    struct stat pinned, named, linked;
                    Check(!fstat(targetFD, &pinned) && S_ISREG(pinned.st_mode) && pinned.st_dev == root.device, @"Invalid restored hardlink target");
                    Check(!linkat(sourceParent, targetLeaf.fileSystemRepresentation, parent, leaf.fileSystemRepresentation, 0), @"Cannot create restored hardlink");
                    Check(!fstatat(sourceParent, targetLeaf.fileSystemRepresentation, &named, AT_SYMLINK_NOFOLLOW) && !fstatat(parent, leaf.fileSystemRepresentation, &linked, AT_SYMLINK_NOFOLLOW) && S_ISREG(linked.st_mode) && named.st_dev == pinned.st_dev && named.st_ino == pinned.st_ino && linked.st_dev == pinned.st_dev && linked.st_ino == pinned.st_ino, @"Restored hardlink target changed");
                } @finally { if (targetFD >= 0) close(targetFD); if (parent >= 0) close(parent); close(sourceParent); } return;
            }
            Check(relative.length && [type isEqual:@"file"], @"Invalid restored file location"); NSString *leaf = nil; int parent = ParentFD(root, relative, YES, &leaf);
            @try { current = openat(parent, leaf.fileSystemRepresentation, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600); Check(current >= 0, @"Restore would overwrite an existing file or link"); } @finally { close(parent); }
        });
        for (NSDictionary *entry in links) {
            Progress(progress, @"restore", written, completed);
            NSString *relative = nil; ArchiveRoot *root = RootForPath(entry[@"path"], opened, &relative); [root pin]; Check(relative.length, @"Invalid root symbolic link"); NSString *leaf = nil; int parent = ParentFD(root, relative, NO, &leaf);
            @try {
                NSString *target = RelocatedLink(entry[@"target"], info[@"sourceRoots"], roots); Check(!symlinkat(target.fileSystemRepresentation, parent, leaf.fileSystemRepresentation), @"Cannot create restored symbolic link");
                struct stat st; Check(!fstatat(parent, leaf.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW), @"Cannot inspect restored link");
                uid_t uid = [entry[@"uid"] unsignedIntValue]; gid_t gid = [entry[@"gid"] unsignedIntValue]; if (st.st_uid != uid || st.st_gid != gid) Check(!fchownat(parent, leaf.fileSystemRepresentation, uid, gid, AT_SYMLINK_NOFOLLOW), @"Cannot restore symbolic link ownership");
                Check(!fchmodat(parent, leaf.fileSystemRepresentation, [entry[@"mode"] unsignedIntValue], AT_SYMLINK_NOFOLLOW), @"Cannot restore symbolic link mode");
                struct timespec times[2] = {{.tv_nsec = UTIME_OMIT}, {.tv_sec = [entry[@"mtime"] longLongValue], .tv_nsec = [entry[@"mtimeNsec"] longValue]}}; Check(!utimensat(parent, leaf.fileSystemRepresentation, times, AT_SYMLINK_NOFOLLOW), @"Cannot restore symbolic link modification time");
                int link = openat(parent, leaf.fileSystemRepresentation, O_RDONLY | O_SYMLINK | O_CLOEXEC);
                Check(link >= 0, @"Cannot safely open symbolic link creation time");
                @try {
                    struct stat pinned, named; Check(!fstat(link, &pinned) && S_ISLNK(pinned.st_mode) && pinned.st_dev == st.st_dev && pinned.st_ino == st.st_ino, @"Symbolic link changed before creation time restoration");
                    CreationTimeFD(link, entry);
                    Check(!fstatat(parent, leaf.fileSystemRepresentation, &named, AT_SYMLINK_NOFOLLOW) && named.st_dev == pinned.st_dev && named.st_ino == pinned.st_ino, @"Symbolic link changed during creation time restoration");
                } @finally { close(link); }
            } @finally { close(parent); }
        }
        NSArray *ordered = [directories sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *left, NSDictionary *right) { return [right[@"path"] compare:left[@"path"]]; }];
        for (NSDictionary *entry in ordered) {
            Progress(progress, @"restore", written, completed);
            NSString *relative = nil; ArchiveRoot *root = RootForPath(entry[@"path"], opened, &relative); [root pin]; int fd;
            if (!relative.length) fd = dup(root.fd);
            else { NSString *leaf = nil; int parent = ParentFD(root, relative, NO, &leaf); @try { fd = OpenDirectoryAt(parent, leaf, root.device); } @finally { close(parent); } }
            Check(fd >= 0, @"Cannot open restored directory metadata"); @try { MetadataFD(fd, entry, relative.length > 0); } @finally { close(fd); }
        }
        for (ArchiveRoot *root in opened) [root pin]; Progress(progress, @"restore", written, completed); return YES;
    } @catch (NSException *exception) { PublishError(error, exception); return NO; }
    @finally { if (current >= 0) close(current); }
}
+ (BOOL)verifyRoots:(NSDictionary<NSString *,NSString *> *)roots info:(NSDictionary *)info progress:(SHDWStateProgress)progress error:(NSError **)error {
    @try {
        NSDictionary *expected = InfoEntries(info); NSArray<ArchiveRoot *> *opened = OpenRoots(roots); Check([[NSSet setWithArray:roots.allKeys] isEqual:[NSSet setWithArray:[info[@"sourceRoots"] allKeys]]], @"Verification root scope differs");
        NSMutableSet *seen = [NSMutableSet new]; NSMutableDictionary *identities = [NSMutableDictionary new], *inodePaths = [NSMutableDictionary new], *verifiedStats = [NSMutableDictionary new], *verifiedHashes = [NSMutableDictionary new]; __block unsigned long long bytes = 0;
        __block void (^visit)(ArchiveRoot *, int, NSString *, NSString *);
        __block __weak void (^recurse)(ArchiveRoot *, int, NSString *, NSString *);
        visit = ^(ArchiveRoot *root, int parent, NSString *name, NSString *relative) {
            [root pin]; struct stat st; Check(!fstatat(parent, name.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW), @"Cannot inspect restored root entry");
            Check(st.st_dev == root.device, @"Restored root crosses a filesystem boundary");
            NSString *path = relative.length ? [root.prefix stringByAppendingPathComponent:relative] : root.prefix; NSDictionary *entry = expected[path], *actual = StatEntry(path, st);
            Check(entry && ![seen containsObject:path], @"Restored root contains an extra entry"); [seen addObject:path];
            for (NSString *key in @[@"type", @"mode", @"uid", @"gid", @"mtime", @"mtimeNsec", @"birthtime", @"birthtimeNsec"]) {
                if (!relative.length && [@[@"mtime", @"mtimeNsec", @"birthtime", @"birthtimeNsec"] containsObject:key]) continue;
                Check([actual[key] isEqual:entry[key]], @"Restored entry metadata differs");
            }
            if (S_ISDIR(st.st_mode)) {
                int fd = OpenDirectoryAt(parent, name, root.device);
                @try {
                    struct stat openedStat, finalStat, namedStat; Check(!fstat(fd, &openedStat) && SameStat(st, openedStat), @"Restored directory changed before verification");
                    for (NSString *child in Names(fd)) { NSString *next = relative.length ? [relative stringByAppendingPathComponent:child] : child; if (!Excluded(root.prefix, next)) recurse(root, fd, child, next); }
                    Check(!fstat(fd, &finalStat) && SameStat(st, finalStat) && !fstatat(parent, name.fileSystemRepresentation, &namedStat, AT_SYMLINK_NOFOLLOW) && SameStat(st, namedStat), @"Restored directory changed during verification");
                } @finally { close(fd); }
            }
            else if (S_ISLNK(st.st_mode)) Check([ReadLink(parent, name) isEqual:RelocatedLink(entry[@"target"], info[@"sourceRoots"], roots)], @"Restored symbolic link target differs");
            else {
                Check((unsigned long long)st.st_size == [entry[@"size"] unsignedLongLongValue], @"Restored file size differs");
                NSString *identity = entry[@"hardlink"] ?: path, *inode = InodeKey(st);
                Check(!identities[identity] || [identities[identity] isEqual:inode], @"Restored hardlink identity differs");
                Check(!inodePaths[inode] || [inodePaths[inode] isEqual:identity], @"Unexpected restored file alias");
                identities[identity] = inode; inodePaths[inode] = identity; int fd = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC); Check(fd >= 0, @"Cannot verify restored file");
                @try {
                    struct stat openedStat, finalStat, namedStat;
                    Check(!fstat(fd, &openedStat) && SameStat(st, openedStat), @"Restored file changed before verification");
                    unsigned long long size = (unsigned long long)st.st_size; NSString *digest = verifiedHashes[inode];
                    if (digest) {
                        struct stat previous; [verifiedStats[inode] getBytes:&previous length:sizeof(previous)];
                        Check(SameStat(previous, st), @"Hardlink content changed during verification");
                    } else {
                        digest = HashFDProgress(fd, &size, ^(size_t count) { bytes += count; Progress(progress, @"verify_roots", bytes, seen.count); });
                        verifiedStats[inode] = [NSData dataWithBytes:&st length:sizeof(st)]; verifiedHashes[inode] = digest;
                    }
                    Check(!fstat(fd, &finalStat) && SameStat(st, finalStat) && !fstatat(parent, name.fileSystemRepresentation, &namedStat, AT_SYMLINK_NOFOLLOW) && SameStat(st, namedStat), @"Restored file changed during verification");
                    Check(size == [entry[@"size"] unsignedLongLongValue] && [digest isEqual:entry[@"sha256"]], @"Restored file checksum differs");
                } @finally { close(fd); }
            }
            Progress(progress, @"verify_roots", bytes, seen.count);
        };
        recurse = visit;
        @try { for (ArchiveRoot *root in opened) visit(root, root.fd, @".", @""); } @finally { visit = nil; }
        NSUInteger count = 0; for (NSString *path in expected) if (RootForPath(path, opened, NULL)) count++;
        Check(count == seen.count, @"Restored root has missing entries"); return YES;
    } @catch (NSException *exception) { PublishError(error, exception); return NO; }
}
@end
