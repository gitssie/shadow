#import "FingerprintDetailViewController.h"
#import "Appearance/Theme.h"
#import <Shadow/Fingerprint.h>
#import <Shadow/FingerprintConfiguration.h>

// A selection stays local until Done; the store enforces the lock again on save.
@interface SHDWConfigurationSelectionController : UITableViewController
@property(nonatomic, copy) NSArray<NSDictionary *> *options;
@property(nonatomic, strong) NSMutableSet<NSString *> *selection;
@property(nonatomic) BOOL multiple;
@property(nonatomic, copy) BOOL (^saveSelection)(NSSet<NSString *> *selection);
@end
@implementation SHDWConfigurationSelectionController
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.tableView.rowHeight = 46;
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Done") style:UIBarButtonItemStyleDone target:self action:@selector(done)];
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return self.options.count; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    NSDictionary *option = self.options[indexPath.row];
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil];
    cell.textLabel.text = option[@"Name"]; cell.textLabel.textColor = SHDWInk(); cell.textLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline]; cell.detailTextLabel.text = option[@"Detail"]; cell.tintColor = SHDWAccent();
    cell.accessoryType = [self.selection containsObject:option[@"ID"]] ? UITableViewCellAccessoryCheckmark : UITableViewCellAccessoryNone;
    return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    NSString *identifier = self.options[indexPath.row][@"ID"];
    if (!self.multiple) [self.selection removeAllObjects];
    if (self.multiple && [self.selection containsObject:identifier]) [self.selection removeObject:identifier]; else [self.selection addObject:identifier];
    [tableView reloadData];
}
- (void)done { if (self.saveSelection(self.selection)) [self.navigationController popViewControllerAnimated:YES]; }
@end

