#import "ApplicationEligibility.h"

BOOL SHDWApplicationIsEligible(NSString *identifier, NSString *bundlePath) {
    if (![identifier isKindOfClass:NSString.class] || !identifier.length ||
        ![bundlePath isKindOfClass:NSString.class]) return NO;
    for (NSString *prefix in @[@"com.apple", @"com.opa334", @"org.coolstar",
                              @"science.xnu", @"com.samiiau.loader", @"com.llsc12.palera1nLoader",
                              @"me.jjolano.shadow.manager"]) {
        if ([identifier hasPrefix:prefix]) return NO;
    }
    NSString *path = bundlePath.stringByStandardizingPath;
    return [path hasPrefix:@"/var/containers/Bundle/Application/"] ||
           [path hasPrefix:@"/private/var/containers/Bundle/Application/"];
}
