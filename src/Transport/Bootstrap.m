#import "Bootstrap.h"
#include <string.h>

static const char *const payloadKey = "me.jjolano.shadow.transport.v1";
static const NSUInteger maximumStringBytes = 255;

BOOL SHDWTransportIsNetworkingService(const char *service) {
    return service && !strcmp(service, "com.apple.WebKit.Networking");
}

static NSString *validatedString(id value) {
    if (![value isKindOfClass:NSString.class]) return nil;
    NSString *string = [value copy];
    NSUInteger length = [string lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
    const char *bytes = string.UTF8String;
    if (!length || length > maximumStringBytes || !bytes || strlen(bytes) != length ||
        [string rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) return nil;
    return string;
}

static NSString *xpcString(xpc_object_t value) {
    if (!value || xpc_get_type(value) != XPC_TYPE_STRING) return nil;
    size_t length = xpc_string_get_length(value);
    if (!length || length > maximumStringBytes) return nil;
    const char *bytes = xpc_string_get_string_ptr(value);
    if (!bytes || strnlen(bytes, length + 1) != length) return nil;
    return validatedString([[NSString alloc] initWithBytes:bytes length:length encoding:NSUTF8StringEncoding]);
}

xpc_object_t SHDWTransportBootstrapMessage(xpc_object_t original, NSString *profile, NSString *owner) {
    NSString *selectedProfile = validatedString(profile);
    if (!original || xpc_get_type(original) != XPC_TYPE_DICTIONARY ||
        !SHDWTransportProfileIsSupported(selectedProfile)) return original;
    NSString *identity = validatedString(owner);
    if (!identity) return original;
    xpc_object_t message = xpc_copy(original);
    if (!message) return original;
    xpc_object_t payload = xpc_dictionary_create(NULL, NULL, 0);
    if (!payload) return original;
    xpc_dictionary_set_uint64(payload, "version", 1);
    xpc_dictionary_set_string(payload, "profile", selectedProfile.UTF8String);
    xpc_dictionary_set_string(payload, "owner-bundle-identifier", identity.UTF8String);
    xpc_dictionary_set_value(message, payloadKey, payload);
    return message;
}

NSDictionary *SHDWTransportSnapshot(xpc_object_t bootstrap, xpc_object_t event) {
    if (!bootstrap || xpc_get_type(bootstrap) != XPC_TYPE_DICTIONARY ||
        !event || xpc_get_type(event) != XPC_TYPE_DICTIONARY) return nil;
    xpc_object_t payload = xpc_dictionary_get_value(bootstrap, payloadKey);
    if (!payload || xpc_get_type(payload) != XPC_TYPE_DICTIONARY) return nil;
    xpc_object_t version = xpc_dictionary_get_value(payload, "version");
    if (!version || xpc_get_type(version) != XPC_TYPE_UINT64 || xpc_uint64_get_value(version) != 1) return nil;
    NSString *message = xpcString(xpc_dictionary_get_value(event, "message-name"));
    NSString *service = xpcString(xpc_dictionary_get_value(event, "service-name"));
    NSString *client = xpcString(xpc_dictionary_get_value(event, "client-bundle-identifier"));
    NSString *owner = xpcString(xpc_dictionary_get_value(payload, "owner-bundle-identifier"));
    NSString *profile = xpcString(xpc_dictionary_get_value(payload, "profile"));
    if (![message isEqualToString:@"bootstrap"] || !SHDWTransportIsNetworkingService(service.UTF8String) ||
        !owner || ![owner isEqualToString:client] || !SHDWTransportProfileIsSupported(profile)) return nil;
    return @{@"Profile":profile, @"Owner":owner};
}
