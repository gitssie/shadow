#import <UIKit/UIKit.h>
NS_ASSUME_NONNULL_BEGIN
@interface SHDWInstalledApplication : NSObject
@property(nonatomic, copy) NSString *bundleIdentifier;
@property(nonatomic, copy) NSString *name;
@property(nonatomic, strong, nullable) NSURL *bundleURL;
@end
@interface SHDWInstalledApplications : NSObject
+ (NSArray<SHDWInstalledApplication *> *)applications;
+ (UIImage * _Nullable)iconForApplication:(nullable SHDWInstalledApplication *)application;
@end
NS_ASSUME_NONNULL_END
