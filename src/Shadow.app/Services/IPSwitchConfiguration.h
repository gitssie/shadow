#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
@interface SHDWIPSwitchConfiguration : NSObject
+ (NSArray<NSDictionary<NSString *, NSString *> *> *)configurations;
+ (BOOL)saveConfigurations:(NSArray<NSDictionary<NSString *, NSString *> *> *)configurations error:(NSError **)error;
+ (nullable NSURL *)URLForString:(NSString *)value;
@end
NS_ASSUME_NONNULL_END
