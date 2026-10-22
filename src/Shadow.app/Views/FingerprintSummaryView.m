#import "FingerprintSummaryView.h"
#import "Appearance/Theme.h"
#include <math.h>
@interface SHDWFingerprintSummaryView ()
@property(nonatomic, strong) UILabel *updatedAt;
@property(nonatomic, strong) UILabel *value;
@end
@implementation SHDWFingerprintSummaryView
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = UIColor.whiteColor; self.layer.cornerRadius = 20;
        self.isAccessibilityElement = YES; self.accessibilityTraits = UIAccessibilityTraitButton; self.accessibilityIdentifier = @"home.fingerprint-details";
        UILabel *value = [UILabel new]; self.value = value; value.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; value.textColor = SHDWInk(); value.adjustsFontForContentSizeCategory = YES;
        UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(@"slider.horizontal.3", 24)]; icon.tintColor = SHDWAccent(); icon.contentMode = UIViewContentModeScaleAspectFit;
        UIImageView *chevron = [[UIImageView alloc] initWithImage:SHDWSymbol(@"chevron.right", 15)]; chevron.tintColor = SHDWAccent(); chevron.contentMode = UIViewContentModeScaleAspectFit;
        _updatedAt = [UILabel new]; _updatedAt.font = [UIFont monospacedSystemFontOfSize:12 weight:UIFontWeightRegular]; _updatedAt.textColor = UIColor.secondaryLabelColor;
        UIImageView *clock = [[UIImageView alloc] initWithImage:SHDWSymbol(@"clock", 12)]; clock.tintColor = UIColor.secondaryLabelColor; clock.contentMode = UIViewContentModeScaleAspectFit;
        UIStackView *time = [[UIStackView alloc] initWithArrangedSubviews:@[clock, _updatedAt]]; time.spacing = 6; time.alignment = UIStackViewAlignmentCenter;
        [NSLayoutConstraint activateConstraints:@[[clock.widthAnchor constraintEqualToConstant:12], [clock.heightAnchor constraintEqualToConstant:14]]];
        UIStackView *labels = [[UIStackView alloc] initWithArrangedSubviews:@[value, time]]; labels.axis = UILayoutConstraintAxisVertical; labels.spacing = 5; labels.alignment = UIStackViewAlignmentLeading;
        for (UIView *view in @[icon, labels, chevron]) { view.translatesAutoresizingMaskIntoConstraints = NO; view.userInteractionEnabled = NO; [self addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[icon.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:18], [icon.widthAnchor constraintEqualToConstant:26], [icon.heightAnchor constraintEqualToConstant:26], [icon.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [labels.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:14], [labels.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [labels.topAnchor constraintGreaterThanOrEqualToAnchor:self.topAnchor constant:14], [labels.bottomAnchor constraintLessThanOrEqualToAnchor:self.bottomAnchor constant:-14], [chevron.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-18], [chevron.widthAnchor constraintEqualToConstant:12], [chevron.heightAnchor constraintEqualToConstant:18], [chevron.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [labels.trailingAnchor constraintLessThanOrEqualToAnchor:chevron.leadingAnchor constant:-12]]];
        [self showUpdatedAt:nil];
    } return self;
}
- (void)showSystemVersion:(NSString *)version region:(NSString *)region {
    self.value.text = [NSString stringWithFormat:@"%@ · %@", version, region];
    self.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", self.value.text, self.updatedAt.text ?: @"—"];
}
- (void)showUpdatedAt:(NSNumber *)timestamp {
    NSString *text = @"—";
    if ([timestamp isKindOfClass:NSNumber.class] && isfinite(timestamp.doubleValue) && timestamp.doubleValue > 0) {
        NSDateFormatter *format = [NSDateFormatter new]; format.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"]; format.dateFormat = @"yyyy-MM-dd HH:mm:ss";
        text = [format stringFromDate:[NSDate dateWithTimeIntervalSince1970:timestamp.doubleValue]];
    }
    self.updatedAt.text = text;
    self.accessibilityLabel = [NSString stringWithFormat:@"%@, %@", self.value.text ?: @"", text];
}

@end
