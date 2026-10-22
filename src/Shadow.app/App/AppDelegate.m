#import "AppDelegate.h"
#import "TabBarController.h"
#import "Appearance/Theme.h"
@implementation SHDWAppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds]; self.window.tintColor = SHDWAccent();
    self.window.rootViewController = [SHDWTabBarController new];
    [self.window makeKeyAndVisible]; return YES;
}
@end
