#import "OwnershipDiagnostics.h"
#import "Language.h"
NSString *SHDWOwnershipErrorDescription(NSString *message, NSDictionary *details) {
    NSString *description = SHDWLocalizedText(message);
    if (![details[@"kind"] isEqual:@"keychainOwnership"]) return description;
    NSMutableArray *lines = [NSMutableArray arrayWithObject:description];
    NSDictionary *owners = details[@"sharedKeychainOwners"];
    for (NSString *group in details[@"sharedKeychainGroups"]) {
        [lines addObject:[NSString stringWithFormat:@"\n%@: %@", SHDWLocalizedText(@"Shared keychain group"), group]];
        for (NSString *identifier in owners[group]) [lines addObject:identifier];
    }
    for (NSDictionary *issue in details[@"ownershipIssues"]) {
        [lines addObject:[NSString stringWithFormat:@"\n%@: %@\n%@", SHDWLocalizedText(@"Cannot check app"), issue[@"bundleID"] ?: @"—", SHDWLocalizedText(issue[@"reason"] ?: @"Unreadable ownership")]];
    }
    return [lines componentsJoinedByString:@"\n"];
}
