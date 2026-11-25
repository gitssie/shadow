#import "RegionPresentation.h"

NSString *SHDWRegionIndicator(NSString *region) {
    if (![region isKindOfClass:NSString.class]) return nil;
    NSString *code = region.uppercaseString;
    if (code.length != 2) return nil;
    for (NSUInteger index = 0; index < code.length; ++index) {
        unichar character = [code characterAtIndex:index];
        if (character < 'A' || character > 'Z') return nil;
    }
    return @{@"FR":@"🇫🇷", @"GB":@"🇬🇧", @"US":@"🇺🇸"}[code] ?: code;
}
