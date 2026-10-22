#import <Foundation/Foundation.h>

@interface SHDWFingerprintProfile : NSObject
+ (NSString *)displayIdentifierForData:(NSDictionary *)data;
+ (NSString *)stableFingerprintForInputs:(NSDictionary *)inputs;
@end
