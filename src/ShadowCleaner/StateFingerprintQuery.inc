#import <Shadow/SHDWPlugin.h>

static NSDictionary *StateFingerprintSettings(NSString *identifier) {
    Require(CFPreferencesSynchronize(CFSTR(SHADOW_PREFS_PLIST),CFSTR("mobile"),kCFPreferencesAnyHost),@"Cannot synchronize Shadow fingerprint settings");
    NSDictionary *first = nil;
    NSMutableSet *visited = [NSMutableSet new];
    for (NSString *path in SHDW_STATE_IDENTITY_PATHS()) {
        if ([visited containsObject:path]) continue;
        [visited addObject:path];
        NSError *error = nil;
        NSData *bytes = [NSData dataWithContentsOfFile:path options:0 error:&error];
        if (!bytes) {
            if ([error.domain isEqual:NSCocoaErrorDomain] && error.code == NSFileReadNoSuchFileError) continue;
            Require(NO,@"Cannot read persisted Shadow settings");
        }
        if (!bytes.length && first) continue;
        id root = [NSPropertyListSerialization propertyListWithData:bytes options:NSPropertyListImmutable format:NULL error:NULL];
        Require([root isKindOfClass:NSDictionary.class],@"Invalid persisted Shadow settings");
        if (!first) first = root;
        if (root[identifier]) return root;
    }
    if (first) return first;
    NSArray *keys = @[identifier,SHDWGlobalEnabledID,SHDWSingleToggleMigrationID];
    id root = CFBridgingRelease(CFPreferencesCopyMultiple((__bridge CFArrayRef)keys,CFSTR(SHADOW_PREFS_PLIST),CFSTR("mobile"),kCFPreferencesAnyHost));
    Require(!root || [root isKindOfClass:NSDictionary.class],@"Invalid Shadow settings");
    return root ?: @{};
}

static id StateFingerprintJSON(id value) {
    if ([value isKindOfClass:NSString.class]) return value;
    if ([value isKindOfClass:NSNumber.class]) { Require(isfinite([value doubleValue]),@"Invalid fingerprint number"); return value; }
    if ([value isKindOfClass:NSDate.class]) return @([value timeIntervalSince1970]);
    if ([value isKindOfClass:NSData.class]) return [value base64EncodedStringWithOptions:0];
    if ([value isKindOfClass:NSArray.class]) {
        NSMutableArray *result = [NSMutableArray new];
        for (id item in value) [result addObject:StateFingerprintJSON(item)];
        return result;
    }
    Require([value isKindOfClass:NSDictionary.class],@"Invalid fingerprint value");
    NSMutableDictionary *result = [NSMutableDictionary new];
    for (id key in value) {
        Require([key isKindOfClass:NSString.class],@"Invalid fingerprint key");
        result[key] = StateFingerprintJSON(value[key]);
    }
    return result;
}

static NSDictionary *StateActiveFingerprint(NSString *identifier) {
    NSDictionary *root = StateFingerprintSettings(identifier);
    id app = root[identifier];
    Require(!app || [app isKindOfClass:NSDictionary.class],@"Invalid application fingerprint settings");
    for (NSString *key in @[SHDWAppEnabledID,SHDWAppDisabledID,@"Fingerprint_Managed",@"Fingerprint_Enabled",@"Fingerprint_Locked"])
        Require(!app[key] || [app[key] isKindOfClass:NSNumber.class],@"Invalid application fingerprint switch");
    for (NSString *key in @[SHDWGlobalEnabledID,SHDWSingleToggleMigrationID])
        Require(!root[key] || [root[key] isKindOfClass:NSNumber.class],@"Invalid Shadow switch");
    id data = app[@"Fingerprint_Data"], config = app[@"Fingerprint_Config"];
    Require(!data || [data isKindOfClass:NSDictionary.class],@"Invalid stored fingerprint data");
    if (config) Require([SHDWFingerprintConfiguration configurationByValidating:config error:NULL] != nil,@"Invalid stored fingerprint configuration");
    BOOL available = [data count] > 0;
    NSString *current = available ? StateExternalIdentity(app) : @"";
    if (available) Require(current.length && [ShadowSettings isValidFingerprintData:data],@"Invalid stored fingerprint data");
    BOOL enabled = available && SHDWFingerprintApplicationIsRegistered(app) && SHDWFingerprintApplicationEnabled(app) &&
        SHDWApplicationEnabled(app,[root[SHDWGlobalEnabledID] boolValue],[root[SHDWSingleToggleMigrationID] boolValue],NO);
    NSMutableDictionary *result = [@{@"bundle_id":identifier,@"source":@"stored_settings",@"available":@(available),@"enabled":@(enabled),
        @"locked":@(SHDWFingerprintApplicationLocked(app)),@"current_idfv":current} mutableCopy];
    if (data) result[@"fingerprint_data"] = StateFingerprintJSON(data);
    if (config) result[@"fingerprint_config"] = StateFingerprintJSON(config);
    return result;
}
