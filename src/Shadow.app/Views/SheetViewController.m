#import "SheetViewController.h"
#import "Appearance/Theme.h"

static CGFloat const BottomSpacing = 48;

UIButton *SHDWSheetPrimaryButton(NSString *title, NSString *symbol, id target, SEL action) {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom]; button.backgroundColor = SHDWAccent(); button.layer.cornerRadius = 14;
    UILabel *label = [UILabel new]; label.text = title; label.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]];
    label.adjustsFontForContentSizeCategory = YES; label.numberOfLines = 0; label.textAlignment = NSTextAlignmentCenter; label.textColor = UIColor.whiteColor; label.userInteractionEnabled = NO; label.translatesAutoresizingMaskIntoConstraints = NO; label.accessibilityElementsHidden = YES;
    UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(symbol, 20)]; icon.tintColor = UIColor.whiteColor; icon.contentMode = UIViewContentModeScaleAspectFit;
    UIStackView *content = [[UIStackView alloc] initWithArrangedSubviews:@[icon, label]]; content.spacing = 8; content.alignment = UIStackViewAlignmentCenter; content.userInteractionEnabled = NO; content.accessibilityElementsHidden = YES; content.translatesAutoresizingMaskIntoConstraints = NO;
    [button addSubview:content]; button.accessibilityLabel = title;
    [NSLayoutConstraint activateConstraints:@[[icon.widthAnchor constraintEqualToConstant:20], [icon.heightAnchor constraintEqualToConstant:20], [button.heightAnchor constraintGreaterThanOrEqualToConstant:48], [content.centerXAnchor constraintEqualToAnchor:button.centerXAnchor], [content.centerYAnchor constraintEqualToAnchor:button.centerYAnchor], [content.leadingAnchor constraintGreaterThanOrEqualToAnchor:button.leadingAnchor constant:16], [content.trailingAnchor constraintLessThanOrEqualToAnchor:button.trailingAnchor constant:-16], [content.topAnchor constraintGreaterThanOrEqualToAnchor:button.topAnchor constant:12], [content.bottomAnchor constraintLessThanOrEqualToAnchor:button.bottomAnchor constant:-12]]];
    [button addTarget:target action:action forControlEvents:UIControlEventTouchUpInside]; return button;
}

@interface SHDWSheetViewController () <UIViewControllerTransitioningDelegate>
@property(nonatomic, strong, readwrite) UIStackView *contentStack;
@property(nonatomic, strong, readwrite) UIButton *closeButton;
@property(nonatomic, strong) UIScrollView *scroll;
@property(nonatomic) CGRect keyboardFrame;
- (CGFloat)sheetHeightForWidth:(CGFloat)width;
@end

@interface SHDWSheetPresentation : UIPresentationController
@property(nonatomic, strong) UIControl *shade;
@end
@implementation SHDWSheetPresentation
- (CGRect)frameOfPresentedViewInContainerView {
    SHDWSheetViewController *controller = (id)self.presentedViewController; CGRect bounds = self.containerView.bounds;
    CGFloat bottom = CGRectGetMaxY(bounds); BOOL keyboard = NO;
    if (!CGRectIsNull(controller.keyboardFrame)) {
        CGRect frame = [self.containerView convertRect:controller.keyboardFrame fromView:nil];
        if (CGRectIntersectsRect(frame, bounds)) { bottom = MIN(bottom, CGRectGetMinY(frame)); keyboard = YES; }
    }
    CGFloat height = [controller sheetHeightForWidth:bounds.size.width] + (keyboard ? 0 : self.containerView.safeAreaInsets.bottom);
    height = MIN(height, MAX(0, bottom - CGRectGetMinY(bounds) - self.containerView.safeAreaInsets.top - 16));
    return CGRectMake(CGRectGetMinX(bounds), bottom - height, bounds.size.width, height);
}
- (void)presentationTransitionWillBegin {
    self.shade = [UIControl new]; self.shade.backgroundColor = [UIColor.blackColor colorWithAlphaComponent:0.34]; self.shade.alpha = 0;
    [self.shade addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside]; [self.containerView insertSubview:self.shade atIndex:0];
    [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(__unused id<UIViewControllerTransitionCoordinatorContext> context) { self.shade.alpha = 1; } completion:nil];
}
- (void)dismissalTransitionWillBegin { [self.presentedViewController.transitionCoordinator animateAlongsideTransition:^(__unused id<UIViewControllerTransitionCoordinatorContext> context) { self.shade.alpha = 0; } completion:nil]; }
- (void)containerViewWillLayoutSubviews { self.shade.frame = self.containerView.bounds; self.presentedView.frame = self.frameOfPresentedViewInContainerView; }
- (void)close { [(SHDWSheetViewController *)self.presentedViewController close]; }
@end

