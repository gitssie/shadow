#import "Bootstrap.h"
#include <string.h>

static const char *const payloadKey = "me.jjolano.shadow.web-user-agent.v1";

static NSString *String(id value) {
    if (![value isKindOfClass:NSString.class]) return nil;
    NSString *copy = [value copy];
    NSUInteger length = [copy lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
    const char *bytes = copy.UTF8String;
    if (!length || length > 255 || !bytes || strlen(bytes) != length ||
        [copy rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound) return nil;
    return copy;
}

static NSString *XPCString(xpc_object_t value) {
    if (!value || xpc_get_type(value) != XPC_TYPE_STRING) return nil;
    size_t length = xpc_string_get_length(value);
    if (!length || length > 255) return nil;
    const char *bytes = xpc_string_get_string_ptr(value);
    if (!bytes || strnlen(bytes, length + 1) != length) return nil;
    return String([[NSString alloc] initWithBytes:bytes length:length encoding:NSUTF8StringEncoding]);
}

xpc_object_t SHDWWebUserAgentBootstrapMessage(xpc_object_t original, NSString *version, NSString *owner) {
    NSString *identity = String(owner), *systemVersion = String(version);
    if (!original || xpc_get_type(original) != XPC_TYPE_DICTIONARY || !identity ||
        !SHDWWebUserAgentVersionIsValid(systemVersion)) return original;
    xpc_object_t message = xpc_copy(original);
    xpc_object_t payload = xpc_dictionary_create(NULL, NULL, 0);
    if (!message || !payload) return original;
    xpc_dictionary_set_uint64(payload, "version", 1);
    xpc_dictionary_set_string(payload, "owner-bundle-identifier", identity.UTF8String);
    xpc_dictionary_set_string(payload, "system-version", systemVersion.UTF8String);
    xpc_dictionary_set_value(message, payloadKey, payload);
    return message;
}

NSDictionary *SHDWWebUserAgentSnapshot(xpc_object_t bootstrap, xpc_object_t event) {
    if (!bootstrap || xpc_get_type(bootstrap) != XPC_TYPE_DICTIONARY ||
        !event || xpc_get_type(event) != XPC_TYPE_DICTIONARY) return nil;
    xpc_object_t payload = xpc_dictionary_get_value(bootstrap, payloadKey);
    if (!payload || xpc_get_type(payload) != XPC_TYPE_DICTIONARY) return nil;
    xpc_object_t format = xpc_dictionary_get_value(payload, "version");
    if (!format || xpc_get_type(format) != XPC_TYPE_UINT64 || xpc_uint64_get_value(format) != 1) return nil;
    NSString *message = XPCString(xpc_dictionary_get_value(event, "message-name"));
    NSString *service = XPCString(xpc_dictionary_get_value(event, "service-name"));
    NSString *client = XPCString(xpc_dictionary_get_value(event, "client-bundle-identifier"));
    NSString *owner = XPCString(xpc_dictionary_get_value(payload, "owner-bundle-identifier"));
    NSString *version = XPCString(xpc_dictionary_get_value(payload, "system-version"));
    if (![message isEqual:@"bootstrap"] || ![service isEqual:@"com.apple.WebKit.WebContent"] ||
        !owner || ![owner isEqual:client] || !SHDWWebUserAgentVersionIsValid(version)) return nil;
    return @{@"Version":version, @"Owner":owner};
}
