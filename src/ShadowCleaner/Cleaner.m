#import "Cleaner.h"
#import <Security/Security.h>
#import <LocalAuthentication/LocalAuthentication.h>
#import <CommonCrypto/CommonDigest.h>
#include <mach-o/loader.h>
#include <mach-o/fat.h>
#include <mach-o/dyld.h>
#include <libkern/OSByteOrder.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <dirent.h>
#include <unistd.h>
#include <signal.h>
#include <grp.h>
#include <dlfcn.h>
#include <errno.h>
#include <spawn.h>
#include <poll.h>
#include <time.h>

static NSString *const Metadata = @".com.apple.mobile_container_manager.metadata.plist";
static NSString *const AppRoot = @"/private/var/containers/Bundle/Application";
static NSString *const DataRoot = @"/private/var/mobile/Containers/Data/Application";
static NSString *const GroupRoot = @"/private/var/mobile/Containers/Shared/AppGroup";
static NSString *const SessionRoot = @"/private/var/tmp/shadow-cleaner";
static BOOL mutated;
static NSArray *remainingSteps;
static OSStatus keychainStatus;
static NSString *keychainClass;
static NSString *keychainPhase;
static NSUInteger keychainCount;
static NSMutableDictionary *keychainClassCounts;
static pid_t keychainParent;
static NSDictionary *failureDetails;