@interface SHDWSheetTransition : NSObject <UIViewControllerAnimatedTransitioning>
@property(nonatomic) BOOL presenting;
@end
@implementation SHDWSheetTransition
- (NSTimeInterval)transitionDuration:(id<UIViewControllerContextTransitioning>)context { (void)context; return UIAccessibilityIsReduceMotionEnabled() ? 0.15 : 0.3; }
- (void)animateTransition:(id<UIViewControllerContextTransitioning>)context {
    UIView *view = [context viewForKey:self.presenting ? UITransitionContextToViewKey : UITransitionContextFromViewKey];
    UIViewController *controller = [context viewControllerForKey:self.presenting ? UITransitionContextToViewControllerKey : UITransitionContextFromViewControllerKey];
    if (self.presenting) { view.frame = [context finalFrameForViewController:controller]; [context.containerView addSubview:view]; view.transform = CGAffineTransformMakeTranslation(0, view.bounds.size.height); }
    [UIView animateWithDuration:[self transitionDuration:context] delay:0 options:UIViewAnimationOptionCurveEaseInOut animations:^{ view.transform = self.presenting ? CGAffineTransformIdentity : CGAffineTransformMakeTranslation(0, view.bounds.size.height); } completion:^(__unused BOOL finished) { [context completeTransition:!context.transitionWasCancelled]; }];
}
@end

@interface SHDWSheetCloseButton : UIButton
@end
@implementation SHDWSheetCloseButton
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event { (void)event; return CGRectContainsPoint(CGRectInset(self.bounds, -10, -10), point); }
@end

