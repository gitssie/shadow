#import <UIKit/UIKit.h>
@class SHDWInstalledApplication;
NS_ASSUME_NONNULL_BEGIN
@interface SHDWCleanupViewController : UIViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application;
@property(nonatomic, copy, nullable) void (^completion)(void);
@end
NS_ASSUME_NONNULL_END
