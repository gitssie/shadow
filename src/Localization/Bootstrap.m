#import "Bootstrap.h"
#import <CoreFoundation/CoreFoundation.h>
#include <string.h>

static const char *const payloadKey = "me.jjolano.shadow.localization.v1";
static const NSUInteger maximumStringBytes = 255;
static const NSUInteger maximumLanguages = 32;

BOOL SHDWLocalizationIsWebContentService(const char *service) {
    return service && !strcmp(service, "com.apple.WebKit.WebContent");
}

BOOL SHDWLocalizationBootstrapHasPayload(xpc_object_t bootstrap) {
    if (!bootstrap || xpc_get_type(bootstrap) != XPC_TYPE_DICTIONARY) return NO;
    xpc_object_t payload = xpc_dictionary_get_value(bootstrap, payloadKey);
    if (!payload || xpc_get_type(payload) != XPC_TYPE_DICTIONARY) return NO;
    xpc_object_t version = xpc_dictionary_get_value(payload, "version");
    return version && xpc_get_type(version) == XPC_TYPE_UINT64 && xpc_uint64_get_value(version) == 1;
}

static NSString *validatedString(id value) {
    if (![value isKindOfClass:NSString.class]) return nil;
    NSString *string = [value copy];
    NSUInteger length = [string lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
    const char *bytes = string.UTF8String;
    if (!length || length > maximumStringBytes || !bytes || strlen(bytes) != length) return nil;
    if ([string rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) return nil;
    return string;
}

static NSString *xpcString(xpc_object_t object) {
    if (!object || xpc_get_type(object) != XPC_TYPE_STRING) return nil;
    size_t length = xpc_string_get_length(object);
    if (!length || length > maximumStringBytes) return nil;
    const char *bytes = xpc_string_get_string_ptr(object);
    if (!bytes || strnlen(bytes, length + 1) != length) return nil;
    return validatedString([[NSString alloc] initWithBytes:bytes length:length encoding:NSUTF8StringEncoding]);
}

static NSDictionary *validatedSnapshot(id localeValue, id languagesValue, id zoneValue) {
    NSString *locale = validatedString(localeValue);
    NSString *zone = validatedString(zoneValue);
    if (!locale || !zone || ![languagesValue isKindOfClass:NSArray.class] ||
        ![languagesValue count] || [languagesValue count] > maximumLanguages) return nil;
    NSMutableArray *languages = [NSMutableArray arrayWithCapacity:[languagesValue count]];
    @try {
        NSLocale *localeObject = [[NSLocale alloc] initWithLocaleIdentifier:locale];
        NSString *languageCode = [localeObject objectForKey:NSLocaleLanguageCode];
        if (!localeObject || ![NSLocale.ISOLanguageCodes containsObject:languageCode] ||
            ![NSTimeZone timeZoneWithName:zone]) return nil;
        for (id value in languagesValue) {
            NSString *language = validatedString(value);
            if (!language) return nil;
            NSLocale *languageLocale = [[NSLocale alloc] initWithLocaleIdentifier:language];
            if (![NSLocale.ISOLanguageCodes containsObject:[languageLocale objectForKey:NSLocaleLanguageCode]]) return nil;
            [languages addObject:language];
        }
    } @catch (NSException *exception) {
        return nil;
    }
    return @{@"LocaleIdentifier":locale, @"Languages":[languages copy], @"TimeZone":zone};
}

xpc_object_t SHDWLocalizationBootstrapMessage(xpc_object_t original, NSDictionary *resolved, NSString *owner) {
    if (!original || xpc_get_type(original) != XPC_TYPE_DICTIONARY ||
        ![resolved isKindOfClass:NSDictionary.class] || resolved[@"OverridesSystem"] != (__bridge id)kCFBooleanTrue) return original;
    NSString *identity = validatedString(owner);
    NSDictionary *snapshot = validatedSnapshot(resolved[@"LocaleIdentifier"], resolved[@"Languages"], resolved[@"TimeZone"]);
    if (!identity || !snapshot) return original;
    xpc_object_t message = xpc_copy(original);
    if (!message) return original;
    xpc_object_t payload = xpc_dictionary_create(NULL, NULL, 0);
    xpc_dictionary_set_uint64(payload, "version", 1);
    xpc_dictionary_set_string(payload, "owner-bundle-identifier", identity.UTF8String);
    xpc_dictionary_set_string(payload, "locale-identifier", [snapshot[@"LocaleIdentifier"] UTF8String]);
    xpc_dictionary_set_string(payload, "time-zone", [snapshot[@"TimeZone"] UTF8String]);
    xpc_object_t languages = xpc_array_create(NULL, 0);
    for (NSString *language in snapshot[@"Languages"]) xpc_array_set_string(languages, XPC_ARRAY_APPEND, language.UTF8String);
    xpc_dictionary_set_value(payload, "languages", languages);
    xpc_dictionary_set_value(message, payloadKey, payload);
    xpc_dictionary_set_value(message, "OverrideLanguages", languages);
    return message;
}

static NSDictionary *snapshotForService(xpc_object_t bootstrap, xpc_object_t event, NSString *expectedService) {
    if (!SHDWLocalizationBootstrapHasPayload(bootstrap) ||
        !event || xpc_get_type(event) != XPC_TYPE_DICTIONARY) return nil;
    NSString *messageName = xpcString(xpc_dictionary_get_value(event, "message-name"));
    NSString *service = xpcString(xpc_dictionary_get_value(event, "service-name"));
    NSString *client = xpcString(xpc_dictionary_get_value(event, "client-bundle-identifier"));
    if (![messageName isEqualToString:@"bootstrap"] || ![service isEqualToString:expectedService] || !client) return nil;
    xpc_object_t payload = xpc_dictionary_get_value(bootstrap, payloadKey);
    NSString *owner = xpcString(xpc_dictionary_get_value(payload, "owner-bundle-identifier"));
    if (!owner || ![owner isEqualToString:client]) return nil;
    xpc_object_t values = xpc_dictionary_get_value(payload, "languages");
    if (!values || xpc_get_type(values) != XPC_TYPE_ARRAY) return nil;
    size_t count = xpc_array_get_count(values);
    if (!count || count > maximumLanguages) return nil;
    NSMutableArray *languages = [NSMutableArray arrayWithCapacity:count];
    for (size_t index = 0; index < count; index++) {
        NSString *language = xpcString(xpc_array_get_value(values, index));
        if (!language) return nil;
        [languages addObject:language];
    }
    return validatedSnapshot(xpcString(xpc_dictionary_get_value(payload, "locale-identifier")), languages,
                             xpcString(xpc_dictionary_get_value(payload, "time-zone")));
}

NSDictionary *SHDWLocalizationSnapshot(xpc_object_t bootstrap, xpc_object_t event) {
    return snapshotForService(bootstrap, event, @"com.apple.WebKit.WebContent");
}

NSDictionary *SHDWLocalizationNetworkingSnapshot(xpc_object_t bootstrap, xpc_object_t event) {
    NSDictionary *values = snapshotForService(bootstrap, event, @"com.apple.WebKit.Networking");
    if (!values) return nil;
    NSMutableDictionary *snapshot = [values mutableCopy];
    snapshot[@"Owner"] = xpcString(xpc_dictionary_get_value(event, "client-bundle-identifier"));
    return [snapshot copy];
}