@implementation SHDWSheetViewController
- (instancetype)init { return [self initWithNibName:nil bundle:nil]; }
- (instancetype)initWithNibName:(NSString *)name bundle:(NSBundle *)bundle {
    if ((self = [super initWithNibName:name bundle:bundle])) { _sheetTitle = @""; _keyboardFrame = CGRectNull; self.modalPresentationStyle = UIModalPresentationCustom; self.transitioningDelegate = self; }
    return self;
}
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.view.layer.cornerRadius = 24; self.view.layer.maskedCorners = kCALayerMinXMinYCorner | kCALayerMaxXMinYCorner; self.view.clipsToBounds = YES;
    UIView *handle = [UIView new]; handle.backgroundColor = UIColor.systemGray3Color; handle.layer.cornerRadius = 1.5;
    UIView *header = [UIView new];
    UIImageView *icon = [[UIImageView alloc] initWithImage:self.sheetIcon]; icon.contentMode = UIViewContentModeScaleAspectFit; icon.layer.cornerRadius = 4.5; icon.clipsToBounds = YES;
    UILabel *title = [UILabel new]; title.text = self.sheetTitle; title.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleHeadline] scaledFontForFont:[UIFont systemFontOfSize:16 weight:UIFontWeightSemibold]]; title.adjustsFontForContentSizeCategory = YES; title.textColor = SHDWInk(); title.numberOfLines = 2; title.accessibilityTraits |= UIAccessibilityTraitHeader;
    self.closeButton = [SHDWSheetCloseButton new]; [self.closeButton setImage:SHDWSymbol(@"xmark", 12) forState:UIControlStateNormal]; self.closeButton.tintColor = UIColor.secondaryLabelColor; self.closeButton.backgroundColor = UIColor.tertiarySystemFillColor; self.closeButton.layer.cornerRadius = 12; self.closeButton.accessibilityLabel = SHDWText(@"Close"); [self.closeButton addTarget:self action:@selector(close) forControlEvents:UIControlEventTouchUpInside];
    self.contentStack = [[UIStackView alloc] initWithArrangedSubviews:@[header]]; self.contentStack.axis = UILayoutConstraintAxisVertical; self.contentStack.spacing = 12;
    self.scroll = [UIScrollView new]; self.scroll.alwaysBounceVertical = NO;
    for (UIView *view in @[handle, self.scroll]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self.view addSubview:view]; }
    self.contentStack.translatesAutoresizingMaskIntoConstraints = NO; [self.scroll addSubview:self.contentStack];
    for (UIView *view in @[icon, title, self.closeButton]) { view.translatesAutoresizingMaskIntoConstraints = NO; [header addSubview:view]; }
    [NSLayoutConstraint activateConstraints:@[
        [handle.topAnchor constraintEqualToAnchor:self.view.topAnchor constant:4], [handle.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor], [handle.widthAnchor constraintEqualToConstant:34], [handle.heightAnchor constraintEqualToConstant:3],
        [self.scroll.topAnchor constraintEqualToAnchor:handle.bottomAnchor constant:4], [self.scroll.leadingAnchor constraintEqualToAnchor:self.view.leadingAnchor constant:18], [self.scroll.trailingAnchor constraintEqualToAnchor:self.view.trailingAnchor constant:-18], [self.scroll.bottomAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.bottomAnchor constant:-BottomSpacing],
        [self.contentStack.topAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.topAnchor], [self.contentStack.bottomAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.bottomAnchor], [self.contentStack.leadingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.leadingAnchor], [self.contentStack.trailingAnchor constraintEqualToAnchor:self.scroll.contentLayoutGuide.trailingAnchor], [self.contentStack.widthAnchor constraintEqualToAnchor:self.scroll.frameLayoutGuide.widthAnchor],
        [header.heightAnchor constraintGreaterThanOrEqualToConstant:28], [icon.leadingAnchor constraintEqualToAnchor:header.leadingAnchor constant:2], [icon.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:self.sheetIcon ? 18 : 0], [icon.heightAnchor constraintEqualToConstant:22],
        [title.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:self.sheetIcon ? 12 : 0], [title.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [title.topAnchor constraintGreaterThanOrEqualToAnchor:header.topAnchor], [title.bottomAnchor constraintLessThanOrEqualToAnchor:header.bottomAnchor], [title.trailingAnchor constraintLessThanOrEqualToAnchor:self.closeButton.leadingAnchor constant:-8],
        [self.closeButton.trailingAnchor constraintEqualToAnchor:header.trailingAnchor constant:-2], [self.closeButton.centerYAnchor constraintEqualToAnchor:header.centerYAnchor], [self.closeButton.widthAnchor constraintEqualToConstant:24], [self.closeButton.heightAnchor constraintEqualToConstant:24]
    ]];
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter; [center addObserver:self selector:@selector(keyboardChanged:) name:UIKeyboardWillChangeFrameNotification object:nil]; [center addObserver:self selector:@selector(keyboardChanged:) name:UIKeyboardWillHideNotification object:nil];
}
- (void)dealloc { [NSNotificationCenter.defaultCenter removeObserver:self]; }
- (CGFloat)sheetHeightForWidth:(CGFloat)width {
    [self loadViewIfNeeded]; CGSize content = [self.contentStack systemLayoutSizeFittingSize:CGSizeMake(MAX(0, width - 36), UILayoutFittingCompressedSize.height) withHorizontalFittingPriority:UILayoutPriorityRequired verticalFittingPriority:UILayoutPriorityFittingSizeLevel]; return ceil(content.height) + 11 + BottomSpacing;
}
- (void)requestSheetLayout { [self.presentationController.containerView setNeedsLayout]; }
- (void)scrollToView:(UIView *)view animated:(BOOL)animated { [self.view layoutIfNeeded]; [self.scroll scrollRectToVisible:CGRectInset([view convertRect:view.bounds toView:self.scroll], 0, -8) animated:animated]; }
- (void)keyboardChanged:(NSNotification *)notification {
    if (!self.view.window) return;
    self.keyboardFrame = [notification.name isEqual:UIKeyboardWillHideNotification] ? CGRectNull : [notification.userInfo[UIKeyboardFrameEndUserInfoKey] CGRectValue];
    UIView *container = self.presentationController.containerView; [container setNeedsLayout];
    NSTimeInterval duration = [notification.userInfo[UIKeyboardAnimationDurationUserInfoKey] doubleValue]; UIViewAnimationOptions curve = [notification.userInfo[UIKeyboardAnimationCurveUserInfoKey] unsignedIntegerValue] << 16;
    [UIView animateWithDuration:duration delay:0 options:curve | UIViewAnimationOptionBeginFromCurrentState animations:^{ [container layoutIfNeeded]; } completion:nil];
}
- (void)close { if (!self.modalInPresentation && !self.isBeingDismissed) { [self.view endEditing:YES]; [self dismissViewControllerAnimated:YES completion:nil]; } }
- (UIPresentationController *)presentationControllerForPresentedViewController:(UIViewController *)presented presentingViewController:(UIViewController *)presenting sourceViewController:(UIViewController *)source { (void)source; return [[SHDWSheetPresentation alloc] initWithPresentedViewController:presented presentingViewController:presenting]; }
- (id<UIViewControllerAnimatedTransitioning>)animationControllerForPresentedController:(UIViewController *)presented presentingController:(UIViewController *)presenting sourceController:(UIViewController *)source { (void)presented; (void)presenting; (void)source; SHDWSheetTransition *transition = [SHDWSheetTransition new]; transition.presenting = YES; return transition; }
- (id<UIViewControllerAnimatedTransitioning>)animationControllerForDismissedController:(UIViewController *)dismissed { (void)dismissed; SHDWSheetTransition *transition = [SHDWSheetTransition new]; transition.presenting = NO; return transition; }
@end

