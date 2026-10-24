#import <Foundation/Foundation.h>

static inline BOOL SHDWBackupFinalizationOnly(NSDictionary *snapshot, BOOL sameIDFV) {
    return sameIDFV && ![snapshot[@"unavailable"] boolValue] &&
        [snapshot[@"recoverySource"] boolValue] && [snapshot[@"finalizationPending"] boolValue];
}
static inline BOOL SHDWBackupCanRestore(NSDictionary *snapshot, BOOL sameIDFV) {
    if ([snapshot[@"unavailable"] boolValue]) return NO;
    if ([snapshot[@"restorePending"] boolValue] && ![snapshot[@"recoverySource"] boolValue]) return NO;
    return !sameIDFV || SHDWBackupFinalizationOnly(snapshot, sameIDFV);
}
