#import "OwnershipDiagnostics.h"
#import "Language.h"
NSString *SHDWOwnershipErrorDescription(NSString *message, NSDictionary *details) {
    NSString *description = SHDWLocalizedText(message);
    BOOL containers = [details[@"kind"] isEqual:@"containerOwnership"];
    if (!containers && ![details[@"kind"] isEqual:@"keychainOwnership"]) return description;
    NSMutableArray *lines = [NSMutableArray arrayWithObject:description];
    NSDictionary *owners = details[containers ? @"sharedGroupOwners" : @"sharedKeychainOwners"];
    NSArray *shared = details[containers ? @"sharedAppGroups" : @"sharedKeychainGroups"] ?: @[];
    NSArray *groups = containers ? (details[@"containerGroups"] ?: shared) : (shared.count ? shared : details[@"keychainGroups"]);
    for (NSString *group in groups) {
        BOOL confirmed = [shared containsObject:group];
        NSString *title = containers ? (confirmed ? @"Shared app group" : @"App group being checked") : (confirmed ? @"Shared keychain group" : @"Keychain group being checked");
        [lines addObject:[NSString stringWithFormat:@"\n%@: %@", SHDWLocalizedText(title), group]];
        for (NSString *identifier in owners[group]) [lines addObject:identifier];
    }
    for (NSDictionary *issue in details[@"ownershipIssues"]) {
        [lines addObject:[NSString stringWithFormat:@"\n%@: %@\n%@", SHDWLocalizedText(@"Cannot check app"), issue[@"bundleID"] ?: @"—", SHDWLocalizedText(issue[@"reason"] ?: @"Unreadable ownership")]];
    }
    return [lines componentsJoinedByString:@"\n"];
}
