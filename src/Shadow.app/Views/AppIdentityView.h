#import <UIKit/UIKit.h>
@class SHDWInstalledApplication;
@interface SHDWAppIdentityView : UIView
- (void)showApplication:(SHDWInstalledApplication *)application fingerprint:(NSString *)fingerprint;
@end
