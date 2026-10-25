#import "IPSwitchConfiguration.h"
#import "Language.h"
static NSString *const ConfigurationsKey = @"IPSwitchConfigurations";
@implementation SHDWIPSwitchConfiguration
+ (NSURL *)URLForString:(NSString *)value {
    if (![value isKindOfClass:NSString.class] || !value.length ||
        [value rangeOfCharacterFromSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].location != NSNotFound) return nil;
    NSURLComponents *parts = [NSURLComponents componentsWithString:value];
    if (!([parts.scheme.lowercaseString isEqual:@"https"] || [parts.scheme.lowercaseString isEqual:@"http"]) ||
        !parts.host.length || parts.user || parts.password || parts.fragment) return nil;
    return parts.URL;
}
+ (NSArray<NSDictionary<NSString *, NSString *> *> *)configurations {
    id stored = [NSUserDefaults.standardUserDefaults objectForKey:ConfigurationsKey];
    NSMutableArray *result = [NSMutableArray new];
    if (![stored isKindOfClass:NSArray.class]) return result;
    for (id item in stored) {
        if (![item isKindOfClass:NSDictionary.class] || ![item[@"name"] isKindOfClass:NSString.class] ||
            ![item[@"name"] length] || ![self URLForString:item[@"url"]]) continue;
        [result addObject:@{@"name":item[@"name"], @"url":item[@"url"]}];
    }
    return [result copy];
}
+ (BOOL)saveConfigurations:(NSArray<NSDictionary<NSString *, NSString *> *> *)configurations error:(NSError **)error {
    NSMutableArray *saved = [NSMutableArray new]; NSMutableSet *names = [NSMutableSet new];
    for (NSDictionary *item in configurations) {
        id rawName = [item isKindOfClass:NSDictionary.class] ? item[@"name"] : nil;
        id rawURL = [item isKindOfClass:NSDictionary.class] ? item[@"url"] : nil;
        NSString *name = [rawName isKindOfClass:NSString.class] ? [rawName stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] : @"";
        NSString *url = [rawURL isKindOfClass:NSString.class] ? [rawURL stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet] : @"";
        NSString *message = !name.length ? @"Enter a name for this IP switch." :
            (![self URLForString:url] ? @"Enter a valid HTTP or HTTPS URL without credentials or spaces." :
            ([names containsObject:name.lowercaseString] ? @"Use a different name for each IP switch." : nil));
        if (message) { if (error) *error = [NSError errorWithDomain:@"me.jjolano.shadow.ip-switch" code:1 userInfo:@{NSLocalizedDescriptionKey:SHDWLocalizedText(message)}]; return NO; }
        [names addObject:name.lowercaseString]; [saved addObject:@{@"name":name, @"url":url}];
    }
    [NSUserDefaults.standardUserDefaults setObject:saved forKey:ConfigurationsKey];
    return YES;
}
@end
