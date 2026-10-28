#import "FingerprintStorage.h"
#import <Shadow/Settings.h>
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>

NSString *SHDWFingerprintOwnerIdentifier(NSString *bundleID) {
    if(!bundleID.length) return nil;
    static NSMutableDictionary<NSString *, id> *owners;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ owners = [NSMutableDictionary dictionary]; });
    @synchronized(owners) {
        id owner = owners[bundleID];
        if(!owner) {
            owner = [[ShadowSettings sharedInstance] fingerprintOwnerIdentifierForIdentifier:bundleID];
            if(![owner isKindOfClass:NSString.class] || ![owner length]) owner = NSNull.null;
            owners[bundleID] = owner;
        }
        return owner == NSNull.null ? nil : owner;
    }
}

static NSDictionary *SHDWFingerprintProcessSnapshot(NSString *bundleID) {
    NSString *owner = SHDWFingerprintOwnerIdentifier(bundleID);
    if(!owner.length) return nil;
    static NSMutableDictionary<NSString *, NSDictionary *> *snapshots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ snapshots = [NSMutableDictionary dictionary]; });
    @synchronized(snapshots) {
        if(!snapshots[owner]) {
            NSUUID *identifier = nil;
            NSDictionary *data = [[ShadowSettings sharedInstance]
                runtimeFingerprintDataForIdentifier:owner vendorIdentifier:&identifier];
            // Pin both results from one persisted read, including failures.
            snapshots[owner] = @{@"Data": [data copy] ?: @{},
                @"VendorIdentifier": identifier ?: (id)NSNull.null};
        }
        return snapshots[owner];
    }
}

NSUUID *SHDWFingerprintStoredVendorIdentifier(NSString *bundleID) {
    id value = SHDWFingerprintProcessSnapshot(bundleID)[@"VendorIdentifier"];
    return [value isKindOfClass:NSUUID.class] ? value : nil;
}

NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    return SHDWFingerprintProcessSnapshot(bundleID)[@"Data"];
}

NSDictionary *SHDWFingerprintConfig(NSString *bundleID) {
    static NSMutableDictionary *snapshots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ snapshots = [NSMutableDictionary new]; });
    NSString *identifier = SHDWFingerprintOwnerIdentifier(bundleID) ?: @"";
    @synchronized(snapshots) {
        if (!snapshots[identifier]) snapshots[identifier] =
            [[SHDWFingerprintStore sharedStore] configurationForApplication:identifier];
        return snapshots[identifier];
    }
}

NSDictionary *SHDWFingerprintSystem(NSString *bundleID) {
    static NSMutableDictionary *snapshots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ snapshots = [NSMutableDictionary new]; });
    NSString *identifier = SHDWFingerprintOwnerIdentifier(bundleID) ?: @"";
    @synchronized(snapshots) {
        if (!snapshots[identifier]) snapshots[identifier] =
            [SHDWFingerprintConfiguration resolvedSystemForConfiguration:SHDWFingerprintConfig(identifier)];
        return snapshots[identifier];
    }
}