@interface SHDWMessageSheetViewController : SHDWSheetViewController
@property(nonatomic, copy) NSString *message;
@end
@implementation SHDWMessageSheetViewController
- (void)viewDidLoad {
    [super viewDidLoad];
    UILabel *message = [UILabel new]; message.text = self.message; message.numberOfLines = 0; message.textColor = UIColor.secondaryLabelColor; message.font = [[UIFontMetrics metricsForTextStyle:UIFontTextStyleBody] scaledFontForFont:[UIFont systemFontOfSize:15]]; message.adjustsFontForContentSizeCategory = YES;
    [self.contentStack addArrangedSubview:message];
    [self.contentStack setCustomSpacing:20 afterView:message];
    UIButton *confirm = SHDWSheetPrimaryButton(SHDWText(@"OK"), @"checkmark", self, @selector(close)); confirm.accessibilityIdentifier = @"message.confirm"; [self.contentStack addArrangedSubview:confirm];
}
@end

void SHDWPresentMessageSheet(UIViewController *controller, NSString *title, NSString *message) {
    SHDWMessageSheetViewController *sheet = [SHDWMessageSheetViewController new]; sheet.sheetTitle = title; sheet.sheetIcon = SHDWSymbol(@"exclamationmark.circle", 20); sheet.message = message;
    [controller presentViewController:sheet animated:YES completion:nil];
}
