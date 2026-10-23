#import "Views/SheetViewController.h"
@class SHDWInstalledApplication;

NS_ASSUME_NONNULL_BEGIN
@interface SHDWBackupMetadataViewController : SHDWSheetViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application snapshot:(nullable NSDictionary *)snapshot;
@property(nonatomic, copy, nullable) void (^save)(NSDictionary *metadata);
@end
NS_ASSUME_NONNULL_END
