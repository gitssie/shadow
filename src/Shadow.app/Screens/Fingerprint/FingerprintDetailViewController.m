#import "FingerprintDetailViewController.h"
#import "Appearance/Theme.h"
#import <Shadow/Fingerprint.h>
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
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return 2; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil]; cell.selectionStyle = UITableViewCellSelectionStyleNone; cell.textLabel.textColor = SHDWInk(); cell.textLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleSubheadline]; cell.detailTextLabel.font = cell.textLabel.font; cell.detailTextLabel.textColor = UIColor.secondaryLabelColor;
    if (indexPath.section == 0) {
        cell.textLabel.text = indexPath.row == 0 ? @"iOS" : SHDWText(@"Region"); cell.detailTextLabel.text = indexPath.row == 0 ? @"18.7.1" : @"France"; cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator; cell.selectionStyle = UITableViewCellSelectionStyleDefault;
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
- (void)lockedChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setLocked:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (void)shadowChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setShadowEnabled:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (void)aggressiveChanged:(UISwitch *)toggle { NSError *error = nil; if (![[SHDWFingerprintStore sharedStore] setAggressive:toggle.on forApplication:self.bundleIdentifier error:&error]) { toggle.on = !toggle.on; SHDWShowError(self, error); } }
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES]; if (indexPath.section != 0) return;
    UIAlertController *alert = [UIAlertController alertControllerWithTitle:SHDWText(indexPath.row == 0 ? @"System version" : @"Region") message:(indexPath.row == 0 ? @"iOS 18.7.1 (22H31)" : @"France · fr_FR · Europe/Paris") preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:SHDWText(@"OK") style:UIAlertActionStyleDefault handler:nil]]; [self presentViewController:alert animated:YES completion:nil];
}
@end
