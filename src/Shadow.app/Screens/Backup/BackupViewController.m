#import "BackupViewController.h"
#import "BackupActionsViewController.h"
#import "BackupMetadataViewController.h"
#import "Views/SheetViewController.h"
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
    if ((self = [super initWithFrame:frame])) { self.backgroundColor = SHDWAccent(); self.layer.cornerRadius = 14; self.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]]; self.titleLabel.adjustsFontForContentSizeCategory = YES; [self setTitleColor:UIColor.whiteColor forState:UIControlStateNormal]; [self setTitleColor:[UIColor.whiteColor colorWithAlphaComponent:0.7] forState:UIControlStateDisabled]; self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.spinner.color = UIColor.whiteColor; self.spinner.hidesWhenStopped = YES; self.spinner.userInteractionEnabled = NO; [self addSubview:self.spinner]; self.symbol = [[UIImageView alloc] initWithImage:SHDWSymbol(@"square.and.arrow.up", 20)]; self.symbol.tintColor = UIColor.whiteColor; self.symbol.contentMode = UIViewContentModeScaleAspectFit; self.symbol.userInteractionEnabled = NO; [self addSubview:self.symbol]; }
    return self;
}
- (void)setWorking:(BOOL)working { self.symbol.hidden = working; if (working) [self.spinner startAnimating]; else [self.spinner stopAnimating]; [self setNeedsLayout]; }
- (void)layoutSubviews { [super layoutSubviews]; CGSize title = [self.titleLabel sizeThatFits:CGSizeMake(MAX(0, self.bounds.size.width - 60), self.bounds.size.height)]; CGFloat x = (self.bounds.size.width - title.width - 28) / 2; self.spinner.frame = CGRectMake(x, (self.bounds.size.height - 20) / 2, 20, 20); self.symbol.frame = self.spinner.frame; self.titleLabel.frame = CGRectMake(x + 28, (self.bounds.size.height - title.height) / 2, title.width, title.height); }
@end

