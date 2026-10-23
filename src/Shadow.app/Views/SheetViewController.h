#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT UIButton *SHDWSheetPrimaryButton(NSString *title, NSString *symbol, id target, SEL action);
@interface SHDWSheetViewController : UIViewController
@property(nonatomic, copy) NSString *sheetTitle;
@property(nonatomic, strong, nullable) UIImage *sheetIcon;
@property(nonatomic, strong, readonly) UIStackView *contentStack;
@property(nonatomic, strong, readonly) UIButton *closeButton;
- (void)requestSheetLayout;
- (void)scrollToView:(UIView *)view animated:(BOOL)animated;
- (void)close;
@end
FOUNDATION_EXPORT void SHDWPresentMessageSheet(UIViewController *controller, NSString *title, NSString *message);
NS_ASSUME_NONNULL_END
