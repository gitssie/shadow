#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
FOUNDATION_EXPORT UIColor *SHDWBackground(void);
FOUNDATION_EXPORT UIColor *SHDWInk(void);
FOUNDATION_EXPORT UIColor *SHDWAccent(void);
FOUNDATION_EXPORT UIColor *SHDWLockColor(void);
FOUNDATION_EXPORT NSString *SHDWText(NSString *key);
FOUNDATION_EXPORT UIImage * _Nullable SHDWSymbol(NSString *name, CGFloat size);
FOUNDATION_EXPORT void SHDWShowError(UIViewController *controller, NSError * _Nullable error);
NS_ASSUME_NONNULL_END
