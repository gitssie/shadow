#import <Shadow/FingerprintDiagnostics.h>
@interface SHDWFingerprintDiagnostics (Runtime)
+ (void)recordNetworkUserAgentSourceReady:(BOOL)ready;
+ (void)recordData:(NSDictionary *)data configuration:(NSDictionary *)configuration owner:(NSString *)owner enabled:(BOOL)enabled;
@end
