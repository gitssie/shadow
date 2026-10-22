#import "AppSelectionViewController.h"
#import "Services/InstalledApplications.h"
#import "Appearance/Theme.h"
#import <Shadow/Fingerprint.h>
@interface SHDWAppSelectionViewController () <UISearchResultsUpdating>
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *applications;
@property(nonatomic, copy) NSArray<SHDWInstalledApplication *> *filtered;
@property(nonatomic, strong) UISearchController *searchController;
@property(nonatomic, strong) NSMutableSet<NSString *> *stagedIdentifiers;
@property(nonatomic, copy) NSString *lastAddedIdentifier;
@end
@implementation SHDWAppSelectionViewController
- (instancetype)init { return [super initWithStyle:UITableViewStylePlain]; }
- (void)viewDidLoad {
    [super viewDidLoad]; self.title = SHDWText(@"Applications"); self.view.backgroundColor = SHDWBackground(); self.definesPresentationContext = YES;
    self.navigationItem.rightBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Done") style:UIBarButtonItemStyleDone target:self action:@selector(done)];
    self.navigationItem.leftBarButtonItem = [[UIBarButtonItem alloc] initWithTitle:SHDWText(@"Cancel") style:UIBarButtonItemStylePlain target:self action:@selector(cancel)];
    self.searchController = [[UISearchController alloc] initWithSearchResultsController:nil]; self.searchController.searchResultsUpdater = self; self.searchController.obscuresBackgroundDuringPresentation = NO; self.searchController.searchBar.placeholder = SHDWText(@"Search applications");
    self.navigationItem.searchController = self.searchController; self.navigationItem.hidesSearchBarWhenScrolling = NO;
    self.applications = [SHDWInstalledApplications applications]; self.filtered = self.applications;
    self.stagedIdentifiers = [NSMutableSet setWithArray:[[SHDWFingerprintStore sharedStore] registeredBundleIdentifiers]];
    self.tableView.separatorStyle = UITableViewCellSeparatorStyleNone; self.tableView.rowHeight = 58; self.tableView.backgroundColor = SHDWBackground(); self.tableView.tableFooterView = [UIView new]; self.tableView.accessibilityIdentifier = @"applications.list";
    UILabel *empty = [UILabel new]; empty.text = SHDWText(@"No applications found"); empty.textColor = UIColor.secondaryLabelColor; empty.textAlignment = NSTextAlignmentCenter; empty.numberOfLines = 0;
    self.tableView.backgroundView = self.applications.count ? nil : empty;
}
- (void)cancel { [self dismissViewControllerAnimated:YES completion:nil]; }
- (void)done {
    SHDWFingerprintStore *store = [SHDWFingerprintStore sharedStore];
    NSSet *actual = [NSSet setWithArray:[store registeredBundleIdentifiers]];
    NSMutableSet *additions = [self.stagedIdentifiers mutableCopy]; [additions minusSet:actual];
    NSMutableSet *removals = [actual mutableCopy]; [removals minusSet:self.stagedIdentifiers];
    NSError *error = nil; NSUInteger completed = 0; BOOL success = YES;
    NSMutableSet<NSString *> *completedRemovals = [NSMutableSet new];
    for (NSString *identifier in [[additions allObjects] sortedArrayUsingSelector:@selector(compare:)]) {
        if (![store registerApplication:identifier error:&error]) { success = NO; break; } completed++;
    }
    if (success) for (NSString *identifier in [[removals allObjects] sortedArrayUsingSelector:@selector(compare:)]) {
        if (![store removeApplication:identifier error:&error]) { success = NO; break; } [completedRemovals addObject:identifier]; completed++;
    }
    if (completed && self.selectionChanged) self.selectionChanged(@"", [completedRemovals copy]);
    if (!success) {
        if (completed) {
            NSString *message = [NSString stringWithFormat:@"%@\n%@", SHDWText(@"Some changes were saved. Retry to finish."), error.localizedDescription ?: SHDWText(@"Try again")];
            NSError *partial = [NSError errorWithDomain:@"Shadow.AppSelection" code:1 userInfo:@{NSLocalizedDescriptionKey:message}]; SHDWShowError(self, partial);
        } else SHDWShowError(self, error);
        return;
    }
    if (self.selectionChanged) self.selectionChanged([self.stagedIdentifiers containsObject:self.lastAddedIdentifier ?: @""] ? self.lastAddedIdentifier : @"", [completedRemovals copy]);
    [self dismissViewControllerAnimated:YES completion:nil];
}
- (void)updateSearchResultsForSearchController:(UISearchController *)searchController {
    NSString *query = [searchController.searchBar.text stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    self.filtered = query.length ? [self.applications filteredArrayUsingPredicate:[NSPredicate predicateWithBlock:^BOOL(SHDWInstalledApplication *app, NSDictionary *bindings) { return [app.name localizedCaseInsensitiveContainsString:query] || [app.bundleIdentifier localizedCaseInsensitiveContainsString:query]; }]] : self.applications;
    [self.tableView reloadData];
}
- (NSInteger)tableView:(UITableView *)tableView numberOfRowsInSection:(NSInteger)section { return self.filtered.count; }
- (UITableViewCell *)tableView:(UITableView *)tableView cellForRowAtIndexPath:(NSIndexPath *)indexPath {
    UITableViewCell *cell = [tableView dequeueReusableCellWithIdentifier:@"Application"];
    if (!cell) {
        cell = [[UITableViewCell alloc] initWithStyle:UITableViewCellStyleDefault reuseIdentifier:@"Application"];
        cell.backgroundColor = UIColor.clearColor;
        UIImageView *icon = [UIImageView new]; icon.tag = 1; icon.layer.cornerRadius = 8; icon.clipsToBounds = YES; icon.contentMode = UIViewContentModeScaleAspectFit;
        UILabel *name = [UILabel new]; name.tag = 2; name.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody]; name.textColor = SHDWInk(); name.adjustsFontForContentSizeCategory = YES;
        UILabel *identifier = [UILabel new]; identifier.tag = 3; identifier.font = [UIFont systemFontOfSize:11]; identifier.textColor = UIColor.secondaryLabelColor;
        UIStackView *labels = [[UIStackView alloc] initWithArrangedSubviews:@[name, identifier]]; labels.axis = UILayoutConstraintAxisVertical; labels.spacing = 3;
        for (UIView *view in @[icon, labels]) { view.translatesAutoresizingMaskIntoConstraints = NO; [cell.contentView addSubview:view]; }
        [NSLayoutConstraint activateConstraints:@[[icon.leadingAnchor constraintEqualToAnchor:cell.contentView.leadingAnchor constant:20], [icon.centerYAnchor constraintEqualToAnchor:cell.contentView.centerYAnchor], [icon.widthAnchor constraintEqualToConstant:34], [icon.heightAnchor constraintEqualToConstant:34], [labels.leadingAnchor constraintEqualToAnchor:icon.trailingAnchor constant:12], [labels.trailingAnchor constraintEqualToAnchor:cell.contentView.trailingAnchor constant:-12], [labels.centerYAnchor constraintEqualToAnchor:cell.contentView.centerYAnchor]]];
        UIView *separator = [UIView new]; separator.tag = 4; separator.backgroundColor = UIColor.separatorColor; separator.translatesAutoresizingMaskIntoConstraints = NO; [cell addSubview:separator];
        [NSLayoutConstraint activateConstraints:@[[separator.leadingAnchor constraintEqualToAnchor:cell.leadingAnchor constant:66], [separator.trailingAnchor constraintEqualToAnchor:cell.trailingAnchor constant:-20], [separator.bottomAnchor constraintEqualToAnchor:cell.bottomAnchor], [separator.heightAnchor constraintEqualToConstant:1.0 / UIScreen.mainScreen.scale]]];
    }
    SHDWInstalledApplication *app = self.filtered[indexPath.row]; ((UILabel *)[cell.contentView viewWithTag:2]).text = app.name; ((UILabel *)[cell.contentView viewWithTag:3]).text = app.bundleIdentifier; ((UIImageView *)[cell.contentView viewWithTag:1]).image = [SHDWInstalledApplications iconForApplication:app];
    [cell viewWithTag:4].hidden = (NSUInteger)indexPath.row + 1 == self.filtered.count;
    cell.accessibilityLabel = app.name;
    BOOL locked = [[SHDWFingerprintStore sharedStore] lockedForApplication:app.bundleIdentifier];
    UIImageView *lock = locked ? [[UIImageView alloc] initWithImage:SHDWSymbol(@"lock.fill", 17)] : nil;
    lock.tintColor = SHDWLockColor(); cell.accessoryView = lock;
    cell.selectionStyle = locked ? UITableViewCellSelectionStyleNone : UITableViewCellSelectionStyleDefault;
    cell.accessibilityHint = locked ? SHDWText(@"Unlock fingerprint before removing application") : nil;
    cell.accessibilityTraits = locked ? UIAccessibilityTraitNotEnabled : UIAccessibilityTraitNone;
    cell.accessoryType = [self.stagedIdentifiers containsObject:app.bundleIdentifier] ? UITableViewCellAccessoryCheckmark : UITableViewCellAccessoryNone; cell.accessibilityIdentifier = [@"applications." stringByAppendingString:app.bundleIdentifier]; return cell;
}
- (void)tableView:(UITableView *)tableView didSelectRowAtIndexPath:(NSIndexPath *)indexPath {
    [tableView deselectRowAtIndexPath:indexPath animated:YES]; SHDWInstalledApplication *app = self.filtered[indexPath.row];
    if ([[SHDWFingerprintStore sharedStore] lockedForApplication:app.bundleIdentifier]) return;
    if ([self.stagedIdentifiers containsObject:app.bundleIdentifier]) [self.stagedIdentifiers removeObject:app.bundleIdentifier];
    else { [self.stagedIdentifiers addObject:app.bundleIdentifier]; self.lastAddedIdentifier = app.bundleIdentifier; }
    [self.tableView reloadRowsAtIndexPaths:@[indexPath] withRowAnimation:UITableViewRowAnimationNone];
}
@end
