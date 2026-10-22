static NSArray *StateWritableKeys(void) {
    return @[(__bridge id)kSecClass, (__bridge id)kSecAttrAccessGroup, (__bridge id)kSecAttrAccount, (__bridge id)kSecAttrService,
        (__bridge id)kSecAttrServer, (__bridge id)kSecAttrPort, (__bridge id)kSecAttrProtocol, (__bridge id)kSecAttrAuthenticationType,
        (__bridge id)kSecAttrSecurityDomain, (__bridge id)kSecAttrPath, (__bridge id)kSecAttrAccessible, (__bridge id)kSecAttrSynchronizable,
        (__bridge id)kSecAttrLabel, (__bridge id)kSecAttrDescription, (__bridge id)kSecAttrComment, (__bridge id)kSecAttrGeneric,
        (__bridge id)kSecAttrCreator, (__bridge id)kSecAttrType, (__bridge id)kSecAttrIsInvisible, (__bridge id)kSecAttrIsNegative,
        (__bridge id)kSecValueData, @"ArchivedACL"];
}
static NSArray *StateIdentityKeys(NSDictionary *record) {
    if ([record[(__bridge id)kSecClass] isEqual:(__bridge id)kSecClassGenericPassword]) return @[(__bridge id)kSecAttrService, (__bridge id)kSecAttrAccount];
    return @[(__bridge id)kSecAttrAccount, (__bridge id)kSecAttrSecurityDomain, (__bridge id)kSecAttrServer, (__bridge id)kSecAttrProtocol,
        (__bridge id)kSecAttrAuthenticationType, (__bridge id)kSecAttrPort, (__bridge id)kSecAttrPath];
}
static NSDictionary *StateRecordIdentity(NSDictionary *record) {
    NSMutableDictionary *identity = [@{(__bridge id)kSecClass:record[(__bridge id)kSecClass], (__bridge id)kSecAttrAccessGroup:record[(__bridge id)kSecAttrAccessGroup], (__bridge id)kSecAttrSynchronizable:@([record[(__bridge id)kSecAttrSynchronizable] boolValue])} mutableCopy];
    for (NSString *key in StateIdentityKeys(record)) identity[key] = record[key] ?: ([key isEqual:(__bridge id)kSecAttrPort] ? @0 : @"");
    return identity;
}
static NSMutableDictionary *StateDecodeRecord(NSDictionary *record) {
    NSMutableDictionary *value = [record mutableCopy]; NSData *encoded = value[@"ArchivedACL"]; [value removeObjectForKey:@"ArchivedACL"];
    for (NSString *key in @[(__bridge id)kSecAttrSynchronizable, (__bridge id)kSecAttrIsInvisible, (__bridge id)kSecAttrIsNegative]) if (value[key]) value[key] = @([value[key] boolValue]);
    if (encoded) {
        SecAccessControlRef (*decode)(CFAllocatorRef, CFDataRef, CFErrorRef *) = dlsym(RTLD_DEFAULT, "SecAccessControlCreateFromData");
        SecAccessControlRef acl = decode ? decode(kCFAllocatorDefault, (__bridge CFDataRef)encoded, NULL) : NULL;
        Require(acl != NULL, @"Archived credential protection is unsupported"); value[(__bridge id)kSecAttrAccessControl] = CFBridgingRelease(acl); [value removeObjectForKey:(__bridge id)kSecAttrAccessible];
    }
    return value;
}
static void StateValidateRecords(NSArray *records, NSArray *groups) {
    Require([records isKindOfClass:NSArray.class] && records.count <= 100000, @"Invalid credential archive"); NSMutableSet *identities = [NSMutableSet new];
    NSArray *strings = @[(__bridge id)kSecAttrAccount, (__bridge id)kSecAttrService, (__bridge id)kSecAttrServer, (__bridge id)kSecAttrProtocol,
        (__bridge id)kSecAttrAuthenticationType, (__bridge id)kSecAttrSecurityDomain, (__bridge id)kSecAttrPath, (__bridge id)kSecAttrAccessible,
        (__bridge id)kSecAttrLabel, (__bridge id)kSecAttrDescription, (__bridge id)kSecAttrComment];
    for (NSDictionary *record in records) {
        Require([record isKindOfClass:NSDictionary.class] && [groups containsObject:record[(__bridge id)kSecAttrAccessGroup]] &&
            [@[(__bridge id)kSecClassGenericPassword, (__bridge id)kSecClassInternetPassword] containsObject:record[(__bridge id)kSecClass]] &&
            [record[(__bridge id)kSecValueData] isKindOfClass:NSData.class], @"Credential archive scope or type is unsupported");
        id sync = record[(__bridge id)kSecAttrSynchronizable]; Require([sync isKindOfClass:NSNumber.class] && [@[@NO, @YES] containsObject:sync], @"Invalid credential synchronization flag");
        for (NSString *key in record) Require([StateWritableKeys() containsObject:key], @"Credential archive contains a nonportable attribute");
        BOOL genericPassword = [record[(__bridge id)kSecClass] isEqual:(__bridge id)kSecClassGenericPassword];
        NSArray *incompatible = genericPassword ? @[(__bridge id)kSecAttrServer, (__bridge id)kSecAttrPort, (__bridge id)kSecAttrProtocol, (__bridge id)kSecAttrAuthenticationType, (__bridge id)kSecAttrSecurityDomain, (__bridge id)kSecAttrPath] : @[(__bridge id)kSecAttrService, (__bridge id)kSecAttrGeneric];
        for (NSString *key in incompatible) Require(!record[key], @"Credential archive contains attributes from another credential class");
        for (NSString *key in strings) if (record[key]) Require([record[key] isKindOfClass:NSString.class], @"Invalid credential string attribute");
        NSString *accessible = record[(__bridge id)kSecAttrAccessible];
        Require(accessible != nil || record[@"ArchivedACL"] != nil, @"Credential protection is missing from the archive");
        if (accessible) {
            Require([@[@"ak", @"ck", @"dk", @"aku", @"cku", @"dku", @"akpu"] containsObject:accessible], @"Unsupported credential accessibility");
            Require(![sync boolValue] || ![accessible hasSuffix:@"u"], @"Synchronized credentials cannot use device-only protection");
        }
        for (NSString *key in @[(__bridge id)kSecAttrPort, (__bridge id)kSecAttrCreator, (__bridge id)kSecAttrType]) if (record[key]) {
            NSNumber *number = record[key]; Require([number isKindOfClass:NSNumber.class] && isfinite(number.doubleValue) && number.doubleValue == number.unsignedIntValue && (![key isEqual:(__bridge id)kSecAttrPort] || number.unsignedIntValue <= 65535), @"Invalid credential number attribute");
        }
        for (NSString *key in @[(__bridge id)kSecAttrIsInvisible, (__bridge id)kSecAttrIsNegative]) if (record[key]) Require([record[key] isKindOfClass:NSNumber.class] && [@[@NO, @YES] containsObject:record[key]], @"Invalid credential Boolean attribute");
        id generic = record[(__bridge id)kSecAttrGeneric]; if (generic) Require([generic isKindOfClass:NSData.class] || [generic isKindOfClass:NSString.class], @"Unsupported generic credential attribute");
        if (record[@"ArchivedACL"]) Require([record[@"ArchivedACL"] isKindOfClass:NSData.class] && [record[@"ArchivedACL"] length] <= 1024 * 1024, @"Invalid archived credential protection");
        StateDecodeRecord(record); NSDictionary *identity = StateRecordIdentity(record); Require(![identities containsObject:identity], @"Duplicate credential archive identity"); [identities addObject:identity];
    }
    NSData *encoded = [NSPropertyListSerialization dataWithPropertyList:records format:NSPropertyListBinaryFormat_v1_0 options:0 error:NULL]; Require(encoded && encoded.length <= 16 * 1024 * 1024, @"Credential archive exceeds its size limit");
}
static NSArray *StateExportRecords(NSArray *groups) {
    NSMutableArray *records = [NSMutableArray new];
    CFDataRef (*copyACL)(SecAccessControlRef) = dlsym(RTLD_DEFAULT, "SecAccessControlCopyData");
    for (NSString *group in groups) for (id itemClass in @[(__bridge id)kSecClassGenericPassword, (__bridge id)kSecClassInternetPassword, (__bridge id)kSecClassCertificate, (__bridge id)kSecClassKey, (__bridge id)kSecClassIdentity]) {
        BOOL password = [@[(__bridge id)kSecClassGenericPassword, (__bridge id)kSecClassInternetPassword] containsObject:itemClass];
        NSMutableDictionary *query = KeychainQuery(group, itemClass); query[(__bridge id)kSecReturnAttributes] = @YES; query[(__bridge id)kSecMatchLimit] = (__bridge id)kSecMatchLimitAll; if (password) query[(__bridge id)kSecReturnData] = @YES;
        CFTypeRef value = NULL; OSStatus status = SecItemCopyMatching((__bridge CFDictionaryRef)query, &value); id result = value ? CFBridgingRelease(value) : nil;
        if (status == errSecItemNotFound) { Require(!result, @"Credential export returned contradictory results"); continue; }
        Require(status == errSecSuccess && result != nil, [NSString stringWithFormat:@"Credential export failed (%d)", (int)status]);
        NSArray *items = [result isKindOfClass:NSArray.class] ? result : [result isKindOfClass:NSDictionary.class] ? @[result] : nil;
        Require(items != nil, @"Credential export returned an unsupported result"); Require(password || !items.count, @"Certificates, private keys, and identities cannot be backed up");
        for (NSDictionary *item in items) {
            Require([item isKindOfClass:NSDictionary.class] && [item[(__bridge id)kSecAttrAccessGroup] isEqual:group] && (!item[(__bridge id)kSecClass] || [item[(__bridge id)kSecClass] isEqual:itemClass]), @"Credential export returned attributes outside the requested scope"); NSMutableDictionary *record = [NSMutableDictionary new];
            for (NSString *key in StateWritableKeys()) if (item[key] && ![key isEqual:@"ArchivedACL"]) record[key] = item[key];
            record[(__bridge id)kSecClass] = itemClass; record[(__bridge id)kSecAttrAccessGroup] = group; record[(__bridge id)kSecAttrSynchronizable] = item[(__bridge id)kSecAttrSynchronizable] ?: @NO;
            id acl = item[(__bridge id)kSecAttrAccessControl]; if (acl) { CFDataRef data = copyACL ? copyACL((__bridge SecAccessControlRef)acl) : NULL; Require(data != NULL, @"Credential protection cannot be exported"); record[@"ArchivedACL"] = CFBridgingRelease(data); }
            [records addObject:record];
        }
    }
    StateValidateRecords(records, groups); return records;
}
static void StateValidateReplacement(NSArray *records, NSArray *current, NSArray *groups) {
    StateValidateRecords(records, groups); NSMutableDictionary *desired = [NSMutableDictionary new];
    for (NSDictionary *record in records) desired[StateRecordIdentity(record)] = record;
    for (NSDictionary *old in current) if ([old[(__bridge id)kSecAttrSynchronizable] boolValue]) {
        NSDictionary *saved = desired[StateRecordIdentity(old)]; if (!saved) continue;
        for (NSString *key in @[(__bridge id)kSecAttrAccessible, @"ArchivedACL"]) Require((!old[key] && !saved[key]) || [old[key] isEqual:saved[key]], @"Synchronized credential protection differs");
        NSDictionary *identity = StateRecordIdentity(old); for (NSString *key in old) if (!saved[key] && !identity[key] && ![key isEqual:@"ArchivedACL"] && ![key isEqual:(__bridge id)kSecAttrAccessible]) Fail(@"Removing a synchronized credential attribute is unsupported");
    }
}
static void StateRestoreRecords(NSArray *records, NSArray *current, NSArray *groups) {
    StateValidateReplacement(records, current, groups); NSMutableDictionary *desired = [NSMutableDictionary new], *live = [NSMutableDictionary new];
    for (NSDictionary *record in records) desired[StateRecordIdentity(record)] = record;
    for (NSDictionary *record in current) live[StateRecordIdentity(record)] = record;
    for (NSDictionary *record in current) if ([record[(__bridge id)kSecAttrSynchronizable] boolValue] && !desired[StateRecordIdentity(record)]) {
        Require(getppid() == keychainParent, @"Credential worker parent exited"); NSMutableDictionary *query = [StateRecordIdentity(record) mutableCopy]; query[(__bridge id)kSecUseAuthenticationContext] = KeychainQuery(record[(__bridge id)kSecAttrAccessGroup], record[(__bridge id)kSecClass])[(__bridge id)kSecUseAuthenticationContext];
        OSStatus status = SecItemDelete((__bridge CFDictionaryRef)query); Require(status == errSecSuccess || status == errSecItemNotFound, @"Cannot remove a synchronized credential absent from the snapshot");
    }
    for (NSString *group in groups) for (id itemClass in @[(__bridge id)kSecClassGenericPassword, (__bridge id)kSecClassInternetPassword]) {
        Require(getppid() == keychainParent, @"Credential worker parent exited"); NSMutableDictionary *query = KeychainQuery(group, itemClass); query[(__bridge id)kSecAttrSynchronizable] = @NO;
        OSStatus status = SecItemDelete((__bridge CFDictionaryRef)query); Require(status == errSecSuccess || status == errSecItemNotFound, @"Cannot replace local credentials");
    }
    for (NSDictionary *record in records) {
        Require(getppid() == keychainParent, @"Credential worker parent exited"); NSDictionary *identity = StateRecordIdentity(record), *old = live[identity]; NSMutableDictionary *item = StateDecodeRecord(record); OSStatus status;
        if ([record[(__bridge id)kSecAttrSynchronizable] boolValue] && old) {
            if ([old isEqual:record]) continue;
            NSMutableDictionary *query = [identity mutableCopy]; query[(__bridge id)kSecUseAuthenticationContext] = KeychainQuery(record[(__bridge id)kSecAttrAccessGroup], record[(__bridge id)kSecClass])[(__bridge id)kSecUseAuthenticationContext];
            for (NSString *key in query) [item removeObjectForKey:key]; [item removeObjectForKey:(__bridge id)kSecAttrAccessible]; [item removeObjectForKey:(__bridge id)kSecAttrAccessControl]; status = SecItemUpdate((__bridge CFDictionaryRef)query, (__bridge CFDictionaryRef)item);
        } else status = SecItemAdd((__bridge CFDictionaryRef)item, NULL);
        Require(status == errSecSuccess, [NSString stringWithFormat:@"Credential restoration failed (%d)", (int)status]);
    }
}
