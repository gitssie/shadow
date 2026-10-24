// Target-scoped native preference domains; container paths are resolved only from live authority.
typedef CFDictionaryRef (*StatePreferencesCopyAPI)(CFArrayRef, CFStringRef, CFStringRef, CFStringRef, CFStringRef);
typedef void (*StatePreferencesSetAPI)(CFStringRef, CFPropertyListRef, CFStringRef, CFStringRef, CFStringRef, CFStringRef);
typedef Boolean (*StatePreferencesSyncAPI)(CFStringRef, CFStringRef, CFStringRef, CFStringRef);
typedef void (*StatePreferencesFlushAPI)(CFStringRef, CFStringRef);
static NSString *StatePreferenceContainerID(NSDictionary *target, NSString *identifier) {
    return [identifier isEqual:target[@"bundleID"]] ? @"data" : [@"scope-" stringByAppendingString:identifier];
}
static NSDictionary *StatePreferenceContainers(NSDictionary *target) {
    NSMutableDictionary *result = [NSMutableDictionary new];
    for (NSDictionary *container in target[@"containers"]) {
        NSString *key = StatePreferenceContainerID(target, container[@"identifier"]);
        Require(!result[key], @"Duplicate preference container identity"); result[key] = container[@"path"];
    }
    return result;
}
static BOOL StatePreferenceDomain(NSString *domain) {
    return PreferenceDomainName(domain) && !PreferenceDomainAlias(domain);
}
static NSArray *StatePreferenceScopes(NSDictionary *target) {
    NSDictionary *containers = StatePreferenceContainers(target); NSMutableArray *scopes = [NSMutableArray new];
    for (NSDictionary *query in PreferenceQueries(target)) {
        NSString *containerID = @"", *path = query[@"container"];
        if (path.length) {
            NSArray *keys = [containers allKeysForObject:path]; Require(keys.count == 1, @"Unresolved preference container"); containerID = keys.firstObject;
        }
        Require(StatePreferenceDomain(query[@"domain"]), @"Unsupported application preference domain");
        for (NSString *host in @[@"any", @"current"]) [scopes addObject:@{@"container":containerID, @"domain":query[@"domain"], @"host":host}];
    }
    return [scopes sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) {
        for (NSString *key in @[@"container", @"domain", @"host"]) { NSComparisonResult result = [a[key] compare:b[key]]; if (result != NSOrderedSame) return result; }
        return NSOrderedSame;
    }];
}
static void StateValidatePreferences(NSDictionary *payload, NSDictionary *target) {
    Require([payload isKindOfClass:NSDictionary.class] && payload.count == 2 && [payload[@"version"] isEqual:@1] && [payload[@"records"] isKindOfClass:NSArray.class], @"Invalid archived application preferences");
    NSDictionary *containers = StatePreferenceContainers(target); NSMutableSet *seen = [NSMutableSet new];
    for (id item in payload[@"records"]) {
        Require([item isKindOfClass:NSDictionary.class], @"Invalid archived preference record"); NSDictionary *record = item;
        NSString *container = record[@"container"], *domain = record[@"domain"], *host = record[@"host"]; NSDictionary *values = record[@"values"];
        Require(record.count == 4 && [container isKindOfClass:NSString.class] && StatePreferenceDomain(domain) && [@[@"any", @"current"] containsObject:host] && [values isKindOfClass:NSDictionary.class], @"Invalid archived preference scope");
        Require(container.length ? containers[container] != nil : [target[@"identifiers"] containsObject:domain], @"Archived preferences are outside the selected application");
        Require([NSPropertyListSerialization propertyList:values isValidForFormat:NSPropertyListBinaryFormat_v1_0], @"Unsupported archived preference values");
        for (id key in values) Require([key isKindOfClass:NSString.class], @"Invalid archived preference key");
        NSArray *identity = @[container, domain, host]; Require(![seen containsObject:identity], @"Duplicate archived preference scope"); [seen addObject:identity];
    }
    // The app identity is stable across upgrades. Extensions added afterward
    // have no archived records; restoration treats their current scopes as empty.
    for (NSString *host in @[@"any", @"current"]) Require([seen containsObject:@[@"", target[@"bundleID"], host]], @"Archived preferences are missing the application domain");
}
static NSDictionary *StatePreferenceRead(NSDictionary *scope, NSDictionary *containers) {
    StatePreferencesCopyAPI copy = dlsym(RTLD_DEFAULT, "_CFPreferencesCopyMultipleWithContainer");
    StatePreferencesSyncAPI sync = dlsym(RTLD_DEFAULT, "_CFPreferencesSynchronizeWithContainer");
    StatePreferencesFlushAPI flush = dlsym(RTLD_DEFAULT, "_CFPreferencesFlushCachesForIdentifier");
    Require(copy && sync && flush, @"Native preference APIs unavailable");
    CFStringRef domain = (__bridge CFStringRef)scope[@"domain"], host = [scope[@"host"] isEqual:@"current"] ? kCFPreferencesCurrentHost : kCFPreferencesAnyHost;
    CFStringRef container = [scope[@"container"] length] ? (__bridge CFStringRef)containers[scope[@"container"]] : CFSTR("kCFPreferencesNoContainer");
    flush(domain, CFSTR("mobile")); Require(sync(domain, CFSTR("mobile"), host, container), @"Cannot synchronize application preferences"); flush(domain, CFSTR("mobile"));
    CFDictionaryRef copied = copy(NULL, domain, CFSTR("mobile"), host, container);
    if (!copied) return @{};
    Require(CFGetTypeID(copied) == CFDictionaryGetTypeID(), @"Cannot read native application preferences");
    NSDictionary *values = CFBridgingRelease(copied);
    Require([NSPropertyListSerialization propertyList:values isValidForFormat:NSPropertyListBinaryFormat_v1_0], @"Unsupported application preference values"); return values;
}
static NSDictionary *StateCapturePreferences(NSDictionary *target) {
    NSDictionary *containers = StatePreferenceContainers(target); NSMutableArray *records = [NSMutableArray new];
    for (NSDictionary *scope in StatePreferenceScopes(target)) {
        NSDictionary *values = StatePreferenceRead(scope, containers);
        if ([scope[@"container"] length] && !values.count) continue;
        NSMutableDictionary *record = [scope mutableCopy]; record[@"values"] = values; [records addObject:record];
    }
    NSDictionary *payload = @{@"version":@1, @"records":records}; StateValidatePreferences(payload, target); return payload;
}
static void StateRestorePreferences(NSDictionary *payload, NSDictionary *target) {
    StateValidatePreferences(payload, target);
    StatePreferencesSetAPI set = dlsym(RTLD_DEFAULT, "_CFPreferencesSetValueWithContainer");
    StatePreferencesSyncAPI sync = dlsym(RTLD_DEFAULT, "_CFPreferencesSynchronizeWithContainer");
    Require(set && sync, @"Native preference import APIs unavailable");
    NSDictionary *containers = StatePreferenceContainers(target); NSMutableDictionary *desired = [NSMutableDictionary new], *scopes = [NSMutableDictionary new];
    for (NSDictionary *record in payload[@"records"]) { NSArray *key = @[record[@"container"], record[@"domain"], record[@"host"]]; desired[key] = record[@"values"]; scopes[key] = record; }
    for (NSDictionary *scope in StatePreferenceScopes(target)) { NSArray *key = @[scope[@"container"], scope[@"domain"], scope[@"host"]]; if (!scopes[key]) scopes[key] = scope; }
    for (NSArray *identity in scopes) {
        NSDictionary *scope = scopes[identity], *values = desired[identity] ?: @{}, *current = StatePreferenceRead(scope, containers);
        if ([current isEqual:values]) continue;
        CFStringRef domain = (__bridge CFStringRef)scope[@"domain"], host = [scope[@"host"] isEqual:@"current"] ? kCFPreferencesCurrentHost : kCFPreferencesAnyHost;
        CFStringRef container = [scope[@"container"] length] ? (__bridge CFStringRef)containers[scope[@"container"]] : CFSTR("kCFPreferencesNoContainer");
        for (NSString *key in current) if (!values[key]) set((__bridge CFStringRef)key, NULL, domain, CFSTR("mobile"), host, container);
        for (NSString *key in values) if (![values[key] isEqual:current[key]]) set((__bridge CFStringRef)key, (__bridge CFPropertyListRef)values[key], domain, CFSTR("mobile"), host, container);
        Require(sync(domain, CFSTR("mobile"), host, container), @"Cannot import application preferences");
        Require([StatePreferenceRead(scope, containers) isEqual:values], @"Imported application preferences failed readback");
    }
}
