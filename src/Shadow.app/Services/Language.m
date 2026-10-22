#import "Language.h"
NSNotificationName const SHDWLanguageDidChangeNotification = @"Shadow.LanguageDidChange";
NSString *SHDWLanguage(void) {
    NSString *value = [NSUserDefaults.standardUserDefaults stringForKey:@"AppLanguage"];
    return [@[@"en", @"zh-Hans"] containsObject:value ?: @""] ? value : @"system";
}
void SHDWSetLanguage(NSString *language) {
    if (![@[@"system", @"en", @"zh-Hans"] containsObject:language] || [language isEqualToString:SHDWLanguage()]) return;
    [NSUserDefaults.standardUserDefaults setObject:language forKey:@"AppLanguage"];
    [[NSNotificationCenter defaultCenter] postNotificationName:SHDWLanguageDidChangeNotification object:nil];
}
NSString *SHDWLocalizedText(NSString *key) {
    NSString *language = SHDWLanguage();
    if ([language isEqualToString:@"system"]) return [NSBundle.mainBundle localizedStringForKey:key value:key table:nil];
    NSString *path = [NSBundle.mainBundle pathForResource:language ofType:@"lproj"];
    NSBundle *bundle = path ? [NSBundle bundleWithPath:path] : NSBundle.mainBundle;
    return [bundle localizedStringForKey:key value:key table:nil];
}
