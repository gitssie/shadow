#import "CleanupViewController.h"
#import "Services/CleanupService.h"
#import "Services/InstalledApplications.h"
#import "Appearance/Theme.h"

@interface SHDWCleanupCloseButton : UIButton
@end
@implementation SHDWCleanupCloseButton
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event { (void)event; return CGRectContainsPoint(CGRectInset(self.bounds, -10, -10), point); }
@end

@interface SHDWCleanupActionButton : UIButton
@property(nonatomic, strong) UIActivityIndicatorView *activityIndicator;
- (void)setWorking:(BOOL)working;
@end
@implementation SHDWCleanupActionButton
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) { _activityIndicator = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; _activityIndicator.color = UIColor.whiteColor; _activityIndicator.hidesWhenStopped = YES; _activityIndicator.userInteractionEnabled = NO; _activityIndicator.accessibilityElementsHidden = YES; [self addSubview:_activityIndicator]; }
    return self;
}
- (void)setWorking:(BOOL)working { if (working) [self.activityIndicator startAnimating]; else [self.activityIndicator stopAnimating]; [self setNeedsLayout]; }
- (void)layoutSubviews {
    [super layoutSubviews];
    if (!self.activityIndicator.isAnimating) return;
    CGFloat spinnerWidth = 20, gap = 8;
    CGSize title = [self.titleLabel sizeThatFits:CGSizeMake(MAX(0, CGRectGetWidth(self.bounds) - 32 - spinnerWidth - gap), CGRectGetHeight(self.bounds))];
    CGFloat leading = (CGRectGetWidth(self.bounds) - spinnerWidth - gap - title.width) / 2;
    self.activityIndicator.frame = CGRectMake(leading, (CGRectGetHeight(self.bounds) - spinnerWidth) / 2, spinnerWidth, spinnerWidth);
    self.titleLabel.frame = CGRectMake(leading + spinnerWidth + gap, (CGRectGetHeight(self.bounds) - title.height) / 2, title.width, title.height);
}
@end

