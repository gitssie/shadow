#import "AppSelectorView.h"
#import "AppIdentityView.h"
#import <Shadow/Fingerprint.h>
#import "Services/InstalledApplications.h"
#import "Appearance/Theme.h"
@interface SHDWAppSelectorView ()
@property(nonatomic, strong) SHDWAppIdentityView *identity;
@property(nonatomic, strong) UIImageView *chevron;
@property(nonatomic, strong) UIButton *headerControl;
@property(nonatomic, strong) UIScrollView *list;
@property(nonatomic, strong) UIStackView *rows;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *alternatives;
@property(nonatomic, readwrite, getter=isExpanded) BOOL expanded;
@end
@implementation SHDWAppSelectorView
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = UIColor.whiteColor; self.layer.cornerRadius = 20; self.layer.borderWidth = 0.7; self.clipsToBounds = YES;
        self.layer.borderColor = [SHDWInk() colorWithAlphaComponent:0.1].CGColor; self.accessibilityIdentifier = @"home.application-selector";
        [self addTarget:self action:@selector(toggleExpanded) forControlEvents:UIControlEventTouchUpInside];
        UIButton *header = [UIButton buttonWithType:UIButtonTypeCustom]; self.headerControl = header; [header addTarget:self action:@selector(toggleExpanded) forControlEvents:UIControlEventTouchUpInside]; header.translatesAutoresizingMaskIntoConstraints = NO; [self addSubview:header];
        _identity = [SHDWAppIdentityView new]; _identity.translatesAutoresizingMaskIntoConstraints = NO; [header addSubview:_identity];
        _chevron = [[UIImageView alloc] initWithImage:SHDWSymbol(@"chevron.down", 18)]; _chevron.tintColor = SHDWAccent(); _chevron.contentMode = UIViewContentModeScaleAspectFit; _chevron.userInteractionEnabled = NO; _chevron.translatesAutoresizingMaskIntoConstraints = NO; [header addSubview:_chevron];
        _list = [UIScrollView new]; _list.translatesAutoresizingMaskIntoConstraints = NO; _list.alpha = 0; _list.hidden = YES; _list.alwaysBounceVertical = NO; [self addSubview:_list];
        _rows = [UIStackView new]; _rows.translatesAutoresizingMaskIntoConstraints = NO; _rows.axis = UILayoutConstraintAxisVertical; [_list addSubview:_rows];
        [NSLayoutConstraint activateConstraints:@[
            [header.topAnchor constraintEqualToAnchor:self.topAnchor], [header.leadingAnchor constraintEqualToAnchor:self.leadingAnchor], [header.trailingAnchor constraintEqualToAnchor:self.trailingAnchor], [header.heightAnchor constraintEqualToConstant:70],
            [_identity.leadingAnchor constraintEqualToAnchor:header.leadingAnchor], [_identity.trailingAnchor constraintEqualToAnchor:header.trailingAnchor], [_identity.topAnchor constraintEqualToAnchor:header.topAnchor], [_identity.bottomAnchor constraintEqualToAnchor:header.bottomAnchor],
            [_chevron.trailingAnchor constraintEqualToAnchor:header.trailingAnchor constant:-18], [_chevron.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [_chevron.widthAnchor constraintEqualToConstant:20], [_chevron.heightAnchor constraintEqualToConstant:20],
            [_list.topAnchor constraintEqualToAnchor:header.bottomAnchor], [_list.leadingAnchor constraintEqualToAnchor:self.leadingAnchor], [_list.trailingAnchor constraintEqualToAnchor:self.trailingAnchor], [_list.bottomAnchor constraintEqualToAnchor:self.bottomAnchor],
            [_rows.leadingAnchor constraintEqualToAnchor:_list.contentLayoutGuide.leadingAnchor], [_rows.trailingAnchor constraintEqualToAnchor:_list.contentLayoutGuide.trailingAnchor], [_rows.topAnchor constraintEqualToAnchor:_list.contentLayoutGuide.topAnchor], [_rows.bottomAnchor constraintEqualToAnchor:_list.contentLayoutGuide.bottomAnchor], [_rows.widthAnchor constraintEqualToAnchor:_list.frameLayoutGuide.widthAnchor]
        ]];
    } return self;
}
- (void)showApplication:(SHDWInstalledApplication *)application fingerprint:(NSString *)fingerprint {
    [self.identity showApplication:application fingerprint:fingerprint];
    self.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", application.name ?: SHDWText(@"Choose application"), fingerprint ?: @""];
    self.accessibilityHint = SHDWText(@"Switch application");
    self.headerControl.accessibilityLabel = self.accessibilityLabel; self.headerControl.accessibilityHint = self.accessibilityHint;
}
- (void)showApplications:(NSArray<SHDWInstalledApplication *> *)applications selected:(SHDWInstalledApplication *)selected {
    [self setExpanded:NO animated:NO];
    self.alternatives = [applications filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(SHDWInstalledApplication *app, NSDictionary *bindings) { return ![app.bundleIdentifier isEqualToString:selected.bundleIdentifier]; }]];
    for (UIView *row in self.rows.arrangedSubviews.copy) { [self.rows removeArrangedSubview:row]; [row removeFromSuperview]; }
    [self.alternatives enumerateObjectsUsingBlock:^(SHDWInstalledApplication *app, NSUInteger index, BOOL *stop) {
        UIButton *row = [UIButton buttonWithType:UIButtonTypeCustom]; row.tag = index; row.accessibilityLabel = app.name; row.accessibilityIdentifier = [@"home.switch." stringByAppendingString:app.bundleIdentifier]; [row addTarget:self action:@selector(chooseRow:) forControlEvents:UIControlEventTouchUpInside];
        UIView *line = [UIView new]; line.backgroundColor = [SHDWInk() colorWithAlphaComponent:0.07];
        NSString *fingerprint = [[SHDWFingerprintStore sharedStore] deviceFingerprintForApplication:app.bundleIdentifier];
        SHDWAppIdentityView *identity = [SHDWAppIdentityView new]; [identity showApplication:app fingerprint:fingerprint];
        row.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", app.name, fingerprint ?: @""];
        for (UIView *view in @[identity, line]) { view.translatesAutoresizingMaskIntoConstraints = NO; view.userInteractionEnabled = NO; [row addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[row.heightAnchor constraintEqualToConstant:70], [identity.leadingAnchor constraintEqualToAnchor:row.leadingAnchor], [identity.trailingAnchor constraintEqualToAnchor:row.trailingAnchor], [identity.topAnchor constraintEqualToAnchor:row.topAnchor], [identity.bottomAnchor constraintEqualToAnchor:row.bottomAnchor], [line.leadingAnchor constraintEqualToAnchor:row.leadingAnchor constant:14], [line.trailingAnchor constraintEqualToAnchor:row.trailingAnchor constant:-14], [line.topAnchor constraintEqualToAnchor:row.topAnchor], [line.heightAnchor constraintEqualToConstant:0.5]]];
        [self.rows addArrangedSubview:row];
    }];
    self.chevron.hidden = self.alternatives.count == 0;
}
- (void)toggleExpanded { if (self.enabled) [self setExpanded:!self.expanded animated:YES]; }
- (void)setExpanded:(BOOL)expanded animated:(BOOL)animated {
    expanded = expanded && self.alternatives.count > 0 && self.enabled; self.expanded = expanded;
    self.isAccessibilityElement = !expanded; self.headerControl.isAccessibilityElement = expanded;
    CGFloat height = 70 + (expanded ? MIN((NSUInteger)3, self.alternatives.count) * 70 : 0);
    self.list.hidden = NO; self.list.userInteractionEnabled = expanded;
    if (self.heightChanged) self.heightChanged(height, animated);
    void (^changes)(void) = ^{ self.list.alpha = expanded ? 1 : 0; self.chevron.transform = expanded ? CGAffineTransformMakeRotation(M_PI) : CGAffineTransformIdentity; };
    if (animated) [UIView animateWithDuration:0.22 delay:0 options:UIViewAnimationOptionBeginFromCurrentState | UIViewAnimationOptionCurveEaseInOut animations:changes completion:^(__unused BOOL finished) { self.list.hidden = !self.expanded; }];
    else { changes(); self.list.hidden = !expanded; }
}
- (void)chooseRow:(UIButton *)sender {
    if (!self.enabled || (NSUInteger)sender.tag >= self.alternatives.count) return;
    SHDWInstalledApplication *app = self.alternatives[sender.tag]; [self setExpanded:NO animated:YES]; self.userInteractionEnabled = NO;
    __weak typeof(self) weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.22 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{ typeof(self) self = weakSelf; if (!self) return; self.userInteractionEnabled = YES; if (self.enabled && self.selectionChanged) self.selectionChanged(app); });
}
@end
