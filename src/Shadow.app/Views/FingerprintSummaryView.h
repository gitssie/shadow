#import <UIKit/UIKit.h>
@interface SHDWFingerprintSummaryView : UIControl
- (void)showSystemVersion:(NSString *)version region:(NSString *)region;
- (void)showUpdatedAt:(NSNumber *)timestamp;
@end
