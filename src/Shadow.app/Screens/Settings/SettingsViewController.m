#import "SettingsViewController.h"
#import "Services/Language.h"
#import "Services/IPSwitchConfiguration.h"
#import "Appearance/Theme.h"
static NSArray<NSString *> *SHDWLanguages(void) { return @[@"system", @"zh-Hans", @"en"]; }
static NSString *SHDWLanguageTitle(NSString *language) {
    if ([language isEqualToString:@"zh-Hans"]) return @"简体中文";
    if ([language isEqualToString:@"en"]) return @"English";
    return SHDWText(@"Follow system");
}
@interface SHDWLanguageViewController : UITableViewController @end
@implementation SHDWLanguageViewController
- (instancetype)init { return [super initWithStyle:UITableViewStyleInsetGrouped]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"Language"); self.view.backgroundColor = SHDWBackground(); self.tableView.rowHeight = 46; self.tableView.accessibilityIdentifier = @"settings.languages";
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return SHDWLanguages().count; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:nil]; NSString *language = SHDWLanguages()[indexPath.row];
    cell.textLabel.text = SHDWLanguageTitle(language); cell.textLabel.textColor = SHDWInk(); cell.textLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; cell.accessoryType = [language isEqualToString:SHDWLanguage()] ? UITableViewCellAccessoryCheckmark : UITableViewCellAccessoryNone; cell.accessibilityIdentifier = [@"language." stringByAppendingString:language]; return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath { [tableView deselectRowAtIndexPath:indexPath animated:YES]; SHDWSetLanguage(SHDWLanguages()[indexPath.row]); }
