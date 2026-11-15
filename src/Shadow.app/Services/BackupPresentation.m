#import "BackupPresentation.h"
#import "Language.h"
#import <Shadow/FingerprintConfiguration.h>
#import "../../AppState/BackupStatus.h"

static NSDictionary *Dictionary(id value) { return [value isKindOfClass:NSDictionary.class] ? value : nil; }
static NSString *String(id value) { return [value isKindOfClass:NSString.class] && [value length] ? value : nil; }
static NSString *Display(id value) { return String(value) ?: SHDWLocalizedText(@"Not set"); }
static NSString *Choice(id value) { return [value isEqual:@"native"] ? SHDWLocalizedText(@"Follow system") : Display(value); }
static NSDictionary *Row(NSString *label, id value) {
    return @{@"label":SHDWLocalizedText(label), @"value":Display(value)};
}
NSString *SHDWBackupStatusTitle(NSString *status) {
    if (!String(status)) return nil;
    NSDictionary *titles = @{
        SHDWBackupStatusBackingUp:@"Backing up data", SHDWBackupStatusBackedUp:@"Backup saved",
        SHDWBackupStatusResetting:@"Cleaning", SHDWBackupStatusResetCompleted:@"Cleanup completed",
        SHDWBackupStatusRestoring:@"Restoring data", SHDWBackupStatusIdentityPending:@"Restoring data",
        SHDWBackupStatusIdentityCommitted:@"Verifying backup", SHDWBackupStatusRestored:@"Restore completed"
    };
    if (titles[status]) return SHDWLocalizedText(titles[status]);
    NSString *action = [status isEqual:SHDWBackupStatusBackupFailed] ? @"Back up current data" :
        [status isEqual:SHDWBackupStatusResetFailed] ? @"Clean application data" :
        [status isEqual:SHDWBackupStatusRestoreFailed] ? @"Restore backup" : nil;
    return action ? [NSString stringWithFormat:@"%@ · %@", SHDWLocalizedText(action), SHDWLocalizedText(@"Failed")] : nil;
}
NSArray<NSDictionary *> *SHDWBackupDetailFields(NSDictionary *snapshot, NSString *currentIDFV) {
    snapshot = Dictionary(snapshot) ?: @{};
    NSString *date = nil;
    if ([snapshot[@"date"] isKindOfClass:NSDate.class]) {
        NSDateFormatter *formatter = [NSDateFormatter new];
        formatter.locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US_POSIX"];
        formatter.dateFormat = @"yyyy-MM-dd HH:mm:ss";
        date = [formatter stringFromDate:snapshot[@"date"]];
    }
    NSString *size = [snapshot[@"size"] isKindOfClass:NSNumber.class] ? [NSByteCountFormatter stringFromByteCount:[snapshot[@"size"] longLongValue] countStyle:NSByteCountFormatterCountStyleFile] : nil;
    NSDictionary *config = Dictionary(snapshot[@"Fingerprint_Config"]);
    NSDictionary *system = Dictionary(config[@"System"]), *localization = Dictionary(config[@"Localization"]);
    NSDictionary *profile = [SHDWFingerprintConfiguration systemProfileForConfiguration:@{@"System":system ?: @{}}];
    NSString *version = [system[@"Mode"] isEqual:@"native"] ? SHDWLocalizedText(@"Follow system") : (String(profile[@"Version"]) ?: String(system[@"ProfileID"]));
    NSDictionary *network = Dictionary(config[@"Network"]);
    NSString *tls = config ? SHDWLocalizedText([SHDWFingerprintConfiguration usesCurlTransportForConfiguration:@{@"Network":network ?: @{}}] ? @"Enabled" : @"Disabled") : nil;
    NSMutableArray *radios = [NSMutableArray new];
    if ([network[@"RadioTechnologies"] isKindOfClass:NSArray.class])
        for (NSString *radio in @[@"4g", @"5g"]) if ([network[@"RadioTechnologies"] containsObject:radio]) [radios addObject:radio.uppercaseString];
    NSString *mode = String(Dictionary(config[@"Advertising"])[@"Mode"]) ?: (config ? @"zero" : nil);
    NSString *advertising = mode ? SHDWLocalizedText([mode isEqual:@"zero"] ? @"Disable tracking" : [mode isEqual:@"system"] ? @"Follow system" : @"Advertising fingerprint") : nil;
    id receipts = Dictionary(config[@"Receipts"])[@"InterceptEnabled"];
    NSString *receipt = config ? SHDWLocalizedText([receipts respondsToSelector:@selector(boolValue)] && [receipts boolValue] ? @"Enabled" : @"Disabled") : nil;
    NSString *identifier = String(snapshot[@"idfv"]);
    NSUUID *saved = identifier ? [[NSUUID alloc] initWithUUIDString:identifier] : nil;
    NSUUID *current = String(currentIDFV) ? [[NSUUID alloc] initWithUUIDString:currentIDFV] : nil;
    NSDictionary *name = @{@"label":SHDWLocalizedText(@"Name"), @"value":Display(snapshot[@"title"]),
        @"owner":[(snapshot[@"owner"] ?: @"phone") isEqual:@"phone"] ? @"phone" : @"rv", @"current":@(saved && [saved isEqual:current]), @"fullWidth":@YES};
    NSMutableArray *fields = [NSMutableArray arrayWithArray:@[
        name,
        Row(@"iOS", version), Row(@"Region", Choice(localization[@"Region"])), Row(@"Time zone", Choice(localization[@"TimeZone"])),
        Row(@"Language", Choice(localization[@"Language"])), Row(@"Network", radios.count ? [radios componentsJoinedByString:@" / "] : nil),
        Row(@"Receipt interception", receipt), Row(@"Advertising tracking", advertising), Row(@"TLS fingerprint", tls)
    ]];
    if (String(snapshot[@"error"])) [fields addObject:Row(@"Error", SHDWLocalizedText(snapshot[@"error"]))];
    [fields addObject:Row(@"Backup size", size)];
    [fields addObject:@{@"label":SHDWLocalizedText(@"Backup date"), @"value":Display(date), @"fullWidth":@YES}];
    NSString *note = String(snapshot[@"note"]);
    if ([note stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].length)
        [fields addObject:@{@"label":SHDWLocalizedText(@"Note"), @"value":note, @"fullWidth":@YES}];
    return [fields copy];
}
