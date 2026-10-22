#import <UIKit/UIKit.h>
@interface SHDWFingerprintActionControl : UIControl
- (void)setRefreshAllowed:(BOOL)allowed locked:(BOOL)locked;
- (void)setWorking:(BOOL)working;
- (void)showCompleted;
@end
