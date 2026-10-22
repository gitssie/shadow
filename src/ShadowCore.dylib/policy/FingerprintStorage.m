#import "FingerprintStorage.h"
#import <Shadow/Settings.h>
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>

NSDictionary *SHDWFingerprintData(NSString *bundleID) {
    if(!bundleID.length) return nil;
    static NSMutableDictionary<NSString *, NSDictionary *> *snapshots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ snapshots = [NSMutableDictionary dictionary]; });
    @synchronized(snapshots) {
        NSDictionary *data = snapshots[bundleID];
        if(!data) {
            data = [[ShadowSettings sharedInstance] fingerprintDataForIdentifier:bundleID];
            // Pin failures too: never switch profiles halfway through a process.
            snapshots[bundleID] = data ?: @{};
        }
        return snapshots[bundleID];
    }
}

NSDictionary *SHDWFingerprintConfig(NSString *bundleID) {
    static NSMutableDictionary *snapshots;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ snapshots = [NSMutableDictionary new]; });
    NSString *identifier = bundleID ?: @"";
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
    NSString *identifier = bundleID ?: @"";
    @synchronized(snapshots) {
        if (!snapshots[identifier]) snapshots[identifier] =
            [SHDWFingerprintConfiguration resolvedSystemForConfiguration:SHDWFingerprintConfig(identifier)];
        return snapshots[identifier];
    }
}
