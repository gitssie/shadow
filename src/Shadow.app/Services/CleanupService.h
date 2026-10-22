#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
typedef void (^SHDWCleanupProgress)(NSString *step, NSString *state, NSString * _Nullable message);
@interface SHDWCleanupService : NSObject
@property(atomic, readonly) BOOL running;
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier;
- (void)startWithSteps:(NSArray<NSString *> *)steps
              progress:(SHDWCleanupProgress)progress
            completion:(void (^)(BOOL success, NSError * _Nullable error))completion;
@end
NS_ASSUME_NONNULL_END