@interface SHDWRestoreViewController : SHDWSheetViewController
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, strong) NSDictionary *snapshot;
@property(nonatomic) BOOL sameIDFV;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic, strong) UISwitch *saveCurrent;
@property(nonatomic, strong) SHDWBackupButton *action;
@property(nonatomic, strong) UILabel *status;
@property(nonatomic, strong) UIStackView *saveRow;
@property(nonatomic, strong) UILabel *hint;
@property(nonatomic, copy) void (^completion)(void);
@property(nonatomic) BOOL completed;
@property(nonatomic) BOOL requiresRecovery;
@end
@implementation SHDWRestoreViewController
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Restore backup"); self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application];
    [super viewDidLoad]; self.view.accessibilityIdentifier = @"backup.restore-sheet";
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.spacing = 16; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.layoutMarginsRelativeArrangement = YES; card.layoutMargins = UIEdgeInsetsMake(14, 16, 14, 16);
    UILabel *name = [UILabel new]; name.text = self.snapshot[@"title"]; name.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:15 weight:UIFontWeightMedium]]; name.adjustsFontForContentSizeCategory = YES; name.textColor = SHDWInk(); name.numberOfLines = 0;
    UILabel *date = [UILabel new]; date.text = BackupDate(self.snapshot[@"date"]); date.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleCaption1] scaledFontForFont:[UIFont systemFontOfSize:12]]; date.adjustsFontForContentSizeCategory = YES; date.textColor = UIColor.secondaryLabelColor;
    UIStackView *details = [[UIStackView alloc] initWithArrangedSubviews:@[name, date]]; details.axis = UILayoutConstraintAxisVertical; details.spacing = 4; [card addArrangedSubview:details];
    UILabel *save = [UILabel new]; save.text = SHDWText(@"Back up current data first"); save.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:15]]; save.adjustsFontForContentSizeCategory = YES; save.textColor = SHDWInk(); save.numberOfLines = 0;
    BOOL recovery = [self.snapshot[@"restorePending"] boolValue]; self.requiresRecovery = recovery;
    self.saveCurrent = [UISwitch new]; self.saveCurrent.onTintColor = SHDWAccent(); self.saveCurrent.on = !self.sameIDFV && !recovery; self.saveCurrent.accessibilityIdentifier = @"backup.restore.save-current"; [self.saveCurrent addTarget:self action:@selector(updateTitle) forControlEvents:UIControlEventValueChanged];
    self.saveRow = [[UIStackView alloc] initWithArrangedSubviews:@[save, self.saveCurrent]]; self.saveRow.spacing = 12; self.saveRow.alignment = UIStackViewAlignmentCenter; [self.saveCurrent setContentHuggingPriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisHorizontal]; [card addArrangedSubview:self.saveRow]; self.saveRow.hidden = self.sameIDFV || recovery;
    self.hint = [UILabel new]; self.hint.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont systemFontOfSize:12]]; self.hint.adjustsFontForContentSizeCategory = YES; self.hint.textColor = UIColor.secondaryLabelColor; self.hint.numberOfLines = 0; self.hint.text = SHDWText(self.sameIDFV ? @"This backup belongs to the current IDFV and cannot be restored." : (recovery ? @"Retry the interrupted restore without backing up partial data." : @"The restored fingerprint stays locked."));
    self.action = [SHDWBackupButton new]; self.action.symbol.image = SHDWSymbol(@"square.and.arrow.down", 20); [self.action.heightAnchor constraintGreaterThanOrEqualToConstant:48].active = YES; self.action.accessibilityIdentifier = @"backup.restore.confirm"; [self.action addTarget:self action:@selector(restore) forControlEvents:UIControlEventTouchUpInside];
    self.status = [UILabel new]; self.status.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont systemFontOfSize:12]]; self.status.adjustsFontForContentSizeCategory = YES; self.status.numberOfLines = 0; self.status.hidden = YES; self.status.accessibilityIdentifier = @"backup.restore.status";
    for (UIView *view in @[card, self.hint, self.action, self.status]) [self.contentStack addArrangedSubview:view]; self.action.enabled = !self.sameIDFV; [self updateTitle];
}
- (void)updateTitle { [self.action setTitle:SHDWText(self.saveCurrent.on ? @"Back up and restore" : @"Restore backup") forState:UIControlStateNormal]; }
- (void)close { if (!self.service.running) [self dismissViewControllerAnimated:YES completion:nil]; }
- (void)restore {
    if (self.sameIDFV || self.completed || self.service.running || [SHDWOperationCoordinator isRunning]) return;
    self.action.enabled = NO; self.saveCurrent.enabled = NO; self.closeButton.enabled = NO; self.modalInPresentation = YES; [self.action setWorking:YES]; [self.action setTitle:SHDWText(@"Restoring data") forState:UIControlStateNormal]; self.status.textColor = UIColor.secondaryLabelColor;
    __weak typeof(self) weakSelf = self;
    [self.service performAction:@"restore" request:@{@"idfv": self.snapshot[@"idfv"], @"saveCurrent": @(!self.sameIDFV && !self.requiresRecovery && self.saveCurrent.on)} progress:^(NSDictionary *event) { weakSelf.status.hidden = NO; weakSelf.status.text = ProgressTitle(event); [weakSelf requestSheetLayout]; } completion:^(id result, NSError *error) { typeof(self) self = weakSelf; if (!self) return; (void)result; [self.action setWorking:NO]; self.closeButton.enabled = YES; self.modalInPresentation = NO; self.completed = error == nil; self.requiresRecovery = self.requiresRecovery || [error.userInfo[@"stateMayBePartial"] boolValue]; if (self.requiresRecovery) { self.saveCurrent.on = NO; self.saveRow.hidden = YES; self.hint.text = SHDWText(@"Retry the interrupted restore without backing up partial data."); } self.action.enabled = error != nil; self.saveCurrent.enabled = !self.completed && !self.sameIDFV && !self.requiresRecovery; self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; self.status.hidden = NO; self.status.text = error ? error.localizedDescription : SHDWText(@"Restore completed"); [self requestSheetLayout]; if (error) [self updateTitle]; else [self.action setTitle:SHDWText(@"Restore completed") forState:UIControlStateNormal]; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, self.status.text); if (self.completion) self.completion(); }];
}
@end

