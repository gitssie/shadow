#import "BackupPromptViewController.h"
#import "Services/BackupService.h"
#import "Services/InstalledApplications.h"
#import "Services/OperationCoordinator.h"
#import "Appearance/Theme.h"

@interface SHDWBackupPromptViewController ()
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic, strong) UILabel *message;
@property(nonatomic, strong) UILabel *actionTitle;
@property(nonatomic, strong) UIImageView *actionIcon;
@property(nonatomic, strong) UIButton *action;
@property(nonatomic, strong) UIButton *direct;
@property(nonatomic, strong) UIActivityIndicatorView *spinner;
@property(nonatomic) BOOL working;
@property(nonatomic) BOOL finishing;
@end

@implementation SHDWBackupPromptViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application service:(SHDWBackupService *)service {
    if ((self = [super initWithNibName:nil bundle:nil])) { self.application = application; self.service = service; }
    return self;
}
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Back up before cleaning?"); self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application];
    [super viewDidLoad]; self.view.accessibilityIdentifier = @"cleanup.backup-prompt"; self.closeButton.accessibilityIdentifier = @"cleanup.backup-close";
    self.message = [UILabel new]; self.message.text = SHDWText(@"Cleaning removes current app data. Back up first to keep it."); self.message.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont systemFontOfSize:13]]; self.message.adjustsFontForContentSizeCategory = YES; self.message.numberOfLines = 0; self.message.textColor = UIColor.secondaryLabelColor;
    self.action = [UIButton new]; self.action.backgroundColor = SHDWAccent(); self.action.layer.cornerRadius = 14; self.action.accessibilityIdentifier = @"cleanup.backup-start"; self.action.accessibilityLabel = SHDWText(@"Backup and clean"); [self.action addTarget:self action:@selector(backup) forControlEvents:UIControlEventTouchUpInside];
    self.actionTitle = [UILabel new]; self.actionTitle.text = SHDWText(@"Backup and clean"); self.actionTitle.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]]; self.actionTitle.adjustsFontForContentSizeCategory = YES; self.actionTitle.textColor = UIColor.whiteColor; self.actionTitle.numberOfLines = 0; self.actionTitle.textAlignment = NSTextAlignmentCenter;
    self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.spinner.color = UIColor.whiteColor; self.spinner.hidesWhenStopped = YES; self.spinner.hidden = YES;
    self.actionIcon = [[UIImageView alloc] initWithImage:SHDWSymbol(@"archivebox", 20)]; self.actionIcon.tintColor = UIColor.whiteColor; self.actionIcon.contentMode = UIViewContentModeScaleAspectFit;
    UIStackView *actionContent = [[UIStackView alloc] initWithArrangedSubviews:@[self.actionIcon, self.spinner, self.actionTitle]]; actionContent.spacing = 8; actionContent.alignment = UIStackViewAlignmentCenter; actionContent.userInteractionEnabled = NO; actionContent.accessibilityElementsHidden = YES;
    self.direct = [UIButton buttonWithType:UIButtonTypeCustom]; self.direct.accessibilityLabel = SHDWText(@"Clean directly"); self.direct.accessibilityIdentifier = @"cleanup.backup-skip"; [self.direct addTarget:self action:@selector(continueToCleanup) forControlEvents:UIControlEventTouchUpInside];
    UIImageView *directIcon = [[UIImageView alloc] initWithImage:SHDWSymbol(@"sparkles", 20)]; directIcon.tintColor = SHDWAccent(); directIcon.contentMode = UIViewContentModeScaleAspectFit;
    UILabel *directTitle = [UILabel new]; directTitle.text = SHDWText(@"Clean directly"); directTitle.textColor = SHDWAccent(); directTitle.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:15]]; directTitle.adjustsFontForContentSizeCategory = YES; directTitle.numberOfLines = 0;
    UIStackView *directContent = [[UIStackView alloc] initWithArrangedSubviews:@[directIcon, directTitle]]; directContent.spacing = 8; directContent.alignment = UIStackViewAlignmentCenter; directContent.userInteractionEnabled = NO; directContent.accessibilityElementsHidden = YES; directContent.translatesAutoresizingMaskIntoConstraints = NO; [self.direct addSubview:directContent];
    [NSLayoutConstraint activateConstraints:@[[self.actionIcon.widthAnchor constraintEqualToConstant:20], [self.actionIcon.heightAnchor constraintEqualToConstant:20], [directIcon.widthAnchor constraintEqualToConstant:20], [directIcon.heightAnchor constraintEqualToConstant:20], [directContent.centerXAnchor constraintEqualToAnchor:self.direct.centerXAnchor], [directContent.centerYAnchor constraintEqualToAnchor:self.direct.centerYAnchor], [directContent.leadingAnchor constraintGreaterThanOrEqualToAnchor:self.direct.leadingAnchor constant:16], [directContent.trailingAnchor constraintLessThanOrEqualToAnchor:self.direct.trailingAnchor constant:-16], [directContent.topAnchor constraintGreaterThanOrEqualToAnchor:self.direct.topAnchor constant:10], [directContent.bottomAnchor constraintLessThanOrEqualToAnchor:self.direct.bottomAnchor constant:-10]]];
    [self.contentStack setCustomSpacing:8 afterView:self.contentStack.arrangedSubviews.firstObject];
    for (UIView *view in @[self.message, self.action, self.direct]) [self.contentStack addArrangedSubview:view];
    [self.contentStack setCustomSpacing:16 afterView:self.message]; [self.contentStack setCustomSpacing:6 afterView:self.action];
    actionContent.translatesAutoresizingMaskIntoConstraints = NO; [self.action addSubview:actionContent];
    [NSLayoutConstraint activateConstraints:@[[self.action.heightAnchor constraintGreaterThanOrEqualToConstant:48], [actionContent.centerXAnchor constraintEqualToAnchor:self.action.centerXAnchor], [actionContent.centerYAnchor constraintEqualToAnchor:self.action.centerYAnchor], [actionContent.leadingAnchor constraintGreaterThanOrEqualToAnchor:self.action.leadingAnchor constant:16], [actionContent.trailingAnchor constraintLessThanOrEqualToAnchor:self.action.trailingAnchor constant:-16], [actionContent.topAnchor constraintGreaterThanOrEqualToAnchor:self.action.topAnchor constant:12], [actionContent.bottomAnchor constraintLessThanOrEqualToAnchor:self.action.bottomAnchor constant:-12], [self.direct.heightAnchor constraintGreaterThanOrEqualToConstant:44]]];
}
- (void)setWorking:(BOOL)working {
    _working = working; self.modalInPresentation = working; self.action.enabled = !working; self.direct.enabled = !working; self.closeButton.enabled = !working;
    self.action.alpha = working ? 0.7 : 1; self.direct.alpha = working ? 0.45 : 1; self.closeButton.alpha = working ? 0.45 : 1;
    self.actionIcon.hidden = working; self.spinner.hidden = !working; if (working) [self.spinner startAnimating]; else [self.spinner stopAnimating];
    self.actionTitle.text = SHDWText(working ? @"Backing up data" : @"Backup and clean"); self.action.accessibilityLabel = self.actionTitle.text;
}
- (void)backup {
    if (self.working || self.finishing || [SHDWOperationCoordinator isRunning]) return;
    self.working = YES; self.message.textColor = UIColor.secondaryLabelColor; self.message.text = SHDWText(@"Backing up data");
    __weak typeof(self) weakSelf = self;
    [self.service performAction:@"backup" request:@{} progress:^(NSDictionary *event) {
        typeof(self) self = weakSelf; if (!self) return;
        NSString *stage = event[@"stage"] ?: @""; self.message.text = SHDWText([stage containsString:@"verify"] || [stage isEqual:@"recheck"] ? @"Verifying backup" : @"Backing up data");
    } completion:^(id result, NSError *error) {
        (void)result; typeof(self) self = weakSelf; if (!self) return; self.working = NO;
        if (error) { self.message.textColor = UIColor.systemRedColor; self.message.text = error.localizedDescription; [self.presentationController.containerView setNeedsLayout]; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, error.localizedDescription); }
        else [self continueToCleanupAfterBackup:YES];
    }];
}
- (void)continueToCleanup { [self continueToCleanupAfterBackup:NO]; }
- (void)continueToCleanupAfterBackup:(BOOL)backupCompleted {
    if (self.working || self.finishing || [SHDWOperationCoordinator isRunning]) return;
    self.finishing = YES; self.action.enabled = NO; self.direct.enabled = NO; self.closeButton.enabled = NO;
    void (^proceed)(BOOL) = [self.proceed copy]; [self dismissViewControllerAnimated:YES completion:^{ if (proceed) proceed(backupCompleted); }];
}
- (void)close { if (!self.working && !self.finishing) [self dismissViewControllerAnimated:YES completion:nil]; }
@end
