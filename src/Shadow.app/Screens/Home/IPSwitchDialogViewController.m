#import "IPSwitchDialogViewController.h"
#import "Services/IPSwitchService.h"
#import "Services/IPSwitchConfiguration.h"
#import "Services/OperationCoordinator.h"
#import "Appearance/Theme.h"
#include <arpa/inet.h>
#include <string.h>

static BOOL IPChanged(NSString *before, NSString *current) {
    if (!before.length || !current.length) return NO;
    unsigned char left[sizeof(struct in6_addr)], right[sizeof(struct in6_addr)];
    int oldFamily = inet_pton(AF_INET, before.UTF8String, left) == 1 ? AF_INET : (inet_pton(AF_INET6, before.UTF8String, left) == 1 ? AF_INET6 : 0);
    int newFamily = inet_pton(AF_INET, current.UTF8String, right) == 1 ? AF_INET : (inet_pton(AF_INET6, current.UTF8String, right) == 1 ? AF_INET6 : 0);
    return oldFamily && newFamily && (oldFamily != newFamily || memcmp(left, right, oldFamily == AF_INET ? sizeof(struct in_addr) : sizeof(struct in6_addr)) != 0);
}

@interface SHDWIPSwitchDialogViewController ()
@property(nonatomic, copy) NSDictionary *entry;
@property(nonatomic, copy) NSArray<NSDictionary *> *entries;
@property(nonatomic, strong) NSArray<UIButton *> *routeButtons;
@property(nonatomic, strong) NSArray<UIImageView *> *routeChecks;
@property(nonatomic, strong) UIButton *switchButton;
@property(nonatomic, strong) UIStackView *beforeCard;
@property(nonatomic, strong) SHDWIPSnapshot *beforeSnapshot;
@property(nonatomic, strong) SHDWIPSnapshot *currentSnapshot;
@property(nonatomic, strong) NSArray<UILabel *> *beforeFields;
@property(nonatomic, strong) NSArray<UILabel *> *currentFields;
@property(nonatomic, strong) UILabel *detailLabel;
@property(nonatomic, strong) UIActivityIndicatorView *spinner;
@property(nonatomic) BOOL started;
@property(nonatomic) BOOL busy;
@property(nonatomic) BOOL closing;
@property(nonatomic) BOOL needsRequery;
@property(nonatomic) BOOL attemptedSwitch;
@end
@implementation SHDWIPSwitchDialogViewController
- (instancetype)initWithEntries:(NSArray<NSDictionary<NSString *,NSString *> *> *)entries {
    if ((self = [super init])) { _entries = [entries copy]; _entry = _entries.firstObject; } return self;
}
- (instancetype)initWithEntry:(NSDictionary<NSString *,NSString *> *)entry { return [self initWithEntries:@[entry]]; }
- (UIView *)routePicker {
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.layoutMarginsRelativeArrangement = YES; card.layoutMargins = UIEdgeInsetsMake(4, 16, 4, 16);
    NSMutableArray *buttons = [NSMutableArray new], *checks = [NSMutableArray new];
    for (NSUInteger i = 0; i < self.entries.count; i++) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom]; button.tag = i; button.accessibilityLabel = self.entries[i][@"name"]; button.accessibilityIdentifier = [NSString stringWithFormat:@"ip-switch.route.%lu", (unsigned long)i];
        UILabel *name = [UILabel new]; name.text = self.entries[i][@"name"]; name.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; name.adjustsFontForContentSizeCategory = YES; name.textColor = SHDWInk(); name.numberOfLines = 0;
        UIImageView *check = [[UIImageView alloc] initWithImage:SHDWSymbol(@"checkmark.circle.fill", 20)]; check.tintColor = SHDWAccent(); check.contentMode = UIViewContentModeScaleAspectFit;
        UIStackView *row = [[UIStackView alloc] initWithArrangedSubviews:@[name, check]]; row.spacing = 12; row.alignment = UIStackViewAlignmentCenter; row.userInteractionEnabled = NO; row.translatesAutoresizingMaskIntoConstraints = NO; [button addSubview:row];
        [NSLayoutConstraint activateConstraints:@[[button.heightAnchor constraintGreaterThanOrEqualToConstant:44], [row.leadingAnchor constraintEqualToAnchor:button.leadingAnchor], [row.trailingAnchor constraintEqualToAnchor:button.trailingAnchor], [row.topAnchor constraintEqualToAnchor:button.topAnchor constant:10], [row.bottomAnchor constraintEqualToAnchor:button.bottomAnchor constant:-10], [check.widthAnchor constraintEqualToConstant:20], [check.heightAnchor constraintEqualToConstant:20]]];
        [button addTarget:self action:@selector(selectRoute:) forControlEvents:UIControlEventTouchUpInside]; [card addArrangedSubview:button]; [buttons addObject:button]; [checks addObject:check];
    }
    self.routeButtons = buttons; self.routeChecks = checks; [self updateRoutes]; return card;
}
- (void)updateRoutes {
    for (UIButton *button in self.routeButtons) {
        BOOL selected = [self.entries[button.tag] isEqual:self.entry];
        self.routeChecks[button.tag].image = SHDWSymbol(selected ? @"checkmark.circle.fill" : @"circle", 20);
        button.accessibilityTraits = UIAccessibilityTraitButton | (selected ? UIAccessibilityTraitSelected : 0); button.enabled = !self.busy;
    }
}
- (void)selectRoute:(UIButton *)button {
    if (self.busy || (NSUInteger)button.tag >= self.entries.count) return;
    if ([self.entry isEqual:self.entries[button.tag]]) return;
    self.entry = self.entries[button.tag]; self.beforeSnapshot = nil; self.needsRequery = NO; self.attemptedSwitch = NO; self.detailLabel.hidden = YES; [self updateRoutes]; [self renderSnapshots];
}
- (NSArray<UILabel *> *)snapshotFields {
    NSMutableArray *fields = [NSMutableArray new];
    for (NSUInteger i = 0; i < 3; i++) {
        UILabel *label = [UILabel new]; label.numberOfLines = 0; label.adjustsFontForContentSizeCategory = YES;
        label.font = i % 2 ? [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1] : [[UIFontMetrics metricsForTextStyle:UIFontTextStyleFootnote] scaledFontForFont:[UIFont monospacedSystemFontOfSize:13 weight:UIFontWeightRegular]];
        label.textColor = i % 2 ? UIColor.secondaryLabelColor : SHDWInk(); [fields addObject:label];
    }
    return fields;
}
- (UIStackView *)snapshotCardWithFields:(NSArray<UILabel *> *)fields {
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.spacing = 6; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.layoutMarginsRelativeArrangement = YES; card.layoutMargins = UIEdgeInsetsMake(12, 12, 12, 12);
    for (NSUInteger i = 0; i < 2; i++) {
        UILabel *family = [UILabel new]; family.text = i ? @"IP" : @"IPv4"; family.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1]; family.textColor = UIColor.secondaryLabelColor; family.adjustsFontForContentSizeCategory = YES;
        [card addArrangedSubview:family]; [card addArrangedSubview:fields[i ? 0 : 2]]; if (i) [card addArrangedSubview:fields[1]];
        if (!i) [card setCustomSpacing:14 afterView:fields[2]];
    }
    return card;
}
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Switch IP"); self.sheetIcon = SHDWIPSwitchSymbol(20); [super viewDidLoad]; self.view.accessibilityIdentifier = @"ip-switch.dialog";
    if (self.entries.count > 1) [self.contentStack addArrangedSubview:[self routePicker]];
    self.detailLabel = [UILabel new]; self.detailLabel.numberOfLines = 0; self.detailLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleFootnote]; self.detailLabel.textColor = UIColor.secondaryLabelColor; self.detailLabel.hidden = YES; self.detailLabel.adjustsFontForContentSizeCategory = YES; [self.contentStack addArrangedSubview:self.detailLabel];
    self.beforeFields = [self snapshotFields]; self.currentFields = [self snapshotFields];
    self.beforeCard = [self snapshotCardWithFields:self.beforeFields];
    UIStackView *comparison = [[UIStackView alloc] initWithArrangedSubviews:@[self.beforeCard, [self snapshotCardWithFields:self.currentFields]]]; comparison.spacing = 10; comparison.distribution = UIStackViewDistributionFillEqually; comparison.alignment = UIStackViewAlignmentTop; [self.contentStack addArrangedSubview:comparison];
    self.switchButton = [UIButton buttonWithType:UIButtonTypeCustom]; self.switchButton.backgroundColor = SHDWAccent(); self.switchButton.layer.cornerRadius = 14; self.switchButton.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]]; self.switchButton.titleLabel.adjustsFontForContentSizeCategory = YES; self.switchButton.titleLabel.numberOfLines = 0;
    [self.switchButton setTitleColor:UIColor.whiteColor forState:UIControlStateNormal]; [self.switchButton.heightAnchor constraintGreaterThanOrEqualToConstant:48].active = YES; [self.switchButton addTarget:self action:@selector(performAction) forControlEvents:UIControlEventTouchUpInside]; self.switchButton.accessibilityIdentifier = @"ip-switch.action"; [self.contentStack addArrangedSubview:self.switchButton];
    self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.spinner.hidesWhenStopped = YES; self.spinner.color = UIColor.whiteColor; self.spinner.translatesAutoresizingMaskIntoConstraints = NO; self.spinner.userInteractionEnabled = NO; self.spinner.accessibilityIdentifier = @"ip-switch.loading"; [self.switchButton addSubview:self.spinner];
    [NSLayoutConstraint activateConstraints:@[[self.spinner.centerXAnchor constraintEqualToAnchor:self.switchButton.centerXAnchor], [self.spinner.centerYAnchor constraintEqualToAnchor:self.switchButton.centerYAnchor]]];
    // Explicit close stops observation only; it never repeats or reverses the action.
    [self.closeButton removeTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside]; [self.closeButton addTarget:self action:@selector(dismissProgress) forControlEvents:UIControlEventTouchUpInside];
    [self renderSnapshots];
}
- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated]; if (self.started) return; self.started = YES; [self queryAgain];
}
- (void)dealloc { if (_busy) [SHDWIPSwitchService.sharedService cancel]; }
- (void)showSnapshot:(SHDWIPSnapshot *)snapshot fields:(NSArray<UILabel *> *)fields {
    // Values remain exactly as returned by the providers; only UI labels are localized.
    fields[0].text = snapshot.ip ?: @"—"; fields[1].text = snapshot.region ?: @"—";
    fields[2].text = snapshot.ipv4 ?: @"—";
}
- (void)renderSnapshots {
    self.beforeCard.hidden = self.beforeSnapshot == nil;
    [self showSnapshot:self.beforeSnapshot fields:self.beforeFields]; [self showSnapshot:self.currentSnapshot fields:self.currentFields];
    self.currentFields[0].textColor = IPChanged(self.beforeSnapshot.ip, self.currentSnapshot.ip) ? SHDWAccent() : SHDWInk();
    self.currentFields[2].textColor = IPChanged(self.beforeSnapshot.ipv4, self.currentSnapshot.ipv4) ? SHDWAccent() : SHDWInk();
    BOOL loading = self.busy || !self.started;
    BOOL complete = self.attemptedSwitch && !self.needsRequery && !loading;
    self.switchButton.hidden = complete;
    [self.switchButton setTitle:SHDWText(self.needsRequery ? @"Query again" : @"Switch IP") forState:UIControlStateNormal];
    self.switchButton.accessibilityLabel = loading ? SHDWText(@"Loading") : [self.switchButton titleForState:UIControlStateNormal];
    self.switchButton.enabled = !loading && self.entry != nil; self.switchButton.titleLabel.alpha = loading ? 0 : 1;
    if (loading) [self.spinner startAnimating]; else [self.spinner stopAnimating];
    [self requestSheetLayout];
}
- (void)performAction { if (self.needsRequery) [self queryAgain]; else [self startSwitch]; }
- (BOOL)beginQuery {
    if (self.busy || SHDWIPSwitchService.sharedService.running) return NO;
    NSError *error = nil;
    if (![SHDWOperationCoordinator beginOperation:&error]) { self.detailLabel.text = error.localizedDescription; self.detailLabel.hidden = NO; return NO; }
    self.busy = YES; self.modalInPresentation = YES; self.detailLabel.hidden = YES; [self updateRoutes]; [self renderSnapshots]; return YES;
}
- (void)progress:(SHDWIPSwitchPhase)phase snapshot:(SHDWIPSnapshot *)snapshot {
    if (phase == SHDWIPSwitchPhaseRequesting) { self.beforeSnapshot = snapshot; self.attemptedSwitch = YES; }
    else if (snapshot && snapshot != self.beforeSnapshot) self.currentSnapshot = snapshot;
    [self renderSnapshots];
}
- (void)finishedWithBefore:(SHDWIPSnapshot *)before current:(SHDWIPSnapshot *)current error:(NSError *)error {
    self.busy = NO; self.modalInPresentation = NO; [self updateRoutes];
    if (self.closing) return;
    if (before && !self.beforeSnapshot) self.beforeSnapshot = before;
    if (current && current != self.beforeSnapshot) self.currentSnapshot = current;
    BOOL changed = self.beforeSnapshot && self.currentSnapshot && [SHDWIPSwitchService hasIPChangeFrom:self.beforeSnapshot to:self.currentSnapshot];
    self.needsRequery = error != nil || (self.needsRequery && self.attemptedSwitch && !changed);
    self.detailLabel.hidden = !self.needsRequery;
    self.detailLabel.text = SHDWText(@"Not confirmed yet.");
    [self renderSnapshots];
}
- (void)startSwitch {
    if (!self.entry || ![self beginQuery]) return;
    self.attemptedSwitch = NO; self.needsRequery = NO; self.beforeSnapshot = nil; self.currentSnapshot = nil; [self renderSnapshots];
    __weak typeof(self) weakSelf = self;
    [SHDWIPSwitchService.sharedService startWithURL:[SHDWIPSwitchConfiguration URLForString:self.entry[@"url"]] progress:^(SHDWIPSwitchPhase phase, SHDWIPSnapshot *snapshot) {
        [weakSelf progress:phase snapshot:snapshot];
    } completion:^(SHDWIPSnapshot *before, SHDWIPSnapshot *current, NSError *error) {
        [SHDWOperationCoordinator endOperation]; [weakSelf finishedWithBefore:before current:current error:error];
    }];
}
- (void)queryAgain {
    if (![self beginQuery]) return;
    __weak typeof(self) weakSelf = self;
    // Keep the original baseline in the dialog. Requery never calls the action URL.
    [SHDWIPSwitchService.sharedService queryWithProgress:^(SHDWIPSwitchPhase phase, SHDWIPSnapshot *snapshot) {
        [weakSelf progress:phase snapshot:snapshot];
    } completion:^(SHDWIPSnapshot *current, NSError *error) {
        [SHDWOperationCoordinator endOperation]; [weakSelf finishedWithBefore:nil current:current error:error];
    }];
}
- (void)dismissProgress {
    self.closing = YES;
    if (self.busy) [SHDWIPSwitchService.sharedService cancel];
    self.modalInPresentation = NO; [super close];
}
@end
