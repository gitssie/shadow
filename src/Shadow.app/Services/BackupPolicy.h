#import <Foundation/Foundation.h>

static inline BOOL SHDWBackupPhoneOwned(NSDictionary *snapshot) {
    return [(snapshot[@"owner"] ?: @"phone") isEqual:@"phone"];
}
static inline NSArray<NSDictionary *> *SHDWBackupActiveFirst(NSArray<NSDictionary *> *catalog, NSString *currentIDFV) {
    if (![currentIDFV isKindOfClass:NSString.class] || !currentIDFV.length) return [catalog copy];
    NSString *current = [[NSUUID alloc] initWithUUIDString:currentIDFV].UUIDString;
    if (!current.length) return [catalog copy];
    NSMutableArray *active = [NSMutableArray new], *others = [NSMutableArray new];
    for (NSDictionary *snapshot in catalog) {
        NSString *identifier = [snapshot[@"idfv"] isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:snapshot[@"idfv"]].UUIDString : nil;
        [(identifier && [identifier isEqual:current] ? active : others) addObject:snapshot];
    }
    [active addObjectsFromArray:others];
    return [active copy];
}
static inline BOOL SHDWBackupFinalizationOnly(NSDictionary *snapshot, BOOL sameIDFV) {
    return sameIDFV && ![snapshot[@"unavailable"] boolValue] &&
        [snapshot[@"recoverySource"] boolValue] && [snapshot[@"finalizationPending"] boolValue];
}
static inline BOOL SHDWBackupCanRestore(NSDictionary *snapshot, BOOL sameIDFV) {
    if (!SHDWBackupPhoneOwned(snapshot)) return NO;
    if ([snapshot[@"unavailable"] boolValue]) return NO;
    if ([snapshot[@"restorePending"] boolValue] && ![snapshot[@"recoverySource"] boolValue]) return NO;
    return !sameIDFV || SHDWBackupFinalizationOnly(snapshot, sameIDFV);
}
