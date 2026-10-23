#import "Views/SheetViewController.h"
@class SHDWInstalledApplication, SHDWBackupService;

NS_ASSUME_NONNULL_BEGIN
@interface SHDWBackupPromptViewController : SHDWSheetViewController
@property(nonatomic, copy, nullable) void (^proceed)(BOOL backupCompleted);
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application service:(SHDWBackupService *)service;
@end
NS_ASSUME_NONNULL_END
