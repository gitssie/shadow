#import <UIKit/UIKit.h>
@class SHDWInstalledApplication;
@interface SHDWAppSelectorView : UIButton
@property(nonatomic, copy) void (^heightChanged)(CGFloat height, BOOL animated);
@property(nonatomic, copy) void (^selectionChanged)(SHDWInstalledApplication *application);
@property(nonatomic, readonly, getter=isExpanded) BOOL expanded;
- (void)showApplication:(SHDWInstalledApplication *)application fingerprint:(NSString *)fingerprint;
- (void)showApplications:(NSArray<SHDWInstalledApplication *> *)applications selected:(SHDWInstalledApplication *)selected;
- (void)setExpanded:(BOOL)expanded animated:(BOOL)animated;
@end
