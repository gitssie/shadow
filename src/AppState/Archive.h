#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT NSString *const SHDWStateArchiveErrorDomain;
typedef void (^SHDWStateProgress)(NSDictionary *event);

// A root key is a relative archive prefix, such as containers/data.
// Info contains format, compression, sha256, archiveSize, and entries. Each
// entry records path, type, mode, uid, gid, nanosecond mtime/birthtime,
// size/hash or symlink target. Container roots keep their native timestamps.
// File contents are streamed; only entry metadata and bounded payloads use RAM.
// Metadata covers basic POSIX fields, not xattrs, ACLs or iOS protection classes.
// The PAX creation-time annotation is archive metadata, never an app xattr.
// Throwing from progress cancels the operation and returns an error.
@interface SHDWStateArchive : NSObject
+ (nullable NSDictionary *)captureRoots:(NSDictionary<NSString *, NSString *> *)roots
                               payloads:(NSDictionary<NSString *, NSData *> *)payloads
                                 toPath:(NSString *)path
                               progress:(nullable SHDWStateProgress)progress
                                  error:(NSError **)error;
+ (BOOL)verifyPath:(NSString *)path info:(NSDictionary *)info
          progress:(nullable SHDWStateProgress)progress error:(NSError **)error;
+ (nullable NSDictionary<NSString *, NSData *> *)readPayloadsAtPath:(NSString *)path
                                                            info:(NSDictionary *)info
                                                           names:(NSArray<NSString *> *)names
                                                           error:(NSError **)error;
// Callers must preflight the complete archive and stop the target before
// clearing destination contents. Extraction does not delete destination files.
// After all post-extraction writes, synchronizeRoots must precede commit.
+ (BOOL)restorePath:(NSString *)path info:(NSDictionary *)info
              roots:(NSDictionary<NSString *, NSString *> *)roots
           progress:(nullable SHDWStateProgress)progress error:(NSError **)error;
// Persist regular-file data and directories from children to parents without
// following symbolic links. Call after any post-extraction preference writes
// and before committing restoration state. Sync failures leave restore pending.
+ (BOOL)synchronizeRoots:(NSDictionary<NSString *, NSString *> *)roots
               progress:(nullable SHDWStateProgress)progress error:(NSError **)error;
+ (BOOL)verifyRoots:(NSDictionary<NSString *, NSString *> *)roots info:(NSDictionary *)info
           progress:(nullable SHDWStateProgress)progress error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
