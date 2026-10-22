#ifndef shadow_fingerprint_h
#define shadow_fingerprint_h

#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

__attribute__((visibility("default")))
@interface SHDWFingerprintStore : NSObject
+ (instancetype)sharedStore;
- (NSArray<NSString *> *)registeredBundleIdentifiers;
// Reads a saved snapshot without generating or repairing a profile.
- (nullable NSDictionary *)profileForBundleIdentifier:(NSString *)bundleID;
// Registers a selection; fingerprint generation requires refreshApplication:.
- (BOOL)registerApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
// Saves the new profile and its locked state together.
- (BOOL)refreshApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
- (BOOL)removeApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
- (BOOL)enabledForApplication:(NSString *)bundleID;
- (BOOL)setEnabled:(BOOL)value forApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
- (BOOL)lockedForApplication:(NSString *)bundleID;
- (BOOL)setLocked:(BOOL)value forApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
- (BOOL)shadowEnabledForApplication:(NSString *)bundleID;
- (BOOL)setShadowEnabled:(BOOL)value forApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
- (BOOL)aggressiveForApplication:(NSString *)bundleID;
- (BOOL)setAggressive:(BOOL)value forApplication:(NSString *)bundleID error:(NSError * _Nullable * _Nullable)error;
// Full stable fingerprint for the supported seven-input SHA256 tree.
- (nullable NSString *)deviceFingerprintForApplication:(NSString *)bundleID;
@end

NS_ASSUME_NONNULL_END
#endif
