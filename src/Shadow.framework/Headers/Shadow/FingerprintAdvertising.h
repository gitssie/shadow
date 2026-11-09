#import <Foundation/Foundation.h>
static inline BOOL SHDWFingerprintAdvertisingUUIDValid(id value) {
    if (![value isKindOfClass:NSString.class]) return NO;
    NSUUID *uuid = [[NSUUID alloc] initWithUUIDString:value];
    return uuid && ![uuid.UUIDString isEqual:@"00000000-0000-0000-0000-000000000000"];
}
static inline NSString *SHDWFingerprintAdvertisingValue(NSString *mode, id saved, NSString *native, BOOL authorized) {
    if (!authorized || [mode isEqual:@"system"]) return native;
    if ([mode isEqual:@"zero"]) return @"00000000-0000-0000-0000-000000000000";
    if ([mode isEqual:@"perApp"] && SHDWFingerprintAdvertisingUUIDValid(saved))
        return [[NSUUID alloc] initWithUUIDString:saved].UUIDString;
    return native;
}