@interface SHDWDeleteBackupViewController : SHDWSheetViewController
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, copy) NSDictionary *snapshot;
@property(nonatomic, copy) void (^confirm)(void);
@property(nonatomic) BOOL finishing;
@end
@implementation SHDWDeleteBackupViewController
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Delete backup?"); self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application]; [super viewDidLoad]; self.view.accessibilityIdentifier = @"backup.delete-sheet";
    UILabel *name = [UILabel new]; name.text = self.snapshot[@"title"]; name.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:15]]; name.adjustsFontForContentSizeCategory = YES; name.textColor = SHDWInk(); name.numberOfLines = 0;
    UILabel *date = [UILabel new]; date.text = BackupDate(self.snapshot[@"date"]); date.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleCaption1] scaledFontForFont:[UIFont systemFontOfSize:12]]; date.adjustsFontForContentSizeCategory = YES; date.textColor = UIColor.secondaryLabelColor;
    UIStackView *card = [[UIStackView alloc] initWithArrangedSubviews:@[name, date]]; card.axis = UILayoutConstraintAxisVertical; card.spacing = 4; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.layoutMarginsRelativeArrangement = YES; card.layoutMargins = UIEdgeInsetsMake(14, 16, 14, 16);
    UIButton *remove = SHDWSheetPrimaryButton(SHDWText(@"Delete backup"), @"trash", self, @selector(deleteBackup)); remove.backgroundColor = SHDWDestructiveColor(); remove.accessibilityIdentifier = @"backup.delete.confirm";
    [self.contentStack addArrangedSubview:card]; [self.contentStack addArrangedSubview:remove];
}
- (void)deleteBackup {
    if (self.finishing || [SHDWOperationCoordinator isRunning]) return;
    self.finishing = YES; self.view.userInteractionEnabled = NO; void (^confirm)(void) = self.confirm;
    [self dismissViewControllerAnimated:YES completion:^{ if (confirm) confirm(); }];
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
@property(nonatomic, strong) UIImageView *emptyIcon;
@property(nonatomic, strong) UIActivityIndicatorView *listSpinner;
@property(nonatomic, strong) UIView *listBackground;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *applications;
@property(nonatomic, strong) SHDWInstalledApplication *selected;
@property(nonatomic, copy) NSArray<NSDictionary *> *catalog;
@property(nonatomic, copy) NSString *liveIDFV;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic) BOOL loading;
@property(nonatomic) BOOL reloadPending;
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
    self.empty = [UILabel new]; self.empty.textAlignment = NSTextAlignmentCenter; self.empty.font = [UIFont systemFontOfSize:14]; self.empty.textColor = UIColor.secondaryLabelColor; self.empty.numberOfLines = 0;
    self.emptyIcon = [[UIImageView alloc] initWithImage:SHDWSymbol(@"tray", 28)]; self.emptyIcon.tintColor = [SHDWAccent() colorWithAlphaComponent:0.45]; self.emptyIcon.contentMode = UIViewContentModeScaleAspectFit; self.emptyIcon.isAccessibilityElement = YES; self.emptyIcon.accessibilityLabel = SHDWText(@"No backups yet"); self.emptyIcon.accessibilityIdentifier = @"backup.empty";
    self.listSpinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.listSpinner.color = SHDWAccent(); self.listSpinner.hidesWhenStopped = YES; self.listSpinner.isAccessibilityElement = YES; self.listSpinner.accessibilityLabel = SHDWText(@"Loading backups"); self.listSpinner.accessibilityIdentifier = @"backup.loading";
    self.listBackground = [UIView new]; self.table.backgroundView = self.listBackground;
    UIStackView *emptyContent = [[UIStackView alloc] initWithArrangedSubviews:@[self.listSpinner, self.emptyIcon, self.empty]]; emptyContent.axis = UILayoutConstraintAxisVertical; emptyContent.alignment = UIStackViewAlignmentCenter; emptyContent.spacing = 12; emptyContent.translatesAutoresizingMaskIntoConstraints = NO; [self.listBackground addSubview:emptyContent];
    [NSLayoutConstraint activateConstraints:@[[emptyContent.centerXAnchor constraintEqualToAnchor:self.listBackground.centerXAnchor], [emptyContent.centerYAnchor constraintEqualToAnchor:self.listBackground.centerYAnchor], [emptyContent.leadingAnchor constraintGreaterThanOrEqualToAnchor:self.listBackground.leadingAnchor constant:16], [emptyContent.trailingAnchor constraintLessThanOrEqualToAnchor:self.listBackground.trailingAnchor constant:-16], [self.emptyIcon.widthAnchor constraintEqualToConstant:32], [self.emptyIcon.heightAnchor constraintEqualToConstant:32]]];
    for (UIView *view in @[self.selector, self.action, self.status, self.table]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    self.selectorHeight = [self.selector.heightAnchor constraintEqualToConstant:70]; self.selectorHeight.active = YES; self.tableHeight = [self.table.heightAnchor constraintEqualToConstant:140]; self.tableHeight.priority = UILayoutPriorityDefaultHigh; self.tableHeight.active = YES;
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[[self.selector.topAnchor constraintEqualToAnchor:safe.topAnchor constant:12], [self.selector.leadingAnchor constraintEqualToAnchor:safe.leadingAnchor constant:16], [self.selector.trailingAnchor constraintEqualToAnchor:safe.trailingAnchor constant:-16], [self.action.topAnchor constraintEqualToAnchor:self.selector.topAnchor constant:86], [self.action.leadingAnchor constraintEqualToAnchor:self.selector.leadingAnchor], [self.action.trailingAnchor constraintEqualToAnchor:self.selector.trailingAnchor], [self.action.heightAnchor constraintEqualToConstant:48], [self.status.topAnchor constraintEqualToAnchor:self.action.bottomAnchor constant:8], [self.status.leadingAnchor constraintEqualToAnchor:self.action.leadingAnchor constant:4], [self.status.trailingAnchor constraintEqualToAnchor:self.action.trailingAnchor constant:-4], [self.table.topAnchor constraintEqualToAnchor:self.status.bottomAnchor constant:10], [self.table.leadingAnchor constraintEqualToAnchor:self.selector.leadingAnchor], [self.table.trailingAnchor constraintEqualToAnchor:self.selector.trailingAnchor], [self.table.bottomAnchor constraintLessThanOrEqualToAnchor:safe.bottomAnchor constant:-16]]];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(activityChanged) name:SHDWOperationDidChangeNotification object:nil]; [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(reloadApplications) name:UIApplicationWillEnterForegroundNotification object:nil];
    UITapGestureRecognizer *outside = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(collapseSelector)]; outside.cancelsTouchesInView = NO; outside.delegate = self; [self.view addGestureRecognizer:outside];
}
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self]; }
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.navigationController setNavigationBarHidden:NO animated:animated]; if (!self.working) [self reloadApplications]; }
- (void)collapseSelector { [self.selector setExpanded:NO animated:YES]; }
- (BOOL)gestureRecognizer:(UIGestureRecognizer *)recognizer shouldReceiveTouch:(UITouch *)touch { (void)recognizer; return self.selector.expanded && ![touch.view isDescendantOfView:self.selector]; }
- (void)reloadApplications {
    if (self.working || [SHDWOperationCoordinator isRunning]) { self.reloadPending = YES; return; }
    if (self.loading) { self.reloadPending = YES; return; }
    self.reloadPending = NO;
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
    __weak typeof(self) weakSelf = self; [self.service loadCatalog:^(NSArray *catalog, NSError *error) { typeof(self) self = weakSelf; if (!self || generation != self.loadGeneration) return; self.loading = NO; if (self.reloadPending && !self.working && ![SHDWOperationCoordinator isRunning]) { [self reloadApplications]; return; } self.catalogFailed = error != nil; self.catalog = catalog ?: @[]; self.status.text = error.localizedDescription; self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; [self.table reloadData]; [self updateControls]; }];
}
- (NSDictionary *)currentSnapshot { for (NSDictionary *item in self.catalog) if ([CanonicalIDFV(item[@"idfv"]) isEqual:self.liveIDFV]) return item; return nil; }
- (void)updateControls {
    self.tableHeight.constant = self.catalog.count ? self.catalog.count * 60 : 140;
    BOOL busy = self.working || [SHDWOperationCoordinator isRunning]; BOOL pending = [self.catalog.firstObject[@"restorePending"] boolValue]; self.selector.enabled = !busy && !self.loading; self.table.userInteractionEnabled = !busy; self.action.enabled = self.selected && self.liveIDFV && !self.loading && !self.catalogFailed && !busy && !pending; self.action.alpha = self.action.enabled || self.working || self.loading ? 1 : 0.5; [self.action setWorking:self.working || self.loading];
    if (!self.working) [self.action setTitle:SHDWText([self currentSnapshot] ? @"Update current backup" : @"Back up current data") forState:UIControlStateNormal];
    self.listBackground.hidden = self.catalog.count > 0;
    if (self.loading && !self.listBackground.hidden) [self.listSpinner startAnimating]; else [self.listSpinner stopAnimating];
    NSString *guidance = !self.selected ? SHDWText(@"Choose an application on Home to create a backup.") : (!self.liveIDFV ? SHDWText(@"Refresh the fingerprint on Home before creating a backup.") : nil);
    self.empty.text = guidance; self.empty.hidden = self.loading || !guidance.length;
    self.emptyIcon.hidden = self.loading || guidance.length || self.catalogFailed;
}
- (void)activityChanged { if (self.reloadPending && !self.loading && !self.working && ![SHDWOperationCoordinator isRunning]) [self reloadApplications]; else [self updateControls]; }
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
    SHDWBackupMetadataViewController *editor = [[SHDWBackupMetadataViewController alloc] initWithApplication:self.selected snapshot:snapshot];
    __weak typeof(self) weakSelf = self;
    editor.save = ^(NSDictionary *metadata) { NSMutableDictionary *request = [@{@"metadata":metadata} mutableCopy]; if (snapshot) request[@"idfv"] = snapshot[@"idfv"]; [weakSelf perform:snapshot ? @"edit" : @"backup" request:request]; };
    [self presentViewController:editor animated:YES completion:nil];
}
- (void)showActions:(UIButton *)sender {
    if (self.working || [SHDWOperationCoordinator isRunning] || (NSUInteger)sender.tag >= self.catalog.count) return;
    [self collapseSelector]; NSDictionary *snapshot = self.catalog[sender.tag];
    SHDWBackupActionsViewController *menu = [[SHDWBackupActionsViewController alloc] initWithApplication:self.selected snapshot:snapshot currentIDFV:self.liveIDFV]; __weak typeof(self) weakSelf = self;
    menu.selection = ^(NSString *action) {
        if ([action isEqual:@"restore"]) [weakSelf showRestore:snapshot];
        else if ([action isEqual:@"edit"]) [weakSelf editMetadata:snapshot];
        else if ([action isEqual:@"recheck"]) [weakSelf perform:@"recheck" request:@{@"idfv":snapshot[@"idfv"]}];
        else if ([action isEqual:@"delete"]) [weakSelf confirmDelete:snapshot];
    };
    [self presentViewController:menu animated:YES completion:nil];
}
- (void)confirmDelete:(NSDictionary *)snapshot {
    SHDWDeleteBackupViewController *controller = [SHDWDeleteBackupViewController new]; controller.application = self.selected; controller.snapshot = snapshot;
    __weak typeof(self) weakSelf = self; controller.confirm = ^{ [weakSelf perform:@"delete" request:@{@"idfv":snapshot[@"idfv"]}]; };
    [self presentViewController:controller animated:YES completion:nil];
}
- (void)showRestore:(NSDictionary *)snapshot {
    NSString *currentIDFV = CanonicalIDFV([[SHDWFingerprintStore sharedStore] profileForBundleIdentifier:self.selected.bundleIdentifier][@"VendorIdentifier"]);
    if ([currentIDFV isEqual:CanonicalIDFV(snapshot[@"idfv"])]) { self.status.text = SHDWText(@"This backup belongs to the current IDFV and cannot be restored."); self.status.textColor = UIColor.secondaryLabelColor; return; }
    SHDWRestoreViewController *controller = [SHDWRestoreViewController new]; controller.application = self.selected; controller.snapshot = snapshot; controller.sameIDFV = NO; controller.service = self.service; __weak typeof(self) weakSelf = self; controller.completion = ^{ [weakSelf reloadApplications]; }; [self presentViewController:controller animated:YES completion:nil]; }