static void Fail(NSString *message) {
    @throw [NSException exceptionWithName:@"CleanupFailure" reason:message userInfo:nil];
}
static void Require(BOOL condition, NSString *message) { if (!condition) Fail(message); }
static NSString *Canonical(NSString *path) {
    char value[PATH_MAX];
    Require(path.length && realpath(path.fileSystemRepresentation, value), @"Cannot resolve target path");
    return [NSString stringWithUTF8String:value];
}
static BOOL Inside(NSString *path, NSString *root) {
    return [path hasPrefix:[root stringByAppendingString:@"/"]];
}
static BOOL Identifier(NSString *value) {
    if (![value isKindOfClass:NSString.class] || !value.length || value.length > 255 || [value isEqual:@"."] || [value isEqual:@".."]) return NO;
    return [value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_"] invertedSet]].location == NSNotFound;
}
static BOOL BundleIdentifier(NSString *value) {
    if (!Identifier(value)) return NO;
    NSArray *components = [value componentsSeparatedByString:@"."];
    if (components.count < 2) return NO;
    for (NSString *component in components) if (!component.length) return NO;
    return YES;
}
static BOOL ExecutableName(NSString *value) {
    return [value isKindOfClass:NSString.class] && value.length && value.length <= 255 &&
        ![value isEqual:@"."] && ![value isEqual:@".."] && ![value containsString:@"/"] &&
        [value rangeOfCharacterFromSet:[NSCharacterSet characterSetWithRange:NSMakeRange(0, 1)]].location == NSNotFound;
}
static NSArray *Children(NSString *path) {
    NSError *error = nil;
    NSArray *result = [NSFileManager.defaultManager contentsOfDirectoryAtPath:path error:&error];
    if (!result && error.code == NSFileReadNoSuchFileError) return @[];
    if (!result) {
        NSError *underlying = error.userInfo[NSUnderlyingErrorKey];
        failureDetails = @{@"path":path, @"domain":error.domain ?: @"", @"code":@(error.code),
            @"underlyingDomain":underlying.domain ?: @"", @"underlyingCode":@(underlying.code),
            @"uid":@(getuid()), @"euid":@(geteuid()), @"gid":@(getgid()), @"egid":@(getegid())};
    }
    Require(result != nil, @"Cannot enumerate target storage");
    return [result sortedArrayUsingSelector:@selector(compare:)];
}
static NSDictionary *ReadPlist(NSString *path) {
    struct stat info;
    Require(!lstat(path.fileSystemRepresentation, &info) && S_ISREG(info.st_mode) && info.st_size < 16 * 1024 * 1024, @"Invalid target metadata");
    NSDictionary *value = [NSDictionary dictionaryWithContentsOfFile:path];
    Require([value isKindOfClass:NSDictionary.class], @"Unreadable target metadata");
    return value;
}
static NSArray *InstalledApps(void) {
    NSMutableArray *result = [NSMutableArray new];
    for (NSString *uuid in Children(AppRoot)) {
        if (![[NSUUID alloc] initWithUUIDString:uuid]) continue;
        NSString *directory = [AppRoot stringByAppendingPathComponent:uuid];
        Require([Canonical(directory) isEqual:directory], @"Unexpected installed container alias");
        for (NSString *name in Children(directory)) {
            if (![name.pathExtension isEqual:@"app"]) continue;
            NSString *app = [directory stringByAppendingPathComponent:name];
            Require([Canonical(app) isEqual:app], @"Unexpected installed bundle alias");
            [result addObject:app];
        }
    }
    return result;
}
static NSArray *Bundles(NSString *app) {
    NSMutableArray *result = [NSMutableArray arrayWithObject:app];
    NSString *plugins = [app stringByAppendingPathComponent:@"PlugIns"];
    for (NSString *name in Children(plugins)) {
        if (![name.pathExtension isEqual:@"appex"]) continue;
        NSString *extension = [plugins stringByAppendingPathComponent:name];
        Require([Canonical(extension) isEqual:extension] && Inside(extension, app), @"Invalid extension bundle");
        [result addObject:extension];
    }
    return result;
}
static uint32_t BE32(const uint8_t *bytes) { uint32_t value; memcpy(&value, bytes, 4); return OSSwapBigToHostInt32(value); }
static uint64_t BE64(const uint8_t *bytes) { uint64_t value; memcpy(&value, bytes, 8); return OSSwapBigToHostInt64(value); }
static NSDictionary *ReadExecutableEntitlements(NSString *path) {
    Require([Canonical(path) isEqual:path], @"Invalid executable alias");
    NSData *data = [NSData dataWithContentsOfFile:path options:NSDataReadingMappedIfSafe error:NULL];
    Require(data.length >= sizeof(struct mach_header_64), @"Unreadable target signature");
    const uint8_t *bytes = data.bytes; NSUInteger length = data.length, base = 0, size = length;
    uint32_t magic; memcpy(&magic, bytes, 4);
    if (BE32(bytes) == FAT_MAGIC || BE32(bytes) == FAT_MAGIC_64) {
        BOOL wide = BE32(bytes) == FAT_MAGIC_64; uint32_t count = BE32(bytes + 4);
        Require(count <= 32 && length >= 8 + count * (wide ? 32 : 20), @"Invalid fat signature");
        BOOL found = NO;
        for (uint32_t i = 0; i < count; i++) {
            const uint8_t *arch = bytes + 8 + i * (wide ? 32 : 20);
            if (BE32(arch) != CPU_TYPE_ARM64) continue;
            uint64_t offset = wide ? BE64(arch + 8) : BE32(arch + 8);
            uint64_t extent = wide ? BE64(arch + 16) : BE32(arch + 12);
            Require(offset <= length && extent <= length - offset, @"Invalid architecture bounds");
            base = (NSUInteger)offset; size = (NSUInteger)extent; found = YES; break;
        }
        Require(found, @"Target has no supported executable architecture");
        memcpy(&magic, bytes + base, 4);
    }
    Require(magic == MH_MAGIC_64 && size >= sizeof(struct mach_header_64), @"Unsupported signature format");
    struct mach_header_64 header; memcpy(&header, bytes + base, sizeof(header));
    Require(header.ncmds < 4096 && header.sizeofcmds <= size - sizeof(header), @"Invalid executable commands");
    NSUInteger cursor = sizeof(header), end = cursor + header.sizeofcmds;
    for (uint32_t i = 0; i < header.ncmds; i++) {
        Require(cursor + sizeof(struct load_command) <= end, @"Invalid signature command");
        struct load_command command; memcpy(&command, bytes + base + cursor, sizeof(command));
        Require(command.cmdsize >= sizeof(command) && command.cmdsize <= end - cursor, @"Invalid signature command size");
        if (command.cmd == LC_CODE_SIGNATURE) {
            Require(command.cmdsize >= sizeof(struct linkedit_data_command), @"Invalid signature link");
            struct linkedit_data_command link; memcpy(&link, bytes + base + cursor, sizeof(link));
            Require(link.dataoff <= size && link.datasize <= size - link.dataoff && link.datasize >= 12, @"Invalid signature bounds");
            const uint8_t *blob = bytes + base + link.dataoff;
            Require(BE32(blob) == 0xfade0cc0 && BE32(blob + 4) <= link.datasize, @"Invalid signature blob");
            uint32_t blobLength = BE32(blob + 4), count = BE32(blob + 8);
            Require(count <= 4096 && 12 + (uint64_t)count * 8 <= blobLength, @"Invalid signature slots");
            BOOL hasDER = NO;
            for (uint32_t j = 0; j < count; j++) {
                if (BE32(blob + 12 + j * 8) == 7) hasDER = YES;
                if (BE32(blob + 12 + j * 8) != 5) continue;
                uint32_t offset = BE32(blob + 16 + j * 8);
                Require(offset <= blobLength && blobLength - offset >= 8, @"Invalid entitlement bounds");
                uint32_t extent = BE32(blob + offset + 4);
                Require(BE32(blob + offset) == 0xfade7171 && extent >= 8 && extent <= blobLength - offset, @"Invalid entitlement blob");
                NSData *xml = [NSData dataWithBytes:blob + offset + 8 length:extent - 8];
                id value = [NSPropertyListSerialization propertyListWithData:xml options:0 format:NULL error:NULL];
                Require([value isKindOfClass:NSDictionary.class], @"Unreadable signed entitlements");
                return value;
            }
            Require(!hasDER, @"DER-only signed entitlements unavailable");
            return @{};
        }
        cursor += command.cmdsize;
    }
    Fail(@"Target signature unavailable"); return nil;
}
static NSDictionary *ExecutableEntitlements(NSString *path) {
    @autoreleasepool { return ReadExecutableEntitlements(path); }
}

static NSDictionary *Entitlements(NSString *bundle) {
    NSDictionary *info = ReadPlist([bundle stringByAppendingPathComponent:@"Info.plist"]);
    NSString *name = info[@"CFBundleExecutable"];
    Require(ExecutableName(name), @"Invalid target executable");
    return ExecutableEntitlements([bundle stringByAppendingPathComponent:name]);
}
static NSArray *StringList(id value) {
    if (!value) return @[];
    Require([value isKindOfClass:NSArray.class], @"Invalid signed access groups");
    for (id item in value) Require(Identifier(item), @"Ambiguous signed access group");
    return value;
}
static NSArray *KeychainGroups(NSDictionary *entitlements) {
    id groups = entitlements[@"keychain-access-groups"];
    if (groups) return StringList(groups);
    NSString *applicationID = entitlements[@"application-identifier"];
    return Identifier(applicationID) ? @[applicationID] : @[];
}
static NSString *ValidateBundleIdentity(NSDictionary *info, NSDictionary *entitlements, NSString *mainID, NSString *team) {
    NSString *identifier = info[@"CFBundleIdentifier"], *applicationID = entitlements[@"application-identifier"];
    Require(BundleIdentifier(identifier) && ([identifier isEqual:mainID] || [identifier hasPrefix:[mainID stringByAppendingString:@"."]]), @"Extension is outside the selected application namespace");
    NSString *suffix = [@"." stringByAppendingString:identifier];
    Require([applicationID isKindOfClass:NSString.class] && [applicationID hasSuffix:suffix] && applicationID.length > suffix.length, @"Application identifier does not match its signed identity");
    NSString *prefix = [applicationID substringToIndex:applicationID.length - suffix.length];
    Require(Identifier(prefix) && ![prefix containsString:@"."] && (!team || [team isEqual:prefix]), @"Extension signing team does not match the selected application");
    return prefix;
}
static NSArray *Containers(NSString *root, NSString *identifier) {
    NSMutableArray *result = [NSMutableArray new];
    for (NSString *uuid in Children(root)) {
        if (![[NSUUID alloc] initWithUUIDString:uuid]) continue;
        NSString *path = [root stringByAppendingPathComponent:uuid];
        Require([Canonical(path) isEqual:path], @"Unexpected data container alias");
        NSDictionary *metadata = ReadPlist([path stringByAppendingPathComponent:Metadata]);
        if (![metadata[@"MCMMetadataIdentifier"] isEqual:identifier]) continue;
        struct stat st; Require(!stat(path.fileSystemRepresentation, &st), @"Unreadable container identity");
        [result addObject:@{@"path":path, @"identifier":identifier, @"device":@(st.st_dev), @"inode":@(st.st_ino)}];
    }
    Require(result.count <= 1, @"Ambiguous data container ownership"); return result;
}
static NSString *Hash(id object) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:object options:NSJSONWritingSortedKeys error:NULL];
    Require(data != nil, @"Cannot encode cleanup identity");
    unsigned char digest[CC_SHA256_DIGEST_LENGTH]; CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *result = [NSMutableString new]; for (NSUInteger i = 0; i < sizeof(digest); i++) [result appendFormat:@"%02x", digest[i]];
    return result;
}
static NSDictionary *Resolve(NSString *identifier) {
    Require(BundleIdentifier(identifier) && ![identifier hasPrefix:@"com.apple."] && ![identifier hasPrefix:@"me.jjolano.shadow"], @"Protected or invalid application");
    NSArray *apps = InstalledApps(); NSMutableArray *matches = [NSMutableArray new];
    for (NSString *app in apps) if ([ReadPlist([app stringByAppendingPathComponent:@"Info.plist"])[@"CFBundleIdentifier"] isEqual:identifier]) [matches addObject:app];
    Require(matches.count == 1, @"Application not installed or identity ambiguous");
    NSString *app = matches.firstObject; NSMutableSet *groups = [NSMutableSet new], *keychain = [NSMutableSet new];
    NSMutableArray *identifiers = [NSMutableArray new], *containers = [NSMutableArray new], *shared = [NSMutableArray new], *executables = [NSMutableArray new];
    NSString *team = nil;
    for (NSString *bundle in Bundles(app)) {
        NSDictionary *info = ReadPlist([bundle stringByAppendingPathComponent:@"Info.plist"]);
        NSString *bid = info[@"CFBundleIdentifier"];
        Require(BundleIdentifier(bid) && ![identifiers containsObject:bid], @"Invalid or duplicate extension identifier"); [identifiers addObject:bid];
        NSDictionary *entitlements = Entitlements(bundle);
        team = ValidateBundleIdentity(info, entitlements, identifier, team);
        struct stat executableStat;
        NSString *executable = [bundle stringByAppendingPathComponent:info[@"CFBundleExecutable"]];
        Require(!stat(executable.fileSystemRepresentation, &executableStat) && S_ISREG(executableStat.st_mode), @"Invalid executable identity");
        [executables addObject:@{@"path":executable, @"inode":@(executableStat.st_ino), @"device":@(executableStat.st_dev), @"size":@(executableStat.st_size), @"modified":@(executableStat.st_mtime)}];
        [groups addObjectsFromArray:StringList(entitlements[@"com.apple.security.application-groups"])];
        [keychain addObjectsFromArray:KeychainGroups(entitlements)];
        [containers addObjectsFromArray:Containers(DataRoot, bid)];
    }
    Require(containers.count > 0 && [containers[0][@"identifier"] isEqual:identifier], @"Application data container unavailable");
    NSMutableSet *sharedKeys = [NSMutableSet new], *sharedGroups = [NSMutableSet new];
    NSMutableArray *ownershipIssues = [NSMutableArray new];
    BOOL ownershipComplete = YES;
    for (NSString *other in apps) {
        if ([other isEqual:app]) continue;
        NSArray *otherBundles = Bundles(other);
        for (NSString *bundle in otherBundles) {
            NSString *claimedID = ReadPlist([bundle stringByAppendingPathComponent:@"Info.plist"])[@"CFBundleIdentifier"];
            Require(BundleIdentifier(claimedID) && ![identifiers containsObject:claimedID], @"Application identity is claimed by another installed bundle");
        }
        for (NSString *bundle in otherBundles) {
            @try {
                NSDictionary *entitlements = Entitlements(bundle);
                for (NSString *group in KeychainGroups(entitlements)) if ([keychain containsObject:group]) [sharedKeys addObject:group];
                for (NSString *group in StringList(entitlements[@"com.apple.security.application-groups"])) if ([groups containsObject:group]) [sharedGroups addObject:group];
            } @catch (NSException *exception) {
                ownershipComplete = NO;
                NSString *bid = ReadPlist([bundle stringByAppendingPathComponent:@"Info.plist"])[@"CFBundleIdentifier"];
                [ownershipIssues addObject:@{@"bundleID":bid, @"reason":exception.reason ?: @"Unreadable ownership"}];
            }
        }
    }
    for (NSString *group in [[groups allObjects] sortedArrayUsingSelector:@selector(compare:)]) {
        if (!ownershipComplete || [sharedGroups containsObject:group]) { [shared addObject:group]; continue; }
        [containers addObjectsFromArray:Containers(GroupRoot, group)];
    }
    struct stat bundleStat; Require(!stat(app.fileSystemRepresentation, &bundleStat), @"Unreadable installed application");
    NSDictionary *target = @{@"bundleID":identifier, @"bundlePath":app, @"identifiers":identifiers, @"team":team,
        @"containers":containers, @"executables":executables, @"keychainGroups":[[keychain allObjects] sortedArrayUsingSelector:@selector(compare:)],
        @"preservedSharedGroups":shared, @"sharedKeychainGroups":[[sharedKeys allObjects] sortedArrayUsingSelector:@selector(compare:)],
        @"ownershipComplete":@(ownershipComplete), @"ownershipIssues":ownershipIssues, @"bundleInode":@(bundleStat.st_ino)};
    return @{@"target":target, @"token":Hash(target)};
}
static BOOL Prefix(NSString *path, NSString *root) { return [path isEqual:root] || Inside(path, root); }
static NSString *Category(NSString *relative) {
    for (NSString *root in @[@"StoreKit", @"_MASReceipt", @"Library/StoreKit", @"Library/Caches/StoreKit"]) if (Prefix(relative, root)) return @"receipts";
    for (NSString *root in @[@"Library/WebKit", @"Library/HTTPStorages", @"Library/Cookies", @"Library/Caches/WebKit"]) if (Prefix(relative, root)) return @"web";
    for (NSString *root in @[@"Library/Preferences", @"Library/Caches", @"tmp"]) if (Prefix(relative, root)) return @"preferences";
    return @"files";
}
static BOOL CategoryAncestor(NSString *relative) {
    return [@[@"Library", @"Library/Caches"] containsObject:relative];
}
static BOOL RemoveAt(int parent, const char *name) {
    if (!name || !name[0] || !strcmp(name, ".") || !strcmp(name, "..") || strchr(name, '/')) { errno = EINVAL; return NO; }
    struct stat st;
    if (fstatat(parent, name, &st, AT_SYMLINK_NOFOLLOW)) return errno == ENOENT;
    if (S_ISDIR(st.st_mode)) {
        int fd = openat(parent, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (fd < 0) return NO;
        DIR *directory = fdopendir(fd);
        if (!directory) { close(fd); return NO; }
        BOOL success = YES; struct dirent *entry;
        errno = 0;
        while ((entry = readdir(directory))) {
            if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
            if (!RemoveAt(fd, entry->d_name)) { success = NO; break; }
            errno = 0;
        }
        if (errno) success = NO;
        closedir(directory);
        if (!success) return NO;
        mutated = YES; return unlinkat(parent, name, AT_REMOVEDIR) == 0;
    }
    mutated = YES; return unlinkat(parent, name, 0) == 0;
}
static void Walk(int parent, NSString *relative, NSString *step, BOOL perform, NSUInteger *count) {
    int fd = dup(parent); Require(fd >= 0, @"Cannot duplicate container descriptor");
    DIR *directory = fdopendir(fd); Require(directory != NULL, @"Cannot inspect container");
    NSMutableArray *names = [NSMutableArray new]; struct dirent *entry; errno = 0;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        NSString *name = [NSString stringWithUTF8String:entry->d_name]; Require(name != nil, @"Invalid container entry");
        [names addObject:name]; errno = 0;
    }
    int scanError = errno; closedir(directory); Require(!scanError, @"Cannot enumerate container entries");
    for (NSString *name in names) {
        if (!relative.length && [name hasPrefix:@".com.apple.mobile_container_manager."]) continue;
        NSString *path = relative.length ? [relative stringByAppendingPathComponent:name] : name;
        struct stat st; Require(!fstatat(parent, name.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW), @"Container changed during cleanup");
        if (CategoryAncestor(path) || [path isEqual:@"tmp"] || [path isEqual:@"Documents"]) {
            Require(S_ISDIR(st.st_mode) && !S_ISLNK(st.st_mode), @"Protected storage ancestor is not a directory");
            int child = openat(parent, name.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            Require(child >= 0, @"Cannot open protected storage ancestor");
            @try { Walk(child, path, step, perform, count); } @finally { close(child); }
            continue;
        }
        if (![Category(path) isEqual:step]) continue;
        (*count)++;
        if (perform) Require(RemoveAt(parent, name.fileSystemRepresentation), @"Unable to remove application data");
    }
}
static void ContainerStep(NSDictionary *target, NSString *step, BOOL perform, NSUInteger *count) {
    for (NSDictionary *container in target[@"containers"]) {
        NSString *path = container[@"path"];
        Require([ReadPlist([path stringByAppendingPathComponent:Metadata])[@"MCMMetadataIdentifier"] isEqual:container[@"identifier"]], @"Container ownership changed");
        int fd = open(path.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        Require(fd >= 0, @"Cannot open application container");
        @try {
            struct stat st; Require(!fstat(fd, &st) && st.st_ino == [container[@"inode"] unsignedLongLongValue] && (uint64_t)st.st_dev == [container[@"device"] unsignedLongLongValue], @"Container identity changed");
            Walk(fd, @"", step, perform, count);
            if (perform && [container[@"identifier"] isEqual:target[@"bundleID"]]) {
                for (NSString *name in @[@"Documents", @"Library", @"tmp"]) {
                    if (!mkdirat(fd, name.fileSystemRepresentation, 0755)) Require(!fchownat(fd, name.fileSystemRepresentation, 501, 501, AT_SYMLINK_NOFOLLOW), @"Cannot restore container ownership");
                    else Require(errno == EEXIST, @"Cannot restore application directories");
                }
            }
        } @finally { close(fd); }
    }
}
static void ExternalStep(NSDictionary *target, NSString *step, BOOL perform, NSUInteger *count) {
    NSArray *roots = [step isEqual:@"preferences"] ? @[@"Preferences", @"Preferences/ByHost", @"Caches", @"Saved Application State", @"SplashBoard/Snapshots"] : [step isEqual:@"web"] ? @[@"WebKit", @"HTTPStorages", @"Cookies"] : @[];
    for (NSString *rootName in roots) {
        NSString *root = [@"/private/var/mobile/Library" stringByAppendingPathComponent:rootName];
        int fd = open(root.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (fd < 0 && errno == ENOENT) continue;
        Require(fd >= 0, @"Cannot inspect application system storage");
        @try {
            for (NSString *bid in target[@"identifiers"]) {
                NSArray *names = [rootName isEqual:@"Preferences"] ? @[[bid stringByAppendingString:@".plist"]] :
                    [rootName isEqual:@"Cookies"] ? @[bid, [bid stringByAppendingString:@".binarycookies"]] :
                    [rootName isEqual:@"Saved Application State"] ? @[bid, [bid stringByAppendingString:@".savedState"]] : @[bid];
                if ([rootName isEqual:@"Preferences/ByHost"]) {
                    NSMutableArray *matches = [NSMutableArray new];
                    for (NSString *name in Children(root)) {
                        if (![name.pathExtension isEqual:@"plist"]) continue;
                        NSString *base = name.stringByDeletingPathExtension;
                        if ([[NSUUID alloc] initWithUUIDString:base.pathExtension] && [base.stringByDeletingPathExtension isEqual:bid]) [matches addObject:name];
                    }
                    names = matches;
                }
                for (NSString *name in names) {
                    struct stat st; if (fstatat(fd, name.fileSystemRepresentation, &st, AT_SYMLINK_NOFOLLOW)) { Require(errno == ENOENT, @"Cannot inspect application residual"); continue; }
                    (*count)++; if (perform) Require(RemoveAt(fd, name.fileSystemRepresentation), @"Unable to remove application residual");
                }
            }
        } @finally { close(fd); }
    }
}
static void BundleReceipts(NSDictionary *target, BOOL perform, NSUInteger *count) {
    for (NSString *bundle in Bundles(target[@"bundlePath"])) {
        int root = open(bundle.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        Require(root >= 0, @"Cannot inspect bundle receipt");
        @try {
            for (NSString *name in @[@"StoreKit", @"_MASReceipt"]) {
                int directory = openat(root, name.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
                if (directory < 0 && errno == ENOENT) continue;
                Require(directory >= 0, @"Invalid bundle receipt directory");
                @try {
                    struct stat st;
                    if (fstatat(directory, "receipt", &st, AT_SYMLINK_NOFOLLOW)) { Require(errno == ENOENT, @"Cannot inspect receipt file"); continue; }
                    Require(S_ISREG(st.st_mode) && st.st_nlink == 1, @"Invalid bundle receipt file");
                    (*count)++;
                    if (perform) { mutated = YES; Require(!unlinkat(directory, "receipt", 0), @"Unable to remove receipt file"); }
                } @finally { close(directory); }
            }
        } @finally { close(root); }
    }
}
static NSArray *PreferenceQueries(NSDictionary *target) {
    NSMutableArray *queries = [NSMutableArray new];
    for (NSString *identifier in target[@"identifiers"]) [queries addObject:@{@"domain":identifier, @"container":@""}];
    for (NSDictionary *container in target[@"containers"]) {
        NSMutableSet *domains = [NSMutableSet setWithObject:container[@"identifier"]];
        for (NSString *relative in @[@"Library/Preferences", @"Library/Preferences/ByHost"]) {
            NSString *directory = [container[@"path"] stringByAppendingPathComponent:relative];
            struct stat st;
            if (lstat(directory.fileSystemRepresentation, &st)) { Require(errno == ENOENT, @"Cannot inspect preference domains"); continue; }
            Require(S_ISDIR(st.st_mode) && !S_ISLNK(st.st_mode), @"Invalid preference directory");
            for (NSString *name in Children(directory)) {
                if (![name.pathExtension isEqual:@"plist"]) continue;
                NSString *domain = name.stringByDeletingPathExtension;
                if ([relative hasSuffix:@"ByHost"] && [[NSUUID alloc] initWithUUIDString:domain.pathExtension]) domain = domain.stringByDeletingPathExtension;
                Require(Identifier(domain), @"Invalid application preference domain"); [domains addObject:domain];
            }
        }
        for (NSString *domain in domains) [queries addObject:@{@"domain":domain, @"container":container[@"path"]}];
    }
    return queries;
}
static void PreferenceCache(NSArray *queries, BOOL verify, BOOL refresh) {
    typedef void (*Flush)(CFStringRef, CFStringRef);
    typedef CFDictionaryRef (*Copy)(CFArrayRef, CFStringRef, CFStringRef, CFStringRef, CFStringRef);
    Flush flush = dlsym(RTLD_DEFAULT, "_CFPreferencesFlushCachesForIdentifier");
    Copy copy = dlsym(RTLD_DEFAULT, "_CFPreferencesCopyMultipleWithContainer");
    Require(flush && copy, @"Preference cache APIs unavailable");
    if (!verify && !refresh) return;
    NSMutableSet *flushed = [NSMutableSet new];
    for (NSDictionary *query in queries) {
        NSString *domain = query[@"domain"], *container = query[@"container"];
        if (refresh && ![flushed containsObject:domain]) {
            CFPreferencesSynchronize((__bridge CFStringRef)domain, CFSTR("mobile"), kCFPreferencesAnyHost);
            CFPreferencesSynchronize((__bridge CFStringRef)domain, CFSTR("mobile"), kCFPreferencesCurrentHost);
            flush((__bridge CFStringRef)domain, CFSTR("mobile")); [flushed addObject:domain];
        }
        if (!verify) continue;
        for (NSNumber *byHost in @[@NO, @YES]) {
            CFDictionaryRef values = copy(NULL, (__bridge CFStringRef)domain, CFSTR("mobile"), byHost.boolValue ? kCFPreferencesCurrentHost : kCFPreferencesAnyHost, container.length ? (__bridge CFStringRef)container : NULL);
            BOOL empty = !values || (CFGetTypeID(values) == CFDictionaryGetTypeID() && CFDictionaryGetCount(values) == 0);
            if (values) CFRelease(values);
            Require(empty, @"Application preferences remained in the system cache");
        }
    }
}
static NSArray *Running(NSString *app) {
    int (*list)(void *, int) = dlsym(RTLD_DEFAULT, "proc_listallpids");
    int (*pathForPID)(int, void *, uint32_t) = dlsym(RTLD_DEFAULT, "proc_pidpath");
    Require(list && pathForPID, @"Process inspection unavailable");
    int count = list(NULL, 0); Require(count > 0 && count < 32768, @"Cannot enumerate application processes");
    NSMutableData *data = [NSMutableData dataWithLength:(count + 256) * sizeof(pid_t)];
    int actual = list(data.mutableBytes, (int)data.length); Require(actual >= 0 && actual * sizeof(pid_t) <= data.length, @"Process list changed during inspection");
    NSMutableArray *result = [NSMutableArray new]; pid_t *pids = data.mutableBytes;
    for (int i = 0; i < actual; i++) {
        char path[PATH_MAX] = {0}; if (pathForPID(pids[i], path, sizeof(path)) <= 0) continue;
        char canonical[PATH_MAX]; if (!realpath(path, canonical)) continue;
        if (Inside([NSString stringWithUTF8String:canonical], app)) [result addObject:@(pids[i])];
    }
    return result;
}
static void Stop(NSString *app) {
    for (NSNumber *pid in Running(app)) Require(!kill(pid.intValue, SIGKILL) || errno == ESRCH, @"Cannot stop target application");
    for (int i = 0; i < 30; i++) { if (!Running(app).count) return; usleep(100000); }
    Fail(@"Target application is still running");
}
static NSMutableDictionary *KeychainQuery(NSString *group, id itemClass) {
    NSMutableDictionary *query = [@{(__bridge id)kSecClass:itemClass, (__bridge id)kSecAttrAccessGroup:group,
        (__bridge id)kSecAttrSynchronizable:(__bridge id)kSecAttrSynchronizableAny} mutableCopy];
    LAContext *context = [LAContext new]; context.interactionNotAllowed = YES;
    query[(__bridge id)kSecUseAuthenticationContext] = context;
    return query;
}
static int KeychainWork(NSArray *groups, BOOL clear, BOOL verifyEmpty) {
    NSArray *classes = @[(__bridge id)kSecClassIdentity, (__bridge id)kSecClassGenericPassword, (__bridge id)kSecClassInternetPassword, (__bridge id)kSecClassCertificate, (__bridge id)kSecClassKey];
    keychainStatus = errSecSuccess;
    keychainCount = 0;
    keychainClassCounts = [NSMutableDictionary new];
    if (!clear) for (NSString *itemClass in classes) keychainClassCounts[itemClass] = @0;
    if (clear) {
        for (NSString *group in groups) {
            for (id itemClass in classes) {
                keychainClass = itemClass; keychainPhase = @"delete";
                if (keychainParent && getppid() != keychainParent) return 5;
                keychainStatus = SecItemDelete((__bridge CFDictionaryRef)KeychainQuery(group, itemClass));
                if (keychainStatus != errSecSuccess && keychainStatus != errSecItemNotFound) return 2;
            }
        }
        return 0;
    }
    for (NSString *group in groups) {
        for (id itemClass in classes) {
            keychainClass = itemClass; keychainPhase = clear || verifyEmpty ? @"verify" : @"inspect";
            NSMutableDictionary *query = KeychainQuery(group, itemClass);
            query[(__bridge id)kSecReturnAttributes] = @YES; query[(__bridge id)kSecMatchLimit] = (__bridge id)kSecMatchLimitAll;
            CFTypeRef value = NULL; keychainStatus = SecItemCopyMatching((__bridge CFDictionaryRef)query, &value);
            keychainCount = 0; BOOL validType = YES;
            if (keychainStatus == errSecSuccess && !value) validType = NO;
            if (value) {
                CFTypeID type = CFGetTypeID(value);
                if (type == CFArrayGetTypeID()) keychainCount = (NSUInteger)CFArrayGetCount(value);
                else if (type == CFDictionaryGetTypeID()) keychainCount = 1;
                else validType = NO;
                CFRelease(value);
            }
            if (keychainStatus != errSecSuccess && keychainStatus != errSecItemNotFound) return 3;
            if (!validType) { keychainStatus = errSecDecode; return 3; }
            keychainClassCounts[itemClass] = @([keychainClassCounts[itemClass] unsignedIntegerValue] + keychainCount);
            if (verifyEmpty && keychainCount) return 4;
        }
    }
    return 0;
}
static NSString *OwnExecutable(void) {
    uint32_t size = PATH_MAX; char path[PATH_MAX];
    Require(!_NSGetExecutablePath(path, &size), @"Cannot resolve cleanup worker executable");
    NSString *executable = Canonical([NSString stringWithUTF8String:path]);
    struct stat st; Require(!stat(executable.fileSystemRepresentation, &st) && S_ISREG(st.st_mode) && st.st_uid == 0 && !(st.st_mode & 022), @"Cleanup worker executable is not trusted");
    return executable;
}
static double MonotonicSeconds(void) {
    struct timespec value;
    Require(!clock_gettime(CLOCK_MONOTONIC, &value), @"Cannot read cleanup worker clock");
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}
static void ReapWorker(pid_t child, int *status) {
    kill(child, SIGKILL);
    while (waitpid(child, status, 0) < 0 && errno == EINTR) {}
}
static NSDictionary *RunBoundedLimit(NSString *executable, NSArray<NSString *> *arguments, double timeout, NSUInteger maximum) {
    NSMutableArray *values = [NSMutableArray arrayWithObject:executable]; [values addObjectsFromArray:arguments];
    char **args = calloc(values.count + 1, sizeof(char *)); Require(args != NULL, @"Cannot allocate worker arguments");
    for (NSUInteger i = 0; i < values.count; i++) args[i] = (char *)[values[i] UTF8String];
    char *environment[] = {"PATH=/usr/bin:/bin:/usr/sbin:/sbin", "HOME=/var/mobile", NULL};
    int descriptors[2]; Require(!pipe(descriptors), @"Cannot create keychain worker channel");
    posix_spawn_file_actions_t actions; posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, descriptors[1], STDOUT_FILENO);
    posix_spawn_file_actions_addclose(&actions, descriptors[0]); posix_spawn_file_actions_addclose(&actions, descriptors[1]);
    pid_t child; int spawned = posix_spawn(&child, executable.fileSystemRepresentation, &actions, NULL, (char *const *)args, environment);
    posix_spawn_file_actions_destroy(&actions); free(args); close(descriptors[1]);
    if (spawned) { close(descriptors[0]); Fail(@"Cannot start keychain worker"); }
    NSMutableData *output = [NSMutableData new]; int status = 0; BOOL reaped = NO;
    @try {
        int flags = fcntl(descriptors[0], F_GETFL);
        Require(flags >= 0 && !fcntl(descriptors[0], F_SETFL, flags | O_NONBLOCK), @"Cannot configure keychain worker channel");
        double deadline = MonotonicSeconds() + timeout;
        while (!reaped) {
            Require(MonotonicSeconds() < deadline, @"Keychain worker timed out and was stopped");
            struct pollfd channel = {.fd = descriptors[0], .events = POLLIN | POLLHUP};
            int ready = poll(&channel, 1, 100);
            Require(ready >= 0 || errno == EINTR, @"Keychain worker channel failed");
            Require(!(channel.revents & (POLLERR | POLLNVAL)), @"Keychain worker channel closed unexpectedly");
            if (ready > 0 && (channel.revents & (POLLIN | POLLHUP))) {
                char buffer[1024]; ssize_t length;
                while ((length = read(descriptors[0], buffer, sizeof(buffer))) > 0) {
                    Require(output.length + (NSUInteger)length <= maximum, @"Keychain worker response exceeded its limit");
                    [output appendBytes:buffer length:(NSUInteger)length];
                }
                Require(length >= 0 || errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR, @"Cannot read keychain worker response");
            }
            pid_t finished = waitpid(child, &status, WNOHANG);
            if (finished == child) reaped = YES;
            else Require(finished == 0 || errno == EINTR, @"Cannot wait for keychain worker");
        }
        char tail[1024]; ssize_t length;
        while ((length = read(descriptors[0], tail, sizeof(tail))) > 0) {
            Require(output.length + (NSUInteger)length <= maximum, @"Keychain worker response exceeded its limit");
            [output appendBytes:tail length:(NSUInteger)length];
        }
        Require(length >= 0 || errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR, @"Cannot finish keychain worker response");
    } @finally {
        close(descriptors[0]);
        if (!reaped) ReapWorker(child, &status);
    }
    return @{@"status":@(WIFEXITED(status) ? WEXITSTATUS(status) : -1), @"output":output};
}
static NSDictionary *RunBounded(NSString *executable, NSArray<NSString *> *arguments, double timeout) {
    return RunBoundedLimit(executable, arguments, timeout, 65536);
}
static void PrivateDirectory(NSString *directory) {
    struct stat st;
    Require([directory.stringByDeletingLastPathComponent isEqual:SessionRoot] && [directory.lastPathComponent hasPrefix:@".worker-"] &&
        [Canonical(directory) isEqual:directory] && !lstat(directory.fileSystemRepresentation, &st) && S_ISDIR(st.st_mode) && st.st_uid == 0 && (st.st_mode & 077) == 0, @"Unsafe keychain operation directory");
}
static NSDictionary *ExactEntitlements(NSDictionary *base, NSArray *groups) {
    Require([StringList(groups) isEqual:groups] && [NSSet setWithArray:groups].count == groups.count, @"Invalid exact keychain scope");
    NSMutableDictionary *entitlements = [base mutableCopy]; entitlements[@"keychain-access-groups"] = groups;
    return entitlements;
}
static NSArray *ValidatedKeychainScope(NSDictionary *target) {
    NSString *team = target[@"team"];
    Require(Identifier(team) && ![team containsString:@"."], @"Keychain signing team is unavailable");
    NSString *prefix = [team stringByAppendingString:@"."];
    NSArray *groups = StringList(target[@"keychainGroups"]);
    for (NSString *group in groups) {
        NSString *lower = group.lowercaseString;
        Require([group hasPrefix:prefix] && group.length > prefix.length && ![lower hasPrefix:@"com.apple."] && ![lower hasPrefix:@"apple."] && ![lower isEqual:@"apple"], @"Keychain group is outside the selected application's signing team");
    }
    return groups;
}
static void PreserveWorkerLoaderAnchor(NSString *parent, NSString *directory) {
    NSString *original = [parent.stringByDeletingLastPathComponent stringByAppendingPathComponent:@".jbroot"];
    struct stat link;
    if (lstat(original.fileSystemRepresentation, &link)) {
        Require(errno == ENOENT, @"Cannot inspect the installed worker loader anchor");
#if defined(THEOS_PACKAGE_SCHEME_ROOTHIDE) || defined(SHADOW_ROOTHIDE)
        Fail(@"The installed worker loader anchor is unavailable");
#else
        return;
#endif
    }
    Require(S_ISLNK(link.st_mode) && link.st_uid == 0, @"The installed worker loader anchor is not trusted");
    NSString *destination = Canonical(original); struct stat root;
    Require(!lstat(destination.fileSystemRepresentation, &root) && S_ISDIR(root.st_mode) && root.st_uid == 0 && !(root.st_mode & 022), @"The installed worker loader destination is not trusted");
    NSString *relocated = [directory stringByAppendingPathComponent:@".jbroot"];
    Require(!symlink(destination.fileSystemRepresentation, relocated.fileSystemRepresentation) && [Canonical(relocated) isEqual:destination], @"Cannot preserve the private worker loader anchor");
}
static NSDictionary *ScopedWorker(NSDictionary *target, NSString *mode, NSDictionary *request) {
    Require([target[@"ownershipComplete"] boolValue] && ![target[@"sharedKeychainGroups"] count], @"Keychain access groups are shared or ownership cannot be verified");
    NSArray *groups = ValidatedKeychainScope(target);
    if (!groups.count && ![mode hasPrefix:@"state-"]) return @{@"ok":@YES, @"classCounts":@{}, @"countsQueried":@NO};
    NSString *parent = OwnExecutable(), *identifier = target[@"bundleID"], *token = Hash(target);
    NSString *signer = Canonical([[parent.stringByDeletingLastPathComponent stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"bin/ldid"]);
    struct stat st; Require(!stat(signer.fileSystemRepresentation, &st) && S_ISREG(st.st_mode) && st.st_uid == 0 && !(st.st_mode & 022), @"Keychain worker signer is not trusted");
    NSString *template = [SessionRoot stringByAppendingPathComponent:@".worker-XXXXXX"];
    char *temporary = strdup(template.fileSystemRepresentation); Require(temporary != NULL, @"Cannot allocate keychain operation directory");
    char *created = mkdtemp(temporary); NSString *directory = created ? [NSString stringWithUTF8String:created] : nil; free(temporary);
    Require(directory != nil, @"Cannot create keychain operation directory");
    @try {
        PrivateDirectory(directory);
        NSString *worker = [directory stringByAppendingPathComponent:@"worker"], *plist = [directory stringByAppendingPathComponent:@"entitlements.plist"], *manifestPath = [directory stringByAppendingPathComponent:@"manifest.plist"];
        Require([NSFileManager.defaultManager copyItemAtPath:parent toPath:worker error:NULL] && !chmod(worker.fileSystemRepresentation, 0700), @"Cannot copy keychain worker");
        PreserveWorkerLoaderAnchor(parent, directory);
        NSDictionary *entitlements = ExactEntitlements(ExecutableEntitlements(parent), groups);
        Require([entitlements writeToFile:plist atomically:YES] && !chmod(plist.fileSystemRepresentation, 0600), @"Cannot write exact keychain entitlements");
        NSDictionary *signedResult = RunBounded(signer, @[@"-Cadhoc", [@"-S" stringByAppendingString:plist], worker], 30.0);
        Require([signedResult[@"status"] intValue] == 0 && [StringList(ExecutableEntitlements(worker)[@"keychain-access-groups"]) isEqual:groups], @"Cannot sign or verify exact keychain worker scope");
        Require(!chmod(worker.fileSystemRepresentation, 0700), @"Cannot secure signed keychain worker");
        NSDictionary *manifest = @{@"parent":parent, @"worker":worker, @"token":token, @"bundleID":identifier, @"mode":mode, @"groups":groups};
        Require([manifest writeToFile:manifestPath atomically:YES] && !chmod(manifestPath.fileSystemRepresentation, 0600), @"Cannot secure keychain worker manifest");
        if (request) {
            NSString *requestPath = [directory stringByAppendingPathComponent:@"request.plist"];
            NSData *data = [NSPropertyListSerialization dataWithPropertyList:request format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL];
            Require(data && data.length <= 16 * 1024 * 1024 && [data writeToFile:requestPath options:NSDataWritingAtomic error:NULL] && !chmod(requestPath.fileSystemRepresentation, 0600), @"Cannot secure scoped worker request");
        }
        BOOL stateWorker = [mode hasPrefix:@"state-"];
        NSDictionary *execution = RunBoundedLimit(worker, @[@"keychain-worker", identifier, token, mode], stateWorker ? 120.0 : 45.0, stateWorker ? 24 * 1024 * 1024 : 65536);
        NSData *output = execution[@"output"]; NSDictionary *response = output.length ? [NSJSONSerialization JSONObjectWithData:output options:0 error:NULL] : nil;
        Require([execution[@"status"] intValue] == 0 && [response[@"ok"] boolValue], [NSString stringWithFormat:@"Keychain %@ failed (status %@, worker %@, class %@, phase %@, count %@)", mode, response[@"securityStatus"] ?: @"unavailable", response[@"workerCode"] ?: @"unavailable", response[@"itemClass"] ?: @"unavailable", response[@"phase"] ?: @"unavailable", response[@"itemCount"] ?: response[@"error"] ?: @"unavailable"]);
        return response;
    } @finally {
        [NSFileManager.defaultManager removeItemAtPath:directory error:NULL];
    }
}
static NSDictionary *Keychain(NSDictionary *target, BOOL clear, BOOL verifyEmpty) {
    return ScopedWorker(target, clear ? @"clear" : verifyEmpty ? @"empty" : @"inspect", nil);
}
static int SessionLockForAccess(NSString *identifier, BOOL exclusive) {
    if (mkdir(SessionRoot.fileSystemRepresentation, 0700)) Require(errno == EEXIST, @"Cannot create cleanup session directory");
    struct stat st; Require(!lstat(SessionRoot.fileSystemRepresentation, &st) && S_ISDIR(st.st_mode) && st.st_uid == 0 && (st.st_mode & 077) == 0, @"Unsafe cleanup session directory");
    NSString *path = [SessionRoot stringByAppendingPathComponent:[Hash(@[identifier]) stringByAppendingString:@".lock"]];
    int fd = open(path.fileSystemRepresentation, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0 || fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != 0 || st.st_nlink != 1) { if (fd >= 0) close(fd); Fail(@"Cannot open application operation session"); }
    if (flock(fd, (exclusive ? LOCK_EX : LOCK_SH) | LOCK_NB)) { close(fd); Fail(@"An operation is already running."); }
    return fd;
}
static int SessionLock(NSString *identifier) { return SessionLockForAccess(identifier, YES); }
static NSString *SessionPath(NSString *identifier) { return [SessionRoot stringByAppendingPathComponent:[Hash(@[identifier]) stringByAppendingString:@".json"]]; }
static void SaveSession(NSString *identifier, NSDictionary *session) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:session options:0 error:NULL];
    Require([data writeToFile:SessionPath(identifier) options:NSDataWritingAtomic error:NULL], @"Cannot save cleanup progress");
    Require(!chmod(SessionPath(identifier).fileSystemRepresentation, 0600), @"Cannot secure cleanup progress");
}
#ifdef SHADOW_STATE_SUPPORT
#import "StateBackend.inc"
#endif
static NSDictionary *Execute(int argc, const char *argv[]) {
    Require(argc >= 3, @"Expected inspect, prepare, or run and an application identifier");
    NSString *command = [NSString stringWithUTF8String:argv[1]], *identifier = [NSString stringWithUTF8String:argv[2]];
    Require(geteuid() == 0 && (getuid() == 0 || getuid() == 501), @"Cleanup requires the installed privileged helper");
    Require(!setegid(0) && geteuid() == 0, @"Cannot enter the privileged filesystem context");
    if ([command isEqual:@"keychain-worker"]) {
        Require(argc == 5, @"Invalid private worker arguments");
        NSString *own = OwnExecutable();
        int (*pathForPID)(int, void *, uint32_t) = dlsym(RTLD_DEFAULT, "proc_pidpath");
        NSString *directory = own.stringByDeletingLastPathComponent; PrivateDirectory(directory);
        NSString *manifestPath = [directory stringByAppendingPathComponent:@"manifest.plist"];
        struct stat manifestStat; Require(!lstat(manifestPath.fileSystemRepresentation, &manifestStat) && S_ISREG(manifestStat.st_mode) && manifestStat.st_uid == 0 && (manifestStat.st_mode & 077) == 0 && manifestStat.st_nlink == 1, @"Unsafe keychain worker manifest");
        NSDictionary *manifest = ReadPlist(manifestPath);
        char parent[PATH_MAX] = {0};
        Require([manifest[@"worker"] isEqual:own] && [manifest[@"bundleID"] isEqual:identifier] && [manifest[@"token"] isEqual:[NSString stringWithUTF8String:argv[3]]] && [manifest[@"mode"] isEqual:[NSString stringWithUTF8String:argv[4]]] && pathForPID && pathForPID(getppid(), parent, sizeof(parent)) > 0 && [Canonical([NSString stringWithUTF8String:parent]) isEqual:manifest[@"parent"]], @"Keychain worker requires its trusted cleanup helper parent");
        struct stat parentStat; Require(!stat([manifest[@"parent"] fileSystemRepresentation], &parentStat) && S_ISREG(parentStat.st_mode) && parentStat.st_uid == 0 && !(parentStat.st_mode & 022), @"Untrusted cleanup helper parent");
        keychainParent = getppid();
        NSDictionary *scope = Resolve(identifier), *target = scope[@"target"];
        Require([scope[@"token"] isEqual:[NSString stringWithUTF8String:argv[3]]] && [target[@"ownershipComplete"] boolValue] && ![target[@"sharedKeychainGroups"] count], @"Keychain worker ownership changed");
        ValidatedKeychainScope(target);
        Require([manifest[@"groups"] isEqual:target[@"keychainGroups"]] && [StringList(ExecutableEntitlements(own)[@"keychain-access-groups"]) isEqual:target[@"keychainGroups"]], @"Keychain worker signed scope changed");
        NSString *mode = [NSString stringWithUTF8String:argv[4]];
#ifdef SHADOW_STATE_SUPPORT
        if ([mode hasPrefix:@"state-"]) return StateWorker(mode, target, directory);
#endif
        Require([@[@"inspect", @"clear", @"empty"] containsObject:mode], @"Invalid private worker mode");
        Require(!setgroups(0, NULL) && !setgid(501) && !setuid(501) && getuid() == 501 && geteuid() == 501, @"Cannot enter mobile keychain context");
        int code = KeychainWork(target[@"keychainGroups"], [mode isEqual:@"clear"], ![mode isEqual:@"inspect"]);
        return @{@"ok":@(code == 0), @"workerCode":@(code), @"securityStatus":@(keychainStatus), @"itemClass":keychainClass ?: @"", @"phase":keychainPhase ?: @"", @"itemCount":@(keychainCount),
            @"countsQueried":@(![mode isEqual:@"clear"]), @"classCounts":keychainClassCounts ?: @{},
            @"uid":@(getuid()), @"euid":@(geteuid()), @"gid":@(getgid()), @"egid":@(getegid())};
    }
#ifdef SHADOW_STATE_SUPPORT
    if ([command isEqual:@"state"]) return StateCommand(argc, argv);
#endif
    Require([@[@"inspect", @"prepare", @"run", @"recheck"] containsObject:command], @"Unknown cleanup operation");
    NSDictionary *scope = Resolve(identifier), *target = scope[@"target"];
    if ([command isEqual:@"inspect"]) {
        Require(argc == 3, @"Unexpected inspection arguments");
        return @{@"ok":@YES, @"token":scope[@"token"], @"target":target,
            @"capabilities":@{@"files":@YES, @"preferences":@YES, @"web":@YES, @"receipts":@YES,
                @"keychain":@([target[@"ownershipComplete"] boolValue] && ![target[@"sharedKeychainGroups"] count])}};
    }
    Require(argc == 5 && [scope[@"token"] isEqual:[NSString stringWithUTF8String:argv[3]]], @"Application identity changed; inspect it again");
    int lock = SessionLock(identifier);
    @try {
        NSArray *order = @[@"files", @"preferences", @"web", @"keychain", @"receipts", @"fingerprint"];
        NSString *argument = [NSString stringWithUTF8String:argv[4]];
        if ([command isEqual:@"prepare"]) {
            NSArray *selected = [argument componentsSeparatedByString:@","]; NSMutableArray *steps = [NSMutableArray new];
            NSDictionary *keychainCounts = @{};
            for (NSString *step in order) if ([selected containsObject:step]) [steps addObject:step];
            Require(steps.count > 0 && steps.count == selected.count, @"Invalid or duplicate cleanup steps");
            for (NSString *step in steps) {
                if ([step isEqual:@"fingerprint"]) continue;
                if ([step isEqual:@"keychain"]) { keychainCounts = Keychain(target, NO, NO)[@"classCounts"]; continue; }
                if ([step isEqual:@"preferences"]) PreferenceCache(PreferenceQueries(target), NO, NO);
                NSUInteger count = 0; ContainerStep(target, step, NO, &count); ExternalStep(target, step, NO, &count);
                if ([step isEqual:@"receipts"]) BundleReceipts(target, NO, &count);
            }
            Stop(target[@"bundlePath"]);
            SaveSession(identifier, @{@"token":scope[@"token"], @"steps":steps, @"next":@0, @"created":@(NSDate.date.timeIntervalSince1970), @"preferenceQueries":[steps containsObject:@"preferences"] ? PreferenceQueries(target) : @[]});
            return @{@"ok":@YES, @"prepared":@YES, @"steps":steps, @"preservedSharedGroups":target[@"preservedSharedGroups"], @"keychainClassCounts":keychainCounts};
        }
        NSData *data = [NSData dataWithContentsOfFile:SessionPath(identifier)];
        NSDictionary *session = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
        NSArray *steps = session[@"steps"]; NSUInteger next = [session[@"next"] unsignedIntegerValue];
        if ([command isEqual:@"recheck"]) {
            mutated = YES;
            NSArray *selected = [argument componentsSeparatedByString:@","]; NSMutableArray *normalized = [NSMutableArray new];
            for (NSString *step in order) if ([selected containsObject:step]) [normalized addObject:step];
            NSUInteger helperCount = steps.count - ([steps containsObject:@"fingerprint"] ? 1 : 0);
            Require([session[@"token"] isEqual:scope[@"token"]] && NSDate.date.timeIntervalSince1970 - [session[@"created"] doubleValue] < 1800 && [normalized isEqual:steps] && selected.count == normalized.count && next == helperCount, @"Cleanup session incomplete or recheck scope changed");
            Require(!Running(target[@"bundlePath"]).count, @"Target application restarted before final verification");
            NSMutableArray *failed = [NSMutableArray new];
            NSDictionary *keychainCounts = @{};
            for (NSString *step in steps) {
                if ([step isEqual:@"fingerprint"]) continue;
                @try {
                    if ([step isEqual:@"keychain"]) { keychainCounts = Keychain(target, NO, YES)[@"classCounts"]; continue; }
                    NSUInteger count = 0; ContainerStep(target, step, NO, &count); ExternalStep(target, step, NO, &count);
                    if ([step isEqual:@"receipts"]) BundleReceipts(target, NO, &count);
                    Require(!count, @"Selected application data remained after cleanup");
                    if ([step isEqual:@"preferences"]) PreferenceCache(session[@"preferenceQueries"], YES, NO);
                } @catch (NSException *exception) { (void)exception; [failed addObject:step]; }
            }
            remainingSteps = [failed copy]; Require(!failed.count, @"Final verification found remaining selected application data");
            return @{@"ok":@YES, @"recheckVerified":@YES, @"scope":@{@"steps":steps, @"preservedSharedGroups":target[@"preservedSharedGroups"], @"systemSharedCachesCovered":@NO, @"keychainClassCounts":keychainCounts}};
        }
        Require([order containsObject:argument] && ![argument isEqual:@"fingerprint"], @"Invalid helper cleanup step");
        Require([session[@"token"] isEqual:scope[@"token"]] && NSDate.date.timeIntervalSince1970 - [session[@"created"] doubleValue] < 1800 && next < steps.count && [steps[next] isEqual:argument], @"Cleanup session expired or step is out of order");
        Require(!Running(target[@"bundlePath"]).count, @"Target application restarted; cleanup stopped");
        NSUInteger count = 0;
        if ([argument isEqual:@"keychain"]) { mutated = YES; Keychain(target, YES, YES); }
        else {
            NSArray *preferenceQueries = [argument isEqual:@"preferences"] ? PreferenceQueries(target) : nil;
            if (preferenceQueries) PreferenceCache(preferenceQueries, NO, YES);
            ContainerStep(target, argument, YES, &count); ExternalStep(target, argument, YES, &count);
            if (preferenceQueries) PreferenceCache(preferenceQueries, NO, YES);
            if ([argument isEqual:@"receipts"]) BundleReceipts(target, YES, &count);
        }
        NSMutableDictionary *updated = [session mutableCopy]; updated[@"next"] = @(next + 1); SaveSession(identifier, updated);
        return @{@"ok":@YES, @"step":argument, @"removedEntries":@(count), @"executed":@YES, @"verified":@NO};
    } @finally { close(lock); }
}
int CleanerMain(int argc, const char *argv[]) {
    NSDictionary *result; int status = 0;
    @try { result = Execute(argc, argv); }
    @catch (NSException *exception) {
        BOOL recheck = argc >= 2 && !strcmp(argv[1], "recheck");
        result = @{@"ok":@NO, @"error":exception.reason ?: @"Cleanup failed", @"partial":@(mutated || recheck),
            @"details":failureDetails ?: @{}, @"remainingSteps":remainingSteps ?: @[], @"step":recheck ? @"recheck" : argc == 5 && !strcmp(argv[1], "run") ? [NSString stringWithUTF8String:argv[4]] : @""}; status = 1;
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:NULL];
    if (data) { fwrite(data.bytes, 1, data.length, stdout); fputc('\n', stdout); }
    return status;
}
