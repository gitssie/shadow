#import "Views/SheetViewController.h"
@class SHDWInstalledApplication;

NS_ASSUME_NONNULL_BEGIN
@interface SHDWBackupActionsViewController : SHDWSheetViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application snapshot:(NSDictionary *)snapshot currentIDFV:(nullable NSString *)currentIDFV;
@property(nonatomic, copy, nullable) void (^selection)(NSString *action);
@end
NS_ASSUME_NONNULL_END
