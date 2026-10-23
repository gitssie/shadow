#import <Foundation/Foundation.h>
#import "Archive.h"
#include <sys/types.h>

NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT NSString *const SHDWAppStateErrorDomain;

// The device adapter owns target authority and shared-group checks. A target
// has bundleID, token, version, build, containers (ID -> path), keychainGroups.
// The main container ID is "data"; other IDs are stable shared-group IDs.
// Capture returns data/configuration/locked; archive identity excludes locked.
// Fingerprint restoration writes data/configuration and locked=YES together.
@protocol SHDWAppStateBackend <NSObject>
- (nullable NSDictionary *)resolveBundle:(NSString *)bundleID error:(NSError **)error;
- (BOOL)stopTarget:(NSDictionary *)target error:(NSError **)error;
- (BOOL)assertStopped:(NSDictionary *)target error:(NSError **)error;
- (BOOL)flushPreferencesForTarget:(NSDictionary *)target error:(NSError **)error;
- (nullable NSString *)currentVendorIdentifierForTarget:(NSDictionary *)target error:(NSError **)error;
- (nullable NSDictionary *)capturePreferencesForTarget:(NSDictionary *)target error:(NSError **)error;
- (BOOL)validatePreferences:(NSDictionary *)preferences target:(NSDictionary *)target error:(NSError **)error;
- (BOOL)restorePreferences:(NSDictionary *)preferences target:(NSDictionary *)target error:(NSError **)error;
- (nullable NSArray<NSDictionary *> *)captureKeychainForTarget:(NSDictionary *)target error:(NSError **)error;
- (BOOL)validateKeychain:(NSArray<NSDictionary *> *)records target:(NSDictionary *)target error:(NSError **)error;
- (BOOL)restoreKeychain:(NSArray<NSDictionary *> *)records target:(NSDictionary *)target error:(NSError **)error;
- (nullable NSDictionary *)captureFingerprintForTarget:(NSDictionary *)target error:(NSError **)error;
- (BOOL)validateFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error;
- (BOOL)restoreFingerprint:(NSDictionary *)fingerprint target:(NSDictionary *)target error:(NSError **)error;
@end

@interface SHDWAppStateStore : NSObject
@property(nonatomic, copy, nullable) SHDWStateProgress progressHandler;
- (nullable instancetype)initWithRoot:(NSString *)root backend:(id<SHDWAppStateBackend>)backend error:(NSError **)error;
// Storage and restored container entries use this UID/GID; SUID/SGID are rejected.
- (nullable instancetype)initWithRoot:(NSString *)root ownerUID:(uid_t)uid ownerGID:(gid_t)gid backend:(id<SHDWAppStateBackend>)backend error:(NSError **)error;
// snapshots/<canonical IDFV>/manifest.plist + data.tar.zst + state.tar.zst. Metadata is title/note.
- (nullable NSDictionary *)backupBundle:(NSString *)bundleID metadata:(nullable NSDictionary *)metadata error:(NSError **)error;
- (nullable NSArray<NSDictionary *> *)catalogBundle:(NSString *)bundleID error:(NSError **)error;
- (BOOL)recheckBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error;
// Restoration into the currently active IDFV is rejected.
// Failed/partial restores stay pending; source identity restrictions still apply.
- (nullable NSDictionary *)restoreBundle:(NSString *)bundleID idfv:(NSString *)idfv
                            saveCurrent:(BOOL)saveCurrent error:(NSError **)error;
- (BOOL)editBundle:(NSString *)bundleID idfv:(NSString *)idfv metadata:(NSDictionary *)metadata error:(NSError **)error;
- (BOOL)deleteBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
