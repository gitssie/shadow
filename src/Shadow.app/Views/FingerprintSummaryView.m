#import "FingerprintSummaryView.h"
#import "Appearance/Theme.h"
#include <math.h>
@interface SHDWFingerprintSummaryView ()
@property(nonatomic, strong) UILabel *updatedAt;
@property(nonatomic, strong) UILabel *value;
@property(nonatomic, strong) UIControl *details;
@property(nonatomic, strong) UIButton *cleanup;
@end
@implementation SHDWFingerprintSummaryView
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = UIColor.whiteColor; self.layer.cornerRadius = 20;
        self.isAccessibilityElement = NO;
        _details = [UIControl new]; _details.accessibilityIdentifier = @"home.fingerprint-details"; _details.isAccessibilityElement = YES; _details.accessibilityTraits = UIAccessibilityTraitButton; [_details addTarget:self action:@selector(detailsTapped) forControlEvents:UIControlEventTouchUpInside];
        _cleanup = [UIButton buttonWithType:UIButtonTypeSystem]; _cleanup.accessibilityIdentifier = @"home.cleanup"; [_cleanup addTarget:self action:@selector(cleanupPressed) forControlEvents:UIControlEventTouchUpInside];
        for (UIView *row in @[_details, _cleanup]) { row.translatesAutoresizingMaskIntoConstraints = NO; [self addSubview:row]; }
        UIView *line = [UIView new]; line.backgroundColor = UIColor.separatorColor; line.alpha = 0.35; line.translatesAutoresizingMaskIntoConstraints = NO; [self addSubview:line];
        UIImageView *broom = [[UIImageView alloc] initWithImage:SHDWSymbol(@"sparkles", 23)]; broom.tintColor = SHDWAccent(); broom.contentMode = UIViewContentModeScaleAspectFit;
        UILabel *cleanupLabel = [UILabel new]; cleanupLabel.text = SHDWText(@"Clean application data"); cleanupLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; cleanupLabel.textColor = SHDWInk(); cleanupLabel.adjustsFontForContentSizeCategory = YES;
        UIImageView *cleanupArrow = [[UIImageView alloc] initWithImage:SHDWSymbol(@"chevron.right", 15)]; cleanupArrow.tintColor = SHDWAccent(); cleanupArrow.contentMode = UIViewContentModeScaleAspectFit;
        for (UIView *part in @[broom, cleanupLabel, cleanupArrow]) { part.translatesAutoresizingMaskIntoConstraints = NO; part.userInteractionEnabled = NO; [_cleanup addSubview:part]; }
        _cleanup.accessibilityLabel = cleanupLabel.text;
        [NSLayoutConstraint activateConstraints:@[[_details.leadingAnchor constraintEqualToAnchor:self.leadingAnchor], [_details.trailingAnchor constraintEqualToAnchor:self.trailingAnchor], [_details.topAnchor constraintEqualToAnchor:self.topAnchor], [_details.heightAnchor constraintGreaterThanOrEqualToConstant:76], [line.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:18], [line.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-18], [line.topAnchor constraintEqualToAnchor:_details.bottomAnchor], [line.heightAnchor constraintEqualToConstant:0.5], [_cleanup.topAnchor constraintEqualToAnchor:line.bottomAnchor], [_cleanup.leadingAnchor constraintEqualToAnchor:self.leadingAnchor], [_cleanup.trailingAnchor constraintEqualToAnchor:self.trailingAnchor], [_cleanup.bottomAnchor constraintEqualToAnchor:self.bottomAnchor], [_cleanup.heightAnchor constraintEqualToAnchor:_details.heightAnchor], [broom.leadingAnchor constraintEqualToAnchor:_cleanup.leadingAnchor constant:18], [broom.widthAnchor constraintEqualToConstant:26], [broom.heightAnchor constraintEqualToConstant:26], [broom.centerYAnchor constraintEqualToAnchor:_cleanup.centerYAnchor], [cleanupLabel.leadingAnchor constraintEqualToAnchor:broom.trailingAnchor constant:14], [cleanupLabel.centerYAnchor constraintEqualToAnchor:_cleanup.centerYAnchor], [cleanupLabel.topAnchor constraintGreaterThanOrEqualToAnchor:_cleanup.topAnchor constant:14], [cleanupLabel.bottomAnchor constraintLessThanOrEqualToAnchor:_cleanup.bottomAnchor constant:-14], [cleanupArrow.trailingAnchor constraintEqualToAnchor:_cleanup.trailingAnchor constant:-18], [cleanupArrow.widthAnchor constraintEqualToConstant:12], [cleanupArrow.heightAnchor constraintEqualToConstant:18], [cleanupArrow.centerYAnchor constraintEqualToAnchor:_cleanup.centerYAnchor], [cleanupLabel.trailingAnchor constraintLessThanOrEqualToAnchor:cleanupArrow.leadingAnchor constant:-12]]];
        UILabel *value = [UILabel new]; self.value = value; value.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; value.textColor = SHDWInk(); value.adjustsFontForContentSizeCategory = YES;
        UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(@"slider.horizontal.3", 24)]; icon.tintColor = SHDWAccent(); icon.contentMode = UIViewContentModeScaleAspectFit;
        UIImageView *chevron = [[UIImageView alloc] initWithImage:SHDWSymbol(@"chevron.right", 15)]; chevron.tintColor = SHDWAccent(); chevron.contentMode = UIViewContentModeScaleAspectFit;
        _updatedAt = [UILabel new]; _updatedAt.font = [UIFont monospacedSystemFontOfSize:12 weight:UIFontWeightRegular]; _updatedAt.textColor = UIColor.secondaryLabelColor;
        UIImageView *clock = [[UIImageView alloc] initWithImage:SHDWSymbol(@"clock", 12)]; clock.tintColor = UIColor.secondaryLabelColor; clock.contentMode = UIViewContentModeScaleAspectFit;
        UIStackView *time = [[UIStackView alloc] initWithArrangedSubviews:@[clock, _updatedAt]]; time.spacing = 6; time.alignment = UIStackViewAlignmentCenter;
        [NSLayoutConstraint activateConstraints:@[[clock.widthAnchor constraintEqualToConstant:12], [clock.heightAnchor constraintEqualToConstant:14]]];
        UIStackView *labels = [[UIStackView alloc] initWithArrangedSubviews:@[value, time]]; labels.axis = UILayoutConstraintAxisVertical; labels.spacing = 5; labels.alignment = UIStackViewAlignmentLeading;
        for (UIView *view in @[icon, labels, chevron]) { view.translatesAutoresizingMaskIntoConstraints = NO; view.userInteractionEnabled = NO; [self.details addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[icon.leadingAnchor constraintEqualToAnchor:self.details.leadingAnchor constant:18], [icon.widthAnchor constraintEqualToConstant:26], [icon.heightAnchor constraintEqualToConstant:26], [icon.centerYAnchor constraintEqualToAnchor:self.details.centerYAnchor], [labels.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:14], [labels.centerYAnchor constraintEqualToAnchor:self.details.centerYAnchor], [labels.topAnchor constraintGreaterThanOrEqualToAnchor:self.details.topAnchor constant:14], [labels.bottomAnchor constraintLessThanOrEqualToAnchor:self.details.bottomAnchor constant:-14], [chevron.trailingAnchor constraintEqualToAnchor:self.details.trailingAnchor constant:-18], [chevron.widthAnchor constraintEqualToConstant:12], [chevron.heightAnchor constraintEqualToConstant:18], [chevron.centerYAnchor constraintEqualToAnchor:self.details.centerYAnchor], [labels.trailingAnchor constraintLessThanOrEqualToAnchor:chevron.leadingAnchor constant:-12]]];
        [self showUpdatedAt:nil];
    } return self;
}
- (void)showSystemVersion:(NSString *)version region:(NSString *)region {
    self.value.text = [NSString stringWithFormat:@"%@ · %@", version, region];
    self.details.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", self.value.text, self.updatedAt.text ?: @"—"];
}
- (void)showUpdatedAt:(NSNumber *)timestamp {
    NSString *text = @"—";
    if ([timestamp isKindOfClass:NSNumber.class] && isfinite(timestamp.doubleValue) && timestamp.doubleValue > 0) {
        NSDateFormatter *format = [NSDateFormatter new]; format.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"]; format.dateFormat = @"yyyy-MM-dd HH:mm:ss";
        text = [format stringFromDate:[NSDate dateWithTimeIntervalSince1970:timestamp.doubleValue]];
    }
    self.updatedAt.text = text;
    self.details.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", self.value.text ?: @"", text];
}

- (void)detailsTapped { [self sendActionsForControlEvents:UIControlEventTouchUpInside]; }
- (void)cleanupPressed { if (self.cleanupTapped) self.cleanupTapped(); }
- (void)setEnabled:(BOOL)enabled { [super setEnabled:enabled]; self.details.enabled = enabled; self.cleanup.enabled = enabled; }
@end