@end
@interface SHDWIPSwitchSettingsViewController ()
@property(nonatomic, strong) NSMutableArray<NSMutableDictionary *> *entries;
@end
@implementation SHDWIPSwitchSettingsViewController
- (instancetype)init { return [super initWithStyle:UITableViewStyleInsetGrouped]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"IP switching"); self.view.backgroundColor = SHDWBackground();
    self.tableView.rowHeight = UITableViewAutomaticDimension; self.tableView.estimatedRowHeight = 52; self.tableView.keyboardDismissMode = UIScrollViewKeyboardDismissModeOnDrag; self.tableView.accessibilityIdentifier = @"settings.ip-switch.list";
    self.entries = [NSMutableArray new];
    for (NSDictionary *item in SHDWIPSwitchConfiguration.configurations) [self.entries addObject:[item mutableCopy]];
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Save") style:UIBarButtonItemStyleDone target:self action:@selector(save)];
    self.navigationItem.rightBarButtonItem.accessibilityIdentifier = @"settings.ip-switch.save";
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return self.entries.count + 1; }
- (NSString *)tableView:(UITableView *)tableView titleForFooterInSection:(NSInteger)section { return SHDWText(@"Enter a label on the left and the full switch URL on the right. Swipe a row to delete it."); }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:nil];
    if (indexPath.row == self.entries.count) { cell.textLabel.text = SHDWText(@"Add URL"); cell.textLabel.textColor = SHDWAccent(); cell.imageView.image = SHDWSymbol(@"plus.circle", 19); cell.imageView.tintColor = SHDWAccent(); cell.accessibilityIdentifier = @"settings.ip-switch.add"; return cell; }
    cell.selectionStyle = UITableViewCellSelectionStyleNone;
    UITextField *label = [UITextField new], *url = [UITextField new];
    label.text = self.entries[indexPath.row][@"name"]; label.placeholder = SHDWText(@"Label"); label.tag = indexPath.row * 2;
    url.text = self.entries[indexPath.row][@"url"]; url.placeholder = @"https://…"; url.tag = indexPath.row * 2 + 1; url.keyboardType = UIKeyboardTypeURL; url.clearButtonMode = UITextFieldViewModeWhileEditing;
    label.accessibilityLabel = SHDWText(@"Label"); url.accessibilityLabel = @"URL";
    label.accessibilityIdentifier = [NSString stringWithFormat:@"settings.ip-switch.label.%ld", (long)indexPath.row]; url.accessibilityIdentifier = [NSString stringWithFormat:@"settings.ip-switch.url.%ld", (long)indexPath.row];
    UIView *separator = [UIView new]; separator.backgroundColor = UIColor.separatorColor; separator.translatesAutoresizingMaskIntoConstraints = NO; [cell.contentView addSubview:separator];
    for (UITextField *field in @[label, url]) {
        field.translatesAutoresizingMaskIntoConstraints = NO; field.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; field.adjustsFontForContentSizeCategory = YES; field.textColor = SHDWInk(); field.tintColor = SHDWAccent();
        field.autocapitalizationType = UITextAutocapitalizationTypeNone; field.autocorrectionType = UITextAutocorrectionTypeNo; field.smartQuotesType = UITextSmartQuotesTypeNo; field.smartDashesType = UITextSmartDashesTypeNo;
        [field addTarget:self action:@selector(fieldChanged:) forControlEvents:UIControlEventEditingChanged]; [cell.contentView addSubview:field];
    }
    [NSLayoutConstraint activateConstraints:@[
        [label.heightAnchor constraintGreaterThanOrEqualToConstant:44], [label.leadingAnchor constraintEqualToAnchor:cell.contentView.leadingAnchor constant:16], [label.widthAnchor constraintEqualToConstant:76], [label.topAnchor constraintEqualToAnchor:cell.contentView.topAnchor constant:4], [label.bottomAnchor constraintEqualToAnchor:cell.contentView.bottomAnchor constant:-4],
        [separator.leadingAnchor constraintEqualToAnchor:label.trailingAnchor constant:8], [separator.widthAnchor constraintEqualToConstant:1], [separator.heightAnchor constraintEqualToConstant:24], [separator.centerYAnchor constraintEqualToAnchor:cell.contentView.centerYAnchor],
        [url.leadingAnchor constraintEqualToAnchor:separator.trailingAnchor constant:12], [url.trailingAnchor constraintEqualToAnchor:cell.contentView.trailingAnchor constant:-16], [url.topAnchor constraintEqualToAnchor:label.topAnchor], [url.bottomAnchor constraintEqualToAnchor:label.bottomAnchor]
    ]]; return cell;
}
- (void)fieldChanged:(UITextField *)field {
    NSUInteger index = (NSUInteger)field.tag / 2;
    if (index < self.entries.count) self.entries[index][field.tag % 2 ? @"url" : @"name"] = field.text ?: @"";
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES];
    if (indexPath.row != self.entries.count) return;
    [self.view endEditing:YES]; [self.entries addObject:[@{@"name":@"", @"url":@""} mutableCopy]]; [self.tableView reloadData];
    [self.tableView scrollToRowAtIndexPath:[NSIndexPath indexPathForRow:self.entries.count - 1 inSection:0] atScrollPosition:UITableViewScrollPositionMiddle animated:YES];
}
- (BOOL)tableView:(UITableView *)tableView canEditRowAtIndexPath:(NSIndexPath *)indexPath { return indexPath.row < self.entries.count; }
- (void)tableView:(UITableView *)tableView commitEditingStyle:(UITableViewCellEditingStyle)style forRowAtIndexPath:(NSIndexPath *)indexPath {
    if (style != UITableViewCellEditingStyleDelete || indexPath.row >= self.entries.count) return;
    [self.view endEditing:YES]; [self.entries removeObjectAtIndex:indexPath.row]; [self.tableView reloadData];
}
- (void)save {
    [self.view endEditing:YES]; NSError *error = nil;
    if (![SHDWIPSwitchConfiguration saveConfigurations:self.entries error:&error]) { SHDWShowError(self, error); return; }
    [self.navigationController popViewControllerAnimated:YES];
}
@end

@implementation SHDWSettingsViewController
- (instancetype)init { return [super initWithStyle:UITableViewStyleInsetGrouped]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"Settings"); self.view.backgroundColor = SHDWBackground(); self.tableView.rowHeight = 46; self.tableView.accessibilityIdentifier = @"settings.list";
}
- (void)viewWillAppear:(BOOL)animated { [super viewWillAppear:animated]; [self.tableView reloadData]; }
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return 2; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil]; cell.textLabel.textColor = SHDWInk(); cell.imageView.tintColor = SHDWAccent(); cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator;
    if (!indexPath.row) { cell.textLabel.text = SHDWText(@"Language"); cell.detailTextLabel.text = SHDWLanguageTitle(SHDWLanguage()); cell.imageView.image = SHDWSymbol(@"character.bubble", 17); cell.accessibilityIdentifier = @"settings.language"; }
    else { cell.textLabel.text = SHDWText(@"IP switching"); NSUInteger count = SHDWIPSwitchConfiguration.configurations.count; cell.detailTextLabel.text = count ? [NSString stringWithFormat:@"%lu", (unsigned long)count] : SHDWText(@"Not configured"); cell.imageView.image = SHDWIPSwitchSymbol(17); cell.accessibilityIdentifier = @"settings.ip-switch"; }
    return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath { [tableView deselectRowAtIndexPath:indexPath animated:YES]; [self.navigationController pushViewController:indexPath.row ? [SHDWIPSwitchSettingsViewController new] : [SHDWLanguageViewController new] animated:YES]; }
@end
