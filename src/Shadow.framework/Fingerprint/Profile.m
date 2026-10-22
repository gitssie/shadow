#import "Profile.h"
#import "Signals.h"
#import <CommonCrypto/CommonDigest.h>

static NSString *SHDWFingerprintASCIIHash(NSString *text) {
  NSData *bytes = [text dataUsingEncoding:NSASCIIStringEncoding
                    allowLossyConversion:NO] ?: [NSData data];
  unsigned char digest[CC_SHA256_DIGEST_LENGTH];
  CC_SHA256(bytes.bytes, (CC_LONG)bytes.length, digest);
  NSMutableString *result = [NSMutableString stringWithCapacity:64];
  for (NSUInteger i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
    [result appendFormat:@"%02x", digest[i]];
  }
  return [result copy];
}

@implementation SHDWFingerprintProfile
+ (NSString *)displayIdentifierForData:(NSDictionary *)data {
  return [self stableFingerprintForInputs:SHDWFingerprintInputsForData(data)];
}

+ (NSString *)stableFingerprintForInputs:(NSDictionary *)inputs {
  if (![inputs isKindOfClass:NSDictionary.class]) {
    return nil;
  }
  NSArray<NSString *> *hardwareKeys = @[
    @"deviceType", @"deviceModel", @"displayResolution", @"displayScale",
    @"memorySize", @"processorCount"
  ];
  NSMutableString *hardwareLeaves = [NSMutableString new];
  for (NSString *key in hardwareKeys) {
    id value = inputs[key];
    if (![value isKindOfClass:NSString.class]) {
      return nil;
    }
    [hardwareLeaves appendString:SHDWFingerprintASCIIHash(value)];
  }
  id biometry = inputs[@"biometryType"];
  if (![biometry isKindOfClass:NSString.class]) {
    return nil;
  }
  NSString *empty = SHDWFingerprintASCIIHash(@"");
  NSString *hardware = SHDWFingerprintASCIIHash(hardwareLeaves);
  NSString *authentication =
      SHDWFingerprintASCIIHash(SHDWFingerprintASCIIHash(biometry));
  NSString *groups = [@[empty, hardware, empty, empty, empty, authentication]
      componentsJoinedByString:@""];
  return SHDWFingerprintASCIIHash(groups);
}
@end
