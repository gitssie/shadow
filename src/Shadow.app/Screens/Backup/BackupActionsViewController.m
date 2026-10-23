#import "BackupActionsViewController.h"
#import "Services/InstalledApplications.h"
#import "Services/OperationCoordinator.h"
#import "Appearance/Theme.h"

@interface SHDWBackupActionsViewController ()
@property(nonatomic, strong) SHDWInstalledApplication *application;
@property(nonatomic, copy) NSDictionary *snapshot;
@property(nonatomic) BOOL finishing;
@property(nonatomic, copy) NSString *currentIDFV;
@end

@implementation SHDWBackupActionsViewController
- (instancetype)initWithApplication:(SHDWInstalledApplication *)application snapshot:(NSDictionary *)snapshot currentIDFV:(NSString *)currentIDFV {
    if ((self = [super init])) { _application = application; _snapshot = [snapshot copy]; _currentIDFV = [currentIDFV copy]; }
    return self;
}
- (void)viewDidLoad {
    self.sheetTitle = SHDWText(@"Backup actions");
    self.sheetIcon = [SHDWInstalledApplications iconForApplication:self.application];
    [super viewDidLoad];
    self.view.accessibilityIdentifier = @"backup.actions-sheet";
    UIStackView *card = [UIStackView new]; card.axis = UILayoutConstraintAxisVertical; card.backgroundColor = UIColor.whiteColor; card.layer.cornerRadius = 16; card.clipsToBounds = YES;
    BOOL pending = [self.snapshot[@"restorePending"] boolValue], recoverySource = [self.snapshot[@"recoverySource"] boolValue];
    BOOL sameIDFV = self.currentIDFV.length && [[[[NSUUID alloc] initWithUUIDString:self.currentIDFV] UUIDString] isEqual:[[[NSUUID alloc] initWithUUIDString:self.snapshot[@"idfv"]] UUIDString]];
    NSArray *actions = @[@"restore", @"edit", @"recheck", @"delete"];
    NSArray *titles = @[recoverySource ? @"Retry restore" : @"Restore backup", @"Edit backup", @"Recheck backup", @"Delete backup"];
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
        button.enabled = index == 0 ? (!sameIDFV && !(pending && !recoverySource)) : ((index == 1 || index == 3) ? !recoverySource : YES); button.alpha = button.enabled ? 1 : 0.4;
        [button addTarget:self action:@selector(selectAction:) forControlEvents:UIControlEventTouchUpInside]; [button.heightAnchor constraintGreaterThanOrEqualToConstant:48].active = YES; [card addArrangedSubview:button];
    }
    [self.contentStack addArrangedSubview:card];
}
- (void)selectAction:(UIButton *)sender {
    if (self.finishing || !sender.enabled || [SHDWOperationCoordinator isRunning]) return;
    self.finishing = YES; self.view.userInteractionEnabled = NO;
    NSString *action = @[@"restore", @"edit", @"recheck", @"delete"][sender.tag]; void (^selection)(NSString *) = self.selection;
    [self dismissViewControllerAnimated:YES completion:^{ if (selection && ![SHDWOperationCoordinator isRunning]) selection(action); }];
}
@end
