#import <Foundation/Foundation.h>
NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT NSNotificationName const SHDWOperationDidChangeNotification;
@interface SHDWOperationCoordinator : NSObject
+ (BOOL)isRunning;
+ (BOOL)beginOperation:(NSError * _Nullable * _Nullable)error;
+ (void)endOperation;
@end
NS_ASSUME_NONNULL_END
