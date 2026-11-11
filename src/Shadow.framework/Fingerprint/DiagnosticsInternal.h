#import <Shadow/FingerprintDiagnostics.h>
@interface SHDWFingerprintDiagnostics (Runtime)
+ (void)recordData:(NSDictionary *)data configuration:(NSDictionary *)configuration owner:(NSString *)owner enabled:(BOOL)enabled;
@end