@interface SHDWFingerprintDetailViewController ()
@property(nonatomic, copy) NSString *bundleIdentifier;
@end
@implementation SHDWFingerprintDetailViewController
- (instancetype)initWithBundleIdentifier:(NSString *)bundleIdentifier name:(NSString *)name {
    if ((self = [super initWithStyle:UITableViewStyleInsetGrouped])) { _bundleIdentifier = [bundleIdentifier copy]; self.title = name; } return self;
}
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = SHDWBackground(); self.tableView.rowHeight = 46; self.tableView.estimatedRowHeight = 46; self.tableView.sectionHeaderHeight = 16; self.tableView.sectionFooterHeight = 0.01; self.tableView.accessibilityIdentifier = @"fingerprint.details";
    if (@available(iOS 15.0, *)) self.tableView.sectionHeaderTopPadding = 0;
}
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.tableView reloadData]; }
- (NSInteger)numberOfSectionsInTableView:(UITableView *)tableView { return 3; }
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return section == 0 ? 6 : 2; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil]; cell.selectionStyle = UITableViewCellSelectionStyleNone; cell.textLabel.textColor = SHDWInk(); cell.textLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline]; cell.detailTextLabel.font = cell.textLabel.font; cell.detailTextLabel.textColor = UIColor.secondaryLabelColor;
    if (indexPath.section == 0) {
        SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
        NSDictionary *configuration = [store configurationForApplication:self.bundleIdentifier];
        BOOL locked = [store lockedForApplication:self.bundleIdentifier];
        NSArray *labels = @[@"iOS", SHDWText(@"Region"), SHDWText(@"Time zone"), SHDWText(@"Language"), SHDWText(@"Network"), SHDWText(@"Receipt interception")];
        cell.textLabel.text = labels[indexPath.row];
        cell.accessibilityIdentifier = @[@"fingerprint.system", @"fingerprint.region", @"fingerprint.time-zone", @"fingerprint.language", @"fingerprint.network", @"fingerprint.receipts-row"][indexPath.row];
        if (indexPath.row == 0) {
            NSDictionary *profile = [SHDWFingerprintConfiguration systemProfileForConfiguration:configuration];
            cell.detailTextLabel.text = profile[@"Version"] ?: UIDevice.currentDevice.systemVersion;
        } else if (indexPath.row == 1) cell.detailTextLabel.text = [NSLocale.currentLocale objectForKey:NSLocaleCountryCode] ?: @"—";
        else if (indexPath.row == 2) cell.detailTextLabel.text = NSTimeZone.systemTimeZone.name;
        else if (indexPath.row == 3) cell.detailTextLabel.text = NSLocale.preferredLanguages.firstObject ?: @"—";
        else if (indexPath.row == 4) {
            NSArray *technologies = configuration[@"Network"][@"RadioTechnologies"];
            NSMutableArray *values = [NSMutableArray new];
            for (NSString *value in @[@"4g", @"5g"]) if ([technologies containsObject:value]) [values addObject:value.uppercaseString];
            cell.detailTextLabel.text = values.count ? [values componentsJoinedByString:@" / "] : @"—";
        } else {
            UISwitch *toggle = [UISwitch new]; toggle.onTintColor = SHDWAccent(); toggle.on = [configuration[@"Receipts"][@"InterceptEnabled"] boolValue]; toggle.enabled = !locked;
            toggle.accessibilityIdentifier = @"fingerprint.receipts"; [toggle addTarget:self action:@selector(receiptsChanged:) forControlEvents:UIControlEventValueChanged]; cell.accessoryView = toggle;
        }
        if (indexPath.row == 0 || indexPath.row == 4) {
            cell.accessoryType = locked ? UITableViewCellAccessoryNone : UITableViewCellAccessoryDisclosureIndicator;
            cell.selectionStyle = locked ? UITableViewCellSelectionStyleNone : UITableViewCellSelectionStyleDefault;
            cell.textLabel.textColor = locked ? UIColor.secondaryLabelColor : SHDWInk();
        }
    } else if (indexPath.section == 1) {
        BOOL enabledRow = indexPath.row == 0;
        cell.textLabel.text = SHDWText(enabledRow ? @"Enable fingerprint" : @"Lock fingerprint");
        UISwitch *toggle = [UISwitch new]; toggle.onTintColor = SHDWAccent();
        toggle.on = enabledRow ? [[SHDWFingerprintStore sharedStore] enabledForApplication:self.bundleIdentifier] : [[SHDWFingerprintStore sharedStore] lockedForApplication:self.bundleIdentifier];
        [toggle addTarget:self action:(enabledRow ? @selector(enabledChanged:) : @selector(lockedChanged:)) forControlEvents:UIControlEventValueChanged]; toggle.accessibilityIdentifier = enabledRow ? @"fingerprint.enabled" : @"fingerprint.locked"; cell.accessoryView = toggle;
    } else if (indexPath.row == 0) {
        cell.textLabel.text = SHDWText(@"Aggressive mode"); UISwitch *toggle = [UISwitch new]; toggle.onTintColor = SHDWAccent(); toggle.on = [[SHDWFingerprintStore sharedStore] aggressiveForApplication:self.bundleIdentifier]; [toggle addTarget:self action:@selector(aggressiveChanged:) forControlEvents:UIControlEventValueChanged]; toggle.accessibilityIdentifier = @"fingerprint.aggressive"; cell.accessoryView = toggle;
    } else {
        BOOL enabled = [[SHDWFingerprintStore sharedStore] shadowEnabledForApplication:self.bundleIdentifier];
        cell.textLabel.text = SHDWText(@"Shadow status");
        UISwitch *status = [UISwitch new]; status.onTintColor = SHDWAccent(); status.on = enabled; [status addTarget:self action:@selector(shadowChanged:) forControlEvents:UIControlEventValueChanged]; status.accessibilityIdentifier = @"fingerprint.shadow-status"; cell.accessoryView = status;
    } return cell;
}
- (void)enabledChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setEnabled:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (void)lockedChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setLocked:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } [self.tableView reloadData]; }
- (void)shadowChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setShadowEnabled:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (void)aggressiveChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setAggressive:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (BOOL)saveConfiguration:(NSDictionary *)configuration {
    if ([configuration isEqual:[[SHDWFingerprintStore sharedStore] configurationForApplication:self.bundleIdentifier]]) return YES;
    NSError *error = nil;
    BOOL saved = [[SHDWFingerprintStore sharedStore] setConfiguration:configuration forApplication:self.bundleIdentifier error:&error];
    if (!saved) SHDWShowError(self.navigationController.topViewController ?: self, error);
    [self.tableView reloadData]; return saved;
}
- (void)receiptsChanged:(UISwitch *)toggle {
    NSMutableDictionary *configuration = [[[SHDWFingerprintStore sharedStore] configurationForApplication:self.bundleIdentifier] mutableCopy];
    configuration[@"Receipts"] = @{@"InterceptEnabled": @(toggle.on)};
    if (![self saveConfiguration:configuration]) toggle.on = !toggle.on;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES];
    if (indexPath.section != 0 || (indexPath.row != 0 && indexPath.row != 4)) return;
    SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
    if ([store lockedForApplication:self.bundleIdentifier]) return;
    NSDictionary *configuration = [store configurationForApplication:self.bundleIdentifier];
    SHDWConfigurationSelectionController *controller = [[SHDWConfigurationSelectionController alloc] initWithStyle:UITableViewStyleInsetGrouped];
    controller.multiple = indexPath.row == 4;
    controller.title = SHDWText(controller.multiple ? @"Network" : @"System version");
    if (controller.multiple) {
        controller.options = @[@{@"ID": @"4g", @"Name": @"4G"}, @{@"ID": @"5g", @"Name": @"5G"}];
        controller.selection = [NSMutableSet setWithArray:configuration[@"Network"][@"RadioTechnologies"] ?: @[]];
    } else {
        NSMutableArray *options = [NSMutableArray arrayWithObject:@{@"ID": @"native", @"Name": SHDWText(@"Use device system"), @"Detail": UIDevice.currentDevice.systemVersion}];
        for (NSDictionary *profile in [SHDWFingerprintConfiguration systemProfilesForCurrentDevice]) [options addObject:@{@"ID": profile[@"ID"], @"Name": profile[@"Version"], @"Detail": profile[@"Build"] ?: @""}];
        controller.options = options;
        controller.selection = [NSMutableSet setWithObject:[configuration[@"System"][@"Mode"] isEqual:@"profile"] ? configuration[@"System"][@"ProfileID"] : @"native"];
    }
    __weak typeof(self) weakSelf = self; BOOL network = controller.multiple;
    controller.saveSelection = ^BOOL(NSSet<NSString *> *selection) {
        typeof(self) self = weakSelf; if (!self) return NO;
        NSMutableDictionary *latest = [[[SHDWFingerprintStore sharedStore] configurationForApplication:self.bundleIdentifier] mutableCopy];
        if (network) {
            NSMutableArray *technologies = [NSMutableArray new];
            for (NSString *value in @[@"4g", @"5g"]) if ([selection containsObject:value]) [technologies addObject:value];
            latest[@"Network"] = @{@"RadioTechnologies": technologies};
        } else {
            NSString *identifier = selection.anyObject ?: @"native";
            latest[@"System"] = [identifier isEqual:@"native"] ? @{@"Mode": @"native"} : @{@"Mode": @"profile", @"ProfileID": identifier};
        }
        return [self saveConfiguration:latest];
    };
    [self.navigationController pushViewController:controller animated:YES];
}
@end
