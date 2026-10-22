#import "TabBarController.h"
#import "Screens/Home/HomeViewController.h"
#import "Screens/Settings/SettingsViewController.h"
#import "Screens/Backup/BackupViewController.h"
#import "Services/OperationCoordinator.h"
#import "Services/Language.h"
#import "Views/TabBarView.h"
#import "Appearance/Theme.h"
@interface SHDWTabBarController ()
@property(nonatomic, strong) SHDWTabBarView *bottomBar;
@end
@implementation SHDWTabBarController
- (void)viewDidLoad {
    [super viewDidLoad]; self.tabBar.alpha = 0; self.tabBar.userInteractionEnabled = NO; self.tabBar.accessibilityElementsHidden = YES;
    self.bottomBar = [SHDWTabBarView new]; [self.bottomBar addTarget:self action:@selector(changeTab:) forControlEvents:UIControlEventValueChanged]; [self.view addSubview:self.bottomBar];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(reloadTabs) name:SHDWLanguageDidChangeNotification object:nil]; [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(activityChanged) name:SHDWOperationDidChangeNotification object:nil]; [self reloadTabs];
}
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self]; }
- (void)reloadTabs {
    NSUInteger selected = self.viewControllers.count ? self.selectedIndex : 0;
    UINavigationController *home = [[UINavigationController alloc] initWithRootViewController:[SHDWHomeViewController new]];
    UINavigationController *backup = [[UINavigationController alloc] initWithRootViewController:[SHDWBackupViewController new]];
    UINavigationController *settings = [[UINavigationController alloc] initWithRootViewController:[SHDWSettingsViewController new]];
    home.tabBarItem = [[UITabBarItem alloc] initWithTitle:@"" image:nil selectedImage:nil]; settings.tabBarItem = [[UITabBarItem alloc] initWithTitle:@"" image:nil selectedImage:nil];
    backup.tabBarItem = [[UITabBarItem alloc] initWithTitle:@"" image:nil selectedImage:nil]; backup.tabBarItem.accessibilityLabel = SHDWText(@"Data backups");
    home.tabBarItem.accessibilityLabel = SHDWText(@"Home"); settings.tabBarItem.accessibilityLabel = SHDWText(@"Settings");
    for (UINavigationController *navigation in @[home, backup, settings]) navigation.topViewController.navigationItem.backBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Back") style:UIBarButtonItemStylePlain target:nil action:nil];
    self.viewControllers = @[home, backup, settings]; self.selectedIndex = MIN(selected, (NSUInteger)2); [self.bottomBar updateAccessibilityLabels]; [self.view setNeedsLayout];
}
- (void)activityChanged { self.bottomBar.userInteractionEnabled = ![SHDWOperationCoordinator isRunning]; }
- (void)setSelectedIndex:(NSUInteger)selectedIndex { if ([SHDWOperationCoordinator isRunning] && self.viewControllers.count && selectedIndex != self.selectedIndex) return; [super setSelectedIndex:selectedIndex]; self.bottomBar.selectedIndex = selectedIndex; }
- (void)changeTab:(SHDWTabBarView *)sender { if ([SHDWOperationCoordinator isRunning]) { sender.selectedIndex = self.selectedIndex; return; } self.selectedIndex = sender.selectedIndex; }
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews]; self.tabBar.alpha = 0;
    self.bottomBar.frame = [self.view convertRect:self.tabBar.bounds fromView:self.tabBar]; [self.view bringSubviewToFront:self.bottomBar];
}
@end
