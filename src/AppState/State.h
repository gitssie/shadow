#import <Foundation/Foundation.h>
#import "Archive.h"

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
// snapshots/<canonical IDFV>/manifest.plist + data.tar.zst. Metadata is title/note.
- (nullable NSDictionary *)backupBundle:(NSString *)bundleID metadata:(nullable NSDictionary *)metadata error:(NSError **)error;
- (nullable NSArray<NSDictionary *> *)catalogBundle:(NSString *)bundleID error:(NSError **)error;
- (BOOL)recheckBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error;
// A same-IDFV restore must not overwrite its selected source with live data.
// Such requests require saveCurrent=NO. Failed/partial restores stay pending.
- (nullable NSDictionary *)restoreBundle:(NSString *)bundleID idfv:(NSString *)idfv
                            saveCurrent:(BOOL)saveCurrent error:(NSError **)error;
- (BOOL)editBundle:(NSString *)bundleID idfv:(NSString *)idfv metadata:(NSDictionary *)metadata error:(NSError **)error;
- (BOOL)deleteBundle:(NSString *)bundleID idfv:(NSString *)idfv error:(NSError **)error;
@end
NS_ASSUME_NONNULL_END
