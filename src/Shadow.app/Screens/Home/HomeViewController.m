#import "HomeViewController.h"
#import "Screens/Applications/AppSelectionViewController.h"
#import "Screens/Fingerprint/FingerprintDetailViewController.h"
#import "Services/InstalledApplications.h"
#import "Views/AppSelectorView.h"
#import "Views/FingerprintActionControl.h"
#import "Views/FingerprintSummaryView.h"
#import "Appearance/Theme.h"
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>
static NSString *const SHDWSelectedApplicationKey = @"SelectedApplicationBundleIdentifier";
@interface SHDWHomeViewController () <UIGestureRecognizerDelegate>
@property(nonatomic, strong) SHDWAppSelectorView *selector;
@property(nonatomic, strong) SHDWFingerprintActionControl *refreshControl;
@property(nonatomic, strong) SHDWFingerprintSummaryView *summary;
@property(nonatomic, strong) UIButton *addButton;
@property(nonatomic, strong) UIButton *manageButton;
@property(nonatomic, strong) UIButton *lockButton;
@property(nonatomic, strong) NSLayoutConstraint *selectorHeight;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *applications;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *registered;
@property(nonatomic, strong) SHDWInstalledApplication *selected;
@property(nonatomic, strong) dispatch_queue_t operationQueue;
@property(nonatomic) BOOL busy;
@end
@implementation SHDWHomeViewController
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.operationQueue = dispatch_queue_create("me.jjolano.shadow.manager.operations", DISPATCH_QUEUE_SERIAL);
    self.selector = [SHDWAppSelectorView new];
    __weak typeof(self) weakSelf = self;
    self.selector.heightChanged = ^(CGFloat height, BOOL animated) { typeof(self) self = weakSelf; if (!self) return; self.selectorHeight.constant = height; [self.view bringSubviewToFront:self.selector]; if (animated) [UIView animateWithDuration:0.22 delay:0 options:UIViewAnimationOptionBeginFromCurrentState | UIViewAnimationOptionCurveEaseInOut animations:^{ [self.view layoutIfNeeded]; } completion:nil]; else [self.view layoutIfNeeded]; };
    self.selector.selectionChanged = ^(SHDWInstalledApplication *app) { typeof(self) self = weakSelf; if (!self || self.busy) return; self.selected = app; [self.refreshControl setWorking:NO]; [self renderSelection]; };
    self.refreshControl = [SHDWFingerprintActionControl new]; [self.refreshControl addTarget:self action:@selector(refreshFingerprint) forControlEvents:UIControlEventTouchUpInside];
    self.summary = [SHDWFingerprintSummaryView new]; [self.summary addTarget:self action:@selector(showDetails) forControlEvents:UIControlEventTouchUpInside];
    UIImageView *mark = [[UIImageView alloc] initWithImage:SHDWSymbol(@"touchid", 30)]; mark.tintColor = SHDWAccent(); mark.contentMode = UIViewContentModeScaleAspectFit;
    UIStackView *brand = [[UIStackView alloc] initWithArrangedSubviews:@[mark]]; brand.alignment = UIStackViewAlignmentCenter;
    self.manageButton = [UIButton buttonWithType:UIButtonTypeSystem]; [self.manageButton setImage:SHDWSymbol(@"plus", 17) forState:UIControlStateNormal]; [self.manageButton addTarget:self action:@selector(manageApplications) forControlEvents:UIControlEventTouchUpInside]; self.manageButton.accessibilityLabel = SHDWText(@"Applications"); self.manageButton.accessibilityIdentifier = @"home.manage-applications";
    self.lockButton = [UIButton buttonWithType:UIButtonTypeCustom]; [self.lockButton addTarget:self action:@selector(lockFingerprint) forControlEvents:UIControlEventTouchUpInside]; self.lockButton.accessibilityIdentifier = @"home.lock-fingerprint";
    self.addButton = [UIButton buttonWithType:UIButtonTypeSystem]; [self.addButton setTitle:SHDWText(@"Add application") forState:UIControlStateNormal]; [self.addButton setImage:SHDWSymbol(@"plus.circle.fill", 22) forState:UIControlStateNormal]; self.addButton.titleLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleHeadline]; self.addButton.backgroundColor = UIColor.whiteColor; self.addButton.layer.cornerRadius = 16; [self.addButton addTarget:self action:@selector(manageApplications) forControlEvents:UIControlEventTouchUpInside]; self.addButton.accessibilityIdentifier = @"home.add-application";
    UIView *operationRegion = [UIView new]; operationRegion.userInteractionEnabled = YES;
    for (UIView *view in @[brand, self.manageButton, self.lockButton, self.selector, operationRegion, self.summary, self.addButton]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    self.refreshControl.translatesAutoresizingMaskIntoConstraints = NO; [operationRegion addSubview:self.refreshControl];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    self.selectorHeight = [self.selector.heightAnchor constraintEqualToConstant:70]; self.selectorHeight.active = YES;
    [NSLayoutConstraint activateConstraints:@[
        [brand.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:22], [brand.topAnchor constraintEqualToAnchor:safe.topAnchor constant:20], [brand.heightAnchor constraintEqualToConstant:44], [mark.widthAnchor constraintEqualToConstant:30],
        [self.manageButton.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16], [self.manageButton.centerYAnchor constraintEqualToAnchor:brand.centerYAnchor], [self.manageButton.widthAnchor constraintEqualToConstant:44], [self.manageButton.heightAnchor constraintEqualToConstant:44], [brand.trailingAnchor constraintLessThanOrEqualToAnchor:self.lockButton.leadingAnchor constant:-8], [self.lockButton.trailingAnchor constraintEqualToAnchor:self.manageButton.leadingAnchor constant:-8], [self.lockButton.centerYAnchor constraintEqualToAnchor:brand.centerYAnchor], [self.lockButton.widthAnchor constraintEqualToConstant:44], [self.lockButton.heightAnchor constraintEqualToConstant:44],
        [self.selector.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16], [self.selector.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16], [self.selector.topAnchor constraintEqualToAnchor:brand.bottomAnchor constant:20], [self.selector.heightAnchor constraintGreaterThanOrEqualToConstant:70],
        [self.summary.leadingAnchor constraintEqualToAnchor:self.selector.leadingAnchor], [self.summary.trailingAnchor constraintEqualToAnchor:self.selector.trailingAnchor], [self.summary.bottomAnchor constraintEqualToAnchor:safe.bottomAnchor constant:-20], [self.summary.heightAnchor constraintGreaterThanOrEqualToConstant:76],
        [operationRegion.topAnchor constraintEqualToAnchor:self.selector.topAnchor constant:86], [operationRegion.bottomAnchor constraintEqualToAnchor:self.summary.topAnchor constant:-20], [operationRegion.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor], [operationRegion.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor],
        [self.refreshControl.centerXAnchor constraintEqualToAnchor:operationRegion.centerXAnchor], [self.refreshControl.centerYAnchor constraintEqualToAnchor:operationRegion.centerYAnchor constant:-12], [self.refreshControl.widthAnchor constraintEqualToConstant:160], [self.refreshControl.heightAnchor constraintEqualToAnchor:self.refreshControl.widthAnchor], [self.refreshControl.topAnchor constraintGreaterThanOrEqualToAnchor:operationRegion.topAnchor], [self.refreshControl.bottomAnchor constraintLessThanOrEqualToAnchor:operationRegion.bottomAnchor],
        [self.addButton.heightAnchor constraintGreaterThanOrEqualToConstant:56], [self.addButton.widthAnchor constraintGreaterThanOrEqualToConstant:200], [self.addButton.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor], [self.addButton.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor], [self.addButton.leadingAnchor constraintGreaterThanOrEqualToAnchor:safe.leadingAnchor constant:24], [self.addButton.trailingAnchor constraintLessThanOrEqualToAnchor:safe.trailingAnchor constant:-24]
    ]];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(reloadApplications) name:UIApplicationWillEnterForegroundNotification object:nil];
    UITapGestureRecognizer *outsideTap = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(dismissApplicationSelector)]; outsideTap.delegate = self; outsideTap.cancelsTouchesInView = NO; [self.view addGestureRecognizer:outsideTap];
    [self reloadApplications];
}
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self]; }
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.navigationController setNavigationBarHidden:YES animated:animated]; if (self.isViewLoaded && !self.busy) [self reloadApplications]; }
- (void)viewWillDisappear:(BOOL)animated { [super viewWillDisappear:animated]; [self.navigationController setNavigationBarHidden:NO animated:animated]; }
- (void)reloadApplications {
    if (self.busy) return;
    self.applications = [SHDWInstalledApplications applications]; NSSet *identifiers = [NSSet setWithArray:[[SHDWFingerprintStore sharedStore] registeredBundleIdentifiers]];
    self.registered = [self.applications filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(SHDWInstalledApplication *app, NSDictionary *bindings) { return [identifiers containsObject:app.bundleIdentifier]; }]];
    NSString *selectedID = self.selected.bundleIdentifier ?: [NSUserDefaults.standardUserDefaults stringForKey:SHDWSelectedApplicationKey]; self.selected = nil;
    for (SHDWInstalledApplication *app in self.registered) if ([app.bundleIdentifier isEqualToString:selectedID]) { self.selected = app; break; }
    if (!self.selected && !selectedID.length) self.selected = self.registered.firstObject;
    [self renderSelection];
}
- (void)renderSelection {
    BOOL present = self.selected != nil; self.selector.hidden = !present && !self.registered.count; self.refreshControl.hidden = !present; self.summary.hidden = !present; self.addButton.hidden = present || self.registered.count > 0;
    if (present) { [NSUserDefaults.standardUserDefaults setObject:self.selected.bundleIdentifier forKey:SHDWSelectedApplicationKey]; [self.selector showApplication:self.selected fingerprint:[[SHDWFingerprintStore sharedStore] deviceFingerprintForApplication:self.selected.bundleIdentifier]]; }
    if (!present) [self.selector showApplication:nil fingerprint:nil];
    [self.selector showApplications:self.registered selected:self.selected];
    SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
    BOOL locked = present && [store lockedForApplication:self.selected.bundleIdentifier];
    BOOL enabled = present && [store enabledForApplication:self.selected.bundleIdentifier];
    [self.refreshControl setRefreshAllowed:enabled locked:locked];
    self.lockButton.hidden = !present; self.lockButton.enabled = present && !self.busy;
    [self.lockButton setImage:SHDWSymbol(locked ? @"lock.fill" : @"lock.open", 17) forState:UIControlStateNormal]; self.lockButton.tintColor = locked ? SHDWLockColor() : UIColor.secondaryLabelColor;
    self.lockButton.accessibilityLabel = SHDWText(locked ? @"Unlock fingerprint" : @"Lock fingerprint");
    NSDictionary *configuration = present ? [store configurationForApplication:self.selected.bundleIdentifier] : [SHDWFingerprintConfiguration defaultConfiguration];
    NSDictionary *systemProfile = [SHDWFingerprintConfiguration systemProfileForConfiguration:configuration];
    [self.summary showSystemVersion:systemProfile[@"Version"] ?: UIDevice.currentDevice.systemVersion region:[NSLocale.currentLocale objectForKey:NSLocaleCountryCode] ?: @"—"];
    [self.summary showUpdatedAt:present ? [[SHDWFingerprintStore sharedStore] profileForBundleIdentifier:self.selected.bundleIdentifier][@"UpdatedAt"] : nil];
}
- (void)manageApplications {
    if (self.busy) return;
    [self.selector setExpanded:NO animated:NO];
    SHDWAppSelectionViewController *controller = [SHDWAppSelectionViewController new]; __weak typeof(self) weakSelf = self;
    controller.selectionChanged = ^(NSString *identifier, NSSet<NSString *> *removedIdentifiers) {
        typeof(self) self = weakSelf; if (!self) return;
        NSString *previous = self.selected.bundleIdentifier ?: [NSUserDefaults.standardUserDefaults stringForKey:SHDWSelectedApplicationKey];
        NSArray *registered = [[SHDWFingerprintStore sharedStore] registeredBundleIdentifiers]; self.selected = nil;
        if (identifier.length && [registered containsObject:identifier]) [NSUserDefaults.standardUserDefaults setObject:identifier forKey:SHDWSelectedApplicationKey];
        else if (previous.length && [removedIdentifiers containsObject:previous]) [NSUserDefaults.standardUserDefaults removeObjectForKey:SHDWSelectedApplicationKey];
        [self reloadApplications];
    };
    UINavigationController *navigation = [[UINavigationController alloc] initWithRootViewController:controller]; [self presentViewController:navigation animated:YES completion:nil];
}
- (void)dismissApplicationSelector { [self.selector setExpanded:NO animated:YES]; }
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gestureRecognizer shouldReceiveTouch:(UITouch *)touch {
    return self.selector.expanded && ![touch.view isDescendantOfView:self.selector];
}
- (void)lockFingerprint {
    if (self.busy || !self.selected) return;
    SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
    BOOL locked = [store lockedForApplication:self.selected.bundleIdentifier];
    NSError *error = nil;
    if (![store setLocked:!locked forApplication:self.selected.bundleIdentifier error:&error]) SHDWShowError(self, error);
    [self renderSelection];
}
- (void)refreshFingerprint {
    if (self.busy || !self.selected) return;
    SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
    if (![store enabledForApplication:self.selected.bundleIdentifier] || [store lockedForApplication:self.selected.bundleIdentifier]) { [self renderSelection]; return; }
    [self.selector setExpanded:NO animated:YES];
    NSString *identifier = [self.selected.bundleIdentifier copy]; self.busy = YES; self.selector.enabled = NO; self.summary.enabled = NO; self.manageButton.enabled = NO; self.lockButton.enabled = NO; [self.refreshControl setWorking:YES];
    __weak typeof(self) weakSelf = self;
    dispatch_async(self.operationQueue, ^{ NSError *error = nil; BOOL success = [[SHDWFingerprintStore sharedStore] refreshApplication:identifier error:&error];
        dispatch_async(dispatch_get_main_queue(), ^{ typeof(self) self = weakSelf; if (!self) return; self.busy = NO; self.selector.enabled = YES; self.summary.enabled = YES; self.manageButton.enabled = YES; [self.refreshControl setWorking:NO]; [self reloadApplications];
            if (success && [self.selected.bundleIdentifier isEqualToString:identifier]) [self.refreshControl showCompleted]; else if (!success) SHDWShowError(self, error);
        });
    });
}
- (void)showDetails { if (self.busy || !self.selected) return; [self.selector setExpanded:NO animated:NO]; [self.navigationController pushViewController:[[SHDWFingerprintDetailViewController alloc] initWithBundleIdentifier:self.selected.bundleIdentifier name:self.selected.name] animated:YES]; }
@end
