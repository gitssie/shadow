#import <Foundation/Foundation.h>

static inline BOOL SHDWBackupPhoneOwned(NSDictionary *snapshot) {
    return [(snapshot[@"owner"] ?: @"phone") isEqual:@"phone"];
}
static inline BOOL SHDWBackupCanDiscard(NSArray<NSDictionary *> *catalog, NSString *currentIDFV) {
    NSString *current = [currentIDFV isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:currentIDFV].UUIDString : nil;
    if (!catalog || !current) return NO;
    for (NSDictionary *snapshot in catalog) {
        NSString *identifier = [snapshot[@"idfv"] isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:snapshot[@"idfv"]].UUIDString : nil;
        if ([identifier isEqual:current]) return NO;
    }
    return YES;
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
static inline NSArray<NSDictionary *> *SHDWBackupMatching(NSArray<NSDictionary *> *catalog, NSString *query) {
    NSString *text = [query stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!text.length) return [catalog copy];
    return [catalog filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(NSDictionary *snapshot, NSDictionary *bindings) {
        (void)bindings;
        for (NSString *key in @[@"title", @"note"]) {
            NSString *value = snapshot[key];
            if ([value isKindOfClass:NSString.class] && [value localizedCaseInsensitiveContainsString:text]) return YES;
        }
        return NO;
    }]];
}
static inline BOOL SHDWBackupFinalizationOnly(NSDictionary *snapshot, BOOL sameIDFV) {
    return sameIDFV && ![snapshot[@"unavailable"] boolValue] &&
        [snapshot[@"recoverySource"] boolValue] && [snapshot[@"finalizationPending"] boolValue];
}
static inline BOOL SHDWBackupCanRestore(NSDictionary *snapshot, BOOL sameIDFV) {
    if (!SHDWBackupPhoneOwned(snapshot)) return NO;
    if ([snapshot[@"unavailable"] boolValue]) return NO;
    if ([snapshot[@"restorePending"] boolValue] && ![snapshot[@"recoverySource"] boolValue]) return NO;
    return !sameIDFV || SHDWBackupFinalizationOnly(snapshot, sameIDFV) || ([snapshot[@"recoverySource"] boolValue] && [snapshot[@"resetPending"] boolValue]);
}
