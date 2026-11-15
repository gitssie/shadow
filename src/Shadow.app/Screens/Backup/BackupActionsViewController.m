#import "BackupActionsViewController.h"
#import "Services/InstalledApplications.h"
#import "Services/OperationCoordinator.h"
#import "Services/BackupPolicy.h"
#import "Services/BackupPresentation.h"
#import "Services/BackupService.h"
#import "Appearance/Theme.h"

@interface SHDWBackupActionsViewController ()
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, copy) NSDictionary *snapshot;
@property(nonatomic) BOOL finishing;
@property(nonatomic, copy) NSString *currentIDFV;
@property(nonatomic, strong) UIStackView *actionsCard;
@property(nonatomic, strong) UIStackView *detailsContent;
@property(nonatomic, strong) UIButton *detailsButton;
@property(nonatomic, strong) UIButton *lockButton;
@property(nonatomic, strong) UIButton *deleteButton;
@property(nonatomic, strong) SHDWBackupService *service;
@property(nonatomic) BOOL lockSaving;
@end

@implementation SHDWBackupActionsViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application snapshot:(NSDictionary *)snapshot currentIDFV:(NSString *)currentIDFV {
    if ((self = [super init])) { _application = application; _snapshot = [snapshot copy]; _currentIDFV = [currentIDFV copy]; }
    return self;
}
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Backup actions");
    self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application];
    self.detailsButton = [UIButton buttonWithType:UIButtonTypeCustom];
    [self.detailsButton setImage:SHDWSymbol(@"info.circle", 19) forState:UIControlStateNormal];
    [self.detailsButton setImage:SHDWSymbol(@"info.circle.fill", 19) forState:UIControlStateSelected];
    self.detailsButton.tintColor = SHDWAccent();
    self.detailsButton.accessibilityLabel = SHDWText(@"Show backup details");
    self.detailsButton.accessibilityIdentifier = @"backup.details.toggle";
    [self.detailsButton addTarget:self action:@selector(toggleDetails) forControlEvents:UIControlEventTouchUpInside];
    if (SHDWBackupPhoneOwned(self.snapshot)) {
        self.lockButton = [UIButton buttonWithType:UIButtonTypeCustom];
        [self.lockButton setImage:SHDWSymbol(@"lock.open", 17) forState:UIControlStateNormal];
        [self.lockButton setImage:SHDWSymbol(@"lock.fill", 17) forState:UIControlStateSelected];
        self.lockButton.accessibilityIdentifier = @"backup.delete-lock";
        [self.lockButton addTarget:self action:@selector(toggleDeleteLock) forControlEvents:UIControlEventTouchUpInside];
        self.service = [[SHDWBackupService alloc] initWithBundleIdentifier:self.application.bundleIdentifier];
        self.headerAccessoryButtons = @[self.lockButton, self.detailsButton];
    } else self.headerAccessoryButtons = @[self.detailsButton];
    [super viewDidLoad];
    self.view.accessibilityIdentifier = @"backup.actions-sheet";
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.clipsToBounds = YES;
    BOOL recoverySource = [self.snapshot[@"recoverySource"] boolValue], unavailable = [self.snapshot[@"unavailable"] boolValue];
    BOOL sameIDFV = self.currentIDFV.length && [[[[NSUUID alloc] initWithUUIDString:self.currentIDFV] UUIDString] isEqual:[[[NSUUID alloc] initWithUUIDString:self.snapshot[@"idfv"]] UUIDString]];
    NSArray *actions = @[@"restore", @"edit", @"recheck", @"delete"];
    NSArray *titles = @[SHDWBackupFinalizationOnly(self.snapshot, sameIDFV) ? @"Finish verification" : (recoverySource ? @"Retry restore" : @"Restore backup"), @"Edit backup", @"Recheck backup", @"Delete backup"];
    NSArray *symbols = @[@"arrow.counterclockwise", @"square.and.pencil", @"checkmark.shield", @"trash"];
    for (NSUInteger index = 0; index < actions.count; index++) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom]; button.tag = index;
        UIColor *color = index == 3 ? SHDWDestructiveColor() : SHDWAccent();
        UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(symbols[index], 18)]; icon.tintColor = color; icon.contentMode = UIViewContentModeScaleAspectFit;
        UILabel *title = [UILabel new]; title.text = SHDWText(titles[index]); title.textColor = color; title.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:16]]; title.adjustsFontForContentSizeCategory = YES; title.numberOfLines = 0;
        for (UIView *view in @[icon, title]) { view.translatesAutoresizingMaskIntoConstraints = NO; view.userInteractionEnabled = NO; view.accessibilityElementsHidden = YES; [button addSubview:view]; }
        button.accessibilityLabel = title.text;
        [NSLayoutConstraint activateConstraints:@[[icon.leadingAnchor constraintEqualToAnchor:button.leadingAnchor constant:16], [icon.centerYAnchor constraintEqualToAnchor:button.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:20], [icon.heightAnchor constraintEqualToConstant:20], [title.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:12], [title.trailingAnchor constraintEqualToAnchor:button.trailingAnchor constant:-16], [title.topAnchor constraintEqualToAnchor:button.topAnchor constant:12], [title.bottomAnchor constraintEqualToAnchor:button.bottomAnchor constant:-12]]];
        button.accessibilityIdentifier = [@"backup.action." stringByAppendingString:actions[index]];
        button.enabled = index == 0 ? SHDWBackupCanRestore(self.snapshot, sameIDFV) : (index == 3 ? !recoverySource : (!unavailable && (index != 1 || !recoverySource))); button.alpha = button.enabled ? 1 : 0.4;
        if (!SHDWBackupPhoneOwned(self.snapshot)) { button.enabled = NO; button.alpha = 0.4; }
        if (index == 3) self.deleteButton = button;
        [button addTarget:self action:@selector(selectAction:) forControlEvents:UIControlEventTouchUpInside]; [button.heightAnchor constraintGreaterThanOrEqualToConstant:48].active = YES; [card addArrangedSubview:button];
    }
    self.actionsCard = card;
    [self.contentStack addArrangedSubview:card];
    [self updateDeleteLock];
}
- (UIView *)detailField:(NSDictionary *)field {
    UIFont *font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleCaption1] scaledFontForFont:[UIFont systemFontOfSize:12]];
    UILabel *text = [UILabel new]; text.font = font; text.adjustsFontForContentSizeCategory = YES; text.numberOfLines = 0;
    NSString *value = field[@"value"];
    BOOL name = field[@"owner"] != nil;
    NSString *prefix = name ? @"" : [NSString stringWithFormat:@"%@: ", field[@"label"]];
    NSMutableAttributedString *content = [[NSMutableAttributedString alloc] initWithString:prefix attributes:@{NSForegroundColorAttributeName:UIColor.secondaryLabelColor}];
    [content appendAttributedString:[[NSAttributedString alloc] initWithString:value attributes:@{NSForegroundColorAttributeName:SHDWInk()}]];
    text.attributedText = content;
    if (!name) return text;
    NSMutableArray *views = [NSMutableArray new];
    BOOL phone = [field[@"owner"] isEqual:@"phone"];
    NSArray *symbols = [field[@"current"] boolValue] ? @[phone ? @"iphone" : @"desktopcomputer", @"checkmark.circle.fill"] : @[phone ? @"iphone" : @"desktopcomputer"];
    for (NSString *symbol in symbols) {
        UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(symbol, 12)];
        icon.tintColor = SHDWAccent(); icon.contentMode = UIViewContentModeScaleAspectFit;
        [icon.widthAnchor constraintEqualToConstant:12].active = YES; [icon.heightAnchor constraintEqualToConstant:14].active = YES;
        [views addObject:icon];
    }
    [views addObject:text];
    UIStackView *nameView = [[UIStackView alloc] initWithArrangedSubviews:views]; nameView.spacing = 5; nameView.alignment = UIStackViewAlignmentTop;
    nameView.isAccessibilityElement = YES;
    nameView.accessibilityLabel = [NSString stringWithFormat:@"%@, %@%@", value, SHDWText(phone ? @"Controlled by phone" : @"Controlled by RV"), [field[@"current"] boolValue] ? [@", " stringByAppendingString:SHDWText(@"Current")] : @""];
    return nameView;
}
- (UIStackView *)detailContent {
    UIStackView *content = [UIStackView new]; content.axis = UILayoutConstraintAxisVertical; content.spacing = 12;
    content.backgroundColor = UIColor.whiteColor; content.layer.cornerRadius = 16;
    content.layoutMarginsRelativeArrangement = YES; content.layoutMargins = UIEdgeInsetsMake(12, 14, 12, 14);
    UIStackView *row = nil;
    for (NSDictionary *field in SHDWBackupDetailFields(self.snapshot, self.currentIDFV)) {
        if ([field[@"fullWidth"] boolValue]) {
            if (row.arrangedSubviews.count == 1) { UIView *blank = [UIView new]; [blank.heightAnchor constraintEqualToConstant:0].active = YES; [row addArrangedSubview:blank]; }
            row = nil; [content addArrangedSubview:[self detailField:field]]; continue;
        }
        if (!row || row.arrangedSubviews.count == 2) {
            row = [UIStackView new]; row.axis = UILayoutConstraintAxisHorizontal; row.alignment = UIStackViewAlignmentTop;
            row.distribution = UIStackViewDistributionFillEqually; row.spacing = 14;
            [content addArrangedSubview:row];
        }
        [row addArrangedSubview:[self detailField:field]];
    }
    if (row.arrangedSubviews.count == 1) { UIView *blank = [UIView new]; [blank.heightAnchor constraintEqualToConstant:0].active = YES; [row addArrangedSubview:blank]; }
    return content;
}
- (void)updateDeleteLock {
    BOOL locked = [self.snapshot[@"deleteLocked"] boolValue];
    self.lockButton.selected = locked; self.lockButton.enabled = !self.lockSaving;
    self.lockButton.tintColor = locked ? SHDWAccent() : UIColor.secondaryLabelColor;
    self.lockButton.accessibilityLabel = SHDWText(locked ? @"Unlock backup" : @"Lock backup");
    self.deleteButton.enabled = SHDWBackupPhoneOwned(self.snapshot) && ![self.snapshot[@"recoverySource"] boolValue] && !locked && !self.lockSaving;
    self.deleteButton.alpha = self.deleteButton.enabled ? 1 : 0.4;
    self.actionsCard.userInteractionEnabled = !self.lockSaving;
    self.closeButton.enabled = !self.lockSaving; self.modalInPresentation = self.lockSaving;
}
- (void)toggleDeleteLock {
    if (self.lockSaving || self.finishing || !self.lockButton || [SHDWOperationCoordinator isRunning]) return;
    self.lockSaving = YES; [self updateDeleteLock];
    BOOL locked = ![self.snapshot[@"deleteLocked"] boolValue];
    __weak typeof(self) weakSelf = self;
    [self.service setDeleteLocked:locked forIDFV:self.snapshot[@"idfv"] completion:^(id result, NSError *error) {
        typeof(self) self = weakSelf; if (!self) return;
        self.lockSaving = NO;
        if (!error) {
            NSMutableDictionary *updated = [self.snapshot mutableCopy]; updated[@"deleteLocked"] = result[@"deleteLocked"];
            self.snapshot = updated;
            if (self.snapshotChanged) self.snapshotChanged(updated);
        }
        [self updateDeleteLock];
        if (error) SHDWShowError(self, error);
    }];
}
- (void)toggleDetails {
    if (self.finishing) return;
    BOOL showingDetails = !self.detailsButton.selected;
    if (showingDetails && !self.detailsContent) {
        self.detailsContent = [self detailContent]; self.detailsContent.accessibilityIdentifier = @"backup.details.content";
    }
    UIView *previous = showingDetails ? self.actionsCard : self.detailsContent;
    UIView *next = showingDetails ? self.detailsContent : self.actionsCard;
    [self.contentStack removeArrangedSubview:previous]; [previous removeFromSuperview];
    [self.contentStack addArrangedSubview:next];
    self.detailsButton.selected = showingDetails;
    self.detailsButton.accessibilityLabel = SHDWText(showingDetails ? @"Show backup actions" : @"Show backup details");
    self.sheetTitle = SHDWText(showingDetails ? @"Backup details" : @"Backup actions");
    [self requestSheetLayout];
}
- (void)selectAction:(UIButton *)sender {
    if (self.finishing || !sender.enabled || [SHDWOperationCoordinator isRunning]) return;
    self.finishing = YES; self.view.userInteractionEnabled = NO;
    NSString *action = @[@"restore", @"edit", @"recheck", @"delete"][sender.tag]; void (^selection)(NSString *) = self.selection;
    [self dismissViewControllerAnimated:YES completion:^{ if (selection && ![SHDWOperationCoordinator isRunning]) selection(action); }];
}
@end