@interface SHDWCleanupRow : UIControl
@property(nonatomic, copy) NSString *step;
@property(nonatomic) BOOL selectedForCleanup;
@property(nonatomic, strong) UILabel *titleLabel;
@property(nonatomic, strong) UILabel *messageLabel;
@property(nonatomic, strong) UIImageView *status;
@property(nonatomic, strong) UIActivityIndicatorView *spinner;
- (instancetype)initWithStep:(NSString *)step title:(NSString *)title symbol:(NSString *)symbol;
- (void)showState:(NSString *)state message:(NSString *)message;
@end
@implementation SHDWCleanupRow
- (instancetype)initWithStep:(NSString *)step title:(NSString *)title symbol:(NSString *)symbol {
    if ((self = [super initWithFrame:CGRectZero])) {
        self.step = step; self.selectedForCleanup = YES; self.accessibilityIdentifier = [@"cleanup.step." stringByAppendingString:step]; self.isAccessibilityElement = YES;
        UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(symbol, 20)]; icon.tintColor = SHDWAccent(); icon.contentMode = UIViewContentModeScaleAspectFit;
        self.titleLabel = [UILabel new]; self.titleLabel.text = SHDWText(title); self.titleLabel.textColor = SHDWInk(); self.titleLabel.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:16]]; self.titleLabel.adjustsFontForContentSizeCategory = YES;
        self.messageLabel = [UILabel new]; self.messageLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1]; self.messageLabel.adjustsFontForContentSizeCategory = YES; self.messageLabel.numberOfLines = 0; self.messageLabel.hidden = YES;
        UIStackView *labels = [[UIStackView alloc] initWithArrangedSubviews:@[self.titleLabel, self.messageLabel]]; labels.axis = UILayoutConstraintAxisVertical; labels.spacing = 3;
        self.status = [UIImageView new]; self.status.contentMode = UIViewContentModeScaleAspectFit;
        self.spinner = [[UIActivityIndicatorView alloc] initWithActivityIndicatorStyle:UIActivityIndicatorViewStyleMedium]; self.spinner.color = SHDWAccent(); self.spinner.hidesWhenStopped = YES;
        for (UIView *view in @[icon, labels, self.status, self.spinner]) { view.translatesAutoresizingMaskIntoConstraints = NO; view.userInteractionEnabled = NO; [self addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[self.heightAnchor constraintGreaterThanOrEqualToConstant:44], [icon.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:16], [icon.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:22], [icon.heightAnchor constraintEqualToConstant:22], [labels.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:15], [labels.topAnchor constraintEqualToAnchor:self.topAnchor constant:8], [labels.bottomAnchor constraintEqualToAnchor:self.bottomAnchor constant:-8], [labels.trailingAnchor constraintEqualToAnchor:self.status.leadingAnchor constant:-12], [self.status.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-16], [self.status.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [self.status.widthAnchor constraintEqualToConstant:20], [self.status.heightAnchor constraintEqualToConstant:20], [self.spinner.centerXAnchor constraintEqualToAnchor:self.status.centerXAnchor], [self.spinner.centerYAnchor constraintEqualToAnchor:self.status.centerYAnchor]]];
        [self showState:@"pending" message:nil];
    } return self;
}
- (void)showState:(NSString *)state message:(NSString *)message {
    [self.layer removeAnimationForKey:@"cleanup.breathe"]; [self.spinner stopAnimating]; self.status.hidden = NO;
    BOOL recheck = [self.step isEqualToString:@"recheck"];
    BOOL running = [state isEqualToString:@"running"], failed = [state isEqualToString:@"failed"], completed = [state isEqualToString:@"completed"], skipped = [state isEqualToString:@"skipped"];
    self.backgroundColor = running ? [SHDWAccent() colorWithAlphaComponent:0.09] : UIColor.clearColor;
    self.titleLabel.textColor = skipped ? UIColor.secondaryLabelColor : SHDWInk();
    self.messageLabel.text = message; self.messageLabel.hidden = !message.length; self.messageLabel.textColor = failed ? UIColor.systemRedColor : UIColor.secondaryLabelColor;
    self.status.tintColor = failed ? UIColor.systemRedColor : (completed || self.selectedForCleanup ? SHDWAccent() : UIColor.tertiaryLabelColor);
    self.status.image = SHDWSymbol(failed ? @"exclamationmark.circle.fill" : (completed ? @"checkmark.circle" : (skipped ? @"minus.circle" : (recheck ? @"checkmark.shield" : (self.selectedForCleanup ? @"checkmark.circle.fill" : @"circle")))), 20);
    NSString *statusText = failed ? @"Failed" : (completed ? @"Completed" : (skipped ? @"Skipped" : (running ? @"Cleaning" : (recheck ? @"Required" : (self.selectedForCleanup ? @"Selected" : @"Not selected")))));
    if (running) {
        self.status.hidden = YES; [self.spinner startAnimating];
        if (!UIAccessibilityIsReduceMotionEnabled()) { CABasicAnimation *pulse = [CABasicAnimation animationWithKeyPath:@"backgroundColor"]; pulse.fromValue = (__bridge id)[SHDWAccent() colorWithAlphaComponent:0.04].CGColor; pulse.toValue = (__bridge id)[SHDWAccent() colorWithAlphaComponent:0.13].CGColor; pulse.duration = 0.8; pulse.autoreverses = YES; pulse.repeatCount = HUGE_VALF; [self.layer addAnimation:pulse forKey:@"cleanup.breathe"]; }
    }
    self.accessibilityLabel = self.titleLabel.text; self.accessibilityValue = message.length ? [NSString stringWithFormat:@"%@, %@", SHDWText(statusText), message] : SHDWText(statusText); self.accessibilityTraits = recheck ? UIAccessibilityTraitStaticText : (UIAccessibilityTraitButton | (self.selectedForCleanup ? UIAccessibilityTraitSelected : 0));
}
@end

