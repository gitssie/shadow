#import "InstalledApplications.h"
#import "ApplicationEligibility.h"
#import "Appearance/Theme.h"
#import <objc/message.h>
@interface UIImage (SHDWApplicationIcon)
+ (UIImage *)_applicationIconImageForBundleIdentifier:(NSString *)bundleIdentifier format:(NSInteger)format scale:(CGFloat)scale;
@end
@implementation SHDWInstalledApplication
@end
@implementation SHDWInstalledApplications
+ (NSArray<SHDWInstalledApplication *> *)applications {
    Class workspaceClass = NSClassFromString(@"LSApplicationWorkspace");
    SEL workspaceSelector = NSSelectorFromString(@"defaultWorkspace"), appsSelector = NSSelectorFromString(@"allApplications");
    if (![workspaceClass respondsToSelector:workspaceSelector]) return @[];
    id workspace = ((id(*)(id,SEL))objc_msgSend)(workspaceClass, workspaceSelector);
    if (![workspace respondsToSelector:appsSelector]) return @[];
    NSArray *proxies = ((id(*)(id,SEL))objc_msgSend)(workspace, appsSelector);
    NSMutableDictionary *applications = [NSMutableDictionary dictionary];
    for (id proxy in proxies) {
        @try {
            NSString *identifier = [proxy valueForKey:@"applicationIdentifier"];
            id bundleURL = [proxy valueForKey:@"bundleURL"];
            if (![bundleURL isKindOfClass:NSURL.class]) continue;
            NSString *path = [bundleURL path];
            if (!SHDWApplicationIsEligible(identifier, path)) continue;
            SHDWInstalledApplication *app = [SHDWInstalledApplication new]; app.bundleIdentifier = identifier;
            id name = [proxy valueForKey:@"localizedName"]; app.name = [name isKindOfClass:NSString.class] && [name length] ? name : identifier;
            app.bundleURL = bundleURL;
            applications[identifier] = app;
        } @catch (__unused NSException *exception) { continue; }
    }
    return [[applications allValues] sortedArrayUsingComparator:^NSComparisonResult(SHDWInstalledApplication *a, SHDWInstalledApplication *b) { NSComparisonResult order = [a.name localizedCaseInsensitiveCompare:b.name]; return order == NSOrderedSame ? [a.bundleIdentifier compare:b.bundleIdentifier] : order; }];
}
+ (UIImage *)iconForApplication:(SHDWInstalledApplication *)app {
    if (app && [UIImage respondsToSelector:@selector(_applicationIconImageForBundleIdentifier:format:scale:)]) {
        UIImage *icon = [UIImage _applicationIconImageForBundleIdentifier:app.bundleIdentifier format:2 scale:UIScreen.mainScreen.scale]; if (icon) return icon;
    }
    NSBundle *bundle = app.bundleURL ? [NSBundle bundleWithURL:app.bundleURL] : nil;
    NSDictionary *icons = bundle.infoDictionary[@"CFBundleIcons"][@"CFBundlePrimaryIcon"];
    NSArray *names = icons[@"CFBundleIconFiles"] ?: bundle.infoDictionary[@"CFBundleIconFiles"];
    for (NSString *name in [names reverseObjectEnumerator]) { NSString *path = [bundle pathForResource:name ofType:nil]; UIImage *icon = path ? [UIImage imageWithContentsOfFile:path] : nil; if (icon) return icon; }
    return SHDWSymbol(@"app.fill", 40);
}
@end
