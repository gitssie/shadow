#import "BackupViewController.h"
#import "Services/BackupService.h"
#import "Services/OperationCoordinator.h"
#import "Services/InstalledApplications.h"
#import "Views/AppSelectorView.h"
#import "Appearance/Theme.h"
#import <Shadow/Fingerprint.h>

static NSString *const SelectedApplicationKey = @"SelectedApplicationBundleIdentifier";
static NSString *CanonicalIDFV(NSString *value) { return [value isKindOfClass:NSString.class] ? [[NSUUID alloc] initWithUUIDString:value].UUIDString : nil; }
static NSString *Abbreviate(NSString *value) { return value.length > 16 ? [NSString stringWithFormat:@"%@…%@", [value substringToIndex:8], [value substringFromIndex:value.length - 6]] : (value ?: @"—"); }
static NSString *BackupDate(id value) { if (![value isKindOfClass:NSDate.class]) return @"—"; NSDateFormatter *format = [NSDateFormatter new]; format.dateFormat = @"MM-dd HH:mm"; return [format stringFromDate:value]; }
static NSString *ProgressTitle(NSDictionary *event) {
    NSString *stage = event[@"stage"] ?: @"";
    if ([stage containsString:@"verify"] || [stage isEqual:@"recheck"]) return SHDWText(@"Verifying backup");
    if ([event[@"phase"] isEqual:@"restore"]) return SHDWText(@"Restoring data");
    return SHDWText(@"Backing up data");
}
@interface SHDWBackupButton : UIButton
@property(nonatomic, strong) UIActivityIndicatorView *spinner;
@property(nonatomic, strong) UIImageView *symbol;
- (void)setWorking:(BOOL)working;
@end
@implementation SHDWBackupButton
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) { self.backgroundColor = SHDWAccent(); self.layer.cornerRadius = 15; self.titleLabel.font = [UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]; [self setTitleColor:UIColor.whiteColor forState:UIControlStateNormal]; [self setTitleColor:[UIColor.whiteColor colorWithAlphaComponent:0.7] forState:UIControlStateDisabled]; self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.spinner.color = UIColor.whiteColor; self.spinner.hidesWhenStopped = YES; self.spinner.userInteractionEnabled = NO; [self addSubview:self.spinner]; self.symbol = [[UIImageView alloc] initWithImage:SHDWSymbol(@"square.and.arrow.up", 20)]; self.symbol.tintColor = UIColor.whiteColor; self.symbol.contentMode = UIViewContentModeScaleAspectFit; self.symbol.userInteractionEnabled = NO; [self addSubview:self.symbol]; }
    return self;
}
- (void)setWorking:(BOOL)working { self.symbol.hidden = working; if (working) [self.spinner startAnimating]; else [self.spinner stopAnimating]; [self setNeedsLayout]; }
- (void)layoutSubviews { [super layoutSubviews]; CGSize title = [self.titleLabel sizeThatFits:CGSizeMake(MAX(0, self.bounds.size.width - 60), self.bounds.size.height)]; CGFloat x = (self.bounds.size.width - title.width - 28) / 2; self.spinner.frame = CGRectMake(x, (self.bounds.size.height - 20) / 2, 20, 20); self.symbol.frame = self.spinner.frame; self.titleLabel.frame = CGRectMake(x + 28, (self.bounds.size.height - title.height) / 2, title.width, title.height); }
@end

@interface SHDWBackupPresentation : UIPresentationController
@property(nonatomic, strong) UIControl *shade;
@end
@implementation SHDWBackupPresentation
- (CGRect)frameOfPresentedViewInContainerView { CGRect bounds = self.containerView.bounds; CGFloat height = MIN(bounds.size.height - self.containerView.safeAreaInsets.top - 16, 354 + self.containerView.safeAreaInsets.bottom); return CGRectMake(0, bounds.size.height - height, bounds.size.width, height); }
- (void)presentationTransitionWillBegin { self.shade = [UIControl new]; self.shade.backgroundColor = [UIColor.blackColor colorWithAlphaComponent:0.34]; [self.shade addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside]; [self.containerView insertSubview:self.shade atIndex:0]; self.shade.alpha = 0; [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(__unused id<UIViewControllerTransitionCoordinatorContext> context) { self.shade.alpha = 1; } completion:nil]; }
- (void)dismissalTransitionWillBegin { [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(__unused id<UIViewControllerTransitionCoordinatorContext> context) { self.shade.alpha = 0; } completion:nil]; }
- (void)containerViewWillLayoutSubviews { self.shade.frame = self.containerView.bounds; self.presentedView.frame = self.frameOfPresentedViewInContainerView; }
- (void)close { if (!self.presentedViewController.modalInPresentation) [self.presentedViewController dismissViewControllerAnimated:YES completion:nil]; }
@end