@interface SHDWCleanupPresentation : UIPresentationController
@property(nonatomic, strong) UIControl *dimming;
@end
@implementation SHDWCleanupPresentation
- (CGRect)frameOfPresentedViewInContainerView { CGRect bounds = self.containerView.bounds; CGFloat height = MIN(CGRectGetHeight(bounds) - self.containerView.safeAreaInsets.top - 16, 438 + self.containerView.safeAreaInsets.bottom); return CGRectMake(0, CGRectGetHeight(bounds) - height, CGRectGetWidth(bounds), height); }
- (void)presentationTransitionWillBegin {
    self.dimming = [UIControl new]; self.dimming.backgroundColor = [UIColor.blackColor colorWithAlphaComponent:0.34]; self.dimming.alpha = 0; [self.dimming addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside]; [self.containerView insertSubview:self.dimming atIndex:0];
    [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(id<UIViewControllerTransitionCoordinatorContext> context) { self.dimming.alpha = 1; } completion:nil];
}
- (void)dismissalTransitionWillBegin { [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(id<UIViewControllerTransitionCoordinatorContext> context) { self.dimming.alpha = 0; } completion:nil]; }
- (void)containerViewWillLayoutSubviews { self.dimming.frame = self.containerView.bounds; self.presentedView.frame = self.frameOfPresentedViewInContainerView; }
- (void)close { if (!self.presentedViewController.modalInPresentation) [self.presentedViewController dismissViewControllerAnimated:YES completion:nil]; }
@end
@interface SHDWCleanupTransition : NSObject <UIViewControllerAnimatedTransitioning>
@property(nonatomic) BOOL presenting;
@end
@implementation SHDWCleanupTransition
- (NSTimeInterval)transitionDuration:(id<UIViewControllerContextTransitioning>)context { (void)context; return UIAccessibilityIsReduceMotionEnabled() ? 0.15 : 0.3; }
- (void)animateTransition:(id<UIViewControllerContextTransitioning>)context {
    UIView *view = [context viewForKey:self.presenting ? UITransitionContextToViewKey : UITransitionContextFromViewKey]; UIViewController *controller = [context viewControllerForKey:self.presenting ? UITransitionContextToViewControllerKey : UITransitionContextFromViewControllerKey];
    if (self.presenting) { view.frame = [context finalFrameForViewController:controller]; [context.containerView addSubview:view]; view.transform = CGAffineTransformMakeTranslation(0, CGRectGetHeight(view.bounds)); }
    [UIView animateWithDuration:[self transitionDuration:context] delay:0 options:UIViewAnimationOptionCurveEaseInOut animations:^{ view.transform = self.presenting ? CGAffineTransformIdentity : CGAffineTransformMakeTranslation(0, CGRectGetHeight(view.bounds)); } completion:^(BOOL finished) { (void)finished; [context completeTransition:!context.transitionWasCancelled]; }];
}
@end