- (void)perform:(NSString *)action request:(NSDictionary *)request {
    if (self.working || [SHDWOperationCoordinator isRunning] || !self.service) return;
    self.working = YES; self.status.textColor = UIColor.secondaryLabelColor; self.status.text = SHDWText([action isEqual:@"recheck"] ? @"Verifying backup" : ([action isEqual:@"edit"] ? @"Saving changes" : ([action isEqual:@"delete"] ? @"Deleting backup" : @"Backing up data"))); [self.action setTitle:self.status.text forState:UIControlStateNormal]; [self.action setWorking:YES]; [self collapseSelector]; [self updateControls];
    __weak typeof(self) weakSelf = self; [self.service performAction:action request:request progress:^(NSDictionary *event) { weakSelf.status.text = ProgressTitle(event); } completion:^(id result, NSError *error) { typeof(self) self = weakSelf; if (!self) return; (void)result; self.working = NO; [self.action setWorking:NO]; NSString *message = error ? error.localizedDescription : SHDWText([action isEqual:@"recheck"] ? @"Backup verified" : ([action isEqual:@"delete"] ? @"Backup deleted" : @"Backup saved")); self.status.textColor = error ? UIColor.systemRedColor : UIColor.secondaryLabelColor; self.status.text = message; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, message); self.liveIDFV = CanonicalIDFV([[SHDWFingerprintStore sharedStore] profileForBundleIdentifier:self.selected.bundleIdentifier][@"VendorIdentifier"]); NSUInteger generation = ++self.loadGeneration; [self.service loadCatalog:^(NSArray *catalog, NSError *catalogError) { if (generation != self.loadGeneration) return; self.catalogFailed = catalogError != nil; self.catalog = catalog ?: self.catalog; if (catalogError && !error) self.status.text = catalogError.localizedDescription; [self.table reloadData]; [self updateControls]; }]; }];
}
@end
