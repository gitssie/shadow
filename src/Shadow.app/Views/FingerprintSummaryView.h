#import <UIKit/UIKit.h>
@interface SHDWFingerprintSummaryView : UIControl
@property(nonatomic, copy) void (^cleanupTapped)(void);
- (void)showSystemVersion:(NSString *)version region:(NSString *)region;
- (void)showUpdatedAt:(NSNumber *)timestamp;
@end