@interface SHDWCleanupViewController () <UIViewControllerTransitioningDelegate>
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, strong) SHDWCleanupService *service;
@property(nonatomic, copy) NSArray<SHDWCleanupRow *> *rows;
@property(nonatomic, strong) UIButton *cleanButton;
@property(nonatomic, strong) UIButton *closeButton;
@property(nonatomic, strong) UILabel *resultLabel;
@property(nonatomic, strong) UIScrollView *scroll;
@property(nonatomic) BOOL finished;
@property(nonatomic) BOOL completedSuccessfully;
@property(nonatomic, copy) NSString *activeStep;
@property(nonatomic, strong) SHDWCleanupRow *failedRow;
@end
@implementation SHDWCleanupViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application { if ((self = [super initWithNibName:nil bundle:nil])) { self.application = application; self.service = [[SHDWCleanupService alloc] initWithBundleIdentifier:application.bundleIdentifier]; self.modalPresentationStyle = UIModalPresentationCustom; self.transitioningDelegate = self; } return self; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.view.layer.cornerRadius = 24; self.view.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMaxXMinYCorner; self.view.clipsToBounds = YES;
    UIView *header = [UIView new]; header.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:header];
    UIView *handle = [UIView new]; handle.backgroundColor = UIColor.systemGray3Color; handle.layer.cornerRadius = 1.5;
    UIImageView *icon = [[UIImageView alloc] initWithImage:[SHDWInstalledApplications iconForApplication:self.application]]; icon.contentMode = UIViewContentModeScaleAspectFit; icon.layer.cornerRadius = 4.5; icon.clipsToBounds = YES;
    NSLayoutConstraint *compactHeaderHeight = [header.heightAnchor constraintEqualToConstant:28]; compactHeaderHeight.priority = UILayoutPriorityDefaultHigh; compactHeaderHeight.active = YES;
    UILabel *title = [UILabel new]; [title setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical]; title.text = SHDWText(@"Clean data"); title.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]]; title.textColor = SHDWInk(); title.adjustsFontForContentSizeCategory = YES;
    self.closeButton = [SHDWCleanupCloseButton new]; [self.closeButton setImage:SHDWSymbol(@"xmark", 12) forState:UIControlStateNormal]; self.closeButton.tintColor = UIColor.secondaryLabelColor; self.closeButton.backgroundColor = UIColor.tertiarySystemFillColor; self.closeButton.layer.cornerRadius = 12; self.closeButton.accessibilityLabel = SHDWText(@"Close"); self.closeButton.accessibilityIdentifier = @"cleanup.close"; [self.closeButton addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside];
    self.scroll = [UIScrollView new]; self.scroll.alwaysBounceVertical = NO;
    UIStackView *content = [UIStackView new]; content.axis = UILayoutConstraintAxisVertical; content.spacing = 0;
    NSArray *steps = @[@"files", @"preferences", @"web", @"keychain", @"receipts", @"fingerprint", @"recheck"];
    NSArray *titles = @[@"Application files", @"Preferences and caches", @"Web data", @"Keychain", @"Clean receipts", @"Refresh fingerprint", @"Recheck"];
    NSArray *symbols = @[@"doc.text", @"slider.horizontal.3", @"globe", @"key", @"doc.plaintext", @"touchid", @"checkmark.shield"];
    NSMutableArray *rows = [NSMutableArray new];
    {
        UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.clipsToBounds = YES;
        NSUInteger first = 0, last = 7;
        for (NSUInteger index = first; index < last; index++) {
            SHDWCleanupRow *row = [[SHDWCleanupRow alloc] initWithStep:steps[index] title:titles[index] symbol:symbols[index]]; if (index < 6) [row addTarget:self action:@selector(toggleRow:) forControlEvents:UIControlEventTouchUpInside]; else { row.selectedForCleanup = NO; row.enabled = NO; [row showState:@"pending" message:nil]; } [card addArrangedSubview:row]; [rows addObject:row];
        } [content addArrangedSubview:card];
    } self.rows = rows;
    self.resultLabel = [UILabel new]; self.resultLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleCaption1]; self.resultLabel.adjustsFontForContentSizeCategory = YES; self.resultLabel.numberOfLines = 0; self.resultLabel.hidden = YES; self.resultLabel.accessibilityIdentifier = @"cleanup.result";
    self.cleanButton = [SHDWCleanupActionButton new]; self.cleanButton.backgroundColor = [UIColor colorWithRed:0.79 green:0.34 blue:0.29 alpha:1]; self.cleanButton.layer.cornerRadius = 14; self.cleanButton.titleLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleHeadline]; [self.cleanButton setTitleColor:UIColor.whiteColor forState:UIControlStateNormal]; [self.cleanButton setTitle:SHDWText(@"Clean") forState:UIControlStateNormal]; self.cleanButton.accessibilityIdentifier = @"cleanup.start"; [self.cleanButton addTarget:self action:@selector(startCleanup) forControlEvents:UIControlEventTouchUpInside];
    for (UIView *view in @[handle, self.scroll, self.cleanButton]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    for (UIView *view in @[icon, title, self.closeButton]) { view.translatesAutoresizingMaskIntoConstraints = NO; [header addSubview:view]; } content.translatesAutoresizingMaskIntoConstraints = NO; [self.scroll addSubview:content];
    [NSLayoutConstraint activateConstraints:@[[handle.topAnchor constraintEqualToAnchor:self.view.topAnchor constant:4], [handle.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor], [handle.widthAnchor constraintEqualToConstant:34], [handle.heightAnchor constraintEqualToConstant:3], [header.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:20], [header.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-20], [header.topAnchor constraintEqualToAnchor:handle.bottomAnchor constant:4], [header.heightAnchor constraintGreaterThanOrEqualToConstant:28], [icon.leadingAnchor constraintEqualToAnchor:header.leadingAnchor], [icon.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:18], [icon.heightAnchor constraintEqualToConstant:22], [title.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:12], [title.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [title.topAnchor constraintGreaterThanOrEqualToAnchor:header.topAnchor], [title.bottomAnchor constraintLessThanOrEqualToAnchor:header.bottomAnchor], [title.trailingAnchor constraintLessThanOrEqualToAnchor:self.closeButton.leadingAnchor constant:-8], [self.closeButton.trailingAnchor constraintEqualToAnchor:header.trailingAnchor], [self.closeButton.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [self.closeButton.widthAnchor constraintEqualToConstant:24], [self.closeButton.heightAnchor constraintEqualToConstant:24], [self.scroll.topAnchor constraintEqualToAnchor:header.bottomAnchor constant:5], [self.scroll.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:18], [self.scroll.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-18], [self.scroll.bottomAnchor constraintEqualToAnchor:self.cleanButton.topAnchor constant:-16], [content.leadingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.leadingAnchor], [content.trailingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.trailingAnchor], [content.topAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.topAnchor], [content.bottomAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.bottomAnchor], [content.widthAnchor constraintEqualToAnchor:self.scroll.frameLayoutGuide.widthAnchor], [self.cleanButton.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:18], [self.cleanButton.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-18], [self.cleanButton.bottomAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.bottomAnchor constant:-18], [self.cleanButton.heightAnchor constraintGreaterThanOrEqualToConstant:50]]];
}
- (void)toggleRow:(SHDWCleanupRow *)row {
    if (self.service.running || self.completedSuccessfully || [row.step isEqualToString:@"recheck"]) return;
    row.selectedForCleanup = !row.selectedForCleanup; self.finished = NO;
    for (SHDWCleanupRow *item in self.rows) [item showState:@"pending" message:nil];
    self.resultLabel.hidden = YES; [self.cleanButton setTitle:SHDWText(@"Clean") forState:UIControlStateNormal];
    [self updateButton];
}
- (void)updateButton { BOOL any = NO; for (SHDWCleanupRow *row in self.rows) if (![row.step isEqualToString:@"recheck"]) any |= row.selectedForCleanup; self.cleanButton.enabled = !self.service.running && !self.completedSuccessfully && any; self.cleanButton.alpha = self.cleanButton.enabled ? 1 : 0.5; }
- (void)startCleanup {
    if (self.service.running || self.completedSuccessfully) return;
    NSMutableArray *steps = [NSMutableArray new]; for (SHDWCleanupRow *row in self.rows) { if (row.selectedForCleanup && ![row.step isEqualToString:@"recheck"]) [steps addObject:row.step]; [row showState:@"pending" message:nil]; row.enabled = NO; }
    if (!steps.count) { [self updateButton]; return; }
    self.finished = NO; self.completedSuccessfully = NO; self.activeStep = nil; self.failedRow = nil; self.resultLabel.hidden = YES; self.modalInPresentation = YES; self.closeButton.enabled = NO; self.cleanButton.enabled = NO; self.cleanButton.alpha = 0.7; [self.cleanButton setTitle:SHDWText(@"Cleaning") forState:UIControlStateNormal]; [(SHDWCleanupActionButton *)self.cleanButton setWorking:YES];
    __weak typeof(self) weakSelf = self;
    [self.service startWithSteps:steps progress:^(NSString *step, NSString *state, NSString *message) {
        typeof(self) self = weakSelf; if (!self) return;
        SHDWCleanupRow *row = [self rowForStep:step];
        if ([state isEqualToString:@"running"]) self.activeStep = step;
        if ([state isEqualToString:@"failed"]) { row = row ?: [self failureRow]; self.failedRow = row; }
        if (row) { [row showState:state message:message]; [self.view layoutIfNeeded]; if ([state isEqualToString:@"running"] || [state isEqualToString:@"failed"]) { [self.scroll scrollRectToVisible:[row convertRect:row.bounds toView:self.scroll] animated:!UIAccessibilityIsReduceMotionEnabled()]; UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, [NSString stringWithFormat:@"%@, %@", row.titleLabel.text, row.accessibilityValue]); } }
    } completion:^(BOOL success, NSError *error) {
        typeof(self) self = weakSelf; if (!self) return; [(SHDWCleanupActionButton *)self.cleanButton setWorking:NO]; self.finished = YES; self.completedSuccessfully = success; self.modalInPresentation = NO; self.closeButton.enabled = YES; for (SHDWCleanupRow *row in self.rows) row.enabled = !success && ![row.step isEqualToString:@"recheck"];
        self.resultLabel.hidden = YES;
        if (!success) { SHDWCleanupRow *failed = self.failedRow ?: [self failureRow]; self.failedRow = failed; [failed showState:@"failed" message:error.localizedDescription ?: SHDWText(@"Cleanup incomplete")]; }
        [self.cleanButton setTitle:SHDWText(success ? @"Cleanup completed" : @"Try again") forState:UIControlStateNormal]; [self updateButton]; [self.view layoutIfNeeded];
        UIView *visible = success ? [self rowForStep:@"recheck"] : self.failedRow;
        if (visible) [self.scroll scrollRectToVisible:[visible convertRect:visible.bounds toView:self.scroll] animated:!UIAccessibilityIsReduceMotionEnabled()];
        UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, success ? SHDWText(@"Cleanup completed") : self.failedRow.accessibilityValue);
        if (success) {
            __weak typeof(self) completedSelf = self;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(3 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
                typeof(self) self = completedSelf;
                if (self.completedSuccessfully && !self.service.running && self.presentingViewController && self.presentingViewController.presentedViewController == self && !self.isBeingDismissed) [self dismissViewControllerAnimated:YES completion:nil];
            });
        }
        if (self.completion) self.completion();
    }];
}
- (SHDWCleanupRow *)rowForStep:(NSString *)step { for (SHDWCleanupRow *row in self.rows) if ([row.step isEqualToString:step]) return row; return nil; }
- (SHDWCleanupRow *)failureRow { SHDWCleanupRow *active = [self rowForStep:self.activeStep]; if (active) return active; for (SHDWCleanupRow *row in self.rows) if (row.selectedForCleanup) return row; return nil; }
- (void)close { if (!self.service.running) [self dismissViewControllerAnimated:YES completion:nil]; }
- (UIPresentationController *)presentationControllerForPresentedViewController:(UIViewController *)presented presentingViewController:(UIViewController *)presenting sourceViewController:(UIViewController *)source { (void)source; return [[SHDWCleanupPresentation alloc] initWithPresentedViewController:presented presentingViewController:presenting]; }
- (id<UIViewControllerAnimatedTransitioning>)animationControllerForPresentedController:(UIViewController *)presented presentingController:(UIViewController *)presenting sourceController:(UIViewController *)source { (void)presented; (void)presenting; (void)source; SHDWCleanupTransition *transition = [SHDWCleanupTransition new]; transition.presenting = YES; return transition; }
- (id<UIViewControllerAnimatedTransitioning>)animationControllerForDismissedController:(UIViewController *)dismissed { (void)dismissed; SHDWCleanupTransition *transition = [SHDWCleanupTransition new]; transition.presenting = NO; return transition; }
@end
