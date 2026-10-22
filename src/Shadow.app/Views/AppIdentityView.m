#import "AppIdentityView.h"
#import "Services/InstalledApplications.h"
#import "Appearance/Theme.h"
@interface SHDWAppIdentityView ()
@property(nonatomic, strong) UIImageView *icon;
@property(nonatomic, strong) UILabel *name;
@property(nonatomic, strong) UILabel *fingerprint;
@end
@implementation SHDWAppIdentityView
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.userInteractionEnabled = NO;
        _icon = [UIImageView new]; _icon.layer.cornerRadius = 10; _icon.clipsToBounds = YES; _icon.contentMode = UIViewContentModeScaleAspectFit;
        _name = [UILabel new]; _name.font = [UIFont preferredFontForTextStyle:UIFontTextStyleHeadline]; _name.textColor = SHDWInk(); _name.adjustsFontForContentSizeCategory = YES; _name.lineBreakMode = NSLineBreakByTruncatingTail;
        _fingerprint = [UILabel new]; _fingerprint.font = [UIFont monospacedSystemFontOfSize:12 weight:UIFontWeightRegular]; _fingerprint.textColor = UIColor.secondaryLabelColor; _fingerprint.lineBreakMode = NSLineBreakByTruncatingMiddle;
        [_fingerprint setContentCompressionResistancePriority:UILayoutPriorityDefaultLow forAxis:UILayoutConstraintAxisHorizontal];
        UIImageView *glyph = [[UIImageView alloc] initWithImage:SHDWSymbol(@"touchid", 14)]; glyph.tintColor = SHDWAccent(); glyph.contentMode = UIViewContentModeScaleAspectFit;
        UIStackView *digest = [[UIStackView alloc] initWithArrangedSubviews:@[glyph, _fingerprint]]; digest.spacing = 6; digest.alignment = UIStackViewAlignmentCenter;
        UIStackView *labels = [[UIStackView alloc] initWithArrangedSubviews:@[_name, digest]]; labels.axis = UILayoutConstraintAxisVertical; labels.spacing = 4;
        for (UIView *view in @[_icon, labels]) { view.translatesAutoresizingMaskIntoConstraints = NO; [self addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[
            [_icon.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:14], [_icon.centerYAnchor constraintEqualToAnchor:self.centerYAnchor], [_icon.widthAnchor constraintEqualToConstant:40], [_icon.heightAnchor constraintEqualToConstant:40],
            [labels.leadingAnchor constraintEqualToAnchor:_icon.trailingAnchor constant:12], [labels.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-50], [labels.centerYAnchor constraintEqualToAnchor:self.centerYAnchor],
            [glyph.widthAnchor constraintEqualToConstant:14], [glyph.heightAnchor constraintEqualToConstant:16]
        ]];
    } return self;
}
- (void)showApplication:(SHDWInstalledApplication *)application fingerprint:(NSString *)fingerprint {
    self.icon.image = [SHDWInstalledApplications iconForApplication:application]; self.name.text = application.name ?: SHDWText(@"Choose application"); self.fingerprint.text = fingerprint ?: @"—";
}
@end