@interface SHDWRestoreViewController : UIViewController <UIViewControllerTransitioningDelegate>
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, strong) NSDictionary *snapshot;
@property(nonatomic) BOOL sameIdentity;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic, strong) UISwitch *saveCurrent;
@property(nonatomic, strong) SHDWBackupButton *action;
@property(nonatomic, strong) UIButton *closeButton;
@property(nonatomic, strong) UILabel *status;
@property(nonatomic, copy) void (^completion)(void);
@property(nonatomic) BOOL completed;
@property(nonatomic) BOOL requiresRecovery;
@end
@implementation SHDWRestoreViewController
- (instancetype)init { if ((self = [super init])) { self.modalPresentationStyle = UIModalPresentationCustom; self.transitioningDelegate = self; } return self; }
- (UIPresentationController *)presentationControllerForPresentedViewController:(UIViewController *)presented presentingViewController:(UIViewController *)presenting sourceViewController:(UIViewController *)source { (void)source; return [[SHDWBackupPresentation alloc] initWithPresentedViewController:presented presentingViewController:presenting]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.view.layer.cornerRadius = 22; self.view.clipsToBounds = YES; self.view.accessibilityIdentifier = @"backup.restore-sheet";
    UIView *grabber = [UIView new]; grabber.backgroundColor = UIColor.tertiaryLabelColor; grabber.layer.cornerRadius = 1.5;
    UIImageView *icon = [[UIImageView alloc] initWithImage:[SHDWInstalledApplications iconForApplication:self.application]]; icon.layer.cornerRadius = 5; icon.clipsToBounds = YES;
    UILabel *title = [UILabel new]; title.text = SHDWText(@"Restore backup"); title.font = [UIFont systemFontOfSize:17 weight:UIFontWeightSemibold]; title.textColor = SHDWInk();
    self.closeButton = [UIButton buttonWithType:UIButtonTypeSystem]; [self.closeButton setImage:SHDWSymbol(@"xmark", 15) forState:UIControlStateNormal]; self.closeButton.tintColor = UIColor.secondaryLabelColor; self.closeButton.accessibilityLabel = SHDWText(@"Close"); [self.closeButton addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside];
    UIView *card = [UIView new]; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16;
    UILabel *name = [UILabel new]; name.text = self.snapshot[@"title"]; name.font = [UIFont systemFontOfSize:15 weight:UIFontWeightMedium]; name.textColor = SHDWInk();
    UILabel *date = [UILabel new]; date.text = BackupDate(self.snapshot[@"date"]); date.font = [UIFont systemFontOfSize:11]; date.textColor = UIColor.secondaryLabelColor;
    UILabel *save = [UILabel new]; save.text = SHDWText(@"Back up current data first"); save.font = [UIFont systemFontOfSize:15]; save.textColor = SHDWInk();
    BOOL recovery = [self.snapshot[@"restorePending"] boolValue]; self.requiresRecovery = recovery; self.saveCurrent = [UISwitch new]; self.saveCurrent.onTintColor = SHDWAccent(); self.saveCurrent.on = !self.sameIdentity && !recovery; self.saveCurrent.enabled = !self.sameIdentity && !recovery; self.saveCurrent.accessibilityIdentifier = @"backup.restore.save-current"; [self.saveCurrent addTarget:self action:@selector(updateTitle) forControlEvents:UIControlEventValueChanged];
    UILabel *hint = [UILabel new]; hint.font = [UIFont systemFontOfSize:11]; hint.textColor = UIColor.secondaryLabelColor; hint.numberOfLines = 0; hint.text = SHDWText(self.sameIdentity ? @"Current data uses this backup identity; restore without overwriting it." : (recovery ? @"Retry the interrupted restore without backing up partial data." : @"The restored fingerprint stays locked."));
    self.action = [SHDWBackupButton new]; self.action.symbol.image = SHDWSymbol(@"square.and.arrow.down", 20); self.action.accessibilityIdentifier = @"backup.restore.confirm"; [self.action addTarget:self action:@selector(restore) forControlEvents:UIControlEventTouchUpInside];
    self.status = [UILabel new]; self.status.font = [UIFont systemFontOfSize:12]; self.status.numberOfLines = 0; self.status.textColor = UIColor.secondaryLabelColor; self.status.accessibilityIdentifier = @"backup.restore.status";
    for (UIView *view in @[grabber, icon, title, self.closeButton, card, hint, self.action, self.status]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    for (UIView *view in @[name, date, save, self.saveCurrent]) { view.translatesAutoresizingMaskIntoConstraints = NO; [card addSubview:view]; }
    [NSLayoutConstraint activateConstraints:@[[grabber.topAnchor constraintEqualToAnchor:self.view.topAnchor constant:4], [grabber.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor], [grabber.widthAnchor constraintEqualToConstant:32], [grabber.heightAnchor constraintEqualToConstant:3], [icon.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:18], [icon.topAnchor constraintEqualToAnchor:self.view.topAnchor constant:15], [icon.widthAnchor constraintEqualToConstant:22], [icon.heightAnchor constraintEqualToConstant:22], [title.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:10], [title.centerYAnchor constraintEqualToAnchor:icon.centerYAnchor], [title.trailingAnchor constraintLessThanOrEqualToAnchor:self.closeButton.leadingAnchor], [self.closeButton.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-6], [self.closeButton.centerYAnchor constraintEqualToAnchor:icon.centerYAnchor], [self.closeButton.widthAnchor constraintEqualToConstant:44], [self.closeButton.heightAnchor constraintEqualToConstant:44], [card.topAnchor constraintEqualToAnchor:self.view.topAnchor constant:48], [card.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:16], [card.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-16], [card.heightAnchor constraintEqualToConstant:110], [name.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:16], [name.topAnchor constraintEqualToAnchor:card.topAnchor constant:12], [name.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-16], [date.leadingAnchor constraintEqualToAnchor:name.leadingAnchor], [date.topAnchor constraintEqualToAnchor:name.bottomAnchor constant:4], [save.leadingAnchor constraintEqualToAnchor:name.leadingAnchor], [save.centerYAnchor constraintEqualToAnchor:card.bottomAnchor constant:-27], [save.trailingAnchor constraintLessThanOrEqualToAnchor:self.saveCurrent.leadingAnchor constant:-8], [self.saveCurrent.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-14], [self.saveCurrent.centerYAnchor constraintEqualToAnchor:save.centerYAnchor], [hint.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:4], [hint.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-4], [hint.topAnchor constraintEqualToAnchor:card.bottomAnchor constant:12], [self.action.leadingAnchor constraintEqualToAnchor:card.leadingAnchor], [self.action.trailingAnchor constraintEqualToAnchor:card.trailingAnchor], [self.action.topAnchor constraintEqualToAnchor:hint.bottomAnchor constant:16], [self.action.heightAnchor constraintEqualToConstant:48], [self.status.leadingAnchor constraintEqualToAnchor:card.leadingAnchor constant:4], [self.status.trailingAnchor constraintEqualToAnchor:card.trailingAnchor constant:-4], [self.status.topAnchor constraintEqualToAnchor:self.action.bottomAnchor constant:10], [self.status.bottomAnchor constraintLessThanOrEqualToAnchor:self.view.safeAreaLayoutGuide.bottomAnchor constant:-12]]]; [self updateTitle];
}
- (void)updateTitle { [self.action setTitle:SHDWText(self.saveCurrent.on ? @"Back up and restore" : @"Restore backup") forState:UIControlStateNormal]; }
- (void)close { if (!self.service.running) [self dismissViewControllerAnimated:YES completion:nil]; }
- (void)restore {
    if (self.completed || self.service.running || [SHDWOperationCoordinator isRunning]) return;
    self.action.enabled = NO; self.saveCurrent.enabled = NO; self.closeButton.enabled = NO; self.modalInPresentation = YES; [self.action setWorking:YES]; [self.action setTitle:SHDWText(@"Restoring data") forState:UIControlStateNormal]; self.status.textColor = UIColor.secondaryLabelColor;
    __weak typeof(self) weakSelf = self;
    [self.service performAction:@"restore" request:@{@"idfv": self.snapshot[@"idfv"], @"saveCurrent": @(self.saveCurrent.on)} progress:^(NSDictionary *event) { weakSelf.status.text = ProgressTitle(event); } completion:^(id result, NSError *error) { typeof(self) self = weakSelf; if (!self) return; (void)result; [self.action setWorking:NO]; self.closeButton.enabled = YES; self.modalInPresentation = NO; self.completed = error == nil; self.requiresRecovery = self.requiresRecovery || [error.userInfo[@"stateMayBePartial"] boolValue]; if (self.requiresRecovery) self.saveCurrent.on = NO; self.action.enabled = error != nil; self.saveCurrent.enabled = !self.completed && !self.sameIdentity && !self.requiresRecovery; self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; self.status.text = error ? error.localizedDescription : SHDWText(@"Restore completed"); if (error) [self updateTitle]; else [self.action setTitle:SHDWText(@"Restore completed") forState:UIControlStateNormal]; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, self.status.text); if (self.completion) self.completion(); }];
}
@end

