#import "TabBarController.h"
#import "Screens/Home/HomeViewController.h"
#import "Screens/Settings/SettingsViewController.h"
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
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(reloadTabs) name:SHDWLanguageDidChangeNotification object:nil]; [self reloadTabs];
}
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self]; }
- (void)reloadTabs {
    NSUInteger selected = self.viewControllers.count ? self.selectedIndex : 0;
    UINavigationController *home = [[UINavigationController alloc] initWithRootViewController:[SHDWHomeViewController new]];
    UINavigationController *settings = [[UINavigationController alloc] initWithRootViewController:[SHDWSettingsViewController new]];
    home.tabBarItem = [[UITabBarItem alloc] initWithTitle:@"" image:nil selectedImage:nil]; settings.tabBarItem = [[UITabBarItem alloc] initWithTitle:@"" image:nil selectedImage:nil];
    home.tabBarItem.accessibilityLabel = SHDWText(@"Home"); settings.tabBarItem.accessibilityLabel = SHDWText(@"Settings");
    for (UINavigationController *navigation in @[home, settings]) navigation.topViewController.navigationItem.backBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Back") style:UIBarButtonItemStylePlain target:nil action:nil];
    self.viewControllers = @[home, settings]; self.selectedIndex = MIN(selected, (NSUInteger)1); [self.bottomBar updateAccessibilityLabels]; [self.view setNeedsLayout];
}
- (void)setSelectedIndex:(NSUInteger)selectedIndex { [super setSelectedIndex:selectedIndex]; self.bottomBar.selectedIndex = selectedIndex; }
- (void)changeTab:(SHDWTabBarView *)sender { self.selectedIndex = sender.selectedIndex; }
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews]; self.tabBar.alpha = 0;
    self.bottomBar.frame = [self.view convertRect:self.tabBar.bounds fromView:self.tabBar]; [self.view bringSubviewToFront:self.bottomBar];
}
@end
