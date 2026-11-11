#import "DiagnosticsInternal.h"
#import "StoredApplication.h"
#import <Shadow/Fingerprint.h>
#import <Shadow/Settings.h>
#import <Shadow/SHDWPlugin.h>
#import <Shadow/FingerprintMemory.h>
#import <Shadow/FingerprintConfiguration.h>
static NSDictionary *runtimeSnapshot;
static BOOL networkUserAgentSourceReady;
static NSDictionary *Fields(NSDictionary *data) {
    NSMutableDictionary *result=[NSMutableDictionary new];
    for (NSString *key in @[@"AdvertisingIdentifier",@"VendorIdentifier",@"HomeVolumeCreationTime",@"MemoryDelta",@"UpdatedAt"])
        if (data[key]) result[key]=data[key];
    return [result copy];
}
@implementation SHDWFingerprintDiagnostics
+ (void)recordNetworkUserAgentSourceReady:(BOOL)ready {
    @synchronized(self) { networkUserAgentSourceReady=ready; }
}
+ (void)recordData:(NSDictionary *)data configuration:(NSDictionary *)configuration owner:(NSString *)owner enabled:(BOOL)enabled {
    @synchronized(self) {
        if (runtimeSnapshot) return;
        runtimeSnapshot=@{@"apiVersion":@1,@"bundleIdentifier":NSBundle.mainBundle.bundleIdentifier ?: @"",
            @"ownerIdentifier":owner ?: @"",@"fingerprintEnabled":@(enabled),
            @"fields":Fields(data),@"configuration":[configuration copy] ?: @{},
            @"expectedPhysicalMemory":@(SHDWFingerprintProjectedMemory(NSProcessInfo.processInfo.physicalMemory,[data[@"MemoryDelta"] longLongValue])),
            @"expectedSystem":[SHDWFingerprintConfiguration resolvedSystemForConfiguration:configuration]};
    }
}
+ (NSDictionary *)currentApplicationSnapshot {
    @synchronized(self) {
        if (!runtimeSnapshot) return @{@"apiVersion":@1,@"runtimeAvailable":@NO};
        NSMutableDictionary *result=[runtimeSnapshot mutableCopy];
        result[@"runtimeAvailable"]=@YES;
        result[@"networkUserAgentSourceReady"]=@(networkUserAgentSourceReady);
        NSString *owner=runtimeSnapshot[@"ownerIdentifier"];
        NSDictionary *application=[ShadowSettings.sharedInstance storedFingerprintApplicationForIdentifier:owner];
        id value=application[@"Fingerprint_Data"];
        NSDictionary *saved=[value isKindOfClass:NSDictionary.class] ? value : nil;
        NSDictionary *config=[SHDWFingerprintConfiguration configurationByValidating:application[@"Fingerprint_Config"] error:NULL] ?: SHDWFingerprintConfiguration.defaultConfiguration;
        result[@"savedAvailable"]=@(saved != nil);
        NSDictionary *prefs=[ShadowSettings.sharedInstance getPreferencesForIdentifier:owner];
        BOOL active=[prefs[SHDWAppEnabledID] boolValue] && [prefs[SHDWUniversalFingerprintID] boolValue];
        BOOL ownerMatches=[[ShadowSettings.sharedInstance fingerprintOwnerIdentifierForIdentifier:NSBundle.mainBundle.bundleIdentifier] isEqual:owner];
        result[@"stale"]=@(!ownerMatches || active != [runtimeSnapshot[@"fingerprintEnabled"] boolValue] || !saved || ![Fields(saved) isEqual:runtimeSnapshot[@"fields"]] || ![config isEqual:runtimeSnapshot[@"configuration"]]);
        return [result copy];
    }
}
@end