@interface SHDWBackupViewController () <UITableViewDataSource, UITableViewDelegate, UIGestureRecognizerDelegate>
@property(nonatomic, strong) SHDWAppSelectorView *selector;
@property(nonatomic, strong) NSLayoutConstraint *selectorHeight;
@property(nonatomic, strong) SHDWBackupButton *action;
@property(nonatomic, strong) UILabel *status;
@property(nonatomic, strong) UITableView *table;
@property(nonatomic, strong) NSLayoutConstraint *tableHeight;
@property(nonatomic, strong) UILabel *empty;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *applications;
@property(nonatomic, strong) SHDWInstalledApplication *selected;
@property(nonatomic, copy) NSArray<NSDictionary *> *catalog;
@property(nonatomic, copy) NSString *liveIDFV;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic) BOOL loading;
@property(nonatomic) BOOL catalogFailed;
@property(nonatomic) BOOL working;
@property(nonatomic) NSUInteger loadGeneration;
@end
@implementation SHDWBackupViewController
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"Data backups"); self.view.backgroundColor = SHDWBackground(); self.view.accessibilityIdentifier = @"backup.screen";
    self.selector = [SHDWAppSelectorView new]; self.selector.accessibilityIdentifier = @"backup.application-selector"; __weak typeof(self) weakSelf = self;
    self.selector.heightChanged = ^(CGFloat height, BOOL animated) { typeof(self) self = weakSelf; if (!self) return; self.selectorHeight.constant = height; [self.view bringSubviewToFront:self.selector]; if (animated) [UIView animateWithDuration:0.22 animations:^{ [self.view layoutIfNeeded]; }]; };
    self.selector.selectionChanged = ^(SHDWInstalledApplication *application) { typeof(self) self = weakSelf; if (!self || self.working || [SHDWOperationCoordinator isRunning]) return; self.selected = application; [NSUserDefaults.standardUserDefaults setObject:application.bundleIdentifier forKey:SelectedApplicationKey]; [self showSelection]; };
    self.action = [SHDWBackupButton new]; self.action.accessibilityIdentifier = @"backup.current"; [self.action addTarget:self action:@selector(backupCurrent) forControlEvents:UIControlEventTouchUpInside];
    self.status = [UILabel new]; self.status.font = [UIFont systemFontOfSize:12]; self.status.numberOfLines = 0; self.status.textColor = UIColor.secondaryLabelColor; self.status.accessibilityIdentifier = @"backup.status";
    self.table = [[UITableView alloc] initWithFrame:CGRectZero style:UITableViewStylePlain]; self.table.backgroundColor = UIColor.clearColor; self.table.layer.cornerRadius = 18; self.table.clipsToBounds = YES; self.table.rowHeight = 60; self.table.dataSource = self; self.table.delegate = self; self.table.separatorInset = UIEdgeInsetsMake(0, 16, 0, 16); self.table.separatorColor = [SHDWInk() colorWithAlphaComponent:0.06]; self.table.tableFooterView = [UIView new]; self.table.accessibilityIdentifier = @"backup.snapshots";
    self.empty = [UILabel new]; self.empty.textAlignment = NSTextAlignmentCenter; self.empty.font = [UIFont systemFontOfSize:14]; self.empty.textColor = UIColor.secondaryLabelColor; self.empty.numberOfLines = 0; self.table.backgroundView = self.empty;
    for (UIView *view in @[self.selector, self.action, self.status, self.table]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    self.selectorHeight = [self.selector.heightAnchor constraintEqualToConstant:70]; self.selectorHeight.active = YES; self.tableHeight = [self.table.heightAnchor constraintEqualToConstant:140]; self.tableHeight.priority = UILayoutPriorityDefaultHigh; self.tableHeight.active = YES;
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[[self.selector.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12], [self.selector.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16], [self.selector.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16], [self.action.topAnchor constraintEqualToAnchor:self.selector.topAnchor constant:86], [self.action.leadingAnchor constraintEqualToAnchor:self.selector.leadingAnchor], [self.action.trailingAnchor constraintEqualToAnchor:self.selector.trailingAnchor], [self.action.heightAnchor constraintEqualToConstant:48], [self.status.topAnchor constraintEqualToAnchor:self.action.bottomAnchor constant:8], [self.status.leadingAnchor constraintEqualToAnchor:self.action.leadingAnchor constant:4], [self.status.trailingAnchor constraintEqualToAnchor:self.action.trailingAnchor constant:-4], [self.table.topAnchor constraintEqualToAnchor:self.status.bottomAnchor constant:10], [self.table.leadingAnchor constraintEqualToAnchor:self.selector.leadingAnchor], [self.table.trailingAnchor constraintEqualToAnchor:self.selector.trailingAnchor], [self.table.bottomAnchor constraintLessThanOrEqualToAnchor:safe.bottomAnchor constant:-16]]];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(activityChanged) name:SHDWOperationDidChangeNotification object:nil]; [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(reloadApplications) name:UIApplicationWillEnterForegroundNotification object:nil];
    UITapGestureRecognizer *outside = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(collapseSelector)]; outside.cancelsTouchesInView = NO; outside.delegate = self; [self.view addGestureRecognizer:outside]; [self reloadApplications];
}
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self]; }
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.navigationController setNavigationBarHidden:NO animated:animated]; if (!self.working) [self reloadApplications]; }
- (void)collapseSelector { [self.selector setExpanded:NO animated:YES]; }
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer shouldReceiveTouch:(UITouch *)touch { (void)recognizer; return self.selector.expanded && ![touch.view isDescendantOfView:self.selector]; }
- (void)reloadApplications {
    if (self.working || [SHDWOperationCoordinator isRunning]) return;
    NSSet *registered = [NSSet setWithArray:[[SHDWFingerprintStore sharedStore] registeredBundleIdentifiers]];
    self.applications = [[SHDWInstalledApplications applications] filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(SHDWInstalledApplication *app, NSDictionary *bindings) { (void)bindings; return [registered containsObject:app.bundleIdentifier]; }]];
    NSString *identifier = [NSUserDefaults.standardUserDefaults stringForKey:SelectedApplicationKey]; self.selected = nil;
    for (SHDWInstalledApplication *application in self.applications) if ([application.bundleIdentifier isEqual:identifier]) { self.selected = application; break; }
    if (!self.selected) self.selected = self.applications.firstObject;
    [self showSelection];
}
- (void)showSelection {
    if (self.selected) [NSUserDefaults.standardUserDefaults setObject:self.selected.bundleIdentifier forKey:SelectedApplicationKey];
    self.liveIDFV = self.selected ? CanonicalIDFV([[SHDWFingerprintStore sharedStore] profileForBundleIdentifier:self.selected.bundleIdentifier][@"VendorIdentifier"]) : nil;
    [self.selector showApplication:self.selected fingerprint:self.selected ? [[SHDWFingerprintStore sharedStore] deviceFingerprintForApplication:self.selected.bundleIdentifier] : nil]; [self.selector showApplications:self.applications selected:self.selected]; self.selector.hidden = !self.applications.count;
    self.service = self.selected ? [[SHDWBackupService alloc] initWithBundleIdentifier:self.selected.bundleIdentifier] : nil; self.catalog = @[]; [self.table reloadData]; [self loadCatalog];
}
- (void)loadCatalog {
    NSUInteger generation = ++self.loadGeneration; self.loading = self.service != nil; self.catalogFailed = NO; self.status.text = nil; [self updateControls]; if (!self.service) return;
    __weak typeof(self) weakSelf = self; [self.service loadCatalog:^(NSArray *catalog, NSError *error) { typeof(self) self = weakSelf; if (!self || generation != self.loadGeneration) return; self.loading = NO; self.catalogFailed = error != nil; self.catalog = catalog ?: @[]; self.status.text = error.localizedDescription; self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; [self.table reloadData]; [self updateControls]; }];
}
- (NSDictionary *)currentSnapshot { for (NSDictionary *item in self.catalog) if ([CanonicalIDFV(item[@"idfv"]) isEqual:self.liveIDFV]) return item; return nil; }
- (void)updateControls {
    self.tableHeight.constant = self.catalog.count ? self.catalog.count * 60 : 140;
    BOOL busy = self.working || [SHDWOperationCoordinator isRunning]; BOOL pending = [self.catalog.firstObject[@"restorePending"] boolValue]; self.selector.enabled = !busy; self.table.userInteractionEnabled = !busy; self.action.enabled = self.selected && self.liveIDFV && !self.loading && !self.catalogFailed && !busy && !pending; self.action.alpha = self.action.enabled || self.working ? 1 : 0.5;
    if (!self.working) [self.action setTitle:SHDWText([self currentSnapshot] ? @"Update current backup" : @"Back up current data") forState:UIControlStateNormal];
    self.empty.text = !self.selected ? SHDWText(@"Choose an application on Home to create a backup.") : (!self.liveIDFV ? SHDWText(@"Refresh the fingerprint on Home before creating a backup.") : (self.loading ? SHDWText(@"Loading backups") : SHDWText(@"No backups yet"))); self.empty.hidden = self.catalog.count > 0;
}
- (void)activityChanged { [self updateControls]; }
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { (void)tableView; (void)section; return self.catalog.count; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    (void)tableView; NSDictionary *item = self.catalog[indexPath.row]; UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:nil]; cell.selectionStyle = UITableViewCellSelectionStyleNone; cell.backgroundColor = UIColor.whiteColor;
    UILabel *title = [UILabel new]; title.text = item[@"title"]; title.font = [UIFont systemFontOfSize:15 weight:UIFontWeightMedium]; title.textColor = SHDWInk(); [title setContentCompressionResistancePriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
    UILabel *current = [UILabel new]; current.text = [NSString stringWithFormat:@" %@ ", SHDWText(@"Current")]; current.font = [UIFont systemFontOfSize:10 weight:UIFontWeightMedium]; current.textColor = SHDWAccent(); current.backgroundColor = [SHDWAccent() colorWithAlphaComponent:0.09]; current.layer.cornerRadius = 8; current.clipsToBounds = YES; current.hidden = ![CanonicalIDFV(item[@"idfv"]) isEqual:self.liveIDFV];
    UIImageView *fingerprint = [[UIImageView alloc] initWithImage:SHDWSymbol(@"touchid", 12)]; fingerprint.tintColor = [SHDWAccent() colorWithAlphaComponent:0.65]; fingerprint.contentMode = UIViewContentModeScaleAspectFit;
    UILabel *digest = [UILabel new]; digest.text = Abbreviate(item[@"digest"]); digest.font = [UIFont monospacedSystemFontOfSize:10 weight:UIFontWeightRegular]; digest.textColor = UIColor.secondaryLabelColor;
    UILabel *detail = [UILabel new]; detail.font = [UIFont systemFontOfSize:10]; detail.textColor = UIColor.secondaryLabelColor; detail.textAlignment = NSTextAlignmentRight; detail.text = [NSString stringWithFormat:@"%@ · %@", BackupDate(item[@"date"]), [NSByteCountFormatter stringFromByteCount:[item[@"size"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile]];
    UIButton *more = [UIButton buttonWithType:UIButtonTypeSystem]; [more setImage:SHDWSymbol(@"ellipsis", 17) forState:UIControlStateNormal]; more.tintColor = SHDWInk(); more.tag = indexPath.row; more.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", item[@"title"], SHDWText(@"Backup actions")]; more.accessibilityIdentifier = [@"backup.actions." stringByAppendingString:item[@"idfv"]]; [more addTarget:self action:@selector(showActions:) forControlEvents:UIControlEventTouchUpInside];
    for (UIView *view in @[title, current, fingerprint, digest, detail, more]) { view.translatesAutoresizingMaskIntoConstraints = NO; [cell.contentView addSubview:view]; }
    [NSLayoutConstraint activateConstraints:@[[title.leadingAnchor constraintEqualToAnchor:cell.contentView.leadingAnchor constant:16], [title.topAnchor constraintEqualToAnchor:cell.contentView.topAnchor constant:10], [title.trailingAnchor constraintLessThanOrEqualToAnchor:more.leadingAnchor constant:-8], [current.leadingAnchor constraintEqualToAnchor:title.trailingAnchor constant:8], [current.centerYAnchor constraintEqualToAnchor:title.centerYAnchor], [current.trailingAnchor constraintLessThanOrEqualToAnchor:more.leadingAnchor constant:-4], [current.heightAnchor constraintEqualToConstant:17], [fingerprint.leadingAnchor constraintEqualToAnchor:title.leadingAnchor], [fingerprint.centerYAnchor constraintEqualToAnchor:digest.centerYAnchor], [fingerprint.widthAnchor constraintEqualToConstant:12], [fingerprint.heightAnchor constraintEqualToConstant:12], [digest.leadingAnchor constraintEqualToAnchor:fingerprint.trailingAnchor constant:6], [digest.topAnchor constraintEqualToAnchor:title.bottomAnchor constant:5], [detail.leadingAnchor constraintGreaterThanOrEqualToAnchor:digest.trailingAnchor constant:8], [detail.trailingAnchor constraintEqualToAnchor:cell.contentView.trailingAnchor constant:-16], [detail.centerYAnchor constraintEqualToAnchor:digest.centerYAnchor], [more.trailingAnchor constraintEqualToAnchor:cell.contentView.trailingAnchor constant:-6], [more.topAnchor constraintEqualToAnchor:cell.contentView.topAnchor], [more.widthAnchor constraintEqualToConstant:44], [more.heightAnchor constraintEqualToConstant:32]]]; cell.accessibilityIdentifier = [@"backup.snapshot." stringByAppendingString:item[@"idfv"]]; return cell;
}
- (void)backupCurrent { if (!self.action.enabled) return; [self collapseSelector]; if ([self currentSnapshot]) [self perform:@"backup" request:@{}]; else [self editMetadata:nil]; }
- (void)editMetadata:(NSDictionary *)snapshot {
    if (self.working || [SHDWOperationCoordinator isRunning]) return;
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:SHDWText(snapshot ? @"Edit backup" : @"New backup") message:nil preferredStyle:UIAlertControllerStyleAlert];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) { field.placeholder = SHDWText(@"Name"); field.text = snapshot ? snapshot[@"title"] : self.selected.name; field.clearButtonMode = UITextFieldViewModeWhileEditing; }];
    [alert addTextFieldWithConfigurationHandler:^(UITextField *field) { field.placeholder = SHDWText(@"Note"); field.text = snapshot[@"note"] ?: @""; }];
    [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    __weak typeof(self) weakSelf = self; [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"Save") style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) { NSString *title = [alert.textFields[0].text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet]; NSString *note = alert.textFields[1].text ?: @""; if (!title.length || title.length > 100 || note.length > 1000) { weakSelf.status.textColor = UIColor.systemRedColor; weakSelf.status.text = SHDWText(@"Use a name of 1–100 characters and a note up to 1000 characters."); return; } NSMutableDictionary *request = [@{@"metadata": @{@"title":title, @"note":note}} mutableCopy]; if (snapshot) request[@"idfv"] = snapshot[@"idfv"]; [weakSelf perform:snapshot ? @"edit" : @"backup" request:request]; }]]; [self presentViewController:alert animated:YES completion:nil];
}
- (void)showActions:(UIButton *)sender {
    if (self.working || [SHDWOperationCoordinator isRunning] || (NSUInteger)sender.tag >= self.catalog.count) return; [self collapseSelector]; NSDictionary *snapshot = self.catalog[sender.tag]; BOOL protected = [snapshot[@"recoverySource"] boolValue]; BOOL pending = [snapshot[@"restorePending"] boolValue];
    UIAlertController *menu = [UIAlertController alertControllerWithTitle:snapshot[@"title"] message:nil preferredStyle:UIAlertControllerStyleActionSheet]; __weak typeof(self) weakSelf = self;
    UIAlertAction *restore = [UIAlertAction actionWithTitle:SHDWText(protected ? @"Retry restore" : @"Restore backup") style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) { [weakSelf showRestore:snapshot]; }]; restore.enabled = !pending || protected; [menu addAction:restore];
    UIAlertAction *edit = [UIAlertAction actionWithTitle:SHDWText(@"Edit backup") style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) { [weakSelf editMetadata:snapshot]; }]; edit.enabled = !protected; [menu addAction:edit];
    [menu addAction:[UIAlertAction actionWithTitle:SHDWText(@"Recheck backup") style:UIAlertActionStyleDefault handler:^(__unused UIAlertAction *action) { [weakSelf perform:@"recheck" request:@{@"idfv":snapshot[@"idfv"]}]; }]];
    UIAlertAction *remove = [UIAlertAction actionWithTitle:SHDWText(@"Delete backup") style:UIAlertActionStyleDestructive handler:^(__unused UIAlertAction *action) { [weakSelf confirmDelete:snapshot]; }]; remove.enabled = !protected; [menu addAction:remove]; [menu addAction:[UIAlertAction actionWithTitle:SHDWText(@"Cancel") style:UIAlertActionStyleCancel handler:nil]]; menu.popoverPresentationController.sourceView = sender; menu.popoverPresentationController.sourceRect = sender.bounds; [self presentViewController:menu animated:YES completion:nil];
}
- (void)confirmDelete:(NSDictionary *)snapshot { UIAlertController *alert = [UIAlertController alertControllerWithTitle:SHDWText(@"Delete backup?") message:snapshot[@"title"] preferredStyle:UIAlertControllerStyleAlert]; [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"Cancel") style:UIAlertActionStyleCancel handler:nil]]; __weak typeof(self) weakSelf = self; [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"Delete backup") style:UIAlertActionStyleDestructive handler:^(__unused UIAlertAction *action) { [weakSelf perform:@"delete" request:@{@"idfv":snapshot[@"idfv"]}]; }]]; [self presentViewController:alert animated:YES completion:nil]; }
- (void)showRestore:(NSDictionary *)snapshot { SHDWRestoreViewController *controller = [SHDWRestoreViewController new]; controller.application = self.selected; controller.snapshot = snapshot; controller.sameIdentity = [CanonicalIDFV(snapshot[@"idfv"]) isEqual:self.liveIDFV]; controller.service = self.service; __weak typeof(self) weakSelf = self; controller.completion = ^{ [weakSelf reloadApplications]; }; [self presentViewController:controller animated:YES completion:nil]; }
- (void)perform:(NSString *)action request:(NSDictionary *)request {
    if (self.working || [SHDWOperationCoordinator isRunning] || !self.service) return;
    self.working = YES; self.status.textColor = UIColor.secondaryLabelColor; self.status.text = SHDWText([action isEqual:@"recheck"] ? @"Verifying backup" : ([action isEqual:@"edit"] ? @"Saving changes" : ([action isEqual:@"delete"] ? @"Deleting backup" : @"Backing up data"))); [self.action setTitle:self.status.text forState:UIControlStateNormal]; [self.action setWorking:YES]; [self collapseSelector]; [self updateControls];
    __weak typeof(self) weakSelf = self; [self.service performAction:action request:request progress:^(NSDictionary *event) { weakSelf.status.text = ProgressTitle(event); } completion:^(id result, NSError *error) { typeof(self) self = weakSelf; if (!self) return; (void)result; self.working = NO; [self.action setWorking:NO]; NSString *message = error ? error.localizedDescription : SHDWText([action isEqual:@"recheck"] ? @"Backup verified" : ([action isEqual:@"delete"] ? @"Backup deleted" : @"Backup saved")); self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; self.status.text = message; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, message); self.liveIDFV = CanonicalIDFV([[SHDWFingerprintStore sharedStore] profileForBundleIdentifier:self.selected.bundleIdentifier][@"VendorIdentifier"]); NSUInteger generation = ++self.loadGeneration; [self.service loadCatalog:^(NSArray *catalog, NSError *catalogError) { if (generation != self.loadGeneration) return; self.catalogFailed = catalogError != nil; self.catalog = catalog ?: self.catalog; if (catalogError && !error) self.status.text = catalogError.localizedDescription; [self.table reloadData]; [self updateControls]; }]; }];
}
@end
