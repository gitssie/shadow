#import "TabBarView.h"
#import "Appearance/Theme.h"
@interface SHDWTabBarView ()
@property(nonatomic, copy) NSArray<UIButton *> *buttons;
@property(nonatomic, copy) NSArray<UIView *> *indicators;
@property(nonatomic, copy) NSArray<UIImageView *> *icons;
@end
@implementation SHDWTabBarView
- (instancetype)initWithFrame:(CGRect)frame {
    if ((self = [super initWithFrame:frame])) {
        self.backgroundColor = [UIColor colorWithRed:237/255.0 green:240/255.0 blue:235/255.0 alpha:1]; self.accessibilityIdentifier = @"navigation.tabs";
        NSMutableArray *buttons = [NSMutableArray new], *indicators = [NSMutableArray new], *icons = [NSMutableArray new];
        for (NSUInteger index = 0; index < 3; index++) {
            UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom]; button.tag = index; button.translatesAutoresizingMaskIntoConstraints = NO; [button addTarget:self action:@selector(chooseTab:) forControlEvents:UIControlEventTouchUpInside]; [self addSubview:button];
            UIView *indicator = [UIView new]; indicator.backgroundColor = [SHDWAccent() colorWithAlphaComponent:0.1]; indicator.layer.cornerRadius = 14.5; indicator.userInteractionEnabled = NO;
            UIImageView *icon = [[UIImageView alloc] initWithImage:SHDWSymbol(index == 0 ? @"touchid" : (index == 1 ? @"archivebox" : @"gearshape"), 17)]; icon.contentMode = UIViewContentModeScaleAspectFit; icon.userInteractionEnabled = NO;
            for (UIView *view in @[indicator, icon]) { view.translatesAutoresizingMaskIntoConstraints = NO; [button addSubview:view]; }
            [NSLayoutConstraint activateConstraints:@[[button.topAnchor constraintEqualToAnchor:self.topAnchor], [button.bottomAnchor constraintEqualToAnchor:self.bottomAnchor], [button.widthAnchor constraintEqualToAnchor:self.widthAnchor multiplier:1.0 / 3.0], [button.leadingAnchor constraintEqualToAnchor:index == 0 ? self.leadingAnchor : ((UIButton *)buttons.lastObject).trailingAnchor], [indicator.centerXAnchor constraintEqualToAnchor:button.centerXAnchor], [indicator.centerYAnchor constraintEqualToAnchor:button.centerYAnchor], [indicator.widthAnchor constraintEqualToConstant:58], [indicator.heightAnchor constraintEqualToConstant:29], [icon.centerXAnchor constraintEqualToAnchor:button.centerXAnchor], [icon.centerYAnchor constraintEqualToAnchor:button.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:22], [icon.heightAnchor constraintEqualToConstant:22]]];
            [buttons addObject:button]; [indicators addObject:indicator]; [icons addObject:icon];
        }
        self.buttons = buttons; self.indicators = indicators; self.icons = icons; [self updateAccessibilityLabels]; [self setSelectedIndex:0];
    } return self;
}
- (void)updateAccessibilityLabels {
    self.buttons[0].accessibilityLabel = SHDWText(@"Home"); self.buttons[1].accessibilityLabel = SHDWText(@"Data backups"); self.buttons[2].accessibilityLabel = SHDWText(@"Settings"); self.buttons[0].accessibilityIdentifier = @"tab.home"; self.buttons[1].accessibilityIdentifier = @"tab.backups"; self.buttons[2].accessibilityIdentifier = @"tab.settings";
}
- (void)setSelectedIndex:(NSUInteger)selectedIndex {
    _selectedIndex = MIN(selectedIndex, (NSUInteger)2);
    for (NSUInteger index = 0; index < self.buttons.count; index++) {
        BOOL selected = index == _selectedIndex; self.indicators[index].hidden = !selected; self.icons[index].tintColor = selected ? SHDWAccent() : UIColor.secondaryLabelColor; self.buttons[index].accessibilityTraits = UIAccessibilityTraitButton | (selected ? UIAccessibilityTraitSelected : 0);
    }
}
- (void)chooseTab:(UIButton *)sender { self.selectedIndex = sender.tag; [self sendActionsForControlEvents:UIControlEventValueChanged]; }
@end
