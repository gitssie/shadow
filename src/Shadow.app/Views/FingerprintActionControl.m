#import "FingerprintActionControl.h"
#import "Appearance/Theme.h"
#import <QuartzCore/QuartzCore.h>
@interface SHDWFingerprintActionControl ()
@property(nonatomic, strong) UIImageView *glyph;
@property(nonatomic) BOOL working;
@property(nonatomic) BOOL refreshAllowed;
@property(nonatomic) BOOL locked;
@property(nonatomic) NSUInteger completionGeneration;
@end
@implementation SHDWFingerprintActionControl
- (UIColor *)stateColor {
    if (!self.refreshAllowed) return UIColor.systemGrayColor;
    return self.locked ? SHDWLockColor() : SHDWAccent();
}
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        _refreshAllowed = YES;
        self.layer.borderWidth = 1.5; self.layer.shadowRadius = 24; self.layer.shadowOffset = CGSizeMake(0, 10);
        self.isAccessibilityElement = YES; self.accessibilityTraits = UIAccessibilityTraitButton; self.accessibilityLabel = SHDWText(@"Refresh fingerprint"); self.accessibilityIdentifier = @"home.refresh-fingerprint";
        _glyph = [[UIImageView alloc] initWithImage:SHDWSymbol(@"touchid", 96)]; _glyph.contentMode = UIViewContentModeScaleAspectFit; _glyph.tintColor = SHDWAccent(); _glyph.userInteractionEnabled = NO;
        for (UIView *view in @[_glyph]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[_glyph.centerXAnchor constraintEqualToAnchor:self.centerXAnchor], [_glyph.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [_glyph.widthAnchor constraintEqualToAnchor:self.widthAnchor multiplier:0.60], [_glyph.heightAnchor constraintEqualToAnchor:_glyph.widthAnchor]]];
        [self updateAvailability];
    } return self;
}
- (void)layoutSubviews { [super layoutSubviews]; self.layer.cornerRadius = self.bounds.size.width / 2; self.layer.shadowPath = [UIBezierPath bezierPathWithOvalInRect:self.bounds].CGPath; }
- (void)setHighlighted:(BOOL)highlighted {
    highlighted = highlighted && self.enabled;
    [super setHighlighted:highlighted];
    [UIView animateWithDuration:0.14 animations:^{ self.transform = highlighted ? CGAffineTransformMakeScale(0.96, 0.96) : CGAffineTransformIdentity; }];
}
- (void)stopBreathing {
    [self.glyph.layer removeAllAnimations]; self.glyph.tintColor = [self stateColor];
}
- (void)startBreathing {
    [self stopBreathing];
    if (!self.refreshAllowed || self.locked) return;
    UIColor *light = [SHDWAccent() colorWithAlphaComponent:0.35];
    if (UIAccessibilityIsReduceMotionEnabled()) { self.glyph.tintColor = light; return; }
    [UIView animateWithDuration:0.55 delay:0 options:UIViewAnimationOptionAutoreverse | UIViewAnimationOptionRepeat | UIViewAnimationOptionAllowUserInteraction animations:^{ self.glyph.tintColor = light; } completion:nil];
}
- (void)updateAvailability {
    self.enabled = self.refreshAllowed && !self.locked && !self.working;
    self.accessibilityTraits = UIAccessibilityTraitButton | (self.enabled ? 0 : UIAccessibilityTraitNotEnabled);
    self.accessibilityLabel = SHDWText(self.locked ? @"Fingerprint locked" : !self.refreshAllowed ? @"Fingerprint disabled" : self.working ? @"Refreshing fingerprint" : @"Refresh fingerprint");
    UIColor *color = [self stateColor];
    self.backgroundColor = self.refreshAllowed && self.locked ? [UIColor colorWithRed:255/255.0 green:251/255.0 blue:241/255.0 alpha:1] : UIColor.whiteColor;
    self.layer.borderColor = [color colorWithAlphaComponent:self.refreshAllowed ? 0.28 : 0.14].CGColor;
    self.layer.shadowColor = color.CGColor;
    self.layer.shadowOpacity = self.refreshAllowed ? 0.22 : 0.08;
}
- (void)setRefreshAllowed:(BOOL)allowed locked:(BOOL)locked {
    BOOL changed = self.refreshAllowed != allowed || self.locked != locked;
    self.refreshAllowed = allowed; self.locked = locked;
    if (changed) self.completionGeneration++;
    [self updateAvailability];
    if (!allowed || locked) { [self stopBreathing]; self.transform = CGAffineTransformIdentity; }
    else if (changed) { if (self.working) [self startBreathing]; else [self stopBreathing]; }
}
- (void)setWorking:(BOOL)working {
    _working = working; self.completionGeneration++; [self updateAvailability];
    if (working) [self startBreathing]; else [self stopBreathing];
}
- (void)showCompleted {
    [self setWorking:NO];
    if (!self.refreshAllowed || self.locked) return;
    [self startBreathing]; self.accessibilityLabel = SHDWText(@"Fingerprint refreshed");
    UINotificationFeedbackGenerator *feedback = [UINotificationFeedbackGenerator new]; [feedback notificationOccurred:UINotificationFeedbackTypeSuccess];
    UIAccessibilityPostNotification(UIAccessibilityAnnouncementNotification, SHDWText(@"Fingerprint refreshed"));
    NSUInteger generation = self.completionGeneration; __weak typeof(self) weakSelf = self;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(1.1 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{ typeof(self) self = weakSelf; if (self && !self.working && generation == self.completionGeneration) { [self stopBreathing]; [self updateAvailability]; } });
}
@end
