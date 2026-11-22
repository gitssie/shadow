#import <Foundation/Foundation.h>
static inline BOOL SHDWFingerprintAdvertisingUUIDValid(id value) {
    if (![value isKindOfClass:NSString.class]) return NO;
    NSUUID *uuid = [[NSUUID alloc] initWithUUIDString:value];
    return uuid && ![uuid.UUIDString isEqual:@"00000000-0000-0000-0000-000000000000"];
}
static inline BOOL SHDWFingerprintAdvertisingTrackingStatus(NSString *mode, NSUInteger *status) {
    if ([mode isEqual:@"perApp"]) { if (status) *status = 3; return YES; }
    if ([mode isEqual:@"zero"]) { if (status) *status = 2; return YES; }
    return NO;
}
static inline NSString *SHDWFingerprintAdvertisingValue(NSString *mode, id saved, NSString *native) {
    if ([mode isEqual:@"zero"]) return @"00000000-0000-0000-0000-000000000000";
    if ([mode isEqual:@"perApp"]) {
        if (SHDWFingerprintAdvertisingUUIDValid(saved)) return [[NSUUID alloc] initWithUUIDString:saved].UUIDString;
        return @"00000000-0000-0000-0000-000000000000";
    }
    return native;
}
