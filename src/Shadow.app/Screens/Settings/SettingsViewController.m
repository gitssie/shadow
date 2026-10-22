#import "SettingsViewController.h"
#import "Services/Language.h"
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
@implementation SHDWSettingsViewController
- (instancetype)init { return [super initWithStyle:UITableViewStyleInsetGrouped]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"Settings"); self.view.backgroundColor = SHDWBackground(); self.tableView.rowHeight = 46; self.tableView.accessibilityIdentifier = @"settings.list";
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return 1; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleValue1 reuseIdentifier:nil]; cell.textLabel.text = SHDWText(@"Language"); cell.textLabel.textColor = SHDWInk(); cell.detailTextLabel.text = SHDWLanguageTitle(SHDWLanguage()); cell.accessoryType = UITableViewCellAccessoryDisclosureIndicator; cell.accessibilityIdentifier = @"settings.language"; return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath { [tableView deselectRowAtIndexPath:indexPath animated:YES]; [self.navigationController pushViewController:[SHDWLanguageViewController new] animated:YES]; }
@end
